import assert from "node:assert/strict";
import test from "node:test";

import { NativeSessionBoundary } from "../src/bootstrap/session.ts";
import { FakeSecureSessionStore } from "../src/platform/fakes.ts";

test("late response from prior principal is discarded after account switch", async () => {
  const session = new NativeSessionBoundary(new FakeSecureSessionStore());
  let resolve!: (value: string) => void;
  const work = new Promise<string>((done) => { resolve = done; });
  const guarded = session.guard(work);
  await session.switchPrincipal("credential_b");
  resolve("report_from_a");
  assert.equal(await guarded, null);
});

test("token rotation invalidates old in-flight work and keeps only the new credential", async () => {
  const store = new FakeSecureSessionStore();
  const session = new NativeSessionBoundary(store);
  await session.switchPrincipal("credential_v1");
  let resolve!: (value: string) => void;
  const oldWork = new Promise<string>((done) => { resolve = done; });
  const guarded = session.guard(oldWork);
  await session.switchPrincipal("credential_v2");
  resolve("stale");
  assert.equal(await guarded, null);
  assert.equal(await store.read(), "credential_v2");
});

test("process restart reconstructs a boundary from secure-store state without retaining in-memory work", async () => {
  const store = new FakeSecureSessionStore();
  const first = new NativeSessionBoundary(store);
  await first.switchPrincipal("credential_persisted");
  const afterRestart = new NativeSessionBoundary(store);
  assert.notEqual(first.epoch, afterRestart.epoch);
  assert.equal(await store.read(), "credential_persisted");
});
