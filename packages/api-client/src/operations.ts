// Runtime guards for operation responses (session, intake, permissions,
// commerce, Premium, feedback, push, comparisons). Like the report guards,
// nothing here trusts a TypeScript cast: an unexpected shape is a PayloadError.
import type { Comparison, Fact, GrantSnapshot, PremiumAnswer, PremiumSoftField } from "@princess/contracts";

import { PayloadError } from "./guards.ts";

type Json = Record<string, unknown>;

const OPAQUE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const SAFE_CODE = /^[a-z0-9_.:-]{1,64}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;
const LOCALE = /^[a-z]{2}(?:-[A-Z]{2})?$/;

function object(value: unknown, path: string): Json {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new PayloadError(path, "expected an object");
  }
  return value as Json;
}

function keys(value: Json, required: readonly string[], optional: readonly string[], path: string): void {
  const allowed = new Set([...required, ...optional]);
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) throw new PayloadError(`${path}/${key}`, "unexpected property");
  }
  for (const key of required) {
    if (!(key in value)) throw new PayloadError(`${path}/${key}`, "required property is missing");
  }
}

function str(value: unknown, path: string, pattern?: RegExp, max = 4096): string {
  if (typeof value !== "string" || value.length > max || (pattern !== undefined && !pattern.test(value))) {
    throw new PayloadError(path, "unexpected string");
  }
  return value;
}

function nullableStr(value: unknown, path: string, pattern?: RegExp, max = 4096): string | null {
  return value === null || value === undefined ? null : str(value, path, pattern, max);
}

function int(value: unknown, path: string, min: number, max = Number.MAX_SAFE_INTEGER): number {
  if (!Number.isInteger(value) || (value as number) < min || (value as number) > max) {
    throw new PayloadError(path, "expected bounded integer");
  }
  return value as number;
}

function finite(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new PayloadError(path, "expected finite number");
  return value;
}

function bool(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new PayloadError(path, "expected boolean");
  return value;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], path: string): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) {
    throw new PayloadError(path, `unknown value ${JSON.stringify(String(value)).slice(0, 40)}`);
  }
  return value as T;
}

function list(value: unknown, path: string, max: number): unknown[] {
  if (!Array.isArray(value) || value.length > max) throw new PayloadError(path, `expected an array of at most ${max}`);
  return value;
}

// --- session -----------------------------------------------------------------

export type PrincipalKind = "ACCOUNT" | "GUEST";

export interface Me {
  readonly principal_id: string;
  readonly kind: PrincipalKind;
}

export function parseMe(raw: unknown): Me {
  const v = object(raw, "");
  keys(v, ["principal_id", "kind"], [], "");
  return { principal_id: str(v.principal_id, "/principal_id", OPAQUE),
           kind: oneOf(v.kind, ["ACCOUNT", "GUEST"] as const, "/kind") };
}

export interface GuestSession {
  readonly principal_id: string;
  readonly guest_token: string;
  readonly expires_at: string | null;
}

export function parseGuestSession(raw: unknown): GuestSession {
  const v = object(raw, "");
  keys(v, ["principal_id", "guest_token", "expires_at"], [], "");
  const token = str(v.guest_token, "/guest_token", undefined, 8192);
  if (token.length < 10 || /\s/.test(token)) throw new PayloadError("/guest_token", "unexpected credential shape");
  return { principal_id: str(v.principal_id, "/principal_id", OPAQUE), guest_token: token,
           expires_at: nullableStr(v.expires_at, "/expires_at", RFC3339) };
}

export function parseGuestTransfer(raw: unknown): { readonly transferred_principal_id: string } {
  const v = object(raw, "");
  keys(v, ["transferred_principal_id"], [], "");
  return { transferred_principal_id: str(v.transferred_principal_id, "/transferred_principal_id", OPAQUE) };
}

export function parseDevIdToken(raw: unknown): string {
  const v = object(raw, "");
  keys(v, ["id_token"], [], "");
  return str(v.id_token, "/id_token", /^\S{10,8192}$/, 8192);
}

export function parseDeletionRequested(raw: unknown): { readonly state: "DELETION_REQUESTED" } {
  const v = object(raw, "");
  keys(v, ["state"], [], "");
  return { state: oneOf(v.state, ["DELETION_REQUESTED"] as const, "/state") };
}

