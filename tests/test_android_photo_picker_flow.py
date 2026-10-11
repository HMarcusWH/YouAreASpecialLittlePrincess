"""Regression contract for Android 36 system photo-picker selection.

CI failure #90: the system picker exposed a real clickable photo with the
accessibility label 'Photo taken on ...', but exposed no icon_thumbnail id.
Successful #80: a thumbnail resource id was present. Both remain supported.
"""
from pathlib import Path
import re


FLOW = (Path(__file__).resolve().parents[1] /
        "apps/mobile/e2e/maestro/pick-first-image.yaml").read_text(encoding="utf-8")
MAIN = (Path(__file__).resolve().parents[1] /
        "apps/mobile/e2e/maestro/free-to-queued.yaml").read_text(encoding="utf-8")


def test_picker_waits_for_semantic_screen_not_thumbnail_resource_id():
    assert "Photos|Albums|Recent|Browse|Photo taken on .*" in FLOW
    first_wait = FLOW.split("- extendedWaitUntil:", 1)[1].split("- runFlow:", 1)[0]
    assert "text:" in first_wait and "icon_thumbnail" not in first_wait
    assert "timeout: 60000" in first_wait


def test_photo_picker_keeps_id_paths_and_a_real_accessibility_fallback():
    assert "com\\\\.google\\\\.android\\\\.providers\\\\.media\\\\.module:id/icon_thumbnail" in FLOW
    assert "com\\\\.android\\\\.providers\\\\.media\\\\.module:id/icon_thumbnail" in FLOW
    assert "com\\\\.(google\\\\.)?android\\\\.documentsui:id/thumbnail" in FLOW
    assert re.search(r'when:\s+visible:\s+text: "Photo taken on \.\*"\s+commands:\s+- tapOn:\s+text: "Photo taken on \.\*"\s+index: 0', FLOW)
    assert FLOW.rindex('text: "Photo taken on .*"') > FLOW.rindex("id/thumbnail")
    assert "point:" not in FLOW and "optional: true" not in FLOW


def test_parent_flow_checks_photo_identity_after_picker_selection():
    assert "- runFlow: pick-first-image.yaml" in MAIN
    assert 'visible: "Analyse my handwriting"' in MAIN
    assert 'assertVisible: ".*900 × 360 px"' in MAIN
