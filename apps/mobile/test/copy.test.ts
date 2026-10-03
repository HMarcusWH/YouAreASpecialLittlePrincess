import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { t as reportText } from "@princess/report-core";

import { COPY_KEYS, copy, resolveLocale } from "../src/i18n/copy.ts";

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : /\.tsx?$/.test(name) ? [path] : [];
  });
}

const root = new URL("..", import.meta.url).pathname;

test("every literal app copy key used by a screen exists, with a Swedish translation", () => {
  const known = new Set<string>(COPY_KEYS);
  const missing: string[] = [];
  for (const file of [...files(join(root, "app")), ...files(join(root, "src"))]) {
    const source = readFileSync(file, "utf8");
    for (const match of source.matchAll(/\bt\("([a-z_]+\.[A-Za-z0-9_.]+)"\)/g)) {
      if (!known.has(match[1]!)) missing.push(`${file}: ${match[1]}`);
    }
  }
  assert.deepEqual(missing, []);
  for (const key of COPY_KEYS) assert.notEqual(copy("sv", key), key, key);
});

test("dynamic copy families resolve for every value the app can show", () => {
  for (const phase of ["PREPARED", "RESERVED", "UPLOADED", "COMPLETED", "PERMITTED", "STARTED", "SUCCEEDED", "FAILED",
                       "CANCELLED", "ABANDONED"]) {
    assert.notEqual(copy("en", `work.${phase}`), `work.${phase}`);
  }
  for (const kind of ["INDIVIDUAL", "PAIR", "HISTORY"]) assert.notEqual(copy("sv", `history.kind.${kind}`), kind);
  for (const reason of ["ABSENT", "UNAVAILABLE", "NON_NUMERIC", "UNIT_MISMATCH", "DOMAIN_UNIT_MISMATCH",
                        "METHOD_ID_MISMATCH", "METHOD_VERSION_MISMATCH", "FORMATTING_MISMATCH"]) {
    assert.notEqual(copy("sv", `compare.reason.${reason}`), `compare.reason.${reason}`);
  }
  for (const state of ["ANSWERED", "OBSERVED_ABSENT", "NOT_ASSESSABLE", "NOT_APPLICABLE", "CONFLICTING_EVIDENCE",
                       "NO_ELIGIBLE_CANDIDATE"]) {
    assert.notEqual(reportText("sv", `premium.answer.${state}`), `premium.answer.${state}`);
  }
  assert.equal(copy("en", "no.such.key"), "no.such.key", "unknown keys render raw, never invented");
  assert.equal(resolveLocale("system", "sv-SE"), "sv");
  assert.equal(resolveLocale("system", "fi-FI"), "en");
  assert.equal(resolveLocale("sv", "en-US"), "sv");
});