// --- intake ------------------------------------------------------------------

export type UploadMediaType = "image/jpeg" | "image/png";

export interface UploadTicket {
  readonly upload_id: string;
  readonly method: "PUT";
  readonly url: string;
  readonly expires_at: string;
  readonly max_bytes: number;
}

export function parseUploadTicket(raw: unknown): UploadTicket {
  const v = object(raw, "");
  keys(v, ["upload_id", "method", "url", "expires_at", "max_bytes"], [], "");
  const url = str(v.url, "/url", /^https?:\/\/\S+$/, 4096);
  return { upload_id: str(v.upload_id, "/upload_id", OPAQUE), method: oneOf(v.method, ["PUT"] as const, "/method"),
           url, expires_at: str(v.expires_at, "/expires_at", RFC3339), max_bytes: int(v.max_bytes, "/max_bytes", 1) };
}

export interface Capture {
  readonly capture_id: string;
  readonly width: number;
  readonly height: number;
  readonly media_type: UploadMediaType;
}

export function parseCapture(raw: unknown): Capture {
  const v = object(raw, "");
  keys(v, ["capture_id", "width", "height", "media_type"], [], "");
  return { capture_id: str(v.capture_id, "/capture_id", OPAQUE), width: int(v.width, "/width", 1),
           height: int(v.height, "/height", 1),
           media_type: oneOf(v.media_type, ["image/jpeg", "image/png"] as const, "/media_type") };
}

const RUN_STATES = ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"] as const;
export type AnalysisState = (typeof RUN_STATES)[number];

export function parseAnalysisStart(raw: unknown): { readonly run_id: string; readonly state: AnalysisState } {
  const v = object(raw, "");
  keys(v, ["run_id", "state"], [], "");
  return { run_id: str(v.run_id, "/run_id", OPAQUE), state: oneOf(v.state, RUN_STATES, "/state") };
}

export interface RunSummary {
  readonly run_id: string;
  readonly state: AnalysisState;
  readonly report_id: string | null;
  readonly error_code: string | null;
  readonly created_at: string;
}

export function parseRunPage(raw: unknown): { readonly items: readonly RunSummary[] } {
  const v = object(raw, "");
  keys(v, ["items"], [], "");
  const items = list(v.items, "/items", 50).map((item, i): RunSummary => {
    const r = object(item, `/items/${i}`);
    keys(r, ["run_id", "state", "report_id", "error_code", "created_at"], [], `/items/${i}`);
    // A succeeded run may carry no report: its report was deleted, so there is nothing to open.
    return { run_id: str(r.run_id, `/items/${i}/run_id`, OPAQUE), state: oneOf(r.state, RUN_STATES, `/items/${i}/state`),
             report_id: nullableStr(r.report_id, `/items/${i}/report_id`, OPAQUE),
             error_code: nullableStr(r.error_code, `/items/${i}/error_code`, SAFE_CODE),
             created_at: str(r.created_at, `/items/${i}/created_at`, RFC3339) };
  });
  return { items };
}

// --- permissions and notices -----------------------------------------------------

export function parseGrantSnapshot(raw: unknown): GrantSnapshot {
  const v = object(raw, "");
  keys(v, ["contract_version", "grant_id", "owner_id", "purpose_id", "purpose_version", "status", "scope",
           "recorded_at", "effective_at", "policy_sha256"], [], "");
  const version = str(v.contract_version, "/contract_version");
  if (version.split(".")[0] !== "1") throw new PayloadError("/contract_version", `unsupported contract major ${version}`);
  str(v.grant_id, "/grant_id", OPAQUE);
  str(v.owner_id, "/owner_id", OPAQUE);
  str(v.purpose_id, "/purpose_id", OPAQUE);
  int(v.purpose_version, "/purpose_version", 1);
  oneOf(v.status, ["GRANTED", "DENIED", "WITHDRAWN"] as const, "/status");
  str(v.scope, "/scope", /^[A-Z_]{1,32}(?::[A-Za-z0-9][A-Za-z0-9._:-]{0,127})?$/);
  str(v.recorded_at, "/recorded_at", RFC3339);
  str(v.effective_at, "/effective_at", RFC3339);
  str(v.policy_sha256, "/policy_sha256", SHA256);
  return v as unknown as GrantSnapshot;
}

