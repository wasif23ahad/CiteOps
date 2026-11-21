-- CiteOps Initial Schema (PostgreSQL 17 + pgvector >= 0.8.0 + Strict Tenant RLS)
-- Idempotent migration executed by `app.db.migrate` under DATABASE_ADMIN_URL.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Least-privilege runtime role (NOSUPERUSER, NOBYPASSRLS) so RLS is strictly enforced.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'citeops_app') THEN
        CREATE ROLE citeops_app
            LOGIN
            PASSWORD 'citeops_app_dev_password'
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOBYPASSRLS;
    ELSE
        ALTER ROLE citeops_app
            WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
EXCEPTION
    WHEN insufficient_privilege THEN
        RAISE NOTICE 'Skipping citeops_app role creation due to hosted DB privileges.';
END
$$;

-- 2. Tenants table
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9_-]{1,62}$'),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Documents table (with SHA-256 content_hash deduplication per tenant)
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    doc_title TEXT NOT NULL,
    doc_type TEXT NOT NULL CHECK (
        doc_type IN ('api_docs', 'security_policy', 'sla_contract', 'runbook')
    ),
    version TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dim INT NOT NULL DEFAULT 768 CHECK (embedding_dim > 0),
    page_count INT NOT NULL DEFAULT 1 CHECK (page_count >= 1),
    chunk_count INT NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_documents_tenant_content_hash UNIQUE (tenant_id, content_hash)
);

-- 4. Document chunks (dense vector(768) + dual simple/english tsvector)
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    doc_type TEXT NOT NULL CHECK (
        doc_type IN ('api_docs', 'security_policy', 'sla_contract', 'runbook')
    ),
    chunk_index INT NOT NULL CHECK (chunk_index >= 0),
    page_number INT NOT NULL DEFAULT 1 CHECK (page_number >= 1),
    section_path TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    contextual_content TEXT NOT NULL,
    token_count INT NOT NULL CHECK (token_count >= 0),
    embedding vector(768) NOT NULL,
    search_tsv tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', coalesce(section_path, '') || ' ' || content), 'A') ||
        setweight(to_tsvector('english', contextual_content), 'B')
    ) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_document_chunks_doc_idx UNIQUE (document_id, chunk_index)
);

-- 5. Query audit logs (operational telemetry under tenant RLS; powers /v1/metrics/summary)
CREATE TABLE IF NOT EXISTS query_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    trace_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('answered', 'insufficient_evidence', 'error')),
    cache_hit BOOLEAN NOT NULL DEFAULT false,
    cache_tier TEXT NOT NULL DEFAULT 'miss' CHECK (cache_tier IN ('exact', 'semantic', 'miss')),
    model TEXT NOT NULL,
    reranker_model TEXT NOT NULL,
    top_rerank_score REAL,
    latency_ms INT NOT NULL CHECK (latency_ms >= 0),
    retrieval_ms INT NOT NULL DEFAULT 0 CHECK (retrieval_ms >= 0),
    rerank_ms INT NOT NULL DEFAULT 0 CHECK (rerank_ms >= 0),
    llm_ms INT NOT NULL DEFAULT 0 CHECK (llm_ms >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 6. Retrieval & operational indexes
CREATE INDEX IF NOT EXISTS idx_documents_tenant_active
    ON documents (tenant_id, doc_type, is_active);

CREATE INDEX IF NOT EXISTS idx_chunks_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_chunks_tsv
    ON document_chunks USING gin (search_tsv);

CREATE INDEX IF NOT EXISTS idx_chunks_tenant_type
    ON document_chunks (tenant_id, doc_type, document_id);

CREATE INDEX IF NOT EXISTS idx_audit_tenant_created
    ON query_audit_logs (tenant_id, created_at DESC);

-- 7. Defense-in-depth Row-Level Security (fail-closed when app.current_tenant_id is unset)
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_documents ON documents;
CREATE POLICY tenant_isolation_documents ON documents
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_chunks ON document_chunks;
CREATE POLICY tenant_isolation_chunks ON document_chunks
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE query_audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE query_audit_logs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_audit ON query_audit_logs;
CREATE POLICY tenant_isolation_audit ON query_audit_logs
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

-- 8. Grants to least-privilege runtime role
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'citeops_app') THEN
        GRANT USAGE ON SCHEMA public TO citeops_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO citeops_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON documents TO citeops_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON document_chunks TO citeops_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON query_audit_logs TO citeops_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO citeops_app;
    END IF;
END
$$;
