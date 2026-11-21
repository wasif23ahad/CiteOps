# Phased Implementation Plan: CiteOps

**Product:** CiteOps — Multi-Tenant Tier-2 Support & Security Compliance Knowledge Engine  
**Source Specs:** [Problem.md](./Problem.md) | [PRD.md](./PRD.md) | [Architecture.md](./Architecture.md)  
**Execution Model:** 8 Vertical, Independently Verifiable Phases (Phases 0–7)  
**Last Updated:** 2026-11-21  

---

## Master Phase Tracker

| Phase | Name | Target Window | Primary Outcome | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 0** | Monorepo Scaffold, Config & Local Infra | Day 1 (AM) | Working `docker-compose`, FastAPI `/v1/health`, Next.js 16 skeleton | `[x] Complete` |
| **Phase 1** | Postgres 17 Schema, RLS & Hexagonal Core | Day 1 (Mid) | `pgvector 0.8.6` + RLS migrations, domain ports, Pydantic contracts | `[x] Complete` |
| **Phase 2** | Idempotent Ingestion, Embeddings & Seed Data | Day 1 (PM) | `POST /v1/ingest`, `/v1/documents`, `pymupdf4llm`, `gemini-embedding-001`, demo corpus | `[x] Complete` |
| **Phase 3** | Hybrid Retrieval, Reranker & Grounded Query | Day 1 (Eve) – Day 2 (AM) | Single-CTE RRF, ONNX reranker, Gemini 3.8 Flash router, Citation Verifier, Dual-Gate Abstention | `[ ] Pending` |
| **Phase 4** | Semantic Cache, Rate Limiter, Metrics & Langfuse | Day 2 (PM) | Versioned L1/L2 Redis cache, Lua rate limiter, `/v1/metrics/summary`, OTel/Langfuse tracing | `[ ] Pending` |
| **Phase 5** | Perplexity-Style Next.js 16 Frontend | Day 3 (AM–Mid) | BFF proxy, Citation Workspace, Source Drawer, Telemetry Bar, Docs & Metrics pages | `[ ] Pending` |
| **Phase 6** | Golden Evals (`DeepEval`) & Two-Tier CI Gate | Day 3 (PM) | 50-Q dataset, deterministic Recall@5, paced DeepEval smoke/full suites, GitHub Actions | `[ ] Pending` |
| **Phase 7** | `$0/month` Cloud Deployment & Benchmark Polish | Day 4 | Live Neon + Upstash + Render/HF Spaces + Vercel + Langfuse + `README.md` scorecard | `[ ] Pending` |

---

## Phase 0: Monorepo Scaffold, Environment & Local Infrastructure

**Objective:** Establish clean monorepo conventions, dependency management, environment configuration, and local Postgres/Redis containers before writing domain logic.

### Deliverables
- [x] **Root orchestration & hygiene:**
  - `.gitignore` (Python, Node/Next.js, `.env`, local ONNX cache, pytest/coverage)
  - `.env.example` (documented variables for Postgres, Redis, `GEMINI_API_KEY`, optional `GROQ_API_KEY` / `OLLAMA_BASE_URL`, `RERANKER_PROFILE`, `EMBEDDING_PROVIDER`, `LANGFUSE_*`, `CITEOPS_INTERNAL_API_KEY`)
  - `docker-compose.yml` running:
    - `postgres`: `pgvector/pgvector:0.8.6-pg17` (with healthcheck & `docker/postgres/init.sql` extension bootstrap)
    - `redis`: `redis:8-alpine` (with healthcheck)
    - `api` and `web` service definitions ready for container builds
- [x] **Backend scaffold (`apps/api/`):**
  - `pyproject.toml` (Python 3.12, `uv`-compatible, FastAPI, Uvicorn, Pydantic v2, `psycopg[binary,pool]`, `pgvector`, `redis`, `google-genai`, `fastembed`, `pymupdf4llm`, `tenacity`, `structlog`, `langfuse`, `numpy`, dev deps `pytest`, `pytest-asyncio`, `httpx`, `ruff`, `mypy`)
  - `Dockerfile` (slim Python 3.12 multi-stage build, non-root user, `--workers 1`)
  - `app/core/config.py` (typed `pydantic-settings` configuration with validation for `RERANKER_PROFILE=light|base`, `LLM_PROVIDER=gemini|ollama`, `EMBEDDING_DIM=768`)
  - `app/core/logging.py` (JSON structured logging via `structlog` + `X-Request-ID` contextvar)
  - `app/main.py` (FastAPI app factory + lifespan hook + request-ID & internal API key middleware)
  - `app/api/v1/health.py` (`GET /v1/health` checking Postgres, `vector` extension, and Redis)
