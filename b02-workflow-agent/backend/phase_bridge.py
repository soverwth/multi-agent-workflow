"""阶段一到阶段二的产物桥接。

阶段一的 R1 是需求确认结果，阶段二的 B01 需要设计规格。
本模块只做结构化转换，不替代人工确认，也不生成领域实现细节：
已确认的 R1 需求会成为设计规格中的 requirements，按需求生成最小
design_entries，后续团队可以在 B01 前替换为更完整的设计规格。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .errors import WorkflowError


def _slug(value: str) -> str:
    """生成符合 B01 计划版本契约的 ASCII 项目标识。"""
    source = value.strip().lower()
    ascii_part = "".join(ch if (ch.isascii() and ch.isalnum()) else "-" for ch in source)
    slug = re.sub(r"-+", "-", ascii_part).strip("-")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}" if slug else f"project-{digest}"


def r1_to_design_spec(run: dict[str, Any]) -> dict[str, Any]:
    """把已确认的讨论运行转换成 B01 可消费的设计规格。

    该转换保留来源运行编号和确认人，便于后续任务追溯到阶段一。
    未完成 R1 的运行一律拒绝进入第二阶段。
    """

    board = run.get("blackboard") or {}
    r1 = board.get("r1") or {}
    if run.get("status") != "COMPLETED" or r1.get("status") != "CONFIRMED":
        raise WorkflowError("只有已完成并发布 R1 的阶段一运行才能进入设计规格阶段。", 409)
    raw_requirements = r1.get("requirements") or []
    if not raw_requirements:
        raise WorkflowError("R1 没有可转换的需求。", 400)

    project_id = _slug(str(run.get("idea") or "project"))
    spec_version = f"S1-{run['run_id']}-v1.0"
    contract_version = f"C1-{run['run_id']}-v1.0"
    requirements: list[dict[str, Any]] = []
    design_entries: list[dict[str, Any]] = []
    for item in raw_requirements:
        req_id = str(item.get("req_id") or "").strip()
        title = str(item.get("description") or req_id).strip()
        if not req_id or not title or not item.get("acceptance"):
            raise WorkflowError(f"R1 需求 {req_id or '<unknown>'} 缺少标题或验收条件。", 400)
        acceptance = item["acceptance"]
        if isinstance(acceptance, str):
            acceptance = [acceptance]
        constraints = ["来源于阶段一已确认 R1"]
        if str(run.get("constraints") or "").strip():
            constraints.append(str(run["constraints"]).strip())
        requirements.append({
            "req_id": req_id,
            "title": title,
            "description": title,
            "priority": str(item.get("priority") or "must").lower(),
            "acceptance": list(acceptance),
            "constraints": constraints,
        })
        design_entries.append({
            "design_id": f"DS-{req_id}",
            "module": f"mvp/{_slug(title)}",
            "req_refs": [req_id],
            "contract_refs": [],
            "test_refs": [f"TC-{req_id}-ACCEPTANCE"],
            "rule": f"实现并验证 {title}；具体技术方案由设计规格评审补充。",
        })

    return {
        "schema_version": "b01.spec.v1",
        "generation_source": str(r1.get("generation_source") or "unknown"),
        "spec_version": spec_version,
        "contract_version": contract_version,
        "project_id": project_id,
        "title": str(run.get("idea") or project_id),
        "requirements": requirements,
        "design_entries": design_entries,
        "contract": {
            "contract_version": contract_version,
            "operations": [],
            "errors": {},
            "field_bounds": {},
            "response_envelope": {},
        },
        "phase1_source": {
            "run_id": run["run_id"],
            "r1_version": r1.get("version", "R1"),
            "generation_source": str(r1.get("generation_source") or "unknown"),
            "confirmed_by": list(r1.get("confirmed_by") or []),
        },
    }
