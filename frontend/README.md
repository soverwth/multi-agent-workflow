# B05 交互展示 Agent · 开发任务 DAG 视图

第 10 组 B05（InterfaceAgent）参考实现。基于 React + TypeScript + Vite + React Flow + dagre，
展示开发任务 DAG、任务状态变化、重试与阻塞，并提供任务详情面板。

数据源严格区分「模拟推演」与「真实接口」，界面会明确标注当前来源，
连接失败时不会把模拟数据当作真实数据展示。

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

也可以直接在页面的“第二阶段入口：设计规格 → PM Agent → 编排器”输入设计规格路径，
点击“从设计规格启动”。页面会调用 B02 的 `/api/task-runs/from-spec`，由 B01 动态生成
计划并创建真实运行；“推进一步”和“运行至完成”分别对应 B02 的调度控制接口。

页面顶部的“统一 SE Workflow 工作台”还支持完整演示路径。输入用户想法后创建第一阶段运行，
推进到需求确认并完成六人确认，随后查看桥接后的 design spec，直接创建第二阶段任务运行。
工作台的模型 API 配置可以启用 DeepSeek 或其他 OpenAI-compatible 服务。没有密钥时使用本地
领域规则，仍会根据不同想法生成不同需求集合。接口和环境变量见 [`docs/LLM_INTEGRATION.md`](../docs/LLM_INTEGRATION.md)。

## 数据源

| 模式 | 数据来源 | 说明 |
| --- | --- | --- |
| 模拟推演 | `src/data/taskRunFixture.json` | 由**真实编排器**（B02+B03+B04+B06）跑出的历史运行快照，不是手工编造。可在下拉框切换「全部通过」「失败/阻断」两个场景 |
| 真实接口 | `GET /api/task-runs/{run_id}`、`/dag`、`/events` | 每 3 秒轮询；连接失败显示错误并清空任务，不回退成模拟数据 |

`taskRunFixture.json` 由 `workflow_runtime/make_frontend_fixture.py` 生成，可随时重新生成。

## 第二阶段能力（D24/D25/D26）

| 要求 | 实现位置 |
| --- | --- |
| 任务节点、依赖、负责 Block、状态、重试、耗时、阻塞 | `src/components/TaskNode.tsx`、`src/layout/dagreLayout.ts` |
| 九态图例（含 `WAITING_DEPENDENCY`、`RETRYING`） | `src/constants/status.ts` |
| 点击任务展示输入、输出、依赖、验收、测试、日志、提交、缺陷 | `src/components/TaskDetailPanel.tsx` |
| 真实接口接入与来源区分 | `src/api/taskRunApi.ts`、`src/hooks/useTaskRun.ts` |
| 模拟/真实数据源切换 | `src/App.tsx` |
| 统一工作台、design spec 查看、模型配置 | `src/App.tsx`、`src/api/taskRunApi.ts` |

任务类型定义（含 `block_id`、`acceptance`、`required_test_ids`、`candidate_commit`、
`logs`、`duration_seconds`、`review` 等字段）见 `src/types/task.ts`，
与 [`docs/TASK_ORCHESTRATION.md`](../docs/TASK_ORCHESTRATION.md) §3 一致。

## 验证

```bash
npm run build     # tsc -b && vite build
npm run lint      # oxlint
```

无头浏览器冒烟测试（需要本机 Chrome 或 Edge，会启动真实 Chromium）：

```bash
npm run build
npx vite preview --host 127.0.0.1 --port 4321 &
node tests/ui_smoke.mjs http://127.0.0.1:4321
```

覆盖内容：DAG 渲染、九态图例、切换到失败场景后的阻塞节点、
任务详情面板的八个区块、真实接口未连接时的错误提示且不渲染模拟节点。

界面截图（输出到指定目录）：

```bash
node tests/screenshots.mjs http://127.0.0.1:4321 shots
```

## 目录

```text
frontend/
├── src/
│   ├── App.tsx                     # 双数据源仪表盘
│   ├── api/
│   │   ├── controlApi.ts           # 讨论流程控制指令
│   │   └── taskRunApi.ts           # B02 任务运行 / DAG / 事件适配
│   ├── components/
│   │   ├── TaskGraph.tsx           # React Flow 画布
│   │   ├── TaskNode.tsx            # 任务节点（Block/重试/耗时/阻塞）
│   │   ├── TaskDetailPanel.tsx     # 任务详情（D25）
│   │   └── CaseSamples.tsx         # T06—T08 案例字段样例
│   ├── constants/status.ts         # 九态配色与文案
│   ├── data/
│   │   ├── simulationRuns.ts       # 快照 fixture 加载
│   │   └── taskRunFixture.json     # 真实编排器产物
│   ├── hooks/
│   │   ├── useTaskRun.ts           # 真实接口轮询
│   │   └── useTaskWebSocket.ts     # 讨论流程 WebSocket
│   ├── layout/dagreLayout.ts       # DAG 布局
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
