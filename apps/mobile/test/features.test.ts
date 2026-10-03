import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { ApiError, TransportError, type ClaimResult, type ExportStatus } from "@princess/api-client";
import type { Comparison, ReportViewModel } from "@princess/contracts";

import { PurchaseOrchestrator, type CommerceApi, type Principal } from "../src/features/commerce.ts";
import { presentComparison } from "../src/features/comparison.ts";
import { ExportController, paperFor } from "../src/features/exports.ts";
import { MAX_COMMENT, normalizeComment, submitFeedback } from "../src/features/feedback.ts";
import { HistoryController } from "../src/features/history.ts";
import { PremiumController, type PremiumApi } from "../src/features/premium.ts";
import { FakeAuthorizedFiles, FakeFileShareClient, FakeNativePurchaseClient } from "../src/platform/fakes.ts";

const fixture = <T>(path: string): T =>
  JSON.parse(readFileSync(new URL(`../../../fixtures/${path}`, import.meta.url), "utf8")) as T;

class FakeCommerce implements CommerceApi {
  claims: string[] = [];
  next: ClaimResult | Error = { outcome: "granted", finish_transaction: true };
  available = 0;
  async catalog() {
    return [{ product_id: "premium_single", credits: 1, catalog_version: "catalog-draft/1",
              rails: { apple_app_store: "se.princess.premium.single.draft", google_play: "premium_single_draft" } }];
  }
  async paymentAccount() { return "7a1f7f84-6a35-4a8b-9a8e-3a5f8d7e1c11"; }
  async credits() { return { platform: "ios" as const, available: this.available, reserved: 0 }; }
  async claimStorePurchase(_rail: string, proof: string) {
    this.claims.push(proof);
    if (this.next instanceof Error) throw this.next;
    if (this.next.outcome === "granted") this.available += 1;
    return this.next;
  }
}

async function firstOffer(orchestrator: PurchaseOrchestrator) {
  const result = await orchestrator.offers();
  assert.equal(result.status, "OK");
  return (result as Extract<typeof result, { status: "OK" }>).offers[0]!;
}

function commerce(principal: Principal | null = { principalId: "prn_a", kind: "ACCOUNT" }) {
  const api = new FakeCommerce();
  const store = new FakeNativePurchaseClient("apple_app_store");
  store.products.set("se.princess.premium.single.draft",
                     { productId: "se.princess.premium.single.draft", displayPrice: "29 kr", title: "Premium reading" });
  let who = principal;
  const orchestrator = new PurchaseOrchestrator({ api, store, platform: "ios", principal: () => who });
  return { api, store, orchestrator, switchTo: (p: Principal | null) => { who = p; } };
}

test("offers join the server catalog with store-localized display prices and require an account", async () => {
  const { orchestrator } = commerce();
  const offers = await orchestrator.offers();
  assert.equal(offers.status, "OK");
  assert.deepEqual(offers.status === "OK" && offers.offers[0], {
    productId: "premium_single", storeProductId: "se.princess.premium.single.draft", credits: 1,
    displayPrice: "29 kr", title: "Premium reading" });
  assert.deepEqual(await commerce({ principalId: "prn_g", kind: "GUEST" }).orchestrator.offers(),
                   { status: "ACCOUNT_REQUIRED" });
});

test("a purchase is finished only after the server reports a durable grant", async () => {
  const { api, store, orchestrator } = commerce();
  const offer = await firstOffer(orchestrator);
  // The fake store refuses a finish without the recorded server grant, like the real contract.
  const original = api.claimStorePurchase.bind(api);
  api.claimStorePurchase = async (rail, proof) => {
    const result = await original(rail, proof);
    store.recordServerGrant(proof);
    return result;
  };
  assert.deepEqual(await orchestrator.buy(offer), { status: "GRANTED", alreadyGranted: false });
  assert.equal(store.finished.length, 1);
  assert.deepEqual(store.accountTokens, ["7a1f7f84-6a35-4a8b-9a8e-3a5f8d7e1c11"], "the store is bound to the account");
  assert.equal((await orchestrator.balance())!.available, 1, "credit comes from the server balance, not a local counter");
});

