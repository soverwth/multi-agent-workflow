# B03 阶段一：现状检查与优化方案

> 版本：v1.0 · 更新时间：2026-11-22 · 状态：待 B02/B04/B06 接口确认
> 负责人：陈怡雯 · 工作块：B03（共享黑板与数据持久化）
> 依据：《阶段开发分工.md》B03 要求与第一阶段交付要求

## 1. 当前功能完成情况

现有实现位于 `b03/b03_implementation/`，核心是 `BlackboardStore`（`blackboard.py`），已有能力：

| 能力 | 现有实现 | 对应新分工 |
|---|---|---|
| 规格/任务登记 | `register_spec_baseline`、`register_task` | 部分满足（无项目维度） |
| 状态原子流转 | `cas_state`（`rev` 乐观锁） | 满足（B02 独占写入的落盘） |
| 租约与幂等派发 | `acquire_lease` 等，`idempotency_key` 唯一 | 满足 |
| 输入快照/版本失效 | `freeze_input_snapshot`、`invalidate_affected` | 部分满足 |
| 事件记录与幂等 | `append_event`（`event_id` 去重、stale 标记）、`list_events` | 部分满足（无回放） |
| 产物版本 | `ArtifactStore`：只追加、绑定快照 | 满足 |
| 检查点 | `write_checkpoint`/`load_checkpoint`（**全局单行 id=1**） | 不满足项目级恢复 |
| 证据/缺陷 | `add_test_evidence`、`add_issue_or_decision` | 部分满足 |
| 案例业务库 | `CampusDB`（users/lost_items/claims） | 属旧案例，非平台核心 |

自检：`python -m b03_implementation.run_checks` → 19 项通过。

## 2. 存在的问题与缺失能力

对照《阶段开发分工.md》L63—86：

1. **无项目隔离**：所有表无 `project_id`，无法满足"不同项目数据相互隔离/历史项目查询"。
2. **无运行与执行尝试历史**：`execution_state` 每任务一行，`attempt_count` 只是计数；无法"区分同一任务的不同执行尝试"、查询历史运行信息。
3. **无历史回放接口**：`list_events` 只能分页读取，不能按项目/任务重建状态。
4. **无独立执行日志/验收结果表**：B04 的 `TaskExecutionResult`、B06 的 `ACCEPT/REJECT/REVALIDATION_REQUIRED` 无专用落库结构。
5. **checkpoint 粒度不足**：全局单行，重启恢复无法按项目/运行区分。
6. **需求/设计/计划存储不完整**：无 project/requirement/design/plan 表及版本追溯链。
7. **副本问题**：父目录与本目录各有一份相同实现，需统一以本目录为准。
8. **接口未冻结**：B02、B06 对接单确认栏为空，B01 为"有条件通过"。

## 3. 下一阶段具体优化任务

在**不改动现有 `BlackboardStore` 接口**的前提下，新增 `platform_store.py`（平台核心存储），落地：

- `projects` / `requirements` / `designs` / `task_plans` 表：记录项目与版本化规格。
- `task_runs` / `task_attempts` 表：区分运行实例与每次执行尝试，记录 Agent、状态、输入版本。
- `execution_logs` / `artifacts` / `test_evidence` / `acceptance_results`：执行日志、产物、证据、验收结果统一格式。
- `events` 增加 `project_id` + `seq`，提供 `replay_project` 历史回放。
- `checkpoints` 改为按 `(project_id, run_id)` 维度保存与读取。
- 所有查询接口带 `project_id` 过滤，实现数据隔离。

## 4. 需要其他模块配合的接口

| 模块 | 需要对方提供/确认 |
|---|---|
| B01 | 需求/设计/任务计划的版本标识与 `project_id` 生成规则（已部分在 B01 对接单 v2/v3） |
| B02 | `project_id`/`run_id`/`attempt_id` 写入约定；状态迁移事件格式；checkpoint 触发点 |
| B04 | `TaskExecutionResult` 字段（产物路径、文件哈希、日志、测试结果） |
| B06 | `ACCEPT/REJECT/REVALIDATION_REQUIRED` 结果与缺陷字段 |

## 5. 计划修改的文件与测试方式

**新增文件**：
- `b03_implementation/platform_store.py`（平台核心存储，主交付）
- `b03_implementation/migrations/004_platform_core.sql`
- `b03_implementation/tests/test_platform_store.py`
- `B03_db_schema.md`
- `B03_history_query_api.md`
- `B03_recovery_test_report.md`

**不修改**：现有 `blackboard.py` / `artifact_store.py` / `campus_db.py` 的全部逻辑，避免回归。

**测试方式**：
- `python -m b03_implementation.run_checks`（现有 19 项不回归）
- `python -m b03_implementation.run_platform_checks`（新增用例：项目隔离、尝试区分、事件幂等、回放、checkpoint 恢复）
