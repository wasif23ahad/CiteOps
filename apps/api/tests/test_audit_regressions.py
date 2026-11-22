"""Regression tests covering critical bugs, security hardening, and performance fixes."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.adapters.llm_router import LLMUnavailableError
from app.adapters.parser_pymupdf import PyMuPDFDocumentParser, UnsupportedDocumentFormatError
from app.core.config import Settings
from app.core.rate_limit import RateLimitDecision, RateLimitExceededError
from app.core.telemetry import TelemetryTracer
from app.domain.models import DocType, GroundedLLMResult, RerankedChunk, RetrievedChunk
from app.main import create_app
from app.schemas.query import QueryRequest
from app.services.ingestion import MAX_UPLOAD_BYTES
from app.services.query import QueryOrchestrator
from app.services.verifier import CitationVerifierAndHydrator


class _FakeLangfuseClient:
    """Minimal Langfuse stub whose context manager does NOT suppress caller exceptions."""

    @contextmanager
    def start_as_current_observation(self, **kwargs: Any) -> Any:
        class _Obs:
            trace_id = "tr_langfuse_test_123"

            def update(self, **_: Any) -> None:
                return None

        yield _Obs()


def test_telemetry_tracer_propagates_caller_exceptions_without_double_yield() -> None:
    """Ensure active Langfuse tracing never crashes with `generator didn't stop after throw()`."""
    settings = Settings(app_env="test")
    tracer = TelemetryTracer(settings)
    tracer._client = _FakeLangfuseClient()  # type: ignore[assignment]

    rate_err = RateLimitExceededError(
        "Tenant exceeded rate limit",
        RateLimitDecision(allowed=False, limit=20, remaining=0, retry_after_seconds=12),
    )

    with pytest.raises(RateLimitExceededError) as exc_info:
        with tracer.trace_query(tenant_id="acme-corp", request_id="req-1", query="test"):
            with tracer.span("rate_limit.tenant"):
                raise rate_err

    assert exc_info.value is rate_err


def test_parser_rejects_spoofed_and_corrupted_pdf_cleanly() -> None:
    parser = PyMuPDFDocumentParser()

    with pytest.raises(UnsupportedDocumentFormatError, match="%PDF-"):
        parser.parse(b"this is actually plain text pretending to be pdf", "fake.pdf")

    with pytest.raises(UnsupportedDocumentFormatError, match="Unable to parse PDF"):
        parser.parse(b"%PDF-1.7\ncompletely truncated corrupted bytes", "broken.pdf")


class _StubEmbedder:
    model_name = "stub-embed"
    dimensions = 4

    def __init__(self) -> None:
        self.embed_query_calls = 0

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.embed_query_calls += 1
        return [1.0, 0.0, 0.0, 0.0]


class _InMemorySemanticCache:
    """Simulates L1 exact + L2 semantic cache to verify L2 -> L1 promotion backfill."""

    def __init__(self) -> None:
        self.exact: dict[str, dict[str, Any]] = {}
        self.semantic_payload: dict[str, Any] | None = None
        self.l2_stores = 0

    async def get_corpus_version(self, tenant_id: str) -> int:
        return 1

    async def bump_corpus_version(self, tenant_id: str) -> int:
        return 2

    async def lookup_exact(
        self,
        *,
        tenant_id: str,
        corpus_version: int,
        doc_types: Sequence[DocType] | None,
        query: str,
    ) -> dict[str, Any] | None:
        return self.exact.get(query.strip().lower())

    async def lookup_semantic(
        self,
        *,
        tenant_id: str,
        corpus_version: int,
        doc_types: Sequence[DocType] | None,
        query_embedding: list[float],
    ) -> tuple[dict[str, Any], float] | None:
        if self.semantic_payload is not None:
            return self.semantic_payload, 0.98
        return None

    async def store(
        self,
        *,
        tenant_id: str,
        corpus_version: int,
        doc_types: Sequence[DocType] | None,
        query: str,
        query_embedding: list[float] | None,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        self.exact[query.strip().lower()] = payload
        if query_embedding is not None:
            self.l2_stores += 1
            self.semantic_payload = payload


class _UnusedRetriever:
    async def retrieve(self, **kwargs: Any) -> list[RetrievedChunk]:
        raise AssertionError("Retriever should not run on cache hits")


class _UnusedReranker:
    model_name = "stub-reranker"

    async def rerank(
        self, query: str, candidates: Sequence[RetrievedChunk], top_k: int = 5
    ) -> list[RerankedChunk]:
        raise AssertionError("Reranker should not run on cache hits")


class _UnusedLLM:
    async def generate(
        self, *, query: str, passages: Sequence[RerankedChunk]
    ) -> tuple[GroundedLLMResult, str]:
        raise AssertionError("LLM should not run on cache hits")


@pytest.mark.asyncio
async def test_l2_semantic_cache_hit_backfills_l1_exact_cache() -> None:
    """Paraphrase L2 hit must promote exact query into L1 so repeat hits L1 with 0 embeds."""
    settings = Settings(app_env="test")
    embedder = _StubEmbedder()
    cache = _InMemorySemanticCache()
    cache.semantic_payload = {
        "status": "answered",
        "answer": "Cached grounded answer [1].",
        "missing_evidence_reason": None,
        "citations": [],
        "model": "gemini-3.5-flash-lite",
        "reranker_model": "stub-reranker",
        "top_rerank_score": 0.95,
    }

    orchestrator = QueryOrchestrator(
        settings=settings,
        embedder=embedder,
        retriever=_UnusedRetriever(),
        reranker=_UnusedReranker(),
        llm=_UnusedLLM(),
        verifier=CitationVerifierAndHydrator(),
        cache=cache,
    )

    req = QueryRequest(tenant_id="acme-corp", query="What triggers ERR_SIG_4092 on SDK v2.4.1?")

    # 1st call: misses L1, embeds once, hits L2, and backfills L1 (without duplicating L2 vector)
    first = await orchestrator.execute(req)
    assert first.telemetry.cache_hit is True
    assert first.telemetry.cache_tier == "semantic"
    assert embedder.embed_query_calls == 1
    assert cache.l2_stores == 0

    # 2nd identical call: hits L1 directly with ZERO additional embedding calls!
    second = await orchestrator.execute(req)
    assert second.telemetry.cache_hit is True
    assert second.telemetry.cache_tier == "exact"
    assert embedder.embed_query_calls == 1


def test_ingest_rejects_oversized_file_and_strips_client_filename_path() -> None:
    settings = Settings(app_env="test", citeops_internal_api_key="")
    app = create_app(settings)

    captured_filenames: list[str] = []

    class _StubIngestion:
        async def ingest(self, **kwargs: Any) -> dict[str, Any]:
            captured_filenames.append(kwargs["filename"])
            return {
                "status": "indexed",
                "document_id": str(uuid4()),
                "tenant_id": kwargs["tenant_id"],
                "doc_title": "Test",
                "doc_type": kwargs["doc_type"],
                "version": kwargs["version"],
                "content_hash": "a" * 64,
                "page_count": 1,
                "chunk_count": 1,
                "corpus_version": 2,
                "latency_ms": 1,
            }

    with TestClient(app) as client:
        app.state.ingestion_orchestrator = _StubIngestion()

        # 1. Oversized upload rejected immediately with 413
        oversized = b"x" * (MAX_UPLOAD_BYTES + 16)
        r_big = client.post(
            "/v1/ingest",
            data={"tenant_id": "acme-corp", "doc_type": "runbook", "version": "v1.0"},
            files={"file": ("huge.md", oversized, "text/markdown")},
        )
        assert r_big.status_code == 413

        # 2. Path traversal / directory prefix stripped from filename
        r_ok = client.post(
            "/v1/ingest",
            data={"tenant_id": "acme-corp", "doc_type": "runbook", "version": "v1.0"},
            files={"file": ("../../etc/secret_notes.md", b"# Safe Doc", "text/markdown")},
        )
        assert r_ok.status_code == 200
        assert captured_filenames == ["secret_notes.md"]


def test_health_sanitizes_internal_errors_and_sets_security_headers() -> None:
    settings = Settings(app_env="test", citeops_internal_api_key="")
    app = create_app(settings)

    class _LeakyPool:
        def connection(self) -> Any:
            raise RuntimeError("FATAL: password authentication failed for user secret_dsn_user")

    class _LeakyRedis:
        async def ping(self) -> bool:
            raise ConnectionError("Error connecting to redis://secret:pw@internal-host:6379")

    with TestClient(app) as client:
        app.state.db_pool = _LeakyPool()
        app.state.redis = _LeakyRedis()

        resp = client.get("/v1/health")
        assert resp.status_code == 503
        body = resp.json()
        assert "secret_dsn_user" not in str(body)
        assert "internal-host" not in str(body)
        assert body["dependencies"]["postgres"]["detail"] == "PostgreSQL unavailable"
        assert body["dependencies"]["redis"]["detail"] == "Redis unavailable"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_query_sanitizes_llm_unavailable_503_detail() -> None:
    settings = Settings(app_env="test", citeops_internal_api_key="")
    app = create_app(settings)

    class _FailingOrchestrator:
        async def execute(self, payload: QueryRequest, *, trace_id: str | None = None) -> Any:
            raise LLMUnavailableError("secret upstream error https://api.groq.com/internal 404")

    with TestClient(app) as client:
        app.state.query_orchestrator = _FailingOrchestrator()
        resp = client.post(
            "/v1/query",
            json={"tenant_id": "acme-corp", "query": "What is the Sev-1 RTO under Section 4.2?"},
        )
        assert resp.status_code == 503
        assert resp.headers["Retry-After"] == "10"
        assert "api.groq.com" not in resp.json()["detail"]
