# 通用多智能体协作开发平台

本仓库实现一个可适配不同业务系统的多智能体协作开发平台。平台把需求讨论、设计规格、任务编排、Agent 执行、证据验收、交互展示和独立质量验收组织成可追溯的 Workflow，不把任何单一业务系统写死在核心流程中。

校园失物招领系统只是用于演示和回归测试的示例 fixture。接入电商、教务、医疗、企业内部系统或其他软件项目时，只需替换领域需求、数据模型、接口契约和测试适配器，平台的黑板、编排器、Agent 协议、证据规则和质量门仍可复用。

## 通用模型

平台由以下稳定能力组成：

- **共享黑板**：保存需求、设计、任务、观点、异议、决策、产物和测试证据。
- **主持人编排器**：根据依赖、权限和验收条件推进任务，处理等待、失败、返修和重验。
- **可插拔 Agent**：产品、用户研究、架构、实现、测试、质量等角色通过统一输入输出协议接入，可替换模型和领域提示词。
- **领域适配器**：为具体系统提供需求模板、术语表、数据模型、接口契约、测试 fixture 和导出格式。
- **独立质量门**：校验计划、证据、缺陷和回归结果，不把模型回复当成测试证据。

通用骨架与领域适配解耦：

```text
通用项目输入 → 需求与设计基线 → 任务图（DAG）→ Agent 产物 → 独立验收 → 集成发布
```

## 两阶段通用 SE Workflow

项目按两个相互衔接的阶段运行：

```text
第一阶段：用户想法 → 多智能体讨论 → 建设方案 → R1 需求确认
                                      ↓ 设计规格/追溯来源
第二阶段：设计规格 → PM Agent 任务分解 → 编排器 → 执行/质量门 → DAG 展示与控制
```

第一阶段形成的 R1 经过确认后，可以通过 B02 阶段桥接接口生成 B01 可消费的最小设计规格；
团队也可以直接提供更完整的 JSON/Markdown design spec。第二阶段的任务数量、依赖和验收条件
由规格动态推导，校园失物招领只是演示 fixture。

## 第二阶段闭环（已完成）

```text
设计规格输入 → B01 任务分解 → B02 任务编排 → B03 状态持久化
→ B04 Agent 执行 → B06 证据验收 → B05 DAG 可视化 → 集成发布
```

各环节的字段与接口契约集中在 **[docs/TASK_ORCHESTRATION.md](docs/TASK_ORCHESTRATION.md)**，
所有工作块按同一份契约实现，跨块联调由 `workflow_runtime/` 装配与验证。

### 能力速览

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 通用规格输入 | `b01-spec-planner/src/b01/spec_input.py` | 支持任意系统的设计规格 JSON/Markdown，归一化为统一结构 |
| 动态计划 | `b01-spec-planner/src/b01/dynamic_planner.py` | 按规格推导任务、DAG、拓扑序，不固定 T01—T11 |
| 计划校验 | `b01-spec-planner/src/b01/plan_validator.py` | 结构、需求覆盖、产物归属、依赖环、版本一致性 |
| 任务编排 API | `b02-workflow-agent/backend/task_api.py` | `task-plans/load`、`task-runs`、`step`、`run`、`events`、`dag`、`replay` |
| 编排状态机 | `b02-workflow-agent/backend/task_orchestrator.py` | 九态、依赖检查、防重复派发、attempt_id、retry_count、有限重试、阻断传播 |
| 状态持久化 | `b03/b03_implementation/task_state.py` | 运行/状态/尝试历史/事件/检查点，支持断点恢复与回放 |
| 统一执行 Gateway | `b04-agent-integration/src/b04/gateway.py` | §5 输入输出契约，`mock` 与真实 runner 两种模式 |
| 质量门 | `b06-quality-consensus/multiagent_quality/task_gate.py` | 九项必查、只返回判定与事件，不写状态 |
| 任务 DAG 展示 | `frontend/src/` | 九态图例、依赖边、重试/耗时/阻塞、任务详情面板、真实接口接入 |
| 闭环演示与验证 | `workflow_runtime/` | 一键跑通闭环 + 契约一致性检查 |

## 当前工作块

- B01：需求确认与规格规划（通用规格输入 + 动态任务计划）
- B02：任务编排器与讨论控制器（含开发任务编排 HTTP API）
- B03：共享黑板、状态持久化与事件
- B04：Agent 接入、统一执行 Gateway 与模型适配
- B05：交互展示与结果导出（任务 DAG 视图）
- B06：质量共识、测试证据与缺陷闭环（含开发任务质量门）

## 分支约定

