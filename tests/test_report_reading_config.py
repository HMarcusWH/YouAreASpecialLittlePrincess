"""R1 fail-closed report-reading composition tests (no providers or credits)."""
import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from princess_app.config_reports import (
    LEGACY_WRITER,
    READING_PACK,
    STORY_WRITER,
    resolve_report_reading_runtime,
)
from princess_app.ports.base import InvalidInput


INACTIVE_MANIFEST = {
    "reading_pack_version": READING_PACK,
    "runtime_activation": False,
    "does_not_activate_base_pack": True,
}


def _digest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def test_flags_default_off_without_manifest_activation():
    for setting in ({}, {"PRINCESS_REPORT_STORY_V2_ENABLED": "", "PRINCESS_PREMIUM_READING_V2_ENABLED": "0"}):
        result = resolve_report_reading_runtime(setting, reviewed_reading_manifest=INACTIVE_MANIFEST)
        assert result.story_writer_enabled is False
        assert result.premium_v2_enabled is False
        assert result.writer_template == LEGACY_WRITER
        assert result.reading_manifest_sha256 is None
        with pytest.raises(FrozenInstanceError):
            result.writer_template = STORY_WRITER


@pytest.mark.parametrize("name", ["PRINCESS_REPORT_STORY_V2_ENABLED", "PRINCESS_PREMIUM_READING_V2_ENABLED"])
@pytest.mark.parametrize("value", ["true", "false", "yes", "on", "2", " 1", "1 ", "-1", True, 1, None])
def test_rejects_ambiguous_switch_values(name, value):
    with pytest.raises(InvalidInput, match="report_reading_flag_invalid"):
        resolve_report_reading_runtime({name: value}, reviewed_reading_manifest=INACTIVE_MANIFEST)


def test_story_requires_exact_template_pin_but_cannot_enable_premium():
    for pin in (None, "", LEGACY_WRITER, "individual-report/3", "individual-report/5"):
        env = {"PRINCESS_REPORT_STORY_V2_ENABLED": "1"}
        if pin is not None:
            env["PRINCESS_EXPECTED_REPORT_TEMPLATE_VERSION"] = pin
        with pytest.raises(InvalidInput, match="report_reading_template_pin_mismatch"):
            resolve_report_reading_runtime(env, reviewed_reading_manifest=INACTIVE_MANIFEST)
    result = resolve_report_reading_runtime({
        "PRINCESS_REPORT_STORY_V2_ENABLED": "1",
        "PRINCESS_EXPECTED_REPORT_TEMPLATE_VERSION": STORY_WRITER,
    }, reviewed_reading_manifest=INACTIVE_MANIFEST)
    assert (result.story_writer_enabled, result.premium_v2_enabled, result.writer_template) == (True, False, STORY_WRITER)


def test_inactive_pack_refuses_generation_even_with_exact_digest():
    with pytest.raises(InvalidInput, match="report_reading_manifest_inactive"):
        resolve_report_reading_runtime({
            "PRINCESS_PREMIUM_READING_V2_ENABLED": "1",
            "PRINCESS_EXPECTED_PREMIUM_READING_MANIFEST_SHA256": _digest(INACTIVE_MANIFEST),
        }, reviewed_reading_manifest=INACTIVE_MANIFEST)


def test_premium_requires_exact_reviewed_manifest_pin_and_isolation():
    approved = {**INACTIVE_MANIFEST, "runtime_activation": True}
    for pin in (None, "", "0" * 64, "A" * 64, "z" * 64):
        env = {"PRINCESS_PREMIUM_READING_V2_ENABLED": "1"}
        if pin is not None:
            env["PRINCESS_EXPECTED_PREMIUM_READING_MANIFEST_SHA256"] = pin
        with pytest.raises(InvalidInput):
            resolve_report_reading_runtime(env, reviewed_reading_manifest=approved)
    for bad in ({**approved, "does_not_activate_base_pack": False},
                {**approved, "reading_pack_version": "premium-reading/3"},
                {**approved, "runtime_activation": "true"}):
        with pytest.raises(InvalidInput):
            resolve_report_reading_runtime({
                "PRINCESS_PREMIUM_READING_V2_ENABLED": "1",
                "PRINCESS_EXPECTED_PREMIUM_READING_MANIFEST_SHA256": _digest(bad),
            }, reviewed_reading_manifest=bad)
    result = resolve_report_reading_runtime({
        "PRINCESS_PREMIUM_READING_V2_ENABLED": "1",
        "PRINCESS_EXPECTED_PREMIUM_READING_MANIFEST_SHA256": _digest(approved),
    }, reviewed_reading_manifest=approved)
    assert result.premium_v2_enabled is True
    assert result.story_writer_enabled is False
    assert result.writer_template == LEGACY_WRITER
    assert result.reading_manifest_sha256 == _digest(approved)
