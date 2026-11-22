# B05 交互展示 Agent · 用户工作台

第 10 组 B05（InterfaceAgent）实现。基于 React + TypeScript + Vite + React Flow + dagre，
提供项目总览、项目主理人、需求与方案、规格与计划、编排与执行、Agent 执行、成果交付、历史项目八个页面。
默认落地在「编排与执行」，保留原有工作流监控、DAG 展示和调试入口。

数据源严格区分「模拟推演」与「真实接口」，界面会明确标注当前来源，
连接失败时不会把模拟数据当作真实数据展示；前端只读取和展示后端数据，不自行生成项目或执行结果。

## 运行

```bash
npm ci
npm run dev
```

浏览器打开 Vite 提示的地址（默认 http://localhost:5173）。

如果要用真实接口，先启动 B02 后端：

```bash
cd ../b02-workflow-agent
python -m backend.app --host 127.0.0.1 --port 7100
```

然后在界面顶部切到「真实接口」，填入 B02 地址与运行编号（`TASK-RUN-…`），
点击「加载运行」。运行编号需要先在 B02 中创建（见 `b02-workflow-agent/README.md`）。

也可以切到「规格与计划」阶段，在“第二阶段入口：设计规格 → PM Agent → 编排器”输入设计规格路径，
点击“从设计规格启动”。页面会调用 B02 的 `/api/task-runs/from-spec`，由 B01 动态生成
计划并创建真实运行；“需求讨论”阶段还支持把第一阶段讨论运行编号转换为任务运行
（`/api/task-runs/from-discussion`），把两套界面接起来。“推进一步”“运行至完成”“回放校验”“断点恢复”
在「编排与执行」阶段的操作栏，分别对应 B02 的调度控制与回放/恢复接口。

## 工作台页面（对应《阶段开发分工》B05）

| 页面 | 展示内容 | 数据来源 |
| --- | --- | --- |
| 01 项目总览 | 项目名称、目标、阶段、完成进度；提交想法创建项目 | `GET /api/runs`、`GET /api/task-runs`、`POST /api/runs` |
| 02 项目主理人 | 提交项目想法、查看讨论结果入口、由 R1 创建任务运行 | `POST /api/runs`、`POST /api/task-runs/from-discussion` |
| 03 需求与方案 | 需求分析、PRD（需求草案/R1）、候选方案、异议、六人确认与人工裁决 | `GET /api/runs/{id}`、`GET /api/runs/{id}/design-spec` |
| 04 规格与计划 | 版本链、设计规格生成任务计划 | `POST /api/task-runs/from-spec` |
| 05 编排与执行 | DAG、时间线、事件流、运行控制、回放与断点恢复 | `GET /api/task-runs/{id}`、`/dag`、`/events?after=` |
| 06 Agent 执行 | 按角色聚合当前任务、真实事件日志、测试证据与异常 | 由任务快照与事件流推导 |
| 07 成果交付 | 生成文件、测试报告、运行导出、C1 契约案例 | 任务快照 `artifacts`/`evidence`/`logs` |
| 08 历史项目 | 历史需求讨论与任务运行记录 | `GET /api/runs`、`GET /api/task-runs` |

> 尚未产生的内容（例如没有 R1 时的设计规格、没有运行时的交付物）会明确标注“未产生 / 暂无”，
> 不会用模拟数据冒充真实执行结果。B02 的 7100 静态讨论页保持独立可访问，未被改动。

## 数据源

| 模式 | 数据来源 | 说明 |
| --- | --- | --- |
| 模拟推演 | `src/data/taskRunFixture.json` | 由**真实编排器**（B02+B03+B04+B06）跑出的历史运行快照，不是手工编造。可在下拉框切换「全部通过」「失败/阻断」两个场景 |
| 真实接口 | `GET /api/task-runs/{run_id}`、`/dag`、`/events?after=` | 每 3 秒轮询；事件用序号游标增量拉取并去重；首次加载失败清空任务，之后失败保留最近成功快照并标注「重连中/已离线」，不回退成模拟数据 |

