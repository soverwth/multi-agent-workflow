# 成员 B 分工 · 设计规格细化、基线对象与阶段一前端

> 组别：组 1（阶段一）。本文是 `docs/TEAM_DIVISION.md` 的个人子文档，只含你的任务。
> 开工前先读主文档第〇节（开工五步 + 深读清单），再读本文。
> 本文中所有"现状"均已在 main `01f88cd` 上核实到行号。

---

## 一、你的分支

| 分支 | 用途 | 从哪切 | 何时合入 |
|---|---|---|---|
| `feat/p1-design-spec` | B-1 契约补全、B-2 基线对象、B-5 C2 案例 | `integration` | 第 1 周末（B-1 最小版）、第 2 周末（B-2）、第 3 周（B-5） |
| `feat/p1-frontend-discussion` | B-3 阶段一前端深化、B-4 模型调用埋点 | `integration` | 第 2 周末（B-3）、第 3 周（B-4） |
| `task/b-<编号>-<短名>` | 每张卡一个任务分支 | 对应功能分支 | PR 合回后删除 |

**两条分支的共同点**：都是"阶段一的产出物"——一条做后端产物（规格长什么样），一条做前端呈现（规格怎么被看到）。它们几乎不改同一个文件，可以并行推进。

**你与别人的联调对象**

| 对方 | 联调什么 | 什么时候 |
|---|---|---|
| A | A-2 完成后 `confirmed_by` 变成角色名列表，基线卡和立场卡直接显示 | 第 1 周中 |
| C | B-2 的规范化哈希函数要和 C-2 共用，放在 `workflow_runtime/` 共享，**不要各写一份** | 第 2 周初约 30 分钟 |
| E | B-4 埋点严格按 E-1 定稿的 schema 落记录；E 没定稿前不动手 | 第 2 周末 |
| F | B-3 改的是 `RoundTableView / RequirementsView` 的**数据接入**，F-1 改的是同一组件的**交互与发送**——先在群里说好谁改哪几行 | 第 2 周每日同步 |

---

## 二、你负责的代码地图

| 文件 | 现状（核实过） | 你要动的 |
|---|---|---|
| `backend/phase_bridge.py` | `r1_to_design_spec(run)`（:65）：把 R1 转成 `b01.spec.v1`。**`contract` 只有骨架**（:122-128，`operations: []`、`errors: {}`、`field_bounds: {}`）；**`design_entries[].contract_refs` 全空**（:108）；`phase1_source` 只有 `run_id / r1_version / generation_source / confirmed_by`（:129-134），**无 revision / parent / sha256** | B-1、B-2 |
| `docs/TASK_ORCHESTRATION.md` §2.1 | 已定义 `contract.operations` 字段：`name/method/path/authenticated/required/status/data`；`errors: {"CODE": 400}`；`field_bounds: {}`——**但 `response_envelope` 与 `data_model` 未定义** | B-1 补文档 |
| `backend/llm.py` | `OpenAICompatibleClient.complete_json(*, system, user) -> dict`（:91）是唯一模型调用出口 | B-4 在此埋点（只加钩子，不改签名） |
| `backend/adapters.py` | `RequirementGateway._prepare_with_llm`（:149）调 `complete_json` | B-4 可能在这里取 `usage` |
| `tests/test_phase_bridge.py` | 4 个用例：拒绝未确认 / 转换成功 / 优先级归一 / 别名表 | B-1、B-2 各加用例 |
| `frontend/src/components/RoundTableView.tsx` | props `{discussion, chatDraft, onChatDraftChange, onOpenRequirements}`；八阶段进度用 `phaseIndexForStage(discussion.stage)` | B-3 接 messages 接口 |
| `frontend/src/components/RequirementsView.tsx` | 读 `/api/runs/{id}` 与 `/design-spec`；立场卡读 `board.signoffs` | B-3 显示 confirmed_by 与规格细化进度 |
| `frontend/src/components/BaselineCard.tsx` | props `{spec, planVersion, specVersion}`；`factsFromDesignSpec` 只取 `phase1_source.run_id / r1_version / confirmed_by / generation_source`；revision / parent / sha256 显示"待后端补齐" | B-2 后端就绪后把占位换实值 |
| `frontend/src/utils/baseline.ts` | `factsFromDesignSpec()` | B-2 扩展 |
| `frontend/src/api/workbenchApi.ts` | `DiscussionRun / Blackboard` 类型；`getDiscussionRun / getDesignSpec / advanceDiscussion / confirmDiscussionByConsensus` | B-3 加 `listMessages / sendMessage` |
| `b01-spec-planner/docs/fixtures/` | `campus-lost-found.spec.json`（无 `phase1_source`，C0 手写）、`lab-equipment-loan.spec.md` | B-5 新增 C2 规格 |

