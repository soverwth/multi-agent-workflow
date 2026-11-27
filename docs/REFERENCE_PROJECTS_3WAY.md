# 参考项目调研：其他三组的 SE Workflow 项目（实跑对比）

> 调研日期：2026-11-27。三个项目均**实际启动、实际跑通主链路、实际执行其自带测试**，本文所有数字来自运行输出，不是从 README 抄的。
> 调研目录：`D:\School\SE wf\Other\{SE-Development-Process-Agent, SE-lib, SE-TeamPrjoect}`。
> 结论只用于课程内的设计借鉴，不复制代码。SE-lib 的更早一次调研见 `REFERENCE_PROJECTS.md`。

---

## 一、三个项目是什么

| 项目 | 组 | 定位 | 技术栈 | 规模 |
|---|---|---|---|---|
| **SE-DPA**（SE-Development-Process-Agent） | 第五组 | 「项目主理人」驱动的开发流程工作台：需求赛马 → 评审整合 → 任务分解 → 排期 → 开发 → 交付，附 SQLite 领域记忆 | Python 3.10+ 纯标准库（`http.server` + `sqlite3`），React/Vite 工作台 | 157 文件；`se_agent/` 约 35 个 py 文件；191 个单测 |
| **SE-lib**（FlowStudio） | — | 把设计规格转成可审核的任务计划：PM Agent 生成候选 → 确定性编排 → React Flow 画布 → 可编辑计划版本 | FastAPI + Pydantic + SQLAlchemy + Alembic；React 19 + Vite + @xyflow | 247 文件；后端 205 通过 1 跳过；前端 17 域测试 + 1 浏览器 E2E + 1 性能基准 |
| **SE-TeamPrjoect** | — | 三个子系统拼接：HAMA 需求工程（7 阶段 + 人工门）→ 软件设计（PRD→Design Spec→PM）→ Twin-Graph 编排器（Git worktree 沙箱 + 条件分支 + 检查点） | Node 24 + `node:sqlite` + TypeScript；Electron/Web 双宿主；React 19 + @xyflow | 143 文件；3 验证门 + 2 HAMA + 12 软件设计测试 |

三个项目对应课程作业的覆盖面：

| 作业 | SE-DPA | SE-lib | SE-TeamPrjoect | 我们 |
|---|---|---|---|---|
| 作业 1：想法 → 规格 | ✅ 赛马 + 评审整合（但**有人工确认门**） | ❌ 从设计规格开始 | ✅ HAMA 7 阶段（**三道人工门**） | ✅ A—H 八阶段、agent 互相确认、无审批门 |
| 设计规格 → 任务计划 | ✅ QLM 确定性分解器 | ✅ PM Agent + 确定性编排（**最规范**） | ✅ PM Agent + Twin-Graph（**图最丰富**） | ✅ B01 动态计划 |
| 真实执行 | ✅ **Git worktree + 真实模型写代码**（唯一） | ❌ 无 | ✅ worktree + shell 门禁（但本次为离线合成） | ⚠️ mock（`simulated=True`） |
| 可观测 / 回溯 | ⚠️ 运行事件 + 经验记录 | ❌ 无 | ✅ SSE 事件流 + FTS5 证据检索 + 审计 | ✅ 事件回放 + 断点恢复 + 八页面工作台 |
| 人工介入 | ⚠️ 默认不弹确认，**可开启确认点** | — | ⚠️ **三道人工门**（澄清 / 审批 / 确认） | ✅ 设计上零审批门 |

---

## 二、逐个项目的实跑记录

### 2.1 SE-DPA（第五组）

**实际做了什么**

| 动作 | 结果 |
|---|---|
| `python -m unittest discover -s tests` | **191 tests OK**，77 秒 |
| `python -m se_agent.workbench --port 18008` | 启动成功，首页 237 KB 单页 HTML |
| `POST /workspace/steward`（一句需求「校园失物招领系统…」） | 自动跑完：2 条讨论路线 → A/B 组独立出案 → 独立评审 → 主理整合 → 规格确认 → 任务分解 → 排期 → 5 任务开发 → 交付。全流程 **约 3 秒**（离线模拟） |
| 读项目详情 | 计划版本 `PLAN-01 v1→v2`，运行 `RUN-01` 绑定 v2，5 任务全部 `done`，排期含关键路径 `critical=true` |

