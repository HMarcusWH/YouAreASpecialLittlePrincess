// The byte transfer to a server-issued upload URL. The URL is a short-lived
// capability for one slot: it is only used when its origin is one the client
// was configured to trust, it never receives the API bearer credential, and a
// failed or ambiguous PUT is reported as such (completion decides the truth).
import { ApiError, TransportError } from "./client.ts";
import type { UploadTicket } from "./operations.ts";
import { isPrivateDevelopmentHost, originOf, parseUri } from "./uri.ts";

/** The ticket URL, if its origin is allowlisted; plain HTTP only for loopback/LAN development hosts. */
export function checkUploadTarget(ticket: UploadTicket, allowedOrigins: ReadonlySet<string>): string {
  const uri = parseUri(ticket.url);
  const origin = uri === null ? null : originOf(uri);
  if (uri === null || origin === null || (uri.scheme !== "https" && uri.scheme !== "http")) {
    throw new ApiError(502, "upload_url_invalid");
  }
  if (uri.userinfo !== null || uri.fragment !== null || !allowedOrigins.has(origin)) {
    throw new ApiError(502, "upload_origin_not_allowed");
  }
  if (uri.scheme !== "https" && !isPrivateDevelopmentHost(uri.host!)) {
    throw new ApiError(502, "upload_origin_not_allowed");
  }
  return ticket.url;
}

/** PUT ``body`` to the ticket URL with only a content type (no credential). */
export async function putUpload(ticket: UploadTicket, body: Uint8Array, mediaType: string,
                                allowedOrigins: ReadonlySet<string>,
                                doFetch: typeof fetch = (input, init) => globalThis.fetch(input, init)): Promise<void> {
  if (body.byteLength > ticket.max_bytes) throw new ApiError(413, "image_too_large");
  const url = checkUploadTarget(ticket, allowedOrigins);
  let response: Response;
  try {
    const init: RequestInit = { method: "PUT", headers: { "content-type": mediaType }, redirect: "error" };
    init.body = body as unknown as NonNullable<RequestInit["body"]>;
    response = await doFetch(url, init);
  } catch (error) {
    throw TransportError.from(error);
  }
  if (!response.ok) {
    let code = "upload_failed";
    try {
      const raw = (await response.json() as { error?: unknown } | null)?.error;
      if (typeof raw === "string" && /^[a-z0-9_.:-]{1,64}$/.test(raw)) code = raw;
    } catch {
      // Storage providers answer with XML or nothing; the status is enough.
    }
    throw new ApiError(response.status, code);
  }
}
