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
      title={title ? `[${index}] ${title}` : `Inspect citation [${index}]`}
      aria-label={`Inspect citation ${index}${title ? `: ${title}` : ""}`}
      className={cn(
        "mx-0.5 inline-flex h-5 min-w-5 cursor-pointer items-center justify-center rounded px-1.5 align-baseline font-mono text-[11px] font-semibold transition-all",
        active
          ? "bg-primary text-primary-foreground ring-2 ring-primary/30"
          : "border border-border bg-accent text-accent-foreground hover:bg-primary hover:text-primary-foreground"
      )}
    >
      {index}
    </button>
  );
}
