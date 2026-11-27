# 成员 E 分工 · 观测数据 Schema、埋点落地与验收证据

> 组别：组 3（阶段三）。本文是 `docs/TEAM_DIVISION.md` 的个人子文档，只含你的任务。
> 开工前先读主文档第〇节（开工五步 + 深读清单），再读本文。
> 本文中所有"现状"均已在 main `01f88cd` 上核实到行号。

---

## 一、你的分支

| 分支 | 用途 | 从哪切 | 何时合入 |
|---|---|---|---|
| `feat/p3-observation` | E-1 Schema、E-2 埋点、E-3 观测页真实化 | `integration` | **第 1 周中（E-1，全组阻塞项）**、第 2 周末（E-2）、第 3 周末（E-3） |
| `feat/p3-acceptance` | E-4 三类验收报告、E-5 签名证据链、E-7 案例台账 | `integration` | 第 3 周（E-4/E-5）、持续（E-7） |
| `task/e-<编号>-<短名>` | 每张卡一个任务分支 | 对应功能分支 | PR 合回后删除 |

**你的核心命题**：让"这个过程发生过什么"变成**可查询、可追溯、可验证**的数据——而不是散在日志里的文字。E-1 是全组的硬依赖（B-4 埋点、E-2、E-3 全等它），**第 1 周必须冻结**。

**你与别人的联调对象**

| 对方 | 联调什么 | 什么时候 |
|---|---|---|
| B | B-4 在 `llm.py` 埋 `model_call`，严格按你 E-1 定稿的字段；你提供落库函数 `record_model_call(...)` | 第 1 周中定稿 → 第 3 周 B 实装 |
| A | A-3 的用户消息消费点要同步写观测记录；你在 `conversation.py` 消费处留钩子（或 A 调你的 `record(...)`） | 第 2 周 |
| D | E-5 要把 D-1 真实 runner 的测试结果接进 B06 `check_evidence`；D 的 runner 返回体要有 `evidence` 字段（D-1 已约定先为空） | 第 3 周 |
| F | E-3 观测页是 F 的地盘之外的组件，但样式 token 与 F-3 对齐 | 第 3 周 |
| C | 0-3 冻结会：你的观测 Schema 与 C-3 的计划 Schema 对齐 `plan_version / input_snapshot / attempt_id` 字段名 | 第 1 周中（你主持） |

---

## 二、你负责的代码地图

| 文件 | 现状（核实过） | 你要动的 |
|---|---|---|
| （无）`docs/OBSERVATION.md`、`docs/contracts/observation.schema.json` | **不存在**。任务文档 2.5.2 已定义五要素与模型调用字段 | E-1 新建 |
| `b03/b03_implementation/task_state.py` | `TaskStateStore`：`_connect / _tx`（`BEGIN IMMEDIATE` 事务，:79-98）、`append_run_event`（:477）、`list_run_events`（:536）、`get_run_view`（:626）。**没有观测表、没有模型调用表** | E-2 新增 `observation.py`（照抄其连接与事务风格，不改本体） |
| `b02-workflow-agent/backend/llm.py` | `OpenAICompatibleClient.complete_json(*, system, user) -> dict`（:91） | **不改**（B-4 在此埋点）；你只提供落库函数 |
| `b06-quality-consensus/multiagent_quality/evidence.py` | `sign_report(report, key)`、`sha256_file`、`check_evidence(envelope, *, key, expected_context, required_test_ids, artifact_root, required_artifacts, now, max_age_seconds)`——HMAC-SHA256 校验、schema_version=1、context 必须与 expected 一致 | E-5 调用方接线（不改它） |
| `b06-quality-consensus/multiagent_quality/runner.py` | `run_suite(suite, *, context, root, key)`、`run_case(command, *, cwd, log_file, timeout_seconds, ...)` 受控执行 | E-5 调用 |
| `b06-quality-consensus/multiagent_quality/task_gate.py` | `review_task(...)`（:367）九项必查 | E-5 可能加 `evidence_verified` 检查项（与 D 协商） |
| `frontend/src/components/ObservationView.tsx` | props 只有 `{source, tasks, eventCount}`；时间轴/工件表/回溯全是占位 | E-3 接真实接口 |
| `frontend/src/hooks/useTaskRun.ts` | 返回 `{tasks, events, eventCursor, replayResult, connection, ...}` | E-3 可能加 `observations` 字段或新 hook |
| `docs/` | 无 `testing/` 目录、无 REAL 报告 | E-4 新建 |
| `workflow_runtime/run_all_checks.py` | 15 步 | E-4 把输出引用进 P0 报告 |

