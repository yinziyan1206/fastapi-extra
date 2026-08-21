# fastapi_extra 文档

`fastapi_extra` 是基于 **FastAPI** 的企业级增强扩展库（Python >= 3.12，BSD-3-Clause 许可），在 FastAPI 之上提供开箱即用的数据库、缓存、任务调度、统一响应、依赖注入等完整能力。

---

## 功能概览

| 模块 | 说明 | 详见 |
|------|------|------|
| 性能增强 | 通过 monkey-patch 优化 FastAPI 内部参数解析与路由匹配，并内置缓存；使用 Cython 原生实现雪花 ID 生成器与 URL 解析器 | [快速入门 · setup 初始化](./getting-started.md) |
| 配置管理 | 基于 `pydantic-settings` 的多层级配置加载（TOML > 环境变量 > 默认值 > Secrets） | [Settings 配置](./settings.md) |
| 依赖注入 | `AbstractComponent` / `AbstractService` 抽象，基于 `Depends` 无缝集成，支持单例、上下文变量传递与生命周期管理 | [依赖注入](./dependency.md) |
| 数据库 ORM | 基于 SQLModel 的 `SQLBase` 基类（雪花 ID + 乐观锁 + 软删 + 时间戳）、异步 Session Factory、泛型 `ModelService[T]` CRUD、以及 `.sql` 模板 SQL 映射 | [数据库层](./database.md) |
| 缓存集成 | 异步 Redis 连接池管理，开箱即用的 `RedisCli` 依赖注入 | [缓存集成](./cache.md) |
| 任务调度 | 基于 APScheduler 的 `TaskRunner`，装饰式注册 Job，任务函数内支持完整的 FastAPI 依赖注入 | [任务调度](./taskrunner.md) |
| 统一响应 | 阿里云风格 `ResultEnum`（120+ 预定义错误码） + 泛型 `APIResult[T]` + `APIResponse` + `APIError` 异常 | [统一响应与错误码](./response.md) |
| 查询模型 | 分页 `Page[T]`、范围查询 `DataRange[T]`、动态条件 `ColumnExpression` / `WhereClause` | [表单与查询模型](./form.md) |

---

## 文档导航

1. **[快速入门 (Getting Started)](./getting-started.md)** — 安装、最小可运行示例、`setup()` 生命周期接入
2. **[配置管理 (Settings)](./settings.md)** — TOML 配置、环境变量覆盖、生产模式校验
3. **[依赖注入 (Dependency)](./dependency.md)** — `AbstractComponent`、`AbstractService`、install / setup / dispose
4. **[数据库层 (Database)](./database.md)** — 模型基类、Session、CRUD Service、SQL 模板映射
5. **[缓存集成 (Cache)](./cache.md)** — `RedisPool`、`RedisCli` 依赖注入
6. **[统一响应与错误码 (Response)](./response.md)** — `APIResult`、`APIError`、`ResultEnum`
7. **[表单与查询模型 (Form)](./form.md)** — `Page` / `WhereClause` / `DataRange` / `ColumnExpression`
8. **[任务调度 (TaskRunner)](./taskrunner.md)** — `add_job` / `@scheduled_job`、依赖注入的任务函数

---

## 技术栈

- **Python** >= 3.12
- **FastAPI** >= 0.141.0
- **SQLModel** >= 0.0.39
- **Pydantic Settings** >= 2.15.0
- **可选依赖**：
  - `redis`（`pip install fastapi-extra[redis]`）
  - `apscheduler`（`pip install fastapi-extra[scheduler]`）
  - `asyncmy` / `aiomysql`（MySQL 异步驱动）
  - `asyncpg`（PostgreSQL 异步驱动）
  - `oracledb`（Oracle 异步驱动）

---

## 项目结构

```
fastapi_extra/
├── __init__.py           # setup() 入口，对 FastAPI 内部打补丁
├── _patch.py             # FastAPI 内部增强（参数解析/路由匹配/QueryParams）
├── dependency.py         # 依赖注入元类、AbstractComponent、AbstractService
├── settings.py           # 多层 Settings（TOML + 环境变量）
├── types.py              # 通用 TypeVar、类型别名（Cursor、LocalDateTime 等）
├── response.py           # APIResult / APIResponse / ResultEnum / APIError
├── form.py               # Page / WhereClause / DataRange / ColumnExpression
├── taskrunner.py         # APScheduler 包装的异步任务调度器
├── utils.py              # 机器码种子（雪花 ID 基础）
├── database/
│   ├── __init__.py       # 对外导出 Session / SQLBase / ModelService
│   ├── model.py          # AutoPK / LocalPK / Versioned / Deleted / Optime / SQLBase
│   ├── session.py        # SessionFactory、get_session 依赖、DefaultSession
│   ├── service.py        # 泛型 ModelService[T] CRUD
│   └── sqlmap.py         # @Mapped 注解 + .sql 模板映射
└── cache/
    ├── __init__.py
    └── redis.py          # RedisPool / RedisCli（可选依赖）
```
