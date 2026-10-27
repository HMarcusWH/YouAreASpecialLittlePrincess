"use client";

// Client-only authorized source plate. The server already chose every fact and
// evidence region; this component only displays exact saved geometry on the
// reauthorized same-origin source image, and never retains image bytes.
import type { EvidenceBundle, ReportViewModel } from "@princess/contracts";
import { focusSourceEvidence, type Locale } from "@princess/report-core";
import { useEffect, useState } from "react";

import { t } from "@princess/report-web";

export function SourceEvidencePlate({ view, evidence, locale, sourceUrl, selectedSectionId }: {
  view: ReportViewModel; evidence: EvidenceBundle | null; locale: Locale;
  sourceUrl: string | null; selectedSectionId: string | null;
}) {
  const [image, setImage] = useState<{ width: number; height: number } | "loading" | "unavailable">(
    sourceUrl === null ? "unavailable" : "loading");
  const [index, setIndex] = useState(0);
  useEffect(() => { setIndex(0); }, [selectedSectionId]);
  useEffect(() => { setImage(sourceUrl === null ? "unavailable" : "loading"); }, [sourceUrl]);

  const focus = selectedSectionId !== null && image !== "loading" && image !== "unavailable"
    ? focusSourceEvidence(view, evidence, selectedSectionId, image.width, image.height)
    : null;
  const regions = focus?.status === "READY" ? focus.regions : [];
  const current = regions.length ? Math.min(index, regions.length - 1) : 0;
  const active = regions[current];
  const root = evidence?.frames.find((frame) => frame.parent_frame_id === null && frame.unit === "px");
  const frameMatches = image !== "loading" && image !== "unavailable" && root !== undefined
    && root.width === image.width && root.height === image.height;

  return (
    <section className="pr-source-evidence" id="source-evidence-plate" tabIndex={-1}
             aria-label={t(locale, "image.title")}>
      <h2>{t(locale, "image.title")}</h2>
      {sourceUrl === null ? (
        <p className="pr-unavailable">{t(locale, "image.unavailable")}</p>
      ) : (
        <>
          {image === "unavailable" && (
            <p role="status" className="pr-unavailable">{t(locale, "image.unavailable")}</p>
          )}
          <figure className="pr-source-figure">
            <div className="pr-source-viewport">
              <img key={sourceUrl} src={sourceUrl} alt={t(locale, "image.title")}
                   referrerPolicy="no-referrer" draggable={false}
                   style={{ display: image === "unavailable" ? "none" : undefined }}
                   onLoad={(event) => {
                     const { naturalWidth: width, naturalHeight: height } = event.currentTarget;
                     setImage(width > 0 && height > 0 ? { width, height } : "unavailable");
                   }}
                   onError={() => setImage("unavailable")} />
              {frameMatches && active ? (
                <svg className="pr-source-outline" aria-hidden="true" role="presentation"
                     viewBox={`0 0 ${image.width} ${image.height}`} preserveAspectRatio="none">
                  <polyline points={active.points.map(([x, y]) => `${x},${y}`).join(" ")} />
                </svg>
              ) : null}
            </div>
            <figcaption className="pr-hint">
              {image === "loading" ? t(locale, "image.loading") : image === "unavailable" ? null
                : !frameMatches && evidence ? t(locale, "image.frame_mismatch")
                : selectedSectionId === null ? t(locale, "image.inspect_prompt")
                : focus?.status === "READY" && active
                  ? `${t(locale, "image.focus_region")}: ${active.regionId} · ${current + 1} / ${regions.length}`
                : t(locale, "image.focus_unavailable")}
            </figcaption>
          </figure>
          {image !== "loading" && image !== "unavailable" && active && (
            <div className="pr-source-inspector" role="group" aria-label={t(locale, "image.focus_region")}>
              <button type="button" disabled={current === 0}
                      onClick={() => setIndex((n) => Math.max(0, n - 1))}>
                {t(locale, "evidence.previous_page")}
              </button>
              <span className="pr-source-count" aria-live="polite">
                {active.regionId} · {current + 1} / {regions.length}
              </span>
              <button type="button" disabled={current >= regions.length - 1}
                      onClick={() => setIndex((n) => Math.min(regions.length - 1, n + 1))}>
                {t(locale, "evidence.next_page")}
              </button>
              {focus && focus.total > regions.length && (
                <p className="pr-hint">{t(locale, "image.focus_limit")
                  .replace("{shown}", String(regions.length)).replace("{total}", String(focus.total))}</p>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