---

## 三、任务卡

### E-1 观测数据 Schema 定稿（10h，第 1 周中，硬门禁）

**目标**：定义"执行过程中哪些数据要记录"，含**模型调用作为一等主体**；写成 JSON Schema 并冻结，B-4/E-2/E-3 按它开发。

**前置**：读任务文档 2.5.2（五要素）与 2.5.4（三级回溯）；读 `REFERENCE_PROJECTS_3WAY.md` 2.3（TeamPrjoect"每次模型调用即工件"）；读 C-3 的 `docs/contracts/` 风格保持一致。

**产出物**

1. `docs/OBSERVATION.md`：
   - 五要素定义表（主体 / 类型 / 时间 / 上下文 / 载荷）；
   - **主体枚举**：`run | stage | task | agent | model_call`；
   - **类型枚举**：`state_change | input | output | error | metric`；
   - 上下文必带：`run_id, plan_version?, input_snapshot?, attempt_id?, baseline_sha256?`；
   - 查询接口约定（见 E-2）。
2. `docs/contracts/observation.schema.json`：
   ```json
   {
     "observation": {
       "obs_id": "string", "run_id": "string", "subject_type": "run|stage|task|agent|model_call",
       "subject_id": "string", "obs_type": "state_change|input|output|error|metric",
       "occurred_at": "iso8601", "stage": "string?",
       "context": {"plan_version": "string?", "input_snapshot": "string?", "attempt_id": "int?", "baseline_sha256": "string?"},
       "payload": {}
     },
     "model_call": {
       "call_id": "string", "run_id": "string", "attempt_id": "int?", "node_id": "string",
       "role": "string", "provider": "string", "model": "string",
       "input_hash": "sha256", "output_hash": "sha256?",
       "usage": {"input_tokens": "int", "output_tokens": "int"} | null,
       "latency_ms": "int>=0",
       "status": "success | budget_exhausted | needs_input | failed",
       "error_code": "string?"
     }
   }
   ```
3. `docs/TASK_ORCHESTRATION.md` 加 §9「观测接口」：
   ```text
   GET /api/task-runs/{id}/observations?subject=task&after=<seq>&limit=
   GET /api/task-runs/{id}/model-calls
   GET /api/runs/{id}/observations            （讨论侧）
   ```

**步骤**

1. `git switch -c task/e-1-schema feat/p3-observation`
2. 先写文档与 Schema（半天），**不写代码**。
3. 拉 B/C/D 开 **0-3 冻结会**（2h）：逐字段过一遍；重点对齐 C-3 的 `plan_version / input_snapshot / attempt_id` 命名、B-2 的 `baseline_sha256`、D-1 的 `evidence` 结构。
4. 会后按纪要修订，PR 合入 `integration`，在群里发"Schema v1 已冻结，改动走小会"。

**细节红线**

- **讨论阶段事件与任务阶段事件进同一 schema**，靠 `subject_type` 区分（任务文档 2.5.2 过程要求 1）。
- 模型调用的 `input_hash / output_hash` 必须用 `workflow_runtime/canonical.py` 的同一函数（B-2 负责），Schema 里写明 `pattern: ^[0-9a-f]{64}$`。
- 任何字段名一旦冻结，改名 = 破坏性变更，必须走小会。

**验收**：Schema 被 C-3 的 `check_schemas.py` 校验通过（本身是合法 JSON Schema）；B/C/D 在 PR 下评论"已读无异议"。

**涉及文件**：`docs/OBSERVATION.md`（新）、`docs/contracts/observation.schema.json`（新）、`docs/TASK_ORCHESTRATION.md`

---

