# B02 前端实时接口（WebSocket）

## 1. 连接地址

同一台电脑联调：

```text
ws://127.0.0.1:7100/ws/runs/{run_id}
```

例如：

```text
ws://127.0.0.1:7100/ws/runs/RUN-548F5D08FE
```

`run_id` 来自 `POST /api/runs` 或 `GET /api/runs`。WebSocket 与现有 HTTP API 共用 **7100 端口**，不需要额外开放第二个端口。

跨电脑联调时，B02 启动：

```bash
npm run dev -- --host 0.0.0.0 --port 7100
```

前端把 `127.0.0.1` 换成运行 B02 的电脑局域网 IP。`127.0.0.1` 在另一台电脑上会指向那台电脑自身。

## 2. 推送协议

### 连接成功后的完整快照

服务器立即发送一次 `snapshot`，断线重连也会重新发送，因此前端不必补齐遗漏消息：

```json
{
  "type": "snapshot",
  "run_id": "RUN-548F5D08FE",
  "sequence": 1,
  "run": {
    "run_id": "RUN-548F5D08FE",
    "stage": "INTAKE",
    "status": "READY",
    "round": 0,
    "max_rounds": 2,
    "blackboard": {},
    "events": []
  }
}
```

实际 `blackboard` 包含观点、异议、决议、Proposal、需求草案和 R1 等字段；`events` 包含截至当前的完整控制事件。

### 每次控制变化后的事件与最新快照

每次阶段推进、批判回路、暂停恢复、人工裁决、需求确认或失败阻断都会推送：

```json
{
  "type": "event",
  "run_id": "RUN-548F5D08FE",
  "sequence": 5,
  "event": {
    "event_id": "E005",
    "sequence": 5,
    "type": "IDEA_FRAMED",
    "time": "2026-11-16T17:35:00+08:00",
    "payload": {},
    "after": {
      "stage": "DIVERGE",
      "status": "READY",
      "round": 0
    }
  },
  "run": {}
}
```

`run` 是该事件写入 B03 后的最新完整运行快照。前端可直接替换本地状态，也可以只读取 `event.after` 更新阶段图。

## 3. 前端原生 JavaScript 示例

```js
function connectWorkflow(runId) {
  const socket = new WebSocket(`ws://127.0.0.1:7100/ws/runs/${runId}`);

  socket.addEventListener("open", () => {
    console.log("B02 实时通道已连接");
    socket.send(JSON.stringify({ type: "ping" }));
  });

  socket.addEventListener("message", (message) => {
    const data = JSON.parse(message.data);

    if (data.type === "snapshot") {
      renderDashboard(data.run);       // 初始化或断线恢复
      return;
    }

    if (data.type === "event") {
      updateWorkflow(data.event.after); // 阶段、状态、轮次
      appendEvent(data.event);          // 事件时间线
      renderDashboard(data.run);        // 最新完整快照
      return;
    }

    if (data.type === "pong") {
      console.log("B02 连接正常");
    }
  });

  socket.addEventListener("close", () => {
    console.log("B02 实时通道已关闭");
    // 产品化时可采用指数退避后重新调用 connectWorkflow(runId)。
  });

  return socket;
}
```

## 4. 操作仍使用 HTTP

WebSocket 是只读数据通道，不能用它越过流程门槛。前端按钮继续调用：

| 操作 | 方法与地址 | 请求体 |
|---|---|---|
| 创建运行 | `POST /api/runs` | `{idea, constraints, scenario, max_rounds}` |
| 推进一阶段 | `POST /api/runs/{run_id}/step` | 无 |
| 运行至人工介入 | `POST /api/runs/{run_id}/until-control-point` | 无 |
| 暂停 / 恢复 | `POST /api/runs/{run_id}/pause` 或 `/resume` | 无 |
| 人类裁决 | `POST /api/runs/{run_id}/human-decision` | `{decision}` |
| 六人确认 | `POST /api/runs/{run_id}/confirm` | `{members: [成员 A…成员 F]}` |
| 主动查询快照 | `GET /api/runs/{run_id}` | 无 |
| 回放校验 | `GET /api/runs/{run_id}/replay` | 无 |

HTTP 操作成功后，服务器先持久化事件，再推送 WebSocket 消息。因此前端收到的快照与磁盘 checkpoint 一致。

## 5. 心跳与边界

- 服务器每 20 秒发送协议级 ping；浏览器会自动回应 pong。
- 前端也可发送 `{"type":"ping"}`，服务器返回 `{"type":"pong"}`。
- 不存在的 `run_id` 会在握手前返回 HTTP 404。
- 当前实现用于课堂本地原型，没有账号认证、TLS 或公网访问控制；不应直接暴露到公网。
