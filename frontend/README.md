# B05 交互展示 Agent · 分组侧栏十页面工作台

第 10 组 B05（InterfaceAgent）实现。基于 React + TypeScript + Vite + React Flow + dagre，
提供从用户想法到任务 DAG、再到观测回溯的完整可视化：

```text
项目        01 项目总览
阶段一      02 项目主理人  03 需求讨论  04 需求与方案  05 规格与计划
阶段二      06 编排与执行（默认落地页）  07 Agent 执行  08 成果交付
阶段三      09 观测与回溯  10 历史项目
```

布局为「顶栏品牌 / 项目切换 / 数据源」+ 左侧按阶段分组的侧栏 + 内容区。
全程无人工审批门：需求确认由 agent 角色互相确认完成，用户只通过圆桌插话参与，流程不因等待而暂停。

数据源严格区分「模拟推演」与「真实接口」，界面会明确标注当前来源，
连接失败时不会把模拟数据当作真实数据展示。

## 运行

### 集成运行（推荐，B02/B05 共用 7100 端口）

生产构建由 B02 的 HTTP 服务托管，页面和 API 使用同源地址：

```bash
npm ci
npm run build

cd ../b02-workflow-agent
python -m backend.app --host 127.0.0.1 --port 7100
```

浏览器打开 `http://127.0.0.1:7100/`。前端构建产物位于 `frontend/dist`，
B02 会优先提供该目录；如果尚未构建，B02 仍会回退到自己的演示页面。

真实接口默认使用当前页面的 origin（`window.location.origin`），
集成运行时无需手动填写后端地址；`VITE_API_BASE` 可覆盖该默认值。

### 独立开发（可选，保留 Vite 热更新）

`vite.config.ts` 会把 `/api` 和 `/ws` 转发到 7100，因此仍然只把 B02 作为后端服务：

```bash
# 终端一
cd ../b02-workflow-agent
python -m backend.app --host 127.0.0.1 --port 7100

# 终端二
cd ../frontend
npm run dev
```

此模式默认打开 Vite 提示的地址（通常为 `http://localhost:5173`），仅用于开发热更新。

## 十页面工作台

| 页面 | 展示内容 | 数据来源 |
| --- | --- | --- |
| 01 项目总览 | 项目名称、目标、阶段、完成进度；提交想法创建项目 | `GET /api/runs`、`GET /api/task-runs`、`POST /api/runs` |
| 02 项目主理人 | 提交想法 → 推进讨论 → agent 共识确认 R1 → 进入第二阶段 | `POST /api/runs`、`POST /api/runs/{id}/until-control-point`、`POST /api/runs/{id}/confirm`、`POST /api/task-runs/from-discussion` |
| 03 需求讨论 | A—H 八阶段进度看板；圆桌（四席位、发言记录、插话输入）。圆桌交互为阶段三占位，暂不发送请求 | 讨论运行黑板 |
| 04 需求与方案 | 需求分析、PRD（需求草案/R1）、候选方案、异议、agent 角色表态 | `GET /api/runs/{id}`、`GET /api/runs/{id}/design-spec` |
| 05 规格与计划 | 设计规格基线卡（baseline_id / sha256 / 父链占位）、版本链、模型 API 配置、设计规格查看、从设计规格启动 | `GET/POST /api/llm/config`、`GET /api/runs/{id}/design-spec`、`POST /api/task-runs/from-spec` |
| 06 编排与执行 | DAG / 甘特排期 / 时间线 / 事件流四种视图、运行控制、回放与断点恢复 | `GET /api/task-runs/{id}`、`/dag`、`/events?after=`、`POST .../step`、`/run`、`/replay`、`GET .../restore` |
| 07 Agent 执行 | 按角色聚合当前任务、真实事件日志、测试证据与异常 | 由任务快照与事件流推导 |
| 08 成果交付 | 生成文件、测试报告、运行导出 | 任务快照 `artifacts`/`evidence`/`logs` |
| 09 观测与回溯 | 跨阶段时间轴、模型调用工件表、三级回溯入口（均为阶段三占位） | 任务快照与事件流；模型调用记录待后端接入 |
| 10 历史项目 | 历史需求讨论与任务运行记录 | `GET /api/runs`、`GET /api/task-runs` |

> 尚未产生的内容（例如没有 R1 时的设计规格、没有运行时的交付物）会明确标注"未产生 / 暂无"，
> 不会用模拟数据冒充真实执行结果。占位功能均以「占位 / 待接入」徽标明示。

## 数据源

| 模式 | 数据来源 | 说明 |
| --- | --- | --- |
| 模拟推演 | `src/data/taskRunFixture.json` | 由**真实编排器**（B02+B03+B04+B06）跑出的历史运行快照，不是手工编造。可在下拉框切换「全部通过」「失败/阻断」两个场景 |
| 真实接口 | `GET /api/task-runs/{run_id}`、`/dag`、`/events?after=` | 每 3 秒轮询；事件用序号游标增量拉取并去重；首次加载失败清空任务，之后失败保留最近成功快照并标注「重连中/已离线」，不回退成模拟数据 |

