# B04 agent_runner 实现与测试说明

归档说明：本文保留 runner 首次交付时的 v0.2.0 阶段记录；本次交付为当前源码快照，项目元数据为 0.3.0。最新跨模块测试与实验边界见 [实验验收说明](<./B04_实验验收说明.md>)，历史阶段数字不作为当前全量结果。

实现依据为 [B04 协议 v0.2.1](<./B04_任务执行协议设计.md>)、[agent_runner 设计 v0.1.1](<./B04_agent_runner模块设计.md>) 以及已实现的 model_adapter。Python 分发包更新为 `0.2.0`；运行协议仍为 `b04.exec.v0.2`，模型契约仍为 `b04.model.v0.1`。

本次交付可运行的 runner、SQLite 参考存储、模型模块桥接、真实 Git 候选读取适配器、模拟服务、示例和单元测试。runner 不包含产品规划规则、全局调度状态机或独立接受流程。

## 1 运行

需要 Python 3.11+、项目依赖；Git 相关测试还需要本机 Git。项目根目录执行：

```powershell
python -m pip install -e ".[test]"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -u -m pytest -q
python examples/agent_runner_demo.py
```

已有依赖时，pytest 配置自动从 src 导入。没有安装包而需运行示例时，先设置 `$env:PYTHONPATH = (Resolve-Path .\src).Path`。

示例展示合法 PM 调用、重复派发、上下文装配、一次模型调用、一次规定自检、实际候选对象／Manifest 登记、原子终结及事件投递。预期为 candidate_submitted、self_check_status=passed、review_status=pending，实际模型发送 1 次；这些是 mock 运行证据，不表示产品计划已接受。

本次测试未访问真实模型或远端服务。Windows Codex 沙箱的 asyncio 本机 socketpair 会挂起，因此测试在允许本机通信的环境运行。测试中的 Git 初始化和提交仅操作 pytest 创建的临时仓库，并关闭提交 hooks 与 GPG 签名；runner 的 Git 适配器只读提交内容，不执行生成代码、不创建提交、不合并分支。

## 2 代码和接入端口

| 文件 | 责任 |
| --- | --- |
| [runner.py](<./src/b04/agent_runner/runner.py>) | 接收、受控执行循环、停止、恢复及提交协调 |
| [contracts.py](<./src/b04/agent_runner/contracts.py>) | 信封、工具、Manifest、终结及回执的可执行契约，共享身份复用 model_adapter |
| [context.py](<./src/b04/agent_runner/context.py>) | 冻结配置、输入状态与版本、十四项变量和安全消息装配 |
| [artifacts.py](<./src/b04/agent_runner/artifacts.py>) | 真实产物、基础 schema、自检证据、内容变更及 Canonical Manifest |
| [store.py](<./src/b04/agent_runner/store.py>) | SQLite 原子接收、执行 fencing、操作检查点、内容、终结 CAS 和 Outbox |
| [outbox.py](<./src/b04/agent_runner/outbox.py>) | 原事件投递、独立额度及五种终结拒收对账结论 |
| [runtime.py](<./src/b04/agent_runner/runtime.py>) | 控制提供器、实际 model_adapter 桥接、传输额度和真实 Git 读取 |
| [ports.py](<./src/b04/agent_runner/ports.py>) | B02/B03、模型、工具、代码来源的集成接口 |
| [testing.py](<./src/b04/agent_runner/testing.py>) | 明确标识的模拟 Orchestrator／工具服务和离线装配夹具 |
| [示例](<./examples/agent_runner_demo.py>) | 完整可运行的 PM mock 闭环 |

ToolExecutorPort 提供 execute_tool、get_operation、stop_operation。它和模型桥接都提供受控 read_result：这是 B03 结果记录读取能力，用来解析 Snapshot.result_ref，不是再次执行调用。ModelAdapterBridge 直接复用现有 ModelAdapterFacade、授权、预算及持久结果，没有改写 model_adapter。

