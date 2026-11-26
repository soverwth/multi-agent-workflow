# 参考项目调研：SE-lib（FlowStudio）

> 本文是**代码级核实结论**。初版曾误判其定位，已按用户澄清修正。

---

## 一、基本信息

| 项目 | 值 |
|---|---|
| 仓库 | https://github.com/cocoliler/SE-lib |
| 本地检出 | `D:\School\SE-lib`（HEAD `699d136`，2026-11-19，与远端 main 一致） |
| 实际产品名 | **FlowStudio** |
| 自述定位 | 「通用可定制的智能软件工程工作流平台」 |
| 后端 | FastAPI + Pydantic + SQLAlchemy + Alembic |
| 前端 | React + Vite + React Flow |
| 规模 | 后端 `app/` 30 个 py 文件，前端 `src/` 12 个 tsx/ts 文件 |

---

## 二、它在课程作业中的实际位置

### 2.1 它自己声明的作业归属

全仓库搜索「课堂作业」，共 7 处命中，**全部指向作业 2**，无一处提及作业 1：

| 文件 | 原文 |
|---|---|
| `delivery/DELIVERY_REPORT.md:11` | 本交付完成**课堂作业 2** 的 P0 闭环 |
| `docs/product/MVP_SCOPE.md:2` | 当前前端与**课堂作业 2** 目标 |
| `docs/product/MVP_SCOPE.md:6` | **课堂作业 2 原型** |
| `docs/product/PRODUCT_POSITIONING.md:17` | **课堂作业 2** 接受已有设计规格，只落地至编排可视化；**不要求重新自动编写 PRD** |
| `docs/BASELINE.md:5` | **课堂作业 2** 的完整目标是 Design Spec → PM Agent → Task Decomposition → Orchestrator → Workflow Visualization |
| `docs/DESIGN_SUMMARY.md:3` | **课堂作业 2** 聚焦从设计规格和 PM 生成的候选任务，到可校验、可修改、可冻结的开发计划 |
| `tech/docs/system-architecture.md:101` | 四段接口（**课堂作业 2** 的流程即按此切分） |

### 2.2 它没有多智能体讨论能力

搜索全仓库代码（`.py` / `.tsx` / `.ts`，排除 node_modules / .venv / generated）：

- `discussion` / `debate` / `consensus` / `blackboard` / `objection` / `质疑` / `观点` / `异议` / `主持人` —— **零命中**
- `proposal` 的 16 处命中全部是 `TaskProposal`（PM Agent 输出给编排器的**任务提案**），不是讨论阶段的 Proposal 草案

`PRODUCT_POSITIONING.md` 明确写：

> 不做聊天机器人。

### 2.3 关于「它是作业 1 的参照」

老师推荐 SE-lib 作为**作业 1 的参照**。上面 2.1、2.2 的代码事实是：它标注的作业归属是作业 2、也没有多智能体讨论的实现。

这两件事并不矛盾，因为**参照的是工程规范，不是功能**：

- 它把「设计规格」这个核心产物用 Pydantic 定义成**唯一事实源**，并生成 JSON Schema / OpenAPI / 前端类型 —— 这正是作业 1 要产出「设计规格」时最该学的做法
- 它的 `design-spec.schema.json` 可以直接作为我们补全 `contract` 字段的蓝本
- 它从设计规格**开始做**，它的起点恰好是我们的**终点**，所以它的规格模型对我们尤其有价值

**结论**：功能上它不覆盖作业 1（我们在作业 1 上确实更完整），但**工程规范上它是作业 1 输出物的格式标杆**。

---

## 三、具体参照什么

用户已明确：**参照它的工程规范，功能用我们自己的。**

按这个定位，SE-lib 的价值不在功能覆盖，而在**工程做法**。以下按价值排序。

### 3.1 高价值：契约单一来源（最值得学）

**它的做法**

`tech/README.md` 写得很清楚：

