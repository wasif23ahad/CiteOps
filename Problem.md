# Problem Statement & System Specification: CiteOps

**Project Name:** CiteOps — Multi-Tenant Tier-2 Support & Security Compliance Knowledge Engine  
**Document Type:** Engineering Problem Statement & Architecture Spec (PRD / RFC)  
**Target Role Positioning:** Senior Applied AI / AI Systems Engineer  

---

## 1. Business Context & Real-World Problem

### The Scenario
**CloudPulse Infrastructure** is a B2B developer-platform company serving 150+ enterprise customers. Every week, its **Solutions Architects** and **Tier-2 Support Engineers** lose **15+ engineering hours** manually searching across 300+ pages of fragmented technical and legal documentation—including API specifications, SDK error-code references, SOC 2 / ISO-27001 security policies, Enterprise SLA contracts, and release changelogs—to resolve two mission-critical workflows:

1. **Enterprise Security & RFP Questionnaires (Pre-Sales & Legal):**
   * *Example Query:* *"Under Section 4.2 of the Enterprise SLA, is AES-256 encryption enforced at rest, and what is the guaranteed Sev-1 RTO failover window?"*
   * *Business Risk:* Inaccurate or unverified claims create immediate legal and compliance liability. If an engineer or AI states that a HIPAA BAA is included by default when it actually requires an enterprise addendum, the company risks a contract breach.
2. **Tier-2 Production Incident Escalations (Post-Sales Engineering):**
   * *Example Query:* *"Why does webhook signature verification fail with `ERR_SIG_4092` on SDK `v2.4.1`, and what is the rollback procedure?"*
   * *Business Risk:* Slow root-cause lookup delays incident resolution, breaching SLA response windows and causing customer churn.

### Why Standard RAG Prototypes Fail in Production
Most existing RAG implementations fail when deployed to B2B support and compliance teams due to four structural flaws:
* **Dense-Only Retrieval Blind Spots:** Pure vector embeddings capture broad semantics well but routinely miss exact alphanumeric identifiers such as `ERR_SIG_4092`, `v2.4.1`, or `Section 4.2`.
* **Uncited Guesswork & Hallucination:** Standard LLM wrappers blend retrieved context with parametric memory, producing confident-sounding answers without verifiable source proof or a safe mechanism to abstain when documentation is missing.
* **Redundant Latency & Token Spend:** Support and RFP teams ask the same 100 security and API questions repeatedly across different customer tickets, paying full LLM inference latency and API fees on every duplicate query.
* **Silent Quality Regressions:** Modifying chunk sizes, swapping embedding models, or editing system prompts frequently degrades retrieval recall or faithfulness without any automated gate catching the regression before deployment.

---

## 2. Core Objectives & Measurable Success Criteria

CiteOps solves these failures by treating retrieval, grounding, caching, and evaluation as deterministic engineering systems:

| Engineering Objective | Architectural Mechanism | Target Production Metric |
| :--- | :--- | :--- |
| **Zero Cross-Tenant Data Leakage** | Strict `tenant_id` isolation enforced at PostgreSQL query, metadata filter, and Redis cache key layers | $0\%$ cross-tenant retrieval leakage |
| **Zero-Cost Idempotent Syncs** | SHA-256 `content_hash` deduplication + document versioning on ingestion | $\$0$ re-embedding cost for unchanged files |
| **High-Precision Hybrid Retrieval** | `pgvector` HNSW cosine search + PostgreSQL `tsvector` BM25 fused via Reciprocal Rank Fusion (RRF) and refined with a Cross-Encoder Reranker | Context Recall $\ge 0.85$ on golden benchmark |
| **Verifiable Grounding & Safe Abstention** | Citation-locked structured JSON output (`[doc_title, page, excerpt]`) + mandatory abstention rule when evidence is insufficient | Faithfulness $\ge 0.90$; $100\%$ abstention on out-of-scope queries |
| **Low-Latency Repeat Queries** | Tenant-scoped Redis semantic cache (cosine similarity $> 0.95$) | Cache-hit p95 latency $< 50\text{ ms}$; $\sim 40\%$ LLM token reduction |
| **Automated CI/CD Quality Gate** | `DeepEval` regression suite executed via `pytest` in GitHub Actions on every pull request | Automated build failure if Faithfulness $< 0.90$ |

---

## 3. Target User Personas & Core Workflows

