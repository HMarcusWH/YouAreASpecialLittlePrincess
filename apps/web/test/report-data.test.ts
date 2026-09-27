import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { ApiError, PayloadError, PrincessApi } from "@princess/api-client";
import { loadOwnerReport } from "../lib/report-data.ts";

const view = JSON.parse(readFileSync(
  new URL("../../../fixtures/reports/view.free.json", import.meta.url), "utf8"));
const reportPath = `/v1/reports/${view.source_report_id}`;

function clientWithEvidence(status: number, body: unknown, reportBody: unknown = view, reportStatus = 200) {
  const calls: string[] = [];
  const api = new PrincessApi({
    baseUrl: "https://api.example.test",
    fetch: async (input, init) => {
      assert.equal(init?.method, "GET");
      const url = new URL(String(input));
      calls.push(url.pathname + url.search);
      if (url.pathname === reportPath && url.search === "?projection=OWNER") {
        return new Response(JSON.stringify(reportBody), { status: reportStatus });
      }
      assert.equal(url.pathname, `${reportPath}/evidence`);
      return new Response(JSON.stringify(body), { status });
    },
  });
  return { api, calls };
}

for (const [status, code] of [
  [409, "stored_evidence_invalid"],
  [502, "evidence_lineage_invalid"],
] as const) {
  test(`${code} preserves the validated report and marks evidence unreadable`, async () => {
    const { api, calls } = clientWithEvidence(status, { error: code });
    const data = await loadOwnerReport(api, view.source_report_id);
    assert.deepEqual(data, { view, evidence: null, evidenceUnreadable: true });
    assert.deepEqual(calls, [`${reportPath}?projection=OWNER`, `${reportPath}/evidence`]);
  });
}

test("a malformed evidence payload preserves the report but is never returned", async () => {
  const { api } = clientWithEvidence(200, { contract_version: "999.0.0", observations: ["rejected"] });
  assert.deepEqual(await loadOwnerReport(api, view.source_report_id), {
    view, evidence: null, evidenceUnreadable: true,
  });
});

test("unavailable evidence keeps its distinct missing state", async () => {
  const { api } = clientWithEvidence(404, { error: "evidence_not_available" });
  assert.deepEqual(await loadOwnerReport(api, view.source_report_id), {
    view, evidence: null, evidenceUnreadable: false,
  });
});

for (const [status, code] of [
  [401, "unauthenticated"],
  [403, "not_authorized"],
  [409, "other_conflict"],
  [502, "request_failed"],
  [503, "unavailable"],
  // A familiar code does not override an access denial or an unexpected status.
  [401, "stored_evidence_invalid"],
  [403, "evidence_lineage_invalid"],
  [409, "evidence_lineage_invalid"],
  [502, "stored_evidence_invalid"],
] as const) {
  test(`${status} ${code} is not swallowed by the evidence fallback`, async () => {
    const { api } = clientWithEvidence(status, { error: code });
    await assert.rejects(loadOwnerReport(api, view.source_report_id), (error: unknown) =>
      error instanceof ApiError && error.status === status && error.code === code);
  });
}

test("a network failure propagates unchanged", async () => {
  const failure = new TypeError("network unavailable");
  const { api } = clientWithEvidence(404, { error: "evidence_not_available" });
  await assert.rejects(loadOwnerReport({
    report: (id, projection) => api.report(id, projection),
    reportEvidence: async () => { throw failure; },
  }, view.source_report_id), (error: unknown) => error === failure);
});

test("an invalid report fails closed before evidence is requested", async () => {
  const { api, calls } = clientWithEvidence(409, { error: "stored_evidence_invalid" }, {});
  await assert.rejects(loadOwnerReport(api, view.source_report_id), PayloadError);
  assert.deepEqual(calls, [`${reportPath}?projection=OWNER`]);
});

for (const status of [401, 403, 404]) {
  test(`report access failure ${status} is not treated as an evidence failure`, async () => {
    const { api, calls } = clientWithEvidence(409, { error: "stored_evidence_invalid" },
      { error: "report_not_available" }, status);
    await assert.rejects(loadOwnerReport(api, view.source_report_id), (error: unknown) =>
      error instanceof ApiError && error.status === status);
    assert.deepEqual(calls, [`${reportPath}?projection=OWNER`]);
  });
}

test("valid evidence is returned without an unreadable warning", async () => {
  const evidence = JSON.parse(readFileSync(
    new URL("../../../fixtures/reports/evidence-bundle.json", import.meta.url), "utf8"));
  const { api } = clientWithEvidence(200, evidence);
  assert.deepEqual(await loadOwnerReport(api, view.source_report_id), {
    view, evidence, evidenceUnreadable: false,
  });
});
