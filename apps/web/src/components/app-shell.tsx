"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Building2,
  Database,
  FileText,
  Search,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { getHealth } from "@/lib/api";
import { TENANT_PRESETS, useTenant } from "@/lib/tenant-context";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Workspace", icon: Search },
  { href: "/documents", label: "Knowledge Base", icon: FileText },
  { href: "/metrics", label: "Metrics", icon: Activity },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { tenantId, setTenantId } = useTenant();

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30_000,
  });

  const healthStatus = healthQuery.data?.status;

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-border bg-card/85 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
          {/* Brand + Navigation */}
          <div className="flex items-center gap-6">
            <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
              <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
                <ShieldCheck className="h-4 w-4" />
              </span>
              <span className="text-sm sm:text-base">CiteOps</span>
            </Link>

            <nav className="flex items-center gap-1" aria-label="Primary Navigation">
              {NAV_ITEMS.map((item) => {
                const Icon = item.icon;
                const active = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors sm:text-sm",
                      active
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </nav>
          </div>

          {/* Right controls: Tenant Workspace Selector + Health Pill */}
          <div className="flex items-center gap-3">
            <div className="hidden items-center gap-1.5 rounded-full border border-border bg-muted/60 px-2.5 py-1 text-[11px] font-medium text-muted-foreground md:inline-flex">
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  healthStatus === "ok" && "bg-emerald-500",
                  healthStatus === "degraded" && "bg-amber-500",
                  healthStatus === "unhealthy" && "bg-rose-500",
                  !healthStatus && "bg-zinc-400"
                )}
              />
              <Database className="h-3 w-3" />
              <span>
                {healthStatus === "ok"
                  ? "RLS + Redis Online"
                  : healthStatus === "degraded"
                    ? "Cache Degraded"
                    : healthStatus === "unhealthy"
                      ? "API Unhealthy"
                      : "Checking..."}
              </span>
            </div>

            <label className="flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-xs">
              <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="sr-only">Tenant Workspace</span>
              <select
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                aria-label="Select tenant workspace"
                className="cursor-pointer bg-transparent font-mono text-xs font-medium text-foreground focus:outline-none"
              >
                {TENANT_PRESETS.map((t) => (
                  <option key={t.id} value={t.id} className="bg-card text-foreground">
                    {t.label} ({t.tier})
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">{children}</main>
    </div>
  );
}
