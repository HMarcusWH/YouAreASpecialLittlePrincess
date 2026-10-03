import assert from "node:assert/strict";
import test from "node:test";

import { ApiError } from "@princess/api-client";

import { PushController, routeForNotification } from "../src/features/push-controller.ts";
import {
  FakeAbuseAttestation, FakeCaptureClient, FakeDevicePushClient, FakeFileShareClient,
  FakeKeyValueFile, FakeNativeIdentityTransport, FakeNativePurchaseClient, FakeSecureSessionStore,
} from "../src/platform/fakes.ts";
import { AllowlistedDeepLinkRouter, pathFor } from "../src/platform/links.ts";

const picked = { uri: "file:///picker/synthetic.heic", width: 4032, height: 3024, mimeType: "image/heic",
                 fileName: "synthetic.heic", fileSize: 2_000_000, source: "CAMERA" as const };

test("secure session fake clears credential material on switch/logout", async () => {
  const store = new FakeSecureSessionStore();
  await store.write("secret");
  assert.equal(await store.read(), "secret");
  await store.clear();
  assert.equal(await store.read(), null);
});

test("capture preserves denial, unavailability and cancellation rather than fabricating a capture", async () => {
  const capture = new FakeCaptureClient();
  capture.next = picked;
  capture.camera = "DENIED";
  assert.deepEqual(await capture.takePhoto(), { status: "DENIED", canAskAgain: false });
  capture.camera = "UNAVAILABLE";
  assert.deepEqual(await capture.takePhoto(), { status: "UNAVAILABLE" });
  capture.cancelNext = true;
  assert.deepEqual(await capture.pickPhoto(), { status: "CANCELLED" });
  capture.cancelNext = false;
  const library = await capture.pickPhoto();
  assert.equal(library.status === "SELECTED" && library.image.source, "LIBRARY");
});

test("purchase fake models store proof then authoritative grant before finish", async () => {
  const pending = new FakeNativePurchaseClient();
  await pending.connect();
  pending.nextState = "PENDING";
  const pendingObservation = await pending.beginPurchase("credit_1", "acct-uuid-1");
  assert.equal(pendingObservation.state, "PENDING");
  assert.equal(pendingObservation.proof, null);
  assert.equal(pending.finished.length, 0);

  const purchase = new FakeNativePurchaseClient();
  await purchase.connect();
  const observation = await purchase.beginPurchase("credit_1", "acct-uuid-1");
  assert.ok(observation.proof);
  await assert.rejects(() => purchase.finishAfterServerGrant(observation), /server_grant_required/);
  assert.equal(purchase.finished.length, 0);
  purchase.recordServerGrant(observation.proof);
  await purchase.finishAfterServerGrant(observation);
  await purchase.finishAfterServerGrant(observation);
  assert.equal(purchase.finished.length, 1);
  assert.deepEqual(await purchase.recoverPendingTransactions(), []);
  assert.throws(() => purchase.recordServerGrant("proof:unknown"), /unknown_purchase_proof/);

  const offline = new FakeNativePurchaseClient();
  offline.available = false;
  assert.equal(await offline.connect(), false);
  assert.equal((await offline.beginPurchase("credit_1", "acct")).state, "UNAVAILABLE");
});

test("deep links fail closed for foreign schemes, unverified hosts and malformed resources", () => {
  const links = new AllowlistedDeepLinkRouter(new Set(["inktrospect-dev"]), new Set(["inktrospect.se"]));
  assert.deepEqual(links.resolve("inktrospect-dev://reports/report_123"), { kind: "REPORT", reportId: "report_123" });
  assert.deepEqual(links.resolve("https://inktrospect.se/reports/report_123"), { kind: "REPORT", reportId: "report_123" });
  assert.deepEqual(links.resolve("inktrospect-dev://history"), { kind: "HISTORY" });
  assert.deepEqual(links.resolve("inktrospect-dev://settings"), { kind: "SETTINGS" });
  assert.equal(links.resolve("https://evil.example/reports/report_123"), null);
  assert.equal(links.resolve("https://inktrospect.se:8443/reports/report_123"), null);
  assert.equal(links.resolve("evil-app://reports/report_123"), null);
  assert.equal(links.resolve("inktrospect-dev://reports/report_123/extra"), null);
  assert.equal(links.resolve("inktrospect-dev://reports/..%2Fadmin"), null);
  assert.equal(links.resolve("https://user:pw@inktrospect.se/reports/r1"), null);
  assert.equal(links.resolve("not a url"), null);
  assert.equal(pathFor(links.resolve("inktrospect-dev://reports/report_123")), "/reports/report_123");
  assert.equal(pathFor(links.resolve("https://evil.example/reports/report_123")), "/");
});

