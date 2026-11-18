# B05 交互展示 Agent · 任务编排视图

第10组软件工程大作业 B05 部分的参考实现（InterfaceAgent）。基于 React + TypeScript + Vite + React Flow + dagre，读取 Orchestrator 事件流展示任务 DAG 与运行面板，提供人工确认入口与成果导出。

## 运行

```bash
npm install
node mock-server.js     # 终端1：启动 Mock Orchestrator (ws://localhost:8000)
npm run dev             # 终端2：启动前端
```

浏览器打开 Vite 提示的地址（默认 http://localhost:5173）。Mock 服务每 3.5 秒推进一步，自动演示 T01→T11、D-01 缺陷发现与返修的完整流程。

## B05 功能与验收条件对照

| 验收条件 | 实现位置 |
|---|---|
| 界面不直接改状态 | 控制动作经 `src/api/controlApi.ts` 发给 B02，仅据 `control_ack`/事件流更新视图 |
| 可追踪当前尝试与输入版本 | 节点与详情面板展示 `attempt_id`/`retry_count`/`input_snapshot`/`spec_version`/`contract_version` |
| 模拟与真实明确区分 | 顶部「模拟推演/真实接口」切换 + 徽标；导出文件元数据含 `data_source`；`?source=real` 切换真实标识 |
| 任务 DAG 与运行面板 | `TaskGraph` + `dagreLayout`（含状态图例、MiniMap、Agent 资源栏） |
| 阻塞及异议详情 | 详情面板含阻塞原因、异议/缺陷、验收证据、尝试历史 |
| 人工确认入口 | 右侧「控制」页：暂停/恢复/重派/取消/变更确认 |
| 成果导出 | `src/utils/export.ts`：快照 JSON、追溯表 CSV、缺陷清单、运行报告 |
| T06—T08 案例前端适配样例 | `src/components/CaseSamples.tsx`（字段对齐 C1，明确标注模拟数据） |

数据源：顶部可切换「模拟推演」与「真实接口」，服务端事件带 `source` 字段，界面与导出均据此区分，避免把模拟结果误认为真实运行。

---

## Vite 模板说明（原始 README）

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
