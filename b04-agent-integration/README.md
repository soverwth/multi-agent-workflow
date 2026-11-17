# B04 运行接入实现与测试

当前包含 `model_adapter`、`agent_runner` 和 `tool_executor`，支持不同产品、Agent 角色和产物的通用运行接入。工具注册、版本、权限、真实文件操作、受控命令、停止和幂等见 [tool_executor 实现与测试说明](<./B04_tool_executor_实现与测试说明.md>)；runner 接口见 [agent_runner 实现与测试说明](<./B04_agent_runner_实现与测试说明.md>)。

独立的校园失物招领 C1 测试产品参考后端位于 `src/b04/reference_backend`，覆盖 T03—T05；接口、运行方式及最新错误映射／U+0000 回归见 [参考后端实现与验收说明](<./B04_T03-T05_参考后端实现与验收说明.md>)。

三模块离线闭环可运行 `python examples/tool_executor_demo.py`：模型使用确定性 mock，文件写入、结构自检和候选提交使用实际模块。命令执行要求可验证的隔离后端，未配置时返回 `TOOL_PROFILE_UNSUPPORTED`。最新联合回归及 Docker 验证范围见工具实现说明；以下 model_adapter 表格保留其最初交付的验证记录。

最新源码全量回归：**592 项通过、1 项可选 Docker 集成测试跳过**（model_adapter 136、agent_runner 84、tool_executor 162、参考后端 210 项通过）。先前通用模块的分发包为 `dist/se_workflow_b04-0.3.0-py3-none-any.whl`。

下文保留 model_adapter 的接口与验证说明。实现依据 [B04 协议 v0.2.1](<./B04_任务执行协议设计.md>) 和 [model_adapter 设计 v0.1.1](<./B04_model_adapter模块设计.md>)。当前分发包版本为 `0.3.0`，运行契约为 `b04.model.v0.1`／`b04.tool.v0.1`／`b04.exec.v0.2`。

下述 model_adapter 提供模型运行接入，支持 PM 规划、不同 Agent 角色、文本、JSON 及工具意图；实际工具执行由 tool_executor 提供，候选提交由 agent_runner 提供。产品任务分解规则和 Orchestrator 状态机由相应上层模块负责，核心代码不依赖失物招领案例。

## 安装与运行

需要 Python 3.11+。本次验证环境为 Windows、Python 3.14.3、jsonschema 4.26.0、pytest 9.1.1。

在项目根目录执行：

```powershell
python -m pip install -e ".[test]"
python -m pip install -r src/b04/reference_backend/requirements.txt
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -u -m pytest -q
python examples/model_adapter_demo.py
```

已有依赖时，可直接 `python -u -m pytest -q`。测试配置自动使用 `src`；未安装包而需运行示例时，先执行 `$env:PYTHONPATH = (Resolve-Path .\src).Path`。

示例使用完整的 mock PM 调用，展示预检、生成、同号去重和查询。预期输出包括 `status=ok`、`duplicate_reused=true`、`actual_sends=1`，不产生业务接受事件或正式任务计划基线。示例中的输入哈希及产品规格是演示夹具；实际值由 runner／B03 提供。

测试使用本地 mock、实际文件／SQLite／临时 Git，以及固定 Windows 进程助手，无真实模型服务或密钥。可选 Docker 隔离集成测试只使用显式配置的本地引擎和已有固定镜像，不启动 Docker、不拉取镜像。当前 Codex Windows 沙箱中 asyncio 的本机 socketpair 会挂起；测试在允许本机通信的环境运行。

## 文件组织

