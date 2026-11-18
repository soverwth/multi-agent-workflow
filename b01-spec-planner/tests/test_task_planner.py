import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from b01.design import DESIGN_ENTRIES, REQUIRED_REQUIREMENTS
from b01.task_planner import build_plan, build_traceability, topological_sort


class TaskPlannerTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan()
        self.tasks = {task["task_id"]: task for task in self.plan["tasks"]}

    def test_generates_t01_to_t11(self):
        self.assertEqual(sorted(self.tasks), [f"T{i:02d}" for i in range(1, 12)])
        self.assertEqual(self.plan["required_requirements"], REQUIRED_REQUIREMENTS)

    def test_topological_order_respects_critical_chain(self):
        order = self.plan["topological_order"]
        for left, right in zip(("T01", "T02", "T03", "T04", "T05", "T10", "T11"), ("T02", "T03", "T04", "T05", "T10", "T11", None)):
            if right is None:
                continue
            self.assertLess(order.index(left), order.index(right))

    def test_outputs_have_single_owner(self):
        outputs = [output for task in self.plan["tasks"] for output in task["outputs"]]
        self.assertEqual(len(outputs), len(set(outputs)))

    def test_requirement_coverage(self):
        covered = {ref for task in self.plan["tasks"] for ref in task["req_refs"]}
        self.assertEqual(covered, set(REQUIRED_REQUIREMENTS))

    def test_t10_waits_for_t03_to_t09(self):
        self.assertEqual(
            set(self.tasks["T10"]["depends_on"]),
            {"T03", "T04", "T05", "T06", "T07", "T08", "T09"},
        )

    def test_t04_contains_required_lost_at_tests(self):
        self.assertTrue({"TC-P01", "TC-P02", "TC-P03"}.issubset(self.tasks["T04"]["required_test_ids"]))

    def test_traceability_includes_b03_entries(self):
        trace = build_traceability(self.plan)
        by_id = {item["design_id"]: item for item in trace["items"]}
        self.assertEqual(len(trace["items"]), len(DESIGN_ENTRIES))
        self.assertIn("T02", by_id["DS-B03-01"]["task_refs"])
        self.assertIn("T04", by_id["DS-LOST-01"]["task_refs"])

    def test_topological_sort_rejects_cycle(self):
        tasks = [
            {"task_id": "A", "depends_on": ["B"]},
            {"task_id": "B", "depends_on": ["A"]},
        ]
        with self.assertRaises(ValueError):
            topological_sort(tasks)


if __name__ == "__main__":
    unittest.main()
