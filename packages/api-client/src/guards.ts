// Runtime validation at the trust boundary. A typed API response is only as
// good as this check: payloads are never cast into contract types.
import type { Action, Fact, Notice, ReportSection, ReportViewModel } from "@princess/contracts";

export class PayloadError extends Error {
  readonly path: string;

  constructor(path: string, message: string) {
    super(`${path}: ${message}`);
    this.name = "PayloadError";
    this.path = path;
  }
}

const AVAILABILITY = new Set(["READY", "MISSING", "NOT_IMPLEMENTED", "INELIGIBLE", "UNCALIBRATED", "LOCKED", "PENDING",
                              "FAILED", "REVOKED"]);
const EVIDENCE = new Set(["MEASURED", "COMPUTATIONAL_PROXY", "REFERENCE_STATISTIC", "AUTHORED_CONTENT",
                          "TRADITIONAL_ASSOCIATION", "AI_SYNTHESIS"]);
const PROJECTIONS = new Set(["OWNER", "FREE", "PREMIUM", "SHARE", "EXPORT"]);
const NOTICE_CLASSES = new Set(["MEASURED", "PROXY", "REFERENCE", "TRADITIONAL", "AI", "PRIVACY"]);
const ACTION_KINDS = new Set(["COMPARE", "EXPORT", "SHARE", "SAVE", "DELETE", "PURCHASE"]);
const OPAQUE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const SUPPORTED_MAJOR = "1";

type Json = Record<string, unknown>;

function object(value: unknown, path: string): Json {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new PayloadError(path, "expected an object");
  }
  return value as Json;
}

function array(value: unknown, path: string, max: number): unknown[] {
  if (!Array.isArray(value) || value.length > max) {
    throw new PayloadError(path, `expected an array of at most ${max}`);
  }
  return value;
}

function str(value: unknown, path: string, pattern?: RegExp): string {
  if (typeof value !== "string" || (pattern !== undefined && !pattern.test(value))) {
    throw new PayloadError(path, "unexpected string");
  }
  return value;
}

function member(value: unknown, allowed: Set<string>, path: string): string {
  const text = str(value, path);
  if (!allowed.has(text)) throw new PayloadError(path, `unknown value ${JSON.stringify(text).slice(0, 40)}`);
  return text;
}

function factValue(value: unknown, path: string): void {
  if (value === null || typeof value === "boolean" || typeof value === "string") return;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new PayloadError(path, "non-finite number");
    return;
  }
  if (Array.isArray(value) && value.every((v) => typeof v === "number" && Number.isFinite(v))) return;
  throw new PayloadError(path, "unsupported fact value");
}

function fact(raw: unknown, path: string): Fact {
  const f = object(raw, path);
  str(f.fact_id, `${path}/fact_id`, OPAQUE);
  str(f.feature_id, `${path}/feature_id`, OPAQUE);
  const availability = member(f.availability, AVAILABILITY, `${path}/availability`);
  member(f.evidence_class, EVIDENCE, `${path}/evidence_class`);
  factValue(f.value, `${path}/value`);
  if ((availability === "MISSING" || availability === "NOT_IMPLEMENTED") && f.value !== null) {
    throw new PayloadError(`${path}/value`, "an unavailable fact cannot carry a value");
  }
  object(f.quality, `${path}/quality`);
  return f as unknown as Fact;
}

function section(raw: unknown, path: string, factIds: Set<string>): ReportSection {
  const s = object(raw, path);
  str(s.section_id, `${path}/section_id`, OPAQUE);
  member(s.availability, AVAILABILITY, `${path}/availability`);
  for (const [i, id] of array(s.fact_ids, `${path}/fact_ids`, 256).entries()) {
    if (!factIds.has(str(id, `${path}/fact_ids/${i}`))) {
      throw new PayloadError(`${path}/fact_ids/${i}`, "section references a fact that is not in this view");
    }
  }
  return s as unknown as ReportSection;
}

export function parseReportView(raw: unknown): ReportViewModel {
  const view = object(raw, "");
  const version = str(view.contract_version, "/contract_version");
  if (version.split(".")[0] !== SUPPORTED_MAJOR) {
    throw new PayloadError("/contract_version", `unsupported contract major ${version}`);
  }
  str(view.source_report_id, "/source_report_id", OPAQUE);
  member(view.projection, PROJECTIONS, "/projection");
  const facts = array(view.facts, "/facts", 1024).map((f, i) => fact(f, `/facts/${i}`));
  const ids = new Set(facts.map((f) => f.fact_id));
  array(view.sections, "/sections", 128).forEach((s, i) => section(s, `/sections/${i}`, ids));
  array(view.notices, "/notices", 128).forEach((n, i) => {
    const notice = object(n, `/notices/${i}`) as unknown as Notice;
    member(notice.class, NOTICE_CLASSES, `/notices/${i}/class`);
  });
  array(view.actions, "/actions", 64).forEach((a, i) => {
    const action = object(a, `/actions/${i}`) as unknown as Action;
    member(action.kind, ACTION_KINDS, `/actions/${i}/kind`);
    if (typeof action.enabled !== "boolean") throw new PayloadError(`/actions/${i}/enabled`, "expected boolean");
  });
  array(view.authorized_asset_ids, "/authorized_asset_ids", 128);
  if (view.projection === "FREE" && (view.sections as ReportSection[]).some((s) => s.premium_section_id !== null)) {
    throw new PayloadError("/sections", "a Free view cannot carry Premium sections");
  }
  return view as unknown as ReportViewModel;
}

export type RunState = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
export interface RunStatus {
  readonly run_id: string;
  readonly state: RunState;
  readonly report_id: string | null;
  readonly error_code: string | null;
}

const RUN_STATES = new Set(["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]);

export function parseRunStatus(raw: unknown): RunStatus {
  const status = object(raw, "");
  str(status.run_id, "/run_id", OPAQUE);
  member(status.state, RUN_STATES, "/state");
  if (status.report_id !== null && status.report_id !== undefined) str(status.report_id, "/report_id", OPAQUE);
  if (status.state === "SUCCEEDED" && typeof status.report_id !== "string") {
    throw new PayloadError("/report_id", "a succeeded run names its report");
  }
  return {
    run_id: status.run_id as string,
    state: status.state as RunState,
    report_id: (status.report_id as string | null | undefined) ?? null,
    error_code: typeof status.error_code === "string" ? status.error_code : null,
  };
}
