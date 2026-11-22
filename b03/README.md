# 第十组 · B03 黑板数据 Agent 交付包

> 负责人：陈怡雯 · 角色标识：`BlackboardAgent`
> 版本：v2.0 · 更新时间：2026-11-22
> 课程：软件工程与项目实践
> 案例：校园失物招领系统（多智能体协作开发平台贯穿案例）
> 上游基线：《第十组 设计规格与开发任务编排.docx》R1 / S1 / C1；《阶段开发分工.md》

本包是 B03 工作块的完整交付：设计文档、三份对接单、平台核心数据持久化实现、自检用例。
v2.0 按《阶段开发分工.md》新增：项目维度隔离、运行/尝试历史、事件回放、按项目 checkpoint 恢复。

## 1. 交付清单

| 文件 | 说明 |
|---|---|
| `B03_黑板数据Agent_设计文档_v1.0.md` | B03 设计规格：存储/事件协议、状态迁移与快照、租约接口、T02 数据层、验收映射 |
| `B03-B01_规格与Schema对齐对接单_v1.0.md` | 对接 B01（蔡昀漪）：输入版本、字段边界、追溯编号，10 项待确认 |
| `B03-B02_状态与租约接口对接单_v1.0.md` | 对接 B02（陈昱希）：接口签名、幂等、回调、租约、恢复，8 项待确认 |
| `B03-B06_验收证据与测试数据对接单_v1.0.md` | 对接 B06（吴天昊）：证据字段、T09 覆盖、夹具隔离，9 项待确认 |
| `B03_阶段一_现状检查与优化方案.md` | 第一阶段交付：现状、缺口、优化任务、需配合接口、测试方式 |
| `B03_数据持久化模块_数据库结构说明.md` | platform.db 十张表结构、项目隔离设计 |
| `B03_历史记录查询接口说明.md` | PlatformStore 全部查询接口与典型调用顺序 |
| `B03_数据恢复测试报告.md` | 恢复机制与 9+28 项测试结果 |
| `b03_implementation/` | 可运行实现与测试（见下） |

## 2. 目录结构

```text
.
├── README.md
├── .gitignore
├── B03_黑板数据Agent_设计文档_v1.0.md
├── B03-B01_规格与Schema对齐对接单_v1.0.md
├── B03-B02_状态与租约接口对接单_v1.0.md
├── B03-B06_验收证据与测试数据对接单_v1.0.md
├── B03_阶段一_现状检查与优化方案.md
├── B03_数据持久化模块_数据库结构说明.md
├── B03_历史记录查询接口说明.md
├── B03_数据恢复测试报告.md
└── b03_implementation/
    ├── __init__.py
    ├── config.py            # 双库路径、租约默认值
    ├── errors.py            # 领域错误码与 HTTP 映射
    ├── blackboard.py        # task_store：状态、租约、快照、事件、检查点、证据、只读视图
    ├── artifact_store.py    # artifact_store：只追加、版本绑定、快照有效才可读
    ├── task_state.py        # task_state_store：任务运行/九态/尝试历史/运行事件/检查点（D18/D19）
    ├── campus_db.py         # 案例 T02 数据层：三张表、校验、隐私视图、事务、测试数据
    ├── platform_store.py    # 平台核心存储（本阶段新增）：项目/运行/尝试/日志/产物/证据/验收/回放/恢复
    ├── run_checks.py        # 全套自检入口
    ├── run_platform_checks.py # 平台核心自检入口
    ├── migrations/
    │   ├── 001_create_user.sql
    │   ├── 002_create_lost_item.sql
    │   ├── 003_create_claim_application.sql
    │   └── 004_platform_core.sql   # 平台核心十张表
    └── tests/
        ├── __init__.py
        ├── test_blackboard.py
<<<<<<< Updated upstream
        ├── test_task_state.py
        └── test_campus_db.py
=======
        ├── test_campus_db.py
        └── test_platform_store.py
>>>>>>> Stashed changes
```

## 2.1 任务状态持久化（第二阶段 D18/D19）

`task_state.py` 提供 `TaskStateStore`，与讨论流程的黑板数据共用 `blackboard.db`
但表结构独立：

