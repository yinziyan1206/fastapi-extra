# Getting Started

This page walks through scaffolding a new FastAPI project with `fastapi_extra`: installation, configuration, lifespan initialization, and writing your first minimal APIs.

---

## 1. Installation

### 1.1 Core + ORM only

```bash
pip install fastapi-extra
# Pick an async database driver for your RDBMS:
pip install fastapi-extra[mysql]      # asyncmy (MySQL)
pip install fastapi-extra[pgsql]      # asyncpg (PostgreSQL)
pip install fastapi-extra[oracle]     # oracledb (Oracle)
```

### 1.2 Full stack (Redis cache + APScheduler)

```bash
pip install fastapi-extra[redis,scheduler]
```

### 1.3 Source install (dev / Cython native extensions)

The Snowflake ID generator and URL query-string parser are implemented in Cython. It is recommended to compile them when installing from source:

```bash
git clone <repo-url>
cd fastapi-extra
pip install -e ".[redis,scheduler,mysql]"
```

> Cython build requires `setuptools>=74.1.0` and a C compiler. If compilation fails, the library still works via the `.pyi` stub files that ship with the package (IDE type hints remain functional).

---

## 2. Prepare configuration files

`fastapi_extra` uses a two-layer configuration system: **TOML + Environment Variables**. Create the following in your project root:

### `config.default.toml`

```toml
title = "My FastAPI Service"
version = "0.1.0"
debug = true
mode  = "dev"   # dev / test / prod; mode=prod forces schema off & debug=False

[datasource]
url = "mysql+asyncmy://root:password@127.0.0.1:3306/demo?charset=utf8mb4"
echo = false
echo_pool = false
isolation_level = "READ COMMITTED"
options.pool_size = 20
options.max_overflow = 40

[redis]
url = "redis://localhost:6379/0"
max_connections = 50

[sqlmap]
path = "./template/sql"
suffix = ".sql"
```

Per-environment overrides can be placed in `config.custom.toml`; its fields take precedence over `config.default.toml`. See [Settings](./settings.md) for loading order details.

---

## 3. Application entry point

Call `fastapi_extra.setup(app)` early in application startup to enable all internal optimizations (cached parameter resolution, optimized router prefix matching, latin-1 compatible QueryParams parsing). We recommended composing it inside a `lifespan` and alongside component lifecycle hooks such as `SessionFactory` / `RedisPool`.

### `main.py`

```python
from contextlib import asynccontextmanager

import fastapi_extra
from fastapi import FastAPI

from fastapi_extra.cache import RedisPool
from fastapi_extra.database import SessionFactory
from fastapi_extra.database.sqlmap import install as sqlmap_install
from fastapi_extra.response import APIResult, APIError, ResultEnum
from fastapi_extra.taskrunner import DefaultTaskRunner


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) Patch FastAPI internals — MUST be called before any route registration
    fastapi_extra.setup(app)

    # 2) Install database connection pool (wires singleton onto app.state)
    db = SessionFactory.install(app)

    # 3) Install Redis connection pool (optional)
    redis = RedisPool.install(app)

    # 4) Load SQL templates from ./template/sql/*.sql
    sqlmap_install()

    # 5) Start task scheduler (optional; needs pip install fastapi-extra[scheduler])
    DefaultTaskRunner.install(app)
    DefaultTaskRunner.start()

    yield   # app is serving requests

    # ---------- shutdown ----------
    await db.dispose()
    await redis.dispose()


app = FastAPI(lifespan=lifespan)


# ————————————————— Example routes —————————————————

@app.get("/")
async def hello() -> APIResult[str]:
    """The simplest unified-response endpoint."""
    return APIResult.ok("Hello fastapi_extra!")


@app.get("/items/{item_id}")
async def get_item(item_id: int, name: str = "demo") -> APIResult[dict]:
    if item_id <= 0:
        # Use a predefined ResultEnum to raise a standardized business exception
        raise APIError(ResultEnum.A0400, message="item_id must be a positive integer")
    return APIResult.ok({"item_id": item_id, "name": name})


# ————————————————— Global APIError handler —————————————————

from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={"code": exc.code, "message": exc.message, "data": None},
    )
```

---

## 4. Start the server

```bash
uvicorn main:app --reload --port 8000
```

Open <http://127.0.0.1:8000/docs> to browse the generated OpenAPI UI.

You can also verify the canonical error response:

```bash
curl http://127.0.0.1:8000/items/-1
# => {"code":"A0400","message":"item_id must be a positive integer","data":null}
```

---

## 5. Next Steps

Now that the minimal project works, we recommend reading these in order:

1. **[Settings / Configuration](./settings.md)** — Understand TOML loading order, what `mode=prod` enforces, and how to add custom configuration sections.
2. **[Dependency Injection](./dependency.md)** — The difference between `AbstractComponent` and `AbstractService`, and how to build custom components.
3. **[Database Layer](./database.md)** — Define models (inherit `SQLBase`), use `ModelService[T]` for CRUD, and bind `.sql` templates with `@Mapped`.
4. **[Unified Response & Error Codes](./response.md)** — Project conventions around `APIResult[T]` / `APIError` / `ResultEnum`.
5. **[Cache Integration](./cache.md)** — Inject `RedisCli` into endpoints and cache query results.
6. **[Task Runner](./taskrunner.md)** — Register asynchronous jobs (report delivery, data cleanup) as scheduled tasks.
