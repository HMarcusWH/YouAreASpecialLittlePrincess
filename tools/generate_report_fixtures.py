#!/usr/bin/env python3
"""Generate shared report fixtures for web, native, PDF and share-card consumers.

``--capture`` runs the engine once on a synthetic, programmatically drawn page
(no human handwriting) and stores its result, evidence payload and analysis
reference under ``fixtures/reports/source``. Assembly and projections are
pure, so the default/``--check`` modes regenerate every output from those
sources without numpy/OpenCV version drift.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from princess_app.domain.analysis import analysis_reference  # noqa: E402
from princess_app.domain.evidence import build_evidence_bundle, map_point, prepend_source_frame  # noqa: E402
from princess_app.domain.reports import (  # noqa: E402
    HIGHLIGHT_TEMPLATE_VERSION,
    PremiumAccess,
    PremiumAuthorization,
    ProjectionRequest,
    assemble_report,
    project_report,
    revise_report,
)

FIXTURES = ROOT / "fixtures" / "reports"
SOURCE = FIXTURES / "source"
CREATED = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
OWNER_ACTIONS = {"COMPARE": None, "EXPORT": None, "SHARE": None, "SAVE": None, "DELETE": None,
                 "PURCHASE": "premium_not_yet_available"}
SYNTHETIC_LINES = ("the quick brown fox jumps", "over a very lazy dog", "writing sample fixture")


def dump(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def capture() -> None:
    import cv2
    import numpy as np

    from princess_graphology import GraphologyEngine, __version__

    image = np.full((360, 900), 245, np.uint8)
    for i, text in enumerate(SYNTHETIC_LINES):
        cv2.putText(image, text, (30, 90 + i * 100), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 1.6, 25, 3, cv2.LINE_AA)
    matrix = cv2.getRotationMatrix2D((450, 180), 3, 1.0)
    image = cv2.warpAffine(image, matrix, (900, 360), borderValue=245)
    result, payload = GraphologyEngine(max_dimension=700).analyze_with_evidence(image, source="synthetic-fixture")
    digest = hashlib.sha256(image.tobytes()).hexdigest()
    reference = analysis_reference(
        analysis_id="analysis_fixture_1", run_id="run_fixture_1", owner_id="owner_fixture_1",
        input_asset_id="asset_fixture_1", input_sha256=digest,
        processed_sha256=result.metadata["input_pixels_sha256"], created_at=CREATED,
        engine_version=__version__, analysis_config_sha256=hashlib.sha256(b"max_dimension=700").hexdigest())
    SOURCE.mkdir(parents=True, exist_ok=True)
    (SOURCE / "engine-result.synthetic.json").write_text(dump(result.to_dict()), encoding="utf-8")
    (SOURCE / "evidence-payload.synthetic.json").write_text(dump(payload), encoding="utf-8")
    (SOURCE / "analysis-reference.synthetic.json").write_text(dump(reference), encoding="utf-8")


def load(name: str):
    return json.loads((SOURCE / name).read_text(encoding="utf-8"))


def build() -> dict[str, str]:
    result = load("engine-result.synthetic.json")
    payload = load("evidence-payload.synthetic.json")
    reference = load("analysis-reference.synthetic.json")

    def need(outcome, what):
        if outcome.value is None:
            raise SystemExit(f"{what} failed: {[i.code for i in outcome.issues][:5]}")
        return outcome.value

    evidence = need(build_evidence_bundle(payload, reference, "evidence_fixture_1"), "evidence bundle")
    report = need(assemble_report(report_id="report_fixture_1", analysis=reference, result=result,
                                  created_at=CREATED, locale="sv-SE", evidence=evidence), "report")
    premium = need(revise_report(report, created_at=CREATED.replace(hour=13), premium_overlay_id="overlay_fixture_1"),
                   "premium revision")
    highlight_reference = json.loads(json.dumps(reference))
    highlight_reference["versions"]["template"] = HIGHLIGHT_TEMPLATE_VERSION
    highlight_report = need(assemble_report(
        report_id="report_fixture_highlight", analysis=highlight_reference, result=result,
        created_at=CREATED, locale="sv-SE", evidence=None,
    ), "highlight report")
    UNLOCKED = PremiumAuthorization("report_fixture_1", "overlay_fixture_1", PremiumAccess.UNLOCKED)
    views = {
        "view.free.json": (report, ProjectionRequest("FREE", CREATED, actions=OWNER_ACTIONS)),
        "view.owner-premium.json": (premium, ProjectionRequest(
            "OWNER", CREATED, premium=UNLOCKED,
            actions={**OWNER_ACTIONS, "PURCHASE": "already_unlocked"})),
        "view.share.json": (premium, ProjectionRequest(
            "SHARE", CREATED, premium=UNLOCKED,
            share_scope=frozenset({"section.slant", "section.baseline"}))),
        "view.export-no-image.json": (report, ProjectionRequest("EXPORT", CREATED, include_source_image=False)),
        "view.owner-image-revoked.json": (report, ProjectionRequest(
            "OWNER", CREATED, source_image_available=False, actions=OWNER_ACTIONS)),
    }
    homography = [1.02, 0.03, 15.0, -0.01, 0.98, 40.0, 0.00002, 0.00001, 1.0]
    frames = prepend_source_frame(evidence.to_dict()["frames"], frame_id="frame_upload", width=1600, height=900,
                                  root_to_new_parent=homography)
    probes = [[0.0, 0.0], [123.0, 77.0], [650.5, 20.25]]
    parity = {
        "frames": frames,
        "cases": [{"from": "frame_analysis", "to": to, "point": point,
                   "expected": list(map_point(frames, "frame_analysis", to, *point))}
                  for to in ("frame_input", "frame_upload") for point in probes],
    }
    outputs = {
        "frame-parity.json": dump(parity),
        "evidence-bundle.json": dump(evidence.to_dict()),
        "report-document.json": dump(report.to_dict()),
        "report-document.premium.json": dump(premium.to_dict()),
        "report-document.highlight.json": dump(highlight_report.to_dict()),
        "view.highlight.json": dump(need(project_report(
            highlight_report, ProjectionRequest("FREE", CREATED, actions=OWNER_ACTIONS)
        ), "highlight view").to_dict()),
    }
    for name, (source, request) in views.items():
        outputs[name] = dump(need(project_report(source, request), name).to_dict())
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated fixtures are stale")
    parser.add_argument("--capture", action="store_true", help="re-run the engine to refresh source inputs")
    args = parser.parse_args()
    if args.capture:
        capture()
    outputs = build()
    stale = [name for name, text in outputs.items()
             if not (FIXTURES / name).is_file() or (FIXTURES / name).read_text(encoding="utf-8") != text]
    if args.check:
        if stale:
            print("stale report fixtures: " + ", ".join(stale))
            return 1
        print(f"PASS: {len(outputs)} report fixtures are current")
        return 0
    for name, text in outputs.items():
        (FIXTURES / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(outputs)} report fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