- **Task Registry**：`task_plans` 保存计划文档与版本（内容不同必须换新 `plan_version`）。
- **Execution State**：`task_runs` + `task_run_tasks`，支持九态与 `rev` 乐观锁（CAS）。
- **尝试历史**：`task_attempts` 按 `(run_id, task_id, attempt_id)` 保留全部历史尝试，
  旧记录不覆盖，便于追溯重试过程。
- **任务事件**：`task_run_events` 按 `sequence` 单调递增，`event_id` 幂等；
  绑定 `plan_version` / `input_snapshot` / `candidate_commit`。
- **断点恢复**：`task_run_checkpoints` + `build_run_checkpoint()` / `restore_run()`；
  恢复视图区分「已完成 / 在途 / 可恢复」，已完成任务不会被重复执行。
- **只读聚合**：`get_run_view(run_id)` 供 B05 与 B06 读取，不提供状态写入旁路。

本模块**不判断业务迁移合法性**（那是 B02 的职责），只拒绝非法状态值与 CAS 冲突。


## 3. 环境要求与快速开始

- Python 3.10+（开发验证版本 3.13.14）
- **仅使用 Python 标准库**，无需 `pip install` 任何第三方包

在 `b03` 目录执行：

```bash
python -m b03_implementation.run_checks          # 全套（28 项，含平台核心）
python -m b03_implementation.run_platform_checks # 仅平台核心（9 项）
```

<<<<<<< Updated upstream
预期输出：`Ran 37 tests ... OK`
=======
预期输出：全套 `Ran 28 tests ... OK`，平台核心 `Ran 9 tests ... OK`。
>>>>>>> Stashed changes

## 4. 关键设计约束

| 约束 | 落地方式 |
|---|---|
| B02 独占状态写入 | `cas_state` 用 `rev` 乐观锁，版本不符即拒绝 |
| 事件去重、过期回调不推进状态 | `event_id` 幂等；attempt/snapshot 不匹配打 `stale` 标记仅入日志 |
| 中断后可恢复、不重复执行 | 事件与检查点同事务；租约 TTL + 幂等派发键 + `reclaim_expired_leases` |
| 任务与产物版本一致 | 输入快照冻结；`get_artifacts_for_task` 只返回快照有效的产物 |
| 两类数据分开 | 黑板与校园业务分别使用 `blackboard.db` / `campus.db` |
| 凭据受保护 | PBKDF2 哈希；`LostView` 不含 `publisher_id`/联系方式/凭据；导出不含 `password_hash` |
| 防重复申请 | `(lost_item_id, applicant_id)` 唯一约束；资格检查与插入同一事务 |

## 5. 与组员对接

三份对接单均含**留空填写栏**，请对应负责人填入结论后回传：

- B01 蔡昀漪 → `B03-B01_规格与Schema对齐对接单_v1.0.md`
- B02 陈昱希 → `B03-B02_状态与租约接口对接单_v1.0.md`（固定交叉评审 `B02 ↔ B03`）
- B06 吴天昊 → `B03-B06_验收证据与测试数据对接单_v1.0.md`

B04/B05 的接口在 B02 对接单第 1、6 节一并定义，由 B02 转发对齐。

## 6. 合并到小组仓库的建议

1. 从共同仓库已接受提交创建独立分支：`feature/b03-blackboard`
2. 仅提交本包文件，不要覆盖受保护主线或他人文件
3. 通过合并请求（PR）接受 B02 交叉评审与 CI 检查后再合并
4. 接口变更须同步所有消费方，并在新提交上重跑受影响检查

## 7. 注意事项

- 测试数据为虚构/脱敏样例，不含真实个人信息。
- 运行时生成的 `*.db`、`checkpoint.json`、`__pycache__` 已由 `.gitignore` 排除，**不要提交**。
- 本实现采用设计文档开放问题 1 的当前假设（SQLite 标准库 + 双库分离）；若小组改选纯 JSON 检查点，接口层可保持不变，仅替换持久化实现。

## 8. 未决事项

租约 TTL 数值、事件 schema 最终字段、测试数据脱敏规则、`SUCCEEDED` 失效触发条件，分别待 B02/B01/B06/六人确认后更新版本。
