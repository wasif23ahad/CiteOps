"use client";

import { BookOpen, FileText, Gauge, Layers, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { DOC_TYPE_LABELS, type CitationItem } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SourceDrawerProps {
  open: boolean;
  citations: CitationItem[];
  activeIndex: number | null;
  onSelect: (index: number) => void;
  onClose: () => void;
}

export function SourceDrawer({
  open,
  citations,
  activeIndex,
  onSelect,
  onClose,
}: SourceDrawerProps) {
  const cardRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (open && activeIndex !== null) {
      const target = cardRefs.current[activeIndex];
      target?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [open, activeIndex]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-[1px]"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Source Inspector Drawer"
    >
      <aside
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-lg flex-col border-l border-border bg-card shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold">Source Inspector</h2>
            <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
              {citations.length} verified
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close source inspector"
            className="cursor-pointer rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Citation Cards */}
        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          {citations.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No verified citations attached to this response.
            </p>
          ) : (
            citations.map((citation) => {
              const isSelected = activeIndex === citation.citation_index;
              const scorePct = Math.round(citation.rerank_score * 100);
              return (
                <div
                  key={`${citation.document_id}-${citation.citation_index}`}
                  ref={(el) => {
                    cardRefs.current[citation.citation_index] = el;
                  }}
                  onClick={() => onSelect(citation.citation_index)}
                  className={cn(
                    "cursor-pointer rounded-lg border p-4 transition-all",
                    isSelected
                      ? "border-primary bg-accent/40 ring-2 ring-primary/20"
                      : "border-border bg-background hover:border-primary/40"
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-2.5">
                      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded bg-primary font-mono text-xs font-semibold text-primary-foreground">
                        {citation.citation_index}
                      </span>
                      <div>
                        <h3 className="text-sm font-semibold leading-snug">
                          {citation.doc_title}
                        </h3>
                        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                          <span className="rounded bg-muted px-1.5 py-0.5 font-medium">
                            {DOC_TYPE_LABELS[citation.doc_type]}
                          </span>
                          <span className="font-mono">{citation.version}</span>
                          <span>·</span>
                          <span className="inline-flex items-center gap-0.5 font-mono font-semibold text-foreground">
                            <FileText className="h-3 w-3" />
                            Page {citation.page_number}
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className="shrink-0 text-right">
                      <span className="inline-flex items-center gap-1 font-mono text-xs font-semibold text-emerald-700 dark:text-emerald-300">
                        <Gauge className="h-3 w-3" />
                        {scorePct}%
                      </span>
                      <div className="mt-1 h-1.5 w-16 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-emerald-500"
                          style={{ width: `${Math.min(100, Math.max(4, scorePct))}%` }}
                        />
                      </div>
                    </div>
                  </div>

                  {citation.section_path && (
                    <div className="mt-3 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <Layers className="h-3 w-3 shrink-0" />
                      <span className="truncate" title={citation.section_path}>
                        {citation.section_path}
                      </span>
                    </div>
                  )}

                  <blockquote className="mt-3 rounded-md border-l-2 border-primary bg-muted/60 px-3 py-2.5 font-mono text-xs leading-relaxed text-foreground">
                    {citation.excerpt}
                  </blockquote>

                  <div className="mt-2 font-mono text-[10px] text-muted-foreground/80">
                    doc_id: {citation.document_id}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </aside>
    </div>
  );
}
