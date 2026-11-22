"""
End-to-end DeepEval RAG quality gate (`--suite smoke` = 12 stratified Qs, `--suite full` = 50 Qs).

Uses `GeminiModel(model=settings.gemini_fallback_model)` (`gemini-3.5-flash-lite`) with
bounded concurrency and pacing to stay safely within Google AI Studio free-tier limits.

SLO Thresholds enforced:
  - Faithfulness >= 0.90 (mean across answerable cases)
  - Answer Relevancy >= 0.85 (mean across answerable cases)
  - Context Recall@5 >= 0.85 (deterministic + DeepEval Contextual Recall)
  - Abstention Accuracy == 1.00 (100% of out-of-scope + cross-tenant probes abstain)
  - Citation Validity == 1.00 (every answered response has valid inline [n] citations)
  - Cross-Tenant Leakage == 0.00
"""

from __future__ import annotations

import asyncio
from typing import Literal

import psycopg
import pytest

from app.adapters.embeddings_gemini import create_embedding_adapter
from app.adapters.llm_router import ResilientLLMRouter
from app.adapters.reranker_fastembed import FastEmbedReranker
from app.adapters.retriever_postgres import PostgresHybridRetriever
from app.core.config import get_settings
from app.db.migrate import run_migrations
from app.db.pool import create_db_pool
from app.domain.models import DocType
from app.schemas.query import QueryRequest
from app.services.query import QueryOrchestrator
from app.services.verifier import CitationVerifierAndHydrator
from evals.harness import (
    DeepEvalCaseScores,
    SlidingWindowRPMGate,
    build_paced_gemini_judge,
    ensure_live_seeded_corpus,
    evaluate_retrieval_case,
    execute_query_with_context_retry,
    has_valid_inline_citations,
    measure_deepeval_case,
)
from evals.loader import GoldenCase, load_golden_dataset