`taskRunFixture.json` 由 `workflow_runtime/make_frontend_fixture.py` 生成，可随时重新生成。

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
| 时间线视图与本地关键路径估算 | `src/components/TimelineView.tsx`、`src/utils/timeline.ts` |
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
npm run test      # vitest run（18 个纯函数/接口适配单测）
```

单测覆盖：任务映射与事件状态推导、时间轴与关键路径、自然语言提示、
工作台接口路径与错误透传（`workbenchApi.test.ts`）。

无头浏览器冒烟测试（需要本机 Chrome 或 Edge，会启动真实 Chromium）：

```bash
npm run build
npx vite preview --host 127.0.0.1 --port 4321 &
node tests/ui_smoke.mjs http://127.0.0.1:4321
```

覆盖内容：DAG 渲染、九态图例、切换到失败场景后的阻塞节点、
任务详情面板的八个区块、真实接口未连接时的错误提示且不渲染模拟节点。
另用独立页面检查脚本验证八个页面导航与内容渲染均正常。

界面截图（输出到指定目录）：

```bash
node tests/screenshots.mjs http://127.0.0.1:4321 shots
```

## 目录

```text
frontend/
├── src/
│   ├── App.tsx                     # 八页面工作台容器 / 双数据源
│   ├── api/
│   │   ├── controlApi.ts           # 讨论流程控制指令
│   │   ├── taskRunApi.ts           # B02 任务运行 / DAG / 事件适配
│   │   └── workbenchApi.ts         # 讨论运行 / 项目列表 / 设计规格适配
│   ├── components/
│   │   ├── StageNav.tsx            # 八页面工作台导航
│   │   ├── ProjectOverview.tsx     # 项目总览与创建
│   │   ├── RequirementsView.tsx    # 需求分析与方案确认
│   │   ├── AgentExecutionView.tsx  # Agent 执行中心
│   │   ├── HistoryView.tsx         # 历史项目
│   │   ├── TaskGraph.tsx           # React Flow 画布
│   │   ├── TaskNode.tsx            # 任务节点（Block/重试/耗时/阻塞）
│   │   ├── TaskDetailPanel.tsx     # 任务详情 + 状态驱动人工介入
│   │   ├── TimelineView.tsx        # 时间线 / 关键路径视图
│   │   ├── ActivityLog.tsx         # 事件流视图
│   │   ├── VersionChain.tsx        # 版本追溯面包屑
│   │   └── CaseSamples.tsx         # T06—T08 案例字段样例
│   ├── constants/
│   │   ├── status.ts               # 九态配色与文案
│   │   └── naturalLanguage.ts      # 面向普通用户的状态/事件说明
│   ├── data/
│   │   ├── simulationRuns.ts       # 快照 fixture 加载
│   │   └── taskRunFixture.json     # 真实编排器产物
│   ├── hooks/
│   │   ├── useTaskRun.ts           # 增量游标轮询 / 降级重连 / 控制指令
│   │   └── useTaskWebSocket.ts     # 讨论流程 WebSocket
│   ├── layout/dagreLayout.ts       # DAG 布局
│   ├── utils/
│   │   ├── export.ts               # 成果导出
│   │   └── timeline.ts             # 时间轴投影与关键路径估算
│   └── types/task.ts               # 任务数据模型
└── tests/
    ├── ui_smoke.mjs                # 无头浏览器冒烟
    └── screenshots.mjs             # 生成交付截图
```

## 验收条件对照

| 验收条件 | 实现位置 |
| --- | --- |
| 界面不直接改状态 | 控制动作经 `src/api/controlApi.ts` 发给 B02，仅按回执/事件流更新视图 |
| 可追踪当前尝试与输入版本 | 节点与详情面板展示 `attempt_id`、`retry_count`、`input_snapshot` |
| 模拟与真实明确区分 | 顶部「模拟推演 / 真实接口」切换 + 来源徽标 + 详情面板来源标签 |
| 任务 DAG 与运行面板 | `TaskGraph` + `dagreLayout`（状态图例、MiniMap、Block 状态栏） |
| 阻塞及异议详情 | 详情面板含阻塞原因、缺陷/异议、验收证据、尝试历史 |
| 成果导出 | `src/utils/export.ts`：快照 JSON、追溯表 CSV、缺陷清单、运行报告 |
| 用户能创建项目并查看项目总览 | `ProjectOverview.tsx` + `POST /api/runs`（仅真实模式可写） |
| 能查看需求分析和方案确认结果 | `RequirementsView.tsx` + `GET /api/runs/{id}` |
| 能查看任务分解、DAG 与进度 | 「编排与执行」的依赖图 / 时间线 / 事件流 |
| 能查看 Agent 过程、测试与异常 | `AgentExecutionView.tsx`（按角色聚合真实事件与证据） |
| 能查看交付物与历史记录 | 「成果交付」+ `HistoryView.tsx` |
| 真实数据来自后端，不冒充模拟数据 | 来源徽标 + 各页面来源说明 + 缺失内容明确标注 |
