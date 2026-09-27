// Same-origin transport to the product API. It attaches the session credential
// from the HttpOnly cookie, forwards only allowlisted routes and never
// interprets business data: authorization happens in the API.
import { NextResponse } from "next/server";

import { apiBase, devLoginEnabled, sameOrigin, sessionToken } from "../../../../lib/session.ts";

const ID = "[A-Za-z0-9][A-Za-z0-9._:-]{0,127}";
const ROUTES: ReadonlyArray<[string, RegExp]> = [
  ["GET", /^me$/],
  ["POST", /^me\/permissions$/],
  ["GET", new RegExp(`^me/permissions/${ID}$`)],
  ["POST", /^me\/logout-everywhere$/],
  ["DELETE", /^me$/],
  ["POST", /^uploads$/],
  ["POST", new RegExp(`^uploads/${ID}/complete$`)],
  ["POST", /^analyses$/],
  ["GET", new RegExp(`^analyses/${ID}$`)],
  ["POST", new RegExp(`^analyses/${ID}/cancel$`)],
  ["DELETE", new RegExp(`^captures/${ID}$`)],
  ["GET", new RegExp(`^reports/${ID}$`)],
  ["POST", /^report-exports$/],
  ["GET", new RegExp(`^report-exports/${ID}$`)],
  ["GET", new RegExp(`^report-exports/${ID}/file$`)],
];
// The local filesystem store's signed PUT (stands in for a provider's presigned URL).
const DEV_UPLOAD = new RegExp(`^dev/uploads/${ID}$`);
const MAX_JSON_BYTES = 64 * 1024;
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

/** Reads at most `limit` bytes: a larger declared length is refused before
 * reading, and the stream is cut off as soon as it passes the limit. */
async function readLimited(request: Request, limit: number): Promise<Uint8Array<ArrayBuffer> | null> {
  const declared = request.headers.get("content-length");
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > limit)) return null;
  if (!request.body) return new Uint8Array(new ArrayBuffer(0));
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(new ArrayBuffer(size));
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out;
}

async function forward(request: Request, params: Promise<{ path: string[] }>): Promise<Response> {
  const path = (await params).path.join("/");
  const method = request.method.toUpperCase();
  const devUpload = method === "PUT" && DEV_UPLOAD.test(path) && devLoginEnabled();
  if (!devUpload && !ROUTES.some(([m, pattern]) => m === method && pattern.test(path))) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  if (method !== "GET" && !sameOrigin(request)) {
    return NextResponse.json({ error: "cross_origin" }, { status: 403 });
  }
  const url = new URL(request.url);
  const target = `${apiBase()}/v1/${path}${url.search}`;
  const headers: Record<string, string> = { accept: "application/json" };
  const correlation = request.headers.get("x-correlation-id");
  if (correlation) headers["x-correlation-id"] = correlation.slice(0, 64);
  let body: BodyInit | undefined;
  if (devUpload) {
    const bytes = await readLimited(request, MAX_UPLOAD_BYTES);
    if (bytes === null) return NextResponse.json({ error: "upload_too_large" }, { status: 413 });
    headers["content-type"] = request.headers.get("content-type") ?? "application/octet-stream";
    body = bytes;
  } else {
    const token = await sessionToken();
    if (token) headers.authorization = `Bearer ${token}`;
    if (method === "POST" || method === "PUT") {
      const bytes = await readLimited(request, MAX_JSON_BYTES);
      if (bytes === null) return NextResponse.json({ error: "payload_too_large" }, { status: 413 });
      if (bytes.byteLength) {
        headers["content-type"] = "application/json";
        body = bytes;
      }
    }
  }
  const upstream = await fetch(target, { method, headers, body: body ?? null, cache: "no-store", redirect: "manual" });
  // Bytes pass through untouched (JSON, or an export PDF/PNG); nothing is cached.
  const payload = upstream.status === 204 ? null : await upstream.arrayBuffer();
  const responseHeaders: Record<string, string> = {
    "content-type": upstream.headers.get("content-type") ?? "application/json", "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  };
  const disposition = upstream.headers.get("content-disposition");
  if (disposition && /^attachment; filename="[A-Za-z0-9._-]{1,160}"$/.test(disposition)) {
    responseHeaders["content-disposition"] = disposition;
  }
  return new NextResponse(payload, { status: upstream.status, headers: responseHeaders });
}

type Context = { params: Promise<{ path: string[] }> };

export const GET = (request: Request, context: Context) => forward(request, context.params);
export const POST = (request: Request, context: Context) => forward(request, context.params);
export const PUT = (request: Request, context: Context) => forward(request, context.params);
export const DELETE = (request: Request, context: Context) => forward(request, context.params);