export interface PermissionCheck {
  readonly purpose_id: string;
  readonly allowed: boolean;
  readonly reason: string | null;
}

export function parsePermissionCheck(raw: unknown): PermissionCheck {
  const v = object(raw, "");
  keys(v, ["purpose_id", "allowed", "reason"], [], "");
  return { purpose_id: str(v.purpose_id, "/purpose_id", OPAQUE), allowed: bool(v.allowed, "/allowed"),
           reason: nullableStr(v.reason, "/reason", SAFE_CODE) };
}

export interface NoticePurpose {
  readonly purpose_id: string;
  readonly purpose_version: number;
  readonly label: string;
  readonly explanation: string;
  readonly decline_consequence: string;
}

export interface ConsentNotice {
  readonly notice_version: string;
  readonly status: "DRAFT" | "APPROVED" | "RETIRED";
  readonly accepted_for_use: boolean;
  readonly locale: "en" | "sv";
  readonly purposes: readonly NoticePurpose[];
}

export function parseConsentNotices(raw: unknown): readonly ConsentNotice[] {
  const v = object(raw, "");
  keys(v, ["notices"], [], "");
  return list(v.notices, "/notices", 16).map((n, i): ConsentNotice => {
    const notice = object(n, `/notices/${i}`);
    keys(notice, ["notice_version", "status", "accepted_for_use", "locale", "purposes"], [], `/notices/${i}`);
    const purposes = list(notice.purposes, `/notices/${i}/purposes`, 32).map((p, j): NoticePurpose => {
      const path = `/notices/${i}/purposes/${j}`;
      const purpose = object(p, path);
      keys(purpose, ["purpose_id", "purpose_version", "label", "explanation", "decline_consequence"], [], path);
      return { purpose_id: str(purpose.purpose_id, `${path}/purpose_id`, OPAQUE),
               purpose_version: int(purpose.purpose_version, `${path}/purpose_version`, 1),
               label: str(purpose.label, `${path}/label`, undefined, 200),
               explanation: str(purpose.explanation, `${path}/explanation`, undefined, 2000),
               decline_consequence: str(purpose.decline_consequence, `${path}/decline_consequence`, undefined, 2000) };
    });
    return { notice_version: str(notice.notice_version, `/notices/${i}/notice_version`, /^notice\.[a-z0-9.-]{1,64}:\d{1,6}$/),
             status: oneOf(notice.status, ["DRAFT", "APPROVED", "RETIRED"] as const, `/notices/${i}/status`),
             accepted_for_use: bool(notice.accepted_for_use, `/notices/${i}/accepted_for_use`),
             locale: oneOf(notice.locale, ["en", "sv"] as const, `/notices/${i}/locale`), purposes };
  });
}

// --- commerce and Premium ---------------------------------------------------------

export type StoreRail = "apple_app_store" | "google_play";
export type ClientPlatform = "web" | "ios" | "android";

export interface CatalogProduct {
  readonly product_id: string;
  readonly credits: number;
  readonly rails: Readonly<Record<string, string>>;
  readonly catalog_version: string;
}

export function parseCatalog(raw: unknown): readonly CatalogProduct[] {
  const v = object(raw, "");
  keys(v, ["products"], [], "");
  return list(v.products, "/products", 64).map((p, i): CatalogProduct => {
    const product = object(p, `/products/${i}`);
    keys(product, ["product_id", "credits", "rails", "catalog_version"], [], `/products/${i}`);
    const rails = object(product.rails, `/products/${i}/rails`);
    const out: Record<string, string> = {};
    for (const [rail, storeId] of Object.entries(rails)) {
      oneOf(rail, ["stripe", "apple_app_store", "google_play"] as const, `/products/${i}/rails/${rail}`);
      out[rail] = str(storeId, `/products/${i}/rails/${rail}`, /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/);
    }
    return { product_id: str(product.product_id, `/products/${i}/product_id`, OPAQUE),
             credits: int(product.credits, `/products/${i}/credits`, 1, 1000), rails: out,
             catalog_version: str(product.catalog_version, `/products/${i}/catalog_version`, undefined, 64) };
  });
}

