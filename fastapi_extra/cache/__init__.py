__author__ = "ziyan.yin"
__date__ = "2025-01-10"

try:
    from .redis import RedisCli, RedisPool
except ImportError:
    RedisPool = None
    RedisCli = None

__all__ = ["RedisPool", "RedisCli"]
