"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileText, FileUp, Loader2, Sparkles, UploadCloud, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";

import { ApiError, ingestDocument } from "@/lib/api";
import { DOC_TYPES, DOC_TYPE_LABELS, type DocType, type IngestResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

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

  const { reset: resetMutation } = mutation;

  const resetAndClose = useCallback(() => {
    setLastResult(null);
    resetMutation();
    onClose();
  }, [onClose, resetMutation]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        resetAndClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, resetAndClose]);

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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4 backdrop-blur-[2px]"
      onClick={resetAndClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="upload-dialog-title"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="ledger-overlay animate-ledger-enter flex w-full max-w-lg flex-col rounded-2xl bg-ledger-folio"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-ledger-hairline px-5 py-4">
          <div className="flex items-center gap-2.5">
            <FileUp className="size-4 text-ledger-accent" />
            <h2
              id="upload-dialog-title"
              className="text-sm font-semibold tracking-[-0.01em] text-ledger-ink"
            >
              Ingest document into <span className="font-mono">{tenantId}</span>
            </h2>
          </div>
          <button
            type="button"
            onClick={resetAndClose}
            aria-label="Close upload dialog"
            className="flex size-8 cursor-pointer items-center justify-center rounded-lg text-ledger-ink-muted transition-colors duration-150 hover:bg-ledger-hairline-subtle hover:text-ledger-ink"
          >
            <X className="size-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4 p-5">
          {/* Drag and Drop Zone */}
          <div
            role="button"
            tabIndex={0}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-5 py-7 text-center transition-colors duration-150",
              dragOver
                ? "border-ledger-accent bg-ledger-accent-tint"
                : "border-ledger-hairline-strong bg-ledger-inset hover:border-ledger-accent-border"
            )}
          >
            {file ? (
              <div className="flex items-center gap-2.5 rounded-lg border border-ledger-hairline bg-ledger-folio px-3 py-2">
                <FileText className="size-4 shrink-0 text-ledger-accent" />
                <div className="text-left">
                  <p className="text-xs font-medium text-ledger-ink">{file.name}</p>
                  <p className="font-mono text-[11px] tabular-nums text-ledger-ink-tertiary">
                    {(file.size / 1024).toFixed(1)} KB
                  </p>
                </div>
              </div>
            ) : (
              <>
                <UploadCloud className="size-6 text-ledger-ink-muted" />
                <p className="text-xs font-medium text-ledger-ink">
                  Drop a PDF, Markdown, or TXT file here, or click to select
                </p>
                <p className="text-[11px] text-ledger-ink-muted">
                  Up to 25 MB. Identical SHA-256 uploads skip re-embedding automatically.
                </p>
              </>
            )}
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

          {/* Document Type Segmented Control (replaces raw native <select>) */}
          <fieldset className="flex flex-col gap-1.5">
            <legend className="text-xs font-medium text-ledger-ink-secondary">
              Document category
            </legend>
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
              {DOC_TYPES.map((dt) => {
                const active = docType === dt;
                return (
                  <button
                    key={dt}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setDocType(dt)}
                    className={cn(
                      "cursor-pointer rounded-lg border px-2.5 py-2 text-xs font-medium transition-colors duration-150 active:scale-[0.98]",
                      active
                        ? "border-ledger-accent-border bg-ledger-accent-tint text-ledger-accent"
                        : "border-ledger-hairline bg-ledger-inset text-ledger-ink-secondary hover:border-ledger-hairline-strong hover:text-ledger-ink"
                    )}
                  >
                    {DOC_TYPE_LABELS[dt]}
                  </button>
                );
              })}
            </div>
          </fieldset>

          {/* Version & Optional Title */}
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-ledger-ink-secondary">Version</span>
              <input
                type="text"
                required
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                placeholder="v2.4.1"
                className="h-9 rounded-lg border border-ledger-hairline bg-ledger-inset px-3 font-mono text-xs text-ledger-ink placeholder:text-ledger-ink-muted focus:border-ledger-accent-border focus:outline-none"
              />
            </label>

            <label className="flex flex-col gap-1.5 sm:col-span-2">
              <span className="text-xs font-medium text-ledger-ink-secondary">
                Document title <span className="text-ledger-ink-muted">(optional)</span>
              </span>
              <input
                type="text"
                value={docTitle}
                onChange={(e) => setDocTitle(e.target.value)}
                placeholder="Defaults to filename"
                className="h-9 rounded-lg border border-ledger-hairline bg-ledger-inset px-3 text-xs text-ledger-ink placeholder:text-ledger-ink-muted focus:border-ledger-accent-border focus:outline-none"
              />
            </label>
          </div>

          {/* Error Banner */}
          {mutation.isError && (
            <div
              role="alert"
              className="rounded-xl border border-status-fault-border bg-status-fault-tint px-3.5 py-2.5 text-xs text-status-fault"
            >
              {mutation.error instanceof ApiError
                ? mutation.error.message
                : "Ingestion failed. Verify the file format and backend connectivity."}
            </div>
          )}

          {/* Indexed / SHA-256 Deduplicated Outcome */}
          {lastResult && (
            <div
              className={cn(
                "flex flex-col gap-1 rounded-xl border px-3.5 py-3 text-xs",
                lastResult.status === "skipped_unchanged"
                  ? "border-status-info-border bg-status-info-tint"
                  : "border-status-verified-border bg-status-verified-tint"
              )}
            >
              <div className="flex items-center gap-2 font-semibold text-ledger-ink">
                {lastResult.status === "skipped_unchanged" ? (
                  <>
                    <Sparkles className="size-4 text-status-info" />
                    <span>Unchanged SHA-256 match — skipped with $0 re-embedding cost</span>
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="size-4 text-status-verified" />
                    <span>
                      Indexed {lastResult.chunk_count} chunks across {lastResult.page_count}{" "}
                      page(s)
                    </span>
                  </>
                )}
              </div>
              <p className="font-mono text-[11px] tabular-nums text-ledger-ink-secondary">
                corpus v{lastResult.corpus_version} / sha256{" "}
                {lastResult.content_hash.slice(0, 12)} / {lastResult.latency_ms} ms
              </p>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-2 border-t border-ledger-hairline pt-4">
            <button
              type="button"
              onClick={resetAndClose}
              className="h-9 cursor-pointer rounded-lg border border-ledger-hairline px-3.5 text-xs font-medium text-ledger-ink-secondary transition-colors duration-150 hover:border-ledger-hairline-strong hover:text-ledger-ink"
            >
              Close
            </button>
            <button
              type="submit"
              disabled={!file || mutation.isPending}
              className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg bg-ledger-accent px-4 text-xs font-semibold text-ledger-accent-ink transition-colors duration-150 hover:bg-ledger-accent-hover active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45"
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" />
                  <span>Indexing</span>
                </>
              ) : (
                <span>Ingest document</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
