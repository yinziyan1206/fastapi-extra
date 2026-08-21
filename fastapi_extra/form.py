__author__ = "ziyan.yin"
__date__ = "2024-12-24"


from typing import Generic, Literal

from pydantic import BaseModel, Field, model_validator

from fastapi_extra.types import C, S, Schema


class DataRange(BaseModel, Generic[C]):
    start: C | None = Field(default=None, title="from")
    end: C | None = Field(default=None, title="to")


class ColumnExpression(BaseModel, Generic[S]):
    column_name: str = Field(title="column")
    option: Literal["eq", "ne", "gt", "lt", "ge", "le"] = Field(
        default="eq", title="operator"
    )
    value: S = Field(title="value")

    @model_validator(mode="after")  # type: ignore
    def validate_value(self):
        if self.value is None and self.option not in ("eq", "ne"):
            raise ValueError("NoneType is not comparable")


class WhereClause(BaseModel):
    option: Literal["and", "or"] = Field(default="and", title="operator")
    column_clauses: list["ColumnExpression | WhereClause"]


class Page(BaseModel, Generic[Schema]):
    items: list[Schema] = Field(default_factory=list, title="items")
    total: int = Field(default=0, title="total")
    page_num: int = Field(default=0, title="page_num")
    page_size: int = Field(default=0, title="page_size")
