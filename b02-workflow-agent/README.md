# B02 WorkflowAgent · discussion_controller + task_orchestrator

这是第 10 组**第一部分 B02 流程编排 Agent**的可运行原型，包含两套相互独立的能力：

1. **讨论状态机（`discussion_controller`）**：轮次控制、独立发散、批判回路、暂停恢复、
   人工确认入口，以及 Workflow 图、阶段迁移表和控制伪代码。
2. **开发任务编排器（`task_orchestrator`，第二阶段 D15/D16）**：读取 B01 `plan.json`，
   维护九态、检查依赖、拒绝重复派发、管理 `attempt_id` / `retry_count`，
   把任务派发给 B04、把候选结果交给 B06 验收，并记录任务事件。

两者的状态存储相互独立：讨论流程用 `data/RUN-*.json`，任务编排用
`data/task-state.db`（B03 `TaskStateStore`）。接口契约见
[`docs/TASK_ORCHESTRATION.md`](../docs/TASK_ORCHESTRATION.md)。

## 任务编排 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/task-plans/load` | 载入并校验计划（`{"plan": {...}}` 或 `{"plan_path": "..."}`） |
| POST | `/api/task-runs/from-spec` | 设计规格经 B01 动态分解后创建任务运行 |
| POST | `/api/task-runs/from-discussion` | 已确认 R1 经阶段桥接后创建任务运行 |
| GET | `/api/task-plans` | 已载入计划列表 |
| GET | `/api/task-plans/{plan_id}` | 计划详情 |
| POST | `/api/task-runs` | 由计划创建运行 |
| GET | `/api/task-runs` | 运行列表 |
| GET | `/api/task-runs/{run_id}` | 运行快照 |
| POST | `/api/task-runs/{run_id}/step` | 推进一个调度步（最多派发一个任务） |
| POST | `/api/task-runs/{run_id}/run` | 推进到收敛或步数上限 |
| GET | `/api/task-runs/{run_id}/events?after=&limit=` | 事件流（游标分页） |
| GET | `/api/task-runs/{run_id}/dag` | DAG 视图（节点 + 边） |
| POST | `/api/task-runs/{run_id}/replay` | 事件回放并与快照比对 |
| GET | `/api/task-runs/{run_id}/restore` | 断点恢复视图 |

第一阶段讨论运行在 `COMPLETED` 且已发布 R1 后，可通过
`GET /api/runs/{run_id}/design-spec` 查看 B01 可消费的设计规格。阶段二也可以直接使用
JSON/Markdown 设计规格，不依赖校园案例。

第一阶段的 R1 需求支持 OpenAI-compatible API。默认没有密钥时会使用本地领域规则生成需求，
配置 `SE_WORKFLOW_LLM_API_KEY`、`SE_WORKFLOW_LLM_BASE_URL`、`SE_WORKFLOW_LLM_MODEL` 后，
`RequirementGateway` 会调用模型并校验结构化 JSON。B05 统一工作台也可以在运行时配置模型。
详见 [`docs/LLM_INTEGRATION.md`](../docs/LLM_INTEGRATION.md)。

示例（B02 启动后）：

```bash
curl -X POST http://127.0.0.1:7100/api/task-plans/load \
  -H "Content-Type: application/json" \
  -d '{"plan_path": "b01-spec-planner/docs/fixtures/campus-lost-found.plan.json"}'

curl -X POST http://127.0.0.1:7100/api/task-runs \
  -H "Content-Type: application/json" -d '{"plan_id": "PLAN-campus-lost-found-v1.0"}'

curl -X POST http://127.0.0.1:7100/api/task-runs/TASK-RUN-XXXXXXXX/run \
  -H "Content-Type: application/json" -d '{"max_steps": 200}'

curl http://127.0.0.1:7100/api/task-runs/TASK-RUN-XXXXXXXX/dag
```

### 状态机要点

- 九态：`PENDING READY RUNNING WAITING_DEPENDENCY REVIEWING FAILED RETRYING BLOCKED SUCCEEDED`。
- 只有依赖全部 `SUCCEEDED` 才进入 `READY`；上游 `FAILED`/`BLOCKED` 使下游 `BLOCKED` 并记录
  `blocked_reason`。
- `RUNNING`/`REVIEWING` 期间重复派发被拒绝；`attempt_id` 单调递增，`retry_count`
  只在失败重派时递增，且不超过任务的 `retry_budget`。
- 事件绑定 `task_id` / `attempt_id` / `plan_version` / `input_snapshot`；
  `TASK_OUTPUT_SUBMITTED` 与 `TASK_ACCEPTED` 额外携带 `candidate_commit`。
- **只有 B02 写状态**：B04 只返回执行结果，B06 只返回判定与事件。
  `TASK_ACCEPTED` 等状态事件的 `producer` 恒为 `B02`，B06 结论通过
  `payload.gate` 与独立缺陷事件体现。

### 执行与验收接入

默认（未安装其他工作块时）使用编排器内置的显式占位实现，返回值标记 `simulated`。
从仓库根目录运行时可自动接入真实工作块：

- 执行：B04 `b04.gateway.TaskExecutionGateway`（`mock` 确定性模式）。
- 验收：B06 `multiagent_quality.task_gate.review_task`。

## 1. 启动与验证

环境：Python 3.10+、Node.js 18+（仅运行脚本和浏览器测试需要 Node）。运行时无第三方 Python 或前端依赖。

正式集成运行时，先构建 B05，再由本服务在同一端口托管页面与 API：

