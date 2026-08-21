# Cache Integration

`fastapi_extra` ships a Redis connection-pool component built on top of the `redis-py` asyncio client. Via `RedisPool` (app-scoped Component) + `RedisCli` (request-scoped dependency annotation), you can use Redis directly in any route or Service without managing connections manually.

> This module is an **optional extra**. Run `pip install fastapi-extra[redis]` first. Otherwise both `RedisPool` and `RedisCli` evaluate to `None` on import to avoid breaking imports when `redis` is not installed.

---

## 1. Configuration

`config.default.toml`:

```toml
[redis]
url = "redis://:password@localhost:6379/0"
max_connections = 50                          # pool size (None = unlimited)
connection_kwargs.socket_timeout   = 5       # extra kwargs for ConnectionPool.from_url
connection_kwargs.socket_connect_timeout = 2
connection_kwargs.retry_on_timeout = true
```

Notes:

- `url` supports `redis://`, `rediss://` (TLS) and `unix://` (Unix Socket).
- `max_connections` and every key inside `connection_kwargs` are passed through to `ConnectionPool.from_url(...)`.

---

## 2. Lifecycle: install / dispose

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi_extra.cache import RedisPool

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Install the component (creates the pool, writes to app.state)
    redis = RedisPool.install(app)

    yield

    # Close all connections in the pool
    await redis.dispose()
```

Temporary overrides at call-site are supported via `install(app, **override_options)`, useful for tests:

```python
redis = RedisPool.install(
    app,
    max_connections=10,
    socket_connect_timeout=1,
)
```

---

## 3. Use `RedisCli` in route handlers

`RedisCli` is a ready-made `Annotated[redis.asyncio.Redis, Depends(get_redis)]`:

```python
from fastapi_extra.cache import RedisCli
from fastapi_extra.response import APIResult

@app.get("/cache/echo")
async def cache_echo(key: str, value: str, redis: RedisCli) -> APIResult[str]:
    await redis.set(key, value, ex=60)    # 60-second TTL
    got = await redis.get(key)
    return APIResult.ok(got.decode() if got else None)
```

`get_redis` wraps each request with `async with pool.get_client() as client:`:

1. Borrows a connection from the `RedisPool` pool.
2. `yield client` to the route handler.
3. **Automatically returns** the connection to the pool after the request.

> ⚠️ Forgetting `RedisPool.install(app)` causes `AssertionError: RedisPool must be installed in lifespan` on first route access.

---

## 4. Use inside a Service

Combined with the `AbstractService` DI system:

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
            # Also cache empty values for 1 minute (cache penetration protection)
            await redis.setex(key, 60, json.dumps(None))
            return None

        profile = UserProfile.model_validate(user, from_attributes=True)
        await redis.setex(key, 600, profile.model_dump_json())
        return profile
```

---

## 5. Common patterns

### 5.1 Distributed lock (client-level)

`redis-py` natively supports `SET NX EX`. A lightweight lock is a one-liner:

```python
async def acquire(redis: RedisCli, key: str, ttl: int = 10) -> bool:
    return await redis.set(key, "1", nx=True, ex=ttl)

async def release(redis: RedisCli, key: str) -> None:
    await redis.delete(key)
```

### 5.2 Counters / rate limiting

```python
@app.post("/views/{article_id}")
async def incr_view(article_id: int, redis: RedisCli) -> APIResult[int]:
    total = await redis.incr(f"view:article:{article_id}")
    return APIResult.ok(total)
```

### 5.3 Pub / Sub

```python
# publisher
await redis.publish("news:channel", json.dumps({"hello": "fastapi_extra"}))

# subscriber (run inside lifespan or a dedicated task)
async def listener(pool: RedisPool):
    async with pool.get_client() as client:
        async with client.pubsub() as ps:
            await ps.subscribe("news:channel")
            async for msg in ps.listen():
                if msg["type"] == "message":
                    print("NEWS:", msg["data"])
```

---

## 6. FAQ

### Q1: Why is `RedisPool` equal to `None`?
Make sure to `pip install fastapi-extra[redis]`. When `redis` is missing, `fastapi_extra.cache.__init__` sets both `RedisPool` and `RedisCli` to `None` inside an `except ImportError` guard to avoid crashing imports.

### Q2: Pool size too small, leading to waits?
Look for `BlockingPool` waits in your logs. As a rule of thumb, set `max_connections` to `2~3 × concurrent worker count`, then tune via load testing.

### Q3: Unclosed client session warning?
Always call `await RedisPool.dispose()` in the shutdown phase of lifespan. Failing to do so leaves connections dangling and produces the unclosed session warning on exit.
