__author__ = "ziyan.yin"
__date__ = "2026-07-17"


import logging
from contextlib import AsyncExitStack
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.dependencies.models import _is_coroutine_callable
from fastapi.dependencies.utils import get_dependant, solve_dependencies
from fastapi.exceptions import ValidationException
from starlette.types import Scope

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
except ImportError:  # pragma: nocover
    AsyncIOScheduler = None


logger = logging.getLogger(__name__)


class TaskRunner:
    __slot__ = (
        "_scheduler",
        "_is_running",
    )
    scope: Scope = {"type": "http", "query_string": b"", "headers": []}

    def __init__(self):
        assert (
            AsyncIOScheduler is not None
        ), "apscheduler.schedulers.asyncio.AsyncIOScheduler is not installed"
        self._scheduler = AsyncIOScheduler()
        self._is_running = False

    @classmethod
    def install(cls, app: FastAPI):
        cls.scope["app"] = app

    def add_job(self, call: Callable, trigger=None, **kwargs):
        dependant = get_dependant(path="_background", call=call)
        assert dependant.call is not None, "dependant.call must be a function"
        is_coroutine = _is_coroutine_callable(dependant.call)

        async def runner():
            request = Request(dict(self.scope))
            async with AsyncExitStack() as runner_stack:
                async with AsyncExitStack() as function_stack:
                    request.scope["fastapi_function_astack"] = function_stack
                    async_exit_stack = request.scope["fastapi_inner_astack"] = (
                        runner_stack
                    )
                    solved_result = await solve_dependencies(
                        request=request,
                        dependant=dependant,
                        body=None,
                        dependency_overrides_provider=None,
                        async_exit_stack=async_exit_stack,
                        embed_body_fields=False,
                    )
                    errors = solved_result.errors
                    if errors:
                        raise ValidationException(errors)
                    if not dependant.call:
                        return
                    if is_coroutine:
                        await dependant.call(**solved_result.values)
                    else:
                        await run_in_threadpool(dependant.call, **solved_result.values)

        self._scheduler.add_job(runner, trigger, **kwargs)

    def scheduled_job(self, trigger, **kwargs):
        def inner(func):
            self.add_job(func, trigger, **kwargs)
            return func

        return inner

    def start(self):
        self._scheduler.start()
        self._is_running = True
        logger.info("[TaskRunner] started")


DefaultTaskRunner = TaskRunner()
