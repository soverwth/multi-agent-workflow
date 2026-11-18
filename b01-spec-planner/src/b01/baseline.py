"""T01 基线登记：校验、登记并冻结 R1/S1/C1 与任务计划。

默认要求六人确认齐全；团队文档中的示例没有真实确认记录，因此 CLI 必须显式
传入 --allow-reference 才能生成参考基线，且输出状态会标记为 REFERENCE_FROZEN。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .design import C1_OPERATIONS, REQUIRED_REQUIREMENTS
from .plan_validator import validate_plan

BASELINE_ARTIFACTS = {
    "r1": "docs/r1.json",
    "s1": "docs/s1.json",
    "c1": "docs/c1.json",
    "plan": "docs/plan.json",
    "traceability": "docs/traceability.json",
}


class BaselineError(ValueError):
    """T01 冻结前置条件不满足。"""


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _human_confirmation_ok(r1: dict[str, Any]) -> bool:
    confirmation = r1.get("human_confirmation") or {}
    if r1.get("status") != "CONFIRMED" or confirmation.get("status") != "CONFIRMED":
        return False
    reviewers = confirmation.get("reviewers") or {}
    return all(reviewers.get(block) == "CONFIRMED" for block in ("B01", "B02", "B03", "B04", "B05", "B06"))


def register_baseline(
    plan: dict[str, Any],
    contract: dict[str, Any],
    r1: dict[str, Any],
    s1: dict[str, Any],
    *,
    allow_reference: bool = False,
    artifacts: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """生成 T01 基线登记清单；任一门槛不满足时抛出 BaselineError。"""
    reasons: list[str] = []
    warnings: list[str] = []

    plan_report = validate_plan(plan, REQUIRED_REQUIREMENTS)
    reasons.extend(f"plan: {reason}" for reason in plan_report.reasons)

    if contract.get("contract_version") != plan.get("contract_version"):
        reasons.append("contract: contract_version does not match plan")
    operations = contract.get("operations")
    if not isinstance(operations, list):
        reasons.append("contract: operations must be a list")
        operations = []
    actual_names = [op.get("name") for op in operations if isinstance(op, dict)]
    expected_names = [op["name"] for op in C1_OPERATIONS]
    if actual_names != expected_names:
        reasons.append(f"contract: operations must be {expected_names}, got {actual_names}")
    errors = contract.get("errors")
    if not isinstance(errors, dict) or not errors:
        reasons.append("contract: errors must be a non-empty object")

    r1_requirements = {item.get("req_id") for item in r1.get("requirements", []) if isinstance(item, dict)}
    if r1_requirements != set(REQUIRED_REQUIREMENTS):
        reasons.append(f"r1: requirements must cover {REQUIRED_REQUIREMENTS}")
    if r1.get("blocking_open_questions"):
        reasons.append("r1: blocking open questions must be closed before freeze")

    if s1.get("spec_version") != plan.get("spec_version"):
        reasons.append("s1: spec_version does not match plan")

    confirmed = _human_confirmation_ok(r1)
    if not confirmed:
        if allow_reference:
            warnings.append("六人确认未完成：输出为参考基线，不得用于真实任务派发。")
        else:
            reasons.append("r1: six-person human confirmation is not complete; use --allow-reference only for reference runs")

    checksums: dict[str, str] = {}
    root = _package_root()
    for logical_name, relative_path in BASELINE_ARTIFACTS.items():
        if artifacts is not None:
            data = artifacts.get(logical_name)
            if data is None:
                reasons.append(f"artifacts: missing inline artifact {logical_name}")
                continue
            checksums[logical_name] = sha256_bytes(data)
            continue
        path = root / relative_path
        if not path.is_file():
            reasons.append(f"artifacts: missing file {relative_path}")
            continue
        checksums[logical_name] = sha256_bytes(path.read_bytes())

    if reasons:
        raise BaselineError("T01 冻结失败：\n- " + "\n- ".join(reasons))

    return {
        "status": "FROZEN" if confirmed else "REFERENCE_FROZEN",
        "task_id": "T01",
        "project_id": plan.get("project_id"),
        "spec_version": plan.get("spec_version"),
        "contract_version": plan.get("contract_version"),
        "plan_version": plan.get("plan_version"),
        "requirements_version": r1.get("requirements_version"),
        "approved_ref": (
            (r1.get("human_confirmation") or {}).get("approval_ref")
            if confirmed
            else "REFERENCE_EXAMPLE_PENDING_HUMAN_CONFIRMATION"
        ),
        "file_checksums": checksums,
        "contract_test_ids": sorted(
            {
                test_id
                for task in plan["tasks"]
                if task.get("task_id") in {"T04", "T09"}
                for test_id in task.get("required_test_ids", [])
            }
        ),
        "topological_order": plan_report.topological_order,
        "open_questions": [item.get("id") for item in r1.get("non_blocking_open_questions", [])],
        "warnings": warnings,
    }
