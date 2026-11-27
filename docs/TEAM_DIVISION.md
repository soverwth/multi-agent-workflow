# 团队分工方案（v2 · 按当前进度）

> 版本：2026-11-27 重写。取代 v1（老师对话记录版，见 git 历史 `a502cc9`）。
> 依据：① 修订版任务文档（`PROJECT_GOALS_AND_PROCESS.md` / docx）；② 当前代码实况（main `01f88cd`，已逐项核实）；③ 其他三组实跑调研（`REFERENCE_PROJECTS_3WAY.md`）的吸收清单；④ 老师的 2+2+2 建议（组 2 内容偏多，适当移出）与"先跑通再迭代"原则。
> 本文回答四件事：**现在做到哪了 → 谁管哪些分支 → 每个人具体做什么 → 怎么协作不冲突**。
> **v2.1（2026-11-27）拆分为 1 份总纲 + 6 份个人文档**：总纲只保留全局视图与跨人依赖；每张任务卡的步骤、红线、验收、涉及文件全部下沉到 `docs/team/A—F`。**每位成员只需读主文档第〇节 + 自己那份个人文档。**

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

## 四、三组分工总表（详细任务卡见个人文档）

> 每张任务卡的 **内容 / 前置 / 步骤 / 细节红线 / 验收 / 涉及文件 / 分支 / 估时** 全部写在 `docs/team/` 下对应的个人文档里；本节只给全局视图与跨人依赖。
> **每人只需读自己的那份 + 主文档第〇节。**

### 4.1 个人文档索引

| 成员 | 组 | 个人文档 | 功能分支（属主） | 核心命题 |
|---|---|---|---|---|
| A | 1 | [A-讨论状态机与共识](team/A-讨论状态机与共识.md) | `feat/p1-agent-consensus`、`feat/p1-conversation-memory` | 拆三处人工门、六人确认→agent 共识、对话记忆表、圆桌后端 |
| B | 1 | [B-设计规格与基线](team/B-设计规格与基线.md) | `feat/p1-design-spec`、`feat/p1-frontend-discussion` | 契约六块补全、基线对象（hash/父链）、阶段一前端、模型调用埋点、C2 案例 |
| C | 2 | [C-计划编辑与契约](team/C-计划编辑与契约.md) | `feat/p2-plan-editing`、`feat/p2-contract-schema` | 契约 JSON Schema、计划编辑回写、CAS、图节点语义、增量分解 |
| D | 2 | [D-真实执行与案例](team/D-真实执行与案例.md) | `feat/p2-real-execution`、`feat/p2-cases` | 真实 runner（不伪提交）、网页产物与预览、写入范围、分档路由、L1→C3 案例 |
| E | 3 | [E-观测与验收](team/E-观测与验收.md) | `feat/p3-observation`、`feat/p3-acceptance` | 观测 Schema（硬门禁）、埋点、观测页真实化、三类验收报告、签名证据链 |
| F | 3 | [F-圆桌与统一框架](team/F-圆桌与统一框架.md) | `feat/p3-roundtable`、`feat/p3-unified-ui` | 圆桌前端、CAS 冲突 UI、预览按钮、样式规范、性能可达性基准 |

### 4.2 任务卡总表（33 张）

| 卡 | 内容 | 估时 | 周 | 对应缺口 |
|---|---|---|---|---|
| A-1 | 拆除三处 `WAITING_HUMAN`（`controller.py:170/195/208`） | 12h | 1 | G1 |
| A-2 | `publish()` 六人→agent 共识，删 `MEMBERS` | 6h | 1 | G2 |
| A-3 | 对话记忆表 + 阶段边界消费 | 16h | 2 | G3 |
| A-4 | 简化 / 极简模式 | 8h | 4 | — |
| A-5 | 圆桌后端四指令 | 10h | 3 | G12 |
| A-6 | 分支治理：公示与删除 8 个已并入分支 | 2h | 1 | G14 |
| B-1 | 设计规格契约六块（operations/errors/field_bounds/envelope/data_model/nonfunctional） | 18h | 1–3 | G4 |
| B-2 | 基线对象 revision/parent/sha256 + 共享哈希函数 | 8h | 2 | G5 |
| B-3 | 阶段一前端深化（插话列表 / 实时进度 / 立场卡） | 14h | 2 | G12 |
| B-4 | 模型调用埋点（按 E-1 Schema） | 8h | 3 | G11 |
| B-5 | 第一个 C2 案例（真实流程生成） | 6h | 3 | G10 |
| C-3 | 契约 JSON Schema + 一致性校验（赶 0-3 冻结会） | 10h | 1 | G8 |
| C-1 | 节点编辑回写 + 布局持久化 | 16h | 2 | G6 |
| C-2 | 计划 CAS + input_hash 强校验 | 6h | 2 | G6 |
| C-4 | 图节点语义 decision/checkpoint/join + pass/fail/loop | 12h | 3 | G9 |
| C-5 | 增量分解 | 8h | 4 | — |
| C-6 | 分支治理：评审 `b01-spec-planner`、`feature/b03-blackboard` | 2h | 1 | G14 |
| D-1 | B04 真实 runner（失败不伪提交） | 14h | 1 | G7 |
| D-2 | 网页产物 + `/preview/<run_id>/` | 8h | 2 | G7 |
| D-3 | 写入范围校验（路径段匹配） | 6h | 2 | — |
| D-4 | 模型分档路由 | 6h | 3 | — |
| D-5 | 案例重建 L1→L2→C3 | 10h | 3 | G10 |
| D-6 | 分支治理：评审 `b04-agent-integration-task-delivery` | 2h | 1 | G14 |
| E-1 | 观测 Schema 定稿并冻结（**硬门禁**） | 10h | 1 | G11 |
| E-2 | 观测表 + 模型调用表 + 三条 GET 路由 | 14h | 2 | G11 |
| E-3 | 观测页真实化（时间轴 / 工件表 / 三级回溯） | 14h | 3 | G12 |
| E-4 | 三类验收报告 | 6h | 3 | G13 |
| E-5 | B06 签名证据接入执行链 | 8h | 3 | G13 |
| E-6 | 复核 C 的 `b03-blackboard` 评审结论 | 1h | 1 | G14 |
| E-7 | 案例成熟度台账（持续） | 2h | 持续 | — |
| F-1 | 圆桌前端（对接 A-5） | 14h | 3 | G12 |
| F-2 | CAS 冲突弹窗（对接 C-2） | 6h | 2 | — |
| F-3 | `UI_GUIDELINES.md` + 清理 40 处硬编码色 | 10h | 4 | — |
| F-4 | 性能可达性基准（`ui_perf.mjs`） | 10h | 2 | — |
| F-5 | 交付页预览按钮（对接 D-2） | 2h | 2 | — |
| F-6 | 分支治理：评审 `feat/b05-frontend-viz`、`feat/b02-discussion-controller` | 2h | 1 | G14 |

