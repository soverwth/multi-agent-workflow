# 成员 A 分工 · 讨论状态机与 agent 共识

> 组别：组 1（阶段一）。本文是 `docs/TEAM_DIVISION.md` 的个人子文档，只含你的任务。
> 开工前先读主文档第〇节（开工五步 + 深读清单），再读本文。
> 本文中所有"现状"均已在 main `01f88cd` 上核实到行号。

---

## 一、你的分支

| 分支 | 用途 | 从哪切 | 何时合入 |
|---|---|---|---|
| `feat/p1-agent-consensus` | A-1 拆审批门、A-2 共识确认、A-4 简化模式 | `integration` | 第 1 周末（A-1/A-2），第 4 周（A-4） |
| `feat/p1-conversation-memory` | A-3 对话记忆表、A-5 圆桌后端 | `integration` | 第 2 周末（A-3），第 3 周末（A-5） |
| `task/a-<编号>-<短名>` | 每张卡一个任务分支，从对应功能分支切 | 功能分支 | PR 合回功能分支后删除 |

**你管的两条功能分支的共同点**：都在 `b02-workflow-agent/backend/`，但改的文件不同——`agent-consensus` 动 `controller.py / adapters.py / workflow_definition.py`；`conversation-memory` 动 `app.py` 路由 + B03 新文件 + `controller.py` 的阶段边界。两条分支**都会碰 `controller.py`**，所以 A-3 开工前先把 A-1/A-2 合进 `integration`，否则自己和自己冲突。

**你与别人的联调对象**

| 对方 | 联调什么 | 什么时候 |
|---|---|---|
| B | A-2 完成后 `confirmed_by` 字段格式（基线卡显示） | 第 1 周中 |
| F | A-5 圆桌四个指令的请求/响应形状，先写进 `TASK_ORCHESTRATION.md` 再各自实现 | 第 2 周末约定，第 3 周联调 |
| E | A-3 的消息消费点要同步写观测记录（E-2 的钩子位置） | 第 2 周 |

---

## 二、你负责的代码地图

| 文件 | 现状（核实过） | 你要动的 |
|---|---|---|
| `backend/controller.py` | `DiscussionController`：`create_run / step / run_until_control_point / _execute_current_stage / _evaluate_discussion(:164) / _review_proposal(:183) / resolve_human_decision(:211) / confirm_requirements(:233) / pause / resume / replay`。**三处 `WAITING_HUMAN`：:170、:195、:208** | A-1、A-2、A-4、A-3 的消费点 |
| `backend/adapters.py` | `ROLES = (产品经理, 用户研究员, 技术架构师, 质疑者)`（:8）；`MEMBERS = (成员 A…F)`（:9）；`LocalAgentGateway.frame / independent / critique / draft_proposal / review_proposal / evaluate_discussion / evaluate_proposal`；`RequirementGateway.prepare_draft / _prepare_with_llm / _prepare_locally / _normalize_requirements / _draft`；`publish(draft, members)`（:239，校验 `len(members)==6`） | A-2 改 `publish`、删 `MEMBERS`；A-1 可能新增 `debate()` 方法 |
| `backend/workflow_definition.py` | `STAGES / TRANSITIONS / PSEUDOCODE`，含 `HUMAN_CONFIRMATION` 阶段、`"owner": "B01 人类门槛"`、"六人逐项确认"文案；`/api/workflow` 原样返回给前端 | A-1 同步改文案与伪代码 |
| `backend/app.py` | POST `/api/runs/{id}/{step\|until-control-point\|pause\|resume\|human-decision\|confirm\|export}`（:210-224）；`/confirm` 调 `controller.confirm_requirements(run_id, payload["members"])` | A-2 改 `/confirm`；A-3 加 `/messages` 路由；A-5 加 `/roundtable` 路由 |
| `backend/llm.py` | `OpenAICompatibleClient`，无密钥时 `RequirementGateway` 走 `_prepare_locally` 规则兜底 | 不直接改（E 的埋点在这） |
| `tests/test_controller.py` | 9 个用例，其中 **`test_normal_flow_stops_at_six_person_gate_then_publishes_r1`(:30)**、**`test_value_conflict_pauses_for_human_decision`(:71)**、:36 和 :75 断言 `WAITING_HUMAN`、:11 `from backend.adapters import MEMBERS` | A-1/A-2 必须改写这两个用例与 MEMBERS 引用 |
| `tests/test_phase_bridge.py` | 桥接测试 | 不动（B 的） |

