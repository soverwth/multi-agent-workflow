STAGES = [
    {"id": "INTAKE", "code": "A", "name": "框定 Idea", "owner": "WorkflowAgent", "action": "整理问题、假设、约束与未决项。"},
    {"id": "DIVERGE", "code": "B", "name": "独立发散", "owner": "B04 角色", "action": "四个角色独立生成观点，彼此不可见。"},
    {"id": "CLUSTER", "code": "C", "name": "聚类整合", "owner": "WorkflowAgent", "action": "按来源整理观点，保留原始意见。"},
    {"id": "CRITIQUE", "code": "D", "name": "结构化批判", "owner": "B04 + B06", "action": "记录赞同、反对、有条件赞同及具体异议。"},
    {"id": "EVALUATE", "code": "E", "name": "共识评价", "owner": "B06 → B02", "action": "消费评价结果，决定回路、暂停或前进。"},
    {"id": "PROPOSAL_REVIEW", "code": "F", "name": "Proposal 审阅", "owner": "B04 + B06", "action": "生成草案并收集角色 sign-off。"},
    {"id": "HUMAN_CONFIRMATION", "code": "G", "name": "需求确认", "owner": "B01 人类门槛", "action": "六人逐项确认后才能发布 R1。"},
    {"id": "COMPLETED", "code": "H", "name": "完成", "owner": "WorkflowAgent", "action": "输出 Proposal、R1、未决项与回放日志。"},
]

TRANSITIONS = [
    {"from": "INTAKE", "event": "frame_completed", "guard": "问题定义已记录", "to": "DIVERGE"},
    {"from": "DIVERGE", "event": "independent_completed", "guard": "至少四个不同角色成功提交", "to": "CLUSTER"},
    {"from": "CLUSTER", "event": "cluster_completed", "guard": "观点来源完整", "to": "CRITIQUE"},
    {"from": "CRITIQUE", "event": "critique_completed", "guard": "立场和异议结构合法", "to": "EVALUATE"},
    {"from": "EVALUATE", "event": "revision_required", "guard": "有开放异议且 round < max_rounds", "to": "CRITIQUE"},
    {"from": "EVALUATE", "event": "human_required", "guard": "高影响价值分歧未解决", "to": "EVALUATE / WAITING_HUMAN"},
    {"from": "EVALUATE", "event": "budget_exhausted", "guard": "有开放异议且达到轮数上限", "to": "EVALUATE / STOPPED"},
    {"from": "EVALUATE", "event": "discussion_converged", "guard": "无开放异议", "to": "PROPOSAL_REVIEW"},
    {"from": "PROPOSAL_REVIEW", "event": "review_rejected", "guard": "有 Pending/Disagree 且预算允许", "to": "CRITIQUE"},
    {"from": "PROPOSAL_REVIEW", "event": "review_completed", "guard": "四角色 sign-off 完成且无阻断异议", "to": "HUMAN_CONFIRMATION"},
    {"from": "HUMAN_CONFIRMATION", "event": "requirements_confirmed", "guard": "B01 校验六人确认与需求验收字段", "to": "COMPLETED"},
]

PSEUDOCODE = """on_start(idea, constraints, budget):
    blackboard = B03.create(idea, constraints)
    stage, round = INTAKE, 0

step(run):
    assert run.status == READY
    if pause_requested: pause_and_checkpoint()
    dispatch STAGE_STARTED
    try:
        execute_current_stage_through_adapter()
    except AgentError as error:
        B03.record_failure(error)
        status = BLOCKED             # 不伪造观点或共识
        return

    if stage == EVALUATE:
        verdict = B06.evaluate(blackboard)  # B02 只消费评价
        if verdict.needs_human:
            status = WAITING_HUMAN
        elif verdict.open_count > 0 and round < max_rounds:
            round += 1
            stage = CRITIQUE         # 定向批判回路
        elif verdict.open_count > 0:
            status = STOPPED         # 达到预算不等于共识
        else:
            stage = PROPOSAL_REVIEW

    if stage == HUMAN_CONFIRMATION:
        status = WAITING_HUMAN       # 不得自动越过 B01 门槛
    B03.append_event_and_checkpoint(run)

confirm_requirements(run, six_members):
    assert stage == HUMAN_CONFIRMATION
    R1 = B01.publish(draft, six_members)
    stage, status = COMPLETED, COMPLETED

replay(run_id):
    for event in B03.ordered_events(run_id):
        apply_control_transition(event)
    verify_replayed_state_equals_checkpoint()
"""
