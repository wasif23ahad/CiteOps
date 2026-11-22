import asyncio

from redis.asyncio import Redis

from app.core.logging import get_logger

logger = get_logger(__name__)

_REDIS_OP_TIMEOUT_S = 0.4


class CorpusVersionStore:
    """
    Canonical manager for per-tenant `corpus_version` counters (`tenant:version:{tenant_id}`).

    Provides bounded-timeout O(1) generation-based cache invalidation on document ingest/delete
    and fails open (returns version 1) if Redis is temporarily unavailable.
    """

    def __init__(self, redis_client: Redis | None) -> None:
        self._redis = redis_client

    @staticmethod
    def _key(tenant_id: str) -> str:
        return f"tenant:version:{tenant_id}"

    async def get_version(self, tenant_id: str) -> int:
        if self._redis is None:
            return 1
        try:
            async with asyncio.timeout(_REDIS_OP_TIMEOUT_S):
                raw = await self._redis.get(self._key(tenant_id))
            if raw is None:
                return 1
            return max(1, int(raw))
        except Exception as exc:
            logger.warning("redis_corpus_version_get_failed", tenant_id=tenant_id, error=str(exc))
            return 1

    async def bump_version(self, tenant_id: str) -> int:
        if self._redis is None:
            return 1
        key = self._key(tenant_id)
        try:
            async with asyncio.timeout(_REDIS_OP_TIMEOUT_S):
                # Initialize unset key to 1 before INCR so v1 caches always invalidate to v2+
                pipe = self._redis.pipeline(transaction=True)
                pipe.set(key, "1", nx=True)
                pipe.incr(key)
                results = await pipe.execute()
            return max(2, int(results[-1]))
        except Exception as exc:
            logger.warning("redis_corpus_version_bump_failed", tenant_id=tenant_id, error=str(exc))
            return 1
