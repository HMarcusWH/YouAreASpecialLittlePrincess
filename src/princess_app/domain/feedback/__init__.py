"""Report feedback contract (T24): what an owner may tell us about a report.

Feedback is not telemetry. It is bound to one owner and one saved report,
points at an element that exists in that report, and carries an optional
short comment that is screened before storage:

* refused: payload-like text (data/base64 blobs, JSON or markup, control
  characters) and anything over the length cap — we never store a pasted
  report, transcription dump or image;
* redacted: e-mail addresses, links and long digit runs (phone or card
  numbers) become neutral markers.

A keyword screen is a guardrail, not a guarantee; support review stays
restricted (see migration 0007).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from ...ports.base import InvalidInput, require_opaque_id

CONTRACT_VERSION = "report-feedback/1"
CATEGORIES = frozenset({"MEASUREMENT_LOOKS_WRONG", "HARD_TO_UNDERSTAND", "HARMFUL_OR_OFFENSIVE",
                        "PREMIUM_TEXT_ISSUE", "OTHER"})
TARGET_KINDS = frozenset({"REPORT", "SECTION", "FACT", "PREMIUM"})
MAX_COMMENT = 500
MAX_PER_REPORT = 20

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_PAYLOAD = re.compile(r"(data:[a-z]+/|[A-Za-z0-9+/=]{64,}|<[a-zA-Z/!]|\{\s*\"|\"\s*:\s*[\[{\"0-9])")
_EMAIL = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(\.[\w-]{1,63})+")
_LINK = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_DIGITS = re.compile(r"(?:\d[\s-]?){7,}")


@dataclass(frozen=True)
class FeedbackSubmission:
    report_id: str
    category: str
    target_kind: str
    target_ref: str | None
    comment: str | None
    request_id: str


def screen_comment(text: str | None) -> str | None:
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    if len(text) > MAX_COMMENT:
        raise InvalidInput("comment_too_long")
    if _CONTROL.search(text) or _PAYLOAD.search(text):
        raise InvalidInput("comment_not_allowed")  # never store pasted payloads or markup
    text = _EMAIL.sub("[email removed]", text)
    text = _LINK.sub("[link removed]", text)
    return _DIGITS.sub("[number removed]", text)


def check_submission(submission: FeedbackSubmission, report: Mapping[str, Any]) -> None:
    """``report`` is the saved ReportDocument the owner can read."""
    require_opaque_id(submission.request_id, "request_id")
    if submission.category not in CATEGORIES:
        raise InvalidInput("unknown_category")
    kind, ref = submission.target_kind, submission.target_ref
    if kind not in TARGET_KINDS:
        raise InvalidInput("unknown_target")
    if kind == "REPORT":
        if ref is not None:
            raise InvalidInput("unknown_target")
        return
    known = {"SECTION": {s["section_id"] for s in report["sections"]},
             "FACT": {f["fact_id"] for f in report["facts"]},
             "PREMIUM": {report["premium_overlay_id"]} - {None}}[kind]
    if ref not in known:
        raise InvalidInput("unknown_target")  # feedback points at something in this report


__all__ = ["CATEGORIES", "CONTRACT_VERSION", "FeedbackSubmission", "MAX_COMMENT", "MAX_PER_REPORT", "TARGET_KINDS",
           "check_submission", "screen_comment"]
