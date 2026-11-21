"use client";

import { ArrowUp, Loader2 } from "lucide-react";
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
      label: "ERR_SIG_4092 + Rollback",
      query:
        "Why does webhook signature verification fail with ERR_SIG_4092 on SDK v2.4.1, and what is the rollback procedure?",
    },
    {
      label: "Section 4.2 + HIPAA BAA",
      query:
        "Under Section 4.2 of the Enterprise SLA, is AES-256 encryption enforced at rest, what is the Sev-1 RTO, and is a HIPAA BAA included by default?",
    },
    {
      label: "FedRAMP High (Abstain)",
      query: "Does CloudPulse currently hold FedRAMP High authorization?",
    },
    {
      label: "ERR_GLOBEX_9901 (Isolation)",
      query: "How do I resolve ERR_GLOBEX_9901?",
    },
  ],
  "globex-io": [
    {
      label: "ERR_GLOBEX_9901 HSM",
      query: "How do I resolve ERR_GLOBEX_9901?",
    },
    {
      label: "Dublin Sovereign Enclave RTO",
      query: "What region and Sev-1 RTO guarantee apply to Globex IO?",
    },
    {
      label: "Relay Key Rotation",
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
  onSubmit: (queryText?: string, overrideDocTypes?: DocType[]) => void;
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
  const canSubmit = !isLoading && query.trim().length >= 3;

  const handleFormSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (canSubmit) {
      onSubmit();
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSubmit) {
        onSubmit();
      }
    }
  };

  return (
    <section aria-label="Evidence query composer" className="flex flex-col gap-3">
      {/* Concentric Composer Shell: outer rounded-2xl (p-2) -> inner inset well rounded-xl */}
      <form
        onSubmit={handleFormSubmit}
        className="ledger-folio flex flex-col gap-2 rounded-2xl p-2"
      >
        <div className="rounded-xl border border-ledger-hairline bg-ledger-inset px-3.5 py-2.5 transition-colors duration-150 focus-within:border-ledger-accent-border">
          <textarea
            rows={3}
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            placeholder={`Ask a Tier-2 incident or security compliance question for ${tenantId}...`}
            aria-label="Ask CiteOps a question"
            className="w-full resize-none bg-transparent text-[15px] leading-relaxed text-ledger-ink placeholder:text-ledger-ink-muted focus:outline-none disabled:opacity-60"
          />
        </div>

        {/* Bottom Control Strip: Document Category Scope + Submit Action */}
        <div className="flex flex-wrap items-center justify-between gap-2 px-1.5 pb-1 pt-0.5">
          <div
            role="group"
            aria-label="Filter document categories"
            className="flex flex-wrap items-center gap-1"
          >
            <button
              type="button"
              aria-pressed={selectedDocTypes.length === 0}
              onClick={() => onToggleDocType(null)}
              className={cn(
                "cursor-pointer rounded-lg px-2.5 py-1 text-xs font-medium transition-colors duration-150 active:scale-[0.98]",
                selectedDocTypes.length === 0
                  ? "bg-ledger-accent-tint text-ledger-accent"
                  : "text-ledger-ink-tertiary hover:bg-ledger-hairline-subtle hover:text-ledger-ink"
              )}
            >
              All docs
            </button>
            {ALL_DOC_TYPES.map((dt) => {
              const active = selectedDocTypes.includes(dt);
              return (
                <button
                  key={dt}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onToggleDocType(dt)}
                  className={cn(
                    "cursor-pointer rounded-lg px-2.5 py-1 text-xs font-medium transition-colors duration-150 active:scale-[0.98]",
                    active
                      ? "bg-ledger-accent-tint text-ledger-accent"
                      : "text-ledger-ink-tertiary hover:bg-ledger-hairline-subtle hover:text-ledger-ink"
                  )}
                >
                  {DOC_TYPE_LABELS[dt]}
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-2.5">
            <span className="hidden font-mono text-[11px] text-ledger-ink-muted sm:inline">
              Enter to search
            </span>
            <button
              type="submit"
              disabled={!canSubmit}
              className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg bg-ledger-accent px-3.5 text-xs font-semibold text-ledger-accent-ink transition-colors duration-150 hover:bg-ledger-accent-hover active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45"
            >
              {isLoading ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" />
                  <span>Verifying</span>
                </>
              ) : (
                <>
                  <span>Search</span>
                  <ArrowUp className="size-3.5" />
                </>
              )}
            </button>
          </div>
        </div>
      </form>

      {/* Tenant-Scoped Quick Scenarios (auto-resets category filter to All docs) */}
      <div className="flex flex-wrap items-center gap-1.5 px-0.5">
        <span className="text-xs text-ledger-ink-muted">Scenarios:</span>
        {prompts.map((sample) => (
          <button
            key={sample.label}
            type="button"
            disabled={isLoading}
            onClick={() => {
              onToggleDocType(null);
              onQueryChange(sample.query);
              onSubmit(sample.query, []);
            }}
            className="cursor-pointer rounded-lg border border-ledger-hairline bg-ledger-folio px-2.5 py-1 text-xs font-medium text-ledger-ink-secondary transition-colors duration-150 hover:border-ledger-hairline-strong hover:text-ledger-ink active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45"
          >
            {sample.label}
          </button>
        ))}
      </div>
    </section>
  );
}
