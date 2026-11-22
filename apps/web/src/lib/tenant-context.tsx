"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

export interface TenantPreset {
  id: string;
  label: string;
  tier: string;
}

export const TENANT_PRESETS: TenantPreset[] = [
  { id: "acme-corp", label: "acme-corp", tier: "CloudPulse Enterprise" },
  { id: "globex-io", label: "globex-io", tier: "Sovereign Enclave" },
];

interface TenantContextValue {
  tenantId: string;
  setTenantId: (tenant: string) => void;
}

const TenantContext = createContext<TenantContextValue | null>(null);

export function TenantProvider({ children }: { children: ReactNode }) {
  const [tenantId, setTenantId] = useState<string>("acme-corp");

  return (
    <TenantContext.Provider value={{ tenantId, setTenantId }}>
      {children}
    </TenantContext.Provider>
  );
}

export function useTenant(): TenantContextValue {
  const ctx = useContext(TenantContext);
  if (!ctx) {
    throw new Error("useTenant must be used inside TenantProvider");
  }
  return ctx;
}