---

## 三、任务卡

### B-1 H 阶段设计规格细化（18h，第 1 周出最小版，第 3 周收尾）

**目标**：阶段一的终点不再是"需求级列表"，而是带接口、错误码、字段边界、响应结构、数据模型、非功能约束的**设计级规格**；`contract_refs` 不再为空。

**前置**：A-2 已合入（`confirmed_by` 是角色名）；读完 `TASK_ORCHESTRATION.md` §2.1 和 `REFERENCE_PROJECTS_3WAY.md` 2.2（SE-lib 的 design-spec schema 字段组织方式）。

**契约六块的定义（先写进文档，再写代码）**

在 `TASK_ORCHESTRATION.md` §2.1 的 JSON 示例里补全为：

```json
"contract": {
  "contract_version": "C1-...",
  "operations": [
    {"op_id": "OP-001", "name": "createLostItem", "method": "POST", "path": "/api/lost-items",
     "authenticated": true, "req_refs": ["R-001"],
     "request_fields": [{"name": "title", "type": "string", "required": true, "bounds": "length:1..80"}],
     "response_fields": [{"name": "id", "type": "string"}], "status": 201}
  ],
  "errors": {"ITEM_NOT_FOUND": 404, "TITLE_TOO_LONG": 400},
  "field_bounds": {"title": {"type": "string", "min_length": 1, "max_length": 80, "required": true}},
  "response_envelope": {"data": "object|null", "error": {"code": "string", "message": "string"}, "meta": "object"},
  "data_model": [{"entity": "LostItem", "fields": [{"name": "id", "type": "string", "pk": true}], "relations": ["Claim.lost_item_id -> LostItem.id"], "indexes": ["id"]}],
  "nonfunctional": ["响应时间 p95 < 500ms", "所有写接口需鉴权"]
}
```

**步骤**

1. `git switch -c task/b-1-contract-detail feat/p1-design-spec`
2. 先改文档 `TASK_ORCHESTRATION.md` §2.1（上面六块）+ 在 §2.1 末尾加一句"由 B02 `phase_bridge` 生成，字段缺省值见 `b01.spec.v1`"。
3. `phase_bridge.py` 新增 `_derive_contract(project_id, requirements, constraints) -> dict`：
   - **operations**：每条需求至少一个操作。从 `req_id` 与 `title` 推导 `op_id = f"OP-{req_id}"`、`name = _camel(_slug(title))`；有"创建/登记/提交"类动词 → `POST`，"浏览/查看/列表" → `GET`，"修改/更新" → `PUT`，"删除/取消" → `DELETE`；`path = f"/api/{_slug(module)}/{op_id.lower()}"`；`req_refs = [req_id]`。动词判定用关键词表，**不要**调模型——桥接必须是确定性转换（文档 2.3 约束 3）。
   - **errors**：每条操作固定配 `{"{OP_NAME}_NOT_FOUND": 404, "{OP_NAME}_INVALID": 400}`；需求 acceptance 里出现"必填/不能为空" → 加 `"{OP_NAME}_REQUIRED": 400`。
   - **field_bounds**：从 acceptance 文本抽"不超过 N 字 / N 个 / N 天"→ `max_length / max_items`；抽不到的字段给保守默认（string 1..255）并标 `"source": "default"`。
   - **response_envelope**：统一信封 `{data, error{code,message}, meta}`。
   - **data_model**：每条需求一个实体，`pk = id: string`；需求间有"属于/关联"字样 → 加 relation。
   - **nonfunctional**：从 `run.constraints` 透传 + 固定两条（响应时间、鉴权）。
