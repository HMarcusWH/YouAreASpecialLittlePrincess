import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import test from "node:test";

// expo-file-system 57 resolves move/copy/bytes/text/... asynchronously (moveSync/copySync are the blocking forms).
// The native adapters cannot load under node, so their call sites are checked in source: a file call that is not
// awaited or returned lets the next step read a copy that is not in place yet (a prepared photo reported missing at
// submit, or a journal write that completes after the next one starts).
const ASYNC_FILE_CALL = /\.(move|copy|bytes|text|base64|upload|pickFileAsync|pickDirectoryAsync|downloadFileAsync)\(/g;

function unawaitedFileCalls(source: string): string[] {
  const found: string[] = [];
  for (const line of source.split("\n")) {
    if (/^\s*(\/\/|\*)/.test(line)) continue;
    for (const match of line.matchAll(ASYNC_FILE_CALL)) {
      const before = line.slice(0, match.index);
      if (!/\b(await|return)\b/.test(before)) found.push(line.trim());
    }
  }
  return found;
}

const src = new URL("../src/", import.meta.url);
const adapters = readdirSync(src, { recursive: true, encoding: "utf8" })
  .filter((path) => /\.tsx?$/.test(path))
  .filter((path) => readFileSync(new URL(path, src), "utf8").includes("from \"expo-file-system\""));

test("the check flags a floating file move and accepts awaited or returned calls", () => {
  assert.deepEqual(unawaitedFileCalls("  source.move(target);\n  void temp.move(next, { overwrite: true });"),
                   ["source.move(target);", "void temp.move(next, { overwrite: true });"]);
  assert.deepEqual(unawaitedFileCalls("  await source.move(target);\n  return file.exists ? file.text() : null;\n"
                                      + "  result = await file.upload(url, options);\n  // file.move(target) in prose"),
                   []);
});

test("every asynchronous expo-file-system call in the app is awaited or returned", () => {
  assert.ok(adapters.includes("platform/native/capture.ts") && adapters.includes("platform/native/files.ts"),
            `expected the native file adapters, found ${adapters.join(", ")}`);
  for (const path of adapters) {
    assert.deepEqual(unawaitedFileCalls(readFileSync(new URL(path, src), "utf8")), [], path);
  }
});