- [x] **Frontend scaffold (`apps/web/`):**
  - Next.js 16 (App Router) + React 19 + TypeScript + Tailwind CSS v4 + `shadcn/ui` + Lucide Icons + TanStack Query v5
  - `Dockerfile` (standalone output build)

### Exit Gate & Verification
1. `docker compose up -d postgres redis` passes container health checks.
2. `uvicorn app.main:app` boots cleanly and `GET /v1/health` returns `200 OK` with `postgres: ok`, `pgvector: ok`, `redis: ok`.
3. `ruff check apps/api` and `npx tsc --noEmit` (in `apps/web`) exit with `0`.

---

## Phase 1: Database Schema, Multi-Tenant RLS & Hexagonal Core

**Objective:** Lock in the database schema, database-enforced tenant isolation (PostgreSQL RLS), hexagonal domain interfaces (`Protocol`s), and strict Pydantic API contracts.

### Deliverables
- [x] **SQL Schema & Migrations (`apps/api/app/db/`):**
  - `migrations/001_init.sql`:
    - `CREATE EXTENSION IF NOT EXISTS vector;`
    - Non-`BYPASSRLS` runtime role `citeops_app` granted least-privilege `SELECT, INSERT, UPDATE, DELETE`
    - Tables: `tenants`, `documents` (`UNIQUE(tenant_id, content_hash)`), `document_chunks` (`vector(768)`, dual generated `search_tsv` combining `'simple'` weight A + `'english'` weight B), and `query_audit_logs`
    - Indexes: HNSW (`vector_cosine_ops`, `m=16, ef_construction=64`), GIN (`search_tsv`), composite B-tree `(tenant_id, doc_type, document_id)`
    - `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` policies on `documents`, `document_chunks`, and `query_audit_logs`
  - `migrate.py` (idempotent migration runner tracking applied versions)
  - `pool.py` (`psycopg_pool.AsyncConnectionPool` + `pgvector.psycopg.register_vector_async` + `tenant_transaction(tenant_id)` context manager executing `SELECT set_config('app.current_tenant_id', %s, true)`)
- [x] **Hexagonal Domain & Contracts:**
  - `app/domain/models.py` (internal immutable dataclasses: `ParsedPage`, `DocumentChunkDraft`, `RetrievedChunk`, `RerankedChunk`, `VerifiedCitation`)
  - `app/domain/ports.py` (`DocumentParserPort`, `EmbeddingPort`, `HybridRetrieverPort`, `RerankerPort`, `SemanticCachePort`, `GroundedLLMPort`, `DocumentRepoPort`, `AuditRepoPort`)
  - `app/schemas/` (`common.py`, `ingest.py`, `query.py`, `documents.py`, `metrics.py`, `health.py`) with strict `tenant_id` regex validation (`^[a-z0-9][a-z0-9_-]{1,62}$`)
- [x] **Tests (`apps/api/tests/`):**
  - `test_rls_isolation.py` & `test_schemas.py` (verifies `acme-corp` cannot read `globex-io` rows, unset `app.current_tenant_id` returns `0` rows, `citeops_app` cannot bypass RLS, and cross-tenant writes fail closed)

### Exit Gate & Verification
1. Running `python -m app.db.migrate` twice succeeds idempotently.
2. `pytest apps/api/tests/test_rls_isolation.py` passes `100%`, proving `0%` cross-tenant leakage at the database engine layer.

---

## Phase 2: Idempotent Document Ingestion, Embeddings & Demo Seed Corpus

**Objective:** Deliver the complete ingestion & document lifecycle pipeline (PDF/Markdown parsing, structure-aware chunking, free-tier embeddings, SHA-256 deduplication, atomic writes) plus realistic multi-tenant seed documents.

