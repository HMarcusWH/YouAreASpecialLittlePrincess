// In-memory model of the intake API's business semantics (T04), used to test
// native recovery: reservation is not idempotent, completion converges on the
// same capture for the same digest, permission grants are keyed by request ID
// and analysis start is deduplicated per capture. ``lose`` injects a response
// lost *after* the server applied the effect, the hard case for recovery.
import { ApiError, TransportError, sha256HexSync, type AnalysisState, type Capture, type RunStatus,
         type UploadMediaType, type UploadTicket } from "@princess/api-client";

import type { WorkflowApi } from "../../src/work/capture-workflow.ts";

type Method = keyof WorkflowApi | "put";

export class FakeIntakeServer implements WorkflowApi {
  now: () => Date;
  quota = 3;
  reservations = 0;
  readonly uploads = new Map<string, { mediaType: string; expiresAt: number; bytes: Uint8Array | null;
                                       captureId: string | null }>();
  readonly captures = new Map<string, { sha256: string; deleted: boolean; width: number; height: number }>();
  readonly grants = new Map<string, string>();  // request_id -> capture
  readonly granted = new Set<string>();
  readonly runs = new Map<string, { captureId: string; state: AnalysisState; reportId: string | null;
                                    error: string | null }>();
  readonly startCalls: string[] = [];
  private counter = 0;
  private faults: Array<{ method: Method; error: Error; afterEffect: boolean }> = [];

  constructor(now: () => Date) {
    this.now = now;
  }

  /** The next call of ``method`` fails; with ``afterEffect`` the server applied it first (lost response). */
  fail(method: Method, error: Error, afterEffect = false): void {
    this.faults.push({ method, error, afterEffect });
  }

  lose(method: Method): void {
    this.fail(method, new TransportError("NETWORK"), true);
  }

  private async around<T>(method: Method, effect: () => T): Promise<T> {
    const index = this.faults.findIndex((f) => f.method === method);
    if (index >= 0) {
      const [fault] = this.faults.splice(index, 1);
      if (fault!.afterEffect) effect();
      throw fault!.error;
    }
    return effect();
  }

  private id(prefix: string): string {
    this.counter += 1;
    return `${prefix}_${this.counter}`;
  }

  reserveUpload(mediaType: UploadMediaType): Promise<UploadTicket> {
    return this.around("reserveUpload", () => {
      if (this.reservations >= this.quota) throw new ApiError(429, "upload_quota_exceeded", 3_600_000);
      this.reservations += 1;
      const uploadId = this.id("upl");
      const expiresAt = this.now().getTime() + 900_000;
      this.uploads.set(uploadId, { mediaType, expiresAt, bytes: null, captureId: null });
      return { upload_id: uploadId, method: "PUT" as const, url: `https://uploads.test/v1/${uploadId}?sig=s`,
               expires_at: new Date(expiresAt).toISOString().replace(/\.\d{3}Z$/, "Z"), max_bytes: 20 * 1024 * 1024 };
    });
  }

  /** Wired as FakeLocalFiles.onUpload: the signed PUT. */
  put(ticket: UploadTicket, bytes: Uint8Array): Promise<void> {
    return this.around("put", () => {
      const upload = this.uploads.get(ticket.upload_id);
      if (!upload || upload.captureId !== null) throw new ApiError(404, "upload_not_found");
      if (this.now().getTime() >= upload.expiresAt) throw new ApiError(401, "bad_signature");
      upload.bytes = bytes;
    });
  }

  completeUpload(uploadId: string, sha256: string): Promise<Capture> {
    return this.around("completeUpload", () => {
      const upload = this.uploads.get(uploadId);
      if (!upload) throw new ApiError(404, "upload_not_found");
      if (upload.captureId !== null) {
        const existing = this.captures.get(upload.captureId)!;
        if (existing.sha256 !== sha256) throw new ApiError(409, "upload_completed_with_different_bytes");
        return { capture_id: upload.captureId, width: existing.width, height: existing.height,
                 media_type: upload.mediaType as UploadMediaType };
      }
      if (this.now().getTime() >= upload.expiresAt) throw new ApiError(409, "upload_expired");
      if (upload.bytes === null) throw new ApiError(404, "upload_not_found");
      if (sha256HexSync(upload.bytes) !== sha256) throw new ApiError(409, "digest_mismatch");
      const captureId = this.id("capture");
      upload.captureId = captureId;
      this.captures.set(captureId, { sha256, deleted: false, width: 900, height: 360 });
      return { capture_id: captureId, width: 900, height: 360, media_type: upload.mediaType as UploadMediaType };
    });
  }

