# 成员 D 分工 · 真实执行链路、网页产物与案例重建

> 组别：组 2（阶段二）。本文是 `docs/TEAM_DIVISION.md` 的个人子文档，只含你的任务。
> 开工前先读主文档第〇节（开工五步 + 深读清单），再读本文。
> 本文中所有"现状"均已在 main `01f88cd` 上核实到行号。

---

## 一、你的分支

| 分支 | 用途 | 从哪切 | 何时合入 |
|---|---|---|---|
| `feat/p2-real-execution` | D-1 真实 runner、D-2 网页产物与预览、D-3 写入范围、D-4 分档路由 | `integration` | 第 1 周末（D-1 最小版）、第 2 周末（D-2/D-3）、第 3 周（D-4） |
| `feat/p2-cases` | D-5 案例重建（L1 → L2 → C3） | `integration` | 第 3 周末 |
| `task/d-<编号>-<短名>` | 每张卡一个任务分支 | 对应功能分支 | PR 合回后删除 |

**你的核心命题**：把执行从 `simulated=True` 变成真的产出文件，且**失败时不伪造产物**。这是"不止编排，还要推到执行"的落地，也是全组唯一一条会让项目从 C2 走到 C3 的线。

**你与别人的联调对象**

| 对方 | 联调什么 | 什么时候 |
|---|---|---|
| C | 你在 `app.py` 加 `GET /preview/<run_id>/` 静态路由，C 在同文件加 `do_PATCH`——**路由段两人同改**，群里说谁先合 | 第 2 周 |
| F | D-2 的交付页"打开预览"按钮由 F-5 做，你只提供 `/preview/<run_id>/` 能返回 200 | 第 2 周末 |
| E | E-5 要把你的真实 runner 产出的测试结果接进 B06 签名证据链；你的 runner 返回体要有 `evidence` 字段 | 第 3 周 |
| B | D-5 的 C3 案例用 B-5 生成的 C2 规格作输入 | 第 3 周 |

---

## 二、你负责的代码地图

| 文件 | 现状（核实过） | 你要动的 |
|---|---|---|
| `b04-agent-integration/src/b04/gateway.py` | `validate_request / validate_result`（契约校验）；`MockTaskExecutor`（返回 `"simulated": True`，:283）；**`RunnerTaskExecutor(runner_callable)`（:287）已存在但从未被装配**；`TaskExecutionGateway(mode="mock"\|"runner", runner_callable=None)`（:312），runner 模式必须提供 `runner_callable` | D-1 新增 runner 实现 |
| `b02-workflow-agent/backend/task_api.py` | `default_stack(db_path, *, execution_mode="mock", scenario=None)`（:36）：**只构造 `TaskExecutionGateway(mode=execution_mode, scenario=scenario)`，没传 `runner_callable`**（:49）→ 即使 `execution_mode="runner"` 也会抛 GatewayError | D-1 接线；D-4 加分档配置 |
| `b02-workflow-agent/backend/app.py` | `main()` 的 argparse 只有 `--host/--port/--task-db/--frontend-dir`；`_static(path)`（:281）有**路径约束写法可照抄**（`candidate.relative_to(root)` 防目录穿越） | D-1 加 `--execution-mode`；D-2 加 `/preview/` 路由 |
| `b04/agent_runner/` | `runner.py`（44KB）、`store.py`、`artifacts.py`、`contracts.py`、`testing.py`（`build_demo_runtime`）——B04 已有一套完整的 agent 运行时与 SQLite 产物库，**但它与 §5 gateway 契约之间没有桥** | D-1 决定：直接复用 `AgentRunner`（重但完整）还是先写轻量 `ModelFileRunner`（快）。**建议先轻量**，见 D-1 |
| `b04/model_adapter/` | 模型适配层 | D-1 可能复用其客户端 |
| `b04/examples/agent_runner_demo.py` | 演示 `build_demo_runtime → runner.invoke_agent → wait_invocation → 读 manifest` 的完整调用链 | D-1 若走重方案，照这个写 runner_callable |
| `b06-quality-consensus/multiagent_quality/evidence.py` | `check_evidence(envelope, *, key, expected_context, required_test_ids, ...)`、`sign_report / sha256_file` | **不改**（E-5 的）；你的 runner 只需产出能被它校验的 evidence 结构 |
| `b01-spec-planner/docs/fixtures/` | 现有全是 C0 手写 | D-5 新增 L1/L2/C3 |
| `workflow_runtime/pipeline.py` | `run_pipeline(...)` 四场景，mock 执行 | D-5 加 `--real` 开关或新脚本 |

