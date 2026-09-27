// Renders one authorized ReportViewModel. Everything shown comes from the
// saved projection: no measurement, percentile or model text is computed here.
import type { Action, EvidenceBundle, Fact, Notice, ReportSection, ReportViewModel } from "@princess/contracts";
import { formatFact } from "@princess/report-core";

import { EvidenceView } from "./EvidenceView.tsx";
import { featureName, sectionTitle, t, type Locale } from "./messages.ts";

const EVIDENCE_ICON: Record<Fact["evidence_class"], string> = {
  MEASURED: "◆", COMPUTATIONAL_PROXY: "◇", REFERENCE_STATISTIC: "▲", AUTHORED_CONTENT: "✎",
  TRADITIONAL_ASSOCIATION: "☾", AI_SYNTHESIS: "✦",
};
const EVIDENCE_ROLE: Record<Fact["evidence_class"], string> = {
  MEASURED: "measured", COMPUTATIONAL_PROXY: "proxy", REFERENCE_STATISTIC: "reference",
  AUTHORED_CONTENT: "authored", TRADITIONAL_ASSOCIATION: "traditional", AI_SYNTHESIS: "ai",
};

export function EvidenceBadge({ evidence, locale }: { evidence: Fact["evidence_class"]; locale: Locale }) {
  return (
    <span className={`pr-badge pr-evidence-${EVIDENCE_ROLE[evidence]}`} data-evidence={evidence}>
      <span aria-hidden="true">{EVIDENCE_ICON[evidence]}</span> {t(locale, `evidence.${evidence}`)}
    </span>
  );
}

export function FactValue({ fact, locale }: { fact: Fact; locale: Locale }) {
  const formatted = formatFact(fact, locale);
  if (formatted.state === "UNAVAILABLE") {
    return (
      <span className={`pr-unavailable pr-availability-${formatted.availability.toLowerCase()}`}
            data-availability={formatted.availability}>
        {t(locale, formatted.reasonKey)}
      </span>
    );
  }
  return (
    <span className="pr-value" data-availability={fact.availability}>
      {formatted.text.startsWith("value.") ? t(locale, formatted.text) : formatted.text}
      {!formatted.calibrated && <span className="pr-hint"> · {t(locale, "availability.UNCALIBRATED")}</span>}
    </span>
  );
}

function FactRow({ fact, locale }: { fact: Fact; locale: Locale }) {
  return (
    <tr data-fact-id={fact.fact_id}>
      <th scope="row">{featureName(fact.feature_id)}</th>
      <td><FactValue fact={fact} locale={locale} /></td>
      <td><EvidenceBadge evidence={fact.evidence_class} locale={locale} /></td>
      <td className="pr-quality" title={t(locale, "quality.observations")}>n = {fact.quality.n_observations}</td>
    </tr>
  );
}

function SectionBlock({ section, facts, locale }: { section: ReportSection; facts: Map<string, Fact>;
                                                    locale: Locale }) {
  const rows = section.fact_ids.map((id) => facts.get(id)).filter((f): f is Fact => f !== undefined);
  const headingId = `section-${section.section_id}`;
  return (
    <section className="pr-section" aria-labelledby={headingId} data-section={section.section_id}
             data-availability={section.availability}>
      <h2 id={headingId}>{sectionTitle(section.template)}</h2>
      {section.premium_section_id !== null && (
        <p className="pr-premium"><EvidenceBadge evidence="AI_SYNTHESIS" locale={locale} /> {t(locale, "report.premium_saved")}</p>
      )}
      {section.availability !== "READY" && section.availability !== "UNCALIBRATED" && rows.length === 0 && (
        <p className="pr-unavailable">{t(locale, `availability.${section.availability}`)}</p>
      )}
      {rows.length > 0 && (
        <div className="pr-table-wrap">
          <table className="pr-facts">
            <caption className="pr-visually-hidden">{sectionTitle(section.template)}: {t(locale, "report.facts")}</caption>
            <tbody>{rows.map((fact) => <FactRow key={fact.fact_id} fact={fact} locale={locale} />)}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function NoticeBar({ notices, locale }: { notices: readonly Notice[]; locale: Locale }) {
  return (
    <ul className="pr-notices" aria-label="Notices">
      {notices.map((n) => (
        <li key={n.notice_id} data-notice={n.class}
            {...(n.localization_key === "notice.source_image_omitted" ? { "data-image": "omitted" } : {})}>
          {t(locale, n.localization_key)}
        </li>
      ))}
    </ul>
  );
}

export function ActionBar({ actions, locale, onAction }: { actions: readonly Action[]; locale: Locale;
                                                           onAction?: (kind: Action["kind"]) => void }) {
  return (
    <div className="pr-actions" role="group" aria-label="Report actions">
      {actions.map((a) => (
        <span key={a.action_id} className="pr-action">
          <button type="button" disabled={!a.enabled} aria-describedby={a.reason ? `${a.action_id}-why` : undefined}
                  onClick={a.enabled && onAction ? () => onAction(a.kind) : undefined}>
            {t(locale, `action.${a.kind}`)}
          </button>
          {a.reason && <span id={`${a.action_id}-why`} className="pr-hint">{t(locale, `reason.${a.reason}`)}</span>}
        </span>
      ))}
    </div>
  );
}

export function ReportView({ view, locale, evidence, onAction }: {
  view: ReportViewModel; locale: Locale; evidence?: EvidenceBundle | null;
  onAction?: (kind: Action["kind"]) => void;
}) {
  const facts = new Map(view.facts.map((f) => [f.fact_id, f]));
  return (
    <article className="pr-report" data-projection={view.projection} lang={locale}>
      <header className="pr-header">
        <h1>{t(locale, `projection.${view.projection}`)}</h1>
        <p className="pr-hint">{t(locale, "report.revision")} {view.source_revision}</p>
      </header>
      <NoticeBar notices={view.notices} locale={locale} />
      {view.sections.map((s) => <SectionBlock key={s.section_id} section={s} facts={facts} locale={locale} />)}
      {evidence && <EvidenceView bundle={evidence} locale={locale} />}
      <ActionBar actions={view.actions} locale={locale} {...(onAction ? { onAction } : {})} />
    </article>
  );
}
