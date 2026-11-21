from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.domain.models import DocType
from app.schemas.common import TENANT_ID_PATTERN
from app.schemas.documents import DocumentDeleteResponse, DocumentListResponse
from app.services.ingestion import DocumentLifecycleService

router = APIRouter(tags=["documents"])


def _get_lifecycle_service(request: Request) -> DocumentLifecycleService:
    svc: DocumentLifecycleService | None = getattr(
        request.app.state, "document_lifecycle_service", None
    )
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document service is not initialized.",
        )
    return svc


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    request: Request,
    tenant_id: Annotated[str, Query(pattern=TENANT_ID_PATTERN)],
    doc_type: Annotated[DocType | None, Query()] = None,
) -> DocumentListResponse:
    """List active documents belonging strictly to `tenant_id`."""
    svc = _get_lifecycle_service(request)
    return await svc.list_documents(tenant_id=tenant_id, doc_type=doc_type)


@router.delete("/documents/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    request: Request,
    document_id: UUID,
    tenant_id: Annotated[str, Query(pattern=TENANT_ID_PATTERN)],
) -> DocumentDeleteResponse:
    """Delete a tenant's document + chunks (RLS-enforced) and invalidate tenant caches."""
    svc = _get_lifecycle_service(request)
    result = await svc.delete_document(tenant_id=tenant_id, document_id=document_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found for tenant '{tenant_id}'.",
        )
    return result
