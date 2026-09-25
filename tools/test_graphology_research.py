"""Offline regression tests for the supporting-materials importer only."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import check_graphology_research as checker

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "research/graphology/foundations-v0.1"
FEATURES = Path(os.environ.get("GRAPHOLOGY_FEATURE_SCHEMA", str(REPO / "schema/graphology_feature_database_v1.json")))


class ResearchImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "snapshot"
        shutil.copytree(ROOT, self.root)

    def mutate(self, path, callback):
        p = self.root / path
        value = checker.load(p)
        callback(value)
        p.write_bytes(checker.encoded(value))

    def assert_failed_check(self, name):
        report, _ = checker.validate(self.root, FEATURES)
        self.assertEqual(report["status"], "FAIL")
        matches = [c for c in report["checks"] if c["check"] == name]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["result"], "FAIL")

    def test_originals_reconstruct(self):
        report, originals = checker.validate(self.root, FEATURES)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(originals), 7)
        self.assertEqual(report["counts"]["questions"], 89)

    def test_unknown_feature(self):
        self.mutate("blueprint/questions/01-context.json", lambda x: x[0]["related_canonical_feature_ids"].append("FAKE_FEATURE"))
        self.assert_failed_check("Canonical feature references resolve")

    def test_invalid_draft_promotion(self):
        self.mutate("blueprint/questions/01-context.json", lambda x: x[0].update(status="ACTIVE"))
        self.assert_failed_check("All questions draft")

    def test_readonly_owner_cannot_be_model_answer(self):
        self.mutate("blueprint/questions/01-context.json", lambda x: x[0].update(model_call_role="ANSWER"))
        self.assert_failed_check("Non-model questions read-only")

    def test_new_numbers_disabled(self):
        self.mutate("blueprint/metadata.json", lambda x: x["soft_field_definitions"][0].update(allow_new_numbers=True))
        self.assert_failed_check("Soft fields forbid new numbers")

    def test_altered_source_bytes(self):
        with (self.root / "graphology_foundations.md").open("ab") as f:
            f.write(b"\nChanged source\n")
        self.assert_failed_check("Original artifact SHA-256: graphology_foundations.md")

    def test_duplicate_json_keys(self):
        p = Path(self.tmp.name) / "bad.json"
        p.write_text('{"x": 1, "x": 2}', encoding="utf-8")
        with self.assertRaises(ValueError):
            checker.load(p)

    def test_nonfinite_json(self):
        p = Path(self.tmp.name) / "bad.json"
        p.write_text('{"x": NaN}', encoding="utf-8")
        with self.assertRaises(ValueError):
            checker.load(p)

    def test_path_escape(self):
        with self.assertRaises(ValueError):
            checker.safe_path(self.root, "../outside.json")

    def test_reordered_questions(self):
        self.mutate("blueprint/questions/01-context.json", lambda x: x.reverse())
        with self.assertRaises(ValueError):
            checker.reconstruct(self.root, checker.load(self.root / "provenance/import_manifest.json"))

    def test_cli_export_and_no_overwrite(self):
        output = Path(self.tmp.name) / "export"
        cmd = [sys.executable, str(REPO / "tools/check_graphology_research.py"),
               "--root", str(self.root), "--feature-schema", str(FEATURES),
               "--assemble-dir", str(output)]
        first = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(len(list(output.iterdir())), 7)
        second = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertNotEqual(second.returncode, 0)


if __name__ == "__main__":
    unittest.main()
