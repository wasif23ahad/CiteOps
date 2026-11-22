import math
import uuid
from collections.abc import Sequence

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from app.adapters.cache_redis import RedisSemanticCache, normalize_query
from app.core.config import Settings, get_settings
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


def _rotated_unit_vec(angle_rad: float, dim: int = 768) -> list[float]:
    vec = [0.0] * dim
    vec[0] = math.cos(angle_rad)
    vec[1] = math.sin(angle_rad)
    return vec


class _ScriptedEmbedder:
    """Returns exact vectors for specific queries so cosine similarity is deterministic."""

    def __init__(self, mapping: dict[str, list[float]]) -> None:
        self._mapping = mapping
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "scripted-embed"

    @property
    def dimensions(self) -> int:
        return 768

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [_rotated_unit_vec(0.0) for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        return self._mapping.get(text, _rotated_unit_vec(1.2))


class _StubRetriever:
    def __init__(self, chunk: RetrievedChunk) -> None:
        self._chunk = chunk

    async def retrieve(
        self,
        *,
        tenant_id: str,
        query_text: str,
        query_embedding: list[float],
        doc_types: Sequence[DocType] | None = None,
        candidate_limit: int = 25,
    ) -> list[RetrievedChunk]:
        return [self._chunk]


class _StubReranker:
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
            RerankedChunk(chunk=c, raw_logit=3.0, rerank_score=0.95)
            for c in candidates[:top_k]
        ]


class _CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        *,
        query: str,
        passages: Sequence[RerankedChunk],
    ) -> tuple[GroundedLLMResult, str]:
        self.calls += 1
        return (
            GroundedLLMResult(
                status="answered",
                answer="Pass the raw buffer to verifySignature() on SDK v2.4.1 [1].",
                used_passages=(
                    LLMUsedPassage(
                        passage_index=1,
                        supporting_quote="Pass the raw buffer to verifySignature()",
                    ),
                ),
            ),
            "gemini-3.8-flash",
        )


def test_normalize_query_collapses_case_whitespace_and_punctuation() -> None:
    assert normalize_query("  Why does ERR_SIG_4092   fail??? ") == "why does err_sig_4092 fail"


