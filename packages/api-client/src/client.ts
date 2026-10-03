// Typed calls to the product API. In the browser the base URL is the web
// app's same-origin proxy (the session cookie never reaches client code); on
// the server it is the API with a bearer token read from the session cookie;
// in the native app it is the API with the current credential read per call.
import type { Comparison, EvidenceBundle, GrantSnapshot, ReportPage, ReportViewModel } from "@princess/contracts";
import { parseEvidenceBundle, parseReportPage, parseReportView, parseRunStatus, type RunStatus } from "./guards.ts";
import {
  parseAnalysisStart, parseCapture, parseCatalog, parseClaimResult, parseComparison, parseConsentNotices,
  parseCredits, parseDeletionRequested, parseDevIdToken, parseFeedbackReceipt, parseGrantSnapshot, parseGuestSession,
  parseGuestTransfer, parseMe, parsePaymentAccount, parsePermissionCheck, parsePremiumContent, parsePremiumJob,
  parsePremiumRequest, parsePushInstallation, parseRunPage, parseUploadTicket,
  type AnalysisState, type Capture, type CatalogProduct, type ClaimResult, type ClientPlatform, type ConsentNotice,
  type Credits, type FeedbackCategory, type FeedbackReceipt, type FeedbackTarget, type GuestSession, type Me,
  type PermissionCheck, type PremiumContent, type PremiumJob, type RunSummary, type StoreRail, type UploadMediaType,
  type UploadTicket,
} from "./operations.ts";
import { sha256HexSync } from "./sha256.ts";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /** Server back-off hint (Retry-After), when the response carried one. */
  readonly retryAfterMs: number | null;

  constructor(status: number, code: string, retryAfterMs: number | null = null) {
    super(`${status} ${code}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfterMs = retryAfterMs;
  }
}

/**
 * No HTTP response was received: offline, DNS/TLS failure, a client timeout or
 * an abort. The server may still have executed the request, so a mutation
 * that fails this way has an unknown outcome and must be reconciled, not
 * assumed to have failed.
 */
export class TransportError extends Error {
  readonly kind: "TIMEOUT" | "NETWORK" | "ABORTED";

  constructor(kind: "TIMEOUT" | "NETWORK" | "ABORTED") {
    super(`transport ${kind.toLowerCase()}`);
    this.name = "TransportError";
    this.kind = kind;
  }

  static from(error: unknown): TransportError {
    if (error instanceof TransportError) return error;
    const name = (error as { name?: unknown } | null)?.name;
    if (name === "TimeoutError") return new TransportError("TIMEOUT");
    if (name === "AbortError") return new TransportError("ABORTED");
    return new TransportError("NETWORK");
  }
}

/** Current credential per request; lets a native session rotate or clear it. */
export type CredentialSource = () => string | null | Promise<string | null>;

export interface ClientOptions {
  readonly baseUrl: string;
  readonly fetch?: typeof fetch;
  /** A fixed credential (server-side web). Prefer ``credentials`` for long-lived clients. */
  readonly token?: string | null;
  readonly credentials?: CredentialSource;
  readonly correlationId?: string;
  /** Per-request client timeout; a timeout is not proof the server did nothing. */
  readonly timeoutMs?: number;
}

export type { Capture, UploadTicket } from "./operations.ts";

export interface NotificationPreferences {
  readonly mail_report_ready: boolean;
  readonly locale: string;
}

const LOCALE = /^[a-z]{2}(?:-[A-Z]{2})?$/;

export function parseNotificationPreferences(raw: unknown): NotificationPreferences {
  const value = raw as Record<string, unknown> | null;
  if (!value || typeof value.mail_report_ready !== "boolean" || typeof value.locale !== "string"
      || !LOCALE.test(value.locale) || Object.keys(value).some((key) => key !== "mail_report_ready" && key !== "locale")) {
    throw new ApiError(502, "unreadable_notification_preferences");
  }
  return value as unknown as NotificationPreferences;
}

export type Projection = "FREE" | "OWNER" | "EXPORT";

export type ExportState = "QUEUED" | "READY" | "FAILED" | "REVOKED";
export type ExportLayout = "A4" | "LETTER" | "CARD_SQUARE" | "CARD_STORY";

export interface ExportStatus {
  readonly export_id: string;
  readonly report_id: string;
  readonly revision: number;
  readonly layout: ExportLayout;
  readonly state: ExportState;
  readonly error_code: string | null;
  readonly media_type?: string | null;
  readonly size_bytes?: number | null;
}

const EXPORT_STATES = new Set<string>(["QUEUED", "READY", "FAILED", "REVOKED"]);
const EXPORT_LAYOUTS = new Set<string>(["A4", "LETTER", "CARD_SQUARE", "CARD_STORY"]);
const EXPORT_MEDIA = new Set<string>(["application/pdf", "image/png"]);

export function parseExportStatus(raw: unknown): ExportStatus {
  const v = raw as Record<string, unknown> | null;
  if (!v || typeof v.export_id !== "string" || typeof v.report_id !== "string" || typeof v.revision !== "number"
      || typeof v.layout !== "string" || !EXPORT_LAYOUTS.has(v.layout) || typeof v.state !== "string"
      || !EXPORT_STATES.has(v.state) || (v.error_code !== null && typeof v.error_code !== "string")
      || (v.media_type !== undefined && v.media_type !== null
          && (typeof v.media_type !== "string" || !EXPORT_MEDIA.has(v.media_type)))
      || (v.size_bytes !== undefined && v.size_bytes !== null
          && (!Number.isInteger(v.size_bytes) || (v.size_bytes as number) < 0))) {
    throw new ApiError(502, "unreadable_export_status");
  }
  return v as unknown as ExportStatus;
}

/** A request the native file layer performs itself, bound to the API origin. */
export interface AuthorizedDownload {
  readonly url: string;
  readonly headers: Readonly<Record<string, string>>;
}

const SAFE_CODE = /^[a-z0-9_.:-]{1,64}$/;
const DEFAULT_TIMEOUT_MS = 20_000;

function retryAfter(response: Response): number | null {
  const header = response.headers.get("retry-after");
  if (header === null || !/^\d{1,6}$/.test(header.trim())) return null;
  return Math.min(Number(header.trim()), 3600) * 1000;
}

export class PrincessApi {
  private readonly base: string;
  private readonly doFetch: typeof fetch;
  private readonly credentials: CredentialSource;
  private readonly correlationId: string | undefined;
  private readonly timeoutMs: number;

  constructor(options: ClientOptions) {
    this.base = options.baseUrl.replace(/\/+$/, "");
    // Never call the global fetch as a method of this object: browsers throw "Illegal invocation".
    this.doFetch = options.fetch ?? ((input, init) => globalThis.fetch(input, init));
    const fixed = options.token ?? null;
    this.credentials = options.credentials ?? (() => fixed);
    this.correlationId = options.correlationId;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  private async headers(json: boolean, anonymous: boolean): Promise<Record<string, string>> {
    const headers: Record<string, string> = { accept: "application/json" };
    if (json) headers["content-type"] = "application/json";
    const token = anonymous ? null : await this.credentials();
    if (token) headers.authorization = `Bearer ${token}`;
    if (this.correlationId) headers["x-correlation-id"] = this.correlationId;
    return headers;
  }

  private async call(method: string, path: string, body?: unknown,
                     options: { anonymous?: boolean } = {}): Promise<unknown> {
    const headers = await this.headers(body !== undefined, options.anonymous ?? false);
    // Keep the shared transport native-compatible: RequestInit.cache is a browser-only extension.
    const init: RequestInit = { method, headers, credentials: "same-origin" };
    if (body !== undefined) init.body = JSON.stringify(body);
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    let timedOut = false;
    const timer = controller ? setTimeout(() => { timedOut = true; controller.abort(); }, this.timeoutMs) : null;
    if (controller) init.signal = controller.signal;
    let response: Response;
    try {
      response = await this.doFetch(`${this.base}${path}`, init);
    } catch (error) {
      throw timedOut ? new TransportError("TIMEOUT") : TransportError.from(error);
    } finally {
      if (timer !== null) clearTimeout(timer);
    }
    if (response.status === 204) return null;
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      if (response.ok) throw new ApiError(response.status, "unreadable_response");
    }
    if (!response.ok) {
      const raw = (payload as { error?: unknown } | null)?.error;
      throw new ApiError(response.status, typeof raw === "string" && SAFE_CODE.test(raw) ? raw : "request_failed",
                         retryAfter(response));
    }
    return payload;
  }

  // --- session -----------------------------------------------------------------

  async me(): Promise<Me> {
    return parseMe(await this.call("GET", "/v1/me"));
  }

  /** Starts a new guest principal. Sent without any current credential. */
  async createGuestSession(): Promise<GuestSession> {
    return parseGuestSession(await this.call("POST", "/v1/guest-sessions", undefined, { anonymous: true }));
  }

  /** Moves a guest's work to the signed-in account; proves possession of both credentials. */
  async transferGuest(guestToken: string): Promise<string> {
    return parseGuestTransfer(await this.call("POST", "/v1/me/guest-transfer", { guest_token: guestToken }))
      .transferred_principal_id;
  }

  /** Local/test only: the API registers this route only with a fake identity provider. */
  async devIdToken(subject: string): Promise<string> {
    return parseDevIdToken(await this.call("POST", "/v1/dev/id-tokens", { subject }, { anonymous: true }));
  }

  async logoutEverywhere(): Promise<void> {
    await this.call("POST", "/v1/me/logout-everywhere");
  }

  /** Asynchronous: the 202 means erasure was requested, not that it finished. */
  async deleteAccount(): Promise<{ readonly state: "DELETION_REQUESTED" }> {
    return parseDeletionRequested(await this.call("DELETE", "/v1/me"));
  }

  // --- intake and analysis ------------------------------------------------------------

  async reserveUpload(mediaType: UploadMediaType): Promise<UploadTicket> {
    return parseUploadTicket(await this.call("POST", "/v1/uploads", { media_type: mediaType }));
  }

  async completeUpload(uploadId: string, sha256: string): Promise<Capture> {
    return parseCapture(await this.call("POST", `/v1/uploads/${encodeURIComponent(uploadId)}/complete`, { sha256 }));
  }

  async recordPermission(choice: { purpose_id: string; scope_kind: string; scope_ref: string | null;
                                   decision: "GRANT" | "DENY" | "WITHDRAW"; notice_version: string;
                                   request_id: string }): Promise<GrantSnapshot> {
    return parseGrantSnapshot(await this.call("POST", "/v1/me/permissions", choice));
  }

  async checkPermission(purposeId: string, scopeKind = "SUBJECT_WIDE", scopeRef: string | null = null):
      Promise<PermissionCheck> {
    const query = new URLSearchParams({ scope_kind: scopeKind });
    if (scopeRef !== null) query.set("scope_ref", scopeRef);
    return parsePermissionCheck(await this.call(
      "GET", `/v1/me/permissions/${encodeURIComponent(purposeId)}?${query.toString()}`));
  }

  async consentNotices(locale: string): Promise<readonly ConsentNotice[]> {
    const query = new URLSearchParams({ locale: LOCALE.test(locale) ? locale : "en" });
    return parseConsentNotices(await this.call("GET", `/v1/consent-notices?${query.toString()}`, undefined,
                                               { anonymous: true }));
  }

  async startAnalysis(captureId: string): Promise<{ readonly run_id: string; readonly state: AnalysisState }> {
    return parseAnalysisStart(await this.call("POST", "/v1/analyses", { capture_id: captureId }));
  }

  async analysis(runId: string): Promise<RunStatus> {
    return parseRunStatus(await this.call("GET", `/v1/analyses/${encodeURIComponent(runId)}`));
  }

  /** The principal's newest runs, for recovery when no local journal exists. */
  async recentAnalyses(limit = 20): Promise<readonly RunSummary[]> {
    return parseRunPage(await this.call("GET", `/v1/analyses?limit=${Math.max(1, Math.min(50, limit))}`)).items;
  }

  async cancelAnalysis(runId: string): Promise<{ readonly run_id: string; readonly state: AnalysisState }> {
    return parseAnalysisStart(await this.call("POST", `/v1/analyses/${encodeURIComponent(runId)}/cancel`));
  }

  async deleteCapture(captureId: string): Promise<{ readonly state: "DELETION_REQUESTED" }> {
    return parseDeletionRequested(await this.call("DELETE", `/v1/captures/${encodeURIComponent(captureId)}`));
  }

  // --- reports ------------------------------------------------------------------------------

  async reports(limit = 20, cursor: string | null = null): Promise<ReportPage> {
    const query = new URLSearchParams({ limit: String(limit) });
    if (cursor !== null) query.set("cursor", cursor);
    return parseReportPage(await this.call("GET", `/v1/reports?${query.toString()}`));
  }

  async report(reportId: string, projection: Projection = "OWNER"): Promise<ReportViewModel> {
    const path = `/v1/reports/${encodeURIComponent(reportId)}?projection=${projection}`;
    return parseReportView(await this.call("GET", path));
  }

  async reportEvidence(reportId: string): Promise<EvidenceBundle> {
    return parseEvidenceBundle(await this.call(
      "GET", `/v1/reports/${encodeURIComponent(reportId)}/evidence`));
  }

  /** Deletes the specimen behind the report (and so the report). Erasure is asynchronous. */
  async deleteReport(reportId: string): Promise<{ readonly state: "DELETION_REQUESTED" }> {
    return parseDeletionRequested(await this.call("DELETE", `/v1/reports/${encodeURIComponent(reportId)}`));
  }

  /** The retained source image, re-authorized by the API on every request. */
  async sourceImageDownload(reportId: string): Promise<AuthorizedDownload> {
    return this.download(`/v1/reports/${encodeURIComponent(reportId)}/source-image`, "image/*");
  }

  async compare(kind: "PAIR" | "HISTORY", reportIds: readonly string[]): Promise<Comparison> {
    return parseComparison(await this.call("POST", "/v1/comparisons", { kind, report_ids: reportIds }));
  }

  async submitFeedback(reportId: string, feedback: { category: FeedbackCategory; target_kind: FeedbackTarget;
                                                     target_ref: string | null; comment: string | null;
                                                     request_id: string }): Promise<FeedbackReceipt> {
    return parseFeedbackReceipt(await this.call(
      "POST", `/v1/reports/${encodeURIComponent(reportId)}/feedback`, feedback));
  }

  async withdrawFeedback(feedbackId: string): Promise<void> {
    await this.call("DELETE", `/v1/feedback/${encodeURIComponent(feedbackId)}`);
  }

  // --- exports ---------------------------------------------------------------------------------

  async requestExport(reportId: string, layout: ExportLayout = "A4",
                      options: { sections?: readonly string[]; shareGrantRef?: string } = {}): Promise<ExportStatus> {
    const body: Record<string, unknown> = { report_id: reportId, layout };
    if (options.sections && options.sections.length > 0) body.sections = options.sections;
    if (options.shareGrantRef) body.share_grant_ref = options.shareGrantRef;
    return parseExportStatus(await this.call("POST", "/v1/report-exports", body));
  }

  async exportStatus(exportId: string): Promise<ExportStatus> {
    return parseExportStatus(await this.call("GET", `/v1/report-exports/${encodeURIComponent(exportId)}`));
  }

  /** Same-origin URL of the file; the API re-authorizes it on every request. */
  exportFileUrl(exportId: string): string {
    return `${this.base}/v1/report-exports/${encodeURIComponent(exportId)}/file`;
  }

  /** Native: the bearer-authenticated request for the export file (no browser cookie exists). */
  async exportDownload(exportId: string): Promise<AuthorizedDownload> {
    return this.download(`/v1/report-exports/${encodeURIComponent(exportId)}/file`, "application/pdf, image/png");
  }

  private async download(path: string, accept: string): Promise<AuthorizedDownload> {
    const headers = await this.headers(false, false);
    headers.accept = accept;
    // Only API paths: the credential is never attached to storage or third-party URLs.
    return { url: `${this.base}${path}`, headers };
  }

  // --- commerce and Premium -------------------------------------------------------------------

  async catalog(): Promise<readonly CatalogProduct[]> {
    return parseCatalog(await this.call("GET", "/v1/catalog"));
  }

  /** Opaque token the store binds to the purchase (appAccountToken / obfuscated account ID). */
  async paymentAccount(): Promise<string> {
    return parsePaymentAccount(await this.call("GET", "/v1/me/payment-account"));
  }

  async credits(platform: ClientPlatform): Promise<Credits> {
    return parseCredits(await this.call("GET", `/v1/me/credits?platform=${platform}`));
  }

  /** Hands a store proof to the server; only a durable grant lets the client finish the store transaction. */
  async claimStorePurchase(rail: StoreRail, proof: string): Promise<ClaimResult> {
    return parseClaimResult(await this.call("POST", "/v1/purchases/claims", { rail, proof }));
  }

  async requestPremium(reportId: string, platform: ClientPlatform): Promise<{ readonly job_id: string;
                                                                               readonly created: boolean }> {
    return parsePremiumRequest(await this.call(
      "POST", `/v1/reports/${encodeURIComponent(reportId)}/premium`, { platform }));
  }

  async premiumJob(jobId: string): Promise<PremiumJob> {
    return parsePremiumJob(await this.call("GET", `/v1/premium-jobs/${encodeURIComponent(jobId)}`));
  }

  /** The saved, validated overlay. Read-only: the API never calls a model on read. */
  async premiumContent(reportId: string): Promise<PremiumContent> {
    return parsePremiumContent(await this.call("GET", `/v1/reports/${encodeURIComponent(reportId)}/premium`));
  }

  // --- notifications ---------------------------------------------------------------------------

  async registerPush(device: { device_token: string; platform: "apns" | "fcm"; app_environment: string;
                               locale: string }): Promise<string> {
    return parsePushInstallation(await this.call("POST", "/v1/me/push-installations", device));
  }

  async unregisterPush(installationId: string): Promise<void> {
    await this.call("DELETE", `/v1/me/push-installations/${encodeURIComponent(installationId)}`);
  }

  async notificationPreferences(): Promise<NotificationPreferences> {
    return parseNotificationPreferences(await this.call("GET", "/v1/me/notification-preferences"));
  }

  async setNotificationPreferences(preferences: NotificationPreferences): Promise<NotificationPreferences> {
    return parseNotificationPreferences(await this.call("PUT", "/v1/me/notification-preferences", preferences));
  }
}

/** Drops responses that arrive after the signed-in principal changed. */
export class SessionEpoch {
  private epoch = 0;

  current(): number {
    return this.epoch;
  }

  switchPrincipal(): void {
    this.epoch += 1;
  }

  async guard<T>(work: Promise<T>): Promise<T | null> {
    const started = this.epoch;
    const result = await work;
    return started === this.epoch ? result : null;
  }
}

/** Cache keys include principal and revision so one account never sees another's report. */
export function reportCacheKey(principalId: string, reportId: string, revision: number, projection: Projection): string {
  return ["report", principalId, reportId, String(revision), projection].join("|");
}

/** Bounded backoff for job polling: never a tight loop, never forever. */
export function pollDelayMs(attempt: number): number {
  return Math.min(8000, 500 * 2 ** Math.min(attempt, 4));
}

/** The next poll delay, honouring a server Retry-After hint within a ceiling. */
export function nextPollDelayMs(attempt: number, error: unknown = null): number {
  const hint = error instanceof ApiError ? error.retryAfterMs : null;
  return hint === null ? pollDelayMs(attempt) : Math.min(60_000, Math.max(pollDelayMs(attempt), hint));
}

/** SHA-256 hex of exactly these bytes; WebCrypto when present, else a portable implementation (Hermes). */
export async function sha256Hex(bytes: ArrayBuffer | Uint8Array): Promise<string> {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  type Digest = { digest(algorithm: string, data: Uint8Array): Promise<ArrayBuffer> };
  const subtle = (globalThis as { crypto?: { subtle?: Digest } }).crypto?.subtle;
  if (subtle !== undefined && typeof subtle.digest === "function") {
    const digest = await subtle.digest("SHA-256", view);
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  }
  return sha256HexSync(view);
}
