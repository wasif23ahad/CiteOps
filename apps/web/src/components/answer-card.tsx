"use client";

import { BookOpen, CheckCircle2, FileText, RotateCcw, ShieldAlert } from "lucide-react";

import { CitationBadge } from "@/components/citation-badge";
import { TelemetryBar } from "@/components/telemetry-bar";
import { DOC_TYPE_LABELS, type CitationItem, type DocType, type QueryResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

interface AnswerCardProps {
  query: string;
  appliedDocTypes: DocType[] | null;
  response: QueryResponse;
  activeCitationIndex: number | null;
  isActiveBriefing: boolean;
  onInspectCitation: (citations: CitationItem[], index: number) => void;
  onRetryAllCategories?: (queryText: string) => void;
}

function renderTokenizedAnswer(
  answer: string,
  citations: CitationItem[],
  activeCitationIndex: number | null,
  onInspectCitation: (citations: CitationItem[], index: number) => void
) {
  const citationMap = new Map<number, CitationItem>(
    citations.map((c) => [c.citation_index, c])
  );
  const parts = answer.split(/(\[\d+\])/g);

  return parts.map((segment, idx) => {
    const match = /^\[(\d+)\]$/.exec(segment);
    if (!match) {
      return <span key={idx}>{segment}</span>;
    }
    const citationNum = Number.parseInt(match[1], 10);
    const matchedCitation = citationMap.get(citationNum);
    return (
      <CitationBadge
        key={`${idx}-${citationNum}`}
        index={citationNum}
        title={
          matchedCitation
            ? `${matchedCitation.doc_title} (Page ${matchedCitation.page_number})`
            : undefined
        }
        active={activeCitationIndex === citationNum}
        onClick={() => onInspectCitation(citations, citationNum)}
      />
    );
  });
}

export function AnswerCard({
  query,
  appliedDocTypes,
  response,
  activeCitationIndex,
  isActiveBriefing,
  onInspectCitation,
  onRetryAllCategories,
}: AnswerCardProps) {
  const isAbstained = response.status === "insufficient_evidence";
  const hasNarrowFilter = Boolean(appliedDocTypes && appliedDocTypes.length > 0);

  return (
    <article
      className={cn(
        "ledger-folio animate-ledger-enter flex flex-col gap-4 rounded-2xl p-5 sm:p-6",
        isActiveBriefing && !isAbstained && "ring-1 ring-ledger-accent-border"
      )}
    >
      {/* Question Heading + Grounding Seal */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h2 className="text-[17px] font-semibold leading-snug tracking-[-0.02em] text-ledger-ink text-balance">
            {query}
          </h2>
          {hasNarrowFilter && appliedDocTypes && (
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-ledger-ink-muted">
              <span>Scoped to</span>
              {appliedDocTypes.map((dt) => (
                <span
                  key={dt}
                  className="rounded border border-ledger-hairline bg-ledger-inset px-1.5 py-0.5 text-ledger-ink-secondary"
                >
                  {DOC_TYPE_LABELS[dt]}
                </span>
              ))}
            </div>
          )}
        </div>

        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium",
            isAbstained
              ? "border-status-abstained-border bg-status-abstained-tint text-status-abstained"
              : "border-status-verified-border bg-status-verified-tint text-status-verified"
          )}
        >
          {isAbstained ? (
            <>
              <ShieldAlert className="size-3.5" />
              <span>Insufficient evidence</span>
            </>
          ) : (
            <>
              <CheckCircle2 className="size-3.5" />
              <span>Verified</span>
            </>
          )}
        </span>
      </div>

      {/* Main Verdict: Safe Abstention Attestation OR Citation-Locked Answer */}
      {isAbstained ? (
        <div className="flex flex-col gap-3 rounded-xl border border-status-abstained-border bg-status-abstained-tint p-4">
          <div className="flex items-start gap-2.5">
            <ShieldAlert className="mt-0.5 size-4 shrink-0 text-status-abstained" />
            <div className="flex flex-col gap-1.5">
              <p className="text-sm font-medium leading-relaxed text-ledger-ink text-pretty">
                {response.answer}
              </p>
              {response.missing_evidence_reason && (
                <p className="text-xs leading-relaxed text-ledger-ink-secondary text-pretty">
                  {response.missing_evidence_reason}
                </p>
              )}
            </div>
          </div>

          {hasNarrowFilter && onRetryAllCategories && (
            <div className="flex items-center justify-between gap-3 border-t border-status-abstained-border/60 pt-2.5">
              <span className="text-xs text-ledger-ink-secondary">
                Category filter excluded other tenant documents.
              </span>
              <button
                type="button"
                onClick={() => onRetryAllCategories(query)}
                className="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-ledger-hairline-strong bg-ledger-folio px-2.5 py-1 text-xs font-medium text-ledger-ink transition-colors duration-150 hover:border-ledger-accent-border hover:text-ledger-accent active:scale-[0.98]"
              >
                <RotateCcw className="size-3" />
                <span>Search all categories</span>
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          {/* Answer Prose (constrained 68ch measure for crisp audit legibility) */}
          <p className="max-w-[68ch] whitespace-pre-line text-[15px] leading-[1.72] text-ledger-ink text-pretty">
            {renderTokenizedAnswer(
              response.answer,
              response.citations,
              isActiveBriefing ? activeCitationIndex : null,
              onInspectCitation
            )}
          </p>

          {/* Compact Source Ledger Strip */}
          {response.citations.length > 0 && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ledger-ink-tertiary">
                  <BookOpen className="size-3.5 text-ledger-ink-muted" />
                  <span>
                    Grounded sources ({response.citations.length})
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() =>
                    onInspectCitation(
                      response.citations,
                      response.citations[0].citation_index
                    )
                  }
                  className="cursor-pointer text-xs font-medium text-ledger-accent transition-opacity duration-150 hover:opacity-80 xl:hidden"
                >
                  Inspect excerpts
                </button>
              </div>

              <div className="grid gap-2 sm:grid-cols-2">
                {response.citations.map((c) => {
                  const selected =
                    isActiveBriefing && activeCitationIndex === c.citation_index;
                  const pct = Math.round(c.rerank_score * 100);
                  return (
                    <button
                      key={`${c.document_id}-${c.citation_index}`}
                      type="button"
                      onClick={() => onInspectCitation(response.citations, c.citation_index)}
                      className={cn(
                        "group flex cursor-pointer items-start gap-2.5 rounded-xl border px-3 py-2.5 text-left transition-colors duration-150 active:scale-[0.99]",
                        selected
                          ? "border-ledger-accent-border bg-ledger-accent-tint/60"
                          : "border-ledger-hairline bg-ledger-inset/70 hover:border-ledger-hairline-strong"
                      )}
                    >
                      <span
                        className={cn(
                          "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded font-mono text-[11px] font-semibold tabular-nums transition-colors duration-150",
                          selected
                            ? "bg-ledger-accent text-ledger-accent-ink"
                            : "border border-ledger-hairline-strong bg-ledger-folio text-ledger-ink-secondary group-hover:border-ledger-accent-border group-hover:text-ledger-accent"
                        )}
                      >
                        {c.citation_index}
                      </span>
                      <div className="flex min-w-0 flex-1 flex-col gap-1">
                        <p className="truncate text-xs font-medium text-ledger-ink">
                          {c.doc_title}
                        </p>
                        <div className="flex items-center justify-between gap-2 text-[11px] text-ledger-ink-tertiary">
                          <span className="inline-flex items-center gap-1 font-mono tabular-nums">
                            <FileText className="size-3 text-ledger-ink-muted" />
                            <span>p.{c.page_number}</span>
                            <span className="font-sans text-ledger-ink-muted">
                              {DOC_TYPE_LABELS[c.doc_type]}
                            </span>
                          </span>
                          <span className="font-mono font-medium tabular-nums text-status-verified">
                            {pct}%
                          </span>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Hairline Telemetry & Stage Waterfall Footer */}
      <TelemetryBar telemetry={response.telemetry} />
    </article>
  );
}
