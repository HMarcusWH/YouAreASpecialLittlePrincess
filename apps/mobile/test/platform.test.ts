import assert from "node:assert/strict";
import test from "node:test";

import {
  AllowlistedDeepLinkRouter, FakeAbuseAttestation, FakeCaptureClient, FakeFileShareClient,
  FakeNativeIdentityTransport, FakeNativePurchaseClient, FakePushRegistration, FakeSecureSessionStore,
} from "../src/platform/fakes.ts";

test("secure session fake clears credential material on switch/logout", async () => {
  const store = new FakeSecureSessionStore();
  await store.write("secret");
  assert.equal(await store.read(), "secret");
  await store.clear();
  assert.equal(await store.read(), null);
});

test("capture fake preserves permission denial rather than fabricating a capture", async () => {
  const capture = new FakeCaptureClient();
  capture.camera = "DENIED";
  capture.next = {
    localUri: "file:///synthetic.jpg", width: 100, height: 100, mimeType: "image/jpeg",
    source: "CAMERA", originalMimeType: "image/heic", fileName: "synthetic.heic", orientationMetadata: "PRESENT",
  };
  assert.equal(await capture.takePhoto(), null);
});

test("purchase fake models store proof then authoritative grant before finish", async () => {
  const pending = new FakeNativePurchaseClient();
  pending.products.set("credit_1", { productId: "credit_1", displayPrice: "TEST" });
  pending.nextState = "PENDING";
  const pendingObservation = await pending.beginPurchase("credit_1");
  assert.equal(pendingObservation.state, "PENDING");
  assert.equal(pendingObservation.proof, null);
  assert.equal(pending.finished.length, 0);

  const purchase = new FakeNativePurchaseClient();
  purchase.products.set("credit_1", { productId: "credit_1", displayPrice: "TEST" });
  purchase.nextState = "PROOF_READY";
  const observation = await purchase.beginPurchase("credit_1");
  assert.ok(observation.proof);
  const proof = observation.proof;

  await assert.rejects(() => purchase.finishAfterServerGrant(proof), /server_grant_required/);
  assert.equal(purchase.finished.length, 0);

  purchase.recordServerGrant(proof);
  await purchase.finishAfterServerGrant(proof);
  await purchase.finishAfterServerGrant(proof);
  assert.deepEqual(purchase.finished, ["proof:credit_1"]);
  assert.deepEqual(await purchase.recoverPendingTransactions(), []);

  assert.throws(() => purchase.recordServerGrant("proof:unknown"), /unknown_purchase_proof/);
});

test("deep link router fails closed for foreign schemes and malformed resources", () => {
  const links = new AllowlistedDeepLinkRouter(new Set(["inktrospect-dev"]));
  assert.deepEqual(links.resolve("inktrospect-dev://reports/report_123"), { kind: "REPORT", reportId: "report_123" });
  assert.deepEqual(links.resolve("inktrospect-dev://history"), { kind: "HISTORY" });
  assert.equal(links.resolve("https://evil.example/reports/report_123"), null);
  assert.equal(links.resolve("not a url"), null);
});

test("push/account switch and file cleanup fakes expose lifecycle state", async () => {
  const push = new FakePushRegistration();
  assert.ok(await push.register("principal_a"));
  await push.clear();
  assert.equal(push.current, null);

  const files = new FakeFileShareClient();
  assert.equal(await files.shareAuthorizedFile("file:///export.pdf"), "SHARED");
  await files.cleanup("file:///export.pdf");
  assert.deepEqual(files.cleaned, ["file:///export.pdf"]);

  const abuse = new FakeAbuseAttestation();
  assert.equal((await abuse.attest("upload", "nonce")).status, "UNAVAILABLE");
});

test("unavailable camera fails closed", async () => {
  const capture = new FakeCaptureClient();
  capture.camera = "UNAVAILABLE";
  capture.next = {
    localUri: "file:///should-not-return.jpg", width: 100, height: 100, mimeType: "image/jpeg",
    source: "CAMERA", originalMimeType: "image/heic", fileName: "blocked.heic", orientationMetadata: "UNKNOWN",
  };
  assert.equal(await capture.takePhoto(), null);
});

test("identity transport is external-user-agent shaped and carries no provider secret", async () => {
  const identity = new FakeNativeIdentityTransport();
  identity.next = {
    status: "SUCCESS",
    callbackUrl: "inktrospect-dev://auth/callback?code=test&state=state_1",
  };
  const result = await identity.authorize({
    authorizationUrl: "https://identity.example/authorize?code_challenge=test",
    redirectUrl: "inktrospect-dev://auth/callback",
    expectedState: "state_1",
  });
  assert.equal(result.status, "SUCCESS");
  assert.equal(identity.requests.length, 1);
  assert.ok(!JSON.stringify(identity.requests[0]).toLowerCase().includes("client_secret"));
});
