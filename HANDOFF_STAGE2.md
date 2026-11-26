# 第二阶段交接说明（B01—B06 任务编排闭环）

> 本文档交给**下一位 Agent**。阅读顺序建议：先看「一、当前状态」确认起点，
> 再看「四、遗留任务」决定下一步做什么，其余章节作为参考。
>
> 上一版交接文档是仓库根目录的 `B01-B06_项目交接任务说明.md`（**该文件不在 git 仓库内**，
> 是用户桌面上的工作副本）。本文档承接它，不要重复它的背景描述。

---

## 一、当前状态（可直接复核）

### 1.1 代码状态

| 项目 | 值 |
| --- | --- |
| 工作副本 | `D:\School\MultiAgent\work\maw`（git clone，非原始工作目录） |
| 当前分支 | `feat/second-stage-closed-loop` |
| 本地 HEAD | `7e4093d` |
| 远端 `main` | `1d918c4` |
| 远端 `integration` | `1d918c4` |
| 工作树 | 干净（0 个未提交文件） |

本地 HEAD 比远端 tip 少一个 merge commit，这是正常的（feature 分支合入后未快进）。

### 1.2 提交历史（本次新增 4 个 commit）

```text
7e4093d test: verify the 11 acceptance criteria instead of asserting them
28a3125 fix(b01): make fixture plan regeneration byte-identical
2e13cc3 docs: record second-stage status, remaining work and verification
20d424c feat: close the B01-B06 second-stage task-orchestration loop
9fa1519 docs: explain generic task runtime        ← 接手时的 main
```

`1d918c4` 是 `main` 上的 merge commit，内容等价于 `7e4093d`。

### 1.3 CI 状态

`main` 与 `integration` 的 tip `1d918c4` 上：

```text
Project checks      | main        | completed/success
Integration checks  | integration | completed/success
Project checks      | integration | completed/success
```

### 1.4 测试与检查结果（本轮实测）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| B01 | `cd b01-spec-planner; python -m pytest -q` | **43 passed** |
| B02 | `cd b02-workflow-agent; python -m unittest discover -s tests` | **113 tests OK** |
| B03 | `python -m pytest b03/b03_implementation -q` | **37 passed** |
| B04 | `cd b04-agent-integration; python -m pytest -q` | **664 passed, 1 skipped**（docker） |
| B06 | `cd b06-quality-consensus; python -m pytest -q` | **75 passed** |
| 跨块闭环 | `python -m pytest workflow_runtime/test_closed_loop.py -q` | **13 passed** |
| 契约一致性 | `python workflow_runtime/verify_contracts.py` | **6/6 通过** |
| 最终验收 | `python workflow_runtime/verify_acceptance.py` | **13/13 通过** |
| 全量 | `python workflow_runtime/run_all_checks.py` | **15/15 步骤通过** |
| 前端 | `npm run build` / `npm run lint` | 构建成功 / **0 warning 0 error** |
| 前端 UI | `node tests/ui_smoke.mjs http://127.0.0.1:7100` | **35 项检查通过** |

> 注意：B02 当前为 110 项；本轮新增 3 项 B05 构建资源与单端口回退测试。

---

## 二、做了什么（按工作块）

### 2.1 先确认了交接文档要求的第一件事

原交接文档说「上次推送 workflow_runtime 被中断，要先确认远端是否存在」。
实测结果：

- `workflow_runtime` **已在 `main`**（`9fa1519` 就有）；
- 但 **不在 `integration`**。

已通过把 feature 分支合入 `integration` 补齐，现在两者一致。

### 2.2 新增/修改文件清单

**新增（38 个）**

