// Account-backed report history (N05): server pages, stable cursors, and
// report-scoped deletion that does not depend on a capture ID remembered on
// one device. Dates are the report's creation time on the server, never
// presented as the date the handwriting was written.
import type { PrincessApi, RunSummary } from "@princess/api-client";
import type { ReportSummary } from "@princess/contracts";

export type HistoryApi = Pick<PrincessApi, "reports" | "deleteReport" | "recentAnalyses">;

export interface HistoryItem extends ReportSummary {
  readonly deletion: "NONE" | "REQUESTED";
}

export interface HistoryState {
  readonly items: readonly HistoryItem[];
  readonly nextCursor: string | null;
  /** Runs still queued/running on the server (this or another device). */
  readonly inProgress: readonly RunSummary[];
}

const PAGE = 20;

export class HistoryController {
  private readonly api: HistoryApi;
  private state: HistoryState = { items: [], nextCursor: null, inProgress: [] };

  constructor(api: HistoryApi) {
    this.api = api;
  }

  current(): HistoryState {
    return this.state;
  }

  async refresh(): Promise<HistoryState> {
    const [page, runs] = await Promise.all([this.api.reports(PAGE, null), this.api.recentAnalyses(20)]);
    this.state = {
      items: page.items.map((item) => ({ ...item, deletion: "NONE" as const })),
      nextCursor: page.next_cursor,
      inProgress: runs.filter((run) => run.state === "QUEUED" || run.state === "RUNNING"),
    };
    return this.state;
  }

  async more(): Promise<HistoryState> {
    if (this.state.nextCursor === null) return this.state;
    const page = await this.api.reports(PAGE, this.state.nextCursor);
    const seen = new Set(this.state.items.map((item) => item.report_id));
    this.state = {
      ...this.state,
      items: [...this.state.items, ...page.items.filter((item) => !seen.has(item.report_id))
        .map((item) => ({ ...item, deletion: "NONE" as const }))],
      nextCursor: page.next_cursor,
    };
    return this.state;
  }

  /** Erasure is asynchronous: the item is marked as requested, not claimed erased. */
  async remove(reportId: string): Promise<HistoryState> {
    await this.api.deleteReport(reportId);
    this.state = { ...this.state, items: this.state.items.map((item) => (item.report_id === reportId
      ? { ...item, deletion: "REQUESTED" as const } : item)) };
    return this.state;
  }
}
