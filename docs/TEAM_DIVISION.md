# 团队分工方案（v2 · 按当前进度）

> 版本：2026-11-27 重写。取代 v1（老师对话记录版，见 git 历史 `a502cc9`）。
> 依据：① 修订版任务文档（`PROJECT_GOALS_AND_PROCESS.md` / docx）；② 当前代码实况（main `01f88cd`，已逐项核实）；③ 其他三组实跑调研（`REFERENCE_PROJECTS_3WAY.md`）的吸收清单；④ 老师的 2+2+2 建议（组 2 内容偏多，适当移出）与"先跑通再迭代"原则。
> 本文回答四件事：**现在做到哪了 → 谁管哪些分支 → 每个人具体做什么（内容/流程/细节/验收）→ 怎么协作不冲突**。

---

## 〇、开工前必读：每人开工仪式（强制）

**每位成员在每次开工前，先读仓库整体内容，再动自己的分支。** 这不是形式主义：现在每人管多个分支、跨阶段依赖多，不读全局就动手，最容易改坏别人正在消费的契约。

### 0.1 开工五步（每次 sit-down 都做，约 5 分钟）

| 步 | 命令 / 动作 | 目的 |
|---|---|---|
| 1 | `git fetch origin && git log --oneline -20 origin/main` | 看别人昨天推了什么，避免基于过期认知开工 |
| 2 | `git status --porcelain` + 确认自己在正确的分支上 | 防止把 A 分支的活提交到 B 分支 |
| 3 | 扫一遍 `docs/STAGE2_STATUS.md` 的「遗留项」和自己任务卡的前置条件 | 确认依赖方还没变卦 |
| 4 | `python workflow_runtime/run_all_checks.py`（或至少 `verify_contracts.py`） | 确认本地基线是绿的，坏的先报告，不叠加 |
| 5 | 在自己的任务分支 `git rebase origin/main`（或 merge）后再写代码 | 减少 PR 冲突 |

### 0.2 首周深读清单（每人一次性，约 2 小时）

| 顺序 | 读什么 | 为什么 |
|---|---|---|
| 1 | `README.md` 全文 | 项目定位、两阶段闭环、快速开始 |
| 2 | `docs/PROJECT_GOALS_AND_PROCESS.md`（本次修订版） | 目标与流程的唯一权威：基线对象、CAS、模型调用即工件、三类证据 |
| 3 | `docs/TASK_ORCHESTRATION.md` | B01—B06 的字段与接口契约，所有跨块联调按它判定 |
| 4 | `docs/STAGE2_STATUS.md` | 已完成项、8 条关键设计决定、5 条遗留项——你的任务大概率是遗留项之一 |
| 5 | 自己负责的目录（见 0.3 仓库地图）+ 对应测试 | 动手前知道现有测试怎么写 |
| 6 | `docs/REFERENCE_PROJECTS_3WAY.md` 第四节吸收清单 | 你的任务里标了"吸收自 X"的，去看那一节的做法 |

### 0.3 仓库地图（谁的家在哪儿）

| 目录 | 内容 | 主要责任 |
|---|---|---|
| `b02-workflow-agent/backend/` | 讨论状态机（`controller.py`）、角色适配（`adapters.py`）、阶段桥接（`phase_bridge.py`）、任务编排器（`task_orchestrator.py`）、任务 API（`task_api.py`）、HTTP 服务（`app.py`） | 组 1 / 组 2 |
| `b01-spec-planner/src/b01/` | 规格输入、动态计划、计划校验 | 组 2 |
| `b03/b03_implementation/task_state.py` | 状态持久化、事件、检查点 | 组 2 / 组 3 |
| `b04-agent-integration/src/b04/gateway.py` | 执行 Gateway（mock / 真实 runner 注入位） | 组 2 |
| `b06-quality-consensus/multiagent_quality/task_gate.py` | 九项必查质量门、缺陷登记 | 组 2 / 组 3 |
| `frontend/src/` | 工作台（`App.tsx` + `components/` + `constants/` + `api/`） | 组 1 / 组 3 |
| `workflow_runtime/` | 装配、`verify_contracts.py`、`run_all_checks.py`、四场景 pipeline | 全体（CI 门禁） |
| `docs/` | 全部设计文档 | 改哪份由对应任务卡指定 |

---

## 一、当前进度盘点（2026-11-27，main `01f88cd`，逐项核实过）

### 1.1 已完成（不要重做）

| 项 | 状态 | 证据 |
|---|---|---|
| 第二阶段闭环：规格 → 分解 → 编排 → mock 执行 → 质量门 → DAG | ✅ | `pipeline --scenario success` 24/24、`run_all_checks` 15/15 |
| 九态任务状态机、防重复派发、有限重试、阻断传播、断点恢复、回放一致 | ✅ | `task_orchestrator.py`、186 事件回放 0 不一致 |
| 单端口 7100：B02 托管前端生产构建 | ✅ | `app.py:_static` |
| 前端十页面分组侧栏工作台（项目/阶段一/阶段二/阶段三分组） | ✅ 本轮 | `constants/stages.ts`、`ui_smoke` PASS |
| 六人确认 UI 已移除；前端改为 `confirmDiscussionByConsensus`（过渡期传 agent 角色名单） | ✅ 本轮 | `App.tsx:57,287` |
| 圆桌 / 观测与回溯 / 基线卡 **界面占位**（无后端） | ✅ 本轮 | `RoundTableView.tsx`、`ObservationView.tsx`、`BaselineCard.tsx` |
| 四种任务视图（DAG/甘特/时间线/事件流）+ 六种导出 | ✅ | `frontend/src/components/`、`utils/export.ts` |
| 模型 API 配置（DeepSeek 及 OpenAI-compatible，密钥只在后端进程） | ✅ | `/api/llm/config` |
| 结构化布局断言 + 无头冒烟测试（自起 Chromium/CDP，不依赖 playwright） | ✅ 本轮 | `tests/ui_layout.mjs`、`tests/ui_smoke.mjs` |
| 三阶段文档体系 + 三组参考调研 | ✅ 本轮 | `docs/` |

