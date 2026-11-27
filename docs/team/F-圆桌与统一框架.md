# 成员 F 分工 · 圆桌交互前端、统一框架与性能可达性

> 组别：组 3（阶段三）。本文是 `docs/TEAM_DIVISION.md` 的个人子文档，只含你的任务。
> 开工前先读主文档第〇节（开工五步 + 深读清单），再读本文。
> 本文中所有"现状"均已在 main `01f88cd` 上核实到行号。

---

## 一、你的分支

| 分支 | 用途 | 从哪切 | 何时合入 |
|---|---|---|---|
| `feat/p3-roundtable` | F-1 圆桌前端、F-2 CAS 冲突 UI、F-5 预览按钮 | `integration` | 第 2 周末（F-2）、第 3 周末（F-1/F-5） |
| `feat/p3-unified-ui` | F-3 样式规范文档与硬编码清理、F-4 性能可达性基准 | `integration` | 第 2 周末（F-4 先出数据给 E-4）、第 4 周（F-3） |
| `task/f-<编号>-<短名>` | 每张卡一个任务分支 | 对应功能分支 | PR 合回后删除 |

**你的核心命题**：把"用户随时插话、agent 不停"这个交互真正做出来（圆桌），并把本轮已搭好的 token 体系固化成规范与基准，让后三周五个人同时改前端不打架。

**你与别人的联调对象**

| 对方 | 联调什么 | 什么时候 |
|---|---|---|
| A | A-5 的四个圆桌指令接口：`POST /api/runs/{id}/roundtable`，body `{action, target_role?, opponent_role?, text, ref_id?}` → 202。**第 2 周末先一起把形状写进 `TASK_ORCHESTRATION.md` §3.4，再各自实现** | 第 2 周末约定、第 3 周联调 |
| B | B-3 改 `RoundTableView.tsx` 的**数据接入**（props/读取），你改**交互**（按钮/发送/状态）。**同一文件，先在群里划行** | 第 2 周每日同步 |
| C | C-2 的 409 响应体 `{error: {code: "REVISION_CONFLICT", message, current_revision}}`，F-2 据此做弹窗；C-1 改 `TaskGraph.tsx` 的 `useEffect`，你不碰那个文件 | 第 2 周中 |
| D | D-2 提供 `/preview/<run_id>/` 与 `deliverable_url`，F-5 在交付页加按钮 | 第 2 周末 |
| E | E-3 观测页与你共享 token；E-4 引用你 F-4 的基准数据 | 第 2 周末出数据 |

---

## 二、你负责的代码地图

| 文件 | 现状（核实过） | 你要动的 |
|---|---|---|
| `frontend/src/components/RoundTableView.tsx` | 171 行。席位 `SEATS`（`constants/discussion.ts`）四角色；发言流读 `blackboard.claims / objections`；**四个按钮全部 `disabled`（:137-140），发送按钮 `disabled`（:134）**；`chatDraft` 由 App 持有 | F-1 接通按钮与发送 |
| `frontend/src/constants/discussion.ts` | `DISCUSSION_PHASES`、`SEATS`、`phaseIndexForStage` | 不改（A/B 可能加字段） |
| `frontend/src/App.tsx` | 994 行；`chatDraft` state；`handleAdvanceDiscussion / handleConfirmDiscussion`；交付页 `delivery-grid` 段 | F-1 传回调；F-5 加预览按钮 |
| `frontend/src/api/workbenchApi.ts` | `DiscussionRun / Blackboard / DiscussionClaim / DiscussionObjection / DiscussionSignoff` 类型；`advanceDiscussion / confirmDiscussionByConsensus`；无 roundtable 调用 | F-1 加 `sendRoundtableAction` |
| `frontend/src/components/TaskGraph.tsx` | **C-1 的地盘**（布局持久化、连线）——你不碰 | — |
| `frontend/src/App.css` | **59 处 hex 色值，其中 19 处在 `:root` 定义**，其余 40 处散在规则里；组件内联 style 硬编码色 10 处（`TaskNode.tsx` 6 处、`RoundTableView.tsx` 3 处、`TaskGraph.tsx` 1 处） | F-3 清理 |
| `frontend/tests/ui_layout.mjs` | CDP 结构化盒模型断言（宽屏十页 + 窄屏） | F-4 扩展对比度/焦点断言 |
| `frontend/tests/ui_smoke.mjs` | 功能冒烟（十页导航、DAG、视图、表单、错误隔离） | F-1/F-5 加断言 |
| `frontend/src/data/taskRunFixture.json` | 24 任务真实编排器快照（283KB） | F-4 做 100 任务级 fixture 时**新生成**，不改它 |
| `docs/UI_GUIDELINES.md` | **不存在** | F-3 新建 |

