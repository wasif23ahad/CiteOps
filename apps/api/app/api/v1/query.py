from fastapi import APIRouter, HTTPException, Request, status

from app.adapters.llm_router import LLMUnavailableError
from app.core.logging import get_logger, request_id_ctx
from app.core.rate_limit import RateLimitExceededError
from app.schemas.query import QueryRequest, QueryResponse
from app.services.query import QueryOrchestrator

logger = get_logger(__name__)
router = APIRouter(tags=["query"])


def _get_query_orchestrator(request: Request) -> QueryOrchestrator:
    orchestrator: QueryOrchestrator | None = getattr(
        request.app.state, "query_orchestrator", None
    )
    if orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Query service is not initialized (check DB and GEMINI_API_KEY).",
        )
    return orchestrator


@router.post("/query", response_model=QueryResponse)
async def execute_query(request: Request, payload: QueryRequest) -> QueryResponse:
    """Execute a citation-locked, tenant-isolated hybrid retrieval and grounded synthesis query."""
    orchestrator = _get_query_orchestrator(request)
    trace_id = request_id_ctx.get()

    try:
        return await orchestrator.execute(payload, trace_id=trace_id)
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.detail,
            headers={
                "Retry-After": str(exc.decision.retry_after_seconds),
                "X-RateLimit-Limit": str(exc.decision.limit),
                "X-RateLimit-Remaining": str(exc.decision.remaining),
            },
        ) from exc
    except LLMUnavailableError as exc:
        logger.warning(
            "query_llm_unavailable",
            tenant_id=payload.tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "All upstream LLM providers are temporarily unavailable or rate-limited. "
                "Please retry shortly."
            ),
            headers={"Retry-After": "10"},
        ) from exc
