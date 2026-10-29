// Print and share-card presentations of one saved projection (T21). They add
// no measurements, prose or ranks: only layout, the revision identity and the
// same notices the interactive report shows.
import type { EvidenceBundle, Fact, ReportViewModel } from "@princess/contracts";
import type { ReactNode } from "react";
import { formatFact, mapToAncestor } from "@princess/report-core";

import { featureName, t, type Locale } from "./messages.ts";
import { ReportView } from "./ReportView.tsx";

const PRINT_TEXT: Record<Locale, Record<string, string>> = {
  en: {
    "print.report": "Report", "print.generated": "Rendered", "print.dossier": "Personal dossier",
    "print.method": "How this was made",
    "print.method_text": "Every value comes from deterministic image measurement of your photo. Computed proxies are " +
      "engineering indices without calibration. Nothing is ranked against other writers unless a named reference " +
      "group is shown. This is not a personality, health or ability assessment.",
    "print.not_recallable": "A downloaded copy cannot be recalled once it has been saved elsewhere.",
    "print.summary": "Summary · selected evidence and facts",
    "print.full": "Full technical appendix · all authorized measurements",
    "print.source": "Authorized handwriting source and supported regions",
    "print.source_limit": "Up to 24 saved, eligible regions are shown; other geometry is not evidence.",
    "card.context": "Handwriting measurements — not a personality test",
    "card.no_handwriting_measurements": "No supported handwriting measurements shown",
  },
  sv: {
    "print.report": "Rapport", "print.generated": "Renderad", "print.dossier": "Personlig dossier",
    "print.method": "Så här togs den fram",
    "print.method_text": "Alla värden kommer från deterministisk bildmätning av ditt foto. Beräknade närmevärden är " +
      "tekniska index utan kalibrering. Inget rangordnas mot andra skribenter om ingen namngiven referensgrupp visas. " +
      "Detta är ingen bedömning av personlighet, hälsa eller förmåga.",
    "print.not_recallable": "En nedladdad kopia kan inte återkallas när den har sparats någon annanstans.",
    "print.summary": "Sammandrag · utvalt underlag och mätvärden",
    "print.full": "Fullständig teknisk bilaga · alla behöriga mätvärden",
    "print.source": "Godkänd handskriftsbild och belagda regioner",
    "print.source_limit": "Högst 24 sparade, godkända regioner visas; övrig geometri är inte belägg.",
    "card.context": "Handstilsmätningar — inget personlighetstest",
    "card.no_handwriting_measurements": "Inga styrkta handskriftsmätvärden visas",
  },
};

function p(locale: Locale, key: string): string {
  return PRINT_TEXT[locale][key] ?? PRINT_TEXT.en[key] ?? key;
}

/** Summary selects an editorial subset of exact saved facts; it never computes, ranks, or rewrites them. */
export function summaryView(view: ReportViewModel): ReportViewModel {
  const chapter = /^section\.(slant|baseline|spacing|size|layout|ink)$/;
  const selected = view.sections.filter((s) =>
    s.section_id === "section.sample" || chapter.test(s.section_id) ||
    s.template === "HIGHLIGHT_PRIMARY" || s.template === "HIGHLIGHT_SECONDARY" ||
    s.template === "PATTERN_CONNECTION",
  ).map((s) => ({ ...s, fact_ids: s.fact_ids.slice(0, s.section_id === "section.sample" ? 4 : 2) }));
  const ids = new Set(selected.flatMap((s) => s.fact_ids));
  return { ...view, sections: selected, facts: view.facts.filter((f) => ids.has(f.fact_id)) };
}

export function PrintReport({ view, locale, generatedAt, detail, evidence, sourceEvidence }: {
  view: ReportViewModel; locale: Locale; generatedAt: string;
  detail?: "SUMMARY" | "FULL"; evidence?: EvidenceBundle | null; sourceEvidence?: ReactNode;
}) {
  const renderedView = detail === "SUMMARY" ? summaryView(view) : view;
  return (
    <div className={"pr-print" + (detail === "SUMMARY" ? " pr-print-summary" : "")}>
      <header className="pr-print-cover">
        <p className="pr-print-brand">Inktrospect</p>
        <p className="pr-print-kicker">{p(locale, "print.dossier")}</p>
        <h1>{t(locale, `projection.${view.projection}`)}</h1>
        {detail && <p className="pr-print-detail">{p(locale, detail === "SUMMARY" ? "print.summary" : "print.full")}</p>}
        <p className="pr-print-meta">
          {p(locale, "print.report")} {view.source_report_id} · {t(locale, "report.revision")} {view.source_revision}
          {" · "}{p(locale, "print.generated")} {generatedAt}
        </p>
      </header>
      <ReportView view={{ ...renderedView, actions: [] }} locale={locale} showHeader={false}
                  sourceEvidence={sourceEvidence}
                  {...(detail === "FULL" && evidence ? { evidence } : {})} />
      <section className="pr-section pr-colophon" aria-labelledby="colophon">
        <h2 id="colophon">{p(locale, "print.method")}</h2>
        <p>{p(locale, "print.method_text")}</p>
        <p className="pr-hint">
          {p(locale, "print.report")} {view.source_report_id} · {t(locale, "report.revision")} {view.source_revision} ·{" "}
          {p(locale, "print.generated")} {generatedAt}
        </p>
        <p className="pr-hint">{p(locale, "print.not_recallable")}</p>
      </section>
    </div>
  );
}

