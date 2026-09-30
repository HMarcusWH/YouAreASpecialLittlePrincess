import { NextResponse } from "next/server";

import { clearedCredentialCookie, sameOrigin } from "../../../../lib/session.ts";

/** Clear only this browser's opaque credential transport; provider/session
 * revocation is the separate /v1/me/logout-everywhere application operation. */
export async function POST(request: Request) {
  if (!sameOrigin(request)) return NextResponse.json({ error: "cross_origin" }, { status: 403 });
  const response = new NextResponse(null, { status: 204 });
  response.cookies.set(clearedCredentialCookie());
  return response;
}
