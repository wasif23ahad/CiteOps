"""
Zero-LLM deterministic retrieval & tenant-isolation regression gate across all 50 golden cases.

Runs PostgreSQL 17 hybrid retrieval (pgvector HNSW + dual simple/english tsvector RRF + RLS)
plus the local ONNX Cross-Encoder reranker (`Xenova/ms-marco-MiniLM-L-6-v2` by default):
  - Asserts Context Recall@5 >= 0.85 across all 40 answerable queries
  - Asserts 0% cross-tenant leakage across all 50 queries (including all 4 isolation probes)
  - Automatically falls back to deterministic offline embeddings on forked PRs without API keys
"""

from __future__ import annotations

import psycopg
import pytest

from app.core.config import get_settings
from app.db.migrate import run_migrations
from app.db.pool import create_db_pool
from evals.harness import run_deterministic_retrieval_suite
from evals.loader import load_golden_dataset


@pytest.mark.asyncio
async def test_golden_50_deterministic_retrieval_and_isolation() -> None:
    settings = get_settings()
    try:
        run_migrations(settings.database_admin_url)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL unavailable for deterministic retrieval eval: {exc}")

    cases = load_golden_dataset(suite="full")
    assert len(cases) == 50, f"Expected 50 golden cases, found {len(cases)}"

    pool = create_db_pool(settings, conninfo=settings.database_url)
    await pool.open(wait=True)
    try:
        summary = await run_deterministic_retrieval_suite(
            settings=settings,
            pool=pool,
            cases=cases,
            top_k=5,
        )
    finally:
        await pool.close()

    print(
        f"\n[Deterministic Retrieval Eval | mode={summary.mode}] "
        f"Recall@5={summary.mean_recall_at_5:.4f} "
        f"(Full-Hit={summary.full_hit_rate:.4f}, "
        f"Leakage={summary.leakage_count}/{summary.total_cases})"
    )
    for cat, score in summary.category_recall.items():
        print(f"  - {cat:<16}: {score:.4f}")

    # Report any missed answerable cases clearly for fast debugging
    misses = [
        r for r in summary.results if r.source_recall is not None and r.source_recall < 1.0
    ]
    if misses:
        print(f"  Missed/partial answerable cases ({len(misses)}):")
        for row in misses:
            print(
                f"    * {row.case_id} ({row.category}, tenant={row.tenant_id}): "
                f"recall={row.source_recall:.2f} top_score={row.top_rerank_score} "
                f"got={list(row.top_sources[:3])}"
            )

    # Hard SLO Gate 1: Zero Cross-Tenant Leakage
    leaks = [r for r in summary.results if r.leaked_substrings or r.leaked_titles]
    assert summary.leakage_count == 0, (
        f"Cross-tenant leakage detected in {summary.leakage_count} case(s): "
        + ", ".join(
            f"{r.case_id}(substrings={r.leaked_substrings}, titles={r.leaked_titles})"
            for r in leaks
        )
    )

    # Hard SLO Gate 2: Context Recall@5 >= 0.85 across all 40 answerable queries
    assert summary.mean_recall_at_5 >= 0.85, (
        f"Context Recall@5 ({summary.mean_recall_at_5:.4f}) dropped below 0.85 SLO "
        f"(by category: {summary.category_recall})"
    )