/** A trusted data raster with geometric proof from the saved evidence frame, not a detected drawing. */
export function PrintSourceEvidence({ view, bundle, imageDataUri, locale }: {
  view: ReportViewModel; bundle: EvidenceBundle; imageDataUri: string; locale: Locale;
}) {
  const roots = bundle.frames.filter((f) => f.parent_frame_id === null && f.unit === "px");
  if (roots.length !== 1 || roots[0]!.frame_id !== "frame_input") return null;
  const root = roots[0]!;
  const relevant = new Set(view.sections.flatMap((s) => s.fact_ids));
  const regions = new Map(bundle.regions.map((r) => [r.region_id, r] as const));
  const selected = new Set<string>();
  const polygons: { id: string; coords: string }[] = [];
  for (const fact of view.facts) {
    if (!relevant.has(fact.fact_id) || !["READY", "UNCALIBRATED"].includes(fact.availability) ||
        !["MEASURED", "COMPUTATIONAL_PROXY"].includes(fact.evidence_class)) continue;
    for (const id of fact.source_region_ids) {
      if (selected.has(id)) continue;
      selected.add(id);
      const region = regions.get(id);
      if (!region || !["LINE", "WORD", "COMPONENT"].includes(region.scope)) continue;
      const corners: readonly (readonly [number, number])[] = [
        [region.x, region.y], [region.x + region.width, region.y],
        [region.x + region.width, region.y + region.height], [region.x, region.y + region.height],
      ];
      try {
        const points = corners.map(([x, y]) => mapToAncestor(bundle.frames, region.frame_id,
                                                                 root.frame_id, x, y));
        if (points.every(([x, y]) => Number.isFinite(x) && Number.isFinite(y) &&
            x >= -1e-6 && y >= -1e-6 && x <= root.width + 1e-6 && y <= root.height + 1e-6)) {
          const coords = points.map(([x, y]) => x + "," + y).join(" ");
          polygons.push({ id, coords });
          if (polygons.length === 24) break;
        }
      } catch { /* Unknown transform: never draw an invented source region. */ }
    }
    if (polygons.length === 24) break;
  }
  return (
    <figure className="pr-v3-source" data-source-evidence="authorized">
      <figcaption>{p(locale, "print.source")}</figcaption>
      <svg viewBox={"0 0 " + root.width + " " + root.height} role="img"
           aria-label={p(locale, "print.source")} preserveAspectRatio="xMidYMid meet">
        <image href={imageDataUri} x={0} y={0} width={root.width} height={root.height}
               preserveAspectRatio="none" />
        {polygons.map((polygon) => (
          <polygon key={polygon.id} points={polygon.coords} fill="none"
                   className="pr-v3-source-region" data-region-id={polygon.id} />
        ))}
      </svg>
      <p className="pr-hint">{p(locale, "print.source_limit")}</p>
    </figure>
  );
}

const IMAGE_ONLY_FACTS = new Set(["IMG_WIDTH_PX", "IMG_HEIGHT_PX", "IMG_MEGAPIXELS", "IMG_ASPECT_RATIO"]);

function unqualifiedShare(view: ReportViewModel): boolean {
  if (view.sections.some((section) => section.section_id === "section.sample"
      && section.availability === "INELIGIBLE")) return true;
  // SHARE may omit section.sample; missing-only views must not look analyzed.
  return !view.facts.some((fact) => !IMAGE_ONLY_FACTS.has(fact.feature_id)
    && (fact.availability === "READY" || fact.availability === "UNCALIBRATED") && fact.value !== null);
}

/** Deterministic pick: the first present scalar facts of the shared projection, in section order. */
export function cardFacts(view: ReportViewModel, limit = 4): Fact[] {
  const byId = new Map(view.facts.map((f) => [f.fact_id, f]));
  const picked: Fact[] = [];
  const unqualified = unqualifiedShare(view);
  for (const section of view.sections) {
    for (const id of section.fact_ids) {
      const fact = byId.get(id);
      if (fact && (!unqualified || IMAGE_ONLY_FACTS.has(fact.feature_id))
          && (fact.availability === "READY" || fact.availability === "UNCALIBRATED")
          && (typeof fact.value === "number" || typeof fact.value === "string") && !picked.includes(fact)) {
        picked.push(fact);
      }
      if (picked.length === limit) return picked;
    }
  }
  return picked;
}

export function ShareCard({ view, locale, shape }: { view: ReportViewModel; locale: Locale;
                                                     shape: "square" | "story" }) {
  const facts = cardFacts(view, shape === "story" ? 6 : 4);
  const unqualified = unqualifiedShare(view);
  return (
    <div className={`pr-card pr-card-${shape}${unqualified ? " pr-card-unqualified" : ""}`} lang={locale}>
      <header className="pr-card-header">
        <p className="pr-card-brand">Inktrospect</p>
        <p className="pr-card-context">{p(locale, unqualified ? "card.no_handwriting_measurements" : "card.context")}</p>
      </header>
      <dl className="pr-card-facts">
        {facts.map((fact) => {
          const formatted = formatFact(fact, locale);
          return (
            <div key={fact.fact_id} className="pr-card-fact" data-fact-id={fact.fact_id}>
              <dt>{featureName(fact.feature_id, locale)}</dt>
              <dd>{formatted.state === "VALUE" ? formatted.text : t(locale, formatted.reasonKey)}</dd>
              <dd className="pr-card-label">
                {t(locale, `evidence.${fact.evidence_class}`)}
                {fact.availability === "UNCALIBRATED" ? ` · ${t(locale, "availability.UNCALIBRATED")}` : ""}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}
