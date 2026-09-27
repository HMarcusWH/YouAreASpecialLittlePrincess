"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, PrincessApi, pollDelayMs, type ExportStatus } from "@princess/api-client";
import type { EvidenceBundle, ReportViewModel } from "@princess/contracts";
import { ReportView, t, type Locale } from "@princess/report-web";

type Phase = { kind: "idle" } | { kind: "preparing" } | { kind: "ready"; href: string } | { kind: "failed" };

/** The owner report with its working actions. Only EXPORT has a flow here;
 * the API marks the others disabled with a reason. */
export function ReportClient({ view, locale, evidence, evidenceUnreadable = false }: {
  view: ReportViewModel; locale: Locale; evidence: EvidenceBundle | null; evidenceUnreadable?: boolean;
}) {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const stopped = useRef(false);
  useEffect(() => () => { stopped.current = true; }, []);

  async function exportPdf() {
    const api = new PrincessApi({ baseUrl: "/api" });
    setPhase({ kind: "preparing" });
    try {
      let status: ExportStatus = await api.requestExport(view.source_report_id, "A4");
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
                  onAction={(kind) => { if (kind === "EXPORT") void exportPdf(); }} />
      {evidenceUnreadable && (
        <p role="alert" className="error">The saved evidence could not be read safely, so it is not shown.</p>
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
