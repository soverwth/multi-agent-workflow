"""平台核心存储（B03 新阶段主交付）。

职责（对应《阶段开发分工.md》B03）：
- 项目/需求/设计/任务计划的版本化存储与数据隔离；
- 任务运行记录、执行尝试记录、Agent 产物、执行日志、测试证据、验收结果；
- 执行事件幂等、历史回放；
- 按项目 + 运行的 checkpoint 保存/读取，支持重启恢复。

约定：
- 只做持久化与查询，不维护 B02 状态决策、B04 执行、B06 判定的业务逻辑。
- 使用独立数据库 PLATFORM_DB，不与校园案例业务库混用。
- 所有业务接口强制 project_id，保证不同项目数据隔离。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import BASE_DIR, MIGRATIONS_DIR
from .errors import InvalidField, NotFound

PLATFORM_DB = BASE_DIR / "platform.db"

VERSION_KINDS = {"requirement", "design", "plan"}
VERDICTS = {"ACCEPT", "REJECT", "REVALIDATION_REQUIRED"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _dumps(data: Any) -> str:
    return json.dumps(data or {}, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class EventAppendResult:
    accepted: bool
    duplicate: bool
    event_id: str
    seq: int


class PlatformStore:
    """平台核心数据持久化服务，所有接口以 project_id 隔离。"""

    def __init__(self, db_path=PLATFORM_DB, migrations_dir=MIGRATIONS_DIR):
        self.db_path = str(db_path)
        self.migrations_dir = Path(migrations_dir)
        self.initialize()

    # ---------- 基础设施 ----------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
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
        with self._connect() as conn:
            migration = self.migrations_dir / "004_platform_core.sql"
            if not migration.exists():
                raise NotFound(str(migration))
            conn.executescript(migration.read_text(encoding="utf-8"))
            conn.commit()

    @staticmethod
    def _require_project(project_id: str) -> str:
        if not project_id:
            raise InvalidField("project_id")
        return project_id

    # ---------- 项目与版本 ----------

    def create_project(
        self,
        *,
        project_id: str | None = None,
        name: str,
        goal: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        if not name:
            raise InvalidField("name")
        project_id = project_id or _uuid()
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO projects (project_id, name, goal, created_at, metadata_json)
                   VALUES (?,?,?,?,?)""",
                (project_id, name, goal, _now(), _dumps(metadata)),
            )
        return self.get_project(project_id)  # type: ignore[return-value]

    def get_project(self, project_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE project_id=?", (self._require_project(project_id),)
            ).fetchone()
            return dict(row) if row else None

    def list_projects(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at, project_id").fetchall()
            return [dict(r) for r in rows]

    def save_version(
        self,
        *,
        project_id: str,
        version_kind: str,
        version_label: str,
        content: dict,
    ) -> dict:
        self._require_project(project_id)
        if version_kind not in VERSION_KINDS:
            raise InvalidField("version_kind")
        if not version_label:
            raise InvalidField("version_label")
        version_id = _uuid()
        with self._tx() as conn:
            if conn.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone() is None:
                raise NotFound("project_id")
            conn.execute(
                """INSERT INTO project_versions
                   (version_id, project_id, version_kind, version_label, content_json, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (version_id, project_id, version_kind, version_label, _dumps(content), _now()),
            )
        return self.get_version(project_id, version_kind, version_label)  # type: ignore[return-value]

    def get_version(
        self, project_id: str, version_kind: str, version_label: str
    ) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM project_versions
                   WHERE project_id=? AND version_kind=? AND version_label=?""",
                (self._require_project(project_id), version_kind, version_label),
            ).fetchone()
            return dict(row) if row else None

    def list_versions(self, project_id: str, version_kind: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if version_kind:
                rows = conn.execute(
                    """SELECT * FROM project_versions
                       WHERE project_id=? AND version_kind=? ORDER BY created_at, version_id""",
                    (self._require_project(project_id), version_kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM project_versions WHERE project_id=? ORDER BY created_at, version_id",
                    (self._require_project(project_id),),
                ).fetchall()
            return [dict(r) for r in rows]

    # ---------- 运行与执行尝试 ----------

    def start_run(
        self,
        *,
        project_id: str,
        run_id: str | None = None,
        plan_version: str,
        metadata: dict | None = None,
    ) -> dict:
        self._require_project(project_id)
        run_id = run_id or _uuid()
        with self._tx() as conn:
            if conn.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone() is None:
                raise NotFound("project_id")
            conn.execute(
                """INSERT INTO task_runs
                   (run_id, project_id, plan_version, status, started_at, metadata_json)
                   VALUES (?,?,?, 'RUNNING', ?, ?)""",
                (run_id, project_id, plan_version, _now(), _dumps(metadata)),
            )
        return self.get_run(project_id, run_id)  # type: ignore[return-value]

    def get_run(self, project_id: str, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_runs WHERE project_id=? AND run_id=?",
                (self._require_project(project_id), run_id),
            ).fetchone()
            return dict(row) if row else None

    def finish_run(self, project_id: str, run_id: str, status: str) -> dict:
        if status not in {"RUNNING", "PAUSED", "COMPLETED", "CANCELLED"}:
            raise InvalidField("status")
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE task_runs SET status=?, finished_at=? WHERE project_id=? AND run_id=?",
                (status, _now(), self._require_project(project_id), run_id),
            )
            if cur.rowcount == 0:
                raise NotFound("run_id")
        return self.get_run(project_id, run_id)  # type: ignore[return-value]

    def list_runs(self, project_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_runs WHERE project_id=? ORDER BY started_at, run_id",
                (self._require_project(project_id),),
            ).fetchall()
            return [dict(r) for r in rows]

    def start_attempt(
        self,
        *,
        project_id: str,
        run_id: str,
        task_id: str,
        attempt_no: int,
        agent_role: str | None = None,
        input_snapshot: dict | None = None,
        state: str = "RUNNING",
    ) -> dict:
        self._require_project(project_id)
        attempt_id = _uuid()
        with self._tx() as conn:
            if conn.execute("SELECT 1 FROM task_runs WHERE project_id=? AND run_id=?", (project_id, run_id)).fetchone() is None:
                raise NotFound("run_id")
            try:
                conn.execute(
                    """INSERT INTO task_attempts
                       (attempt_id, run_id, project_id, task_id, attempt_no, agent_role,
                        state, input_snapshot_json, started_at, result_json)
                       VALUES (?,?,?,?,?,?,?,?,?, '{}')""",
                    (
                        attempt_id,
                        run_id,
                        project_id,
                        task_id,
                        attempt_no,
                        agent_role,
                        state,
                        _dumps(input_snapshot),
                        _now(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise InvalidField("attempt_no duplicated") from exc
        return self.get_attempt(project_id, attempt_id)  # type: ignore[return-value]

    def get_attempt(self, project_id: str, attempt_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_attempts WHERE project_id=? AND attempt_id=?",
                (self._require_project(project_id), attempt_id),
            ).fetchone()
            return dict(row) if row else None

    def finish_attempt(
        self,
        *,
        project_id: str,
        attempt_id: str,
        state: str,
        result: dict | None = None,
    ) -> dict:
        with self._tx() as conn:
            cur = conn.execute(
                """UPDATE task_attempts
                   SET state=?, result_json=?, finished_at=?
                   WHERE project_id=? AND attempt_id=?""",
                (state, _dumps(result), _now(), self._require_project(project_id), attempt_id),
            )
            if cur.rowcount == 0:
                raise NotFound("attempt_id")
        return self.get_attempt(project_id, attempt_id)  # type: ignore[return-value]

    def list_attempts(self, project_id: str, task_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if task_id:
                rows = conn.execute(
                    """SELECT * FROM task_attempts WHERE project_id=? AND task_id=?
                       ORDER BY attempt_no, started_at""",
                    (self._require_project(project_id), task_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM task_attempts WHERE project_id=? ORDER BY started_at, attempt_id",
                    (self._require_project(project_id),),
                ).fetchall()
            return [dict(r) for r in rows]

    # ---------- 执行日志 / 产物 / 证据 / 验收 ----------

    def append_log(
        self,
        *,
        project_id: str,
        message: str,
        run_id: str | None = None,
        attempt_id: str | None = None,
        level: str = "INFO",
        context: dict | None = None,
    ) -> str:
        if not message:
            raise InvalidField("message")
        log_id = _uuid()
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO execution_logs
                   (log_id, project_id, run_id, attempt_id, level, message, context_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (log_id, self._require_project(project_id), run_id, attempt_id, level, message, _dumps(context), _now()),
            )
        return log_id

    def list_logs(self, project_id: str, attempt_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if attempt_id:
                rows = conn.execute(
                    "SELECT * FROM execution_logs WHERE project_id=? AND attempt_id=? ORDER BY created_at, log_id",
                    (self._require_project(project_id), attempt_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM execution_logs WHERE project_id=? ORDER BY created_at, log_id",
                    (self._require_project(project_id),),
                ).fetchall()
            return [dict(r) for r in rows]

    def put_artifact(
        self,
        *,
        project_id: str,
        task_id: str,
        attempt_id: str,
        version: str,
        path: str | None = None,
        content_hash: str | None = None,
        commit_ref: str | None = None,
        run_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        self._require_project(project_id)
        artifact_id = _uuid()
        with self._tx() as conn:
            try:
                conn.execute(
                    """INSERT INTO platform_artifacts
                       (artifact_id, project_id, run_id, attempt_id, task_id, version,
                        path, content_hash, commit_ref, metadata_json, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (artifact_id, project_id, run_id, attempt_id, task_id, version,
                     path, content_hash, commit_ref, _dumps(metadata), _now()),
                )
            except sqlite3.IntegrityError as exc:
                raise InvalidField("artifact version duplicated") from exc
        return self.get_artifact(project_id, artifact_id)  # type: ignore[return-value]

    def get_artifact(self, project_id: str, artifact_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM platform_artifacts WHERE project_id=? AND artifact_id=?",
                (self._require_project(project_id), artifact_id),
            ).fetchone()
            return dict(row) if row else None

    def list_artifacts(self, project_id: str, task_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if task_id:
                rows = conn.execute(
                    "SELECT * FROM platform_artifacts WHERE project_id=? AND task_id=? ORDER BY created_at",
                    (self._require_project(project_id), task_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM platform_artifacts WHERE project_id=? ORDER BY created_at",
                    (self._require_project(project_id),),
                ).fetchall()
            return [dict(r) for r in rows]

    def record_evidence(
        self,
        *,
        project_id: str,
        task_id: str,
        test_id: str,
        verdict: str,
        attempt_id: str | None = None,
        inputs: dict | None = None,
        expected: str | None = None,
        actual: str | None = None,
        env: str | None = None,
        artifact_ref: str | None = None,
    ) -> str:
        if verdict not in {"PASS", "FAIL"}:
            raise InvalidField("verdict")
        evidence_id = _uuid()
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO evidence_records
                   (evidence_id, project_id, task_id, attempt_id, test_id, input_json,
                    expected, actual, env, artifact_ref, verdict, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (evidence_id, self._require_project(project_id), task_id, attempt_id, test_id,
                 _dumps(inputs), expected, actual, env, artifact_ref, verdict, _now()),
            )
        return evidence_id

    def list_evidence(self, project_id: str, task_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if task_id:
                rows = conn.execute(
                    "SELECT * FROM evidence_records WHERE project_id=? AND task_id=? ORDER BY created_at",
                    (self._require_project(project_id), task_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM evidence_records WHERE project_id=? ORDER BY created_at",
                    (self._require_project(project_id),),
                ).fetchall()
            return [dict(r) for r in rows]

    def record_acceptance(
        self,
        *,
        project_id: str,
        task_id: str,
        verdict: str,
        attempt_id: str | None = None,
        reason: str | None = None,
        evidence_refs: list[str] | None = None,
        defect: dict | None = None,
    ) -> str:
        if verdict not in VERDICTS:
            raise InvalidField("verdict")
        acceptance_id = _uuid()
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO acceptance_results
                   (acceptance_id, project_id, task_id, attempt_id, verdict, reason,
                    evidence_refs_json, defect_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (acceptance_id, self._require_project(project_id), task_id, attempt_id, verdict,
                 reason, json.dumps(evidence_refs or [], ensure_ascii=False), _dumps(defect), _now()),
            )
        return acceptance_id

    def list_acceptance(self, project_id: str, task_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if task_id:
                rows = conn.execute(
                    "SELECT * FROM acceptance_results WHERE project_id=? AND task_id=? ORDER BY created_at",
                    (self._require_project(project_id), task_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM acceptance_results WHERE project_id=? ORDER BY created_at",
                    (self._require_project(project_id),),
                ).fetchall()
            return [dict(r) for r in rows]

    # ---------- 事件（幂等）与历史回放 ----------

    def append_event(
        self,
        *,
        project_id: str,
        event_type: str,
        event_id: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        attempt_id: str | None = None,
        payload: dict | None = None,
        input_version: dict | None = None,
        occurred_at: str | None = None,
    ) -> EventAppendResult:
        self._require_project(project_id)
        event_id = event_id or _uuid()
        with self._tx() as conn:
            existing = conn.execute(
                "SELECT seq FROM platform_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if existing is not None:
                return EventAppendResult(
                    accepted=True, duplicate=True, event_id=event_id, seq=existing["seq"]
                )
            cur = conn.execute(
                """INSERT INTO platform_events
                   (event_id, project_id, run_id, task_id, attempt_id, event_type,
                    payload_json, input_version_json, occurred_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (event_id, project_id, run_id, task_id, attempt_id, event_type,
                 _dumps(payload), _dumps(input_version), occurred_at or _now()),
            )
            seq = cur.lastrowid
        return EventAppendResult(accepted=True, duplicate=False, event_id=event_id, seq=seq)

    def list_events(
        self,
        project_id: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM platform_events
                   WHERE project_id=? AND seq>? ORDER BY seq LIMIT ?""",
                (self._require_project(project_id), after_seq, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def replay_project(
        self,
        project_id: str,
        *,
        after_seq: int = 0,
        limit: int | None = None,
    ) -> list[dict]:
        """按 seq 顺序回放项目事件，供状态重建与历史审计。"""
        self._require_project(project_id)
        sql = "SELECT * FROM platform_events WHERE project_id=? AND seq>? ORDER BY seq"
        params: list[Any] = [project_id, after_seq]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    # ---------- Checkpoint（按项目 + 运行） ----------

    def save_checkpoint(
        self,
        *,
        project_id: str,
        run_id: str,
        checkpoint_id: str,
        state: dict,
        processed_event_seq: int = 0,
    ) -> dict:
        self._require_project(project_id)
        with self._tx() as conn:
            if conn.execute("SELECT 1 FROM task_runs WHERE project_id=? AND run_id=?", (project_id, run_id)).fetchone() is None:
                raise NotFound("run_id")
            conn.execute(
                """INSERT OR REPLACE INTO platform_checkpoints
                   (project_id, run_id, checkpoint_id, state_json, processed_event_seq, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (project_id, run_id, checkpoint_id, _dumps(state), processed_event_seq, _now()),
            )
        return self.get_checkpoint(project_id, run_id, checkpoint_id)  # type: ignore[return-value]

    def get_checkpoint(self, project_id: str, run_id: str, checkpoint_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM platform_checkpoints
                   WHERE project_id=? AND run_id=? AND checkpoint_id=?""",
                (self._require_project(project_id), run_id, checkpoint_id),
            ).fetchone()
            return dict(row) if row else None

    def latest_checkpoint(self, project_id: str, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM platform_checkpoints
                   WHERE project_id=? AND run_id=? ORDER BY created_at DESC, checkpoint_id DESC LIMIT 1""",
                (self._require_project(project_id), run_id),
            ).fetchone()
            return dict(row) if row else None

    def list_checkpoints(self, project_id: str, run_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM platform_checkpoints
                   WHERE project_id=? AND run_id=? ORDER BY created_at, checkpoint_id""",
                (self._require_project(project_id), run_id),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- 恢复辅助 ----------

    def recover_run(self, project_id: str, run_id: str) -> dict:
        """恢复视图：返回运行信息、最新 checkpoint、未处理事件与执行尝试。"""
        run = self.get_run(project_id, run_id)
        if run is None:
            raise NotFound("run_id")
        cp = self.latest_checkpoint(project_id, run_id)
        processed_seq = int(cp["processed_event_seq"]) if cp else 0
        return {
            "run": run,
            "checkpoint": cp,
            "unprocessed_events": self.replay_project(project_id, after_seq=processed_seq),
            "attempts": self.list_attempts(project_id),
        }