### 1.2 未完成（本分工的工作对象，全部有代码级定位）

| # | 缺口 | 位置（核实过） | 归属 |
|---|---|---|---|
| G1 | 3 处 `WAITING_HUMAN` 人工审批门 | `controller.py:170,195,208` | 组 1 / A-1 |
| G2 | `MEMBERS` 六人名单与 `publish()` 六人全勾校验 | `adapters.py:9,239-241` | 组 1 / A-2 |
| G3 | 对话记忆表 `conversation_messages` 未实现（全仓库 0 命中） | B03 SQLite | 组 1 / A-3 |
| G4 | H 阶段设计规格未细化：契约引用全空 | `phase_bridge.py:108`（`contract_refs: []`） | 组 1 / B-1 |
| G5 | 基线对象缺 `revision / parent_baseline_id / sha256`（前端占位已在等） | `phase_bridge.py` | 组 1 / B-2 |
| G6 | 计划编辑不可回写、无 CAS、`input_snapshot` 不强制 | `task_api.py`、STAGE2_STATUS 遗留 5 | 组 2 / C-1, C-2 |
| G7 | 执行仍是 mock（`simulated=True`），无网页产物 | `b04/gateway.py` | 组 2 / D-1, D-2 |
| G8 | 契约靠手写文档，无机器可读 Schema | `TASK_ORCHESTRATION.md` | 组 2 / C-3 |
| G9 | 任务图只有 task+dep，无 decision/checkpoint/join 语义 | `dynamic_planner.py`、`task_orchestrator.py` | 组 2 / C-4 |
| G10 | 全部案例为 C0 手写（无 `phase1_source`） | `b01-spec-planner/docs/fixtures/` | 组 2 / D-5 |
| G11 | 观测 schema 未定义；模型调用无记录 | 无此表 | 组 3 / E-1, E-2 |
| G12 | 圆桌、观测页是占位（前端无后端） | `RoundTableView/ObservationView` | 组 3 / A-5, E-3, F-2 |
| G13 | B06 签名证据未接执行链；真实验收未成文 | STAGE2_STATUS 遗留 2、无 REAL 报告 | 组 3 / E-4 |
| G14 | 5 个远端分支未并入 main，8 个已并入未清理 | 见第二节 | 全体 / 0-2 |

---

## 二、分支现状与治理（先清理，再开工）

### 2.1 现状

旧的模型是"一人一分支"：B01—B06 六个工作块各挂一个长期分支。现在代码已经全部汇到 `main`，旧的六分支有的已并入、有的成了无人认领的僵尸。新模型见第三节：**每人管理 2 条功能分支 + 若干短期任务分支**。

| 类别 | 分支 | 最后提交 | 处理 |
|---|---|---|---|
| 共享 | `main` | 11-27 | 保护分支：只接受每周发布合并 |
| 共享 | `integration` | 11-27 | 集成分支：所有 PR 先进这里 |
| 已并入 main（8 个） | `b06-quality-consensus`、`feat/b02-b05-single-port`、`feat/llm-adaptive-workbench`、`feat/second-stage-closed-loop`、`feat/unify-b05-and-fix-bridge`、`feat/workbench-gantt-export`、`feature/b03-platform-store`、（`integration` 本身） | 11-16 ~ 11-27 | 确认无本地依赖后**删除远端** |
| 未并入 main（5 个） | `b01-spec-planner`(11-18)、`feat/b02-discussion-controller`(11-17)、`feature/b03-blackboard`(11-17)、`feat/b05-frontend-viz`(11-18)、`b04-agent-integration-task-delivery`(11-18) | 均早于闭环完成 | 指定人逐个评审：有价值内容 cherry-pick 或写明放弃理由，然后删除 |

### 2.2 治理任务（0-2，合计约 6h，一周内完成）

| 责任人 | 任务 | 步骤 |
|---|---|---|
| 成员 C | 评审 `b01-spec-planner`、`feature/b03-blackboard` | `git log origin/main..<branch> --oneline` 列差异 → 逐 commit 判断是否已在 main 有等价实现 → 有价值的开 task 分支 cherry-pick 并 PR，没有的在 PR/群内写一行放弃理由 → 建议 `git push origin --delete` |
| 成员 D | 评审 `b04-agent-integration-task-delivery`（含本地同名分支） | 同上 |
| 成员 F | 评审 `feat/b05-frontend-viz`、`feat/b02-discussion-controller` | 同上 |
| 成员 A | 通知全组核对本地旧分支；一周后执行 8 个已并入分支的远端删除 | `git branch -r --merged origin/main` 复核 → 群内公示 48h → `git push origin --delete <branch>`；删除清单写进本文档变更记录 |

**红线**：删除远端分支前必须在群里公示 48 小时；任何人提出本地未合并工作，该分支暂缓删除。

---

## 三、分支管理模型（一人多分支）

### 3.1 分支类型与命名

