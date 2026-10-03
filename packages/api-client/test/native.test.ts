import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  ApiError, PayloadError, PrincessApi, TransportError, checkUploadTarget, nextPollDelayMs, parseCatalog,
  parseClaimResult, parseComparison, parseConsentNotices, parseCredits, parseGrantSnapshot, parseGuestSession,
  parsePremiumContent, parsePremiumJob, parseRunPage, parseUploadTicket, putUpload, sha256Hex, sha256HexSync,
} from "../src/index.ts";

const comparison = (name: string) =>
  JSON.parse(readFileSync(new URL(`../../../fixtures/comparisons/${name}`, import.meta.url), "utf8"));

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });

test("portable SHA-256 matches node:crypto across block boundaries and large inputs", async () => {
  const lengths = [0, 1, 3, 55, 56, 57, 63, 64, 65, 119, 120, 127, 128, 129, 1000, 4096, 1 << 20];
  for (const length of lengths) {
    const bytes = new Uint8Array(randomBytes(length));
    const expected = createHash("sha256").update(bytes).digest("hex");
    assert.equal(sha256HexSync(bytes), expected, `length ${length}`);
  }
  assert.equal(sha256HexSync(new TextEncoder().encode("abc")),
               "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");

  // Without WebCrypto (Hermes) sha256Hex falls back to the portable implementation.
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  Object.defineProperty(globalThis, "crypto", { value: {}, configurable: true, writable: true });
  try {
    const bytes = new Uint8Array(randomBytes(70_001));
    assert.equal(await sha256Hex(bytes), createHash("sha256").update(bytes).digest("hex"));
    assert.equal(await sha256Hex(bytes.buffer), createHash("sha256").update(bytes).digest("hex"));
  } finally {
    if (descriptor) Object.defineProperty(globalThis, "crypto", descriptor);
  }
});

test("the credential is read per request and never sent on anonymous calls", async () => {
  const seen: Array<{ url: string; auth: string | undefined }> = [];
  const fake = (async (url: string, init: RequestInit) => {
    seen.push({ url, auth: (init.headers as Record<string, string>).authorization });
    if (url.endsWith("/v1/guest-sessions")) {
      return json({ principal_id: "prn_g", guest_token: "guest-token-abcdef", expires_at: null }, 201);
    }
    if (url.includes("/v1/consent-notices")) return json({ notices: [] });
    return json({ principal_id: "prn_a", kind: "ACCOUNT" });
  }) as unknown as typeof fetch;
  let current: string | null = "token_v1";
  const api = new PrincessApi({ baseUrl: "https://api.example.invalid", fetch: fake, credentials: () => current });
  await api.me();
  current = "token_v2";  // rotation: the same long-lived client picks up the new credential
  await api.me();
  current = null;  // sign-out: nothing stale is sent
  await api.me();
  current = "token_v3";
  await api.createGuestSession();
  await api.consentNotices("sv-SE");
  assert.deepEqual(seen.map((s) => s.auth), ["Bearer token_v1", "Bearer token_v2", undefined, undefined, undefined]);
  assert.ok(seen[4]!.url.endsWith("/v1/consent-notices?locale=sv-SE"));
});

test("transport failures are distinct from API errors and timeouts are reported as unknown outcomes", async () => {
  const offline = (async () => { throw new TypeError("Network request failed"); }) as unknown as typeof fetch;
  const api = new PrincessApi({ baseUrl: "https://api.example.invalid", fetch: offline, token: "t" });
  await assert.rejects(api.startAnalysis("capture_1"), (e: unknown) => e instanceof TransportError && e.kind === "NETWORK");

  const hanging = ((_url: string, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
    init.signal?.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
  })) as unknown as typeof fetch;
  const slow = new PrincessApi({ baseUrl: "https://api.example.invalid", fetch: hanging, token: "t", timeoutMs: 20 });
  await assert.rejects(slow.completeUpload("upl_1", "a".repeat(64)),
                       (e: unknown) => e instanceof TransportError && e.kind === "TIMEOUT");

  const limited = (async () => json({ error: "too_many_active_analyses" }, 429, { "retry-after": "60" })) as
    unknown as typeof fetch;
  const busy = new PrincessApi({ baseUrl: "https://api.example.invalid", fetch: limited, token: "t" });
  const error = await busy.startAnalysis("capture_1").catch((e: unknown) => e);
  assert.ok(error instanceof ApiError && error.status === 429 && error.retryAfterMs === 60_000);
  assert.equal(nextPollDelayMs(0, error), 60_000);
  assert.equal(nextPollDelayMs(2), 2000);
  assert.equal(nextPollDelayMs(1, new ApiError(503, "x", 7_200_000)), 60_000);
});

