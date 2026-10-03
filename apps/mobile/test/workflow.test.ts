import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, TransportError } from "@princess/api-client";

import { FakeKeyValueFile, FakeLocalFiles } from "../src/platform/fakes.ts";
import { CaptureWorkflow, WorkflowError } from "../src/work/capture-workflow.ts";
import { JOURNAL_FILE, WorkJournal, type WorkEntry } from "../src/work/journal.ts";
import { FakeIntakeServer, ManualClock } from "./support/fake-api.ts";

const NOTICE = "notice.consent-choices:1";
const ALICE = "prn_alice";

function world() {
  const clock = new ClockedWorld();
  return clock;
}

class ClockedWorld {
  readonly clock = new ManualClock();
  readonly server = new FakeIntakeServer(this.clock.now);
  readonly disk = new FakeKeyValueFile();
  readonly files = new FakeLocalFiles();
  private ids = 0;
  workflow: CaptureWorkflow;

  constructor() {
    this.files.onUpload = (ticket, bytes) => this.server.put(ticket, bytes);
    this.workflow = this.relaunch();
  }

  /** A new process: fresh in-memory state, same private storage and server. */
  relaunch(): CaptureWorkflow {
    this.workflow = new CaptureWorkflow({ api: this.server, files: this.files, journal: new WorkJournal(this.disk),
                                          now: this.clock.now, newId: () => `id${++this.ids}` });
    return this.workflow;
  }

  image(name = "page") {
    const uri = this.files.add(`file:///private/${name}.jpg`, new TextEncoder().encode(`synthetic ${name} bytes`));
    return { uri, mediaType: "image/jpeg" as const, width: 900, height: 360, source: "LIBRARY" as const };
  }

  async start(name = "page"): Promise<WorkEntry> {
    return this.workflow.create(ALICE, this.image(name), NOTICE);
  }
}

test("happy path reaches a saved report with one slot, one capture, one grant and one run", async () => {
  const w = world();
  const created = await w.start();
  assert.equal(created.phase, "PREPARED");
  const started = await w.workflow.advance(ALICE, created.opId);
  assert.equal(started.phase, "STARTED");
  assert.ok(started.runId);
  assert.equal(w.server.reservations, 1);
  assert.equal(w.server.captures.size, 1);
  assert.equal(w.server.runs.size, 1);
  assert.deepEqual(w.files.uploads.map((u) => u.sha256), [created.local!.sha256], "the digest describes the sent bytes");
  assert.ok(w.files.removed.includes(created.local!.uri), "private bytes removed once the server verified them");

  assert.equal((await w.workflow.poll(ALICE, created.opId)).phase, "STARTED");
  const reportId = w.server.succeed(started.runId!);
  const done = await w.workflow.poll(ALICE, created.opId);
  assert.equal(done.phase, "SUCCEEDED");
  assert.equal(done.reportId, reportId);
});

test("process death plus a lost response at every transition creates no second business result", async () => {
  for (const method of ["reserveUpload", "put", "completeUpload", "recordPermission", "startAnalysis"] as const) {
    const w = world();
    const created = await w.start();
    w.server.lose(method);
    const interrupted = await w.workflow.advance(ALICE, created.opId);
    assert.equal(interrupted.blocked, "RETRY", method);
    assert.equal(interrupted.errorCode, "network", method);
    w.clock.advance(60_000);
    const resumed = await w.relaunch().advance(ALICE, created.opId);
    assert.equal(resumed.phase, "STARTED", method);
    assert.equal(w.server.captures.size, 1, `${method}: one capture`);
    assert.equal(w.server.runs.size, 1, `${method}: one run`);
    assert.equal(new Set(w.server.grants.values()).size, 1, `${method}: one grant record`);
    // Only a lost reservation response costs a second (expiring) slot, and that cost is recorded.
    assert.equal(w.server.reservations, method === "reserveUpload" ? 2 : 1, method);
    assert.equal(resumed.reservations, method === "reserveUpload" ? 2 : 1, method);
  }
});