**先跑一遍基线**：`cd b02-workflow-agent && python -m unittest discover -s tests` → 当前 **113 tests OK**（约 21 秒）。改完后这个数字只能增不能减。

---

## 三、任务卡

### A-1 拆除三处人工审批门（12h，第 1 周，本组第一优先）

**目标**：讨论从想法到 R1，全程没有任何 `WAITING_HUMAN` 状态，也不需要任何人点按钮。

**前置**：读完 `controller.py` 全文（约 270 行）、`adapters.py` 的 `LocalAgentGateway`、`workflow_definition.py`。跑一遍 113 测试确认绿。

**步骤**

1. 切分支：`git switch -c task/a-1-remove-gates feat/p1-agent-consensus`
2. **先写失败测试**（TDD）：在 `tests/test_controller.py` 新增 `test_normal_flow_publishes_r1_without_human_gate`：`create_run → run_until_control_point` 循环直到 `status == COMPLETED`，断言过程中从未出现 `WAITING_HUMAN`，且 `blackboard.r1.status == "CONFIRMED"`。此时它应该失败。
3. 改 `:170`（`_evaluate_discussion`）：现在高影响分歧 → `WAITING_HUMAN`。改为调用新方法 `_auto_debate(run)`：
   - 对每条 `severity == high` 且未回应的异议，让**非提出者**的 2 个角色各追加一条 stance（`Agree / Disagree / Conditional` + reason），最多 `max_rounds` 轮；
   - 轮次用尽仍有 `Disagree`：**不阻塞**，把分歧写入 `blackboard.decisions`（`decided_by: "agent:auto"`, `content: "分歧未收敛，按推荐方案推进"`），然后 `_complete(...)` 进 PROPOSAL_REVIEW。
4. 改 `:195`（`_review_proposal`）：现在 Proposal 被拒 → `WAITING_HUMAN`。改为自动修订：复用 `RequirementGateway.prepare_draft` 重新起草，`run["revision_attempts"] += 1`；超过 3 次 → 走现有 `STOPPED` 路径（`_record(run, "DISCUSSION_STOPPED", {...reason: "proposal_rejected_3_times"})`）。**不得伪装成通过**。
5. 改 `:208`（HUMAN_CONFIRMATION）：现在 `run["stage"]="HUMAN_CONFIRMATION"; status=WAITING_HUMAN`。改为直接调用 A-2 的共识确认（本卡先写桩 `self._consensus_confirm(run)`，A-2 实装）。
6. 同步 `workflow_definition.py`：`HUMAN_CONFIRMATION` 阶段改 `owner: "B01 agent 共识"`、`action: "角色全部表态后发布 R1"`；`PSEUDOCODE` 里 `confirm_requirements(run, six_members)` 改成新签名；删掉"六人"字样。
7. 改写旧测试：`test_normal_flow_stops_at_six_person_gate_then_publishes_r1` → 改名为 `test_normal_flow_publishes_r1_by_consensus`，去掉 `assertEqual("WAITING_HUMAN")`；`test_value_conflict_pauses_for_human_decision` → 改名 `test_value_conflict_auto_debates_and_records_tradeoff`，断言 `status != WAITING_HUMAN` 且 `decisions` 里有记录。
8. 保留 `resolve_human_decision` 方法（:211）作为兼容入口，但让它只做"把用户意见写进黑板"，不再改变流程——A-3 会复用它接用户插话。

**细节红线**

- 判定者从人换成 agent，但"**多角色参与**"（每个角色都要表态）与"**异议必须被回应或显式记录**"两条门槛保留。
- `STOPPED` 是诚实停止，不是失败也不许删——这是任务文档 N8 的要求。
- `confirm_requirements` 的 `members` 参数本卡先保留，A-2 再换。

**验收**