---

## 三、任务卡

### D-1 B04 真实 runner（14h，第 1 周出最小版）

**目标**：`execution_mode="runner"` 时，任务由真实模型生成文件内容；模型空返回、截断、语法无效时**不登记产物**，返回结构化错误。

**前置**：读 `gateway.py` 全文（§5 请求/结果契约在 `validate_request / validate_result` 里）；读 `REFERENCE_PROJECTS_3WAY.md` 2.1（SE-DPA 的"不伪提交"与 worktree 做法，**只取原则，不搬实现**）。

**方案选择（第 1 周初决定，写进 PR）**

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| **轻量（建议先做）** | 新建 `b04/gateway_runner.py`：`ModelFileRunner(llm_client)`，`__call__(request)` 调 `OpenAICompatibleClient.complete_json` 让模型按 `request["write_scope"]` 输出 `{path: content}`，组装 §5 结果 | 一天能通；零新依赖 | 没有 B04 agent_runner 的租约/工具/审计 |
| 完整 | `runner_callable` 内部走 `build_demo_runtime` 式的 `AgentRunner.invoke_agent`，再把 manifest 转 §5 | 复用 B04 44KB 的运行时 | 桥接层复杂，且 B04 runtime 是异步的 |

先做轻量版让链路通，第 3 周若有余力再评估切完整版。

**步骤**

1. `git switch -c task/d-1-real-runner feat/p2-real-execution`
2. `b04/gateway_runner.py`（新）：
   ```python
   class ModelFileRunner:
       def __init__(self, llm_client, *, max_output_chars=60_000): ...
       def __call__(self, request: dict) -> dict:
           # request: task_id, attempt_id, goal, acceptance, write_scope, required_test_ids, ...
           # 1) 组 prompt：goal + acceptance + write_scope + "只输出 JSON {path: content}"
           # 2) 调模型；捕获：空返回 / finish_reason == "length" / JSON 解析失败 / 路径越界
           # 3) 任一失败 → 返回 §5 failure 结果：
           #    {"status": "failed", "artifacts": [], "error": {"code": "MODEL_EMPTY|MODEL_TRUNCATED|MODEL_INVALID_JSON|PATH_OUT_OF_SCOPE",
           #      "message": "...", "target_file": "...", "retryable": True}}
           # 4) 成功 → artifacts 每项 {path, content_sha256, bytes}，evidence 先为空（E-5 接），
           #    "simulated": False, "execution_mode": "runner"
   ```
3. `task_api.default_stack`：加 `llm_client` 参数；`execution_mode == "runner"` 时 `TaskExecutionGateway(mode="runner", runner_callable=ModelFileRunner(llm_client))`。`app.py` `ApplicationService` 把已有的 `service.llm_client` 传进去；argparse 加 `--execution-mode mock|runner`（默认 mock——**CI 和演示默认不花钱**）。
4. `task_orchestrator._apply_result`（:485）已按 §5 结果推进：确认它对 `status == "failed"` 且 `artifacts == []` 的处理是 `_fail_attempt` → `_retry_or_fail`，**不要为此改编排器**。
5. 测试 `tests/gateway/test_runner.py`（B04）：
   - 假 llm_client 返回正常 JSON → 结果含 artifacts、`simulated=False`；
   - 返回空字符串 → `MODEL_EMPTY`，`artifacts == []`；
   - 返回截断标记 → `MODEL_TRUNCATED`；
   - 返回 `{"../etc/passwd": "x"}` → `PATH_OUT_OF_SCOPE`；
   - 每条都断言**没有登记任何产物**。
6. B02 `tests/test_task_api.py` 加 `test_runner_mode_requires_llm`（未配置模型时 `--execution-mode runner` 启动返回清晰错误而不是 500）。
7. 手测：配好 Key，`python -m backend.app --execution-mode runner`，用 L1 计算 spec（D-5 先建）跑到完成，把 `work/deliverables/<run_id>/` 截图贴 PR。

**细节红线**

- **模拟与真实严格分离（N8）**：runner 失败就是失败，**绝不回落 mock**；`simulated` 字段必须如实。
- **不伪提交**：任何失败路径 `artifacts` 必须为空，不许塞占位文件。
- 不改 `task_gate.py`（E 的）；不改 `task_orchestrator.py` 的状态机（C 的）。
- 模型输出不做语法高深度校验（不是编译器），但 JSON 必须能解析、路径必须在 `write_scope` 内。

