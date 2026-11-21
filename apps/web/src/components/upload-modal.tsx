"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileUp, Loader2, Sparkles, UploadCloud, X } from "lucide-react";
import { useRef, useState, type DragEvent, type FormEvent } from "react";

import { ApiError, ingestDocument } from "@/lib/api";
import { DOC_TYPE_LABELS, type DocType, type IngestResponse } from "@/lib/types";

interface UploadModalProps {
  open: boolean;
  tenantId: string;
  onClose: () => void;
}

export function UploadModal({ open, tenantId, onClose }: UploadModalProps) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [docType, setDocType] = useState<DocType>("api_docs");
  const [version, setVersion] = useState("v1.0");
  const [docTitle, setDocTitle] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [lastResult, setLastResult] = useState<IngestResponse | null>(null);

  const mutation = useMutation({
    mutationFn: ingestDocument,
    onSuccess: (data) => {
      setLastResult(data);
      queryClient.invalidateQueries({ queryKey: ["documents", tenantId] });
    },
  });

  if (!open) return null;

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragOver(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) {
      setFile(dropped);
      setLastResult(null);
    }
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    mutation.mutate({
      file,
      tenantId,
      docType,
      version: version.trim() || "v1.0",
      docTitle: docTitle.trim() || undefined,
    });
  };

  const resetAndClose = () => {
    setLastResult(null);
    mutation.reset();
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-[1px]"
      onClick={resetAndClose}
      role="dialog"
      aria-modal="true"
      aria-label="Upload Document"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-xl border border-border bg-card p-6 shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-border pb-3">
          <div className="flex items-center gap-2">
            <FileUp className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold">
              Ingest Document into <span className="font-mono">{tenantId}</span>
            </h2>
          </div>
          <button
            type="button"
            onClick={resetAndClose}
            aria-label="Close upload modal"
            className="cursor-pointer rounded-md p-1 text-muted-foreground hover:bg-muted"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          {/* Drag and Drop Zone */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={
              dragOver
                ? "flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-primary bg-accent/40 p-6 text-center"
                : "flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-border bg-background p-6 text-center hover:border-primary/50"
            }
          >
            <UploadCloud className="h-7 w-7 text-muted-foreground" />
            <p className="mt-2 text-xs font-medium text-foreground">
              {file ? file.name : "Drop a PDF, Markdown (.md), or TXT file here, or click to browse"}
            </p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {file
                ? `${(file.size / 1024).toFixed(1)} KB · SHA-256 deduplicated automatically`
                : "Max 25 MB · Unchanged files incur $0 embedding cost"}
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.md,.markdown,.txt"
              className="hidden"
              onChange={(e) => {
                const picked = e.target.files?.[0] ?? null;
                setFile(picked);
                setLastResult(null);
              }}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-xs">
              <span className="font-medium text-muted-foreground">Document Type</span>
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value as DocType)}
                className="w-full rounded-md border border-border bg-background px-2.5 py-2 text-xs text-foreground"
              >
                {(Object.keys(DOC_TYPE_LABELS) as DocType[]).map((dt) => (
                  <option key={dt} value={dt}>
                    {DOC_TYPE_LABELS[dt]}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-1 text-xs">
              <span className="font-medium text-muted-foreground">Version</span>
              <input
                type="text"
                required
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                placeholder="v2.4.1"
                className="w-full rounded-md border border-border bg-background px-2.5 py-2 font-mono text-xs text-foreground"
              />
            </label>
          </div>

          <label className="block space-y-1 text-xs">
            <span className="font-medium text-muted-foreground">
              Document Title (optional — defaults to filename)
            </span>
            <input
              type="text"
              value={docTitle}
              onChange={(e) => setDocTitle(e.target.value)}
              placeholder="e.g. Enterprise Security Addendum"
              className="w-full rounded-md border border-border bg-background px-2.5 py-2 text-xs text-foreground"
            />
          </label>

          {/* Error Banner */}
          {mutation.isError && (
            <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-700 dark:text-rose-300">
              {mutation.error instanceof ApiError
                ? mutation.error.message
                : "Upload failed. Check file format and backend status."}
            </div>
          )}

          {/* Deduplication / Indexed Outcome */}
          {lastResult && (
            <div
              className={
                lastResult.status === "skipped_unchanged"
                  ? "rounded-lg border border-sky-500/35 bg-sky-500/10 p-3 text-xs"
                  : "rounded-lg border border-emerald-500/35 bg-emerald-500/10 p-3 text-xs"
              }
            >
              <div className="flex items-center gap-2 font-semibold">
                {lastResult.status === "skipped_unchanged" ? (
                  <>
                    <Sparkles className="h-4 w-4 text-sky-600 dark:text-sky-400" />
                    <span>Skipped Unchanged — $0 Re-Embedding Cost (SHA-256 Match)</span>
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                    <span>
                      Indexed {lastResult.chunk_count} chunks across {lastResult.page_count} page(s)
                    </span>
                  </>
                )}
              </div>
              <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                corpus_version: v{lastResult.corpus_version} · hash:{" "}
                {lastResult.content_hash.slice(0, 12)} · {lastResult.latency_ms} ms
              </p>
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={resetAndClose}
              className="cursor-pointer rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted"
            >
              Close
            </button>
            <button
              type="submit"
              disabled={!file || mutation.isPending}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span>Ingesting...</span>
                </>
              ) : (
                <span>Ingest Document</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
