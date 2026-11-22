import uuid

import psycopg
import pytest

from app.adapters.repo_postgres import PostgresDocumentRepository
from app.adapters.retriever_postgres import PostgresHybridRetriever, build_lexical_or_query
from app.core.config import get_settings
from app.db.migrate import run_migrations
from app.db.pool import create_db_pool
from app.domain.models import DocumentChunkDraft


def _unit_vec(hot_index: int, dim: int = 768) -> list[float]:
    vec = [0.0] * dim
    vec[hot_index] = 1.0
    return vec


def test_build_lexical_or_query_prioritizes_exact_codes_and_strips_stopwords() -> None:
    q = (
        "Why does webhook signature verification fail with ERR_SIG_4092 "
        "on SDK v2.4.1, and what is the rollback procedure?"
    )
    lex = build_lexical_or_query(q)
    tokens = lex.split(" OR ")
    assert "ERR_SIG_4092" in tokens[:3]
    assert "v2.4.1" in tokens[:3]
    assert "why" not in [t.lower() for t in tokens]
    assert "does" not in [t.lower() for t in tokens]


@pytest.mark.asyncio
async def test_hybrid_rrf_surfaces_exact_codes_filters_doc_types_and_isolates_tenants() -> None:
    settings = get_settings()
    try:
        run_migrations(settings.database_admin_url)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Local PostgreSQL unavailable for hybrid RRF test: {exc}")

    pool = create_db_pool(settings, conninfo=settings.database_url)
    await pool.open(wait=True)

    run_id = uuid.uuid4().hex[:8]
    tenant_a = f"rrf-acme-{run_id}"
    tenant_b = f"rrf-globex-{run_id}"

    repo = PostgresDocumentRepository(pool)
    retriever = PostgresHybridRetriever(pool)

    try:
        # Tenant A Doc 1 (api_docs): exact code ERR_SIG_4092 at vector axis 0
        await repo.save_document_with_chunks(
            tenant_id=tenant_a,
            doc_title="Webhook Error Reference",
            doc_type="api_docs",
            version="v2.4.1",
            source_filename="webhooks.md",
            content_hash=f"a1{run_id:0<62}",
            embedding_model="test-768",
            embedding_dim=768,
            page_count=14,
            chunks=[
                DocumentChunkDraft(
                    chunk_index=0,
                    page_number=14,
                    section_path="4.3 Webhook Error Codes > ERR_SIG_4092",
                    content=(
                        "ERR_SIG_4092 occurs on SDK v2.4.1 when JSON middleware "
                        "mutates raw request bytes before verifySignature()."
                    ),
                    contextual_content=(
                        "[Document: Webhook Error Reference | Version: v2.4.1 | Page: 14]\n"
                        "ERR_SIG_4092 occurs on SDK v2.4.1 when JSON middleware "
                        "mutates raw request bytes before verifySignature()."
                    ),
                    token_count=28,
                ),
            ],
            embeddings=[_unit_vec(0)],
        )

        # Tenant A Doc 2 (sla_contract): Section 4.2 AES-256 at vector axis 1
        await repo.save_document_with_chunks(
            tenant_id=tenant_a,
            doc_title="Enterprise SLA Contract",
            doc_type="sla_contract",
            version="v3.2",
            source_filename="sla.md",
            content_hash=f"a2{run_id:0<62}",
            embedding_model="test-768",
            embedding_dim=768,
            page_count=7,
            chunks=[
                DocumentChunkDraft(
                    chunk_index=0,
                    page_number=4,
                    section_path="Section 4.2 Encryption at Rest",
                    content="Section 4.2 enforces AES-256-GCM encryption at rest and 15 min RTO.",
                    contextual_content=(
                        "[Document: Enterprise SLA Contract | Version: v3.2 | Page: 4]\n"
                        "Section 4.2 enforces AES-256-GCM encryption at rest and 15 min RTO."
                    ),
                    token_count=24,
                ),
            ],
            embeddings=[_unit_vec(1)],
        )

        # Tenant B Doc (sla_contract): private secret ERR_GLOBEX_9901 at axis 0
        await repo.save_document_with_chunks(
            tenant_id=tenant_b,
            doc_title="Globex Private SLA",
            doc_type="sla_contract",
            version="v1.0",
            source_filename="globex.md",
            content_hash=f"b1{run_id:0<62}",
            embedding_model="test-768",
            embedding_dim=768,
            page_count=1,
            chunks=[
                DocumentChunkDraft(
                    chunk_index=0,
                    page_number=1,
                    section_path="Sovereign Enclave",
                    content="ERR_GLOBEX_9901 is private to Globex IO eu-west-1 enclave.",
                    contextual_content=(
                        "[Document: Globex Private SLA | Version: v1.0 | Page: 1]\n"
                        "ERR_GLOBEX_9901 is private to Globex IO eu-west-1 enclave."
                    ),
                    token_count=20,
                ),
            ],
            embeddings=[_unit_vec(0)],
        )

        # 1. Exact code query where dense vector deliberately points at axis 1 (SLA),
        #    proving lexical branch + RRF still retrieves ERR_SIG_4092 from api_docs!
        results = await retriever.retrieve(
            tenant_id=tenant_a,
            query_text="Why does webhook signature fail with ERR_SIG_4092 on SDK v2.4.1?",
            query_embedding=_unit_vec(1),
            candidate_limit=10,
        )
        assert len(results) == 2
        assert any("ERR_SIG_4092" in r.content and r.page_number == 14 for r in results)
        # Zero cross-tenant leakage from tenant B
        assert all("ERR_GLOBEX_9901" not in r.content for r in results)

        # 2. Filtered by doc_types=["sla_contract"] returns ONLY SLA chunk
        sla_only = await retriever.retrieve(
            tenant_id=tenant_a,
            query_text="Section 4.2 AES-256 encryption",
            query_embedding=_unit_vec(1),
            doc_types=["sla_contract"],
            candidate_limit=10,
        )
        assert len(sla_only) == 1
        assert sla_only[0].doc_type == "sla_contract"
        assert sla_only[0].page_number == 4
    finally:
        await pool.close()
        with psycopg.connect(settings.database_admin_url, autocommit=True) as admin_conn:
            with admin_conn.cursor() as cur:
                cur.execute("DELETE FROM tenants WHERE id = ANY(%s)", ([tenant_a, tenant_b],))
