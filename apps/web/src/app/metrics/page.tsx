"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  Clock,
  Cpu,
  Gauge,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Zap,
} from "lucide-react";

import { ApiError, getMetricsSummary } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";

function fmtMs(value: number | null): string {
  if (value === null) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)}s`;
}

export default function MetricsPage() {
  const { tenantId } = useTenant();

  const metricsQuery = useQuery({
    queryKey: ["metrics", tenantId],
    queryFn: () => getMetricsSummary(tenantId),
  });

  const data = metricsQuery.data;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Observability & Unit Economics</h1>
          <p className="mt-1 text-xs text-muted-foreground sm:text-sm">
            RLS-scoped telemetry from <code className="font-mono">query_audit_logs</code> for{" "}
            <span className="font-mono font-semibold">{tenantId}</span>.
          </p>
        </div>

        <button
          type="button"
          onClick={() => metricsQuery.refetch()}
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-xs font-medium hover:bg-muted"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${metricsQuery.isFetching ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {metricsQuery.isError && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-500/35 bg-rose-500/10 p-4 text-xs text-rose-700 dark:text-rose-300">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>
            {metricsQuery.error instanceof ApiError
              ? metricsQuery.error.message
              : "Unable to load metrics summary."}
          </span>
        </div>
      )}

      {metricsQuery.isLoading || !data ? (
        <div className="flex items-center justify-center rounded-xl border border-border bg-card py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          {/* Primary KPI Row */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>Total Queries</span>
                <Activity className="h-4 w-4 text-primary" />
              </div>
              <p className="mt-2 font-mono text-2xl font-semibold">{data.total_queries}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Scoped to tenant <span className="font-mono">{data.tenant_id}</span>
              </p>
            </div>

            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>Cache Hit Rate</span>
                <Zap className="h-4 w-4 text-emerald-500" />
              </div>
              <p className="mt-2 font-mono text-2xl font-semibold">
                {(data.cache_hit_rate * 100).toFixed(1)}%
              </p>
              <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                L1 Exact: {data.exact_cache_hits} · L2 Semantic: {data.semantic_cache_hits}
              </p>
            </div>

            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>Safe Abstention Rate</span>
                <ShieldAlert className="h-4 w-4 text-amber-500" />
              </div>
              <p className="mt-2 font-mono text-2xl font-semibold">
                {(data.abstention_rate * 100).toFixed(1)}%
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Dual-gate refusal on insufficient evidence
              </p>
            </div>

            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>Median Latency (p50)</span>
                <Clock className="h-4 w-4 text-primary" />
              </div>
              <p className="mt-2 font-mono text-2xl font-semibold">
                {fmtMs(data.p50_latency_ms)}
              </p>
              <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                p95 overall: {fmtMs(data.p95_latency_ms)}
              </p>
            </div>
          </div>

          {/* Latency Breakdown + Runtime Profile */}
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border bg-card p-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <Gauge className="h-4 w-4 text-primary" />
                Latency Percentiles (Cache Hit vs. Miss)
              </h2>
              <div className="mt-4 space-y-3 text-xs">
                <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3.5 py-2.5">
                  <span className="text-muted-foreground">Cache Hit p95 (L1 + L2)</span>
                  <span className="font-mono font-semibold text-emerald-700 dark:text-emerald-300">
                    {fmtMs(data.p95_cache_hit_ms)}
                  </span>
                </div>
                <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3.5 py-2.5">
                  <span className="text-muted-foreground">Cache Miss p95 (Retrieval + Rerank + LLM)</span>
                  <span className="font-mono font-semibold">{fmtMs(data.p95_cache_miss_ms)}</span>
                </div>
                <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3.5 py-2.5">
                  <span className="text-muted-foreground">Overall p50 / p95</span>
                  <span className="font-mono font-semibold">
                    {fmtMs(data.p50_latency_ms)} / {fmtMs(data.p95_latency_ms)}
                  </span>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-border bg-card p-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <Cpu className="h-4 w-4 text-primary" />
                Active Inference & Isolation Profile
              </h2>
              <dl className="mt-4 space-y-3 text-xs">
                <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3.5 py-2.5">
                  <dt className="text-muted-foreground">Primary LLM</dt>
                  <dd className="font-mono font-semibold">{data.active_llm_model}</dd>
                </div>
                <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3.5 py-2.5">
                  <dt className="text-muted-foreground">Cross-Encoder Reranker</dt>
                  <dd className="font-mono font-semibold">
                    {data.active_reranker_model} ({data.reranker_profile})
                  </dd>
                </div>
                <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3.5 py-2.5">
                  <dt className="text-muted-foreground">Multi-Tenant Isolation</dt>
                  <dd className="font-mono font-semibold text-emerald-700 dark:text-emerald-300">
                    PostgreSQL RLS + Versioned Redis
                  </dd>
                </div>
              </dl>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
