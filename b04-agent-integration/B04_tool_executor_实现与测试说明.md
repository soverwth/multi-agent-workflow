# B04 tool_executor 实现与测试说明

归档说明：本文保留三个通用模块首次联合验证的阶段记录；后续加入 T03—T05 参考后端及其回归。当前源码的统一实验结果见 [实验验收说明](<./B04_实验验收说明.md>)。

日期：2026-11-17。实现依据 [B04 协议 v0.2.1](<./B04_任务执行协议设计.md>)、[tool_executor 设计 v0.1.1](<./B04_tool_executor模块设计.md>)，复用现有 model_adapter 和 agent_runner 的共享契约。分发包版本为 `0.3.0`，Wire 版本保持 `b04.exec.v0.2`、`b04.tool.v0.1`、`b04.model.v0.1`。

本模块实现工具目录管理、冻结绑定、受权调用、真实文件读写、结构检查、命令后端接入、停止核对、SQLite 幂等记录、父子预算和完整结果反馈。功能由配置决定，未包含失物招领字段、产品专属任务编号、PM 分解策略或全局任务状态机。

## 1 运行

需要 Python 3.11+；本次验证环境为 Windows、Python 3.14、pytest 9.1.1、jsonschema 4.26.0。项目根目录执行：

```powershell
python -m pip install -e ".[test]"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -u -m pytest -q
python examples/tool_executor_demo.py
```

已有依赖时，pytest 自动使用 `src`。未安装包而需运行示例时，先设置 `$env:PYTHONPATH = (Resolve-Path .\src).Path`。

示例输出 `execution_mode=mock`、`candidate_submitted`、`self_check_status=passed`、`review_status=pending`；模型发送 2 次、实际工具操作 2 次，实际写入 29 字节，保留 CRLF。示例的模型和 B02/B03 权威服务为演示夹具，文件写入、JSON Schema 自检、SQLite 操作账本和 runner 提交逻辑为真实实现；不表示业务产物已接受，也不运行生成的代码。

## 2 文件组织

| 文件 | 职责 |
| --- | --- |
| [executor.py](<./src/b04/tool_executor/executor.py>) | 六个异步运行入口、控制授权、操作复用、执行守卫、停止与迟到核对 |
| [contracts.py](<./src/b04/tool_executor/contracts.py>) | 共享请求／结果 schema、OperationRef、TOOL_ 错误、驱动及后端协议 |
| [registry.py](<./src/b04/tool_executor/registry.py>) | 独立管理权限、显式版本发布、配置不可变、冻结工具绑定与权限解析 |
| [store.py](<./src/b04/tool_executor/store.py>) | SQLite 目录、执行意图、唯一操作、停止墓碑、审计、资源隔离及预算预留／结算 |
| [files.py](<./src/b04/tool_executor/files.py>) | 相对路径校验、真实句柄／目录身份、互斥锁、有界读取、原子创建／条件替换 |
| [drivers.py](<./src/b04/tool_executor/drivers.py>) | 产物读取、文件读取／写入、结构检查、固定命令 profile 驱动 |
| [sandbox.py](<./src/b04/tool_executor/sandbox.py>) | 本地 Docker Linux 隔离后端、固定镜像、受控快照、临时写区与全单元停止 |
| [process.py](<./src/b04/tool_executor/process.py>) | Windows Job Object 进程树原语和有界 stdout／stderr 缓冲 |
| [testing.py](<./src/b04/tool_executor/testing.py>) | 明确标注的三模块演示装配和工具请求夹具，非生产授权服务 |
| [示例](<./examples/tool_executor_demo.py>) | 三模块闭环运行 |
| [测试目录](<./tests/tool_executor/>) | 注册、权限、文件、命令、停止、恢复、边界及兼容测试 |

## 3 管理接口与运行接口

管理接口属于 `ToolRegistry`，只接受 `ManagementContext`：

```python
registry.register_tool(definition, management_context)
registry.validate_tool(tool_name, tool_version, management_context)
registry.publish_tool("tool:name@1", review_context)
registry.deprecate_tool(tool_name, tool_version, management_context)
registry.disable_tool(tool_name, tool_version, management_context)
```

配置 schema、profile、driver、runtime、command 同样需要独立 `configure` 权限。管理 grant 不由模型参数或运行上下文签发。

定义字段严格使用设计中的 14 个字段：`tool_name`、`tool_version`、`driver_ref`、`capability_refs`、`input_schema_ref`、`output_schema_ref`、`permission_classes`、`side_effect_profile`、`execution_profile_ref`、`limits_profile_ref`、`idempotency_policy`、`stop_query_policy_ref`、`owner_ref`、`review_refs`。显式版本禁止覆盖，不接受 `latest` 或 `*`；发布前需依赖校验和评审引用。生命周期为 `draft → validated → published → deprecated/disabled`，禁用不能反向恢复为已发布。

