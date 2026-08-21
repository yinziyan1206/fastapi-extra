# 数据库层

`fastapi_extra` 的数据库模块构建在 **SQLModel**（SQLAlchemy + Pydantic 融合）之上，提供四套能力：

1. **模型基类**：`SQLBase` 统一主键、乐观锁、软删、时间戳；
2. **异步 Session 工厂**：`SessionFactory`（应用级组件）+ `get_session`（请求级依赖）+ `DefaultSession`（可直接注解使用）；
3. **泛型 CRUD Service**：`ModelService[T]`，基于 `AbstractService`，一行即获得 get / list / create / update / delete；
4. **SQL 模板映射**：把 `.sql` 文件和 Service 方法通过 `@Mapped` 绑定，按方法返回类型自动选择 `execute` / `fetch_one` / `fetch_all`。

---

## 1. 配置

在 `config.default.toml` 中声明：

```toml
[datasource]
url = "mysql+asyncmy://root:pass@127.0.0.1:3306/demo?charset=utf8mb4"
echo = false                 # SQLAlchemy echo：打印 SQL（开发用）
echo_pool = false            # 打印连接池日志
isolation_level = "READ COMMITTED"
options.pool_size = 20       # 传给 create_async_engine 的额外参数
options.max_overflow = 40
```

支持的驱动：`mysql+asyncmy`、`mysql+aiomysql`、`postgresql+asyncpg`、`oracle+oracledb`。

---

## 2. 模型基类

### 2.1 `SQLBase` = LocalPK + Versioned + Deleted + Optime

```python
from fastapi_extra.database import SQLBase
from sqlmodel import Field

class User(SQLBase, table=True):
    name: str = Field(max_length=64, title="用户名")
    age: int | None = Field(default=None, title="年龄")
    email: str = Field(max_length=128, unique=True)
```

继承后的 `User` 会自动拥有下列字段：

| 基类 | 字段 | 说明 |
|------|------|------|
| `LocalPK` | `id: Cursor`（BigInteger） | 雪花算法主键，默认由 `get_machine_seed()` 生成 machine-id；可在 `fastapi_extra/utils.py` 中替换实现。**序列化时自动转为字符串**（通过 `types.Cursor` 的 PlainSerializer）。 |
| `Versioned` | `version_id: int` | 乐观锁列（SQLAlchemy `version_id_col`），并发 UPDATE 时自动冲突检测。 |
| `Deleted` | `deleted: int` | 软删标识，0 = 未删除，1 = 已删除，默认 0。 |
| `Optime` | `create_at: LocalDateTime` | 创建时间，DB 端 `DEFAULT NOW()`；序列化格式 `%Y-%m-%d %H:%M:%S`。 |
| `Optime` | `update_at: LocalDateTime` | 更新时间，DB 端 `ON UPDATE NOW()`；同上。 |

> `LocalPK` 与 `AutoPK` 的区别：`AutoPK` 使用数据库自增 ID（`autoincrement=True`），`LocalPK` 使用本地雪花生成器（`autoincrement=False`，适合分库分表、多写场景）。默认 `SQLBase` 使用雪花 ID。

### 2.2 按需组合

例如你不需要软删，只需要主键 + 乐观锁：

```python
from fastapi_extra.database.model import LocalPK, Versioned, Optime

class Order(LocalPK, Versioned, Optime, table=True):
    ...
```

### 2.3 删除标识

软删可以通过event监听来实现

```python
from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session
from fastapi_extra.database.model import Deleted

@event.listens_for(Session, "do_orm_execute")
def add_filtering_criteria(execute_state: ORMExecuteState):
    """add_filtering_criteria 

    自动为所有 ORM 查询添加 deleted == 0 的过滤条件

    Args:
        execute_state (_type_): _description_
    """
    if (
        execute_state.bind_mapper
        and execute_state.is_select
        and not execute_state.execution_options.get("include_deleted", False)
        and issubclass(execute_state.bind_mapper.class_, Deleted)
    ):  
        execute_state.statement = execute_state.statement.where(execute_state.bind_mapper.c.deleted == 0) # type: ignore
```