### Deliverables
- [x] **Parsing & Structure-Aware Chunking:**
  - `app/adapters/parser_pymupdf.py` (`pymupdf4llm` `page_chunks=True` for PDFs; heading- and page-marker-preserving Markdown/text parser)
  - `app/services/chunker.py` (hierarchical H1–H3 split, keeps Markdown tables & code fences intact up to `600`-token ceiling, `450`-token target with `65`-token overlap, prepends `[Document | Version | Section | Page N]` breadcrumb to `contextual_content`)
- [x] **Embedding Adapters (`EmbeddingPort`):**
  - `app/adapters/embeddings_gemini.py` (`google-genai` `gemini-embedding-001`, `output_dimensionality=768`, L2 normalization, asymmetric `RETRIEVAL_DOCUMENT` vs. `RETRIEVAL_QUERY` formatting, batched calls with `tenacity` backoff + optional `FastEmbedEmbeddingAdapter`)
- [x] **Repository & Orchestrators:**
  - `app/adapters/repo_postgres.py` (SHA-256 fast-path lookup, single-tx document insert + optional active-version superseding + bulk chunk insert, list & cascade delete)
  - `app/adapters/corpus_version.py` (atomic `INCR tenant:version:{tenant_id}` Redis helper with fail-open degradation)
  - `app/services/ingestion.py` (`IngestionOrchestrator` keeping parsing & embedding strictly outside DB transactions; `DocumentLifecycleService`)
  - `app/api/v1/ingest.py` (`POST /v1/ingest`) and `app/api/v1/documents.py` (`GET /v1/documents`, `DELETE /v1/documents/{document_id}`)
- [x] **Realistic Demo Corpus & Seed Script:**
  - `scripts/demo_docs/` (curated Markdown docs for `acme-corp`: *Webhook Integration & Error Reference v2.4.1* containing `ERR_SIG_4092` & `v2.4.1`, *Enterprise SLA Contract v3.2* with Section 4.2 AES-256 & 15-min Sev-1 RTO, *SOC 2 & ISO-27001 Security Policy v2.1* noting HIPAA BAA requires enterprise addendum, *Production Rollback Runbook v2.4*; plus distinct private docs for `globex-io` to prove tenant isolation)
  - `scripts/seed_demo.py` (idempotent CLI seeding both tenants via `/v1/ingest`)