| 类型 | 命名 | 生命周期 | 谁能推 |
|---|---|---|---|
| 主干 | `main` | 永久；每周发布合并一次 | 发布责任人（经 PR） |
| 集成 | `integration` | 永久；所有 PR 的目标分支 | 有 CI 绿 + 组内互审即可合并 |
| 个人功能分支 | `feat/<阶段>-<主题>`，如 `feat/p1-agent-consensus` | 跨周存在；按主题划分，不按人名划分 | 属主成员 |
| 任务分支 | `task/<成员>-<编号>-<短名>`，如 `task/a-g1-remove-gates` | 从对应功能分支切出，随 PR 合并消亡 | 属主成员 |
| 修复分支 | `fix/<主题>` | 短期 | 任何人，PR 评审 |

**规则**：
1. 每条功能分支有唯一属主；别人要改，先在 PR / 群里打招呼，避免两条分支改同一文件。
2. 功能分支每周至少 rebase 一次 `origin/main`，落后超过 20 个 commit 必须先同步再继续开发。
3. 任务分支 = 功能分支的一次交付单元；PR 目标是**功能分支本身**（组内互审后再由属主把功能分支 PR 到 `integration`）。
4. 跨组共享的文件（`workflow_runtime/verify_contracts.py`、`TASK_ORCHESTRATION.md`、前端 `App.tsx` 顶栏）改动必须先在本表登记到当周计划里，避免对撞。

### 3.2 每人分支一览（6 人 × 2~3 条功能分支）

| 成员 | 组 | 功能分支（属主） | 主要涉及目录 |
|---|---|---|---|
| **A** | 1 | `feat/p1-agent-consensus`（状态机与共识）<br>`feat/p1-conversation-memory`（对话记忆与圆桌后端） | `controller.py`、`adapters.py`、`workflow_definition.py`、B03 |
| **B** | 1 | `feat/p1-design-spec`（设计规格细化与基线）<br>`feat/p1-frontend-discussion`（阶段一前端与埋点） | `phase_bridge.py`、`frontend/src`、B04 llm 调用点 |
| **C** | 2 | `feat/p2-plan-editing`（编辑回写 / CAS / 增量分解）<br>`feat/p2-contract-schema`（契约 JSON Schema 与图语义） | `task_api.py`、`dynamic_planner.py`、`verify_contracts.py` |
| **D** | 2 | `feat/p2-real-execution`（真实 runner / 网页产物 / 分档路由）<br>`feat/p2-cases`（案例重建） | `b04/gateway.py`、`b02` 预览路由、`fixtures/` |
| **E** | 3 | `feat/p3-observation`（观测 schema / 埋点 / 观测页）<br>`feat/p3-acceptance`（三类验收证据） | B02 llm 层、`task_state.py`、`ObservationView.tsx` |
| **F** | 3 | `feat/p3-roundtable`（圆桌交互前端）<br>`feat/p3-unified-ui`（统一框架 / 可达性 / 性能） | `frontend/src/components/`、`App.css` |

**共享分支**：`integration`（全体可 PR）、`main`（发布责任人合并）。旧分支 `bXX-*` 全部只读待删，不再开发。

---

## 四、三组分工（2+2+2，任务卡）

> 约定：每张卡给出 **内容 / 前置 / 步骤 / 细节红线 / 验收 / 涉及文件 / 分支 / 估时**。估时含测试与文档；标"吸收自 X"的请先读 `REFERENCE_PROJECTS_3WAY.md` 对应小节。

### 组 1 · 阶段一：用户想法 → 设计规格基线

**组目标**：讨论全程无人工审批门（G1/G2），用户并行插话可追溯（G3），阶段一终点是带哈希与父链的设计规格基线（G4/G5），圆桌有真实后端（G12 前半）。

#### 成员 A（讨论状态机与 agent 共识）

| 卡 | 内容 | 前置 | 估时 |
|---|---|---|---|
| **A-1** | 拆除三处 `WAITING_HUMAN` 人工门 | 无（本组第一优先） | 12h |
| **A-2** | `publish()` 六人确认 → agent 共识确认 | A-1 | 6h |
| **A-3** | 对话记忆表 `conversation_messages` + 阶段边界消费 | 无 | 16h |
| **A-4** | 简化 / 极简模式（同一状态机裁剪跳阶段） | A-1 | 8h |
| **A-5** | 圆桌后端：四个非阻塞指令接口 | A-3、与 F-2 联调 | 10h |
| A-6 | 分支治理（0-2 的公示与删除执行） | 无 | 2h |

**A-1 拆除三处人工门**

