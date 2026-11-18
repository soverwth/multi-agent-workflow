"""B01 plan_validator：任务包结构、需求覆盖、产物归属与 DAG 校验。

输出兼容 B06 只读计划检查的核心结论（ok / reasons / topological_order），
并额外检查 B01 职责范围内的标准字段、关键链和规定测试覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .design import PROJECT_ID, REQUIRED_REQUIREMENTS
from .task_planner import topological_sort

REQUIRED_TASK_FIELDS = (
    "role_id",
    "block_id",
    "task_id",
    "project_id",
    "req_refs",
    "design_refs",
    "spec_version",
    "contract_version",
    "goal",
    "inputs",
    "outputs",
    "depends_on",
    "capability",
    "write_scope",
    "acceptance",
    "required_test_ids",
    "priority",
    "timeout",
    "retry_budget",
    "escalation_target",
)

STRING_FIELDS = (
    "role_id",
    "block_id",
    "task_id",
    "project_id",
    "spec_version",
    "contract_version",
    "goal",
    "capability",
    "priority",
    "escalation_target",
)

LIST_FIELDS = (
    "req_refs",
    "design_refs",
    "inputs",
    "outputs",
    "depends_on",
    "write_scope",
    "acceptance",
    "required_test_ids",
)

ALLOWED_CAPABILITIES = {"orchestrator", "DB-01", "BE-01", "FE-01", "QA-01"}
CRITICAL_CHAIN = ["T01", "T02", "T03", "T04", "T05", "T10", "T11"]


@dataclass
class ValidationReport:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    topological_order: list[str] = field(default_factory=list)
    covered_requirements: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "topological_order": self.topological_order,
            "covered_requirements": self.covered_requirements,
        }


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unique_strings(value: Any, *, allow_empty: bool = False) -> bool:
    if not isinstance(value, list):
        return False
    if not value and not allow_empty:
        return False
    seen: set[str] = set()
    for item in value:
        if not _nonempty_text(item):
            return False
        if item in seen:
            return False
        seen.add(item)
    return True


def validate_plan(
    plan: dict[str, Any],
    required_requirements: Iterable[str] | None = None,
) -> ValidationReport:
    reasons: list[str] = []
    warnings: list[str] = []
    report = ValidationReport(ok=False, reasons=reasons, warnings=warnings)

    if not isinstance(plan, dict):
        reasons.append("plan must be an object")
        return report

    required = list(required_requirements or plan.get("required_requirements") or REQUIRED_REQUIREMENTS)
    if not _unique_strings(required):
        reasons.append("required_requirements must be a unique non-empty string list")
        required = list(dict.fromkeys(required)) if isinstance(required, list) else []

    spec_version = plan.get("spec_version")
    contract_version = plan.get("contract_version")
    plan_version = plan.get("plan_version")
    if not _nonempty_text(spec_version):
        reasons.append("plan.spec_version must be a non-empty string")
    if not _nonempty_text(contract_version):
        reasons.append("plan.contract_version must be a non-empty string")
    if not _nonempty_text(plan_version):
        reasons.append("plan.plan_version must be a non-empty string")

    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        reasons.append("plan.tasks must be a non-empty list")
        return report

    registry: dict[str, dict[str, Any]] = {}
    output_owner: dict[str, str] = {}
    covered: set[str] = set()

    for index, task in enumerate(tasks):
        label = f"tasks[{index}]"
        if not isinstance(task, dict):
            reasons.append(f"{label} must be an object")
            continue

        for name in REQUIRED_TASK_FIELDS:
            if name not in task:
                reasons.append(f"{label}: missing field {name}")

        tid = task.get("task_id")
        if not _nonempty_text(tid):
            reasons.append(f"{label}: invalid task_id")
            continue
        label = str(tid)
        if tid in registry:
            reasons.append(f"{label}: duplicate task_id")
            continue
        registry[tid] = task

        for name in STRING_FIELDS:
            if name in task and not _nonempty_text(task[name]):
                reasons.append(f"{label}: {name} must be a non-empty string")

        for name in LIST_FIELDS:
            if name not in task:
                continue
            allow_empty = name == "depends_on"
            if not _unique_strings(task[name], allow_empty=allow_empty):
                reasons.append(f"{label}: {name} must be a unique string list" + ("" if allow_empty else " and non-empty"))

        if task.get("project_id") != plan.get("project_id", PROJECT_ID):
            reasons.append(f"{label}: project_id does not match plan")
        for version_field, expected in (("spec_version", spec_version), ("contract_version", contract_version)):
            if task.get(version_field) != expected:
                reasons.append(f"{label}: {version_field} does not match plan")

        refs = task.get("req_refs") if isinstance(task.get("req_refs"), list) else []
        unknown = sorted(set(refs) - set(required))
        if unknown:
            reasons.append(f"{label}: unknown requirements {unknown}")
        covered.update(refs)

        if task.get("capability") not in ALLOWED_CAPABILITIES:
            reasons.append(f"{label}: capability must be one of {sorted(ALLOWED_CAPABILITIES)}")

        timeout = task.get("timeout")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            reasons.append(f"{label}: timeout must be a positive integer")
        retry_budget = task.get("retry_budget")
        if not isinstance(retry_budget, int) or isinstance(retry_budget, bool) or retry_budget < 0:
            reasons.append(f"{label}: retry_budget must be a non-negative integer")

        for output in task.get("outputs") if isinstance(task.get("outputs"), list) else []:
            if output in output_owner:
                reasons.append(f"{label}: output has two owners: {output} (also {output_owner[output]})")
            else:
                output_owner[output] = label

    for req_id in required:
        if req_id not in covered:
            reasons.append(f"uncovered requirement: {req_id}")

    for tid, task in registry.items():
        for dep in task.get("depends_on") if isinstance(task.get("depends_on"), list) else []:
            if dep not in registry:
                reasons.append(f"{tid}: missing dependency {dep}")
            elif dep == tid:
                reasons.append(f"{tid}: self dependency")

    order: list[str] = []
    if not any("missing dependency" in reason or "self dependency" in reason for reason in reasons):
        try:
            order = topological_sort(registry.values())
        except ValueError as exc:
            reasons.append(str(exc))

    if order:
        positions = {tid: index for index, tid in enumerate(order)}
        for left, right in zip(CRITICAL_CHAIN, CRITICAL_CHAIN[1:]):
            if left in positions and right in positions and positions[left] >= positions[right]:
                reasons.append(f"critical chain violated: {left} must precede {right}")

    t01 = registry.get("T01")
    if t01 and t01.get("depends_on") != []:
        reasons.append("T01: must have no dependencies")

    t04 = registry.get("T04")
    if t04:
        t04_tests = set(t04.get("required_test_ids") or [])
        for test_id in ("TC-P01", "TC-P02", "TC-P03"):
            if test_id not in t04_tests:
                reasons.append(f"T04: required test missing {test_id}")

    t09 = registry.get("T09")
    if t09 and "TC-P02" not in set(t09.get("required_test_ids") or []):
        reasons.append("T09: required direct-call test TC-P02 missing")

    t10 = registry.get("T10")
    if t10:
        expected_deps = {"T03", "T04", "T05", "T06", "T07", "T08", "T09"}
        actual_deps = set(t10.get("depends_on") or [])
        missing = sorted(expected_deps - actual_deps)
        if missing:
            reasons.append(f"T10: missing dependencies {missing}")

    declared_order = plan.get("topological_order")
    if declared_order is not None and declared_order != order:
        warnings.append("plan.topological_order differs from recomputed order")

    report.ok = not reasons
    report.topological_order = order
    report.covered_requirements = sorted(covered)
    return report