**值得吸收的部分**

1. **「主理人」(steward) 的对话式驱动**。用户只需说一句话，主理人自己决定分几组、每组不同提示词、并发出案；运行中可以用自然语言说「暂停」「继续」「任务到哪一步了」「修改……」。它的 `steward_pipeline.py`（53 KB）是单文件状态机，事件流按 stage 分组（groups / race / evaluate / merge / decisions / confirm / plan / start / develop / delivery）。这正是老师说的「用户随时与系统交互」在执行侧的落地形态。
2. **高低配模型路由**（`model_router.py`）：规划/复核/集成用高能力模型，逐文件生成用低成本模型；对 DeepSeek 系模型关闭思考模式、大文件额度 8192→32768。我们已有 DeepSeek 配置，但没有按任务类型分档。
3. **确定性分解器 + 排期器**（`planner.py` / `schedule.py`）：任务分解是确定性基线（可重复），估时按分钟、关键路径按纯依赖图算，排期考虑并发上限和**写入路径冲突**（同文件/包含目录串行）。
4. **真实代码执行的工程细节**：`worktree.py` 每次尝试一个 worktree + 分支，纳入已批准的上游提交后再生成；服务端校验提交可达性、祖先关系、写入范围；**产物不伪提交**——模型没返回正文 / 输出截断 / Git 没新提交时不登记产物。
5. **版本与修订号分离**：内容 `version`（不可覆盖）与 `revision`（并发控制整数）分开，写操作带 `Idempotency-Key` + `expected_revision`。
6. **契约文档写法**：`接口契约-v2.md` 用「记录 → 关键字段 → 规则」三段式，把状态机（waiting/ready/running/review/failed/input_required/blocked/done）的进入条件和允许推进写成表，并**明确 v2 尚未实现、以文档和样例为准**。

**不建议学的部分**

- 默认有可开启的「确认点」（规格 / 开工 / 交付），与我们的「无人工介入」相反；它的 `input_required` 状态允许任务停下来等用户补输入。
- 离线模式下综合方案里出现「DEC-01 · 主理决定 · 多组对该需求提出了不同做法。请核对依据……」这种**把模板文字当成决策**的内容，说明模拟数据质量需要人工核对。
- 六个分支各写一套 `*_preview.py`（intake/synthesis/planner/workbench），代码重复度高。

### 2.2 SE-lib（FlowStudio）

**实际做了什么**

| 动作 | 结果 |
|---|---|
| `pytest tests tests_pm`（venv） | **205 passed, 1 skipped**（REAL 守卫测试按设计跳过） |
| `npm run build`（需绕开 `%TEMP%` 下 esbuild 临时文件被拒的问题，改 `TMP` 后成功） | 67 modules，1.84 s |
| `node --test tests/domain.test.mjs` | 17/17 |
| `node --test tests/browser.test.mjs`（自起 Chromium + CDP，不用 playwright） | 1/1：空项目→填规格→任务→依赖→保存计划 v2→导出→PNG 快照 |
| `node --test tests/performance.test.mjs` | **Q04：100 任务/200 边，可交互 197 ms（目标 2000），拖动 89 fps（目标 30）**；Q08：对比度（最小 4.95）与键盘可达性（12 个焦点）通过 |
| 后端 API 实跑：保存规格版本 → 校验 → 编排 → TEST 模式规划 → 保存计划 v1 → 改计划 v2 → 重复 expected_revision=1 | 校验 `valid=true`，8 条需求全覆盖；编排出 3 个执行阶段、5 个并行批次、14 条边；**输入 hash `66912432…60691` 与交付报告里记录的完全一致**（确定性规范化）；v2 保存成功；旧 revision 再提交返回 **409 `REVISION_CONFLICT`** |

**值得吸收的部分**