test("pending, cancelled, unknown and refused outcomes never finish and never ask to pay twice", async () => {
  const pending = commerce();
  const offer = await firstOffer(pending.orchestrator);
  pending.store.nextState = "PENDING";
  assert.deepEqual(await pending.orchestrator.buy(offer), { status: "PENDING" });
  pending.store.nextState = "CANCELLED";
  assert.deepEqual(await pending.orchestrator.buy(offer), { status: "CANCELLED" });
  assert.deepEqual(pending.api.claims, []);

  const lost = commerce();
  lost.api.next = new TransportError("TIMEOUT");
  assert.deepEqual(await lost.orchestrator.buy(offer), { status: "VERIFYING" });
  assert.equal(lost.store.finished.length, 0, "unknown verification: the store keeps the transaction for replay");

  const refused = commerce();
  refused.api.next = { outcome: "account_mismatch", finish_transaction: false };
  assert.deepEqual(await refused.orchestrator.buy(offer), { status: "NOT_GRANTED", code: "account_mismatch" });
  assert.equal(refused.store.finished.length, 0);
});

test("startup replay claims unfinished transactions once and converges on already_granted", async () => {
  const { api, store, orchestrator } = commerce();
  const offer = await firstOffer(orchestrator);
  api.next = new ApiError(503, "unavailable");
  assert.deepEqual(await orchestrator.buy(offer), { status: "VERIFYING" });
  api.next = { outcome: "already_granted", finish_transaction: true };
  store.recordServerGrant(store.observations[0]!.proof!);
  const outcomes = await orchestrator.reconcile();
  assert.deepEqual(outcomes, [{ status: "GRANTED", alreadyGranted: true }]);
  assert.equal(store.finished.length, 1);
  assert.deepEqual(await orchestrator.reconcile(), [], "nothing left to replay");
});

test("an account switch during a purchase leaves the claim to the owning account", async () => {
  const { api, store, orchestrator, switchTo } = commerce();
  const offer = await firstOffer(orchestrator);
  const begin = store.beginPurchase.bind(store);
  store.beginPurchase = async (productId, token) => {
    const observation = await begin(productId, token);
    switchTo({ principalId: "prn_b", kind: "ACCOUNT" });
    return observation;
  };
  assert.deepEqual(await orchestrator.buy(offer), { status: "VERIFYING" });
  assert.deepEqual(api.claims, [], "never claimed under the account that did not buy it");
});

class FakePremiumApi implements PremiumApi {
  allowed = false;
  available = 0;
  job: { state: "QUEUED" | "LEASED" | "SUCCEEDED" | "FAILED" | "CANCELLED"; error: string | null } =
    { state: "QUEUED", error: null };
  recorded: unknown[] = [];
  requests = 0;
  requestError: Error | null = null;
  async premiumContent(reportId: string) {
    return { report_id: reportId, revision: 2, overlay_id: "overlay_1", evidence_class: "AI_SYNTHESIS" as const,
             answers: [], soft_fields: [], omissions: [] };
  }
  async checkPermission(purposeId: string) { return { purpose_id: purposeId, allowed: this.allowed, reason: null }; }
  async recordPermission(choice: unknown) { this.recorded.push(choice); this.allowed = true; return {}; }
  async credits() { return { platform: "ios" as const, available: this.available, reserved: 0 }; }
  async requestPremium() {
    this.requests += 1;
    if (this.requestError) throw this.requestError;
    return { job_id: "pjob_1", created: this.requests === 1 };
  }
  async premiumJob(jobId: string) { return { job_id: jobId, state: this.job.state, error_code: this.job.error }; }
}

test("Premium is offered only when the server says so and needs account, image, permission and credit", async () => {
  const free = fixture<ReportViewModel>("reports/view.free-v2.json");
  const api = new FakePremiumApi();
  const premium = new PremiumController(api, "ios", () => "req1");
  assert.deepEqual(await premium.load(free, "ACCOUNT"), { status: "NOT_OFFERED", reason: "premium_not_yet_available" });

  const offered: ReportViewModel = { ...free, actions: free.actions.map((a) =>
    a.kind === "PURCHASE" ? { ...a, enabled: true, reason: null } : a) };
  assert.deepEqual(await premium.load(offered, "GUEST"), { status: "ACCOUNT_REQUIRED" });
  assert.deepEqual(await premium.load({ ...offered, authorized_asset_ids: [] }, "ACCOUNT"), { status: "NO_IMAGE" });
  assert.equal((await premium.load(offered, "ACCOUNT")).status, "NEEDS_PERMISSION");
  await premium.grantPermission(offered.source_report_id, "notice.consent-choices:1");
  assert.deepEqual(api.recorded[0], { purpose_id: "third_party_ai_processing", scope_kind: "REPORT",
                                      scope_ref: offered.source_report_id, decision: "GRANT",
                                      notice_version: "notice.consent-choices:1", request_id: "mobile.req1.ai" });
  assert.equal((await premium.load(offered, "ACCOUNT")).status, "NEEDS_CREDIT");
  api.available = 1;
  assert.equal((await premium.load(offered, "ACCOUNT")).status, "READY");
});

