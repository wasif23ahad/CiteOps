"use client";

import { Clock, Cpu, Gauge, Hash, Zap } from "lucide-react";

import type { QueryTelemetry } from "@/lib/types";
import { cn } from "@/lib/utils";

function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function TelemetryBar({ telemetry }: { telemetry: QueryTelemetry }) {
  const tierLabel =
    telemetry.cache_tier === "exact"
      ? "CACHE HIT · L1 EXACT"
      : telemetry.cache_tier === "semantic"
        ? "CACHE HIT · L2 SEMANTIC"
        : "CACHE MISS";

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3 text-[11px] text-muted-foreground">
      {/* Cache Status Pill */}
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 font-mono font-semibold",
          telemetry.cache_hit
            ? "border border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
            : "border border-border bg-muted text-muted-foreground"
        )}
      >
        <Zap className="h-3 w-3" />
        {tierLabel}
      </span>

      {/* Total Latency + Breakdown Tooltip */}
      <span
        title={`Retrieval: ${telemetry.retrieval_ms}ms · Rerank: ${telemetry.rerank_ms}ms · LLM: ${telemetry.llm_ms}ms`}
        className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2.5 py-0.5 font-mono"
      >
        <Clock className="h-3 w-3" />
        <span>{formatLatency(telemetry.latency_ms)}</span>
        {!telemetry.cache_hit && (
          <span className="hidden text-muted-foreground/75 sm:inline">
            (ret {telemetry.retrieval_ms}ms · rr {telemetry.rerank_ms}ms · llm {telemetry.llm_ms}
            ms)
          </span>
        )}
      </span>

      {/* Top Rerank Confidence */}
      {telemetry.top_rerank_score !== null && (
        <span className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2.5 py-0.5 font-mono">
          <Gauge className="h-3 w-3" />
          <span>Confidence {(telemetry.top_rerank_score * 100).toFixed(1)}%</span>
        </span>
      )}

      {/* Active Model */}
      <span className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2.5 py-0.5 font-mono">
        <Cpu className="h-3 w-3" />
        <span>{telemetry.model}</span>
      </span>

      {/* Trace ID */}
      <span
        title={`Trace ID: ${telemetry.trace_id}`}
        className="ml-auto inline-flex items-center gap-1 font-mono text-[10px] text-muted-foreground/80"
      >
        <Hash className="h-3 w-3" />
        <span>{telemetry.trace_id.slice(0, 12)}</span>
      </span>
    </div>
  );
}
