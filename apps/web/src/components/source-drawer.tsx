"use client";

import { BookOpen, Check, Copy, FileText, Layers, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { DOC_TYPE_LABELS, type CitationItem } from "@/lib/types";
import { cn } from "@/lib/utils";

interface EvidenceInspectorProps {
  citations: CitationItem[];
  activeIndex: number | null;
  onSelect: (index: number) => void;
  onClose?: () => void;
}

function CitationFolioCard({
  citation,
  isSelected,
  onSelect,
  cardRef,
}: {
  citation: CitationItem;
  isSelected: boolean;
  onSelect: () => void;
  cardRef: (el: HTMLDivElement | null) => void;
}) {
  const [copied, setCopied] = useState(false);
  const scorePct = Math.round(citation.rerank_score * 100);

  const handleCopyCitation = async (event: React.MouseEvent) => {
    event.stopPropagation();
    const formatted = `${citation.doc_title} (${citation.version}, Page ${citation.page_number}${
      citation.section_path ? ` — ${citation.section_path}` : ""
    }): "${citation.excerpt}"`;
    try {
      await navigator.clipboard.writeText(formatted);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Ignore clipboard failures
    }
  };

  return (
    <div
      ref={cardRef}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "flex cursor-pointer flex-col gap-3 rounded-xl border p-3.5 text-left transition-colors duration-150",
        isSelected
          ? "border-ledger-accent-border bg-ledger-accent-tint/60"
          : "border-ledger-hairline bg-ledger-folio hover:border-ledger-hairline-strong"
      )}
    >
      {/* Document Header + Match Confidence */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span
            className={cn(
              "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md font-mono text-xs font-semibold tabular-nums",
              isSelected
                ? "bg-ledger-accent text-ledger-accent-ink"
                : "border border-ledger-hairline-strong bg-ledger-inset text-ledger-ink-secondary"
            )}
          >
            {citation.citation_index}
          </span>
          <div className="min-w-0">
            <h3 className="text-[13px] font-semibold leading-snug text-ledger-ink">
              {citation.doc_title}
            </h3>
            <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-ledger-ink-tertiary">
              <span>{DOC_TYPE_LABELS[citation.doc_type]}</span>
              <span className="font-mono">{citation.version}</span>
              <span className="inline-flex items-center gap-1 font-mono font-medium text-ledger-ink-secondary tabular-nums">
                <FileText className="size-3 text-ledger-ink-muted" />
                Page {citation.page_number}
              </span>
            </div>
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1">
          <span className="font-mono text-xs font-semibold tabular-nums text-status-verified">
            {scorePct}%
          </span>
          <div
            aria-hidden="true"
            className="h-1 w-12 overflow-hidden rounded-full bg-ledger-hairline"
          >
            <div
              className="h-full rounded-full bg-status-verified"
              style={{ width: `${Math.min(100, Math.max(6, scorePct))}%` }}
            />
          </div>
        </div>
      </div>

      {/* Section Breadcrumb */}
      {citation.section_path && (
        <div className="flex items-center gap-1.5 text-[11px] text-ledger-ink-tertiary">
          <Layers className="size-3 shrink-0 text-ledger-ink-muted" />
          <span className="truncate" title={citation.section_path}>
            {citation.section_path}
          </span>
        </div>
      )}

      {/* Verbatim Source Excerpt (recessed inset well, full hairline border) */}
      <blockquote className="rounded-lg border border-ledger-hairline bg-ledger-inset px-3 py-2.5 font-mono text-[11.5px] leading-[1.65] text-ledger-ink-secondary">
        {citation.excerpt}
      </blockquote>

      {/* Footer: Document UUID + Copy Audit Citation */}
      <div className="flex items-center justify-between gap-2 pt-0.5">
        <span
          className="truncate font-mono text-[10px] text-ledger-ink-muted"
          title={citation.document_id}
        >
          {citation.document_id.slice(0, 18)}
        </span>
        <button
          type="button"
          onClick={handleCopyCitation}
          className="inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-md border border-ledger-hairline px-2 py-1 text-[11px] font-medium text-ledger-ink-secondary transition-colors duration-150 hover:border-ledger-hairline-strong hover:text-ledger-ink active:scale-[0.97]"
        >
          {copied ? (
            <>
              <Check className="size-3 text-status-verified" />
              <span className="text-status-verified">Copied</span>
            </>
          ) : (
            <>
              <Copy className="size-3" />
              <span>Copy citation</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}

function EvidenceInspectorBody({
  citations,
  activeIndex,
  onSelect,
  onClose,
}: EvidenceInspectorProps) {
  const cardRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    if (activeIndex !== null) {
      const target = cardRefs.current[activeIndex];
      target?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [activeIndex]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-ledger-hairline px-4">
        <div className="flex items-center gap-2">
          <BookOpen className="size-4 text-ledger-accent" />
          <h2 className="text-[13px] font-semibold tracking-[-0.01em] text-ledger-ink">
            Evidence inspector
          </h2>
          {citations.length > 0 && (
            <span className="rounded-md bg-ledger-accent-tint px-1.5 py-0.5 font-mono text-[11px] font-medium tabular-nums text-ledger-accent">
              {citations.length}
            </span>
          )}
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close evidence inspector"
            className="flex size-8 cursor-pointer items-center justify-center rounded-lg text-ledger-ink-muted transition-colors duration-150 hover:bg-ledger-hairline-subtle hover:text-ledger-ink"
          >
            <X className="size-4" />
          </button>
        )}
      </div>

      {/* Scrollable Citation Folios */}
      <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
        {citations.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2.5 px-4 py-12 text-center">
            <div className="flex size-10 items-center justify-center rounded-xl border border-ledger-hairline bg-ledger-inset text-ledger-ink-muted">
              <BookOpen className="size-4" />
            </div>
            <p className="text-xs font-medium text-ledger-ink-secondary">
              Verbatim source folios appear here
            </p>
            <p className="max-w-[26ch] text-xs leading-relaxed text-ledger-ink-muted text-pretty">
              Select any numbered citation token inside an answer to inspect the exact
              page, section breadcrumb, and calibrated reranker score.
            </p>
          </div>
        ) : (
          citations.map((citation) => (
            <CitationFolioCard
              key={`${citation.document_id}-${citation.citation_index}`}
              citation={citation}
              isSelected={activeIndex === citation.citation_index}
              onSelect={() => onSelect(citation.citation_index)}
              cardRef={(el) => {
                cardRefs.current[citation.citation_index] = el;
              }}
            />
          ))
        )}
      </div>
    </div>
  );
}

