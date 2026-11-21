"use client";

import { cn } from "@/lib/utils";

interface CitationBadgeProps {
  index: number;
  title?: string;
  active?: boolean;
  onClick: () => void;
}

export function CitationBadge({
  index,
  title,
  active = false,
  onClick,
}: CitationBadgeProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title ? `Inspect source [${index}]: ${title}` : `Inspect source [${index}]`}
      aria-label={`Inspect source ${index}${title ? `: ${title}` : ""}`}
      aria-pressed={active}
      className={cn(
        "mx-0.5 inline-flex h-[19px] min-w-[21px] -translate-y-[1px] cursor-pointer items-center justify-center rounded px-1 align-baseline font-mono text-[11px] font-semibold tabular-nums transition-colors duration-150 active:scale-[0.95]",
        active
          ? "bg-ledger-accent text-ledger-accent-ink"
          : "border border-ledger-accent-border bg-ledger-accent-tint text-ledger-accent hover:bg-ledger-accent hover:text-ledger-accent-ink"
      )}
    >
      {index}
    </button>
  );
}
