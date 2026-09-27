import { NextResponse } from "next/server";

import { SESSION_COOKIE, sameOrigin } from "../../../../lib/session.ts";

export async function POST(request: Request) {
  if (!sameOrigin(request)) return NextResponse.json({ error: "cross_origin" }, { status: 403 });
  const response = new NextResponse(null, { status: 204 });
  response.cookies.set({ name: SESSION_COOKIE, value: "", path: "/", maxAge: 0, httpOnly: true, sameSite: "lax" });
  return response;
}
