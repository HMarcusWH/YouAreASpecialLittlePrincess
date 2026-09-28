import type { EvidenceBundle } from "@princess/contracts";
import { baselineTraces, spacingBrackets } from "@princess/report-core";

import { featureName, t, type Locale } from "./messages.ts";

function numberText(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "sv" ? "sv-SE" : "en-GB", { maximumFractionDigits: 2 }).format(value);
}

function BaselineEvidence({ bundle, locale }: { bundle: EvidenceBundle; locale: Locale }) {
  const traces = baselineTraces(bundle);
  const frames = new Map(bundle.frames.map((frame) => [frame.frame_id, frame] as const));
  if (traces.length === 0) return <p className="pr-unavailable">{t(locale, "evidence.none")}</p>;
  return (
    <section className="pr-evidence-block" aria-labelledby="baseline-evidence-title">
      <h3 id="baseline-evidence-title">{t(locale, "evidence.baseline")}</h3>
      <div className="pr-baseline-grid">
        {traces.map((trace, index) => {
          const frame = frames.get(trace.frameId);
          if (!frame) return null;
          const titleId = `baseline-svg-${index}-title`;
          const descriptionId = `baseline-svg-${index}-description`;
          return (
            <figure key={trace.lineRegionId} className="pr-baseline-figure">
              <svg role="img" aria-labelledby={`${titleId} ${descriptionId}`}
                   viewBox={`0 0 ${frame.width} ${frame.height}`} preserveAspectRatio="xMidYMid meet">
                <title id={titleId}>{t(locale, "evidence.baseline_line")} {index + 1}</title>
                <desc id={descriptionId}>
                  {trace.points.length} {t(locale, "evidence.points")};
                  {" "}{trace.angleDegrees === null ? t(locale, "evidence.angle_missing")
                    : `${numberText(trace.angleDegrees, locale)}°`}
                </desc>
                <polyline className="pr-baseline-line" fill="none"
                          points={trace.points.map(([x, y]) => `${x},${y}`).join(" ")} />
                {trace.points.map(([x, y], point) => (
                  <circle key={point} className="pr-baseline-point" cx={x} cy={y} r={1.5} />
                ))}
              </svg>
              <figcaption>
                {t(locale, "evidence.baseline_line")} {index + 1} · {trace.points.length} {t(locale, "evidence.points")}
                {trace.angleDegrees !== null && <> · {numberText(trace.angleDegrees, locale)}°</>}
              </figcaption>
            </figure>
          );
        })}
      </div>
    </section>
  );
}

function SpacingEvidence({ bundle, locale, featureId }: {
  bundle: EvidenceBundle; locale: Locale; featureId: "LINE_SPACING_PX" | "WORD_SPACING_PX";
}) {
  const rows = spacingBrackets(bundle, featureId);
  if (rows.length === 0) return null;
  const headingId = `spacing-${featureId.toLowerCase()}`;
  return (
    <section className="pr-evidence-block" aria-labelledby={headingId}>
      <h3 id={headingId}>{featureName(featureId, locale)}</h3>
      <div className="pr-table-wrap">
        <table className="pr-evidence-table">
          <thead><tr>
            <th scope="col">{t(locale, "evidence.regions")}</th>
            <th scope="col">{t(locale, "evidence.value")}</th>
            <th scope="col">{t(locale, "evidence.status")}</th>
          </tr></thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${row.from.region_id}-${row.to.region_id}-${index}`}>
                <td>{row.from.region_id} → {row.to.region_id}</td>
                <td className="pr-value">{numberText(row.gap, locale)} px</td>
                <td>{row.accepted ? t(locale, "evidence.accepted")
                                  : `${t(locale, "evidence.rejected")}: ${row.rejectionReason ?? ""}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ObservationEvidence({ bundle, locale }: { bundle: EvidenceBundle; locale: Locale }) {
  const rows = bundle.observations.filter((observation) => observation.feature_id === "SLANT_ANGLE_MEAN");
  if (rows.length === 0) return null;
  return (
    <section className="pr-evidence-block" aria-labelledby="slant-observations-title">
      <h3 id="slant-observations-title">{t(locale, "evidence.slant_observations")}</h3>
      <p className="pr-hint">{t(locale, "evidence.no_histogram")}</p>
      <div className="pr-table-wrap">
        <table className="pr-evidence-table">
          <thead><tr>
            <th scope="col">{t(locale, "evidence.observation")}</th>
            <th scope="col">{t(locale, "evidence.value")}</th>
            <th scope="col">{t(locale, "evidence.status")}</th>
          </tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.observation_id}>
                <td>{row.observation_id}</td>
                <td className="pr-value">
                  {typeof row.value === "number" ? numberText(row.value, locale) : String(row.value)}
                  {row.unit ? ` ${row.unit}` : ""}
                </td>
                <td>{row.accepted ? t(locale, "evidence.accepted")
                                  : `${t(locale, "evidence.rejected")}: ${row.rejection_reason ?? ""}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function EvidenceView({ bundle, locale }: { bundle: EvidenceBundle; locale: Locale }) {
  return (
    <section className="pr-evidence" aria-labelledby="evidence-title">
      <h2 id="evidence-title">{t(locale, "evidence.title")}</h2>
      <p className="pr-hint">{t(locale, "evidence.intro")}</p>
      <BaselineEvidence bundle={bundle} locale={locale} />
      <SpacingEvidence bundle={bundle} locale={locale} featureId="LINE_SPACING_PX" />
      <SpacingEvidence bundle={bundle} locale={locale} featureId="WORD_SPACING_PX" />
      <ObservationEvidence bundle={bundle} locale={locale} />
    </section>
  );
}
