import { NextResponse } from "next/server";

import { apiBase, credentialCookie, sameOrigin } from "../../../../lib/session.ts";

export async function POST(request: Request) {
  if (!sameOrigin(request)) return NextResponse.json({ error: "cross_origin" }, { status: 403 });
  let guest: { principal_id: string; guest_token: string; expires_at: string | null };
  try {
    const upstream = await fetch(`${apiBase()}/v1/guest-sessions`, { method: "POST", cache: "no-store" });
    if (!upstream.ok) return NextResponse.json({ error: "guest_unavailable" }, { status: 502 });
    guest = (await upstream.json()) as typeof guest;
    if (!guest || typeof guest.guest_token !== "string" || !guest.guest_token ||
        typeof guest.principal_id !== "string" || !guest.principal_id) {
      return NextResponse.json({ error: "guest_unavailable" }, { status: 502 });
    }
  } catch {
    return NextResponse.json({ error: "guest_unavailable" }, { status: 502 });
  }
  const response = NextResponse.json({ principal_id: guest.principal_id, kind: "GUEST", expires_at: guest.expires_at },
                                     { status: 201 });
  response.cookies.set(credentialCookie(guest.guest_token));
  return response;
}
