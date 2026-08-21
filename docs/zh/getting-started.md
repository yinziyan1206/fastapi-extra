# 快速入门

本文介绍如何在一个新的 FastAPI 项目中接入 `fastapi_extra`，完成安装、配置、初始化、以及编写最小可运行的 API。

---

## 1. 安装

### 1.1 基础安装（只包含核心 + ORM）

```bash
pip install fastapi-extra
# 选择一种数据库异步驱动
pip install fastapi-extra[mysql]      # asyncmy（MySQL）
pip install fastapi-extra[pgsql]      # asyncpg（PostgreSQL）
pip install fastapi-extra[oracle]     # oracledb（Oracle）
```

### 1.2 完整安装（含 Redis 缓存 + APScheduler 任务调度）

```bash
pip install fastapi-extra[redis,scheduler]
```

### 1.3 从源码安装（开发 / Cython 原生扩展）

仓库内的雪花 ID 生成器与 URL 查询串解析器使用 Cython 编写，推荐在构建机器上编译安装：

```bash
git clone <repo-url>
cd fastapi-extra
pip install -e ".[redis,scheduler,mysql]"
```

> Cython 构建需要 `setuptools>=74.1.0` 与 C 编译器；若编译失败，仍可通过纯 Python 回退（`.pyi` stub 文件保证类型提示可用）。

---

## 2. 准备配置文件

`fastapi_extra` 采用 **TOML + 环境变量** 双层配置。在项目根目录创建：

### `config.default.toml`

```toml
title = "My FastAPI Service"
version = "0.1.0"
debug = true
mode  = "dev"   # dev / test / prod；mode=prod 会自动关闭 debug 与 OpenAPI schema

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

如需区分部署环境，可创建 `config.custom.toml`，其字段会覆盖 `config.default.toml`。加载优先级参见 [Settings 配置](./settings.md)。

---

## 3. 初始化入口

在应用启动时调用 `fastapi_extra.setup(app)` 即可启用所有内部增强（参数解析缓存、路由前缀匹配优化、QueryParams latin-1 兼容）。推荐在 `lifespan` 中完成，并配合 `SessionFactory` / `RedisPool` 等组件完成 install / dispose。

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
    # 1) 对 FastAPI 打补丁（必须在任何路由注册前调用）
    fastapi_extra.setup(app)

    # 2) 安装数据库连接池组件（install → app.state 上挂载单例）
    db = SessionFactory.install(app)

    # 3) 安装 Redis 连接池（可选）
    redis = RedisPool.install(app)

    # 4) 加载 SQL 模板（放置于 ./template/sql/*.sql）
    sqlmap_install()

    # 5) 启动任务调度器（可选，需要 pip install fastapi-extra[scheduler]）
    DefaultTaskRunner.install(app)
    DefaultTaskRunner.start()

    yield   # 服务运行中

    # ---------- shutdown ----------
    await db.dispose()
    await redis.dispose()


app = FastAPI(lifespan=lifespan)


# ————————————————— 示例路由 —————————————————

@app.get("/")
async def hello() -> APIResult[str]:
    """最简单的统一响应接口。"""
    return APIResult.ok("Hello fastapi_extra!")


@app.get("/items/{item_id}")
async def get_item(item_id: int, name: str = "demo") -> APIResult[dict]:
    if item_id <= 0:
        # 使用预定义错误码抛出统一异常，由全局异常处理器返回规范 JSON
        raise APIError(ResultEnum.A0400, message="item_id 必须为正整数")
    return APIResult.ok({"item_id": item_id, "name": name})


# 注册全局 APIError 异常处理器（FastAPI 自定义异常）
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

## 4. 启动服务

```bash
uvicorn main:app --reload --port 8000
```

打开 <http://127.0.0.1:8000/docs> 即可看到 OpenAPI 文档。

你也可以测试统一错误码返回：

```bash
curl http://127.0.0.1:8000/items/-1
# => {"code":"A0400","message":"item_id 必须为正整数","data":null}
```

---

## 5. 下一步

至此，最小项目已经跑通。推荐按以下顺序继续阅读：

1. **[Settings 配置](./settings.md)** — 深入理解 TOML 加载顺序、`mode=prod` 的校验行为、如何扩展自定义配置段。
2. **[依赖注入](./dependency.md)** — `AbstractComponent` 与 `AbstractService` 的差异、如何实现自定义组件。
3. **[数据库层](./database.md)** — 定义模型（继承 `SQLBase`）、使用 `ModelService[T]` 做 CRUD、用 `@Mapped` 绑定 `.sql` 模板。
4. **[统一响应与错误码](./response.md)** — 约定 `APIResult[T]` / `APIError` / `ResultEnum` 的项目级最佳实践。
5. **[缓存集成](./cache.md)** — 在路由中注入 `RedisCli`、缓存查询结果。
6. **[任务调度](./taskrunner.md)** — 把需要异步执行的业务（报表推送、数据清理）注册为调度任务。
