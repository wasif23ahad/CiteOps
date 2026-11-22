import asyncio
import time
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.health import DependencyCheck, HealthResponse

logger = get_logger(__name__)
router = APIRouter(tags=["health"])


async def _check_postgres(
    pool: AsyncConnectionPool | None,
) -> tuple[DependencyCheck, DependencyCheck]:
    if pool is None:
        err = DependencyCheck(status="error", detail="Database pool not initialized")
        return err, err

    started = time.perf_counter()
    try:
        async with asyncio.timeout(2.5):
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT current_setting('server_version')")
                    pg_row = await cur.fetchone()
                    pg_ver = pg_row[0] if pg_row else "unknown"

                    await cur.execute(
                        "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                    )
                    vec_row = await cur.fetchone()
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        pg_check = DependencyCheck(status="ok", detail=f"PostgreSQL {pg_ver}", latency_ms=elapsed)
        if vec_row and vec_row[0]:
            vec_check = DependencyCheck(
                status="ok", detail=f"pgvector {vec_row[0]}", latency_ms=elapsed
            )
        else:
            vec_check = DependencyCheck(
                status="error",
                detail="pgvector extension is not enabled",
                latency_ms=elapsed,
            )
        return pg_check, vec_check
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        logger.warning(
            "health_postgres_check_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        err = DependencyCheck(status="error", detail="PostgreSQL unavailable", latency_ms=elapsed)
        return err, DependencyCheck(status="error", detail="Skipped (postgres unreachable)")


async def _check_redis(redis_client: Redis | None) -> DependencyCheck:
    if redis_client is None:
        return DependencyCheck(status="degraded", detail="Redis client not initialized")

    started = time.perf_counter()
    try:
        async with asyncio.timeout(2.0):
            pong = await redis_client.ping()
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        if pong:
            return DependencyCheck(status="ok", detail="PONG", latency_ms=elapsed)
        return DependencyCheck(
            status="degraded",
            detail="Unexpected ping response",
            latency_ms=elapsed,
        )
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        logger.warning("health_redis_check_failed", error_type=type(exc).__name__, error=str(exc))
        return DependencyCheck(status="degraded", detail="Redis unavailable", latency_ms=elapsed)


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request, response: Response) -> HealthResponse:
    """Readiness and liveness probe verifying Postgres, pgvector, and Redis."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    db_pool: AsyncConnectionPool | None = getattr(request.app.state, "db_pool", None)
    redis_client: Redis | None = getattr(request.app.state, "redis", None)

    (pg_check, vec_check), redis_check = await asyncio.gather(
        _check_postgres(db_pool),
        _check_redis(redis_client),
    )

    overall: Literal["ok", "degraded", "unhealthy"]
    if pg_check.status == "error" or vec_check.status == "error":
        overall = "unhealthy"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif redis_check.status != "ok":
        # Redis cache is fail-open by architecture design
        overall = "degraded"
    else:
        overall = "ok"

    return HealthResponse(
        status=overall,
        service=settings.app_name,
        environment=settings.app_env,
        reranker_profile=settings.reranker_profile,
        reranker_model=settings.reranker_model_name,
        llm_provider=settings.llm_provider,
        llm_model=settings.active_llm_model,
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
        dependencies={
            "postgres": pg_check,
            "pgvector": vec_check,
            "redis": redis_check,
        },
    )