---


## 3. Session：连接池 & 依赖注入

### 3.1 安装 SessionFactory

```python
from fastapi_extra.database import SessionFactory

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionFactory.install(app)   # 内部创建 AsyncEngine + ConnectionPool
    yield
    await db.dispose()                 # 关闭引擎，释放所有连接
```

### 3.2 在路由中使用 `DefaultSession`

`DefaultSession` 是已经打包好的 `Annotated[AsyncSession, Depends(get_session)]`：

```python
from fastapi_extra.database import DefaultSession
from fastapi_extra.response import APIResult

@app.get("/users/{pk}")
async def get_user(pk: int, session: DefaultSession) -> APIResult[dict]:
    user = await session.get(User, pk)
    if not user or user.deleted:
        return APIResult.ok(None)
    return APIResult.ok(UserOut.model_validate(user, from_attributes=True))
```

`get_session` 作为 FastAPI 依赖会：
1. 向 SessionFactory 申请一个 `AsyncSession`；
2. `yield` 给路由函数；
3. 请求结束后自动 `await session.commit()`（若抛异常则会由 FastAPI 处理并 rollback，业务侧可按需显式 rollback）。

---

## 4. `ModelService[T]`：泛型 CRUD

如果每个模型都要写一套 CRUD，那实在太繁琐。`ModelService[T]` 帮你一次性搞定：

### 4.1 声明一个 Service

```python
from fastapi_extra.database import ModelService

class UserService(ModelService[User]):
    """针对 User 的业务方法可在此追加。"""

    async def list_by_age_gt(self, age: int):
        return await self.get_list(User.age > age)
```

> ⚠️ 泛型参数 `T` 必须是 `table=True` 的 SQLModel，否则抛出 `TypeError` / `AttributeError`。

### 4.2 内置 API

| 方法签名 | 说明 |
|----------|------|
| `await get(ident: PK, **kwargs) -> T \| None` | 按主键获取。`PK` = `int \| str \| tuple \| dict`，对应 SQLAlchemy `session.get()`。 |
| `await get_list(*clause) -> Sequence[T]` | 按任意 SQLAlchemy 布尔表达式过滤返回全部。 |
| `await create_model(**kwargs) -> T` | 用 kwargs 构造 model → `session.add` → `flush`，返回刷新后的实例。 |
| `await create_batch(values: Sequence[dict]) -> Sequence[T]` | 批量 insert，使用 `INSERT ... RETURNING`，不支持 RETURNING 的数据库请使用 `create_batch_with_pk`。 |
| `await create_batch_with_pk(values, _pk_name="id") -> Sequence[T]` | 先批量插入，再按主键集合分批（每批 1000）回查，兼容所有数据库。 |
| `await update_model(model, _ignore_none=True, **kwargs) -> T` | 按 kwargs 打补丁更新，`_ignore_none=True` 时不覆盖原值为 `None` 的字段。 |
| `await delete(model)` | 调用 `session.delete(model)`（物理删除；要软删请 `update_model(model, deleted=1)`）。 |
| `self.session: AsyncSession` | 属性，直接取到底层 session，方便你使用 `exec` 进行复杂查询。 |

### 4.3 在路由中使用

```python
from fastapi_extra.form import Page

@app.post("/users", response_model=APIResult[UserOut])
async def create_user(body: UserIn, service: UserService):
    user = await service.create_model(**body.model_dump())
    return APIResult.ok(UserOut.model_validate(user, from_attributes=True))


@app.get("/users", response_model=APIResult[Page[UserOut]])
async def list_users(service: UserService, page_num: int = 1, page_size: int = 20):
    all_items = await service.get_list()   # 简化示例，真实场景请分页
    total = len(all_items)
    items = [UserOut.model_validate(u, from_attributes=True)
             for u in all_items[(page_num-1)*page_size : page_num*page_size]]
    return APIResult.ok(Page(items=items, total=total, page_num=page_num, page_size=page_size))
```

---

## 5. SQL 模板映射（`sqlmap`）

