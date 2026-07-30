"""Async Redis client singleton backed by a connection pool.

The client gracefully degrades when Redis is unavailable: all public methods
return ``None`` (or an empty container) instead of raising connection errors,
so that caching never blocks the main application flow.
"""
from __future__ import annotations

import logging
from typing import Any

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_KEY_PREFIX = "rag_kb:"


class RedisClient:
    """Singleton async Redis client with graceful failure handling."""

    _instance: RedisClient | None = None

    def __new__(cls, *, prefix: str = DEFAULT_KEY_PREFIX) -> RedisClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance._prefix = prefix
            cls._instance._redis = None
        return cls._instance

    async def _init(self) -> None:
        if self._initialized:
            return
        try:
            self._pool = ConnectionPool.from_url(
                settings.redis_url,
                max_connections=50,
                decode_responses=True,
            )
            self._redis = Redis(connection_pool=self._pool)
            self._initialized = True
        except RedisError as exc:
            logger.warning("Redis connection pool creation failed: %s", exc)
            self._redis = None
            self._initialized = True

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def _safe(self, coro_factory):
        """Wrap a coroutine factory so Redis errors return None instead of raising.

        ``coro_factory`` is called *after* ``_init`` has run, so ``self._redis``
        is guaranteed to be either a ``Redis`` instance or ``None``.
        """

        async def wrapper(*args, **kwargs):
            await self._init()
            if self._redis is None:
                return None
            try:
                return await coro_factory(*args, **kwargs)
            except RedisError as exc:
                logger.warning("Redis operation failed: %s", exc)
                return None

        return wrapper

    # ------------------------------------------------------------------ #
    # String operations
    # ------------------------------------------------------------------ #
    async def get(self, key: str) -> str | None:
        return await self._safe(lambda: self._redis.get(self._key(key)))()

    async def set(self, key: str, value: str) -> bool | None:
        return await self._safe(lambda: self._redis.set(self._key(key), value))()

    async def setex(self, key: str, value: str, ttl: int) -> bool | None:
        return await self._safe(lambda: self._redis.setex(self._key(key), ttl, value))()

    # ------------------------------------------------------------------ #
    # Hash operations
    # ------------------------------------------------------------------ #
    async def hget(self, key: str, field: str) -> str | None:
        return await self._safe(lambda: self._redis.hget(self._key(key), field))()

    async def hset(self, key: str, field: str, value: str) -> int | None:
        return await self._safe(lambda: self._redis.hset(self._key(key), field, value))()

    async def hdel(self, key: str, *fields: str) -> int | None:
        return await self._safe(lambda: self._redis.hdel(self._key(key), *fields))()

    async def hgetall(self, key: str) -> dict[str, str] | None:
        return await self._safe(lambda: self._redis.hgetall(self._key(key)))()

    # ------------------------------------------------------------------ #
    # Set operations
    # ------------------------------------------------------------------ #
    async def smembers(self, key: str) -> set[str] | None:
        result = await self._safe(lambda: self._redis.smembers(self._key(key)))()
        return result if result is None else set(result)

    async def sadd(self, key: str, *members: str) -> int | None:
        return await self._safe(lambda: self._redis.sadd(self._key(key), *members))()

    async def sismember(self, key: str, member: str) -> bool | None:
        return await self._safe(lambda: self._redis.sismember(self._key(key), member))()

    # ------------------------------------------------------------------ #
    # List operations
    # ------------------------------------------------------------------ #
    async def lpush(self, key: str, *values: str) -> int | None:
        return await self._safe(lambda: self._redis.lpush(self._key(key), *values))()

    async def rpush(self, key: str, *values: str) -> int | None:
        return await self._safe(lambda: self._redis.rpush(self._key(key), *values))()

    async def lrange(self, key: str, start: int, stop: int) -> list[str] | None:
        return await self._safe(lambda: self._redis.lrange(self._key(key), start, stop))()

    async def ltrim(self, key: str, start: int, stop: int) -> bool | None:
        return await self._safe(lambda: self._redis.ltrim(self._key(key), start, stop))()

    async def llen(self, key: str) -> int | None:
        return await self._safe(lambda: self._redis.llen(self._key(key)))()

    # ------------------------------------------------------------------ #
    # Generic / pipeline
    # ------------------------------------------------------------------ #
    async def delete(self, *keys: str) -> int | None:
        if not keys:
            return 0
        prefixed = [self._key(k) for k in keys]
        return await self._safe(lambda: self._redis.delete(*prefixed))()

    async def expire(self, key: str, ttl: int) -> bool | None:
        return await self._safe(lambda: self._redis.expire(self._key(key), ttl))()

    async def ttl(self, key: str) -> int | None:
        return await self._safe(lambda: self._redis.ttl(self._key(key)))()

    async def incr(self, key: str) -> int | None:
        return await self._safe(lambda: self._redis.incr(self._key(key)))()

    async def scan_delete(self, pattern: str) -> int | None:
        """Delete all keys matching ``pattern`` using SCAN (production-safe).

        Returns the number of keys deleted, or ``None`` if Redis is unavailable.
        """
        await self._init()
        if self._redis is None:
            return None
        full_pattern = self._key(pattern)
        deleted = 0
        try:
            async for key in self._redis.scan_iter(match=full_pattern, count=100):
                await self._redis.delete(key)
                deleted += 1
            return deleted
        except RedisError as exc:
            logger.warning("Redis scan_delete failed: %s", exc)
            return None

    async def pipeline(self) -> "RedisPipeline" | None:
        """Return a wrapped pipeline that safely executes commands."""
        await self._init()
        if self._redis is None:
            return None
        return RedisPipeline(self._redis, self._prefix)

    async def close(self) -> None:
        await self._init()
        if self._redis is not None:
            try:
                await self._redis.close()
                await self._pool.disconnect()
            except RedisError as exc:
                logger.warning("Redis close failed: %s", exc)


