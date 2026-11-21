from redis.asyncio import Redis

from app.core.logging import get_logger

logger = get_logger(__name__)


class CorpusVersionStore:
    """
    Manages per-tenant `corpus_version` counters in Redis (`tenant:version:{tenant_id}`).

    Provides O(1) generation-based cache invalidation on document ingest/delete and
    fails open (returns version 1) if Redis is temporarily unavailable.
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
        try:
            new_version = await self._redis.incr(self._key(tenant_id))
            return max(1, int(new_version))
        except Exception as exc:
            logger.warning("redis_corpus_version_bump_failed", tenant_id=tenant_id, error=str(exc))
            return 1
