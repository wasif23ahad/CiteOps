"use client";

import { useMutation } from "@tanstack/react-query";
import { AlertCircle, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";

import { AnswerCard } from "@/components/answer-card";
import { QueryBox } from "@/components/query-box";
import { SourceDrawer } from "@/components/source-drawer";
import { ApiError, queryKnowledgeBase } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import type { CitationItem, DocType, QueryResponse } from "@/lib/types";

interface ThreadItem {
  id: string;
  tenantId: string;
  query: string;
  response: QueryResponse;
}

export default function WorkspacePage() {
  const { tenantId } = useTenant();
  const [queryInput, setQueryInput] = useState("");
  const [selectedDocTypes, setSelectedDocTypes] = useState<DocType[]>([]);
  const [threadsByTenant, setThreadsByTenant] = useState<Record<string, ThreadItem[]>>({});

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerCitations, setDrawerCitations] = useState<CitationItem[]>([]);
  const [activeCitationIndex, setActiveCitationIndex] = useState<number | null>(null);

  const tenantThreads = threadsByTenant[tenantId] ?? [];

  const queryMutation = useMutation({
    mutationFn: queryKnowledgeBase,
    onSuccess: (data, variables) => {
      const item: ThreadItem = {
        id: data.telemetry.trace_id || `${Date.now()}`,
        tenantId: variables.tenant_id,
        query: variables.query,
        response: data,
      };
      setThreadsByTenant((prev) => ({
        ...prev,
        [variables.tenant_id]: [item, ...(prev[variables.tenant_id] ?? [])],
      }));
      if (data.citations.length > 0) {
        setDrawerCitations(data.citations);
        setActiveCitationIndex(data.citations[0].citation_index);
      }
    },
  });

  const handleToggleDocType = (docType: DocType | null) => {
    if (docType === null) {
      setSelectedDocTypes([]);
      return;
    }
    setSelectedDocTypes((prev) =>
      prev.includes(docType) ? prev.filter((item) => item !== docType) : [...prev, docType]
    );
  };

  const handleSubmit = (overrideQuery?: string, overrideDocTypes?: DocType[]) => {
    const text = (overrideQuery ?? queryInput).trim();
    if (text.length < 3) return;
    const effectiveDocTypes = overrideDocTypes ?? selectedDocTypes;
    queryMutation.mutate({
      tenant_id: tenantId,
      query: text,
      doc_types: effectiveDocTypes.length > 0 ? effectiveDocTypes : null,
      top_k: 5,
    });
  };

  const handleInspectCitation = (citations: CitationItem[], index: number) => {
    setDrawerCitations(citations);
    setActiveCitationIndex(index);
    setDrawerOpen(true);
  };

  const clearTenantHistory = () => {
    setThreadsByTenant((prev) => ({ ...prev, [tenantId]: [] }));
    setDrawerOpen(false);
    setDrawerCitations([]);
    setActiveCitationIndex(null);
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* Header Intro */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5 text-primary" />
            <span>
              PostgreSQL RLS Workspace: <strong className="font-mono text-foreground">{tenantId}</strong>
            </span>
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
            Citation-Locked Support & Compliance Search
          </h1>
          <p className="mt-1 text-xs text-muted-foreground sm:text-sm">
            Hybrid dense + lexical retrieval with calibrated ONNX reranking, verified inline
            citations, and strict dual-gate abstention.
          </p>
        </div>

        {tenantThreads.length > 0 && (
          <button
            type="button"
            onClick={clearTenantHistory}
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Clear Thread
          </button>
        )}
      </div>

      {/* Query Composer & Filters */}
      <QueryBox
        tenantId={tenantId}
        query={queryInput}
        onQueryChange={setQueryInput}
        selectedDocTypes={selectedDocTypes}
        onToggleDocType={handleToggleDocType}
        isLoading={queryMutation.isPending}
        onSubmit={handleSubmit}
      />

      {/* API / Rate-Limit Error Banner */}
      {queryMutation.isError && (
        <div className="flex items-start gap-2.5 rounded-xl border border-rose-500/35 bg-rose-500/10 p-4 text-sm text-rose-700 dark:text-rose-300">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-semibold">
              {queryMutation.error instanceof ApiError && queryMutation.error.status === 429
                ? "Rate Limit Reached (HTTP 429)"
                : "Query Failed"}
            </p>
            <p className="mt-0.5 text-xs">
              {queryMutation.error instanceof ApiError
                ? `${queryMutation.error.message}${
                    queryMutation.error.retryAfter
                      ? ` (Retry after ${queryMutation.error.retryAfter}s)`
                      : ""
                  }`
                : "Unable to complete query. Verify the CiteOps API is running."}
            </p>
          </div>
        </div>
      )}

      {/* Results Stream */}
      {tenantThreads.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-card/50 p-10 text-center">
          <p className="text-sm font-medium text-foreground">
            Ready to query <span className="font-mono">{tenantId}</span>
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Click one of the sample RFP or Tier-2 incident prompts above, or enter your own
            question. Repeat queries resolve from Redis cache in milliseconds.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {tenantThreads.map((item) => (
            <AnswerCard
              key={item.id}
              query={item.query}
              response={item.response}
              activeCitationIndex={drawerOpen ? activeCitationIndex : null}
              onInspectCitation={handleInspectCitation}
            />
          ))}
        </div>
      )}

      {/* Source Inspector Drawer */}
      <SourceDrawer
        open={drawerOpen}
        citations={drawerCitations}
        activeIndex={activeCitationIndex}
        onSelect={setActiveCitationIndex}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