对于复杂多表查询 / 报表 SQL，写 SQLAlchemy 语句既冗长又难以调试。`sqlmap` 模块允许把 SQL 写到独立的 `.sql` 文件，然后用 `@Mapped` 装饰器直接绑定到 Service 方法。

### 5.1 配置与加载

`config.default.toml`：

```toml
[sqlmap]
path   = "./template/sql"   # 存放 .sql 文件的目录
suffix = ".sql"
```

启动时加载：

```python
from fastapi_extra.database.sqlmap import install as sqlmap_install

@asynccontextmanager
async def lifespan(app: FastAPI):
    ...
    sqlmap_install()   # 扫描 path 下所有 suffix 文件，写入 _templates 全局字典
    yield
```

### 5.2 示例

`template/sql/select_user_order_stats.sql`：

```sql
SELECT
    u.id        AS user_id,
    u.name      AS user_name,
    COUNT(o.id) AS order_count,
    SUM(o.amount) AS total_amount
FROM user u
LEFT JOIN "order" o ON o.user_id = u.id
WHERE u.deleted = 0
  AND (:min_age IS NULL OR u.age >= :min_age)
  AND (:max_age IS NULL OR u.age <= :max_age)
GROUP BY u.id, u.name
ORDER BY total_amount DESC
LIMIT :limit_ OFFSET :offset_;
```

在 Service 中声明一个**空方法**，方法名必须和 SQL 文件名（去掉后缀）一致：

```python
from pydantic import BaseModel
from fastapi_extra.database.sqlmap import Mapped
from fastapi_extra.database.service import ModelService
from typing import Sequence

class UserOrderStat(BaseModel):
    user_id: int
    user_name: str
    order_count: int
    total_amount: float | None = None

class ReportService(ModelService[User]):  # 只要是 SessionService 都可以
    ...

    @Mapped
    async def select_user_order_stats(
        self,
        min_age: int | None,
        max_age: int | None,
        limit_: int,
        offset_: int,
    ) -> Sequence[UserOrderStat]:
        """参数名需和 SQL 里的 :param 一一对应；空方法体即可。"""
```

然后在路由中使用：

```python
@app.get("/reports/user-order-stats")
async def stats(svc: ReportService, min_age: int = 20, max_age: int | None = None):
    rows = await svc.select_user_order_stats(min_age, max_age, limit_=10, offset_=0)
    return APIResult.ok(rows)
```

### 5.3 `@Mapped` 的行为规则

装饰器**完全根据方法签名推导**执行策略（不需要传任何额外参数）：

| 返回类型注解 | 行为 |
|--------------|------|
| `None` / 省略 | 执行 `session.execute(sql, params)`，不返回（用于 INSERT / UPDATE / DDL） |
| `X \| None` / `Optional[X]` | `fetch_one`：用 `first()` 或 `scalar_one_or_none()`；X 是 BaseModel 时会 `model_validate(row, from_attributes=True)`；返回 None 不报错。 |
| `X`（非空，非列表） | `fetch_one`，返回 None 时抛 `ValueError("Query ... expected a result but got None")`。 |
| `list[X]` / `Sequence[X]` / 其他序列 | `fetch_all`：X 是 BaseModel → `all()` 逐行 validate；X 是标量 → `scalars().all()`。 |

> 小提示：多表结果要映射到 Pydantic 时，务必在 SQL 中用 `AS` 把列别名对齐模型字段名（如 `user_name` 对应用户名字段）。

---

## 6. 最佳实践

1. **软删 / 未删除过滤**：所有查询记得加 `Model.deleted == 0`（除非要查历史）。`ModelService.get_list()` 不会自动加此条件，避免隐式约束。
2. **并发更新**：优先使用 `update_model(model, ...)`，其底层由 SQLAlchemy `version_id_col` 保护，冲突时抛 `StaleDataError`。
3. **事务边界**：每个请求 `DefaultSession` 结束时统一 `commit`，批量场景如需尽早提交可手动 `await service.session.commit()`。
4. **SQL 模板命名**：以动词语义 + 业务对象命名（`list_active_orders.sql` / `stat_user_growth.sql`），并在代码评审时把 SQL 纳入版本审查。
