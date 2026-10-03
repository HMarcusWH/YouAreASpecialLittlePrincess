// Live development-API journey for the native client's non-UI layers.
//
// Runs the app's real composition (createServices: session manager, API
// client, journal, capture workflow, runner, controllers) in Node against a
// running local API and workers, with Node stand-ins only for device I/O
// (secure storage, private files, downloads). It is evidence that the native
// business flow works against the real server; it is not device, simulator or
// UI evidence. Started by tools/run_mobile_journey.sh.
import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { ApiError, putUpload, sha256Hex, type AuthorizedDownload, type UploadMediaType,
         type UploadTicket } from "@princess/api-client";
import { buildDossier } from "@princess/report-core";

import { createServices, type NativePorts, type Services } from "../src/bootstrap/services.ts";
import { parseRuntimeConfig, type RuntimeConfig } from "../src/config/runtime.ts";
import { presentComparison } from "../src/features/comparison.ts";
import { ExportController } from "../src/features/exports.ts";
import { submitFeedback } from "../src/features/feedback.ts";
import { HistoryController } from "../src/features/history.ts";
import type { AuthorizedFileClient, DownloadedFile, KeyValueFile } from "../src/platform/contracts.ts";
import {
  FakeCaptureClient, FakeDevicePushClient, FakeFileShareClient, FakeImagePreparer, FakeSecureSessionStore,
} from "../src/platform/fakes.ts";
import { AllowlistedDeepLinkRouter } from "../src/platform/links.ts";
import type { LocalFiles } from "../src/work/capture-workflow.ts";
import type { WorkEntry } from "../src/work/journal.ts";

const API = process.env.PRINCESS_E2E_API ?? "http://127.0.0.1:8000";
const SAMPLE = process.env.PRINCESS_E2E_SAMPLE ?? "";
const SECOND = process.env.PRINCESS_E2E_SAMPLE_2 ?? "";
const GATE = process.env.PRINCESS_E2E_WORKER_GATE ?? "";
const WORK = process.env.PRINCESS_E2E_WORK_DIR ?? "";
const EXPORTS = process.env.PRINCESS_E2E_EXPORTS === "1";
assert.ok(SAMPLE && SECOND && GATE && WORK, "set PRINCESS_E2E_SAMPLE, _SAMPLE_2, _WORKER_GATE and _WORK_DIR");

class DiskDocuments implements KeyValueFile {
  private readonly dir: string;
  constructor(dir: string) { this.dir = dir; mkdirSync(dir, { recursive: true }); }
  async read(name: string) { try { return readFileSync(join(this.dir, name), "utf8"); } catch { return null; } }
  async write(name: string, value: string) { writeFileSync(join(this.dir, `${name}.tmp`), value); writeFileSync(join(this.dir, name), value); }
  async remove(name: string) { rmSync(join(this.dir, name), { force: true }); }
}

class NodeLocalFiles implements LocalFiles {
  private readonly origins: ReadonlySet<string>;
  private readonly fetcher: typeof fetch;
  constructor(origins: ReadonlySet<string>, fetcher: typeof fetch) { this.origins = origins; this.fetcher = fetcher; }
  async digest(uri: string) {
    try {
      const bytes = readFileSync(new URL(uri));
      return { sha256: await sha256Hex(new Uint8Array(bytes)), bytes: bytes.byteLength };
    } catch { return null; }
  }
  async upload(ticket: UploadTicket, uri: string, mediaType: UploadMediaType) {
    await putUpload(ticket, new Uint8Array(readFileSync(new URL(uri))), mediaType, this.origins, this.fetcher);
  }
  async remove(uri: string) { rmSync(new URL(uri), { force: true }); }
}

class NodeDownloads implements AuthorizedFileClient {
  private readonly dir: string;
  constructor(dir: string) { this.dir = dir; mkdirSync(dir, { recursive: true }); }
  async download(request: AuthorizedDownload, name: string, limits: { maxBytes: number; mediaTypes: readonly string[] }):
      Promise<DownloadedFile> {
    const response = await fetch(request.url, { headers: { ...request.headers } });
    if (!response.ok) throw new ApiError(response.status, "download_failed");
    const bytes = new Uint8Array(await response.arrayBuffer());
    const mediaType = bytes[0] === 0x25 && bytes[1] === 0x50 ? "application/pdf"
      : bytes[0] === 0x89 ? "image/png" : bytes[0] === 0xff ? "image/jpeg" : "unknown";
    if (bytes.byteLength > limits.maxBytes || !limits.mediaTypes.includes(mediaType)) {
      throw new ApiError(502, "download_out_of_bounds");
    }
    const path = join(this.dir, name);
    writeFileSync(path, bytes);
    return { uri: new URL(`file://${path}`).toString(), bytes: bytes.byteLength, mediaType };
  }
  async remove(uri: string) { rmSync(new URL(uri), { force: true }); }
  async sweep() { return 0; }
}

