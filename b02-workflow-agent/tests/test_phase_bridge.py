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
from backend.phase_bridge import r1_to_design_spec
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


if __name__ == "__main__":
    unittest.main()
