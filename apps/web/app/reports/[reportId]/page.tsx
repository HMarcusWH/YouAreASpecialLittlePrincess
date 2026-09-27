import { notFound } from "next/navigation";

import { ApiError, PayloadError } from "@princess/api-client";
import { serverApi } from "../../../lib/session.ts";
import { ReportClient } from "./ReportClient.tsx";

export const dynamic = "force-dynamic";

export default async function Report({ params, searchParams }: {
  params: Promise<{ reportId: string }>; searchParams: Promise<{ locale?: string }>;
}) {
  const { reportId } = await params;
  const locale = (await searchParams).locale === "sv" ? "sv" : "en";
  try {
    const view = await (await serverApi()).report(reportId, "OWNER");
    return <ReportClient view={view} locale={locale} />;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    if (e instanceof ApiError && e.status === 401) {
      return <p role="alert">Your session has ended. Start a new analysis or sign in again to see your reports.</p>;
    }
    if (e instanceof PayloadError) {
      return <p role="alert">This report could not be read safely, so it is not shown.</p>;
    }
    throw e;
  }
}