/** Drops the response of the first matching request after the server handled it. */
function lossyFetch(match: RegExp): { fetch: typeof fetch; dropped: () => number } {
  let dropped = 0;
  return {
    dropped: () => dropped,
    fetch: async (input, init) => {
      const response = await fetch(input, init);
      if (dropped === 0 && match.test(String(input))) {
        dropped += 1;
        throw new TypeError("connection reset after the server responded");
      }
      return response;
    },
  };
}

const config: RuntimeConfig = (() => {
  const result = parseRuntimeConfig({ variant: "development", backendEnvironment: "test", apiBaseUrl: API,
                                      devIdentity: true, linkSchemes: ["inktrospect-dev"], linkHosts: [] });
  assert.ok(result.ok);
  return result.config;
})();

const secure = new FakeSecureSessionStore();
const documents = new DiskDocuments(join(WORK, "documents"));

function boot(fetcher: typeof fetch = fetch): Services {
  const ports: NativePorts = {
    secureStore: secure, documents, files: new NodeLocalFiles(config.uploadOrigins, fetcher),
    preparer: new FakeImagePreparer(), capture: new FakeCaptureClient(), downloads: new NodeDownloads(join(WORK, "downloads")),
    share: new FakeFileShareClient(), purchases: null, push: new FakeDevicePushClient(),
    links: new AllowlistedDeepLinkRouter(config.linkSchemes),
  };
  return createServices(config, ports, { fetch: fetcher, timers: { setTimeout, clearTimeout: (h) => clearTimeout(h as never) },
                                          newId: () => randomUUID().replace(/-/g, "").slice(0, 20) });
}

async function until(services: Services, principalId: string, opId: string, phases: readonly string[],
                     timeoutMs = 120_000): Promise<WorkEntry> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    services.runner.kick();
    await services.runner.settle();
    const entry = await services.journal.get(principalId, opId);
    if (entry && phases.includes(entry.phase)) return entry;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${phases.join("/")}: ${JSON.stringify(entry)}`);
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
}

function copyToPrivate(path: string, name: string): string {
  const target = join(WORK, "captures", name);
  mkdirSync(join(WORK, "captures"), { recursive: true });
  writeFileSync(target, readFileSync(path));
  return new URL(`file://${target}`).toString();
}

function step(name: string) {
  console.log(`PASS ${name}`);
}

// 1. Clean install: explicit signed-out state, then a private guest session.
const lossy = lossyFetch(/\/v1\/uploads\/[^/]+\/complete$/);
let app = boot(lossy.fetch);
assert.deepEqual(await app.session.hydrate(), { status: "SIGNED_OUT", reason: "fresh" });
const guest = await app.session.startGuest();
assert.ok(guest.status === "ACTIVE" && guest.kind === "GUEST");
const guestId = guest.principalId;
step("clean install reaches signed-out, then a verified guest session");

// 2. The server's notice text and version, then a journaled capture.
const notices = await app.api.consentNotices("sv-SE");
const notice = notices.find((n) => n.purposes.some((p) => p.purpose_id === "service_processing"));
assert.ok(notice && notice.accepted_for_use && notice.status === "DRAFT");
const sampleUri = copyToPrivate(SAMPLE, "first.png");
const created = await app.workflow.create(guestId, { uri: sampleUri, mediaType: "image/png", width: 900, height: 360,
                                                     source: "LIBRARY" }, notice.notice_version, { retainImage: true });
const digest = createHash("sha256").update(readFileSync(new URL(sampleUri))).digest("hex");
assert.equal(created.local!.sha256, digest, "the journal digest is the digest of the bytes on disk");
step("notice served by the API; capture recorded before any network call");

// 3. Upload with a lost completion response, then the analysis is queued (worker gated).
const first = await until(app, guestId, created.opId, ["STARTED"]);
assert.equal(lossy.dropped(), 1, "the completion response was lost after the server applied it");
assert.equal(first.reservations, 1);
assert.ok(first.captureId && first.runId);
let gone = false;
try { statSync(new URL(sampleUri)); } catch { gone = true; }
assert.ok(gone, "the private copy is removed once the server verified the bytes");
step("lost completion response converged on one capture and one queued run");

// 4. Process death: a new process with the same secure store and private documents resumes the run.
app.runner.stop();
app = boot();
const resumed = await app.session.hydrate();
assert.ok(resumed.status === "ACTIVE" && resumed.principalId === guestId && resumed.verified);
const known = await app.journal.get(guestId, created.opId);
assert.equal(known?.runId, first.runId);
const remote = await app.api.recentAnalyses(10);
assert.ok(remote.some((run) => run.run_id === first.runId && run.state === "QUEUED"), "server-side discovery sees it");
writeFileSync(GATE, "go");  // let the analysis worker start
const done = await until(app, guestId, created.opId, ["SUCCEEDED", "FAILED"]);
assert.equal(done.phase, "SUCCEEDED", JSON.stringify(done));
assert.equal(done.runId, first.runId, "relaunch polled the same run; nothing was started twice");
assert.equal((await app.api.recentAnalyses(10)).length, 1);
step("relaunch resumed the same run from the journal and reached a saved report");