### E-2 埋点落地：观测表 + 模型调用表 + 查询接口（14h，第 2 周）

**目标**：讨论事件、任务事件、模型调用都落进 B03 的观测表，前端可通过 API 查到。

**前置**：E-1 冻结；读完 `task_state.py` 的 `_connect / _tx / append_run_event` 写法（新文件照抄，**不改 task_state.py 本体**——那是 C 的地盘）。

**步骤**

1. `git switch -c task/e-2-observation-store feat/p3-observation`
2. `b03/b03_implementation/observation.py`（新）：
   - `class ObservationStore(db_path)`，`initialize()` 建两表：`observations`、`model_calls`，字段按 Schema；
   - 方法：`record(obs: dict) -> obs`、`record_model_call(call: dict) -> call`、`list_observations(run_id, *, subject_type=None, after=0, limit=200)`、`list_model_calls(run_id, *, after=0, limit=200)`；
   - 用 `_tx()` 事务；`occurred_at` 由调用方给（不带时区的拒绝）。
3. `backend/app.py` 加三个 GET 路由（与 A/C 的路由段同文件，群里说一声）：`/api/task-runs/{id}/observations`、`/api/task-runs/{id}/model-calls`、`/api/runs/{id}/observations`。
4. **任务事件桥接**：`task_orchestrator._emit`（:248）已写 `task_run_events`——**不要重复写**。在 `_ingest_gate_events`（:577）或新建 `_emit_observation` 钩子里，对**关键节点**（RUN_CREATED / TASK_DISPATCHED / TASK_ACCEPTED / TASK_REJECTED / TASK_BLOCKED / RUN_COMPLETED）各写一条 `observation{subject_type: task, obs_type: state_change, payload: {event_seq}}`，payload 只引用 `event_seq` 不复制内容（红线：同一事实一条记录）。
5. **讨论事件桥接**：A-3 的消费点与 `controller._record`（:27）处——给 A 一个 `on_observation` 回调（`DiscussionController.__init__` 已有 `on_event` 钩子，:19！**复用它**，在 `app.py` 装配时把 `on_event` 接到 `observation.record`，不改 controller）。
6. **模型调用桥接**：提供 `record_model_call()`，B-4 在 `llm.py` 调它；本卡先用 `test_llm.py` 的假客户端写一条到表里验证链路。
7. 测试 `b03/tests/test_observation.py`：建表 / 写读 / `after` 游标 / `subject_type` 过滤 / 时区校验；`test_task_api.py` 加三条 GET 路由用例。

**细节红线**

- 不写两遍：任务事件本体仍在 `task_run_events`，观测表只放"观测视角"的引用与派生指标。
- 讨论侧的钩子走现有 `on_event`，**不改 `controller.py`**（A 的）。
- 表名/字段名严格等于 Schema；改动先改 Schema。

**验收**：B03 `pytest -q` 46 → ≥ 53；跑一次 mock 运行后 `GET /api/task-runs/{id}/observations` 返回 ≥ 6 条且 `payload.event_seq` 都能在 `task_run_events` 找到；`verify_contracts.py` 加 `verify_observations_exist` 通过。

**涉及文件**：`b03/b03_implementation/observation.py`（新）、`b03/tests/test_observation.py`（新）、`backend/app.py`、`backend/task_orchestrator.py`（仅加 `_emit_observation` 钩子）、`workflow_runtime/verify_contracts.py`、`tests/test_task_api.py`

---

### E-3 观测与回溯页真实化（14h，第 3 周）

**目标**：`ObservationView.tsx` 的占位全部换成真实数据：跨阶段时间轴、模型调用工件表、三级回溯。

**前置**：E-2 路由可用；B-4 已埋点（至少 mock 运行有 observation）；与 F 对齐"观测页只用现有 token，新增组件命名 `obs-*`"。

**步骤**

