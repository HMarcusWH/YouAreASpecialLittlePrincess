import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  ApiError, PayloadError, PrincessApi, SessionEpoch, parseEvidenceBundle, parseNotificationPreferences,
  parseReportPage, parseReportView, parseRunStatus, pollDelayMs, reportCacheKey, sha256Hex,
} from "../src/index.ts";

const fixture = (name: string) =>
  JSON.parse(readFileSync(new URL(`../../../fixtures/reports/${name}`, import.meta.url), "utf8"));

test("every shared view fixture passes the runtime guard", () => {
  for (const name of ["view.free.json", "view.free-v2.json", "view.owner-premium.json",
                      "view.owner-image-revoked.json", "view.share.json", "view.share-v2.json",
                      "view.export-no-image.json", "view.export-v2-no-image.json"]) {
    const view = parseReportView(fixture(name));
    assert.ok(view.facts.length >= 0 && view.contract_version.startsWith("1."), name);
  }
});

test("corrupt, future-major and smuggled payloads are rejected", () => {
  const free = fixture("view.free.json");
  const cases: Array<[string, (v: any) => void]> = [
    ["future major", (v) => { v.contract_version = "2.0.0"; }],
    ["unknown projection", (v) => { v.projection = "ADMIN"; }],
    ["missing value smuggled as zero", (v) => {
      const f = v.facts[0]; f.availability = "MISSING"; f.value = 0; }],
    ["non-finite", (v) => { v.facts[0].value = "NaN"; v.facts[0].value = Number.NaN; }],
    ["dangling section fact", (v) => { v.sections[0].fact_ids = ["fact.NOT_HERE"]; }],
    ["premium in free", (v) => { v.sections[0].premium_section_id = "premium_1"; }],
    ["unknown evidence", (v) => { v.facts[0].evidence_class = "VIBES"; }],
    ["not an object", (v) => { v.facts = "all"; }],
  ];
  for (const [name, mutate] of cases) {
    const copy = structuredClone(free);
    mutate(copy);
    assert.throws(() => parseReportView(copy), PayloadError, name);
  }
  assert.throws(() => parseRunStatus({ run_id: "run_1", state: "SUCCEEDED", report_id: null }), PayloadError);
  assert.equal(parseRunStatus({ run_id: "run_1", state: "QUEUED", report_id: null, error_code: null }).state, "QUEUED");
});

test("history and evidence payloads are guarded before clients use them", () => {
  const page = parseReportPage({
    contract_version: "1.0.0",
    items: [{ report_id: "report_1", revision: 2, kind: "INDIVIDUAL",
              created_at: "2026-09-27T12:00:00Z", locale: "en" }],
    next_cursor: "cursor_1",
  });
  assert.equal(page.items[0]!.revision, 2);
  assert.equal(parseEvidenceBundle(fixture("evidence-bundle.json")).bundle_id, "evidence_fixture_1");

  assert.throws(() => parseReportPage({
    contract_version: "1.0.0", items: [{ report_id: "report_1", revision: 0, kind: "INDIVIDUAL",
      created_at: "2026-09-27T12:00:00Z", locale: "en" }], next_cursor: null,
  }), PayloadError);
  const corrupt = structuredClone(fixture("evidence-bundle.json"));
  corrupt.frames[0].width = 0;
  assert.throws(() => parseEvidenceBundle(corrupt), PayloadError);
});

test("errors expose only safe codes and bearer tokens are sent only when configured", async () => {
  const seen: Array<{ url: string; init: RequestInit }> = [];
  const fake = (async (url: string, init: RequestInit) => {
    seen.push({ url, init });
    if (url.endsWith("/v1/me")) {
      return new Response(JSON.stringify({ error: "session_revoked" }), { status: 401 });
    }
    return new Response(JSON.stringify({ error: "<script>alert(1)</script>" }), { status: 500 });
  }) as unknown as typeof fetch;
  const api = new PrincessApi({ baseUrl: "https://api.example.invalid/", fetch: fake, token: "tok" });
  await assert.rejects(api.me(), (e: ApiError) => e.status === 401 && e.code === "session_revoked");
  await assert.rejects(api.analysis("run_1"), (e: ApiError) => e.code === "request_failed");
  assert.equal((seen[0]!.init.headers as Record<string, string>).authorization, "Bearer tok");
  const anonymous = new PrincessApi({ baseUrl: "/api", fetch: fake });
  await assert.rejects(anonymous.me());
  assert.equal((seen[2]!.init.headers as Record<string, string>).authorization, undefined);
});

