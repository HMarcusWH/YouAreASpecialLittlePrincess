// Platform-neutral reading model of one authorized ReportViewModel for native
// and print renderers. It only partitions and resolves what the server saved:
// highlight order, section order, facts, notices and actions are taken as
// given. Nothing is selected, ranked, recomputed or filled in on the device.
import type { Action, Fact, Notice, ReportSection, ReportViewModel } from "@princess/contracts";

import { formatFact } from "./format.ts";
import { featureName, contentText, sectionTitle, t, type Locale } from "./messages.ts";

export const EVIDENCE_ICON: Readonly<Record<Fact["evidence_class"], string>> = {
  MEASURED: "◆", COMPUTATIONAL_PROXY: "◇", REFERENCE_STATISTIC: "▲", AUTHORED_CONTENT: "✎",
  TRADITIONAL_ASSOCIATION: "☾", AI_SYNTHESIS: "✦",
};

export interface FactPresentation {
  readonly factId: string;
  readonly featureId: string;
  readonly label: string;
  /** Localized display text; ``null`` when the fact carries no value (never shown as zero). */
  readonly value: string | null;
  readonly availability: Fact["availability"];
  readonly availabilityText: string;
  readonly calibrated: boolean;
  readonly evidenceClass: Fact["evidence_class"];
  readonly evidenceIcon: string;
  readonly evidenceText: string;
  readonly observations: number;
  readonly isVector: boolean;
}

export function presentFact(fact: Fact, locale: Locale): FactPresentation {
  const formatted = formatFact(fact, locale === "sv" ? "sv-SE" : "en-GB");
  const base = {
    factId: fact.fact_id, featureId: fact.feature_id, label: featureName(fact.feature_id, locale),
    availability: fact.availability, availabilityText: t(locale, `availability.${fact.availability}`),
    evidenceClass: fact.evidence_class, evidenceIcon: EVIDENCE_ICON[fact.evidence_class],
    evidenceText: t(locale, `evidence.${fact.evidence_class}`), observations: fact.quality.n_observations,
  };
  if (formatted.state === "UNAVAILABLE") return { ...base, value: null, calibrated: false, isVector: false };
  const text = formatted.text.startsWith("value.") ? t(locale, formatted.text) : formatted.text;
  return { ...base, value: text, calibrated: formatted.calibrated, isVector: Array.isArray(fact.value) };
}

export type DossierSectionKind = "HIGHLIGHT_PRIMARY" | "HIGHLIGHT_SECONDARY" | "SECTION";

export interface DossierSection {
  readonly sectionId: string;
  readonly kind: DossierSectionKind;
  readonly title: string;
  readonly availability: ReportSection["availability"];
  readonly availabilityText: string;
  /** Reviewed authored copy for the server-selected highlight; unknown content IDs are skipped. */
  readonly copy: readonly string[];
  readonly facts: readonly FactPresentation[];
  readonly premiumSectionId: string | null;
}

export interface DossierModel {
  readonly reportId: string;
  readonly revision: number;
  readonly projection: ReportViewModel["projection"];
  readonly locale: Locale;
  readonly reportLocale: string;
  readonly generatedAt: string;
  /** Server-selected First Reveal, in server order. Empty means no eligible highlight. */
  readonly highlights: readonly DossierSection[];
  readonly sections: readonly DossierSection[];
  readonly notices: readonly (Notice & { readonly text: string })[];
  readonly actions: readonly (Action & { readonly label: string; readonly reasonText: string | null })[];
  readonly sourceImageOmitted: boolean;
  readonly hasPremium: boolean;
}

function kindOf(section: ReportSection): DossierSectionKind {
  if (section.template === "HIGHLIGHT_PRIMARY") return "HIGHLIGHT_PRIMARY";
  if (section.template === "HIGHLIGHT_SECONDARY") return "HIGHLIGHT_SECONDARY";
  return "SECTION";
}

export function buildDossier(view: ReportViewModel, locale: Locale): DossierModel {
  const facts = new Map(view.facts.map((fact) => [fact.fact_id, fact] as const));
  const sections = view.sections.map((section): DossierSection => {
    const kind = kindOf(section);
    const title = kind === "HIGHLIGHT_PRIMARY" ? t(locale, "report.what_stands_out")
      : kind === "HIGHLIGHT_SECONDARY" ? t(locale, "report.also_noticeable") : sectionTitle(section.template);
    return {
      sectionId: section.section_id, kind, title, availability: section.availability,
      availabilityText: t(locale, `availability.${section.availability}`),
      copy: section.content_ids.map((id) => contentText(id, locale)).filter((c): c is string => c !== undefined),
      // The guard already proved every referenced fact is present in this view.
      facts: section.fact_ids.map((id) => facts.get(id)).filter((f): f is Fact => f !== undefined)
        .map((fact) => presentFact(fact, locale)),
      premiumSectionId: section.premium_section_id,
    };
  });
  return {
    reportId: view.source_report_id, revision: view.source_revision, projection: view.projection, locale,
    reportLocale: view.locale, generatedAt: view.generated_at,
    highlights: sections.filter((s) => s.kind !== "SECTION"),
    sections: sections.filter((s) => s.kind === "SECTION"),
    notices: view.notices.map((notice) => ({ ...notice, text: t(locale, notice.localization_key) })),
    actions: view.actions.map((action) => ({
      ...action, label: t(locale, `action.${action.kind}`),
      reasonText: action.reason === null ? null : t(locale, `reason.${action.reason}`),
    })),
    sourceImageOmitted: view.notices.some((n) => n.localization_key === "notice.source_image_omitted")
      || view.authorized_asset_ids.length === 0,
    hasPremium: view.sections.some((s) => s.premium_section_id !== null),
  };
}

/** Locale used for report display: the device preference when supported, else English. */
export function displayLocale(preferred: string | null | undefined): Locale {
  return (preferred ?? "").toLowerCase().startsWith("sv") ? "sv" : "en";
}
