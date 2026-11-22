# B03 历史记录查询接口说明

> 版本：v1.0 · 更新时间：2026-11-22 · 状态：实现完成，待集成联调
> 负责人：陈怡雯 · 实现：`b03_implementation/platform_store.py` 的 `PlatformStore`

所有接口均以 `project_id` 为第一过滤条件，保证数据隔离。返回值为字典列表或字典（JSON 友好）。

## 1. 项目与版本

| 方法 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `create_project` | `name`, `goal?`, `project_id?`, `metadata?` | 项目字典 | 新建项目 |
| `get_project` | `project_id` | 项目字典 / None | 查项目 |
| `list_projects` | — | 项目列表 | 历史项目入口（供 B05） |
| `save_version` | `project_id`, `version_kind`, `version_label`, `content` | 版本字典 | 保存需求/设计/计划版本 |
| `get_version` | `project_id`, `version_kind`, `version_label` | 版本字典 / None | 按版本标签查 |
| `list_versions` | `project_id`, `version_kind?` | 版本列表 | 列全部或某类版本 |

`version_kind` 取值：`requirement` / `design` / `plan`。

## 2. 运行与执行尝试

| 方法 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `start_run` | `project_id`, `plan_version`, `run_id?`, `metadata?` | 运行字典 | 创建一次运行 |
| `get_run` / `list_runs` | `project_id`, (`run_id`) | 运行字典 / 列表 | 查询运行记录 |
| `finish_run` | `project_id`, `run_id`, `status` | 运行字典 | 结束/暂停/取消运行 |
| `start_attempt` | `project_id`, `run_id`, `task_id`, `attempt_no`, `agent_role?`, `input_snapshot?` | 尝试字典 | 登记一次执行尝试 |
| `get_attempt` / `list_attempts` | `project_id`, (`attempt_id` 或 `task_id`) | 尝试字典 / 列表 | 区分同一任务多次尝试 |
| `finish_attempt` | `project_id`, `attempt_id`, `state`, `result?` | 尝试字典 | 记录尝试结果与结束状态 |

## 3. 执行日志 / 产物 / 证据 / 验收

| 方法 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `append_log` | `project_id`, `message`, `run_id?`, `attempt_id?`, `level?`, `context?` | `log_id` | 写执行日志 |
| `list_logs` | `project_id`, `attempt_id?` | 日志列表 | 查执行日志 |
| `put_artifact` | `project_id`, `task_id`, `attempt_id`, `version`, `path?`, `content_hash?`, `commit_ref?`, `run_id?` | 产物字典 | 存 Agent 产物 |
| `list_artifacts` | `project_id`, `task_id?` | 产物列表 | 查历史产物 |
| `record_evidence` | `project_id`, `task_id`, `test_id`, `verdict`, `attempt_id?`, 等 | `evidence_id` | 存测试证据（PASS/FAIL） |
| `list_evidence` | `project_id`, `task_id?` | 证据列表 | 查测试证据 |
| `record_acceptance` | `project_id`, `task_id`, `verdict`, `reason?`, `evidence_refs?`, `defect?` | `acceptance_id` | 存验收结果 |
| `list_acceptance` | `project_id`, `task_id?` | 验收列表 | 查验收历史 |

`verdict`（验收）：`ACCEPT` / `REJECT` / `REVALIDATION_REQUIRED`，对应 B06 三种判定。

## 4. 事件与历史回放

| 方法 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `append_event` | `project_id`, `event_type`, `event_id?`, `run_id?`, `task_id?`, `attempt_id?`, `payload?`, `input_version?` | `EventAppendResult` | 写事件；`event_id` 重复则 `duplicate=True` |
| `list_events` | `project_id`, `after_seq?`, `limit?` | 事件列表 | 分页拉取 |
| `replay_project` | `project_id`, `after_seq?`, `limit?` | 事件列表 | 按 `seq` 顺序回放，用于状态重建与审计 |

`EventAppendResult` 字段：`accepted`、`duplicate`、`event_id`、`seq`。

## 5. Checkpoint 与恢复

| 方法 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `save_checkpoint` | `project_id`, `run_id`, `checkpoint_id`, `state`, `processed_event_seq?` | checkpoint 字典 | 保存检查点 |
| `get_checkpoint` | `project_id`, `run_id`, `checkpoint_id` | checkpoint / None | 按 ID 查 |
| `latest_checkpoint` | `project_id`, `run_id` | checkpoint / None | 取最新检查点 |
| `list_checkpoints` | `project_id`, `run_id` | checkpoint 列表 | 查全部检查点 |
| `recover_run` | `project_id`, `run_id` | 恢复视图字典 | 返回 run + 最新 checkpoint + 未处理事件 + 尝试列表 |

## 6. 典型调用顺序（B02 集成参考）

```text
create_project
→ save_version(requirement) / save_version(design) / save_version(plan)
→ start_run
→ start_attempt（任务某次执行）
→ append_log / put_artifact / record_evidence（B04/B06 写入）
→ record_acceptance（B06 写入判定）
→ append_event（推进事件）
→ save_checkpoint（带 processed_event_seq）
→ finish_attempt / finish_run
→ replay_project / recover_run（历史查询与恢复）
```

接口不推进任务状态；状态迁移仍由 B02 通过 `BlackboardStore.cas_state` 或编排器自身完成。
