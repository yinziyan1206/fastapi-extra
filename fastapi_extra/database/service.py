__author__ = "ziyan.yin"
__date__ = "2025-01-12"


from typing import Any, Generic, Sequence, TypeVar

from sqlalchemy import ColumnExpressionArgument
from sqlmodel import col, insert, select

from fastapi_extra.database.model import SQLModel
from fastapi_extra.database.session import AsyncSession, DefaultSession
from fastapi_extra.dependency import AbstractService

Model = TypeVar("Model", bound=SQLModel)
ID = int | str
PK = ID | tuple[ID] | dict[str, ID]


class ModelService(AbstractService, Generic[Model], abstract=True):
    __slot__ = ()
    __model__: type[Model]

    @classmethod
    def __class_getitem__(cls, item: type[SQLModel]) -> type["ModelService"]:
        if not issubclass(item, SQLModel):
            raise TypeError(f"type[SQLModel] expected, got {item}")
        if not (table_arg := item.model_config.get("table", None)):
            raise AttributeError(
                f"True expected for argument {item.__name__}.model_config.table, got {table_arg}"
            )

        class SubService(ModelService):
            __slot__ = ()
            __model__ = item

        return SubService

    def __init__(self, session: DefaultSession):
        super().__init__(session=session)

    @property
    def session(self) -> AsyncSession:
        _session = self.get_context("session")
        assert _session is not None, "Session is not initialized"
        return _session

    async def get(self, ident: PK, **kwargs: Any) -> Model | None:
        return await self.session.get(self.__model__, ident, **kwargs)

    async def get_list(
        self, *clause: ColumnExpressionArgument[bool] | bool
    ) -> Sequence[Model]:
        return (await self.session.exec(select(self.__model__).where(*clause))).all()

    async def create_model(self, **kwargs: Any) -> Model:
        model = self.__model__.model_validate(kwargs)
        self.session.add(model)
        await self.session.flush()
        return model

    async def create_batch(self, values: Sequence[dict]) -> Sequence[Model]:
        stmt = insert(self.__model__).returning(self.__model__)
        data_to_insert = [
            self.__model__.model_validate(value).model_dump() for value in values
        ]
        results = await self.session.scalars(stmt, params=data_to_insert)
        return results.all()

    async def create_batch_with_pk(
        self, values: Sequence[dict], _pk_name: str = "id"
    ) -> Sequence[Model]:
        stmt = insert(self.__model__)
        data_to_insert = [
            self.__model__.model_validate(value).model_dump() for value in values
        ]
        pk_set = tuple(data[_pk_name] for data in data_to_insert)
        await self.session.exec(stmt, params=data_to_insert)
        results = []
        if pk_set:
            for i in range(0, len(pk_set), 1000):
                results.extend(
                    await self.get_list(
                        col(getattr(self.__model__, _pk_name)).in_(pk_set[i : i + 1000])
                    )
                )
        return results

    async def update_model(
        self, model: Model, _ignore_none: bool = True, **kwargs: Any
    ) -> Model:
        for key, value in kwargs.items():
            if key not in model.__pydantic_fields__:
                continue
            if _ignore_none and value is None:
                continue
            setattr(model, key, value)
        await self.session.flush()
        return model

    async def delete(self, model: Model) -> None:
        return await self.session.delete(model)
