# 参考项目调研：SE-lib（FlowStudio）

> 老师推荐参考「任务 1 做得很好」的其他组项目。
> 本文是**代码级核实结论**，不是转述。

---

## 一、基本信息

| 项目 | 值 |
|---|---|
| 仓库 | https://github.com/cocoliler/SE-lib |
| 本地检出 | `D:\School\SE-lib` |
| 实际产品名 | **FlowStudio** |
| 定位（自述） | 「通用可定制的智能软件工程工作流平台」 |
| 后端 | FastAPI + Pydantic + SQLAlchemy + Alembic |
| 前端 | React + Vite + React Flow |
| 规模 | 后端 `app/` 30 个 py 文件，前端 `src/` 12 个 tsx/ts 文件 |
| 当前阶段 | P0 闭环完成，P2（执行与监督）未做 |

---

## 二、⚠️ 关键结论：它不是作业 1 的参考

**老师推荐的是"任务 1 做得很好"，但 SE-lib 实际实现的是作业 2。**

### 证据 1：自述定位

`README.md` 第一句：

> FlowStudio 把**设计规格**转成可审核的任务计划。可以手动拆解任务，也可以让 PM Agent 生成候选，再用工作流画布查看依赖、执行顺序和并行批次。

—— 这是作业 2 的流程（设计规格 → 任务分解 → 编排），**起点是设计规格，不是用户想法**。

### 证据 2：完全没有任何多智能体讨论实现

对 `backend/` 全目录搜索以下关键词，**零命中**：

```
讨论 / discussion / debate / 质疑者 / devil's advocate
consensus / 共识 / 黑板 / blackboard / sign-off
```

### 证据 3：角色是"任务角色"，不是"讨论角色"

`docs/development/TEAM_ASSIGNMENTS.md` 里的六个角色是**开发分工**：

| 成员 | 职责 |
|---|---|
| A | 架构契约（T01 Schema） |
| B | 前端（T03 规格入口、T06 任务画布） |
| C | PM Agent（T04 Provider、Prompt） |
| D | 编排（T05 校验、Kahn、批次） |
| E | 后端数据（T02 项目/规格、T07 计划版本） |
| F | 测试交付（T08 验证、端到端） |

而作业 1 要求的角色是：主持人、产品经理、用户研究员、技术架构师、设计师、商业分析、**质疑者**、记录员。

**两者完全不同**。

### 证据 4：P2「执行与监督」明确未做

`docs/PROJECT_AUDIT.md`：

> 实际执行：当前产物是供团队审核和执行的任务计划；**自动执行、工件检查与监督属于后续范围**。

`docs/product/MVP_SCOPE.md`：

> P2 | 多 Agent 实际执行、成果管理、SSE、审批、重试、监督、Reviewer 和反馈修订... 不纳入作业 2 演示承诺

### 证据 5：自己的文档就写着"课堂作业 2"

`docs/product/MVP_SCOPE.md` 的章节标题：

> ## 课堂作业 2 原型

---

## 三、它的实际能力（可参考的部分）

### 3.1 已实现

| 能力 | 实现位置 | 对我们的价值 |
|---|---|---|
| Design Spec JSON Schema | `docs/contracts/design-spec.schema.json` | ★★★ 可直接参考的规格格式 |
| TaskProposal Schema | `docs/contracts/task-proposal.schema.json` | ★★★ 任务分解输出格式 |
| PM Agent（DeepSeek） | `backend/flowstudio_pm/` | ★★ 结构化输出 + 校验 + 修复 |
| 编排算法 | `backend/flowstudio_orchestration/` | ★★ Kahn 拓扑 + 阶段 + 并行批次 |
| 工作流画布 | `frontend/src/canvas.tsx` | ★★ React Flow 交互（搜索、拖拽、连线、PNG） |
| 契约生成 | Pydantic → JSON Schema → OpenAPI → TS 类型 | ★★★ 契约单一来源 |
| 计划版本与冲突处理 | `backend/app/persistence/` | ★ 乐观锁、幂等 |

### 3.2 未实现（与作业 2 完整要求的差距）