> 1. `flowstudio_contracts/` 是**唯一事实源**：严格 Pydantic 模型，定义设计规格、任务提案、校验报告、规划运行、计划版本、布局与接口 DTO。
> 2. `artifacts/schema/` 是可通用的 JSON Schema，PM 输出、编排校验、落库前检查都按它判定；`artifacts/openapi.json` 是接口契约，后端按它实现路由。
> 3. 前端**不手写类型**：`generated/contracts.ts` 由同一模型生成。
> 4. 改契约的唯一正确方式：改模型 → 重新生成 → 一起提交；手改会被 `--check` 覆盖。

**我们的问题**

我们目前是**手写 dict + 手写文档**，已经因字段漂移出过真实 bug：

| 历史 bug | 原因 |
|---|---|
| B04 只校验「非空字符串」，B06 要求 64 位十六进制 | 两边 `SHA256_PATTERN` 不一致，执行通过但验收必然拒绝 |
| 真实模型返回 `P0/P1`，B01 只接受 `must/should/any` | 契约没有强制优先级取值域，`phase_bridge` 只做 `.lower()` |

**建议采用的做法**（不必引入 Pydantic，但要有单一来源）

1. 把 `docs/TASK_ORCHESTRATION.md` 的字段定义抽成**机器可读的 JSON Schema**
2. 写一个 `verify_contracts.py` 的扩展：**校验 Python 代码里的常量与 Schema 一致**
3. 前端类型从 Schema 生成，而不是手写在 `types/task.ts`

**估时**：约 8—12 小时。收益是消除一整类跨块字段漂移 bug。

### 3.2 高价值：Design Spec 的结构参考

它的规格 Schema 在 `docs/contracts/design-spec.schema.json`（3.5 KB）。

**对我们的直接用处**

我们的 `phase_bridge.py` 从 R1 生成设计规格时，`contract` 字段是空的：

```python
"contract": {
    "contract_version": ...,
    "operations": [],        # 空
    "errors": {},            # 空
    "field_bounds": {},      # 空
    "response_envelope": {}, # 空
}
```

而作业 1 的终点是「输出需求规格/设计规格」，作业 2 要消费它。**它的 Schema 可以作为我们补全 `contract` 的字段蓝本**。

**注意**：不是照抄，而是参考它的字段组织方式（operations 的结构、错误码的表达、字段边界的描述粒度）。

### 3.3 中价值：交付文档的组织方式

它有 60+ 份文档，按**角色可读**分层：

```
product/       PRD、SRS、MVP_SCOPE、REQUIREMENTS_TRACEABILITY
architecture/  SYSTEM_ARCHITECTURE、DATABASE_DESIGN、API_SPECIFICATION、
               ORCHESTRATION_ENGINE、PM_AGENT_DESIGN、TASK_DECOMPOSITION
design/        DESIGN_SYSTEM、UI_UX_DESIGN、WORKFLOW_EDITOR、EXECUTION_VISUALIZATION
development/   GIT_COLLABORATION、LOCAL_DEPLOYMENT、ROADMAP、TASK_BREAKDOWN
testing/       TEST_STRATEGY、ACCEPTANCE_TESTS、QUALITY_ATTRIBUTES、
               P0_CLOSURE_REPORT、REAL_ACCEPTANCE_REPORT
research/      REFERENCE_PROJECTS、DESIGN_BENCHMARK
contracts/     design-spec.schema.json、task-proposal.schema.json
```

以及 `delivery/`：

```
DELIVERY_REPORT.md   交付范围、复现命令、证据、剩余风险
MANIFEST.json        机器可读的输入清单
```

**值得学的一点**：**交付物要有「剩余风险」章节**。这比只报好消息诚实，也方便验收方判断边界。

我们目前 `docs/` 有 10 份，偏技术契约，缺产品与验收视角。

### 3.4 中价值：验收证据的组织

它的 `testing/` 下把产出分成**三类证据**，明确不混在一起：

