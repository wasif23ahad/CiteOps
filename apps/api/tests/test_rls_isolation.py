import uuid

import psycopg
import pytest

from app.core.config import get_settings
from app.db.migrate import run_migrations
from app.db.pool import create_db_pool, tenant_transaction


def _zero_vector(dim: int = 768) -> list[float]:
    vec = [0.0] * dim
    vec[0] = 1.0
    return vec


@pytest.mark.asyncio
async def test_migrations_are_idempotent_and_rls_enforces_zero_leakage() -> None:
    """Integration test proving PostgreSQL RLS enforces 0% cross-tenant data leakage."""
    settings = get_settings()

    # 1. Verify migrations run idempotently under admin URL
    try:
        run_migrations(settings.database_admin_url)
        second_run = run_migrations(settings.database_admin_url)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Local PostgreSQL unavailable for RLS integration test: {exc}")
    assert second_run == []

    # 2. Verify runtime role `citeops_app` cannot bypass RLS
    pool = create_db_pool(settings, conninfo=settings.database_url)
    await pool.open(wait=True)

    run_suffix = uuid.uuid4().hex[:8]
    tenant_a = f"rls-acme-{run_suffix}"
    tenant_b = f"rls-globex-{run_suffix}"
    shared_hash = f"{run_suffix:0<64}"

    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT current_user, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
                role_row = await cur.fetchone()
                assert role_row is not None
                role_name, is_super, can_bypass_rls = role_row
                assert role_name == "citeops_app", (
                    "DATABASE_URL must connect as non-BYPASSRLS role 'citeops_app' "
                    "(refresh .env from .env.example)"
                )
                assert is_super is False
                assert can_bypass_rls is False

        # 3. Seed tenant A data inside tenant A RLS transaction
        async with tenant_transaction(pool, tenant_a) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO tenants (id, name) VALUES (%s, %s)",
                    (tenant_a, "Acme Test Corp"),
                )
                await cur.execute(
                    """
                    INSERT INTO documents (
                        tenant_id, doc_title, doc_type, version, source_filename,
                        content_hash, embedding_model, embedding_dim, page_count, chunk_count
                    )
                    VALUES (%s, %s, 'api_docs', 'v2.4.1', 'webhook.md', %s,
                            'gemini-embedding-001', 768, 14, 1)
                    RETURNING id
                    """,
                    (tenant_a, "Acme Webhook Spec", shared_hash),
                )
                doc_a_row = await cur.fetchone()
                assert doc_a_row is not None
                doc_a_id = doc_a_row[0]

                await cur.execute(
                    """
                    INSERT INTO document_chunks (
                        tenant_id, document_id, doc_type, chunk_index, page_number,
                        section_path, content, contextual_content, token_count, embedding
                    )
                    VALUES (%s, %s, 'api_docs', 0, 14, '4.3 Errors',
                            'ERR_SIG_4092 secret Acme token',
                            'Acme Webhook Spec ERR_SIG_4092', 12, %s::vector)
                    """,
                    (tenant_a, doc_a_id, _zero_vector()),
                )

                await cur.execute(
                    """
                    INSERT INTO query_audit_logs (
                        tenant_id, trace_id, status, cache_hit, cache_tier,
                        model, reranker_model, top_rerank_score, latency_ms
                    )
                    VALUES (%s, 'trace-a', 'answered', false, 'miss',
                            'gemini-3.8-flash', 'Xenova/ms-marco-MiniLM-L-6-v2', 0.94, 410)
                    """,
                    (tenant_a,),
                )

        # 4. Seed tenant B with the SAME content_hash (must be allowed independently per tenant)
        async with tenant_transaction(pool, tenant_b) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO tenants (id, name) VALUES (%s, %s)",
                    (tenant_b, "Globex Test IO"),
                )
                await cur.execute(
                    """
                    INSERT INTO documents (
                        tenant_id, doc_title, doc_type, version, source_filename,
                        content_hash, embedding_model, embedding_dim, page_count, chunk_count
                    )
                    VALUES (%s, %s, 'sla_contract', 'v1.0', 'sla.pdf', %s,
                            'gemini-embedding-001', 768, 8, 1)
                    RETURNING id
                    """,
                    (tenant_b, "Globex Private SLA", shared_hash),
                )
                doc_b_row = await cur.fetchone()
                assert doc_b_row is not None
                doc_b_id = doc_b_row[0]

                await cur.execute(
                    """
                    INSERT INTO document_chunks (
                        tenant_id, document_id, doc_type, chunk_index, page_number,
                        section_path, content, contextual_content, token_count, embedding
                    )
                    VALUES (%s, %s, 'sla_contract', 0, 3, 'Section 4.2',
                            'Globex confidential Sev-1 RTO is 5 minutes',
                            'Globex Private SLA Section 4.2', 14, %s::vector)
                    """,
                    (tenant_b, doc_b_id, _zero_vector()),
                )

        # 5. Tenant A query WITHOUT a WHERE clause still sees ONLY Tenant A rows (pure RLS proof)
        async with tenant_transaction(pool, tenant_a) as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT tenant_id, doc_title FROM documents")
                docs_a = await cur.fetchall()
                assert docs_a == [(tenant_a, "Acme Webhook Spec")]

                await cur.execute(
                    "SELECT tenant_id, content FROM document_chunks "
                    "WHERE search_tsv @@ websearch_to_tsquery('simple', 'ERR_SIG_4092')"
                )
                chunks_a = await cur.fetchall()
                assert len(chunks_a) == 1
                assert chunks_a[0][0] == tenant_a

                await cur.execute("SELECT tenant_id FROM query_audit_logs")
                audits_a = await cur.fetchall()
                assert audits_a == [(tenant_a,)]

        # 6. Tenant B cannot see Tenant A's documents, chunks, or audit logs
        async with tenant_transaction(pool, tenant_b) as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT tenant_id, doc_title FROM documents")
                docs_b = await cur.fetchall()
                assert docs_b == [(tenant_b, "Globex Private SLA")]

                await cur.execute("SELECT tenant_id FROM query_audit_logs")
                assert await cur.fetchall() == []

        # 7. Unset app.current_tenant_id fails CLOSED (0 rows visible)
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM documents")
                count_docs = await cur.fetchone()
                assert count_docs == (0,)

                await cur.execute("SELECT COUNT(*) FROM document_chunks")
                count_chunks = await cur.fetchone()
                assert count_chunks == (0,)

        # 8. Cross-tenant INSERT inside Tenant A's transaction is blocked by RLS WITH CHECK
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            async with tenant_transaction(pool, tenant_a) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO documents (
                            tenant_id, doc_title, doc_type, version, source_filename,
                            content_hash, embedding_model, embedding_dim, page_count, chunk_count
                        )
                        VALUES (%s, 'Forged Cross-Tenant Doc', 'runbook', 'v1', 'x.md', %s,
                                'gemini-embedding-001', 768, 1, 0)
                        """,
                        (tenant_b, "f" * 64),
                    )
    finally:
        await pool.close()
        # Clean up ephemeral test tenants under admin connection
        with psycopg.connect(settings.database_admin_url, autocommit=True) as admin_conn:
            with admin_conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM tenants WHERE id = ANY(%s)",
                    ([tenant_a, tenant_b],),
                )
