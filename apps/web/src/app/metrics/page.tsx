"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, RefreshCw, ShieldCheck } from "lucide-react";

import { ApiError, getMetricsSummary } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import { cn } from "@/lib/utils";

function fmtMs(value: number | null): string {
  if (value === null) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

function MetricsSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="ledger-folio flex flex-col gap-4 rounded-2xl p-6 lg:col-span-2">
          <div className="ledger-skeleton h-4 w-36 rounded" />
          <div className="ledger-skeleton h-10 w-28 rounded-md" />
          <div className="ledger-skeleton h-2.5 w-full rounded-full" />
        </div>
        <div className="ledger-folio flex flex-col gap-4 rounded-2xl p-6">
          <div className="ledger-skeleton h-4 w-32 rounded" />
          <div className="ledger-skeleton h-10 w-24 rounded-md" />
          <div className="ledger-skeleton h-3.5 w-44 rounded" />
        </div>
      </div>
      <div className="ledger-folio flex flex-col gap-4 rounded-2xl p-6">
        <div className="ledger-skeleton h-4 w-48 rounded" />
        <div className="ledger-skeleton h-8 w-full rounded-lg" />
        <div className="ledger-skeleton h-8 w-full rounded-lg" />
        <div className="ledger-skeleton h-8 w-full rounded-lg" />
      </div>
    </div>
  );
}

