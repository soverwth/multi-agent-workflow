import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from b01.plan_validator import validate_plan
from b01.task_planner import build_plan


class PlanValidatorTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan()

    def test_reference_plan_passes(self):
        report = validate_plan(self.plan)
        self.assertTrue(report.ok, report.reasons)
        self.assertEqual(report.covered_requirements, ["LR-01", "LR-02", "LR-03", "LR-04", "LR-05"])
        self.assertEqual(report.topological_order[0], "T01")

    def test_duplicate_output_is_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan["tasks"][1]["outputs"] = plan["tasks"][0]["outputs"]
        report = validate_plan(plan)
        self.assertFalse(report.ok)
        self.assertTrue(any("output has two owners" in reason for reason in report.reasons))

    def test_uncovered_requirement_is_rejected(self):
        plan = copy.deepcopy(self.plan)
        for task in plan["tasks"]:
            task["req_refs"] = [ref for ref in task["req_refs"] if ref != "LR-04"] or ["LR-01"]
        report = validate_plan(plan)
        self.assertFalse(report.ok)
        self.assertIn("uncovered requirement: LR-04", report.reasons)

    def test_cycle_is_rejected(self):
        plan = copy.deepcopy(self.plan)
        by_id = {task["task_id"]: task for task in plan["tasks"]}
        by_id["T01"]["depends_on"] = ["T11"]
        report = validate_plan(plan)
        self.assertFalse(report.ok)
        self.assertTrue(any("dependency cycle" in reason or "critical chain" in reason for reason in report.reasons))

    def test_t04_missing_required_test_is_rejected(self):
        plan = copy.deepcopy(self.plan)
        t04 = next(task for task in plan["tasks"] if task["task_id"] == "T04")
        t04["required_test_ids"] = ["TC-P01"]
        report = validate_plan(plan)
        self.assertFalse(report.ok)
        self.assertTrue(any("TC-P02" in reason for reason in report.reasons))

    def test_missing_standard_field_is_rejected(self):
        plan = copy.deepcopy(self.plan)
        del plan["tasks"][0]["escalation_target"]
        report = validate_plan(plan)
        self.assertFalse(report.ok)
        self.assertTrue(any("missing field escalation_target" in reason for reason in report.reasons))


if __name__ == "__main__":
    unittest.main()