**验收**：B04 `pytest -q` 664 → ≥ 669；B02 单测全绿；手测产物目录有文件且 `simulated=False`。

**涉及文件**：`b04/gateway_runner.py`（新）、`b04/tests/gateway/test_runner.py`（新）、`backend/task_api.py`、`backend/app.py`、`tests/test_task_api.py`

---

### D-2 网页产物与预览（8h，第 2 周）

**目标**：真实执行产出的文件归档到 `work/deliverables/<run_id>/`，通过 7100 的 `/preview/<run_id>/` 直接打开。

**前置**：D-1 最小版已合入；与 C 约好 `app.py` 路由段谁先合。

**步骤**

1. `git switch -c task/d-2-deliverable-preview feat/p2-real-execution`
2. 产物落盘：`ModelFileRunner` 成功时把 `artifacts` 写到 `work/deliverables/<run_id>/<path>`（`run_id` 从 request 取；目录不存在则建）。约定 `index.html` 为入口（内联 CSS/JS，零构建——任务文档 2.4.7）。
3. `app.py` 加 `GET /preview/<run_id>/<file>`：
   - 照 `_static` 的路径约束写法：`(deliverables_root / run_id / file).resolve().relative_to(deliverables_root / run_id)`，失败 → 404；
   - 只服务 `work/deliverables/` 下的文件；`Content-Type` 用 `mimetypes`；
   - `run_id` 校验 `^[A-Z0-9-]+$`。
4. `GET /api/task-runs/{id}` 返回体加 `deliverable_url: "/preview/<run_id>/"`（有产物时）。
5. 前端交付页的"打开预览"按钮——**F-5 做**，你把 URL 字段给到即可。
6. 测试：`test_static.py` 加 `test_preview_serves_deliverable`、`test_preview_rejects_traversal`。

**红线**：复用 7100 单端口（N7），**不起新服务**；预览路由只读。

**验收**：真实运行后浏览器打开 `/preview/<run_id>/index.html` 能渲染；目录穿越请求返回 404。

**涉及文件**：`b04/gateway_runner.py`、`backend/app.py`、`backend/task_api.py`、`tests/test_static.py`

---

### D-3 写入范围校验（6h，第 2 周）

**目标**：产物路径必须落在任务 `write_scope` 内；目录前缀按路径段匹配。

**前置**：D-1 合入。

**步骤**

1. `git switch -c task/d-3-write-scope feat/p2-real-execution`
2. `b04/gateway_runner.py` 抽出 `assert_in_scope(path: str, write_scope: list[str]) -> bool`：
   - `write_scope` 项可以是文件（`app/index.html`）或目录（`app/`、`app`）；
   - 目录按**路径段**匹配：`app/` 匹配 `app/a.py`，**不匹配** `app2/a.py`（吸收自 SE-DPA 契约 §3 的坑）；
   - 拒绝绝对路径与含 `..` 的段。
3. 任一产物越界 → 整个结果 `PATH_OUT_OF_SCOPE` 失败（不是部分成功）。
4. 测试：`test_scope_dir_matches_segments_only`、`test_scope_rejects_parent_traversal`、`test_scope_rejects_absolute_path`。

**验收**：B04 测试 ≥ 672；手测让模型写一个越界文件，运行里看到 `PATH_OUT_OF_SCOPE`。

**涉及文件**：`b04/gateway_runner.py`、`b04/tests/gateway/test_runner.py`

---

### D-4 模型分档路由（6h，第 3 周）

**目标**：规划/复核用高能力模型，逐文件生成用低成本模型；大文件单独提高输出额度。

**前置**：D-1 合入；读 `REFERENCE_PROJECTS_3WAY.md` 2.1 SE-DPA `model_router.py` 的**思路**。

**步骤**

1. `git switch -c task/d-4-model-tiers feat/p2-real-execution`
2. `llm.py` `LLMConfig` 加可选 `tiers: {high: {model, max_tokens}, low: {model, max_tokens}}`，`public()` 脱敏输出；`/api/llm/config` 的 GET/POST 透传。
3. `ModelFileRunner` 按 `request` 的 `capability / role_id` 选档：`规划|复核|集成` → high，其余 → low；文件后缀 `.js/.ts/.py/.html` 且 `max_output_chars` 超阈值 → 用该档的 `max_tokens`。
4. B06 质量门复核（`review_task`）用 high 档——这需要 `task_gate.py` 的调用处能拿到 client，**与 E 协商**，E 没空就先只做执行侧。
5. 前端 `App.tsx` 模型配置区加两档输入——**交给 F 在 F-3 顺手做**，你只定接口。

