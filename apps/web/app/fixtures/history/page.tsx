import { ReportHistory } from "../../reports/ReportHistory.tsx";

export const dynamic = "force-dynamic";

const ITEMS = [
  { report_id: "report_3", revision: 2, kind: "INDIVIDUAL" as const, created_at: "2026-09-27T11:00:00Z",
    locale: "en", has_premium: true },
  { report_id: "report_2", revision: 1, kind: "INDIVIDUAL" as const, created_at: "2026-09-26T11:00:00Z",
    locale: "sv", has_premium: false },
  { report_id: "report_1", revision: 1, kind: "INDIVIDUAL" as const, created_at: "2026-09-25T11:00:00Z",
    locale: "en", has_premium: false },
];

export default async function HistoryFixture({ searchParams }: { searchParams: Promise<{ locale?: string; empty?: string }> }) {
  if (process.env.PRINCESS_WEB_FIXTURES !== "1") return null;
  const params = await searchParams;
  const locale = params.locale === "sv" ? "sv" : "en";
  const items = params.empty === "1" ? [] : ITEMS;
  return <ReportHistory page={{ contract_version: "1.0.0", items, next_cursor: items.length ? "next_cursor_1" : null }}
                        locale={locale} />;
}
