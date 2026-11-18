import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from b01.baseline import BaselineError, register_baseline
from b01.design import C1_CONTRACT, R1, S1
from b01.task_planner import build_plan, build_traceability

ARTIFACTS = {
    "r1": b"r1",
    "s1": b"s1",
    "c1": b"c1",
    "plan": b"plan",
    "traceability": b"trace",
}


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan()
        self.contract = copy.deepcopy(C1_CONTRACT)
        self.r1 = copy.deepcopy(R1)
        self.s1 = copy.deepcopy(S1)

    def test_pending_confirmation_blocks_real_freeze(self):
        with self.assertRaises(BaselineError) as ctx:
            register_baseline(self.plan, self.contract, self.r1, self.s1, artifacts=ARTIFACTS)
        self.assertIn("six-person human confirmation", str(ctx.exception))

    def test_reference_freeze_is_allowed_with_explicit_flag(self):
        manifest = register_baseline(
            self.plan,
            self.contract,
            self.r1,
            self.s1,
            allow_reference=True,
            artifacts=ARTIFACTS,
        )
        self.assertEqual(manifest["status"], "REFERENCE_FROZEN")
        self.assertEqual(manifest["task_id"], "T01")
        self.assertEqual(len(manifest["file_checksums"]), 5)
        self.assertTrue(manifest["warnings"])

    def test_real_freeze_requires_all_six_reviewers(self):
        r1 = copy.deepcopy(self.r1)
        r1["status"] = "CONFIRMED"
        r1["human_confirmation"]["status"] = "CONFIRMED"
        r1["human_confirmation"]["approval_ref"] = "test-approval"
        for block in r1["human_confirmation"]["reviewers"]:
            r1["human_confirmation"]["reviewers"][block] = "CONFIRMED"

        manifest = register_baseline(self.plan, self.contract, r1, self.s1, artifacts=ARTIFACTS)
        self.assertEqual(manifest["status"], "FROZEN")
        self.assertEqual(manifest["approved_ref"], "test-approval")
        self.assertEqual(manifest["warnings"], [])

    def test_contract_operation_drift_blocks_freeze(self):
        contract = copy.deepcopy(self.contract)
        contract["operations"] = contract["operations"][:-1]
        with self.assertRaises(BaselineError) as ctx:
            register_baseline(
                self.plan,
                contract,
                self.r1,
                self.s1,
                allow_reference=True,
                artifacts=ARTIFACTS,
            )
        self.assertIn("operations must be", str(ctx.exception))

    def test_plan_traceability_is_generated(self):
        trace = build_traceability(self.plan)
        self.assertEqual(trace["plan_version"], self.plan["plan_version"])
        self.assertTrue(all(item["task_refs"] for item in trace["items"]))


if __name__ == "__main__":
    unittest.main()