- `python -m unittest discover -s tests`：≥ 113 全绿（旧 2 个改写 + 新增 1 个）
- `grep -n WAITING_HUMAN backend/controller.py`：只剩 `pause/resume` 里的兼容判断（:73），**不再有任何赋值 `= "WAITING_HUMAN"`**
- `cd .. && python workflow_runtime/run_all_checks.py` → 15/15（闭环用的是任务运行，不受影响，但要确认）
- PR 描述贴上：改前/改后 `python -c "from backend.app import service; print(service.controller...)"` 一段 `scenario=normal` 的事件类型列表，证明没有 `REQUIREMENTS_CONFIRMATION_REQUIRED` 之外的等待事件

**涉及文件**：`controller.py`、`workflow_definition.py`、`tests/test_controller.py`

---

### A-2 agent 共识确认（6h，第 1 周，紧接 A-1）

**目标**：R1 的发布由四个 agent 角色各自表态达成共识完成，`confirmed_by` 记录角色名。删除六人名单。

**前置**：A-1 已合入 `feat/p1-agent-consensus`。

**步骤**

1. `git switch -c task/a-2-consensus-publish feat/p1-agent-consensus`
2. `adapters.py`：删除 `MEMBERS`（:9）。`publish(draft, members)` → `publish(draft, roles: list[str])`：
   - 校验 `set(roles) == set(ROLES)`，否则 `WorkflowError("R1 发布需要全部角色表态：缺少 …")`
   - 校验黑板 `signoffs` 里每个角色 `stance in (Agree, Conditional)` 且 Conditional 的 `reason` 非空；任一 `Disagree/Pending` → `WorkflowError`，并返回需要辩论的 `role`
   - `confirmed_by = list(roles)`（保持 `list[str]`，B 的基线卡直接显示）
3. `controller.py`：把 A-1 留的桩 `_consensus_confirm(run)` 实装为：读 `blackboard.signoffs`，不齐则先跑一轮 `review_proposal` 收齐表态，再调 `publish`。`confirm_requirements(run_id, members)` 签名改为 `confirm_requirements(run_id, roles=None)`，缺省用 `ROLES`。
4. `app.py:223`：`/confirm` 不再要求 `members`，body 可空。
5. 测试：新增 `test_publish_rejects_missing_role`、`test_publish_rejects_disagree`、`test_publish_records_roles_in_confirmed_by`；旧用例里 `from backend.adapters import MEMBERS` 与 `list(MEMBERS)` 全部改为 `ROLES`。
6. **通知 B 与 F**：`confirmed_by` 现在是 `['产品经理','用户研究员','技术架构师','质疑者']`，前端 `App.tsx:57` 的 `AGENT_ROLES` 过渡常量可以删了（让 F 在 F-1 顺手清）。

**细节红线**：`confirmed_by` 是基线对象字段（任务文档 2.3），类型不许改成对象数组；`ROLES` 与 `adapters.independent()` 用的角色集必须同一常量。

**验收**：单测全绿（≥ 116）；`grep -rn MEMBERS backend/` 为空；`POST /api/runs/{id}/confirm` body `{}` 能发布 R1。

**涉及文件**：`adapters.py`、`controller.py`、`app.py`、`tests/test_controller.py`

---

### A-3 对话记忆表与阶段边界消费（16h，第 2 周）

**目标**：用户在任何时刻插话都不阻塞流程；消息在**下一个阶段边界**被 agent 读取并应用，且能追溯"这条输入影响了哪版产物"。

**前置**：A-1/A-2 已合 `integration`；先在群里和 C（也动 B03）约好时间窗；读完 `b03/b03_implementation/task_state.py` 的 `_connect / _tx / append_run_event / list_run_events` 写法，照抄其事务风格。

**步骤**

1. `git switch -c task/a-3-conversation-memory feat/p1-conversation-memory`
2. B03 新文件 `b03/b03_implementation/conversation.py`，类 `ConversationStore(db_path)`，`initialize()` 建表（字段见任务文档 2.2.2）：
   ```sql
   CREATE TABLE IF NOT EXISTS conversation_messages (
     message_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, stage TEXT,
     role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
     consumed_at TEXT, applied_to TEXT);
   CREATE INDEX IF NOT EXISTS idx_conv_pending ON conversation_messages(run_id, consumed_at);
   ```
   方法：`append(run_id, role, content, stage) -> message`、`pending(run_id) -> list`、`mark_consumed(message_ids, *, consumed_at, applied_to)`、`list(run_id) -> list`。
