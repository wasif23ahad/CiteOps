import asyncio
import hmac
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from app.adapters.audit_postgres import PostgresAuditRepository
from app.adapters.cache_redis import RedisSemanticCache
from app.adapters.corpus_version import CorpusVersionStore
from app.adapters.embeddings_gemini import create_embedding_adapter
from app.adapters.llm_router import ResilientLLMRouter
from app.adapters.parser_pymupdf import PyMuPDFDocumentParser
from app.adapters.repo_postgres import PostgresDocumentRepository
from app.adapters.reranker_fastembed import FastEmbedReranker
from app.adapters.retriever_postgres import PostgresHybridRetriever
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.ingest import router as ingest_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.query import router as query_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger, request_id_ctx
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.telemetry import TelemetryTracer
from app.db.pool import create_db_pool
from app.services.chunker import StructureAwareChunker
from app.services.ingestion import DocumentLifecycleService, IngestionOrchestrator
from app.services.query import QueryOrchestrator
from app.services.verifier import CitationVerifierAndHydrator

logger = get_logger(__name__)

_PUBLIC_PATHS = frozenset({"/v1/health", "/docs", "/redoc", "/openapi.json"})


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)

    db_pool: AsyncConnectionPool | None = None
    redis_client: Redis | None = None
    cpu_semaphore = asyncio.Semaphore(2)
    telemetry = TelemetryTracer(settings)

    if settings.app_env != "test":
        db_pool = create_db_pool(settings)
        try:
            await db_pool.open(wait=False)
        except Exception as exc:
            logger.warning("postgres_pool_init_warning", error=str(exc))

        try:
            redis_client = Redis.from_url(
                settings.redis_url,
                decode_responses=False,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
            )
        except Exception as exc:
            logger.warning("redis_init_warning", error=str(exc))

    app.state.db_pool = db_pool
    app.state.redis = redis_client
    app.state.cpu_semaphore = cpu_semaphore
    app.state.telemetry = telemetry

    corpus_versions = CorpusVersionStore(redis_client)
    semantic_cache = RedisSemanticCache(
        redis_client,
        similarity_threshold=settings.semantic_cache_threshold,
        max_entries=settings.semantic_cache_max_entries,
        default_ttl_seconds=settings.cache_ttl_seconds,
    )
    rate_limiter = SlidingWindowRateLimiter(
        redis_client,
        tenant_rpm=settings.rate_limit_tenant_rpm,
        global_llm_rpm=settings.rate_limit_global_llm_rpm,
    )
    app.state.corpus_versions = corpus_versions
    app.state.semantic_cache = semantic_cache
    app.state.rate_limiter = rate_limiter

    if db_pool is not None:
        doc_repo = PostgresDocumentRepository(db_pool)
        audit_repo = PostgresAuditRepository(db_pool)
        retriever = PostgresHybridRetriever(db_pool)
        reranker = FastEmbedReranker(
            model_name=settings.reranker_model_name,
            cpu_semaphore=cpu_semaphore,
        )
        llm_router = ResilientLLMRouter(settings)
        verifier = CitationVerifierAndHydrator()

        app.state.document_repo = doc_repo
        app.state.audit_repo = audit_repo
        app.state.retriever = retriever
        app.state.reranker = reranker
        app.state.llm_router = llm_router
        app.state.document_lifecycle_service = DocumentLifecycleService(
            repo=doc_repo,
            corpus_versions=corpus_versions,
        )

        try:
            embedder = create_embedding_adapter(settings)
            app.state.embedder = embedder
            app.state.ingestion_orchestrator = IngestionOrchestrator(
                parser=PyMuPDFDocumentParser(),
                chunker=StructureAwareChunker(),
                embedder=embedder,
                repo=doc_repo,
                corpus_versions=corpus_versions,
                cpu_semaphore=cpu_semaphore,
            )
            app.state.query_orchestrator = QueryOrchestrator(
                settings=settings,
                embedder=embedder,
                retriever=retriever,
                reranker=reranker,
                llm=llm_router,
                verifier=verifier,
                audit_repo=audit_repo,
                cache=semantic_cache,
                rate_limiter=rate_limiter,
                telemetry=telemetry,
            )
        except Exception as exc:
            logger.warning("embedder_init_warning", error=str(exc))

    logger.info(
        "app_startup_complete",
        environment=settings.app_env,
        llm_provider=settings.llm_provider,
        reranker_profile=settings.reranker_profile,
        embedding_provider=settings.embedding_provider,
        langfuse_enabled=telemetry.enabled,
    )
    try:
        yield
    finally:
        telemetry.shutdown()
        if redis_client is not None:
            await redis_client.aclose()
        if db_pool is not None:
            await db_pool.close()
        logger.info("app_shutdown_complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        description="Multi-Tenant Tier-2 Support & Security Compliance Knowledge Engine",
        lifespan=_lifespan,
    )
    app.state.settings = resolved_settings
    app.state.db_pool = None
    app.state.redis = None
    app.state.audit_repo = None
    app.state.ingestion_orchestrator = None
    app.state.document_lifecycle_service = None
    app.state.query_orchestrator = None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context_and_auth_middleware(
        request: Request, call_next: object
    ) -> Response:
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_ctx.set(req_id)
        started = time.perf_counter()

        try:
            expected_key = resolved_settings.citeops_internal_api_key
            if (
                expected_key
                and request.method != "OPTIONS"
                and request.url.path not in _PUBLIC_PATHS
            ):
                provided_key = request.headers.get("X-Internal-API-Key", "")
                if not hmac.compare_digest(provided_key, expected_key):
                    return JSONResponse(
                        status_code=401,
                        content={
                            "detail": "Missing or invalid internal API key",
                            "request_id": req_id,
                        },
                        headers={"X-Request-ID": req_id},
                    )

            response: Response = await call_next(request)  # type: ignore[operator]
            response.headers["X-Request-ID"] = req_id
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                latency_ms=elapsed_ms,
            )
            return response
        finally:
            request_id_ctx.reset(token)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        req_id = request_id_ctx.get() or uuid.uuid4().hex
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": req_id},
            headers={"X-Request-ID": req_id},
        )

    app.include_router(health_router, prefix=resolved_settings.api_v1_prefix)
    app.include_router(ingest_router, prefix=resolved_settings.api_v1_prefix)
    app.include_router(documents_router, prefix=resolved_settings.api_v1_prefix)
    app.include_router(query_router, prefix=resolved_settings.api_v1_prefix)
    app.include_router(metrics_router, prefix=resolved_settings.api_v1_prefix)
    return app


app = create_app()
