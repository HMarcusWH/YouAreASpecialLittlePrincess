"""Offline regression tests for the documentation graph and navigation tooling."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import plan_tools


def task(task_id, depends=(), status="PLANNED"):
    record = {
        "id": task_id, "title": "Fixture task", "status": status,
        "depends_on": list(depends), "owner_role": "test", "milestone": "test",
        "platforms": ["shared"], "connectors": [], "required_docs": ["ROADMAP.md"],
        "owned_paths": ["planned/"], "coding_steps": ["Implement fixture"],
        "contract_handoff": "Fixture contract", "acceptance": ["Pass"],
        "negative_tests": ["Reject invalid input"], "artifacts": ["Fixture"],
        "production_gates": [], "validation_profiles": ["docs"], "rollback": ["Revert fixture"],
    }
    if status == "DONE":
        record["completion_evidence"] = "fixture evidence"
    elif status == "IN_PROGRESS":
        record["implementation_evidence"] = "fixture implementation"
        record["remaining_work"] = ["Finish fixture integration"]
    elif status == "IMPLEMENTED_PENDING_REVIEW":
        record["implementation_evidence"] = "fixture implementation"
        record["remaining_work"] = ["Complete fixture review"]
    return record


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

    def test_repository_graph_decouples_presentation_from_empirical_calibration(self):
        data = json.loads((Path(__file__).with_name("tasks.json")).read_text(encoding="utf-8"))
        by_id = {task["id"]: task for task in data["tasks"]}

        self.assertEqual(by_id["T08A"]["depends_on"], ["T01", "T05", "T09"])
        self.assertEqual(by_id["T08"]["depends_on"], ["T06", "T08A"])
        self.assertIn("T08A", by_id["T17"]["depends_on"])
        self.assertEqual(by_id["T18"]["depends_on"], ["T08A", "T09"])
        self.assertEqual(by_id["T13"]["depends_on"], ["T08", "T12"])

        if by_id["T08A"]["status"] == "PLANNED":
            self.assertIn("T08A", [task["id"] for task in plan_tools.ready_tasks(data)])
        self.assertEqual(plan_tools.validate_plan(data), [])

    def test_active_tasks_are_distinct_from_ready_work(self):
        data = plan()
        data["tasks"][1] = task("T00A", ["T00"], status="IN_PROGRESS")
        data["tasks"][2] = task("T01", ["T00A"], status="IMPLEMENTED_PENDING_REVIEW")
        self.assertEqual([t["id"] for t in plan_tools.active_tasks(data)], ["T00A", "T01"])
        self.assertEqual(plan_tools.ready_tasks(data), [])

    def test_partial_status_evidence_rules(self):
        data = plan()
        data["tasks"][1]["status"] = "IN_PROGRESS"
        errors = "\n".join(plan_tools.validate_plan(data))
        self.assertIn("IN_PROGRESS requires nonempty remaining_work", errors)
        data["tasks"][1]["remaining_work"] = ["finish"]
        self.assertEqual(plan_tools.validate_plan(data), [])

        data = plan()
        data["tasks"][1]["status"] = "IMPLEMENTED_PENDING_REVIEW"
        data["tasks"][1]["remaining_work"] = ["review"]
        errors = "\n".join(plan_tools.validate_plan(data))
        self.assertIn("requires implementation_evidence", errors)
        data["tasks"][1]["implementation_evidence"] = "implemented"
        self.assertEqual(plan_tools.validate_plan(data), [])

        data = plan()
        data["tasks"][0]["remaining_work"] = ["should not remain"]
        errors = "\n".join(plan_tools.validate_plan(data))
        self.assertIn("DONE cannot have remaining_work", errors)

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

    def test_done_requires_done_predecessors(self):
        data = plan()
        data["tasks"][2]["status"] = "DONE"
        data["tasks"][2]["completion_evidence"] = "reviewed evidence"
        errors = "\n".join(plan_tools.validate_plan(data))
        self.assertIn("DONE with unfinished predecessors", errors)
        data["tasks"][1]["status"] = "DONE"
        data["tasks"][1]["completion_evidence"] = "reviewed evidence"
        self.assertEqual(plan_tools.validate_plan(data), [])

    def test_done_requires_completion_evidence(self):
        data = plan()
        data["tasks"][1]["status"] = "DONE"
        errors = "\n".join(plan_tools.validate_plan(data))
        self.assertIn("DONE requires nonempty completion_evidence", errors)
        data["tasks"][1]["completion_evidence"] = "reviewed exact-head evidence"
        self.assertEqual(plan_tools.validate_plan(data), [])

    def test_connector_requires_canonical_spec(self):
        data = plan()
        data["tasks"][0]["connectors"] = ["ObjectStore"]
        errors = "\n".join(plan_tools.validate_plan(data))
        self.assertIn("connector ObjectStore requires canonical spec", errors)
        data["tasks"][0]["required_docs"].append("docs/connectors/object-storage.md")
        self.assertEqual(plan_tools.validate_plan(data), [])

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

    def test_required_markdown_outside_standard_folders_is_link_checked(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            required = root / "docs/ci/required.md"
            required.parent.mkdir(parents=True)
            required.write_text("[broken](missing.md)\n", encoding="utf-8")
            data = plan()
            data["tasks"][0]["required_docs"] = ["docs/ci/required.md"]
            paths = plan_tools.markdown_paths(root, data)
            self.assertIn(required, paths)
            self.assertTrue(plan_tools.validate_links(root, paths))

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
