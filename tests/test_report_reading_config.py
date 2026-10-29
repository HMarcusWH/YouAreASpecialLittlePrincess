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


def story_env(**updates):
    from princess_app.domain.content.reading import reviewed_reading_sha256

    setting = {
        "PRINCESS_ENV": "local",
        "PRINCESS_REPORT_STORY_V2_ENABLED": "1",
        "PRINCESS_EXPECTED_REPORT_TEMPLATE_VERSION": STORY_WRITER,
        "PRINCESS_EXPECTED_FREE_READING_REGISTRY_SHA256": reviewed_reading_sha256(),
    }
    setting.update(updates)
    return setting


def source_authority(settings):
    from princess_app.config_reports import resolve_free_story_source

    runtime = resolve_report_reading_runtime(settings, reviewed_reading_manifest=INACTIVE_MANIFEST)
    return resolve_free_story_source(settings, report_runtime=runtime)


def test_private_r2_story_policy_binds_exact_reviewed_source_without_premium():
    from princess_app.domain.reports.story import CHAPTER_ORDER
    from princess_app.domain.content.reading import reviewed_reading_sha256

    for environment in ("local", "test"):
        source = source_authority(story_env(PRINCESS_ENV=environment))
        assert source.sha256 == reviewed_reading_sha256()
        assert tuple(c.section_id for c in source.policy.chapters) == CHAPTER_ORDER
        assert len(source.policy.relation_registry["relations"]) == 6
        assert source.policy.presentation_version == "presentation/2"
        assert source.policy.partial_overview_content_id == "content.reading.v2.state.partial"
    assert source_authority({"PRINCESS_ENV": "test"}) is None
    assert source_authority({
        "PRINCESS_ENV": "test",
        "PRINCESS_EXPECTED_FREE_READING_REGISTRY_SHA256": reviewed_reading_sha256(),
    }) is None


@pytest.mark.parametrize("invalid", (
    {},
    {"PRINCESS_EXPECTED_FREE_READING_REGISTRY_SHA256": ""},
    {"PRINCESS_EXPECTED_FREE_READING_REGISTRY_SHA256": "0" * 64},
    {"PRINCESS_EXPECTED_FREE_READING_REGISTRY_SHA256": "A" * 64},
    {"PRINCESS_ENV": "production"},
    {"PRINCESS_ENV": "staging"},
    {"PRINCESS_ENV": "preview"},
    {"PRINCESS_ENV": "test", "PRINCESS_TEST_PUBLIC_GUEST_ONLY": "1"},
    {"PRINCESS_EVIDENCE_SUPPORT_RESEARCH_OPT_IN": "1"},
))
def test_private_story_startup_rejects_missing_foreign_or_public_authority(invalid):
    from princess_app.config_reports import FREE_SOURCE_PIN_ENV

    settings = story_env()
    settings.update(invalid)
    if not invalid:
        del settings[FREE_SOURCE_PIN_ENV]
    with pytest.raises(InvalidInput, match="report_story_"):
        source_authority(settings)


def test_private_story_startup_refuses_corrupted_baked_registry(monkeypatch):
    from princess_app.domain.content import reading

    monkeypatch.setattr(reading, "_READING_SHA256", "0" * 64)
    reading._load_reading_registry.cache_clear()
    try:
        with pytest.raises(InvalidInput, match="report_story_source_invalid"):
            source_authority({
                "PRINCESS_ENV": "local",
                "PRINCESS_REPORT_STORY_V2_ENABLED": "1",
                "PRINCESS_EXPECTED_REPORT_TEMPLATE_VERSION": STORY_WRITER,
                "PRINCESS_EXPECTED_FREE_READING_REGISTRY_SHA256": "0" * 64,
            })
    finally:
        reading._load_reading_registry.cache_clear()


def test_private_guarded_story_candidate_requires_both_research_pins():
    """Independent /4, qualified-v2 and v5 pins are necessary, never public."""
    from princess_app.application.intake import analysis_config_sha256

    digest = analysis_config_sha256(grid_profile="qualified-v2", evidence_guard_enabled=True)
    settings = story_env(
        PRINCESS_ENV="test", PRINCESS_COMPONENT="api",
        PRINCESS_ANALYSIS_PROFILE="qualified-v2",
        PRINCESS_SEGMENTATION_V2_RESEARCH_OPT_IN="1",
        PRINCESS_EVIDENCE_SUPPORT_RESEARCH_OPT_IN="1",
        PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256=digest,
    )
    source = source_authority(settings)
    assert source.private_qualified_candidate is True
    assert source.policy.presentation_version == "presentation/2"
    for change in (
        {"PRINCESS_ANALYSIS_PROFILE": "legacy"},
        {"PRINCESS_SEGMENTATION_V2_RESEARCH_OPT_IN": "0"},
        {"PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256": "f" * 64},
        {"PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256": ""},
        {"PRINCESS_ENV": "staging"},
        {"PRINCESS_ENV": "production"},
        {"PRINCESS_TEST_PUBLIC_GUEST_ONLY": "1"},
    ):
        with pytest.raises(InvalidInput, match="report_story_"):
            source_authority({**settings, **change})


def test_private_guarded_story_worker_claims_only_exact_v4_candidate():
    """A guarded /4 worker may claim only matching saved /4 configuration."""
    from datetime import datetime, timezone
    from princess_app.adapters.fakes import FakeClock
    from princess_app.application.analysis_worker import AnalysisWorker
    from princess_app.application.intake import analysis_config_sha256
    from princess_app.domain.content.reading import reviewed_reading_sha256
    from princess_app.domain.reports.story import story_policy_from_reviewed_reading
    from princess_graphology import GraphologyEngine

    digest = analysis_config_sha256(grid_profile="qualified-v2", evidence_guard_enabled=True)
    engine = GraphologyEngine(grid_profile="qualified-v2", evidence_guard_enabled=True)
    policy = story_policy_from_reviewed_reading()
    source_sha = reviewed_reading_sha256()
    clock = FakeClock(datetime(2026, 10, 29, tzinfo=timezone.utc))

    class ClaimRecorder:
        def __init__(self):
            self.claims = []

        def claim(self, _worker_id, _lease, _now, **kwargs):
            self.claims.append(kwargs)
            return None

    queue = ClaimRecorder()
    arguments = dict(
        queue=queue, store=None, decode=None, engine=engine, clock=clock,
        context=lambda: None, worker_id="issue92-synthetic-claim",
        engine_version="0.1.0", writer_template=STORY_WRITER,
        story_policy=policy, story_source_sha256=source_sha,
    )
    with pytest.raises(InvalidInput, match="report_story_research_guard_conflict"):
        AnalysisWorker(**arguments)
    worker = AnalysisWorker(**arguments, private_qualified_story_candidate=True)
    assert worker.run_once() is None
    assert queue.claims == [{
        "report_template": STORY_WRITER,
        "analysis_config": digest,
        "story_source_sha256": source_sha,
    }]
    with pytest.raises(InvalidInput, match="report_story_candidate_invalid"):
        AnalysisWorker(**{**arguments, "engine": GraphologyEngine()},
                       private_qualified_story_candidate=True)
