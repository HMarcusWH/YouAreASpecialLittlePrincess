// Authorized PDF export on native (N06): request the server rendering of the
// saved projection, poll its status, download it with the bearer credential
// into private temporary storage (size/type bounded), hand it to the share
// sheet and delete the private copy afterwards. No model is ever involved.
import { ApiError, TransportError, pollDelayMs, type AuthorizedDownload, type ExportLayout,
         type ExportStatus } from "@princess/api-client";

import type { AuthorizedFileClient, DownloadedFile, FileShareClient } from "../platform/contracts.ts";

export interface ExportApi {
  requestExport(reportId: string, layout?: ExportLayout): Promise<ExportStatus>;
  exportStatus(exportId: string): Promise<ExportStatus>;
  exportDownload(exportId: string): Promise<AuthorizedDownload>;
}

export type ExportPhase =
  | { readonly status: "PREPARING" }
  | { readonly status: "READY"; readonly file: DownloadedFile; readonly exportId: string }
  | { readonly status: "FAILED" | "REVOKED" | "UNAVAILABLE" | "TIMEOUT" | "CANCELLED"; readonly code: string };

const MAX_POLLS = 40;
const LETTER_REGIONS = new Set(["US", "CA", "MX", "PH", "CL", "CO", "VE"]);

/** Paper size from the device region: Letter where it is the norm, A4 elsewhere. */
export function paperFor(deviceLocale: string | null | undefined): "A4" | "LETTER" {
  const region = /[-_]([A-Z]{2})\b/.exec(deviceLocale ?? "")?.[1];
  return region !== undefined && LETTER_REGIONS.has(region) ? "LETTER" : "A4";
}
const MAX_EXPORT_BYTES = 30 * 1024 * 1024;

export class ExportController {
  private readonly api: ExportApi;
  private readonly files: AuthorizedFileClient;
  private readonly share: FileShareClient;
  private readonly sleep: (ms: number) => Promise<void>;

  constructor(api: ExportApi, files: AuthorizedFileClient, share: FileShareClient,
              sleep: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms))) {
    this.api = api;
    this.files = files;
    this.share = share;
    this.sleep = sleep;
  }

  async prepare(reportId: string, layout: ExportLayout, cancelled: () => boolean = () => false): Promise<ExportPhase> {
    let status: ExportStatus;
    try {
      status = await this.api.requestExport(reportId, layout);
      for (let attempt = 0; status.state === "QUEUED" && attempt < MAX_POLLS; attempt += 1) {
        if (cancelled()) return { status: "CANCELLED", code: "cancelled" };
        await this.sleep(pollDelayMs(attempt));
        status = await this.api.exportStatus(status.export_id);
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 501) return { status: "UNAVAILABLE", code: error.code };
      if (error instanceof ApiError && error.status === 404) return { status: "REVOKED", code: error.code };
      if (error instanceof ApiError || error instanceof TransportError) {
        return { status: "FAILED", code: error instanceof ApiError ? error.code : "network" };
      }
      throw error;
    }
    if (cancelled()) return { status: "CANCELLED", code: "cancelled" };
    if (status.state === "QUEUED") return { status: "TIMEOUT", code: "export_still_queued" };
    if (status.state === "REVOKED") return { status: "REVOKED", code: status.error_code ?? "revoked" };
    if (status.state !== "READY") return { status: "FAILED", code: status.error_code ?? "export_failed" };
    const mediaTypes = status.layout === "A4" || status.layout === "LETTER" ? ["application/pdf"] : ["image/png"];
    const extension = mediaTypes[0] === "application/pdf" ? "pdf" : "png";
    try {
      const file = await this.files.download(await this.api.exportDownload(status.export_id),
                                             `inktrospect-${status.report_id}-r${status.revision}.${extension}`,
                                             { maxBytes: Math.min(MAX_EXPORT_BYTES, (status.size_bytes ?? MAX_EXPORT_BYTES)),
                                               mediaTypes });
      if (cancelled()) {
        await this.files.remove(file.uri);
        return { status: "CANCELLED", code: "cancelled" };
      }
      return { status: "READY", file, exportId: status.export_id };
    } catch (error) {
      if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        return { status: "REVOKED", code: error.code };
      }
      if (error instanceof ApiError || error instanceof TransportError) {
        return { status: "FAILED", code: error instanceof ApiError ? error.code : "network" };
      }
      throw error;
    }
  }

  /** Open the share sheet, then remove the private copy once the sheet has closed. */
  async shareAndClean(file: DownloadedFile): Promise<"SHARED" | "CANCELLED" | "UNAVAILABLE"> {
    try {
      return await this.share.shareAuthorizedFile(file.uri, file.mediaType);
    } finally {
      await this.share.cleanup(file.uri);
    }
  }

  discard(file: DownloadedFile): Promise<void> {
    return this.files.remove(file.uri);
  }
}
