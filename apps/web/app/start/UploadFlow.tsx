"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ApiError, PrincessApi, sha256Hex } from "@princess/api-client";

const NOTICE = "notice.consent-choices:1";
const TYPES = new Set(["image/jpeg", "image/png"]);
type Step = "idle" | "session" | "uploading" | "verifying" | "consent" | "queueing";

const MESSAGES: Record<string, string> = {
  upload_quota_exceeded: "You have reached today's upload limit. Please try again later.",
  unsupported_media: "Only JPEG and PNG photos are supported.",
  image_too_large: "This image is too large. Please use a smaller photo.",
  image_too_small: "This image is too small to measure.",
  pixel_limit_exceeded: "This image has too many pixels to process safely.",
  permission_not_granted: "Processing needs your permission for this photo.",
  too_many_active_analyses: "You already have several analyses running. Please wait for one to finish.",
  completion_in_progress: "This upload is still being checked. Please try again in a moment.",
  uploads_disabled: "Uploads are paused right now.",
};

export function UploadFlow() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [step, setStep] = useState<Step>("idle");
  const [error, setError] = useState<string | null>(null);
  const api = new PrincessApi({ baseUrl: "/api" });

  async function ensureSession() {
    try {
      await api.me();
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 401) throw e;
      const guest = await fetch("/api/session/guest", { method: "POST" });
      if (!guest.ok) throw new ApiError(guest.status, "guest_unavailable");
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !consent || step !== "idle") return;
    setError(null);
    try {
      if (!TYPES.has(file.type)) throw new ApiError(422, "unsupported_media");
      setStep("session");
      await ensureSession();
      setStep("uploading");
      const bytes = await file.arrayBuffer();
      const ticket = await api.reserveUpload(file.type as "image/jpeg" | "image/png");
      const put = await fetch(ticket.url, { method: "PUT", body: bytes, headers: { "content-type": file.type } });
      if (!put.ok) throw new ApiError(put.status, "upload_failed");
      setStep("verifying");
      const capture = await api.completeUpload(ticket.upload_id, await sha256Hex(bytes));
      setStep("consent");
      await api.recordPermission({ purpose_id: "service_processing", scope_kind: "SPECIMEN",
                                   scope_ref: capture.capture_id, decision: "GRANT", notice_version: NOTICE,
                                   request_id: `web-${crypto.randomUUID()}` });
      setStep("queueing");
      const run = await api.startAnalysis(capture.capture_id);
      router.push(`/analyses/${encodeURIComponent(run.run_id)}`);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "unexpected";
      setError(MESSAGES[code] ?? `Something went wrong (${code}). Your photo was not analysed.`);
      setStep("idle");
    }
  }

  const busy = step !== "idle";
  return (
    <form className="stack" onSubmit={submit} aria-busy={busy}>
      <div className="panel stack">
        <label htmlFor="photo" style={{ display: "block" }}>
          <span>Photo of your handwriting (JPEG or PNG, up to 20 MB)</span>
        </label>
        <input id="photo" name="photo" type="file" accept="image/jpeg,image/png" disabled={busy}
               onChange={(e) => setFile(e.currentTarget.files?.[0] ?? null)} />
      </div>
      <fieldset>
        <legend>Permission</legend>
        <label>
          <input type="checkbox" checked={consent} disabled={busy} onChange={(e) => setConsent(e.currentTarget.checked)} />
          <span>
            Analyse this page. We process this photo of your own handwriting to measure it and build your report.
            You can withdraw this permission later, which deletes the report.
          </span>
        </label>
        <p className="muted">
          Keeping the image, AI-assisted processing and sharing are separate choices, and none of them is needed
          for the free report.
        </p>
      </fieldset>
      <p role="status" aria-live="polite" className="status">{busy ? progressText(step) : ""}</p>
      {error && <p role="alert" className="error">{error}</p>}
      <p><button className="button" type="submit" disabled={!file || !consent || busy}>Analyse my handwriting</button></p>
    </form>
  );
}

function progressText(step: Step): string {
  return { idle: "", session: "Starting a private session…", uploading: "Uploading…",
           verifying: "Checking the photo…", consent: "Recording your permission…",
           queueing: "Queueing the analysis…" }[step];
}
