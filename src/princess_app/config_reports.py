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

from .ports.base import InvalidInput

LEGACY_WRITER = "individual-report/2"
STORY_WRITER = "individual-report/4"
READING_PACK = "premium-reading/2"


@dataclass(frozen=True)
class ReportReadingRuntime:
    story_writer_enabled: bool
    premium_v2_enabled: bool
    writer_template: str
    reading_manifest_sha256: str | None


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
