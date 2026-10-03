// The native capture-to-report operation as a resumable state machine.
//
// Every step reuses an idempotent server operation and is recorded in the
// journal before and after its side effect:
//   PREPARED --reserve--> RESERVED --PUT--> UPLOADED --complete--> COMPLETED
//   --grant(request_id)--> PERMITTED --start(dedupe)--> STARTED --poll--> SUCCEEDED
// Upload completion converges on the same capture for the same digest, the
// permission grant is keyed by a request ID derived from the operation, and
// analysis start is deduplicated per capture, so replaying any step after
// process death or a lost response creates no second business result.
// Upload reservation is the one non-idempotent call: a lost reservation
// response costs one daily slot, which is recorded, and the orphaned slot
// expires server-side. Byte-level resumable upload is not offered.
import {
  ApiError, TransportError, nextPollDelayMs, type AnalysisState, type Capture, type RunStatus, type UploadMediaType,
  type UploadTicket,
} from "@princess/api-client";

import type { Blocker, LocalDerivative, WorkEntry, WorkJournal } from "./journal.ts";
import { TERMINAL_PHASES } from "./journal.ts";

export interface WorkflowApi {
  reserveUpload(mediaType: UploadMediaType): Promise<UploadTicket>;
  completeUpload(uploadId: string, sha256: string): Promise<Capture>;
  recordPermission(choice: { purpose_id: string; scope_kind: string; scope_ref: string | null;
                             decision: "GRANT" | "DENY" | "WITHDRAW"; notice_version: string;
                             request_id: string }): Promise<unknown>;
  startAnalysis(captureId: string): Promise<{ readonly run_id: string; readonly state: AnalysisState }>;
  analysis(runId: string): Promise<RunStatus>;
  cancelAnalysis(runId: string): Promise<unknown>;
  deleteCapture(captureId: string): Promise<unknown>;
}

export interface LocalFiles {
  /** Digest and size of the private file's current bytes; null when it no longer exists. */
  digest(uri: string): Promise<{ readonly sha256: string; readonly bytes: number } | null>;
  /** PUT the file to the server-issued slot (allowlisted origin, no credential). */
  upload(ticket: UploadTicket, uri: string, mediaType: UploadMediaType): Promise<void>;
  remove(uri: string): Promise<void>;
}

export interface PreparedImage {
  readonly uri: string;
  readonly mediaType: UploadMediaType;
  readonly width: number;
  readonly height: number;
  readonly source: "CAMERA" | "LIBRARY";
}

const SLOT_SAFETY_MS = 30_000;
const MAX_DIGEST_RETRIES = 2;

// Completion refusals that describe the image itself: retrying cannot help.
const IMAGE_REFUSALS = new Set([
  "unsupported_media", "unsupported_media_heif", "unsupported_media_gif", "unsupported_media_webp",
  "media_type_mismatch", "animated_or_multi_frame_image", "image_dimensions_out_of_range", "image_too_many_pixels",
  "invalid_orientation", "upload_too_large", "image_too_large", "content_type_mismatch", "media_type_not_allowed",
]);

export class WorkflowError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.name = "WorkflowError";
    this.code = code;
  }
}

export class CaptureWorkflow {
  private readonly api: WorkflowApi;
  private readonly files: LocalFiles;
  private readonly journal: WorkJournal;
  private readonly now: () => Date;
  private readonly newId: () => string;
  private readonly running = new Map<string, Promise<WorkEntry>>();

  constructor(deps: { api: WorkflowApi; files: LocalFiles; journal: WorkJournal; now?: () => Date;
                      newId: () => string }) {
    this.api = deps.api;
    this.files = deps.files;
    this.journal = deps.journal;
    this.now = deps.now ?? (() => new Date());
    this.newId = deps.newId;
  }