export function parsePaymentAccount(raw: unknown): string {
  const v = object(raw, "");
  keys(v, ["account_ref"], [], "");
  return str(v.account_ref, "/account_ref", /^[A-Za-z0-9-]{8,128}$/);
}

export interface Credits {
  readonly platform: ClientPlatform;
  readonly available: number;
  readonly reserved: number;
}

export function parseCredits(raw: unknown): Credits {
  const v = object(raw, "");
  keys(v, ["platform", "available", "reserved"], [], "");
  return { platform: oneOf(v.platform, ["web", "ios", "android"] as const, "/platform"),
           available: int(v.available, "/available", 0), reserved: int(v.reserved, "/reserved", 0) };
}

export interface ClaimResult {
  readonly outcome: string;
  readonly finish_transaction: boolean;
}

export function parseClaimResult(raw: unknown): ClaimResult {
  const v = object(raw, "");
  keys(v, ["outcome", "finish_transaction"], [], "");
  const outcome = str(v.outcome, "/outcome", SAFE_CODE);
  const finish = bool(v.finish_transaction, "/finish_transaction");
  if (finish && outcome !== "granted" && outcome !== "already_granted") {
    // The client may finish a store transaction only after a durable grant.
    throw new PayloadError("/finish_transaction", "finish without a durable grant");
  }
  return { outcome, finish_transaction: finish };
}

export function parsePremiumRequest(raw: unknown): { readonly job_id: string; readonly created: boolean } {
  const v = object(raw, "");
  keys(v, ["job_id", "created"], [], "");
  return { job_id: str(v.job_id, "/job_id", OPAQUE), created: bool(v.created, "/created") };
}

const JOB_STATES = ["QUEUED", "LEASED", "SUCCEEDED", "FAILED", "CANCELLED"] as const;
export type PremiumJobState = (typeof JOB_STATES)[number];

export interface PremiumJob {
  readonly job_id: string;
  readonly state: PremiumJobState;
  readonly error_code: string | null;
}

export function parsePremiumJob(raw: unknown): PremiumJob {
  const v = object(raw, "");
  keys(v, ["job_id", "state", "error_code"], [], "");
  return { job_id: str(v.job_id, "/job_id", OPAQUE), state: oneOf(v.state, JOB_STATES, "/state"),
           error_code: nullableStr(v.error_code, "/error_code", SAFE_CODE) };
}

export interface PremiumOmission {
  readonly item_id: string;
  readonly reason: string;
  readonly detail: string | null;
}

export interface PremiumContent {
  readonly report_id: string;
  readonly revision: number;
  readonly overlay_id: string;
  readonly evidence_class: "AI_SYNTHESIS";
  readonly answers: readonly PremiumAnswer[];
  readonly soft_fields: readonly PremiumSoftField[];
  readonly omissions: readonly PremiumOmission[];
}

const ANSWER_STATES = ["ANSWERED", "OBSERVED_ABSENT", "NOT_ASSESSABLE", "NOT_APPLICABLE", "CONFLICTING_EVIDENCE",
                       "NO_ELIGIBLE_CANDIDATE"] as const;

function idList(value: unknown, path: string, max: number): string[] {
  return list(value, path, max).map((id, i) => str(id, `${path}/${i}`, OPAQUE));
}

