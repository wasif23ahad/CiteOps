import uuid
from collections.abc import Sequence

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.llm_router import LLMUnavailableError
from app.core.config import Settings
from app.domain.models import (
    DocType,
    GroundedLLMResult,
    LLMUsedPassage,
    QueryAuditRecord,
    RerankedChunk,
    RetrievedChunk,
    TenantMetricsSummary,
)
from app.main import create_app
from app.services.query import QueryOrchestrator
from app.services.verifier import CitationVerifierAndHydrator


class _StubEmbedder:
    @property
    def model_name(self) -> str:
        return "stub-embed"

    @property
    def dimensions(self) -> int:
        return 768

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.1] * 768 for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [0.1] * 768


class _StubRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks

    async def retrieve(
        self,
        *,
        tenant_id: str,
        query_text: str,
        query_embedding: list[float],
        doc_types: Sequence[DocType] | None = None,
        candidate_limit: int = 25,
    ) -> list[RetrievedChunk]:
        return self._chunks


class _StubReranker:
    def __init__(self, score: float) -> None:
        self._score = score

    @property
    def model_name(self) -> str:
        return "Xenova/ms-marco-MiniLM-L-6-v2"

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievedChunk],
        top_k: int = 5,
    ) -> list[RerankedChunk]:
        return [
            RerankedChunk(chunk=c, raw_logit=1.0, rerank_score=self._score)
            for c in candidates[:top_k]
        ]


class _SpyLLM:
    def __init__(
        self,
        result: GroundedLLMResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls = 0
        self._result = result
        self._error = error

    async def generate(
        self,
        *,
        query: str,
        passages: Sequence[RerankedChunk],
    ) -> tuple[GroundedLLMResult, str]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result, "gemini-3.8-flash"


class _SpyAuditRepo:
    def __init__(self) -> None:
        self.records: list[QueryAuditRecord] = []

    async def record_query(self, record: QueryAuditRecord) -> None:
        self.records.append(record)

    async def get_metrics_summary(self, tenant_id: str) -> TenantMetricsSummary:
        return TenantMetricsSummary(
            tenant_id=tenant_id,
            total_queries=len(self.records),
            cache_hit_rate=0.0,
            exact_cache_hits=0,
            semantic_cache_hits=0,
            abstention_rate=0.0,
            p50_latency_ms=None,
            p95_latency_ms=None,
            p95_cache_hit_ms=None,
            p95_cache_miss_ms=None,
        )


def _sample_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        doc_title="Webhook Integration & Error Reference",
        doc_type="api_docs",
        version="v2.4.1",
        page_number=14,
        section_path="4.3 Webhook Error Codes > ERR_SIG_4092",
        content=(
            "ERR_SIG_4092 occurs on SDK v2.4.1 when JSON middleware mutates raw bytes "
            "before HMAC-SHA256 verification. Pass the raw byte buffer to verifySignature()."
        ),
        contextual_content="ERR_SIG_4092",
        rrf_score=0.032,
    )


@pytest.mark.asyncio
async def test_gate1_abstains_without_calling_llm_when_rerank_score_below_threshold() -> None:
    settings = Settings(app_env="test", citeops_internal_api_key="", min_rerank_score=0.35)
    llm = _SpyLLM(
        result=GroundedLLMResult(status="answered", answer="Should never run [1]."),
    )
    audit = _SpyAuditRepo()

    app = create_app(settings)
    app.state.query_orchestrator = QueryOrchestrator(
        settings=settings,
        embedder=_StubEmbedder(),
        retriever=_StubRetriever([_sample_chunk()]),
        reranker=_StubReranker(score=0.14),
        llm=llm,
        verifier=CitationVerifierAndHydrator(),
        audit_repo=audit,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/query",
            json={"tenant_id": "acme-corp", "query": "Is FedRAMP High authorized?"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []
    assert body["telemetry"]["llm_ms"] == 0
    assert body["telemetry"]["model"] == "none (gate_1_abstain)"
    assert llm.calls == 0
    assert len(audit.records) == 1
    assert audit.records[0].status == "insufficient_evidence"


@pytest.mark.asyncio
async def test_gate2_returns_verified_hydrated_answer_and_records_audit() -> None:
    settings = Settings(app_env="test", citeops_internal_api_key="", min_rerank_score=0.35)
    chunk = _sample_chunk()
    llm = _SpyLLM(
        result=GroundedLLMResult(
            status="answered",
            answer="Pass the raw byte buffer to verifySignature() on SDK v2.4.1 [1].",
            used_passages=(
                LLMUsedPassage(
                    passage_index=1,
                    supporting_quote="Pass the raw byte buffer to verifySignature()",
                ),
            ),
        )
    )
    audit = _SpyAuditRepo()

    app = create_app(settings)
    app.state.query_orchestrator = QueryOrchestrator(
        settings=settings,
        embedder=_StubEmbedder(),
        retriever=_StubRetriever([chunk]),
        reranker=_StubReranker(score=0.94),
        llm=llm,
        verifier=CitationVerifierAndHydrator(),
        audit_repo=audit,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/query",
            json={"tenant_id": "acme-corp", "query": "How do I fix ERR_SIG_4092 on v2.4.1?"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "answered"
    assert len(body["citations"]) == 1
    assert body["citations"][0]["document_id"] == str(chunk.document_id)
    assert body["citations"][0]["page_number"] == 14
    assert body["citations"][0]["rerank_score"] == 0.94
    assert body["telemetry"]["model"] == "gemini-3.8-flash"
    assert llm.calls == 1
    assert len(audit.records) == 1


@pytest.mark.asyncio
async def test_all_llms_unavailable_returns_503_with_retry_after() -> None:
    settings = Settings(app_env="test", citeops_internal_api_key="", min_rerank_score=0.35)
    llm = _SpyLLM(error=LLMUnavailableError("All providers exhausted"))

    app = create_app(settings)
    app.state.query_orchestrator = QueryOrchestrator(
        settings=settings,
        embedder=_StubEmbedder(),
        retriever=_StubRetriever([_sample_chunk()]),
        reranker=_StubReranker(score=0.92),
        llm=llm,
        verifier=CitationVerifierAndHydrator(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/query",
            json={"tenant_id": "acme-corp", "query": "How do I fix ERR_SIG_4092?"},
        )

    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "10"
