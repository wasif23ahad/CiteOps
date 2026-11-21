import time
import uuid

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain.models import QueryAuditRecord
from app.domain.ports import (
    AuditRepoPort,
    EmbeddingPort,
    GroundedLLMPort,
    HybridRetrieverPort,
    RerankerPort,
)
from app.schemas.query import CitationItem, QueryRequest, QueryResponse, QueryTelemetry
from app.services.verifier import CitationVerifierAndHydrator

logger = get_logger(__name__)


class QueryOrchestrator:
    """
    End-to-end citation-locked query pipeline:
      Embed -> Hybrid RRF (RLS) -> Calibrated ONNX Rerank ->
      Gate 1 Pre-LLM Abstention -> Resilient LLM -> Gate 2 Citation Verifier -> Audit Log
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
    ) -> None:
        self._settings = settings
        self._embedder = embedder
        self._retriever = retriever
        self._reranker = reranker
        self._llm = llm
        self._verifier = verifier
        self._audit_repo = audit_repo

    async def execute(
        self,
        request: QueryRequest,
        *,
        trace_id: str | None = None,
    ) -> QueryResponse:
        total_started = time.perf_counter()
        resolved_trace = trace_id or f"tr_{uuid.uuid4().hex[:16]}"

        # 1. Embed query + Hybrid RRF Retrieval (strict tenant RLS)
        ret_started = time.perf_counter()
        query_embedding = await self._embedder.embed_query(request.query)
        candidates = await self._retriever.retrieve(
            tenant_id=request.tenant_id,
            query_text=request.query,
            query_embedding=query_embedding,
            doc_types=request.doc_types,
            candidate_limit=self._settings.rerank_candidate_count,
        )
        retrieval_ms = int((time.perf_counter() - ret_started) * 1000)

        # 2. Cross-Encoder Reranking & Sigmoid Calibration
        rerank_started = time.perf_counter()
        reranked = await self._reranker.rerank(
            request.query,
            candidates,
            top_k=request.top_k,
        )
        rerank_ms = int((time.perf_counter() - rerank_started) * 1000)
        top_score = reranked[0].rerank_score if reranked else None

        # 3. Gate 1 — Pre-LLM Retrieval Confidence Gate (0 LLM cost on low/no evidence)
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
            await self._record_audit(request.tenant_id, response)
            logger.info(
                "query_gate1_abstain",
                tenant_id=request.tenant_id,
                top_rerank_score=top_score,
                latency_ms=total_ms,
            )
            return response

        # 4. Grounded Structured LLM Generation
        llm_started = time.perf_counter()
        llm_result, model_used = await self._llm.generate(
            query=request.query,
            passages=reranked,
        )
        llm_ms = int((time.perf_counter() - llm_started) * 1000)

        # 5. Gate 2 — Deterministic Citation Verification & DB Metadata Hydration
        outcome = self._verifier.verify(llm_result, reranked)
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