@pytest.mark.asyncio
async def test_redis_l1_l2_cache_isolation_and_corpus_version_invalidation() -> None:
    """Integration test against live Redis 8 proving L1, L2 >0.95, filter scope, and O(1) bump."""
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
        pytest.skip(f"Local Redis unavailable for semantic cache test: {exc}")

    run_id = uuid.uuid4().hex[:8]
    tenant_a = f"cache-acme-{run_id}"
    tenant_b = f"cache-globex-{run_id}"

    q_orig = "Why does ERR_SIG_4092 fail on SDK v2.4.1?"
    q_exact_norm = "  why does err_sig_4092   fail on sdk v2.4.1  "
    q_paraphrase = "What triggers error ERR_SIG_4092 in version 2.4.1?"
    q_unrelated = "What is the monthly uptime credit schedule?"

    # cos(0.0, 0.15) = 0.9888 (> 0.95 -> L2 hit); cos(0.0, 1.2) = 0.362 (< 0.95 -> miss)
    embedder = _ScriptedEmbedder(
        {
            q_orig: _rotated_unit_vec(0.0),
            q_paraphrase: _rotated_unit_vec(0.15),
            q_unrelated: _rotated_unit_vec(1.2),
        }
    )
    llm = _CountingLLM()
    chunk = RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        doc_title="Webhook Error Reference",
        doc_type="api_docs",
        version="v2.4.1",
        page_number=14,
        section_path="4.3 Errors",
        content="ERR_SIG_4092: Pass the raw buffer to verifySignature() on SDK v2.4.1.",
        contextual_content="ERR_SIG_4092",
        rrf_score=0.032,
    )
    cache = RedisSemanticCache(
        redis_client,
        similarity_threshold=0.95,
        max_entries=50,
        default_ttl_seconds=120,
    )
    test_settings = Settings(app_env="test", citeops_internal_api_key="")
    app = create_app(test_settings)
    app.state.query_orchestrator = QueryOrchestrator(
        settings=test_settings,
        embedder=embedder,
        retriever=_StubRetriever(chunk),
        reranker=_StubReranker(),
        llm=llm,
        verifier=CitationVerifierAndHydrator(),
        cache=cache,
    )

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Cold query -> cache miss (1 embed call, 1 LLM call)
            r1 = await client.post("/v1/query", json={"tenant_id": tenant_a, "query": q_orig})
            assert r1.status_code == 200
            assert r1.json()["telemetry"]["cache_hit"] is False
            assert r1.json()["telemetry"]["cache_tier"] == "miss"
            assert llm.calls == 1
            assert embedder.calls == 1

            # 2. L1 exact normalized hit -> < 50 ms, ZERO extra embed or LLM calls
            r2 = await client.post("/v1/query", json={"tenant_id": tenant_a, "query": q_exact_norm})
            assert r2.status_code == 200
            t2 = r2.json()["telemetry"]
            assert t2["cache_hit"] is True
            assert t2["cache_tier"] == "exact"
            assert t2["latency_ms"] < 50
            assert llm.calls == 1
            assert embedder.calls == 1

            # 3. L2 semantic paraphrase hit (cosine 0.9888 > 0.95) -> ZERO extra LLM calls
            r3 = await client.post("/v1/query", json={"tenant_id": tenant_a, "query": q_paraphrase})
            assert r3.status_code == 200
            t3 = r3.json()["telemetry"]
            assert t3["cache_hit"] is True
            assert t3["cache_tier"] == "semantic"
            assert t3["latency_ms"] < 50
            assert llm.calls == 1

            # 4. Different doc_types filter -> isolated cache miss
            r4 = await client.post(
                "/v1/query",
                json={"tenant_id": tenant_a, "query": q_orig, "doc_types": ["api_docs"]},
            )
            assert r4.status_code == 200
            assert r4.json()["telemetry"]["cache_hit"] is False
            assert llm.calls == 2

            # 5. Different tenant -> isolated cache miss (zero cross-tenant cache leak)
            r5 = await client.post("/v1/query", json={"tenant_id": tenant_b, "query": q_orig})
            assert r5.status_code == 200
            assert r5.json()["telemetry"]["cache_hit"] is False
            assert llm.calls == 3

            # 6. Bump corpus_version for tenant A -> invalidates tenant A in O(1), keeps tenant B!
            new_ver = await cache.bump_corpus_version(tenant_a)
            assert new_ver >= 2

            r6a = await client.post("/v1/query", json={"tenant_id": tenant_a, "query": q_orig})
            assert r6a.json()["telemetry"]["cache_hit"] is False
            assert llm.calls == 4

            r6b = await client.post("/v1/query", json={"tenant_id": tenant_b, "query": q_orig})
            assert r6b.json()["telemetry"]["cache_hit"] is True
            assert r6b.json()["telemetry"]["cache_tier"] == "exact"
            assert llm.calls == 4
    finally:
        # Clean up test keys in Redis
        for pattern in (
            f"tenant:version:{tenant_a}",
            f"tenant:version:{tenant_b}",
            f"cache:*:{tenant_a}:*",
            f"cache:*:{tenant_b}:*",
        ):
            keys = [k async for k in redis_client.scan_iter(match=pattern)]
            if keys:
                await redis_client.delete(*keys)
        await redis_client.aclose()


@pytest.mark.asyncio
async def test_semantic_cache_fails_open_when_redis_is_offline() -> None:
    class _BrokenRedis:
        async def get(self, *args: object, **kwargs: object) -> None:
            raise ConnectionError("Redis offline")

        async def incr(self, *args: object, **kwargs: object) -> None:
            raise ConnectionError("Redis offline")

        async def lrange(self, *args: object, **kwargs: object) -> None:
            raise ConnectionError("Redis offline")

        def pipeline(self, *args: object, **kwargs: object) -> "_BrokenRedis":
            return self

        def set(self, *args: object, **kwargs: object) -> None:
            return None

        async def execute(self) -> None:
            raise ConnectionError("Redis offline")

    cache = RedisSemanticCache(_BrokenRedis())  # type: ignore[arg-type]
    assert await cache.get_corpus_version("acme-corp") == 1
    assert (
        await cache.lookup_exact(
            tenant_id="acme-corp",
            corpus_version=1,
            doc_types=None,
            query="ERR_SIG_4092",
        )
        is None
    )
    assert (
        await cache.lookup_semantic(
            tenant_id="acme-corp",
            corpus_version=1,
            doc_types=None,
            query_embedding=_rotated_unit_vec(0.0),
        )
        is None
    )
    # Must not raise
    await cache.store(
        tenant_id="acme-corp",
        corpus_version=1,
        doc_types=None,
        query="ERR_SIG_4092",
        query_embedding=None,
        payload={"status": "answered"},
    )