```text
docs/TASK_ORCHESTRATION.md                        跨块接口契约（最重要，先读这个）
docs/STAGE2_STATUS.md                             完成项/设计决定/遗留项

b01-spec-planner/src/b01/spec_input.py            通用规格输入（D12）
b01-spec-planner/src/b01/dynamic_planner.py       动态计划（D13/D14）
b01-spec-planner/tests/test_spec_input_and_dynamic_plan.py
b01-spec-planner/docs/fixtures/                   6 个 fixture（见 2.3）

b02-workflow-agent/backend/task_orchestrator.py   编排状态机（D15/D16）
b02-workflow-agent/backend/task_api.py            编排 HTTP 接口（D17）
b02-workflow-agent/tests/test_task_orchestrator.py
b02-workflow-agent/tests/test_task_api.py

b03/b03_implementation/task_state.py              运行/状态/尝试/事件/检查点（D18/D19）
b03/b03_implementation/tests/test_task_state.py

b04-agent-integration/src/b04/gateway.py          统一执行 Gateway（D21/D22/D23）
b04-agent-integration/tests/gateway/test_gateway.py

b06-quality-consensus/multiagent_quality/task_gate.py  质量门（D27—D30）
b06-quality-consensus/tests/test_task_gate.py

frontend/src/api/taskRunApi.ts                    真实接口适配（D26）
frontend/src/hooks/useTaskRun.ts                  轮询与错误处理
frontend/src/components/TaskDetailPanel.tsx       任务详情面板（D25）
frontend/src/data/simulationRuns.ts               模拟数据源加载
frontend/src/data/taskRunFixture.json             真实编排器产物（约 280 KB）
frontend/tests/ui_smoke.mjs                       无头浏览器冒烟（35 项）
frontend/tests/screenshots.mjs                    截图脚本
frontend/tests/live_shot.mjs                      真实接口联调截图

workflow_runtime/bootstrap.py                     跨块装配 WorkflowStack
workflow_runtime/pipeline.py                      四个演示场景
workflow_runtime/cli.py                           python -m workflow_runtime 入口
workflow_runtime/verify_contracts.py              契约一致性检查
workflow_runtime/verify_acceptance.py             最终验收 13 项逐条核验
workflow_runtime/run_all_checks.py                一键全量验证
workflow_runtime/test_closed_loop.py              跨块闭环测试
workflow_runtime/make_frontend_fixture.py         从真实编排器生成前端 fixture
```

**修改（31 个，主要项）**

```text
README.md                                 重写：第二阶段能力表、双数据源说明
.github/workflows/integration.yml         新增闭环验证步骤 + tsc 检查
.github/workflows/project.yml             新增必需文件清单 + 拒绝 Windows 非法路径
.gitignore                                忽略 work/、node_modules/、*.db
b01-spec-planner/src/b01/{cli,task_planner,plan_validator,baseline,design}.py
b02-workflow-agent/backend/app.py         新增任务编排路由 + CORS
b03/b03_implementation/blackboard.py      VALID_STATES 扩到九态
b06-quality-consensus/multiagent_quality/__init__.py
frontend/src/{App.tsx,App.css,types/task.ts,constants/status.ts,components/TaskNode.tsx}
各块 README（b01/b02/b03/b06/frontend/workflow_runtime）
docs/INTEGRATION.md
```

### 2.3 校园案例降级为 fixture 的证据

| fixture | 格式 | 生成任务数 |
| --- | --- | --- |
| `campus-lost-found.spec.json` | JSON | **24** |
| `lab-equipment-loan.spec.md` | Markdown | **11** |

任务数量由规格推导，不是固定 T01—T11。这是「通用规格输入」最直接的证明。

---

## 三、关键设计决定（改代码前必须先理解）

这些决定都有测试保护，**改动前请先看对应测试**。

### 3.1 唯一状态写入者

只有 **B02** 修改任务状态。B04 只返回执行结果，B06 只返回判定与事件。

因此事件流里 `TASK_ACCEPTED` 等状态事件的 `producer` **恒为 `B02`**；
B06 的结论体现在 `payload.gate`（`{"gate":"B06","decision":"ACCEPT",...}`）
与独立的 `DEFECT_CREATED` / `DEFECT_CLOSED` 事件里。

测试：`workflow_runtime/test_closed_loop.py::test_b06_verdict_is_traceable_in_acceptance_event`

### 3.2 哈希格式必须跨块一致

