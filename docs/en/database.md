# Database Layer

The database module of `fastapi_extra` is built on top of **SQLModel** (the merged SQLAlchemy + Pydantic layer) and provides four capabilities:

1. **Model base classes**: `SQLBase` uniformly provides primary key, optimistic lock, soft-delete and timestamp columns.
2. **Async Session factory**: `SessionFactory` (app-scoped component) + `get_session` (request-scoped Depends) + `DefaultSession` (annotation-ready alias).
3. **Generic CRUD Service**: `ModelService[T]`, built on `AbstractService`. Subclassing once gives you `get` / `list` / `create` / `update` / `delete` out of the box.
4. **SQL template mapper**: Bind `.sql` files onto service methods via the `@Mapped` decorator. Execution strategy (`execute` / `fetch_one` / `fetch_all`) is automatically selected from the method's return type.

---

## 1. Configuration

Declare in `config.default.toml`:

```toml
[datasource]
url = "mysql+asyncmy://root:pass@127.0.0.1:3306/demo?charset=utf8mb4"
echo = false                 # SQLAlchemy echo: log SQL statements (dev)
echo_pool = false            # log pool events
isolation_level = "READ COMMITTED"
options.pool_size = 20       # passed through to create_async_engine
options.max_overflow = 40
```

Supported drivers: `mysql+asyncmy`, `mysql+aiomysql`, `postgresql+asyncpg`, `oracle+oracledb`.

---

## 2. Model base classes

### 2.1 `SQLBase` = LocalPK + Versioned + Deleted + Optime

```python
from fastapi_extra.database import SQLBase
from sqlmodel import Field

class User(SQLBase, table=True):
    name: str = Field(max_length=64, title="Username")
    age: int | None = Field(default=None, title="Age")
    email: str = Field(max_length=128, unique=True)
```

`User` inherits the following columns automatically:

| Base class | Column | Description |
|------------|--------|-------------|
| `LocalPK` | `id: Cursor` (BigInteger) | Snowflake-generated PK. Machine-id sourced from `get_machine_seed()` in `fastapi_extra/utils.py` (override there to customize). **Serialized as string** via `types.Cursor`'s PlainSerializer. |
| `Versioned` | `version_id: int` | Optimistic-lock column (SQLAlchemy `version_id_col`). Concurrent UPDATEs automatically raise `StaleDataError` on conflict. |
| `Deleted` | `deleted: int` | Soft-delete flag. 0 = alive, 1 = deleted. Defaults to 0. |
| `Optime`  | `create_at: LocalDateTime` | Creation time; DB-side `DEFAULT NOW()`. Serialized as `%Y-%m-%d %H:%M:%S`. |
| `Optime`  | `update_at: LocalDateTime` | Update time; DB-side `ON UPDATE NOW()`. Same format as above. |

> `LocalPK` vs `AutoPK`: `AutoPK` uses database auto-increment (`autoincrement=True`). `LocalPK` uses the local Snowflake generator (`autoincrement=False`), which is suitable for sharded / multi-writer setups. `SQLBase` uses Snowflake by default.

### 2.2 Compose a la carte

You can also pick only the traits you need. For example, a primary-key + optimistic-lock model without soft-delete:

```python
from fastapi_extra.database.model import LocalPK, Versioned, Optime

class Order(LocalPK, Versioned, Optime, table=True):
    ...
```

### 2.3 Deleted flag

You can use the `Deleted` trait to enable soft-delete by event listener. for example:

```python
from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session
from fastapi_extra.database.model import Deleted

@event.listens_for(Session, "do_orm_execute")
def add_filtering_criteria(execute_state: ORMExecuteState):
    """add_filtering_criteria 

    Automatically add `deleted == 0` filtering criteria to all ORM queries.

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

## 3. Session: connection pool & dependency injection

### 3.1 Install the SessionFactory

```python
from fastapi_extra.database import SessionFactory

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionFactory.install(app)   # creates AsyncEngine + ConnectionPool
    yield
    await db.dispose()                 # shuts down the engine; releases all connections
```

### 3.2 Use `DefaultSession` in route handlers

`DefaultSession` is a pre-packaged `Annotated[AsyncSession, Depends(get_session)]`:

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

`get_session` as a FastAPI dependency will:
1. Request an `AsyncSession` from the `SessionFactory`.
2. `yield` it to your route function.
3. Automatically `await session.commit()` once the request finishes (on exception, FastAPI propagates it and rolls back; you can also manually rollback on error).

---

## 4. `ModelService[T]`: generic CRUD

Writing CRUD for every model by hand is tedious. `ModelService[T]` does it once for you.

### 4.1 Declare a Service

```python
from fastapi_extra.database import ModelService

class UserService(ModelService[User]):
    """Domain-specific methods for the User model can be added here."""

    async def list_by_age_gt(self, age: int):
        return await self.get_list(User.age > age)
