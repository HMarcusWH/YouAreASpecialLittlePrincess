// Print and share-card presentations of one saved projection (T21). They add
// no measurements, prose or ranks: only layout, the revision identity and the
// same notices the interactive report shows.
import type { Fact, ReportViewModel } from "@princess/contracts";
import { formatFact } from "@princess/report-core";

import { featureName, t, type Locale } from "./messages.ts";
import { ReportView } from "./ReportView.tsx";

const PRINT_TEXT: Record<Locale, Record<string, string>> = {
  en: {
    "print.report": "Report", "print.generated": "Rendered", "print.method": "How this was made",
    "print.method_text": "Every value comes from deterministic image measurement of your photo. Computed proxies are " +
      "engineering indices without calibration. Nothing is ranked against other writers unless a named reference " +
      "group is shown. This is not a personality, health or ability assessment.",
    "print.not_recallable": "A downloaded copy cannot be recalled once it has been saved elsewhere.",
    "card.context": "Handwriting measurements — not a personality test",
  },
  sv: {
    "print.report": "Rapport", "print.generated": "Renderad", "print.method": "Så här togs den fram",
    "print.method_text": "Alla värden kommer från deterministisk bildmätning av ditt foto. Beräknade närmevärden är " +
      "tekniska index utan kalibrering. Inget rangordnas mot andra skribenter om ingen namngiven referensgrupp visas. " +
      "Detta är ingen bedömning av personlighet, hälsa eller förmåga.",
    "print.not_recallable": "En nedladdad kopia kan inte återkallas när den har sparats någon annanstans.",
    "card.context": "Handstilsmätningar — inget personlighetstest",
  },
};

function p(locale: Locale, key: string): string {
  return PRINT_TEXT[locale][key] ?? PRINT_TEXT.en[key] ?? key;
}

export function PrintReport({ view, locale, generatedAt }: { view: ReportViewModel; locale: Locale;
                                                             generatedAt: string }) {
  return (
    <div className="pr-print">
      <ReportView view={{ ...view, actions: [] }} locale={locale} />
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

/** Deterministic pick: the first present scalar facts of the shared projection, in section order. */
export function cardFacts(view: ReportViewModel, limit = 4): Fact[] {
  const byId = new Map(view.facts.map((f) => [f.fact_id, f]));
  const picked: Fact[] = [];
  for (const section of view.sections) {
    for (const id of section.fact_ids) {
      const fact = byId.get(id);
      if (fact && (fact.availability === "READY" || fact.availability === "UNCALIBRATED")
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
  return (
    <div className={`pr-card pr-card-${shape}`} lang={locale}>
      <p className="pr-card-brand">Inktrospect</p>
      <p className="pr-card-context">{p(locale, "card.context")}</p>
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