3. `app.py`：`POST /api/runs/{id}/messages`（body `{content}`，**返回 202** 与 `pending_count`，不触发任何推进）；`GET /api/runs/{id}/messages`。
4. `controller.py`：在 `_execute_current_stage` 开头（:97）插入 `_consume_user_messages(run)`：
   - `pending = store.conversation.pending(run_id)`，为空直接返回；
   - 按 `created_at` 排序全部取出，拼成 `"[用户插话] …"` 追加到本阶段的角色提示上下文（`LocalAgentGateway` 各方法加可选 `extra_context` 参数，默认 None，不影响现有调用）；
   - 本阶段完成后 `mark_consumed(ids, applied_to=f"{stage}:{run['updated_at']}")`；
   - 若用户意见与当前黑板结论冲突（简单判定：插话含"不要/改成/反对"），要求回应文本写入 `blackboard.decisions`（`decided_by: "agent:response_to_user"`, `content: "已考虑你的意见，但…"`）。
5. `resolve_human_decision`（:211）改为：只调用 `store.conversation.append(run_id, "user", decision)` 并返回当前 run，不再改状态。
6. 测试（新文件 `tests/test_conversation.py`）：① 插 3 条消息 → `step` 两次 → 断言全部 `consumed_at` 非空、`applied_to` 含阶段名；② 插话后立即 `get(run)` 断言 `status` 仍是 `RUNNING/READY` 而非任何等待态；③ 连发多条按时间排序消费；④ B03 `pytest -q` 新增 3 条（建表/查询/标记）。
7. 与 E 约定：消费时同时调 E-2 提供的 `observation.record(...)`（E 没就绪前先用 `try/except ImportError` 占位，**不要硬依赖**）。

**细节红线**

- 对话是"输入"，`task_run_events`/讨论事件是"事实"，**两套表分开**（任务文档 2.3）。
- 任何路径不得因 `pending` 非空而 `WAITING_HUMAN`（N6）。
- 不改 `task_state.py` 本体（那是 C 的地盘），只新增文件；若必须共用连接池，在 `conversation.py` 里 import `task_state.BLACKBOARD_DB` 即可。

**验收**：B03 `pytest -q` ≥ 49 绿；B02 unittest 全绿 + `test_conversation.py` 3 条；用 curl 向一个 `scenario=value_conflict` 运行插一句"优先隐私"，跑完后 `GET /messages` 显示 `consumed_at` 与 `applied_to`，且 `decisions` 里有"已考虑你的意见"。

**涉及文件**：`b03/b03_implementation/conversation.py`（新）、`app.py`、`controller.py`、`adapters.py`（加 `extra_context`）、`tests/test_conversation.py`（新）

---

### A-4 简化 / 极简模式（8h，第 4 周）

**目标**：同一状态机支持三种裁剪：完整（A—H）、简化（跳 F 方案审阅与 G 确认，E 后直接 H）、极简（讨论后直接出结论）。

**前置**：A-1/A-2 稳定运行一周。

**步骤**

1. `git switch -c task/a-4-modes feat/p1-agent-consensus`
2. `create_run(..., mode="full")` 加参数，写入 `run["mode"]`；校验取值 `full|simplified|minimal`。
3. `_complete()`（:127）按 `run["mode"]` 查跳阶段表：`simplified: {PROPOSAL_REVIEW→DESIGN_SPEC}`，`minimal: {CRITIQUE→COMPLETED}`。
4. `workflow_definition.py` 的 `TRANSITIONS` 不改（它是全量迁移表），跳阶段在 `_complete` 里做，并 `_record(run, "STAGE_SKIPPED", {from, to, mode})` 留痕。
5. `app.py` `POST /api/runs` 透传 `mode`。
6. 测试：三种 mode 各一条端到端用例，断言经过的阶段序列正确且 `STAGE_SKIPPED` 事件存在。
7. 前端主理人页加模式下拉——**交给 B 在 B-3 做**，你只负责接口（写进 `TASK_ORCHESTRATION.md` 的接口表）。