- `main`：稳定的项目主线，只接受经过集成验收的合并。
- `integration`：跨工作块集成分支，用于联调和回归测试。
- `bXX-*`：各工作块的长期开发分支。
- `bXX-*/task-*`：单项任务的短期分支。

不要直接向 `main` 推送。提交应关联任务编号、需求引用、输入版本、测试命令和证据；接口变更需通知所有消费方。

## 接入新系统

1. 编写该系统的设计规格（JSON 或 Markdown，格式见 `docs/TASK_ORCHESTRATION.md` §2.1）。
2. 用 `python -m workflow_runtime pipeline --spec <你的规格>` 验证规格能被正确分解。
3. 把领域验收项映射为任务的 `acceptance` 与 `required_test_ids`。
4. 复用通用 Agent 协议、编排规则和质量门跑完整 Workflow。
5. 将领域结果与通用过程证据分开保存，避免污染核心模型。

## 快速开始

环境要求：Python 3.12+、Node.js 22+ 和 npm。

各工作块可以独立验证：

```powershell
# B01 规格规划（含通用规格输入与动态计划）
cd b01-spec-planner
python -m pip install -e ".[test]"
python run_checks.py all --allow-reference
python -m pytest -q

# B02 讨论控制器 + 任务编排器
cd ..\b02-workflow-agent
python -m unittest discover -s tests -v

# B03 黑板与状态持久化
cd ..\b03\b03_implementation
python -m pytest -q

# B04 Agent 接入与受控执行
cd ..\..\b04-agent-integration
python -m pip install -e ".[test]"
python -m pytest -q

# B05 前端
cd ..\..\frontend
npm ci
npm run build
npm run lint

# B06 质量验收
cd ..\b06-quality-consensus
python -m pytest -q
python -m tests.smoke

# 第二阶段闭环（规格 → 计划 → 编排 → 执行 → 验收 → DAG → 回放）
cd ..
python workflow_runtime/verify_contracts.py
python -m workflow_runtime pipeline --scenario success
```

## 运行项目原型（B02/B05 单端口）

B02 后端现在同时托管 B05 的生产构建产物，正式运行只需要 **7100 一个端口**：

```powershell
# 首次运行或前端代码更新后执行一次
cd frontend
npm ci
npm run build

# 启动统一服务
cd ..\b02-workflow-agent
python -m backend.app --host 127.0.0.1 --port 7100
```

浏览器打开 `http://127.0.0.1:7100/`。页面、B02 API 和任务编排接口均来自同一个地址，
不再需要单独启动 5173/4321 端口。

前端有两个数据源，界面会明确标注当前来源：

- **模拟推演**：展示由真实编排器（B02+B03+B04+B06）跑出的历史运行快照，
  可在下拉框切换「全部通过」与「失败/阻断」两个场景。
- **真实接口**：填入 B02 地址与运行编号（`TASK-RUN-…`）后实时拉取
  `GET /api/task-runs/{run_id}` 与 `/dag`。连接失败时显示错误且**不会**
  把模拟数据当作真实数据展示。

前端的“第二阶段入口：设计规格 → PM Agent → 编排器”可以直接填写规格路径，点击“从设计规格启动”
创建真实任务运行；随后可用“推进一步”观察依赖调度，或用“运行至完成”执行完整闭环。

B05 采用分组侧栏十页面工作台（01 项目总览 / 02 项目主理人 / 03 需求讨论 / 04 需求与方案 /
05 规格与计划 / 06 编排与执行 / 07 Agent 执行 / 08 成果交付 / 09 观测与回溯 / 10 历史项目），
侧栏按「项目 / 阶段一 / 阶段二 / 阶段三」分组，默认落地在「编排与执行」。全程无人工审批门。

「02 项目主理人」页：输入用户想法、创建第一阶段运行、推进讨论，到 agent 确认点后由 agent 共识发布 R1，
再直接进入第二阶段任务编排。
「03 需求讨论」页：A—H 八阶段进度看板 + 圆桌（四席位、发言记录、随时插话）。圆桌交互为阶段三占位，暂不发送请求。
「04 需求与方案」页：需求分析、PRD、候选方案与 agent 角色表态。
「05 规格与计划」页的“模型 API 配置”支持 DeepSeek 和其他 OpenAI-compatible 服务。没有 API Key 时，
系统使用领域规则兜底，聊天社交、失物招领、设备预约和通用系统会生成不同的 R1 需求集合；
同页的设计规格基线卡展示 baseline_id / sha256 / 父链（revision / hash 待后端补齐），可查看桥接后的 design spec，并从设计规格启动任务运行。
「06 编排与执行」提供依赖 DAG、甘特排期、时间线、事件流四种视图，
可导出 `workflow.json`、`task.md`、快照 JSON 等六种成果。
「09 观测与回溯」页：跨阶段时间轴、模型调用工件表、三级回溯入口（均为阶段三占位）。
完整配置方式见 [大模型 API 接入说明](docs/LLM_INTEGRATION.md)。