| 文件 | 内容 |
| --- | --- |
| [adapter.py](<./src/b04/model_adapter/adapter.py>) | 五个异步入口、能力预检、一次发送、结果归一、停止及恢复 |
| [contracts.py](<./src/b04/model_adapter/contracts.py>) | Wire TypedDict、运行控制、版本、身份、时间及指纹 |
| [schemas.py](<./src/b04/model_adapter/schemas.py>) | 请求／结果／控制／反馈的可执行契约、严格 JSON 解析、离线 schema profile |
| [errors.py](<./src/b04/model_adapter/errors.py>) | MODEL_ 分类、安全错误信息及 EXEC_ 转换 |
| [ports.py](<./src/b04/model_adapter/ports.py>) | 配置、授权、账本、预算、凭据和供应商驱动端口 |
| [drivers.py](<./src/b04/model_adapter/drivers.py>) | 版本化驱动注册、确定性 MockDriver |
| [ledger.py](<./src/b04/model_adapter/ledger.py>) | SQLite 原子调用登记、发送意图、不可变结果、追加核对记录及受控正文引用 |
| [runtime.py](<./src/b04/model_adapter/runtime.py>) | 本地演示用授权、冻结配置、父子预算和凭据解析实现 |
| [示例](<./examples/model_adapter_demo.py>) | 可运行的通用 PM mock 调用及依赖装配 |
| [测试](<./tests/model_adapter/test_adapter.py>) | 基础接口、结果、错误、预算、授权及并发去重 |
| [工具与能力测试](<./tests/model_adapter/test_tools_and_capabilities.py>) | 工具意图、完整反馈、schema／参数／功能组合 |
| [恢复与安全测试](<./tests/model_adapter/test_recovery_and_security.py>) | 重启、原子登记、撤权、迟到响应、脱敏和持久化故障 |
| [回归测试](<./tests/model_adapter/test_regressions.py>) | 停止竞态、未知状态后续核对、边界请求与用量 |

## 对外接口

导入入口为 `b04.model_adapter`。以下接口均为 `async`，请求、结果和引用对象使用可 JSON 序列化的字典；`ModelRequest`／`ModelResult` 等提供 Python 类型声明，运行时由 schema 校验。

```python
from b04.model_adapter import ModelAdapterFacade, CallControl

adapter = ModelAdapterFacade(
    resolver=config_resolver,
    registry=driver_registry,
    ledger=call_ledger,
    budget=budget_service,
    authority=authority_service,
    credentials=credential_resolver,  # 无凭据的 mock 可省略
)

description = await adapter.describe_model(model_config_ref, call_context)
validation = await adapter.validate_request(request, call_context)
result = await adapter.generate(request, call_control)
snapshot = await adapter.get_call(model_call_ref, observe_context)
stop = await adapter.cancel_call(model_call_ref, "requested_stop", cleanup_context)
```

`model_call_ref` 的结构为：

```json
{
  "invocation_ref": {
    "project_id": "product-id",
    "run_id": "run-id",
    "invocation_id": "invocation-id",
    "task_id": null,
    "attempt_id": 1,
    "dispatch_id": "dispatch-id"
  },
  "model_call_id": "model-call-id",
  "call_seq": 1
}
```

查询与停止不接受裸 ID。`event_id` 不属于模型请求；没有 task_id、计划或仓库的首次 PM 调用仍合法。

### 可信运行控制

`CallControl.context` 使用协议第 14.2 节完整 ControlContext。字段字符串必须通过独立 Authority 服务核验，不能自行改变 purpose 或 grant_ref 获得权限。

```python
call_control = CallControl(
    context=issued_execute_context,
    control_budget_ticket_ref=issued_control_ticket_ref,
    cancel_signal=runner_cancel_event,
    cleanup_context=issued_cleanup_context,
    report_context=issued_report_context,
)
```

最后四项是运行端口注入，不增加 ModelRequest 或 ControlContext 的序列化字段。generate 在发送前要求已核发、绑定同一原调用及快照的 cleanup／report 上下文，确保后续可停止与记录。查询和停止各自传入 purpose=observe／cleanup 的 CallControl，使用独立控制票据。预检及同号查询也消耗控制额度，不重复扣业务模型额度。

发送前再次核验取消、执行授权、预算和期限；等待期间复核执行授权。撤权后使用原调用的独立 cleanup／report，不能据此继续 generate。正常完成后也需要 report 授权持久化真实记录；结果记录或结算失败会保留 unknown 和已持久化发送意图。

### 配置和模型切换

ConfigResolver 必须提供已冻结的模型配置、策略、能力、原调用绑定和 schema。`InMemoryConfigResolver.bind` 的调用来源为可信派发服务；不能拿本次模型请求直接建立授权绑定。

冻结绑定包含协议身份、模式、配置／策略／Agent／模板引用、快照、tool_binding_set_ref、tool_bindings 和允许读取的 schema_refs。配置示例与装配顺序见可运行示例；配置引用不能被同名覆盖。

