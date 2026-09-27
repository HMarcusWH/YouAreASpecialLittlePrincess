// Runtime validation at the trust boundary. A typed API response is only as
// good as this check: payloads are never cast into contract types.
import type {
  Action, EvidenceBundle, Fact, Notice, ReportPage, ReportSection, ReportSummary, ReportViewModel,
} from "@princess/contracts";

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


const REPORT_KINDS = new Set(["INDIVIDUAL", "PAIR", "HISTORY"]);
const FRAME_UNITS = new Set(["px", "normalized"]);
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;

function reportSummary(raw: unknown, path: string): ReportSummary {
  const item = object(raw, path);
  str(item.report_id, `${path}/report_id`, OPAQUE);
  if (!Number.isInteger(item.revision) || (item.revision as number) < 1) {
    throw new PayloadError(`${path}/revision`, "expected positive integer");
  }
  member(item.kind, REPORT_KINDS, `${path}/kind`);
  str(item.created_at, `${path}/created_at`, RFC3339);
  str(item.locale, `${path}/locale`, /^[a-z]{2}(?:-[A-Z]{2})?$/);
  if (typeof item.has_premium !== "boolean") throw new PayloadError(`${path}/has_premium`, "expected boolean");
  return item as unknown as ReportSummary;
}

export function parseReportPage(raw: unknown): ReportPage {
  const page = object(raw, "");
  const version = str(page.contract_version, "/contract_version");
  if (version.split(".")[0] !== SUPPORTED_MAJOR) {
    throw new PayloadError("/contract_version", `unsupported contract major ${version}`);
  }
  array(page.items, "/items", 50).forEach((item, i) => reportSummary(item, `/items/${i}`));
  if (page.next_cursor !== null) {
    const cursor = str(page.next_cursor, "/next_cursor");
    if (cursor.length > 512) throw new PayloadError("/next_cursor", "cursor too long");
  }
  return page as unknown as ReportPage;
}

function finiteNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new PayloadError(path, "expected finite number");
  return value;
}

function integer(value: unknown, path: string, min: number): number {
  if (!Number.isInteger(value) || (value as number) < min) throw new PayloadError(path, "expected bounded integer");
  return value as number;
}

export function parseEvidenceBundle(raw: unknown): EvidenceBundle {
  const bundle = object(raw, "");
  const version = str(bundle.contract_version, "/contract_version");
  if (version.split(".")[0] !== SUPPORTED_MAJOR) {
    throw new PayloadError("/contract_version", `unsupported contract major ${version}`);
  }
  str(bundle.bundle_id, "/bundle_id", OPAQUE);
  const analysis = object(bundle.analysis, "/analysis");
  for (const key of ["analysis_id", "run_id", "owner_id", "input_asset_id"] as const) {
    str(analysis[key], `/analysis/${key}`, OPAQUE);
  }
  for (const key of ["input_sha256", "processed_sha256"] as const) {
    str(analysis[key], `/analysis/${key}`, /^[0-9a-f]{64}$/);
  }

  const frames = array(bundle.frames, "/frames", 64);
  if (frames.length < 1) throw new PayloadError("/frames", "at least one frame is required");
  frames.forEach((rawFrame, i) => {
    const frame = object(rawFrame, `/frames/${i}`);
    str(frame.frame_id, `/frames/${i}/frame_id`, OPAQUE);
    integer(frame.width, `/frames/${i}/width`, 1);
    integer(frame.height, `/frames/${i}/height`, 1);
    member(frame.unit, FRAME_UNITS, `/frames/${i}/unit`);
    if (frame.parent_frame_id !== null) str(frame.parent_frame_id, `/frames/${i}/parent_frame_id`, OPAQUE);
    if (frame.transform_to_parent !== null) {
      const matrix = array(frame.transform_to_parent, `/frames/${i}/transform_to_parent`, 9);
      if (matrix.length !== 9) throw new PayloadError(`/frames/${i}/transform_to_parent`, "expected 3x3 matrix");
      matrix.forEach((v, j) => finiteNumber(v, `/frames/${i}/transform_to_parent/${j}`));
    }
  });

  array(bundle.regions, "/regions", 4096).forEach((rawRegion, i) => {
    const region = object(rawRegion, `/regions/${i}`);
    str(region.region_id, `/regions/${i}/region_id`, OPAQUE);
    str(region.frame_id, `/regions/${i}/frame_id`, OPAQUE);
    str(region.scope, `/regions/${i}/scope`);
    integer(region.x, `/regions/${i}/x`, 0);
    integer(region.y, `/regions/${i}/y`, 0);
    integer(region.width, `/regions/${i}/width`, 1);
    integer(region.height, `/regions/${i}/height`, 1);
    if (region.parent_region_id !== null) {
      str(region.parent_region_id, `/regions/${i}/parent_region_id`, OPAQUE);
    }
  });

  array(bundle.observations, "/observations", 20000).forEach((rawObservation, i) => {
    const observation = object(rawObservation, `/observations/${i}`);
    for (const key of ["observation_id", "feature_id", "method_id"] as const) {
      str(observation[key], `/observations/${i}/${key}`, OPAQUE);
    }
    str(observation.method_version, `/observations/${i}/method_version`);
    array(observation.region_ids, `/observations/${i}/region_ids`, 64)
      .forEach((id, j) => str(id, `/observations/${i}/region_ids/${j}`, OPAQUE));
    factValue(observation.value, `/observations/${i}/value`);
    if (observation.unit !== null) str(observation.unit, `/observations/${i}/unit`);
    if (typeof observation.accepted !== "boolean") {
      throw new PayloadError(`/observations/${i}/accepted`, "expected boolean");
    }
    if (observation.rejection_reason !== null) {
      str(observation.rejection_reason, `/observations/${i}/rejection_reason`);
    }
  });
  array(bundle.warnings, "/warnings", 256).forEach((warning, i) => str(warning, `/warnings/${i}`));
  return bundle as unknown as EvidenceBundle;
}
