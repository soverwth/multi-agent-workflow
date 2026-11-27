# 成员 C 分工 · 计划数据模型、契约 Schema 与任务图语义

> 组别：组 2（阶段二）。本文是 `docs/TEAM_DIVISION.md` 的个人子文档，只含你的任务。
> 开工前先读主文档第〇节（开工五步 + 深读清单），再读本文。
> 本文中所有"现状"均已在 main `01f88cd` 上核实到行号。

---

## 一、你的分支

| 分支 | 用途 | 从哪切 | 何时合入 |
|---|---|---|---|
| `feat/p2-plan-editing` | C-1 编辑回写、C-2 CAS、C-5 增量分解 | `integration` | 第 2 周末（C-1/C-2）、第 4 周（C-5） |
| `feat/p2-contract-schema` | C-3 契约 Schema、C-4 图节点语义 | `integration` | 第 1 周末（C-3，赶在 0-3 冻结会前出初稿）、第 3 周（C-4） |
| `task/c-<编号>-<短名>` | 每张卡一个任务分支 | 对应功能分支 | PR 合回后删除 |

**两条分支的关系**：`contract-schema` 是**定义层**（计划文档长什么样），`plan-editing` 是**操作层**（怎么改计划）。C-4 的图语义会改计划文档字段，所以 C-4 要在 C-1 的编辑接口稳定后再开，否则编辑接口要返工。

**你与别人的联调对象**

| 对方 | 联调什么 | 什么时候 |
|---|---|---|
| B | B-2 的 `canonical_hash` 放 `workflow_runtime/canonical.py`，你的 `input_hash` 直接复用；B 把 `phase1_source` 改名为 `baseline` 时，你改 `task_api.py:166,195` 的读取 | 第 2 周初 30 分钟 |
| D | D-2 要在 `app.py` 加 `/preview/<run_id>/` 静态路由，你在 `app.py` 加 `PATCH` 路由——**路由分发段（`_task_post` 附近）两人同改**，先在群里说谁先合 | 第 2 周 |
| F | C-2 的 409 响应体形状 `{error: {code: "REVISION_CONFLICT", current_revision: 4}}`，F-2 据此做弹窗 | 第 2 周中 |
| E | 0-3 冻结会：你的计划 Schema 与 E 的观测 Schema 对齐 `plan_version / input_snapshot` 字段名 | 第 1 周中 |

---

## 二、你负责的代码地图

| 文件 | 现状（核实过） | 你要动的 |
|---|---|---|
| `backend/task_api.py` | `TaskApi.load_plan / list_plans / get_plan / create_run / create_run_from_spec(:133) / step / run / events / dag / replay / restore`。**没有 PATCH、没有 CAS**。`create_run_from_spec` 已有"同规格复用版本、规格变化递增版本"逻辑（:167-184） | C-1 加 PATCH；C-2 加 expected_revision |
| `backend/app.py` | `_task_post`（:237）分发 `/api/task-plans/*` 与 `/api/task-runs/*`；**没有 `_task_patch`** | C-1/C-2 加 `do_PATCH` |
| `b03/b03_implementation/task_state.py` | `register_plan(plan_id, document)`（:189）：**已有 VersionConflict 保护**（同 plan_id 内容不同 → 拒绝）；`find_plan_by_version`（:232） | 不改本体；C-2 若需按 `plan_id` 存多版本，与 B/A 协商新增方法 |
| `b01-spec-planner/src/b01/dynamic_planner.py` | `canonical_hash(value) -> str`（已有，B-2 可能搬到 `workflow_runtime/`）；`build_plan_from_spec`、`next_plan_version`、`build_traceability`、`_design_tasks / _contract_tasks / _requirement_tasks / _integration_and_delivery` | C-4 改生成逻辑加 `node_type/edge_type` |
| `b01-spec-planner/src/b01/plan_validator.py` | `validate_plan(plan)`（:117）：已检查 `input_snapshot` 为对象且 `spec_version/contract_version` 一致（:152-163） | C-2 补 `spec_sha256` 必填；C-4 加节点类型校验 |
| `b02-workflow-agent/backend/task_orchestrator.py` | `load_plan`（:195）调 `validate_plan`；`_transition / _refresh_dependencies / ready_tasks / dispatch / step / run / replay` | C-4 的 `decision/join/checkpoint` 节点在这里被"识别但不派发" |
| `workflow_runtime/verify_contracts.py` | 6 个检查段（success/failure/evidence/stale 等） | C-2/C-3 加检查项 |
| `docs/TASK_ORCHESTRATION.md` | §2 plan 文档、§3 API、§3.2 事件、§3.3 DAG | C-3/C-4 更新 |
| `frontend/src/components/TaskGraph.tsx` | **57 行，`useEffect` 每次 `layoutedNodes` 变化就 `setNodes(...)`**——用户拖动会被覆盖 | C-1 改布局持久化 |
| `frontend/src/layout/dagreLayout.ts` | `layoutTasks(tasks)` | C-4 按 node_type 布局 |