## 课堂展示：从用户想法到任务 DAG

课堂展示可以按下面顺序完整走一遍：

1. 打开 `http://127.0.0.1:7100/`，停留在默认的「06 编排与执行」页。
2. 切到「02 项目主理人」，输入“我想制作一个校园服务系统”或其他任意想法，点击“创建讨论运行”。
3. 点击“运行到下一个控制点”，展示多智能体讨论、建设方案和需求确认过程；到 agent 确认点后点“agent 共识确认 → 发布 R1”。可顺路切到「03 需求讨论」看八阶段看板与圆桌。
4. 点击“进入第二阶段”，或到「05 规格与计划」查看基线卡与桥接后的 design spec 并从设计规格启动。
5. 回到「06 编排与执行」，切到“真实接口”，填入生成的运行编号；点击“推进一步”观察依赖逐层放行，再点击“运行至完成”。
6. 依次展示依赖 DAG / 甘特排期 / 时间线 / 事件流，以及「07 Agent 执行」「08 成果交付」「09 观测与回溯」和可导出的快照/追溯表。

也可以跳过第一阶段，直接演示课堂要求的核心路径。在「05 规格与计划」的“第二阶段入口”保留默认规格路径，
点击“从设计规格启动”，再回到「06 编排与执行」点击“运行至完成”：

```powershell
# 仍然只需启动一个服务
cd frontend
npm run build
cd ..\b02-workflow-agent
python -m backend.app --host 127.0.0.1 --port 7100
```

浏览器打开 `http://127.0.0.1:7100/`。默认的校园失物招领规格只是演示输入；把输入框换成任意符合
`docs/TASK_ORCHESTRATION.md` §2.1 的 JSON/Markdown 规格，即可生成不同项目的任务图。中文项目名称会自动生成
ASCII 计划版本编号，原始中文标题仍保存在规格和追溯信息中。

Windows 如果 `python` 不在 PATH，可把命令中的 `python` 替换为 `py -3`；先用
`python --version` 或 `py -3 --version` 确认 Python 3.12+ 已安装。

## 一键闭环演示

```powershell
# 全部任务验收通过
python -m workflow_runtime pipeline --scenario success

# 失败 → 有限重试耗尽 → 下游阻塞
python -m workflow_runtime pipeline --scenario retry

# 执行被阻断 → 阻断向下游传播
python -m workflow_runtime pipeline --scenario blocked

# 缺少规定测试证据 → 质量门驳回并登记缺陷
python -m workflow_runtime pipeline --scenario evidence
```

每个场景都会输出计划版本、运行状态、完成数、DAG 规模、检查点序号、
事件回放一致性与失败任务明细。

也可以直接指定任意设计规格：

```powershell
python -m workflow_runtime pipeline --spec b01-spec-planner/docs/fixtures/lab-equipment-loan.spec.md
```

## 文档

### 课程项目

- [项目需求规格](docs/PROJECT_REQUIREMENTS.md) — 三阶段要做什么、功能与非功能需求
- [项目流程设计](docs/PROJECT_WORKFLOW.md) — 三阶段流程怎么走、与现有实现的差距
- [团队分工方案](docs/TEAM_DIVISION.md) — 总纲：进度盘点、分支治理、任务卡总表、跨人依赖
- [个人分工文档](docs/team/) — A 讨论状态机 / B 设计规格 / C 计划契约 / D 真实执行 / E 观测验收 / F 圆桌框架，每人只读自己那份
- [待澄清问题清单](docs/OPEN_QUESTIONS.md) — 需问老师的问题、需内部决定的事、技术遗留
- [作业要求与现状对照](docs/HOMEWORK_SCOPE.md) — 原始作业要求与本仓库实现状态
- [参考项目调研：SE-lib](docs/REFERENCE_PROJECTS.md) — 参照其工程规范的具体清单
- [参考项目调研：其他三组实跑对比](docs/REFERENCE_PROJECTS_3WAY.md) — SE-DPA / SE-lib / SE-TeamPrjoect 的实跑记录、对比与吸收清单

### 工程文档

- [项目总览](docs/PROJECT_OVERVIEW.md)
- [任务编排闭环契约](docs/TASK_ORCHESTRATION.md)
- [第二阶段实施记录](docs/STAGE2_STATUS.md)
- [GitHub 协作与分支流程](docs/BRANCHING.md)
- [集成运行说明](docs/INTEGRATION.md)
- [大模型 API 接入说明](docs/LLM_INTEGRATION.md)

各工作块的实现和使用方式写在对应目录的 README 中。
