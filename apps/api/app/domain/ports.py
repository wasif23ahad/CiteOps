from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from app.domain.models import (
    DocType,
    DocumentChunkDraft,
    DocumentRecord,
    GroundedLLMResult,
    ParsedPage,
    QueryAuditRecord,
    RerankedChunk,
    RetrievedChunk,
    TenantMetricsSummary,
)


@runtime_checkable
class DocumentParserPort(Protocol):
    def parse(self, file_bytes: bytes, filename: str) -> list[ParsedPage]:
        """Extract page-indexed Markdown text from uploaded PDF/Markdown/text bytes."""
        ...


@runtime_checkable
class EmbeddingPort(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Generate normalized dense vectors for document chunks."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Generate a normalized dense vector for an incoming search query."""
        ...


@runtime_checkable
class DocumentRepoPort(Protocol):
    async def ensure_tenant(self, tenant_id: str, name: str | None = None) -> None: ...

    async def find_active_by_hash(
        self, tenant_id: str, content_hash: str
    ) -> DocumentRecord | None: ...

    async def save_document_with_chunks(
        self,
        *,
        tenant_id: str,
        doc_title: str,
        doc_type: DocType,
        version: str,
        source_filename: str,
        content_hash: str,
        embedding_model: str,
        embedding_dim: int,
        page_count: int,
        chunks: Sequence[DocumentChunkDraft],
        embeddings: Sequence[list[float]],
        replace_existing: bool = True,
    ) -> DocumentRecord: ...

    async def list_documents(
        self, tenant_id: str, doc_type: DocType | None = None
    ) -> list[DocumentRecord]: ...

    async def delete_document(self, tenant_id: str, document_id: UUID) -> bool: ...


@runtime_checkable
class HybridRetrieverPort(Protocol):
    async def retrieve(
        self,
        *,
        tenant_id: str,
        query_text: str,
        query_embedding: list[float],
        doc_types: Sequence[DocType] | None = None,
        candidate_limit: int = 25,
    ) -> list[RetrievedChunk]: ...


@runtime_checkable
class RerankerPort(Protocol):
    @property
    def model_name(self) -> str: ...

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievedChunk],
        top_k: int = 5,
    ) -> list[RerankedChunk]: ...


@runtime_checkable
class SemanticCachePort(Protocol):
    async def get_corpus_version(self, tenant_id: str) -> int: ...

    async def bump_corpus_version(self, tenant_id: str) -> int: ...

    async def lookup_exact(
        self,
        *,
        tenant_id: str,
        corpus_version: int,
        doc_types: Sequence[DocType] | None,
        query: str,
    ) -> dict[str, Any] | None: ...

    async def lookup_semantic(
        self,
        *,
        tenant_id: str,
        corpus_version: int,
        doc_types: Sequence[DocType] | None,
        query_embedding: list[float],
    ) -> tuple[dict[str, Any], float] | None: ...

    async def store(
        self,
        *,
        tenant_id: str,
        corpus_version: int,
        doc_types: Sequence[DocType] | None,
        query: str,
        query_embedding: list[float] | None,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None: ...


@runtime_checkable
class GroundedLLMPort(Protocol):
    async def generate(
        self,
        *,
        query: str,
        passages: Sequence[RerankedChunk],
    ) -> tuple[GroundedLLMResult, str]:
        """Generate a structured citation-locked response and return (result, model_used)."""
        ...


@runtime_checkable
class AuditRepoPort(Protocol):
    async def record_query(self, record: QueryAuditRecord) -> None: ...

    async def get_metrics_summary(self, tenant_id: str) -> TenantMetricsSummary: ...