| 字段 | 内容 |
|---|---|
| 内容 | `controller.py` 三处 `run["status"] = "WAITING_HUMAN"`（:170 EVALUATE 分歧、:195 Proposal 被拒、:208 需求确认）全部改为 agent 自动处理 |
| 前置 | 按 0.2 读完 `controller.py`、`workflow_definition.py`、`adapters.py`；跑一遍 `python -m unittest discover -s tests -v`（B02）确认基线绿 |
| 步骤 | ① 在 `task/a-g1-remove-gates` 分支新增 `auto_debate(run, objection)`：对未解决异议发起 ≤ `max_rounds` 轮角色间辩论，每轮产出新增 `stances`，轮次用尽仍分歧 → 按"有条件赞同最低者"方案继续并保留异议记录（不阻塞）。② `:170` 改为调用 `auto_debate` 后直接进入 PROPOSAL_REVIEW。③ `:195` 被拒改为自动修订重试：复用 B02 现有起草链路，重试计数挂 run，超 3 次按现有 `STOPPED` 语义诚实停止（不得伪装成功）。④ `:208` 改为直接调用 A-2 的共识确认。⑤ 同步更新 `workflow_definition.py` 的 `STAGES / TRANSITIONS / PSEUDOCODE`（`/api/workflow` 会把伪代码暴露给前端）。⑥ 为三个控制点各写一条单测：断言事件流里不再出现 `WAITING_HUMAN`。 |
| 细节红线 | ① 判定者从人换成 agent，但**"多角色参与"与"异议必须被解决（或显式记录）"的门槛保留**；② `STOPPED` 语义不许删——预算耗尽诚实停止是文档 N8 的要求；③ 不改前端（前端已按共识模式传参），发现问题报 F。 |
| 验收 | `python -m unittest discover -s tests -v` 全绿 + 新增 3 条单测；`workflow_runtime/run_all_checks.py` 15/15；用 `scenario=normal` 从想法一路跑到 R1 全程无人工事件。 |
| 涉及文件 | `controller.py`、`workflow_definition.py`、`b02 tests/` |
| 分支 | `feat/p1-agent-consensus` ← `task/a-g1-remove-gates` |

**A-2 agent 共识确认**

| 字段 | 内容 |
|---|---|
| 内容 | 删除 `adapters.py:9` 的 `MEMBERS`；`publish(draft, members)`（:239-241）改为 `publish(draft, roles)`：要求 `ROLES` 全部表态，全部 Agree / Conditional（条件已闭环）才发布 R1；`confirmed_by` 写 agent 角色名 |
| 前置 | A-1 合并到功能分支 |
| 步骤 | ① `publish()` 内校验 `set(roles) == set(ROLES)` 且无 Pending；② 有 Disagree → 抛 `WorkflowError` 并触发 A-1 的自动辩论路径；③ `confirmed_by` 保留字段名（前端基线卡直接显示）；④ 同步改 `app.py:223` 的 `/confirm` 处理与 `controller.confirm_requirements`（:233）；⑤ 前端 `AGENT_ROLES` 过渡参数此时与后端完全对齐，无需改前端——在 PR 里说明这一点。 |
| 细节红线 | `confirmed_by` 是 G5 基线对象的字段之一，格式保持 `list[str]`（角色名），不要改成对象数组。 |
| 验收 | 单测覆盖：角色齐全→发布成功；缺一→拒绝且消息可读；六人校验相关旧测试改写后全绿。 |
| 涉及文件 | `adapters.py`、`controller.py`、`app.py`、`b02 tests/` |
| 分支 | `feat/p1-agent-consensus` |

**A-3 对话记忆表**（任务文档 2.2.2 已定行为）

| 字段 | 内容 |
|---|---|
| 内容 | 建表 `conversation_messages(message_id, run_id, stage, role, content, created_at, consumed_at, applied_to)`，落 B03 SQLite；实现"用户消息入队 → 不阻塞 → 阶段边界一次性消费 → 标记 consumed_at + applied_to" |
| 前置 | 无；与 C 组共享 B03 文件，**先在群里约时间窗** |
| 步骤 | ① 在 `task_state.py` 同目录新增 `conversation.py`，复用其连接与事务风格；② `app.py` 暴露 `POST /api/runs/{id}/messages`（用户插话入口，非阻塞 202）与查询接口；③ `controller` 各阶段边界插入消费点：有未消费消息 → 注入提示词上下文 → 应用到当前产物 → 写 `applied_to`（产物版本）；④ 用户意见与 agent 结论冲突时，要求回应文本里显式出现"已考虑你的意见，但…"（写入黑板 decisions）；⑤ 连发多条按时间排序一次消费；⑥ 单测：插入 3 条消息→推进 2 个阶段→断言 consumed_at 全部落、applied_to 指向正确版本、期间无阻塞。 |
| 细节红线 | ① 对话是"输入"，状态事件是"事实"——两套表严格分开（文档 2.3）；② 任何情况下不得因等待用户而暂停（N6）。 |
| 验收 | B03 `pytest -q` 绿 + 新单测；`/api/runs/{id}` 返回里能看到 messages 消费状态。 |
| 涉及文件 | `b03/b03_implementation/`、`app.py`、`controller.py` |
| 分支 | `feat/p1-conversation-memory` |

**A-4 简化/极简模式**：同一状态机支持 `完整 / 简化（跳 F、G）/ 极简（讨论后直接结论）` 三种裁剪。步骤：在 run 上加 `mode` 字段 → `advance` 按模式跳过对应阶段 → 每种模式各一条端到端单测 → `POST /api/runs` 接受 `mode` 参数 → 前端主理人页加模式下拉（与 B 协作，1h）。红线：向下兼容（N2），裁剪不许改共享的迁移表语义。估时 8h。

**A-5 圆桌后端**：四个指令接口 `点名 / 追问 / 要求举证 / 发起辩论`（`POST /api/runs/{id}/roundtable`，动作+目标角色+文本）。全部走 A-3 的记忆表（非阻塞），由被点名 agent 在下一阶段边界响应；辩论指令让两个 agent 各自追加一条 stance。验收：前端占位页（F-2）接上后可走通一次点名-回应往返。红线：接口语义与 `REFERENCE_PROJECTS_3WAY.md` 2.1 SE-DPA 的 steward 指令对齐但**不复制实现**。估时 10h。

#### 成员 B（设计规格、基线与阶段一前端）

