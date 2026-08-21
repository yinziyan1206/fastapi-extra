# 表单与查询模型

面向常见的「列表筛选 / 范围查询 / 分页响应 / 动态条件」需求，`fastapi_extra.form` 提供了一组可直接复用的 Pydantic 模型：

- **`Page[Schema]`**：分页返回容器（items / total / page_num / page_size）。
- **`DataRange[C]`**：用于数值、日期等字段的 `[start, end]` 区间查询。
- **`ColumnExpression[S]`**：单条件表达式（列 + 操作符 + 值），可组合。
- **`WhereClause`**：由 `ColumnExpression` / 自身递归组合的逻辑树（AND / OR）。

---

## 1. `Page[Schema]`：分页响应

```python
from pydantic import BaseModel
from fastapi_extra.form import Page
from fastapi_extra.response import APIResult

class UserOut(BaseModel):
    id: int
    name: str

@app.get("/users", response_model=APIResult[Page[UserOut]])
async def list_users(page_num: int = 1, page_size: int = 20, service: UserService) -> APIResult[Page[UserOut]]:
    stmt = select(User)
    total = await service.session.scalar(stmt.with_only_columns(func.count("*")))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size).order_by(User.id)
    all_users: list[User] = await service.session.exec(stmt)
    items = [UserOut.model_validate(u, from_attributes=True) for u in all_users]
    return APIResult.ok(Page(items=items, total=total, page_num=page_num, page_size=page_size))
```

返回 JSON：

```json
{
  "code": "00000",
  "message": "OK",
  "data": {
    "items":     [...],
    "total":     1234,
    "page_num":  1,
    "page_size": 20
  }
}
```

字段：

| 字段 | 类型 | 含义 |
|------|------|------|
| `items` | `list[Schema]` | 当前页的数据集合 |
| `total` | `int` | 总记录数（用于前端计算总页数） |
| `page_num` | `int` | 从 1 开始的页码 |
| `page_size` | `int` | 每页大小（建议在 10~100 之间，太大可在参数层做限制） |

---

## 2. `DataRange[C]`：区间查询

适用于日期、价格、创建时间等「最小值到最大值」场景。`C` 受约束于 `Comparable = int | float | Decimal | datetime | date | time`。

### 2.1 Query 参数形式（推荐）

```python
from fastapi_extra.types import C
from fastapi_extra.form import DataRange
from datetime import date

@app.get("/orders")
async def list_orders(
    amount_start: float | None = None,
    amount_end:   float | None = None,
    date_start:   date  | None = None,
    date_end:     date  | None = None,
    service: OrderService,
) -> APIResult[Page[OrderOut]]:
    clauses = []
    if amount_start is not None or amount_end is not None:
        rng = DataRange[float](start=amount_start, end=amount_end)
        if rng.start is not None:
            clauses.append(Order.amount >= rng.start)
        if rng.end is not None:
            clauses.append(Order.amount <= rng.end)
    if date_start or date_end:
        rng = DataRange[date](start=date_start, end=date_end)
        if rng.start is not None: clauses.append(Order.create_at >= rng.start)
        if rng.end   is not None: clauses.append(Order.create_at <= rng.end)

    rows = await service.get_list(*clauses)
    ...
```

### 2.2 Body 参数形式（组合查询场景）

```python
from pydantic import BaseModel
from fastapi_extra.form import DataRange
from datetime import datetime

class OrderFilter(BaseModel):
    amount: DataRange[float] | None = None
    create_at: DataRange[datetime] | None = None
    status: list[str] | None = None

@app.post("/orders/search")
async def search_orders(f: OrderFilter, service: OrderService):
    clauses = []
    if f.amount:
        if f.amount.start: clauses.append(Order.amount >= f.amount.start)
        if f.amount.end:   clauses.append(Order.amount <= f.amount.end)
    if f.create_at:
        if f.create_at.start: clauses.append(Order.create_at >= f.create_at.start)
        if f.create_at.end:   clauses.append(Order.create_at <= f.create_at.end)
    if f.status:
        clauses.append(Order.status.in_(f.status))
    ...
```

---

## 3. `ColumnExpression[S]` 与 `WhereClause`：动态条件

面向后台管理系统的「多维筛选器」，前端可以传入任意列 + 操作符构成的条件树，后端直接把它翻译为 SQLAlchemy 表达式。

### 3.1 字段说明

#### `ColumnExpression[S]`

| 字段 | 类型 | 说明 |
|------|------|------|
| `column_name` | `str` | 列名（对应模型字段名，如 `"age"` / `"create_at"`） |
| `option` | `Literal["eq","ne","gt","lt","ge","le"]` | 关系运算符，默认 `"eq"` |
| `value` | `S` | 比较值。若 `option ∉ {eq, ne}` 且 `value is None`，会抛出 `ValueError: NoneType is not comparable`，避免无意义查询。 |

