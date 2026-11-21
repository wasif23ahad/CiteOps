import { NextRequest, NextResponse } from "next/server";

import { getServerConfig } from "@/lib/server-env";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function proxyRequest(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  const { path: pathSegments } = await context.params;
  const { apiUrl, internalApiKey } = getServerConfig();

  const upstreamPath = pathSegments.join("/");
  const search = request.nextUrl.search;
  const targetUrl = `${apiUrl}/${upstreamPath}${search}`;

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
  const body = hasBody ? await request.arrayBuffer() : undefined;

  try {
    const upstream = await fetch(targetUrl, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
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
    const message =
      err instanceof Error ? err.message : "Unable to reach CiteOps API backend.";
    return NextResponse.json(
      { detail: `Backend proxy error: ${message}` },
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
