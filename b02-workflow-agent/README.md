# B02 WorkflowAgent · discussion_controller

这是第 10 组**第一部分 B02 流程编排 Agent**的可运行原型。交付范围是讨论状态机、轮次控制、独立发散、批判回路、暂停恢复、人工确认入口，以及 Workflow 图、阶段迁移表和控制伪代码。

> 本目录不是“课堂作业 2：设计规格 → 开发任务分解 → 开发任务编排”。界面中没有开发任务 DAG，也不声称完成产品代码开发。

## 1. 启动与验证

环境：Python 3.10+、Node.js 18+（仅运行脚本和浏览器测试需要 Node）。运行时无第三方 Python 或前端依赖。

```bash
npm run dev
```

打开 `http://localhost:7100/`。也支持转发主机和端口参数：

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
