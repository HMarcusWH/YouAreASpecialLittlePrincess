import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const manifest = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));

const expected = {
  "expo": "57.0.25",
  "expo-router": "57.0.23",
  "react": "19.2.3",
  "react-native": "0.86.3",
  "expo-dev-client": "57.0.19",
  "expo-secure-store": "57.0.4",
  "expo-image-picker": "57.0.20",
  "expo-image-manipulator": "57.0.20",
  "expo-file-system": "57.0.7",
  "expo-sharing": "57.0.22",
  "expo-linking": "57.0.11",
  "expo-notifications": "57.0.21",
  "expo-build-properties": "57.0.22",
  "expo-constants": "57.0.19",
  "expo-splash-screen": "57.0.9",
  "expo-status-bar": "57.0.1",
  "expo-system-ui": "57.0.4",
  "expo-web-browser": "57.0.3",
  "react-native-safe-area-context": "5.7.0",
  "react-native-screens": "4.26.2",
  "react-native-reanimated": "4.5.1",
  "react-native-worklets": "0.10.1",
  "expo-iap": "5.6.3"
};
for (const [name, version] of Object.entries(expected)) {
  assert.equal(manifest.dependencies[name], version, name + " must be pinned exactly");
  const installed = JSON.parse(readFileSync(require.resolve(name + "/package.json"), "utf8"));
  assert.equal(installed.version, version, name + " installed version drift");
  assert.ok(installed.license, name + " must publish license metadata");
  console.log("PASS", name, version, "license=" + installed.license);
}
console.log("PASS exact native compatibility manifest");
