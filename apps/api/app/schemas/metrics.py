from pydantic import BaseModel, Field

from app.schemas.common import TenantId


class MetricsSummaryResponse(BaseModel):
    tenant_id: TenantId
    total_queries: int = Field(ge=0)
    cache_hit_rate: float = Field(ge=0.0, le=1.0)
    exact_cache_hits: int = Field(ge=0)
    semantic_cache_hits: int = Field(ge=0)
    abstention_rate: float = Field(ge=0.0, le=1.0)
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    p95_cache_hit_ms: float | None = None
    p95_cache_miss_ms: float | None = None
    active_llm_model: str
    active_reranker_model: str
    reranker_profile: str