@pytest.mark.asyncio
async def test_rag_quality_deepeval_gate(
    eval_suite: str,
    eval_delay_seconds: float,
) -> None:
    settings = get_settings()
    if not settings.gemini_api_key:
        pytest.skip("GEMINI_API_KEY not configured — skipping LLM-as-a-judge DeepEval suite.")

    try:
        run_migrations(settings.database_admin_url)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL unavailable for DeepEval RAG suite: {exc}")

    suite_name: Literal["smoke", "full"] = "full" if eval_suite == "full" else "smoke"
    cases = load_golden_dataset(suite=suite_name)
    assert len(cases) > 0

    pool = create_db_pool(settings, conninfo=settings.database_url)
    await pool.open(wait=True)

    try:
        await ensure_live_seeded_corpus(settings=settings, pool=pool)
        embedder = create_embedding_adapter(settings)
        retriever = PostgresHybridRetriever(pool)
        reranker = FastEmbedReranker(
            model_name=settings.reranker_model_name,
            cpu_semaphore=asyncio.Semaphore(2),
        )
        llm_router = ResilientLLMRouter(settings)
        verifier = CitationVerifierAndHydrator()

        # Run fresh uncached pipeline (`cache=None`, `rate_limiter=None`) so every golden case
        # exercises real hybrid retrieval, reranking, LLM generation, and both abstention gates.
        orchestrator = QueryOrchestrator(
            settings=settings,
            embedder=embedder,
            retriever=retriever,
            reranker=reranker,
            llm=llm_router,
            verifier=verifier,
            audit_repo=None,
            cache=None,
            rate_limiter=None,
            telemetry=None,
        )

        rpm_gate = SlidingWindowRPMGate(
            rpm_budget=13,
            min_spacing_seconds=max(0.35, min(eval_delay_seconds, 2.0)),
        )
        judge = build_paced_gemini_judge(
            settings=settings,
            max_concurrent=2,
            delay_seconds=max(0.35, eval_delay_seconds / 2.0),
            rpm_gate=rpm_gate,
        )

        deepeval_scores: list[DeepEvalCaseScores] = []
        retrieval_recalls: list[float] = []
        abstention_total = 0
        abstention_correct = 0
        answerable_total = 0
        valid_citations_count = 0
        leakage_failures: list[str] = []
        abstention_failures: list[str] = []
        pending_judge: list[tuple[GoldenCase, str, list[str], float, str]] = []

        # Phase A: Run all RAG queries once (no duplicate embed/retrieve/rerank per case)
        for case in cases:
            doc_types: list[DocType] | None = (
                list(case.doc_types)  # type: ignore[arg-type]
                if case.doc_types
                else None
            )
            request = QueryRequest(
                tenant_id=case.tenant_id,
                query=case.query,
                doc_types=doc_types,
                top_k=5,
            )

            response, candidates, reranked = await execute_query_with_context_retry(
                orchestrator=orchestrator,
                request=request,
                rpm_gate=rpm_gate,
            )
            ret_eval = evaluate_retrieval_case(case, candidates=candidates, reranked=reranked)
            if ret_eval.source_recall is not None:
                retrieval_recalls.append(ret_eval.source_recall)

            # Check cross-tenant / forbidden leakage in generated answer + hydrated excerpts
            answer_and_excerpts = "\n".join(
                [response.answer, *(c.excerpt for c in response.citations)]
            ).lower()
            leaked_in_output = [
                sub for sub in case.forbidden_substrings if sub.lower() in answer_and_excerpts
            ]
            if leaked_in_output or ret_eval.leaked_substrings or ret_eval.leaked_titles:
                leakage_failures.append(
                    f"{case.id}(output={leaked_in_output}, ret={ret_eval.leaked_substrings}, "
                    f"titles={ret_eval.leaked_titles})"
                )

            if case.expected_status == "insufficient_evidence":
                abstention_total += 1
                if response.status == "insufficient_evidence" and len(response.citations) == 0:
                    abstention_correct += 1
                else:
                    abstention_failures.append(
                        f"{case.id}(status={response.status}, citations={len(response.citations)}, "
                        f"answer={response.answer[:120]!r})"
                    )
                continue

            # Answerable case checks
            answerable_total += 1
            citation_indices = [c.citation_index for c in response.citations]
            if response.status == "answered" and has_valid_inline_citations(
                response.answer, citation_indices
            ):
                valid_citations_count += 1

            retrieval_context = [item.chunk.contextual_content for item in reranked]
            if not retrieval_context:
                retrieval_context = [c.excerpt for c in response.citations]

            pending_judge.append(
                (
                    case,
                    response.answer,
                    retrieval_context,
                    ret_eval.source_recall or 0.0,
                    response.telemetry.model,
                )
            )

        # Phase B: Score all answerable cases via paced DeepEval Gemini judge
        for case, actual_answer, retrieval_context, ret_recall, model_name in pending_judge:
            case_scores = await measure_deepeval_case(
                case_id=case.id,
                query=case.query,
                actual_answer=actual_answer,
                expected_answer=case.expected_answer,
                retrieval_context=retrieval_context,
                judge_model=judge,
            )
            deepeval_scores.append(case_scores)
            print(
                f"  [{case.id} | {case.category:<14}] "
                f"model={model_name} "
                f"F={case_scores.faithfulness:.2f} R={case_scores.answer_relevancy:.2f} "
                f"CR={case_scores.contextual_recall:.2f} ret@5={ret_recall:.2f}",
                flush=True,
            )
    finally:
        await llm_router.aclose()
        await pool.close()

    mean_faithfulness = (
        sum(s.faithfulness for s in deepeval_scores) / len(deepeval_scores)
        if deepeval_scores
        else 0.0
    )
    mean_relevancy = (
        sum(s.answer_relevancy for s in deepeval_scores) / len(deepeval_scores)
        if deepeval_scores
        else 0.0
    )
    mean_ctx_recall_llm = (
        sum(s.contextual_recall for s in deepeval_scores) / len(deepeval_scores)
        if deepeval_scores
        else 0.0
    )
    mean_recall_at_5 = (
        sum(retrieval_recalls) / len(retrieval_recalls) if retrieval_recalls else 0.0
    )
    abstention_accuracy = (
        abstention_correct / abstention_total if abstention_total > 0 else 1.0
    )
    citation_validity = (
        valid_citations_count / answerable_total if answerable_total > 0 else 1.0
    )

    print(
        f"\n[DeepEval RAG Quality Gate | suite={suite_name} | "
        f"judge={settings.gemini_fallback_model}]"
        f"\n  Faithfulness        : {mean_faithfulness:.4f} (SLO >= 0.90)"
        f"\n  Answer Relevancy    : {mean_relevancy:.4f} (SLO >= 0.85)"
        f"\n  Contextual Recall   : {mean_ctx_recall_llm:.4f} (SLO >= 0.85)"
        f"\n  Context Recall@5    : {mean_recall_at_5:.4f} (SLO >= 0.85)"
        f"\n  Citation Validity   : {citation_validity:.4f} (SLO == 1.00)"
        f"\n  Abstention Accuracy : {abstention_accuracy:.4f} (SLO == 1.00)"
        f"\n  Cross-Tenant Leaks  : {len(leakage_failures)} (SLO == 0)"
    )

    assert not leakage_failures, f"Cross-tenant leakage detected: {leakage_failures}"
    assert not abstention_failures, (
        f"Abstention accuracy failed ({abstention_correct}/{abstention_total}): "
        f"{abstention_failures}"
    )
    assert citation_validity == 1.0, (
        f"Citation validity ({citation_validity:.4f}) fell below 1.00 "
        f"({valid_citations_count}/{answerable_total})"
    )
    assert mean_recall_at_5 >= 0.85, (
        f"Deterministic Context Recall@5 ({mean_recall_at_5:.4f}) below 0.85 SLO"
    )
    assert mean_faithfulness >= 0.90, (
        f"DeepEval Faithfulness ({mean_faithfulness:.4f}) below 0.90 SLO"
    )
    assert mean_relevancy >= 0.85, (
        f"DeepEval Answer Relevancy ({mean_relevancy:.4f}) below 0.85 SLO"
    )
    assert mean_ctx_recall_llm >= 0.85, (
        f"DeepEval Contextual Recall ({mean_ctx_recall_llm:.4f}) below 0.85 SLO"
    )
