// Single-report Premium on native (N11). The server decides everything that
// matters: whether Premium is offered (the report's PURCHASE action), whether
// third-party AI processing is permitted for this report, credit
// reservation, generation, validation and publication. The app displays only
// the saved validated overlay; reopening it never calls a model, and a failed
// or refused generation leaves the Free report exactly as it was.
import { ApiError, TransportError, type ClientPlatform, type Credits, type PremiumContent, type PremiumJob,
         type PermissionCheck } from "@princess/api-client";
import type { ReportViewModel } from "@princess/contracts";

export const AI_PURPOSE = "third_party_ai_processing";

export interface PremiumApi {
  premiumContent(reportId: string): Promise<PremiumContent>;
  checkPermission(purposeId: string, scopeKind?: string, scopeRef?: string | null): Promise<PermissionCheck>;
  recordPermission(choice: { purpose_id: string; scope_kind: string; scope_ref: string | null;
                             decision: "GRANT" | "DENY" | "WITHDRAW"; notice_version: string;
                             request_id: string }): Promise<unknown>;
  credits(platform: ClientPlatform): Promise<Credits>;
  requestPremium(reportId: string, platform: ClientPlatform): Promise<{ readonly job_id: string; readonly created: boolean }>;
  premiumJob(jobId: string): Promise<PremiumJob>;
}

export type PremiumState =
  | { readonly status: "SAVED"; readonly content: PremiumContent }
  | { readonly status: "REVOKED" }
  | { readonly status: "NOT_OFFERED"; readonly reason: string | null }
  | { readonly status: "ACCOUNT_REQUIRED" }
  | { readonly status: "NO_IMAGE" }
  | { readonly status: "NEEDS_PERMISSION"; readonly credits: Credits | null }
  | { readonly status: "NEEDS_CREDIT"; readonly credits: Credits }
  | { readonly status: "READY"; readonly credits: Credits }
  | { readonly status: "GENERATING"; readonly jobId: string }
  | { readonly status: "FAILED"; readonly code: string }
  | { readonly status: "UNKNOWN"; readonly code: string };

export class PremiumController {
  private readonly api: PremiumApi;
  private readonly platform: ClientPlatform;
  private readonly newRequestId: () => string;

  constructor(api: PremiumApi, platform: ClientPlatform, newRequestId: () => string) {
    this.api = api;
    this.platform = platform;
    this.newRequestId = newRequestId;
  }

  /** Read state for a report view; never starts work. */
  async load(view: ReportViewModel, kind: "ACCOUNT" | "GUEST"): Promise<PremiumState> {
    const reportId = view.source_report_id;
    if (view.sections.some((s) => s.premium_section_id !== null)) {
      try {
        return { status: "SAVED", content: await this.api.premiumContent(reportId) };
      } catch (error) {
        if (error instanceof ApiError && (error.status === 404 || error.status === 403)) return { status: "REVOKED" };
        throw error;
      }
    }
    const purchase = view.actions.find((a) => a.kind === "PURCHASE");
    if (!purchase || !purchase.enabled) return { status: "NOT_OFFERED", reason: purchase?.reason ?? null };
    if (kind !== "ACCOUNT") return { status: "ACCOUNT_REQUIRED" };
    // The multimodal request needs the retained image; without it nothing can be generated honestly.
    if (view.authorized_asset_ids.length === 0) return { status: "NO_IMAGE" };
    const [permission, credits] = await Promise.all([
      this.api.checkPermission(AI_PURPOSE, "REPORT", reportId),
      this.api.credits(this.platform),
    ]);
    if (!permission.allowed) return { status: "NEEDS_PERMISSION", credits };
    return credits.available > 0 ? { status: "READY", credits } : { status: "NEEDS_CREDIT", credits };
  }

  /** The explicit, report-scoped choice to send this report to the third-party AI processor. */
  async grantPermission(reportId: string, noticeVersion: string): Promise<void> {
    await this.api.recordPermission({ purpose_id: AI_PURPOSE, scope_kind: "REPORT", scope_ref: reportId,
                                      decision: "GRANT", notice_version: noticeVersion,
                                      request_id: `mobile.${this.newRequestId()}.ai` });
  }

  async withdrawPermission(reportId: string): Promise<void> {
    await this.api.recordPermission({ purpose_id: AI_PURPOSE, scope_kind: "REPORT", scope_ref: reportId,
                                      decision: "WITHDRAW", notice_version: "notice.consent-choices:1",
                                      request_id: `mobile.${this.newRequestId()}.ai-withdraw` });
  }

  /**
   * Reserve one credit and enqueue generation. The server keys this by the
   * intended operation, so a retried request after a lost response returns
   * the same job rather than a second billable attempt.
   */
  async request(reportId: string): Promise<PremiumState> {
    try {
      const { job_id: jobId } = await this.api.requestPremium(reportId, this.platform);
      return { status: "GENERATING", jobId };
    } catch (error) {
      if (error instanceof TransportError) return { status: "UNKNOWN", code: "outcome_unknown" };
      if (error instanceof ApiError) {
        if (error.code === "no_eligible_credit") {
          return { status: "NEEDS_CREDIT", credits: await this.api.credits(this.platform) };
        }
        if (error.code === "permission_not_granted") return { status: "NEEDS_PERMISSION", credits: null };
        if (error.status === 501) return { status: "NOT_OFFERED", reason: error.code };
        return { status: "FAILED", code: error.code };
      }
      throw error;
    }
  }

  async poll(reportId: string, jobId: string): Promise<PremiumState> {
    let job: PremiumJob;
    try {
      job = await this.api.premiumJob(jobId);
    } catch (error) {
      if (error instanceof TransportError || (error instanceof ApiError && error.status >= 500)) {
        return { status: "GENERATING", jobId };
      }
      throw error;
    }
    if (job.state === "QUEUED" || job.state === "LEASED") return { status: "GENERATING", jobId };
    if (job.state === "SUCCEEDED") return { status: "SAVED", content: await this.api.premiumContent(reportId) };
    // Failed or cancelled: the reservation is released server-side and the Free report is unchanged.
    return { status: "FAILED", code: job.error_code ?? (job.state === "CANCELLED" ? "cancelled" : "generation_failed") };
  }
}