---

## 三、任务卡

### F-1 圆桌前端实现（14h，第 3 周）

**目标**：圆桌页的四个指令与插话发送接上 A-5 的真实后端；用户发完立即看到"已收到，将在下一阶段边界应用"，agent 的回应在推进后出现在发言流里。

**前置**：A-5 接口合入 `integration`；与 A 在第 2 周末把请求/响应形状写进 `TASK_ORCHESTRATION.md` §3.4；与 B 划清 `RoundTableView.tsx` 的改动行。

**步骤**

1. `git switch -c task/f-1-roundtable feat/p3-roundtable`
2. `workbenchApi.ts` 加：
   ```ts
   export type RoundtableAction = 'call_on' | 'follow_up' | 'demand_evidence' | 'debate';
   export function sendRoundtableAction(baseUrl, runId, body: { action, target_role?, opponent_role?, text, ref_id? }): Promise<{ queued: true; message_id: string; pending_count: number }>
   ```
3. `RoundTableView.tsx` 改 props：加 `onSendAction(action, payload) => Promise<void>`、`pendingMessages: {message_id, content, created_at}[]`（B-3 的 `listMessages` 提供）。
4. **交互状态机**（每个按钮）：idle → 选择目标（点名/追问/举证需要先选一个席位或一条观点；辩论需要选两个席位）→ 输入文本 → 提交 → 显示 `已排队（#n）`。用本地 state 管理选择，不用全局。
5. 发送按钮：调 `sendRoundtableAction({action: 'follow_up', text: chatDraft})`（无目标的通用插话），成功后清空 `chatDraft`，顶部 toast "已收到，将在下一阶段边界应用"。
6. 发言流：在 `claims / objections` 之外，插入 `pendingMessages`（`role=user`，显示"待应用"徽标）和已消费的用户消息（B-3 提供 `consumed_at / applied_to`）。
7. 推进讨论后（`App.tsx` 的 `handleAdvanceDiscussion` 成功回调）重新拉 `discussion`，被点名角色的新 `claims` 自然出现在流里。
8. `ui_smoke.mjs` 加用例：用假后端（现有 `ui_smoke` 的 mock 方式）让 `fetch` 返回 202，点"点名发言"→选席位→输入→提交，断言出现"已排队"。
9. `npm run build && npm run lint && npm run test`。

**细节红线**

- **不设任何审批按钮**：没有"同意/批准/驳回"，只有点名/追问/举证/辩论/插话。
- 用户不响应不影响流程：发送后**不等待回应**，UI 不进入 loading 阻塞态。
- 不改 `TaskGraph.tsx`、`ObservationView.tsx`（C/E 的）。
- 提交失败（404/409）显示错误并保留输入，不清空。

**验收**：build/lint 0 警告/test 全绿；ui_smoke PASS（含新用例）；与 A-5 真联调：点名"质疑者"→推进一阶段→发言流出现质疑者新观点。

**涉及文件**：`frontend/src/api/workbenchApi.ts`、`frontend/src/components/RoundTableView.tsx`、`frontend/src/App.tsx`、`frontend/tests/ui_smoke.mjs`

---

### F-2 CAS 冲突的 UI 呈现（6h，第 2 周末）

**目标**：C-2 返回 409 时，用户看到"计划已更新到 v4"，并选择"在 v4 上重做"或"放弃"。

**前置**：C-2 的 409 响应体形状已定；C-1 的 `TaskGraph.tsx` 连线/编辑已能触发 PATCH。

**步骤**

1. `git switch -c task/f-2-conflict-ui feat/p3-roundtable`
2. `taskRunApi.ts` 的 `patchPlan` 捕获 409，解析 `error.code === "REVISION_CONFLICT"`，抛出带 `current_revision` 的类型化错误（C-1 若已写 `patchPlan`，只加错误解析，不改其他）。
3. 新组件 `PlanConflictDialog.tsx`：模态显示"计划已更新到 v{current_revision}，你的编辑基于 v{expected}。"，两个按钮：**基于最新版本重做**（关闭弹窗、触发 `refreshPlan`、保留用户未提交的表单内容供重新应用）/ **放弃我的修改**。
4. `TaskGraph.tsx` 的连线失败处（C-1 预留了 `alert`）替换为打开该弹窗——**这一处改 C 的文件，先在群里说，或在 PR 里让 C review**。
5. `ui_smoke.mjs`：mock `PATCH` 返回 409 → 断言弹窗文案含"v4"。
6. 用 `App.css` 现有 token 写弹窗样式（新类 `modal-*`），不新增 hex。

**验收**：ui_smoke PASS；与 C 真联调：两个标签页同时编辑，后提交者看到弹窗。