| 卡 | 内容 | 前置 | 估时 |
|---|---|---|---|
| **B-1** | H 阶段设计规格细化（契约补全） | A-2（确认语义稳定） | 18h |
| **B-2** | 基线对象后端（revision/parent/sha256） | B-1 | 8h |
| **B-3** | 阶段一前端深化（对话流/八阶段实时/立场卡） | A-3 接口 | 14h |
| **B-4** | 阶段一观测埋点（model_call 工件） | E-1 schema 定稿 | 8h |
| **B-5** | 用完整流程生成第一个 C2 案例 | B-1、A-1 | 6h |

**B-1 设计规格细化**：`phase_bridge.py` 的 `contract` 目前只有骨架（`contract_refs: []` @:108）。步骤：① 按 `TASK_ORCHESTRATION.md` §2.1 定义 operations（名称/方法/路径/鉴权/请求响应字段/状态码）、errors（错误码→HTTP 映射）、field_bounds（长度/格式/必填/取值域）、response_envelope、data_model、非功能约束六块生成逻辑；② 参照 SE-lib `docs/contracts/design-spec.schema.json` 的**字段组织方式**（吸收自 SE-lib 3.2，不抄内容）；③ 由 R1 的需求条目推导：每个带验收条件的需求至少一个操作 + 对应错误码；④ 更新 `docs/TASK_ORCHESTRATION.md` §2.1 的示例；⑤ 单测：生成的 spec 通过 Schema 校验、`contract_refs` 非空。红线：桥接只做结构化转换，不代替评审（文档 2.3 约束 3）。验收：`verify_contracts.py` 增加"contract 非空"检查项并通过。

**B-2 基线对象**：给桥接产物加 `baseline_id / revision / parent_baseline_id / sha256`。步骤：① `sha256` 对规范化后 JSON（键排序、空白归一）计算——**必须两侧一致**，吸收自 SE-lib 的 input_hash 做法；② 同一 run 的需求变更产生 revision+1 并写 parent；③ `/api/runs/{id}/design-spec` 返回体带上这些字段；④ 与 C-2 对齐哈希工具函数（放 `workflow_runtime/` 共享，别各写一份）。验收：前端 `BaselineCard.tsx` 的"待后端补齐"占位自动变实值（F 侧确认渲染）；两次相同输入 hash 相同。估时 8h。

**B-3 阶段一前端深化**：主理人页接入 messages 接口显示"已收到，将在阶段边界应用"；讨论页 `RoundTableView` 的八阶段进度从真实 `stage` 实时刷新（`phaseIndexForStage` 已有映射）；需求页立场卡显示 confirmed_by（后端 A-2 完成后自然生效）。红线：不改 `constants/stages.ts` 的页面定义（跨组共享，改动需登记）。估时 14h。

**B-4 观测埋点**：按 E-1 定稿的 schema，在 B02 模型调用返回处（`llm.py`）落 `model_call` 记录（run/attempt/node/role/model/input_hash/output_hash/usage/latency/status）。红线：schema 未定稿前不动手，先催 E。估时 8h。

**B-5 C2 案例**：用"想法→讨论→R1→桥接"真实流程生成一个带 `phase1_source.generation_source=llm` 的 spec 存入 `fixtures/`，替代手写样例作为组 2 的输入演示。估时 6h。

---

### 组 2 · 阶段二：设计规格基线 → 编排 → 真实执行 → 网页产物

**组目标**：计划可编辑且有并发保护（G6），契约机器可读（G8），任务图有结构语义（G9），执行产出真实网页（G7），案例从 C0 升到 C2/C3（G10）。

#### 成员 C（计划数据模型、契约与图语义）

| 卡 | 内容 | 前置 | 估时 |
|---|---|---|---|
| **C-1** | 节点编辑 + 回写 API + 并行批次视图完善 | 无 | 16h |
| **C-2** | 计划 CAS（expected_revision）+ input_hash 强校验 | 无 | 6h |
| **C-3** | 契约单一来源：字段抽 JSON Schema + 一致性校验 | 无 | 10h |
| **C-4** | 任务图节点语义：decision/checkpoint/join + pass/fail/loop 边 | C-3 | 12h |
| **C-5** | 增量分解 / 重新分解 | C-1 | 8h |
| C-6 | 分支治理：评审 `b01-spec-planner`、`feature/b03-blackboard` 旧分支 | 无 | 2h |

**C-1 节点编辑与回写**：后端 `PATCH /api/task-plans/{plan_id}/tasks/{task_id}`（增删任务、改依赖、改验收条件、改测试编号），每次编辑生成新计划版本（复用 `register_plan` 的版本冲突保护），旧运行继续绑定启动版本。前端：`TaskGraph` 当前 `useEffect` 每次刷新覆盖布局——改为布局与数据分离（位置存 localStorage 或后端 layout 字段，吸收自 SE-lib 的 Layout 节点做法），拖动/连线可保存。验收：编辑→校验（依赖存在/无环/需求全覆盖/产物唯一）→新版本号+1→运行不受影响；刷新页面布局不丢。红线：**不原地改已派发的计划**（文档 2.4.6）。估时 16h。

**C-2 计划 CAS + 哈希**（吸收自 SE-lib 的 `expected_revision`）：① 写接口带 `expected_revision`，不匹配返回 409 `REVISION_CONFLICT` 并附当前版本号；② 每版本记录规范化 `input_hash`，运行创建时校验一致，不一致拒绝；③ 关闭 STAGE2_STATUS 遗留 5（`validate_plan_document` 强制 `input_snapshot`）；④ 复用 B-2 的共享哈希工具。验收：并发编辑场景单测——甲乙同基于 v3，甲成 v4，乙提交得 409 且错误体带当前版本；前端在错误提示里显示"计划已更新到 v4"（与 F 约一个 1h 联调）。估时 6h。