1. **契约单一来源**（已在 `REFERENCE_PROJECTS.md` 3.1 记录，本次实跑再次确认）：Pydantic 模型 → JSON Schema / OpenAPI / 前端类型。校验错误返回结构化 `issues[]` 和 `request_id`，一眼能定位到 `body/expected_revision`。
2. **`expected_revision` 的 CAS 并发控制 + `input_hash`**。每次保存都带规范化内容的 SHA-256，验收报告引用 hash 而不是文件路径。这解决了我们 B02「计划只做最小校验」和 STAGE2_STATUS 遗留项 5 的同类问题。
3. **PlanningRun 的「有界失败」设计**：`MODEL_BUDGET`、`NEEDS_INPUT` 是正常状态而不是异常；REAL 验收报告明确记录「一次重复 baseline 在 2 次调用后返回 MODEL_BUDGET，系统有界失败，没有自动切换 TEST」——**TEST 与 REAL 严格分离、各自出报告**。
4. **三类验收证据分离**：`P0_CLOSURE_REPORT`（技术闭环）、`REAL_ACCEPTANCE_REPORT`（真实模型，含 usage 与耗时）、`QUALITY_ACCEPTANCE_REPORT`（性能 / 恢复 / 安全）。交付报告有「已知风险」章节。
5. **前端 E2E 不依赖 playwright**：直接 spawn Chromium `--headless=new --remote-debugging-port=0`，用原生 `WebSocket` 连 CDP 执行点击、填表、下载 PNG。这对我们 B05 的 `ui_smoke.mjs` 是零成本的参考。
6. **性能基准写进测试**：100 节点 / 200 边首屏与拖动帧率是断言项，不是口头承诺。

**不建议学的部分**

- 范围只到「计划」，没有执行、审批、SSE（它自己在 DELIVERY_REPORT 里承认）。
- 两套规划引擎（`flowstudio_pm` + `flowstudio_orchestration`）+ `tech/flowstudio_contracts` 三处定义，新人理解成本高。

### 2.3 SE-TeamPrjoect

**实际做了什么**

| 动作 | 结果 |
|---|---|
| `npm run typecheck` | 通过 |
| `npm run verify:gates` | 3/3：`fullstack-smoke`（Bearer + SSE + PRD→Trial→Version→Run + 静态包）、`orchestrator-and-sandbox`（Worktree + HumanGate + GhostNode + Rework + Constitution + Cleanup）、`planner-and-validator`（Modules + Customization + DDD Guard + Export + Capsule） |
| `node --test requirements-engineering/verify/hama.test.ts` | 2/2 |
| `node --test software-design/verify/*.test.ts` | 12/12 |
| `npm run start:web`（端口 14190，数据目录指向我们 work/） | 启动成功，token 化 URL |
| HAMA demo 运行（5 角色、2 轮讨论） | 7 阶段全部走通；**3 道人工门**：`clarification`（intake r1）→ `approval`（proposal r1）→ `confirmation`（prd r1）；产出 74 个工件，其中 **53 次 `model_call` 工件全部留痕**（含 hash）；最终 `succeeded`，发布基线 `baseline-run-38e95fdb`（SHA-256 `cdc1aebb…`） |
| `POST /api/workflows/import-requirements` 用 demo 基线交接 | **409「演示基线只用于演练」**——正确地拒绝了模拟数据流入真实链路 |
| 用自带 Design Spec 预置（课程选课系统）导入 → 试运行 → 锁版 v1.0 → 启动运行 | 21 节点 / 22 边的 Twin-Graph，5 条需求全覆盖，DDD 术语漂移检查通过；试运行 `trial_passed`；锁版后 workflow `locked`；运行 `succeeded`：16 节点成功、2 条件分支跳过、4 个 Git 检查点（`orchestrator/run-…/p3.ckpt-…`），18 次尝试，0 干预 |

**值得吸收的部分**

1. **Twin-Graph 的节点类型**比我们的「任务 + 依赖边」丰富得多：`phase_container` / `task` / `decision`（条件路由）/ `join`（汇合屏障）/ `checkpoint`（物理 Git 检查点）/ `gate_shell`（确定性门禁）/ `selfcheck` / `qa_audit` / `restore`（有界回退）/ `done`。边有 `dep` / `pass` / `fail` / `loop` 四种语义。我们的九态状态机是**任务级**的，没有表达「条件分支」「有界返工环」的能力。
2. **每次模型调用都是工件**（`model_call` 带 `revision` 与 `hash`），可全文检索（FTS5）。我们阶段三要定义的「观测数据 schema」可以直接以此为参照：**工件 = 版本 + 哈希 + 来源运行/尝试**。
3. **`ApprovedRequirementsBaseline` 作为交接契约**：`schemaVersion / id / projectId / revision / parentId / mode / approvedPrd / approval / confirmation / prd / sha256`。它把「PRD + 两道审批 + 版本 + 校验摘要」打包成一个不可变对象，下游按 `baselineId` 签收。我们的 `phase1_source`（run_id / r1_version / generation_source / confirmed_by）是同类东西，但**没有 hash、没有 parent 链**。
4. **「演示」与「真实」的边界是硬的**：demo 基线不能导入下游；`mode: 'live'` 必须配置 provider，否则 400。这与我们「模拟与真实严格分离」的规则三一致，但他们的实现更彻底。
5. **审计与「认知再水化」**：`recentAudit` 按分类记录；`rehydrationCapsule` 把一次运行压缩成「目标 / 已锁定决策 / 自主增量 / 下一个决策提示」，作为下次 agent 的上下文。这是「不把完整历史塞进提示词」的一种工程化解法，与我们 N1 的精神相同。
6. **Design Spec 用 `## Modules` Markdown 分节**（`spec-parser.ts`），模块声明文件范围（`file scope`），PM Agent 据此分任务并检查写入路径重叠。比我们的 JSON/Markdown 规格更贴近「真实设计文档」的形态。

