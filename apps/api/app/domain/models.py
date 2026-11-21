from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

DocType = Literal["api_docs", "security_policy", "sla_contract", "runbook"]
QueryStatus = Literal["answered", "insufficient_evidence", "error"]
CacheTier = Literal["exact", "semantic", "miss"]


@dataclass(frozen=True, slots=True)
class ParsedPage:
    page_number: int
    markdown_text: str


@dataclass(frozen=True, slots=True)
class DocumentChunkDraft:
    chunk_index: int
    page_number: int
    section_path: str
    content: str
    contextual_content: str
    token_count: int


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    id: UUID
    tenant_id: str
    doc_title: str
    doc_type: DocType
    version: str
    source_filename: str
    content_hash: str
    embedding_model: str
    embedding_dim: int
    page_count: int
    chunk_count: int
    is_active: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    doc_title: str
    doc_type: DocType
    version: str
    page_number: int
    section_path: str
    content: str
    contextual_content: str
    rrf_score: float


@dataclass(frozen=True, slots=True)
class RerankedChunk:
    chunk: RetrievedChunk
    raw_logit: float
    rerank_score: float


@dataclass(frozen=True, slots=True)
class LLMUsedPassage:
    passage_index: int
    supporting_quote: str


@dataclass(frozen=True, slots=True)
class GroundedLLMResult:
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    missing_evidence_reason: str | None = None
    used_passages: tuple[LLMUsedPassage, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class VerifiedCitation:
    citation_index: int
    document_id: UUID
    doc_title: str
    doc_type: DocType
    version: str
    page_number: int
    section_path: str
    rerank_score: float
    excerpt: str


@dataclass(frozen=True, slots=True)
class QueryAuditRecord:
    tenant_id: str
    trace_id: str
    status: QueryStatus
    cache_hit: bool
    cache_tier: CacheTier
    model: str
    reranker_model: str
    top_rerank_score: float | None
    latency_ms: int
    retrieval_ms: int
    rerank_ms: int
    llm_ms: int


@dataclass(frozen=True, slots=True)
class TenantMetricsSummary:
    tenant_id: str
    total_queries: int
    cache_hit_rate: float
    exact_cache_hits: int
    semantic_cache_hits: int
    abstention_rate: float
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    p95_cache_hit_ms: float | None
    p95_cache_miss_ms: float | None