工具执行器仍通过端口接入，未将测试用 ScriptedToolExecutor 当作正式 tool_executor。模拟 write_file 会在已注册的隔离目录真实写入并核验字节；模拟检查器会保存实际生成的检查报告，不能作为真实产品测试已运行的证明。

## 3 入口和控制

```python
from b04.agent_runner import AgentRunner

runner = AgentRunner(
    store=b03_store, catalog=frozen_catalog,
    controls=trusted_control_provider, authority=authority_service,
    model_adapter=model_port, tool_executor=tool_executor_port,
    event_sink=b02_event_sink,
    control_budget=control_budget_service,
    transport_budget=transport_budget_service,
    source=source_port,  # 代码任务需要
)

receipt = await runner.invoke_agent(envelope)
snapshot = await runner.get_invocation(invocation_ref)
stop = await runner.stop_invocation(invocation_ref, "requested_stop")
catalog = await runner.describe_capabilities(catalog_ref)
```

四个设计入口均为 async。invoke_agent 在持久接收后返回，并调度本地 worker；回执表示已接受，不表示任务通过。auto_start=False 可接入外部 worker 队列，接受后仍需安排执行。

wait_invocation、flush_events、recover_invocation 是实现层的等待、投递与恢复辅助方法；查询不会隐式重新执行。wait_invocation 超时不会取消正在运行的 worker。

ControlProvider 根据完整 InvocationRef 返回可信 RunnerControls：model、tool、observe、report、cleanup 五个 CallControl 和独立 transport_ticket_ref。前两者使用 execute purpose，分别绑定模型／工具票据；其余使用各自独立 grant。所有上下文绑定原调用、快照、服务身份和控制代际，不能通过请求或模型文本自授。控制、模型及工具服务必须共同实施实际授权。

候选写入与发布验证 execute 授权、输入、当前执行权、停止标志及执行期限。失败、阻塞、停止和投递记录使用 report／cleanup，旧执行租约失效不阻断原调用的诊断；这些授权不能生成新业务结果。observe 不能写检查点、诊断或产物。

## 4 冻结配置与上下文

InMemoryFrozenCatalog 是参考配置后端。可信配置路径注册的 bundle 包含 agent、workflow、input_contract、output_contract、template、tool_config、schemas、input_refs 和 profile。具体可运行结构见 testing.build_demo_runtime；真实 B03 可实现 FrozenCatalog 端口读取既有版本化对象。

参考快照的哈希覆盖冻结信封（排除其自身 input_snapshot_sha256）及全部 bundle 定义哈希。schema、工具绑定、模板、输出契约或目标变化都不能在同版本下静默生效；重复派发指纹不包含动态时间和剩余额度。

输入逐项核验项目、引用、实际字节 SHA-256、状态及 selector。评审契约可明确允许 candidate；开发代码必须有 task_id、已接受的计划、真实仓库基线及隔离工作区。输入状态在接受后变化会阻塞准备，不能偷换“最新版本”。

参考存储的读取范围按原调用和 read_scope_ref 注册，默认只包含冻结输入；额外检索引用必须由可信配置显式登记。相同项目也不能任意读取未授权产物。

十四项变量全部绑定：invocation_context、goal、agent_definition、input_contract、output_contract、context_items、spec_context、plan_context、capability_catalog、tool_descriptions、write_scope、limits、required_checks、feedback_context。模板不执行表达式；system 仅放可信模板和变量位置引用，完整值在 user 的 JSON 数据区中序列化。产品内容中的模板语法不会再次渲染或提升权限。

profile 决定上下文字节上限、输出 token 上限、工具时限、生成参数、工具选择、允许纠正次数、重冻结上限和环境引用。必要上下文超限会阻塞，不静默删除、截断或换模型。普通配置默认不纠正输出；显式允许时使用新模型编号并受既有额度和原 attempt 期限约束。

## 5 幂等、执行与工具

