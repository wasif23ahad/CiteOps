import hashlib
import uuid
from collections.abc import Sequence

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.corpus_version import CorpusVersionStore
from app.adapters.parser_pymupdf import PyMuPDFDocumentParser
from app.adapters.repo_postgres import PostgresDocumentRepository
from app.core.config import Settings, get_settings
from app.db.migrate import run_migrations
from app.db.pool import create_db_pool, tenant_transaction
from app.main import create_app
from app.services.chunker import StructureAwareChunker
from app.services.ingestion import DocumentLifecycleService, IngestionOrchestrator


class _DeterministicTestEmbedder:
    """Offline deterministic 768d embedder for fast integration tests ($0 API calls)."""

    def __init__(self, dim: int = 768) -> None:
        self._dim = dim
        self.call_count = 0

    @property
    def model_name(self) -> str:
        return "test-deterministic-768"

    @property
    def dimensions(self) -> int:
        return self._dim

    def _vec(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [((digest[i % len(digest)] / 255.0) - 0.5) for i in range(self._dim)]
        norm = sum(x * x for x in raw) ** 0.5
        return [x / norm for x in raw]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.call_count += 1
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class _InMemoryCorpusVersionStore(CorpusVersionStore):
    def __init__(self) -> None:
        super().__init__(redis_client=None)
        self._versions: dict[str, int] = {}

    async def get_version(self, tenant_id: str) -> int:
        return self._versions.get(tenant_id, 1)

    async def bump_version(self, tenant_id: str) -> int:
        nxt = self._versions.get(tenant_id, 1) + 1
        self._versions[tenant_id] = nxt
        return nxt


@pytest.mark.asyncio
async def test_ingest_idempotency_tenant_isolation_and_delete() -> None:
    """End-to-end integration test of /v1/ingest and /v1/documents over live Postgres RLS."""
    base_settings = get_settings()
    try:
        run_migrations(base_settings.database_admin_url)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Local PostgreSQL unavailable for ingestion integration test: {exc}")

    pool = create_db_pool(base_settings, conninfo=base_settings.database_url)
    await pool.open(wait=True)

    run_id = uuid.uuid4().hex[:8]
    tenant_a = f"ing-acme-{run_id}"
    tenant_b = f"ing-globex-{run_id}"

    embedder = _DeterministicTestEmbedder(dim=768)
    repo = PostgresDocumentRepository(pool)
    versions = _InMemoryCorpusVersionStore()

    test_settings = Settings(
        app_env="test",
        citeops_internal_api_key="test-internal-key",
        database_url=base_settings.database_url,
        database_admin_url=base_settings.database_admin_url,
    )
    app = create_app(test_settings)
    app.state.db_pool = pool
    app.state.ingestion_orchestrator = IngestionOrchestrator(
        parser=PyMuPDFDocumentParser(),
        chunker=StructureAwareChunker(),
        embedder=embedder,
        repo=repo,
        corpus_versions=versions,
    )
    app.state.document_lifecycle_service = DocumentLifecycleService(
        repo=repo,
        corpus_versions=versions,
    )

    sample_md = (
        b"<!-- page: 14 -->\n"
        b"# Webhook Reference\n"
        b"## ERR_SIG_4092\n"
        b"Pass the unparsed raw request buffer to verifySignature() on SDK v2.4.1.\n"
    )
    headers = {"X-Internal-API-Key": "test-internal-key"}

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. First upload indexes chunks and increments corpus_version
            r1 = await client.post(
                "/v1/ingest",
                headers=headers,
                data={
                    "tenant_id": tenant_a,
                    "doc_type": "api_docs",
                    "version": "v2.4.1",
                    "doc_title": "Webhook Reference",
                },
                files={"file": ("webhook.md", sample_md, "text/markdown")},
            )
            assert r1.status_code == 200
            b1 = r1.json()
            assert b1["status"] == "indexed"
            assert b1["page_count"] == 14
            assert b1["chunk_count"] >= 1
            assert b1["corpus_version"] == 2
            assert embedder.call_count == 1
            doc_a_id = b1["document_id"]

            # 2. Second identical upload returns skipped_unchanged with ZERO embedding calls
            r2 = await client.post(
                "/v1/ingest",
                headers=headers,
                data={
                    "tenant_id": tenant_a,
                    "doc_type": "api_docs",
                    "version": "v2.4.1",
                    "doc_title": "Webhook Reference",
                },
                files={"file": ("webhook.md", sample_md, "text/markdown")},
            )
            assert r2.status_code == 200
            b2 = r2.json()
            assert b2["status"] == "skipped_unchanged"
            assert b2["document_id"] == doc_a_id
            assert b2["chunk_count"] == 0
            assert embedder.call_count == 1  # Still 1: $0 re-embedding cost

            # 3. Same file uploaded to tenant B succeeds independently
            r3 = await client.post(
                "/v1/ingest",
                headers=headers,
                data={
                    "tenant_id": tenant_b,
                    "doc_type": "api_docs",
                    "version": "v2.4.1",
                    "doc_title": "Webhook Reference",
                },
                files={"file": ("webhook.md", sample_md, "text/markdown")},
            )
            assert r3.status_code == 200
            assert r3.json()["status"] == "indexed"
            assert embedder.call_count == 2

            # 4. List documents isolates tenant A strictly
            list_a = await client.get(f"/v1/documents?tenant_id={tenant_a}", headers=headers)
            assert list_a.status_code == 200
            assert list_a.json()["total"] == 1
            assert list_a.json()["documents"][0]["id"] == doc_a_id

            # 5. Cross-tenant delete attempt returns 404 (RLS blocks access)
            cross_del = await client.delete(
                f"/v1/documents/{doc_a_id}?tenant_id={tenant_b}",
                headers=headers,
            )
            assert cross_del.status_code == 404

            # 6. Tenant A deletes its own document; bumps corpus_version & cascades chunks
            del_a = await client.delete(
                f"/v1/documents/{doc_a_id}?tenant_id={tenant_a}",
                headers=headers,
            )
            assert del_a.status_code == 200
            assert del_a.json()["deleted"] is True
            assert del_a.json()["corpus_version"] == 3

            # Confirm 0 chunks remain in Postgres for tenant A
            async with tenant_transaction(pool, tenant_a) as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT COUNT(*) FROM document_chunks")
                    assert await cur.fetchone() == (0,)
    finally:
        await pool.close()
        with psycopg.connect(base_settings.database_admin_url, autocommit=True) as admin_conn:
            with admin_conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM tenants WHERE id = ANY(%s)",
                    ([tenant_a, tenant_b],),
                )
