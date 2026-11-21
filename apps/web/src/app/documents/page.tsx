"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Check,
  Copy,
  FileText,
  FileUp,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useState } from "react";

import { UploadModal } from "@/components/upload-modal";
import { ApiError, deleteDocument, listDocuments } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import { DOC_TYPE_LABELS, type DocType } from "@/lib/types";
import { cn } from "@/lib/utils";

function TableSkeletonRows() {
  return (
    <>
      {[0, 1, 2, 3].map((row) => (
        <tr key={row}>
          <td className="px-4 py-3.5">
            <div className="flex flex-col gap-1.5">
              <div className="ledger-skeleton h-3.5 w-48 rounded" />
              <div className="ledger-skeleton h-3 w-32 rounded" />
            </div>
          </td>
          <td className="px-4 py-3.5">
            <div className="ledger-skeleton h-5 w-20 rounded-md" />
          </td>
          <td className="px-4 py-3.5">
            <div className="ledger-skeleton h-3.5 w-12 rounded" />
          </td>
          <td className="px-4 py-3.5">
            <div className="ledger-skeleton h-3.5 w-20 rounded" />
          </td>
          <td className="px-4 py-3.5">
            <div className="ledger-skeleton h-3.5 w-24 rounded" />
          </td>
          <td className="px-4 py-3.5">
            <div className="ledger-skeleton h-3.5 w-28 rounded" />
          </td>
          <td className="px-4 py-3.5 text-right">
            <div className="ledger-skeleton ml-auto h-7 w-16 rounded-md" />
          </td>
        </tr>
      ))}
    </>
  );
}

