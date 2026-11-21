export type DocType =
  | "api_docs"
  | "security_policy"
  | "sla_contract"
  | "runbook";

export type QueryStatus = "answered" | "insufficient_evidence";
export type CacheTier = "exact" | "semantic" | "miss";

export interface QueryRequest {
  tenant_id: string;
  query: string;
  doc_types?: DocType[] | null;
  top_k?: number;
}

export interface CitationItem {
  citation_index: number;
  document_id: string;
  doc_title: string;
  doc_type: DocType;
  version: string;
  page_number: number;
  section_path: string;
  rerank_score: number;
  excerpt: string;
}

export interface QueryTelemetry {
  cache_hit: boolean;
  cache_tier: CacheTier;
  latency_ms: number;
  retrieval_ms: number;
  rerank_ms: number;
  llm_ms: number;
  model: string;
  reranker_model: string;
  top_rerank_score: number | null;
  trace_id: string;
}

export interface QueryResponse {
  status: QueryStatus;
  answer: string;
  missing_evidence_reason: string | null;
  citations: CitationItem[];
  telemetry: QueryTelemetry;
}

export interface IngestResponse {
  status: "indexed" | "skipped_unchanged";
  document_id: string;
  tenant_id: string;
  doc_title: string;
  doc_type: DocType;
  version: string;
  content_hash: string;
  page_count: number;
  chunk_count: number;
  corpus_version: number;
  latency_ms: number;
}

export interface DocumentSummary {
  id: string;
  tenant_id: string;
  doc_title: string;
  doc_type: DocType;
  version: string;
  source_filename: string;
  content_hash: string;
  embedding_model: string;
  embedding_dim: number;
  page_count: number;
  chunk_count: number;
  is_active: boolean;
  created_at: string;
}

export interface DocumentListResponse {
  tenant_id: string;
  total: number;
  documents: DocumentSummary[];
}

export interface DocumentDeleteResponse {
  deleted: boolean;
  document_id: string;
  tenant_id: string;
  corpus_version: number;
}

export interface MetricsSummaryResponse {
  tenant_id: string;
  total_queries: number;
  cache_hit_rate: number;
  exact_cache_hits: number;
  semantic_cache_hits: number;
  abstention_rate: number;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  p95_cache_hit_ms: number | null;
  p95_cache_miss_ms: number | null;
  active_llm_model: string;
  active_reranker_model: string;
  reranker_profile: string;
}

export interface DependencyCheck {
  status: "ok" | "degraded" | "error";
  detail: string | null;
  latency_ms: number | null;
}

export interface HealthResponse {
  status: "ok" | "degraded" | "unhealthy";
  service: string;
  environment: string;
  reranker_profile: string;
  reranker_model: string;
  llm_provider: string;
  llm_model: string;
  embedding_model: string;
  embedding_dim: number;
  dependencies: Record<string, DependencyCheck>;
}

export const DOC_TYPE_LABELS: Record<DocType, string> = {
  api_docs: "API Docs",
  security_policy: "Security Policy",
  sla_contract: "SLA Contract",
  runbook: "Runbook",
};
