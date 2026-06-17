import asyncio
from redis.asyncio import Redis


class RedisLock:
    def __init__(self, redis: Redis, key: str, ttl: int = 60):
        self._redis = redis
        self._key = f"lock:{key}"
        self._ttl = ttl
        self._acquired = False

    async def acquire(self) -> bool:
        result = await self._redis.set(self._key, "1", nx=True, ex=self._ttl)
        self._acquired = bool(result)
        return self._acquired

    async def release(self):
        if self._acquired:
            await self._redis.delete(self._key)
            self._acquired = False

    async def __aenter__(self):
        acquired = await self.acquire()
        if not acquired:
            raise RuntimeError(f"Could not acquire lock: {self._key}")
        return self

    async def __aexit__(self, *args):
        await self.release()
