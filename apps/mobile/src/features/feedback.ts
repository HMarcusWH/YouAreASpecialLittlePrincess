// Owner-bound report-content feedback (N05/N11). The comment is optional,
// bounded and sent only to the feedback endpoint; it is never written to
// analytics, logs or local storage.
import type { FeedbackCategory, FeedbackReceipt, FeedbackTarget, PrincessApi } from "@princess/api-client";

export const MAX_COMMENT = 500;

export type FeedbackApi = Pick<PrincessApi, "submitFeedback" | "withdrawFeedback">;

export interface FeedbackDraft {
  readonly category: FeedbackCategory;
  readonly target: FeedbackTarget;
  readonly targetRef: string | null;
  readonly comment: string;
}

export function normalizeComment(comment: string): string | null {
  const trimmed = comment.replace(/\s+/g, " ").trim();
  return trimmed.length === 0 ? null : trimmed.slice(0, MAX_COMMENT);
}

export async function submitFeedback(api: FeedbackApi, reportId: string, draft: FeedbackDraft,
                                     requestId: string): Promise<FeedbackReceipt> {
  return api.submitFeedback(reportId, { category: draft.category, target_kind: draft.target,
                                        target_ref: draft.targetRef, comment: normalizeComment(draft.comment),
                                        request_id: requestId });
}