4. `design_entries[].contract_refs = [op_id for op in operations if req_id in op.req_refs]`，`:108` 的 `[]` 不再为空。
5. `rule` 字段（:110）去掉"具体技术方案由设计规格评审补充"这句占位，改为引用 operations 的说明。
6. 测试 `test_phase_bridge.py` 新增：`test_contract_has_operations_for_every_requirement`、`test_contract_refs_nonempty`、`test_contract_is_deterministic`（同一 run 转两次 JSON 相等）。
7. 在 `workflow_runtime/verify_contracts.py` 加一项检查 `contract_nonempty`：对 `campus-lost-found.spec.json` 跑一遍桥接（用一个已确认的假 run）或直接检查 fixture 的 `contract.operations` 非空。

**细节红线**

- 桥接**只做结构化转换，不代替评审**——不要调模型"生成接口"，否则 A 组的"确定性"和回放一致性都会被破坏。
- 抽不到的字段用保守默认并标 `source: default`，**不要编造**精确边界（N8 精神：不伪造）。
- 动词→HTTP 方法表放在 `phase_bridge.py` 模块级常量，便于 review。

**验收**：B02 单测全绿 + 新增 3 条；`verify_contracts.py` 7/7；用 `scenario=normal` 的 run 桥接后 `contract.operations` 数量 == 需求数量。

**涉及文件**：`phase_bridge.py`、`docs/TASK_ORCHESTRATION.md`、`tests/test_phase_bridge.py`、`workflow_runtime/verify_contracts.py`

---

### B-2 基线对象：revision / parent / sha256（8h，第 2 周）

**目标**：`phase1_source` 升级为基线对象，前端 `BaselineCard` 的"待后端补齐"变成实值。

**前置**：B-1 最小版已合入；与 C 开 30 分钟会，把规范化哈希函数定在 `workflow_runtime/canonical.py`（新文件），C-2 的 `input_hash` 也用它。

**共享哈希函数（你负责写，C 复用）**

```python
# workflow_runtime/canonical.py
def canonical_hash(value: Any) -> str:
    """键排序、无空白、UTF-8 的 JSON SHA-256。两侧必须用同一函数。"""
```

注意 B01 已有 `dynamic_planner.canonical_hash`——**先看它的实现**，若等价就复用并把它搬到 `workflow_runtime/`，不要造第三个。

**步骤**

1. `git switch -c task/b-2-baseline feat/p1-design-spec`
2. `r1_to_design_spec` 返回的 `phase1_source` → 改名 `baseline`（保留 `phase1_source` 作别名一个版本，C 组的 `task_api.from-discussion` 读这个字段，**通知 C 改读取路径**），字段：
   ```python
   "baseline": {
     "baseline_id": f"BL-{run['run_id']}",
     "project_id": project_id,
     "revision": 1,
     "parent_baseline_id": None,
     "r1_version": "R1",
     "sha256": canonical_hash({"requirements": requirements, "design_entries": design_entries, "contract": contract}),
     "confirmed_by": [...roles],
     "generation_source": "llm|rules|handwritten",
   }
   ```
