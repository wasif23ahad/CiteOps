from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import CacheTier, DocType, TenantId


class QueryRequest(BaseModel):
    tenant_id: TenantId
    query: str = Field(min_length=3, max_length=2000)
    doc_types: list[DocType] | None = None
    top_k: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("Query must contain at least 3 non-whitespace characters.")
        return cleaned

    @field_validator("doc_types")
    @classmethod
    def normalize_doc_types(cls, value: list[DocType] | None) -> list[DocType] | None:
        if not value:
            return None
        return sorted(set(value))


class CitationItem(BaseModel):
    citation_index: int = Field(ge=1)
    document_id: UUID
    doc_title: str
    doc_type: DocType
    version: str
    page_number: int = Field(ge=1)
    section_path: str
    rerank_score: float = Field(ge=0.0, le=1.0)
    excerpt: str


class QueryTelemetry(BaseModel):
    cache_hit: bool
    cache_tier: CacheTier
    latency_ms: int = Field(ge=0)
    retrieval_ms: int = Field(ge=0)
    rerank_ms: int = Field(ge=0)
    llm_ms: int = Field(ge=0)
    model: str
    reranker_model: str
    top_rerank_score: float | None = Field(default=None, ge=0.0, le=1.0)
    trace_id: str


class QueryResponse(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    missing_evidence_reason: str | None = None
    citations: list[CitationItem]
    telemetry: QueryTelemetry


class UsedPassageSchema(BaseModel):
    passage_index: int = Field(ge=1, description="1-based index of the cited context passage.")
    supporting_quote: str = Field(
        description="Short verbatim quote copied directly from the cited passage."
    )


class GroundedLLMOutputSchema(BaseModel):
    """Strict Pydantic schema passed to Gemini/LLM Structured Outputs."""

    status: Literal["answered", "insufficient_evidence"]
    answer: str = Field(
        description=(
            "Grounded answer citing inline markers like [1][2], or a concise explanation "
            "when evidence is insufficient."
        )
    )
    missing_evidence_reason: str | None = Field(
        default=None,
        description="Required when status is insufficient_evidence; describes missing proof.",
    )
    used_passages: list[UsedPassageSchema] = Field(default_factory=list)
