# Task Runner

Many systems need delayed, periodic or scheduled tasks: daily reports, data cleanup, cache warm-up, order timeout cancellation, etc. `fastapi_extra` wraps `APScheduler AsyncIOScheduler` into a `TaskRunner`. Its key differentiator from hand-written APScheduler code: **scheduled functions enjoy the full FastAPI `Depends` dependency graph** (you can inject `DefaultSession`, `RedisCli`, `ModelService<T>`, etc. exactly as if you were writing a route handler).

> This module is an **optional extra** — run `pip install fastapi-extra[scheduler]`. Otherwise `TaskRunner.__init__` raises `AssertionError`.

---

## 1. Quick setup

### 1.1 Install and start inside lifespan

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi_extra.taskrunner import DefaultTaskRunner
import fastapi_extra

@asynccontextmanager
async def lifespan(app: FastAPI):
    fastapi_extra.setup(app)

    # Install: set the app reference so solve_dependencies can resolve app.state items
    DefaultTaskRunner.install(app)

    # Start APScheduler (non-blocking; all jobs share the same event loop)
    DefaultTaskRunner.start()

    yield

    # (Optional) graceful shutdown:
    # DefaultTaskRunner._scheduler.shutdown(wait=False)
```

### 1.2 Register jobs with the decorator

`@scheduled_job(trigger, **kwargs)` is syntactic sugar for `add_job`. All APScheduler trigger forms are supported.

Common `trigger` values:

| Trigger | Example | Notes |
|---------|---------|-------|
| `"interval"` | `seconds=30` / `minutes=10` / `hours=1` | Run every N seconds/minutes/hours. |
| `"cron"`     | `hour=3, minute=0` / `day_of_week="mon-fri", hour=9` | Cron-style scheduling. |
| `"date"`     | `run_date=datetime(...)` | One-shot delayed execution. |

```python
from fastapi_extra.taskrunner import DefaultTaskRunner
from datetime import datetime

# Run every 5 minutes
@DefaultTaskRunner.scheduled_job("interval", minutes=5)
async def heartbeat():
    print(f"heartbeat @ {datetime.now()}")

# Daily at 03:00
@DefaultTaskRunner.scheduled_job("cron", hour=3, minute=0)
async def daily_report():
    print("generating daily report...")
```

---

## 2. Dependency injection inside job functions

This is where `TaskRunner` differs the most from raw APScheduler. Job function signatures can declare any FastAPI-resolvable dependency:

```python
from fastapi_extra.database import DefaultSession
from fastapi_extra.cache import RedisCli
from sqlmodel import select
from app.models import Order
from app.services import OrderService

@DefaultTaskRunner.scheduled_job("cron", hour=2, minute=30)
async def cancel_timeout_orders(
    session: DefaultSession,   # AsyncSession (auto-committed / returned)
    redis:   RedisCli,         # Redis client
    service: OrderService,     # custom ModelService
):
    stmt = select(Order).where(Order.status == "UNPAID")
    rows = (await session.exec(stmt)).all()
    for order in rows:
        await service.update_model(order, status="CANCELLED")
        await redis.delete(f"order:lock:{order.id}")
```

How it works: when a job fires, `TaskRunner` constructs a minimal synthetic `Request(scope)` and invokes FastAPI's native `solve_dependencies`. This reproduces the exact dependency graph / exception handling / context propagation used during HTTP requests. `_is_coroutine_callable` automatically tells sync from async callables; sync jobs are run via `run_in_threadpool`.

---

## 3. Programmatic registration (dynamic jobs)

Decorators only work at import time. For jobs loaded from a database or configuration, use `add_job(callable, trigger, **kwargs)`:

```python
def start_task(order_id: int, delay_seconds: int = 1800):
    async def timeout_checker(session: DefaultSession, svc: OrderService):
        order = await svc.get(order_id)
        if order and order.status == "UNPAID":
            await svc.update_model(order, status="CANCELLED")

    DefaultTaskRunner.add_job(
        timeout_checker,
        trigger="date",
        run_date=datetime.utcnow() + timedelta(seconds=delay_seconds),
        id=f"order-timeout-{order_id}",   # APScheduler id, used for remove/pause/resume
    )
```

> Native APScheduler methods (`remove_job`, `pause_job`, `resume_job`, `modify_job`) are all available via `DefaultTaskRunner._scheduler`.

---

## 4. Caveats

### 4.1 Multi-worker deployments (gunicorn / uvicorn --workers N)

APScheduler's default jobstore is in-memory. If you run N worker processes, each one gets its own scheduler:
- Cron jobs run N times instead of once.
- Dynamically registered `add_job` tasks only live on the worker that registered them.

Choose one of:
1. **Dedicated scheduler process** (recommended): launch a separate `scheduler.py` process / container. Do not start TaskRunner inside web workers.
2. **Persistent JobStore** (Redis is typical) plus distributed lock semantics:
   ```python
   from apscheduler.jobstores.redis import RedisJobStore
   DefaultTaskRunner._scheduler.add_jobstore(
       RedisJobStore(host="...", port=6379, db=1), alias="redis"
   )
   ```
   Tune `misfire_grace_time`, `coalesce`, and `max_instances` to avoid duplicate firings.

### 4.2 Long-running tasks & exceptions

- Any exception raised inside a job won't crash the scheduler, but the error is otherwise silent. We recommend:
  ```python
  import logging
  logger = logging.getLogger(__name__)

  async def my_job():
      try:
          ...
      except Exception:
          logger.exception("job failed")  # preserve full traceback
  ```
- APScheduler's `misfire_grace_time` (default 1 second) controls how late a missed trigger can still be executed. For long tasks set it explicitly, e.g. `@scheduled_job("cron", hour=3, misfire_grace_time=3600)`.

### 4.3 Synthetic `scope` lacks HTTP details

TaskRunner resolves dependencies against a synthetic `scope = {"type": "http", "query_string": b"", "headers": []}`. Real path / method / headers / client info are not populated. Any dependency reading `Request.url`, `Request.headers`, `Header(...)`, `Query(...)` will see empty / default values. Avoid HTTP-request-level inputs inside scheduled jobs.

---

## 5. Typical scenarios

### 5.1 Daily digest (cron)

```python
@DefaultTaskRunner.scheduled_job("cron", hour=8, minute=0)
async def send_daily_report(
    svc: OrderService,
    redis: RedisCli,
):
    rows = await svc.get_list()
    html = render_template("report.html", rows=rows)
    await send_email("ops@example.com", "Yesterday's orders report", html)
    await redis.incr("stats:reports_sent")
```

### 5.2 Delayed cancellation (date)

See the dynamic `start_task(order_id)` example above for the order-timeout pattern.

### 5.3 Cache warm-up (interval)

```python
@DefaultTaskRunner.scheduled_job("interval", minutes=10)
async def warm_hot_products_cache(
    redis: RedisCli,
    svc:   ProductService,
):
    top = await svc.get_top_sales(limit=100)
    await redis.setex(
        "cache:hot_products",
        15 * 60,           # 15 minutes
        json.dumps([p.model_dump() for p in top]),
    )
```
