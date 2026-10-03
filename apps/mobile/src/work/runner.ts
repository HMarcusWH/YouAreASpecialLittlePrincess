// Drives the current principal's unfinished operations while the app is in
// the foreground: advance the next step, poll started runs with bounded
// back-off (and the server's Retry-After), stop when nothing is active.
// Suspension stops all timers; foregrounding reconciles immediately, because
// mobile background time is not guaranteed and server jobs are durable.
import { TERMINAL_PHASES, type WorkEntry, type WorkJournal } from "./journal.ts";
import type { CaptureWorkflow } from "./capture-workflow.ts";

export interface Timers {
  setTimeout(callback: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

const IDLE_CHECK_MS = 30_000;
const MIN_DELAY_MS = 250;

export class WorkRunner {
  private readonly workflow: CaptureWorkflow;
  private readonly journal: WorkJournal;
  private readonly timers: Timers;
  private readonly now: () => Date;
  private principalId: string | null = null;
  private generation = 0;
  private suspended = false;
  private handle: unknown = null;
  private ticking: Promise<void> | null = null;
  private readonly listeners = new Set<(entries: readonly WorkEntry[]) => void>();
  private entries: readonly WorkEntry[] = [];

  constructor(workflow: CaptureWorkflow, journal: WorkJournal, timers: Timers, now: () => Date = () => new Date()) {
    this.workflow = workflow;
    this.journal = journal;
    this.timers = timers;
    this.now = now;
  }

  subscribe(listener: (entries: readonly WorkEntry[]) => void): () => void {
    this.listeners.add(listener);
    listener(this.entries);
    return () => { this.listeners.delete(listener); };
  }

  snapshot(): readonly WorkEntry[] {
    return this.entries;
  }

  /** Bind to a principal; work of any other principal is never touched. */
  start(principalId: string): void {
    if (this.principalId === principalId) {
      this.kick();
      return;
    }
    this.stop();
    this.principalId = principalId;
    this.kick();
  }

  stop(): void {
    this.generation += 1;
    this.principalId = null;
    this.clear();
    this.publish([]);
  }

  suspend(): void {
    this.suspended = true;
    this.clear();
  }

  resume(): void {
    this.suspended = false;
    this.kick();
  }

  /** Re-evaluate now (new work, pull-to-refresh, foreground). */
  kick(): void {
    this.clear();
    if (this.principalId === null || this.suspended) return;
    void this.tick();
  }

  /** Wait for the current tick (tests and explicit refresh). */
  async settle(): Promise<void> {
    while (this.ticking) await this.ticking;
  }

  private clear(): void {
    if (this.handle !== null) this.timers.clearTimeout(this.handle);
    this.handle = null;
  }

  private publish(entries: readonly WorkEntry[]): void {
    this.entries = entries;
    for (const listener of this.listeners) listener(entries);
  }

  private tick(): Promise<void> {
    if (this.ticking) return this.ticking;
    const run = this.runOnce().finally(() => { this.ticking = null; });
    this.ticking = run;
    return run;
  }

  private async runOnce(): Promise<void> {
    const generation = this.generation;
    const principalId = this.principalId;
    if (principalId === null) return;
    const now = this.now().getTime();
    for (const entry of await this.journal.list(principalId)) {
      if (generation !== this.generation || this.suspended) return;
      if (TERMINAL_PHASES.has(entry.phase) || entry.blocked === "USER") continue;
      if (entry.notBefore !== null && Date.parse(entry.notBefore) > now) continue;
      try {
        if (entry.phase === "STARTED") await this.workflow.poll(principalId, entry.opId);
        else await this.workflow.advance(principalId, entry.opId);
      } catch {
        // An unexpected local failure stays visible on the entry; the loop keeps serving the others.
      }
    }
    if (generation !== this.generation) return;
    const entries = await this.journal.list(principalId);
    this.publish(entries);
    this.schedule(entries, generation);
  }

  private schedule(entries: readonly WorkEntry[], generation: number): void {
    if (this.suspended || generation !== this.generation) return;
    const active = entries.filter((e) => !TERMINAL_PHASES.has(e.phase) && e.blocked !== "USER");
    if (active.length === 0) return;
    const now = this.now().getTime();
    const due = Math.min(...active.map((e) => (e.notBefore === null ? now : Date.parse(e.notBefore))));
    const delay = Math.min(IDLE_CHECK_MS, Math.max(MIN_DELAY_MS, due - now));
    this.handle = this.timers.setTimeout(() => {
      this.handle = null;
      if (generation === this.generation) void this.tick();
    }, delay);
  }
}