#### `WhereClause`

| 字段 | 类型 | 说明 |
|------|------|------|
| `option` | `Literal["and", "or"]` | 逻辑关系，默认 `"and"` |
| `column_clauses` | `list[ColumnExpression \| WhereClause]` | 叶子节点 + 子树，允许递归嵌套 |

### 3.2 从 WhereClause → SQLAlchemy 表达式

下面给出一个通用转换函数（可作为工具函数直接复制到项目中）：

```python
from typing import Any
from sqlalchemy import ColumnExpressionArgument, and_, or_, not_
from fastapi_extra.form import ColumnExpression, WhereClause

_OP = {
    "eq": "__eq__",
    "ne": "__ne__",
    "gt": "__gt__",
    "lt": "__lt__",
    "ge": "__ge__",
    "le": "__le__",
}

def build_expr(model: type, item: ColumnExpression | WhereClause) -> ColumnExpressionArgument[bool]:
    """把前端传入的条件翻译为 SQLAlchemy 表达式。"""
    if isinstance(item, ColumnExpression):
        if not hasattr(model, item.column_name):
            raise ValueError(f"未知列名: {item.column_name}")
        col = getattr(model, item.column_name)
        method = getattr(col, _OP[item.option])
        return method(item.value)

    # WhereClause：递归
    sub = [build_expr(model, c) for c in item.column_clauses]
    if not sub:
        raise ValueError("空的 WhereClause")
    return and_(*sub) if item.option == "and" else or_(*sub)
```

### 3.3 接口示例

```python
@app.post("/users/dynamic", response_model=APIResult[list[UserOut]])
async def dynamic_query(where: WhereClause, service: UserService) -> APIResult[list[UserOut]]:
    expr = build_expr(User, where)
    rows = await service.get_list(expr, User.deleted == 0)
    return APIResult.ok([UserOut.model_validate(u, from_attributes=True) for u in rows])
```

请求示例：

```json
{
  "option": "and",
  "column_clauses": [
    { "column_name": "age",    "option": "ge", "value": 20 },
    { "column_name": "age",    "option": "lt", "value": 30 },
    {
      "option": "or",
      "column_clauses": [
        { "column_name": "name", "option": "eq", "value": "Alice" },
        { "column_name": "name", "option": "eq", "value": "Bob"   }
      ]
    }
  ]
}
```

等价于：

```sql
WHERE age  >= 20
  AND age  <  30
  AND (name = 'Alice' OR name = 'Bob');
```

### 3.4 安全建议

动态条件会让前端拥有较大的查询自由度：

1. **列白名单**：在 `build_expr` 中增加「允许列」校验，避免用户把内部敏感列（如 `password_hash`、`deleted`、`version_id`）放进表达式；
2. **深度限制**：限制 `WhereClause` 的嵌套深度（例如最大 4 层），防止构造超长查询；
3. **和分页模型组合**：将 `WhereClause`、`DataRange`、`page_num / page_size` 统一放到 `SearchRequest` 模型里，接口签名更简洁。

---

## 4. 组合示例：一个通用的 SearchRequest

```python
from pydantic import BaseModel, Field
from fastapi_extra.form import Page, WhereClause, DataRange
from datetime import datetime

class CommonSearch(BaseModel):
    page_num:  int = Field(1,  ge=1,    description="页码")
    page_size: int = Field(20, ge=1, le=200, description="每页大小")
    sort_by:   str = "create_at"
    order:     str = "desc"
    where:     WhereClause | None = None
    create_at: DataRange[datetime] | None = None

@app.post("/users/search", response_model=APIResult[Page[UserOut]])
async def search_users(req: CommonSearch, service: UserService):
    clauses = []
    if req.where:     clauses.append(build_expr(User, req.where))
    if req.create_at:
        if req.create_at.start: clauses.append(User.create_at >= req.create_at.start)
        if req.create_at.end:   clauses.append(User.create_at <= req.create_at.end)
    
    stmt = select(User).where(*clauses)
    total = await service.session.scalar(stmt.with_only_columns(func.count("*")))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    if sort_by:
        if order == "desc":
            stmt = stmt.order_by(getattr(User, req.sort_by).desc())
        else:
            stmt = stmt.order_by(getattr(User, req.sort_by))
    rows = await service.session.exec(stmt)
    items = [UserOut.model_validate(u, from_attributes=True) for u in rows]
    return APIResult.ok(Page(items=items, total=total, page_num=req.page_num, page_size=req.page_size))
```
