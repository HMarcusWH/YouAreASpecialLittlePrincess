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
