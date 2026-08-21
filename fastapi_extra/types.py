__author__ = "ziyan.yin"
__date__ = "2024-12-25"


import datetime
import decimal
from typing import Annotated, Any, ParamSpec, TypeVar, Union

from pydantic import BaseModel, PlainSerializer
from sqlmodel import SQLModel

Comparable = Union[
    int, float, decimal.Decimal, datetime.datetime, datetime.date, datetime.time
]
Serializable = Union[Comparable, bool, str, None]


T = TypeVar("T", bound=Any)
E = TypeVar("E", bound=Exception)
C = TypeVar("C", bound=Comparable)
S = TypeVar("S", bound=Serializable)
P = ParamSpec("P")
Schema = TypeVar("Schema", bound=BaseModel)
Model = TypeVar("Model", bound=SQLModel)
NoneType = type(None)

Cursor = Annotated[int, PlainSerializer(lambda x: str(x), return_type=str)]
LocalDateTime = Annotated[
    datetime.datetime,
    PlainSerializer(lambda x: x.strftime("%Y-%m-%d %H:%M:%S"), return_type=str),
]
