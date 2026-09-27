import { NextResponse } from "next/server";

import { apiBase, sameOrigin, sessionCookie } from "../../../../lib/session.ts";

export async function POST(request: Request) {
  if (!sameOrigin(request)) return NextResponse.json({ error: "cross_origin" }, { status: 403 });
  const upstream = await fetch(`${apiBase()}/v1/guest-sessions`, { method: "POST", cache: "no-store" });
  if (!upstream.ok) return NextResponse.json({ error: "guest_unavailable" }, { status: 502 });
  const guest = (await upstream.json()) as { principal_id: string; guest_token: string; expires_at: string | null };
  const response = NextResponse.json({ principal_id: guest.principal_id, kind: "GUEST", expires_at: guest.expires_at },
                                     { status: 201 });
  response.cookies.set(sessionCookie(guest.guest_token));
  return response;
}
