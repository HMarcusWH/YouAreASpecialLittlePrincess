"""Report feedback contract: screening and report-bound targets (T24)."""
from __future__ import annotations

import pytest

from princess_app.domain.feedback import MAX_COMMENT, FeedbackSubmission, check_submission, screen_comment
from princess_app.ports.base import InvalidInput

REPORT = {"sections": [{"section_id": "section.slant"}], "facts": [{"fact_id": "fact.SLANT_ANGLE_MEAN"}],
          "premium_overlay_id": None}


def submission(kind="FACT", ref="fact.SLANT_ANGLE_MEAN", category="MEASUREMENT_LOOKS_WRONG"):
    return FeedbackSubmission("report_1", category, kind, ref, None, "request_0001")


@pytest.mark.parametrize("text,expected", [
    ("  The slant looks off  ", "The slant looks off"),
    ("mail me at a.person@example.org please", "mail me at [email removed] please"),
    ("see https://example.invalid/x?y=1 now", "see [link removed] now"),
    ("call +46 70 123 45 67", "call +[number removed]"),
    ("", None),
    (None, None),
])
def test_comments_are_trimmed_and_redacted(text, expected):
    assert screen_comment(text) == expected


@pytest.mark.parametrize("text", [
    "x" * (MAX_COMMENT + 1),
    "data:image/png;base64,iVBORw0KGgo=",
    "A" * 80,                                        # a pasted blob
    '{"facts": [{"value": 20.1}]}',                  # a pasted report payload
    "<img src=x onerror=alert(1)>",
    "bell\x07",
])
def test_payload_like_comments_are_refused(text):
    with pytest.raises(InvalidInput):
        screen_comment(text)


def test_targets_must_exist_in_the_report():
    check_submission(submission(), REPORT)
    check_submission(submission("SECTION", "section.slant"), REPORT)
    check_submission(submission("REPORT", None, "OTHER"), REPORT)
    for bad in (submission("FACT", "fact.INVENTED"), submission("SECTION", "section.other"),
                submission("PREMIUM", "overlay_1"), submission("REPORT", "section.slant"),
                submission(category="DIAGNOSE_ME"), submission("PAGE", "x")):
        with pytest.raises(InvalidInput):
            check_submission(bad, REPORT)
    check_submission(submission("PREMIUM", "overlay_1"), {**REPORT, "premium_overlay_id": "overlay_1"})