**红线**：向下兼容（N2）——`mode` 缺省 `full`，旧调用不变；跳阶段的事件必须留痕，否则回放会与快照不一致。

**验收**：单测 ≥ 119；`minimal` 模式 3 次 `step` 内到 `COMPLETED`。

**涉及文件**：`controller.py`、`app.py`、`tests/test_controller.py`

---

### A-5 圆桌后端：四个非阻塞指令（10h，第 3 周）

**目标**：前端圆桌页的"点名发言 / 追问观点 / 要求举证 / 让两位 agent 辩论"四个按钮有真实后端，全部非阻塞。

**前置**：A-3 已合入；与 F 在第 2 周末把请求/响应形状写进 `TASK_ORCHESTRATION.md` §3.4 再动手。

**接口约定（先写文档再实现）**

```text
POST /api/runs/{id}/roundtable
body: { action: "call_on"|"follow_up"|"demand_evidence"|"debate",
        target_role?: str, opponent_role?: str, text: str, ref_id?: str }
resp: 202 { queued: true, message_id, pending_count }
```

**步骤**

1. `git switch -c task/a-5-roundtable-backend feat/p1-conversation-memory`
2. 所有指令**都写入 A-3 的 `conversation_messages`**（`role = "user"`，`content = "[圆桌:{action}:{target}] {text}"`），返回 202——这就是非阻塞。
3. `_consume_user_messages` 扩展：解析 `[圆桌:…]` 前缀：
   - `call_on` → 只让 `target_role` 在本阶段追加一条 `claims`；
   - `follow_up` → 所有角色对 `ref_id` 指向的观点追加 `stances`；
   - `demand_evidence` → `target_role` 必须给出 `evidence` 字段，否则记 `objection(severity=medium, raised_by="user")`；
   - `debate` → `target_role` 与 `opponent_role` 各追加一条相反 stance。
4. 辩论/举证结果照常进 `blackboard`，前端（F-1）读黑板即可看到。
5. 测试：四种 action 各一条，断言对应角色产生了新 claim/stance 且 `status` 从未进入等待。

**红线**：语义参考 SE-DPA steward 指令（`REFERENCE_PROJECTS_3WAY.md` 2.1），**实现不复制**；不设审批按钮、不改变流程推进。

**验收**：单测 ≥ 123；与 F-1 联调走通"点名 → 下一阶段边界后出现该角色回应"。

**涉及文件**：`controller.py`、`app.py`、`tests/test_conversation.py`

---

### A-6 分支治理（2h，第 1 周内）

1. 群里发通知：列出主文档 2.1 表中的 8 个已并入分支，公示 48h，请所有人核对本地是否有未推工作。
2. 到期执行：`git push origin --delete b06-quality-consensus feat/b02-b05-single-port feat/llm-adaptive-workbench feat/second-stage-closed-loop feat/unify-b05-and-fix-bridge feat/workbench-gantt-export feature/b03-platform-store`
3. 把执行结果（日期 + 列表）写进主文档第八节变更记录，PR 到 `integration`。

---

## 四、你的每周节奏

| 周 | 本周交付 | 周五前合入 |
|---|---|---|
| 1 | A-1 + A-2（拆门 + 共识）、A-6 公示与删除 | `feat/p1-agent-consensus` → `integration` |
| 2 | A-3（对话记忆） | `feat/p1-conversation-memory` → `integration` |
| 3 | A-5（圆桌后端）、与 F 联调 | 同上分支追加 |
| 4 | A-4（模式裁剪） | `feat/p1-agent-consensus` → `integration` |

**每次开工**：主文档 0.1 五步。**每日**：和 B 对一次"今天动哪些文件"。**每周中**：两条功能分支各 `rebase origin/main` 一次。

## 五、你的验收命令速查

```powershell
cd b02-workflow-agent
python -m unittest discover -s tests -v          # 基线 113 → 目标 ≥123
cd ..
python workflow_runtime/verify_contracts.py      # 6/6
python workflow_runtime/run_all_checks.py        # 15/15（约 2 分钟）
cd b03/b03_implementation; python -m pytest -q   # 基线 46 → A-3 后 ≥49
```