// 5. The saved report renders from the authorized projection only.
const reportId = done.reportId!;
const view = await app.api.report(reportId, "OWNER");
const model = buildDossier(view, "sv");
assert.equal(view.facts.length, 64);
assert.equal(model.sections.reduce((n, s) => n + s.facts.length, 0) + model.highlights.reduce((n, s) => n + s.facts.length, 0),
             view.sections.reduce((n, s) => n + s.fact_ids.length, 0));
assert.ok(model.highlights.length > 0, "server-selected First Reveal present on a current report");
const evidence = await app.api.reportEvidence(reportId);
assert.equal(evidence.analysis.run_id, first.runId);
const image = await app.ports.downloads.download(await app.api.sourceImageDownload(reportId), "source.img",
                                                 { maxBytes: 20 * 1024 * 1024, mediaTypes: ["image/png", "image/jpeg"] });
assert.equal(createHash("sha256").update(readFileSync(new URL(image.uri))).digest("hex"), digest,
             "the retained source image is exactly the uploaded derivative");
step("Dossier model, evidence lineage and retained source image from authorized routes");

// 6. History, a second capture and a same-owner comparison.
const second = await app.workflow.create(guestId, { uri: copyToPrivate(SECOND, "second.png"), mediaType: "image/png",
                                                    width: 900, height: 360, source: "CAMERA" }, notice.notice_version);
const secondDone = await until(app, guestId, second.opId, ["SUCCEEDED", "FAILED"]);
assert.equal(secondDone.phase, "SUCCEEDED");
const history = new HistoryController(app.api);
const page = await history.refresh();
assert.deepEqual(new Set(page.items.map((i) => i.report_id)), new Set([reportId, secondDone.reportId]));
const comparison = presentComparison(await app.api.compare("PAIR", [reportId, secondDone.reportId!]), "en");
assert.ok(comparison.commonCount > 0 && comparison.rows.length > 0);
step("history pages and a deterministic same-owner comparison");

// 7. Feedback is owner-bound and withdrawable.
const receipt = await submitFeedback(app.api, reportId, { category: "MEASUREMENT_LOOKS_WRONG", target: "REPORT",
                                                          targetRef: null, comment: "  synthetic journey note  " },
                                     `fb.${randomUUID().slice(0, 12)}`);
assert.equal(receipt.report_id, reportId);
await app.api.withdrawFeedback(receipt.feedback_id);
step("feedback submitted and withdrawn");

// 8. Optional: authenticated PDF export to a private file.
if (EXPORTS) {
  const exports = new ExportController(app.api, app.ports.downloads, app.ports.share);
  const phase = await exports.prepare(reportId, "A4");
  assert.equal(phase.status, "READY", JSON.stringify(phase));
  if (phase.status === "READY") {
    assert.equal(readFileSync(new URL(phase.file.uri)).subarray(0, 4).toString(), "%PDF");
    assert.equal(await exports.shareAndClean(phase.file), "SHARED");
  }
  step("authorized PDF export downloaded with the bearer credential and shared");
}

// 9. Development sign-in moves the guest's reports to an account (proof of both credentials).
const token = await app.clientFor(null).devIdToken(`journey-${randomUUID().slice(0, 8)}`);
const account = await app.session.signIn(token, "development");
assert.ok(account.status === "ACTIVE" && account.kind === "ACCOUNT" && account.principalId !== guestId);
assert.deepEqual(await app.journal.list(guestId), [], "the guest's local journal is purged on account switch");
const moved = await new HistoryController(app.api).refresh();
assert.ok(moved.items.some((i) => i.report_id === reportId), "the guest's report now belongs to the account");
step("guest-to-account transfer keeps reports and purges guest-local state");

// 10. Report deletion by report ID, then account deletion.
await app.api.deleteReport(secondDone.reportId!);
await assert.rejects(app.api.report(secondDone.reportId!), (e: unknown) => e instanceof ApiError && e.status === 404);
assert.equal(await app.session.deleteAccount(), "DELETION_REQUESTED");
assert.deepEqual(app.session.current(), { status: "SIGNED_OUT", reason: "deleted" });
assert.equal(secure.value, null, "no credential survives account deletion");
await assert.rejects(app.clientFor(token).me(), (e: unknown) => e instanceof ApiError && e.status === 401);
step("report deletion and account deletion end access; the credential is gone");

console.log("PASS mobile live journey");
