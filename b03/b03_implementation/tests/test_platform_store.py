import tempfile
import unittest
from pathlib import Path

from b03_implementation.errors import InvalidField, NotFound
from b03_implementation.platform_store import PlatformStore


class TestPlatformStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        self.store = PlatformStore(root / "platform.db", migrations_dir=migrations)
        self.store.create_project(project_id="p1", name="项目一", goal="目标一")
        self.store.create_project(project_id="p2", name="项目二", goal="目标二")

    def tearDown(self):
        self.tmp.cleanup()

    def test_project_isolation(self):
        self.store.save_version(
            project_id="p1", version_kind="requirement", version_label="R1", content={"goal": "仅项目一"}
        )
        self.assertEqual(len(self.store.list_versions("p1")), 1)
        self.assertEqual(len(self.store.list_versions("p2")), 0)
        self.assertIsNone(self.store.get_version("p2", "requirement", "R1"))

    def test_version_kind_validation(self):
        with self.assertRaises(InvalidField):
            self.store.save_version(
                project_id="p1", version_kind="unknown", version_label="X1", content={}
            )

    def test_runs_and_attempts_distinguished(self):
        run = self.store.start_run(project_id="p1", plan_version="plan_v1")
        a1 = self.store.start_attempt(
            project_id="p1", run_id=run["run_id"], task_id="T02", attempt_no=1, agent_role="DB-01"
        )
        self.store.finish_attempt(
            project_id="p1", attempt_id=a1["attempt_id"], state="FAILED", result={"error": "缺证据"}
        )
        a2 = self.store.start_attempt(
            project_id="p1", run_id=run["run_id"], task_id="T02", attempt_no=2, agent_role="DB-01"
        )
        attempts = self.store.list_attempts("p1", "T02")
        self.assertEqual(len(attempts), 2)
        self.assertEqual([a["attempt_no"] for a in attempts], [1, 2])
        self.assertEqual(attempts[0]["state"], "FAILED")
        self.assertEqual(attempts[1]["state"], "RUNNING")

    def test_duplicate_attempt_no_rejected(self):
        run = self.store.start_run(project_id="p1", plan_version="plan_v1")
        self.store.start_attempt(project_id="p1", run_id=run["run_id"], task_id="T01", attempt_no=1)
        with self.assertRaises(InvalidField):
            self.store.start_attempt(project_id="p1", run_id=run["run_id"], task_id="T01", attempt_no=1)

    def test_evidence_logs_artifacts_acceptance(self):
        run = self.store.start_run(project_id="p1", plan_version="plan_v1")
        attempt = self.store.start_attempt(
            project_id="p1", run_id=run["run_id"], task_id="T04", attempt_no=1
        )
        log_id = self.store.append_log(
            project_id="p1", message="执行开始", attempt_id=attempt["attempt_id"]
        )
        artifact = self.store.put_artifact(
            project_id="p1", task_id="T04", attempt_id=attempt["attempt_id"],
            version="r1", content_hash="abc123", path="src/app.py"
        )
        evidence_id = self.store.record_evidence(
            project_id="p1", task_id="T04", test_id="TC-P01", verdict="PASS",
            attempt_id=attempt["attempt_id"], artifact_ref=artifact["artifact_id"]
        )
        acceptance_id = self.store.record_acceptance(
            project_id="p1", task_id="T04", verdict="ACCEPT",
            attempt_id=attempt["attempt_id"], evidence_refs=[evidence_id]
        )
        self.assertTrue(log_id)
        self.assertEqual(len(self.store.list_logs("p1", attempt["attempt_id"])), 1)
        self.assertEqual(len(self.store.list_artifacts("p1", "T04")), 1)
        self.assertEqual(len(self.store.list_evidence("p1", "T04")), 1)
        self.assertEqual(len(self.store.list_acceptance("p1", "T04")), 1)
        self.assertTrue(acceptance_id)

    def test_invalid_acceptance_verdict(self):
        with self.assertRaises(InvalidField):
            self.store.record_acceptance(
                project_id="p1", task_id="T01", verdict="MAYBE"
            )

    def test_event_idempotency_and_replay(self):
        first = self.store.append_event(
            project_id="p1", event_id="evt-dup-1", event_type="task.dispatched",
            task_id="T01", payload={"attempt": 1}
        )
        second = self.store.append_event(
            project_id="p1", event_id="evt-dup-1", event_type="task.dispatched",
            task_id="T01", payload={"attempt": 1}
        )
        self.assertFalse(first.duplicate)
        self.assertTrue(second.duplicate)
        self.assertEqual(first.seq, second.seq)
        self.store.append_event(project_id="p1", event_type="task.submitted", task_id="T01")
        replay = self.store.replay_project("p1")
        self.assertEqual(len(replay), 2)
        self.assertEqual([e["seq"] for e in replay], sorted(e["seq"] for e in replay))
        self.assertEqual(len(self.store.replay_project("p2")), 0)

    def test_checkpoint_save_load_and_recover(self):
        run = self.store.start_run(project_id="p1", plan_version="plan_v1")
        self.store.append_event(project_id="p1", run_id=run["run_id"], event_type="task.dispatched")
        e2 = self.store.append_event(project_id="p1", run_id=run["run_id"], event_type="task.submitted")
        self.store.save_checkpoint(
            project_id="p1", run_id=run["run_id"], checkpoint_id="cp1",
            state={"task_states": {"T01": {"state": "REVIEWING"}}}, processed_event_seq=e2.seq - 1
        )
        cp = self.store.get_checkpoint("p1", run["run_id"], "cp1")
        self.assertIsNotNone(cp)
        self.assertEqual(cp["processed_event_seq"], e2.seq - 1)
        recovery = self.store.recover_run("p1", run["run_id"])
        self.assertEqual(len(recovery["unprocessed_events"]), 1)
        self.assertEqual(recovery["unprocessed_events"][0]["event_id"], e2.event_id)

    def test_recover_unknown_run(self):
        with self.assertRaises(NotFound):
            self.store.recover_run("p1", "missing-run")
