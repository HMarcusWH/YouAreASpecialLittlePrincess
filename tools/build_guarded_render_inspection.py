#!/usr/bin/env python3
"""Rights-safe real engine/report/projection inputs for PR #96 visual qualification.

This generates the actual guarded individual-report/3 from an artificial ruled
canvas; it is not a real writer and not scientific/real-photo qualification.
Outputs contain no writing pixels or private participant data.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from princess_app.application.intake import engine_config_sha256  # noqa: E402
from princess_app.domain.analysis import analysis_reference  # noqa: E402
from princess_app.domain.evidence import build_evidence_bundle  # noqa: E402
from princess_app.domain.reports import assemble_report, project_report  # noqa: E402
from princess_app.domain.reports.projection import ProjectionRequest  # noqa: E402
from princess_app.domain.reports.template import EVIDENCE_SUPPORT_TEMPLATE_VERSION  # noqa: E402
from princess_graphology import GraphologyEngine, __version__  # noqa: E402

OUT = ROOT / "apps/render/artifacts/t06-evidence-support-v3"
STAMP = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
EXACT = frozenset(("IMG_WIDTH_PX", "IMG_HEIGHT_PX", "IMG_MEGAPIXELS", "IMG_ASPECT_RATIO"))


def need(outcome, label: str):
    if outcome.value is None:
        raise RuntimeError(f"{label} failed: {[i.code for i in outcome.issues]}")
    return outcome.value


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    paper = np.full((800, 640, 3), 248, dtype=np.uint8)
    for y in range(45, 790, 96):
        cv2.line(paper, (0, y), (639, y), (210, 190, 170), 2)
    engine = GraphologyEngine(evidence_guard_enabled=True)
    result, payload = engine.analyze_with_evidence(paper, source="rights-safe synthetic ruling only")
    assert result.metadata["evidence_support"]["reason"] == "dominant_thin_page_ruling"
    assert len(result.measurements) == 64
    assert {fid for fid, row in result.measurements.items() if row.raw_value is not None} == EXACT
    assert [r.scope for r in result.regions] == ["PAGE"]
    assert payload["observations"] == []
    reference = analysis_reference(
        analysis_id="analysis_guard_inspection", run_id="run_guard_inspection",
        owner_id="owner_guard_inspection", input_asset_id="asset_guard_inspection",
        input_sha256=hashlib.sha256(paper.tobytes()).hexdigest(),
        processed_sha256=result.metadata["input_pixels_sha256"], created_at=STAMP,
        engine_version=__version__, analysis_config_sha256=engine_config_sha256(engine),
        template=EVIDENCE_SUPPORT_TEMPLATE_VERSION)
    evidence = need(build_evidence_bundle(payload, reference, "bundle_guard_inspection"), "evidence")
    report = need(assemble_report(
        report_id="report_guard_inspection", analysis=reference,
        result=result.to_dict(), created_at=STAMP, locale="en", evidence=evidence), "report")
    assert report.data["analysis"]["versions"]["template"] == EVIDENCE_SUPPORT_TEMPLATE_VERSION
    assert len(report.data["facts"]) == 64
    assert {f["feature_id"] for f in report.data["facts"] if f["value"] is not None} == EXACT
    assert next(s for s in report.data["sections"] if s["section_id"] == "section.sample")["availability"] == "INELIGIBLE"
    assert next(s for s in report.data["sections"] if s["section_id"] == "section.premium")["availability"] == "INELIGIBLE"
    assert any(n["localization_key"] == "notice.image_only" for n in report.data["notices"])
    owner = need(project_report(report, ProjectionRequest(
        "OWNER", STAMP, actions={"PURCHASE": None, "EXPORT": None})), "owner")
    assert all(action["kind"] != "PURCHASE" for action in owner.data["actions"])
    export = need(project_report(report, ProjectionRequest(
        "EXPORT", STAMP, include_source_image=False)), "export")
    share = need(project_report(report, ProjectionRequest(
        "SHARE", STAMP, source_image_available=False,
        share_scope=frozenset(("section.sample", "section.highlight.primary")))), "share")
    assert len(export.data["facts"]) == 64
    assert {f["feature_id"] for f in share.data["facts"] if f["value"] is not None} == EXACT
    assert not export.data["authorized_asset_ids"] and not share.data["authorized_asset_ids"]
    OUT.mkdir(parents=True, exist_ok=True)
    write(OUT / "report-document-v3.synthetic.json", report.to_dict())
    write(OUT / "view.owner-v3.synthetic.json", owner.to_dict())
    write(OUT / "view.export-v3.synthetic.json", export.to_dict())
    write(OUT / "view.share-v3.synthetic.json", share.to_dict())
    print("PASS: actual guarded v3 report, 64 canonical facts, four exact image facts, 60 missing")


if __name__ == "__main__":
    main()
