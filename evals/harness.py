"""Shared eval helpers: corpus seeding, deterministic retrieval scoring, and DeepEval judge."""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import re
import struct
import sys
import time
import uuid
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
from psycopg_pool import AsyncConnectionPool

ROOT_DIR = Path(__file__).resolve().parent.parent
API_DIR = ROOT_DIR / "apps" / "api"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from scripts.seed_demo import DEMO_DOCS_DIR, SEED_MANIFEST  # noqa: E402

from app.adapters.corpus_version import CorpusVersionStore  # noqa: E402
from app.adapters.embeddings_gemini import create_embedding_adapter  # noqa: E402
from app.adapters.parser_pymupdf import PyMuPDFDocumentParser  # noqa: E402
from app.adapters.repo_postgres import PostgresDocumentRepository  # noqa: E402
from app.adapters.reranker_fastembed import FastEmbedReranker  # noqa: E402
from app.adapters.retriever_postgres import PostgresHybridRetriever  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.domain.models import DocType, RerankedChunk, RetrievedChunk  # noqa: E402
from app.services.chunker import StructureAwareChunker  # noqa: E402
from app.services.ingestion import IngestionOrchestrator  # noqa: E402
from evals.loader import ExpectedSource, GoldenCase  # noqa: E402

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_.-]*")
_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")

# Ground-truth document titles owned by each demo tenant (for cross-tenant leakage verification)
TENANT_OWNED_TITLES: dict[str, frozenset[str]] = {
    "acme-corp": frozenset(
        item.doc_title for item in SEED_MANIFEST if item.tenant_id == "acme-corp"
    ),
    "globex-io": frozenset(
        item.doc_title for item in SEED_MANIFEST if item.tenant_id == "globex-io"
    ),
}


