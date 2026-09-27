// Server-only session transport. The API credential lives in an HttpOnly,
// SameSite cookie and is attached to API calls on the server; client code
// never sees it and nothing is stored in localStorage or URLs.
import "server-only";

import { cookies, headers } from "next/headers";

import { PrincessApi } from "@princess/api-client";

export const SESSION_COOKIE = "princess_session";
const MAX_AGE_S = 60 * 60 * 24 * 30;

export function apiBase(): string {
  return (process.env.PRINCESS_API_BASE ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
}

export function environment(): string {
  return process.env.PRINCESS_ENVIRONMENT ?? "local";
}

export function devLoginEnabled(): boolean {
  return environment() === "local" || environment() === "test";
}

export async function sessionToken(): Promise<string | null> {
  return (await cookies()).get(SESSION_COOKIE)?.value ?? null;
}

export async function serverApi(): Promise<PrincessApi> {
  const correlation = (await headers()).get("x-correlation-id") ?? undefined;
  return new PrincessApi({ baseUrl: apiBase(), token: await sessionToken(),
                           ...(correlation ? { correlationId: correlation } : {}) });
}

export function sessionCookie(token: string) {
  return { name: SESSION_COOKIE, value: token, httpOnly: true, sameSite: "lax" as const, path: "/",
           secure: environment() !== "local" && environment() !== "test", maxAge: MAX_AGE_S };
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