`taskRunFixture.json` 由 `workflow_runtime/make_frontend_fixture.py` 生成，可随时重新生成。

## 05 编排与执行：四种任务视图

同一个任务数组支持四种观察角度，切换不改变任何状态：

| 视图 | 组件 | 说明 |
| --- | --- | --- |
| 依赖 DAG | `TaskGraph` + `layout/dagreLayout.ts` | React Flow 画布，九态配色、依赖边、MiniMap |
| 甘特排期 | `TaskTimeline` | 按依赖层级排布的开始位置与估计时长（`.gantt-*` 样式） |
| 时间线 | `TimelineView` + `utils/timeline.ts` | 按真实 `started_at`/`finished_at` 投影，并估算关键路径 |
| 事件流 | `ActivityLog` | 按 `sequence` 倒序展示事件，标注增量游标 |

> 甘特与时间线是两套不同语义的排期视图，样式前缀分别为 `.gantt-` 与 `.timeline-`，互不覆盖。

## 第二阶段能力（D24/D25/D26）

| 要求 | 实现位置 |
| --- | --- |
| 任务节点、依赖、负责 Block、状态、重试、耗时、阻塞 | `src/components/TaskNode.tsx`、`src/layout/dagreLayout.ts` |
| 九态图例（含 `WAITING_DEPENDENCY`、`RETRYING`） | `src/constants/status.ts` |
| 点击任务展示输入、输出、依赖、验收、测试、日志、提交、缺陷 | `src/components/TaskDetailPanel.tsx` |
| 真实接口接入与来源区分 | `src/api/taskRunApi.ts`、`src/hooks/useTaskRun.ts` |
| 模拟/真实数据源切换 | `src/App.tsx` |
| 阶段化工作台（八个页面） | `src/components/StageNav.tsx`、`src/App.tsx` |
| 项目总览 / 创建项目 | `src/components/ProjectOverview.tsx`、`src/api/workbenchApi.ts` |
| 需求与方案（PRD / 候选方案 / 确认结果） | `src/components/RequirementsView.tsx` |
| Agent 执行中心（角色 / 日志 / 测试 / 异常） | `src/components/AgentExecutionView.tsx` |
| 历史项目与成果交付 | `src/components/HistoryView.tsx`、`src/App.tsx` |
| 面向普通用户的自然语言状态提示 | `src/constants/naturalLanguage.ts` |
| 事件流视图与增量游标状态 | `src/components/ActivityLog.tsx`、`src/hooks/useTaskRun.ts` |
| 版本链追溯面包屑 | `src/components/VersionChain.tsx` |
| 详情面板按状态给出人工介入入口 | `src/components/TaskDetailPanel.tsx` |

任务类型定义（含 `block_id`、`acceptance`、`required_test_ids`、`candidate_commit`、
`logs`、`duration_seconds`、`review` 等字段）见 `src/types/task.ts`，
与 [`docs/TASK_ORCHESTRATION.md`](../docs/TASK_ORCHESTRATION.md) §3 一致。

## 验证

```bash
npm run build     # tsc -b && vite build
npm run lint      # oxlint
npm run test      # vitest run（20 个纯函数/接口适配单测）
```

单测覆盖：任务映射与事件状态推导、时间轴与关键路径、自然语言提示、
工作台接口路径与错误透传（`workbenchApi.test.ts`）。

无头浏览器冒烟测试（需要本机 Chrome 或 Edge，会启动真实 Chromium）：

```bash
npm run build
cd ../b02-workflow-agent
python -m backend.app --host 127.0.0.1 --port 7100

# 另开终端
cd ../frontend
node tests/ui_smoke.mjs http://127.0.0.1:7100    # 功能冒烟（导航 / DAG / 视图 / 表单 / 错误隔离）
node tests/ui_layout.mjs http://127.0.0.1:7100   # 布局断言（侧栏/顶栏/内容区、无横向溢出、窄屏断点）
```

覆盖内容：十页面导航逐页渲染与四组分组、DAG 节点与九态图例、四种任务视图切换、
失败场景阻塞节点、任务详情面板、项目主理人的想法输入与 agent 共识确认入口、
圆桌 / 观测 / 基线占位页、模型 API 配置与设计规格入口、
真实接口未连接时的错误提示且不渲染模拟节点；界面不再出现人工审批措辞。

如只验证前端静态产物，也可以用 `vite preview` 临时占用 4321；这不属于正式集成运行。

界面截图（输出到指定目录）：

```bash
node tests/screenshots.mjs http://127.0.0.1:7100 shots   # DAG / 失败 / 详情面板
node tests/ui_shots.mjs http://127.0.0.1:7100 shots       # 主要页面逐页
```