  /** Record the intent and the exact local bytes before any network call. */
  async create(principalId: string, image: PreparedImage, noticeVersion: string,
               options: { readonly retainImage?: boolean } = {}): Promise<WorkEntry> {
    const digest = await this.files.digest(image.uri);
    if (digest === null) throw new WorkflowError("local_file_missing");
    const at = this.now().toISOString();
    const local: LocalDerivative = { uri: image.uri, sha256: digest.sha256, bytes: digest.bytes,
                                     mediaType: image.mediaType, width: image.width, height: image.height,
                                     source: image.source };
    return this.journal.put({
      v: 1, opId: `op_${this.newId()}`, principalId, createdAt: at, updatedAt: at, phase: "PREPARED", local,
      noticeVersion, retainImage: options.retainImage === true, upload: null, captureId: null, runId: null, reportId: null, errorCode: null, blocked: null,
      notBefore: null, attempts: 0, reservations: 0,
    }, this.now());
  }

  /**
   * Drive one operation as far as it can go now: until it is STARTED (the
   * caller polls), terminal, or blocked. Concurrent calls share one run.
   */
  advance(principalId: string, opId: string): Promise<WorkEntry> {
    const key = `${principalId}|${opId}`;
    const existing = this.running.get(key);
    if (existing) return existing;
    const run = this.drive(principalId, opId).finally(() => this.running.delete(key));
    this.running.set(key, run);
    return run;
  }

  private async load(principalId: string, opId: string): Promise<WorkEntry> {
    const entry = await this.journal.get(principalId, opId);
    if (entry === null) throw new WorkflowError("operation_not_found");
    return entry;
  }

  private save(entry: WorkEntry, patch: Partial<WorkEntry>): Promise<WorkEntry> {
    // A phase change is progress: an earlier back-off no longer applies unless the patch sets one.
    const progressed = patch.phase !== undefined && patch.phase !== entry.phase && patch.blocked === undefined
      ? { blocked: null, notBefore: null } : {};
    return this.journal.put({ ...entry, ...progressed, ...patch, updatedAt: this.now().toISOString() }, this.now());
  }

  private async drive(principalId: string, opId: string): Promise<WorkEntry> {
    let entry = await this.load(principalId, opId);
    for (let guard = 0; guard < 12; guard += 1) {
      if (TERMINAL_PHASES.has(entry.phase) || entry.phase === "STARTED") return entry;
      if (entry.blocked === "USER") return entry;
      if (entry.notBefore !== null && Date.parse(entry.notBefore) > this.now().getTime()) return entry;
      const next = await this.step(entry);
      if (next.blocked !== null) return next;
      entry = next;
    }
    return entry;
  }

  private async step(entry: WorkEntry): Promise<WorkEntry> {
    try {
      switch (entry.phase) {
        case "PREPARED": return await this.reserve(entry);
        case "RESERVED": return await this.put(entry);
        case "UPLOADED": return await this.complete(entry);
        case "COMPLETED": return await this.permit(entry);
        case "PERMITTED": return await this.start(entry);
        default: return entry;
      }
    } catch (error) {
      // Re-read: the step may have recorded progress (such as a counted reservation) before failing.
      return this.failStep(await this.load(entry.principalId, entry.opId), error);
    }
  }

  private async reserve(entry: WorkEntry): Promise<WorkEntry> {
    if (entry.local === null) return this.save(entry, { phase: "FAILED", errorCode: "local_file_missing", blocked: null });
    // Count the slot before asking: if the response is lost, the cost is still on record.
    const counted = await this.save(entry, { reservations: entry.reservations + 1 });
    const ticket = await this.api.reserveUpload(entry.local.mediaType);
    if (ticket.max_bytes < entry.local.bytes) {
      return this.save(counted, { phase: "FAILED", errorCode: "image_too_large", blocked: null });
    }
    return this.save(counted, {
      phase: "RESERVED", upload: { uploadId: ticket.upload_id, url: ticket.url, expiresAt: ticket.expires_at,
                                   maxBytes: ticket.max_bytes },
      errorCode: null, blocked: null, notBefore: null, attempts: 0,
    });
  }

  private slotUsable(entry: WorkEntry): boolean {
    return entry.upload !== null && Date.parse(entry.upload.expiresAt) - SLOT_SAFETY_MS > this.now().getTime();
  }

