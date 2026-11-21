import { ShieldCheck } from "lucide-react";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col items-center justify-center px-6 py-16 text-center">
      <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-card px-3.5 py-1.5 text-xs font-medium text-muted-foreground">
        <ShieldCheck className="h-4 w-4 text-primary" />
        <span>Phase 0 Scaffold Ready</span>
      </div>
      <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
        CiteOps Knowledge Engine
      </h1>
      <p className="mt-3 max-w-xl text-sm text-muted-foreground sm:text-base">
        Multi-tenant Tier-2 support and security compliance workspace powered by PostgreSQL
        pgvector hybrid retrieval, calibrated ONNX reranking, and citation-locked grounding.
      </p>
    </main>
  );
}
