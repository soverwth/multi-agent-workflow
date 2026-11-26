from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.adapters import MEMBERS
from backend.controller import DiscussionController
from backend.errors import WorkflowError
from backend.phase_bridge import normalize_priority, r1_to_design_spec
from backend.store import BlackboardStore


class PhaseBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.store = BlackboardStore(Path(self.temporary.name) / "data")
        self.controller = DiscussionController(self.store)

    def tearDown(self):
        self.temporary.cleanup()

    def test_unconfirmed_discussion_cannot_enter_phase_two(self):
        run = self.controller.create_run("制作一个通用协作系统")
        with self.assertRaises(WorkflowError):
            r1_to_design_spec(run)

    def test_confirmed_r1_becomes_b01_design_spec(self):
        run = self.controller.create_run("制作一个通用协作系统", "先完成 MVP")
        run = self.controller.run_until_control_point(run["run_id"])
        run = self.controller.confirm_requirements(run["run_id"], list(MEMBERS))

        spec = r1_to_design_spec(run)

        self.assertEqual("b01.spec.v1", spec["schema_version"])
        self.assertRegex(spec["project_id"], r"^project-[0-9a-f]{8}$")
        self.assertEqual("制作一个通用协作系统", spec["title"])
        self.assertEqual(run["run_id"], spec["phase1_source"]["run_id"])
        self.assertEqual("R1", spec["phase1_source"]["r1_version"])
        self.assertIn(spec["generation_source"], {"local-heuristic", "unknown"})
        self.assertEqual(len(run["blackboard"]["r1"]["requirements"]), len(spec["requirements"]))
        self.assertEqual(len(spec["requirements"]), len(spec["design_entries"]))
        self.assertTrue(all(item["req_refs"] for item in spec["design_entries"]))

    def test_priority_is_normalized_to_b01_contract_values(self):
        """回归：真实模型返回 P0/P1 时，桥接必须归一化为 must|should|may。

        早期实现只做 .lower()，模型一旦输出 P0，B01 的 normalize_spec 就会以
        "priority 必须是 must|should|may" 拒绝整份设计规格（HTTP 400），
        导致真实模型演示无法进入第二阶段。
        """
        run = self.controller.create_run("制作短视频软件")
        run = self.controller.run_until_control_point(run["run_id"])
        run = self.controller.confirm_requirements(run["run_id"], list(MEMBERS))
        # 模拟真实模型的优先级写法
        run["blackboard"]["r1"]["requirements"][0]["priority"] = "P0"
        run["blackboard"]["r1"]["requirements"][1]["priority"] = "P1"
        run["blackboard"]["r1"]["requirements"][2]["priority"] = "P2"

        spec = r1_to_design_spec(run)

        priorities = [item["priority"] for item in spec["requirements"]]
        self.assertEqual(["must", "should", "may"], priorities[:3])
        self.assertTrue(all(item in {"must", "should", "may"} for item in priorities))

    def test_priority_alias_table(self):
        cases = {
            "P0": "must", "p1": "should", "P2": "may",
            "Must": "must", "SHOULD": "should", "may": "may",
            "高": "must", "中": "should", "低": "may",
            "high": "must", "medium": "should", "low": "may",
            "must-have": "must",
            "": "must", None: "must", "unexpected": "must",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(expected, normalize_priority(raw))


if __name__ == "__main__":
    unittest.main()
