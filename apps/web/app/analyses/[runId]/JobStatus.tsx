"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, PrincessApi, pollDelayMs, type RunStatus } from "@princess/api-client";

const TEXT: Record<RunStatus["state"], string> = {
  QUEUED: "Waiting for a measurement worker…",
  RUNNING: "Measuring your handwriting…",
  SUCCEEDED: "Your report is ready.",
  FAILED: "The analysis could not be completed.",
  CANCELLED: "The analysis was cancelled.",
};

/** Polls the known run; a refresh resumes this run and never starts new work. */
export function JobStatus({ runId }: { runId: string }) {
  const router = useRouter();
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const api = new PrincessApi({ baseUrl: "/api" });
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const tick = async () => {
      try {
        const next = await api.analysis(runId);
        if (stopped) return;
        setStatus(next);
        if (next.state === "SUCCEEDED" && next.report_id) {
          router.replace(`/reports/${encodeURIComponent(next.report_id)}`);
          return;
        }
        if (next.state === "QUEUED" || next.state === "RUNNING") timer = setTimeout(tick, pollDelayMs(attempt++));
      } catch (e) {
        if (stopped) return;
        setError(e instanceof ApiError && e.status === 404 ? "This analysis does not exist for your account."
                 : "The status could not be loaded. Retrying…");
        if (!(e instanceof ApiError && e.status === 404)) timer = setTimeout(tick, pollDelayMs(attempt++));
      }
    };
    void tick();
    return () => { stopped = true; if (timer) clearTimeout(timer); };
  }, [runId, router]);

  async function cancel() {
    await new PrincessApi({ baseUrl: "/api" }).cancelAnalysis(runId).catch(() => undefined);
  }

  return (
    <div className="panel stack">
      <p role="status" aria-live="polite" className="status" data-state={status?.state ?? "LOADING"}>
        {status ? TEXT[status.state] : "Loading…"}
      </p>
      {status?.error_code && <p className="muted">Reason: {status.error_code}</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {status && (status.state === "QUEUED" || status.state === "RUNNING") && (
        <p><button type="button" className="button button-secondary" onClick={cancel}>Cancel</button></p>
      )}
    </div>
  );
}
