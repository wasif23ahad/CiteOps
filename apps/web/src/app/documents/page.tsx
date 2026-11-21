"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  FileText,
  FileUp,
  Hash,
  Loader2,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useState } from "react";

import { UploadModal } from "@/components/upload-modal";
import { ApiError, deleteDocument, listDocuments } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import { DOC_TYPE_LABELS, type DocType } from "@/lib/types";

export default function DocumentsPage() {
  const { tenantId } = useTenant();
  const queryClient = useQueryClient();

  const [filterDocType, setFilterDocType] = useState<DocType | "all">("all");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [statusNotice, setStatusNotice] = useState<string | null>(null);

  const docsQuery = useQuery({
    queryKey: ["documents", tenantId, filterDocType],
    queryFn: () =>
      listDocuments(tenantId, filterDocType === "all" ? null : filterDocType),
  });

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => deleteDocument(tenantId, documentId),
    onSuccess: (res) => {
      setStatusNotice(
        `Deleted document and bumped ${res.tenant_id} cache generation to v${res.corpus_version}.`
      );
      queryClient.invalidateQueries({ queryKey: ["documents", tenantId] });
    },
  });

  const documents = docsQuery.data?.documents ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Knowledge Base Manager</h1>
          <p className="mt-1 text-xs text-muted-foreground sm:text-sm">
            Tenant-isolated corpus for <span className="font-mono font-semibold">{tenantId}</span>{" "}
            with SHA-256 idempotent syncs and instant cache invalidation.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => docsQuery.refetch()}
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-xs font-medium hover:bg-muted"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${docsQuery.isFetching ? "animate-spin" : ""}`} />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-xs font-semibold text-primary-foreground hover:opacity-90"
          >
            <FileUp className="h-3.5 w-3.5" />
            Upload PDF / Markdown
          </button>
        </div>
      </div>

      {/* Category Filter */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setFilterDocType("all")}
          className={
            filterDocType === "all"
              ? "cursor-pointer rounded-full bg-primary px-3 py-1 text-xs font-medium text-primary-foreground"
              : "cursor-pointer rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground hover:bg-muted"
          }
        >
          All Categories
        </button>
        {(Object.keys(DOC_TYPE_LABELS) as DocType[]).map((dt) => (
          <button
            key={dt}
            type="button"
            onClick={() => setFilterDocType(dt)}
            className={
              filterDocType === dt
                ? "cursor-pointer rounded-full bg-primary px-3 py-1 text-xs font-medium text-primary-foreground"
                : "cursor-pointer rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground hover:bg-muted"
            }
          >
            {DOC_TYPE_LABELS[dt]}
          </button>
        ))}
      </div>

      {statusNotice && (
        <div className="flex items-center justify-between rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-xs text-emerald-700 dark:text-emerald-300">
          <span>{statusNotice}</span>
          <button
            type="button"
            onClick={() => setStatusNotice(null)}
            className="cursor-pointer font-semibold hover:underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {docsQuery.isError && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-500/35 bg-rose-500/10 p-4 text-xs text-rose-700 dark:text-rose-300">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>
            {docsQuery.error instanceof ApiError
              ? docsQuery.error.message
              : "Failed to load tenant documents."}
          </span>
        </div>
      )}

      {/* Documents Table */}
      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-border bg-muted/50 text-[11px] uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-medium">Document</th>
                <th className="px-4 py-3 font-medium">Category</th>
                <th className="px-4 py-3 font-medium">Version</th>
                <th className="px-4 py-3 font-medium">Pages / Chunks</th>
                <th className="px-4 py-3 font-medium">SHA-256 Hash</th>
                <th className="px-4 py-3 font-medium">Embeddings</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {docsQuery.isLoading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-muted-foreground">
                    <Loader2 className="mx-auto h-5 w-5 animate-spin" />
                  </td>
                </tr>
              ) : documents.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-muted-foreground">
                    No active documents indexed for <span className="font-mono">{tenantId}</span>.
                    Upload a PDF or Markdown file to start querying.
                  </td>
                </tr>
              ) : (
                documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-muted/30">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4 shrink-0 text-primary" />
                        <div>
                          <p className="font-medium text-foreground">{doc.doc_title}</p>
                          <p className="font-mono text-[11px] text-muted-foreground">
                            {doc.source_filename}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] font-medium">
                        {DOC_TYPE_LABELS[doc.doc_type]}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono">{doc.version}</td>
                    <td className="px-4 py-3 font-mono">
                      {doc.page_count}p · {doc.chunk_count} chunks
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-muted-foreground">
                      <span className="inline-flex items-center gap-1" title={doc.content_hash}>
                        <Hash className="h-3 w-3" />
                        {doc.content_hash.slice(0, 12)}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-muted-foreground">
                      {doc.embedding_model} ({doc.embedding_dim}d)
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        disabled={deleteMutation.isPending}
                        onClick={() => deleteMutation.mutate(doc.id)}
                        className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[11px] font-medium text-rose-600 hover:bg-rose-500/10 disabled:opacity-50 dark:text-rose-400"
                      >
                        <Trash2 className="h-3 w-3" />
                        Delete
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <UploadModal
        open={uploadOpen}
        tenantId={tenantId}
        onClose={() => setUploadOpen(false)}
      />
    </div>
  );
}