3. 同一 run 重新桥接（R1 变了）→ `revision = 上次 + 1`、`parent_baseline_id = 上次 baseline_id`。来源：`GET /api/runs/{id}/design-spec` 多次调用时，从 B03 存的基线历史取上一版（新表 `design_baselines(run_id, revision, baseline_id, sha256, created_at)`，放 B03，和 A-3 的新文件并列，不改 `task_state.py`）。
4. `frontend/src/utils/baseline.ts` 的 `factsFromDesignSpec` 扩展读 `baseline`（兼容旧 `phase1_source`）；`BaselineCard.tsx` 占位换实值，hash 显示前 12 位 + 悬浮全量。
5. 测试：`test_baseline_has_hash_and_revision`、`test_same_input_same_hash`、`test_rerun_increments_revision_with_parent`。

**红线**：哈希对**规范化 JSON**算，不含时间戳；`confirmed_by` 类型不变（`list[str]`）。

**验收**：两次相同输入 `sha256` 相同；前端基线卡显示 `BL-RUN-xxx / r1 / sha256 前 12 位`；`verify_contracts.py` 全绿。

**涉及文件**：`phase_bridge.py`、`workflow_runtime/canonical.py`（新）、`b03/b03_implementation/baseline_history.py`（新）、`frontend/src/utils/baseline.ts`、`frontend/src/components/BaselineCard.tsx`、`tests/test_phase_bridge.py`

---

### B-3 阶段一前端深化（14h，第 2 周）

**目标**：用户在主理人页和圆桌页插话后能看到"已收到，将在阶段边界应用"；讨论页进度实时刷新；需求页立场卡显示确认角色。

**前置**：A-3 的 `/api/runs/{id}/messages` 接口已合入（没合入前先用类型桩，不写死）；与 F 划清 `RoundTableView.tsx` 的改动行：**你改数据接入（props 与读取），F 改交互（发送、按钮状态）**。

**步骤**

1. `git switch -c task/b-3-frontend-discussion feat/p1-frontend-discussion`
2. `workbenchApi.ts` 加 `listMessages(baseUrl, runId)`、`sendMessage(baseUrl, runId, content)`（POST，返回 202 的 body）。
3. `App.tsx`：主理人页"本次讨论"卡下方加"最近插话"列表（读 `listMessages`），每条显示 `content / created_at / consumed_at ? "已应用于 {applied_to}" : "待下一阶段边界应用"`。讨论推进后（`handleAdvanceDiscussion` 成功回调）重新拉一次。
4. `RoundTableView.tsx`：八阶段进度改为订阅 `discussion.stage` 实时变化（已有映射 `phaseIndexForStage`），`WAITING_*`/`COMPLETED` 等控制态不要误显示成阶段 A；把"设计规格细化进度"卡改为读真实 `designSpec`（有则显示 operations / errors / field_bounds 数量，没有就显示待补全）。
5. `RequirementsView.tsx`：立场卡的 `confirmed_by`（A-2 后是角色名）直接列出；"设计规格"折叠块里 `JSON.stringify` 换成按六块分组的小标题（operations N 项 / errors N 项 / …），点击展开原始 JSON。
6. `ui_smoke.mjs` 补断言：主理人页有"最近插话"区；讨论页细化进度卡显示"待补全"或数字。
7. `npm run build && npm run lint && npm run test`（20 测试基线）+ `node tests/ui_smoke.mjs http://127.0.0.1:7100`。

**红线**

- 不改 `constants/stages.ts`（跨组共享，页面定义冻结）。
- 不改 `RoundTableView.tsx` 里按钮的 `onClick` 逻辑（F-1 的）。
- 全部走现有 token（`App.css :root`），**不新增硬编码色值**。

**验收**：build/lint 0 警告/test 全绿；ui_smoke PASS（含新断言）；真实接口下插一句话，列表出现且推进后状态变"已应用"。

**涉及文件**：`frontend/src/api/workbenchApi.ts`、`frontend/src/App.tsx`、`frontend/src/components/RoundTableView.tsx`、`frontend/src/components/RequirementsView.tsx`、`frontend/tests/ui_smoke.mjs`

---

### B-4 模型调用埋点（8h，第 3 周，等 E-1 冻结）

**目标**：B02 每一次 `complete_json` 调用落一条 `model_call` 记录，字段严格按 E-1 定稿 schema。

