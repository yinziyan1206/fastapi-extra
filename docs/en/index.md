# fastapi_extra Documentation

`fastapi_extra` is an enterprise-grade enhancement extension library for **FastAPI** (Python >= 3.12, BSD-3-Clause). It adds out-of-the-box database, cache, task scheduling, unified response, and dependency injection capabilities on top of FastAPI.

---

## Feature Overview

| Module | Description | See |
|--------|-------------|-----|
| Performance patch | Monkey-patches FastAPI internals for cached parameter parsing and router prefix matching; Cython-native Snowflake ID generator and URL query-string parser. | [Getting Started · `setup()` initialization](./getting-started.md) |
| Configuration | Multi-layer settings loading via `pydantic-settings` (TOML > Environment variables > Defaults > Secrets). | [Settings](./settings.md) |
| Dependency Injection | `AbstractComponent` / `AbstractService` abstractions, seamless integration with `Depends`, singleton + `ContextVar` context propagation, lifecycle hooks. | [Dependency Injection](./dependency.md) |
| Database ORM | SQLModel-based `SQLBase` (Snowflake PK + optimistic lock + soft-delete + timestamps); async `SessionFactory`; generic `ModelService[T]` CRUD; `.sql` template mapping via `@Mapped`. | [Database Layer](./database.md) |
| Cache | Async Redis connection pool with ready-to-use `RedisCli` dependency. | [Cache Integration](./cache.md) |
| Task Scheduling | APScheduler-backed `TaskRunner` with decorator-based job registration. Job functions enjoy **full FastAPI dependency injection** support. | [Task Runner](./taskrunner.md) |
| Unified Response | Aliyun-style `ResultEnum` (120+ predefined codes) + generic `APIResult[T]` + `APIResponse` + `APIError` exception. | [Unified Response & Error Codes](./response.md) |
| Query Models | `Page[T]` pagination envelope, `DataRange[T]` range filter, `ColumnExpression` / `WhereClause` dynamic conditions. | [Form & Query Models](./form.md) |

---

## Table of Contents

1. **[Getting Started](./getting-started.md)** — Installation, minimal working example, `setup()` in lifespan.
2. **[Settings / Configuration](./settings.md)** — TOML files, environment variable overrides, `mode=prod` validation.
3. **[Dependency Injection](./dependency.md)** — `AbstractComponent`, `AbstractService`, install / setup / dispose.
4. **[Database Layer](./database.md)** — Model base classes, Session, CRUD Service, `.sql` template mapping.
5. **[Cache Integration](./cache.md)** — `RedisPool`, `RedisCli` dependency.
6. **[Unified Response & Error Codes](./response.md)** — `APIResult`, `APIError`, `ResultEnum`.
7. **[Form & Query Models](./form.md)** — `Page` / `WhereClause` / `DataRange` / `ColumnExpression`.
8. **[Task Runner](./taskrunner.md)** — `add_job` / `@scheduled_job`, dependency-aware scheduled functions.

---

## Tech Stack

- **Python** >= 3.12
- **FastAPI** >= 0.141.0
- **SQLModel** >= 0.0.39
- **Pydantic Settings** >= 2.15.0
- **Optional extras**:
  - `redis` (`pip install fastapi-extra[redis]`)
  - `apscheduler` (`pip install fastapi-extra[scheduler]`)
  - `asyncmy` / `aiomysql` (MySQL async drivers)
  - `asyncpg` (PostgreSQL async driver)
  - `oracledb` (Oracle async driver)

---

## Project Structure

```
fastapi_extra/
├── __init__.py           # `setup()` entry; patches FastAPI internals
├── _patch.py             # FastAPI internals (param parsing / router match / QueryParams)
├── dependency.py         # DI metaclass; AbstractComponent / AbstractService
├── settings.py           # Multi-layer Settings (TOML + env)
├── types.py              # Generic TypeVars, type aliases (Cursor, LocalDateTime, …)
├── response.py           # APIResult / APIResponse / ResultEnum / APIError
├── form.py               # Page / WhereClause / DataRange / ColumnExpression
├── taskrunner.py         # APScheduler-backed async task runner
├── utils.py              # Machine seed for Snowflake ID
├── database/
│   ├── __init__.py       # Public exports: Session / SQLBase / ModelService
│   ├── model.py          # AutoPK / LocalPK / Versioned / Deleted / Optime / SQLBase
│   ├── session.py        # SessionFactory, get_session Depends, DefaultSession
│   ├── service.py        # Generic ModelService[T] CRUD
│   └── sqlmap.py         # @Mapped annotation + .sql template mapping
└── cache/
    ├── __init__.py
    └── redis.py          # RedisPool / RedisCli (optional extra)
```
