# 依赖注入

`fastapi_extra` 在 FastAPI 原生的 `Depends` 之上，引入了两类抽象：

- **`AbstractComponent`**：进程级单例组件（如数据库连接池、Redis 连接池），通过 `install(app)` 挂载到 `app.state`，随应用生命周期启动 / 释放。
- **`AbstractService`**：请求级 / 上下文级服务（如基于当前 `AsyncSession` 的 CRUD 服务），自动通过 `ContextVar` 传播上下文，并在类层级上以**单例**方式复用。

两者都通过 `DependencyMetaClass` 元类自动包装成 `Annotated[T, Depends(...)]`，因此可以像普通 FastAPI 依赖一样，直接写在路由签名中。

---

## 1. 核心概念

### 1.1 自动包装的元类

任何继承 `AbstractComponent` 或 `AbstractService`（非 abstract）的具体子类，在类创建时会被元类替换为：

```
Annotated[YourClass, Depends(<loader>)]
```

因此你**不需要**再手动写 `Depends(YourClass)`：

```python
from fastapi_extra.database.service import ModelService

class User:  # 这是 SQLModel，真实代码见 database.md
    pass

class UserService(ModelService[User]):  # 继承 AbstractService 的子类
    pass

# 路由中：直接用类型注解即可被 FastAPI 正确解析为 Depends
@app.get("/users/{pk}")
async def get_user(pk: int, service: UserService):
    return await service.get(pk)
```

### 1.2 Component vs Service

| 维度 | `AbstractComponent` | `AbstractService` |
|------|---------------------|-------------------|
| 生命周期 | 应用级（启动一次、关闭一次） | 请求级（每次请求注入，实例单例但上下文变化） |
| 持有内容 | 连接池、引擎、调度器等重资源 | AsyncSession、当前用户、权限、请求上下文 |
| 初始化方式 | 类方法 `setup(**options)` + `install(app, ...)`（把自身放入 `app.state`） | `__init__(self, **kwargs)` + 通过 `get_context(name)` 读取注入 |
| 依赖加载 | `__load__(request)` 从 `request.app.state` 取回单例 | 直接调用构造，内部用 `ContextVar` 绑定当前上下文 |
| 释放方式 | `async def dispose(self)` 由开发者在 shutdown 时手动调用 | 无（上下文随请求 GC 回收） |

---

## 2. AbstractComponent

典型实现模式：**数据库连接池 `SessionFactory`、Redis 连接池 `RedisPool`**。

### 2.1 自定义组件示例

```python
from typing import Self
from fastapi_extra.dependency import AbstractComponent
from some_client import AsyncClient  # 伪代码：任意异步客户端

class HttpClientPool(AbstractComponent):
    __slot__ = ("_client",)

    def __init__(self):
        self._client = None

    @classmethod
    def setup(cls, **options) -> Self:
        obj = cls()
        obj._client = AsyncClient(**options)  # 重资源初始化
        return obj

    def client(self):
        return self._client

    async def dispose(self) -> None:
        if self._client:
            await self._client.aclose()
```

### 2.2 在 lifespan 中 install

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    http = HttpClientPool.install(app, timeout=10, limits=...)
    yield
    await http.dispose()
```

`install(app, *args, **kwargs)` 会：

1. 调用 `cls.setup(*args, **kwargs)` 创建组件实例；
2. 以 `__token__`（`module.name`）为键写入 `app.state`；
3. 返回组件实例，便于开发者立刻使用。

### 2.3 在路由中作为依赖

```python
@app.get("/ping-external")
async def ping(pool: HttpClientPool):
    resp = await pool.client().get("https://example.com")
    return APIResult.ok(resp.status_code)
```

FastAPI 会通过元类注册的 `__load__(request)` 函数，从 `request.app.state` 取回已 install 的单例。

> ⚠️ 规则：**如果不先 `install(app)`，路由首次访问会触发 `AssertionError: <ClassName> must be installed in lifespan`。**

---

## 3. AbstractService

典型实现模式：**`ModelService[T]`**（依赖 `AsyncSession` 完成 CRUD）。

### 3.1 自定义服务示例

场景：在业务服务中需要同时依赖数据库 session 与当前登录用户信息。

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
    ...  # 解析 token，返回当前用户

class OrderService(AbstractService):

    def __init__(
        self,
        session: DefaultSession,                # 依赖 AsyncSession
        user: CurrentUser = Depends(current_user),  # 依赖当前用户
    ):
        super().__init__(session=session, user=user)  # 存进 ContextVar

    async def create_order(self, sku: str, qty: int):
        session: AsyncSession = self.get_context("session")
        user: CurrentUser = self.get_context("user")
        # 业务逻辑……
        return Order(user_id=user.user_id, sku=sku, qty=qty)
```

要点：

1. `__init__` 可以正常声明依赖（用类型注解即可，或显式 `Depends()`）；
2. 必须调用 `super().__init__(**kwargs)`，其中 `kwargs` 就是需要保存的上下文；
3. 在任意方法里调用 `self.get_context("<name>")` 取回注入的值（没调用父类 init 会抛异常）。

### 3.2 单例语义

`AbstractService.__new__` 会保证**每个子类只有一个对象实例**。真正随请求变化的是 `ContextVar`，这样既避免了每次请求 `__init__` 的构造开销（元信息、方法表等），又保证了上下文隔离。

---

## 4. `async_wrapper`

如果一个类的 `__init__` / 依赖函数是**同步**的，但 FastAPI 依赖图中需要异步执行，`fastapi_extra` 会通过 `async_wrapper(func)` 把它包装为 `async def`。`DependencyMetaClass` 在注册默认 loader 时已经自动应用，通常**无需手动调用**。

---

## 5. 常见问题

### Q1：为什么自定义的类作为依赖注入失败？
- 确认该类继承的子类**不是 `abstract=True`**；
- 如果是 `AbstractComponent`，确保在 `lifespan` 中 `install(app)` 被调用；
- 如果是 `AbstractService`，在 `__init__` 里调用了 `super().__init__(...)`。

### Q2：`install(app)` 可以多次调用吗？
可以。每次调用都会重新执行 `setup()`，并把新实例覆盖写入 `app.state`。通常只在启动时调用一次即可。

### Q3：`ContextVar` 会泄漏吗？
`AbstractService.__container__` 绑定的是 `ContextVar`，它的生命周期与当前 asyncio 任务一致。FastAPI 的 `Depends` 体系会在请求结束后回收任务，因此只要使用 `super().__init__(**kwargs)` 正常赋值，就不会泄漏。
