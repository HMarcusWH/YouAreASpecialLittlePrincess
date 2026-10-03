import assert from "node:assert/strict";
import test from "node:test";

import { originOf, queryParam } from "@princess/api-client";

import {
  validateNativeAuthorizationCallback,
  validateNativeAuthorizationRequest,
} from "../src/platform/native/identity-policy.ts";

const allowedOrigins = new Set(["https://identity.example"]);
const allowedSchemes = new Set(["inktrospect-dev"]);
const request = {
  authorizationUrl: "https://identity.example/authorize?code_challenge=test",
  redirectUrl: "inktrospect-dev://auth/callback",
  expectedState: "state_1",
};

test("native authorization policy accepts the configured HTTPS origin and redirect", () => {
  const validated = validateNativeAuthorizationRequest(request, allowedOrigins, allowedSchemes);
  assert.equal(originOf(validated.authorization), "https://identity.example");
  assert.equal(validated.redirect.scheme, "inktrospect-dev");
});

test("native authorization policy rejects non-HTTPS and foreign authorization origins", () => {
  assert.throws(
    () => validateNativeAuthorizationRequest(
      { ...request, authorizationUrl: "http://identity.example/authorize" },
      allowedOrigins,
      allowedSchemes,
    ),
    /identity_authorization_origin_not_allowed/,
  );
  assert.throws(
    () => validateNativeAuthorizationRequest(
      { ...request, authorizationUrl: "https://evil.example/authorize" },
      allowedOrigins,
      allowedSchemes,
    ),
    /identity_authorization_origin_not_allowed/,
  );
});

test("native authorization policy rejects foreign redirect schemes", () => {
  assert.throws(
    () => validateNativeAuthorizationRequest(
      { ...request, redirectUrl: "evil-app://auth/callback" },
      allowedOrigins,
      allowedSchemes,
    ),
    /identity_redirect_scheme_not_allowed/,
  );
});

test("native authorization callback binds scheme host port and path to the requested redirect", () => {
  const callback = validateNativeAuthorizationCallback(
    "inktrospect-dev://auth/callback?code=test&state=state_1",
    request.redirectUrl,
    request.expectedState,
  );
  assert.equal(queryParam(callback, "code"), "test");

  assert.throws(
    () => validateNativeAuthorizationCallback(
      "inktrospect-dev://evil/callback?code=test&state=state_1",
      request.redirectUrl,
      request.expectedState,
    ),
    /identity_callback_redirect_mismatch/,
  );
  assert.throws(
    () => validateNativeAuthorizationCallback(
      "inktrospect-dev://auth/other?code=test&state=state_1",
      request.redirectUrl,
      request.expectedState,
    ),
    /identity_callback_redirect_mismatch/,
  );
  assert.throws(
    () => validateNativeAuthorizationCallback(
      "inktrospect-dev://auth:1234/callback?code=test&state=state_1",
      request.redirectUrl,
      request.expectedState,
    ),
    /identity_callback_redirect_mismatch/,
  );
});

test("native authorization callback rejects state mismatch and malformed URLs", () => {
  assert.throws(
    () => validateNativeAuthorizationCallback(
      "inktrospect-dev://auth/callback?code=test&state=wrong",
      request.redirectUrl,
      request.expectedState,
    ),
    /identity_state_mismatch/,
  );
  assert.throws(
    () => validateNativeAuthorizationCallback(
      "not a callback url",
      request.redirectUrl,
      request.expectedState,
    ),
    /identity_callback_url_invalid/,
  );
});

test("validation does not depend on the runtime URL class (React Native's is an approximation)", () => {
  const original = globalThis.URL;
  // React Native's URL never throws and reports "" host / "/" path for custom schemes; forbid its use entirely.
  (globalThis as { URL: unknown }).URL = class { constructor() { throw new Error("runtime URL must not be used"); } };
  try {
    assert.throws(
      () => validateNativeAuthorizationCallback("inktrospect-dev://evil/callback?code=x&state=state_1",
                                                request.redirectUrl, request.expectedState),
      /identity_callback_redirect_mismatch/,
    );
    assert.equal(queryParam(validateNativeAuthorizationCallback(
      "inktrospect-dev://auth/callback?state=state_1&code=a%2Bb", request.redirectUrl, request.expectedState), "code"), "a+b");
    assert.throws(() => validateNativeAuthorizationRequest({ ...request, authorizationUrl: "https://identity.example@evil.example/a" },
                                                          allowedOrigins, allowedSchemes),
                  /identity_authorization_origin_not_allowed/);
  } finally {
    (globalThis as { URL: unknown }).URL = original;
  }
});
