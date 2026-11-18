# 规格变更登记模板

> 用途：S1/C1/任务计划的任何行为变更必须先登记，经评估与确认后建立新版本。未经确认不得直接修改 R1/S1/C1 或降低验收门槛。

```yaml
change_request_id: CR-YYYYMMDD-NN
created_at: YYYY-MM-DDTHH:mm:ssZ
requester: B01 / B02 / B03 / B04 / B05 / B06 / 人类确认人
source:
  discussion_ref:  # 讨论或用户反馈来源
  decision_ref:    # 决策编号，如无则写待建立
status: DRAFT | IN_REVIEW | APPROVED | REJECTED | SUPERSEDED

change:
  target_version:
    from: S1-v1.0 / C1-v1.0 / PLAN-v1.0
    to:   S2-v1.0 / C2-v1.0 / PLAN-v2.0
  target_artifacts:
    - docs/s1.json
    - docs/c1.json
    - docs/plan.json
  summary: 一句话说明变更内容
  reason: 为什么要改
  behavior_delta: 对字段、状态、权限、错误行为或验收条件的具体影响

impact:
  req_refs: [LR-01]
  design_refs: [DS-XXX-01]
  contract_refs: [operation_name]
  task_refs: [T04, T09]
  test_refs: [TC-P02]
  affected_blocks: [B01, B02, B03, B04, B05, B06]
  invalidates_acceptance: true | false
  new_baseline_required: true | false

confirmation:
  reviewers:
    B01: PENDING | CONFIRMED | REJECTED
    B02: PENDING | CONFIRMED | REJECTED
    B03: PENDING | CONFIRMED | REJECTED
    B04: PENDING | CONFIRMED | REJECTED
    B05: PENDING | CONFIRMED | REJECTED
    B06: PENDING | CONFIRMED | REJECTED
  approval_ref:  # 确认记录或提交引用
  confirmed_at:

validation:
  plan_validator: PASS | FAIL
  contract_check: PASS | FAIL
  cross_review: PASS | FAIL
  evidence_refs: []
```
