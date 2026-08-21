# Dependency Injection

On top of FastAPI's native `Depends` system, `fastapi_extra` introduces two abstractions:

- **`AbstractComponent`**: process-wide singleton components (database connection pool, Redis connection pool). Mounted onto `app.state` via `install(app)`; started / released with the application lifespan.
- **`AbstractService`**: request-scoped / context-scoped services (e.g. CRUD services over the current `AsyncSession`). Context is propagated via `ContextVar` while the *instance* itself is reused as a class-level singleton.

Both abstractions are implemented via the `DependencyMetaClass` metaclass, which auto-wraps them into `Annotated[T, Depends(...)]` so you can drop them into route signatures just like any other FastAPI dependency — no manual `Depends(X)` required.

---

## 1. Core Concepts

### 1.1 Auto-wrapping metaclass

Any concrete (non-`abstract`) subclass of `AbstractComponent` or `AbstractService` is replaced by the metaclass with:

```
Annotated[YourClass, Depends(<loader>)]
```

So you **do not** need to write `Depends(YourClass)`:

```python
from fastapi_extra.database.service import ModelService

class User:  # see database.md for the real SQLModel definition
    pass

class UserService(ModelService[User]):  # inherits from AbstractService
    pass

# In routes: type annotations are sufficient; FastAPI resolves Depends automatically
@app.get("/users/{pk}")
async def get_user(pk: int, service: UserService):
    return await service.get(pk)
```

### 1.2 Component vs Service

| Dimension | `AbstractComponent` | `AbstractService` |
|-----------|---------------------|-------------------|
| Lifecycle | Application-wide (start once, stop once) | Request-scoped (per-request injection; instance is singleton) |
| Contents | Heavy resources (connection pools, engines, schedulers) | `AsyncSession`, current user, permissions, request context |
| Initialization | Class method `setup(**options)` + `install(app, ...)` (writes self into `app.state`) | `__init__(self, **kwargs)` + read via `get_context(name)` |
| Dependency loading | `__load__(request)` retrieves the singleton from `request.app.state` | Constructor called directly; `ContextVar` binds current context |
| Cleanup | `async def dispose(self)` — invoke manually during shutdown | None (context collected with the request task) |

---

## 2. AbstractComponent

Typical examples: `SessionFactory` (database pool), `RedisPool`.

### 2.1 Example custom component

```python
from typing import Self
from fastapi_extra.dependency import AbstractComponent
from some_client import AsyncClient  # any async client

class HttpClientPool(AbstractComponent):
    __slot__ = ("_client",)

    def __init__(self):
        self._client = None

    @classmethod
    def setup(cls, **options) -> Self:
        obj = cls()
        obj._client = AsyncClient(**options)  # init the heavy resource
        return obj

    def client(self):
        return self._client

    async def dispose(self) -> None:
        if self._client:
            await self._client.aclose()
```

### 2.2 Install during lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    http = HttpClientPool.install(app, timeout=10, limits=...)
    yield
    await http.dispose()
```

`install(app, *args, **kwargs)`:

1. Calls `cls.setup(*args, **kwargs)` to create the component instance.
2. Writes the instance into `app.state` using the `__token__` key (`module.name`).
3. Returns the instance so you can immediately reference it.

### 2.3 Inject into route handlers

```python
@app.get("/ping-external")
async def ping(pool: HttpClientPool):
    resp = await pool.client().get("https://example.com")
    return APIResult.ok(resp.status_code)
```

FastAPI calls the metaclass-registered `__load__(request)` loader, which retrieves the already-installed singleton from `request.app.state`.

> ⚠️ Rule: **Without a prior `install(app)` call the first route access will raise `AssertionError: <ClassName> must be installed in lifespan`.**

---

## 3. AbstractService

Typical example: **`ModelService[T]`** (performs CRUD over an injected `AsyncSession`).

### 3.1 Example custom service

Scenario: an order service that needs the current user AND a database session.

```python
from fastapi import Depends
from pydantic import BaseModel
from fastapi_extra.dependency import AbstractService
from fastapi_extra.database import DefaultSession
from fastapi_extra.database.session import AsyncSession

class CurrentUser(BaseModel):
    user_id: int
    role: str

async def current_user(header: str = Header(...)) -> CurrentUser:
    ...  # parse token, return current user

class OrderService(AbstractService):

    def __init__(
        self,
        session: DefaultSession,                  # depends on AsyncSession
        user: CurrentUser = Depends(current_user), # depends on current user
    ):
        # save everything into the ContextVar
        super().__init__(session=session, user=user)

    async def create_order(self, sku: str, qty: int):
        session: AsyncSession = self.get_context("session")
        user: CurrentUser = self.get_context("user")
        # business logic…
        return Order(user_id=user.user_id, sku=sku, qty=qty)
```

Key points:

1. Dependencies can be declared normally in `__init__` (either via type hints or explicit `Depends()`).
2. You MUST call `super().__init__(**kwargs)` with the keys you want to preserve in the context.
3. Retrieve values anywhere via `self.get_context("<name>")` (asserts that super init was called).

### 3.2 Singleton semantics

`AbstractService.__new__` guarantees **one object instance per subclass**. What varies per request is the `ContextVar`. This avoids reconstructing the method table / class metadata for every request while keeping the context isolated.

---

## 4. `async_wrapper`

If a class's `__init__` / dependency callable is synchronous but the FastAPI dependency graph runs in async context, `fastapi_extra` wraps it into an `async def` via `async_wrapper(func)`. The `DependencyMetaClass` already applies this automatically when registering the default loader, so you generally **don't need to call it manually**.

---

## 5. FAQ

### Q1: Why does my custom class fail to inject?
- Verify the subclass is not declared with `abstract=True`.
- If it is an `AbstractComponent`, ensure `install(app)` is called in the lifespan.
- If it is an `AbstractService`, make sure `super().__init__(...)` is called inside `__init__`.

### Q2: Can `install(app)` be invoked multiple times?
Yes. Every call re-runs `setup()` and overwrites the value stored on `app.state`. In practice you only need to call it once during startup.

### Q3: Does the `ContextVar` leak?
`AbstractService.__container__` is bound to a `ContextVar`, whose lifetime is tied to the current asyncio Task. FastAPI's `Depends` reclaims the Task once the request ends, so as long as you use `super().__init__(**kwargs)` there is no leak.
