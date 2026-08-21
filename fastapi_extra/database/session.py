__author__ = "ziyan.yin"
__date__ = "2024-12-26"

from typing import Annotated, AsyncGenerator, Literal, Self

from fastapi.params import Depends
from pydantic import AnyUrl, BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from fastapi_extra.dependency import AbstractComponent
from fastapi_extra.settings import Settings


class DatabaseConfig(BaseModel):
    url: AnyUrl
    echo: bool = False
    echo_pool: bool = False
    isolation_level: (
        Literal[
            "SERIALIZABLE",
            "REPEATABLE READ",
            "READ COMMITTED",
            "READ UNCOMMITTED",
            "AUTOCOMMIT",
        ]
        | None
    ) = None
    options: dict = Field(default_factory=dict)


class DefaultDatabaseSettings(Settings):
    datasource: DatabaseConfig


_settings = DefaultDatabaseSettings()  # type: ignore


class SessionFactory(AbstractComponent):
    __slot__ = ("_engine",)
    default_config = _settings.datasource

    def __init__(self):
        self._engine: AsyncEngine | None = None

    @classmethod
    def setup(cls, **options) -> Self:
        db = cls()
        db._engine = create_async_engine(
            url=str(cls.default_config.url),
            **cls.default_config.model_dump(
                exclude_defaults=True, exclude={"url", "options"}
            ),
            **cls.default_config.options,
            **options,
        )
        return db

    def create_session(self) -> AsyncSession:
        return AsyncSession(self._engine)

    async def dispose(self) -> None:
        if self._engine:
            await self._engine.dispose()


async def get_session(factory: SessionFactory) -> AsyncGenerator[AsyncSession, None]:
    async with factory.create_session() as session:
        yield session
        await session.commit()


DefaultSession = Annotated[AsyncSession, Depends(get_session)]
