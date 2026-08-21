__author__ = "ziyan.yin"
__date__ = "2025-01-05"

from abc import ABCMeta
from contextvars import ContextVar
from functools import update_wrapper
from typing import Annotated, Any, Callable, ClassVar, Self, final

from fastapi import Depends, FastAPI, Request


def async_wrapper(func: Callable):

    async def func_wrapper(*args, **kwds):
        return func(*args, **kwds)

    return update_wrapper(func_wrapper, func)


class DependencyMetaClass(ABCMeta):
    __load__ = None
    __token__ = None

    def __new__(
        mcs, name: str, bases: tuple[type, ...], attrs: dict, abstract: bool = False
    ):
        new_cls = super().__new__(mcs, name, bases, attrs)
        new_cls.__token__ = f"{new_cls.__module__}.{new_cls.__name__}"
        if not abstract:
            if not new_cls.__load__:
                return Annotated[new_cls, Depends(async_wrapper(new_cls))]
            return Annotated[new_cls, Depends(new_cls.__load__)]
        return new_cls


class AbstractComponent(metaclass=DependencyMetaClass, abstract=True):
    __slot__ = ()
    __token__: ClassVar[str]

    @classmethod
    def setup(cls, *args: Any, **kwargs: Any) -> Self:
        raise NotImplementedError

    @final
    @classmethod
    def install(cls, app: FastAPI, *args: Any, **kwargs: Any) -> Self:
        component = cls.setup(*args, **kwargs)
        setattr(app.state, cls.__token__, component)
        return component

    @final
    @classmethod
    async def __load__(cls, request: Request) -> Self:
        assert hasattr(
            request.app.state, cls.__token__
        ), f"{cls.__name__} must be installed in lifespan"
        return getattr(request.app.state, cls.__token__)

    async def dispose(self) -> None:
        pass


class AbstractService(metaclass=DependencyMetaClass, abstract=True):
    __slot__ = ()
    __load__ = None
    __instance__ = None
    __token__: ClassVar[str]
    __container__ = ContextVar[dict[str, Any] | None](
        "__container__", default=None
    )

    @final
    def __new__(cls, *args, **kwargs) -> Self:
        if cls.__instance__ is None:
            cls.__instance__ = super().__new__(cls)
        return cls.__instance__

    def __init__(self, **kwargs: Any):
        self.__container__.set(kwargs)
    
    @final
    def get_context(self, name: str) -> Any:
        context = self.__container__.get()
        assert context is not None, "service must be initialized by super().__init__()"
        return context[name]
