import { ApiError, PayloadError, type PrincessApi } from "@princess/api-client";
import type { EvidenceBundle, ReportViewModel } from "@princess/contracts";

interface OwnerReportData {
  readonly view: ReportViewModel;
  readonly evidence: EvidenceBundle | null;
  readonly evidenceUnreadable: boolean;
}

/** Optional evidence may fail integrity checks without hiding a validated report. */
export async function loadOwnerReport(
  api: Pick<PrincessApi, "report" | "reportEvidence">,
  reportId: string,
): Promise<OwnerReportData> {
  // Report validation and authorization must succeed outside the evidence fallback.
  const view = await api.report(reportId, "OWNER");
  try {
    return { view, evidence: await api.reportEvidence(reportId), evidenceUnreadable: false };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return { view, evidence: null, evidenceUnreadable: false };
    }
    if (error instanceof PayloadError || (error instanceof ApiError && (
      (error.status === 409 && error.code === "stored_evidence_invalid")
      || (error.status === 502 && error.code === "evidence_lineage_invalid")
    ))) {
      return { view, evidence: null, evidenceUnreadable: true };
    }
    // Never turn authentication, authorization or unrelated service failures into success.
    throw error;
  }
}