### 4.3 跨人依赖（谁等谁）

```text
第 1 周  E-1 Schema ──┬─→ B-4 埋点（第 3 周）
                     ├─→ E-2 埋点（第 2 周）
                     └─→ E-3 观测页（第 3 周）
         A-1 → A-2 ──┬─→ B-1 契约（confirmed_by 格式）
                     └─→ A-4 模式
         C-3 Schema ──→ C-1 编辑接口的请求体定义
         D-1 runner ──┬─→ D-2 预览 ──→ F-5 按钮
                      ├─→ E-5 证据链
                      └─→ D-5 C3 案例 ←── B-5 C2 规格
第 2 周  A-3 记忆表 ──┬─→ A-5 圆桌后端 ──→ F-1 圆桌前端
                     └─→ B-3 插话列表
         B-2 哈希函数 ──→ C-2 input_hash
         C-2 409 形状 ──→ F-2 弹窗
第 3 周  E-2 路由 ──→ E-3；F-4 基准 ──→ E-4 报告
第 4 周  所有前端 PR 合入 ──→ F-3 清理硬编码
```

**同一文件多人改的"对撞点"**（必须按个人文档里的约定划行/排序）：

| 文件 | 谁 | 约定 |
|---|---|---|
| `b02-workflow-agent/backend/app.py` 路由段 | A（`/messages` `/roundtable`）、C（`PATCH`）、D（`/preview`）、E（三条观测 GET） | 按前缀分段；每次合并前在群里说；一次只合一个人的路由 PR |
| `b02-workflow-agent/backend/controller.py` | A（本体）、E（只通过 `on_event` 钩子，不改本体） | E 不碰 |
| `b03/b03_implementation/task_state.py` | 本体不改；A 加 `conversation.py`、B 加 `baseline_history.py`、E 加 `observation.py` | 全部新文件并列 |
| `frontend/src/components/RoundTableView.tsx` | B（数据接入）、F（交互按钮） | 先划行再动手 |
| `frontend/src/components/TaskGraph.tsx` | C（布局/连线）、F（仅弹窗调用一行） | F 的改动让 C review |
| `frontend/src/components/TaskNode.tsx` | C（节点类型渲染）、F（F-3 清内联色） | 约时间窗 |
| `frontend/src/App.tsx` | 所有人 | 只改自己的页面段；顶栏与路由定义冻结 |

### 4.4 共同任务（0-x，计入各组工作量）

| # | 任务 | 责任人 | 估时 | 完成标志 |
|---|---|---|---|---|
| 0-1 | 开工仪式执行（0.1 每次开工 + 0.2 首周深读） | 全体 | 2h/人 | 各自 PR 描述附"已读清单" |
| 0-2 | 分支治理（第二节 2.2；评审任务见各人 A-6/C-6/D-6/E-6/F-6） | A/C/D/E/F | 约 2h/人 | 旧分支清理完毕并记录 |
| 0-3 | 契约冻结会（一次 2h）：**E 主持**；E-1 观测 Schema × C-3 计划 Schema × B-2 基线字段 × D-1 evidence 结构 四者对齐 | E 主持，B/C/D 到场，A/F 列席 | 2h | Schema 冻结 v1，纪要写入 `TASK_ORCHESTRATION.md` |
| 0-4 | 每周发布：周五轮值组把 `integration` 合并到 `main` 并打 tag | 轮值组 | 1h/周 | main 绿 + tag |

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
| 2026-11-27 | v2.1 细化：拆出 6 份个人文档 `docs/team/A—F`。每份含：本人分支表与联调对象、代码地图（文件→现状行号→要动的部分）、任务卡（步骤到行号级、测试用例名、红线、验收数字）、每周节奏、验收命令速查。总纲第四节改为索引 + 33 张卡总表 + 跨人依赖图 + **同文件对撞点表**（`app.py` 路由段四人同改等 7 处）。补齐 v2 遗漏：C-3 应先于 C-1（冻结会需要）、0-3 由 E 主持、各块测试基线数字（B01 44 / B02 113 / B03 46 / B04 664+1 / B06 75 / 前端 20）。 |