test("push registration is contextual, principal-bound and survives denial", async () => {
  const device = new FakeDevicePushClient();
  const file = new FakeKeyValueFile();
  const calls: unknown[] = [];
  const api = {
    registerPush: async (body: unknown) => { calls.push(["register", body]); return "inst_1"; },
    unregisterPush: async (id: string) => { calls.push(["unregister", id]); },
  };
  const push = new PushController(api, device, file, "local");
  assert.equal(await push.status("prn_a"), "NOT_REGISTERED");
  assert.equal(await push.enable("prn_a", "sv"), "REGISTERED");
  assert.deepEqual(calls[0], ["register", { device_token: "fcm-device-token-0001", platform: "fcm",
                                            app_environment: "local", locale: "sv" }]);
  assert.equal(await push.refresh("prn_a", "sv"), "REGISTERED");
  assert.equal(calls.length, 1, "same token: no re-registration");
  device.rotate({ token: "fcm-device-token-0002", platform: "fcm" });
  assert.equal(await push.refresh("prn_a", "sv"), "REGISTERED");
  assert.equal(calls.length, 2, "rotated token re-binds");
  await push.forget("prn_a");
  assert.deepEqual(calls[2], ["unregister", "inst_1"]);
  assert.equal(await push.status("prn_a"), "NOT_REGISTERED");
  assert.equal(await push.refresh("prn_b", "en"), "NOT_REGISTERED", "another principal never inherits the binding");

  device.state = "DENIED";
  assert.equal(await push.enable("prn_a", "en"), "DENIED");
  assert.equal(calls.length, 3, "a denial never reaches the API");

  const failing = new PushController({ registerPush: async () => { throw new ApiError(422, "environment_mismatch"); },
                                       unregisterPush: async () => undefined },
                                     new FakeDevicePushClient(), new FakeKeyValueFile(), "production");
  assert.equal(await failing.enable("prn_a", "en"), "FAILED");
});

test("a notification selects a resource but never authorizes it", () => {
  assert.deepEqual(routeForNotification({ type: "report_ready", reference: "report_1" }),
                   { kind: "REPORT", reportId: "report_1" });
  assert.deepEqual(routeForNotification({ type: "report_ready", reference: "../x" }), { kind: "HISTORY" });
  assert.equal(routeForNotification({ type: "balance_changed", reference: "5" }), null);
});

test("file sharing exposes cancellation, unavailability and explicit cleanup", async () => {
  const files = new FakeFileShareClient();
  assert.equal(await files.shareAuthorizedFile("file:///export.pdf", "application/pdf"), "SHARED");
  files.cancel = true;
  assert.equal(await files.shareAuthorizedFile("file:///export.pdf", "application/pdf"), "CANCELLED");
  files.available = false;
  assert.equal(await files.shareAuthorizedFile("file:///export.pdf", "application/pdf"), "UNAVAILABLE");
  await files.cleanup("file:///export.pdf");
  assert.deepEqual(files.cleaned, ["file:///export.pdf"]);
  const abuse = new FakeAbuseAttestation();
  assert.equal((await abuse.attest("upload", "nonce")).status, "UNAVAILABLE");
});

test("identity transport is external-user-agent shaped and carries no provider secret", async () => {
  const identity = new FakeNativeIdentityTransport();
  identity.next = { status: "SUCCESS", callbackUrl: "inktrospect-dev://auth/callback?code=test&state=state_1" };
  const result = await identity.authorize({
    authorizationUrl: "https://identity.example/authorize?code_challenge=test",
    redirectUrl: "inktrospect-dev://auth/callback",
    expectedState: "state_1",
  });
  assert.equal(result.status, "SUCCESS");
  assert.equal(identity.requests.length, 1);
  assert.ok(!JSON.stringify(identity.requests[0]).toLowerCase().includes("client_secret"));
});