**C-3 契约 JSON Schema**（吸收自 SE-lib 3.1）：把 `TASK_ORCHESTRATION.md` 的任务/计划/事件字段抽成 `docs/contracts/task-plan.schema.json` 等机器可读文件；`verify_contracts.py` 加一致性检查（代码里的状态枚举、哈希正则等常量与 Schema 对齐，防再出 B04/B06 哈希不一致类 bug）；前端类型后续可由 Schema 生成（与 F 约定即可，不强求本轮）。红线：改 Schema 必须同步本文档 §0.3 登记的所有消费方。估时 10h。

**C-4 图节点语义**（吸收自 TeamPrjoect Twin-Graph，取最小集）：计划文档增加可选 `node_type`（task 默认 / decision / checkpoint / join）与 `edge_type`（dep 默认 / pass / fail / loop）；B01 按"验收任务失败可走 fail 分支到修复任务"生成最小示例；B02 校验合法性；B05 按类型渲染（decision 菱形、checkpoint 锚点图标）。红线：九态状态机**不动**，这是叠加的图语义层。估时 12h。

**C-5 增量分解**：`POST /api/task-plans/{plan_id}/rederive`，按当前基线重算受影响任务（基线变了哪些需求 → 哪些任务重导出），未受影响任务保留编号。估时 8h。

#### 成员 D（执行链路与案例）

| 卡 | 内容 | 前置 | 估时 |
|---|---|---|---|
| **D-1** | B04 真实 runner（模型生成文件，产物不伪提交） | 无 | 14h |
| **D-2** | 网页产物 + `/preview/<run_id>/` 预览（复用 7100） | D-1 | 8h |
| **D-3** | 写入范围校验 + 失败不伪提交 | D-1 | 6h |
| **D-4** | 模型分档路由（规划高档 / 生成低档） | D-1 | 6h |
| **D-5** | 案例重建：L1→L2→C3（配合 B-5 的 C2） | D-2 | 10h |
| **D-6** | 分支治理：评审 `b04-agent-integration-task-delivery` 旧分支 | 无 | 2h |

**D-1 真实 runner**：`gateway.py` 已有 `runner_callable` 注入位与结果契约校验（STAGE2_STATUS 遗留 1）。步骤：① 实现 `ModelFileRunner`：输入=任务 goal/acceptance/写范围，调模型输出文件内容，返回 envelope（artifacts 带 `simulated=False`、content 哈希）；② 失败路径：模型空返回 / 截断 / 语法无效 → 返回结构化错误（目标文件、原因、可重试性），**不登记产物**（吸收自 SE-DPA "不伪提交"）；③ 重试沿用现有 retry_count 预算；④ `evidence` 场景的冒烟保持可用（mock 与真实并存，`mode` 显式选择）。红线：模拟与真实严格分离（N8）——真实 runner 失败就是失败，不许回落 mock；B06 证据链接入是 E 组的卡，别越界改 `task_gate.py`。验收：单测（假模型客户端）+ 一次真实模型手测记录（贴进 PR）；`run_all_checks` 不回归。估时 14h。

**D-2 网页产物与预览**：产物按运行归档 `work/deliverables/<run_id>/index.html`（内联 CSS/JS，零构建）；`app.py` 加 `GET /preview/<run_id>/` 静态路由（复用 7100，N7）；交付页（08）加"打开预览"按钮（与 F 约一个 1h 联调）。验收：浏览器打开预览、核心交互可点。估时 8h。

**D-3 写入范围**：执行前按任务 `write_scope` 校验产出路径，越界即失败并记录；目录前缀按路径段匹配（防 `app` 误匹配 `app2`，吸收自 SE-DPA 契约 §3）。估时 6h。

**D-4 分档路由**（吸收自 SE-DPA `model_router.py` 的思路）：规划/复核/集成用高档模型，逐文件生成用低档；配置进 `/api/llm/config` 现有结构（加 `tiers` 可选字段）。估时 6h。

**D-5 案例重建**：L1 四则计算器（手写最小 spec 走通链路）→ L2 待办事项 → 用 B-5 的 C2 规格与 D-1 真实执行产出 **C3 端到端案例**；每个案例固定输入、可 `pipeline --spec` 重跑、输出对比。红线：手写 fixture 只作输入测试，验收口径是"至少一个 C3"（文档 1.5）。估时 10h。

---

### 组 3 · 阶段三：可观测性 + 执行交互 + 统一框架

**组目标**：观测 schema 定稿并落地（G11），圆桌真实可用（G12），真实模型验收成文（G13），前端风格统一（本轮已打基础）。

#### 成员 E（观测数据与验收证据）

| 卡 | 内容 | 前置 | 估时 |
|---|---|---|---|
| **E-1** | 观测数据 schema 定稿（含模型调用一等主体） | 无（本周第一优先） | 10h |
| **E-2** | 埋点落地：讨论事件 + 模型调用进同一观测体系 | E-1、B-4 配合 | 14h |
| **E-3** | 观测与回溯页真实数据（跨阶段时间轴 / 工件表 / 复盘） | E-2、F 联调 | 14h |
| **E-4** | 三类验收报告：REAL_ACCEPTANCE 等成文 | D-1 有真实运行后 | 6h |
| **E-5** | B06 签名证据接入执行链（STAGE2_STATUS 遗留 2） | D-1 | 8h |
| E-6 | 分支治理：评审 `feature/b03-blackboard`（与 C 拆分：C 评审该分支，E 只复核）→ 改为：复核 C 的评审结论 | 无 | 1h |
| E-7 | 三组案例成熟度台账：维护 C0→C3 状态表 | 持续 | 2h |

