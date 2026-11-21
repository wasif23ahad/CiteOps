import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.core.rate_limit import SlidingWindowRateLimiter
from app.domain.models import (
    DocType,
    GroundedLLMResult,
    LLMUsedPassage,
    RerankedChunk,
    RetrievedChunk,
)
from app.main import create_app
from app.services.query import QueryOrchestrator
from app.services.verifier import CitationVerifierAndHydrator


class _InMemoryCache:
    def __init__(self) -> None:
        self._exact: dict[str, dict[str, Any]] = {}

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
        return self._exact.get(f"{tenant_id}:{query.strip().lower()}")

    async def lookup_semantic(
        self,
        *,
        tenant_id: str,
        corpus_version: int,
        doc_types: Sequence[DocType] | None,
        query_embedding: list[float],
    ) -> tuple[dict[str, Any], float] | None:
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
        self._exact[f"{tenant_id}:{query.strip().lower()}"] = payload


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
    async def retrieve(
        self,
        *,
        tenant_id: str,
        query_text: str,
        query_embedding: list[float],
        doc_types: Sequence[DocType] | None = None,
        candidate_limit: int = 25,
    ) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                doc_title="SLA",
                doc_type="sla_contract",
                version="v3.2",
                page_number=4,
                section_path="Section 4.2",
                content="AES-256-GCM encryption at rest.",
                contextual_content="AES-256-GCM",
                rrf_score=0.03,
            )
        ]


class _StubReranker:
    @property
    def model_name(self) -> str:
        return "stub-reranker"

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievedChunk],
        top_k: int = 5,
    ) -> list[RerankedChunk]:
        return [RerankedChunk(chunk=c, raw_logit=2.0, rerank_score=0.9) for c in candidates[:top_k]]


class _StubLLM:
    async def generate(
        self,
        *,
        query: str,
        passages: Sequence[RerankedChunk],
    ) -> tuple[GroundedLLMResult, str]:
        return (
            GroundedLLMResult(
                status="answered",
                answer="AES-256-GCM encryption is enforced at rest [1].",
                used_passages=(
                    LLMUsedPassage(
                        passage_index=1,
                        supporting_quote="AES-256-GCM encryption at rest.",
                    ),
                ),
            ),
            "gemini-3.8-flash",
        )


@pytest.mark.asyncio
async def test_rate_limiter_enforces_tenant_rpm_and_cache_hits_bypass_llm_budget() -> None:
    """Proves per-tenant 429 works AND cached hits bypass the global LLM-miss RPM cap."""
    limiter = SlidingWindowRateLimiter(
        redis_client=None,  # Deterministic in-memory sliding window
        tenant_rpm=4,
        global_llm_rpm=1,
        window_seconds=60,
    )
    settings = Settings(app_env="test", citeops_internal_api_key="")
    app = create_app(settings)
    app.state.query_orchestrator = QueryOrchestrator(
        settings=settings,
        embedder=_StubEmbedder(),
        retriever=_StubRetriever(),
        reranker=_StubReranker(),
        llm=_StubLLM(),
        verifier=CitationVerifierAndHydrator(),
        cache=_InMemoryCache(),
        rate_limiter=limiter,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. First cold query uses the 1 global LLM slot
        r1 = await client.post(
            "/v1/query",
            json={"tenant_id": "acme-corp", "query": "Is AES-256 enforced?"},
        )
        assert r1.status_code == 200
        assert r1.json()["telemetry"]["cache_hit"] is False

        # 2. Repeat query hits L1 cache -> bypasses exhausted global_llm_rpm=1!
        r2 = await client.post(
            "/v1/query",
            json={"tenant_id": "acme-corp", "query": "Is AES-256 enforced?"},
        )
        assert r2.status_code == 200
        assert r2.json()["telemetry"]["cache_hit"] is True

        # 3. Brand new uncached query hits global_llm_rpm=1 -> HTTP 429 + Retry-After
        r3 = await client.post(
            "/v1/query",
            json={"tenant_id": "acme-corp", "query": "What is the Sev-1 RTO window?"},
        )
        assert r3.status_code == 429
        assert int(r3.headers["Retry-After"]) >= 1
        assert r3.headers["X-RateLimit-Limit"] == "1"

        # 4. Fourth request still within tenant_rpm=4 via cache hit succeeds, fifth trips tenant 429
        r4 = await client.post(
            "/v1/query",
            json={"tenant_id": "acme-corp", "query": "Is AES-256 enforced?"},
        )
        assert r4.status_code == 200

        r5 = await client.post(
            "/v1/query",
            json={"tenant_id": "acme-corp", "query": "Is AES-256 enforced?"},
        )
        assert r5.status_code == 429
        assert r5.headers["X-RateLimit-Limit"] == "4"


@pytest.mark.asyncio
async def test_redis_lua_sliding_window_rate_limiter_enforces_exact_cap() -> None:
    settings = get_settings()
    redis_client = Redis.from_url(
        settings.redis_url,
        decode_responses=False,
        socket_connect_timeout=1.5,
        socket_timeout=1.5,
    )
    try:
        await redis_client.ping()
    except Exception as exc:
        await redis_client.aclose()
        pytest.skip(f"Local Redis unavailable for Lua rate limit test: {exc}")

    tenant = f"rl-test-{uuid.uuid4().hex[:8]}"
    limiter = SlidingWindowRateLimiter(
        redis_client=redis_client,
        tenant_rpm=2,
        global_llm_rpm=10,
        window_seconds=60,
    )
    try:
        d1 = await limiter.check_tenant(tenant)
        assert d1.allowed is True
        assert d1.remaining == 1

        d2 = await limiter.check_tenant(tenant)
        assert d2.allowed is True
        assert d2.remaining == 0

        from app.core.rate_limit import RateLimitExceededError

        with pytest.raises(RateLimitExceededError) as exc_info:
            await limiter.check_tenant(tenant)
        assert exc_info.value.decision.retry_after_seconds >= 1
    finally:
        await redis_client.delete(f"rl:tenant:{tenant}")
        await redis_client.aclose()