---

## 三、任务卡

### C-3 契约单一来源：JSON Schema + 一致性校验（10h，第 1 周，赶 0-3 冻结会）

**目标**：`TASK_ORCHESTRATION.md` 里的字段定义变成机器可读 Schema，代码常量与 Schema 自动比对，杜绝"B04 哈希正则与 B06 不一致"这类跨块漂移。

**为什么先做 C-3 而不是 C-1**：0-3 冻结会需要你的 Schema 初稿；且 C-1/C-2 的请求/响应体都要按 Schema 定义。

**前置**：读 `TASK_ORCHESTRATION.md` §0—§3 全文；读 `REFERENCE_PROJECTS_3WAY.md` 2.2（SE-lib 的 `flowstudio_contracts` 做法）。

**步骤**

1. `git switch -c task/c-3-contract-schema feat/p2-contract-schema`
2. 新建 `docs/contracts/` 目录，从 `TASK_ORCHESTRATION.md` 抽出：
   - `task-plan.schema.json`：`plan_id / plan_version / project_id / spec_version / contract_version / input_snapshot{spec_sha256, spec_version, contract_version} / tasks[] / topological_order / traceability`
   - `task.schema.json`：§1 的任务字段（`task_id / goal / depends_on / block_id / role_id / capability / priority / write_scope / outputs / evidence / acceptance / required_test_ids / retry_budget ...`）
   - `task-status.schema.json`：九态枚举 + `statusLabels`
   - `task-event.schema.json`：§3.2 的 12 种事件类型 + 必带字段
   - `api-error.schema.json`：`{error: {code, message, details?}}` 与 HTTP 状态码表（400/404/409/422）
3. `workflow_runtime/check_schemas.py`（新）：
   - 用 Python 读 Schema（`jsonschema` 未安装则手写最小校验：只比对枚举与正则），断言 `task_orchestrator.STATUS_*` 常量 == Schema `enum`；`b04/gateway.py` 与 `b06/task_gate.py` 的 `SHA256_PATTERN` == Schema `pattern`；`frontend/src/constants/status.ts` 的 `ALL_STATUSES` == Schema `enum`（读 TS 文件用正则抓数组）。
   - 接入 `verify_contracts.py` 作为一个新 check 段 `verify_schema_consistency(root)`。
4. `TASK_ORCHESTRATION.md` 顶部加一段"机器可读定义见 `docs/contracts/`，改字段先改 Schema 再改文档"。
5. 测试：`workflow_runtime/test_schema_consistency.py`（或并入 `test_closed_loop.py`）——人为把一个枚举改错，断言检查能抓到。

**红线**：Schema 是**冻结物**——改它必须同时通知 §0.3 登记的消费方；CI 只跑 `check_schemas.py`，不引入 `jsonschema` 等新依赖。

**验收**：`python workflow_runtime/verify_contracts.py` 从 6/6 变 7/7；0-3 冻结会上用 `docs/contracts/` 作为讨论底稿。