## 目录

```text
frontend/
├── src/
│   ├── App.tsx                     # 工作台壳层 / 双数据源 / 页面装配
│   ├── api/
│   │   ├── controlApi.ts           # 讨论流程控制指令
│   │   ├── taskRunApi.ts           # B02 任务运行 / DAG / 事件 / 回放 / 模型配置
│   │   └── workbenchApi.ts         # 讨论运行 / 项目列表 / 设计规格适配
│   ├── components/
│   │   ├── StageNav.tsx            # 分组侧边栏导航（定义在 constants/stages.ts）
│   │   ├── ProjectOverview.tsx     # 项目总览与创建
│   │   ├── RoundTableView.tsx      # 需求讨论：八阶段看板 + 圆桌（占位）
│   │   ├── RequirementsView.tsx    # 需求分析与 agent 共识表态
│   │   ├── BaselineCard.tsx        # 设计规格基线卡（hash / 父链占位）
│   │   ├── ObservationView.tsx     # 观测与回溯（阶段三占位）
│   │   ├── AgentExecutionView.tsx  # Agent 执行中心
│   │   ├── HistoryView.tsx         # 历史项目
│   │   ├── TaskGraph.tsx           # React Flow 画布
│   │   ├── TaskNode.tsx            # 任务节点（Block/重试/耗时/阻塞）
│   │   ├── TaskTimeline.tsx        # 甘特排期
│   │   ├── TimelineView.tsx        # 时间线 / 关键路径视图
│   │   ├── ActivityLog.tsx         # 事件流视图
│   │   ├── TaskDetailPanel.tsx     # 任务详情 + 运行控制
│   │   └── VersionChain.tsx        # 版本追溯面包屑
│   ├── constants/
│   │   ├── stages.ts               # 页面定义与阶段分组
│   │   ├── discussion.ts           # A—H 阶段与圆桌席位
│   │   ├── status.ts               # 九态配色与文案
│   │   └── naturalLanguage.ts      # 面向普通用户的状态/事件说明
│   ├── data/
│   │   ├── simulationRuns.ts       # 快照 fixture 加载
│   │   └── taskRunFixture.json     # 真实编排器产物
│   ├── hooks/
│   │   ├── useTaskRun.ts           # 增量游标轮询 / 降级重连 / 控制与回放
│   │   └── useTaskWebSocket.ts     # 讨论流程 WebSocket
│   ├── layout/dagreLayout.ts       # DAG 布局
│   ├── utils/
│   │   ├── export.ts               # 成果导出（快照/工作流/task.md/追溯/缺陷/报告）
│   │   ├── baseline.ts             # 从 design spec 推导基线事实
│   │   └── timeline.ts             # 时间轴投影与关键路径估算
│   └── types/task.ts               # 任务数据模型
└── tests/
    ├── ui_smoke.mjs                # 无头浏览器冒烟
    ├── ui_layout.mjs               # 结构化布局断言（宽屏 / 窄屏）
    ├── screenshots.mjs             # DAG / 失败 / 详情面板截图
    └── ui_shots.mjs                # 主要页面逐页截图
```

## 验收条件对照

| 验收条件 | 实现位置 |
| --- | --- |
| 界面不直接改状态 | 控制动作经 `src/api/controlApi.ts` 发给 B02，仅按回执/事件流更新视图 |
| 可追踪当前尝试与输入版本 | 节点与详情面板展示 `attempt_id`、`retry_count`、`input_snapshot` |
| 模拟与真实明确区分 | 顶部「模拟推演 / 真实接口」切换 + 来源徽标 + 详情面板来源标签 |
| 任务 DAG 与运行面板 | `TaskGraph` + `dagreLayout`（状态图例、MiniMap、Block 状态栏） |
| 阻塞及异议详情 | 详情面板含阻塞原因、缺陷/异议、验收证据、尝试历史 |
| 成果导出 | `src/utils/export.ts`：快照 JSON、workflow.json、task.md、追溯表 CSV、缺陷清单、运行报告 |
| 用户能创建项目并查看项目总览 | `ProjectOverview.tsx` + `POST /api/runs`（仅真实模式可写） |
| 能查看需求分析和方案确认结果 | `RequirementsView.tsx` + `GET /api/runs/{id}` |
| 能查看任务分解、DAG 与进度 | 「编排与执行」的依赖图 / 甘特 / 时间线 / 事件流 |
| 能查看 Agent 过程、测试与异常 | `AgentExecutionView.tsx`（按角色聚合真实事件与证据） |
| 能查看交付物与历史记录 | 「成果交付」+ `HistoryView.tsx` |
| 真实数据来自后端，不冒充模拟数据 | 来源徽标 + 各页面来源说明 + 缺失内容明确标注 |
