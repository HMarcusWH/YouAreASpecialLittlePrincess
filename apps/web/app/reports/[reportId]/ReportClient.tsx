"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, PrincessApi, pollDelayMs, type ExportDetail, type ExportStatus } from "@princess/api-client";
import type { EvidenceBundle, ReportViewModel } from "@princess/contracts";
import { ReportView, t, type Locale } from "@princess/report-web";
import { focusSourceEvidence, sourceImageEligible } from "@princess/report-core";
import { SourceEvidencePlate } from "./SourceEvidencePlate.tsx";

type Phase = { kind: "idle" } | { kind: "preparing" } | { kind: "ready"; href: string } | { kind: "failed" };

/** The owner report with its working actions. Only EXPORT has a flow here;
 * the API marks the others disabled with a reason. */
export function ReportClient({ view, locale, evidence, evidenceUnreadable = false, privateV3 = false }: {
  view: ReportViewModel; locale: Locale; evidence: EvidenceBundle | null; evidenceUnreadable?: boolean;
  privateV3?: boolean;
}) {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [exportDetail, setExportDetail] = useState<ExportDetail>("SUMMARY");
  const [includeImage, setIncludeImage] = useState(false);
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(null);
  const stopped = useRef(false);
  const sourceUrl = sourceImageEligible(view)
    ? `/api/v1/reports/${encodeURIComponent(view.source_report_id)}/source-image` : null;
  const root = evidence?.frames.find((f) => f.parent_frame_id === null && f.unit === "px");
  const inspectableSourceIds = sourceUrl !== null && root ? view.sections
    .filter((section) => focusSourceEvidence(view, evidence, section.section_id,
      root.width, root.height).status === "READY")
    .map((section) => section.section_id) : [];
  function inspectSource(sectionId: string) {
    setSelectedSectionId(sectionId);
    document.getElementById("source-evidence-plate")?.focus({ preventScroll: false });
  }
  useEffect(() => () => { stopped.current = true; }, []);

  async function exportPdf() {
    const api = new PrincessApi({ baseUrl: "/api" });
    setPhase({ kind: "preparing" });
    try {
      let status: ExportStatus = await api.requestExport(
        view.source_report_id, "A4",
        privateV3 ? { detail: exportDetail, includeImage: includeImage && sourceUrl !== null } : {},
      );
      for (let attempt = 0; status.state === "QUEUED" && attempt < 40 && !stopped.current; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, pollDelayMs(attempt)));
        status = await api.exportStatus(status.export_id);
      }
      if (stopped.current) return;
      setPhase(status.state === "READY" ? { kind: "ready", href: api.exportFileUrl(status.export_id) }
                                        : { kind: "failed" });
    } catch (e) {
      if (!stopped.current) setPhase({ kind: "failed" });
      if (!(e instanceof ApiError)) throw e;
    }
  }

  return (
    <>
      <ReportView view={view} locale={locale} evidence={evidence}
                  sourceEvidence={<SourceEvidencePlate view={view} evidence={evidence} locale={locale}
                    sourceUrl={sourceUrl} selectedSectionId={selectedSectionId} />}
                  onInspectSource={sourceUrl === null ? undefined : inspectSource}
                  inspectableSourceIds={inspectableSourceIds}
                  onAction={(kind) => { if (kind === "EXPORT") void exportPdf(); }} />
      {evidenceUnreadable && (
        <p role="alert" className="error">The saved evidence could not be read safely, so it is not shown.</p>
      )}
      {privateV3 && view.actions.some((action) => action.kind === "EXPORT" && action.enabled) && (
        <fieldset className="stack" data-private-v3-export>
          <legend>{locale === "sv" ? "PDF-export (privat testläge)" : "PDF export (private test mode)"}</legend>
          <label htmlFor="export-detail">
            {locale === "sv" ? "Innehåll" : "Content"}
          </label>
          <select id="export-detail" value={exportDetail} disabled={phase.kind === "preparing"}
                  onChange={(event) => { setExportDetail(event.target.value as ExportDetail);
                                        setPhase({ kind: "idle" }); }}>
            <option value="SUMMARY">{locale === "sv" ? "Sammandrag" : "Summary"}</option>
            <option value="FULL">{locale === "sv" ? "Full rapport" : "Full report"}</option>
          </select>
          <label>
            <input type="checkbox" checked={includeImage} disabled={sourceUrl === null || phase.kind === "preparing"}
                   onChange={(event) => { setIncludeImage(event.target.checked);
                                         setPhase({ kind: "idle" }); }} />
            {locale === "sv" ? "Inkludera tillåten handskriftsbild" : "Include authorized handwriting image"}
          </label>
          {sourceUrl === null && <p className="muted">
            {locale === "sv" ? "Originalbilden är inte tillgänglig för export."
                             : "The original image is not available for export."}
          </p>}
        </fieldset>
      )}
      <div className="stack" aria-live="polite" data-export={phase.kind}>
        {phase.kind === "preparing" && <p role="status">{t(locale, "export.preparing")}</p>}
        {phase.kind === "ready" && (
          <p role="status">
            {t(locale, "export.ready")}{" "}
            <a className="button" href={phase.href} download>{t(locale, "export.download")}</a>
          </p>
        )}
        {phase.kind === "ready" && <p className="muted">{t(locale, "export.not_recallable")}</p>}
        {phase.kind === "failed" && <p role="alert" className="error">{t(locale, "export.failed")}</p>}
      </div>
    </>
  );
}