**不建议学的部分**

- 三道人工门是产品选择，与我们「无人工介入」相反（但它的「附条件批准 → 第二次等待」机制说明他们把人工门做成了可审计的状态，而不是弹窗）。
- 概念堆叠过重：SkillsBank / Sleep-Time Dreaming / Ebbinghaus 记忆衰减 / Constitution / MCP Pool / GhostNode / USD 遥测……课程作业范围内大部分是「有接口、无实际效果」。
- 软件设计子系统把「评审修订 / 签收账本 / 幂等交接」做了 6 步、每步一个 `stepN-verification.md` + `evidence.json`，文档与证据量远超代码量，可读性一般。

---

## 三、与我们项目的对比

| 维度 | 我们 | SE-DPA | SE-lib | SE-TeamPrjoect |
|---|---|---|---|---|
| 讨论 → 规格 | ✅ A—H、四角色、agent 互相确认、**无审批门** | ⚠️ 赛马 + 评审，可开确认点 | ❌ | ⚠️ 7 阶段，三道人工门 |
| 用户非阻塞插话 | 设计 ✅ / 实现 ⚠️（阶段边界消费，无对话 UI） | ✅ 对话驱动主理人 | ❌ | ⚠️ 通过人工门 |
| 规格细化 | ⚠️ `contract` 字段空 | ✅ 规格 + 决策 + 未决项 | ✅ **Pydantic 单一来源** | ✅ PRD→Design Spec 六步 |
| 任务分解 | ✅ 动态计划（24 / 11 任务） | ✅ 确定性 + 排期 | ✅ PM Agent + 假设确认 | ✅ Twin-Graph + 条件分支 |
| 并发控制 | ⚠️ 计划版本冲突保护，无 CAS | ✅ `revision` + Idempotency-Key | ✅ `expected_revision` + `input_hash` | ✅ 版本冻结 + 运行绑定版本 |
| 真实执行 | ❌ mock | ✅ **worktree + 真实模型** | ❌ | ✅ worktree + shell 门禁（离线合成） |
| 事件 / 证据 | ✅ 12 种事件、回放一致、九项必查 | ✅ 事件 + 尝试 + 产物版本 | ⚠️ 仅规划运行 | ✅ **每次模型调用留痕 + FTS5** |
| 可视化 | ✅ 八页面、DAG/甘特/时间线/事件流 | ✅ 单页工作台 + 甘特 | ✅ React Flow + 布局版本 + PNG 导出 | ✅ Twin-Graph 画布 + 中英双语 |
| 前端 E2E | ⚠️ `ui_smoke.mjs` 需手起服务 | ❌ | ✅ **自起 Chromium/CDP，CI 可跑** | ✅ 3 验证门（HTTP 级） |
| 性能基准 | ❌ | ❌ | ✅ 100/200 图 197 ms / 89 fps | ❌ |
| 交付文档 | ⚠️ 12 份，偏技术契约 | ✅ 分模块文档 + 对接文档 | ✅ **60+ 份按角色分层 + 三类验收报告** | ⚠️ 每步 verification + evidence |

**一句话结论**