class RedisPipeline:
    """Lightweight wrapper around redis.asyncio.Pipeline with key prefixing."""

    def __init__(self, redis: Redis, prefix: str) -> None:
        self._pipe = redis.pipeline()
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> "RedisPipeline":
        self._pipe.get(self._key(key))
        return self

    def set(self, key: str, value: str) -> "RedisPipeline":
        self._pipe.set(self._key(key), value)
        return self

    def setex(self, key: str, value: str, ttl: int) -> "RedisPipeline":
        self._pipe.setex(self._key(key), ttl, value)
        return self

    def hget(self, key: str, field: str) -> "RedisPipeline":
        self._pipe.hget(self._key(key), field)
        return self

    def hset(self, key: str, field: str, value: str) -> "RedisPipeline":
        self._pipe.hset(self._key(key), field, value)
        return self

    def hdel(self, key: str, *fields: str) -> "RedisPipeline":
        self._pipe.hdel(self._key(key), *fields)
        return self

    def hgetall(self, key: str) -> "RedisPipeline":
        self._pipe.hgetall(self._key(key))
        return self

    def smembers(self, key: str) -> "RedisPipeline":
        self._pipe.smembers(self._key(key))
        return self

    def sadd(self, key: str, *members: str) -> "RedisPipeline":
        self._pipe.sadd(self._key(key), *members)
        return self

    def sismember(self, key: str, member: str) -> "RedisPipeline":
        self._pipe.sismember(self._key(key), member)
        return self

    def delete(self, *keys: str) -> "RedisPipeline":
        if keys:
            self._pipe.delete(*[self._key(k) for k in keys])
        return self

    def expire(self, key: str, ttl: int) -> "RedisPipeline":
        self._pipe.expire(self._key(key), ttl)
        return self

    def incr(self, key: str) -> "RedisPipeline":
        self._pipe.incr(self._key(key))
        return self

    async def execute(self) -> list[Any] | None:
        try:
            return await self._pipe.execute()
        except RedisError as exc:
            logger.warning("Redis pipeline execution failed: %s", exc)
            return None


# Module-level singleton for convenient imports.
redis_client = RedisClient()
