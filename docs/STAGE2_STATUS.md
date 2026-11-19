# 第二阶段实施记录（B01—B06）

记录第二阶段（开发任务闭环）的完成情况、验证方式与遗留项。
工作块字段与接口契约见 [`TASK_ORCHESTRATION.md`](TASK_ORCHESTRATION.md)。

## 一、闭环状态

```text
设计规格输入 → B01 任务分解 → B02 任务编排 → B03 状态持久化
→ B04 Agent 执行 → B06 证据验收 → B05 DAG 可视化 → 集成发布
```

全链路已打通并可一键复现，见 `workflow_runtime/pipeline.py`。

与第一阶段的连接也已补齐：已确认的 B02 R1 可通过 `/api/runs/{run_id}/design-spec`
导出为 B01 设计规格，或通过 `/api/task-runs/from-discussion` 直接创建第二阶段运行。
第二阶段还支持直接提交任意 JSON/Markdown design spec；B05 页面提供生成运行、单步推进和
运行至完成控制。B05 统一工作台还可以在同一页创建第一阶段运行、配置模型 API、查看 design spec
并进入第二阶段。

| 任务 | 内容 | 实现位置 | 状态 |
| --- | --- | --- | --- |
| B01-D12 | 通用规格输入（JSON/Markdown） | `b01/spec_input.py` | 完成 |
| B01-D13 | 动态计划（不固定 T01—T11） | `b01/dynamic_planner.py` | 完成 |
| B01-D14 | 计划快照与追溯表 | `b01/dynamic_planner.py` | 完成 |
| B02-D15 | 开发任务编排（九态、依赖、派发、重试） | `backend/task_orchestrator.py` | 完成 |
| B02-D16 | 任务事件（绑定尝试与版本） | `backend/task_orchestrator.py` | 完成 |
| B02-D17 | 编排 HTTP API | `backend/task_api.py` | 完成 |
| B03-D18 | 任务注册表与执行状态 | `b03_implementation/task_state.py` | 完成 |
| B03-D19 | 断点恢复与事件回放 | `b03_implementation/task_state.py` | 完成 |
| B04-D21 | 统一执行 Gateway（输入输出契约） | `b04/gateway.py` | 完成 |
| B04-D22 | 执行结果结构化返回 | `b04/gateway.py` | 完成 |
| B04-D23 | 真实 runner 适配位 | `b04/gateway.py` | 完成（适配层，需注入真实 runner） |
| B05-D24 | 任务 DAG 展示 | `frontend/src/components/TaskGraph.tsx` | 完成 |
| B05-D25 | 任务详情面板 | `frontend/src/components/TaskDetailPanel.tsx` | 完成 |
| B05-D26 | 真实接口接入与来源区分 | `frontend/src/api/taskRunApi.ts` | 完成 |
| B06-D27 | 任务字段与需求覆盖校验 | `multiagent_quality/task_gate.py` | 完成 |
| B06-D28 | 依赖环与重复产物校验 | `multiagent_quality/task_gate.py` | 完成 |
| B06-D29 | 日志/产物哈希与测试编号 | `multiagent_quality/task_gate.py` | 完成 |
| B06-D30 | 提交引用与版本一致性 | `multiagent_quality/task_gate.py` | 完成 |

### 近期补全

- 第一阶段需求草案支持 OpenAI-compatible API，默认 DeepSeek 配置，并保留无密钥时的领域规则兜底。
- 本地兜底会根据聊天社交、失物招领、设备预约和通用系统生成不同的需求数量与内容。
- B05 增加统一 SE Workflow 工作台、模型配置、第一阶段运行控制和 design spec JSON 查看。

## 二、关键设计决定

1. **单一状态写入者**：只有 B02 改任务状态。B04 返回执行结果，B06 返回判定与事件。
   因此事件流里 `TASK_ACCEPTED` 等状态事件的 `producer` 恒为 `B02`；
   B06 的结论通过 `payload.gate` 与独立的 `DEFECT_CREATED` / `DEFECT_CLOSED` 体现。
   这样既避免同一语义重复成两条事件，又保留了“谁判定的”可追溯性。

