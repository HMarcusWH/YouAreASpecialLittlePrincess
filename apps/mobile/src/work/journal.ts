// Minimal, owner-bound record of in-flight capture work, written before each
// external side effect so process death or relaunch resumes the same business
// operation instead of starting another. It holds identifiers, private file
// metadata/digests, consent and retry state, and the upload slot URL/expiry. A
// signed upload URL is a scoped capability: never log this journal. It stores
// no image bytes, report bodies, store proofs or account credentials and lives
// in app-private storage, not preferences. See docs/architecture/mobile-lifecycle.md.
import type { UploadMediaType } from "@princess/api-client";

import type { KeyValueFile } from "../platform/contracts.ts";

export const JOURNAL_FILE = "work-journal.v1.json";
const MAX_ENTRIES_PER_PRINCIPAL = 20;
const TERMINAL_RETENTION_MS = 7 * 24 * 3600 * 1000;

export type WorkPhase =
  | "PREPARED"   // local derivative hashed; no slot reserved yet
  | "RESERVED"   // upload slot issued; bytes not acknowledged
  | "UPLOADED"   // PUT acknowledged; completion not acknowledged
  | "COMPLETED"  // capture verified server-side; local bytes no longer needed
  | "PERMITTED"  // service-processing grant recorded for the capture
  | "STARTED"    // analysis run exists; waiting for the durable result
  | "SUCCEEDED" | "FAILED" | "CANCELLED" | "ABANDONED";

export const TERMINAL_PHASES: ReadonlySet<WorkPhase> = new Set(["SUCCEEDED", "FAILED", "CANCELLED", "ABANDONED"]);

export interface LocalDerivative {
  readonly uri: string;
  readonly sha256: string;
  readonly bytes: number;
  readonly mediaType: UploadMediaType;
  readonly width: number;
  readonly height: number;
  readonly source: "CAMERA" | "LIBRARY";
}

export interface UploadSlot {
  readonly uploadId: string;
  readonly url: string;
  readonly expiresAt: string;
  readonly maxBytes: number;
}

export type Blocker = "RETRY" | "WAIT" | "USER";

export interface WorkEntry {
  readonly v: 1;
  readonly opId: string;
  readonly principalId: string;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly phase: WorkPhase;
  readonly local: LocalDerivative | null;
  readonly noticeVersion: string;
  /** The separate, optional choice to keep the original with the report (image_retention). */
  readonly retainImage: boolean;
  readonly upload: UploadSlot | null;
  readonly captureId: string | null;
  readonly runId: string | null;
  readonly reportId: string | null;
  /** Last safe error code; the phase says what still has to happen. */
  readonly errorCode: string | null;
  /** Why the entry is not advancing: transient retry, server back-off, or the user must act. */
  readonly blocked: Blocker | null;
  readonly notBefore: string | null;
  readonly attempts: number;
  /** Upload slots consumed by this intent (a lost reservation response costs one). */
  readonly reservations: number;
}

function valid(entry: unknown): entry is WorkEntry {
  const e = entry as Partial<WorkEntry> | null;
  return !!e && e.v === 1 && typeof e.opId === "string" && typeof e.principalId === "string"
    && typeof e.phase === "string" && typeof e.noticeVersion === "string" && typeof e.retainImage === "boolean";
}

export class WorkJournal {
  private readonly file: KeyValueFile;
  private cache: WorkEntry[] | null = null;
  private writes: Promise<unknown> = Promise.resolve();

  constructor(file: KeyValueFile) {
    this.file = file;
  }

  private async load(): Promise<WorkEntry[]> {
    if (this.cache !== null) return this.cache;
    let entries: WorkEntry[] = [];
    try {
      const raw = await this.file.read(JOURNAL_FILE);
      const parsed = raw === null ? [] : JSON.parse(raw) as unknown;
      entries = Array.isArray(parsed) ? parsed.filter(valid) : [];
    } catch {
      entries = [];  // a corrupt journal is dropped; the server-side run list still recovers work
    }
    this.cache = entries;
    return entries;
  }

  private persist(entries: WorkEntry[]): Promise<void> {
    this.cache = entries;
    const snapshot = JSON.stringify(entries);
    const write = this.writes.then(() => this.file.write(JOURNAL_FILE, snapshot));
    this.writes = write.catch(() => undefined);
    return write;
  }

  async list(principalId: string): Promise<WorkEntry[]> {
    return (await this.load()).filter((e) => e.principalId === principalId)
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }

  async get(principalId: string, opId: string): Promise<WorkEntry | null> {
    return (await this.load()).find((e) => e.opId === opId && e.principalId === principalId) ?? null;
  }

  async put(entry: WorkEntry, now: Date): Promise<WorkEntry> {
    const entries = (await this.load()).filter((e) => e.opId !== entry.opId);
    entries.push(entry);
    return this.persist(prune(entries, now)).then(() => entry);
  }

  /** Remove everything recorded for a principal (sign-out, deletion, account switch). */
  async purge(principalId: string): Promise<WorkEntry[]> {
    const entries = await this.load();
    const removed = entries.filter((e) => e.principalId === principalId);
    await this.persist(entries.filter((e) => e.principalId !== principalId));
    return removed;
  }

  async allLocalUris(): Promise<Set<string>> {
    return new Set((await this.load()).flatMap((e) => (e.local && !TERMINAL_PHASES.has(e.phase) ? [e.local.uri] : [])));
  }
}

function prune(entries: WorkEntry[], now: Date): WorkEntry[] {
  const cutoff = now.getTime() - TERMINAL_RETENTION_MS;
  const fresh = entries.filter((e) => !TERMINAL_PHASES.has(e.phase) || Date.parse(e.updatedAt) >= cutoff);
  const byPrincipal = new Map<string, WorkEntry[]>();
  for (const entry of fresh) byPrincipal.set(entry.principalId, [...(byPrincipal.get(entry.principalId) ?? []), entry]);
  const kept: WorkEntry[] = [];
  for (const list of byPrincipal.values()) {
    const sorted = list.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    // Unfinished work is never dropped to make room; only old terminal entries are.
    const active = sorted.filter((e) => !TERMINAL_PHASES.has(e.phase));
    const terminal = sorted.filter((e) => TERMINAL_PHASES.has(e.phase));
    kept.push(...active, ...terminal.slice(0, Math.max(0, MAX_ENTRIES_PER_PRINCIPAL - active.length)));
  }
  return kept;
}
