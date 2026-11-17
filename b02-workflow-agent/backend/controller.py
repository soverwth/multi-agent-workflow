from __future__ import annotations

import threading
from datetime import datetime, timezone
from uuid import uuid4

from .adapters import ConsensusEvaluator, LocalAgentGateway, RequirementGateway, ROLES
from .errors import AgentExecutionError, InvalidTransition, WorkflowError
from .store import BlackboardStore


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class DiscussionController:
    """B02 WorkflowAgent: the only component allowed to advance discussion stages."""

    def __init__(self, store: BlackboardStore, agents=None, evaluator=None, requirements=None, on_event=None):
        self.store = store
        self.agents = agents or LocalAgentGateway()
        self.evaluator = evaluator or ConsensusEvaluator()
        self.requirements = requirements or RequirementGateway()
        self.on_event = on_event
        self._lock = threading.RLock()

    def _record(self, run: dict, event_type: str, payload: dict | None = None) -> dict:
        event = {
            "event_id": f"E{len(run['events']) + 1:03d}", "sequence": len(run["events"]) + 1,
            "type": event_type, "time": now_iso(), "payload": payload or {},
            "after": {"stage": run["stage"], "status": run["status"], "round": run["round"]},
        }
        run["events"].append(event)
        run["updated_at"] = event["time"]
        self.store.save(run)
        if self.on_event:
            self.on_event(run, event)
        return event

    def create_run(self, idea: str, constraints: str = "", scenario: str = "normal", max_rounds: int = 2) -> dict:
        idea = idea.strip()
        if len(idea) < 3:
            raise WorkflowError("请输入至少 3 个字符的项目想法。")
        if scenario not in ("normal", "value_conflict", "budget_exhaustion", "agent_failure"):
            raise WorkflowError("未知演示场景。")
        max_rounds = int(max_rounds)
        if not 1 <= max_rounds <= 5:
            raise WorkflowError("最大批判轮数必须在 1—5 之间。")
        run = {
            "run_id": "RUN-" + uuid4().hex[:10].upper(), "idea": idea, "constraints": constraints.strip(),
            "scenario": scenario, "max_rounds": max_rounds, "round": 0,
            "stage": "INTAKE", "status": "READY", "pause_requested": False,
            "created_at": now_iso(), "updated_at": now_iso(), "events": [],
            "blackboard": {
                "idea": idea, "constraints": constraints.strip(), "problem": "", "assumptions": [],
                "claims": [], "clusters": [], "objections": [], "stances": [], "decisions": [],
                "open_questions": [], "proposal_draft": "", "signoffs": [],
                "requirements_draft": None, "r1": None,
            },
            "latest_consensus": None, "failure": None,
        }
        self._record(run, "RUN_CREATED", {"scenario": scenario, "max_rounds": max_rounds})
        return run

    def get(self, run_id: str) -> dict:
        return self.store.get(run_id)

    def step(self, run_id: str) -> dict:
        with self._lock:
            run = self.store.get(run_id)
            if run["status"] == "PAUSED":
                raise InvalidTransition("流程已暂停，请先恢复；恢复前不会派发新角色任务。")
            if run["status"] == "WAITING_HUMAN":
                raise InvalidTransition("当前正在等待人类处理，不能自动越过该门槛。")
            if run["status"] != "READY":
                raise InvalidTransition(f"当前状态 {run['status']} 不允许推进。")
            if run["stage"] in ("COMPLETED", "HUMAN_CONFIRMATION"):
                raise InvalidTransition("当前阶段没有可自动执行的下一步。")
            run["status"] = "RUNNING"
            self._record(run, "STAGE_STARTED", {"stage": run["stage"]})
            try:
                self._execute_current_stage(run)
            except Exception as error:
                run["status"] = "BLOCKED"
                run["failure"] = {"type": type(error).__name__, "message": str(error), "stage": run["stage"]}
                self._record(run, "RUN_BLOCKED", run["failure"])
            return run

    def run_until_control_point(self, run_id: str) -> dict:
        for _ in range(40):
            run = self.store.get(run_id)
            if run["status"] != "READY":
                return run
            self.step(run_id)
        raise WorkflowError("自动控制预算已用尽，请检查事件日志。")

    def _execute_current_stage(self, run: dict) -> None:
        stage = run["stage"]
        board = run["blackboard"]
        if stage == "INTAKE":
            framed = self.agents.frame(run["idea"], run["constraints"])
            board.update(framed)
            self._complete(run, "IDEA_FRAMED", "DIVERGE", {"assumptions": len(board["assumptions"])})
        elif stage == "DIVERGE":
            claims = self.agents.independent(run["idea"], run["constraints"], run["scenario"])
            self._validate_claims(claims)
            board["claims"] = []
            for claim in claims:
                board["claims"].append({**claim, "claim_id": f"C{len(board['claims']) + 1:03d}", "round": 1})
            self._complete(run, "INDEPENDENT_DIVERGENCE_COMPLETED", "CLUSTER", {"roles": list(ROLES), "isolated": True})
        elif stage == "CLUSTER":
            board["clusters"] = [{"cluster_id": f"CL-{index:02d}", "theme": claim["role"], "claim_ids": [claim["claim_id"]]} for index, claim in enumerate(board["claims"], 1)]
            self._complete(run, "CLAIMS_CLUSTERED", "CRITIQUE", {"cluster_count": len(board["clusters"])})
            run["round"] = 1
            self._record(run, "ROUND_STARTED", {"round": 1})
        elif stage == "CRITIQUE":
            result = self.agents.critique(board, run["round"], run["scenario"])
            self._apply_critique(run, result)
            self._complete(run, "CRITIQUE_COMPLETED", "EVALUATE", {"new_objections": len(result.get("objections", []))})
        elif stage == "EVALUATE":
            self._evaluate_discussion(run)
        elif stage == "PROPOSAL_REVIEW":
            self._review_proposal(run)
        else:
            raise InvalidTransition(f"阶段 {stage} 没有自动执行器。")

    def _complete(self, run: dict, event: str, next_stage: str, payload: dict) -> None:
        previous = run["stage"]
        run["stage"] = next_stage
        run["status"] = "READY"
        self._record(run, event, {**payload, "from": previous, "to": next_stage})

    @staticmethod
    def _validate_claims(claims: list) -> None:
        if not isinstance(claims, list) or {item.get("role") for item in claims} != set(ROLES) or len(claims) != len(ROLES):
            raise AgentExecutionError("B04 输出未包含四个不同角色的独立观点。")
        for claim in claims:
            if not all(claim.get(field) for field in ("claim", "reason", "evidence", "impact")):
                raise AgentExecutionError(f"角色 {claim.get('role', '未知')} 的观点缺少理由、证据或影响。")

    def _apply_critique(self, run: dict, result: dict) -> None:
        board = run["blackboard"]
        claims = {item["claim_id"] for item in board["claims"]}
        for objection in result.get("objections", []):
            if not all(objection.get(field) for field in ("raised_by", "target_id", "category", "content", "severity", "evidence", "status")):
                raise AgentExecutionError("批判结果缺少异议对象、理由、证据或状态。")
            if objection["target_id"] not in claims:
                raise AgentExecutionError("异议指向了不存在的观点。")
            if objection["severity"] not in ("low", "medium", "high") or objection["category"] not in ("fact", "value", "tradeoff"):
                raise AgentExecutionError("异议分类或严重级别不合法。")
            board["objections"].append({
                **objection, "objection_id": f"O{len(board['objections']) + 1:03d}",
                "round": run["round"], "response": None, "resolution_ref": None,
            })
        for objection_id in result.get("resolved_ids", []):
            target = next((item for item in board["objections"] if item["objection_id"] == objection_id), None)
            if target:
                target["status"] = "resolved"
                target["response"] = "已补充适用范围、验证方式与责任边界。"
        board["stances"] = result.get("stances", [])
        if {item.get("role") for item in board["stances"]} != set(ROLES):
            raise AgentExecutionError("本轮立场记录未覆盖四个角色。")

    def _evaluate_discussion(self, run: dict) -> None:
        board = run["blackboard"]
        verdict = self.evaluator.evaluate_discussion(board, run["round"])
        run["latest_consensus"] = verdict
        self._record(run, "CONSENSUS_EVALUATED", verdict)
        if verdict["needs_human"]:
            run["status"] = "WAITING_HUMAN"
            self._record(run, "HUMAN_DECISION_REQUIRED", {"reason": verdict["reason"], "stage": "EVALUATE"})
        elif verdict["open_count"] > 0 and run["round"] < run["max_rounds"]:
            run["round"] += 1
            run["stage"] = "CRITIQUE"
            run["status"] = "READY"
            self._record(run, "CRITIQUE_LOOP", {"from": "EVALUATE", "to": "CRITIQUE", "next_round": run["round"]})
        elif verdict["open_count"] > 0:
            run["status"] = "STOPPED"
            self._record(run, "BUDGET_STOPPED", {"reason": "达到最大轮数仍有开放异议；停止不等于达成共识。", "open_count": verdict["open_count"]})
        else:
            self._complete(run, "DISCUSSION_CONVERGED", "PROPOSAL_REVIEW", {"reason": verdict["reason"]})

    def _review_proposal(self, run: dict) -> None:
        board = run["blackboard"]
        if not board["proposal_draft"]:
            board["proposal_draft"] = self.agents.draft_proposal(board)
            self._record(run, "PROPOSAL_DRAFTED", {"length": len(board["proposal_draft"])})
        board["signoffs"] = self.agents.review_proposal(board)
        if {item.get("role") for item in board["signoffs"]} != set(ROLES):
            raise AgentExecutionError("Proposal 审阅未覆盖四个角色。")
        verdict = self.evaluator.evaluate_proposal(board)
        run["latest_consensus"] = verdict
        self._record(run, "PROPOSAL_REVIEW_EVALUATED", verdict)
        if verdict["needs_human"]:
            run["status"] = "WAITING_HUMAN"
            self._record(run, "HUMAN_DECISION_REQUIRED", {"reason": verdict["reason"], "stage": "PROPOSAL_REVIEW"})
        elif not verdict["can_proceed"] and run["round"] < run["max_rounds"]:
            run["round"] += 1
            run["stage"] = "CRITIQUE"
            run["status"] = "READY"
            self._record(run, "PROPOSAL_REVISION_LOOP", {"next_round": run["round"]})
        elif not verdict["can_proceed"]:
            run["status"] = "STOPPED"
            self._record(run, "REVIEW_STOPPED", {"reason": "Proposal 未通过且修订预算已用尽。"})
        else:
            board["requirements_draft"] = self.requirements.prepare_draft(board)
            run["stage"] = "HUMAN_CONFIRMATION"
            run["status"] = "WAITING_HUMAN"
            self._record(run, "REQUIREMENTS_CONFIRMATION_REQUIRED", {"from": "PROPOSAL_REVIEW", "to": "HUMAN_CONFIRMATION", "requirement_count": len(board["requirements_draft"]["requirements"])})

    def resolve_human_decision(self, run_id: str, decision: str) -> dict:
        decision = decision.strip()
        if len(decision) < 3:
            raise WorkflowError("请填写人类裁决内容及理由。")
        with self._lock:
            run = self.store.get(run_id)
            if run["status"] != "WAITING_HUMAN" or run["stage"] not in ("EVALUATE", "PROPOSAL_REVIEW"):
                raise InvalidTransition("当前没有可处理的分歧裁决入口。")
            board = run["blackboard"]
            decision_id = f"D{len(board['decisions']) + 1:03d}"
            board["decisions"].append({"decision_id": decision_id, "content": decision, "time": now_iso(), "decided_by": "人类团队"})
            resolved = []
            for objection in board["objections"]:
                if objection["status"] == "open" and objection["severity"] == "high":
                    objection["status"] = "resolved"
                    objection["resolution_ref"] = decision_id
                    objection["response"] = decision
                    resolved.append(objection["objection_id"])
            run["status"] = "READY"
            self._record(run, "HUMAN_DECISION_RECORDED", {"decision_id": decision_id, "resolved_objections": resolved})
            return run

    def confirm_requirements(self, run_id: str, members: list[str]) -> dict:
        with self._lock:
            run = self.store.get(run_id)
            if run["stage"] != "HUMAN_CONFIRMATION" or run["status"] != "WAITING_HUMAN":
                raise InvalidTransition("需求确认门槛不可跳过：当前尚未进入六人确认阶段。")
            board = run["blackboard"]
            board["r1"] = self.requirements.publish(board["requirements_draft"], members)
            run["stage"] = "COMPLETED"
            run["status"] = "COMPLETED"
            self._record(run, "R1_PUBLISHED", {"version": "R1", "confirmed_by": members})
            return run

    def pause(self, run_id: str) -> dict:
        with self._lock:
            run = self.store.get(run_id)
            if run["status"] != "READY":
                raise InvalidTransition("只有处于阶段间 READY 状态的运行可以暂停；进行中的角色调用不会被假装取消。")
            run["pause_requested"] = True
            run["status"] = "PAUSED"
            self._record(run, "RUN_PAUSED", {"checkpoint": run["stage"]})
            return run

    def resume(self, run_id: str) -> dict:
        with self._lock:
            run = self.store.get(run_id)
            if run["status"] != "PAUSED":
                raise InvalidTransition("当前运行未暂停。")
            run["pause_requested"] = False
            run["status"] = "READY"
            self._record(run, "RUN_RESUMED", {"checkpoint": run["stage"]})
            return run

    def replay(self, run_id: str) -> dict:
        run = self.store.get(run_id)
        expected = list(range(1, len(run["events"]) + 1))
        sequences = [event["sequence"] for event in run["events"]]
        state = {"stage": None, "status": None, "round": 0}
        timeline = []
        for event in run["events"]:
            state.update(event["after"])
            timeline.append({"sequence": event["sequence"], "event_id": event["event_id"], "type": event["type"], **event["after"]})
        passed = sequences == expected and state == {"stage": run["stage"], "status": run["status"], "round": run["round"]}
        return {"passed": passed, "event_count": len(timeline), "replayed_state": state, "checkpoint_state": {"stage": run["stage"], "status": run["status"], "round": run["round"]}, "timeline": timeline}
