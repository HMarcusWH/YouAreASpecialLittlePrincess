import assert from "node:assert/strict";
import test from "node:test";

import { parseRuntimeConfig } from "../src/config/runtime.ts";

const dev = { variant: "development", backendEnvironment: "local", apiBaseUrl: "http://192.168.1.20:8000",
              devIdentity: true, linkSchemes: ["inktrospect-dev"], linkHosts: [] };

test("development builds may use a LAN API and the development identity helper", () => {
  const result = parseRuntimeConfig(dev);
  assert.ok(result.ok);
  assert.equal(result.config.apiBaseUrl, "http://192.168.1.20:8000");
  assert.deepEqual([...result.config.uploadOrigins], ["http://192.168.1.20:8000"]);
  assert.equal(result.config.devIdentity, true);
});

test("release builds require HTTPS, a matching backend and no development authority", () => {
  const store = { variant: "store", backendEnvironment: "production", apiBaseUrl: "https://api.inktrospect.se",
                  linkSchemes: ["inktrospect"], linkHosts: ["inktrospect.se"] };
  assert.ok(parseRuntimeConfig(store).ok);
  assert.deepEqual(parseRuntimeConfig({ ...store, apiBaseUrl: "http://api.inktrospect.se" }),
                   { ok: false, code: "config_api_base_not_https" });
  assert.deepEqual(parseRuntimeConfig({ ...store, devIdentity: true }),
                   { ok: false, code: "config_dev_identity_not_allowed" });
  assert.deepEqual(parseRuntimeConfig({ ...store, backendEnvironment: "staging" }),
                   { ok: false, code: "config_store_backend_invalid" });
  assert.deepEqual(parseRuntimeConfig({ ...dev, backendEnvironment: "production" }),
                   { ok: false, code: "config_development_backend_invalid" });
  assert.deepEqual(parseRuntimeConfig({ ...dev, apiBaseUrl: "http://api.example.com" }),
                   { ok: false, code: "config_api_base_not_https" });
  assert.deepEqual(parseRuntimeConfig({ ...dev, backendEnvironment: "preview", devIdentity: true }),
                   { ok: false, code: "config_dev_identity_not_allowed" });
});

test("missing or malformed configuration fails closed with a code", () => {
  assert.deepEqual(parseRuntimeConfig(undefined), { ok: false, code: "config_variant_invalid" });
  assert.deepEqual(parseRuntimeConfig({ ...dev, apiBaseUrl: "" }), { ok: false, code: "config_api_base_missing" });
  assert.deepEqual(parseRuntimeConfig({ ...dev, apiBaseUrl: "https://user:pw@api.example" }),
                   { ok: false, code: "config_api_base_invalid" });
  assert.deepEqual(parseRuntimeConfig({ ...dev, uploadOrigins: ["ftp://x"] }),
                   { ok: false, code: "config_upload_origin_invalid" });
  const withUploads = parseRuntimeConfig({ ...dev, uploadOrigins: ["https://uploads.example"] });
  assert.ok(withUploads.ok && withUploads.config.uploadOrigins.has("https://uploads.example"));
});

test("private v3 exports only exist in explicit development/local or development/test builds", () => {
  const enabled = parseRuntimeConfig({ ...dev, privateV3Exports: true });
  assert.ok(enabled.ok && enabled.config.privateV3Exports === true);
  assert.equal(parseRuntimeConfig({ ...dev }).ok, true);
  const denied = [
    { ...dev, variant: "store", backendEnvironment: "production", apiBaseUrl: "https://api.example.invalid",
      devIdentity: false, privateV3Exports: true },
    { ...dev, backendEnvironment: "preview", devIdentity: false, privateV3Exports: true },
    { ...dev, devIdentity: false, privateV3Exports: true },
  ];
  for (const candidate of denied) {
    assert.deepEqual(parseRuntimeConfig(candidate), { ok: false, code: "config_private_v3_not_allowed" });
  }
  assert.deepEqual(parseRuntimeConfig({ ...dev, privateV3Exports: "true" }),
                   { ok: false, code: "config_private_v3_invalid" });
});
