from psycopg_pool import AsyncConnectionPool

from app.core.logging import get_logger
from app.db.pool import tenant_transaction
from app.domain.models import QueryAuditRecord, TenantMetricsSummary

logger = get_logger(__name__)


class PostgresAuditRepository:
    """RLS-enforced operational query telemetry store powering `/v1/metrics/summary`."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def record_query(self, record: QueryAuditRecord) -> None:
        try:
            async with tenant_transaction(self._pool, record.tenant_id) as conn:
                await conn.execute(
                    """
                    INSERT INTO tenants (id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (record.tenant_id, record.tenant_id),
                )
                await conn.execute(
                    """
                    INSERT INTO query_audit_logs (
                        tenant_id, trace_id, status, cache_hit, cache_tier,
                        model, reranker_model, top_rerank_score,
                        latency_ms, retrieval_ms, rerank_ms, llm_ms
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.tenant_id,
                        record.trace_id,
                        record.status,
                        record.cache_hit,
                        record.cache_tier,
                        record.model,
                        record.reranker_model,
                        record.top_rerank_score,
                        record.latency_ms,
                        record.retrieval_ms,
                        record.rerank_ms,
                        record.llm_ms,
                    ),
                )
        except Exception as exc:
            logger.warning(
                "audit_log_write_failed",
                tenant_id=record.tenant_id,
                trace_id=record.trace_id,
                error=str(exc),
            )

    async def get_metrics_summary(self, tenant_id: str) -> TenantMetricsSummary:
        async with tenant_transaction(self._pool, tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT
                        COUNT(*)::int AS total_queries,
                        COUNT(*) FILTER (WHERE cache_tier = 'exact')::int AS exact_hits,
                        COUNT(*) FILTER (WHERE cache_tier = 'semantic')::int AS semantic_hits,
                        COUNT(*) FILTER (
                            WHERE status = 'insufficient_evidence'
                        )::int AS abstentions,
                        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50_ms,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)
                            FILTER (WHERE cache_hit = true) AS p95_hit_ms,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)
                            FILTER (WHERE cache_hit = false) AS p95_miss_ms
                    FROM query_audit_logs
                    WHERE tenant_id = %s
                    """,
                    (tenant_id,),
                )
                row = await cur.fetchone()

        if row is None or row[0] == 0:
            return TenantMetricsSummary(
                tenant_id=tenant_id,
                total_queries=0,
                cache_hit_rate=0.0,
                exact_cache_hits=0,
                semantic_cache_hits=0,
                abstention_rate=0.0,
                p50_latency_ms=None,
                p95_latency_ms=None,
                p95_cache_hit_ms=None,
                p95_cache_miss_ms=None,
            )

        total, exact_hits, semantic_hits, abstentions = (
            int(row[0]),
            int(row[1]),
            int(row[2]),
            int(row[3]),
        )
        return TenantMetricsSummary(
            tenant_id=tenant_id,
            total_queries=total,
            cache_hit_rate=round((exact_hits + semantic_hits) / total, 4),
            exact_cache_hits=exact_hits,
            semantic_cache_hits=semantic_hits,
            abstention_rate=round(abstentions / total, 4),
            p50_latency_ms=round(float(row[4]), 2) if row[4] is not None else None,
            p95_latency_ms=round(float(row[5]), 2) if row[5] is not None else None,
            p95_cache_hit_ms=round(float(row[6]), 2) if row[6] is not None else None,
            p95_cache_miss_ms=round(float(row[7]), 2) if row[7] is not None else None,
        )