test("Premium generation reads only the saved overlay and failures leave Free intact", async () => {
  const api = new FakePremiumApi();
  const premium = new PremiumController(api, "android", () => "req1");
  assert.deepEqual(await premium.request("report_1"), { status: "GENERATING", jobId: "pjob_1" });
  assert.deepEqual(await premium.request("report_1"), { status: "GENERATING", jobId: "pjob_1" },
                   "a retried request returns the same job, not a second billable attempt");
  assert.deepEqual(await premium.poll("report_1", "pjob_1"), { status: "GENERATING", jobId: "pjob_1" });
  api.job = { state: "FAILED", error: "validation_refused" };
  assert.deepEqual(await premium.poll("report_1", "pjob_1"), { status: "FAILED", code: "validation_refused" });
  api.job = { state: "SUCCEEDED", error: null };
  assert.equal((await premium.poll("report_1", "pjob_1")).status, "SAVED");

  api.requestError = new TransportError("TIMEOUT");
  assert.deepEqual(await premium.request("report_1"), { status: "UNKNOWN", code: "outcome_unknown" });
  api.requestError = new ApiError(501, "premium_generation_disabled");
  assert.deepEqual(await premium.request("report_1"), { status: "NOT_OFFERED", reason: "premium_generation_disabled" });

  const saved = fixture<ReportViewModel>("reports/view.owner-premium.json");
  assert.equal((await premium.load(saved, "ACCOUNT")).status, "SAVED");
  api.premiumContent = async () => { throw new ApiError(404, "premium_not_available"); };
  assert.deepEqual(await premium.load(saved, "ACCOUNT"), { status: "REVOKED" });
});

function exportStatus(state: ExportStatus["state"], extra: Partial<ExportStatus> = {}): ExportStatus {
  return { export_id: "export_1", report_id: "report_1", revision: 1, layout: "A4", state, error_code: null,
           media_type: "application/pdf", size_bytes: 2048, ...extra };
}

test("PDF export polls, downloads within bounds, shares and then removes the private copy", async () => {
  const states = [exportStatus("QUEUED"), exportStatus("READY")];
  const api = {
    requestExport: async () => exportStatus("QUEUED"),
    exportStatus: async () => states.shift() ?? exportStatus("READY"),
    exportDownload: async () => ({ url: "https://api.test/v1/report-exports/export_1/file",
                                   headers: { authorization: "Bearer t" } }),
  };
  const files = new FakeAuthorizedFiles();
  const share = new FakeFileShareClient();
  const exports = new ExportController(api, files, share, async () => undefined);
  const ready = await exports.prepare("report_1", "A4");
  assert.equal(ready.status, "READY");
  assert.equal(files.requests[0]!.headers.authorization, "Bearer t");
  assert.ok(ready.status === "READY");
  assert.equal(await exports.shareAndClean(ready.file), "SHARED");
  assert.deepEqual(share.cleaned, ["file:///private/export.pdf"]);

  files.next = { uri: "file:///private/x.pdf", bytes: 4096, mediaType: "application/pdf" };
  const oversized = await exports.prepare("report_1", "A4");
  assert.deepEqual(oversized, { status: "FAILED", code: "download_out_of_bounds" }, "a larger file than announced is refused");

  const revoked = new ExportController({ ...api, requestExport: async () => exportStatus("REVOKED", { error_code: "report_deleted" }) },
                                       files, share, async () => undefined);
  assert.deepEqual(await revoked.prepare("report_1", "A4"), { status: "REVOKED", code: "report_deleted" });
  const disabled = new ExportController({ ...api, requestExport: async () => { throw new ApiError(501, "exports_not_configured"); } },
                                        files, share, async () => undefined);
  assert.deepEqual(await disabled.prepare("report_1", "A4"), { status: "UNAVAILABLE", code: "exports_not_configured" });
  let cancel = false;
  const slow = new ExportController({ ...api, exportStatus: async () => { cancel = true; return exportStatus("QUEUED"); } },
                                    files, share, async () => undefined);
  assert.deepEqual(await slow.prepare("report_1", "A4", () => cancel), { status: "CANCELLED", code: "cancelled" });
});

