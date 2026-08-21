**FastAPI Extension Suite**

---

### Project Overview

**fastapi_extra** is a feature-rich enhancement extension library for FastAPI (Python >= 3.12, BSD-3-Clause license) designed to provide an out-of-the-box, enterprise-grade framework on top of FastAPI.

---

### Key Features

* **Performance Optimization** — Uses monkey-patching on FastAPI's internal argument parsing and router matching logic with built-in caching; includes Cython-native implementations for Snowflake ID generation and high-speed URL parsing.
* **Complete ORM Layer** — Built on top of SQLModel (SQLAlchemy + Pydantic) with a `SQLBase` base class that incorporates Snowflake IDs, optimistic locking (versioning), soft deletes, and automatic timestamps.
* **Unified API Responses** — Features an Alibaba Cloud-style `ResultEnum` (120+ pre-defined status codes) and generic `APIResult[T]` response models for standardized API outputs.
* **SQL Template Engine** — Supports external `.sql` files with an `@Mapped` decorator for annotation-driven query execution (`execute`, `fetch_all`, `fetch_one`).
* **Dependency Injection Architecture** — Provides `AbstractComponent` and `AbstractService` abstractions with singleton management and `ContextVar` context passing, seamlessly integrating with FastAPI's `Depends`.
* **Redis Cache Integration** — Async connection pool management with ready-to-use Redis dependency injection.
* **Scheduled Tasks** — Integrated async task runner built on APScheduler, supporting decorator-based job registration with full dependency injection support inside task functions.
* **TOML-Driven Configuration** — Multi-layered settings loading (TOML > Env > Defaults > Secrets) powered by `pydantic-settings`.

---

### Tech Stack

* **Python** >= 3.12
* **FastAPI** >= 0.141.0
* **SQLModel** >= 0.0.39
* **Pydantic Settings** >= 2.15.0
* **Cython** (for performance-critical modules)

---

### Target Use Case

Ideal for building high-performance RESTful API services in enterprise environments, offering a complete end-to-end toolkit covering database connection pooling, ORM operations, caching, scheduled jobs, and standardized API responses.