1. `git switch -c task/e-3-observation-page feat/p3-observation`
2. `workbenchApi.ts` 加 `listObservations(baseUrl, runId, {subject_type, after})`、`listModelCalls(baseUrl, runId)`。
3. 新 hook `useObservation(baseUrl, runId, enabled)`：轮询拉取（与 `useTaskRun` 同步频），返回 `{observations, modelCalls, loading, error}`。
4. `ObservationView.tsx` 改 props 为 `{source, runId, tasks, observations, modelCalls}`：
   - **指标卡**：观测事件 = `observations.length`；模型调用 = `modelCalls.length`（有 usage 时加总 token）；
   - **跨阶段时间轴**：对齐算法——以 `observations` 中最早的 `occurred_at` 为 t₀，按 `stage` 分组取首末时间投影到轨道；讨论侧（`/api/runs/{id}/observations`）与任务侧用同一组件渲染，`subject_type` 决定颜色（沿用现有 `.obs-span` 三色）；
   - **模型调用工件表**：遍 `modelCalls`，列 = 角色 / 节点 / `input_hash` 前 12 位 / usage / latency / status 徽标；点击行展开完整 `output_hash`；
   - **事后回溯**：技术级 → 调现有 `POST /replay`（`useTaskRun.replayResult` 已有，直接复用）；因果级 → 点击产物 hash → 调 `GET /model-calls?output_hash=...`（E-2 加一个可选过滤参数）→ 弹出调用明细与 `input_snapshot`；业务级 → 先做"耗时 Top5 任务 / 重试次数 Top5"两个小表（从 `tasks` 算），跨运行对比留占位并标"待接入"。
5. `App.tsx` 观测页调用处改传新 props。
6. `ui_smoke.mjs`：观测页断言改为"有运行时工件表行数 ≥ 1；无运行时显示空态"；`ui_layout.mjs` 不变。
7. `npm run build && npm run lint && npm run test` + `node tests/ui_smoke.mjs`。

**细节红线**

- 没有模型调用记录时显示"尚无记录（mock 运行不产生模型调用）"，**不伪造行**。
- 不改 `constants/stages.ts`；新 CSS 只加 `obs-` 前缀类。

**验收**：build/lint 0 警告/test 全绿；ui_smoke PASS；真实运行（B-4 已埋点）后观测页显示 ≥ 1 条模型调用且 input_hash 可点击追溯。

**涉及文件**：`frontend/src/api/workbenchApi.ts`、`frontend/src/hooks/useObservation.ts`（新）、`frontend/src/components/ObservationView.tsx`、`frontend/src/App.tsx`、`frontend/tests/ui_smoke.mjs`、`frontend/src/App.css`（obs-* 追加）

---

### E-4 三类验收报告（6h，第 3 周）

**目标**：技术闭环 / 真实模型 / 质量属性三类证据各自成文，互不替代（任务文档 1.5）。

**前置**：D-1 真实 runner 可用；F-4 性能基准已出结果（F 没出则先引用 `ui_layout.mjs` 的布局断言）。

**步骤**

1. `git switch -c task/e-4-acceptance-reports feat/p3-acceptance`
2. 新建 `docs/testing/`：
   - `P0_CLOSURE_REPORT.md`：贴 `run_all_checks.py` 15/15（E-2 后 17/17）的完整输出 + `verify_contracts.py` 输出 + 四场景 pipeline 摘要；写明复现命令。
   - `REAL_ACCEPTANCE_REPORT.md`：**手动触发**一次真实模型运行（`--execution-mode runner` + 已配 Key），记录：模型 ID、输入 `baseline.sha256`、任务数、usage 总和、耗时、产物 hash、预览 URL；明确"REAL 与 TEST 分开报告，CI 一律 mock"。
   - `QUALITY_ATTRIBUTES.md`：引用 F-4 的 `work/ui-perf.json`（首屏可交互 ms、帧率、对比度、键盘焦点数）+ 断点恢复验证（`pipeline --scenario retry` 的 restore 输出）。
3. `run_all_checks.py` 末尾加一行提示"三类报告见 docs/testing/，REAL 需手动触发"。
4. 主文档 1.5 的"三类证据"表加链接。

**红线**：REAL 报告**不得**用模拟运行的数据填充；没跑过就写"待跑"，不编造数字。

**验收**：三份文档入库，P0 与 QUALITY 的数字能被对应脚本复现。