幂等登记绑定项目、run、invocation、attempt、dispatch 和信封指纹；同键异内容或同项目幂等别名冲突拒绝，不覆盖原记录。SQLite 事务保证只有一个有效执行 owner。已有终结返回原回执，不重复生成或检查。

每个模型请求、原始工具意图映射、归一 ToolRequest 都先持久化，再登记 called 意图，然后调用端口。每次新生成的 model_call_id／call_seq 唯一，工具 operation_id 与原意图稳定关联。进行中只查询原引用并读取既有结果；called 但结果未知时不盲目再发。

模型调用按设计先 validate_request，再 generate。实际 Result 的身份、快照、模式、模型配置、状态与结构均核验。内部请求错误保留 MODEL_ 原因并转换成 EXEC_MODEL_ERROR，不修改已接受回执或生成 EXEC_INVALID_ENVELOPE 事件。模型自称成功不影响编排状态。

工具绑定固定公开名、版本、两种参数 schema 和哈希。模型来源需要真实 model_call_id／tool_call_id；自检来源只携带 check_ref，不伪造模型意图。执行前校验 schema、授权范围、命令 profile、时限和额度。

inline-text-to-draft@1 当前明确支持 UTF-8：先持久化原意图映射，再在 draft_namespace_ref 下保存不可变实际字节，取得 content_ref／sha256／size_bytes，构造执行参数并二次校验。不会静默转换换行、BOM 或目标。草稿保存成功不表示文件已经写入。

反馈包含完整 ToolFeedback：身份、绑定、status、result_code、payload、exit_code、stop_status、side_effects_state、error、引用、变更和 truncation。默认不截断数据；上下文超限则明确停止。unknown、in_progress、停止未确认不能作为已完成工具消息发起下一轮。工具错误的完整结果保存在受控引用，事件只带必要错误元数据，避免把 stdout 或错误正文公开。

runner 只限制允许的调用次数并转交已有票据，不重复扣账。model_adapter 和 tool_executor 分别负责实际执行的原子预算预留／结算，父 invocation 消耗与未知预留不能因重派重置。自检通过同一工具端口计入工具额度。传输使用独立有限票据，不消耗模型发送数。

## 6 自检、产物和终结

产物来源支持 model_text、model_json 的声明 JSON Pointer、repository_bundle 和 tool_report。种类、数量、media_type、schema 及命名空间由 output_contract.slots 决定，不能从模型输出新增类型或覆盖身份。保存后核验真实字节、哈希、大小及基础 schema。

test_report 必须来自实际已完成工具操作的 report_ref 及证据，不能由模型预测 passed。计划、文档和评审内容可来自模型草稿，但保存为实际对象后仍为 pending 候选。

GitWorkspaceSource 在 PREPARING 核验注册工作区、仓库归属、真实基线、祖先关系和干净状态；不要求此时已经生成新文件。最终从真实 candidate_commit 的 Git blob 读取所声明文件，检查实际变更范围，不用模型提供的提交号冒充结果。源代码 bundle 是含文件路径、哈希及 base64 字节的 JSON 对象。

基础交付失败不能提交合规候选。专业自检依赖注册的规则与工具，报告必须对应同一组产物引用／哈希、输入快照、环境、预期和实际结果。失败记录 failed；未运行或证据不足记录 not_run／incomplete，同时列出所有缺失项。基础结构有效时可提交这样的候选，B06／B02 外部门槛仍不能放行。

检查后重新核验内容。已提交代码在检查中变化时，旧证据失效，按受限次数重新冻结、检查；脏工作区、持续变化或不可读取内容不能发布。Manifest 内嵌协议全部必需摘要，execution_record_ref 不替代字段。参考存储的 read_execution_record 按 observe 授权解析该引用，返回真实检查点、操作、终结与追加事件日志，不暴露执行 owner token。