test("operation guards reject smuggled or inconsistent payloads", () => {
  assert.equal(parseGuestSession({ principal_id: "prn_1", guest_token: "abcdefghijk", expires_at: null }).principal_id,
               "prn_1");
  assert.throws(() => parseGuestSession({ principal_id: "prn_1", guest_token: "short", expires_at: null }), PayloadError);
  assert.throws(() => parseGuestSession({ principal_id: "prn_1", guest_token: "abcdefghijk", expires_at: null,
                                          admin: true }), PayloadError);

  const ticket = { upload_id: "upl_1", method: "PUT", url: "https://uploads.example/upl_1?sig=x",
                   expires_at: "2026-10-03T12:00:00Z", max_bytes: 20971520 };
  assert.equal(parseUploadTicket(ticket).upload_id, "upl_1");
  assert.throws(() => parseUploadTicket({ ...ticket, url: "javascript:alert(1)" }), PayloadError);
  assert.throws(() => parseUploadTicket({ ...ticket, method: "POST" }), PayloadError);

  assert.deepEqual(parseClaimResult({ outcome: "granted", finish_transaction: true }),
                   { outcome: "granted", finish_transaction: true });
  assert.equal(parseClaimResult({ outcome: "pending", finish_transaction: false }).outcome, "pending");
  // A client may only finish a store transaction after a durable grant.
  assert.throws(() => parseClaimResult({ outcome: "pending", finish_transaction: true }), PayloadError);

  assert.throws(() => parseCredits({ platform: "ios", available: -1, reserved: 0 }), PayloadError);
  assert.equal(parseCatalog({ products: [{ product_id: "premium_single", credits: 1, catalog_version: "catalog-draft/1",
                                           rails: { apple_app_store: "se.princess.premium.single.draft" } }] })[0]!
               .rails.apple_app_store, "se.princess.premium.single.draft");
  assert.throws(() => parseCatalog({ products: [{ product_id: "p", credits: 1, catalog_version: "v",
                                                  rails: { paypal: "x" } }] }), PayloadError);
  assert.equal(parsePremiumJob({ job_id: "pjob_1", state: "LEASED", error_code: null }).state, "LEASED");

  const runs = parseRunPage({ items: [
    { run_id: "run_2", state: "RUNNING", report_id: null, error_code: null, created_at: "2026-10-03T12:00:00.5Z" },
    { run_id: "run_1", state: "SUCCEEDED", report_id: null, error_code: null, created_at: "2026-10-03T11:00:00Z" },
  ] });
  assert.equal(runs.items.length, 2);
  assert.throws(() => parseRunPage({ items: [{ run_id: "run_1", state: "DONE", report_id: null, error_code: null,
                                               created_at: "2026-10-03T11:00:00Z" }] }), PayloadError);

  const grant = { contract_version: "1.0.0", grant_id: "evt_1", owner_id: "prn_1", purpose_id: "service_processing",
                  purpose_version: 1, status: "GRANTED", scope: "SPECIMEN:capture_1",
                  recorded_at: "2026-10-03T12:00:00Z", effective_at: "2026-10-03T12:00:00Z", policy_sha256: "a".repeat(64) };
  assert.equal(parseGrantSnapshot(grant).status, "GRANTED");
  assert.throws(() => parseGrantSnapshot({ ...grant, contract_version: "2.0.0" }), PayloadError);

  const notices = parseConsentNotices({ notices: [{ notice_version: "notice.consent-choices:1", status: "DRAFT",
    accepted_for_use: true, locale: "en", purposes: [{ purpose_id: "service_processing", purpose_version: 1,
      label: "Analyse this page", explanation: "We process this photo.", decline_consequence: "No report." }] }] });
  assert.equal(notices[0]!.purposes[0]!.label, "Analyse this page");
  assert.throws(() => parseConsentNotices({ notices: [{ notice_version: "../x", status: "DRAFT", accepted_for_use: true,
                                                        locale: "en", purposes: [] }] }), PayloadError);
});