**E-1 schema 定稿**：按任务文档 2.5.2 五要素（主体/类型/时间/上下文/载荷）写 `docs/OBSERVATION.md` + `docs/contracts/observation.schema.json`。**模型调用是一等主体**（吸收自 TeamPrjoect"每次调用即工件"）：`call_id / run_id / attempt_id / node_id / role / provider / model / input_hash / output_hash / usage{in,out} / latency_ms / status(success|budget_exhausted|needs_input|failed)`。讨论阶段事件（A—H 的黑板变化）与任务事件进同一 schema，靠 `subject` 区分。**本周内定稿并冻结**——B-4、E-2、E-3 全等它。估时 10h。

**E-2 埋点**：B03 新增 observation 表（复用 task_state 连接）；讨论侧由 A-3 的消费点同步写入；任务侧由编排器既有事件桥接（不重复写，引用 event sequence）。红线：不写两遍——同一事实一条记录。估时 14h。

**E-3 观测页真实化**：`ObservationView.tsx` 占位全部换真数据——跨阶段时间轴（对齐算法：以"提交想法"为 t₀，各阶段起止投影；占位样式已有 `.obs-*`）；工件表接真实 model_call；回溯区三块中"技术级"复用编排页回放接口，"因果级"做"产物→调用→输入版本"反查链（点击产物 hash 弹出调用明细）。验收：ui_smoke 更新断言工件表行数>0（真实运行时）。估时 14h。

**E-4 三类验收报告**（吸收自 SE-lib 3.4）：`docs/testing/REAL_ACCEPTANCE_REPORT.md`——单独触发真实模型运行（勿默认进 CI，防费用），记录模型 ID / usage / 耗时 / 输入 hash / 结果；`P0_CLOSURE` 用现有 `run_all_checks` 输出；`QUALITY` 引用 F-4 的基准结果。估时 6h。

**E-5 签名证据链**：mock 执行器不产签名 → 让 D-1 的真实 runner 把测试结果走 B06 `evidence.check_evidence` 的 HMAC 校验与 `runner.run_suite` 受控执行（遗留 2 原文）。与 D 约接口（runner 返回 evidence 字段）。估时 8h。

#### 成员 F（圆桌交互与统一框架）

| 卡 | 内容 | 前置 | 估时 |
|---|---|---|---|
| **F-1** | 圆桌前端实现（对接 A-5） | A-3/A-5 接口就绪 | 14h |
| **F-2** | 编辑/CAS 冲突的 UI 呈现（对接 C-1/C-2） | C-2 | 6h |
| **F-3** | 统一可视化框架收尾：组件复用与样式规范文档 | 无 | 10h |
| **F-4** | 性能与可达性基准进测试（吸收自 SE-lib 3.4/性能测试） | 无 | 10h |
| **F-5** | 交付页预览按钮（对接 D-2） | D-2 | 2h |
| **F-6** | 分支治理：评审 `feat/b05-frontend-viz`、`feat/b02-discussion-controller` 旧分支 | 无 | 2h |

**F-1 圆桌前端**：占位页 `RoundTableView.tsx` 接 A-5 四指令；发言流合并真实 claims / objections（已有渲染逻辑）与用户消息（A-3 记忆表回读）；插话发送后立即显示"已收到，将在下一阶段边界应用"（非阻塞反馈，文档 2.2.2 语义边界）。红线：**不设任何审批按钮**；用户不响应不影响流程。验收：ui_smoke 新增"点名→agent 回合边界后出现回应"断言（用假后端 fixture）。估时 14h。

**F-2 CAS 冲突 UI**：C-2 的 409 → 前端弹"计划已更新到 vX"差异提示与"在 v4 上重做 / 放弃"选择。估时 6h。

**F-3 统一框架收尾**：把本轮已建立的 token 体系（`App.css :root`）写成 `docs/UI_GUIDELINES.md`（色彩/间距/徽标/占位块/表格用法 + 反例）；抽查各页替换残留的硬编码色值。红线：纯样式重构的 PR 不混功能改动。估时 10h。

**F-4 基准测试**：仿 SE-lib `performance.test.mjs` 思路，用现有 CDP 无头方案加两条断言：① 大图首屏可交互 < 2s（100 任务级 fixture）；② 对比度 ≥ 4.5、键盘可达焦点 ≥ 5（现有 badge/按钮体系核对）。输出 `work/ui-perf.json` 供 E-4 引用。估时 10h。

---

### 共同任务（0-x，计入各组工作量）

| # | 任务 | 责任人 | 估时 | 完成标志 |
|---|---|---|---|---|
| 0-1 | 开工仪式执行（0.1 每次开工 + 0.2 首周深读） | 全体 | 2h/人 | 各自 PR 描述附"已读清单" |
| 0-2 | 分支治理（第二节 2.2） | A/C/D/F | 6h+2h | 旧分支清理完毕并记录 |
| 0-3 | 契约冻结会（一次 2h 会议）：E-1 观测 schema × C-3 计划 Schema × B-2 基线字段 三者对齐；产出会议纪要写入 `TASK_ORCHESTRATION.md` | E 主持，B/C/D 到场 | 2h | Schema 冻结 v1 |
| 0-4 | 每周发布：周五由轮值组把 `integration` 合并到 `main` 并打 tag | 轮值组 | 1h/周 | main 绿 + tag |

