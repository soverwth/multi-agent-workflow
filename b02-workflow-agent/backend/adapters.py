from __future__ import annotations

import json

from .errors import AgentExecutionError, WorkflowError
from .llm import OpenAICompatibleClient

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
    """B01 boundary with an optional structured LLM and a local fallback.

    The fallback is intentionally domain-sensitive so the prototype remains
    useful without credentials.  When an OpenAI-compatible API is configured,
    the model supplies the requirements and the same validation gate still
    requires six independent human confirmations.
    """

    def __init__(self, llm_client: OpenAICompatibleClient | None = None):
        self.llm_client = llm_client or OpenAICompatibleClient()

    def prepare_draft(self, blackboard: dict) -> dict:
        if self.llm_client.enabled():
            return self._prepare_with_llm(blackboard)
        return self._prepare_locally(blackboard)

    def _prepare_with_llm(self, blackboard: dict) -> dict:
        system = (
            "你是软件工程需求分析 Agent。请把用户想法转换成可执行的 MVP 需求。"
            "只输出 JSON 对象，字段为 requirements 和 open_questions。"
            "requirements 必须是 2 到 8 项，每项包含 req_id、description、priority、"
            "acceptance 和 constraints。acceptance 必须是可观察的验收条件。"
        )
        user = {
            "idea": blackboard.get("idea", ""),
            "constraints": blackboard.get("constraints", ""),
            "problem": blackboard.get("problem", ""),
            "proposal": blackboard.get("proposal_draft", ""),
            "claims": blackboard.get("claims", []),
            "objections": blackboard.get("objections", []),
            "open_questions": blackboard.get("open_questions", []),
        }
        result = self.llm_client.complete_json(system=system, user=json.dumps(user, ensure_ascii=False))
        requirements = self._normalize_requirements(result.get("requirements"))
        return self._draft(requirements, blackboard, source="llm")

    def _prepare_locally(self, blackboard: dict) -> dict:
        idea = str(blackboard.get("idea") or "通用软件系统")
        normalized = idea.lower()
        if any(token in normalized for token in ("微信", "聊天", "社交", "即时消息", "通讯")):
            requirements = [
                {"req_id": "REQ-01", "description": "用户可以安全注册、登录并管理个人资料。", "priority": "Must", "acceptance": ["注册和登录成功后生成会话", "错误凭据不会建立会话"]},
                {"req_id": "REQ-02", "description": "用户可以搜索、添加和管理联系人关系。", "priority": "Must", "acceptance": ["联系人搜索结果可分页", "重复添加不会产生重复关系"]},
                {"req_id": "REQ-03", "description": "联系人之间可以发送、接收并查看消息。", "priority": "Must", "acceptance": ["消息发送后可在会话中查询", "消息失败时返回可识别错误"]},
                {"req_id": "REQ-04", "description": "系统需要提供消息隐私、举报和内容安全边界。", "priority": "Should", "acceptance": ["未授权用户不能读取他人会话", "举报记录可追溯"]},
            ]
        elif any(token in normalized for token in ("失物", "招领", "物品", "认领")):
            requirements = [
                {"req_id": "REQ-01", "description": "用户可以发布带图片、位置和时间的物品信息。", "priority": "Must", "acceptance": ["缺失必要字段时拒绝发布", "发布记录可查询"]},
                {"req_id": "REQ-02", "description": "用户可以按关键词和状态搜索公开物品信息。", "priority": "Must", "acceptance": ["搜索结果支持分页", "已关闭记录不会出现在默认结果"]},
                {"req_id": "REQ-03", "description": "用户可以提交、审核和处理认领申请。", "priority": "Must", "acceptance": ["本人不能认领本人发布的物品", "申请状态变化可追踪"]},
                {"req_id": "REQ-04", "description": "系统需要保护联系方式和操作权限。", "priority": "Must", "acceptance": ["未授权用户不能查看私密字段", "越权操作返回明确错误"]},
                {"req_id": "REQ-05", "description": "认领完成后系统应通知相关用户并关闭物品状态。", "priority": "Should", "acceptance": ["认领结果会通知发布者和申请者", "完成后的物品不会再次进入待认领列表"]},
            ]
        elif any(token in normalized for token in ("预约", "设备", "借用", "实验室", "会议室")):
            requirements = [
                {"req_id": "REQ-01", "description": "管理员可以维护可预约资源及其可用状态。", "priority": "Must", "acceptance": ["资源编号唯一", "停用资源不能被预约"]},
                {"req_id": "REQ-02", "description": "用户可以查询时间段并提交资源预约。", "priority": "Must", "acceptance": ["冲突时间段不能重复预约", "预约状态可查询"]},
                {"req_id": "REQ-03", "description": "管理员可以审核、批准或拒绝预约申请。", "priority": "Must", "acceptance": ["审批结果记录操作人和时间", "拒绝时返回原因"]},
            ]
        else:
            requirements = [
                {"req_id": "REQ-01", "description": f"用户可以进入 {idea} 的核心业务流程。", "priority": "Must", "acceptance": ["核心流程可以从入口开始并到达完成状态"]},
                {"req_id": "REQ-02", "description": "系统可以保存核心业务数据并支持查询。", "priority": "Must", "acceptance": ["数据保存后可按主要字段查询", "无效数据不会写入"]},
                {"req_id": "REQ-03", "description": "系统为关键操作提供权限和失败处理。", "priority": "Must", "acceptance": ["未授权操作被拒绝", "失败响应包含可识别错误"]},
            ]
        return self._draft(requirements, blackboard, source="local-heuristic")

    @staticmethod
    def _normalize_requirements(raw: object) -> list[dict]:
        if not isinstance(raw, list) or not 2 <= len(raw) <= 8:
            raise AgentExecutionError("大模型返回的 requirements 必须是 2—8 项数组。")
        normalized: list[dict] = []
        seen: set[str] = set()
        for index, item in enumerate(raw, 1):
            if not isinstance(item, dict):
                raise AgentExecutionError(f"大模型需求第 {index} 项不是对象。")
            req_id = str(item.get("req_id") or f"REQ-{index:02d}").strip()
            description = str(item.get("description") or item.get("title") or "").strip()
            acceptance = item.get("acceptance")
            if isinstance(acceptance, str):
                acceptance = [acceptance]
            if req_id in seen or not description or not isinstance(acceptance, list) or not acceptance:
                raise AgentExecutionError(f"大模型需求第 {index} 项缺少唯一编号、描述或验收条件。")
            seen.add(req_id)
            normalized.append({
                "req_id": req_id,
                "description": description,
                "priority": str(item.get("priority") or "Must").title(),
                "acceptance": [str(value).strip() for value in acceptance if str(value).strip()],
                "constraints": [str(value).strip() for value in (item.get("constraints") or []) if str(value).strip()],
            })
        if any(not item["acceptance"] for item in normalized):
            raise AgentExecutionError("大模型需求包含空验收条件。")
        return normalized

    @staticmethod
    def _draft(requirements: list[dict], blackboard: dict, *, source: str) -> dict:
        return {
            "version": "R-draft", "status": "IN_REVIEW", "generation_source": source,
            "requirements": [{**item, "status": "IN_REVIEW"} for item in requirements],
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
        return {
            "version": "R1",
            "status": "CONFIRMED",
            "requirements": confirmed,
            "generation_source": str(draft.get("generation_source") or "unknown"),
            "confirmed_by": list(members),
        }
