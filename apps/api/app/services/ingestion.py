import asyncio
import hashlib
import time
from pathlib import Path
from uuid import UUID

from app.adapters.corpus_version import CorpusVersionStore
from app.core.logging import get_logger
from app.db.pool import validate_tenant_id
from app.domain.models import DocType, DocumentChunkDraft, DocumentRecord, ParsedPage
from app.domain.ports import DocumentParserPort, DocumentRepoPort, EmbeddingPort
from app.schemas.documents import DocumentDeleteResponse, DocumentListResponse, DocumentSummary
from app.schemas.ingest import IngestResponse
from app.services.chunker import StructureAwareChunker

logger = get_logger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB


class PayloadTooLargeError(ValueError):
    """Raised when an uploaded document exceeds MAX_UPLOAD_BYTES."""


class IngestionOrchestrator:
    """
    Coordinates idempotent document ingestion with out-of-transaction parsing/embedding
    and single-transaction PostgreSQL commits + O(1) Redis corpus_version bumps.
    """

    def __init__(
        self,
        *,
        parser: DocumentParserPort,
        chunker: StructureAwareChunker,
        embedder: EmbeddingPort,
        repo: DocumentRepoPort,
        corpus_versions: CorpusVersionStore,
        cpu_semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self._parser = parser
        self._chunker = chunker
        self._embedder = embedder
        self._repo = repo
        self._corpus_versions = corpus_versions
        self._cpu_semaphore = cpu_semaphore or asyncio.Semaphore(2)

    async def ingest(
        self,
        *,
        tenant_id: str,
        file_bytes: bytes,
        filename: str,
        doc_type: DocType,
        version: str,
        doc_title: str | None = None,
        replace_existing: bool = True,
    ) -> IngestResponse:
        started = time.perf_counter()
        validated_tenant = validate_tenant_id(tenant_id)

        if len(file_bytes) > MAX_UPLOAD_BYTES:
            raise PayloadTooLargeError(
                f"File exceeds maximum size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            )

        content_hash = hashlib.sha256(file_bytes).hexdigest()
        resolved_title = (doc_title or "").strip() or Path(filename).stem

        # 1. Fast-path SHA-256 idempotency check ($0 embedding cost on unchanged files)
        existing = await self._repo.find_active_by_hash(validated_tenant, content_hash)
        if existing is not None:
            corpus_version = await self._corpus_versions.get_version(validated_tenant)
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "ingest_skipped_unchanged",
                tenant_id=validated_tenant,
                document_id=str(existing.id),
                content_hash=content_hash[:12],
                latency_ms=latency_ms,
            )
            return IngestResponse(
                status="skipped_unchanged",
                document_id=existing.id,
                tenant_id=existing.tenant_id,
                doc_title=existing.doc_title,
                doc_type=existing.doc_type,
                version=existing.version,
                content_hash=existing.content_hash,
                page_count=existing.page_count,
                chunk_count=0,
                corpus_version=corpus_version,
                latency_ms=latency_ms,
            )

        # 2. CPU-bound parsing & structure-aware chunking strictly outside DB transaction
        pages, chunks = await self._parse_and_chunk(
            file_bytes=file_bytes,
            filename=filename,
            doc_title=resolved_title,
            version=version,
        )
        page_count = max(p.page_number for p in pages)

        # 3. External embedding API call strictly outside DB transaction
        embeddings = await self._embedder.embed_documents(
            [chunk.contextual_content for chunk in chunks]
        )

        # 4. Single short atomic DB transaction (RLS-enforced)
        saved = await self._repo.save_document_with_chunks(
            tenant_id=validated_tenant,
            doc_title=resolved_title,
            doc_type=doc_type,
            version=version,
            source_filename=filename,
            content_hash=content_hash,
            embedding_model=self._embedder.model_name,
            embedding_dim=self._embedder.dimensions,
            page_count=page_count,
            chunks=chunks,
            embeddings=embeddings,
            replace_existing=replace_existing,
        )

        # 5. Atomic O(1) cache invalidation via corpus_version increment
        corpus_version = await self._corpus_versions.bump_version(validated_tenant)
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "ingest_indexed",
            tenant_id=validated_tenant,
            document_id=str(saved.id),
            doc_type=doc_type,
            page_count=saved.page_count,
            chunk_count=saved.chunk_count,
            corpus_version=corpus_version,
            latency_ms=latency_ms,
        )
        return IngestResponse(
            status="indexed",
            document_id=saved.id,
            tenant_id=saved.tenant_id,
            doc_title=saved.doc_title,
            doc_type=saved.doc_type,
            version=saved.version,
            content_hash=saved.content_hash,
            page_count=saved.page_count,
            chunk_count=saved.chunk_count,
            corpus_version=corpus_version,
            latency_ms=latency_ms,
        )

    async def _parse_and_chunk(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        doc_title: str,
        version: str,
    ) -> tuple[list[ParsedPage], list[DocumentChunkDraft]]:
        def _work() -> tuple[list[ParsedPage], list[DocumentChunkDraft]]:
            pages = self._parser.parse(file_bytes, filename)
            chunks = self._chunker.chunk(pages, doc_title=doc_title, version=version)
            return pages, chunks

        async with self._cpu_semaphore:
            return await asyncio.to_thread(_work)


class DocumentLifecycleService:
    """Handles listing and deleting tenant documents with instant cache invalidation."""

    def __init__(
        self,
        *,
        repo: DocumentRepoPort,
        corpus_versions: CorpusVersionStore,
    ) -> None:
        self._repo = repo
        self._corpus_versions = corpus_versions

    async def list_documents(
        self, tenant_id: str, doc_type: DocType | None = None
    ) -> DocumentListResponse:
        validated_tenant = validate_tenant_id(tenant_id)
        records = await self._repo.list_documents(validated_tenant, doc_type=doc_type)
        summaries = [self._to_summary(r) for r in records]
        return DocumentListResponse(
            tenant_id=validated_tenant,
            total=len(summaries),
            documents=summaries,
        )

    async def delete_document(
        self, tenant_id: str, document_id: UUID
    ) -> DocumentDeleteResponse | None:
        validated_tenant = validate_tenant_id(tenant_id)
        deleted = await self._repo.delete_document(validated_tenant, document_id)
        if not deleted:
            return None
        corpus_version = await self._corpus_versions.bump_version(validated_tenant)
        logger.info(
            "document_deleted",
            tenant_id=validated_tenant,
            document_id=str(document_id),
            corpus_version=corpus_version,
        )
        return DocumentDeleteResponse(
            deleted=True,
            document_id=document_id,
            tenant_id=validated_tenant,
            corpus_version=corpus_version,
        )

    @staticmethod
    def _to_summary(record: DocumentRecord) -> DocumentSummary:
        return DocumentSummary(
            id=record.id,
            tenant_id=record.tenant_id,
            doc_title=record.doc_title,
            doc_type=record.doc_type,
            version=record.version,
            source_filename=record.source_filename,
            content_hash=record.content_hash,
            embedding_model=record.embedding_model,
            embedding_dim=record.embedding_dim,
            page_count=record.page_count,
            chunk_count=record.chunk_count,
            is_active=record.is_active,
            created_at=record.created_at,
        )
