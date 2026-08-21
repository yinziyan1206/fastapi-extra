# 任务调度（TaskRunner）

许多业务需要异步 / 延迟 / 定时执行的任务：每日报表、数据清理、缓存预热、订单超时取消等。`fastapi_extra` 基于 `APScheduler AsyncIOScheduler` 封装了 `TaskRunner`，其最大特点是：**任务函数可以直接使用 FastAPI 的 `Depends` 依赖注入体系**（包括 `DefaultSession`、`RedisCli`、`ModelService` 等），仿佛就是在写一个路由。

> 本模块为**可选依赖**：需要 `pip install fastapi-extra[scheduler]`，否则 `TaskRunner.__init__` 抛出 `AssertionError`。

---

## 1. 快速上手

### 1.1 生命周期里安装并启动

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi_extra.taskrunner import DefaultTaskRunner
import fastapi_extra

@asynccontextmanager
async def lifespan(app: FastAPI):
    fastapi_extra.setup(app)

    # 安装：把 app 写入 TaskRunner.scope，以便任务函数 solve_dependencies 时能访问 app.state
    DefaultTaskRunner.install(app)

    # 启动 APScheduler（非阻塞，所有 job 注册在同一 event loop 下）
    DefaultTaskRunner.start()

    yield

    # APScheduler 不会强制挂起请求；如需优雅关闭，可在此处补充：
    # DefaultTaskRunner._scheduler.shutdown(wait=False)
```

### 1.2 装饰式注册 Job

`@scheduled_job(trigger, **kwargs)` 是装饰器语法糖，参数完全兼容 APScheduler `add_job`。

常见 `trigger`：

| Trigger | 示例 | 说明 |
|---------|------|------|
| `"interval"` | `seconds=30` / `minutes=10` / `hours=1` | 固定间隔执行。 |
| `"cron"`     | `hour=3, minute=0` / `day_of_week="mon-fri", hour=9` | Cron 风格。 |
| `"date"`     | `run_date=datetime(...)` | 一次性延时执行。 |

```python
from fastapi_extra.taskrunner import DefaultTaskRunner as runner
from datetime import datetime


# 每 5 分钟跑一次
@runner.scheduled_job("interval", minutes=5)
async def heartbeat():
    print(f"heartbeat @ {datetime.now()}")

# 每天凌晨 3 点
@runner.scheduled_job("cron", hour=3, minute=0)
async def daily_report():
    print("generating daily report...")
```

---

## 2. 任务函数中的依赖注入

这是 `TaskRunner` 与手写 `APScheduler` 最大的不同。任务函数签名里可以写任何 FastAPI 可解析的依赖：

```python
from fastapi_extra.database import DefaultSession
from fastapi_extra.cache import RedisCli
from sqlmodel import select
from app.models import Order
from app.services import OrderService

@runner.scheduled_job("cron", hour=2, minute=30)
async def cancel_timeout_orders(
    session: DefaultSession,   # AsyncSession（会自动 commit / 归还）
    redis:   RedisCli,         # Redis 客户端
    service: OrderService,     # 自定义 ModelService
):
    # 查询 30 分钟前未支付的订单
    stmt = select(Order).where(Order.status == "UNPAID")
    rows = (await session.exec(stmt)).all()
    for order in rows:
        await service.update_model(order, status="CANCELLED")
        await redis.delete(f"order:lock:{order.id}")
```

实现原理：执行 Job 时，`TaskRunner` 会构造一个最小的 `Request(scope)`，并在内部调用 FastAPI 原生的 `solve_dependencies`，因此和路由侧一模一样的依赖图、异常、上下文都会被正确建立。`_is_coroutine_callable` 自动判断异步 / 同步，同步函数将走 `run_in_threadpool`。

---

## 3. 编程式注册（动态任务）

装饰器只能在模块加载时静态注册。如果任务来自数据库 / 配置动态加载，使用 `add_job(callable, trigger, **kwargs)`：

```python
def start_task(order_id: int, delay_seconds: int = 1800):
    async def timeout_checker(session: DefaultSession, svc: OrderService):
        order = await svc.get(order_id)
        if order and order.status == "UNPAID":
            await svc.update_model(order, status="CANCELLED")

    runner.add_job(
        timeout_checker,
        trigger="date",
        run_date=datetime.utcnow() + timedelta(seconds=delay_seconds),
        id=f"order-timeout-{order_id}",   # APScheduler id，便于后续 remove / pause
    )
```

> APScheduler 原生能力：`_scheduler.remove_job(id)` / `pause_job` / `resume_job` / `modify_job` 等；可通过 `DefaultTaskRunner._scheduler` 调用。

---

## 4. 注意事项

### 4.1 与多 worker（gunicorn / uvicorn --workers N）

APScheduler 的 Job 存储默认是**内存级**。如果你起了多个 worker 进程，每个进程都有自己的调度器副本，会导致：
- 同一个 cron Job 被执行 N 次；
- `add_job` 动态注册的任务只对当前 worker 生效。

解决方案（任选其一）：
1. **任务独立部署**：起一个单独的 `scheduler.py` 进程（或容器）专门跑调度，不要在 Web worker 里启动 TaskRunner；
2. **使用持久化 JobStore**（推荐 Redis），并启用分布式锁：
   ```python
   from apscheduler.jobstores.redis import RedisJobStore
   runner._scheduler.add_jobstore(
       RedisJobStore(host="...", port=6379, db=1), alias="redis"
   )
   ```
   并配合 `misfire_grace_time`、`coalesce`、`max_instances` 参数避免重复触发。

### 4.2 长任务 & 异常

- 任务内任何异常不会影响调度器运行，但会丢失上下文。建议：
  ```python
  import logging
  logger = logging.getLogger(__name__)

  async def my_job():
      try:
          ...
      except Exception:
          logger.exception("job failed")  # 把堆栈打出来，便于排查
  ```
- APScheduler 的 `misfire_grace_time`（默认 1s）决定了「任务错过调度窗口多少秒内仍补执行」。长任务建议显式设置 `@scheduled_job("cron", hour=3, misfire_grace_time=3600)`。

### 4.3 Scope 不完整

TaskRunner 在解决依赖时使用的是 `scope = {"type": "http", "query_string": b"", "headers": []}`，**没有真实的 path / method / headers / client 信息**。因此如果依赖里读 `Request.url`、`Request.headers`、`Header(...)`、`Query(...)` 这类请求相关内容，其行为是空的或默认值。业务 Job 里不要依赖 HTTP 请求级信息。

---

## 5. 典型场景

### 5.1 报表推送（cron）

```python
@runner.scheduled_job("cron", hour=8, minute=0)
async def send_daily_report(
    svc: OrderService,
    redis: RedisCli,
):
    rows = await svc.get_list()
    html = render_template("report.html", rows=rows)
    await send_email("ops@example.com", "昨日订单报表", html)
    await redis.incr("stats:reports_sent")
```

### 5.2 延迟关闭（date）

见「编程式注册」示例（订单超时取消）。

### 5.3 缓存预热（interval）

```python
@runner.scheduled_job("interval", minutes=10)
async def warm_hot_products_cache(
    redis: RedisCli,
    svc:   ProductService,
):
    top = await svc.get_top_sales(limit=100)
    await redis.setex(
        "cache:hot_products",
        15 * 60,           # 15 min
        json.dumps([p.model_dump() for p in top]),
    )
```
