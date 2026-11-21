"""
Reproducible CiteOps Benchmark Runner — generates Markdown & JSON scorecards.

Supports two execution targets:
  1. `--target inprocess` (default): boots the CiteOps QueryOrchestrator against local
     PostgreSQL 17 + Redis 8, evaluates cold-miss RAG quality (deterministic + DeepEval)
     and warm L1 cache-hit latency.
  2. `--target https://<api-url>`: benchmarks any live local or cloud-deployed CiteOps API
     via HTTP `/v1/query` (used in Phase 7 live deployment verification).

Usage:
  uv run --directory apps/api python ../../evals/run_benchmark.py --suite smoke
  uv run --directory apps/api python ../../evals/run_benchmark.py --suite full --delay-seconds 2.5
  uv run --directory apps/api python ../../evals/run_benchmark.py --target https://citeops.onrender.com
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from redis.asyncio import Redis

ROOT_DIR = Path(__file__).resolve().parent.parent
API_DIR = ROOT_DIR / "apps" / "api"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

from app.adapters.cache_redis import RedisSemanticCache  # noqa: E402
from app.adapters.embeddings_gemini import create_embedding_adapter  # noqa: E402
from app.adapters.llm_router import ResilientLLMRouter  # noqa: E402
from app.adapters.reranker_fastembed import FastEmbedReranker  # noqa: E402
from app.adapters.retriever_postgres import PostgresHybridRetriever  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.db.migrate import run_migrations  # noqa: E402
from app.db.pool import create_db_pool  # noqa: E402
from app.domain.models import DocType  # noqa: E402
from app.schemas.query import QueryRequest, QueryResponse  # noqa: E402
from app.services.query import QueryOrchestrator  # noqa: E402
from app.services.verifier import CitationVerifierAndHydrator  # noqa: E402
from evals.harness import (  # noqa: E402
    SlidingWindowRPMGate,
    build_paced_gemini_judge,
    ensure_live_seeded_corpus,
    evaluate_retrieval_case,
    execute_query_with_retry,
    has_valid_inline_citations,
    measure_deepeval_case,
    percentile,
)
from evals.loader import GoldenCase, load_golden_dataset  # noqa: E402


@dataclass
class CaseBenchmarkRecord:
    case_id: str
    category: str
    tenant_id: str
    expected_status: str
    actual_status: str
    model: str
    cold_cache_tier: str
    cold_latency_ms: int
    retrieval_ms: int
    rerank_ms: int
    llm_ms: int
    warm_cache_hit: bool
    warm_cache_tier: str
    warm_latency_ms: int
    source_recall_at_5: float | None
    citation_valid: bool | None
    abstention_correct: bool | None
    leaked: bool
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    contextual_recall: float | None = None


def _source_recall_from_citations(case: GoldenCase, response: QueryResponse) -> float | None:
    if case.expected_status != "answered" or not case.expected_sources:
        return None
    matched = 0
    for exp in case.expected_sources:
        for cit in response.citations:
            title_ok = cit.doc_title.strip().lower() == exp.doc_title.strip().lower()
            page_ok = exp.page_number is None or cit.page_number == exp.page_number
            if title_ok and page_ok:
                matched += 1
                break
    return matched / len(case.expected_sources)


def _check_output_leakage(case: GoldenCase, response: QueryResponse) -> bool:
    blob = "\n".join([response.answer, *(c.excerpt for c in response.citations)]).lower()
    return any(sub.lower() in blob for sub in case.forbidden_substrings)


def _format_markdown_scorecard(report: dict[str, Any]) -> str:
    m = report["metrics"]
    lat = report["latency_ms"]
    gates = report["slo_gates"]

    def _badge(passed: bool | None) -> str:
        if passed is None:
            return "SKIPPED"
        return "PASS" if passed else "FAIL"

    def _fmt_score(val: float | None) -> str:
        return "N/A" if val is None else f"{val:.3f}"

    leak_pct = m["cross_tenant_leakage_rate"] * 100
    leak_cnt = m["cross_tenant_leakage_count"]
    total_cnt = report["total_cases"]
    warm_hit_pct = m["warm_cache_hit_rate"] * 100

    lines = [
        f"# CiteOps Evaluation Scorecard (`{report['suite']}` suite)",
        "",
        f"- **Generated (UTC):** `{report['generated_at_utc']}`",
        f"- **Target:** `{report['target']}`",
        (
            f"- **Cases Evaluated:** `{total_cnt}` "
            f"(`{report['answerable_cases']}` answerable, "
            f"`{report['abstention_cases']}` abstention/isolation)"
        ),
        f"- **Judge Model:** `{report['judge_model']}`",
        f"- **Overall Status:** **{'PASS' if report['all_gates_passed'] else 'FAIL'}**",
        "",
        "## Quality & Isolation Metrics",
        "",
        "| Metric | Measured | SLO Target | Gate |",
        "| :--- | ---: | ---: | :---: |",
        (
            f"| **Context Recall@5** | {_fmt_score(m['context_recall_at_5'])} "
            f"| >= 0.850 | {_badge(gates['context_recall_at_5'])} |"
        ),
        (
            f"| **Faithfulness (DeepEval)** | {_fmt_score(m['faithfulness'])} "
            f"| >= 0.900 | {_badge(gates['faithfulness'])} |"
        ),
        (
            f"| **Answer Relevancy (DeepEval)** | {_fmt_score(m['answer_relevancy'])} "
            f"| >= 0.850 | {_badge(gates['answer_relevancy'])} |"
        ),
        (
            f"| **Contextual Recall (DeepEval)** | {_fmt_score(m['contextual_recall'])} "
            f"| >= 0.850 | {_badge(gates['contextual_recall'])} |"
        ),
        (
            f"| **Citation Validity** | {m['citation_validity'] * 100:.1f}% "
            f"| 100.0% | {_badge(gates['citation_validity'])} |"
        ),
        (
            f"| **Abstention Accuracy** | {m['abstention_accuracy'] * 100:.1f}% "
            f"| 100.0% | {_badge(gates['abstention_accuracy'])} |"
        ),
        (
            f"| **Cross-Tenant Leakage** | {leak_pct:.1f}% ({leak_cnt}/{total_cnt}) "
            f"| 0.0% | {_badge(gates['zero_leakage'])} |"
        ),
        "",
        "## Latency & Cache Performance",
        "",
        "| Metric | p50 (ms) | p95 (ms) | Notes |",
        "| :--- | ---: | ---: | :--- |",
        (
            f"| **Cold Query (Cache Miss)** | {lat['cold_p50_ms']:.1f} "
            f"| {lat['cold_p95_ms']:.1f} | Full hybrid RRF + ONNX rerank + LLM |"
        ),
        (
            f"| **Warm Query (L1 Cache Hit)** | {lat['warm_hit_p50_ms']:.1f} "
            f"| {lat['warm_hit_p95_ms']:.1f} | Target `< 50 ms` server-side "
            f"({warm_hit_pct:.1f}% hit rate) |"
        ),
        (
            f"| **Retrieval Stage (Cold)** | {lat['retrieval_p50_ms']:.1f} "
            f"| {lat['retrieval_p95_ms']:.1f} | Query embed + pgvector/tsvector RRF |"
        ),
        (
            f"| **ONNX Reranker Stage** | {lat['rerank_p50_ms']:.1f} "
            f"| {lat['rerank_p95_ms']:.1f} | Local CPU cross-encoder |"
        ),
        (
            f"| **LLM Generation Stage** | {lat['llm_p50_ms']:.1f} "
            f"| {lat['llm_p95_ms']:.1f} | Answered cold queries only |"
        ),
        "",
    ]
    return "\n".join(lines)


async def run_benchmark(
    *,
    settings: Settings,
    suite: Literal["smoke", "full"],
    target: str,
    api_key: str,
    delay_seconds: float,
    max_concurrent: int,
    rpm_budget: int,
    skip_deepeval: bool,
    output_dir: Path,
) -> tuple[dict[str, Any], str]:
    cases = load_golden_dataset(suite=suite)
    use_deepeval = not skip_deepeval and bool(settings.gemini_api_key)
    rpm_gate = SlidingWindowRPMGate(
        rpm_budget=rpm_budget,
        min_spacing_seconds=max(0.35, min(delay_seconds, 2.0)),
    )
    judge = (
        build_paced_gemini_judge(
            settings=settings,
            max_concurrent=max_concurrent,
            delay_seconds=max(0.35, delay_seconds / 2.0),
            rpm_gate=rpm_gate,
        )
        if use_deepeval
        else None
    )

    records: list[CaseBenchmarkRecord] = []
    pending_judge: list[tuple[CaseBenchmarkRecord, GoldenCase, str, list[str]]] = []

    if target == "inprocess":
        run_migrations(settings.database_admin_url)
        pool = create_db_pool(settings, conninfo=settings.database_url)
        await pool.open(wait=True)
        redis_client: Redis | None = None
        try:
            redis_client = Redis.from_url(
                settings.redis_url,
                decode_responses=False,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
            )
            await redis_client.ping()
        except Exception:
            redis_client = None

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
            cache = RedisSemanticCache(
                redis_client,
                similarity_threshold=settings.semantic_cache_threshold,
                max_entries=settings.semantic_cache_max_entries,
                default_ttl_seconds=settings.cache_ttl_seconds,
            )

            # Bump corpus version once so Pass 1 measures genuine cold cache-miss performance
            if redis_client is not None:
                for tenant_id in ("acme-corp", "globex-io"):
                    await cache.bump_corpus_version(tenant_id)

            orchestrator = QueryOrchestrator(
                settings=settings,
                embedder=embedder,
                retriever=retriever,
                reranker=reranker,
                llm=llm_router,
                verifier=verifier,
                audit_repo=None,
                cache=cache,
                rate_limiter=None,
                telemetry=None,
            )

            # Phase A: Execute cold miss + warm L1 hit pass for every case
            for idx, case in enumerate(cases):
                doc_types: list[DocType] | None = (
                    list(case.doc_types)  # type: ignore[arg-type]
                    if case.doc_types
                    else None
                )
                req = QueryRequest(
                    tenant_id=case.tenant_id,
                    query=case.query,
                    doc_types=doc_types,
                    top_k=5,
                )

                # Capture retrieval recall & full reranked passages for DeepEval
                q_vec = await embedder.embed_query(case.query)
                candidates = await retriever.retrieve(
                    tenant_id=case.tenant_id,
                    query_text=case.query,
                    query_embedding=q_vec,
                    doc_types=doc_types,
                    candidate_limit=settings.rerank_candidate_count,
                )
                reranked = await reranker.rerank(case.query, candidates, top_k=5)
                ret_eval = evaluate_retrieval_case(case, candidates=candidates, reranked=reranked)

                # Pass 1: Cold execution (populates L1 + L2 cache for answered / L1 for gate-1)
                cold_resp = await execute_query_with_retry(
                    orchestrator=orchestrator,
                    request=req,
                    rpm_gate=rpm_gate,
                )

                # Pass 2: Immediate warm repeat (measures L1 cache-hit latency, 0 LLM calls)
                warm_resp = await orchestrator.execute(req)

                leaked = (
                    _check_output_leakage(case, cold_resp)
                    or bool(ret_eval.leaked_substrings)
                    or bool(ret_eval.leaked_titles)
                )
                citation_valid: bool | None = None
                abstention_correct: bool | None = None
                if case.expected_status == "insufficient_evidence":
                    abstention_correct = (
                        cold_resp.status == "insufficient_evidence"
                        and len(cold_resp.citations) == 0
                    )
                else:
                    citation_valid = cold_resp.status == "answered" and has_valid_inline_citations(
                        cold_resp.answer, [c.citation_index for c in cold_resp.citations]
                    )

                rec = CaseBenchmarkRecord(
                    case_id=case.id,
                    category=case.category,
                    tenant_id=case.tenant_id,
                    expected_status=case.expected_status,
                    actual_status=cold_resp.status,
                    model=cold_resp.telemetry.model,
                    cold_cache_tier=cold_resp.telemetry.cache_tier,
                    cold_latency_ms=cold_resp.telemetry.latency_ms,
                    retrieval_ms=cold_resp.telemetry.retrieval_ms,
                    rerank_ms=cold_resp.telemetry.rerank_ms,
                    llm_ms=cold_resp.telemetry.llm_ms,
                    warm_cache_hit=warm_resp.telemetry.cache_hit,
                    warm_cache_tier=warm_resp.telemetry.cache_tier,
                    warm_latency_ms=warm_resp.telemetry.latency_ms,
                    source_recall_at_5=ret_eval.source_recall,
                    citation_valid=citation_valid,
                    abstention_correct=abstention_correct,
                    leaked=leaked,
                )
                records.append(rec)

                if judge is not None and case.expected_status == "answered":
                    contexts = [item.chunk.contextual_content for item in reranked]
                    if not contexts:
                        contexts = [c.excerpt for c in cold_resp.citations]
                    pending_judge.append((rec, case, cold_resp.answer, contexts))

                print(
                    f"  [RAG {idx + 1:>2}/{len(cases)}] {case.id} ({case.category:<14}) | "
                    f"status={rec.actual_status:<21} | cold={rec.cold_latency_ms:>5}ms | "
                    f"warm={rec.warm_latency_ms:>3}ms({rec.warm_cache_tier})",
                    flush=True,
                )
        finally:
            if redis_client is not None:
                await redis_client.aclose()
            await pool.close()
    else:
        # Remote HTTP target benchmark (`--target https://...`)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-Internal-API-Key"] = api_key
        endpoint = f"{target.rstrip('/')}/v1/query"

        async with httpx.AsyncClient(timeout=60.0) as client:
            for idx, case in enumerate(cases):
                await rpm_gate.acquire()
                payload = {
                    "tenant_id": case.tenant_id,
                    "query": case.query,
                    "doc_types": case.doc_types,
                    "top_k": 5,
                }
                t0 = time.perf_counter()
                r1 = await client.post(endpoint, headers=headers, json=payload)
                r1.raise_for_status()
                cold_wall_ms = int((time.perf_counter() - t0) * 1000)
                cold_resp = QueryResponse.model_validate(r1.json())

                r2 = await client.post(endpoint, headers=headers, json=payload)
                r2.raise_for_status()
                warm_resp = QueryResponse.model_validate(r2.json())

                leaked = _check_output_leakage(case, cold_resp)
                source_recall = _source_recall_from_citations(case, cold_resp)
                citation_valid = None
                abstention_correct = None
                if case.expected_status == "insufficient_evidence":
                    abstention_correct = (
                        cold_resp.status == "insufficient_evidence"
                        and len(cold_resp.citations) == 0
                    )
                else:
                    citation_valid = cold_resp.status == "answered" and has_valid_inline_citations(
                        cold_resp.answer, [c.citation_index for c in cold_resp.citations]
                    )

                rec = CaseBenchmarkRecord(
                    case_id=case.id,
                    category=case.category,
                    tenant_id=case.tenant_id,
                    expected_status=case.expected_status,
                    actual_status=cold_resp.status,
                    model=cold_resp.telemetry.model,
                    cold_cache_tier=cold_resp.telemetry.cache_tier,
                    cold_latency_ms=cold_resp.telemetry.latency_ms or cold_wall_ms,
                    retrieval_ms=cold_resp.telemetry.retrieval_ms,
                    rerank_ms=cold_resp.telemetry.rerank_ms,
                    llm_ms=cold_resp.telemetry.llm_ms,
                    warm_cache_hit=warm_resp.telemetry.cache_hit,
                    warm_cache_tier=warm_resp.telemetry.cache_tier,
                    warm_latency_ms=warm_resp.telemetry.latency_ms,
                    source_recall_at_5=source_recall,
                    citation_valid=citation_valid,
                    abstention_correct=abstention_correct,
                    leaked=leaked,
                )
                records.append(rec)

                if judge is not None and case.expected_status == "answered":
                    contexts = [
                        f"[{c.citation_index}] {c.doc_title} (p.{c.page_number}, "
                        f"{c.section_path}): {c.excerpt}"
                        for c in cold_resp.citations
                    ]
                    if contexts:
                        pending_judge.append((rec, case, cold_resp.answer, contexts))

                print(
                    f"  [RAG {idx + 1:>2}/{len(cases)}] {case.id} ({case.category:<14}) | "
                    f"status={rec.actual_status:<21} | cold={rec.cold_latency_ms:>5}ms | "
                    f"warm={rec.warm_latency_ms:>3}ms({rec.warm_cache_tier})",
                    flush=True,
                )

    # Phase B: Paced DeepEval LLM-as-a-Judge scoring (strictly within free-tier RPM)
    if judge is not None and pending_judge:
        print(
            f"\nScoring {len(pending_judge)} answerable case(s) with DeepEval "
            f"({settings.gemini_fallback_model}, rpm_budget={rpm_budget})...",
            flush=True,
        )
        for j_idx, (rec, case, actual_answer, contexts) in enumerate(pending_judge, start=1):
            scores = await measure_deepeval_case(
                case_id=case.id,
                query=case.query,
                actual_answer=actual_answer,
                expected_answer=case.expected_answer,
                retrieval_context=contexts,
                judge_model=judge,
            )
            rec.faithfulness = scores.faithfulness
            rec.answer_relevancy = scores.answer_relevancy
            rec.contextual_recall = scores.contextual_recall
            print(
                f"  [Judge {j_idx:>2}/{len(pending_judge)}] {case.id} | "
                f"F={scores.faithfulness:.2f} R={scores.answer_relevancy:.2f} "
                f"CR={scores.contextual_recall:.2f}",
                flush=True,
            )

    answerable_recs = [r for r in records if r.expected_status == "answered"]
    abstention_recs = [r for r in records if r.expected_status == "insufficient_evidence"]

    recall_vals = [
        r.source_recall_at_5 for r in answerable_recs if r.source_recall_at_5 is not None
    ]
    mean_recall = sum(recall_vals) / len(recall_vals) if recall_vals else 0.0

    faith_vals = [r.faithfulness for r in answerable_recs if r.faithfulness is not None]
    rel_vals = [r.answer_relevancy for r in answerable_recs if r.answer_relevancy is not None]
    cr_vals = [r.contextual_recall for r in answerable_recs if r.contextual_recall is not None]

    mean_faith = sum(faith_vals) / len(faith_vals) if faith_vals else None
    mean_rel = sum(rel_vals) / len(rel_vals) if rel_vals else None
    mean_cr = sum(cr_vals) / len(cr_vals) if cr_vals else None

    citation_validity = (
        sum(1 for r in answerable_recs if r.citation_valid) / len(answerable_recs)
        if answerable_recs
        else 1.0
    )
    abstention_accuracy = (
        sum(1 for r in abstention_recs if r.abstention_correct) / len(abstention_recs)
        if abstention_recs
        else 1.0
    )
    leakage_count = sum(1 for r in records if r.leaked)
    leakage_rate = leakage_count / len(records) if records else 0.0

    cold_latencies = [float(r.cold_latency_ms) for r in records if r.cold_cache_tier == "miss"]
    if not cold_latencies:
        cold_latencies = [float(r.cold_latency_ms) for r in records]
    warm_hits = [r for r in records if r.warm_cache_hit]
    warm_hit_latencies = [float(r.warm_latency_ms) for r in warm_hits]
    warm_cache_hit_rate = len(warm_hits) / len(records) if records else 0.0

    retrieval_latencies = [float(r.retrieval_ms) for r in records if r.retrieval_ms > 0]
    rerank_latencies = [float(r.rerank_ms) for r in records if r.rerank_ms > 0]
    llm_latencies = [float(r.llm_ms) for r in answerable_recs if r.llm_ms > 0]

    slo_gates: dict[str, bool | None] = {
        "context_recall_at_5": mean_recall >= 0.85,
        "faithfulness": (mean_faith >= 0.90) if mean_faith is not None else None,
        "answer_relevancy": (mean_rel >= 0.85) if mean_rel is not None else None,
        "contextual_recall": (mean_cr >= 0.85) if mean_cr is not None else None,
        "citation_validity": citation_validity == 1.0,
        "abstention_accuracy": abstention_accuracy == 1.0,
        "zero_leakage": leakage_count == 0,
    }
    all_gates_passed = all(v is not False for v in slo_gates.values())

    report: dict[str, Any] = {
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "suite": suite,
        "target": target,
        "judge_model": settings.gemini_fallback_model if judge is not None else "disabled",
        "total_cases": len(records),
        "answerable_cases": len(answerable_recs),
        "abstention_cases": len(abstention_recs),
        "all_gates_passed": all_gates_passed,
        "slo_gates": slo_gates,
        "metrics": {
            "context_recall_at_5": round(mean_recall, 4),
            "faithfulness": round(mean_faith, 4) if mean_faith is not None else None,
            "answer_relevancy": round(mean_rel, 4) if mean_rel is not None else None,
            "contextual_recall": round(mean_cr, 4) if mean_cr is not None else None,
            "citation_validity": round(citation_validity, 4),
            "abstention_accuracy": round(abstention_accuracy, 4),
            "cross_tenant_leakage_count": leakage_count,
            "cross_tenant_leakage_rate": round(leakage_rate, 4),
            "warm_cache_hit_rate": round(warm_cache_hit_rate, 4),
        },
        "latency_ms": {
            "cold_p50_ms": round(percentile(cold_latencies, 50), 1),
            "cold_p95_ms": round(percentile(cold_latencies, 95), 1),
            "warm_hit_p50_ms": round(percentile(warm_hit_latencies, 50), 1),
            "warm_hit_p95_ms": round(percentile(warm_hit_latencies, 95), 1),
            "retrieval_p50_ms": round(percentile(retrieval_latencies, 50), 1),
            "retrieval_p95_ms": round(percentile(retrieval_latencies, 95), 1),
            "rerank_p50_ms": round(percentile(rerank_latencies, 50), 1),
            "rerank_p95_ms": round(percentile(rerank_latencies, 95), 1),
            "llm_p50_ms": round(percentile(llm_latencies, 50), 1),
            "llm_p95_ms": round(percentile(llm_latencies, 95), 1),
        },
        "cases": [asdict(r) for r in records],
    }

    markdown = _format_markdown_scorecard(report)

    def _write_reports() -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"scorecard_{suite}.json"
        md_path = output_dir / f"scorecard_{suite}.md"
        json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        md_path.write_text(markdown, encoding="utf-8")

    await asyncio.to_thread(_write_reports)

    return report, markdown


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")
    settings = get_settings()

    parser = argparse.ArgumentParser(description="Run CiteOps golden evaluation benchmark.")
    parser.add_argument(
        "--suite",
        choices=("smoke", "full"),
        default="smoke",
        help="Dataset slice: 'smoke' (12 stratified Qs) or 'full' (50 Qs).",
    )
    parser.add_argument(
        "--target",
        default="inprocess",
        help="'inprocess' (default) or live API base URL (e.g. http://localhost:8000).",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("CITEOPS_INTERNAL_API_KEY", settings.citeops_internal_api_key),
        help="X-Internal-API-Key header for HTTP --target mode.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=1.5,
        help="Delay between queries to respect free-tier LLM rate limits.",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=2,
        help="Max concurrent DeepEval judge requests (default: 2).",
    )
    parser.add_argument(
        "--rpm-budget",
        type=int,
        default=int(os.getenv("EVAL_RPM_BUDGET", "13")),
        help="Shared free-tier Gemini RPM budget across RAG + judge calls (default: 13).",
    )
    parser.add_argument(
        "--skip-deepeval",
        action="store_true",
        help="Skip LLM-as-a-judge DeepEval metrics and measure deterministic/latency SLOs only.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT_DIR / "evals" / "reports",
        help="Directory for generated scorecard Markdown & JSON reports.",
    )
    args = parser.parse_args()

    coro = run_benchmark(
        settings=settings,
        suite=args.suite,
        target=args.target,
        api_key=args.api_key,
        delay_seconds=args.delay_seconds,
        max_concurrent=args.max_concurrent,
        rpm_budget=args.rpm_budget,
        skip_deepeval=args.skip_deepeval,
        output_dir=args.output_dir,
    )

    if sys.platform == "win32":
        report, markdown = asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    else:
        report, markdown = asyncio.run(coro)

    print("\n" + markdown)
    print(f"Saved reports to: {args.output_dir}")
    raise SystemExit(0 if report["all_gates_passed"] else 1)


if __name__ == "__main__":
    main()
