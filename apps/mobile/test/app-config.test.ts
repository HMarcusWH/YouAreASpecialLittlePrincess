import assert from "node:assert/strict";
import test from "node:test";

import appConfig from "../app.config.ts";
import { parseRuntimeConfig } from "../src/config/runtime.ts";

function build(env: Record<string, string>) {
  const saved = { ...process.env };
  for (const key of Object.keys(process.env)) if (key.startsWith("INKTROSPECT_")) delete process.env[key];
  Object.assign(process.env, env);
  try {
    return appConfig({ config: {} } as never);
  } finally {
    for (const key of Object.keys(process.env)) if (key.startsWith("INKTROSPECT_")) delete process.env[key];
    Object.assign(process.env, saved);
  }
}

test("a store build targets production over HTTPS with no development identity", () => {
  const config = build({ INKTROSPECT_APP_VARIANT: "store", INKTROSPECT_API_BASE: "https://api.inktrospect.se",
                         INKTROSPECT_LINK_HOSTS: "inktrospect.se" });
  const runtime = parseRuntimeConfig((config.extra as { runtime: unknown }).runtime);
  assert.ok(runtime.ok, JSON.stringify(runtime));
  assert.equal(runtime.config.devIdentity, false);
  assert.equal(config.ios?.bundleIdentifier, "se.inktrospect");
  assert.deepEqual(config.ios?.associatedDomains, ["applinks:inktrospect.se"]);
  assert.equal((config.ios?.infoPlist as Record<string, unknown>).NSAppTransportSecurity, undefined);
  assert.equal(config.android?.intentFilters?.[0]?.autoVerify, true);
  const http = build({ INKTROSPECT_APP_VARIANT: "store", INKTROSPECT_API_BASE: "http://api.inktrospect.se" });
  assert.deepEqual(parseRuntimeConfig((http.extra as { runtime: unknown }).runtime),
                   { ok: false, code: "config_api_base_not_https" });
});

test("development builds reach a LAN API and only they carry the development identity path", () => {
  const config = build({ INKTROSPECT_API_BASE: "http://192.168.1.20:8000" });
  const runtime = parseRuntimeConfig((config.extra as { runtime: unknown }).runtime);
  assert.ok(runtime.ok && runtime.config.devIdentity);
  assert.equal(config.scheme, "inktrospect-dev");
  const staging = build({ INKTROSPECT_APP_VARIANT: "staging", INKTROSPECT_API_BASE: "https://staging-api.inktrospect.se" });
  const stagingRuntime = parseRuntimeConfig((staging.extra as { runtime: unknown }).runtime);
  assert.ok(stagingRuntime.ok && !stagingRuntime.config.devIdentity);
  assert.throws(() => build({ INKTROSPECT_APP_VARIANT: "beta" }), /INKTROSPECT_APP_VARIANT/);
});

test("broad media and microphone permissions are blocked; the picker needs none", () => {
  const config = build({ INKTROSPECT_API_BASE: "http://127.0.0.1:8000" });
  for (const permission of ["android.permission.RECORD_AUDIO", "android.permission.READ_MEDIA_IMAGES",
                            "android.permission.READ_EXTERNAL_STORAGE"]) {
    assert.ok(config.android?.blockedPermissions?.includes(permission), permission);
  }
  const picker = (config.plugins ?? []).find((p) => Array.isArray(p) && p[0] === "expo-image-picker") as [string, Record<string, unknown>];
  assert.equal(picker[1].microphonePermission, false);
  assert.equal(picker[1].photosPermission, false);
});
