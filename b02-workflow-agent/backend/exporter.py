from __future__ import annotations

import json

from .workflow_definition import PSEUDOCODE, STAGES, TRANSITIONS


def export_run(run: dict, replay: dict, format: str) -> dict:
    if format == "json":
        return {"filename": f"{run['run_id']}_B02讨论流程.json", "mime": "application/json;charset=utf-8", "content": json.dumps({"run": run, "replay": replay, "stages": STAGES, "transitions": TRANSITIONS, "pseudocode": PSEUDOCODE}, ensure_ascii=False, indent=2)}
    if format != "markdown":
        raise ValueError("仅支持 JSON 或 Markdown 导出。")
    board = run["blackboard"]
    lines = [
        f"# B02 WorkflowAgent 运行报告：{run['run_id']}", "",
        f"- Idea：{run['idea']}", f"- 当前阶段：{run['stage']}", f"- 运行状态：{run['status']}",
        f"- 批判轮次：{run['round']} / {run['max_rounds']}", f"- 事件数：{len(run['events'])}",
        f"- 回放校验：{'通过' if replay['passed'] else '失败'}", "",
        "> 停止、暂停或等待人类均不等于共识通过；只有六人确认后才发布 R1。", "",
        "## Workflow 阶段", "", "| 阶段 | 名称 | 责任边界 | 动作 |", "|---|---|---|---|",
    ]
    lines.extend(f"| {stage['code']} {stage['id']} | {stage['name']} | {stage['owner']} | {stage['action']} |" for stage in STAGES)
    lines.extend(["", "## 阶段迁移表", "", "| 当前阶段 | 事件 | 守卫条件 | 下一状态 |", "|---|---|---|---|"])
    lines.extend(f"| {item['from']} | {item['event']} | {item['guard']} | {item['to']} |" for item in TRANSITIONS)
    lines.extend(["", "## 控制伪代码", "", "```text", PSEUDOCODE, "```", "", "## 观点与立场", ""])
    for claim in board["claims"]:
        lines.append(f"- {claim['claim_id']} · {claim['role']}：{claim['claim']}（证据：{claim['evidence']}）")
    lines.extend(["", "## 异议与分歧", ""])
    if not board["objections"]:
        lines.append("暂无异议记录。")
    for item in board["objections"]:
        lines.append(f"- {item['objection_id']} · {item['severity']} / {item['category']} · {item['status']}：{item['content']} 回应：{item.get('response') or '尚未回应'}；决议：{item.get('resolution_ref') or '无'}。")
    lines.extend(["", "## 未决事项", ""])
    lines.extend(f"- {item}" for item in board["open_questions"])
    if board["proposal_draft"]:
        lines.extend(["", "## Proposal", "", board["proposal_draft"]])
    if board["r1"]:
        lines.extend(["", "## 已确认 R1", "", f"确认人：{', '.join(board['r1']['confirmed_by'])}", ""])
        for requirement in board["r1"]["requirements"]:
            lines.append(f"- {requirement['req_id']}：{requirement['description']} 验收：{requirement['acceptance']}")
    lines.extend(["", "## 控制事件回放", "", "| 序号 | 事件 | 阶段 | 状态 | 轮次 |", "|---:|---|---|---|---:|"])
    lines.extend(f"| {event['sequence']} | {event['type']} | {event['after']['stage']} | {event['after']['status']} | {event['after']['round']} |" for event in run["events"])
    return {"filename": f"{run['run_id']}_B02讨论流程.md", "mime": "text/markdown;charset=utf-8", "content": "\n".join(lines)}