B04 `SHA256_PATTERN` 与 B06 `SHA256_PATTERN` 都是 `^[0-9a-f]{64}$`。

这曾是真实 bug：B04 只校验「非空字符串」，导致执行通过、验收必然拒绝。
`candidate_commit` 同理，两边都是 `^[0-9a-f]{7,40}$`。

### 3.3 缺陷单点登记 + 可关闭

- 每条阻断 finding 只在 `_open_defects_for_findings` 登记**一次**；
- 去重键是 `(code, ref)`，不是 `(code, message)`——否则同一违规换个措辞会重复登记；
- 缺陷编号 `D-<task>-A<attempt>-NNN`，**跨尝试唯一**，回放时能区分新旧；
- 当本次未再复现同一 code 时发 `DEFECT_CLOSED`（`resolution: "evidence_revalidated"`）。

最后一条尤为关键：**没有它，任务被一次旧缺陷永久卡死，重试预算全部浪费**。

### 3.4 每个状态变化都必须有事件

包括 `WAITING_DEPENDENCY` 和重试后的 `RETRYING→READY` 回队。
为此新增了事件类型 `TASK_WAITING_DEPENDENCY`（在 `EVENT_TYPES` 与 `EVENT_TO_STATE` 里）。

没有它，运行中途 `replay()` 会与快照不一致。

### 3.5 只读查询不写状态

`ready_tasks()` 是**纯计算**，不产生事件。要真正推进依赖必须调用 `step()`。

### 3.6 模拟与真实严格分离

- 模拟数据源：`frontend/src/data/taskRunFixture.json`，由**真实编排器**跑出来，不是手写；
- 真实数据源：轮询 B02 的 `/api/task-runs/{id}` 与 `/dag`；
- **真实接口失败时显示错误并清空节点**，绝不静默回退成模拟数据。

### 3.7 fixture 必须可逐字节复现

`run_checks.py plan` 会对比规格哈希：规格没变则**沿用**原 `plan_version` 与
`generated_at`。只有规格真的改了才递增版本、刷新时间戳。

因此 `run_all_checks.py` **不要**传 `--previous-plan` 指向不存在的文件——
那会被当成新区划而递增版本，每次运行都产生无意义 diff。

---

## 四、遗留任务（下一步做什么）

按优先级排列。前两项是真正的能力缺口，其余是细节。

### P0-1　接入 B04 真实 runner（未完成）

**现状**：`b04/gateway.py` 只有 `RunnerTaskExecutor` 适配层，构造时要求注入
`runner_callable(request) -> dict`。仓库内**没有任何真实实现**，
`AgentRunner` 只出现在注释里。所有演示与测试都用 `MockTaskExecutor`（`simulated=True`）。

**要做的**：

1. 实现 `runner_callable`：把 §5 的 `TaskExecutionRequest` 转成 B04
   `AgentRunner.invoke_agent` 需要的 envelope；
2. 等待终态，把 manifest 转成 §5 的 `TaskExecutionResult`；
3. 在 `task_api.default_stack()` 里用 `TaskExecutionGateway(mode="runner", runner_callable=...)` 替换 mock。

**参考**：`b04-agent-integration/src/b04/agent_runner/contracts.py`（envelope 结构）、
`tests/agent_runner/support.py`（`execute(runtime)` 的用法）。

**风险**：B04 envelope 需要 `lease_ref`、`budget_ticket_ref`、`control` 上下文等受控字段，
需要读 `agent_runner/testing.py::configure_runtime` 才能构造正确。

### P0-2　B06 签名证据接入执行链（未完成）

**现状**：`evidence.check_evidence` 的 HMAC 校验、`runner.run_suite` 的受控执行都已实现并有测试，
但管线里的 mock 执行器**不产生签名证据**。也就是说当前是「结构化证据」，不是「可信证据」。

**要做的**：让 B04 的测试结果走 B06 的受控 runner 签名，B02 在验收时把
`check_evidence` 接进去（而不是只做 `review_task` 的字段检查）。

**注意**：签名密钥不能进入模型环境，见 `b06/README.md` 的「证据边界」。

