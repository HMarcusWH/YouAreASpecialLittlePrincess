// Shared, read-only fact formatting for web, native, PDF and share cards.
// All numbers come from saved facts; this module only renders them.
import type { Fact } from "@princess/contracts";

export const FORMAT_VERSION = "report-format/1" as const;

export type FormattedFact =
  | { readonly state: "VALUE"; readonly text: string; readonly calibrated: boolean }
  | { readonly state: "UNAVAILABLE"; readonly availability: Fact["availability"]; readonly reasonKey: string };

// Unit suffixes by formatting key. Keys absent here render without a unit.
// ``score_0_1`` is an engineering index, never a percentile: no "%" suffix.
const SUFFIX: Readonly<Record<string, string>> = {
  "measurement.px": " px",
  "measurement.degrees": "°",
  "measurement.MP": " MP",
};

const PRESENT = new Set<Fact["availability"]>(["READY", "UNCALIBRATED"]);

export function formatFact(fact: Fact, locale: string): FormattedFact {
  if (!PRESENT.has(fact.availability) || fact.value === null) {
    return { state: "UNAVAILABLE", availability: fact.availability, reasonKey: `availability.${fact.availability}` };
  }
  const calibrated = fact.availability === "READY";
  const value = fact.value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new RangeError(`non-finite fact value for ${fact.fact_id}`);
    }
    const digits = fact.precision ?? 2;
    const text = new Intl.NumberFormat(locale, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(value);
    // Avoid rendering a negative zero such as "-0.0".
    const normalized = /^[-−]0([.,]0+)?$/.test(text) ? text.replace(/^[-−]/, "") : text;
    return { state: "VALUE", text: normalized + (SUFFIX[fact.formatting_key] ?? ""), calibrated };
  }
  if (typeof value === "boolean") {
    return { state: "VALUE", text: value ? "value.yes" : "value.no", calibrated };
  }
  if (typeof value === "string") {
    return { state: "VALUE", text: value, calibrated };
  }
  // Vectors/distributions are charted, not printed as a single value.
  return { state: "VALUE", text: `vector[${value.length}]`, calibrated };
}
