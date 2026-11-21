"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Check,
  ChevronsUpDown,
  FileText,
  Lock,
  Moon,
  Search,
  Sun,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { getHealth } from "@/lib/api";
import { TENANT_PRESETS, useTenant } from "@/lib/tenant-context";
import { useTheme } from "@/lib/theme-context";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Workspace", icon: Search },
  { href: "/documents", label: "Knowledge Base", icon: FileText },
  { href: "/metrics", label: "Telemetry", icon: Activity },
];

function CiteOpsMark() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className="shrink-0"
    >
      <rect
        x="2"
        y="2"
        width="20"
        height="20"
        rx="5"
        className="fill-ledger-accent-tint stroke-ledger-accent-border"
        strokeWidth="1.25"
      />
      <path
        d="M8.5 7.5H6.5V16.5H8.5M15.5 7.5H17.5V16.5H15.5"
        className="stroke-ledger-accent"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="2" className="fill-ledger-accent" />
    </svg>
  );
}

function TenantVaultSwitcher() {
  const { tenantId, setTenantId } = useTenant();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const activePreset =
    TENANT_PRESETS.find((t) => t.id === tenantId) ?? TENANT_PRESETS[0];

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label="Switch isolated tenant vault"
        className="flex w-full cursor-pointer items-center justify-between gap-2 rounded-lg border border-ledger-hairline bg-ledger-inset px-2.5 py-2 text-left transition-colors duration-150 hover:border-ledger-hairline-strong active:scale-[0.99]"
      >
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-ledger-accent-tint text-ledger-accent">
            <Lock className="size-3.5" />
          </span>
          <div className="min-w-0">
            <p className="truncate font-mono text-xs font-medium text-ledger-ink">
              {activePreset.id}
            </p>
            <p className="truncate text-[11px] text-ledger-ink-tertiary">
              {activePreset.tier}
            </p>
          </div>
        </div>
        <ChevronsUpDown className="size-3.5 shrink-0 text-ledger-ink-muted" />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label="Tenant workspaces"
          className="ledger-overlay animate-ledger-enter absolute left-0 right-0 top-[calc(100%+6px)] z-50 flex flex-col gap-0.5 rounded-xl p-1.5"
        >
          <div className="px-2 py-1 text-[11px] font-medium text-ledger-ink-muted">
            Isolated RLS vaults
          </div>
          {TENANT_PRESETS.map((preset) => {
            const selected = preset.id === tenantId;
            return (
              <button
                key={preset.id}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => {
                  setTenantId(preset.id);
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full cursor-pointer items-center justify-between gap-2 rounded-lg px-2 py-2 text-left transition-colors duration-150",
                  selected
                    ? "bg-ledger-accent-tint text-ledger-ink"
                    : "text-ledger-ink-secondary hover:bg-ledger-hairline-subtle hover:text-ledger-ink"
                )}
              >
                <div className="min-w-0">
                  <p className="truncate font-mono text-xs font-medium">
                    {preset.id}
                  </p>
                  <p className="truncate text-[11px] text-ledger-ink-tertiary">
                    {preset.label} ({preset.tier})
                  </p>
                </div>
                {selected && <Check className="size-3.5 shrink-0 text-ledger-accent" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30_000,
  });

  const healthStatus = healthQuery.data?.status;
  const pgDetail = healthQuery.data?.dependencies?.postgres?.detail;
  const rerankerProfile = healthQuery.data?.reranker_profile;

  const statusLabel =
    healthStatus === "ok"
      ? "RLS & cache ready"
      : healthStatus === "degraded"
        ? "Cache degraded"
        : healthStatus === "unhealthy"
          ? "Backend offline"
          : "Checking stack";

  return (
    <div className="flex min-h-screen flex-col bg-ledger-canvas text-ledger-ink lg:flex-row">
      {/* Desktop Persistent Navigation Rail (same neutral canvas family, hairline border) */}
      <aside className="hidden w-[236px] shrink-0 flex-col border-r border-ledger-hairline bg-ledger-rail lg:sticky lg:top-0 lg:flex lg:h-screen">
        {/* Brand Header */}
        <div className="flex h-14 items-center justify-between px-4">
          <Link
            href="/"
            className="flex items-center gap-2.5 text-[15px] font-semibold tracking-[-0.02em] text-ledger-ink"
          >
            <CiteOpsMark />
            <span>CiteOps</span>
          </Link>
          <span className="rounded border border-ledger-hairline px-1.5 py-0.5 font-mono text-[10px] font-medium text-ledger-ink-muted">
            v0.1
          </span>
        </div>

        {/* Isolated Tenant Vault Selector */}
        <div className="px-3 pb-3">
          <TenantVaultSwitcher />
        </div>

        {/* Primary Navigation */}
        <nav
          aria-label="Primary navigation"
          className="flex flex-1 flex-col gap-1 px-3 py-1"
        >
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-colors duration-150",
                  active
                    ? "bg-ledger-accent-tint text-ledger-ink"
                    : "text-ledger-ink-secondary hover:bg-ledger-hairline-subtle hover:text-ledger-ink"
                )}
              >
                <Icon
                  className={cn(
                    "size-4 shrink-0",
                    active ? "text-ledger-accent" : "text-ledger-ink-muted"
                  )}
                />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* Footer: System Health & Theme Toggle */}
        <div className="flex flex-col gap-2.5 border-t border-ledger-hairline px-3 py-3">
          <div
            className="flex items-center justify-between gap-2 rounded-lg bg-ledger-inset px-2.5 py-2"
            title={
              pgDetail
                ? `PostgreSQL ${pgDetail} with forced tenant RLS`
                : "Stack health status"
            }
          >
            <div className="flex min-w-0 items-center gap-2">
              <span
                className={cn(
                  "size-2 shrink-0 rounded-full",
                  healthStatus === "ok" && "bg-status-verified",
                  healthStatus === "degraded" && "bg-status-abstained",
                  healthStatus === "unhealthy" && "bg-status-fault",
                  !healthStatus && "bg-ledger-ink-muted"
                )}
              />
              <span className="truncate text-[11px] font-medium text-ledger-ink-secondary">
                {statusLabel}
              </span>
            </div>
            {rerankerProfile && (
              <span className="shrink-0 font-mono text-[10px] text-ledger-ink-muted">
                {rerankerProfile}
              </span>
            )}
          </div>

          <button
            type="button"
            onClick={toggleTheme}
            aria-label={
              theme === "dark" ? "Switch to light archival theme" : "Switch to dark ledger theme"
            }
            className="flex w-full cursor-pointer items-center justify-between rounded-lg px-2.5 py-1.5 text-xs font-medium text-ledger-ink-secondary transition-colors duration-150 hover:bg-ledger-hairline-subtle hover:text-ledger-ink"
          >
            <span className="flex items-center gap-2">
              {theme === "dark" ? (
                <Sun className="size-3.5 text-ledger-ink-muted" />
              ) : (
                <Moon className="size-3.5 text-ledger-ink-muted" />
              )}
              <span>{theme === "dark" ? "Light surface" : "Dark surface"}</span>
            </span>
            <span className="font-mono text-[10px] text-ledger-ink-muted">
              {theme === "dark" ? "Obsidian" : "Vellum"}
            </span>
          </button>
        </div>
      </aside>

      {/* Mobile / Tablet Compact Header */}
      <header className="sticky top-0 z-30 flex flex-col gap-2.5 border-b border-ledger-hairline bg-ledger-rail px-4 py-3 lg:hidden">
        <div className="flex items-center justify-between gap-3">
          <Link
            href="/"
            className="flex items-center gap-2 text-sm font-semibold tracking-[-0.02em] text-ledger-ink"
          >
            <CiteOpsMark />
            <span>CiteOps</span>
          </Link>

          <div className="flex items-center gap-2">
            <span
              title={statusLabel}
              className="flex items-center gap-1.5 rounded-full border border-ledger-hairline bg-ledger-inset px-2 py-1 text-[11px] text-ledger-ink-secondary"
            >
              <span
                className={cn(
                  "size-1.5 rounded-full",
                  healthStatus === "ok" && "bg-status-verified",
                  healthStatus === "degraded" && "bg-status-abstained",
                  healthStatus === "unhealthy" && "bg-status-fault",
                  !healthStatus && "bg-ledger-ink-muted"
                )}
              />
              <span className="hidden sm:inline">{statusLabel}</span>
            </span>

            <div className="w-40">
              <TenantVaultSwitcher />
            </div>

            <button
              type="button"
              onClick={toggleTheme}
              aria-label="Toggle color theme"
              className="flex size-9 cursor-pointer items-center justify-center rounded-lg border border-ledger-hairline bg-ledger-inset text-ledger-ink-secondary transition-colors hover:text-ledger-ink"
            >
              {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </button>
          </div>
        </div>

        <nav aria-label="Mobile navigation" className="flex items-center gap-1">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors duration-150",
                  active
                    ? "bg-ledger-accent-tint text-ledger-ink"
                    : "text-ledger-ink-secondary hover:bg-ledger-hairline-subtle"
                )}
              >
                <Icon
                  className={cn(
                    "size-3.5",
                    active ? "text-ledger-accent" : "text-ledger-ink-muted"
                  )}
                />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </header>

      {/* Main Content Surface */}
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