  private async put(entry: WorkEntry): Promise<WorkEntry> {
    if (entry.local === null) return this.save(entry, { phase: "FAILED", errorCode: "local_file_missing", blocked: null });
    if (!this.slotUsable(entry)) return this.save(entry, { phase: "PREPARED", upload: null, errorCode: "upload_expired" });
    const current = await this.files.digest(entry.local.uri);
    if (current === null) return this.save(entry, { phase: "FAILED", errorCode: "local_file_missing", blocked: null });
    if (current.sha256 !== entry.local.sha256) {
      // The private derivative changed after it was recorded: never upload bytes the digest does not describe.
      return this.save(entry, { phase: "FAILED", errorCode: "local_file_changed", blocked: null });
    }
    const slot = entry.upload!;
    await this.files.upload({ upload_id: slot.uploadId, method: "PUT", url: slot.url, expires_at: slot.expiresAt,
                              max_bytes: slot.maxBytes }, entry.local.uri, entry.local.mediaType);
    return this.save(entry, { phase: "UPLOADED", errorCode: null, blocked: null, notBefore: null, attempts: 0 });
  }

  private async complete(entry: WorkEntry): Promise<WorkEntry> {
    const capture = await this.api.completeUpload(entry.upload!.uploadId, entry.local!.sha256);
    const done = await this.save(entry, { phase: "COMPLETED", captureId: capture.capture_id, errorCode: null,
                                          blocked: null, notBefore: null, attempts: 0 });
    // The server holds verified bytes now; the private copy is no longer needed.
    await this.removeLocal(done);
    return done;
  }

  private async permit(entry: WorkEntry): Promise<WorkEntry> {
    // Each purpose is its own decision with its own request ID, so replays converge on one event each.
    await this.api.recordPermission({
      purpose_id: "service_processing", scope_kind: "SPECIMEN", scope_ref: entry.captureId, decision: "GRANT",
      notice_version: entry.noticeVersion, request_id: `mobile.${entry.opId}.service`,
    });
    if (entry.retainImage) {
      await this.api.recordPermission({
        purpose_id: "image_retention", scope_kind: "SPECIMEN", scope_ref: entry.captureId, decision: "GRANT",
        notice_version: entry.noticeVersion, request_id: `mobile.${entry.opId}.retention`,
      });
    }
    return this.save(entry, { phase: "PERMITTED", errorCode: null, blocked: null, notBefore: null, attempts: 0 });
  }

  private async start(entry: WorkEntry): Promise<WorkEntry> {
    const run = await this.api.startAnalysis(entry.captureId!);
    return this.save(entry, { phase: "STARTED", runId: run.run_id, errorCode: null, blocked: null, notBefore: null,
                              attempts: 0 });
  }

