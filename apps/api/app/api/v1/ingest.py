from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from app.adapters.parser_pymupdf import UnsupportedDocumentFormatError
from app.domain.models import DocType
from app.schemas.ingest import IngestResponse
from app.services.ingestion import IngestionOrchestrator, PayloadTooLargeError

router = APIRouter(tags=["ingestion"])


def _get_orchestrator(request: Request) -> IngestionOrchestrator:
    orchestrator: IngestionOrchestrator | None = getattr(
        request.app.state, "ingestion_orchestrator", None
    )
    if orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ingestion service is not initialized (check DB and GEMINI_API_KEY).",
        )
    return orchestrator


@router.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    request: Request,
    file: Annotated[UploadFile, File(description="PDF, Markdown, or plain-text document")],
    tenant_id: Annotated[str, Form(min_length=2, max_length=63)],
    doc_type: Annotated[DocType, Form()],
    version: Annotated[str, Form(min_length=1, max_length=64)],
    doc_title: Annotated[str | None, Form(max_length=200)] = None,
    replace_existing: Annotated[bool, Form()] = True,
) -> IngestResponse:
    """Idempotently ingest a PDF or Markdown file into a tenant's isolated knowledge base."""
    orchestrator = _get_orchestrator(request)
    file_bytes = await file.read()
    filename = file.filename or "uploaded_document.md"

    try:
        return await orchestrator.ingest(
            tenant_id=tenant_id,
            file_bytes=file_bytes,
            filename=filename,
            doc_type=doc_type,
            version=version.strip(),
            doc_title=doc_title,
            replace_existing=replace_existing,
        )
    except PayloadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except (UnsupportedDocumentFormatError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
