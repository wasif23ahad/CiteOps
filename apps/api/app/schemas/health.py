from typing import Literal

from pydantic import BaseModel


class DependencyCheck(BaseModel):
    status: Literal["ok", "degraded", "error"]
    detail: str | None = None
    latency_ms: float | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "unhealthy"]
    service: str
    environment: str
    reranker_profile: str
    reranker_model: str
    llm_provider: str
    llm_model: str
    embedding_model: str
    embedding_dim: int
    dependencies: dict[str, DependencyCheck]
