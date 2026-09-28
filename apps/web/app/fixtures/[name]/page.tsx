// Design review and browser tests: renders the shared synthetic view fixtures.
// Disabled unless PRINCESS_WEB_FIXTURES=1 (never in staging or production).
import { readFile } from "node:fs/promises";
import path from "node:path";

import { notFound } from "next/navigation";

import { parseEvidenceBundle, parseReportView } from "@princess/api-client";
import { ReportView } from "@princess/report-web";

export const dynamic = "force-dynamic";
const NAMES = new Set(["free", "free-v2", "owner-premium", "owner-image-revoked", "share", "export-no-image"]);

export default async function Fixture({ params, searchParams }: {
  params: Promise<{ name: string }>; searchParams: Promise<{ locale?: string }>;
}) {
  const { name } = await params;
  if (process.env.PRINCESS_WEB_FIXTURES !== "1" || !NAMES.has(name)) notFound();
  const file = path.join(process.cwd(), "..", "..", "fixtures", "reports", `view.${name}.json`);
  const view = parseReportView(JSON.parse(await readFile(file, "utf8")));
  const evidenceFile = name === "free" ? "evidence-bundle.json"
    : name === "free-v2" ? "evidence-bundle.v2.json" : null;
  const evidence = evidenceFile
    ? parseEvidenceBundle(JSON.parse(await readFile(path.join(process.cwd(), "..", "..", "fixtures", "reports",
                                                               evidenceFile), "utf8")))
    : null;
  const locale = (await searchParams).locale === "sv" ? "sv" : "en";
  return <ReportView view={view} locale={locale} evidence={evidence} />;
}