**涉及文件**：`frontend/src/api/taskRunApi.ts`、`frontend/src/components/PlanConflictDialog.tsx`（新）、`frontend/src/components/TaskGraph.tsx`（仅弹窗调用一行）、`frontend/src/App.css`（modal-*）、`frontend/tests/ui_smoke.mjs`

---

### F-3 统一可视化框架收尾（10h，第 4 周）

**目标**：把本轮建立的 token 体系写成规范；清掉散落的硬编码色值，后续五个人改前端有据可依。

**前置**：F-1/F-2/E-3/C-4 的前端改动都已合入（否则清理会和它们冲突）；读 `REFERENCE_PROJECTS_3WAY.md` 2.2（SE-lib 的 DESIGN_SYSTEM 文档组织）。

**步骤**

1. `git switch -c task/f-3-ui-guidelines feat/p3-unified-ui`
2. 新建 `docs/UI_GUIDELINES.md`：
   - 色彩 token 表（`--primary / --success / --warning / --danger / --purple / --info` + 各 bg/border）与使用场景；
   - 间距与圆角（`--radius-sm / --radius / --radius-lg`）；
   - 组件用法：`.card / .badge（六种语义）/ .btn（primary/ghost/danger/sm）/ .placeholder + .todo / .table-wrap / .kv / .metric / .stance（四态）`——每项附一段"用在哪、不用在哪"；
   - **反例**：不用内联 `style={{color:'#...'}}`、不在组件里新造语义色、占位块必须带 `.todo` 徽标；
   - 分组侧栏的页面定义在 `constants/stages.ts`，改页面先登记。
3. 清理 `App.css` 中 `:root` 之外的 40 处 hex：能映射到现有 token 的替换为 `var(--…)`；真正一次性的（如 `.obs-span` 三色）抽成 `--obs-discussion / --obs-orchestration / --obs-observe` 三个 token。
4. 清理组件内联色 10 处：`TaskNode.tsx` 6 处改为 CSS 类（`.task-node-*`），**这是 C 的地盘——与 C 约一个时间窗**；`RoundTableView.tsx` 3 处（`SEATS[].color` 是数据驱动的席位色，保留但抽为 token `--seat-pm/ux/arch/critic`）；`TaskGraph.tsx` 1 处（MiniMap 背景）。
5. `ui_layout.mjs` 加一条断言：`document.querySelectorAll('[style*="#"]')` 在主页面为 0（允许 `SEATS` 数据色通过 CSS 变量注入）。
6. **纯样式/文档 PR，不混任何功能改动**。

**验收**：`grep -c '#[0-9a-f]\{3,6\}' frontend/src/App.css` 只剩 `:root` 与新增 token 行；`UI_GUIDELINES.md` 被主文档 §0.3 链接；ui_layout PASS。

**涉及文件**：`docs/UI_GUIDELINES.md`（新）、`frontend/src/App.css`、`frontend/src/components/TaskNode.tsx`（与 C 约定）、`frontend/src/components/RoundTableView.tsx`、`frontend/src/components/TaskGraph.tsx`（仅 MiniMap 行）、`frontend/tests/ui_layout.mjs`

---

### F-4 性能与可达性基准（10h，第 2 周末出数据）

**目标**：把"100 任务大图可交互 < 2s、对比度 ≥ 4.5、键盘可达"写成测试断言，并输出 `work/ui-perf.json` 给 E-4 引用。

**前置**：读 `REFERENCE_PROJECTS_3WAY.md` 2.2（SE-lib 的 `performance.test.mjs` 做法：CDP + `requestAnimationFrame` 帧计数 + 计算样式对比度）。本项目的 `ui_layout.mjs` 已有 CDP 框架，直接扩展。

**步骤**

1. `git switch -c task/f-4-perf-a11y feat/p3-unified-ui`
2. **大图 fixture**：`workflow_runtime/make_frontend_fixture.py` 现在生成 24 任务；加参数 `--scale 4` 复制任务到 ~100 个（依赖关系按拓扑复制，保证无环），输出到 `frontend/src/data/taskRunFixtureLarge.json`（新文件，**不改原 fixture**）；`simulationRuns.ts` 加一个 key `large`。
3. `ui_perf.mjs`（新，复用 `ui_layout.mjs` 的 CDP 连接）：
   - **首屏可交互**：导航到编排页、选 `large`、`performance.now()` 计时至 `.react-flow__node` 数量 ≥ 100 且主线程空闲（`requestAnimationFrame` 两帧），断言 < 2000ms；
   - **拖动帧率**：对节点 `mousePressed → mouseMoved ×60 → mouseReleased`，用 rAF 计数算 fps，断言 ≥ 30；
   - **对比度**：对 `.badge / .btn / .stat-value / td / th` 取 `color` 与背景色（含父级）算 WCAG 对比度，断言 ≥ 4.5（`.badge.sim` 的 `#92400e on #fff4dc` 等逐个核）；
   - **键盘可达**：Tab 遍历，断言可见焦点元素 ≥ 5 且都有可访问名（`aria-label / textContent`）；
   - 结果写 `work/ui-perf.json`，格式 `{q04: {...}, q08: {...}, status}`。