运行接口属于 `ToolExecutor`，全部为异步：

```python
description = await executor.describe_tool(name, version, access_context)
validation = await executor.validate_tool_request(request, tool_control)
result = await executor.execute_tool(request, tool_control)
snapshot = await executor.get_operation(operation_ref, observe_context)
receipt = await executor.stop_operation(operation_ref, "requested_stop", cleanup_context)
result = await executor.read_result(operation_ref, snapshot["result_ref"], observe_context)
await executor.aclose()
```

`CallControl` 直接复用 model_adapter，包含主要 ControlContext、独立控制预算、取消信号及 report／cleanup 上下文；查询和停止不要求原 execute grant 仍有效。最后四个业务方法与现有 `ToolExecutorPort` 兼容。

OperationRef 为 `{"invocation_ref": {project_id, run_id, invocation_id, task_id, attempt_id, dispatch_id}, "operation_id": ...}`。不能用裸 operation_id 查询或停止。所有字段、snapshot、模式和工具绑定均核对，task_id、dispatch_id 也不能同号替换。

JSON 可表达且身份完整的执行阶段错误返回完整 ToolResult。非 JSON 值、非法／缺失身份无法构造合法 ToolResult，抛出 `ToolExecutorError`；这与已接收 invocation 的终结反馈不同。管理接口的配置编程错误也可能抛出 `ValueError`，不应交给模型修复。

## 4 可信依赖与装配

```python
executor = ToolExecutor(
    registry=tool_registry,
    store=sqlite_tool_store,
    authority=authority_service,
    policy=frozen_tool_policy,
    artifacts=b03_artifact_port,
    workspaces=workspace_registry,
    control_budget=independent_control_budget,
    sandboxes={"sandbox:linux@1": verified_backend},
)
# 使用同一个实例替换 runner 的 tool_executor 端口。
```

| 依赖 | 必须由可信方提供的信息／行为 |
| --- | --- |
| authority | 核对原始 ControlContext、purpose、身份、撤权和期限，不能只检查字段是否存在 |
| FrozenToolPolicy | 已冻结的身份、snapshot、lease、tool_config、workspace、模式、绑定、写范围、工具预算及原 attempt 期限 |
| grant.bindings | 唯一 model alias、显式工具／驱动版本、模型和执行 schema 引用／哈希、归一化及命令 profile 引用 |
| grant 权限 | permission_classes、model_binding_refs、read_artifacts 元数据、read_paths、candidate_read_namespaces、workspace_lease_ref、command_profile_refs、self_check_bindings |
| current_check 回调 | 每次副作用／轮询边界重新核对权威输入状态、attempt、generation、停止／终结标志和总执行 deadline |
| ArtifactPort | 实际字节与元数据读写、所有权和完整性核对、草稿隔离；与 SQLiteRunnerStore 现有端口相同 |
| WorkspaceRegistry | logical workspace_ref 对应的项目、真实本地根目录和独占工作区租约 |
| SQLiteToolStore | 同一工作区的所有执行实例共用持久账本、资源隔离记录和工具父子预算 |
| SandboxBackend | 如实声明能力、验证部署环境、启动唯一受控单元、提供结果和整个单元停止证据 |

`FrozenToolPolicy` 保存授权配置摘要，配置更改不能沿用旧 snapshot；新发布版本不会自动升级已有绑定。已弃用版本可继续服务原冻结调用，但不能建立新的冻结绑定；禁用版本在新操作及进行中守卫处均被阻止。

演示 `ManagementAuthority`、`FrozenToolPolicy` 的本地注册表、B03 参考存储和预算服务用于联调，部署时需接入 B02/B03 的权威来源。重启后须从可信配置恢复 driver／schema／profile／grant，SQLite 目录中的引用不能自行产生权限。

## 5 文件和产物

`ArtifactReadDriver` 核对允许读取的精确产物引用、项目、kind、state、sha256，返回实际元数据、有界正文和受控正文引用。`FileReadDriver` 另核对工作区读范围，支持 UTF-8／binary、字节区间和期望哈希，返回完整文件与区间哈希。`complete` 表示实际读取范围；`inline_complete` 表示反馈内是否包含完整文本，二者分开。

`FileWriteDriver` 只接受 runner 已暂存的 `content_ref`、`expected_content_sha256`、显式编码、目标路径和创建／替换前置条件，不接受 inline content。暂存对象必须属于原 invocation 的草稿空间且 kind 为 draft_content；UTF-8 校验不改变 BOM、CRLF 或字节内容。