test("relaunching mid-flight resumes from the journal without repeating finished steps", async () => {
  const w = world();
  const created = await w.start();
  w.server.fail("startAnalysis", new ApiError(503, "unavailable"));
  const blocked = await w.workflow.advance(ALICE, created.opId);
  assert.equal(blocked.phase, "PERMITTED");
  const journal = JSON.parse(w.disk.values.get(JOURNAL_FILE)!) as WorkEntry[];
  assert.equal(journal[0]!.captureId, blocked.captureId);
  assert.equal(JSON.stringify(journal).includes("synthetic page bytes"), false, "no image bytes in the journal");
  w.clock.advance(5_000);
  const resumed = await w.relaunch().advance(ALICE, created.opId);
  assert.equal(resumed.phase, "STARTED");
  assert.equal(w.server.startCalls.length, 1, "the refused start never reached the server effect");
  assert.equal(w.files.uploads.length, 1, "bytes were not sent again");
});

test("an expired slot is replaced before upload and a storage refusal resets the slot", async () => {
  const w = world();
  const created = await w.start();
  w.server.fail("put", new TransportError("TIMEOUT"));
  const retry = await w.workflow.advance(ALICE, created.opId);
  assert.equal(retry.phase, "RESERVED");
  w.clock.advance(16 * 60_000);  // past the 15 minute ticket
  const resumed = await w.workflow.advance(ALICE, created.opId);
  assert.equal(resumed.phase, "STARTED");
  assert.equal(w.server.reservations, 2);

  const v = world();
  const second = await v.start();
  v.server.fail("put", new ApiError(401, "bad_signature"));
  const reset = await v.workflow.advance(ALICE, second.opId);
  assert.equal(reset.phase, "STARTED", "a bad storage signature is a slot problem, not a sign-out");
  assert.equal(v.server.reservations, 2);
});

test("bytes changed after recording are never uploaded under the old digest", async () => {
  const w = world();
  const created = await w.start();
  w.files.files.set(created.local!.uri, new TextEncoder().encode("tampered"));
  const failed = await w.workflow.advance(ALICE, created.opId);
  assert.equal(failed.phase, "FAILED");
  assert.equal(failed.errorCode, "local_file_changed");
  assert.equal(w.files.uploads.length, 0);

  const gone = world();
  const missing = await gone.start();
  gone.files.files.delete(missing.local!.uri);
  assert.equal((await gone.workflow.advance(ALICE, missing.opId)).errorCode, "local_file_missing");
});

test("image refusals are terminal, explained and clean up the private copy", async () => {
  const w = world();
  const created = await w.start();
  w.server.fail("completeUpload", new ApiError(422, "image_dimensions_out_of_range"));
  const failed = await w.workflow.advance(ALICE, created.opId);
  assert.equal(failed.phase, "FAILED");
  assert.equal(failed.errorCode, "image_dimensions_out_of_range");
  assert.ok(w.files.removed.includes(created.local!.uri));
});

test("server back-off, quota and capacity wait instead of looping", async () => {
  const w = world();
  w.server.quota = 0;
  const created = await w.start();
  const quota = await w.workflow.advance(ALICE, created.opId);
  assert.equal(quota.blocked, "WAIT");
  assert.equal(quota.errorCode, "upload_quota_exceeded");
  assert.equal(Date.parse(quota.notBefore!) - w.clock.now().getTime(), 60_000, "Retry-After honoured within a ceiling");
  assert.equal((await w.workflow.advance(ALICE, created.opId)).updatedAt, quota.updatedAt, "no call before notBefore");

  const v = world();
  const second = await v.start();
  v.server.fail("startAnalysis", new ApiError(429, "too_many_active_analyses", 30_000));
  const busy = await v.workflow.advance(ALICE, second.opId);
  assert.equal(busy.phase, "PERMITTED");
  assert.equal(busy.blocked, "WAIT");
  v.clock.advance(30_001);
  assert.equal((await v.workflow.advance(ALICE, second.opId)).phase, "STARTED");
});

test("withdrawn permission and expired sessions stop for the user instead of retrying", async () => {
  const w = world();
  const created = await w.start();
  w.server.fail("startAnalysis", new ApiError(403, "permission_not_granted"));
  const withdrawn = await w.workflow.advance(ALICE, created.opId);
  assert.equal(withdrawn.phase, "COMPLETED");
  assert.equal(withdrawn.blocked, "USER");
  assert.equal((await w.workflow.advance(ALICE, created.opId)).blocked, "USER", "not retried silently");

  const v = world();
  const second = await v.start();
  v.server.fail("reserveUpload", new ApiError(401, "session_revoked"));
  const expired = await v.workflow.advance(ALICE, second.opId);
  assert.equal(expired.errorCode, "signin_required");
  assert.equal(expired.blocked, "USER");

  const n = world();
  const third = await n.workflow.create(ALICE, n.image(), "notice.consent-choices:0");
  const refused = await n.workflow.advance(ALICE, third.opId);
  assert.equal(refused.errorCode, "notice_not_accepted");
  await n.workflow.reconsent(ALICE, third.opId, NOTICE);
  assert.equal((await n.workflow.advance(ALICE, third.opId)).phase, "STARTED");
});