**涉及文件**：`docs/testing/*.md`（新）、`workflow_runtime/run_all_checks.py`、`docs/TEAM_DIVISION.md`（链接）

---

### E-5 B06 签名证据接入执行链（8h，第 3 周）

**目标**：真实 runner 的测试结果经过 B06 受控执行 + HMAC 签名，`task_gate` 能校验证据可信（关闭 STAGE2_STATUS 遗留 2）。

**前置**：D-1 合入；读 `evidence.py` 全文（`check_evidence` 要求 envelope = `{report, signature}`，report 含 `schema_version=1 / context / results`，key 由服务端持有）；读 `runner.py` 的 `run_suite`。

**步骤**

1. `git switch -c task/e-5-evidence-chain feat/p3-acceptance`
2. 与 D 约定：D 的 `ModelFileRunner` 成功时返回 `evidence: []`（空）；本卡新增 `b04/evidence_bridge.py`：当任务有 `required_test_ids` 且产物目录下有测试文件时，调 `runner.run_suite(...)` 产出 report → `sign_report(report, key)` → 填进 `evidence`。
3. `task_gate.py` 的 `_check_result_hash_and_tests`（:232）已查"规定测试全部通过"——加一步：有 `evidence` envelope 时调 `check_evidence(...)`，失败 → finding `EVIDENCE_UNTRUSTED`（blocking）。**这是改 B06，先在群里说**。
4. 密钥：环境变量 `B06_EVIDENCE_KEY`（32 字节 hex），未配置 → 跳过签名校验并记 `EVIDENCE_UNSIGNED`（warning，不阻断），保证 CI 与 mock 不受影响。
5. 测试：`b06/tests/` 加 `test_evidence_bridge_signs_report`、`test_gate_rejects_tampered_evidence`、`test_gate_warns_when_unsigned`。

**红线**：mock 执行器继续不产签名（文档 N8：模拟不冒充真实）；签名 key 不入库、不进日志。

**验收**：B06 `pytest -q` 75 → ≥ 78；真实运行的质量门事件里出现 `EVIDENCE_VERIFIED`；篡改 report 后 `EVIDENCE_UNTRUSTED` 阻断。

**涉及文件**：`b04/evidence_bridge.py`（新）、`b06/multiagent_quality/task_gate.py`、`b06/tests/`、`b04/gateway_runner.py`（D 的，仅加一行调用）

---

### E-7 案例成熟度台账（持续，2h）

`docs/CASES.md` 由 D-5 创建，你维护其中的"成熟度"列：每两周案例重跑后更新 C0→C3 状态，并记录 `baseline.sha256` 与 `input_hash`，作为主文档 1.5"至少一个 C3"口径的证据。

### E-6 复核 C 的分支评审（1h，第 1 周）

C-6 评审 `feature/b03-blackboard` 时，你从"B03 观测表是否会与该分支的黑板设计冲突"角度复核结论，在 PR 下评论。

---

## 四、你的每周节奏

| 周 | 本周交付 | 周五前合入 |
|---|---|---|
| 1 | **E-1 Schema 冻结**（周三前开完 0-3 会）、E-6 | `feat/p3-observation` → `integration` |
| 2 | E-2 埋点 + 三条 GET 路由 | `feat/p3-observation` → `integration` |
| 3 | E-3 观测页、E-4 报告、E-5 证据链 | 两条功能分支 → `integration` |
| 4 | E-7 台账、配合答辩演示观测页 | — |

**每次开工**：主文档 0.1 五步。**每日**：和 F 对"观测页今天谁改哪个文件"。**每周中**：功能分支 `rebase origin/main`。

## 五、你的验收命令速查

```powershell
cd b03/b03_implementation; python -m pytest -q            # 基线 46 → ≥ 53
cd ..\..\b06-quality-consensus; python -m pytest -q        # 基线 75 → ≥ 78
cd ..; python workflow_runtime/verify_contracts.py         # 6/6 → ≥ 9/9
python workflow_runtime/run_all_checks.py                  # 15/15 → 17/17
cd frontend; npm run build; npm run lint; npm run test      # 0 警告 / 20 通过
```