export default function MetricsPage() {
  const { tenantId } = useTenant();

  const metricsQuery = useQuery({
    queryKey: ["metrics", tenantId],
    queryFn: () => getMetricsSummary(tenantId),
  });

  const data = metricsQuery.data;

  // Derived proportions for Cache Distribution Bar
  const totalQ = data?.total_queries ?? 0;
  const exactHits = data?.exact_cache_hits ?? 0;
  const semanticHits = data?.semantic_cache_hits ?? 0;
  const coldMisses = Math.max(0, totalQ - exactHits - semanticHits);
  const exactPct = totalQ > 0 ? (exactHits / totalQ) * 100 : 0;
  const semanticPct = totalQ > 0 ? (semanticHits / totalQ) * 100 : 0;
  const missPct = totalQ > 0 ? (coldMisses / totalQ) * 100 : 0;

  // Derived latency scale for horizontal comparison chart
  const latencyScaleMax = Math.max(
    100,
    data?.p95_cache_miss_ms ?? 0,
    data?.p95_latency_ms ?? 0,
    data?.p50_latency_ms ?? 0,
    data?.p95_cache_hit_ms ?? 0
  );

  const latencyBars = data
    ? [
        {
          label: "Cache hit p95 (L1 + L2)",
          value: data.p95_cache_hit_ms,
          accent: "bg-status-verified",
          note:
            data.p95_cache_hit_ms !== null && data.p95_cache_hit_ms < 50
              ? "Within 50 ms SLO"
              : "Target < 50 ms",
        },
        {
          label: "Overall median (p50)",
          value: data.p50_latency_ms,
          accent: "bg-status-info",
          note: "All queries combined",
        },
        {
          label: "Overall tail (p95)",
          value: data.p95_latency_ms,
          accent: "bg-ledger-ink-secondary",
          note: "All queries combined",
        },
        {
          label: "Cache miss p95 (full RAG)",
          value: data.p95_cache_miss_ms,
          accent: "bg-status-abstained",
          note: "Embed + RRF + ONNX + LLM",
        },
      ]
    : [];

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-8 sm:py-8">
      {/* Header */}
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-[-0.025em] text-ledger-ink text-balance">
            Observability and unit economics
          </h1>
          <p className="text-sm text-ledger-ink-secondary text-pretty">
            RLS-scoped audit telemetry from{" "}
            <code className="font-mono text-xs text-ledger-ink">query_audit_logs</code> for{" "}
            <span className="font-mono text-ledger-ink">{tenantId}</span>.
          </p>
        </div>

        <button
          type="button"
          onClick={() => metricsQuery.refetch()}
          className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg border border-ledger-hairline bg-ledger-folio px-3 text-xs font-medium text-ledger-ink-secondary transition-colors duration-150 hover:border-ledger-hairline-strong hover:text-ledger-ink active:scale-[0.98]"
        >
          <RefreshCw className={cn("size-3.5", metricsQuery.isFetching && "animate-spin")} />
          <span>Refresh</span>
        </button>
      </header>

      {metricsQuery.isError && (
        <div
          role="alert"
          className="flex items-center gap-2.5 rounded-xl border border-status-fault-border bg-status-fault-tint p-4 text-xs text-status-fault"
        >
          <AlertCircle className="size-4 shrink-0" />
          <span>
            {metricsQuery.error instanceof ApiError
              ? metricsQuery.error.message
              : "Could not load telemetry summary. Verify API status and retry."}
          </span>
        </div>
      )}

      {metricsQuery.isLoading || !data ? (
        <MetricsSkeleton />
      ) : (
        <>
          {/* Asymmetric 2:1 Hero Telemetry Band */}
          <section
            aria-label="Cache efficiency and abstention summary"
            className="grid gap-5 lg:grid-cols-3"
          >
            {/* Primary 2-col: Cache Hit Distribution & LLM Cost Avoidance */}
            <div className="ledger-folio flex flex-col justify-between gap-5 rounded-2xl p-6 lg:col-span-2">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-ledger-ink-tertiary">
                    Semantic cache hit rate
                  </span>
                  <div className="flex items-baseline gap-3">
                    <span className="font-mono text-4xl font-semibold tracking-[-0.03em] tabular-nums text-ledger-ink">
                      {(data.cache_hit_rate * 100).toFixed(1)}%
                    </span>
                    <span className="font-mono text-xs tabular-nums text-status-verified">
                      {exactHits + semanticHits} of {totalQ} resolved without LLM
                    </span>
                  </div>
                </div>

                <div className="flex flex-col items-end gap-0.5">
                  <span className="text-xs text-ledger-ink-tertiary">Total audited queries</span>
                  <span className="font-mono text-lg font-semibold tabular-nums text-ledger-ink">
                    {totalQ}
                  </span>
                </div>
              </div>

              {/* Proportional L1 Exact / L2 Semantic / Cold Miss Bar */}
              <div className="flex flex-col gap-2.5">
                <div
                  aria-label="Query resolution breakdown"
                  className="flex h-2.5 w-full overflow-hidden rounded-full bg-ledger-inset"
                >
                  {exactPct > 0 && (
                    <div
                      className="h-full bg-status-verified"
                      style={{ width: `${exactPct}%` }}
                      title={`L1 Exact: ${exactHits}`}
                    />
                  )}
                  {semanticPct > 0 && (
                    <div
                      className="h-full bg-status-info"
                      style={{ width: `${semanticPct}%` }}
                      title={`L2 Semantic: ${semanticHits}`}
                    />
                  )}
                  {missPct > 0 && (
                    <div
                      className="h-full bg-ledger-hairline-strong"
                      style={{ width: `${missPct}%` }}
                      title={`Cold RAG: ${coldMisses}`}
                    />
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-ledger-ink-secondary">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-2 rounded-full bg-status-verified" />
                    <span className="font-mono tabular-nums">L1 exact: {exactHits}</span>
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-2 rounded-full bg-status-info" />
                    <span className="font-mono tabular-nums">L2 semantic: {semanticHits}</span>
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-2 rounded-full bg-ledger-hairline-strong" />
                    <span className="font-mono tabular-nums">Cold RAG: {coldMisses}</span>
                  </span>
                </div>
              </div>
            </div>

            {/* Secondary 1-col: Safe Abstention & Enclave Integrity */}
            <div className="ledger-folio flex flex-col justify-between gap-5 rounded-2xl p-6">
              <div className="flex flex-col gap-1">
                <span className="text-xs font-medium text-ledger-ink-tertiary">
                  Safe abstention rate
                </span>
                <span className="font-mono text-4xl font-semibold tracking-[-0.03em] tabular-nums text-ledger-ink">
                  {(data.abstention_rate * 100).toFixed(1)}%
                </span>
                <p className="mt-1 text-xs leading-relaxed text-ledger-ink-muted text-pretty">
                  Refusals enforced by Gate-1 reranker confidence floor and Gate-2 deterministic
                  citation verifier.
                </p>
              </div>

              <div className="flex items-center gap-2 border-t border-ledger-hairline pt-3 text-xs text-status-verified">
                <ShieldCheck className="size-4 shrink-0" />
                <span>PostgreSQL RLS active on {data.tenant_id}</span>
              </div>
            </div>
          </section>

          {/* Latency Percentile Comparison Chart + Active Runtime Specification */}
          <div className="grid gap-5 lg:grid-cols-5">
            {/* Horizontal Latency Bars (3 cols) */}
            <section
              aria-label="Latency percentiles"
              className="ledger-folio flex flex-col gap-5 rounded-2xl p-6 lg:col-span-3"
            >
              <div className="flex items-baseline justify-between gap-3">
                <h2 className="text-sm font-semibold tracking-[-0.01em] text-ledger-ink">
                  Latency percentiles
                </h2>
                <span className="font-mono text-[11px] text-ledger-ink-muted">
                  Cache-hit SLO &lt; 50 ms
                </span>
              </div>

              <div className="flex flex-col gap-4">
                {latencyBars.map((bar) => {
                  const pct =
                    bar.value !== null && bar.value > 0
                      ? Math.max(3, Math.min(100, (bar.value / latencyScaleMax) * 100))
                      : 0;
                  return (
                    <div key={bar.label} className="flex flex-col gap-1.5">
                      <div className="flex items-baseline justify-between gap-2 text-xs">
                        <span className="font-medium text-ledger-ink-secondary">{bar.label}</span>
                        <div className="flex items-baseline gap-2.5">
                          <span className="hidden text-[11px] text-ledger-ink-muted sm:inline">
                            {bar.note}
                          </span>
                          <span className="font-mono font-semibold tabular-nums text-ledger-ink">
                            {fmtMs(bar.value)}
                          </span>
                        </div>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-ledger-inset">
                        <div
                          className={cn("h-full rounded-full", bar.accent)}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* Runtime & Isolation Specification Ledger (2 cols) */}
            <section
              aria-label="Active runtime configuration"
              className="ledger-folio flex flex-col gap-4 rounded-2xl p-6 lg:col-span-2"
            >
              <h2 className="text-sm font-semibold tracking-[-0.01em] text-ledger-ink">
                Runtime specification
              </h2>

              <dl className="flex flex-col divide-y divide-ledger-hairline text-xs">
                <div className="flex items-center justify-between gap-3 py-3 first:pt-0">
                  <dt className="text-ledger-ink-tertiary">Primary model</dt>
                  <dd className="font-mono font-medium text-ledger-ink">
                    {data.active_llm_model}
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-3 py-3">
                  <dt className="text-ledger-ink-tertiary">Reranker model</dt>
                  <dd className="truncate font-mono font-medium text-ledger-ink">
                    {data.active_reranker_model}
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-3 py-3">
                  <dt className="text-ledger-ink-tertiary">Memory profile</dt>
                  <dd className="font-mono font-medium text-ledger-ink">
                    {data.reranker_profile}
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-3 py-3">
                  <dt className="text-ledger-ink-tertiary">Tenant isolation</dt>
                  <dd className="font-mono font-medium text-status-verified">
                    Forced RLS + versioned cache
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-3 py-3 last:pb-0">
                  <dt className="text-ledger-ink-tertiary">Active enclave</dt>
                  <dd className="font-mono font-medium text-ledger-ink">{data.tenant_id}</dd>
                </div>
              </dl>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