终结提交以稳定 submission_id 执行原子 CAS，一次 attempt 最多一个 candidate_submitted／execution_failed／execution_blocked／execution_stopped。参考 B03 还核验 Manifest 的实际产物、命名空间、冻结输入、输出契约和规定检查证据，防止摘要伪报 passed。

提交超时、回执损坏或响应丢失先查询原 submission_id。确认已提交只复用记录；无法确认则保持 SUBMITTING 和 commit_unknown，不补发另一终结。明确没有提交且执行授权失效时，才可沿用原 submission_id 按 report 保存诊断。

## 7 停止、恢复与事件

停止先持久化意图，阻止新业务动作，再对原模型／工具引用核对。confirmed 必须属于正确原资源并带可核对证据，不能用别的操作回执或本地取消充当证明。全部确认后才产生 execution_stopped；未知停止保留 stop_unconfirmed，已有终结只追加清理记录。

普通恢复需要权威控制服务确认旧 worker 不再有效并核发更高代际，旧 owner 被存储 fencing 拒绝。已持久化模型、工具和检查结果复用；未知发送查询／停止，不重做。已有终结仅补投递；SUBMITTING 的幂等提交可直接核对／重试，不开启新的模型循环。模板、输入或模型更换仍由 B02 派发新 attempt。

Outbox 的 event_id、event_seq 由存储事务分配，重传保持原内容。recorded／stale 仅是投递和历史结论，不是独立验收。终结 rejected 调用独立 reconcile_terminal，五种 resolution 分别记录补记、历史关闭、原事件重传、B02 新 attempt 决定或人工阻塞；保留原事件和 decision_ref。非终结拒收不伪造 submission_id。

通道或对账额度耗尽保留待发送／拒收记录，并登记责任方 B02 的待核对事项。不会重新执行 Agent，也不会由 B04 直接修改全局 SUCCEEDED、接受记录或下游依赖。

## 8 验证范围

2026-11-16 的最终联合回归结果为 **220 passed in 21.38s**：其中 agent_runner 84 项，原 model_adapter 136 项全部保持通过。Python 字节码编译、离线 runner 示例及 `0.2.0` wheel 构建另行检查。

离线示例实测为：重复派发不重跑、实际模型发送 1 次、工具自检 1 次、4 个原始事件成功投递，产物状态为 candidate_submitted／review_status=pending。

单元测试使用真实 ModelAdapterFacade、SQLite 原子存储和隔离 Git 仓库，B02 与专业工具为明确的模拟端口。真实供应商、正式 tool_executor、分布式租约／预算／共享 B03、平台独立质量验收仍需相应服务联调；本次不宣称这些外部模块已实现。

| 设计验收项 | 本次验证 |
| --- | --- |
| AR-01—02 | 合法／无效／重复／冲突派发，PM 无任务图或仓库 |
| AR-03—06 | 十四变量、候选状态、数据角色隔离、读取范围及上下文上限 |
| AR-07—09 | 模型分支、多轮工具、稳定映射、未知结果、原引用查询 |
| AR-10—13 | 基础交付门槛、failed／incomplete、检查后真实 Git 变更、计划／文档／代码／真实工具报告 |
| AR-14—15 | 提交丢响应／坏回执、唯一终结、停止竞态及 Outbox 重传／stale |
| AR-16—17 | 模型／工具／检查／传输额度，超时和停止证明身份 |
| AR-18 | 模型、工具、自检持久结果后的模拟中断及恢复，SQLite 重新打开，未知提交恢复 |
| AR-19—20 | 旧 owner fencing、更高代际恢复，跨产品和自定义角色，mock 不冒充 live |
| AR-21—25 | 独立诊断授权、暂存与完整反馈、in_progress、Canonical Manifest、自检证据再校验及五种拒收对账 |

测试文件位于 [tests/agent_runner](<./tests/agent_runner/test_runner.py>)，分别覆盖基础流程、工具、自检与产物、投递、恢复和边界回归。所有原协议、设计文档、角色模板和 DOCX 均未修改。
