// Typed calls to the product API. In the browser the base URL is the web
// app's same-origin proxy (the session cookie never reaches client code); on
// the server it is the API with a bearer token read from the session cookie.
import type { EvidenceBundle, ReportPage, ReportViewModel } from "@princess/contracts";
import { parseEvidenceBundle, parseReportPage, parseReportView, parseRunStatus, type RunStatus } from "./guards.ts";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(`${status} ${code}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export interface ClientOptions {
  readonly baseUrl: string;
  readonly fetch?: typeof fetch;
  readonly token?: string | null;
  readonly correlationId?: string;
}

export interface UploadTicket {
  readonly upload_id: string;
  readonly method: string;
  readonly url: string;
  readonly expires_at: string;
  readonly max_bytes: number;
}

export interface Capture {
  readonly capture_id: string;
  readonly width: number;
  readonly height: number;
  readonly media_type: string;
}

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

export interface ExportStatus {
  readonly export_id: string;
  readonly report_id: string;
  readonly revision: number;
  readonly layout: "A4" | "LETTER" | "CARD_SQUARE" | "CARD_STORY";
  readonly state: ExportState;
  readonly error_code: string | null;
}

const EXPORT_STATES = new Set<string>(["QUEUED", "READY", "FAILED", "REVOKED"]);

export function parseExportStatus(raw: unknown): ExportStatus {
  const v = raw as Record<string, unknown> | null;
  if (!v || typeof v.export_id !== "string" || typeof v.report_id !== "string" || typeof v.revision !== "number"
      || typeof v.layout !== "string" || typeof v.state !== "string" || !EXPORT_STATES.has(v.state)
      || (v.error_code !== null && typeof v.error_code !== "string")) {
    throw new ApiError(502, "unreadable_export_status");
  }
  return v as unknown as ExportStatus;
}

const SAFE_CODE = /^[a-z0-9_.:-]{1,64}$/;

export class PrincessApi {
  private readonly base: string;
  private readonly doFetch: typeof fetch;
  private readonly token: string | null;
  private readonly correlationId: string | undefined;

  constructor(options: ClientOptions) {
    this.base = options.baseUrl.replace(/\/+$/, "");
    // Never call the global fetch as a method of this object: browsers throw "Illegal invocation".
    this.doFetch = options.fetch ?? ((input, init) => globalThis.fetch(input, init));
    this.token = options.token ?? null;
    this.correlationId = options.correlationId;
  }

  private async call(method: string, path: string, body?: unknown): Promise<unknown> {
    const headers: Record<string, string> = { accept: "application/json" };
    if (body !== undefined) headers["content-type"] = "application/json";
    if (this.token) headers.authorization = `Bearer ${this.token}`;
    if (this.correlationId) headers["x-correlation-id"] = this.correlationId;
    // Keep the shared transport native-compatible: RequestInit.cache is a browser-only extension.
    const init: RequestInit = { method, headers, credentials: "same-origin" };
    if (body !== undefined) init.body = JSON.stringify(body);
    const response = await this.doFetch(`${this.base}${path}`, init);
    if (response.status === 204) return null;
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      if (response.ok) throw new ApiError(response.status, "unreadable_response");
    }
    if (!response.ok) {
      const raw = (payload as { error?: unknown } | null)?.error;
      throw new ApiError(response.status, typeof raw === "string" && SAFE_CODE.test(raw) ? raw : "request_failed");
    }
    return payload;
  }

  me(): Promise<{ principal_id: string; kind: "ACCOUNT" | "GUEST" }> {
    return this.call("GET", "/v1/me") as Promise<{ principal_id: string; kind: "ACCOUNT" | "GUEST" }>;
  }

  reserveUpload(mediaType: "image/jpeg" | "image/png"): Promise<UploadTicket> {
    return this.call("POST", "/v1/uploads", { media_type: mediaType }) as Promise<UploadTicket>;
  }

  completeUpload(uploadId: string, sha256: string): Promise<Capture> {
    return this.call("POST", `/v1/uploads/${encodeURIComponent(uploadId)}/complete`, { sha256 }) as Promise<Capture>;
  }

  recordPermission(choice: { purpose_id: string; scope_kind: string; scope_ref: string | null;
                             decision: "GRANT" | "DENY" | "WITHDRAW"; notice_version: string;
                             request_id: string }): Promise<unknown> {
    return this.call("POST", "/v1/me/permissions", choice);
  }

  async startAnalysis(captureId: string): Promise<{ run_id: string; state: string }> {
    return this.call("POST", "/v1/analyses", { capture_id: captureId }) as Promise<{ run_id: string; state: string }>;
  }

  async analysis(runId: string): Promise<RunStatus> {
    return parseRunStatus(await this.call("GET", `/v1/analyses/${encodeURIComponent(runId)}`));
  }

  cancelAnalysis(runId: string): Promise<unknown> {
    return this.call("POST", `/v1/analyses/${encodeURIComponent(runId)}/cancel`);
  }

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

  async requestExport(reportId: string, layout: "A4" | "LETTER" = "A4"): Promise<ExportStatus> {
    return parseExportStatus(await this.call("POST", "/v1/report-exports", { report_id: reportId, layout }));
  }

  async exportStatus(exportId: string): Promise<ExportStatus> {
    return parseExportStatus(await this.call("GET", `/v1/report-exports/${encodeURIComponent(exportId)}`));
  }

  /** Same-origin URL of the file; the API re-authorizes it on every request. */
  exportFileUrl(exportId: string): string {
    return `${this.base}/v1/report-exports/${encodeURIComponent(exportId)}/file`;
  }

  deleteCapture(captureId: string): Promise<unknown> {
    return this.call("DELETE", `/v1/captures/${encodeURIComponent(captureId)}`);
  }

  async notificationPreferences(): Promise<NotificationPreferences> {
    return parseNotificationPreferences(await this.call("GET", "/v1/me/notification-preferences"));
  }

  async setNotificationPreferences(preferences: NotificationPreferences): Promise<NotificationPreferences> {
    return parseNotificationPreferences(await this.call("PUT", "/v1/me/notification-preferences", preferences));
  }

  logoutEverywhere(): Promise<unknown> {
    return this.call("POST", "/v1/me/logout-everywhere");
  }

  deleteAccount(): Promise<unknown> {
    return this.call("DELETE", "/v1/me");
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

export async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}