```bash
cd ../frontend
npm ci
npm run build
cd ../b02-workflow-agent
python -m backend.app --host 127.0.0.1 --port 7100
```

浏览器打开 `http://127.0.0.1:7100/`。B05 构建目录默认是 `../frontend/dist`，也可以通过
`--frontend-dir` 指定其他构建目录。

```bash
npm run dev
```

`npm run dev` 只启动 B02 服务（适合后端测试）；如果已经执行过 `npm run build`，打开
`http://localhost:7100/` 即可看到 B05 页面。也支持转发主机和端口参数：

```bash
npm run dev -- --host 127.0.0.1 --port 7100
```

运行单元测试：

```bash
npm test
```

运行真实 Edge 浏览器端到端测试（Windows，会临时启动并在结束时关闭自有服务与浏览器进程）：

```bash
npm run test:browser
```

## 2. 课堂演示路线

### 正常收敛

1. 选择“正常收敛 → 六人确认”，点击“启动讨论 Workflow”。
2. 先点“推进一阶段”，观察事件与 A～H 阶段变化；再点“运行至人工介入”。
3. 第一轮产生开放异议，B02 根据预算回到 `CRITIQUE`；第二轮异议解决后才进入 Proposal 审阅。
4. 流程停在 `HUMAN_CONFIRMATION / WAITING_HUMAN`，此时没有 R1。
5. 只选五人会显示拒绝信息；六人全部确认后才进入 `COMPLETED` 并发布 R1。

### 价值分歧

选择“价值分歧 → 人类裁决”。流程停在 `EVALUATE / WAITING_HUMAN`，自动推进按钮不可用。填写裁决与理由后，异议关联 `decision_id`，流程才恢复。

### 预算耗尽

选择“预算耗尽 → 诚实停止”。达到最大批判轮数后仍有开放异议，状态为 `STOPPED`。这不等于达成共识，不生成 Proposal 确认结果或 R1。

### Agent 失败

选择“Agent 失败 → 阻断”。B04 模拟超时，流程在 `DIVERGE` 进入 `BLOCKED`，黑板观点保持为空，不伪造后续结果。

### 暂停、回放与导出

- 在阶段间 `READY` 状态可暂停；恢复前不会派发新任务。
- “事件回放”显示连续 `sequence / event_id / type / after` 并核对回放状态与 checkpoint。
- JSON 与 Markdown 导出均包含阶段、迁移表、伪代码、观点、异议、Proposal、事件和回放校验；R1 只在确认后出现。

### 前端实时连接

B02 向可视化前端提供只读 WebSocket：

```text
ws://127.0.0.1:7100/ws/runs/{run_id}
```

连接后立即收到完整 `snapshot`；每次控制事件持久化后，推送 `event + 最新 run`。暂停、裁决、确认等操作仍走 HTTP，前端不能通过 WebSocket 直接改黑板。完整消息格式和 JavaScript 示例见 `WEBSOCKET_API.md`。

## 3. 职责与接口

| 模块 | 本原型中的责任 | 边界 |
|---|---|---|
| B01 | 提供需求草案与六人确认门槛 | B02 不自行发布需求 |
| **B02** | **唯一推进讨论阶段的控制器** | 不生成角色专业答案，不代替 B06 评价 |
| B03 | 文件型黑板、事件和检查点持久化 | 原子写入 `data/RUN-*.json` |
| B04 | 四角色独立观点、批判、Proposal 审阅候选输出 | 返回内容，不控制阶段 |
| B05 | 消费 HTTP 快照和 WebSocket 事件进行可视化 | 不直接修改控制状态 |
| B06 | 返回开放异议、是否需要人类、能否前进等评价 | B02 决定控制动作 |

当前 `backend/adapters.py` 中的 B01 / B04 / B06 是**可替换的本地测试适配器**，用于验证 B02 契约，不冒充其他成员的真实模型或服务成果。

## 4. 项目结构

```text
b02-workflow-agent/
├── backend/
│   ├── app.py                  # HTTP / WebSocket 与静态页面服务
│   ├── controller.py           # DiscussionController，唯一阶段推进入口
│   ├── websocket.py            # 只读快照、事件推送与心跳
│   ├── workflow_definition.py  # A—H 阶段、迁移表、控制伪代码
│   ├── adapters.py             # B01 / B04 / B06 测试适配器
│   ├── store.py                # B03 快照与事件存储
│   ├── exporter.py             # JSON / Markdown 报告
│   └── errors.py               # 可控流程异常
├── static/                     # 操作界面，无外部 CDN
├── tests/
│   ├── test_controller.py      # 9 项控制单元测试
│   ├── test_websocket.py       # 3 项协议与事件分发测试
│   └── browser_smoke.mjs       # 浏览器及真实 WebSocket 端到端验收
├── B02_设计说明.md              # Workflow 图、迁移表、伪代码与接口契约
├── WEBSOCKET_API.md             # 前端连接地址、消息协议与示例
└── data/                       # 运行后生成的本地持久化快照
```

## 5. 简化与未完成项

- 这是课堂流程原型，不接入真实大模型、外部检索或团队账号系统。
- B03 使用本地 JSON 文件，适合单机演示，不是并发生产数据库。
- 人类确认以六个独立复选项模拟，不包含身份认证和电子签名。
- `replay()` 校验有序控制事件与当前 checkpoint 一致；不是重新调用模型生成分歧内容。
- WebSocket 没有认证和 TLS，只用于本地或受控局域网演示，不应直接暴露公网。
- 本地预览不等于公网部署；本项目包含后端 API，不能作为纯静态站点发布。
