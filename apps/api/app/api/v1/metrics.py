from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.config import get_settings
from app.domain.ports import AuditRepoPort
from app.schemas.common import TENANT_ID_PATTERN
from app.schemas.metrics import MetricsSummaryResponse

router = APIRouter(tags=["metrics"])


def _get_audit_repo(request: Request) -> AuditRepoPort:
    repo: AuditRepoPort | None = getattr(request.app.state, "audit_repo", None)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metrics repository is not initialized.",
        )
    return repo


@router.get("/metrics/summary", response_model=MetricsSummaryResponse)
async def get_metrics_summary(
    request: Request,
    tenant_id: Annotated[str, Query(pattern=TENANT_ID_PATTERN)],
) -> MetricsSummaryResponse:
    """Return RLS-scoped operational metrics (hit rate, abstention rate, p50/p95 latencies)."""
    repo = _get_audit_repo(request)
    settings = getattr(request.app.state, "settings", None) or get_settings()
    summary = await repo.get_metrics_summary(tenant_id)

    active_llm = (
        f"ollama/{settings.ollama_model}"
        if settings.llm_provider == "ollama"
        else settings.gemini_primary_model
    )

    return MetricsSummaryResponse(
        tenant_id=summary.tenant_id,
        total_queries=summary.total_queries,
        cache_hit_rate=summary.cache_hit_rate,
        exact_cache_hits=summary.exact_cache_hits,
        semantic_cache_hits=summary.semantic_cache_hits,
        abstention_rate=summary.abstention_rate,
        p50_latency_ms=summary.p50_latency_ms,
        p95_latency_ms=summary.p95_latency_ms,
        p95_cache_hit_ms=summary.p95_cache_hit_ms,
        p95_cache_miss_ms=summary.p95_cache_miss_ms,
        active_llm_model=active_llm,
        active_reranker_model=settings.reranker_model_name,
        reranker_profile=settings.reranker_profile,
    )