**涉及文件**：`docs/contracts/*.schema.json`（新）、`workflow_runtime/check_schemas.py`（新）、`workflow_runtime/verify_contracts.py`、`docs/TASK_ORCHESTRATION.md`

---

### C-1 节点编辑与回写（16h，第 2 周）

**目标**：用户能增删任务、改依赖、改验收条件，后端生成新计划版本，旧运行不受影响；前端拖动位置不再被刷新覆盖。

**前置**：C-3 合入（PATCH 请求体按 Schema 定义）；与 D 约好 `app.py` 路由段谁先合。

**后端步骤**

1. `git switch -c task/c-1-plan-edit feat/p2-plan-editing`
2. `app.py` 加 `do_PATCH` → `_task_patch(path, payload)`，路由：`PATCH /api/task-plans/{plan_id}`，body：
   ```json
   { "expected_revision": 3,
     "tasks": [ ... 完整任务列表 ... ],
     "reason": "用户调整依赖" }
   ```
   **整份提交**（不按 task_id 单改，避免半更新）。
3. `task_api.edit_plan(plan_id, payload)`：
   - 取当前文档；`expected_revision` 不等于当前版本号 → 409（C-2 实装前先返回 `{error: {code: "REVISION_CONFLICT", current_revision}}`）；
   - 对 tasks 跑 `plan_validator.validate_plan`（依赖存在 / 无环 / 需求全覆盖 / 产物唯一）+ `task_gate` 的计划校验，失败返回 422 与 findings；
   - 通过 → `next_plan_version(old.plan_version, project_id)` 生成新版本，**新 plan_id**（`f"{project}-{new_version}"`），`register_plan`；旧 plan 原样保留；
   - 返回 `{plan: 新版本摘要, previous_plan_id, revision}`。
4. 测试 `test_task_api.py` 新增：`test_patch_creates_new_plan_version`、`test_patch_invalid_dependency_rejected`、`test_patch_cycle_rejected`、`test_running_run_unaffected_by_patch`（先建运行、PATCH、断言运行仍绑旧 plan_version）。

**前端步骤（布局与数据分离）**

5. `TaskGraph.tsx`：
   - `useEffect` 改为：只在 `tasks` 的 **id 集合**变化时重新布局；位置用 `localStorage["dag-layout:{run_id}"]` 持久化，`onNodesChange` 里 position 变化就写回；
   - 加 `onConnect`：连线 → 调 `PATCH`（`depends_on` 增加），断线同理；连到自身或成环 → 后端 422 → 用 F-2 的冲突组件提示（F 没就绪前 `alert`）；
   - 加"删除任务""新增任务"入口（工具栏按钮 + 简单表单：goal / depends_on / acceptance）。
6. `taskRunApi.ts` 加 `patchPlan(baseUrl, planId, body)`。

**红线**：**绝不原地改已派发的计划**（任务文档 2.4.6）；旧运行绑定旧版本是正确行为，不是 bug。

**验收**：B02 单测 ≥ 117；真实接口下 PATCH 后 `GET /api/task-plans` 出现两个版本，旧运行 `plan_version` 不变；刷新页面节点位置不丢；`ui_smoke` 新增"拖动后刷新位置保留"断言。

**涉及文件**：`backend/app.py`、`backend/task_api.py`、`tests/test_task_api.py`、`frontend/src/components/TaskGraph.tsx`、`frontend/src/api/taskRunApi.ts`

---

### C-2 计划 CAS + input_hash 强校验（6h，第 2 周）

**目标**：两个人同时编辑计划，后提交者得到明确的 409 与当前版本号；每个计划版本带规范化 `input_hash`，运行创建时校验。

**前置**：B-2 的 `workflow_runtime/canonical.py` 已就绪（没就绪先用 B01 的 `dynamic_planner.canonical_hash`）；C-1 的 PATCH 已有 `expected_revision` 骨架。

**步骤**

