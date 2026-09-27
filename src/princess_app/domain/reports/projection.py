"""Authorization-filtered ReportViewModel projections (T09).

A projection omits; it never rewrites. Every projection is compiled and then
checked with ``validate_projection`` against the exact saved report, so a
Free view cannot carry Premium sections and no view can change a fact.
Commerce and sharing decisions arrive as inputs: this module does not read
entitlements, grants or storage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping

from princess_contracts import (
    ContractIssue,
    ValidatedDocument,
    ValidationResult,
    compile_document,
    validate_projection,
)
from princess_contracts import generated as g

from ..analysis import rfc3339

ACTION_KINDS = ("COMPARE", "EXPORT", "SHARE", "SAVE", "DELETE", "PURCHASE")
SOURCE_IMAGE_SCOPE = "source_image"


class PremiumAccess(str, Enum):
    NONE = "NONE"          # never purchased/published for this report
    UNLOCKED = "UNLOCKED"  # published overlay the viewer may read
    REVOKED = "REVOKED"    # refunded/withdrawn: stop serving it


@dataclass(frozen=True)
class ProjectionRequest:
    projection: str  # FREE | OWNER | PREMIUM | SHARE | EXPORT
    generated_at: datetime
    premium_access: PremiumAccess = PremiumAccess.NONE
    source_image_available: bool = True
    include_source_image: bool = True
    share_scope: frozenset[str] = field(default_factory=frozenset)
    # action kind -> None when enabled, or the reason it is disabled
    actions: Mapping[str, str | None] = field(default_factory=dict)


def _issue(code: str, message: str) -> ValidationResult[ValidatedDocument]:
    return ValidationResult(None, (ContractIssue(code, "", message),))


def project_report(report: ValidatedDocument, request: ProjectionRequest) -> ValidationResult[ValidatedDocument]:
    if report.schema_name != "ReportDocument":
        return _issue("WRONG_DOCUMENT_KIND", "expected a ReportDocument")
    kind = request.projection
    if kind not in {"FREE", "OWNER", "PREMIUM", "SHARE", "EXPORT"}:
        return _issue("UNKNOWN_PROJECTION", kind)
    unlocked = request.premium_access is PremiumAccess.UNLOCKED
    if kind == "PREMIUM" and not unlocked:
        return _issue("PREMIUM_NOT_AUTHORIZED", "Premium projection requires an unlocked, unrevoked overlay")
    unknown_actions = set(request.actions) - set(ACTION_KINDS)
    if unknown_actions:
        return _issue("UNKNOWN_ACTION", ",".join(sorted(unknown_actions)))

    source = report.to_dict()
    include_premium = kind in {"OWNER", "PREMIUM", "EXPORT", "SHARE"} and unlocked
    sections = []
    for section in source["sections"]:
        if section["premium_section_id"] is not None and not include_premium:
            continue
        if kind == "SHARE" and section["section_id"] not in request.share_scope:
            continue
        sections.append(section)
    referenced = {fid for section in sections for fid in section["fact_ids"]}
    facts = [fact for fact in source["facts"] if fact["fact_id"] in referenced]

    notices = [n for n in source["notices"] if n["class"] != "AI" or any(
        s["premium_section_id"] for s in sections)]
    image_allowed = request.source_image_available and (
        (kind == "SHARE" and SOURCE_IMAGE_SCOPE in request.share_scope)
        or (kind == "EXPORT" and request.include_source_image)
        or kind in {"FREE", "OWNER", "PREMIUM"})
    if not request.source_image_available:
        notices.append({"notice_id": "notice.source_image", "class": "PRIVACY",
                        "localization_key": "notice.source_image_unavailable"})
    elif kind in {"EXPORT", "SHARE"} and not image_allowed:
        notices.append({"notice_id": "notice.source_image", "class": "PRIVACY",
                        "localization_key": "notice.source_image_omitted"})
    if request.premium_access is PremiumAccess.REVOKED and source["premium_overlay_id"]:
        notices.append({"notice_id": "notice.premium_revoked", "class": "AI",
                        "localization_key": "notice.premium_revoked"})

    # Recipients and renderers never get owner actions.
    actions = [] if kind in {"SHARE", "EXPORT"} else [
        {"action_id": f"action.{k.lower()}", "kind": k, "enabled": request.actions[k] is None,
         "reason": request.actions[k]}
        for k in ACTION_KINDS if k in request.actions]
    view = {
        "contract_version": g.CONTRACT_VERSION,
        "source_report_id": source["report_id"],
        "source_revision": source["revision"],
        "source_digest": source["document_digest"],
        "projection": kind,
        "generated_at": rfc3339(request.generated_at),
        "locale": source["locale"],
        "facts": facts,
        "sections": sections,
        "notices": notices,
        "actions": actions,
        "authorized_asset_ids": [source["analysis"]["input_asset_id"]] if image_allowed else [],
    }
    compiled = compile_document("ReportViewModel", view)
    if compiled.value is None:
        return compiled
    issues = validate_projection(report, compiled.value)
    return compiled if not issues else ValidationResult(None, issues)