**红线**：tiers 缺省为空 → 行为与现在完全一致（向下兼容）；密钥不落盘。

**验收**：单测全绿；配置 tiers 后一次运行的事件里能看到不同任务用了不同 `model`。

**涉及文件**：`backend/llm.py`、`b04/gateway_runner.py`、`backend/task_api.py`

---

### D-5 案例重建：L1 → L2 → C3（10h，第 3 周）

**目标**：从手写 C0 走到端到端 **C3**：固定输入、可重跑、可对比。

**前置**：D-1/D-2 合入；B-5 的 C2 规格已入库。

**步骤**

1. `git switch -c task/d-5-cases feat/p2-cases`
2. **L1 四则计算器**：手写最小 spec `fixtures/calculator.spec.json`（3—5 条需求：加/减/乘/除、输入校验），用途是**最快验证链路**，不是产品目标。
3. **L2 待办事项**：`fixtures/todo.spec.json`（8—12 条需求：增删改查、完成状态、过滤）。
4. **C3**：用 `fixtures/campus-activity-signup.spec.json`（B-5 的 C2 规格）+ `--execution-mode runner` 跑完整流程，确认 `work/deliverables/<run_id>/index.html` 可打开、核心交互可用；把 run_id、输入 hash、模型、用量、产物 hash 记进 `docs/CASES.md`（新）。
5. `workflow_runtime/pipeline.py` 加 `--runner` 开关（真实执行时跳过 CI 默认，仅手动触发）；每个案例一个 `pipeline --spec` 命令写进 README 案例表。
6. 主文档 1.5 案例成熟度表更新：calculator/todo → C1（手写但跑通），signup → **C3**。

**红线**：手写 fixture 只作输入测试；C3 的判定标准是"讨论产出 + 真实执行产物 + 可运行网页"三者都有（文档 1.5）。

**验收**：`docs/CASES.md` 存在且每个案例可一键重跑；C3 案例的预览 URL 在 README 可点。

**涉及文件**：`b01-spec-planner/docs/fixtures/{calculator,todo}.spec.json`（新）、`workflow_runtime/pipeline.py`、`docs/CASES.md`（新）、`README.md`

---

### D-6 分支治理：评审旧分支（2h，第 1 周）

评审 **`b04-agent-integration-task-delivery`**（远端 + 本地同名分支）：

```powershell
git log origin/main..origin/b04-agent-integration-task-delivery --oneline
git diff origin/main...origin/b04-agent-integration-task-delivery --stat
```

重点看：该分支是否有 main 没有的 runner/gateway 改动（与 D-1 直接相关！）。有价值的 → 开 `task/d-6-cherry-pick` 分支 cherry-pick 并 PR；没有的 → 群里写一行放弃理由。结论写进主文档 2.1 表。本地分支确认无用后 `git branch -D b04-agent-integration-task-delivery`。

---

## 四、你的每周节奏

| 周 | 本周交付 | 周五前合入 |
|---|---|---|
| 1 | **D-1 最小版**（runner 能出文件、失败不伪提交）、D-6 评审 | `feat/p2-real-execution` → `integration` |
| 2 | D-2 预览、D-3 写入范围 | 同上 |
| 3 | D-4 分档、D-5 案例重建 | 两条功能分支 → `integration` |
| 4 | 配合 E-5 接证据链；缓冲 | — |

**每次开工**：主文档 0.1 五步。**每日**：和 C 对"`app.py` 今天谁动"。**每周中**：功能分支 `rebase origin/main`。

## 五、你的验收命令速查

```powershell
cd b04-agent-integration; python -m pytest -q          # 基线 664 passed, 1 skipped → ≥ 672
cd ..\b02-workflow-agent; python -m unittest discover -s tests   # 113 → ≥ 114
cd ..; python workflow_runtime/run_all_checks.py       # 15/15（默认 mock 模式不应受影响）
# 手测（会产生模型费用，只手动）
cd b02-workflow-agent; python -m backend.app --port 7100 --execution-mode runner
```