class DeterministicHashEmbedder:
    """
    Zero-API-key deterministic 768-dim signed feature-hashing embedder for offline CI retrieval
    tests (e.g. forked PRs without GEMINI_API_KEY). Preserves word unigrams, bigrams, and
    subword trigrams so pgvector HNSW + PostgreSQL tsvector RRF + ONNX reranking are exercised
    end-to-end with zero external calls.
    """

    def __init__(self, dimensions: int = 768) -> None:
        self._dimensions = dimensions

    @property
    def model_name(self) -> str:
        return "deterministic-hash-768"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _encode_one(self, text: str) -> list[float]:
        vec = np.zeros(self._dimensions, dtype=np.float32)
        tokens = _WORD_RE.findall(text.lower())
        features: list[tuple[str, float]] = []
        for idx, tok in enumerate(tokens):
            features.append((f"w:{tok}", 2.0))
            if idx + 1 < len(tokens):
                features.append((f"b:{tok}_{tokens[idx + 1]}", 1.5))
            if len(tok) >= 4:
                for pos in range(len(tok) - 2):
                    features.append((f"c:{tok[pos : pos + 3]}", 0.4))

        for feat, weight in features:
            digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
            bucket, sign_byte = struct.unpack("<IB", digest[:5])
            idx = bucket % self._dimensions
            sign = 1.0 if (sign_byte & 1) == 0 else -1.0
            vec[idx] += sign * weight

        norm = float(np.linalg.norm(vec))
        if norm > 0.0:
            vec = vec / norm
        else:
            vec[0] = 1.0
        return vec.tolist()

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._encode_one(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._encode_one(text)


@dataclass(frozen=True, slots=True)
class RetrievalCaseResult:
    case_id: str
    category: str
    tenant_id: str
    expected_status: str
    retrieved_count: int
    top_rerank_score: float | None
    expected_source_count: int
    matched_source_count: int
    source_recall: float | None  # None for abstention/cross_tenant cases
    leaked_substrings: tuple[str, ...]
    leaked_titles: tuple[str, ...]
    top_sources: tuple[str, ...]


@dataclass(slots=True)
class RetrievalSuiteSummary:
    mode: str
    total_cases: int
    answerable_cases: int
    mean_recall_at_5: float
    full_hit_rate: float
    leakage_count: int
    leakage_rate: float
    category_recall: dict[str, float] = field(default_factory=dict)
    results: list[RetrievalCaseResult] = field(default_factory=list)


def _source_matches(expected: ExpectedSource, chunk: RetrievedChunk) -> bool:
    if chunk.doc_title.strip().lower() != expected.doc_title.strip().lower():
        return False
    if expected.page_number is not None and chunk.page_number != expected.page_number:
        return False
    return True


def evaluate_retrieval_case(
    case: GoldenCase,
    *,
    candidates: Sequence[RetrievedChunk],
    reranked: Sequence[RerankedChunk],
) -> RetrievalCaseResult:
    top_chunks = [item.chunk for item in reranked]
    top_score = reranked[0].rerank_score if reranked else None

    # 1. Cross-tenant leakage scan across ALL retrieved candidates (stricter than top-5)
    combined_lower = "\n".join(c.content.lower() for c in candidates)
    leaked_substrings = tuple(
        sub for sub in case.forbidden_substrings if sub.lower() in combined_lower
    )

    allowed_titles = TENANT_OWNED_TITLES.get(case.tenant_id)
    leaked_titles: tuple[str, ...] = ()
    if allowed_titles is not None:
        leaked_titles = tuple(
            sorted({c.doc_title for c in candidates if c.doc_title not in allowed_titles})
        )

    # 2. Context Recall@5 for answerable cases
    expected_count = len(case.expected_sources)
    matched_count = 0
    source_recall: float | None = None
    if case.expected_status == "answered" and expected_count > 0:
        for exp in case.expected_sources:
            if any(_source_matches(exp, ch) for ch in top_chunks):
                matched_count += 1
        source_recall = matched_count / expected_count

    top_sources = tuple(
        f"{item.chunk.doc_title} (p.{item.chunk.page_number}, score={item.rerank_score:.2f})"
        for item in reranked[:5]
    )

    return RetrievalCaseResult(
        case_id=case.id,
        category=case.category,
        tenant_id=case.tenant_id,
        expected_status=case.expected_status,
        retrieved_count=len(candidates),
        top_rerank_score=top_score,
        expected_source_count=expected_count,
        matched_source_count=matched_count,
        source_recall=source_recall,
        leaked_substrings=leaked_substrings,
        leaked_titles=leaked_titles,
        top_sources=top_sources,
    )


async def ensure_live_seeded_corpus(
    *,
    settings: Settings,
    pool: AsyncConnectionPool,
) -> None:
    """
    Ensure `acme-corp` (4 docs) and `globex-io` (2 docs) are indexed in PostgreSQL
    using the configured live embedding provider (idempotent via content_hash).
    """
    repo = PostgresDocumentRepository(pool)
    acme_docs = await repo.list_documents("acme-corp")
    globex_docs = await repo.list_documents("globex-io")
    if len(acme_docs) >= 4 and len(globex_docs) >= 2:
        return

    embedder = create_embedding_adapter(settings)
    orchestrator = IngestionOrchestrator(
        parser=PyMuPDFDocumentParser(),
        chunker=StructureAwareChunker(),
        embedder=embedder,
        repo=repo,
        corpus_versions=CorpusVersionStore(None),
        cpu_semaphore=asyncio.Semaphore(2),
    )

    for item in SEED_MANIFEST:
        file_path = DEMO_DOCS_DIR / item.relative_path
        raw_bytes = file_path.read_bytes()
        doc_type: DocType = item.doc_type  # type: ignore[assignment]
        await orchestrator.ingest(
            tenant_id=item.tenant_id,
            doc_type=doc_type,
            version=item.version,
            filename=file_path.name,
            file_bytes=raw_bytes,
            doc_title=item.doc_title,
        )


async def seed_ephemeral_offline_corpus(
    *,
    pool: AsyncConnectionPool,
) -> tuple[dict[str, str], DeterministicHashEmbedder, list[str]]:
    """
    Seed ephemeral RLS-isolated tenants using `DeterministicHashEmbedder` so CI PRs
    without `GEMINI_API_KEY` still execute the full 50-question retrieval benchmark.
    """
    run_id = uuid.uuid4().hex[:8]
    tenant_map = {
        "acme-corp": f"eval-acme-{run_id}",
        "globex-io": f"eval-globex-{run_id}",
    }
    embedder = DeterministicHashEmbedder(dimensions=768)
    repo = PostgresDocumentRepository(pool)
    orchestrator = IngestionOrchestrator(
        parser=PyMuPDFDocumentParser(),
        chunker=StructureAwareChunker(),
        embedder=embedder,
        repo=repo,
        corpus_versions=CorpusVersionStore(None),
        cpu_semaphore=asyncio.Semaphore(2),
    )

    for item in SEED_MANIFEST:
        file_path = DEMO_DOCS_DIR / item.relative_path
        raw_bytes = file_path.read_bytes()
        doc_type: DocType = item.doc_type  # type: ignore[assignment]
        await orchestrator.ingest(
            tenant_id=tenant_map[item.tenant_id],
            doc_type=doc_type,
            version=item.version,
            filename=file_path.name,
            file_bytes=raw_bytes,
            doc_title=item.doc_title,
        )

    return tenant_map, embedder, list(tenant_map.values())


def cleanup_tenants(admin_conninfo: str, tenant_ids: Sequence[str]) -> None:
    if not tenant_ids:
        return
    with psycopg.connect(admin_conninfo, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE id = ANY(%s)", (list(tenant_ids),))


async def run_deterministic_retrieval_suite(
    *,
    settings: Settings,
    pool: AsyncConnectionPool,
    cases: Sequence[GoldenCase],
    top_k: int = 5,
    force_offline: bool = False,
) -> RetrievalSuiteSummary:
    """Run zero-LLM retrieval + ONNX reranking across the golden dataset."""
    env_offline = os.getenv("EVAL_FORCE_OFFLINE", "").strip().lower() in {"1", "true", "yes"}
    use_live = (
        not force_offline
        and not env_offline
        and settings.embedding_provider == "gemini"
        and bool(settings.gemini_api_key)
    )

    ephemeral_tenants: list[str] = []
    if use_live:
        await ensure_live_seeded_corpus(settings=settings, pool=pool)
        embedder: Any = create_embedding_adapter(settings)
        tenant_map = {"acme-corp": "acme-corp", "globex-io": "globex-io"}
        mode = f"live ({embedder.model_name})"
    else:
        tenant_map, embedder, ephemeral_tenants = await seed_ephemeral_offline_corpus(pool=pool)
        mode = f"offline ({embedder.model_name})"

    retriever = PostgresHybridRetriever(pool)
    reranker = FastEmbedReranker(
        model_name=settings.reranker_model_name,
        cpu_semaphore=asyncio.Semaphore(2),
    )

    results: list[RetrievalCaseResult] = []
    try:
        # Embed all queries cleanly in batch (1 API call in live mode, instant in offline mode!)
        query_texts = [c.query for c in cases]
        query_embeddings: list[list[float]] = []
        if use_live:
            # Batch query embeddings to respect Gemini free-tier RPM (1–2 calls for all 50 Qs!)
            for start in range(0, len(query_texts), 50):
                batch = query_texts[start : start + 50]
                batch_vecs = await asyncio.to_thread(
                    embedder._embed_batch_sync, batch, "RETRIEVAL_QUERY"
                )
                query_embeddings.extend(batch_vecs)
        else:
            for q in query_texts:
                query_embeddings.append(await embedder.embed_query(q))

        for case, q_vec in zip(cases, query_embeddings, strict=True):
            actual_tenant = tenant_map[case.tenant_id]
            doc_types: list[DocType] | None = (
                list(case.doc_types)  # type: ignore[arg-type]
                if case.doc_types
                else None
            )
            candidates = await retriever.retrieve(
                tenant_id=actual_tenant,
                query_text=case.query,
                query_embedding=q_vec,
                doc_types=doc_types,
                candidate_limit=settings.rerank_candidate_count,
            )
            reranked = await reranker.rerank(case.query, candidates, top_k=top_k)
            results.append(
                evaluate_retrieval_case(case, candidates=candidates, reranked=reranked)
            )
    finally:
        if ephemeral_tenants:
            cleanup_tenants(settings.database_admin_url, ephemeral_tenants)

    answerable = [r for r in results if r.source_recall is not None]
    mean_recall = (
        sum(r.source_recall for r in answerable if r.source_recall is not None) / len(answerable)
        if answerable
        else 0.0
    )
    full_hits = sum(1 for r in answerable if r.source_recall == 1.0)
    full_hit_rate = full_hits / len(answerable) if answerable else 0.0

    leakage_count = sum(1 for r in results if r.leaked_substrings or r.leaked_titles)
    leakage_rate = leakage_count / len(results) if results else 0.0

    category_recall: dict[str, float] = {}
    for cat in ("exact_code", "compliance_sla", "multi_hop"):
        cat_rows = [r for r in answerable if r.category == cat and r.source_recall is not None]
        if cat_rows:
            category_recall[cat] = sum(
                r.source_recall for r in cat_rows if r.source_recall is not None
            ) / len(cat_rows)

    return RetrievalSuiteSummary(
        mode=mode,
        total_cases=len(results),
        answerable_cases=len(answerable),
        mean_recall_at_5=round(mean_recall, 4),
        full_hit_rate=round(full_hit_rate, 4),
        leakage_count=leakage_count,
        leakage_rate=round(leakage_rate, 4),
        category_recall={k: round(v, 4) for k, v in category_recall.items()},
        results=results,
    )


def has_valid_inline_citations(answer: str, citation_indices: Sequence[int]) -> bool:
    markers = {int(m) for m in _CITATION_MARKER_RE.findall(answer)}
    if not markers or not citation_indices:
        return False
    valid_set = set(citation_indices)
    return markers.issubset(valid_set)


def percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[lower])
    frac = rank - lower
    return float(ordered[lower] * (1.0 - frac) + ordered[upper] * frac)


_RETRY_DELAY_RE = re.compile(
    r"(?:retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s|retry in (\d+(?:\.\d+)?)s)",
    re.IGNORECASE,
)


def parse_retry_delay_seconds(error_text: str, default_wait: float = 15.0) -> float:
    """Extract server-suggested retry delay from Gemini 429 RESOURCE_EXHAUSTED errors."""
    match = _RETRY_DELAY_RE.search(error_text)
    if match:
        raw = match.group(1) or match.group(2)
        if raw:
            return min(float(raw) + 2.5, 70.0)
    return default_wait


def is_transient_rate_or_capacity_error(error_text: str) -> bool:
    upper = error_text.upper()
    return any(
        token in upper
        for token in ("429", "503", "504", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED")
    )


class SlidingWindowRPMGate:
    """
    In-process sliding-window rate pacer shared across RAG generation and DeepEval judge
    calls so evaluation suites stay safely beneath Google AI Studio Free Tier's 15 RPM cap.
    """

    def __init__(
        self,
        *,
        rpm_budget: int = 13,
        window_seconds: float = 61.0,
        min_spacing_seconds: float = 0.35,
    ) -> None:
        self._rpm_budget = max(1, rpm_budget)
        self._window_seconds = window_seconds
        self._min_spacing_seconds = max(0.0, min_spacing_seconds)
        self._timestamps: deque[float] = deque()
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self) -> None:
        lock = self._get_lock()
        while True:
            wait_s = 0.0
            async with lock:
                now = time.monotonic()
                while self._timestamps and (now - self._timestamps[0]) >= self._window_seconds:
                    self._timestamps.popleft()

                if len(self._timestamps) >= self._rpm_budget:
                    wait_s = self._window_seconds - (now - self._timestamps[0]) + 0.25
                elif self._timestamps and self._min_spacing_seconds > 0.0:
                    since_last = now - self._timestamps[-1]
                    if since_last < self._min_spacing_seconds:
                        wait_s = self._min_spacing_seconds - since_last

                if wait_s <= 0.0:
                    self._timestamps.append(now)
                    return
            await asyncio.sleep(wait_s)

    def acquire_sync(self) -> None:
        while True:
            now = time.monotonic()
            while self._timestamps and (now - self._timestamps[0]) >= self._window_seconds:
                self._timestamps.popleft()

            if len(self._timestamps) >= self._rpm_budget:
                wait_s = self._window_seconds - (now - self._timestamps[0]) + 0.25
                time.sleep(wait_s)
                continue
            if self._timestamps and self._min_spacing_seconds > 0.0:
                since_last = now - self._timestamps[-1]
                if since_last < self._min_spacing_seconds:
                    time.sleep(self._min_spacing_seconds - since_last)
                    continue
            self._timestamps.append(time.monotonic())
            return


async def execute_query_with_retry(
    *,
    orchestrator: Any,
    request: Any,
    rpm_gate: SlidingWindowRPMGate | None = None,
    max_attempts: int = 4,
) -> Any:
    """Execute a QueryOrchestrator request with automatic 429/503 cooldown retry for evals."""
    for attempt in range(max_attempts):
        if rpm_gate is not None:
            await rpm_gate.acquire()
        try:
            return await orchestrator.execute(request)
        except Exception as exc:
            err_text = str(exc)
            if not is_transient_rate_or_capacity_error(err_text) or attempt == max_attempts - 1:
                raise
            wait_s = parse_retry_delay_seconds(err_text, default_wait=20.0)
            print(
                f"  [eval-pacer] Upstream 429/503 on query; sleeping {wait_s:.1f}s "
                f"(attempt {attempt + 1}/{max_attempts})...",
                flush=True,
            )
            await asyncio.sleep(wait_s)
            # Clear router cooldown so retry immediately uses the refreshed quota window
            llm = getattr(orchestrator, "_llm", None)
            cooldowns = getattr(llm, "_cooldown_until", None)
            if isinstance(cooldowns, dict):
                cooldowns.clear()
    raise RuntimeError("Unreachable retry exhaustion in execute_query_with_retry")


def build_paced_gemini_judge(
    *,
    settings: Settings,
    max_concurrent: int = 2,
    delay_seconds: float = 0.5,
    rpm_gate: SlidingWindowRPMGate | None = None,
) -> Any:
    """
    Build a free-tier-safe DeepEval `GeminiModel` pointing at `settings.gemini_fallback_model`
    (`gemini-3.5-flash-lite`) with bounded concurrency, shared RPM pacing, and 429 retryDelay.
    """
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    from deepeval.models import GeminiModel
    from google.genai import types as genai_types

    judge_model_name = settings.gemini_fallback_model
    shared_gate = rpm_gate or SlidingWindowRPMGate(
        rpm_budget=int(os.getenv("EVAL_RPM_BUDGET", "13")),
        min_spacing_seconds=max(0.25, delay_seconds),
    )

    class PacedGeminiJudge(GeminiModel):
        def __init__(self) -> None:
            super().__init__(
                model=judge_model_name,
                api_key=settings.gemini_api_key,
                http_options=genai_types.HttpOptions(timeout=35_000),
            )
            self._semaphore: asyncio.Semaphore | None = None
            self._max_concurrent = max(1, max_concurrent)
            self._rpm_gate = shared_gate

        def _ensure_semaphore(self) -> asyncio.Semaphore:
            if self._semaphore is None:
                self._semaphore = asyncio.Semaphore(self._max_concurrent)
            return self._semaphore

        async def a_generate(
            self,
            prompt: str,
            schema: Any = None,
            audio: Any = None,
        ) -> Any:
            sem = self._ensure_semaphore()
            for attempt in range(5):
                async with sem:
                    await self._rpm_gate.acquire()
                    try:
                        return await super().a_generate(prompt, schema=schema, audio=audio)
                    except Exception as exc:
                        err = str(exc)
                        if not is_transient_rate_or_capacity_error(err) or attempt == 4:
                            raise
                        wait_s = parse_retry_delay_seconds(err, default_wait=15.0)
                print(
                    f"  [judge-pacer] 429/503 from {judge_model_name}; sleeping {wait_s:.1f}s "
                    f"(attempt {attempt + 1}/5)...",
                    flush=True,
                )
                await asyncio.sleep(wait_s)
            raise RuntimeError("Unreachable retry exhaustion in PacedGeminiJudge.a_generate")

        def generate(
            self,
            prompt: str,
            schema: Any = None,
            audio: Any = None,
        ) -> Any:
            for attempt in range(5):
                self._rpm_gate.acquire_sync()
                try:
                    return super().generate(prompt, schema=schema, audio=audio)
                except Exception as exc:
                    err = str(exc)
                    if not is_transient_rate_or_capacity_error(err) or attempt == 4:
                        raise
                    wait_s = parse_retry_delay_seconds(err, default_wait=15.0)
                print(
                    f"  [judge-pacer] 429/503 from {judge_model_name}; sleeping {wait_s:.1f}s "
                    f"(attempt {attempt + 1}/5)...",
                    flush=True,
                )
                time.sleep(wait_s)
            raise RuntimeError("Unreachable retry exhaustion in PacedGeminiJudge.generate")

    return PacedGeminiJudge()


@dataclass(frozen=True, slots=True)
class DeepEvalCaseScores:
    case_id: str
    faithfulness: float
    answer_relevancy: float
    contextual_recall: float


async def measure_deepeval_case(
    *,
    case_id: str,
    query: str,
    actual_answer: str,
    expected_answer: str,
    retrieval_context: list[str],
    judge_model: Any,
) -> DeepEvalCaseScores:
    """Measure Faithfulness, Answer Relevancy, and Contextual Recall for one answerable case."""
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualRecallMetric,
        FaithfulnessMetric,
    )
    from deepeval.test_case import LLMTestCase

    ctx_items: list[Any] = list(retrieval_context)
    test_case = LLMTestCase(
        input=query,
        actual_output=actual_answer,
        expected_output=expected_answer,
        retrieval_context=ctx_items,
    )

    faithfulness = FaithfulnessMetric(
        threshold=0.90,
        model=judge_model,
        include_reason=False,
        async_mode=True,
    )
    relevancy = AnswerRelevancyMetric(
        threshold=0.85,
        model=judge_model,
        include_reason=False,
        async_mode=True,
    )
    recall = ContextualRecallMetric(
        threshold=0.85,
        model=judge_model,
        include_reason=False,
        async_mode=True,
    )

    await faithfulness.a_measure(test_case, _show_indicator=False)
    await relevancy.a_measure(test_case, _show_indicator=False)
    await recall.a_measure(test_case, _show_indicator=False)

    return DeepEvalCaseScores(
        case_id=case_id,
        faithfulness=round(float(faithfulness.score or 0.0), 4),
        answer_relevancy=round(float(relevancy.score or 0.0), 4),
        contextual_recall=round(float(recall.score or 0.0), 4),
    )