export function parsePremiumContent(raw: unknown): PremiumContent {
  const v = object(raw, "");
  keys(v, ["report_id", "revision", "overlay_id", "evidence_class", "answers", "soft_fields", "omissions"], [], "");
  const answers = list(v.answers, "/answers", 64).map((a, i): PremiumAnswer => {
    const path = `/answers/${i}`;
    const answer = object(a, path);
    keys(answer, ["question_id", "answer_state", "selected_candidate_ids", "support_fact_ids", "prose"], [], path);
    return { question_id: str(answer.question_id, `${path}/question_id`, OPAQUE),
             answer_state: oneOf(answer.answer_state, ANSWER_STATES, `${path}/answer_state`),
             selected_candidate_ids: idList(answer.selected_candidate_ids, `${path}/selected_candidate_ids`, 32),
             support_fact_ids: idList(answer.support_fact_ids, `${path}/support_fact_ids`, 64),
             prose: nullableStr(answer.prose, `${path}/prose`, undefined, 4000) };
  });
  const softFields = list(v.soft_fields, "/soft_fields", 32).map((f, i): PremiumSoftField => {
    const path = `/soft_fields/${i}`;
    const field = object(f, path);
    keys(field, ["field_id", "text", "support_fact_ids"], [], path);
    return { field_id: str(field.field_id, `${path}/field_id`, OPAQUE),
             text: str(field.text, `${path}/text`, undefined, 4000),
             support_fact_ids: idList(field.support_fact_ids, `${path}/support_fact_ids`, 64) };
  });
  const omissions = list(v.omissions ?? [], "/omissions", 256).map((o, i): PremiumOmission => {
    const path = `/omissions/${i}`;
    const omission = object(o, path);
    keys(omission, ["item_id", "reason"], ["detail"], path);
    return { item_id: str(omission.item_id, `${path}/item_id`, OPAQUE),
             reason: str(omission.reason, `${path}/reason`, SAFE_CODE),
             detail: nullableStr(omission.detail, `${path}/detail`, undefined, 128) };
  });
  return { report_id: str(v.report_id, "/report_id", OPAQUE), revision: int(v.revision, "/revision", 1),
           overlay_id: str(v.overlay_id, "/overlay_id", OPAQUE),
           evidence_class: oneOf(v.evidence_class, ["AI_SYNTHESIS"] as const, "/evidence_class"),
           answers, soft_fields: softFields, omissions };
}

// --- feedback and push -------------------------------------------------------------

export type FeedbackCategory = "MEASUREMENT_LOOKS_WRONG" | "HARD_TO_UNDERSTAND" | "HARMFUL_OR_OFFENSIVE"
  | "PREMIUM_TEXT_ISSUE" | "OTHER";
export type FeedbackTarget = "REPORT" | "SECTION" | "FACT" | "PREMIUM";

export interface FeedbackReceipt {
  readonly feedback_id: string;
  readonly report_id: string;
  readonly revision: number;
  readonly category: FeedbackCategory;
  readonly comment_stored: string | null;
  readonly expires_at: string;
  readonly contract_version: string;
}

export function parseFeedbackReceipt(raw: unknown): FeedbackReceipt {
  const v = object(raw, "");
  keys(v, ["feedback_id", "report_id", "revision", "category", "comment_stored", "expires_at", "contract_version"],
       [], "");
  return { feedback_id: str(v.feedback_id, "/feedback_id", OPAQUE), report_id: str(v.report_id, "/report_id", OPAQUE),
           revision: int(v.revision, "/revision", 1),
           category: oneOf(v.category, ["MEASUREMENT_LOOKS_WRONG", "HARD_TO_UNDERSTAND", "HARMFUL_OR_OFFENSIVE",
                                        "PREMIUM_TEXT_ISSUE", "OTHER"] as const, "/category"),
           comment_stored: nullableStr(v.comment_stored, "/comment_stored", undefined, 500),
           expires_at: str(v.expires_at, "/expires_at", RFC3339),
           contract_version: str(v.contract_version, "/contract_version", /^report-feedback\/\d+$/) };
}

export function parsePushInstallation(raw: unknown): string {
  const v = object(raw, "");
  keys(v, ["installation_id"], [], "");
  return str(v.installation_id, "/installation_id", OPAQUE);
}

// --- comparisons ------------------------------------------------------------------------

const EXCLUSION_REASONS = ["ABSENT", "UNAVAILABLE", "NON_NUMERIC", "UNIT_MISMATCH", "DOMAIN_UNIT_MISMATCH",
                           "METHOD_ID_MISMATCH", "METHOD_VERSION_MISMATCH", "FORMATTING_MISMATCH"] as const;

