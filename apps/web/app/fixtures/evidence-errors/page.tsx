// Synthetic browser regression for the same loader and client used by owner reports.
// Like the other design fixtures, this route is unavailable without fixture mode.
import { readFile } from "node:fs/promises";
import path from "node:path";

import { notFound } from "next/navigation";

import { PrincessApi } from "@princess/api-client";
import { loadOwnerReport } from "../../../lib/report-data.ts";
import { ReportClient } from "../../reports/[reportId]/ReportClient.tsx";

export const dynamic = "force-dynamic";

export default async function EvidenceErrors({ searchParams }: {
  searchParams: Promise<{ error?: string }>;
}) {
  if (process.env.PRINCESS_WEB_FIXTURES !== "1") notFound();
  const { error = "stored_evidence_invalid" } = await searchParams;
  const status = error === "stored_evidence_invalid" ? 409 : error === "evidence_lineage_invalid" ? 502 : null;
  if (status === null) notFound();
  const file = path.join(process.cwd(), "..", "..", "fixtures", "reports", "view.free.json");
  const view = JSON.parse(await readFile(file, "utf8"));
  const api = new PrincessApi({
    baseUrl: "https://fixture.invalid",
    fetch: async (input) => {
      const evidenceRequest = new URL(String(input)).pathname.endsWith("/evidence");
      return new Response(JSON.stringify(evidenceRequest ? { error } : view), {
        status: evidenceRequest ? status : 200,
      });
    },
  });
  const data = await loadOwnerReport(api, view.source_report_id);
  return <ReportClient {...data} locale="en" />;
}