不同供应商通过 `ProviderDriverRegistry.register(driver_ref, driver)` 扩展。驱动实现 describe、validate_mapping、estimate_input_tokens、send_once、normalize、cancel；供应商异常显式抛出 ProviderFailure，不能由 facade 根据一个 HTTP 状态码猜测原因。驱动需要保持非阻塞，并关闭 SDK／HTTP 自动重试和 fallback。

当前只支持已实现的 `transport:single-send@1` 配置。一个逻辑调用最多一次发送，同一 attempt 内配置被冻结；切换需要 B02 新建 attempt 和快照。模块不尝试备用模型、不隐式等待 retry_after_seconds，也不自行增加 call_seq 或 retry_count。

本次提供 MockDriver 及自定义测试驱动，未实现真实供应商 SDK 驱动。mock 的服务端结构化能力、停止确认和 token 上界均是模拟语义；不能作为真实模型接入证据。

### 结构化输出和工具往返

text 保留完整文本；json_object 严格要求 JSON 对象；json_schema 根据受控引用读取 schema、核对能力和保障级别，并做本地结构验证。工具意图作为独立中间分支，不受最终产物 schema 约束，但每项 arguments 必须符合对应的模型侧工具 schema。

拒绝 Markdown 包裹、重复 JSON 键、NaN／Infinity、截断、非法参数、未注册工具、未知结束原因和空响应，不自动修复或重新提问。合法结构中的 DAG、需求覆盖或产品业务错误仍交 runner／B01／B06 判断；`status=ok` 不是任务通过。

本地 schema profile 为 Draft 2020-12 子集，支持嵌套对象、数组、组合约束及本地 JSON Pointer `$ref`。所有 schema 必须预先注册；远程／文件引用、外部 `$id`、未实现的关键字及 format 均在发送前拒绝，避免隐式联网或忽略约束。参数和 provider_options 的 schema 也遵守相同规则。注册 schema 的本地示例以 canonical JSON 字节计算哈希；B03 实现须提供与其不可变存储一致的表示。

工具的公开 name、binding_ref、两个参数 schema 及其哈希必须匹配冻结绑定。返回工具意图附回 binding_ref，内部 tool_call_id 确定性生成为 `<model_call_id>:tool:<index>`，并保留 provider_tool_call_id。adapter 只返回意图，文件读写、内容暂存和命令执行仍由 runner／tool_executor 负责。

下一轮模型调用必须使用新 model_call_id／call_seq。assistant 消息携带原工具意图；tool 消息的 content 文本部件序列化完整 ToolFeedback，使用内部 tool_call_id 关联。完整状态、退出码、错误、停止、副作用、操作记录和截断信息均保留。payload-only、来源或快照不匹配、in_progress、unknown、停止未确认的反馈不能进入下一轮生成。

### 错误和记录

有合法调用身份的执行错误返回 `status=error/cancelled/unknown` 的 ModelResult；同号且确认仍运行时返回 `in_progress`，其 response、error、结束时间和最终耗时为空。get_call 单独返回 Snapshot。查询不到原记录表示 unknown，不能推断没有发送。

缺失或非法的调用身份、快照身份无法形成可信 ModelResult 时，generate 抛出带 MODEL_REQUEST_INVALID 的 ModelAdapterError，不补造 ID。validate_request 可用于提前取得 valid=false 和问题列表。授权失败也使用 ModelAdapterError 或已具身份的失败结果。尚未成功登记的预检拒绝允许 call_record_ref=null；runner 应记录其执行阶段诊断。

`to_exec_error(model_error, model_call_ref, policy_retry_allowed=False)` 补全协议第 14.6 节 ExecError 字段。内部请求无效转换为 EXEC_MODEL_ERROR；不追溯改变已接收的 InvocationReceipt，也不生成 EXEC_INVALID_ENVELOPE。原 code、用量不确定性、等待建议及来源引用保留。确认取消走 runner 停止流程，不强造另一个错误事件。

SQLite 在发送前原子登记调用和发送意图，同号异内容拒绝、同序号异 ID 拒绝、同号已完成复用结果。另一 adapter 或重启进程看到只有发送意图时返回 unknown，不重做发送。未知结果保持不可变；后续停止和迟到响应追加核对记录，迟到内容不替换原终结。并发停止共享一次驱动取消。

正文、有效消息和原始响应使用受控引用，异常正文不进入公共错误信息，已知凭据会被脱敏。SQLite 数据库包含受保护的模型内容，不能直接作为无鉴权的公开查询服务；实际部署的存储访问和日志保留由 B03 对接负责。

