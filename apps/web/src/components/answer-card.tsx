"use client";

import { BookOpen, CheckCircle2, FileText, ShieldAlert } from "lucide-react";

import { CitationBadge } from "@/components/citation-badge";
import { TelemetryBar } from "@/components/telemetry-bar";
import { DOC_TYPE_LABELS, type CitationItem, type QueryResponse } from "@/lib/types";

interface AnswerCardProps {
  query: string;
  response: QueryResponse;
  activeCitationIndex: number | null;
  onInspectCitation: (citations: CitationItem[], index: number) => void;
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
            ? `${matchedCitation.doc_title} (p.${matchedCitation.page_number})`
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
  response,
  activeCitationIndex,
  onInspectCitation,
}: AnswerCardProps) {
  const isAbstained = response.status === "insufficient_evidence";

  return (
    <article className="space-y-4 rounded-xl border border-border bg-card p-5 shadow-xs">
      {/* User Question Header */}
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-base font-semibold leading-snug tracking-tight sm:text-lg">
          {query}
        </h2>
        <span
          className={
            isAbstained
              ? "inline-flex shrink-0 items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-amber-700 dark:text-amber-300"
              : "inline-flex shrink-0 items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-700 dark:text-emerald-300"
          }
        >
          {isAbstained ? (
            <>
              <ShieldAlert className="h-3.5 w-3.5" />
              Abstained
            </>
          ) : (
            <>
              <CheckCircle2 className="h-3.5 w-3.5" />
              Verified Grounding
            </>
          )}
        </span>
      </div>

      {/* Main Answer Body or Safe Abstention Alert */}
      {isAbstained ? (
        <div className="rounded-lg border border-amber-500/35 bg-amber-500/10 p-4 text-sm">
          <div className="flex items-start gap-2.5">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <div className="space-y-1">
              <p className="font-medium text-foreground">{response.answer}</p>
              {response.missing_evidence_reason && (
                <p className="text-xs leading-relaxed text-muted-foreground">
                  <span className="font-semibold text-foreground">Gap identified: </span>
                  {response.missing_evidence_reason}
                </p>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="whitespace-pre-line text-sm leading-7 text-foreground/95 sm:text-[15px]">
            {renderTokenizedAnswer(
              response.answer,
              response.citations,
              activeCitationIndex,
              onInspectCitation
            )}
          </p>

          {/* Compact Source Cards Strip */}
          {response.citations.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <BookOpen className="h-3.5 w-3.5" />
                  Verified Sources ({response.citations.length})
                </span>
                <button
                  type="button"
                  onClick={() =>
                    onInspectCitation(
                      response.citations,
                      response.citations[0].citation_index
                    )
                  }
                  className="cursor-pointer text-xs font-medium text-primary hover:underline"
                >
                  Open Inspector →
                </button>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {response.citations.map((c) => (
                  <button
                    key={`${c.document_id}-${c.citation_index}`}
                    type="button"
                    onClick={() => onInspectCitation(response.citations, c.citation_index)}
                    className="group flex cursor-pointer items-start gap-2.5 rounded-lg border border-border bg-background p-3 text-left transition-colors hover:border-primary/50 hover:bg-accent/30"
                  >
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded bg-accent font-mono text-[11px] font-semibold text-accent-foreground group-hover:bg-primary group-hover:text-primary-foreground">
                      {c.citation_index}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-semibold text-foreground">
                        {c.doc_title}
                      </p>
                      <p className="mt-0.5 flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
                        <FileText className="h-3 w-3 shrink-0" />
                        <span>p.{c.page_number}</span>
                        <span>·</span>
                        <span>{DOC_TYPE_LABELS[c.doc_type]}</span>
                        <span>·</span>
                        <span className="text-emerald-700 dark:text-emerald-300">
                          {Math.round(c.rerank_score * 100)}%
                        </span>
                      </p>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Telemetry Pill Bar */}
      <TelemetryBar telemetry={response.telemetry} />
    </article>
  );
}
