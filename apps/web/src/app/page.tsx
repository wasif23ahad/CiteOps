"use client";

import { useMutation } from "@tanstack/react-query";
import { AlertCircle, BookOpen, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";

import { AnswerCard } from "@/components/answer-card";
import { QueryBox } from "@/components/query-box";
import { DockedEvidenceRail, SourceDrawer } from "@/components/source-drawer";
import { ApiError, queryKnowledgeBase } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import type { CitationItem, DocType, QueryResponse } from "@/lib/types";

interface ThreadItem {
  id: string;
  tenantId: string;
  query: string;
  docTypes: DocType[] | null;
  response: QueryResponse;
}

function SearchingSkeleton({ tenantId }: { tenantId: string }) {
  return (
    <div
      aria-live="polite"
      aria-label="Searching and verifying sources"
      className="ledger-folio animate-ledger-enter flex flex-col gap-4 rounded-2xl p-5 sm:p-6"
    >
      <div className="flex items-center justify-between gap-4">
        <div className="ledger-skeleton h-5 w-2/3 rounded-md" />
        <span className="font-mono text-[11px] text-ledger-ink-muted">
          Searching {tenantId}
        </span>
      </div>
      <div className="flex flex-col gap-2.5">
        <div className="ledger-skeleton h-3.5 w-full rounded" />
        <div className="ledger-skeleton h-3.5 w-11/12 rounded" />
        <div className="ledger-skeleton h-3.5 w-3/4 rounded" />
      </div>
      <div className="grid gap-2 pt-1 sm:grid-cols-2">
        <div className="ledger-skeleton h-14 rounded-xl" />
        <div className="ledger-skeleton h-14 rounded-xl" />
      </div>
    </div>
  );
}

export default function WorkspacePage() {
  const { tenantId } = useTenant();
  const [queryInput, setQueryInput] = useState("");
  const [selectedDocTypes, setSelectedDocTypes] = useState<DocType[]>([]);
  const [threadsByTenant, setThreadsByTenant] = useState<Record<string, ThreadItem[]>>({});

  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [activeCitations, setActiveCitations] = useState<CitationItem[]>([]);
  const [activeCitationIndex, setActiveCitationIndex] = useState<number | null>(null);

  const tenantThreads = threadsByTenant[tenantId] ?? [];

  const queryMutation = useMutation({
    mutationFn: queryKnowledgeBase,
    onSuccess: (data, variables) => {
      const id = data.telemetry.trace_id || `${Date.now()}`;
      const item: ThreadItem = {
        id,
        tenantId: variables.tenant_id,
        query: variables.query,
        docTypes: variables.doc_types ?? null,
        response: data,
      };
      setThreadsByTenant((prev) => ({
        ...prev,
        [variables.tenant_id]: [item, ...(prev[variables.tenant_id] ?? [])],
      }));
      setActiveThreadId(id);
      if (data.citations.length > 0) {
        setActiveCitations(data.citations);
        setActiveCitationIndex(data.citations[0].citation_index);
      } else {
        setActiveCitations([]);
        setActiveCitationIndex(null);
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

  const handleRetryAllCategories = (queryText: string) => {
    setSelectedDocTypes([]);
    setQueryInput(queryText);
    handleSubmit(queryText, []);
  };

  const handleInspectCitation = (
    threadId: string,
    citations: CitationItem[],
    index: number
  ) => {
    setActiveThreadId(threadId);
    setActiveCitations(citations);
    setActiveCitationIndex(index);
    setMobileDrawerOpen(true);
  };

  const clearTenantHistory = () => {
    setThreadsByTenant((prev) => ({ ...prev, [tenantId]: [] }));
    setMobileDrawerOpen(false);
    setActiveThreadId(null);
    setActiveCitations([]);
    setActiveCitationIndex(null);
  };

  // Sync displayed desktop rail citations with active tenant's current briefing
  const currentTenantHasActive = tenantThreads.some((t) => t.id === activeThreadId);
  const railCitations = currentTenantHasActive
    ? activeCitations
    : (tenantThreads[0]?.response.citations ?? []);
  const railActiveIndex = currentTenantHasActive
    ? activeCitationIndex
    : (railCitations[0]?.citation_index ?? null);
  const effectiveActiveThreadId = currentTenantHasActive
    ? activeThreadId
    : (tenantThreads[0]?.id ?? null);

  return (
    <div className="flex min-h-full w-full">
      {/* Primary Briefing Column */}
      <div className="min-w-0 flex-1 px-4 py-6 sm:px-8 sm:py-8">
        <div className="mx-auto flex max-w-[760px] flex-col gap-6">
          {/* Page Header (direct heading, no decorative eyebrow pill) */}
          <header className="flex flex-wrap items-end justify-between gap-4">
            <div className="flex flex-col gap-1">
              <h1 className="text-2xl font-semibold tracking-[-0.025em] text-ledger-ink text-balance">
                Evidence workspace
              </h1>
              <p className="text-sm text-ledger-ink-secondary text-pretty">
                Query <span className="font-mono text-ledger-ink">{tenantId}</span> documentation
                with verified inline citations and dual-gate abstention.
              </p>
            </div>

            <div className="flex items-center gap-2">
              {railCitations.length > 0 && (
                <button
                  type="button"
                  onClick={() => setMobileDrawerOpen(true)}
                  className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-ledger-hairline bg-ledger-folio px-2.5 text-xs font-medium text-ledger-ink-secondary transition-colors duration-150 hover:border-ledger-hairline-strong hover:text-ledger-ink xl:hidden"
                >
                  <BookOpen className="size-3.5 text-ledger-accent" />
                  <span>Sources ({railCitations.length})</span>
                </button>
              )}

              {tenantThreads.length > 0 && (
                <button
                  type="button"
                  onClick={clearTenantHistory}
                  className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-ledger-hairline bg-ledger-folio px-2.5 text-xs font-medium text-ledger-ink-secondary transition-colors duration-150 hover:border-ledger-hairline-strong hover:text-ledger-ink active:scale-[0.98]"
                >
                  <Trash2 className="size-3.5" />
                  <span>Clear thread</span>
                </button>
              )}
            </div>
          </header>

          {/* Focal Composer */}
          <QueryBox
            tenantId={tenantId}
            query={queryInput}
            onQueryChange={setQueryInput}
            selectedDocTypes={selectedDocTypes}
            onToggleDocType={handleToggleDocType}
            isLoading={queryMutation.isPending}
            onSubmit={handleSubmit}
          />

          {/* API / Rate-Limit Error Alert */}
          {queryMutation.isError && (
            <div
              role="alert"
              className="animate-ledger-enter flex items-start gap-3 rounded-xl border border-status-fault-border bg-status-fault-tint p-4 text-sm"
            >
              <AlertCircle className="mt-0.5 size-4 shrink-0 text-status-fault" />
              <div className="flex flex-col gap-1">
                <p className="font-semibold text-ledger-ink">
                  {queryMutation.error instanceof ApiError &&
                  queryMutation.error.status === 429
                    ? "Rate limit reached (HTTP 429)"
                    : "Query could not complete"}
                </p>
                <p className="text-xs leading-relaxed text-ledger-ink-secondary">
                  {queryMutation.error instanceof ApiError
                    ? `${queryMutation.error.message}${
                        queryMutation.error.retryAfter
                          ? ` Wait ${queryMutation.error.retryAfter} seconds and retry.`
                          : ""
                      }`
                    : "Check that the CiteOps API and PostgreSQL database are reachable, then retry."}
                </p>
              </div>
            </div>
          )}

          {/* Pending Skeleton State */}
          {queryMutation.isPending && <SearchingSkeleton tenantId={tenantId} />}

          {/* Results Stream or Intentional Empty State */}
          {tenantThreads.length === 0 && !queryMutation.isPending ? (
            <div className="flex flex-col items-start gap-3 rounded-2xl border border-dashed border-ledger-hairline-strong bg-ledger-rail/60 p-6 sm:p-8">
              <div className="flex items-center gap-2 text-xs font-medium text-ledger-ink-secondary">
                <ShieldCheck className="size-4 text-ledger-accent" />
                <span>
                  Enclave locked to <span className="font-mono text-ledger-ink">{tenantId}</span>
                </span>
              </div>
              <p className="max-w-[58ch] text-sm leading-relaxed text-ledger-ink-secondary text-pretty">
                Choose a scenario above or enter a compliance, SLA, or error-code query. Every
                claim is cross-checked against retrieved pages, and unsupported questions abstain
                rather than fabricate citations.
              </p>
              <div className="flex flex-wrap gap-x-6 gap-y-1.5 pt-1 text-xs text-ledger-ink-muted">
                <span>Hybrid pgvector + tsvector RRF</span>
                <span>ONNX cross-encoder gate</span>
                <span>L1/L2 versioned Redis cache</span>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-5">
              {tenantThreads.map((item) => (
                <AnswerCard
                  key={item.id}
                  query={item.query}
                  appliedDocTypes={item.docTypes}
                  response={item.response}
                  isActiveBriefing={effectiveActiveThreadId === item.id}
                  activeCitationIndex={
                    effectiveActiveThreadId === item.id ? railActiveIndex : null
                  }
                  onInspectCitation={(citations, idx) =>
                    handleInspectCitation(item.id, citations, idx)
                  }
                  onRetryAllCategories={handleRetryAllCategories}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Desktop Docked Evidence Inspector Rail (`xl+`) */}
      <DockedEvidenceRail
        citations={railCitations}
        activeIndex={railActiveIndex}
        onSelect={setActiveCitationIndex}
      />

      {/* Mobile & Tablet Slide-Over Evidence Sheet (`< xl`) */}
      <SourceDrawer
        open={mobileDrawerOpen}
        citations={railCitations}
        activeIndex={railActiveIndex}
        onSelect={setActiveCitationIndex}
        onClose={() => setMobileDrawerOpen(false)}
      />
    </div>
  );
}
