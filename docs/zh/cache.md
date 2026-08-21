# 缓存集成

`fastapi_extra` 内置基于 `redis-py` asyncio 客户端的 Redis 连接池组件。通过 `RedisPool`（应用级 Component）+ `RedisCli`（请求级依赖注解），可在任意路由 / Service 中直接使用 Redis，无需手动管理连接生命周期。

> 本模块为**可选依赖**：需要 `pip install fastapi-extra[redis]`。否则 `RedisPool` / `RedisCli` 导入值为 `None`。

---

## 1. 配置

`config.default.toml`：

```toml
[redis]
url = "redis://:password@localhost:6379/0"
max_connections = 50                # 连接池最大连接数（默认 None = 无限）
connection_kwargs.socket_timeout   = 5    # 传给 redis.asyncio.ConnectionPool 的额外参数
connection_kwargs.socket_connect_timeout = 2
connection_kwargs.retry_on_timeout = true
```

说明：

- `url` 支持 `redis://` / `rediss://`（TLS）/ `unix://`（Unix Socket）。
- `max_connections`、`connection_kwargs` 均直接透传给 `ConnectionPool.from_url(...)`。

---

## 2. 生命周期：install / dispose

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi_extra.cache import RedisPool

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 安装组件（创建连接池，写入 app.state）
    redis = RedisPool.install(app)

    yield

    # 关闭连接池（断开所有 Redis 连接）
    await redis.dispose()
```

`install(app, **override_options)` 支持在调用处临时覆盖部分配置，例如测试环境：

```python
redis = RedisPool.install(
    app,
    max_connections=10,
    socket_connect_timeout=1,
)
```

---

## 3. 在路由中直接用 `RedisCli`

`RedisCli` 是一个 `Annotated[redis.asyncio.Redis, Depends(get_redis)]`，可直接写入签名：

```python
from fastapi_extra.cache import RedisCli
from fastapi_extra.response import APIResult

@app.get("/cache/echo")
async def cache_echo(key: str, value: str, redis: RedisCli) -> APIResult[str]:
    await redis.set(key, value, ex=60)    # 60 秒过期
    got = await redis.get(key)
    return APIResult.ok(got.decode() if got else None)
```

`get_redis` 内部每次请求都会 `async with pool.get_client() as client:`：

1. 从 `RedisPool` 连接池中借出一个连接；
2. `yield client` 给路由函数使用；
3. 请求结束后**自动归还**到连接池。

> ⚠️ 若你忘记 `RedisPool.install(app)`，路由首次访问会抛 `AssertionError: RedisPool must be installed in lifespan`。

---

## 4. 在 Service 中使用

配合 `AbstractService` 依赖注入系统：

```python
from fastapi_extra.cache import RedisCli
from fastapi_extra.database.service import ModelService
from fastapi_extra.dependency import AbstractService
from pydantic import BaseModel
import json

class UserProfile(BaseModel):
    name: str
    email: str

class UserCacheService(AbstractService):

    def __init__(self, redis: RedisCli, user_service: UserService):
        super().__init__(redis=redis, user_service=user_service)

    async def get_profile(self, user_id: int) -> UserProfile:
        redis = self.get_context("redis")
        user_service = self.get_context("user_service")

        key = f"user:profile:{user_id}"
        cached = await redis.get(key)
        if cached:
            return UserProfile.model_validate_json(cached)

        user = await user_service.get(user_id)
        if not user:
            # 空值也缓存 1 分钟（防止缓存穿透）
            await redis.setex(key, 60, json.dumps(None))
            return None

        profile = UserProfile.model_validate(user, from_attributes=True)
        await redis.setex(key, 600, profile.model_dump_json())
        return profile
```

---

## 5. 常见模式

### 5.1 分布式锁（`redlock` 客户端级）

`redis-py` 自带 SET NX EX，可自己实现轻量锁：

```python
async def acquire(redis: RedisCli, key: str, ttl: int = 10) -> bool:
    return await redis.set(key, "1", nx=True, ex=ttl)

async def release(redis: RedisCli, key: str) -> None:
    await redis.delete(key)
```

### 5.2 计数 / 限流

```python
@app.post("/views/{article_id}")
async def incr_view(article_id: int, redis: RedisCli) -> APIResult[int]:
    total = await redis.incr(f"view:article:{article_id}")
    return APIResult.ok(total)
```

### 5.3 发布 / 订阅

```python
# pub
await redis.publish("news:channel", json.dumps({"hello": "fastapi_extra"}))

# sub（在 lifespan 或独立协程中）
async def listener(pool: RedisPool):
    async with pool.get_client() as client:
        async with client.pubsub() as ps:
            await ps.subscribe("news:channel")
            async for msg in ps.listen():
                if msg["type"] == "message":
                    print("NEWS:", msg["data"])
```

---

## 6. 常见问题

### Q1：为什么我的 `RedisPool` 为 `None`？
请确认 `pip install fastapi-extra[redis]`。在未安装 redis 时，`fastapi_extra.cache.__init__` 会把 `RedisPool` / `RedisCli` 捕获为 `None`，避免 `ImportError` 直接中断导入。

### Q2：连接池太小导致等待？
观察日志中是否有 `BlockingPool` 等待；建议把 `max_connections` 设为 `2~3 × 并发 worker 数`，或在压测工具中逐步调优。

### Q3：关闭时未释放？
务必在 lifespan 的 shutdown 阶段 `await RedisPool.dispose()`，否则会看到 `Unclosed client session` 警告。
