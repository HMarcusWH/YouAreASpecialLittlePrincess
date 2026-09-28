"""Pure, deterministic ReportDocument assembly (T09).

Input is the canonical ``AnalysisResult`` JSON, its ``AnalysisReference`` and
optionally a compiled ``EvidenceBundle``. Output is a compiled, self-digested
``ReportDocument`` or contract issues with no value. Nothing here calls a
model, reads storage or consults entitlements.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from princess_contracts import (
    ContractIssue,
    ValidatedDocument,
    ValidationResult,
    canonical_digest,
    compile_document,
    free_feature_ids,
    free_method_ids,
)
from princess_contracts import generated as g

from ..analysis import method_versions, rfc3339
from ..content import presentation_registry, select_highlights
from .template import (BASE_TEMPLATE_VERSION, FACT_SECTIONS, HIGHLIGHT_PRESENTATION_VERSION,
                       PREMIUM_SECTION, REFERENCE_SECTION, SUPPORTED_TEMPLATE_VERSIONS,
                       TEMPLATE_VERSION, formatting_for)

MAX_SOURCE_REGIONS = 128
EVIDENCE_CLASS = {"MEASURED_VISUAL_FEATURE": "MEASURED", "COMPUTATIONAL_PROXY": "COMPUTATIONAL_PROXY"}
PRESENT = {"READY", "UNCALIBRATED"}


def _fail(code: str, path: str, message: str) -> ValidationResult[ValidatedDocument]:
    return ValidationResult(None, (ContractIssue(code, path, message),))


def _nearest_kept(region_id: str, parents: Mapping[str, str | None], kept: set[str]) -> str | None:
    seen: set[str] = set()
    current: str | None = region_id
    while current is not None and current not in kept and current not in seen:
        seen.add(current)
        current = parents.get(current)
    return current if current in kept else None


def _source_regions(ids: Sequence[str], parents: Mapping[str, str | None], kept: set[str] | None) -> list[str]:
    out = list(dict.fromkeys(ids))
    if kept is not None:
        out = list(dict.fromkeys(r for r in (_nearest_kept(i, parents, kept) for i in out) if r is not None))
    while len(out) > MAX_SOURCE_REGIONS:
        coarser = list(dict.fromkeys(parents.get(r) or r for r in out))
        if coarser == out:
            return out[:0]
        out = coarser
    return out


def facts_from_result(result: Mapping[str, Any], *,
                      evidence_region_ids: set[str] | None = None) -> tuple[list[dict[str, Any]], list[ContractIssue]]:
    """Map canonical measurements to report facts; missing stays missing."""
    versions = method_versions()
    free = set(free_method_ids())
    parents = {r["region_id"]: r.get("parent_id") for r in result.get("regions", ())}
    measurements = result.get("measurements", {})
    order = [f for _, _, ids in FACT_SECTIONS for f in ids]
    ordered = [f for f in order if f in measurements] + sorted(set(measurements) - set(order))
    facts, issues = [], []
    for feature_id in ordered:
        m = measurements[feature_id]
        method_id = m.get("method_version")
        if method_id not in versions:
            issues.append(ContractIssue("UNKNOWN_METHOD", f"/measurements/{feature_id}", str(method_id)))
            continue
        if method_id not in free:
            issues.append(ContractIssue("NON_FREE_METHOD", f"/measurements/{feature_id}", str(method_id)))
            continue
        if m.get("evidence_status") not in EVIDENCE_CLASS:
            # Traditional, contested or unsupported classes are never relabelled as proxies.
            issues.append(ContractIssue("UNSUPPORTED_EVIDENCE_STATUS", f"/measurements/{feature_id}",
                                        str(m.get("evidence_status"))))
            continue
        missing = m.get("quality_flag") == "MISSING" or m.get("raw_value") is None
        availability = "MISSING" if missing else (
            "UNCALIBRATED" if m.get("confidence_kind") == "UNCALIBRATED" else "READY")
        formatting_key, precision = formatting_for(m.get("unit"))
        facts.append({
            "fact_id": f"fact.{feature_id}",
            "feature_id": feature_id,
            "availability": availability,
            "value": None if missing else m.get("raw_value"),
            "unit": m.get("unit"),
            "evidence_class": EVIDENCE_CLASS[m["evidence_status"]],
            "method_id": method_id,
            "method_version": versions[method_id],
            "source_region_ids": _source_regions(m.get("source_regions", ()), parents, evidence_region_ids),
            "quality": {
                "state": m.get("quality_flag"),
                "missing_reason": m.get("missing_reason") if missing else None,
                "n_observations": m.get("n_observations"),
                "confidence": m.get("confidence"),
                "confidence_kind": m.get("confidence_kind"),
            },
            "formatting_key": formatting_key,
            "precision": precision,
        })
    return facts, issues


def _section_availability(facts: Sequence[Mapping[str, Any]]) -> str:
    states = {f["availability"] for f in facts}
    if not states or states == {"MISSING"}:
        return "MISSING"
    return "READY" if "READY" in states else "UNCALIBRATED"


def _highlight_availability(facts: Sequence[Mapping[str, Any]]) -> str:
    """A compound statement is only as calibrated as its least-ready support."""
    return "READY" if facts and all(f["availability"] == "READY" for f in facts) else "UNCALIBRATED"


def _highlight_sections(facts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    registry = presentation_registry()
    if registry["version"] != HIGHLIGHT_PRESENTATION_VERSION:
        raise ValueError("highlight template/presentation authority drift")
    by_id = {f["fact_id"]: f for f in facts}
    selected = select_highlights(facts, limit=3)
    if not selected:
        return [{
            "section_id": "section.highlight.primary",
            "template": "HIGHLIGHT_PRIMARY",
            "availability": "INELIGIBLE",
            "fact_ids": [],
            "content_ids": [registry["fallback_content_id"]],
            "premium_section_id": None,
        }]
    sections: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected):
        members = [by_id[fact_id] for fact_id in candidate.support_fact_ids]
        primary = index == 0
        sections.append({
            "section_id": "section.highlight.primary" if primary else f"section.highlight.secondary.{index}",
            "template": "HIGHLIGHT_PRIMARY" if primary else "HIGHLIGHT_SECONDARY",
            "availability": _highlight_availability(members),
            "fact_ids": list(candidate.support_fact_ids),
            "content_ids": [candidate.content_id],
            "premium_section_id": None,
        })
    return sections


def build_sections(facts: Sequence[Mapping[str, Any]], *, reference_claims: Sequence[Mapping[str, Any]],
                   premium_overlay_id: str | None, template_version: str = TEMPLATE_VERSION) -> list[dict[str, Any]]:
    if template_version not in SUPPORTED_TEMPLATE_VERSIONS:
        raise ValueError(f"unsupported report template {template_version!r}")
    by_feature = {f["feature_id"]: f for f in facts}
    sections = [] if template_version == BASE_TEMPLATE_VERSION else _highlight_sections(facts)
    for section_id, template, feature_ids in FACT_SECTIONS:
        members = [by_feature[f] for f in feature_ids if f in by_feature]
        if members:
            sections.append({"section_id": section_id, "template": template,
                             "availability": _section_availability(members),
                             "fact_ids": [f["fact_id"] for f in members], "content_ids": [],
                             "premium_section_id": None})
    claimed = [by_feature[c["feature_id"]]["fact_id"] for c in reference_claims if c["feature_id"] in by_feature]
    sections.append({"section_id": REFERENCE_SECTION[0], "template": REFERENCE_SECTION[1],
                     "availability": "READY" if claimed else "INELIGIBLE", "fact_ids": list(dict.fromkeys(claimed)),
                     "content_ids": [], "premium_section_id": None})
    sections.append({"section_id": PREMIUM_SECTION[0], "template": PREMIUM_SECTION[1],
                     "availability": "READY" if premium_overlay_id else "LOCKED", "fact_ids": [],
                     "content_ids": [],
                     "premium_section_id": f"premium.{premium_overlay_id}" if premium_overlay_id else None})
    return sections


def build_notices(facts: Sequence[Mapping[str, Any]], *, has_reference: bool,
                  premium_overlay_id: str | None) -> list[dict[str, str]]:
    classes = {f["evidence_class"] for f in facts if f["availability"] in PRESENT}
    notices = []
    if "MEASURED" in classes:
        notices.append({"notice_id": "notice.measured", "class": "MEASURED", "localization_key": "notice.measured"})
    if "COMPUTATIONAL_PROXY" in classes:
        notices.append({"notice_id": "notice.proxy", "class": "PROXY",
                        "localization_key": "notice.proxy_uncalibrated"})
    notices.append({"notice_id": "notice.reference", "class": "REFERENCE",
                    "localization_key": "notice.reference_named_cohort" if has_reference
                    else "notice.reference_unavailable"})
    notices.append({"notice_id": "notice.traditional", "class": "TRADITIONAL",
                    "localization_key": "notice.traditional_not_included"})
    if premium_overlay_id:
        notices.append({"notice_id": "notice.ai", "class": "AI", "localization_key": "notice.ai_synthesis"})
    notices.append({"notice_id": "notice.privacy", "class": "PRIVACY", "localization_key": "notice.private_report"})
    return notices


def _finish(document: dict[str, Any]) -> ValidationResult[ValidatedDocument]:
    document["document_digest"] = None
    document["document_digest"] = canonical_digest(document)
    return compile_document("ReportDocument", document)


def assemble_report(*, report_id: str, analysis: Mapping[str, Any], result: Mapping[str, Any],
                    created_at: datetime, locale: str, evidence: ValidatedDocument | None = None,
                    reference_claims: Sequence[Mapping[str, Any]] = (),
                    premium_overlay_id: str | None = None) -> ValidationResult[ValidatedDocument]:
    """Assemble revision 1 of an individual report."""
    metadata = result.get("metadata", {})
    if metadata.get("schema_version") != g.FEATURE_SCHEMA_VERSION:
        return _fail("RESULT_SCHEMA_DRIFT", "/metadata/schema_version", "result was produced for another schema")
    if metadata.get("input_pixels_sha256") != analysis.get("processed_sha256"):
        return _fail("RESULT_ANALYSIS_MISMATCH", "/metadata/input_pixels_sha256",
                     "result was produced from different pixels than this analysis")
    template_version = analysis.get("versions", {}).get("template")
    if template_version not in SUPPORTED_TEMPLATE_VERSIONS:
        return _fail("TEMPLATE_VERSION_MISMATCH", "/analysis/versions/template",
                     f"supported templates are {sorted(SUPPORTED_TEMPLATE_VERSIONS)}")
    missing = set(free_feature_ids()) - set(result.get("measurements", {}))
    if missing:
        return _fail("INCOMPLETE_RESULT", "/measurements",
                     f"{len(missing)} Free aggregates absent, e.g. {sorted(missing)[0]}")
    kept = None
    if evidence is not None:
        if evidence.schema_name != "EvidenceBundle":
            return _fail("WRONG_DOCUMENT_KIND", "/evidence", "expected an EvidenceBundle")
        if evidence.to_dict()["analysis"] != dict(analysis):
            return _fail("EVIDENCE_ANALYSIS_MISMATCH", "/evidence", "evidence belongs to another analysis/run")
        kept = {r["region_id"] for r in evidence.data["regions"]}
    facts, issues = facts_from_result(result, evidence_region_ids=kept)
    if issues:
        return ValidationResult(None, tuple(issues))
    claims = [dict(c) for c in reference_claims]
    document = {
        "contract_version": g.CONTRACT_VERSION,
        "report_id": report_id,
        "revision": 1,
        "kind": "INDIVIDUAL",
        "created_at": rfc3339(created_at),
        "locale": locale,
        "analysis": dict(analysis),
        "evidence_bundle_id": evidence.data["bundle_id"] if evidence is not None else None,
        "facts": facts,
        "reference_claims": claims,
        "sections": build_sections(facts, reference_claims=claims, premium_overlay_id=premium_overlay_id,
                                   template_version=template_version),
        "notices": build_notices(facts, has_reference=bool(claims), premium_overlay_id=premium_overlay_id),
        "premium_overlay_id": premium_overlay_id,
    }
    return _finish(document)


def revise_report(previous: ValidatedDocument, *, created_at: datetime,
                  premium_overlay_id: str | None) -> ValidationResult[ValidatedDocument]:
    """Create the next revision with a (new) Premium overlay attached.

    Facts, analysis, evidence and reference claims are carried over unchanged;
    a different benchmark or analysis is a new report, never a revision.
    """
    if previous.schema_name != "ReportDocument":
        return _fail("WRONG_DOCUMENT_KIND", "", "expected a ReportDocument")
    old = previous.to_dict()
    if created_at < datetime.fromisoformat(old["created_at"].replace("Z", "+00:00")):
        return _fail("REVISION_BEFORE_PREVIOUS", "/created_at", "a revision cannot predate its predecessor")
    document = {**old, "revision": old["revision"] + 1, "created_at": rfc3339(created_at),
                "premium_overlay_id": premium_overlay_id,
                "sections": build_sections(old["facts"], reference_claims=old["reference_claims"],
                                           premium_overlay_id=premium_overlay_id,
                                           template_version=old["analysis"]["versions"]["template"]),
                "notices": build_notices(old["facts"], has_reference=bool(old["reference_claims"]),
                                         premium_overlay_id=premium_overlay_id)}
    return _finish(document)


IMMUTABLE_ACROSS_REVISIONS = ("report_id", "kind", "locale", "analysis", "evidence_bundle_id", "facts",
                              "reference_claims")


def check_revision(previous: ValidatedDocument, candidate: ValidatedDocument) -> tuple[ContractIssue, ...]:
    """Persistence-side guard: a stored revision may only extend its predecessor."""
    old, new = previous.to_dict(), candidate.to_dict()
    issues = [ContractIssue("REVISION_MUTATES_" + field.upper(), f"/{field}",
                            f"{field} is immutable across revisions")
              for field in IMMUTABLE_ACROSS_REVISIONS if old[field] != new[field]]
    if new["revision"] != old["revision"] + 1:
        issues.append(ContractIssue("REVISION_NOT_SEQUENTIAL", "/revision", "revisions increase by one"))
    # Sections and notices are derived, never authored: a revision cannot hide
    # facts or reword notices by recompiling a self-consistent document.
    overlay = new.get("premium_overlay_id")
    if new["sections"] != build_sections(new["facts"], reference_claims=new["reference_claims"],
                                         premium_overlay_id=overlay,
                                         template_version=new["analysis"]["versions"]["template"]):
        issues.append(ContractIssue("REVISION_SECTIONS_NOT_DERIVED", "/sections", "sections must be derived"))
    if new["notices"] != build_notices(new["facts"], has_reference=bool(new["reference_claims"]),
                                       premium_overlay_id=overlay):
        issues.append(ContractIssue("REVISION_NOTICES_NOT_DERIVED", "/notices", "notices must be derived"))
    if _parse_time(new["created_at"]) < _parse_time(old["created_at"]):
        issues.append(ContractIssue("REVISION_BEFORE_PREVIOUS", "/created_at", "a revision cannot predate its predecessor"))
    return tuple(issues)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
