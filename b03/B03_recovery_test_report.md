# B03 数据恢复测试报告

> 版本：v1.0 · 更新时间：2026-11-22 · 状态：测试通过
> 负责人：陈怡雯 · 测试对象：`platform_store.PlatformStore`
> 环境：Python 3.13.14 / SQLite3（Python 标准库）/ Windows

## 1. 测试目标

验证《阶段开发分工.md》B03 验收标准中以下四项：

- 项目、任务和执行记录能够持久化保存；
- 能够区分同一任务的不同执行尝试；
- 重复事件不会造成重复数据或错误记录；
- 系统重启后能够恢复历史运行信息（checkpoint + 事件位点）；
- 不同项目的数据相互隔离。

## 2. 测试方式与命令

在 `multi-agent-workflow/b03` 目录执行：

```bash
python -m b03_implementation.run_platform_checks
python -m b03_implementation.run_checks
```

## 3. 测试结果

| 测试集 | 用例数 | 结果 |
|---|---|---|
| 平台核心存储（本阶段新增） | 9 | 全部通过 |
| 原有 B03 全套（含新增） | 28 | 全部通过 |

具体用例与结论：

| 用例 | 验证点 | 结果 |
|---|---|---|
| `test_project_isolation` | p1 存版本后，p2 查不到，数据隔离 | 通过 |
| `test_version_kind_validation` | 非法 `version_kind` 被拒绝 | 通过 |
| `test_runs_and_attempts_distinguished` | 同一任务 T02 的两次尝试独立记录，状态/结果各自保留 | 通过 |
| `test_duplicate_attempt_no_rejected` | 同 run 同任务重复 attempt_no 被拒绝 | 通过 |
| `test_evidence_logs_artifacts_acceptance` | 日志/产物/证据/验收结果均可落库并查询 | 通过 |
| `test_invalid_acceptance_verdict` | 非法验收判定（MAYBE）被拒绝 | 通过 |
| `test_event_idempotency_and_replay` | 相同 event_id 重复提交返回 duplicate，回放按 seq 有序且仅项目内 | 通过 |
| `test_checkpoint_save_load_and_recover` | checkpoint 保存后，恢复视图返回未处理事件（位点之后仅 1 条） | 通过 |
| `test_recover_unknown_run` | 不存在的 run 恢复时抛 NotFound | 通过 |

## 4. 恢复机制说明

`recover_run(project_id, run_id)` 返回：

- `run`：运行实例信息（状态、计划版本、时间）；
- `checkpoint`：最新检查点（含 `processed_event_seq` 已处理事件位点）；
- `unprocessed_events`：位点之后尚未处理的事件（供 B02 重放）；
- `attempts`：该项目的执行尝试列表（供核对未结束尝试，避免重复执行）。

中断恢复流程：系统重启后，B02 调 `recover_run` → 核对未结束 attempt → 从 checkpoint 位点续跑未处理事件 → 保存新 checkpoint。该流程不重复执行已完成事件，满足"不重复有效执行"约束。

## 5. 已知限制 / 待联调项

- checkpoint 位点由 B02 在保存时传入 `processed_event_seq`，B03 只负责持久化，不判断事件是否"已处理"。
- 事件回放返回原始事件字典，具体状态重建逻辑由 B02/编排器实现。
- 验收判定字段已按 `ACCEPT/REJECT/REVALIDATION_REQUIRED` 落库，B06 的具体缺陷结构需按对接单确认后细化 `defect_json`。
- 7100 集成系统代码不在本目录，跨模块端到端恢复需在集成环境联调验证。