export function parseComparison(raw: unknown): Comparison {
  const v = object(raw, "");
  keys(v, ["contract_version", "comparison_id", "kind", "created_at", "ordering_basis", "input_report_ids", "inputs",
           "candidate_feature_ids", "common_feature_ids", "coverage", "differences", "exclusions", "facts",
           "method_version", "presentation_version", "comparison_digest"], [], "");
  const version = str(v.contract_version, "/contract_version");
  if (version.split(".")[0] !== "1") throw new PayloadError("/contract_version", `unsupported contract major ${version}`);
  str(v.comparison_id, "/comparison_id", OPAQUE);
  const kind = oneOf(v.kind, ["PAIR", "HISTORY"] as const, "/kind");
  str(v.created_at, "/created_at", RFC3339);
  oneOf(v.ordering_basis, ["REQUEST_ORDER", "REPORT_CREATED_AT"] as const, "/ordering_basis");
  const inputIds = idList(v.input_report_ids, "/input_report_ids", 16);
  if (inputIds.length < 2 || (kind === "PAIR" && inputIds.length !== 2) || new Set(inputIds).size !== inputIds.length) {
    throw new PayloadError("/input_report_ids", "unexpected comparison inputs");
  }
  const inputs = list(v.inputs, "/inputs", 16);
  if (inputs.length !== inputIds.length) throw new PayloadError("/inputs", "inputs do not match input_report_ids");
  inputs.forEach((raw, i) => {
    const input = object(raw, `/inputs/${i}`);
    if (int(input.position, `/inputs/${i}/position`, 0, 15) !== i) {
      throw new PayloadError(`/inputs/${i}/position`, "positions must be in order");
    }
    str(input.report_id, `/inputs/${i}/report_id`, OPAQUE);
    int(input.revision, `/inputs/${i}/revision`, 1);
    str(input.report_digest, `/inputs/${i}/report_digest`, SHA256);
    str(input.report_created_at, `/inputs/${i}/report_created_at`, RFC3339);
  });
  const common = new Set(idList(v.common_feature_ids, "/common_feature_ids", 512));
  idList(v.candidate_feature_ids, "/candidate_feature_ids", 512);
  const coverage = object(v.coverage, "/coverage");
  int(coverage.candidate_n, "/coverage/candidate_n", 0);
  if (int(coverage.common_n, "/coverage/common_n", 0) !== common.size) {
    throw new PayloadError("/coverage/common_n", "coverage does not match common features");
  }
  int(coverage.excluded_n, "/coverage/excluded_n", 0);
  const fraction = finite(coverage.common_fraction, "/coverage/common_fraction");
  if (fraction < 0 || fraction > 1) throw new PayloadError("/coverage/common_fraction", "outside [0, 1]");
  list(v.differences, "/differences", 8192).forEach((raw, i) => {
    const path = `/differences/${i}`;
    const d = object(raw, path);
    if (!common.has(str(d.feature_id, `${path}/feature_id`, OPAQUE))) {
      throw new PayloadError(`${path}/feature_id`, "difference outside the common features");
    }
    int(d.from_position, `${path}/from_position`, 0, 15);
    int(d.to_position, `${path}/to_position`, 0, 15);
    str(d.unit, `${path}/unit`, undefined, 32);
    for (const key of ["value_from", "value_to", "signed_delta", "absolute_delta"] as const) finite(d[key], `${path}/${key}`);
    oneOf(d.direction, ["FROM_GREATER", "TO_GREATER", "EQUAL"] as const, `${path}/direction`);
    str(d.formatting_key, `${path}/formatting_key`, undefined, 64);
    if (d.precision !== null) int(d.precision, `${path}/precision`, 0, 12);
    const domain = object(d.display_domain, `${path}/display_domain`);
    finite(domain.min, `${path}/display_domain/min`);
    finite(domain.max, `${path}/display_domain/max`);
  });
  list(v.exclusions, "/exclusions", 8192).forEach((raw, i) => {
    const e = object(raw, `/exclusions/${i}`);
    str(e.feature_id, `/exclusions/${i}/feature_id`, OPAQUE);
    oneOf(e.reason, EXCLUSION_REASONS, `/exclusions/${i}/reason`);
    list(e.affected_positions, `/exclusions/${i}/affected_positions`, 16)
      .forEach((p, j) => int(p, `/exclusions/${i}/affected_positions/${j}`, 0, 15));
  });
  list(v.facts, "/facts", 8192).forEach((raw, i) => {
    const fact = object(raw, `/facts/${i}`) as unknown as Fact;
    str(fact.fact_id, `/facts/${i}/fact_id`, OPAQUE);
  });
  str(v.method_version, "/method_version", undefined, 64);
  str(v.presentation_version, "/presentation_version", undefined, 64);
  nullableStr(v.comparison_digest, "/comparison_digest", SHA256);
  return v as unknown as Comparison;
}