test("keeping the photo is a separate, optional grant recorded once per operation", async () => {
  const w = world();
  const created = await w.workflow.create(ALICE, w.image(), NOTICE, { retainImage: true });
  w.server.lose("recordPermission");
  await w.workflow.advance(ALICE, created.opId);
  w.clock.advance(60_000);
  const started = await w.relaunch().advance(ALICE, created.opId);
  assert.equal(started.phase, "STARTED");
  assert.deepEqual([...w.server.grants.keys()].sort(),
                   [`mobile.${created.opId}.retention`, `mobile.${created.opId}.service`]);
  const plain = world();
  const second = await plain.start();
  await plain.workflow.advance(ALICE, second.opId);
  assert.deepEqual([...plain.server.grants.keys()], [`mobile.${second.opId}.service`], "no retention unless chosen");
});

test("operations are owner-bound: another principal cannot read, drive or cancel them", async () => {
  const w = world();
  const created = await w.start();
  await assert.rejects(w.workflow.advance("prn_bob", created.opId),
                       (e: unknown) => e instanceof WorkflowError && e.code === "operation_not_found");
  assert.deepEqual(await new WorkJournal(w.disk).list("prn_bob"), []);
  assert.equal(w.server.reservations, 0);
});

test("concurrent advances share one run and never double-reserve", async () => {
  const w = world();
  const created = await w.start();
  const [a, b] = await Promise.all([w.workflow.advance(ALICE, created.opId), w.workflow.advance(ALICE, created.opId)]);
  assert.equal(a.phase, "STARTED");
  assert.equal(b.runId, a.runId);
  assert.equal(w.server.reservations, 1);
});

test("explicit cancel and discard are distinct from leaving the screen", async () => {
  const w = world();
  const created = await w.start();
  const started = await w.workflow.advance(ALICE, created.opId);
  const cancelled = await w.workflow.cancel(ALICE, created.opId);
  assert.equal(cancelled.phase, "CANCELLED");
  assert.equal(w.server.runs.get(started.runId!)!.state, "CANCELLED");
  assert.equal((await w.workflow.discard(ALICE, created.opId)).phase, "CANCELLED", "terminal work is left as is");

  const v = world();
  const second = await v.start();
  v.server.fail("recordPermission", new ApiError(503, "unavailable"));
  const completed = await v.workflow.advance(ALICE, second.opId);
  assert.equal(completed.phase, "COMPLETED");
  const discarded = await v.workflow.discard(ALICE, second.opId);
  assert.equal(discarded.phase, "ABANDONED");
  assert.equal(v.server.captures.get(completed.captureId!)!.deleted, true, "the verified capture is deleted on request");
  assert.equal(v.server.runs.size, 0);
});

test("a failed or deleted run is reported, never retried into a second analysis", async () => {
  const w = world();
  const created = await w.start();
  const started = await w.workflow.advance(ALICE, created.opId);
  w.server.runs.get(started.runId!)!.state = "FAILED";
  w.server.runs.get(started.runId!)!.error = "engine_rejected_image";
  const failed = await w.workflow.poll(ALICE, created.opId);
  assert.equal(failed.phase, "FAILED");
  assert.equal(failed.errorCode, "engine_rejected_image");
  assert.equal(w.server.startCalls.length, 1);

  const v = world();
  const second = await v.start();
  const run = await v.workflow.advance(ALICE, second.opId);
  v.server.captures.get(run.captureId!)!.deleted = true;
  assert.equal((await v.workflow.poll(ALICE, second.opId)).errorCode, "run_not_found");
});

test("a poll timeout is retried later, not reported as a failed analysis", async () => {
  const w = world();
  const created = await w.start();
  await w.workflow.advance(ALICE, created.opId);
  w.server.fail("analysis", new TransportError("TIMEOUT"));
  const waiting = await w.workflow.poll(ALICE, created.opId);
  assert.equal(waiting.phase, "STARTED");
  assert.equal(waiting.blocked, "RETRY");
});
