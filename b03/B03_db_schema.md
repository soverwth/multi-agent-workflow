# B03 数据持久化模块 · 数据库结构说明

> 版本：v1.0 · 更新时间：2026-11-22 · 状态：实现完成，待集成联调
> 负责人：陈怡雯 · 依据：《阶段开发分工.md》B03 交付物要求

## 1. 存储分层

| 数据库 | 文件 | 内容 | 说明 |
|---|---|---|---|
| 黑板库 | `blackboard.db` | 任务状态、租约、输入快照、旧事件、旧证据/缺陷、全局 checkpoint | 上一阶段实现，保留不动 |
| 平台核心库 | `platform.db` | 项目/版本、运行/尝试、执行日志、产物、证据、验收、事件、按运行 checkpoint | 本阶段新增，通用、与案例无关 |
| 案例业务库 | `campus.db` | 校园失物招领三张表 | 旧案例样例，非平台核心 |

**关键原则**：平台核心库（`platform.db`）所有表都带 `project_id`，通过外键与 `projects` 关联，保证不同项目数据隔离。

## 2. platform.db 表结构

| 表名 | 主键 | 关键字段 | 用途 |
|---|---|---|---|
| `projects` | `project_id` | `name`, `goal`, `metadata_json`, `created_at` | 项目元信息 |
| `project_versions` | `version_id` | `project_id`, `version_kind`(requirement/design/plan), `version_label`, `content_json` | 需求/设计/计划的版本化存储；`(project_id, kind, label)` 唯一 |
| `task_runs` | `run_id` | `project_id`, `plan_version`, `status`, `started_at`, `finished_at` | 一次任务计划运行实例 |
| `task_attempts` | `attempt_id` | `run_id`, `project_id`, `task_id`, `attempt_no`, `agent_role`, `state`, `input_snapshot_json`, `result_json` | 同一任务的不同执行尝试；`(run_id, task_id, attempt_no)` 唯一 |
| `execution_logs` | `log_id` | `project_id`, `run_id`, `attempt_id`, `level`, `message`, `context_json` | Agent 执行日志 |
| `platform_artifacts` | `artifact_id` | `project_id`, `task_id`, `attempt_id`, `version`, `path`, `content_hash`, `commit_ref` | Agent 真实产物；`(project_id, task_id, attempt_id, version)` 唯一 |
| `evidence_records` | `evidence_id` | `project_id`, `task_id`, `test_id`, `verdict`(PASS/FAIL), `artifact_ref` | 测试证据 |
| `acceptance_results` | `acceptance_id` | `project_id`, `task_id`, `verdict`(ACCEPT/REJECT/REVALIDATION_REQUIRED), `reason`, `defect_json` | B06 验收结果与结构化缺陷 |
| `platform_events` | `seq`(自增) | `event_id`(唯一，幂等键), `project_id`, `event_type`, `payload_json`, `input_version_json`, `occurred_at` | 执行事件；按 `seq` 顺序支持回放 |
| `platform_checkpoints` | `(project_id, run_id, checkpoint_id)` | `state_json`, `processed_event_seq`, `created_at` | 按项目+运行粒度的检查点 |

## 3. 设计要点

1. **项目隔离**：所有业务表带 `project_id`，全部查询接口强制传 `project_id`；跨项目查询返回空，不串数据。
2. **版本可追溯**：需求(R)/设计(S)/计划(plan)以 `version_kind + version_label` 版本化保存，同一组合唯一，不覆盖历史。
3. **尝试可区分**：`task_attempts` 用 `attempt_no` 区分同一任务多次执行，记录各自状态与结果。
4. **事件幂等**：`event_id` 唯一约束；重复提交返回 `duplicate=True`，不新增记录。
5. **回放顺序**：`platform_events.seq` 自增，保证事件严格有序，`replay_project` 按 `seq` 返回。
6. **恢复粒度**：checkpoint 从"全局单行"升级为 `(project_id, run_id, checkpoint_id)`，`processed_event_seq` 标记已处理事件位点。

## 4. 迁移文件

`b03_implementation/migrations/004_platform_core.sql`：建表 + 索引，使用 `CREATE TABLE IF NOT EXISTS`，幂等可重复执行。

## 5. 与旧模块的关系

- `BlackboardStore` 保留：负责单任务粒度的 CAS 状态、租约、快照失效。
- `PlatformStore` 新增：负责项目维度的运行历史、证据、回放、恢复。
- 二者分库，不互相覆盖；集成时由 B02 决定状态权威来源（B02 仍是唯一状态写入者）。