```

> ⚠️ The generic parameter `T` MUST be a `table=True` SQLModel. Otherwise a `TypeError` / `AttributeError` is raised.

### 4.2 Built-in API

| Signature | Description |
|-----------|-------------|
| `await get(ident: PK, **kwargs) -> T \| None` | Fetch by primary key. `PK = int \| str \| tuple \| dict` — forwarded to SQLAlchemy `session.get()`. |
| `await get_list(*clause) -> Sequence[T]` | Return all rows that satisfy any number of SQLAlchemy boolean expressions. |
| `await create_model(**kwargs) -> T` | Build model from kwargs → `session.add` → `flush`, then return the refreshed instance. |
| `await create_batch(values: Sequence[dict]) -> Sequence[T]` | Bulk insert using `INSERT ... RETURNING`. If your database doesn't support RETURNING, use `create_batch_with_pk` instead. |
| `await create_batch_with_pk(values, _pk_name="id") -> Sequence[T]` | Bulk insert first, then query back by PK set in chunks of 1000; compatible with every database. |
| `await update_model(model, _ignore_none=True, **kwargs) -> T` | Patches the model with kwargs. With `_ignore_none=True`, fields set to `None` do not overwrite existing values. |
| `await delete(model)` | Calls `session.delete(model)` (**physical** delete). For soft-delete, call `update_model(model, deleted=1)` instead. |
| `self.session: AsyncSession` | Property that returns the underlying session, handy for `exec` with complex queries. |

### 4.3 Use in routes

```python
from fastapi_extra.form import Page

@app.post("/users", response_model=APIResult[UserOut])
async def create_user(body: UserIn, service: UserService):
    user = await service.create_model(**body.model_dump())
    return APIResult.ok(UserOut.model_validate(user, from_attributes=True))


@app.get("/users", response_model=APIResult[Page[UserOut]])
async def list_users(service: UserService, page_num: int = 1, page_size: int = 20):
    all_items = await service.get_list()   # simplified; apply pagination in production
    total = len(all_items)
    items = [UserOut.model_validate(u, from_attributes=True)
             for u in all_items[(page_num-1)*page_size : page_num*page_size]]
    return APIResult.ok(Page(items=items, total=total, page_num=page_num, page_size=page_size))
```

---

## 5. SQL template mapper (`sqlmap`)

For complex multi-table reporting SQL, writing SQLAlchemy statements is verbose and hard to review. The `sqlmap` module lets you keep SQLs as standalone `.sql` files and bind them to service methods with the `@Mapped` decorator.

### 5.1 Configuration & loading

`config.default.toml`:

```toml
[sqlmap]
path   = "./template/sql"   # directory that contains your .sql files
suffix = ".sql"
```

Load templates at boot:

```python
from fastapi_extra.database.sqlmap import install as sqlmap_install

@asynccontextmanager
async def lifespan(app: FastAPI):
    ...
    sqlmap_install()   # scans every `suffix` file under `path` into _templates
    yield
```

### 5.2 Example

`template/sql/select_user_order_stats.sql`:

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

Declare an **empty method** on a service whose name matches the file stem exactly (without `.sql`):

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

class ReportService(ModelService[User]):  # any SessionService works
    ...

    @Mapped
    async def select_user_order_stats(
        self,
        min_age: int | None,
        max_age: int | None,
        limit_: int,
        offset_: int,
    ) -> Sequence[UserOrderStat]:
        """Parameter names must exactly match :param placeholders in SQL. Method body stays empty."""
```

Then use it in a route:

```python
@app.get("/reports/user-order-stats")
async def stats(svc: ReportService, min_age: int = 20, max_age: int | None = None):
    rows = await svc.select_user_order_stats(min_age, max_age, limit_=10, offset_=0)
    return APIResult.ok(rows)
```

### 5.3 `@Mapped` behavior rules

The decorator derives execution strategy **completely from the method signature** (no extra parameters required):

| Return type annotation | Behavior |
|------------------------|----------|
| `None` / omitted       | Runs `session.execute(sql, params)`; returns nothing. Use for INSERT / UPDATE / DDL. |
| `X \| None` / `Optional[X]` | `fetch_one`: returns `first()` or `scalar_one_or_none()`. When `X` is a BaseModel, the row is `model_validate(row, from_attributes=True)`'d. Returning `None` is NOT an error. |
| `X` (non-null, non-list) | `fetch_one`. If DB returns nothing, raises `ValueError("Query ... expected a result but got None")`. |
| `list[X]` / `Sequence[X]` / any sequence | `fetch_all`: when X is a BaseModel, rows are collected via `all()` and validated; when X is a scalar type, returns `scalars().all()`. |

> Tip: when you map multi-table result sets to Pydantic, always use `AS` in SQL to produce column aliases that exactly match your model field names (e.g. `user_name`).

---

## 6. Best practices

1. **Soft-delete filtering**: Always append `Model.deleted == 0` unless you intend to query historical records. `ModelService.get_list()` does NOT add this automatically — implicit behavior is avoided.
2. **Concurrent updates**: Prefer `update_model(model, ...)`. It is backed by SQLAlchemy's `version_id_col` and throws `StaleDataError` on version mismatch.
3. **Transaction boundary**: Each `DefaultSession` commits at the end of the request. For batching pipelines that need earlier persistence, call `await service.session.commit()` manually.
4. **SQL template naming**: Use verb + business-object naming (`list_active_orders.sql`, `stat_user_growth.sql`) and include SQL changes in code review.
