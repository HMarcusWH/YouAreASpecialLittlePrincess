"""Offline regression tests for the documentation graph and navigation tooling."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import plan_tools


def task(task_id, depends=(), status="PLANNED"):
    return {
        "id": task_id, "title": "Fixture task", "status": status,
        "depends_on": list(depends), "owner_role": "test", "milestone": "test",
        "platforms": ["shared"], "connectors": [], "required_docs": ["ROADMAP.md"],
        "owned_paths": ["planned/"], "coding_steps": ["Implement fixture"],
        "contract_handoff": "Fixture contract", "acceptance": ["Pass"],
        "negative_tests": ["Reject invalid input"], "artifacts": ["Fixture"],
        "production_gates": [], "validation_profiles": ["docs"], "rollback": ["Revert fixture"],
    }


def plan():
    return {
        "plan_version": "2.0", "baseline_commit": "fixture", "gate_registry": {},
        "validation_profiles": {"docs": {"state": "TO_IMPLEMENT", "commands": [], "description": "fixture"}},
        "tasks": [task("T00", status="DONE"), task("T00A", ["T00"]), task("T01", ["T00A"])],
    }


class PlanTests(unittest.TestCase):
    def test_valid_graph_and_derived_readiness(self):
        data = plan()
        self.assertEqual(plan_tools.validate_plan(data), [])
        self.assertEqual([t["id"] for t in plan_tools.ready_tasks(data)], ["T00A"])

    def test_duplicate_and_unknown_predecessor_rejected(self):
        data = plan()
        data["tasks"].append(deepcopy(data["tasks"][0]))
        data["tasks"][1]["depends_on"] = ["T99"]
        errors = "\n".join(plan_tools.validate_plan(data))
        self.assertIn("duplicate task ID", errors)
        self.assertIn("unknown predecessor", errors)

    def test_cycle_rejected(self):
        data = plan()
        data["tasks"][0]["depends_on"] = ["T01"]
        self.assertTrue(any("cycle" in error for error in plan_tools.validate_plan(data)))

    def test_stored_ready_and_fake_existing_command_rejected(self):
        data = plan()
        data["tasks"][1]["status"] = "READY"
        data["validation_profiles"]["docs"]["commands"] = ["imaginary-test"]
        errors = "\n".join(plan_tools.validate_plan(data))
        self.assertIn("READY must be computed", errors)
        self.assertIn("planned suite", errors)

    def test_required_documents_are_checked_but_owned_paths_are_planned(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(any("required document" in e for e in plan_tools.validate_plan(plan(), root)))
            (root / "ROADMAP.md").write_text("# Plan\n", encoding="utf-8")
            self.assertEqual(plan_tools.validate_plan(plan(), root), [])

    def test_rendering_is_deterministic_and_keeps_task_anchors(self):
        data = plan()
        text = plan_tools.render_backlog(data)
        self.assertEqual(text, plan_tools.render_backlog(deepcopy(data)))
        self.assertIn('<a id="t00a"></a>', text)
        self.assertIn("Required failure and regression cases", text)
        self.assertIn("TO_IMPLEMENT", text)

    def test_local_links_and_fragments(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            page = root / "a.md"
            target = root / "b.md"
            target.write_text('# Target\n<a id="task"></a>\n', encoding="utf-8")
            page.write_text("[good](b.md#task)\n[remote](https://example.com)\n", encoding="utf-8")
            self.assertEqual(plan_tools.validate_links(root, [page]), [])
            page.write_text("[bad](b.md#missing)\n[absent](gone.md)\n", encoding="utf-8")
            self.assertEqual(len(plan_tools.validate_links(root, [page])), 2)

    def test_fenced_examples_do_not_create_links(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            page = root / "a.md"
            page.write_text("```text\n[planned](does-not-exist.md)\n```\n", encoding="utf-8")
            self.assertEqual(plan_tools.validate_links(root, [page]), [])

    def test_no_path_escape(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            page = root / "a.md"
            page.write_text("[escape](../outside.md)\n", encoding="utf-8")
            self.assertTrue(plan_tools.validate_links(root, [page]))


if __name__ == "__main__":
    unittest.main()