### Persona A: Tier-2 Support Engineer
* **Goal:** Diagnose production incidents in seconds using exact error codes and version-specific runbooks.
* **Workflow:** Selects the customer's workspace (`tenant_id`), asks a technical question, inspects inline citations (`[1]`, `[2]`), and clicks a citation badge to verify the exact runbook paragraph in the side-panel source viewer.

### Persona B: Solutions Architect / Compliance Lead
* **Goal:** Answer enterprise RFP and SOC 2 security questionnaires with audit-ready proof.
* **Workflow:** Submits compliance questions; receives either a citation-backed answer with reranker confidence scores or an explicit `insufficient_evidence` status flagging a documentation gap rather than a fabricated claim.

### Persona C: AI Platform Engineer
* **Goal:** Maintain ingestion pipelines, monitor unit economics, and ship prompt/retrieval updates safely.
* **Workflow:** Uploads updated PDF/Markdown docs via the Knowledge Base Manager (or REST API), inspects per-request latency, cache-hit status, and token cost in Langfuse, and relies on GitHub Actions `DeepEval` gates before merging changes.

---

## 4. Monorepo Structure & Full-Stack Architecture

To deliver a cohesive, single-command developer experience and showcase end-to-end product ownership, CiteOps is structured as a **monorepo** housing the Python AI backend, the Next.js Perplexity-style citation frontend, automated evaluation suites, and local container orchestration.

### Repository Layout

```text
citeops/
├── apps/
│   ├── api/                        # Python 3.12 + FastAPI AI Backend
│   │   ├── app/
│   │   │   ├── api/v1/             # /ingest, /query, /documents, /health routes
│   │   │   ├── core/               # Config, logging, OpenTelemetry / Langfuse setup
│   │   │   ├── db/                 # PostgreSQL pool, SQL schema, migrations
│   │   │   ├── schemas/            # Strict Pydantic request/response contracts
│   │   │   └── services/           # Chunking, hybrid RRF retriever, BGE reranker, semantic cache
│   │   ├── tests/                  # Unit & integration tests
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   │
│   └── web/                        # Next.js 15 + TypeScript Perplexity-Style UI
│       ├── src/
│       │   ├── app/                # App Router pages (Workspace Chat, Knowledge Base, Metrics)
│       │   ├── components/         # CitationBadge, SourceDrawer, QueryBox, UploadModal
│       │   └── lib/                # Typed API client & shared response types
│       ├── Dockerfile
│       └── package.json
│
├── evals/                          # Automated LLM & Retrieval Evaluation Suite
│   ├── datasets/                   # Golden 50-question RFP & Tier-2 Support JSONL benchmark
│   ├── test_rag_quality.py         # DeepEval (Faithfulness, Answer Relevancy, Context Recall)
│   └── run_benchmark.py            # CLI script generating latency & accuracy scorecards
│
├── scripts/
│   └── seed_demo.py                # Seeds realistic API Error Docs, Enterprise SLA, & SOC2 Policy
│
├── .github/
│   └── workflows/
│       └── ci.yml                  # Linting, unit tests, and DeepEval regression gate
│
├── docker-compose.yml              # Boots api, web, postgres (pgvector:pg17), and redis
├── .env.example
├── Problem.md
└── README.md
```

### Recommended Full-Stack Technology Choices

#### Backend (`apps/api`)
* **Framework:** **Python 3.12 + FastAPI** (async I/O, automatic OpenAPI docs, strict Pydantic v2 validation).
* **Primary Database & Hybrid Search:** **PostgreSQL 17 + `pgvector`** — stores document metadata, dense embeddings (`vector(1536)` with HNSW cosine index), and generated `tsvector` columns (with GIN index) in a single ACID-compliant store, eliminating dual-database sync complexity.
* **Retrieval & Reranking Pipeline:**
  1. Top-50 dense cosine candidates + Top-50 BM25 (`ts_rank_cd`) candidates fused via Reciprocal Rank Fusion:
     $$\text{RRF}(d) = \sum_{i \in \{\text{dense}, \text{bm25}\}} \frac{1}{60 + \text{rank}_i(d)}$$
  2. **Cross-Encoder Reranker** (`BAAI/bge-reranker-base` via FastEmbed/ONNX or Cohere Rerank API) compresses top-50 RRF results down to top-5 high-precision passages.
* **Caching & Rate Limiting:** **Redis 7** — tenant-prefixed semantic query cache + sliding-window rate limiter.
* **LLM & Observability:** **OpenAI / LiteLLM** (structured JSON outputs) + **Langfuse** (end-to-end span tracing for retrieval latency, reranker scores, cache hits, and token cost).