test("Premium content keeps evidence class, bounded prose and explicit omissions", () => {
  const content = parsePremiumContent({
    report_id: "report_1", revision: 2, overlay_id: "overlay_1", evidence_class: "AI_SYNTHESIS",
    answers: [{ question_id: "q.slant", answer_state: "ANSWERED", selected_candidate_ids: ["c.right"],
                support_fact_ids: ["fact.SLANT_ANGLE_MEAN"], prose: "Most strokes lean right." }],
    soft_fields: [{ field_id: "summary", text: "A short summary.", support_fact_ids: ["fact.SLANT_ANGLE_MEAN"] }],
    omissions: [{ item_id: "q.traditional", reason: "not_model_answered", detail: null }],
  });
  assert.equal(content.answers[0]!.prose, "Most strokes lean right.");
  assert.equal(content.omissions[0]!.reason, "not_model_answered");
  assert.throws(() => parsePremiumContent({ ...content, evidence_class: "MEASURED" }), PayloadError);
  assert.throws(() => parsePremiumContent({ ...content, answers: [{ ...content.answers[0], prose: "x".repeat(5000) }] }),
                PayloadError);
});

test("shared comparison fixtures pass the comparison guard and corruption is rejected", () => {
  for (const name of ["pair-ab.json", "pair-ba.json", "pair-equal.json", "history.json", "no-overlap.json"]) {
    const value = parseComparison(comparison(name));
    assert.ok(value.inputs.length >= 2, name);
  }
  const corrupt = structuredClone(comparison("pair-ab.json"));
  corrupt.coverage.common_n += 1;
  assert.throws(() => parseComparison(corrupt), PayloadError);
  const duplicated = structuredClone(comparison("pair-ab.json"));
  duplicated.input_report_ids = [duplicated.input_report_ids[0], duplicated.input_report_ids[0]];
  assert.throws(() => parseComparison(duplicated), PayloadError);
  const outside = structuredClone(comparison("pair-ab.json"));
  if (outside.differences.length > 0) {
    outside.differences[0].feature_id = "NOT_COMMON";
    assert.throws(() => parseComparison(outside), PayloadError);
  }
});

test("upload PUT goes only to allowlisted origins, without a credential, and reports failures", async () => {
  const ticket = parseUploadTicket({ upload_id: "upl_1", method: "PUT", url: "https://uploads.example/v1/upl_1?sig=s",
                                     expires_at: "2026-10-03T12:00:00Z", max_bytes: 8 });
  const allowed = new Set(["https://uploads.example"]);
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const ok = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(null, { status: 204 });
  }) as unknown as typeof fetch;
  await putUpload(ticket, new Uint8Array([1, 2, 3]), "image/jpeg", allowed, ok);
  const headers = calls[0]!.init.headers as Record<string, string>;
  assert.deepEqual(Object.keys(headers), ["content-type"]);
  assert.equal(calls[0]!.init.method, "PUT");

  await assert.rejects(putUpload(ticket, new Uint8Array(9), "image/jpeg", allowed, ok),
                       (e: unknown) => e instanceof ApiError && e.code === "image_too_large");
  await assert.rejects(putUpload(ticket, new Uint8Array(1), "image/jpeg", new Set(["https://other.example"]), ok),
                       (e: unknown) => e instanceof ApiError && e.code === "upload_origin_not_allowed");
  const plain = parseUploadTicket({ ...ticket, url: "http://uploads.example/v1/upl_1" });
  assert.throws(() => checkUploadTarget(plain, new Set(["http://uploads.example"])), ApiError);
  const lan = parseUploadTicket({ ...ticket, url: "http://192.168.1.20:8000/v1/dev/uploads/upl_1?sig=s" });
  assert.equal(checkUploadTarget(lan, new Set(["http://192.168.1.20:8000"])).hostname, "192.168.1.20");

  const expired = (async () => json({ error: "upload_expired" }, 409)) as unknown as typeof fetch;
  await assert.rejects(putUpload(ticket, new Uint8Array(1), "image/jpeg", allowed, expired),
                       (e: unknown) => e instanceof ApiError && e.status === 409 && e.code === "upload_expired");
  const dropped = (async () => { throw new TypeError("connection reset"); }) as unknown as typeof fetch;
  await assert.rejects(putUpload(ticket, new Uint8Array(1), "image/jpeg", allowed, dropped),
                       (e: unknown) => e instanceof TransportError && e.kind === "NETWORK");
});

test("native downloads are bound to API paths and carry the current bearer credential", async () => {
  const api = new PrincessApi({ baseUrl: "https://api.example.invalid/", credentials: async () => "tok" });
  const exportFile = await api.exportDownload("export_1");
  assert.equal(exportFile.url, "https://api.example.invalid/v1/report-exports/export_1/file");
  assert.equal(exportFile.headers.authorization, "Bearer tok");
  const image = await api.sourceImageDownload("report/../1");
  assert.equal(image.url, "https://api.example.invalid/v1/reports/report%2F..%2F1/source-image");
});
