"""Pure Comparison document construction for T18."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from princess_contracts import ContractIssue, ValidatedDocument, ValidationResult, canonical_digest, compile_document
from princess_contracts import generated as g

from ..analysis import rfc3339
from ..content import PRESENTATION_VERSION
from .policy import (
    COMPARISON_METHOD_VERSION,
    HISTORY_ORDERING,
    PAIR_ORDERING,
    assess_feature,
    candidate_feature_ids,
    native_delta,
)

MAX_HISTORY_INPUTS = 16


def _fail(code: str, path: str, message: str) -> ValidationResult[ValidatedDocument]:
    return ValidationResult(None, (ContractIssue(code, path, message),))


def _report_data(report: ValidatedDocument, position: int) -> Mapping[str, Any]:
    if report.schema_name != "ReportDocument":
        raise ValueError(f"input {position} is not a ReportDocument")
    data = report.data
    if data["kind"] != "INDIVIDUAL":
        raise ValueError(f"input {position} is not an individual report")
    if data["document_digest"] is None:
        raise ValueError(f"input {position} has no immutable report digest")
    return data


def _ordered(kind: str, reports: Sequence[ValidatedDocument]) -> list[ValidatedDocument]:
    if kind == "PAIR":
        return list(reports)
    return sorted(reports, key=lambda report: (str(report.data["created_at"]), str(report.data["report_id"])))


def _input_row(position: int, data: Mapping[str, Any]) -> dict[str, Any]:
    analysis = data["analysis"]
    return {
        "position": position,
        "report_id": data["report_id"],
        "revision": data["revision"],
        "report_digest": data["document_digest"],
        "report_created_at": data["created_at"],
        "analysis_id": analysis["analysis_id"],
        "run_id": analysis["run_id"],
        "analysis_created_at": analysis["created_at"],
        "versions": dict(analysis["versions"]),
    }


def build_comparison(*, comparison_id: str, kind: str, reports: Sequence[ValidatedDocument],
                     created_at: datetime) -> ValidationResult[ValidatedDocument]:
    """Build deterministic pair/history comparison from saved report snapshots.

    PAIR preserves caller order. HISTORY is ordered by report creation time and
    report ID as a stable tie-breaker; this is explicitly not a writing-date claim.
    """
    if kind not in {"PAIR", "HISTORY"}:
        return _fail("UNSUPPORTED_COMPARISON_KIND", "/kind", "kind must be PAIR or HISTORY")
    if kind == "PAIR" and len(reports) != 2:
        return _fail("PAIR_INPUT_COUNT", "/inputs", "PAIR requires exactly two reports")
    if kind == "HISTORY" and not 2 <= len(reports) <= MAX_HISTORY_INPUTS:
        return _fail("HISTORY_INPUT_COUNT", "/inputs", "HISTORY requires 2..16 reports")

    ordered = _ordered(kind, reports)
    try:
        rows = [_report_data(report, position) for position, report in enumerate(ordered)]
    except ValueError as exc:
        return _fail("INVALID_COMPARISON_INPUT", "/inputs", str(exc))

    report_ids = [str(row["report_id"]) for row in rows]
    if len(report_ids) != len(set(report_ids)):
        return _fail("DUPLICATE_COMPARISON_INPUT", "/input_report_ids", "comparison inputs must be distinct reports")

    fact_maps: list[dict[str, Mapping[str, Any]]] = []
    for position, row in enumerate(rows):
        mapping: dict[str, Mapping[str, Any]] = {}
        for fact in row["facts"]:
            feature_id = str(fact["feature_id"])
            if feature_id in mapping:
                return _fail("AMBIGUOUS_INPUT_FEATURE", f"/inputs/{position}",
                             f"report contains more than one fact for feature {feature_id}")
            mapping[feature_id] = fact
        fact_maps.append(mapping)

    candidates = list(candidate_feature_ids())
    common: list[str] = []
    exclusions: list[dict[str, Any]] = []
    assessments: dict[str, Any] = {}
    for feature_id in candidates:
        assessment = assess_feature(
            feature_id, fact_maps,
            analysis_versions=[row["analysis"]["versions"] for row in rows],
        )
        assessments[feature_id] = assessment
        if assessment.comparable:
            common.append(feature_id)
        else:
            exclusions.append({
                "feature_id": feature_id,
                "reason": assessment.reason,
                "affected_positions": list(assessment.affected_positions),
            })

    differences: list[dict[str, Any]] = []
    for feature_id in common:
        assessment = assessments[feature_id]
        facts = assessment.facts
        domain = dict(assessment.domain)
        wire_domain = {
            "min": domain["min"],
            "max": domain["max"],
            "unit": domain["unit"],
            "kind": domain["kind"],
            "accepted_min": domain.get("accepted_min"),
            "accepted_max": domain.get("accepted_max"),
        }
        for from_position in range(len(facts) - 1):
            to_position = from_position + 1
            fact_from, fact_to = facts[from_position], facts[to_position]
            value_from, value_to = float(fact_from["value"]), float(fact_to["value"])
            signed, absolute, direction = native_delta(value_from, value_to)
            differences.append({
                "feature_id": feature_id,
                "from_position": from_position,
                "to_position": to_position,
                "from_fact_id": fact_from["fact_id"],
                "to_fact_id": fact_to["fact_id"],
                "unit": fact_from["unit"],
                "value_from": value_from,
                "value_to": value_to,
                "signed_delta": signed,
                "absolute_delta": absolute,
                "direction": direction,
                "method_id": fact_from["method_id"],
                "method_version": fact_from["method_version"],
                "formatting_key": fact_from["formatting_key"],
                "precision": fact_from["precision"],
                "display_domain": wire_domain,
            })

    document = {
        "contract_version": g.CONTRACT_VERSION,
        "comparison_id": comparison_id,
        "kind": kind,
        "created_at": rfc3339(created_at),
        "ordering_basis": PAIR_ORDERING if kind == "PAIR" else HISTORY_ORDERING,
        "input_report_ids": report_ids,
        "inputs": [_input_row(position, row) for position, row in enumerate(rows)],
        "candidate_feature_ids": candidates,
        "common_feature_ids": common,
        "coverage": {
            "candidate_n": len(candidates),
            "common_n": len(common),
            "excluded_n": len(exclusions),
            "common_fraction": len(common) / len(candidates),
        },
        "differences": differences,
        "exclusions": exclusions,
        "facts": [],
        "method_version": COMPARISON_METHOD_VERSION,
        "presentation_version": PRESENTATION_VERSION,
        "comparison_digest": None,
    }
    document["comparison_digest"] = canonical_digest(document)
    return compile_document("Comparison", document)
