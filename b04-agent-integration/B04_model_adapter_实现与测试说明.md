# B04 model_adapter 实现与测试说明

交付整理日期：2026-11-17。依据 [任务执行协议 v0.2.1](<./B04_任务执行协议设计.md>) 和 [model_adapter 设计 v0.1.1](<./B04_model_adapter模块设计.md>)；运行契约为 `b04.model.v0.1`／`b04.exec.v0.2`。本文补齐独立模块说明，详细字段和最初验证记录同时保留在 [README](<./README.md>)。本次归档的实际结果以 [实验验收说明](<./B04_实验验收说明.md>) 和包内 evidence 为准。

## 1 实现范围

提供与产品、Agent 角色和供应商无关的统一模型调用入口：按冻结配置解析模型及能力，验证输入、结构化输出和工具意图，使用独立授权和预算，记录一次发送与结果，支持查询、取消和未知状态核对。

PM 规划、不同角色和不同产品通过 request 中的配置、消息、response_spec、工具绑定与输入快照变化接入。模块不硬编码校园案例、失物字段或 PM 任务分解规则，不执行真实工具、不接受候选，也不修改 Orchestrator 全局状态。

当前包含供应商驱动端口、版本化注册和确定性 MockDriver；真实供应商 SDK、凭据与在线服务未在本次交付中验收，不能把本地 mock 结果解释为真实模型质量或连通性通过。

## 2 文件清单

| 文件 | 职责 |
| --- | --- |
| [adapter.py](<./src/b04/model_adapter/adapter.py>) | 五个异步入口、预检、发送、归一、幂等、停止与恢复 |
| [contracts.py](<./src/b04/model_adapter/contracts.py>) | 请求／结果／控制 TypedDict、身份、时间、指纹 |
| [schemas.py](<./src/b04/model_adapter/schemas.py>) | 可执行 wire schema、严格 JSON、离线输出 schema profile |
| [errors.py](<./src/b04/model_adapter/errors.py>) | MODEL_ 分类、脱敏与 EXEC_ 转换 |
| [ports.py](<./src/b04/model_adapter/ports.py>) | 配置、授权、预算、账本、凭据及供应商驱动接口 |
| [drivers.py](<./src/b04/model_adapter/drivers.py>) | ProviderDriverRegistry、MockDriver 及能力声明 |
| [ledger.py](<./src/b04/model_adapter/ledger.py>) | SQLite 调用登记、发送意图、不可变结果与追加核对 |
| [runtime.py](<./src/b04/model_adapter/runtime.py>) | 本地参考授权、配置、父子预算和凭据解析 |
| [__init__.py](<./src/b04/model_adapter/__init__.py>) | 导出公共 API 和依赖端口 |

测试位于 [tests/model_adapter](<./tests/model_adapter/>)，演示为 [model_adapter_demo.py](<./examples/model_adapter_demo.py>)。

## 3 公共接口

```python
description = await adapter.describe_model(model_config_ref, call_context)
validation = await adapter.validate_request(request, call_context)
result = await adapter.generate(request, call_control)
snapshot = await adapter.get_call(model_call_ref, observe_context)
receipt = await adapter.cancel_call(model_call_ref, "requested_stop", cleanup_context)
```

请求为 ModelRequest；model_call_ref 包含完整 invocation_ref、model_call_id 和 call_seq，不能用裸 ID 查询。CallControl 与另外两个核心模块共用，execute、observe、report、cleanup 权限独立。

| 输入类别 | 关键字段 |
| --- | --- |
| 契约与身份 | adapter_contract_version、protocol_version、execution_mode、project/run/invocation/task/attempt/dispatch、model_call_id、call_seq |
| 冻结配置 | input_snapshot_id／sha256、agent_definition_ref、prompt_template_ref、model_policy_ref、model_config_ref |
| 模型内容 | messages、response_spec、tools、tool_choice、parameters |
| 执行控制 | call_limits、budget_ticket_ref，以及可信 CallControl |

generate 返回固定 ModelResult，status 为 ok、in_progress、error、cancelled 或 unknown。结果保留身份与快照、selected_model、response、结束原因、用量、时序、错误和受控原始／部分响应／调用记录引用。模型产生的工具调用只是意图，需交 runner／tool_executor 做真实权限检查与执行。

## 4 切换、错误及一致性

模型选择通过版本化 model_config_ref、model_policy_ref、driver_ref 和能力声明进行，消息不能自行更换供应商或取得凭据。角色和产品无需改变调用 schema。已冻结的同一次调用不能修改配置后继续复用旧编号；自动重发、换模型或换 attempt 的业务决定归上层。

支持文本、结构化 JSON 和工具意图。response_spec 所需能力、参数组合和 schema 不满足时明确拒绝；结构化输出仍做本地验证，不把供应商“声称结构正确”当作验证通过。工具反馈保持完整身份及执行状态，不能用 payload 代替整个反馈契约。

同号同指纹复用已有结果，不增加实际发送次数；同号异参数拒绝冲突。调用在发送前持久化意图，未知投递或未知停止保留不确定性及预算，不盲目生成新编号发送。查询与清理使用独立有限控制预算，原 execute 授权失效不自动阻断合法诊断和停止。

MODEL_ 错误包含稳定 code／category／stage、投递与停止状态、证据引用和恢复建议，避免公开密钥、认证头、底层堆栈或完整敏感正文。凭据解析、供应商异常、结构无效、预算、超时、取消和未知结果分别处理，由 runner 转换为相应 EXEC_ 反馈。

## 5 运行与验证

项目根目录执行：

```powershell
python -m pip install -e ".[test]"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -u -m pytest -q tests/model_adapter
$env:PYTHONPATH = (Resolve-Path .\src).Path
python examples/model_adapter_demo.py
```

全项目测试还需安装 `src/b04/reference_backend/requirements.txt`，统一运行步骤见实验验收说明。Windows 本机 asyncio 回环受环境限制时，需要在允许本机通信的环境运行；本地测试不连接真实供应商。

当前测试集合为 136 项，覆盖预检、结果归一、模型配置、结构化输出、工具与能力组合、身份及权限、父子预算、并发去重、撤权、超时取消、持久化失败和未知状态恢复。演示会核对 duplicate_reused=true、actual_sends=1、结果 status=ok。

## 6 交接条件

B02/B03 仍需提供实际的配置、控制授权、预算、持久账本及受控正文读取能力；真实供应商接入应在已审查驱动中处理凭据、能力、传输及停止证据。runner 消费统一结果，工具执行器消费工具意图归一后的 ToolRequest；model_adapter 不越过二者职责边界。参考服务和 mock 验证不替代团队交叉评审或 B06 独立验收。
