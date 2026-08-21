
import asyncio
from contextlib import asynccontextmanager
from typing import Any, MutableMapping

from fastapi import APIRouter, FastAPI
from pyinstrument import Profiler

import fastapi_extra
from fastapi_extra.response import APIResult


@asynccontextmanager
async def lifespan(app: FastAPI):
    fastapi_extra.setup(app)
    yield


app = FastAPI(lifespan=lifespan)
routers = [APIRouter(prefix=f"/test{i}") for i in range(100)]
for router in routers:
    app.include_router(router)


@router.get("/{num:int}")
async def read_fastapi(num: int, a: int, b: int) -> APIResult[dict]:
    # 模拟一个路由处理
    return APIResult.ok({"data": num, "a": a, "b": b})


async def mock_receive() -> dict[str, Any]:
    return {}

async def mock_send(message: MutableMapping[str, Any]) -> None:
    return None


async def main():
    # 测试路由
    scope = {
        "type": "http",
        "method": "GET",
        "app": app,
        "router": app.router,
        "query_string": b"a=123&b=456",
        "headers": [(b"host", b"localhost")],
    }
    p = Profiler(async_mode='disabled')
    await app(scope | {"path": "/test99/0"}, mock_receive, mock_send)
    with p:
        async with app.router.lifespan_context(app):
            await asyncio.gather(*(app(scope | {"path": f"/test99/{i}"}, mock_receive, mock_send) for i in range(10000)))
        # async with litestar_app.lifespan():
        #     await asyncio.gather(*(litestar_app(scope | {"path": f"/test/{i}"}, mock_receive, mock_send) for i in range(10000)))
    p.print()
    

asyncio.run(main())
