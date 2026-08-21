# Form & Query Models

For the common needs of "list filtering / range queries / paginated responses / dynamic conditions", `fastapi_extra.form` provides a set of reusable Pydantic models:

- **`Page[Schema]`**: pagination envelope (`items` / `total` / `page_num` / `page_size`).
- **`DataRange[C]`**: `[start, end]` interval queries for numbers, dates, etc.
- **`ColumnExpression[S]`**: a single condition (column + operator + value), composable.
- **`WhereClause`**: a recursively-composable logic tree (AND / OR) built from `ColumnExpression` or nested `WhereClause`.

---

## 1. `Page[Schema]`: paginated responses

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

Response JSON:

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

Fields:

| Field | Type | Description |
|-------|------|-------------|
| `items` | `list[Schema]` | Records of the current page. |
| `total` | `int` | Total number of records (used by frontend to compute page count). |
| `page_num` | `int` | 1-based page index. |
| `page_size` | `int` | Records per page (recommend 10~100; cap it at the parameter layer for larger values). |

---

## 2. `DataRange[C]`: interval queries

Suited to scenarios like "price between X and Y", "created_at between start date and end date". `C` is constrained to `Comparable = int | float | Decimal | datetime | date | time`.

### 2.1 Flat query parameters (recommended)

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

### 2.2 Body payload (complex filters)

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

## 3. `ColumnExpression[S]` & `WhereClause`: dynamic conditions

Tailored to admin dashboards with multi-dimension filters — the frontend can submit arbitrary column + operator condition trees, and the backend translates them into SQLAlchemy expressions.

### 3.1 Field reference

#### `ColumnExpression[S]`

| Field | Type | Description |
|-------|------|-------------|
| `column_name` | `str` | Name of the model field (e.g. `"age"`, `"create_at"`). |
| `option` | `Literal["eq","ne","gt","lt","ge","le"]` | Comparison operator; defaults to `"eq"`. |
| `value` | `S` | Right-hand side value. If `option ∉ {eq, ne}` and `value is None`, a `ValueError: NoneType is not comparable` is raised to guard against meaningless queries. |

#### `WhereClause`

| Field | Type | Description |
|-------|------|-------------|
| `option` | `Literal["and", "or"]` | Logical operator; defaults to `"and"`. |
| `column_clauses` | `list[ColumnExpression \| WhereClause]` | Leaf nodes + child trees. Recursive nesting is allowed. |

### 3.2 Translate WhereClause → SQLAlchemy expression

Below is a general-purpose helper you can drop directly into your project:

```python
from typing import Any
from sqlalchemy import ColumnExpressionArgument, and_, or_
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
    """Translate a frontend condition tree into SQLAlchemy boolean expressions."""
    if isinstance(item, ColumnExpression):
        if not hasattr(model, item.column_name):
            raise ValueError(f"Unknown column: {item.column_name}")
        col = getattr(model, item.column_name)
        method = getattr(col, _OP[item.option])
        return method(item.value)

    # WhereClause: recursive
    sub = [build_expr(model, c) for c in item.column_clauses]
    if not sub:
        raise ValueError("Empty WhereClause")
    return and_(*sub) if item.option == "and" else or_(*sub)
```

### 3.3 Endpoint example

```python
@app.post("/users/dynamic", response_model=APIResult[list[UserOut]])
async def dynamic_query(where: WhereClause, service: UserService) -> APIResult[list[UserOut]]:
    expr = build_expr(User, where)
    rows = await service.get_list(expr, User.deleted == 0)
    return APIResult.ok([UserOut.model_validate(u, from_attributes=True) for u in rows])
```

Sample request:

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

Equivalent to:

```sql
WHERE deleted = 0
  AND age  >= 20
  AND age  <  30
  AND (name = 'Alice' OR name = 'Bob');
```

### 3.4 Security recommendations

Dynamic conditions give the frontend considerable query freedom:

1. **Column allow-lists**: add "allowed columns" validation inside `build_expr` to prevent users from filtering on sensitive internal columns (`password_hash`, `deleted`, `version_id`, etc.).
2. **Depth limits**: cap `WhereClause` nesting depth (e.g. max 4 levels) to avoid arbitrarily expensive queries.
3. **Combine with pagination**: wrap `WhereClause`, `DataRange`, `page_num / page_size` together inside a `SearchRequest` model for a tidier route signature.

---

## 4. Composition: a generic `SearchRequest`

```python
from pydantic import BaseModel, Field
from fastapi_extra.form import Page, WhereClause, DataRange
from datetime import datetime

class CommonSearch(BaseModel):
    page_num:  int = Field(1,  ge=1,    description="Page number (1-based)")
    page_size: int = Field(20, ge=1, le=200, description="Records per page")
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