test("late responses for a previous principal are dropped", async () => {
  const epoch = new SessionEpoch();
  let release!: (value: string) => void;
  const slow = new Promise<string>((resolve) => { release = resolve; });
  const guarded = epoch.guard(slow);
  epoch.switchPrincipal();  // sign-out or account switch while the request was in flight
  release("alice's report");
  assert.equal(await guarded, null);
  assert.equal(await epoch.guard(Promise.resolve("bob's report")), "bob's report");
});

test("cache keys, backoff and hashing", async () => {
  assert.notEqual(reportCacheKey("prn_a", "r1", 1, "OWNER"), reportCacheKey("prn_b", "r1", 1, "OWNER"));
  assert.notEqual(reportCacheKey("prn_a", "r1", 1, "OWNER"), reportCacheKey("prn_a", "r1", 2, "OWNER"));
  assert.deepEqual([0, 1, 2, 3, 4, 9].map(pollDelayMs), [500, 1000, 2000, 4000, 8000, 8000]);
  const digest = await sha256Hex(new TextEncoder().encode("abc").buffer as ArrayBuffer);
  assert.equal(digest, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});

test("the default fetch is called unbound, as browsers require", async () => {
  const original = globalThis.fetch;
  let receiver: unknown = "unset";
  globalThis.fetch = function (this: unknown) {
    receiver = this;
    return Promise.resolve(new Response(JSON.stringify({ principal_id: "prn_1", kind: "GUEST" })));
  } as typeof fetch;
  try {
    await new PrincessApi({ baseUrl: "/api" }).me();
  } finally {
    globalThis.fetch = original;
  }
  assert.ok(receiver === undefined || receiver === globalThis, "fetch must not be invoked on the client instance");
});


test("notification preferences are strictly parsed and preserve backend errors", async () => {
  assert.deepEqual(parseNotificationPreferences({ mail_report_ready: false, locale: "en" }),
                   { mail_report_ready: false, locale: "en" });
  assert.deepEqual(parseNotificationPreferences({ mail_report_ready: true, locale: "sv-SE" }),
                   { mail_report_ready: true, locale: "sv-SE" });
  for (const bad of [
    null,
    {},
    { mail_report_ready: "yes", locale: "en" },
    { mail_report_ready: true, locale: "english" },
    { mail_report_ready: true, locale: "sv-se" },
    { mail_report_ready: true, locale: "en", extra: true },
  ]) {
    assert.throws(() => parseNotificationPreferences(bad),
                  (error: unknown) => error instanceof ApiError && error.code === "unreadable_notification_preferences");
  }

  const calls: Array<{ url: string; init: RequestInit }> = [];
  const fake = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    if (init.method === "GET") {
      return new Response(JSON.stringify({ mail_report_ready: false, locale: "sv-SE" }), { status: 200 });
    }
    if ((init.body as string).includes('"mail_report_ready":true')) {
      return new Response(JSON.stringify({ mail_report_ready: true, locale: "sv-SE" }), { status: 200 });
    }
    return new Response(JSON.stringify({ error: "account_required" }), { status: 403 });
  }) as unknown as typeof fetch;
  const api = new PrincessApi({ baseUrl: "https://api.example.invalid", fetch: fake, token: "tok" });
  assert.equal((await api.notificationPreferences()).locale, "sv-SE");
  assert.equal((await api.setNotificationPreferences({ mail_report_ready: true, locale: "sv-SE" })).mail_report_ready,
               true);
  await assert.rejects(
    api.setNotificationPreferences({ mail_report_ready: false, locale: "sv-SE" }),
    (error: unknown) => error instanceof ApiError && error.status === 403 && error.code === "account_required",
  );
  assert.equal(calls[1]!.init.method, "PUT");
  assert.equal((calls[1]!.init.headers as Record<string, string>)["content-type"], "application/json");
});