test("paper size follows the device region", () => {
  assert.equal(paperFor("en-US"), "LETTER");
  assert.equal(paperFor("sv-SE"), "A4");
  assert.equal(paperFor("en"), "A4");
  assert.equal(paperFor(null), "A4");
});

test("history pages without duplicates, surfaces unfinished server work and marks deletion as requested", async () => {
  const page = (ids: string[], next: string | null) => ({ contract_version: "1.0.0" as const, next_cursor: next,
    items: ids.map((id) => ({ report_id: id, revision: 1, kind: "INDIVIDUAL" as const,
                              created_at: "2026-10-03T12:00:00Z", locale: "en" })) });
  const deleted: string[] = [];
  const api = {
    reports: async (_limit?: number, cursor?: string | null) => (cursor ? page(["r2", "r3"], null) : page(["r1", "r2"], "c1")),
    deleteReport: async (id: string) => { deleted.push(id); return { state: "DELETION_REQUESTED" as const }; },
    recentAnalyses: async () => [
      { run_id: "run_9", state: "RUNNING" as const, report_id: null, error_code: null, created_at: "2026-10-03T12:00:00Z" },
      { run_id: "run_1", state: "SUCCEEDED" as const, report_id: "r1", error_code: null, created_at: "2026-10-03T11:00:00Z" },
    ],
  };
  const history = new HistoryController(api);
  const first = await history.refresh();
  assert.deepEqual(first.inProgress.map((r) => r.run_id), ["run_9"]);
  const all = await history.more();
  assert.deepEqual(all.items.map((i) => i.report_id), ["r1", "r2", "r3"]);
  assert.equal(all.nextCursor, null);
  const after = await history.remove("r2");
  assert.deepEqual(deleted, ["r2"]);
  assert.equal(after.items.find((i) => i.report_id === "r2")!.deletion, "REQUESTED");
});

test("feedback comments are bounded and blank comments are not sent", async () => {
  assert.equal(normalizeComment("   "), null);
  assert.equal(normalizeComment("a\n\n  b"), "a b");
  assert.equal(normalizeComment("x".repeat(900))!.length, MAX_COMMENT);
  const sent: unknown[] = [];
  const api = {
    submitFeedback: async (reportId: string, body: unknown) => {
      sent.push([reportId, body]);
      return { feedback_id: "fb_1", report_id: reportId, revision: 1, category: "OTHER" as const,
               comment_stored: null, expires_at: "2027-01-01T00:00:00Z", contract_version: "report-feedback/1" };
    },
    withdrawFeedback: async () => undefined,
  };
  await submitFeedback(api, "report_1", { category: "HARMFUL_OR_OFFENSIVE", target: "PREMIUM", targetRef: null,
                                          comment: "  " }, "fbreq_00000001");
  assert.deepEqual(sent[0], ["report_1", { category: "HARMFUL_OR_OFFENSIVE", target_kind: "PREMIUM", target_ref: null,
                                           comment: null, request_id: "fbreq_00000001" }]);
});

test("comparison presentation formats saved differences without inventing a score", () => {
  const pair = fixture<Comparison>("comparisons/pair-ab.json");
  const view = presentComparison(pair, "sv");
  assert.equal(view.rows.length, pair.differences.length);
  assert.equal(view.commonCount, pair.coverage.common_n);
  for (const row of view.rows) {
    assert.ok(row.fromPosition >= 0 && row.fromPosition <= 1);
    assert.ok(!/score|similar/i.test(row.label));
  }
  const none = presentComparison(fixture<Comparison>("comparisons/no-overlap.json"), "en");
  assert.equal(none.rows.length, 0);
  assert.ok(none.exclusions.length > 0, "no common coverage is explained, not hidden");
});
