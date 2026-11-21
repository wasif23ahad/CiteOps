import uuid

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.audit_postgres import PostgresAuditRepository
from app.core.config import Settings, get_settings
from app.db.migrate import run_migrations
from app.db.pool import create_db_pool
from app.domain.models import QueryAuditRecord
from app.main import create_app


@pytest.mark.asyncio
async def test_metrics_summary_computes_rls_isolated_hit_rate_and_percentiles() -> None:
    settings = get_settings()
    try:
        run_migrations(settings.database_admin_url)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Local PostgreSQL unavailable for metrics summary test: {exc}")

    pool = create_db_pool(settings, conninfo=settings.database_url)
    await pool.open(wait=True)

    run_id = uuid.uuid4().hex[:8]
    tenant_a = f"met-acme-{run_id}"
    tenant_b = f"met-globex-{run_id}"

    audit_repo = PostgresAuditRepository(pool)
    test_settings = Settings(app_env="test", citeops_internal_api_key="met-key")
    app = create_app(test_settings)
    app.state.audit_repo = audit_repo

    try:
        records = [
            QueryAuditRecord(
                tenant_id=tenant_a,
                trace_id="t1",
                status="answered",
                cache_hit=False,
                cache_tier="miss",
                model="gemini-3.8-flash",
                reranker_model="Xenova/ms-marco-MiniLM-L-6-v2",
                top_rerank_score=0.94,
                latency_ms=1000,
                retrieval_ms=120,
                rerank_ms=180,
                llm_ms=700,
            ),
            QueryAuditRecord(
                tenant_id=tenant_a,
                trace_id="t2",
                status="answered",
                cache_hit=True,
                cache_tier="exact",
                model="gemini-3.8-flash",
                reranker_model="Xenova/ms-marco-MiniLM-L-6-v2",
                top_rerank_score=0.94,
                latency_ms=12,
                retrieval_ms=0,
                rerank_ms=0,
                llm_ms=0,
            ),
            QueryAuditRecord(
                tenant_id=tenant_a,
                trace_id="t3",
                status="answered",
                cache_hit=True,
                cache_tier="semantic",
                model="gemini-3.8-flash",
                reranker_model="Xenova/ms-marco-MiniLM-L-6-v2",
                top_rerank_score=0.94,
                latency_ms=28,
                retrieval_ms=0,
                rerank_ms=0,
                llm_ms=0,
            ),
            QueryAuditRecord(
                tenant_id=tenant_a,
                trace_id="t4",
                status="insufficient_evidence",
                cache_hit=False,
                cache_tier="miss",
                model="none (gate_1_abstain)",
                reranker_model="Xenova/ms-marco-MiniLM-L-6-v2",
                top_rerank_score=0.05,
                latency_ms=200,
                retrieval_ms=100,
                rerank_ms=100,
                llm_ms=0,
            ),
            # Tenant B row (must never leak into Tenant A metrics)
            QueryAuditRecord(
                tenant_id=tenant_b,
                trace_id="tb1",
                status="answered",
                cache_hit=False,
                cache_tier="miss",
                model="gemini-3.8-flash",
                reranker_model="Xenova/ms-marco-MiniLM-L-6-v2",
                top_rerank_score=0.88,
                latency_ms=9999,
                retrieval_ms=100,
                rerank_ms=100,
                llm_ms=9799,
            ),
        ]
        for rec in records:
            await audit_repo.record_query(rec)

        headers = {"X-Internal-API-Key": "met-key"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp_a = await client.get(
                f"/v1/metrics/summary?tenant_id={tenant_a}", headers=headers
            )
            assert resp_a.status_code == 200
            body_a = resp_a.json()
            assert body_a["total_queries"] == 4
            assert body_a["exact_cache_hits"] == 1
            assert body_a["semantic_cache_hits"] == 1
            assert body_a["cache_hit_rate"] == 0.5
            assert body_a["abstention_rate"] == 0.25
            assert body_a["p95_cache_hit_ms"] < 50.0
            assert body_a["p95_cache_miss_ms"] <= 1000.0

            resp_b = await client.get(
                f"/v1/metrics/summary?tenant_id={tenant_b}", headers=headers
            )
            assert resp_b.status_code == 200
            assert resp_b.json()["total_queries"] == 1
    finally:
        await pool.close()
        with psycopg.connect(settings.database_admin_url, autocommit=True) as admin_conn:
            with admin_conn.cursor() as cur:
                cur.execute("DELETE FROM tenants WHERE id = ANY(%s)", ([tenant_a, tenant_b],))
