import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  SESSION_COOKIE,
  SESSION_MAX_AGE_S,
  clearedCredentialCookie,
  credentialCookie,
  devCredentialIssuanceEnabled,
  webEnvironment,
  type WebEnvironment,
} from "../lib/session-policy.ts";

test("web credential cookie is HttpOnly/SameSite and Secure outside local/test", () => {
  const environments: WebEnvironment[] = ["local", "test", "preview", "staging", "production"];
  for (const environment of environments) {
    const cookie = credentialCookie("opaque-credential", environment);
    assert.equal(cookie.name, SESSION_COOKIE);
    assert.equal(cookie.value, "opaque-credential");
    assert.equal(cookie.httpOnly, true);
    assert.equal(cookie.sameSite, "lax");
    assert.equal(cookie.path, "/");
    assert.equal(cookie.maxAge, SESSION_MAX_AGE_S);
    assert.equal(cookie.secure, environment !== "local" && environment !== "test");
  }
});

test("clearing a credential uses the exact same cookie identity/security policy", () => {
  for (const environment of ["local", "test", "preview", "staging", "production"] as const) {
    const issued = credentialCookie("opaque", environment);
    const cleared = clearedCredentialCookie(environment);
    assert.deepEqual(
      {
        name: cleared.name,
        httpOnly: cleared.httpOnly,
        sameSite: cleared.sameSite,
        path: cleared.path,
        secure: cleared.secure,
      },
      {
        name: issued.name,
        httpOnly: issued.httpOnly,
        sameSite: issued.sameSite,
        path: issued.path,
        secure: issued.secure,
      },
    );
    assert.equal(cleared.value, "");
    assert.equal(cleared.maxAge, 0);
  }
});

test("web environment is bounded and dev credential issuance stays local/test only", () => {
  assert.equal(webEnvironment(undefined), "local");
  for (const environment of ["local", "test", "preview", "staging", "production"] as const) {
    assert.equal(webEnvironment(environment), environment);
    assert.equal(devCredentialIssuanceEnabled(environment), environment === "local" || environment === "test");
  }
  assert.throws(() => webEnvironment("prod-ish"), /invalid_web_environment/);
  assert.throws(() => credentialCookie("", "test"), /empty_session_credential/);
});

test("server credential transport stays opaque and server-only", () => {
  const session = readFileSync(new URL("../lib/session.ts", import.meta.url), "utf8");
  const proxy = readFileSync(new URL("../app/api/v1/[...path]/route.ts", import.meta.url), "utf8");
  const logout = readFileSync(new URL("../app/api/session/logout/route.ts", import.meta.url), "utf8");

  assert.match(session, /import "server-only"/);
  assert.match(session, /sessionCredential/);
  assert.doesNotMatch(session, /localStorage|sessionStorage/);
  assert.doesNotMatch(session, /supabase|clerk|jwt\.|decode/i);

  assert.match(proxy, /const credential = await sessionCredential\(\)/);
  assert.match(proxy, /authorization = `Bearer \$\{credential\}`/);
  assert.doesNotMatch(proxy, /supabase|clerk|jwt\.|decode/i);

  assert.match(logout, /clearedCredentialCookie\(\)/);
  assert.match(logout, /logout-everywhere/);
});