| 文档 | 证明什么 |
|---|---|
| `P0_CLOSURE_REPORT.md` | 技术闭环跑通 |
| `REAL_ACCEPTANCE_REPORT.md` | 真实模型（DeepSeek）跑通 |
| `QUALITY_ACCEPTANCE_REPORT.md` | 质量属性（性能、恢复、安全）达标 |

并明确写「REAL 与 TEST 分开报告」。

**我们的对应现状**

| 类型 | 我们有什么 | 缺口 |
|---|---|---|
| 技术闭环 | `verify_contracts.py` 6/6、`run_all_checks.py` 15/15 | ✅ |
| 真实模型 | 已实测（RUN-8FFA023764 / TASK-RUN-0211492B），但**没有写成报告** | ⚠️ 需补 |
| 质量属性 | 无 | ❌ |

**建议**：把 11-26 的真实模型验证写成 `docs/REAL_ACCEPTANCE_REPORT.md`（约 2 小时）。

### 3.5 低价值 / 不建议

| 项 | 理由 |
|---|---|
| 整体技术栈迁移（改 FastAPI + SQLAlchemy） | 我们零第三方依赖是优势，迁移成本高、对课程作业无收益 |
| 直接复用代码 | 两边数据模型差异大，适配层负担超过重写 |
| 照搬它的 P2 规划 | 它的 P2（执行、监督、审批）大部分我们已实现，且方向不同 |

---

## 四、功能对比（客观陈述）

| 维度 | 我们的项目 | SE-lib |
|---|---|---|
| **作业 1（想法 → 需求规格）** | ✅ 完整（A—H 八阶段、黑板、六人确认、真实模型实测） | ❌ 无 |
| 需求规格 → 设计规格 | ⚠️ 有桥接，但 `contract` 为空 | ✅ Schema 完整（但它从设计规格**开始**，不做上游） |
| 作业 2（分解 + 编排） | ✅ 完整（B01 动态计划 + B02 九态） | ✅ 完整（PM Agent + Kahn） |
| 作业 2（执行） | ⚠️ mock（`simulated=True`） | ❌ 无 |
| 作业 2（执行控制） | ⚠️ 只有推进/跑完 | ❌ 无 |
| 作业 3（可观测） | ⚠️ 部分（事件流、回放、八页面工作台） | ❌ 无 |
| 契约管理 | ⚠️ 手写 dict + 文档 | ✅ Pydantic 单一来源 + 生成 |
| 交付文档 | ⚠️ 10 份，偏技术 | ✅ 60+，按角色分层 |
| 验收证据 | ⚠️ 技术闭环有，真实模型未成文 | ✅ 三类证据分离 |

**结论**：功能覆盖我们更全；**工程质量（契约、文档、证据）它更规范**。这正是「参照它的工程规范」的含义。

---

## 五、行动建议

按优先级：

| # | 行动 | 估时 | 归属 |
|---|---|---|---|
| 1 | 把 `TASK_ORCHESTRATION.md` 的字段抽成 JSON Schema，并加代码一致性校验 | 8—12h | 组 2 或组 3 |
| 2 | 用 SE-lib 的 Schema 作蓝本，补全 `phase_bridge` 的 `contract` 字段 | 12h | 组 1 |
| 3 | 把 11-26 的真实模型验证写成 `docs/REAL_ACCEPTANCE_REPORT.md` | 2h | 全员 |
| 4 | 文档按「产品 / 架构 / 设计 / 开发 / 测试 / 交付」重组 | 6h | 组 3 |

第 1 项和第 2 项直接服务于「作业 1 输出可被作业 2 消费的规格」这个串联目标，优先级最高。

---

## 六、致谢与边界

- 本调研仅用于课程内的设计借鉴，不做代码复制。
- 引用其文档时注明来源仓库。
- 「参照工程规范」的边界由用户确认：**可参考做法，功能实现独立完成**。
