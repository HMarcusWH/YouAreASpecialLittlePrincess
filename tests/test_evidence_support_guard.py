"""Synthetic image-only opt-in guard: no handwriting rights, AI, or real-person data."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from princess_app.application.intake import (analysis_config_sha256, engine_config_sha256, resolve_analysis_runtime)
from princess_app.domain.analysis import analysis_reference
from princess_app.domain.content.presentation import feature_label
from princess_app.domain.evidence import build_evidence_bundle
from princess_app.domain.reports import assemble_report
from princess_app.domain.reports.template import EVIDENCE_SUPPORT_TEMPLATE_VERSION
from princess_graphology import GraphologyEngine
from princess_graphology.evidence_support import support_warning
from princess_graphology.models import Box


def synthetic_paper(kind: str) -> np.ndarray:
    image = np.full((800, 640, 3), 248, dtype=np.uint8)
    if kind in ("lined", "grid"):
        for y in range(45, 790, 96):
            cv2.line(image, (0, y), (639, y), (210, 190, 170), 2)
    if kind == "grid":
        for x in range(35, 630, 63):
            cv2.line(image, (x, 0), (x, 799), (210, 190, 170), 2)
    if kind == "text":
        for i, txt in enumerate(("Alpha Beta Gamma", "Delta Zeta Eta", "Theta Iota Kappa", "Mu Nu Omicron")):
            cv2.putText(image, txt, (45, 120 + i * 146), cv2.FONT_HERSHEY_SIMPLEX,
                        0.85, (20, 24, 32), 2, cv2.LINE_AA)
    return image


def _run(image, *, profile="legacy", guard=True):
    return GraphologyEngine(grid_profile=profile, evidence_guard_enabled=guard).analyze_with_evidence(image)


def test_opt_in_is_independent_and_changes_source_configuration_identity():
    reference = analysis_config_sha256()
    off = GraphologyEngine()
    on = GraphologyEngine(evidence_guard_enabled=True)
    assert off.evidence_guard_enabled is False
    assert engine_config_sha256(off) == reference
    assert engine_config_sha256(on) == analysis_config_sha256(evidence_guard_enabled=True)
    assert engine_config_sha256(on) != reference
    for profile in ("legacy", "grid-v1", "qualified-v2"):
        assert (analysis_config_sha256(grid_profile=profile, evidence_guard_enabled=True)
                != analysis_config_sha256(grid_profile=profile))
    with pytest.raises(ValueError, match="boolean"):
        GraphologyEngine(evidence_guard_enabled=1)


def test_excessively_long_thin_ruling_abstains_instead_of_reporting_fake_lines():
    image = synthetic_paper("lined")
    original = GraphologyEngine().analyze(image)
    assert original.measurements['PAGE_LINE_COUNT'].raw_value >= 4
    repaired, evidence = _run(image)
    measurements = repaired.measurements
    exact = {'IMG_WIDTH_PX', 'IMG_HEIGHT_PX', 'IMG_MEGAPIXELS', 'IMG_ASPECT_RATIO'}
    assert set(measurements) and len(measurements) == 64
    assert {key for key, value in measurements.items() if value.raw_value is not None} == exact
    assert all(measurements[key].raw_value is None for key in ('PAGE_LINE_COUNT', 'PAGE_WORD_COUNT',
                                                               'LINE_SPACING_CV', 'PAGE_HORIZONTAL_DENSITY'))
    assert all(measurements[key].missing_reason == 'dominant_thin_page_ruling'
               for key in ('PAGE_LINE_COUNT', 'PAGE_WORD_COUNT', 'LINE_SPACING_CV'))
    assert [(r.region_id, r.scope) for r in repaired.regions] == [('page_0', 'PAGE')]
    assert len(evidence['observations']) == 0
    assert {r['scope'] for r in evidence['regions']} == {'PAGE'}


def test_one_page_spanning_nontext_contour_abstains():
    fake = SimpleNamespace(width=640, height=800, original_width=640, original_height=800,
                           lines=[Box(0, 0, 640, 800)], words=[], components=[Box(0, 0, 640, 800)],
                           x_height_px=None)
    assert support_warning(fake) == 'page_spanning_nontext_artifact'


def test_low_resolution_sparse_layout_abstains_without_claiming_empty():
    fake = SimpleNamespace(width=400, height=520, original_width=400, original_height=520,
                           lines=[Box(50, 150, 180, 12), Box(80, 270, 160, 12), Box(70, 390, 140, 12)],
                           words=[Box(50, 150, 180, 12)] * 5,
                           components=[Box(50, 150, 180, 12)] * 5,
                           x_height_px=None)
    assert support_warning(fake) == 'low_resolution_structure_collapsed'
    fake.original_width, fake.original_height = 1600, 2000
    assert support_warning(fake) is None
    fake.original_width, fake.original_height = 400, 520
    fake.components = [Box(i, 200, 7, 12) for i in range(15)]
    assert support_warning(fake) is None


def test_regular_synthetic_text_keeps_word_line_region_evidence_and_facts():
    raw = synthetic_paper('text')
    baseline = GraphologyEngine().analyze(raw)
    guarded, evidence = _run(raw)
    assert guarded.metadata.get('evidence_support') is None
    assert guarded.to_dict()['measurements'] == baseline.to_dict()['measurements']
    assert guarded.to_dict()['regions'] == baseline.to_dict()['regions']
    assert len(guarded.regions) > 1
    assert any(item['scope'] == 'LINE' for item in evidence['regions'])


def test_qualified_original_input_policy_stays_off_by_default():
    assert feature_label('PAGE_WORD_COUNT', 'en') == 'Detected geometric word groups'
    assert feature_label('PAGE_WORD_COUNT', 'sv-SE') == 'Upptäckta geometriska ordgrupper'


def test_repaired_report_and_evidence_compile_without_any_false_highlights():
    image = synthetic_paper('lined')
    engine = GraphologyEngine(evidence_guard_enabled=True)
    result, evidence = engine.analyze_with_evidence(image, source='synthetic-ruling')
    raw = result.to_dict()
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    ref = analysis_reference(
        analysis_id='analysis_synthetic_guard', run_id='run_synthetic_guard',
        owner_id='owner_synthetic_guard', input_asset_id='asset_synthetic_guard',
        input_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
        processed_sha256=raw['metadata']['input_pixels_sha256'], created_at=now,
        engine_version='0.1.0', analysis_config_sha256=engine_config_sha256(engine),
        template=EVIDENCE_SUPPORT_TEMPLATE_VERSION,
    )
    bundle = build_evidence_bundle(evidence, ref, 'bundle_synthetic_guard')
    assert bundle.ok, bundle.issues
    assembled = assemble_report(
        report_id='report_synthetic_guard', analysis=ref, result=raw,
        created_at=now, locale='en', evidence=bundle.value,
    )
    assert assembled.ok, assembled.issues
    report = assembled.value.to_dict()
    assert len(report['facts']) == 64
    assert sum(f['value'] is not None for f in report['facts']) == 4
    assert next(s for s in report['sections'] if s['section_id'] == 'section.sample')['availability'] == 'INELIGIBLE'
    assert [s['content_ids'] for s in report['sections'] if s['section_id'].startswith('section.highlight.')] == [
        ['content.highlight.v1.none']
    ]


def test_explicit_local_research_guard_requires_paired_digest_and_is_rejected_in_public():
    digest = analysis_config_sha256(evidence_guard_enabled=True)
    local = {"PRINCESS_ENV": "local", "PRINCESS_COMPONENT": "analysis_worker",
             "PRINCESS_EVIDENCE_SUPPORT_RESEARCH_OPT_IN": "1",
             "PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256": digest}
    resolved = resolve_analysis_runtime(local)
    assert (resolved.profile, resolved.digest, resolved.evidence_guard_enabled) == ("legacy", digest, True)
    assert resolve_analysis_runtime({}).evidence_guard_enabled is False
    for changed in ({**local, "PRINCESS_ENV": "production"},
                    {**local, "PRINCESS_ENV": "staging"},
                    {**local, "PRINCESS_TEST_PUBLIC_GUEST_ONLY": "1"},
                    {**local, "PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256": analysis_config_sha256()},
                    {k: v for k, v in local.items() if k != "PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256"},
                    {**local, "PRINCESS_EVIDENCE_SUPPORT_RESEARCH_OPT_IN": "true"}):
        with pytest.raises(ValueError):
            resolve_analysis_runtime(changed)


def test_report_template_v2_and_v3_have_distinct_blank_suitability_semantics():
    from princess_app.domain.reports.assembly import build_sections, facts_from_result
    from princess_app.domain.reports.template import HIGHLIGHT_TEMPLATE_VERSION

    sample = GraphologyEngine().analyze(np.full((80, 120), 255, np.uint8)).to_dict()
    facts, issues = facts_from_result(sample)
    assert not issues
    def sample_availability(template):
        sections = build_sections(facts, reference_claims=(), premium_overlay_id=None,
                                  template_version=template)
        return next(s["availability"] for s in sections if s["section_id"] == "section.sample")
    assert sample_availability(HIGHLIGHT_TEMPLATE_VERSION) == "READY"  # immutable historical /2
    assert sample_availability(EVIDENCE_SUPPORT_TEMPLATE_VERSION) == "INELIGIBLE"