### P1-1　B05 运行报告导出参数为空（未完成）

**现状**：`frontend/src/App.tsx:191`

```tsx
<button onClick={() => exportRunReport(tasks, [], [], buildExportContext())}>运行报告</button>
```

`logs` 与 `acks` 传的是空数组。

**要做的**：把 `useTaskRun` 返回的 `events` 映射成 `export.ts` 需要的 `LogEntry`
再传入。契约见 `exportRunReport(tasks, logs: LogEntry[], acks: AckEntry[], ctx)`。

### P1-2　B02 对计划只做最小校验（待你决定）

**现状**：`validate_plan_document` 只检查编号唯一、依赖存在、无环、版本字段非空。
计划缺 `input_snapshot` 时能载入，运行时带空字符串进每个事件。

这一行为被写成 **characterization 测试**（`test_plan_without_input_snapshot_is_accepted_with_empty_snapshot`），
即「记录现状」而非「认定正确」。

**待决策**：契约 §2 把 `input_snapshot` 标为必填。若要求硬性拒绝，
应在 `validate_plan_document` 里补校验，并改该测试。**这个决定需要用户确认**。

### P1-3　开发依赖 npm audit 提示（未处理）

`frontend` 的 devDependencies 有 5 个 high 提示（上游模板依赖链），
**生产依赖无漏洞**。`npm ci` 时会打印，CI 不受影响。是否处理取决于是否愿意承担升级风险。

### P2-1　B05 未使用的遗留文件

`frontend/src/components/CaseSamples.tsx`、`frontend/src/data/mockTasks.ts`、
`frontend/mock-server.js` 在新 App 中已无引用（`TaskGraph`/`TaskDetailPanel` 取代）。

保留是因为它们仍可用于讨论流程视图的历史对照。若要精简可删除，
但需确认 `export.ts` 的 `LogEntry` 类型来源（它在 `useTaskWebSocket` 里）。

---

## 五、遇到的问题与解决（排查手册）

### 5.1 GitHub 直连不稳定（**下次还会遇到**）

**现象**：`git push` / `ls-remote` 报
`Recv failure: Connection was reset` 或
`Failed to connect to github.com:443 after 21098 ms`。

**原因**：本机 DNS 把 `github.com` 解析到不可达地址（实测解析出过
`57.155.223.240`、`20.6.7.17`），而可用 IP 会随时间漂移。

**解决**：用 `--resolve` 强制指定 IP：

```powershell
git -c http.curloptResolve=github.com:443:<可用IP> push origin <branch>
```

**本轮实测可用过的 IP**（不保证长期有效，需现测）：
`20.200.245.247`、`4.208.26.197`、`140.82.113.3`、`140.82.112.3`。

**探测哪个 IP 可用**：

```powershell
curl.exe -sS --resolve "github.com:443:<IP>" -o NUL -w "%{http_code}" `
  --max-time 15 "https://github.com/soverwth/multi-agent-workflow.git/info/refs?service=git-upload-pack"