  /** One status read of a STARTED operation. A timeout is not a failure; it is retried. */
  async poll(principalId: string, opId: string): Promise<WorkEntry> {
    const entry = await this.load(principalId, opId);
    if (entry.phase !== "STARTED" || entry.runId === null) return entry;
    try {
      const status = await this.api.analysis(entry.runId);
      if (status.state === "SUCCEEDED") {
        return this.save(entry, { phase: "SUCCEEDED", reportId: status.report_id, errorCode: null, blocked: null,
                                  notBefore: null });
      }
      if (status.state === "FAILED") {
        return this.save(entry, { phase: "FAILED", errorCode: status.error_code ?? "analysis_failed", blocked: null });
      }
      if (status.state === "CANCELLED") {
        return this.save(entry, { phase: "CANCELLED", errorCode: status.error_code, blocked: null });
      }
      return this.save(entry, { errorCode: null, blocked: null, attempts: entry.attempts + 1,
                                notBefore: new Date(this.now().getTime() + nextPollDelayMs(entry.attempts)).toISOString() });
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return this.save(entry, { phase: "FAILED", errorCode: "run_not_found", blocked: null });
      }
      return this.failStep(entry, error);
    }
  }

  /** Explicit user cancellation. Leaving a screen never cancels server work. */
  async cancel(principalId: string, opId: string): Promise<WorkEntry> {
    const entry = await this.load(principalId, opId);
    if (TERMINAL_PHASES.has(entry.phase)) return entry;
    if (entry.runId !== null) {
      await this.api.cancelAnalysis(entry.runId);
      return this.save(entry, { phase: "CANCELLED", errorCode: "cancelled_by_user", blocked: null });
    }
    return this.discard(principalId, opId);
  }

  /**
   * Abandon work that has no run yet: remove the private file and, if the
   * server already holds a verified capture, request its deletion.
   */
  async discard(principalId: string, opId: string): Promise<WorkEntry> {
    const entry = await this.load(principalId, opId);
    if (TERMINAL_PHASES.has(entry.phase)) return entry;
    if (entry.runId !== null) throw new WorkflowError("analysis_already_started");
    if (entry.captureId !== null) {
      try {
        await this.api.deleteCapture(entry.captureId);
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404)) throw error;
      }
    }
    await this.removeLocal(entry);
    return this.save(entry, { phase: "ABANDONED", local: null, errorCode: "discarded_by_user", blocked: null });
  }

  /** The user reviewed a newer notice after the server refused the recorded one. */
  async reconsent(principalId: string, opId: string, noticeVersion: string): Promise<WorkEntry> {
    const entry = await this.load(principalId, opId);
    return this.save(entry, { noticeVersion, blocked: null, errorCode: null, notBefore: null });
  }

  /** Clear a back-off so the next advance runs now (pull-to-refresh, foreground). */
  async retryNow(principalId: string, opId: string): Promise<WorkEntry> {
    const entry = await this.load(principalId, opId);
    if (entry.blocked === "USER" && entry.errorCode !== "signin_required" && entry.errorCode !== "network") {
      return entry;
    }
    return this.save(entry, { notBefore: null, blocked: null });
  }

  private async removeLocal(entry: WorkEntry): Promise<void> {
    if (entry.local === null) return;
    try {
      await this.files.remove(entry.local.uri);
    } catch {
      // The startup sweep removes expired private files that no journal entry references.
    }
  }

  private async failStep(entry: WorkEntry, error: unknown): Promise<WorkEntry> {
    const attempts = entry.attempts + 1;
    const later = (blocked: Blocker, code: string, err: unknown = error) => this.save(entry, {
      blocked, errorCode: code, attempts,
      notBefore: new Date(this.now().getTime() + nextPollDelayMs(attempts, err)).toISOString(),
    });
    if (error instanceof TransportError) return later("RETRY", "network");
    if (!(error instanceof ApiError)) throw error;
    const { status, code } = error;
    if (entry.phase === "RESERVED") {
      // Storage answers for the slot itself: a bad, expired or revoked signature needs a new slot.
      if (status === 401 || status === 403 || status === 404 || code === "upload_expired") {
        return this.save(entry, { phase: "PREPARED", upload: null, errorCode: code, attempts: 0, blocked: null });
      }
    } else if (status === 401) {
      return this.save(entry, { blocked: "USER", errorCode: "signin_required", attempts });
    }
    if (status >= 500 && status !== 501) return later("RETRY", code);
    if (status === 429 || code === "uploads_disabled") return later("WAIT", code);
    if (code === "notice_does_not_cover_purpose" || (entry.phase === "COMPLETED" && status === 422)) {
      return this.save(entry, { blocked: "USER", errorCode: "notice_not_accepted", attempts });
    }
    if (code === "permission_not_granted" || (entry.phase === "PERMITTED" && status === 403)) {
      // Withdrawn or never recorded: the user must choose again; nothing is retried silently.
      return this.save(entry, { phase: "COMPLETED", blocked: "USER", errorCode: "permission_not_granted", attempts });
    }
    if (entry.phase === "UPLOADED") {
      if (code === "completion_in_progress") return later("RETRY", code);
      if (code === "upload_expired" || code === "upload_not_found") {
        return this.save(entry, { phase: "PREPARED", upload: null, errorCode: code, attempts: 0, blocked: null });
      }
      if (code === "digest_mismatch" && attempts <= MAX_DIGEST_RETRIES) {
        // The stored bytes were not ours: send them again to the same slot.
        return this.save(entry, { phase: "RESERVED", errorCode: code, attempts, blocked: null });
      }
    }
    if (IMAGE_REFUSALS.has(code) || status === 413 || status === 404 || status === 409 || status === 422) {
      const done = await this.save(entry, { phase: "FAILED", errorCode: code, blocked: null, attempts });
      await this.removeLocal(done);
      return done;
    }
    return later("RETRY", code);
  }
}
