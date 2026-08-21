__author__ = "ziyan.yin"
__date__ = "2024-12-25"


import datetime

from pydantic import ConfigDict
from sqlalchemy import BigInteger, DateTime, Integer, SmallInteger, func
from sqlalchemy.ext.declarative import declared_attr
from sqlmodel import Field, SQLModel
from typing_extensions import Unpack

from fastapi_extra.cursor import Cursor as _Cursor  # type: ignore
from fastapi_extra.types import Cursor, LocalDateTime
from fastapi_extra.utils import get_machine_seed


class AutoPK(SQLModel):
    id: int = Field(
        default=None,
        title="ID",
        primary_key=True,
        sa_type=BigInteger,
        sa_column_kwargs={"autoincrement": True},
        schema_extra={"json_schema_extra": {"readOnly": True}},
    )
    
    def __init_subclass__(cls, **kwargs: Unpack[ConfigDict]):
        cls.model_fields["id"].default_factory = None
        return super().__init_subclass__(**kwargs)


class LocalPK(SQLModel):
    id: Cursor = Field(
        default_factory=lambda: None,
        title="ID",
        primary_key=True,
        sa_type=BigInteger,
        sa_column_kwargs={"autoincrement": False},
        schema_extra={"json_schema_extra": {"readOnly": True}},
    )
    
    def __init_subclass__(cls, **kwargs: Unpack[ConfigDict]):
        if cls.model_fields["id"].default_factory is not None:
            cls.model_fields["id"].default_factory = _Cursor(get_machine_seed()).next_val
        return super().__init_subclass__(**kwargs)


class Deleted(SQLModel):
    deleted: int = Field(
        default=0,
        title="DELETED",
        sa_type=SmallInteger,
        sa_column_kwargs={"nullable": False, "comment": "DELETED"},
        schema_extra={"json_schema_extra": {"readOnly": True}},
    )


class Versioned(SQLModel):
    version_id: int = Field(
        default=0,
        title="VERSION_ID",
        sa_type=Integer,
        sa_column_kwargs={"nullable": False, "comment": "VERSION_ID"},
        schema_extra={"json_schema_extra": {"readOnly": True}},
    )

    @declared_attr  # type: ignore
    def __mapper_args__(cls) -> dict:
        return {"version_id_col": cls.version_id}


class Optime(SQLModel):
    create_at: LocalDateTime = Field(
        default_factory=datetime.datetime.now,
        title="CREATE_AT",
        sa_type=DateTime,
        sa_column_kwargs={
            "default": func.now(),
            "nullable": False,
            "comment": "CREATE_AT",
        },
        schema_extra={"json_schema_extra": {"readOnly": True}},
    )
    update_at: LocalDateTime = Field(
        default_factory=datetime.datetime.now,
        title="UPDATE_AT",
        sa_type=DateTime,
        sa_column_kwargs={
            "default": func.now(),
            "onupdate": func.now(),
            "nullable": False,
            "comment": "UPDATE_AT",
        },
        schema_extra={"json_schema_extra": {"readOnly": True}},
    )


class SQLBase(LocalPK, Versioned, Deleted, Optime):
    pass
