import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.logging import get_logger

logger = get_logger(__name__)

# Atomic sliding-window ZSET rate limiter executed server-side in Redis
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now_ms - window_ms)
local current = redis.call('ZCARD', key)
if current >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_ms = window_ms
    if oldest and oldest[2] then
        retry_ms = math.max(1000, (tonumber(oldest[2]) + window_ms) - now_ms)
    end
    return {0, 0, retry_ms}
end

redis.call('ZADD', key, now_ms, member)
redis.call('PEXPIRE', key, window_ms + 1000)
local remaining = math.max(0, limit - current - 1)
return {1, remaining, 0}
"""


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class RateLimitExceededError(Exception):
    """Raised when a tenant or global LLM-miss sliding window quota is exceeded."""

    def __init__(self, detail: str, decision: RateLimitDecision) -> None:
        super().__init__(detail)
        self.detail = detail
        self.decision = decision


class SlidingWindowRateLimiter:
    """
    Atomic Redis Lua sliding-window rate limiter with in-process deque fallback:
      - Per-tenant API admission (`rl:tenant:{tenant_id}`)
      - Global LLM-miss budget (`rl:llm:global`) — bypassed on L1/L2 cache hits!
    """

    def __init__(
        self,
        redis_client: Redis | None,
        *,
        tenant_rpm: int = 20,
        global_llm_rpm: int = 12,
        window_seconds: int = 60,
    ) -> None:
        self._redis = redis_client
        self._tenant_rpm = max(1, tenant_rpm)
        self._global_llm_rpm = max(1, global_llm_rpm)
        self._window_ms = max(1, window_seconds) * 1000
        self._fallback_buckets: dict[str, deque[int]] = {}

    async def check_tenant(self, tenant_id: str) -> RateLimitDecision:
        key = f"rl:tenant:{tenant_id}"
        decision = await self._evaluate(key, self._tenant_rpm)
        if not decision.allowed:
            raise RateLimitExceededError(
                f"Tenant '{tenant_id}' exceeded rate limit ({self._tenant_rpm} req/min).",
                decision,
            )
        return decision

    async def check_llm_budget(self) -> RateLimitDecision:
        key = "rl:llm:global"
        decision = await self._evaluate(key, self._global_llm_rpm)
        if not decision.allowed:
            raise RateLimitExceededError(
                f"Upstream LLM free-tier rate budget reached ({self._global_llm_rpm} req/min). "
                "Please retry shortly.",
                decision,
            )
        return decision

    async def _evaluate(self, key: str, limit: int) -> RateLimitDecision:
        now_ms = int(time.time() * 1000)
        if self._redis is not None:
            try:
                member = f"{now_ms}:{uuid.uuid4().hex[:8]}"
                async with asyncio.timeout(0.35):
                    raw = await self._redis.eval(  # type: ignore[misc]
                        _SLIDING_WINDOW_LUA,
                        1,
                        key,
                        str(now_ms),
                        str(self._window_ms),
                        str(limit),
                        member,
                    )
                allowed = int(raw[0]) == 1
                remaining = int(raw[1])
                retry_after_s = max(1, (int(raw[2]) + 999) // 1000) if not allowed else 0
                return RateLimitDecision(
                    allowed=allowed,
                    limit=limit,
                    remaining=remaining,
                    retry_after_seconds=retry_after_s,
                )
            except Exception as exc:
                logger.warning("rate_limit_redis_fallback", key=key, error=str(exc))

        return self._evaluate_in_memory(key, limit, now_ms)

    def _evaluate_in_memory(self, key: str, limit: int, now_ms: int) -> RateLimitDecision:
        bucket = self._fallback_buckets.setdefault(key, deque())
        cutoff = now_ms - self._window_ms
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            retry_ms = max(1000, (bucket[0] + self._window_ms) - now_ms)
            return RateLimitDecision(
                allowed=False,
                limit=limit,
                remaining=0,
                retry_after_seconds=(retry_ms + 999) // 1000,
            )

        bucket.append(now_ms)
        return RateLimitDecision(
            allowed=True,
            limit=limit,
            remaining=max(0, limit - len(bucket)),
            retry_after_seconds=0,
        )