#### Frontend (`apps/web`)
* **Framework:** **Next.js 15 (App Router) + TypeScript** — clean, fast SSR/CSR hybrid with typed API contracts.
* **Styling & UI Primitives:** **Tailwind CSS + shadcn/ui + Lucide Icons** — crisp, technical dark/light interface designed around verifiable answers.
* **State & Data Fetching:** **TanStack Query (React Query)** — handles optimistic document uploads, query loading states, and cache invalidation.
* **Key UI Views (Scoped for 4-Day Execution):**
  1. **Perplexity-Style Citation Workspace:** Tenant selector (`acme-corp`, `globex-io`), category filter (`all`, `api_docs`, `security_policy`, `sla_contract`), streamed/structured grounded answer with clickable inline citations (`[1]`, `[2]`), and a **Source Inspector Drawer** showing the exact matched document excerpt, page number, and reranker score.
  2. **Telemetry Pill Bar:** Displays live `latency_ms`, `CACHE HIT / MISS` badge, and retrieval confidence score under every answer.
  3. **Document Ingestion Drawer:** Drag-and-drop PDF/Markdown uploader showing SHA-256 deduplication status (`indexed` vs. `skipped_unchanged`).

#### Evals & DevOps (`evals/` & Root)
* **Evaluation Framework:** **DeepEval + `pytest`** measuring Faithfulness, Answer Relevancy, Context Recall, and Abstention Accuracy.
* **Containerization & CI:** **Docker Compose** (local development) + **GitHub Actions** (CI eval gate) + **Railway / Fly.io (API) & Vercel (Web)** for live cloud hosting.

---

## 5. API Contracts & Acceptance Criteria

### 1. Document Ingestion (`POST /v1/ingest`)
* **Inputs:** `file` (PDF or Markdown), `tenant_id`, `doc_type` (`api_docs` | `security_policy` | `sla_contract` | `runbook`), `version`.
* **Behavior:** Computes SHA-256 hash of file bytes. If `(tenant_id, content_hash)` already exists, returns `200 OK` with `status: "skipped_unchanged"` without calling the embedding API. Otherwise parses pages, chunks with overlap, generates batch embeddings, and commits atomically.

### 2. Citation-Locked Query (`POST /v1/query`)
* **Inputs:** `tenant_id`, `query`, optional `doc_types` filter, `top_k` (default `5`).
* **Output Schema:**
  ```json
  {
    "status": "answered",
    "answer": "Webhook signature verification fails with ERR_SIG_4092 on SDK v2.4.1 when the raw request body is parsed as JSON before HMAC-SHA256 validation [1]. To resolve this, pass the unparsed raw byte buffer to verifySignature() [1][2].",
    "citations": [
      {
        "citation_index": 1,
        "document_id": "doc_891a",
        "doc_title": "Webhook Integration & Error Reference v2.4",
        "doc_type": "api_docs",
        "page_number": 14,
        "rerank_score": 0.94,
        "excerpt": "ERR_SIG_4092: Payload digest mismatch triggered when middleware mutates whitespace prior to HMAC-SHA256 verification..."
      }
    ],
    "telemetry": {
      "cache_hit": false,
      "latency_ms": 1140,
      "model": "gpt-4o-mini"
    }
  }
  ```
* **Abstention Acceptance Criterion:** When top reranked passages fall below the confidence threshold or do not directly support the claim, the API **must** return `"status": "insufficient_evidence"`, an explanation of what documentation is missing, and `"citations": []`.

---

## 6. Four-Day Monorepo Execution Plan

* **Day 1 — Monorepo Scaffold, Hybrid Postgres & Core API:** Set up `apps/api`, `apps/web`, and `docker-compose.yml`. Implement PostgreSQL `pgvector` + `tsvector` RRF search, `/v1/ingest`, `/v1/query`, and `scripts/seed_demo.py`.
* **Day 2 — Reranking, Semantic Cache & Langfuse Tracing:** Add `BAAI/bge-reranker-base` reranking, tenant-scoped Redis semantic caching, and Langfuse observability spans.
* **Day 3 — Perplexity-Style Next.js Frontend & DeepEval CI Gate:** Build the `apps/web` citation workspace + source drawer and write the 50-question `DeepEval` + GitHub Actions CI suite.
* **Day 4 — Cloud Deployment & Benchmark Polish:** Deploy `apps/api` and `apps/web`, capture live p95 latency and DeepEval scores, and document architecture benchmarks in `README.md`.