/**
 * Sticky side-by-side Evidence Inspector rail rendered on wide desktop viewports (`xl+`),
 * enabling compliance engineers to verify verbatim excerpts alongside the active answer.
 */
export function DockedEvidenceRail({
  citations,
  activeIndex,
  onSelect,
}: Omit<EvidenceInspectorProps, "onClose">) {
  return (
    <aside
      aria-label="Evidence inspector"
      className="hidden w-[384px] shrink-0 border-l border-ledger-hairline bg-ledger-rail xl:sticky xl:top-0 xl:flex xl:h-screen xl:flex-col"
    >
      <EvidenceInspectorBody
        citations={citations}
        activeIndex={activeIndex}
        onSelect={onSelect}
      />
    </aside>
  );
}

interface SourceDrawerProps extends EvidenceInspectorProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Slide-over Evidence Inspector sheet for viewports narrower than `xl` (or explicit inspection).
 */
export function SourceDrawer({
  open,
  citations,
  activeIndex,
  onSelect,
  onClose,
}: SourceDrawerProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-[2px] xl:hidden"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Evidence inspector"
    >
      <aside
        onClick={(e) => e.stopPropagation()}
        className="ledger-overlay animate-ledger-enter flex h-full w-full max-w-md flex-col border-l border-ledger-hairline bg-ledger-rail"
      >
        <EvidenceInspectorBody
          citations={citations}
          activeIndex={activeIndex}
          onSelect={onSelect}
          onClose={onClose}
        />
      </aside>
    </div>
  );
}