export default function DocumentsPage() {
  const { tenantId } = useTenant();
  const queryClient = useQueryClient();

  const [filterDocType, setFilterDocType] = useState<DocType | "all">("all");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [statusNotice, setStatusNotice] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [copiedHashId, setCopiedHashId] = useState<string | null>(null);

  const docsQuery = useQuery({
    queryKey: ["documents", tenantId, filterDocType],
    queryFn: () =>
      listDocuments(tenantId, filterDocType === "all" ? null : filterDocType),
  });

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => deleteDocument(tenantId, documentId),
    onSuccess: (res) => {
      setConfirmDeleteId(null);
      setStatusNotice(
        `Removed document from ${res.tenant_id} and bumped cache generation to v${res.corpus_version}.`
      );
      queryClient.invalidateQueries({ queryKey: ["documents", tenantId] });
    },
  });

  const documents = docsQuery.data?.documents ?? [];
  const totalChunks = documents.reduce((sum, d) => sum + d.chunk_count, 0);
  const totalPages = documents.reduce((sum, d) => sum + d.page_count, 0);

  const handleCopyHash = async (docId: string, hash: string) => {
    try {
      await navigator.clipboard.writeText(hash);
      setCopiedHashId(docId);
      window.setTimeout(() => setCopiedHashId(null), 1600);
    } catch {
      // Ignore clipboard failures
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-8 sm:py-8">
      {/* Header */}
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-[-0.025em] text-ledger-ink text-balance">
            Knowledge base
          </h1>
          <p className="text-sm text-ledger-ink-secondary text-pretty">
            Active indexed corpus for <span className="font-mono text-ledger-ink">{tenantId}</span>{" "}
            with SHA-256 deduplication and instant cache generation invalidation.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => docsQuery.refetch()}
            className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg border border-ledger-hairline bg-ledger-folio px-3 text-xs font-medium text-ledger-ink-secondary transition-colors duration-150 hover:border-ledger-hairline-strong hover:text-ledger-ink active:scale-[0.98]"
          >
            <RefreshCw className={cn("size-3.5", docsQuery.isFetching && "animate-spin")} />
            <span>Refresh</span>
          </button>
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg bg-ledger-accent px-3.5 text-xs font-semibold text-ledger-accent-ink transition-colors duration-150 hover:bg-ledger-accent-hover active:scale-[0.98]"
          >
            <FileUp className="size-3.5" />
            <span>Ingest document</span>
          </button>
        </div>
      </header>

      {/* Hairline Corpus Summary Ledger (single cohesive band, not 4 boxed KPI cards) */}
      <section
        aria-label="Corpus summary"
        className="ledger-folio grid grid-cols-2 divide-y divide-ledger-hairline rounded-2xl sm:grid-cols-4 sm:divide-x sm:divide-y-0"
      >
        <div className="flex flex-col gap-1 px-5 py-4">
          <span className="text-xs text-ledger-ink-tertiary">Active documents</span>
          <span className="font-mono text-xl font-semibold tabular-nums text-ledger-ink">
            {docsQuery.isLoading ? "—" : documents.length}
          </span>
        </div>
        <div className="flex flex-col gap-1 px-5 py-4">
          <span className="text-xs text-ledger-ink-tertiary">Indexed chunks</span>
          <span className="font-mono text-xl font-semibold tabular-nums text-ledger-ink">
            {docsQuery.isLoading ? "—" : totalChunks}
          </span>
        </div>
        <div className="flex flex-col gap-1 px-5 py-4">
          <span className="text-xs text-ledger-ink-tertiary">Tracked pages</span>
          <span className="font-mono text-xl font-semibold tabular-nums text-ledger-ink">
            {docsQuery.isLoading ? "—" : totalPages}
          </span>
        </div>
        <div className="flex flex-col gap-1 px-5 py-4">
          <span className="text-xs text-ledger-ink-tertiary">Deduplication</span>
          <span className="font-mono text-sm font-medium text-status-verified">
            SHA-256 ($0 re-embed)
          </span>
        </div>
      </section>

      {/* Category Filter Bar */}
      <div
        role="group"
        aria-label="Filter documents by category"
        className="flex flex-wrap items-center gap-1.5"
      >
        <button
          type="button"
          aria-pressed={filterDocType === "all"}
          onClick={() => setFilterDocType("all")}
          className={cn(
            "cursor-pointer rounded-lg px-3 py-1.5 text-xs font-medium transition-colors duration-150",
            filterDocType === "all"
              ? "bg-ledger-accent-tint text-ledger-accent"
              : "text-ledger-ink-secondary hover:bg-ledger-hairline-subtle hover:text-ledger-ink"
          )}
        >
          All categories
        </button>
        {(Object.keys(DOC_TYPE_LABELS) as DocType[]).map((dt) => (
          <button
            key={dt}
            type="button"
            aria-pressed={filterDocType === dt}
            onClick={() => setFilterDocType(dt)}
            className={cn(
              "cursor-pointer rounded-lg px-3 py-1.5 text-xs font-medium transition-colors duration-150",
              filterDocType === dt
                ? "bg-ledger-accent-tint text-ledger-accent"
                : "text-ledger-ink-secondary hover:bg-ledger-hairline-subtle hover:text-ledger-ink"
            )}
          >
            {DOC_TYPE_LABELS[dt]}
          </button>
        ))}
      </div>

      {/* Status Notice */}
      {statusNotice && (
        <div
          role="status"
          className="animate-ledger-enter flex items-center justify-between gap-4 rounded-xl border border-status-verified-border bg-status-verified-tint px-4 py-3 text-xs text-ledger-ink"
        >
          <span>{statusNotice}</span>
          <button
            type="button"
            onClick={() => setStatusNotice(null)}
            className="shrink-0 cursor-pointer font-medium text-status-verified hover:underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Error Banner */}
      {docsQuery.isError && (
        <div
          role="alert"
          className="flex items-center gap-2.5 rounded-xl border border-status-fault-border bg-status-fault-tint p-4 text-xs text-status-fault"
        >
          <AlertCircle className="size-4 shrink-0" />
          <span>
            {docsQuery.error instanceof ApiError
              ? docsQuery.error.message
              : "Could not load tenant documents. Check API connectivity and retry."}
          </span>
        </div>
      )}

      {/* Inventory Table */}
      <div className="ledger-folio overflow-hidden rounded-2xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-ledger-hairline bg-ledger-rail text-[11px] font-medium text-ledger-ink-tertiary">
              <tr>
                <th className="px-4 py-3 font-medium">Document</th>
                <th className="px-4 py-3 font-medium">Category</th>
                <th className="px-4 py-3 font-medium">Version</th>
                <th className="px-4 py-3 font-medium">Pages / chunks</th>
                <th className="px-4 py-3 font-medium">SHA-256 digest</th>
                <th className="px-4 py-3 font-medium">Embedding model</th>
                <th className="px-4 py-3 text-right font-medium">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ledger-hairline">
              {docsQuery.isLoading ? (
                <TableSkeletonRows />
              ) : documents.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center">
                    <div className="mx-auto flex max-w-sm flex-col items-center gap-2.5">
                      <p className="text-sm font-medium text-ledger-ink">
                        No documents indexed for{" "}
                        <span className="font-mono">{tenantId}</span>
                      </p>
                      <p className="text-xs text-ledger-ink-muted text-pretty">
                        Upload a PDF, Markdown, or text policy file to populate this isolated
                        tenant corpus.
                      </p>
                      <button
                        type="button"
                        onClick={() => setUploadOpen(true)}
                        className="mt-1 inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg bg-ledger-accent px-3 text-xs font-semibold text-ledger-accent-ink hover:bg-ledger-accent-hover"
                      >
                        <FileUp className="size-3.5" />
                        <span>Ingest first document</span>
                      </button>
                    </div>
                  </td>
                </tr>
              ) : (
                documents.map((doc) => {
                  const awaitingConfirm = confirmDeleteId === doc.id;
                  const copied = copiedHashId === doc.id;
                  return (
                    <tr
                      key={doc.id}
                      className="transition-colors duration-100 hover:bg-ledger-hairline-subtle"
                    >
                      <td className="px-4 py-3.5">
                        <div className="flex items-start gap-2.5">
                          <FileText className="mt-0.5 size-4 shrink-0 text-ledger-accent" />
                          <div className="min-w-0">
                            <p className="font-medium text-ledger-ink">{doc.doc_title}</p>
                            <p className="font-mono text-[11px] text-ledger-ink-muted">
                              {doc.source_filename}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3.5">
                        <span className="inline-flex rounded-md border border-ledger-hairline bg-ledger-inset px-2 py-0.5 text-[11px] font-medium text-ledger-ink-secondary">
                          {DOC_TYPE_LABELS[doc.doc_type]}
                        </span>
                      </td>
                      <td className="px-4 py-3.5 font-mono text-ledger-ink-secondary">
                        {doc.version}
                      </td>
                      <td className="px-4 py-3.5 font-mono tabular-nums text-ledger-ink-secondary">
                        {doc.page_count}p / {doc.chunk_count}c
                      </td>
                      <td className="px-4 py-3.5">
                        <button
                          type="button"
                          onClick={() => handleCopyHash(doc.id, doc.content_hash)}
                          title={`Copy full SHA-256: ${doc.content_hash}`}
                          className="inline-flex cursor-pointer items-center gap-1.5 rounded px-1.5 py-0.5 font-mono text-[11px] text-ledger-ink-tertiary transition-colors duration-150 hover:bg-ledger-hairline-subtle hover:text-ledger-ink"
                        >
                          {copied ? (
                            <>
                              <Check className="size-3 text-status-verified" />
                              <span className="text-status-verified">Copied</span>
                            </>
                          ) : (
                            <>
                              <Copy className="size-3 text-ledger-ink-muted" />
                              <span>{doc.content_hash.slice(0, 12)}</span>
                            </>
                          )}
                        </button>
                      </td>
                      <td className="px-4 py-3.5 font-mono text-[11px] text-ledger-ink-tertiary">
                        {doc.embedding_model} ({doc.embedding_dim}d)
                      </td>
                      <td className="px-4 py-3.5 text-right">
                        {awaitingConfirm ? (
                          <div className="inline-flex items-center gap-1.5">
                            <button
                              type="button"
                              disabled={deleteMutation.isPending}
                              onClick={() => deleteMutation.mutate(doc.id)}
                              className="cursor-pointer rounded-md border border-status-fault-border bg-status-fault-tint px-2 py-1 text-[11px] font-semibold text-status-fault transition-opacity hover:opacity-90 disabled:opacity-50"
                            >
                              Confirm
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmDeleteId(null)}
                              className="cursor-pointer rounded-md border border-ledger-hairline px-2 py-1 text-[11px] font-medium text-ledger-ink-secondary hover:text-ledger-ink"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            disabled={deleteMutation.isPending}
                            onClick={() => setConfirmDeleteId(doc.id)}
                            className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-ledger-hairline px-2.5 py-1 text-[11px] font-medium text-ledger-ink-secondary transition-colors duration-150 hover:border-status-fault-border hover:bg-status-fault-tint hover:text-status-fault disabled:opacity-50"
                          >
                            <Trash2 className="size-3" />
                            <span>Delete</span>
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })
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
