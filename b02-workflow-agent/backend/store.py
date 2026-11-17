from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .errors import WorkflowError


class BlackboardStore:
    """B03 boundary: durable blackboard snapshots and ordered control events."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, run_id: str) -> Path:
        if not run_id.startswith("RUN-") or not run_id.replace("-", "").isalnum():
            raise WorkflowError("运行编号不合法。", 404)
        return self.data_dir / f"{run_id}.json"

    def save(self, run: dict) -> None:
        with self._lock:
            path = self._path(run["run_id"])
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, path)

    def get(self, run_id: str) -> dict:
        path = self._path(run_id)
        if not path.exists():
            raise WorkflowError("讨论运行不存在。", 404)
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        runs = []
        for path in self.data_dir.glob("RUN-*.json"):
            run = json.loads(path.read_text(encoding="utf-8"))
            runs.append({
                "run_id": run["run_id"], "idea": run["idea"], "stage": run["stage"],
                "status": run["status"], "round": run["round"], "updated_at": run["updated_at"],
            })
        return sorted(runs, key=lambda item: item["updated_at"], reverse=True)