| 缺口 | 说明 |
|---|---|
| 真实执行 | 只产出计划，不执行 |
| 执行可视化 | 只有规划视图，无执行状态 |
| 执行控制 | 无 |
| 暂停 / 重试 / 审批 | 无 |

所以 **SE-lib 在作业 2 上也不是完整的**——它做完了「分解 + 编排 + 规划可视化」，但「执行可视化与控制」没有。

---

## 四、和我们项目的对比

| 维度 | 我们的项目 | SE-lib |
|---|---|---|
| **作业 1（讨论）** | ✅ 完整（A—H 八阶段、黑板、六人确认） | ❌ 完全没有 |
| **作业 2（分解+编排）** | ✅ 完整（B01 动态计划 + B02 九态） | ✅ 完整（PM Agent + Kahn） |
| **作业 2（执行）** | ⚠️ mock（`simulated=True`） | ❌ 没有 |
| **作业 2（执行控制）** | ⚠️ 只有推进/跑完 | ❌ 没有 |
| **作业 3（可观测）** | ⚠️ 部分（事件流、回放） | ❌ 没有 |
| **契约管理** | 手写 dict + 文档 | ✅ Pydantic 生成，单一来源 |
| **后端技术** | 标准库 `http.server` | FastAPI + SQLAlchemy + Alembic |
| **部署** | 单端口 7100 | 双端口（8000 + 5173） |

### 结论

**我们项目的功能覆盖比 SE-lib 更完整**：多了作业 1 的全部、执行环节、以及部分作业 3 能力。SE-lib 的优势在**工程质量**（契约生成、ORM、迁移、审计文档）。

---

## 五、可复用的具体建议

按价值排序：

### 高价值（建议参考）

1. **Design Spec / TaskProposal 的 JSON Schema**
   - 位置：`docs/contracts/*.schema.json`
   - 用途：完善我们 `phase_bridge` 产出的设计规格结构（当前 `contract` 是空的）
   - 注意：不要直接替换我们现有的 `docs/TASK_ORCHESTRATION.md` 契约，而是**吸收它缺失的字段**

2. **契约单一来源的做法**
   - 它用 Pydantic 模型生成 JSON Schema → OpenAPI → TS 类型
   - 我们目前是手写 dict + 手写文档，容易出现字段漂移（历史上已发生过 `SHA256_PATTERN` 不一致）

3. **PM Agent 的结构化输出与修复机制**
   - 位置：`backend/flowstudio_pm/`
   - 用途：我们的真实模型接入已遇到 `P0/P1` 优先级格式问题，可参考它的容错与修复策略

### 中价值（可借鉴思路）

4. **Kahn 拓扑 + 并行批次**
   - 我们有拓扑序，但"并行批次"的概念可以增强甘特视图的表达

5. **工作流画布的交互细节**
   - 搜索定位、连线编辑、PNG 导出

### 低价值（不建议）

6. **整体技术栈迁移**（改 FastAPI / SQLAlchemy）
   - 我们没有依赖，迁移成本高、收益低
7. **直接复用代码**
   - 两边数据模型差异大，直接搬会产生适配层负担

---

## 六、给老师的一句话澄清（建议）

老师可能没意识到 SE-lib 是作业 2 的实现。建议这样问：

> 我们核对了 SE-lib（FlowStudio）的代码，发现它实现的是**作业 2**（设计规格 → PM Agent 任务分解 → 编排 → 规划可视化），**不包含作业 1 的多智能体讨论**（无讨论状态机、无质疑者角色、无共识机制）。
> 请问推荐它作为「任务 1 参考」是否基于它的**文档组织 / 契约管理 / 工程质量**，还是希望我们参考它的**某个具体做法**？

---

## 七、附：它的文档结构（值得学习）

SE-lib 的 `docs/` 有 60+ 份文档，按主题分层：

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

**这一点值得学**：文档按角色可读（产品/架构/设计/开发/测试），而不是按代码目录。

我们目前的 `docs/` 只有 8 份，且偏技术契约，缺少产品与验收视角的文档。