2. **哈希格式统一**：B04 `SHA256_PATTERN` 与 B06 `SHA256_PATTERN` 都是
   `^[0-9a-f]{64}$`。此前 B04 只校验“非空字符串”，导致执行通过但验收必然拒绝。

3. **缺陷单点登记**：B06 的每条阻断 finding 只在 `_open_defects_for_findings`
   登记一次，去重键 `(code, ref)`。此前同一违规会被两个检查器各登记一次。

4. **缺陷可关闭**：B06 在“本次未再复现同一 code”时发出 `DEFECT_CLOSED`。
   否则任务被一次旧缺陷永久卡住，重试预算全部浪费在注定被拒的尝试上。

5. **每个状态变化都有事件**：包括 `WAITING_DEPENDENCY` 与重试后的 `READY` 回队。
   此前这两处直接改状态不发事件，导致运行中途 `replay()` 与快照不一致。

6. **只读查询不写状态**：`ready_tasks()` 是纯计算，不产生事件。
   需要推进依赖应调用 `step()`。

7. **模拟与真实严格分离**：B05 的两套数据源共用同一字段结构；
   真实接口失败时显示错误并清空节点，不静默回退成模拟数据。

8. **校园案例只是 fixture**：`docs/fixtures/` 同时提供校园失物招领（JSON）与
   设备借用系统（Markdown）两个规格，任务数量分别为 24 与 11，证明计划是推导而非写死。

## 三、验证方式

```powershell
# 全部工作块 + 跨块闭环（14 个步骤）
python workflow_runtime/run_all_checks.py

# 只跑契约一致性检查（CI 同款）
python workflow_runtime/verify_contracts.py

# 四个演示场景
python -m workflow_runtime pipeline --scenario success
python -m workflow_runtime pipeline --scenario retry
python -m workflow_runtime pipeline --scenario blocked
python -m workflow_runtime pipeline --scenario evidence

# 前端
cd frontend
npm run build && npm run lint
node tests/ui_smoke.mjs http://127.0.0.1:4321
```

最近一次完整检查结果：B01 44 / B02 107 / B03 37 / B04 664（1 项 docker 跳过）/ B06 75 /
闭环 13 项测试通过；`verify_contracts` 6/6；`run_all_checks` 15/15；
前端 build + lint 通过；浏览器冒烟覆盖讨论流程、真实任务接口、响应式布局和错误隔离。

## 四、遗留项

以下不属于第二阶段范围，或需要外部条件，记录在此以免误认为已完成：

1. **B04 真实 runner 尚未接生产模型**。`gateway.py` 提供了 `runner_callable` 注入位与
   结果契约校验，但未在此仓库内构造真实的 `AgentRunner` envelope 与 manifest 转换。
   演示与测试一律使用显式标注 `simulated=True` 的确定性 mock 执行器。

2. **B06 证据签名未接入执行链**。`evidence.check_evidence` 的 HMAC 校验与
   `runner.run_suite` 的受控执行已具备并有测试，但管线的 mock 执行器不产生签名证据。
   接入真实 runner 时要让 B04 的测试结果走 B06 的受控 runner，才能形成真证据链。

3. **B05 控制回执仅在 WebSocket 控制链路中可见**。真实 HTTP 任务编排模式已经把
   `useTaskRun` 的事件映射到运行报告的 `event_logs`；若要把“推进一步/运行至完成”的
   HTTP 回执也写入报告，需要为控制 API 返回值增加前端回执记录。

4. **开发依赖仍有 npm audit 提示**（上游模板依赖，生产依赖无漏洞）。

5. **B02 对计划只做最小校验**（编号唯一、依赖存在、无环），完整校验属 B01。
   计划缺 `input_snapshot` 时运行会带空字符串，当前记录为 characterization 测试，
   未按契约强制拒绝——如需强制，应在 `validate_plan_document` 中补齐。

## 五、GitHub 推送说明

本机 DNS 会把 `github.com` 解析到不可达地址，且可用 IP 随时间变化。
仓库不包含绕过脚本（`push_*_retry.py` 仅作本地工具，未入库），
如需推送可用：

```powershell
git -c http.curloptResolve=github.com:443:<可用IP> push origin <branch>
```
