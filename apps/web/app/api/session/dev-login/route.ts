import { NextResponse } from "next/server";

import { apiBase, devLoginEnabled, sameOrigin, sessionCookie } from "../../../../lib/session.ts";

/** Local/test only: sign in as a synthetic subject through the fake identity provider. */
export async function POST(request: Request) {
  if (!devLoginEnabled()) return NextResponse.json({ error: "not_found" }, { status: 404 });
  if (!sameOrigin(request)) return NextResponse.json({ error: "cross_origin" }, { status: 403 });
  const body = (await request.json().catch(() => null)) as { subject?: unknown } | null;
  const subject = typeof body?.subject === "string" && /^[a-z0-9-]{1,64}$/.test(body.subject) ? body.subject : null;
  if (!subject) return NextResponse.json({ error: "invalid_subject" }, { status: 422 });
  const upstream = await fetch(`${apiBase()}/v1/dev/id-tokens`, {
    method: "POST", cache: "no-store", headers: { "content-type": "application/json" },
    body: JSON.stringify({ subject }),
  });
  if (!upstream.ok) return NextResponse.json({ error: "login_unavailable" }, { status: 502 });
  const { id_token: token } = (await upstream.json()) as { id_token: string };
  const response = NextResponse.json({ signed_in: true }, { status: 201 });
  response.cookies.set(sessionCookie(token));
  return response;
}
