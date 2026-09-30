// Server-only credential transport. The opaque API credential lives in an
// HttpOnly SameSite cookie and is attached to API calls on the server; client
// code never sees it and nothing is stored in localStorage or URLs.
import "server-only";

import { cookies, headers } from "next/headers";

import { PrincessApi } from "@princess/api-client";

import {
  SESSION_COOKIE,
  clearedCredentialCookie as clearedCredentialCookieFor,
  credentialCookie as credentialCookieFor,
  devCredentialIssuanceEnabled,
  webEnvironment,
  type WebEnvironment,
} from "./session-policy.ts";

export { SESSION_COOKIE };

export function apiBase(): string {
  return (process.env.PRINCESS_API_BASE ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
}

export function environment(): WebEnvironment {
  return webEnvironment(process.env.PRINCESS_ENVIRONMENT);
}

export function devLoginEnabled(): boolean {
  return devCredentialIssuanceEnabled(environment());
}

export async function sessionCredential(): Promise<string | null> {
  return (await cookies()).get(SESSION_COOKIE)?.value ?? null;
}

export async function serverApi(): Promise<PrincessApi> {
  const correlation = (await headers()).get("x-correlation-id") ?? undefined;
  return new PrincessApi({
    baseUrl: apiBase(),
    token: await sessionCredential(),
    ...(correlation ? { correlationId: correlation } : {}),
  });
}

export function credentialCookie(credential: string) {
  return credentialCookieFor(credential, environment());
}

export function clearedCredentialCookie() {
  return clearedCredentialCookieFor(environment());
}

/** Same-origin check for cookie-authenticated mutations (CSRF defence). */
export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (!origin || !host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}
