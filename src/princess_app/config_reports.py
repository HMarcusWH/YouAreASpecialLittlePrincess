"""Fail-closed opt-in for report-reading v2 composition.

These flags select *only* a new report writer or a separately reviewed reading
policy. They never enable the existing model, commerce, research or egress
runtime gates. Reading old or already-saved reports does not consult this switch.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

from .domain.content.reading import reviewed_reading_sha256
from .domain.reports.story import StoryPolicy, story_policy_from_reviewed_reading
from .ports.base import InvalidInput

LEGACY_WRITER = "individual-report/2"
STORY_WRITER = "individual-report/4"
READING_PACK = "premium-reading/2"
FREE_SOURCE_PIN_ENV = "PRINCESS_EXPECTED_FREE_READING_REGISTRY_SHA256"


@dataclass(frozen=True)
class ReportReadingRuntime:
    story_writer_enabled: bool
    premium_v2_enabled: bool
    writer_template: str
    reading_manifest_sha256: str | None


@dataclass(frozen=True)
class VerifiedFreeStorySource:
    """Verified local/test Free story policy and content identity, not an activation token."""

    sha256: str
    policy: StoryPolicy
    private_qualified_candidate: bool = False  # private v2+v5 and /4 only


def resolve_free_story_source(
    environ: Mapping[str, str], *, report_runtime: ReportReadingRuntime,
) -> VerifiedFreeStorySource | None:
    """Fail closed *before* database or asset I/O on private /4 opt-in.

    This remains unavailable to public guest deployments and all staging or
    production providers while native/web/export /4 readers are unqualified.
    Neither the Premium manifest nor any HTTP-supplied flag can enable it.
    """
    if not report_runtime.story_writer_enabled:
        return None
    if (environ.get("PRINCESS_ENV") not in ("local", "test")
            or environ.get("PRINCESS_TEST_PUBLIC_GUEST_ONLY") == "1"):
        raise InvalidInput("report_story_private_test_only")
    # An opted-in guarded /4 is a private synthetic candidate only: require
    # independently pinned qualified-v2, evidence-support/5 and story source.
    # This does not create a new production flag or approve human data.
    guarded_candidate = environ.get("PRINCESS_EVIDENCE_SUPPORT_RESEARCH_OPT_IN") == "1"
    if guarded_candidate:
        from .application.intake import resolve_analysis_runtime
        try:
            runtime = resolve_analysis_runtime(environ)
        except ValueError as exc:
            raise InvalidInput("report_story_research_guard_conflict") from exc
        if (runtime.profile != "qualified-v2" or not runtime.evidence_guard_enabled
                or environ.get("PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256") != runtime.digest):
            raise InvalidInput("report_story_research_guard_conflict")
    expected = environ.get(FREE_SOURCE_PIN_ENV)
    if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise InvalidInput("report_story_source_pin_missing")
    try:
        current = reviewed_reading_sha256()
        policy = story_policy_from_reviewed_reading()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise InvalidInput("report_story_source_invalid") from exc
    if expected != current:
        raise InvalidInput("report_story_source_pin_mismatch")
    return VerifiedFreeStorySource(current, policy, guarded_candidate)


def _strict_switch(environ: Mapping[str, str], name: str) -> bool:
    value = environ.get(name, "")
    if value == "1" and isinstance(value, str):
        return True
    if value in ("", "0") and isinstance(value, str):
        return False
    raise InvalidInput("report_reading_flag_invalid", detail=name)


def _reviewed_manifest_digest(manifest: Mapping[str, object]) -> str:
    if not isinstance(manifest, Mapping):
        raise InvalidInput("report_reading_manifest_invalid")
    if manifest.get("runtime_activation") is not True:
        raise InvalidInput("report_reading_manifest_inactive")
    if manifest.get("reading_pack_version") != READING_PACK:
        raise InvalidInput("report_reading_manifest_version")
    if manifest.get("does_not_activate_base_pack") is not True:
        raise InvalidInput("report_reading_manifest_scope")
    if not all(isinstance(key, str) for key in manifest):
        raise InvalidInput("report_reading_manifest_invalid")
    try:
        canonical = json.dumps(
            dict(manifest), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise InvalidInput("report_reading_manifest_invalid") from exc
    return hashlib.sha256(canonical).hexdigest()


def resolve_report_reading_runtime(
    environ: Mapping[str, str], *, reviewed_reading_manifest: Mapping[str, object],
) -> ReportReadingRuntime:
    """Resolve an immutable writer/policy selection; grant no operational access.

    Enabling v2 Premium requires a separate approved manifest and exact hash.
    Other existing provider, permission, credit and kill-switch gates remain
    mandatory at the real composition and transaction boundaries.
    """
    story = _strict_switch(environ, "PRINCESS_REPORT_STORY_V2_ENABLED")
    premium = _strict_switch(environ, "PRINCESS_PREMIUM_READING_V2_ENABLED")
    template = STORY_WRITER if story else LEGACY_WRITER

    if story and environ.get("PRINCESS_EXPECTED_REPORT_TEMPLATE_VERSION") != STORY_WRITER:
        raise InvalidInput("report_reading_template_pin_mismatch")

    digest = None
    if premium:
        expected = environ.get("PRINCESS_EXPECTED_PREMIUM_READING_MANIFEST_SHA256")
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise InvalidInput("report_reading_manifest_pin_missing")
        digest = _reviewed_manifest_digest(reviewed_reading_manifest)
        if expected != digest:
            raise InvalidInput("report_reading_manifest_pin_mismatch")

    return ReportReadingRuntime(
        story_writer_enabled=story,
        premium_v2_enabled=premium,
        writer_template=template,
        reading_manifest_sha256=digest,
    )