### 预算与边界

BudgetPort 按 transport_attempt_id 原子预留／结算。attempt 子票据受 invocation 父账本约束，已消耗和未知预留不因新 attempt 清除；runner 不重复扣执行次数。明确未发送可释放，发送不明或 token 用量不可得／仅估算时保留未结算额度。strict_token_budget 要求驱动声明可靠 token 上界；未知能力时拒绝，不能用估算冒充保证。实际观测超过预留上界会报错并保留真实消耗。

`InMemoryAuthority`、`InMemoryConfigResolver`、`InMemoryBudget`、`MappingCredentialResolver` 是测试／演示后端。生产 B02/B03 必须替换为持久、权威、可鉴权的服务，提供真实租约代际、预算核对、凭据读取和存储访问；内存预算不具有跨进程恢复能力，未知预留不会自动释放。SQLiteCallLedger 提供本地持久化参考实现，不替代平台共同状态服务。

## 本次验证记录

2026-11-16 验证结果：

| 检查 | 实际结果 |
| --- | --- |
| `python -u -m pytest -q`，关闭全局 pytest 插件自动加载 | **136 passed in 4.48s** |
| PM mock 示例 | status=ok、task_id=null、2 个候选任务、同号结果复用、实际发送 1 次 |
| Python 字节码编译 | 通过 |
| wheel 构建 | `se_workflow_b04-0.1.0-py3-none-any.whl` |

单元测试覆盖五个入口、结构化输出、完整工具反馈、冻结配置、原子去重、持久记录恢复、父子额度、超时、撤权、取消竞态、迟到响应、记录失败和凭据脱敏。以下是设计验收项与单元证据的对应，不代表 B06 已完成平台独立验收：

| 设计项 | 本次单元证据／范围 |
| --- | --- |
| MA-01 | mock 与另一种测试驱动的供应商格式归一；真实异构服务待接入 |
| MA-02 | policy／config／能力、Agent／模板及快照绑定检查 |
| MA-03 | task_id=null、无计划／仓库的首次 PM 调用 |
| MA-04 | 参数、schema、模态和功能组合不支持时发送前拒绝 |
| MA-05 | text、JSON 对象／schema、工具意图分支 |
| MA-06 | 截断、非法 JSON／参数、未注册工具不可执行 |
| MA-07 | 结构合法但有业务依赖环的 JSON 正常归一，业务结论不由 adapter 判定 |
| MA-08 | 两轮工具往返完整反馈、新调用编号和固定配置；真实工具执行不在本模块 |
| MA-09 | 同号完成复用、进行中去重、异内容冲突、并发原子登记 |
| MA-10 | 限流、凭据和服务故障分类，无隐藏重试 |
| MA-11 | 超时、未知发送、取消及迟到响应；停止证据与本地取消分开 |
| MA-12 | attempt 内切换拒绝，新冻结 attempt 可使用另一配置 |
| MA-13 | 原工具反馈和调用历史保留；真实副作用隔离由 runner／executor 联调验证 |
| MA-14 | 父子预算、实际发送、真实／未知用量、预留及结算故障 |
| MA-15 | 公共结果和原始记录中的已知凭据脱敏、项目隔离 |
| MA-16 | 产品标识变化复用同一接口；mock 不伪装 live，真实 live 尚未实现 |
| MA-17 | 不同模型配置和有效参数、同引用变更检测、schema 指纹 |
| MA-18 | SQLite 发送意图后重启及结果记录失败不重新发送 |
| MA-19 | 同号运行中返回固定 ModelResult，空值语义正确 |
| MA-20 | 绑定、模型参数 schema 与完整 ToolFeedback；执行参数归一仍属于 runner |
| MA-21 | 撤销 execute 后独立 observe／cleanup／report 继续生效 |
| MA-22 | 内部无效请求保留 MODEL_REQUEST_INVALID 并转换为 EXEC_MODEL_ERROR |

原 B04 协议、三份模块设计、角色模板及两份 DOCX 未修改。真实供应商参数映射、真实远端停止、分布式预算恢复和 B02/B03/B06 联调仍需相应模块的实际服务与独立验证。

实现所用 API 依据：[jsonschema 验证与 profile 文档](https://python-jsonschema.readthedocs.io/en/stable/validate/)、[Python asyncio 的任务与等待语义](https://docs.python.org/3/library/asyncio-task.html)。
