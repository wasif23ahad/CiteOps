import fs from "node:fs";
import path from "node:path";

let cachedRootEnv: Record<string, string> | null = null;

function readRootEnvFallback(): Record<string, string> {
  if (cachedRootEnv !== null) {
    return cachedRootEnv;
  }
  const parsed: Record<string, string> = {};
  const candidates = [
    path.resolve(process.cwd(), ".env"),
    path.resolve(process.cwd(), "../../.env"),
  ];

  for (const envPath of candidates) {
    if (!fs.existsSync(envPath)) continue;
    try {
      const content = fs.readFileSync(envPath, "utf8");
      for (const rawLine of content.split(/\r?\n/)) {
        const line = rawLine.trim();
        if (!line || line.startsWith("#")) continue;
        const eqIdx = line.indexOf("=");
        if (eqIdx === -1) continue;
        const key = line.slice(0, eqIdx).trim();
        const val = line.slice(eqIdx + 1).trim().replace(/^["']|["']$/g, "");
        if (key && !(key in parsed)) {
          parsed[key] = val;
        }
      }
    } catch {
      // Ignore unreadable env files in containerized environments
    }
  }

  cachedRootEnv = parsed;
  return parsed;
}

export function getServerConfig(): { apiUrl: string; internalApiKey: string } {
  const fallback = readRootEnvFallback();
  const apiUrl = (
    process.env.CITEOPS_API_URL ||
    fallback.CITEOPS_API_URL ||
    "http://localhost:8000"
  ).replace(/\/+$/, "");

  const internalApiKey =
    process.env.CITEOPS_INTERNAL_API_KEY ||
    fallback.CITEOPS_INTERNAL_API_KEY ||
    "";

  return { apiUrl, internalApiKey };
}