---

## 五、协作流程

### 5.1 一次典型交付（以 A-1 为例）

```text
读仓库（0.1 五步）
  → git switch -c task/a-g1-remove-gates feat/p1-agent-consensus
  → 实现 + 单测
  → python -m unittest discover -s tests -v && python workflow_runtime/run_all_checks.py
  → push 任务分支 → PR（目标：feat/p1-agent-consensus）
  → 组内互审（B 审 A）+ CI 绿 → 合并
  → 功能分支 → PR（目标：integration）→ 对组组长复核 → 合并
  → integration 上跑 run_all_checks + ui_smoke → 周五随发布进 main
```

### 5.2 审查规则

| 规则 | 内容 |
|---|---|
| 组内互审 | 同组另一人必审；跨组消费方（契约变更时）加审 |
| PR 描述必备 | 任务卡编号、需求/文档引用、修改范围、测试命令与结果、已知限制 |
| CI 门禁 | `.github/workflows/integration.yml`（B01—B06 测试 + 闭环 + 前端三件套）必须绿 |
| 冲突处理 | 先按冻结契约判断谁对谁错（BRANCHING.md 原则），再谈代码；共享文件（0.3 登记）改动提前一天在群里说 |

### 5.3 节奏

| 频率 | 事项 |
|---|---|
| 每次开工 | 0.1 五步 |
| 每日 | 组内 10 分钟同步：昨天推了什么 / 今天动哪些文件 |
| 每周中 | 功能分支 rebase origin/main；落后 >20 commit 强制同步 |
| 每周五 | 发布：integration → main（轮值组），打 tag `v0.x`，跑一遍 `ui_smoke + ui_layout + run_all_checks` 留档 |
| 每两周 | 案例重跑对比（D-5 的固定输入集），结果贴进 E-7 台账 |

---

## 六、工作量汇总

| 成员 | 组 | 任务卡 | 合计 |
|---|---|---|---|
| A | 1 | A-1 12 + A-2 6 + A-3 16 + A-4 8 + A-5 10 + A-6 2 | **54h** |
| B | 1 | B-1 18 + B-2 8 + B-3 14 + B-4 8 + B-5 6 | **54h** |
| C | 2 | C-1 16 + C-2 6 + C-3 10 + C-4 12 + C-5 8 + C-6 2 | **54h** |
| D | 2 | D-1 14 + D-2 8 + D-3 6 + D-4 6 + D-5 10 + D-6 2 | **46h** |
| E | 3 | E-1 10 + E-2 14 + E-3 14 + E-4 6 + E-5 8 + E-6 1 + E-7 2 | **55h** |
| F | 3 | F-1 14 + F-2 6 + F-3 10 + F-4 10 + F-5 2 + F-6 2 | **44h** |
| 全体 | — | 0-1（2h/人）+ 0-3（2h/人）+ 0-4（1h/周×轮值） | 约 +5h/人 |

**每人 49~59h**，基本均衡；对比 v1 的组 2 偏重问题（老师指出），本轮已把编排侧拆给 C/D 两线、观测埋点拆给 B/E 协作。按每人每周 12~15h，约 4 周完成。

### 排期（吸收"先跑通再迭代"，三周为界）

| 周 | 目标 | 关键卡 |
|---|---|---|
| 第 1 周 | **链路通**：无审批门的讨论 → R1 → 基线 → 真实 runner 出文件 | A-1、A-2、D-1（最小版）、E-1 schema 冻结、0-2 治理 |
| 第 2 周 | **可编辑 + 可观测**：计划 CAS 与编辑、对话记忆、埋点落地、网页预览 | A-3、C-1、C-2、B-2、D-2、E-2 |
| 第 3 周 | **深化与证据**：图语义、圆桌真实化、观测页真实数据、C3 案例、三类报告 | C-4、F-1、E-3、D-5、B-1 收尾、E-4 |
| 第 4 周 | 收尾与答辩准备：F-3/F-4、简化模式、增量分解、回归与文档 | A-4、C-5、其余收尾卡 |

---

## 七、风险与交接

| 风险 | 缓解 |
|---|---|
| E-1 schema 拖延阻塞 B-4/E-2 | 设为第 1 周硬门禁；冻结后改动走 0-3 一样的小会 |
| A 组与 C 组同改 `app.py` 路由 | 0.3 登记 + 每日同步；路由新增按前缀分段（`/api/runs/...` 归 A，`/api/task-*` 归 C/D） |
| 真实模型产生费用 | REAL 运行单独触发、记录用量；CI 一律 mock（N8） |
| 旧分支里有人本地未推工作 | 删除前 48h 公示（2.2 红线） |
| 成员缺席 | 每张任务卡有"涉及文件 + 分支"字段，接手人按卡重建环境即可；功能分支属主缺席超 3 天，同组另一人接管并在分支表更新 |

## 八、变更记录

| 日期 | 变更 |
|---|---|
| 2026-11-27 | v2 重写：按 main `01f88cd` 实况核对完成/未完成清单；分支模型从"一人一块一分支"改为"一人多分支 + 阶段功能分支"；加入三组调研吸收项（CAS、基线哈希、模型调用工件、真实执行闭环、图语义、性能基准）；加入旧分支治理任务与开工仪式。v1（老师对话记录）见 git 历史。 |
