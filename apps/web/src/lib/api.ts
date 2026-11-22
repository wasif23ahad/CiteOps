import type {
  DocType,
  DocumentDeleteResponse,
  DocumentListResponse,
  HealthResponse,
  IngestResponse,
  MetricsSummaryResponse,
  QueryRequest,
  QueryResponse,
} from "@/lib/types";

export class ApiError extends Error {
  status: number;
  retryAfter: number | null;

  constructor(message: string, status: number, retryAfter: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

async function parseJsonOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed with HTTP ${response.status}`;
    try {
      const errBody = (await response.json()) as { detail?: unknown };
      if (typeof errBody.detail === "string") {
        detail = errBody.detail;
      } else if (errBody.detail) {
        detail = JSON.stringify(errBody.detail);
      }
    } catch {
      // Keep fallback message
    }
    const retryHeader = response.headers.get("retry-after");
    const retryAfter = retryHeader ? Number.parseInt(retryHeader, 10) : null;
    throw new ApiError(detail, response.status, Number.isFinite(retryAfter) ? retryAfter : null);
  }
  return (await response.json()) as T;
}

export async function queryKnowledgeBase(payload: QueryRequest): Promise<QueryResponse> {
  const response = await fetch("/api/citeops/v1/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonOrThrow<QueryResponse>(response);
}

export async function listDocuments(
  tenantId: string,
  docType?: DocType | null
): Promise<DocumentListResponse> {
  const params = new URLSearchParams({ tenant_id: tenantId });
  if (docType) {
    params.set("doc_type", docType);
  }
  const response = await fetch(`/api/citeops/v1/documents?${params.toString()}`);
  return parseJsonOrThrow<DocumentListResponse>(response);
}

export async function ingestDocument(params: {
  file: File;
  tenantId: string;
  docType: DocType;
  version: string;
  docTitle?: string;
}): Promise<IngestResponse> {
  const form = new FormData();
  form.append("file", params.file);
  form.append("tenant_id", params.tenantId);
  form.append("doc_type", params.docType);
  form.append("version", params.version);
  if (params.docTitle?.trim()) {
    form.append("doc_title", params.docTitle.trim());
  }

  const response = await fetch("/api/citeops/v1/ingest", {
    method: "POST",
    body: form,
  });
  return parseJsonOrThrow<IngestResponse>(response);
}

export async function deleteDocument(
  tenantId: string,
  documentId: string
): Promise<DocumentDeleteResponse> {
  const params = new URLSearchParams({ tenant_id: tenantId });
  const response = await fetch(
    `/api/citeops/v1/documents/${encodeURIComponent(documentId)}?${params.toString()}`,
    { method: "DELETE" }
  );
  return parseJsonOrThrow<DocumentDeleteResponse>(response);
}

export async function getMetricsSummary(
  tenantId: string
): Promise<MetricsSummaryResponse> {
  const params = new URLSearchParams({ tenant_id: tenantId });
  const response = await fetch(`/api/citeops/v1/metrics/summary?${params.toString()}`);
  return parseJsonOrThrow<MetricsSummaryResponse>(response);
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch("/api/citeops/v1/health");
  return parseJsonOrThrow<HealthResponse>(response);
}
