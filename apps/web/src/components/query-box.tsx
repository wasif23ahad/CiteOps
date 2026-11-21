"use client";

import { ArrowUp, Loader2, Sparkles } from "lucide-react";
import type { FormEvent, KeyboardEvent } from "react";

import { DOC_TYPE_LABELS, type DocType } from "@/lib/types";
import { cn } from "@/lib/utils";

const ALL_DOC_TYPES: DocType[] = [
  "api_docs",
  "security_policy",
  "sla_contract",
  "runbook",
];

const SAMPLE_PROMPTS: Record<string, { label: string; query: string }[]> = {
  "acme-corp": [
    {
      label: "Tier-2: ERR_SIG_4092 + Rollback",
      query:
        "Why does webhook signature verification fail with ERR_SIG_4092 on SDK v2.4.1, and what is the rollback procedure?",
    },
    {
      label: "RFP: Section 4.2 + HIPAA Trap",
      query:
        "Under Section 4.2 of the Enterprise SLA, is AES-256 encryption enforced at rest, what is the Sev-1 RTO, and is a HIPAA BAA included by default?",
    },
    {
      label: "Abstention: FedRAMP High",
      query: "Does CloudPulse currently hold FedRAMP High authorization?",
    },
    {
      label: "Isolation Probe: ERR_GLOBEX_9901",
      query: "How do I resolve ERR_GLOBEX_9901?",
    },
  ],
  "globex-io": [
    {
      label: "Globex HSM: ERR_GLOBEX_9901",
      query: "How do I resolve ERR_GLOBEX_9901?",
    },
    {
      label: "Globex Sovereign Enclave RTO",
      query: "What region and Sev-1 RTO guarantee apply to Globex IO?",
    },
    {
      label: "Relay Secret Rotation Cadence",
      query: "How often does Globex IO rotate webhook relay keys and what command is used?",
    },
  ],
};

interface QueryBoxProps {
  tenantId: string;
  query: string;
  onQueryChange: (value: string) => void;
  selectedDocTypes: DocType[];
  onToggleDocType: (docType: DocType | null) => void;
  isLoading: boolean;
  onSubmit: (queryText?: string) => void;
}

export function QueryBox({
  tenantId,
  query,
  onQueryChange,
  selectedDocTypes,
  onToggleDocType,
  isLoading,
  onSubmit,
}: QueryBoxProps) {
  const prompts = SAMPLE_PROMPTS[tenantId] ?? SAMPLE_PROMPTS["acme-corp"];

  const handleFormSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!isLoading && query.trim().length >= 3) {
      onSubmit();
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!isLoading && query.trim().length >= 3) {
        onSubmit();
      }
    }
  };

  return (
    <section className="space-y-3">
      <form
        onSubmit={handleFormSubmit}
        className="rounded-xl border border-border bg-card p-3 shadow-xs focus-within:border-primary/60 focus-within:ring-2 focus-within:ring-primary/15"
      >
        <textarea
          rows={3}
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
          placeholder={`Ask a compliance or Tier-2 support question scoped to ${tenantId}...`}
          aria-label="Ask CiteOps a question"
          className="w-full resize-none bg-transparent px-1 py-1 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none sm:text-[15px]"
        />

        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-2.5">
          {/* Category Filter Pills */}
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => onToggleDocType(null)}
              className={cn(
                "cursor-pointer rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
                selectedDocTypes.length === 0
                  ? "bg-primary text-primary-foreground"
                  : "border border-border bg-background text-muted-foreground hover:bg-muted"
              )}
            >
              All Docs
            </button>
            {ALL_DOC_TYPES.map((dt) => {
              const active = selectedDocTypes.includes(dt);
              return (
                <button
                  key={dt}
                  type="button"
                  onClick={() => onToggleDocType(dt)}
                  className={cn(
                    "cursor-pointer rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
                    active
                      ? "bg-primary text-primary-foreground"
                      : "border border-border bg-background text-muted-foreground hover:bg-muted"
                  )}
                >
                  {DOC_TYPE_LABELS[dt]}
                </button>
              );
            })}
          </div>

          <button
            type="submit"
            disabled={isLoading || query.trim().length < 3}
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-primary px-3.5 py-1.5 text-xs font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>Searching & Verifying...</span>
              </>
            ) : (
              <>
                <span>Ask CiteOps</span>
                <ArrowUp className="h-3.5 w-3.5" />
              </>
            )}
          </button>
        </div>
      </form>

      {/* Clickable Sample Prompt Chips */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
          <Sparkles className="h-3 w-3" />
          Try:
        </span>
        {prompts.map((sample) => (
          <button
            key={sample.label}
            type="button"
            disabled={isLoading}
            onClick={() => {
              onQueryChange(sample.query);
              onSubmit(sample.query);
            }}
            className="cursor-pointer rounded-full border border-border bg-card px-2.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-50"
          >
            {sample.label}
          </button>
        ))}
      </div>
    </section>
  );
}
