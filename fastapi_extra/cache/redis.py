__author__ = "ziyan.yin"
__date__ = "2025-01-17"


from typing import Annotated, AsyncGenerator, Self

from fastapi.params import Depends
from pydantic import BaseModel, Field, RedisDsn
from redis.asyncio import ConnectionPool, Redis

from fastapi_extra.dependency import AbstractComponent
from fastapi_extra.settings import Settings


class RedisConfig(BaseModel):
    url: RedisDsn = RedisDsn("redis://localhost:6379/0")
    max_connections: int | None = None
    connection_kwargs: dict = Field(default_factory=dict)


class DefaultRedisSettings(Settings):
    redis: RedisConfig


_settings = DefaultRedisSettings()  # type: ignore


class RedisPool(AbstractComponent):
    default_config = _settings.redis

    def __init__(self):
        self._pool: ConnectionPool | None = None

    @classmethod
    def setup(cls, **options) -> Self:
        redis = cls()
        redis._pool = ConnectionPool.from_url(
            str(cls.default_config.url),
            **cls.default_config.model_dump(
                exclude_defaults=True, exclude={"url", "connection_kwargs"}
            ),
            **cls.default_config.connection_kwargs,
            **options,
        )
        return redis

    def get_client(self) -> Redis:
        return Redis(connection_pool=self._pool)

    async def dispose(self) -> None:
        if self._pool:
            await self._pool.aclose()


async def get_redis(pool: RedisPool) -> AsyncGenerator[Redis, None]:
    async with pool.get_client() as client:
        yield client


RedisCli = Annotated[Redis, Depends(get_redis)]
