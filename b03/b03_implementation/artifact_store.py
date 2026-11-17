"""artifact_store：版本化、只追加的产物存储。

职责边界：
- Artifacts 只追加；同一 (task_id, attempt_id, version) 唯一。
- 每版绑定 content_hash、candidate_commit、input_snapshot_ref。
- 读取接口只返回对当前快照版本有效的产物；无效版本不返回、不静默降级。
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from .config import BLACKBOARD_DB
from .errors import InvalidSnapshot, NotFound


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    task_id: str
    attempt_id: str
    version: str
    snapshot_ref: str


class ArtifactStore:
    """与 BlackboardStore 共用黑板数据库，但职责独立。"""

    def __init__(self, db_path=BLACKBOARD_DB, blackboard=None):
        self.db_path = str(db_path)
        self.blackboard = blackboard
        self.initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        ddl = """
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
        CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);
        CREATE INDEX IF NOT EXISTS idx_artifacts_snapshot ON artifacts(snapshot_ref);
        """
        with self._connect() as conn:
            conn.executescript(ddl)
            conn.commit()

    def put_artifact(
        self,
        *,
        task_id: str,
        attempt_id: str,
        version: str,
        content_hash: str,
        snapshot_ref: str,
        candidate_commit: str | None = None,
        write_scope: str | None = None,
    ) -> ArtifactRef:
        artifact_id = _uuid()
        with self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO artifacts
                       (artifact_id, task_id, attempt_id, version, content_hash,
                        candidate_commit, write_scope, snapshot_ref, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        artifact_id,
                        task_id,
                        attempt_id,
                        version,
                        content_hash,
                        candidate_commit,
                        write_scope,
                        snapshot_ref,
                        _now(),
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise InvalidSnapshot(f"产物版本重复或快照无效: {exc}") from exc
        return ArtifactRef(
            artifact_id=artifact_id,
            task_id=task_id,
            attempt_id=attempt_id,
            version=version,
            snapshot_ref=snapshot_ref,
        )

    def get_artifact(self, artifact_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
            return dict(row) if row else None

    def get_artifacts_for_task(
        self,
        task_id: str,
        *,
        valid_snapshot_ref: str,
    ) -> list[dict]:
        """只返回绑定该快照且快照仍有效的产物。"""
        if self.blackboard is not None and not self.blackboard.verify_snapshot_still_valid(valid_snapshot_ref):
            raise InvalidSnapshot(valid_snapshot_ref)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM artifacts
                   WHERE task_id=? AND snapshot_ref=?
                   ORDER BY version, created_at""",
                (task_id, valid_snapshot_ref),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_versions(self, task_id: str) -> list[str]:
        """列出任务全部历史版本（含失效），用于追溯；不代表可读。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT version FROM artifacts WHERE task_id=? ORDER BY created_at", (task_id,)
            ).fetchall()
            return [r["version"] for r in rows]

    def assert_artifact_exists(self, artifact_id: str) -> dict:
        artifact = self.get_artifact(artifact_id)
        if artifact is None:
            raise NotFound(artifact_id)
        return artifact
