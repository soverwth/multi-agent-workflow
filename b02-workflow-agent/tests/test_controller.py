from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.adapters import LocalAgentGateway, MEMBERS, ROLES
from backend.controller import DiscussionController
from backend.errors import InvalidTransition
from backend.exporter import export_run
from backend.store import BlackboardStore


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.store = BlackboardStore(Path(self.temporary.name) / "data")
        self.controller = DiscussionController(self.store)

    def tearDown(self):
        self.temporary.cleanup()

    def create(self, scenario="normal", max_rounds=2):
        return self.controller.create_run("构建一个可验证的通用产品协作流程", "首期不收集敏感信息", scenario, max_rounds)

    def test_normal_flow_stops_at_six_person_gate_then_publishes_r1(self):
        run = self.create()
        with self.assertRaises(InvalidTransition):
            self.controller.confirm_requirements(run["run_id"], list(MEMBERS))
        run = self.controller.run_until_control_point(run["run_id"])
        self.assertEqual("HUMAN_CONFIRMATION", run["stage"])
        self.assertEqual("WAITING_HUMAN", run["status"])
        self.assertEqual(2, run["round"])
        self.assertEqual(4, len(run["blackboard"]["claims"]))
        self.assertEqual(4, len(run["blackboard"]["signoffs"]))
        self.assertTrue(run["blackboard"]["objections"])
        self.assertTrue(all(item["status"] == "resolved" for item in run["blackboard"]["objections"]))
        self.assertIsNone(run["blackboard"]["r1"])
        with self.assertRaises(InvalidTransition):
            self.controller.step(run["run_id"])
        with self.assertRaises(Exception):
            self.controller.confirm_requirements(run["run_id"], list(MEMBERS[:5]))
        run = self.controller.confirm_requirements(run["run_id"], list(MEMBERS))
        self.assertEqual("COMPLETED", run["status"])
        self.assertEqual("R1", run["blackboard"]["r1"]["version"])
        self.assertEqual(6, len(run["blackboard"]["r1"]["confirmed_by"]))
        self.assertTrue(self.controller.replay(run["run_id"])["passed"])

    def test_independent_divergence_uses_four_isolated_roles(self):
        gateway = LocalAgentGateway()
        calls = []
        original = gateway.independent

        def observe(idea, constraints, scenario):
            calls.append((idea, constraints, scenario))
            return original(idea, constraints, scenario)

        gateway.independent = observe
        controller = DiscussionController(self.store, agents=gateway)
        run = controller.create_run("任意产品想法")
        controller.step(run["run_id"])
        run = controller.step(run["run_id"])
        self.assertEqual(1, len(calls))
        self.assertEqual({item["role"] for item in run["blackboard"]["claims"]}, set(ROLES))
        self.assertTrue(all("首轮未读取其他角色答案" in item["reason"] for item in run["blackboard"]["claims"]))

    def test_value_conflict_pauses_for_human_decision(self):
        run = self.create("value_conflict")
        run = self.controller.run_until_control_point(run["run_id"])
        self.assertEqual("EVALUATE", run["stage"])
        self.assertEqual("WAITING_HUMAN", run["status"])
        self.assertTrue(run["latest_consensus"]["needs_human"])
        with self.assertRaises(InvalidTransition):
            self.controller.step(run["run_id"])
        run = self.controller.resolve_human_decision(run["run_id"], "团队决定首期优先隐私与可控成本，并保留该取舍理由。")
        self.assertEqual("READY", run["status"])
        run = self.controller.run_until_control_point(run["run_id"])
        self.assertEqual("HUMAN_CONFIRMATION", run["stage"])
        high = next(item for item in run["blackboard"]["objections"] if item["severity"] == "high")
        self.assertEqual("resolved", high["status"])
        self.assertEqual("D001", high["resolution_ref"])

    def test_budget_exhaustion_stops_without_fake_consensus(self):
        run = self.create("budget_exhaustion", max_rounds=2)
        run = self.controller.run_until_control_point(run["run_id"])
        self.assertEqual("STOPPED", run["status"])
        self.assertEqual("EVALUATE", run["stage"])
        self.assertGreater(run["latest_consensus"]["open_count"], 0)
        self.assertIsNone(run["blackboard"]["r1"])
        self.assertIn("BUDGET_STOPPED", [event["type"] for event in run["events"]])
        self.assertTrue(self.controller.replay(run["run_id"])["passed"])
        with self.assertRaises(InvalidTransition):
            self.controller.confirm_requirements(run["run_id"], list(MEMBERS))

    def test_pause_resume_preserves_checkpoint(self):
        run = self.create()
        run = self.controller.pause(run["run_id"])
        self.assertEqual("PAUSED", run["status"])
        with self.assertRaises(InvalidTransition):
            self.controller.step(run["run_id"])
        run = self.controller.resume(run["run_id"])
        self.assertEqual("READY", run["status"])
        self.assertEqual("INTAKE", run["stage"])
        run = self.controller.step(run["run_id"])
        self.assertEqual("DIVERGE", run["stage"])
        self.assertTrue(self.controller.replay(run["run_id"])["passed"])

    def test_agent_failure_blocks_without_inventing_claims(self):
        run = self.create("agent_failure")
        run = self.controller.run_until_control_point(run["run_id"])
        self.assertEqual("BLOCKED", run["status"])
        self.assertEqual("DIVERGE", run["stage"])
        self.assertEqual([], run["blackboard"]["claims"])
        self.assertIn("RUN_BLOCKED", [event["type"] for event in run["events"]])

    def test_invalid_role_output_is_blocked(self):
        class BrokenGateway(LocalAgentGateway):
            def independent(self, idea, constraints, scenario):
                return super().independent(idea, constraints, "normal")[:3]

        controller = DiscussionController(self.store, agents=BrokenGateway())
        run = controller.create_run("任意产品想法")
        controller.step(run["run_id"])
        run = controller.step(run["run_id"])
        self.assertEqual("BLOCKED", run["status"])
        self.assertIn("四个不同角色", run["failure"]["message"])

    def test_store_reload_and_replay_match_checkpoint(self):
        run = self.create()
        run = self.controller.run_until_control_point(run["run_id"])
        reloaded = DiscussionController(self.store).get(run["run_id"])
        self.assertEqual(run["stage"], reloaded["stage"])
        self.assertEqual(run["events"], reloaded["events"])
        replay = self.controller.replay(run["run_id"])
        self.assertEqual(replay["replayed_state"], replay["checkpoint_state"])
        self.assertEqual(len(run["events"]), replay["event_count"])

    def test_export_contains_design_and_honest_boundaries(self):
        run = self.create()
        run = self.controller.run_until_control_point(run["run_id"])
        report = export_run(run, self.controller.replay(run["run_id"]), "markdown")
        self.assertIn("## 阶段迁移表", report["content"])
        self.assertIn("## 控制伪代码", report["content"])
        self.assertIn("停止、暂停或等待人类均不等于共识通过", report["content"])
        self.assertNotIn("## 已确认 R1", report["content"])


if __name__ == "__main__":
    unittest.main()
