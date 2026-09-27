import { ApiError, PayloadError } from "@princess/api-client";
import { serverApi } from "../../lib/session.ts";
import { ReportHistory } from "./ReportHistory.tsx";

export const dynamic = "force-dynamic";

export default async function Reports({ searchParams }: {
  searchParams: Promise<{ cursor?: string; locale?: string }>;
}) {
  const params = await searchParams;
  const locale = params.locale === "sv" ? "sv" : "en";
  try {
    const page = await (await serverApi()).reports(20, params.cursor ?? null);
    return <ReportHistory page={page} locale={locale} />;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      return <p role="alert">Your session has ended. Start a new analysis or sign in again to see your reports.</p>;
    }
    if (e instanceof ApiError && e.status === 400) {
      return (
        <div className="stack">
          <p role="alert">This report-history page link is not valid.</p>
          <p><a href={`/reports?locale=${locale}`}>Return to your latest reports</a></p>
        </div>
      );
    }
    if (e instanceof PayloadError) {
      return <p role="alert">Your report history could not be read safely, so it is not shown.</p>;
    }
    throw e;
  }
}