4. `package.json` 加 `"test:perf": "node tests/ui_perf.mjs"`；不进 `npm test`（需要浏览器），README 说明手动跑。
5. 跑一次，把结果贴给 E（E-4 引用）。

**细节红线**：阈值与 SE-lib 一致（2000ms / 30fps / 4.5），但 fixture 是我们自己的；测试在本机跑，结果只代表本机（报告里要写明）。

**验收**：`node tests/ui_perf.mjs` PASS 并产出 json；`npm test` 不受影响。

**涉及文件**：`workflow_runtime/make_frontend_fixture.py`（加 `--scale`）、`frontend/src/data/taskRunFixtureLarge.json`（新）、`frontend/src/data/simulationRuns.ts`、`frontend/tests/ui_perf.mjs`（新）、`frontend/package.json`

---

### F-5 交付页预览按钮（2h，第 2 周末）

**目标**：交付页有"打开预览"按钮，指向 D-2 的 `/preview/<run_id>/`。

**步骤**

1. `git switch -c task/f-5-preview-button feat/p3-roundtable`
2. `taskRunApi.ts` 的运行快照类型加 `deliverable_url?: string`（D-2 提供）。
3. `App.tsx` 交付页头部 `page-head-actions` 加 `<a className="btn" href={deliverable_url} target="_blank">打开预览 ↗</a>`，无 `deliverable_url` 时不渲染（**不显示禁用按钮**，避免误导）。
4. `ui_smoke.mjs`：mock 运行快照含 `deliverable_url` 时断言按钮存在。

**验收**：真实运行后按钮可点、新标签打开预览。

**涉及文件**：`frontend/src/api/taskRunApi.ts`、`frontend/src/App.tsx`、`frontend/tests/ui_smoke.mjs`

---

### F-6 分支治理：评审旧分支（2h，第 1 周）

评审 **`feat/b05-frontend-viz`** 与 **`feat/b02-discussion-controller`**（均未并入 main，核实过差异）：

| 分支 | 差异（核实） | 评审重点 |
|---|---|---|
| `feat/b05-frontend-viz` | 3 commit，+4372 行，31 文件：`utils/export.ts`、tsconfig、vite.config 等 | 现有 `export.ts` 已有六种导出；看该分支是否有 main 没有的导出格式或 tsconfig 配置值得 cherry-pick |
| `feat/b02-discussion-controller` | 2 commit，+2397 行：`static/styles.css`、`browser_smoke.mjs`、`test_controller.py`、`test_websocket.py`、`PROJECT_OVERVIEW.md` | 现有 B02 已有 113 测试与 `tests/browser_smoke.mjs`；重点看它的 `browser_smoke.mjs`（231 行）是否比现有 `frontend/tests/ui_smoke.mjs` 多覆盖了讨论流程的断言 |

有价值的 → `task/f-6-cherry-pick-xxx` 并 PR；没有的 → 群里写一行放弃理由。结论写进主文档 2.1 表。

---

## 四、你的每周节奏

| 周 | 本周交付 | 周五前合入 |
|---|---|---|
| 1 | F-6 评审；读 A-5 接口约定并一起写进文档 | — |
| 2 | **F-4 基准出数据**（给 E）、F-2 冲突弹窗、F-5 预览按钮 | `feat/p3-unified-ui`、`feat/p3-roundtable` → `integration` |
| 3 | F-1 圆桌前端、与 A 联调 | `feat/p3-roundtable` → `integration` |
| 4 | F-3 规范与硬编码清理（等所有前端 PR 合入后） | `feat/p3-unified-ui` → `integration` |

**每次开工**：主文档 0.1 五步。**每日**：和 B 对"`RoundTableView.tsx` 今天谁动哪几行"。**每周中**：功能分支 `rebase origin/main`。

## 五、你的验收命令速查

```powershell
cd frontend
npm run build; npm run lint; npm run test          # 0 警告 / 20 通过
node tests/ui_smoke.mjs http://127.0.0.1:7100     # 需先启动 B02
node tests/ui_layout.mjs http://127.0.0.1:7100    # LAYOUT: PASS
node tests/ui_perf.mjs  http://127.0.0.1:7100     # F-4 后可用，产出 work/ui_perf.json
```