文件路径拒绝绝对／UNC／盘符、上跳、空段、反斜线、ADS、保留设备名、尾随空格／点、非规范 Unicode 等歧义。还核对真实父目录／文件句柄、reparse point、junction、symlink 和硬链接；不把字符串前缀当作最终安全判断。

创建使用不覆盖的原子提交；替换要求 expected_target_sha256，在同目录临时文件写入、flush／fsync、重新核对目标身份和前置哈希后原子替换，并读取实际结果。返回 changes 的 before／after 哈希及真实版本引用。提交后证据或记录失败返回 unknown，不因重传再次写入。

当前文件写入 profile 要求**父目录由可信环境预先创建**，`allow_mkdir=True` 明确拒绝，避免隐含目录副作用。工作区租约要求所有写入方共用资源锁；本实现不保证对任意越过租约的主机进程实现跨进程文件 CAS。命令不能因此获得宿主机直接执行权限。

## 6 命令、检查及隔离

`CommandDriver` 接受已绑定 `command_profile_ref` 和经过 schema 校验的参数。profile 解析固定 runtime／可执行文件、argv 模板、最小环境、cwd、资源限制、退出码策略、副作用范围和进程控制后端。参数不能选可执行文件、shell 入口、动态 `-c`／`--eval` 入口、未声明选项、工作目录或任意环境；路径参数另核对声明的 read／write 范围。

仅使用 argv 并不满足隔离条件。后端必须满足文件系统、网络、进程树停止、内存、PID 和临时文件系统限额；缺少任一能力时返回 `TOOL_PROFILE_UNSUPPORTED`，没有宿主机 shell／subprocess 回退路径。

提供的 Docker Linux 后端使用显式本地 endpoint、已有固定 `sha256:<image-id>` 镜像和受审查入口，不启动 Docker、不拉取镜像。仅把获准输入复制到专属快照，挂载只读快照、有限 tmpfs 写区；关闭网络、根文件系统只读、移除默认 capabilities、限制 PID／内存／CPU，业务子进程降为 uid/gid 1000 且不继承主机凭据。

可信 PID 1 控制程序在业务父进程退出后仍核查、终止及回收其余业务进程；业务进程无权修改 root 专属完成标记。宿主侧有界读取日志／产物、拒绝不安全 tar 成员和未声明输出，停止并核对整个容器后才把通过验证的输出条件提交回工作区。输出删除当前不支持，会返回 TOOL_OUTPUT_INVALID。

stdout、stderr 分别保存受控引用，持续有界读取，超量显式截断或按 profile 停止。必要报告需要实际文件和 schema 校验，不能用退出 0 替代。退出码 1 仅在 exit_code_policy 明确配置时表示业务检查失败，此时 ToolResult 为 completed、check_outcome 为 failed，不是基础设施故障。

`SchemaCheckDriver` 是可配置的实际 JSON Schema 检查驱动，核对候选产物所有权、kind、hash 和规定规则；它只证明结构规则，不能代替专业行为检查、命令隔离验收或 B06 独立验证。

