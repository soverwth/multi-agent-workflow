from __future__ import annotations

from .errors import AgentExecutionError, WorkflowError

ROLES = ("产品经理", "用户研究员", "技术架构师", "质疑者")
MEMBERS = ("成员 A", "成员 B", "成员 C", "成员 D", "成员 E", "成员 F")


class LocalAgentGateway:
    """B04 test adapter. It supplies role outputs but never controls stage transitions."""

    def frame(self, idea: str, constraints: str) -> dict:
        return {
            "problem": f"围绕“{idea}”形成可评审的 MVP 建设方案。",
            "assumptions": ["目标用户与真实使用频率尚待验证", "团队优先实现可验证的最小流程"],
            "open_questions": ["哪些价值取舍需要由六名成员最终确认？"],
            "constraints": constraints,
        }

    def independent(self, idea: str, constraints: str, scenario: str) -> list[dict]:
        if scenario == "agent_failure":
            raise AgentExecutionError("B04 角色调用失败：已模拟模型超时，未生成任何观点。")
        content = {
            "产品经理": "先把核心价值、MVP 范围和非目标写清楚，避免未经评审持续扩张功能。",
            "用户研究员": "目标用户、场景频率和痛点真实性仍需要用户证据，不能把角色推测写成事实。",
            "技术架构师": "采用明确接口和可替换适配器实现基础流程，优先控制依赖、成本与可测试性。",
            "质疑者": "需要主动检查隐私、权限、失败路径和范围假设，防止多个角色互相附和形成假共识。",
        }
        return [{
            "role": role, "claim": content[role],
            "reason": f"该观点只来自{role}的专业职责，首轮未读取其他角色答案。",
            "evidence": "当前仅有用户输入，无外部事实证据。",
            "assumptions": ["输入想法具有进一步评审价值"],
            "impact": "影响 Proposal 的范围、风险与验证计划。",
        } for role in ROLES]

    def critique(self, blackboard: dict, round_number: int, scenario: str) -> dict:
        objections = blackboard["objections"]
        stances = []
        new_objections = []
        if round_number > 1 and scenario == "normal":
            resolved_ids = [item["objection_id"] for item in objections if item["status"] in ("open", "responded")]
            stances = [{"role": role, "stance": "Agree", "reason": "上一轮异议已回应，当前无新增阻断理由。"} for role in ROLES]
            return {"objections": [], "resolved_ids": resolved_ids, "stances": stances}
        else:
            claims = blackboard["claims"]
            if scenario == "value_conflict":
                new_objections.append({
                    "raised_by": "质疑者", "target_id": claims[0]["claim_id"], "category": "value",
                    "content": "功能完整性与隐私、成本之间存在需要人类选择的价值冲突，不能由模型投票代替。",
                    "severity": "high", "evidence": "当前规格没有给出团队的价值优先级。", "status": "open",
                })
            elif scenario == "budget_exhaustion":
                new_objections.append({
                    "raised_by": "质疑者", "target_id": claims[0]["claim_id"], "category": "tradeoff",
                    "content": f"第 {round_number} 轮仍出现新的范围与成本权衡，需要进一步证据。",
                    "severity": "medium", "evidence": "尚无新调研证据。", "status": "open",
                })
            else:
                new_objections.extend([
                    {
                        "raised_by": "质疑者", "target_id": claims[0]["claim_id"], "category": "fact",
                        "content": "核心价值成立所需的用户证据尚未提供，需要把未知项保留到报告。",
                        "severity": "medium", "evidence": "当前没有用户访谈或检索证据。", "status": "open",
                    },
                    {
                        "raised_by": "技术架构师", "target_id": claims[-1]["claim_id"], "category": "tradeoff",
                        "content": "需要明确基础版的失败处理和实现边界，否则验收成本不可估计。",
                        "severity": "medium", "evidence": "设计约束中尚未列出完整失败矩阵。", "status": "open",
                    },
                ])
            stances = [{"role": role, "stance": "Disagree" if role == "质疑者" else "Conditional", "reason": "需要回应本轮具体异议并补充验证条件。"} for role in ROLES]
        return {"objections": new_objections, "stances": stances}

    def draft_proposal(self, blackboard: dict) -> str:
        return (
            f"# Proposal：{blackboard['idea']}\n\n"
            "## 背景与问题\n形成范围明确、可验证、保留分歧的最小建设方案。\n\n"
            "## 目标用户与价值\n目标用户及使用频率仍需验证；首期价值以可观察的核心流程为准。\n\n"
            "## MVP 范围与非目标\n仅纳入经评审的核心能力；证据不足或未经确认的功能不进入基线。\n\n"
            "## 技术方案概要\n使用职责明确的角色适配器、结构化黑板和受控 Workflow；模型输出不代替质量证据。\n\n"
            "## 风险与成功指标\n重点检查隐私、权限、成本、失败路径；以规定用例和人工评审记录作为阶段证据。"
        )

    def review_proposal(self, blackboard: dict) -> list[dict]:
        unresolved_high = any(item["status"] == "open" and item["severity"] == "high" for item in blackboard["objections"])
        return [{
            "role": role,
            "stance": "Pending" if unresolved_high else "Agree",
            "reason": "仍有高影响异议，暂不审阅通过。" if unresolved_high else "已阅读 Proposal、未决项和保留分歧，同意提交人类需求确认。",
        } for role in ROLES]