1. `git switch -c task/c-2-plan-cas feat/p2-plan-editing`
2. 计划文档加字段 `revision: int`（从 1 起）与 `input_hash: str`（= `canonical_hash({tasks, spec_version, contract_version})`，**不含** plan_id / 时间戳）。`register_plan` 时计算并写入。
3. `task_api.edit_plan`：比较 `payload.expected_revision` 与当前 `revision`，不等 → `409 {"error": {"code": "REVISION_CONFLICT", "message": "计划已更新到 v4", "current_revision": 4}}`。**通知 F 这个形状**。
4. `task_orchestrator.create_run`：读 plan 的 `input_hash` 重算一次，不一致 → 拒绝创建（防止文档被绕过 API 改了）。关闭 STAGE2_STATUS 遗留 5：`validate_plan` 已要求 `input_snapshot` 是对象（:152），再补 `spec_sha256` 必须匹配 `^[0-9a-f]{64}$`。
5. `verify_contracts.py` 加 `verify_plan_cas`：两次相同 PATCH 请求，第二次应 409。
6. 测试：`test_concurrent_edit_second_writer_gets_409`、`test_input_hash_rejects_tampered_plan`、`test_same_content_same_hash`。

**验收**：上述测试全绿；`verify_contracts.py` 8/8；与 F-2 联调 409 弹窗显示"计划已更新到 v4"。

**涉及文件**：`backend/task_api.py`、`backend/task_orchestrator.py`、`b01-spec-planner/src/b01/plan_validator.py`、`b03/b03_implementation/task_state.py`（若需存 revision，与 A/B 协商加列）、`workflow_runtime/verify_contracts.py`、`tests/test_task_api.py`

---

### C-4 任务图节点语义：decision / checkpoint / join + pass/fail/loop（12h，第 3 周）

**目标**：任务图能表达"验收失败走修复分支""阶段边界有可恢复锚点""并行分支汇合"，而不是只有 task + dep。

**前置**：C-3 Schema 合入；C-1 PATCH 接口稳定；读 `REFERENCE_PROJECTS_3WAY.md` 2.3（TeamPrjoect 的 Twin-Graph 节点类型）。

**字段定义（先加进 Schema）**

```json
"tasks": [{
  "task_id": "T07", "node_type": "task",            // task(默认) | decision | checkpoint | join
  "edge_type": "dep",                                 // dep(默认) | pass | fail | loop
  "depends_on": ["T06"],
  "route": {"on": "T06.status", "pass": ["T08"], "fail": ["T09-fix"]}   // 仅 decision
}]
```

**步骤**

1. `git switch -c task/c-4-graph-semantics feat/p2-contract-schema`
2. Schema 加字段（可选、有默认值——**向下兼容**，旧计划不变）。
3. `dynamic_planner.py`：`_requirement_tasks` 为每条带"失败可修复"验收条件的需求生成 `decision` 节点 + `fail` 边指向一个 `-fix` 任务（`loop` 回原任务）；`_integration_and_delivery` 在每个阶段末尾插 `checkpoint` 节点（`title: "阶段 N 检查点"`）；并行分支后插 `join`。
4. `plan_validator.py`：decision 必须有 `route.pass` 与 `route.fail`；checkpoint/join 无 `write_scope`；loop 边必须指向上游且不与重试预算冲突。
5. `task_orchestrator.py`：
   - `decision`：上游完成时读 `route.on` 的状态，只放行对应分支；`_transition` 前查 `node_type`；
   - `checkpoint`：到达时调 `task_state.write_run_checkpoint`（已有 :558），节点状态直接 `SUCCEEDED`，**不派发**；
   - `join`：所有入边上游 `SUCCEEDED` 才放行，否则 `WAITING_DEPENDENCY`；
   - 这三类节点**不产生 `TASK_DISPATCHED/STARTED` 事件**，只产生状态事件（否则回放会与快照不一致）。
6. 前端 `TaskNode.tsx`：按 `node_type` 渲染（decision 菱形、checkpoint 锚点图标、join 汇合条），`dagreLayout.ts` 对 decision 分叉布局。**与 F 说好你只改 `TaskNode.tsx` 与 `dagreLayout.ts`**。
7. 测试：`test_decision_routes_fail_to_fix_task`、`test_checkpoint_writes_checkpoint_without_dispatch`、`test_join_waits_all_branches`、`test_legacy_plan_without_node_type_still_valid`。

