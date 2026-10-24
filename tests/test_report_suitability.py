"""R2 support assessment: mechanical suitability never means purchase permission."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from princess_app.domain.reports.suitability import (
    ReportSuitability,
    assess_report_suitability,
    assess_sample_support,
    premium_sample_eligible,
)

ROOT = Path(__file__).resolve().parents[1]


def _report(*, template: str = "individual-report/2",
            lines: object = 3, words: object = 3,
            line_state: object = "UNCALIBRATED",
            word_state: object = "UNCALIBRATED",
            sample_state: object = "READY") -> dict:
    return {
        "analysis": {"versions": {"template": template}},
        "sections": [{"section_id": "section.sample", "availability": sample_state}],
        "facts": [
            {"fact_id": "fact.PAGE_LINE_COUNT", "feature_id": "PAGE_LINE_COUNT",
             "availability": line_state, "value": lines},
            {"fact_id": "fact.PAGE_WORD_COUNT", "feature_id": "PAGE_WORD_COUNT",
             "availability": word_state, "value": words},
        ],
    }


@pytest.mark.parametrize("template", [
    "individual-report/1", "individual-report/2",
    "individual-report/3", "individual-report/4",
])
def test_supported_versions_use_same_read_only_gate(template):
    doc = _report(template=template)
    before = copy.deepcopy(doc)
    assert assess_report_suitability(doc) is ReportSuitability.SUPPORTED
    assert assess_sample_support(doc) is ReportSuitability.SUPPORTED
    assert premium_sample_eligible(doc) is True
    assert doc == before


@pytest.mark.parametrize("template", [None, 3, [], {}, "individual-report/5",
                                       "individual-report/0", "presentation/2"])
def test_unknown_template_fails_before_mechanical_measurements(template):
    doc = _report()
    doc["analysis"]["versions"]["template"] = template
    doc["sections"][0]["availability"] = "INELIGIBLE"
    assert assess_report_suitability(doc) is ReportSuitability.UNSUPPORTED_TEMPLATE
    assert not premium_sample_eligible(doc)


@pytest.mark.parametrize("malformed", [None, 5, [], {}, {"analysis": {}},
                                       {"analysis": {"versions": []}}])
def test_missing_structure_never_grants_support(malformed):
    assert assess_report_suitability(malformed) is ReportSuitability.UNSUPPORTED_TEMPLATE


@pytest.mark.parametrize("bad_value", [None, False, True, 0, -1, 0.0, -0.5,
                                       "2", float("nan"), float("inf"),
                                       -float("inf"), [], {}, 10 ** 1000])
def test_line_count_unavailable_or_nonpositive_is_unqualified(bad_value):
    assert assess_report_suitability(_report(lines=bad_value)) is ReportSuitability.UNQUALIFIED


@pytest.mark.parametrize("availability", ["MISSING", "INELIGIBLE", "LOCKED", "", None, []])
def test_missing_line_availability_is_not_silently_promoted(availability):
    assert assess_report_suitability(_report(lines=3, line_state=availability)) is ReportSuitability.UNQUALIFIED


@pytest.mark.parametrize("bad_value", [None, False, True, 0, -1, 0.0,
                                       "3", float("nan"), float("inf"),
                                       [], {}, 10 ** 1000])
def test_word_count_unavailable_or_nonpositive_is_partial(bad_value):
    assert assess_report_suitability(_report(words=bad_value)) is ReportSuitability.PARTIAL
    assert not premium_sample_eligible(_report(words=bad_value))


@pytest.mark.parametrize("availability", ["MISSING", "LOCKED", "INELIGIBLE", None, []])
def test_missing_word_availability_is_partial(availability):
    assert assess_report_suitability(_report(words=3, word_state=availability)) is ReportSuitability.PARTIAL


def test_missing_line_or_word_group_fact_never_defaults_to_zero_or_supported():
    doc = _report()
    doc["facts"].pop(0)
    assert assess_report_suitability(doc) is ReportSuitability.UNQUALIFIED
    doc = _report()
    doc["facts"].pop(1)
    assert assess_report_suitability(doc) is ReportSuitability.PARTIAL


def test_duplicate_critical_facts_fail_closed():
    doc = _report()
    doc["facts"].append(copy.deepcopy(doc["facts"][0]))
    assert assess_report_suitability(doc) is ReportSuitability.UNQUALIFIED
    doc = _report()
    doc["facts"].append(copy.deepcopy(doc["facts"][1]))
    assert assess_report_suitability(doc) is ReportSuitability.PARTIAL


def test_saved_explicit_ineligibility_precedes_valid_counts():
    assert assess_report_suitability(_report(sample_state="INELIGIBLE")) is ReportSuitability.UNQUALIFIED


def test_duplicate_sample_sections_and_invalid_sections_fail_closed():
    doc = _report()
    doc["sections"].append(dict(doc["sections"][0]))
    assert assess_report_suitability(doc) is ReportSuitability.UNQUALIFIED
    doc["sections"] = None
    assert assess_report_suitability(doc) is ReportSuitability.UNQUALIFIED


def test_normal_uncalibrated_positive_counts_are_supported_not_high_confidence():
    assert assess_report_suitability(_report(lines=1.0, words=1.0)) is ReportSuitability.SUPPORTED
    assert assess_report_suitability(_report(lines=2, words=5,
                                            line_state="READY", word_state="READY")) is ReportSuitability.SUPPORTED


def test_real_legacy_fixture_remains_supported_without_reinterpreting_it():
    for filename in ("report-document.json", "report-document.v2.json"):
        doc = json.loads((ROOT / "fixtures" / "reports" / filename).read_text(encoding="utf-8"))
        before = copy.deepcopy(doc)
        assert assess_report_suitability(doc) is ReportSuitability.SUPPORTED
        assert doc == before


def test_validated_document_like_input_is_read_without_mutation():
    class ReadOnlySnapshot:
        def __init__(self, value):
            self.value = value

        def to_dict(self):
            return copy.deepcopy(self.value)

    assert assess_report_suitability(ReadOnlySnapshot(_report())) is ReportSuitability.SUPPORTED
