import assert from "node:assert/strict";
import test from "node:test";

import { FakeKeyValueFile, FakeLocalFiles } from "../src/platform/fakes.ts";
import { CaptureWorkflow } from "../src/work/capture-workflow.ts";
import { WorkJournal } from "../src/work/journal.ts";
import { WorkRunner } from "../src/work/runner.ts";
import { FakeIntakeServer, ManualClock, ManualTimers } from "./support/fake-api.ts";

function setup() {
  const clock = new ManualClock();
  const server = new FakeIntakeServer(clock.now);
  const files = new FakeLocalFiles();
  files.onUpload = (ticket, bytes) => server.put(ticket, bytes);
  const journal = new WorkJournal(new FakeKeyValueFile());
  let ids = 0;
  const workflow = new CaptureWorkflow({ api: server, files, journal, now: clock.now, newId: () => `id${++ids}` });
  const timers = new ManualTimers(clock);
  const runner = new WorkRunner(workflow, journal, timers, clock.now);
  const image = (name: string) => ({ uri: files.add(`file:///private/${name}.jpg`, new TextEncoder().encode(name)),
                                     mediaType: "image/jpeg" as const, width: 900, height: 360,
                                     source: "CAMERA" as const });
  return { clock, server, files, journal, workflow, timers, runner, image };
}

test("the runner drives new work to a saved report with bounded polling", async () => {
  const w = setup();
  const created = await w.workflow.create("prn_a", w.image("a"), "notice.consent-choices:1");
  const seen: string[] = [];
  w.runner.subscribe((entries) => { if (entries[0]) seen.push(entries[0].phase); });
  w.runner.start("prn_a");
  await w.runner.settle();
  assert.equal(seen.at(-1), "STARTED");
  const runId = [...w.server.runs.keys()][0]!;
  assert.ok(w.timers.pending.size === 1, "one scheduled poll, never a tight loop");
  w.timers.fireNext();
  await w.runner.settle();
  w.server.succeed(runId);
  for (let i = 0; i < 3 && seen.at(-1) !== "SUCCEEDED"; i += 1) {
    w.timers.fireNext();
    await w.runner.settle();
  }
  assert.equal(seen.at(-1), "SUCCEEDED");
  assert.equal(w.timers.pending.size, 0, "nothing scheduled once every operation is terminal");
  assert.equal((await w.journal.get("prn_a", created.opId))!.reportId, `report_${runId}`);
});

test("suspension stops timers and foregrounding reconciles at once", async () => {
  const w = setup();
  await w.workflow.create("prn_a", w.image("a"), "notice.consent-choices:1");
  w.runner.start("prn_a");
  await w.runner.settle();
  w.runner.suspend();
  assert.equal(w.timers.pending.size, 0);
  w.server.succeed([...w.server.runs.keys()][0]!);
  w.runner.resume();
  await w.runner.settle();
  assert.equal(w.runner.snapshot()[0]!.phase, "SUCCEEDED");
});

test("switching principal stops the old work and never touches it for the new principal", async () => {
  const w = setup();
  await w.workflow.create("prn_a", w.image("a"), "notice.consent-choices:1");
  w.runner.start("prn_b");
  await w.runner.settle();
  assert.equal(w.server.reservations, 0);
  assert.deepEqual(w.runner.snapshot(), []);
  w.runner.stop();
  assert.equal(w.timers.pending.size, 0);
});
