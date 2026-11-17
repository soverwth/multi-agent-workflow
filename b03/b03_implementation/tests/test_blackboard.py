import tempfile
import unittest
from pathlib import Path

from b03_implementation.artifact_store import ArtifactStore
from b03_implementation.blackboard import BlackboardStore
from b03_implementation.errors import InvalidSnapshot, LeaseConflict, VersionConflict


class TestBlackboard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "board.db"
        self.store = BlackboardStore(self.db)
        self.artifacts = ArtifactStore(self.db, self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _register(self, task_id="t1"):
        self.store.register_task(
            task_id=task_id, spec_version="s1", contract_version="c1", plan_version="p1"
        )

    def _freeze(self, task_id="t1", **overrides):
        params = dict(
            task_id=task_id,
            spec_version="s1",
            contract_version="c1",
            plan_version="p1",
            dependency_artifact_refs=[],
        )
        params.update(overrides)
        return str(self.store.freeze_input_snapshot(**params).snapshot_ref)

    def test_register_task_starts_pending(self):
        self._register()
        state = self.store.get_task_state("t1")
        self.assertEqual(state["state"], "PENDING")
        self.assertEqual(state["rev"], 0)

    def test_cas_state_rejects_stale_rev(self):
        self._register()
        result = self.store.cas_state("t1", 0, "READY")
        self.assertTrue(result.ok)
        self.assertEqual(result.rev, 1)
        with self.assertRaises(VersionConflict):
            self.store.cas_state("t1", 0, "RUNNING")

    def test_cas_state_rejects_invalid_snapshot(self):
        self._register()
        ref = self._freeze()
        self.store.invalidate_affected("s1")
        with self.assertRaises(InvalidSnapshot):
            self.store.cas_state("t1", 0, "READY", input_snapshot_ref=ref)

    def test_event_idempotent(self):
        event = {
            "event_id": "evt-1",
            "event_type": "task.submitted",
            "task_id": "t1",
            "occurred_at": "2026-11-17T00:00:00+00:00",
        }
        first = self.store.append_event(event)
        second = self.store.append_event(event)
        self.assertFalse(first.duplicate)
        self.assertTrue(second.duplicate)
        self.assertEqual(len(self.store.list_events()), 1)

    def test_stale_callback_recorded_but_flagged(self):
        event = {
            "event_id": "evt-2",
            "event_type": "task.submitted",
            "attempt_id": "old",
            "input_snapshot_ref": "old-ref",
        }
        self.store.append_event(event, current_attempt_id="new", current_snapshot_ref="new-ref")
        self.assertTrue(self.store.is_stale_event("evt-2"))

    def test_lease_conflict_reclaim_and_idempotent_redelivery(self):
        lease = self.store.acquire_lease(
            "be-01", task_id="t1", attempt_id="a1", idempotency_key="k1", ttl_seconds=60
        )
        # 幂等重发：同 idempotency_key 且租约仍有效时返回原租约。
        again = self.store.acquire_lease(
            "be-01", task_id="t1", attempt_id="a1", idempotency_key="k1", ttl_seconds=60
        )
        self.assertEqual(again.lease_token, lease.lease_token)
        # 冲突：不同任务争用同一资源。
        with self.assertRaises(LeaseConflict):
            self.store.acquire_lease(
                "be-01", task_id="t2", attempt_id="a2", idempotency_key="k2", ttl_seconds=60
            )
        # 回收后资源可被新任务获取；这是新租约，不是原尝试的重发。
        reclaimed = self.store.reclaim_expired_leases(now="2099-01-01T00:00:00+00:00")
        self.assertEqual(len(reclaimed), 1)
        self.assertEqual(reclaimed[0].lease_token, lease.lease_token)
        fresh = self.store.acquire_lease(
            "be-01", task_id="t3", attempt_id="a3", idempotency_key="k3", ttl_seconds=60
        )
        self.assertNotEqual(fresh.lease_token, lease.lease_token)

    def test_checkpoint_roundtrip_and_json_export(self):
        self.store.write_checkpoint(
            {"plan_version": "p1", "task_states": {}, "processed_event_ids": []}
        )
        self.assertEqual(self.store.load_checkpoint()["plan_version"], "p1")
        out = Path(self.tmp.name) / "cp.json"
        self.store.export_checkpoint_json(out)
        self.assertTrue(out.exists())

    def test_event_and_checkpoint_same_transaction(self):
        event = {"event_id": "evt-3", "event_type": "task.completed", "task_id": "t1"}
        cp = {"plan_version": "p1", "processed_event_ids": ["evt-3"]}
        self.store.record_event_and_checkpoint(event, cp)
        self.assertEqual(len(self.store.list_events()), 1)
        self.assertIn("evt-3", self.store.load_checkpoint()["processed_event_ids"])

    def test_artifacts_only_readable_with_valid_snapshot(self):
        ref = self._freeze()
        self.artifacts.put_artifact(
            task_id="t1",
            attempt_id="a1",
            version="r1",
            content_hash="abc123",
            snapshot_ref=ref,
            candidate_commit="deadbeef",
        )
        found = self.artifacts.get_artifacts_for_task("t1", valid_snapshot_ref=ref)
        self.assertEqual(len(found), 1)
        self.store.invalidate_affected("s1")
        with self.assertRaises(InvalidSnapshot):
            self.artifacts.get_artifacts_for_task("t1", valid_snapshot_ref=ref)

    def test_snapshot_view(self):
        self._register()
        view = self.store.get_snapshot_view()
        self.assertEqual(len(view["task_states"]), 1)