**红线**：**九态状态机一个字不改**，这是叠加在它上面的图语义层；旧计划（无 `node_type`）必须照常运行。

**验收**：B01 44 → ≥48；B02 ≥ 121；`pipeline --scenario evidence` 走 fail 分支到 fix 任务（新增场景或扩展现有）；`ui_smoke` DAG 出现菱形节点。

**涉及文件**：`docs/contracts/task.schema.json`、`b01/dynamic_planner.py`、`b01/plan_validator.py`、`backend/task_orchestrator.py`、`frontend/src/components/TaskNode.tsx`、`frontend/src/layout/dagreLayout.ts`、各块 tests

---

### C-5 增量分解 / 重新分解（8h，第 4 周）

**目标**：基线改了，只重导出受影响需求对应的任务，未受影响任务保留编号。

**前置**：B-2 的 `baseline.revision/parent` 已有；C-1/C-4 合入。

**步骤**

1. `git switch -c task/c-5-rederive feat/p2-plan-editing`
2. `POST /api/task-plans/{plan_id}/rederive`，body `{baseline: {...新基线...}}`。
3. 比对新旧 `requirements`（按 `req_id`）：新增/修改的需求 → 其 `design_entries` 对应任务重导出；删除的需求 → 对应任务标 `removed: true`（不物理删，保追溯）；未变需求 → 任务原样保留 `task_id`。
4. 产出新 plan_version，`traceability` 同步更新；`input_hash` 用新基线算。
5. 测试：`test_rederive_keeps_untouched_task_ids`、`test_rederive_marks_removed_requirements`。

**验收**：单测全绿；用 B-5 的 C2 规格改一条需求后 rederive，断言只有对应任务编号变化。

**涉及文件**：`backend/task_api.py`、`backend/app.py`、`b01/dynamic_planner.py`、`tests/test_task_api.py`

---

### C-6 分支治理：评审旧分支（2h，第 1 周）

评审 **`b01-spec-planner`** 与 **`feature/b03-blackboard`** 两个未并入 main 的远端分支：

```powershell
git log origin/main..origin/b01-spec-planner --oneline
git log origin/main..origin/feature/b03-blackboard --oneline
git diff origin/main...origin/b01-spec-planner --stat
```

对每个 commit 判断：main 是否已有等价实现（看 `STAGE2_STATUS.md` 已完成表）。有价值的 → 开 `task/c-6-cherry-pick-xxx` 分支 cherry-pick 并 PR；没有的 → 在群里写一行"放弃理由：xxx"。两个分支的结论写进主文档 2.1 表的"处理"列。

---

## 四、你的每周节奏

| 周 | 本周交付 | 周五前合入 |
|---|---|---|
| 1 | **C-3 Schema**（0-3 冻结会前出初稿）、C-6 评审 | `feat/p2-contract-schema` → `integration` |
| 2 | C-1 编辑回写、C-2 CAS | `feat/p2-plan-editing` → `integration` |
| 3 | C-4 图语义 | `feat/p2-contract-schema` → `integration` |
| 4 | C-5 增量分解 | `feat/p2-plan-editing` → `integration` |

**每次开工**：主文档 0.1 五步。**每日**：和 D 对"今天动 `app.py` 哪几行"。**每周中**：两条功能分支各 `rebase origin/main` 一次。

## 五、你的验收命令速查

```powershell
cd b02-workflow-agent; python -m unittest discover -s tests   # 基线 113 → ≥121
cd b01-spec-planner; python -m pytest -q                      # 基线 44 → ≥48
cd b03/b03_implementation; python -m pytest -q                # 基线 46（不该变，变了说明你动了 task_state）
cd ..\..\..; python workflow_runtime/verify_contracts.py      # 6/6 → 8/8
python workflow_runtime/run_all_checks.py                     # 15/15 → 17/17
cd frontend; npm run build; npm run lint; npm run test        # 0 警告 / 20 通过
```