**前置**：E-1 的 `docs/contracts/observation.schema.json` 已冻结；E-2 提供 `observation.record_model_call(...)` 的落库函数（E 没就绪前用 `try/except` 占位）。

**步骤**

1. `git switch -c task/b-4-model-call-trace feat/p1-frontend-discussion`
2. `llm.py` 的 `complete_json`：记录 `started = time.perf_counter()`，成功后组装记录：`run_id / node_id / role`（从调用处透传——`complete_json` 加可选 `context: dict | None = None` 参数，`RequirementGateway._prepare_with_llm` 与 `LocalAgentGateway` 各调用处传入 `{run_id, node: stage, role}`）、`input_hash = canonical_hash({system, user})`、`output_hash = canonical_hash(result)`、`usage`（响应里的 `usage`，没有则 None）、`latency_ms`、`status = success`；异常 → `status = failed|budget_exhausted`，同样落记录后**原样抛出**。
3. 调 E-2 的落库函数。
4. 测试 `test_llm.py`：假客户端返回固定结果，断言记录的 `input_hash/output_hash/latency_ms` 存在且 hash 稳定。

**红线**：埋点**绝不吞异常、绝不改变返回值**；`complete_json` 签名只加可选参数。

**验收**：B02 单测全绿 + 新增 2 条；一次真实模型运行后，观测页（E-3）工件表出现记录。

**涉及文件**：`backend/llm.py`、`backend/adapters.py`（调用处传 context）、`tests/test_llm.py`

---

### B-5 第一个 C2 案例（6h，第 3 周）

**目标**：用完整流程真实生成一个带 `baseline.generation_source = "llm"` 的规格，替换手写 fixture 作为"讨论产出"的演示。

**前置**：B-1、B-2 已合入；配置好 DeepSeek Key（`/api/llm/config`）。

**步骤**

1. 启动 7100，在主理人页输入"校园活动报名与签到工具"（**不要用失物招领**，那是 C0 fixture 的题目），约束填"移动端、人数上限、复用登录"。
2. 推进到 R1，进第二阶段，`GET /api/runs/{id}/design-spec` 取规格。
3. 存为 `b01-spec-planner/docs/fixtures/campus-activity-signup.spec.json`，确认 `baseline.sha256` 与 `generation_source: "llm"` 都在。
4. 用它跑 `python -m workflow_runtime pipeline --spec b01-spec-planner/docs/fixtures/campus-activity-signup.spec.json`，确认能分解编排。
5. 在主文档 1.5 的"案例成熟度"表里把它记为 **C2**（有讨论来源但还没真实执行产物）。

**验收**：fixture 文件入库且 pipeline 通过；README 案例表加一行。

**涉及文件**：`b01-spec-planner/docs/fixtures/campus-activity-signup.spec.json`（新）、`README.md`（案例表）

---

## 四、你的每周节奏

| 周 | 本周交付 | 周五前合入 |
|---|---|---|
| 1 | B-1 最小版（operations + errors，field_bounds 先默认） | `feat/p1-design-spec` → `integration` |
| 2 | B-1 收尾、B-2 基线、B-3 前端 | 两条功能分支 → `integration` |
| 3 | B-4 埋点、B-5 C2 案例 | 两条功能分支 → `integration` |
| 4 | 配合 A-4 加模式下拉（主理人页，1h）；缓冲 | — |

**每次开工**：主文档 0.1 五步。**每日**：和 A 对"今天动哪些文件"。**每周中**：两条功能分支各 `rebase origin/main` 一次。

## 五、你的验收命令速查

```powershell
cd b02-workflow-agent; python -m unittest discover -s tests   # 基线 113 → ≥118
cd ..; python workflow_runtime/verify_contracts.py            # 6/6 → 7/7
cd frontend; npm run build; npm run lint; npm run test         # 0 警告 / 20 通过
node tests/ui_smoke.mjs http://127.0.0.1:7100                 # 需先启动 B02
```
