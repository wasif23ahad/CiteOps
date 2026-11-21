"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import type { QueryTelemetry } from "@/lib/types";
import { cn } from "@/lib/utils";

function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function TelemetryBar({ telemetry }: { telemetry: QueryTelemetry }) {
  const [copiedTrace, setCopiedTrace] = useState(false);

  const tierLabel =
    telemetry.cache_tier === "exact"
      ? "L1 cache hit"
      : telemetry.cache_tier === "semantic"
        ? "L2 semantic hit"
        : "Live retrieval";

  const stageSum = Math.max(
    1,
    telemetry.retrieval_ms + telemetry.rerank_ms + telemetry.llm_ms
  );
  const retPct = (telemetry.retrieval_ms / stageSum) * 100;
  const rrPct = (telemetry.rerank_ms / stageSum) * 100;
  const llmPct = (telemetry.llm_ms / stageSum) * 100;

  const handleCopyTrace = async () => {
    try {
      await navigator.clipboard.writeText(telemetry.trace_id);
      setCopiedTrace(true);
      window.setTimeout(() => setCopiedTrace(false), 1600);
    } catch {
      // Ignore clipboard denials
    }
  };

  return (
    <footer className="flex flex-wrap items-center justify-between gap-x-5 gap-y-2 border-t border-ledger-hairline pt-3 text-xs text-ledger-ink-tertiary">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {/* Cache Tier Indicator */}
        <span
          className={cn(
            "inline-flex items-center gap-1.5 font-medium",
            telemetry.cache_hit ? "text-status-verified" : "text-ledger-ink-secondary"
          )}
        >
          <span
            className={cn(
              "size-1.5 rounded-full",
              telemetry.cache_hit ? "bg-status-verified" : "bg-ledger-ink-muted"
            )}
          />
          {tierLabel}
        </span>

        {/* Latency + Micro Proportional Stage Waterfall */}
        <div
          className="inline-flex items-center gap-2 font-mono text-[11px] tabular-nums"
          title={`Retrieval ${telemetry.retrieval_ms} ms, Rerank ${telemetry.rerank_ms} ms, Generation ${telemetry.llm_ms} ms`}
        >
          <span className="font-medium text-ledger-ink">
            {formatLatency(telemetry.latency_ms)}
          </span>
          {!telemetry.cache_hit && (
            <div className="hidden items-center gap-2 sm:flex">
              <div
                aria-hidden="true"
                className="flex h-1.5 w-14 overflow-hidden rounded-full bg-ledger-hairline"
              >
                {telemetry.retrieval_ms > 0 && (
                  <span
                    className="h-full bg-status-info"
                    style={{ width: `${Math.max(8, retPct)}%` }}
                  />
                )}
                {telemetry.rerank_ms > 0 && (
                  <span
                    className="h-full bg-status-abstained"
                    style={{ width: `${Math.max(8, rrPct)}%` }}
                  />
                )}
                {telemetry.llm_ms > 0 && (
                  <span
                    className="h-full bg-ledger-accent"
                    style={{ width: `${Math.max(8, llmPct)}%` }}
                  />
                )}
              </div>
              <span className="text-ledger-ink-muted">
                ret {telemetry.retrieval_ms}ms / rr {telemetry.rerank_ms}ms / llm{" "}
                {telemetry.llm_ms}ms
              </span>
            </div>
          )}
        </div>

        {/* Confidence Readout */}
        {telemetry.top_rerank_score !== null && (
          <span className="font-mono text-[11px] tabular-nums text-ledger-ink-secondary">
            Match {(telemetry.top_rerank_score * 100).toFixed(0)}%
          </span>
        )}

        {/* Active Model */}
        <span className="font-mono text-[11px] text-ledger-ink-muted">
          {telemetry.model}
        </span>
      </div>

      {/* Copyable Trace Identifier */}
      <button
        type="button"
        onClick={handleCopyTrace}
        title={`Copy trace ID ${telemetry.trace_id}`}
        className="inline-flex cursor-pointer items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[11px] text-ledger-ink-muted transition-colors duration-150 hover:bg-ledger-hairline-subtle hover:text-ledger-ink"
      >
        {copiedTrace ? (
          <>
            <Check className="size-3 text-status-verified" />
            <span className="text-status-verified">Copied</span>
          </>
        ) : (
          <>
            <Copy className="size-3" />
            <span>{telemetry.trace_id.slice(0, 10)}</span>
          </>
        )}
      </button>
    </footer>
  );
}
