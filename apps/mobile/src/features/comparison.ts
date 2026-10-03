// Presentation of a server-built comparison (N12). Differences, coverage and
// exclusions come from the saved reports through the T18 builder; this module
// only formats them. There is no similarity score and no relationship claim.
import type { Comparison, ComparisonExclusionReason } from "@princess/contracts";
import { featureName, type Locale } from "@princess/report-core";

export interface ComparisonRow {
  readonly featureId: string;
  readonly label: string;
  readonly from: string;
  readonly to: string;
  readonly delta: string;
  readonly direction: "FROM_GREATER" | "TO_GREATER" | "EQUAL";
  /** Positions of both values on the fixed display domain, 0..1, for a bar without rescaling per person. */
  readonly fromPosition: number;
  readonly toPosition: number;
}

export interface ComparisonView {
  readonly kind: "PAIR" | "HISTORY";
  readonly commonCount: number;
  readonly candidateCount: number;
  readonly coverage: number;
  readonly rows: readonly ComparisonRow[];
  readonly exclusions: ReadonlyArray<{ readonly reason: ComparisonExclusionReason; readonly featureIds: readonly string[] }>;
  readonly inputs: ReadonlyArray<{ readonly reportId: string; readonly revision: number; readonly createdAt: string }>;
}

function number(value: number, precision: number | null, locale: Locale, unit: string): string {
  const digits = precision ?? 2;
  const text = new Intl.NumberFormat(locale === "sv" ? "sv-SE" : "en-GB",
                                     { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
  const clean = /^[-−]0([.,]0+)?$/.test(text) ? text.replace(/^[-−]/, "") : text;
  return unit === "px" ? `${clean} px` : unit === "degrees" ? `${clean}°` : clean;
}

function position(value: number, min: number, max: number): number {
  if (!(max > min)) return 0.5;
  return Math.min(1, Math.max(0, (value - min) / (max - min)));
}

export function presentComparison(comparison: Comparison, locale: Locale): ComparisonView {
  const rows = comparison.differences.map((d): ComparisonRow => ({
    featureId: d.feature_id, label: featureName(d.feature_id, locale),
    from: number(d.value_from, d.precision, locale, d.unit), to: number(d.value_to, d.precision, locale, d.unit),
    delta: (d.signed_delta > 0 ? "+" : "") + number(d.signed_delta, d.precision, locale, d.unit),
    direction: d.direction,
    fromPosition: position(d.value_from, d.display_domain.min, d.display_domain.max),
    toPosition: position(d.value_to, d.display_domain.min, d.display_domain.max),
  }));
  const grouped = new Map<ComparisonExclusionReason, string[]>();
  for (const exclusion of comparison.exclusions) {
    grouped.set(exclusion.reason, [...(grouped.get(exclusion.reason) ?? []), exclusion.feature_id]);
  }
  return {
    kind: comparison.kind, commonCount: comparison.coverage.common_n, candidateCount: comparison.coverage.candidate_n,
    coverage: comparison.coverage.common_fraction, rows,
    exclusions: [...grouped.entries()].map(([reason, featureIds]) => ({ reason, featureIds })),
    inputs: comparison.inputs.map((input) => ({ reportId: input.report_id, revision: input.revision,
                                                createdAt: input.report_created_at })),
  };
}
