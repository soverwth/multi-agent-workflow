import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from b01.design import C1_CONTRACT, DESIGN_ENTRIES, R1, S1
from b01.task_planner import build_plan, build_traceability

DOCS = Path(__file__).resolve().parents[1] / "docs"


def load(name):
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


class AssetConsistencyTests(unittest.TestCase):
    def test_generated_assets_match_code(self):
        plan = build_plan()
        self.assertEqual(load("r1.json"), R1)
        self.assertEqual(load("s1.json"), S1)
        self.assertEqual(load("c1.json"), C1_CONTRACT)
        self.assertEqual(load("design_entries.json"), DESIGN_ENTRIES)
        self.assertEqual(load("plan.json"), plan)
        self.assertEqual(load("traceability.json"), build_traceability(plan))

    def test_baseline_manifest_is_reference_frozen(self):
        manifest = load("baseline_manifest.json")
        self.assertEqual(manifest["status"], "REFERENCE_FROZEN")
        self.assertEqual(manifest["task_id"], "T01")


if __name__ == "__main__":
    unittest.main()