  recordPermission(choice: { purpose_id: string; scope_kind: string; scope_ref: string | null;
                             decision: "GRANT" | "DENY" | "WITHDRAW"; notice_version: string;
                             request_id: string }): Promise<unknown> {
    return this.around("recordPermission", () => {
      if (choice.notice_version !== "notice.consent-choices:1") throw new ApiError(422, "notice_does_not_cover_purpose");
      const previous = this.grants.get(choice.request_id);
      if (previous !== undefined && previous !== choice.scope_ref) throw new ApiError(409, "request_id_reused");
      this.grants.set(choice.request_id, choice.scope_ref!);
      if (choice.decision === "GRANT") this.granted.add(choice.scope_ref!);
      else this.granted.delete(choice.scope_ref!);
      return { status: "GRANTED" };
    });
  }

  startAnalysis(captureId: string): Promise<{ run_id: string; state: AnalysisState }> {
    return this.around("startAnalysis", () => {
      this.startCalls.push(captureId);
      const capture = this.captures.get(captureId);
      if (!capture || capture.deleted) throw new ApiError(404, "capture_not_found");
      if (!this.granted.has(captureId)) throw new ApiError(403, "permission_not_granted");
      for (const [runId, run] of this.runs) if (run.captureId === captureId) return { run_id: runId, state: run.state };
      const runId = this.id("run");
      this.runs.set(runId, { captureId, state: "QUEUED", reportId: null, error: null });
      return { run_id: runId, state: "QUEUED" as const };
    });
  }

  analysis(runId: string): Promise<RunStatus> {
    return this.around("analysis", () => {
      const run = this.runs.get(runId);
      if (!run || this.captures.get(run.captureId)?.deleted) throw new ApiError(404, "run_not_found");
      return { run_id: runId, state: run.state, report_id: run.reportId, error_code: run.error };
    });
  }

  cancelAnalysis(runId: string): Promise<unknown> {
    return this.around("cancelAnalysis", () => {
      const run = this.runs.get(runId);
      if (!run) throw new ApiError(404, "run_not_found");
      if (run.state === "QUEUED" || run.state === "RUNNING") run.state = "CANCELLED";
      return { run_id: runId, state: run.state };
    });
  }

  deleteCapture(captureId: string): Promise<unknown> {
    return this.around("deleteCapture", () => {
      const capture = this.captures.get(captureId);
      if (!capture) throw new ApiError(404, "capture_not_found");
      capture.deleted = true;
      return { state: "DELETION_REQUESTED" };
    });
  }

  /** Worker side: finish the run with a report. */
  succeed(runId: string): string {
    const run = this.runs.get(runId)!;
    run.state = "SUCCEEDED";
    run.reportId = `report_${runId}`;
    return run.reportId;
  }

  running(runId: string): void {
    this.runs.get(runId)!.state = "RUNNING";
  }
}

export class ManualClock {
  private value: number;

  constructor(iso = "2026-10-03T12:00:00Z") {
    this.value = Date.parse(iso);
  }

  now = (): Date => new Date(this.value);

  advance(ms: number): void {
    this.value += ms;
  }
}

export class ManualTimers {
  private next = 1;
  readonly pending = new Map<number, { at: number; callback: () => void }>();
  private readonly clock: ManualClock;

  constructor(clock: ManualClock) {
    this.clock = clock;
  }

  setTimeout = (callback: () => void, ms: number): unknown => {
    const id = this.next++;
    this.pending.set(id, { at: this.clock.now().getTime() + ms, callback });
    return id;
  };

  clearTimeout = (handle: unknown): void => {
    this.pending.delete(handle as number);
  };

  /** Advance the clock to the next timer and fire it. */
  fireNext(): boolean {
    const due = [...this.pending.entries()].sort((a, b) => a[1].at - b[1].at)[0];
    if (!due) return false;
    this.pending.delete(due[0]);
    const delta = due[1].at - this.clock.now().getTime();
    if (delta > 0) this.clock.advance(delta);
    due[1].callback();
    return true;
  }
}
