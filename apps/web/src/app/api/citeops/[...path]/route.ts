import { NextRequest, NextResponse } from "next/server";

import { getServerConfig } from "@/lib/server-env";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const UPSTREAM_TIMEOUT_MS = 45_000;
const MAX_JSON_BODY_BYTES = 128 * 1024; // 128 KB
const MAX_INGEST_BODY_BYTES = 26 * 1024 * 1024; // 26 MB (25 MB file + multipart overhead)

const UUID_SEGMENT_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isAllowedUpstreamRoute(method: string, segments: string[]): boolean {
  if (
    segments.length === 0 ||
    segments.some((seg) => !seg || seg === "." || seg === ".." || /[\\/?#@]/.test(seg))
  ) {
    return false;
  }

  const joined = segments.join("/");
  if (method === "GET") {
    return (
      joined === "v1/health" ||
      joined === "v1/documents" ||
      joined === "v1/metrics/summary"
    );
  }
  if (method === "POST") {
    return joined === "v1/query" || joined === "v1/ingest";
  }
  if (method === "DELETE") {
    return (
      segments.length === 3 &&
      segments[0] === "v1" &&
      segments[1] === "documents" &&
      UUID_SEGMENT_RE.test(segments[2])
    );
  }
  return false;
}

async function proxyRequest(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  const { path: pathSegments } = await context.params;
  if (!isAllowedUpstreamRoute(request.method, pathSegments)) {
    return NextResponse.json(
      { detail: "Route not permitted on CiteOps BFF proxy." },
      { status: 404 }
    );
  }

  const { apiUrl, internalApiKey } = getServerConfig();
  const upstreamPath = pathSegments.map(encodeURIComponent).join("/");
  const search = request.nextUrl.search;
  const targetUrl = `${apiUrl}/${upstreamPath}${search}`;

  const isIngest = pathSegments.join("/") === "v1/ingest";
  const maxBytes = isIngest ? MAX_INGEST_BODY_BYTES : MAX_JSON_BODY_BYTES;

  const contentLengthHeader = request.headers.get("content-length");
  if (contentLengthHeader) {
    const declaredLength = Number.parseInt(contentLengthHeader, 10);
    if (Number.isFinite(declaredLength) && declaredLength > maxBytes) {
      return NextResponse.json(
        { detail: "Request payload exceeds maximum permitted size." },
        { status: 413 }
      );
    }
  }

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) {
    headers.set("content-type", contentType);
  }
  const reqId = request.headers.get("x-request-id");
  if (reqId) {
    headers.set("x-request-id", reqId);
  }
  if (internalApiKey) {
    headers.set("X-Internal-API-Key", internalApiKey);
  }

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  let body: ArrayBuffer | undefined;
  if (hasBody) {
    body = await request.arrayBuffer();
    if (body.byteLength > maxBytes) {
      return NextResponse.json(
        { detail: "Request payload exceeds maximum permitted size." },
        { status: 413 }
      );
    }
  }

  try {
    const upstream = await fetch(targetUrl, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });

    const responseBuffer = await upstream.arrayBuffer();
    const outHeaders = new Headers();
    const respType = upstream.headers.get("content-type");
    if (respType) outHeaders.set("content-type", respType);
    const respReqId = upstream.headers.get("x-request-id");
    if (respReqId) outHeaders.set("x-request-id", respReqId);
    const retryAfter = upstream.headers.get("retry-after");
    if (retryAfter) outHeaders.set("retry-after", retryAfter);

    return new NextResponse(responseBuffer, {
      status: upstream.status,
      headers: outHeaders,
    });
  } catch (err) {
    console.error("[citeops-bff] upstream request failed", {
      method: request.method,
      path: upstreamPath,
      error: err instanceof Error ? err.message : String(err),
    });
    return NextResponse.json(
      { detail: "CiteOps API backend is temporarily unreachable." },
      { status: 502 }
    );
  }
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  return proxyRequest(request, context);
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  return proxyRequest(request, context);
}

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  return proxyRequest(request, context);
}