- [x] **Tests:**
  - `test_chunker.py` (verifies PDF page extraction, tables/code blocks aren't corrupted, and page numbers/breadcrumbs persist)
  - `test_ingest_idempotency.py` (verifies second identical upload returns `skipped_unchanged` with `0` embedding calls; cross-tenant delete returns `404`; tenant delete cascades chunks)

### Exit Gate & Verification
1. `python scripts/seed_demo.py` indexes both `acme-corp` and `globex-io`.
2. Re-running `python scripts/seed_demo.py` immediately returns `status: "skipped_unchanged"` for every file with zero embedding calls.
3. `GET /v1/documents?tenant_id=acme-corp` returns only `acme-corp` documents; `pytest` ingestion & chunker suites pass.

---

## Phase 3: Hybrid Retrieval, Calibrated Reranking & Citation-Locked Generation

**Objective:** Implement the core intelligence pipeline for `POST /v1/query`: single-CTE hybrid search with `pgvector 0.8` iterative scans, calibrated ONNX cross-encoder reranking, resilient free-tier LLM routing, deterministic citation verification, and dual-gate abstention.

### Deliverables
- [ ] **Hybrid Retrieval (`HybridRetrieverPort`):**
  - `app/adapters/retriever_postgres.py`: single-CTE SQL executing `SET LOCAL hnsw.iterative_scan = relaxed_order` + `hnsw.ef_search = 64`, fusing Top-50 dense cosine + Top-50 dual-dictionary `tsvector` (`simple` + `english`) via RRF ($k = 60$) -> Top-25 candidates (`RERANK_CANDIDATE_COUNT`).
- [ ] **Calibrated Reranker (`RerankerPort`):**
  - `app/adapters/reranker_fastembed.py`: supports `RERANKER_PROFILE=light` (`Xenova/ms-marco-MiniLM-L-6-v2`) and `base` (`BAAI/bge-reranker-base`); runs ONNX inside `asyncio.to_thread` bounded by `asyncio.Semaphore(2)`; normalizes raw logits via sigmoid $1 / (1 + e^{-x})$.
- [ ] **Resilient Free-Tier LLM Router (`GroundedLLMPort`):**
  - `app/adapters/llm_router.py`:
    - Primary: `gemini-3.8-flash` (`temperature=0.0`, `thinking_level="low"`, Pydantic `GroundedLLMOutput` structured JSON)
    - Failover 1: `gemini-3.5-flash-lite` on `429`/`503`/timeout
    - Failover 2: Optional Groq (`llama-3.3-70b-versatile`) with context trimming (`top_k <= 3`) to fit 8k–12k TPM caps
    - Privacy Mode: Optional `LLM_PROVIDER=ollama` local adapter
- [ ] **Deterministic Citation Verifier & Query Orchestrator:**
  - `app/services/verifier.py` (`CitationVerifierAndHydrator`: parses `[n]` tags, rejects out-of-bounds citations, verifies quote grounding against `chunk.content`, hydrates `document_id`, `doc_title`, `doc_type`, `version`, `page_number`, `section_path`, `rerank_score` strictly from DB records, auto-downgrades to `insufficient_evidence` on grounding failure)
  - `app/services/query.py` (`QueryOrchestrator` implementing Gate-1 pre-LLM abstention on `max(rerank_score) < MIN_RERANK_SCORE`, Gate-2 LLM abstention, and `query_audit_logs` persistence)
  - `app/api/v1/query.py` (`POST /v1/query`)
- [ ] **Tests:**
  - `test_hybrid_rrf.py` (exact error code `ERR_SIG_4092` & `Section 4.2` recall + `doc_types` filtering)
  - `test_reranker_calibration.py` (sigmoid bounds `(0, 1)` and candidate ordering)
  - `test_citation_verifier.py` (dangling `[9]`, zero citations, DB metadata hydration, quote fallback)
  - `test_abstention_gates.py` (Gate-1 zero-LLM-call abstention + Gate-2 partial-match abstention)

### Exit Gate & Verification
1. Querying `"Why does webhook signature verification fail with ERR_SIG_4092 on SDK v2.4.1?"` under `acme-corp` returns `status: "answered"` with verified inline `[1]` citation hydrated with exact `doc_title`, `page_number`, and `rerank_score`.
2. Querying an out-of-scope topic (e.g., FedRAMP High) or a `globex-io`-only fact under `acme-corp` returns `status: "insufficient_evidence"` and `citations: []` with zero leakage.
3. All unit and integration tests pass.

---

## Phase 4: Versioned Semantic Cache, Rate Limiter, Metrics & Observability

**Objective:** Achieve `< 50 ms` repeat query latency, instant $O(1)$ cache invalidation on corpus changes, free-tier quota protection, and full OpenTelemetry + Langfuse v3+ visibility.

### Deliverables
- [ ] **Generation-Versioned Redis Cache (`SemanticCachePort`):**
  - `app/adapters/cache_redis.py`:
    - `corpus_version` counter at `tenant:version:{tenant_id}`
    - L1 exact normalized hash cache (`cache:exact:{tenant_id}:v{ver}:{filter}:{hash}`, 24h TTL)
    - L2 tenant-bounded semantic cache (`cache:vec:{tenant_id}:v{ver}:{filter}`, LRU cap 500 entries, vectorized NumPy cosine similarity `> 0.95`)
    - Fail-open timeout/error wrapper so Redis outage never breaks `/v1/query`
  - Wire atomic `INCR tenant:version:{tenant_id}` into `IngestionOrchestrator` and `DocumentLifecycleService`.
- [ ] **Atomic Sliding-Window Rate Limiter:**
  - `app/core/rate_limit.py` (Redis Lua ZSET script enforcing per-tenant `20 req/min` + global LLM-miss `12 req/min`, returning HTTP `429` with `Retry-After`).
- [ ] **Metrics API & Langfuse v3+ Observability:**
  - `app/core/telemetry.py` (`langfuse` v3+ `@observe()` root trace + child spans for `cache_lookup`, `embed_query`, `hybrid_retrieval`, `rerank`, `llm_generate`, `citation_verify`; OTel scope filter dropping noisy ASGI framework spans)
  - `app/api/v1/metrics.py` (`GET /v1/metrics/summary?tenant_id=...` computing total queries, L1/L2 cache hit rate, abstention rate, and `PERCENTILE_CONT` p50/p95 latencies from `query_audit_logs`)
- [ ] **Tests:**
  - `test_semantic_cache.py` (L1 exact hit, L2 paraphrased hit > 0.95, `doc_types` scope isolation, immediate invalidation after ingest/delete, fail-open behavior)
  - `test_rate_limit.py` (per-tenant burst triggers `429`; cache hits bypass LLM-miss budget)

### Exit Gate & Verification
1. Sending an identical or semantically equivalent (`> 0.95` cosine) query returns `cache_hit: true` with `latency_ms < 50`.
2. Ingesting or deleting a document for `acme-corp` increments `corpus_version` and causes the next repeat query to recompute fresh results while leaving `globex-io`'s cache intact.
3. End-to-end spans appear in Langfuse Cloud (or local OTel log when unconfigured) with matching `trace_id` returned in `telemetry.trace_id`.

---

## Phase 5: Perplexity-Style Next.js 16 Frontend (`apps/web`)

**Objective:** Deliver a clean, responsive, citation-first technical UI wired through a secure Next.js BFF proxy.

### Deliverables
- [ ] **BFF Proxy & Typed Client (`apps/web/src/`):**
  - `app/api/citeops/[...path]/route.ts` (server-side proxy injecting `CITEOPS_INTERNAL_API_KEY`, supporting both JSON and `multipart/form-data` streaming)
  - `lib/types.ts` & `lib/api.ts` (strict TypeScript types mirroring FastAPI schemas) + `components/providers.tsx` (TanStack Query v5 + theme toggle)
- [ ] **Citation Workspace (`app/page.tsx`):**
  - Top navigation + `TenantSelector` (`acme-corp`, `globex-io`) + `DocTypeFilterPills` (`all`, `api_docs`, `security_policy`, `sla_contract`, `runbook`)
  - `QueryBox` with clickable sample RFP & Tier-2 incident prompt chips
  - `AnswerCard`: safely tokenizes `[1]`, `[2]` markers into interactive `CitationBadge` pills; renders clear amber **Insufficient Evidence** panel with `missing_evidence_reason` when abstaining
  - `TelemetryBar`: live `latency_ms`, `CACHE HIT (EXACT / SEMANTIC)` vs. `CACHE MISS` badge, `top_rerank_score`, active `model`, and `trace_id`
  - `SourceDrawer`: slide-over / side panel highlighting active citation's `doc_title`, `version`, `doc_type`, `page_number`, `section_path`, calibrated `rerank_score`, and verbatim `excerpt`
- [ ] **Knowledge Base Manager (`app/documents/page.tsx`):**
  - `UploadModal` (drag-and-drop `.pdf`/`.md`, `doc_type`, `version`) displaying `indexed` chunk count vs. `skipped_unchanged` (`$0` badge)
  - Tenant document inventory table with SHA-256 hash preview, page/chunk counts, and `Delete` action with TanStack Query cache invalidation
- [ ] **Metrics Dashboard (`app/metrics/page.tsx`):**
  - Summary KPI cards (Total Queries, Cache Hit Rate L1/L2, Abstention Rate, p50/p95 Latency Hit vs. Miss, active reranker/LLM profile)

### Exit Gate & Verification
1. `npm run lint`, `npx tsc --noEmit`, and `npm run build` succeed cleanly.
2. End-to-end manual/browser test confirms: workspace query -> inline `[n]` click opens `SourceDrawer` -> repeat query shows `CACHE HIT` badge `< 50 ms` -> uploading duplicate file shows `skipped_unchanged` -> deleting file updates inventory & invalidates cache.

---

## Phase 6: Golden Evaluation Suite (`evals/`) & Two-Tier GitHub Actions CI Gate

**Objective:** Operationalize Eval-Driven Development with a 50-question golden benchmark and free-tier-safe automated regression gates in GitHub Actions.

### Deliverables
- [ ] **Golden Benchmark Dataset (`evals/datasets/golden_50.jsonl`):**
  - 50 curated evaluation records across `acme-corp` & `globex-io`:
    - 15 exact error-code / SDK version lookups
    - 15 enterprise RFP / SOC 2 / SLA policy compliance questions (including nuanced conditional clauses like HIPAA BAA addendum)
    - 10 multi-passage / table synthesis questions
    - 10 out-of-scope abstention & cross-tenant isolation probes
- [ ] **Evaluation Harnesses (`evals/`):**
  - `evals/test_retrieval_deterministic.py` (0 LLM calls; verifies Context Recall@5 `>= 0.85` & `0%` cross-tenant leakage across all 50 Qs)
  - `evals/test_rag_quality.py` (`DeepEval` configured with `GeminiModel(model="gemini-3.5-flash-lite")`, `max_concurrent=2` + retry backoff; `--suite smoke` = 12 stratified Qs; `--suite full` = 50 Qs; thresholds: Faithfulness `>= 0.90`, Answer Relevancy `>= 0.85`, Abstention Accuracy `== 1.0`)
  - `evals/run_benchmark.py` (CLI generating Markdown & JSON scorecards with accuracy metrics + cache-hit/miss p50/p95 latency)
- [ ] **GitHub Actions Workflows (`.github/workflows/`):**
  - `ci.yml` (Tier-1 PR Gate: `ruff`, `mypy`, `eslint`, `tsc`, Postgres+Redis service containers, unit + RLS integration tests, 50-Q deterministic Recall@5 gate, and 12-Q DeepEval smoke gate)
  - `eval_full.yml` (Tier-2 Nightly / `workflow_dispatch`: paced 50-Q DeepEval benchmark publishing Markdown job summary & JSON artifact)

### Exit Gate & Verification
1. `pytest evals/test_retrieval_deterministic.py` achieves Context Recall@5 `>= 0.85` and `0%` leakage.
2. `pytest evals/test_rag_quality.py --suite smoke` passes with Faithfulness `>= 0.90` and Abstention `= 100%` without hitting unhandled `429` failures.
3. `python evals/run_benchmark.py` outputs a reproducible Markdown scorecard.

---

## Phase 7: `$0/month` Cloud Deployment, Live Benchmarking & Documentation Polish

**Objective:** Deploy the complete stack live at `$0/month`, validate production memory/latency constraints, capture real benchmark evidence, and finalize portfolio documentation.

### Deliverables
- [ ] **Cloud Provisioning & Secrets:**
  - **Neon Free:** Provision Postgres 17 + `pgvector`, run `001_init.sql` (including `citeops_app` role), seed demo tenants via `seed_demo.py`.
  - **Upstash Redis Free:** Provision Redis instance and configure TLS `REDIS_URL`.
  - **Langfuse Cloud Hobby & Google AI Studio Free:** Configure API keys in host secret managers.
- [ ] **Service Deployments:**
  - **API (`apps/api`):** Deploy Docker image to **Render Free** (`RERANKER_PROFILE=light`, `uvicorn --workers 1`, verify steady-state RSS `<= 400 MB`) *or* **Hugging Face Spaces Docker Free** (`RERANKER_PROFILE=base` with 16 GB RAM).
  - **Web (`apps/web`):** Deploy to **Vercel Hobby** with `CITEOPS_API_URL` and `CITEOPS_INTERNAL_API_KEY`.
- [ ] **Live Verification & `README.md` Polish:**
  - Run `python evals/run_benchmark.py --target <LIVE_API_URL>` to record live p50/p95 latency (cache hit vs. miss) and full 50-question DeepEval scores.
  - Author production `README.md` featuring live demo URLs, system architecture diagram, local one-command quickstart (`docker compose up`), measured benchmark scorecard table, and ADR trade-off highlights.

### Exit Gate & Verification
1. Live Vercel app resolves queries against live API/Neon/Upstash, displays clickable source citations, shows `< 50 ms` server-side cache hits, and safely abstains on out-of-scope prompts.
2. Live container RSS stays within host ceiling (`<= 400 MB` on 512 MB Render Free) with zero OOM restarts.
3. `README.md` contains verified benchmark outputs and clean setup instructions.