- **我们在「作业 1 的无审批多智能体讨论」和「任务级证据验收（九项必查、回放一致）」上是最完整的**，这是不能丢的差异化。
- **工程规范要学 SE-lib**（契约单一来源、CAS + hash、三类验收报告、自带浏览器的 E2E）。
- **执行侧要学 SE-DPA**（worktree + 产物不伪提交 + 模型分档路由）。
- **图表达与交接对象要学 SE-TeamPrjoect**（Twin-Graph 节点类型、Baseline 带 hash 的交接契约、模型调用即工件）。

---

## 四、吸收清单（按优先级）

| # | 吸收项 | 来源 | 落到我们的哪里 | 估时 |
|---|---|---|---|---|
| 1 | **基线交接对象带 hash 与父链**：`phase1_source` 扩展为 `{baseline_id, project_id, revision, parent_id, r1_version, sha256, confirmed_by}` | TeamPrjoect `ApprovedRequirementsBaseline` | `phase_bridge.py`、`TASK_ORCHESTRATION.md` §2.1 | 4h |
| 2 | **计划版本 CAS + `input_hash`**：保存计划必须带 `expected_revision` 与规范化 hash；冲突 409 | SE-lib | B02 `register_plan`、`task_api.py`；同时关掉 STAGE2_STATUS 遗留项 5 | 6h |
| 3 | **契约单一来源**：`TASK_ORCHESTRATION.md` 字段抽成 JSON Schema，代码常量与 Schema 一致性校验，前端类型生成 | SE-lib `flowstudio_contracts` | `workflow_runtime/verify_contracts.py` 扩展、`frontend/src/types` | 8—12h |
| 4 | **每次模型调用即工件**：`model_call{run, attempt, node, revision, hash, usage, latency}` 进观测体系 | TeamPrjoect | 阶段三观测 schema；B02 `llm.py` 返回处 | 6h |
| 5 | **三类验收报告分离**：`P0_CLOSURE / REAL_ACCEPTANCE / QUALITY_ATTR`，REAL 单独跑、不默认触发 | SE-lib `docs/testing/` | `docs/` 新增 3 份；复用 11-26 的真实模型运行 | 3h |
| 6 | **前端 E2E 自起浏览器 + 性能基准断言**（CDP，不引 playwright） | SE-lib `tests/browser.test.mjs`、`performance.test.mjs` | `frontend/tests/ui_smoke.mjs` 改造 | 6h |
| 7 | **真实执行的最小工程闭环**：worktree / 任务分支 / 产物提交校验 / 失败不伪提交 | SE-DPA `worktree.py`、`worker.py` | B04 `gateway.py` 真实 runner（对应 PROJECT_WORKFLOW 3.3 的 a） | 12h |
| 8 | **模型分档路由**：规划/复核用高能力，逐文件生成用低成本 | SE-DPA `model_router.py` | B02 `llm.py`、B04 runner | 4h |
| 9 | **Twin-Graph 节点语义**：至少补 `decision`（条件分支）与 `checkpoint`（阶段检查点）两类节点与 `pass/fail` 边语义 | TeamPrjoect | B01 动态计划输出、B05 画布、九态状态机之外加「节点类型」字段 | 8h |
| 10 | **排期考虑写入路径冲突**：同文件 / 包含目录的任务串行 | SE-DPA `schedule.py`、TeamPrjoect file scope | B02 调度、B05 甘特 | 4h |

**不吸收**：任何形式的人工审批门（与 N6 冲突）；SkillsBank / Dreaming / Ebbinghaus 等概念堆叠；FastAPI/SQLAlchemy 技术栈迁移。

---

## 五、本次调研对项目文档的修改

见 `PROJECT_GOALS_AND_PROCESS.md` 的修订记录章节。核心变化：

1. 阶段一→阶段二的衔接对象从「设计规格 + 来源信息」升级为**带 hash 与父链的需求/设计基线**（吸收 TeamPrjoect）。
2. 计划编辑与版本控制补充 **CAS + input_hash**（吸收 SE-lib）。
3. 观测数据 schema 把「模型调用」列为一等主体并要求 **hash + usage + latency**（吸收 TeamPrjoect）。
4. 验收口径补充**三类证据分离**与**前端 E2E / 性能基准**（吸收 SE-lib）。
5. 执行侧补充**真实执行的最小工程闭环**要求：任务分支、提交校验、失败不伪提交、模型分档（吸收 SE-DPA）。
6. 任务图语义补充 `decision` / `checkpoint` 节点与 `pass/fail/loop` 边（吸收 TeamPrjoect）。
