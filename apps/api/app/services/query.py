import time
import uuid
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.telemetry import TelemetryTracer
from app.domain.models import CacheTier, QueryAuditRecord
from app.domain.ports import (
    AuditRepoPort,
    EmbeddingPort,
    GroundedLLMPort,
    HybridRetrieverPort,
    RerankerPort,
    SemanticCachePort,
)
from app.schemas.query import CitationItem, QueryRequest, QueryResponse, QueryTelemetry
from app.services.verifier import CitationVerifierAndHydrator

logger = get_logger(__name__)

_GATE1_ABSTAIN_CACHE_TTL_S = 3600


class QueryOrchestrator:
    """
    End-to-end citation-locked query pipeline:
      Tenant Rate Limit -> L1 Exact Cache -> Embed -> L2 Semantic Cache ->
      Hybrid RRF (RLS) -> Calibrated ONNX Rerank -> Gate 1 Abstention ->
      Global LLM-Miss Budget -> Resilient LLM -> Gate 2 Citation Verifier ->
      Versioned Cache Store -> Audit Log + Langfuse OTel Spans
    """

    def __init__(
        self,
        *,
        settings: Settings,
        embedder: EmbeddingPort,
        retriever: HybridRetrieverPort,
        reranker: RerankerPort,
        llm: GroundedLLMPort,
        verifier: CitationVerifierAndHydrator,
        audit_repo: AuditRepoPort | None = None,
        cache: SemanticCachePort | None = None,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        telemetry: TelemetryTracer | None = None,
    ) -> None:
        self._settings = settings
        self._embedder = embedder
        self._retriever = retriever
        self._reranker = reranker
        self._llm = llm
        self._verifier = verifier
        self._audit_repo = audit_repo
        self._cache = cache
        self._rate_limiter = rate_limiter
        self._telemetry = telemetry

    async def execute(
        self,
        request: QueryRequest,
        *,
        trace_id: str | None = None,
    ) -> QueryResponse:
        total_started = time.perf_counter()
        req_id = trace_id or f"tr_{uuid.uuid4().hex[:16]}"
        tracer = self._telemetry

        if tracer is not None:
            with tracer.trace_query(
                tenant_id=request.tenant_id,
                request_id=req_id,
                query=request.query,
            ) as (root_obs, resolved_trace):
                response = await self._execute_pipeline(
                    request=request,
                    resolved_trace=resolved_trace,
                    total_started=total_started,
                )
                root_obs.update(
                    output={"status": response.status, "citations": len(response.citations)},
                    metadata={
                        "cache_hit": response.telemetry.cache_hit,
                        "cache_tier": response.telemetry.cache_tier,
                        "model": response.telemetry.model,
                        "latency_ms": response.telemetry.latency_ms,
                        "top_rerank_score": response.telemetry.top_rerank_score,
                    },
                )
                return response

        return await self._execute_pipeline(
            request=request,
            resolved_trace=req_id,
            total_started=total_started,
        )

    async def _execute_pipeline(
        self,
        *,
        request: QueryRequest,
        resolved_trace: str,
        total_started: float,
    ) -> QueryResponse:
        # 1. Per-tenant sliding-window admission control
        if self._rate_limiter is not None:
            with self._span("rate_limit.tenant", input_data={"tenant_id": request.tenant_id}):
                await self._rate_limiter.check_tenant(request.tenant_id)

        corpus_version = 1
        if self._cache is not None:
            corpus_version = await self._cache.get_corpus_version(request.tenant_id)

            # 2. L1 Exact Normalized Cache (zero embedding, zero DB, zero LLM -> <15 ms)
            with self._span("cache.l1_exact_lookup") as l1_span:
                l1_payload = await self._cache.lookup_exact(
                    tenant_id=request.tenant_id,
                    corpus_version=corpus_version,
                    doc_types=request.doc_types,
                    query=request.query,
                )
                l1_span.update(output={"hit": l1_payload is not None})

            if l1_payload is not None:
                return await self._finalize_cache_hit(
                    tenant_id=request.tenant_id,
                    cached_payload=l1_payload,
                    cache_tier="exact",
                    total_started=total_started,
                    resolved_trace=resolved_trace,
                )

        # 3. Embed query
        embed_started = time.perf_counter()
        with self._span(
            "embeddings.embed_query",
            as_type="embedding",
            model=self._embedder.model_name,
        ):
            query_embedding = await self._embedder.embed_query(request.query)
        embed_ms = int((time.perf_counter() - embed_started) * 1000)

        # 4. L2 Tenant-Bounded Semantic Cache (cosine > 0.95)
        if self._cache is not None:
            with self._span("cache.l2_semantic_lookup") as l2_span:
                l2_match = await self._cache.lookup_semantic(
                    tenant_id=request.tenant_id,
                    corpus_version=corpus_version,
                    doc_types=request.doc_types,
                    query_embedding=query_embedding,
                )
                l2_span.update(
                    output={
                        "hit": l2_match is not None,
                        "similarity": l2_match[1] if l2_match else None,
                    }
                )
            if l2_match is not None:
                return await self._finalize_cache_hit(
                    tenant_id=request.tenant_id,
                    cached_payload=l2_match[0],
                    cache_tier="semantic",
                    total_started=total_started,
                    resolved_trace=resolved_trace,
                )

        # 5. Hybrid RRF Retrieval (strict PostgreSQL RLS)
        ret_started = time.perf_counter()
        with self._span(
            "retrieval.postgres_hybrid_rrf",
            as_type="retriever",
            metadata={"tenant_id": request.tenant_id, "doc_types": request.doc_types},
        ) as ret_span:
            candidates = await self._retriever.retrieve(
                tenant_id=request.tenant_id,
                query_text=request.query,
                query_embedding=query_embedding,
                doc_types=request.doc_types,
                candidate_limit=self._settings.rerank_candidate_count,
            )
            ret_span.update(output={"candidate_count": len(candidates)})
        retrieval_ms = embed_ms + int((time.perf_counter() - ret_started) * 1000)

        # 6. Cross-Encoder Reranking & Sigmoid Calibration
        rerank_started = time.perf_counter()
        with self._span(
            "rerank.onnx_cross_encoder",
            as_type="retriever",
            model=self._reranker.model_name,
        ) as rr_span:
            reranked = await self._reranker.rerank(
                request.query,
                candidates,
                top_k=request.top_k,
            )
            top_score = reranked[0].rerank_score if reranked else None
            rr_span.update(
                output={"top_k": len(reranked), "top_rerank_score": top_score}
            )
        rerank_ms = int((time.perf_counter() - rerank_started) * 1000)

        # 7. Gate 1 — Pre-LLM Retrieval Confidence Gate (0 LLM calls on low/no evidence)
        if not reranked or (top_score is not None and top_score < self._settings.min_rerank_score):
            total_ms = int((time.perf_counter() - total_started) * 1000)
            reason = (
                f"No active documents matched tenant '{request.tenant_id}' for this query."
                if not reranked
                else (
                    f"Top retrieved passage confidence ({top_score:.2f}) fell below the "
                    f"minimum grounding threshold ({self._settings.min_rerank_score:.2f}) "
                    f"for tenant '{request.tenant_id}'."
                )
            )
            response = QueryResponse(
                status="insufficient_evidence",
                answer=(
                    "Insufficient evidence in the tenant knowledge base to answer "
                    "this question reliably."
                ),
                missing_evidence_reason=reason,
                citations=[],
                telemetry=QueryTelemetry(
                    cache_hit=False,
                    cache_tier="miss",
                    latency_ms=total_ms,
                    retrieval_ms=retrieval_ms,
                    rerank_ms=rerank_ms,
                    llm_ms=0,
                    model="none (gate_1_abstain)",
                    reranker_model=self._reranker.model_name,
                    top_rerank_score=top_score,
                    trace_id=resolved_trace,
                ),
            )
            # Cache deterministic Gate-1 abstention in L1 only (short TTL, version-invalidated)
            if self._cache is not None:
                await self._cache.store(
                    tenant_id=request.tenant_id,
                    corpus_version=corpus_version,
                    doc_types=request.doc_types,
                    query=request.query,
                    query_embedding=None,
                    payload=self._serialize_cacheable(response),
                    ttl_seconds=_GATE1_ABSTAIN_CACHE_TTL_S,
                )
            await self._record_audit(request.tenant_id, response)
            logger.info(
                "query_gate1_abstain",
                tenant_id=request.tenant_id,
                top_rerank_score=top_score,
                latency_ms=total_ms,
            )
            return response

        # 8. Global LLM-miss rate limit guard (protects free-tier upstream RPM)
        if self._rate_limiter is not None:
            with self._span("rate_limit.global_llm"):
                await self._rate_limiter.check_llm_budget()

        # 9. Grounded Structured LLM Generation
        llm_started = time.perf_counter()
        with self._span(
            "llm.grounded_generate",
            as_type="generation",
            input_data={"query": request.query, "passage_count": len(reranked)},
        ) as llm_span:
            llm_result, model_used = await self._llm.generate(
                query=request.query,
                passages=reranked,
            )
            llm_span.update(
                model=model_used,
                output={"status": llm_result.status, "cited_count": len(llm_result.used_passages)},
            )
        llm_ms = int((time.perf_counter() - llm_started) * 1000)

        # 10. Gate 2 — Deterministic Citation Verification & DB Metadata Hydration
        with self._span("citation.verify_and_hydrate", as_type="guardrail") as v_span:
            outcome = self._verifier.verify(llm_result, reranked)
            v_span.update(
                output={
                    "status": outcome.status,
                    "citations_valid": len(outcome.citations),
                    "downgraded": outcome.downgraded,
                }
            )
        total_ms = int((time.perf_counter() - total_started) * 1000)

        citations = [
            CitationItem(
                citation_index=c.citation_index,
                document_id=c.document_id,
                doc_title=c.doc_title,
                doc_type=c.doc_type,
                version=c.version,
                page_number=c.page_number,
                section_path=c.section_path,
                rerank_score=c.rerank_score,
                excerpt=c.excerpt,
            )
            for c in outcome.citations
        ]

        response = QueryResponse(
            status=outcome.status,
            answer=outcome.answer,
            missing_evidence_reason=outcome.missing_evidence_reason,
            citations=citations,
            telemetry=QueryTelemetry(
                cache_hit=False,
                cache_tier="miss",
                latency_ms=total_ms,
                retrieval_ms=retrieval_ms,
                rerank_ms=rerank_ms,
                llm_ms=llm_ms,
                model=model_used,
                reranker_model=self._reranker.model_name,
                top_rerank_score=top_score,
                trace_id=resolved_trace,
            ),
        )

        # 11. Populate L1 + L2 semantic cache (only for verified answered responses)
        with self._span("cache.write_and_audit"):
            if self._cache is not None and response.status == "answered":
                await self._cache.store(
                    tenant_id=request.tenant_id,
                    corpus_version=corpus_version,
                    doc_types=request.doc_types,
                    query=request.query,
                    query_embedding=query_embedding,
                    payload=self._serialize_cacheable(response),
                )
            await self._record_audit(request.tenant_id, response)

        logger.info(
            "query_completed",
            tenant_id=request.tenant_id,
            status=response.status,
            citations=len(response.citations),
            model=model_used,
            top_rerank_score=top_score,
            latency_ms=total_ms,
            downgraded=outcome.downgraded,
        )
        return response

    def _span(self, name: str, **kwargs: Any) -> Any:
        if self._telemetry is not None:
            return self._telemetry.span(name, **kwargs)
        from contextlib import nullcontext

        class _Dummy:
            def update(self, **_: Any) -> None:
                return None

        return nullcontext(_Dummy())

    @staticmethod
    def _serialize_cacheable(response: QueryResponse) -> dict[str, Any]:
        return {
            "status": response.status,
            "answer": response.answer,
            "missing_evidence_reason": response.missing_evidence_reason,
            "citations": [c.model_dump(mode="json") for c in response.citations],
            "model": response.telemetry.model,
            "reranker_model": response.telemetry.reranker_model,
            "top_rerank_score": response.telemetry.top_rerank_score,
        }

    async def _finalize_cache_hit(
        self,
        *,
        tenant_id: str,
        cached_payload: dict[str, Any],
        cache_tier: CacheTier,
        total_started: float,
        resolved_trace: str,
    ) -> QueryResponse:
        total_ms = int((time.perf_counter() - total_started) * 1000)
        response = QueryResponse(
            status=cached_payload["status"],
            answer=cached_payload["answer"],
            missing_evidence_reason=cached_payload.get("missing_evidence_reason"),
            citations=[CitationItem.model_validate(c) for c in cached_payload.get("citations", [])],
            telemetry=QueryTelemetry(
                cache_hit=True,
                cache_tier=cache_tier,
                latency_ms=total_ms,
                retrieval_ms=0,
                rerank_ms=0,
                llm_ms=0,
                model=cached_payload.get("model", "cached"),
                reranker_model=cached_payload.get("reranker_model", self._reranker.model_name),
                top_rerank_score=cached_payload.get("top_rerank_score"),
                trace_id=resolved_trace,
            ),
        )
        await self._record_audit(tenant_id, response)
        logger.info(
            "query_cache_hit",
            tenant_id=tenant_id,
            cache_tier=cache_tier,
            status=response.status,
            latency_ms=total_ms,
        )
        return response

    async def _record_audit(self, tenant_id: str, response: QueryResponse) -> None:
        if self._audit_repo is None:
            return
        t = response.telemetry
        await self._audit_repo.record_query(
            QueryAuditRecord(
                tenant_id=tenant_id,
                trace_id=t.trace_id,
                status=response.status,
                cache_hit=t.cache_hit,
                cache_tier=t.cache_tier,
                model=t.model,
                reranker_model=t.reranker_model,
                top_rerank_score=t.top_rerank_score,
                latency_ms=t.latency_ms,
                retrieval_ms=t.retrieval_ms,
                rerank_ms=t.rerank_ms,
                llm_ms=t.llm_ms,
            )
        )
