from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import DocType, TenantId


class DocumentSummary(BaseModel):
    id: UUID
    tenant_id: TenantId
    doc_title: str
    doc_type: DocType
    version: str
    source_filename: str
    content_hash: str = Field(min_length=64, max_length=64)
    embedding_model: str
    embedding_dim: int
    page_count: int
    chunk_count: int
    is_active: bool
    created_at: datetime


class DocumentListResponse(BaseModel):
    tenant_id: TenantId
    total: int = Field(ge=0)
    documents: list[DocumentSummary]


class DocumentDeleteResponse(BaseModel):
    deleted: bool
    document_id: UUID
    tenant_id: TenantId
    corpus_version: int = Field(ge=1)