class ConsensusEvaluator:
    """B06 boundary: returns quality judgments; B02 alone decides what control action follows."""

    def evaluate_discussion(self, blackboard: dict, round_number: int) -> dict:
        open_items = [item for item in blackboard["objections"] if item["status"] == "open"]
        high = [item for item in open_items if item["severity"] == "high"]
        current = [item for item in open_items if item["round"] == round_number]
        needs_human = any(item["category"] == "value" for item in high)
        return {
            "open_count": len(open_items), "high_count": len(high), "new_count": len(current),
            "needs_human": needs_human, "can_proceed": not open_items,
            "reason": "存在需要人类裁决的高影响价值分歧。" if needs_human else (f"仍有 {len(open_items)} 项开放异议。" if open_items else "开放异议均已处理，可进入 Proposal 审阅。"),
            "stance_counts": self._stance_counts(blackboard["stances"]),
        }

    def evaluate_proposal(self, blackboard: dict) -> dict:
        signoffs = blackboard.get("signoffs", [])
        pending = [item for item in signoffs if item["stance"] in ("Pending", "Disagree")]
        high = [item for item in blackboard["objections"] if item["status"] == "open" and item["severity"] == "high"]
        complete_roles = {item["role"] for item in signoffs} == set(ROLES)
        return {
            "can_proceed": not pending and not high and complete_roles and bool(blackboard.get("proposal_draft")),
            "needs_human": bool(high),
            "reason": "角色审阅完成且无阻断异议。" if not pending and not high and complete_roles else "Proposal 仍有未审阅、反对或高影响异议。",
            "signoff_count": len(signoffs),
        }

    @staticmethod
    def _stance_counts(stances: list[dict]) -> dict:
        result = {"Agree": 0, "Conditional": 0, "Disagree": 0, "Pending": 0}
        for item in stances:
            result[item["stance"]] = result.get(item["stance"], 0) + 1
        return result


class RequirementGateway:
    """B01 boundary: prepare a draft and enforce the independent six-person confirmation gate."""

    def prepare_draft(self, blackboard: dict) -> dict:
        return {
            "version": "R-draft", "status": "IN_REVIEW",
            "requirements": [
                {"req_id": "REQ-01", "description": "核心流程必须限定在已评审的 MVP 范围内。", "priority": "Must", "acceptance": "范围外功能不进入当前基线。", "status": "IN_REVIEW"},
                {"req_id": "REQ-02", "description": "关键假设、风险和未决分歧必须保留并可追溯。", "priority": "Must", "acceptance": "报告可查看未决项、少数意见及处理状态。", "status": "IN_REVIEW"},
                {"req_id": "REQ-03", "description": "核心行为的验收条件必须可观察。", "priority": "Must", "acceptance": "每项需求均有明确验收条件并经六人确认。", "status": "IN_REVIEW"},
            ],
            "open_questions": list(blackboard["open_questions"]),
            "decision_refs": [item["decision_id"] for item in blackboard["decisions"]],
        }

    @staticmethod
    def publish(draft: dict, members: list[str]) -> dict:
        if len(members) != 6 or set(members) != set(MEMBERS):
            raise WorkflowError("R1 发布必须由六名成员分别确认，沉默或 Pending 不算赞同。")
        requirements = draft.get("requirements", [])
        if not requirements or any(not item.get("acceptance") or not item.get("req_id") for item in requirements):
            raise WorkflowError("需求草案缺少编号或验收条件，不能发布 R1。")
        confirmed = list(requirements)
        for item in confirmed:
            item["status"] = "CONFIRMED"
        return {"version": "R1", "status": "CONFIRMED", "requirements": confirmed, "confirmed_by": list(members)}