Windows Job Object 原语单独提供真实进程树和有界日志验证，明确声明不具备文件系统／网络隔离，不能单独成为上述命令 profile 的合格后端。平台行为依据 [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)、[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew) 和 [Docker run](https://docs.docker.com/engine/containers/run/) 的官方说明。

## 7 幂等、停止和预算

唯一键绑定 project／run／invocation／attempt／operation，并完整核对 task／dispatch。请求、冻结配置及有效范围形成指纹；同号同指纹复用结果，同号不同参数返回 TOOL_OPERATION_CONFLICT。仍由本实例执行的同号请求返回 in_progress，结束时间／最终耗时／error 为 null，stop_status 为 null。失去原执行者时返回 unknown，不能据此重新启动。

SQLite 在实际副作用前记录 prepared 意图，并在事务中转换 running、核对停止墓碑和资源竞争。不同操作编号及 attempt 仍受未知资源隔离约束；跨进程同时取得 prepared 的操作也不能同时进入相同资源执行区。完成结果不可覆盖，后续停止或迟到证据以追加记录保存。

deadline 从首次接收开始计算，取请求、工具 timeout、ControlContext、冻结 attempt 上限的最小值；重传不重新计算原执行时间。文件分块／提交和命令轮询反复执行守卫。停止清理有独立有限等待窗口，后端迟迟不返回时给出 unknown，并在迟到证明到达后追加核对，不把本地 cancel 或父入口退出当作全树已停止。report 授权丢失时保留可查意图，不返回未落账的成功。

工具额度通过 `purpose=tool_execute` 的父 invocation／子 attempt BudgetTicket 原子预留。实际执行只按 OperationRef 计一次；同号复用、查询和预检不再次扣实际执行额度。已知未执行释放预留，未知结果保留 reserved／unsettled。新的 attempt 不能重置父额度。observe／cleanup 及重复投递使用独立有限控制预算，业务额度耗尽仍能查询、停止。

get_operation 返回真实记录／结果引用、资源摘要、阶段、停止／副作用状态、原操作预算预留及结算和追加核对记录。业务开始前的拒绝使用服务端持久诊断记录，不生成虚构引用。对外错误采用稳定 code／category／stage／operation_ref／证据引用，底层异常堆栈或敏感路径不作为 message 回传。

**恢复边界：**没有原执行者归属或权威 fencing 证明的 prepared／running 操作保守返回 unknown；当前不自动接管 prepared 操作，也不自动释放未知资源或预算。B02/B03 必须先核对实际文件／执行单元和历史，再决定恢复或新的 attempt。此规则是当前参考实现对设计恢复流程的保守约束，不能把哈希相同当作完整命令已完成的证明。

## 8 与现有模块的兼容

直接复用现有 TOOL_REQUEST_SCHEMA、TOOL_RESULT_SCHEMA 和 CallControl。model_adapter 无改动，继续只产生模型输出／工具意图。runner 负责模型工具别名解析、inline 内容暂存、请求编号、反馈、自检、候选及事件；executor 不调用 submit_event，不接受产物，不更新全局任务状态。

runner 本次仅补充两处契约映射：

1. TOOL_NOT_REGISTERED／TOOL_DISABLED／TOOL_PROFILE_UNSUPPORTED 映射 EXEC_CAPABILITY_UNAVAILABLE，规定自检不能吞掉 blocked 错误。
2. TOOL_SCOPE_DENIED／TOOL_PATH_INVALID 的文件写拒绝映射 EXEC_WRITE_SCOPE，读取／执行拒绝保留 EXEC_TOOL_ERROR 及原始权限错误。

三模块兼容测试实际覆盖模型 → 读取产物 → 完整 ToolFeedback → 后续模型调用，以及模型 inline 写入 → 草稿暂存 → 实际文件提交 → 真实结构自检 → Manifest／候选提交。CLI 与失物招领只是更换 product/spec 的两种测试夹具，核心没有为后者增设逻辑。

## 9 验证范围和环境限制

阶段历史记录（三个通用模块）：**382 项通过，1 项跳过**（tool_executor 162 项通过、1 项可选 Docker 测试跳过，agent_runner 84 项通过，model_adapter 136 项通过）。当时三模块示例运行成功，源码编译检查通过，v0.3.0 wheel 构建完成；包内 30 个 Python 源文件与当时源码逐字节一致，model_adapter 的 9 个源文件与 v0.2.0 分发包一致。原协议、角色模板和三个核心设计文档的 SHA-256 未改变。

已在隔离 Python 导入环境中显式加入已安装依赖目录，直接从 wheel 导入三个模块，避免误从当前源码目录加载。离线构建命令为 `python -m pip wheel . --no-deps --no-build-isolation --no-index --no-cache-dir --wheel-dir dist`。

```text
python -u -m pytest -q
382 passed, 1 skipped in 43.25s
```

单元与集成测试覆盖设计 TE-01～TE-24 所涉及的目录、权限、路径、哈希、版本、幂等、完整反馈、预算和停止场景。命令控制面和错误分支使用**只允许 mock 模式的模拟后端**，不会把这些结果计为真实 Docker 隔离证据。

真实 Windows Job Object 测试启动固定、可审查的 Python 助手，验证父进程退出后子进程仍受跟踪、全树终止、分别有界采集日志及退出码 259。真实文件测试覆盖硬链接、Windows junction、读取后目标被改变、精确字节和提交后记账故障。

当前机器未配置可用的 Docker Linux 引擎／固定测试镜像，因此真实 Docker 集成测试跳过；不能据此宣称 TE-11 的真实隔离行为已经验收。未满足部署条件的实际命令请求明确拒绝。

Docker 集成测试需由环境负责人准备已审核且本地已有的 Linux 镜像（包含 `/usr/local/bin/python`），然后显式配置：

```powershell
$env:B04_TEST_DOCKER_EXE = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$env:B04_TEST_DOCKER_ENDPOINT = "npipe:////./pipe/dockerDesktopLinuxEngine"
$env:B04_TEST_DOCKER_IMAGE = "sha256:<本地已审核镜像的64位哈希>"
python -u -m pytest -q tests/tool_executor/test_sandbox.py
```

该可选测试实际检查只读快照／范围外写入被拒绝、无默认网络路由、有界双日志和业务后代进程收尾。测试与参考后端均不启动 Docker 或下载镜像。生产接入还需 B02/B03 授权和租约联调、B05 反馈显示及 B06 独立验收；本地演示结果不替代这些工作。