# 200 = 可用
```

**几点经验**：

- `api.github.com` 与 `codeload.github.com` 走的是**不同 IP**，它们通常正常；
  因此「API 能通但 git 不通」是正常现象，不代表网络全断。
- 不可用 IP 通常表现为 15 秒左右超时，可以快速轮换。
- 本机 `hosts` 文件**无写权限**（非管理员），不能用改 hosts 的办法绕过。
- 本机**没有**配置代理（`ProxyEnable=0`，7897 端口未监听）。

**token 位置**：在 Windows 凭据管理器里，可用
`"protocol=https`nhost=github.com`n`n" | git credential fill` 读出。

### 5.2 PowerShell 的坑（会反复咬人）

| 坑 | 症状 | 规避 |
| --- | --- | --- |
| heredoc | `python - <<'PY'` 报「缺少文件规范」 | 把脚本写成临时 `.py` 文件再执行 |
| `Set-Content` 破坏 UTF-8 | 中文变成 `闇€姹?` | **永远用 `write`/`edit` 工具改文件，不要用 PowerShell 重写** |
| `Get-Content -Raw` 参数位置 | `-Raw:Select-Object` 报错 | 用 `-Raw` 单独使用 |
| 输出 mangling | 控制台中文乱码 | 只是显示问题，加 `$env:PYTHONIOENCODING="utf-8"` |

**5.2 的教训是真实的**：我曾用 PowerShell 的 `Set-Content` 处理
`b01-spec-planner/src/b01/spec_input.py`，把整个文件的中文注释写坏；
又曾用 PowerShell 脚本批量删除 `@unittest.skip(` 行，因为只删了首行而留下
多行字符串残骸，把 `tests/test_task_orchestrator.py` 弄成语法错误。

**恢复方式**：该文件当时**未被 git 跟踪**（新建文件），
`git checkout --` 无法恢复，只能手工修复损坏的 docstring 段落。

**结论**：新增/修改文件一律走 `write` / `edit` 工具。

### 5.3 子 Agent 并行写测试踩到真实 bug（这是收获，不是问题）

我派了一个 subagent 只写测试、不许改源码。它找到 6 个真实缺陷，
我全部修复并**取消了它留的 skip**：

| # | 缺陷 | 修复 |
| --- | --- | --- |
| 1 | B04 接受非十六进制 `sha256` | 新增 `SHA256_PATTERN`，校验 artifacts/logs/test_results |
| 2 | B06 同一违规登记两条缺陷 | 缺陷登记收敛到 `_open_defects_for_findings`，键改 `(code, ref)` |
| 3 | B02 `emit=False` 未生效，只读查询写事件 | `_refresh_dependencies` 真正读取该参数 |
| 4 | B02 状态迁移不发事件（`WAITING_DEPENDENCY`、`RETRYING→READY`） | 新增 `TASK_WAITING_DEPENDENCY`；回队补 `TASK_READY` |
| 5 | B02 发出缺 `candidate_commit` 的事件 | 缺提交引用按失败处理，不发事件 |
| 6 | B06 永不关闭缺陷，任务无法恢复 | 未复现即发 `DEFECT_CLOSED` |

**注意**：修复 3/4/5/6 改变了事件序列，`test_bounded_retry_with_budget_one_dispatches_twice_then_fails`
的期望事件列表因此多了一个 `TASK_READY`——这是**正确的新行为**，不是回归。

### 5.4 CORS（联调时才暴露）

B02 与 Vite 前端不同端口，浏览器跨源请求被拒。
`test_task_api.py` 里的纯 Python 测试**发现不了**（不受同源策略限制），
是用 Chrome 真实加载页面时才暴露的。

已加白名单（只允许 `127.0.0.1` / `localhost` 任意端口）+ `do_OPTIONS` 预检。

**教训**：涉及浏览器的集成问题必须用真实浏览器验证，HTTP 客户端测试不够。

### 5.5 验收脚本第一版是假的

我最初把「CI 通过」硬编码成 `record("CI 通过", True, ...)`——
那不是检查，是自我宣称。

改成真实核验后它**立刻失败**了，原因是「工作树有未提交改动」。
这恰好证明它在工作。现在的判定条件是：

1. 工作树干净；
2. 本地 HEAD 已合入 `main` 与 `integration`；
3. 两分支 tip 一致；
4. 该 commit 上**每个** workflow 都 `completed/success`。

无 token 或断网时**报 FAIL 并说明原因**，不静默通过。

### 5.6 run_all_checks 破坏 fixture（已修）

最初 `run_all_checks.py` 传 `--previous-plan docs/fixtures/__none__.json`，
导致每次检查都把已入库 fixture 当新区划递增 `plan_version`。

已移除该参数，并让 `cli.py` 在规格未变时复用原版本号与时间戳。
现在跑完 15 步后工作树保持干净。

---

## 六、如何验证（复制即用）

在 `D:\School\MultiAgent\work\maw` 下：

```powershell
# 一键全量（15 步，实测约 130 秒）
$env:PYTHONIOENCODING="utf-8"
python workflow_runtime/run_all_checks.py

# 最终验收 13 项（含真实 CI 查询，需要 token）
$env:GITHUB_TOKEN="<从 git credential fill 读取>"
python workflow_runtime/verify_acceptance.py

# 只要不联网的部分
python workflow_runtime/verify_acceptance.py --skip-ci
```

闭环演示（四个场景）：

```powershell
python -m workflow_runtime pipeline --scenario success    # 全部通过
python -m workflow_runtime pipeline --scenario retry      # 有限重试→阻塞
python -m workflow_runtime pipeline --scenario blocked    # 执行阻断传播
python -m workflow_runtime pipeline --scenario evidence    # 缺证据被驳回
```

前端（正式集成运行只使用 B02 的 7100 端口；需要真实浏览器验证，不要只靠 build 通过）：

```powershell
# 构建 B05，然后启动唯一的 B02/B05 服务
cd frontend; npm ci; npm run build
cd ..\b02-workflow-agent; python -m backend.app --host 127.0.0.1 --port 7100

# 另开终端执行冒烟
cd frontend; node tests/ui_smoke.mjs http://127.0.0.1:7100
```

**注意**：`npm run dev`（5173）仍可用于前端热更新，但正式演示和验收使用
`http://127.0.0.1:7100/`，避免 B02 与 B05 分别占用端口。

---

## 七、给下一位 Agent 的建议

1. **先读 `docs/TASK_ORCHESTRATION.md`**，那是唯一的跨块契约。
   不要从各块源码反推接口，容易漏字段。
2. **不要重新审查 B02—B06 的既有实现**（原交接文档明确要求）。
   除第四节列出的遗留项外，其余已验证可用。
3. **改任何状态机代码前，先跑 `test_task_orchestrator.py`**。
   那里有一条测试会逐字断言事件序列，改动会被立刻发现——这是设计意图。
4. **改文件只用 `write`/`edit` 工具**（见 5.2）。
5. **涉及浏览器的改动必须用 `ui_smoke.mjs` 验**（见 5.4）。
6. **声明「完成」前跑 `verify_acceptance.py`（不带 `--skip-ci`）**。
   它是唯一能证明 CI 与远端状态一致的检查。

---

## 八、本次会话未能留下的东西

诚实记录，避免下一位误以为它们存在：

- **没有**在仓库里保留 GitHub 推送的绕过脚本（`push_helper.py` 等）。
  它们只是本地运维工具，用完即删，避免把网络绕过手段混进项目。
  需要时按 5.1 自行重建。
- **没有**真实模型调用记录。所有执行都是 mock，`simulated=True` 如实标注。
- **没有**在前端做过真实接口的自动化回归测试。
  `live_shot.mjs` 是手动联调脚本，需要先启动 B02 并创建运行，未纳入 CI。
- **截图**在 `work/shots/`（已被 `.gitignore` 忽略），未入库。
  如需交付截图，用 `node tests/screenshots.mjs` 重新生成。

---

## 九、文件位置速查

| 内容 | 路径 |
| --- | --- |
| **本文档** | `D:\School\MultiAgent\work\maw\HANDOFF_STAGE2.md` |
| 上一版交接文档 | `D:\School\MultiAgent\B01-B06_项目交接任务说明.md`（**不在 git 仓库内**） |
| 工作副本（git clone） | `D:\School\MultiAgent\work\maw` |
| 跨块契约（最重要） | `work/maw/docs/TASK_ORCHESTRATION.md` |
| 完成项/遗留项记录 | `work/maw/docs/STAGE2_STATUS.md` |
| 全量验证入口 | `work/maw/workflow_runtime/run_all_checks.py` |
| 验收核验入口 | `work/maw/workflow_runtime/verify_acceptance.py` |

> 原始工作目录 `D:\School\MultiAgent` 下有大量 `work/` 子目录（早前的 audit、
> 解压、渲染过程产物）。**它们不是当前代码**，不要在那里改文件。
> 一切改动都在 `work/maw` 这个 git clone 里进行，提交后推送到 GitHub。

