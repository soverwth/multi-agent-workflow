"""B02 任务编排 HTTP 接口（D15/D16）。

接口清单见 docs/TASK_ORCHESTRATION.md §3。本模块只做“HTTP ↔ 编排器”的参数适配：

- 校验请求体与查询参数；
- 把 `WorkflowError` 映射成合适的 HTTP 状态码；
- 不实现任何调度/状态规则（那属于 `task_orchestrator`）。

默认执行器与质量门由 `default_stack()` 延迟装配：
- 执行：B04 `b04.gateway.TaskExecutionGateway`（mock 模式，确定性）。
- 验收：B06 `multiagent_quality.task_gate.review_task`。
若这些工作块不可导入，则回退到编排器内置的显式占位实现（结果会标记 simulated）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .errors import WorkflowError
from .task_orchestrator import TaskOrchestrationError, TaskOrchestrator

REPO_ROOT = Path(__file__).resolve().parents[2]


def _ensure_blocks_on_path() -> None:
    """允许在未安装包时从仓库根目录直接运行。"""
    for relative in ("b01-spec-planner/src", "b03", "b04-agent-integration/src", "b06-quality-consensus"):
        path = REPO_ROOT / relative
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))


def default_stack(db_path: Path, *, execution_mode: str = "mock", scenario: dict[str, Any] | None = None):
    """装配 (store, orchestrator)；失败时抛出 WorkflowError，由调用方决定是否回退。"""
    _ensure_blocks_on_path()
    try:
        from b03_implementation.task_state import TaskStateStore  # type: ignore[import-not-found]
    except ModuleNotFoundError as error:
        raise WorkflowError(f"B03 任务状态库不可用: {error}", 500) from error
    store = TaskStateStore(db_path)
    executor = None
    reviewer = None
    try:
        from b04.gateway import TaskExecutionGateway  # type: ignore[import-not-found]

        gateway = TaskExecutionGateway(mode=execution_mode, scenario=scenario)
        executor = gateway
    except ModuleNotFoundError:
        executor = None
    try:
        from multiagent_quality.task_gate import review_task  # type: ignore[import-not-found]

        reviewer = review_task
    except ModuleNotFoundError:
        reviewer = None
    return store, TaskOrchestrator(store, executor=executor, reviewer=reviewer)


class TaskApi:
    """把编排器包装成 HTTP 友好的方法集合。"""

    def __init__(
        self,
        db_path: Path,
        *,
        orchestrator: TaskOrchestrator | None = None,
        execution_mode: str = "mock",
        scenario: dict[str, Any] | None = None,
    ):
        if orchestrator is not None:
            self.orchestrator = orchestrator
            self.store = orchestrator.store
            self.execution_mode = execution_mode
        else:
            self.store, self.orchestrator = default_stack(
                db_path, execution_mode=execution_mode, scenario=scenario
            )
            self.execution_mode = execution_mode
        self.db_path = Path(db_path)

    # ---------- 计划 ----------

    def load_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan = payload.get("plan")
        plan_path = payload.get("plan_path")
        if plan is None and plan_path:
            path = Path(str(plan_path))
            if not path.is_absolute():
                path = REPO_ROOT / path
            if not path.is_file():
                raise WorkflowError(f"计划文件不存在: {plan_path}", 400)
            try:
                plan = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise WorkflowError(f"计划文件不是合法 JSON: {error}", 400) from error
        if not isinstance(plan, dict):
            raise WorkflowError("请求必须包含 plan 对象或 plan_path。", 400)
        stored = self.orchestrator.load_plan(plan)
        document = self.store.get_plan_document(stored["plan_id"]) or {}
        return {
            "plan": {
                **stored,
                "input_snapshot": document.get("input_snapshot"),
                "spec_version": document.get("spec_version", stored.get("spec_version")),
                "contract_version": document.get("contract_version", stored.get("contract_version")),
            }
        }

    def list_plans(self) -> dict[str, Any]:
        return {"plans": self.store.list_plans()}

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        stored = self.store.get_plan(plan_id)
        if stored is None:
            raise WorkflowError(f"未知计划: {plan_id}", 404)
        document = self.store.get_plan_document(plan_id) or {}
        return {"plan": {**stored, "document": document}}

    # ---------- 运行 ----------

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan_id = payload.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id.strip():
            raise WorkflowError("请求必须包含 plan_id。", 400)
        run_id = payload.get("run_id")
        if run_id is not None and not isinstance(run_id, str):
            raise WorkflowError("run_id 必须是字符串。", 400)
        return {"run": self.orchestrator.create_run(plan_id, run_id=run_id)}

    def create_run_from_spec(self, payload: dict[str, Any]) -> dict[str, Any]:
        """设计规格 → B01 计划 → B02 运行，作为阶段二统一入口。"""
        _ensure_blocks_on_path()
        try:
            from b01.spec_input import load_spec, load_spec_from_text, normalize_spec  # type: ignore[import-not-found]
            from b01.dynamic_planner import build_plan_from_spec, next_plan_version  # type: ignore[import-not-found]
        except ModuleNotFoundError as error:
            raise WorkflowError(f"B01 规格规划器不可用: {error}", 500) from error

        spec_path = payload.get("spec_path")
        spec_text = payload.get("spec_text")
        raw_spec = payload.get("spec")
        try:
            if spec_path:
                path = Path(str(spec_path))
                if not path.is_absolute():
                    path = REPO_ROOT / path
                if not path.is_file():
                    raise WorkflowError(f"设计规格文件不存在: {spec_path}", 400)
                spec = load_spec(path)
            elif isinstance(spec_text, str) and spec_text.strip():
                spec = load_spec_from_text(spec_text)
            elif isinstance(raw_spec, dict):
                spec = normalize_spec(raw_spec, source_format="json")
            else:
                raise WorkflowError("请求必须包含 spec_path、spec_text 或 spec。", 400)
        except WorkflowError:
            raise
        except (TypeError, ValueError) as error:
            raise WorkflowError(f"设计规格无效: {error}", 400) from error

        plan = build_plan_from_spec(spec)
        if isinstance(payload.get("source_metadata"), dict):
            plan["phase1_source"] = dict(payload["source_metadata"])
        # 同一规格重复点击“从设计规格启动”时复用已有版本；规格真的变化时递增版本。
        existing = self.store.find_plan_by_version(plan["plan_version"])
        if existing is not None:
            existing_document = self.store.get_plan_document(existing["plan_id"])
            existing_snapshot = (existing_document or {}).get("input_snapshot") or {}
            if existing_snapshot.get("spec_sha256") == plan["input_snapshot"].get("spec_sha256"):
                plan = existing_document or plan
                stored = existing
            else:
                # 只递增一档不够：同一项目第三次、第四次桥接时，v1.1 可能已被占用。
                # 必须推进到第一个尚未登记的版本，否则 register_plan 会抛 409。
                candidate = next_plan_version(plan["plan_version"], spec.project_id)
                while self.store.find_plan_by_version(candidate) is not None:
                    candidate = next_plan_version(candidate, spec.project_id)
                plan["plan_version"] = candidate
                stored = self.orchestrator.load_plan(plan)
        else:
            stored = self.orchestrator.load_plan(plan)
        run = self.orchestrator.create_run(stored["plan_id"], run_id=payload.get("run_id"))
        if payload.get("auto_run"):
            raw_steps = payload.get("max_steps", len(plan["tasks"]) * 3 + 20)
            try:
                max_steps = int(raw_steps)
            except (TypeError, ValueError) as error:
                raise WorkflowError("max_steps 必须是整数。", 400) from error
            run = self.orchestrator.run(run["run_id"], max_steps=max_steps)
        source_document = spec.as_dict()
        if isinstance(payload.get("source_metadata"), dict):
            source_document["phase1_source"] = dict(payload["source_metadata"])
        return {
            "plan": {**stored, "task_count": len(plan["tasks"])},
            "run": run,
            "source": source_document,
        }

    def list_runs(self) -> dict[str, Any]:
        return {"runs": self.store.list_runs()}

    def get_run(self, run_id: str) -> dict[str, Any]:
        return {"run": self.orchestrator.snapshot(run_id)}

    def step(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.orchestrator.step(run_id)

    def run(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("max_steps", 200)
        try:
            max_steps = int(raw)
        except (TypeError, ValueError) as error:
            raise WorkflowError("max_steps 必须是整数。", 400) from error
        if max_steps < 1:
            raise WorkflowError("max_steps 必须大于 0。", 400)
        return self.orchestrator.run(run_id, max_steps=max_steps)

    def events(self, run_id: str, query: dict[str, list[str]]) -> dict[str, Any]:
        after_raw = (query.get("after") or [None])[0]
        after: int | None = None
        if after_raw is not None:
            try:
                after = int(after_raw)
            except ValueError as error:
                raise WorkflowError("after 必须是整数序号。", 400) from error
        limit_raw = (query.get("limit") or ["500"])[0]
        try:
            limit = int(limit_raw)
        except ValueError as error:
            raise WorkflowError("limit 必须是整数。", 400) from error
        if not 1 <= limit <= 5000:
            raise WorkflowError("limit 必须在 1—5000 之间。", 400)
        return self.orchestrator.events(run_id, after=after, limit=limit)

    def dag(self, run_id: str) -> dict[str, Any]:
        return {"dag": self.orchestrator.dag(run_id)}

    def replay(self, run_id: str) -> dict[str, Any]:
        return {"replay": self.orchestrator.replay(run_id)}

    def restore(self, run_id: str) -> dict[str, Any]:
        return {"restore": self.store.restore_run(run_id)}

    def describe(self) -> dict[str, Any]:
        return {
            "block": "B02",
            "controller": "task_orchestrator",
            "execution_mode": self.execution_mode,
            "db": str(self.db_path),
            "contract": "docs/TASK_ORCHESTRATION.md#3",
        }
