from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import DocType, TenantId


class IngestResponse(BaseModel):
    status: Literal["indexed", "skipped_unchanged"]
    document_id: UUID
    tenant_id: TenantId
    doc_title: str
    doc_type: DocType
    version: str
    content_hash: str = Field(min_length=64, max_length=64)
    page_count: int = Field(ge=1)
    chunk_count: int = Field(ge=0)
    corpus_version: int = Field(ge=1)
    latency_ms: int = Field(ge=0)
