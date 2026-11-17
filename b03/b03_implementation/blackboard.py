"""task_store：黑板过程数据的持久化与原子操作。

职责边界（主文档 5.4 / 5.5 / 10.3）：
- B02 独占状态迁移决策；本模块只提供 cas_state 原子落盘，rev 不匹配即拒绝。
- 事件、产物、证据、缺陷只追加；更正通过新版本记录。
- 事件日志与检查点在同一 SQLite 事务内写入，避免“事件已处理但检查点未落盘”。
- 黑板过程数据与校园业务数据分开：本模块只连 BLACKBOARD_DB。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .config import (
    BLACKBOARD_DB,
    CHECKPOINT_JSON,
    DEFAULT_EVENT_PAGE_SIZE,
    DEFAULT_LEASE_TTL_SECONDS,
)
from .errors import InvalidSnapshot, InvalidState, LeaseConflict, NotFound, VersionConflict

VALID_STATES = {"PENDING", "READY", "RUNNING", "REVIEWING", "SUCCEEDED", "FAILED"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class CasResult:
    ok: bool
    task_id: str
    rev: int
    state: str


@dataclass(frozen=True)
class Lease:
    lease_token: str
    resource_key: str
    task_id: str
    attempt_id: str
    idempotency_key: str
    write_scope: str | None
    acquired_at: str
    expires_at: str


@dataclass(frozen=True)
class SnapshotRef:
    snapshot_ref: str
    task_id: str


@dataclass(frozen=True)
class EventAppendResult:
    accepted: bool
    duplicate: bool
    event_id: str


class BlackboardStore:
    """黑板过程数据的单一状态服务。"""

    def __init__(self, db_path=BLACKBOARD_DB):
        self.db_path = str(db_path)
        self.initialize()

    # ---------- 基础设施 ----------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def initialize(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS spec_baseline (
            spec_version TEXT PRIMARY KEY,
            contract_version TEXT NOT NULL,
            approved_ref TEXT,
            constraints_json TEXT NOT NULL DEFAULT '{}',
            open_questions_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_registry (
            task_id TEXT PRIMARY KEY,
            spec_version TEXT NOT NULL,
            contract_version TEXT NOT NULL,
            plan_version TEXT NOT NULL,
            req_refs_json TEXT NOT NULL DEFAULT '[]',
            design_refs_json TEXT NOT NULL DEFAULT '[]',
            depends_on_json TEXT NOT NULL DEFAULT '[]',
            write_scope TEXT,
            acceptance_json TEXT NOT NULL DEFAULT '[]',
            required_test_ids_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS execution_state (
            task_id TEXT PRIMARY KEY,
            run_id TEXT,
            attempt_id TEXT,
            state TEXT NOT NULL,
            responsible_agent TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            input_snapshot_ref TEXT,
            started_at TEXT,
            finished_at TEXT,
            rev INTEGER NOT NULL DEFAULT 0,
            blocker_reason TEXT,
            accepted_commit TEXT,
            valid INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_ref TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            run_id TEXT,
            attempt_id TEXT,
            spec_version TEXT NOT NULL,
            contract_version TEXT NOT NULL,
            plan_version TEXT NOT NULL,
            dependency_artifact_refs_json TEXT NOT NULL DEFAULT '[]',
            task_package_ref TEXT,
            frozen_at TEXT NOT NULL,
            valid INTEGER NOT NULL DEFAULT 1,
            invalid_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT,
            task_id TEXT,
            attempt_id TEXT,
            event_type TEXT NOT NULL,
            input_snapshot_ref TEXT,
            producer TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            occurred_at TEXT NOT NULL,
            processed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS leases (
            resource_key TEXT PRIMARY KEY,
            lease_token TEXT NOT NULL,
            task_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            write_scope TEXT,
            expires_at TEXT NOT NULL,
            acquired_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            version TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            candidate_commit TEXT,
            write_scope TEXT,
            snapshot_ref TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(task_id, attempt_id, version)
        );
        CREATE TABLE IF NOT EXISTS test_evidence (
            evidence_id TEXT PRIMARY KEY,
            test_id TEXT NOT NULL,
            input_json TEXT NOT NULL DEFAULT '{}',
            expected TEXT,
            actual TEXT,
            env TEXT,
            artifact_ref TEXT,
            snapshot_ref TEXT,
            verdict TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS issues_decisions (
            record_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            target_id TEXT,
            severity TEXT,
            status TEXT NOT NULL,
            resolution_ref TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS checkpoints (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
        CREATE INDEX IF NOT EXISTS idx_leases_exp ON leases(expires_at);
        CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);
        """
        with self._connect() as conn:
            conn.executescript(ddl)
            conn.commit()

    # ---------- 规格 / 任务登记 ----------

    def register_spec_baseline(
        self,
        *,
        spec_version: str,
        contract_version: str,
        approved_ref: str | None = None,
        constraints: dict | None = None,
        open_questions: list | None = None,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO spec_baseline
                   (spec_version, contract_version, approved_ref, constraints_json,
                    open_questions_json, created_at) VALUES (?,?,?,?,?,?)""",
                (
                    spec_version,
                    contract_version,
                    approved_ref,
                    json.dumps(constraints or {}, ensure_ascii=False),
                    json.dumps(open_questions or [], ensure_ascii=False),
                    _now(),
                ),
            )

    def register_task(
        self,
        *,
        task_id: str,
        spec_version: str,
        contract_version: str,
        plan_version: str,
        req_refs: list | None = None,
        design_refs: list | None = None,
        depends_on: list | None = None,
        write_scope: str | None = None,
        acceptance: list | None = None,
        required_test_ids: list | None = None,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO task_registry
                   (task_id, spec_version, contract_version, plan_version, req_refs_json,
                    design_refs_json, depends_on_json, write_scope, acceptance_json,
                    required_test_ids_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    spec_version,
                    contract_version,
                    plan_version,
                    json.dumps(req_refs or [], ensure_ascii=False),
                    json.dumps(design_refs or [], ensure_ascii=False),
                    json.dumps(depends_on or [], ensure_ascii=False),
                    write_scope,
                    json.dumps(acceptance or [], ensure_ascii=False),
                    json.dumps(required_test_ids or [], ensure_ascii=False),
                ),
            )
            conn.execute(
                """INSERT OR IGNORE INTO execution_state
                   (task_id, state, rev) VALUES (?, 'PENDING', 0)""",
                (task_id,),
            )

    def get_task_state(self, task_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM execution_state WHERE task_id=?", (task_id,)).fetchone()
            return dict(row) if row else None

    def get_task_registry(self, task_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM task_registry WHERE task_id=?", (task_id,)).fetchone()
            return dict(row) if row else None

    # ---------- 原子状态（B02 独占决策） ----------

    def cas_state(
        self,
        task_id: str,
        expected_rev: int,
        next_state: str,
        *,
        attempt_id: str | None = None,
        input_snapshot_ref: str | None = None,
        reason: str | None = None,
        responsible_agent: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        accepted_commit: str | None = None,
    ) -> CasResult:
        if next_state not in VALID_STATES:
            raise InvalidState(next_state)
        with self._tx() as conn:
            row = conn.execute("SELECT rev, state FROM execution_state WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise NotFound(task_id)
            if row["rev"] != expected_rev:
                raise VersionConflict(f"{task_id}: expected_rev={expected_rev}, current_rev={row['rev']}")
            if input_snapshot_ref is not None:
                snap = conn.execute(
                    "SELECT valid FROM snapshots WHERE snapshot_ref=?", (input_snapshot_ref,)
                ).fetchone()
                if snap is None or not snap["valid"]:
                    raise InvalidSnapshot(input_snapshot_ref)
            conn.execute(
                """UPDATE execution_state SET
                     state=?, rev=rev+1,
                     attempt_id=COALESCE(?, attempt_id),
                     input_snapshot_ref=COALESCE(?, input_snapshot_ref),
                     responsible_agent=COALESCE(?, responsible_agent),
                     started_at=COALESCE(?, started_at),
                     finished_at=COALESCE(?, finished_at),
                     accepted_commit=COALESCE(?, accepted_commit),
                     blocker_reason=?
                   WHERE task_id=?""",
                (
                    next_state,
                    attempt_id,
                    input_snapshot_ref,
                    responsible_agent,
                    started_at,
                    finished_at,
                    accepted_commit,
                    reason,
                    task_id,
                ),
            )
            return CasResult(ok=True, task_id=task_id, rev=expected_rev + 1, state=next_state)

    # ---------- 租约 ----------

    def acquire_lease(
        self,
        resource_key: str,
        *,
        task_id: str,
        attempt_id: str,
        idempotency_key: str,
        ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
        write_scope: str | None = None,
    ) -> Lease:
        with self._tx() as conn:
            now = datetime.now(timezone.utc)
            # 幂等：同键未过期直接返回原租约，避免中断重发产生第二次有效执行。
            idem = conn.execute(
                "SELECT * FROM leases WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if idem is not None:
                if idem["expires_at"] > now.isoformat():
                    return Lease(**dict(idem))
                conn.execute("DELETE FROM leases WHERE idempotency_key=?", (idempotency_key,))
            held = conn.execute(
                "SELECT * FROM leases WHERE resource_key=?", (resource_key,)
            ).fetchone()
            if held is not None and held["expires_at"] > now.isoformat():
                raise LeaseConflict(f"{resource_key} 已被 {held['task_id']} 占用")
            token = _uuid()
            expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
            acquired = now.isoformat()
            conn.execute(
                """INSERT INTO leases
                   (lease_token, resource_key, task_id, attempt_id, idempotency_key,
                    write_scope, expires_at, acquired_at) VALUES (?,?,?,?,?,?,?,?)""",
                (token, resource_key, task_id, attempt_id, idempotency_key, write_scope, expires, acquired),
            )
            return Lease(
                lease_token=token,
                resource_key=resource_key,
                task_id=task_id,
                attempt_id=attempt_id,
                idempotency_key=idempotency_key,
                write_scope=write_scope,
                acquired_at=acquired,
                expires_at=expires,
            )

    def renew_lease(self, lease_token: str, ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS) -> Lease:
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM leases WHERE lease_token=?", (lease_token,)).fetchone()
            if row is None:
                raise NotFound(lease_token)
            expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
            conn.execute("UPDATE leases SET expires_at=? WHERE lease_token=?", (expires, lease_token))
            return Lease(**{**dict(row), "expires_at": expires})

    def release_lease(self, lease_token: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM leases WHERE lease_token=?", (lease_token,))

    def reclaim_expired_leases(self, now: str | None = None) -> list[Lease]:
        now = now or _now()
        with self._tx() as conn:
            rows = conn.execute("SELECT * FROM leases WHERE expires_at <= ?", (now,)).fetchall()
            leases = [Lease(**dict(r)) for r in rows]
            for lease in leases:
                conn.execute("DELETE FROM leases WHERE lease_token=?", (lease.lease_token,))
            return leases

    # ---------- 输入快照 ----------

    def freeze_input_snapshot(
        self,
        task_id: str,
        *,
        spec_version: str,
        contract_version: str,
        plan_version: str,
        dependency_artifact_refs: list[str] | None = None,
        task_package_ref: str | None = None,
        run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> SnapshotRef:
        ref = _uuid()
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO snapshots
                   (snapshot_ref, task_id, run_id, attempt_id, spec_version,
                    contract_version, plan_version, dependency_artifact_refs_json,
                    task_package_ref, frozen_at, valid)
                   VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
                (
                    ref,
                    task_id,
                    run_id,
                    attempt_id,
                    spec_version,
                    contract_version,
                    plan_version,
                    json.dumps(dependency_artifact_refs or [], ensure_ascii=False),
                    task_package_ref,
                    _now(),
                ),
            )
        return SnapshotRef(snapshot_ref=ref, task_id=task_id)

    def get_snapshot(self, ref: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM snapshots WHERE snapshot_ref=?", (ref,)).fetchone()
            return dict(row) if row else None

    def verify_snapshot_still_valid(self, ref: str) -> bool:
        snap = self.get_snapshot(ref)
        return bool(snap and snap["valid"])

    def invalidate_affected(self, change_ref: str) -> list[str]:
        """标记引用 change_ref 的快照失效，返回受影响快照列表。"""
        with self._tx() as conn:
            rows = conn.execute(
                """SELECT snapshot_ref FROM snapshots WHERE valid=1 AND
                   (spec_version=? OR contract_version=? OR plan_version=? OR
                    dependency_artifact_refs_json LIKE ?)""",
                (change_ref, change_ref, change_ref, f"%{change_ref}%"),
            ).fetchall()
            refs = [r["snapshot_ref"] for r in rows]
            for ref in refs:
                conn.execute(
                    "UPDATE snapshots SET valid=0, invalid_reason=? WHERE snapshot_ref=?",
                    (change_ref, ref),
                )
            return refs

    # ---------- 事件（幂等） ----------

    def append_event(
        self,
        event: dict,
        *,
        current_attempt_id: str | None = None,
        current_snapshot_ref: str | None = None,
    ) -> EventAppendResult:
        """追加事件。attempt/snapshot 不匹配者仍写入日志，但标记 stale。"""
        event_id = event.get("event_id") or _uuid()
        with self._tx() as conn:
            existing = conn.execute("SELECT event_id FROM events WHERE event_id=?", (event_id,)).fetchone()
            if existing is not None:
                return EventAppendResult(accepted=True, duplicate=True, event_id=event_id)
            stale = 0
            if current_attempt_id is not None and event.get("attempt_id") != current_attempt_id:
                stale = 1
            if current_snapshot_ref is not None and event.get("input_snapshot_ref") != current_snapshot_ref:
                stale = 1
            conn.execute(
                """INSERT INTO events
                   (event_id, run_id, task_id, attempt_id, event_type,
                    input_snapshot_ref, producer, payload_json, occurred_at, processed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id,
                    event.get("run_id"),
                    event.get("task_id"),
                    event.get("attempt_id"),
                    event.get("event_type", "unknown"),
                    event.get("input_snapshot_ref"),
                    event.get("producer"),
                    json.dumps({**event.get("payload", {}), "stale": bool(stale)}, ensure_ascii=False),
                    event.get("occurred_at") or _now(),
                    None,
                ),
            )
            return EventAppendResult(accepted=True, duplicate=False, event_id=event_id)

    def list_events(
        self,
        after_event_id: str | None = None,
        limit: int = DEFAULT_EVENT_PAGE_SIZE,
    ) -> list[dict]:
        with self._connect() as conn:
            if after_event_id is None:
                rows = conn.execute(
                    "SELECT * FROM events ORDER BY occurred_at, event_id LIMIT ?", (limit,)
                ).fetchall()
            else:
                cursor = conn.execute(
                    "SELECT occurred_at FROM events WHERE event_id=?", (after_event_id,)
                ).fetchone()
                if cursor is None:
                    raise NotFound(after_event_id)
                rows = conn.execute(
                    """SELECT * FROM events WHERE occurred_at > ? OR
                       (occurred_at = ? AND event_id > ?)
                       ORDER BY occurred_at, event_id LIMIT ?""",
                    (cursor["occurred_at"], cursor["occurred_at"], after_event_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    def is_stale_event(self, event_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM events WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise NotFound(event_id)
            return bool(json.loads(row["payload_json"]).get("stale"))

    # ---------- 检查点 ----------

    def write_checkpoint(self, cp: dict) -> None:
        payload = json.dumps(cp, ensure_ascii=False, sort_keys=True)
        with self._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO checkpoints (id, payload_json, created_at) VALUES (1,?,?)",
                (payload, _now()),
            )

    def load_checkpoint(self) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM checkpoints WHERE id=1").fetchone()
            return json.loads(row["payload_json"]) if row else None

    def export_checkpoint_json(self, path=CHECKPOINT_JSON) -> str:
        """导出检查点快照文件，供“检查点文件”基线或六人复现核查。"""
        cp = self.load_checkpoint() or {}
        Path(path).write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def record_event_and_checkpoint(self, event: dict, cp: dict, **event_kwargs) -> EventAppendResult:
        """事件日志与检查点在同一事务写入，对应 B02 的事件处理顺序。"""
        event_id = event.get("event_id") or _uuid()
        with self._tx() as conn:
            existing = conn.execute("SELECT event_id FROM events WHERE event_id=?", (event_id,)).fetchone()
            if existing is None:
                conn.execute(
                    """INSERT INTO events
                       (event_id, run_id, task_id, attempt_id, event_type,
                        input_snapshot_ref, producer, payload_json, occurred_at, processed_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        event_id,
                        event.get("run_id"),
                        event.get("task_id"),
                        event.get("attempt_id"),
                        event.get("event_type", "unknown"),
                        event.get("input_snapshot_ref"),
                        event.get("producer"),
                        json.dumps(event.get("payload", {}), ensure_ascii=False),
                        event.get("occurred_at") or _now(),
                        _now(),
                    ),
                )
            conn.execute(
                "INSERT OR REPLACE INTO checkpoints (id, payload_json, created_at) VALUES (1,?,?)",
                (json.dumps(cp, ensure_ascii=False, sort_keys=True), _now()),
            )
        return EventAppendResult(
            accepted=True, duplicate=existing is not None, event_id=event_id
        )

    # ---------- 证据 / 缺陷 ----------

    def add_test_evidence(
        self,
        *,
        test_id: str,
        verdict: str,
        artifact_ref: str | None = None,
        snapshot_ref: str | None = None,
        inputs: dict | None = None,
        expected: str | None = None,
        actual: str | None = None,
        env: str | None = None,
    ) -> str:
        evidence_id = _uuid()
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO test_evidence
                   (evidence_id, test_id, input_json, expected, actual, env,
                    artifact_ref, snapshot_ref, verdict, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    evidence_id,
                    test_id,
                    json.dumps(inputs or {}, ensure_ascii=False),
                    expected,
                    actual,
                    env,
                    artifact_ref,
                    snapshot_ref,
                    verdict,
                    _now(),
                ),
            )
        return evidence_id

    def list_test_evidence(self, test_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if test_id:
                rows = conn.execute(
                    "SELECT * FROM test_evidence WHERE test_id=?", (test_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM test_evidence").fetchall()
            return [dict(r) for r in rows]

    def add_issue_or_decision(
        self,
        *,
        kind: str,
        target_id: str | None = None,
        severity: str | None = None,
        status: str,
        resolution_ref: str | None = None,
        payload: dict | None = None,
    ) -> str:
        record_id = _uuid()
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO issues_decisions
                   (record_id, kind, target_id, severity, status, resolution_ref,
                    payload_json, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    record_id,
                    kind,
                    target_id,
                    severity,
                    status,
                    resolution_ref,
                    json.dumps(payload or {}, ensure_ascii=False),
                    _now(),
                ),
            )
        return record_id

    # ---------- 只读视图（供 B05） ----------

    def get_snapshot_view(self, recent_events: int = 20) -> dict:
        with self._connect() as conn:
            states = conn.execute(
                "SELECT task_id, state, rev, blocker_reason, attempt_id FROM execution_state ORDER BY task_id"
            ).fetchall()
            events = conn.execute(
                "SELECT event_id, task_id, event_type, occurred_at FROM events ORDER BY occurred_at DESC LIMIT ?",
                (recent_events,),
            ).fetchall()
        return {
            "task_states": [dict(s) for s in states],
            "recent_events": [dict(e) for e in events],
            "blockers": [dict(s) for s in states if s["blocker_reason"]],
        }
