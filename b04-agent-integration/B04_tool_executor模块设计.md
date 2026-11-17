# B04 tool_executor 模块设计

本文定义通用 SE Workflow 平台的工具注册、权限校验、文件读写、命令执行、超时停止及执行结果反馈。tool_executor 执行 runner 已核验的工具请求，提供真实操作与副作用记录，不决定产品任务、模型切换、独立验收或全局任务状态。

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v0.1.1 |
| 模块契约版本 | `b04.tool.v0.1` |
| 上层运行协议 | `b04.exec.v0.2` |
| 适用设计 | 角色模板 v0.1；model_adapter、agent_runner 设计 v0.1.1 |
| 负责人 | 汤志豪 |
| 状态 | 待交叉评审的设计草案 |
| 更新日期 | 2026-11-16 |
| 范围 | 注册、授权、文件读写、进程执行、停止恢复和结果 |
| 交付性质 | 设计与契约模板，不表示工具驱动、执行隔离或真实验收已经实现 |

本次为未发布草案的接口一致性修订，协议标识保持 `b04.exec.v0.2`，模块标识保持原值。新增枚举和字段须由全部消费方按协议第 14 节共同确认，不能据此声明兼容已部署旧实现。角色模板 v0.1 的专业职责保持适用。

## 1 设计依据与职责

### 1.1 设计依据

- [B04 任务执行协议设计 v0.2.1](<./B04_任务执行协议设计.md>)：工具身份、授权、租约、产物及异常恢复。
- [B04 Agent 角色模板设计 v0.1](<./B04_Agent角色模板设计.md>)：角色工具需求与实际授权的区别。
- [B04 model_adapter 模块设计 v0.1.1](<./B04_model_adapter模块设计.md>)：工具调用意图、关联编号和模型结果边界。
- [B04 agent_runner 模块设计 v0.1.1](<./B04_agent_runner模块设计.md>)：ToolExecutorPort、操作去重、预算、自检、反馈和停止竞态。

本文细化既有 execute_tool／get_operation／stop_operation 能力，不改变运行调用包、全局事件和验收责任。新增字段、工具名、配置和错误码是拟议设计，须与接口消费方确认；不绑定未选定的进程隔离技术或具体命令工具。

### 1.2 职责边界

| 组件 | 主责 | 本模块边界 |
| --- | --- | --- |
| B01／专业规则 | 产品规格、任务和检查要求 | 以契约或受控输入消费，不硬编码业务规则 |
| B02 Orchestrator | 阶段、资源、派发、重派和全局状态 | 遵循当前执行权；不另建任务尝试 |
| B03 共享数据 | 快照、配置、租约、操作和产物存储 | 使用授权与原子接口，不直接改全局成功状态 |
| agent_runner | 工具意图核验、上下文、自检、候选及事件 | 执行其标准请求，返回真实结果和不确定性 |
| model_adapter | 模型响应与工具意图归一 | 不接受其模型输出绕过 runner 直接执行 |
| tool_executor | 工具注册适配、二次授权、实际执行、停止和操作记录 | 不接受计划、放行交付或唯一验收自己 |
| B05 | 工具能力和运行详情展示 | 只展示授权范围内的目录及脱敏结果 |
| B06 | 检查规则、退出语义和独立质量 | 检查失败按规则反馈，不擅自改成工具成功或业务通过 |

运行时工具授权与成员个人使用 IDE、模型和辅助工具分别管理。工具目录不是个人开发工具白名单，也不因注册成功就赋予所有 Agent 调用权。

### 1.3 基础版范围

- 提供版本化产物读取、工作区文件读取、文件创建／条件替换、受控命令／检查能力。
- 管理查询、注册和发布接口与模型可见运行工具分开。
- 基础命令采用配置固定的执行入口和结构化参数，不提供任意 shell 文本入口。
- 删除、移动、网络服务、数据库迁移等其他副作用通过独立工具定义及授权接入，不由通用命令隐式获得。
- 模拟与真实执行分别标识；任何隔离能力需实际验证后才能在目录中标为支持。

## 2 工具注册与目录

### 2.1 ToolDefinition

| 字段 | 要求 |
| --- | --- |
| tool_name、tool_version | 稳定逻辑名和不可变版本；不能只按“最新”解析 |
| driver_ref | 已审查的实现引用和版本，不从产品文字加载任意代码 |
| capability_refs | 能力分类，供 PM 和 runner 判断 |
| input_schema_ref、output_schema_ref | 参数、结果和必要字段的版本化契约 |
| permission_classes | 读取、写入、进程执行等所需权限类型 |
| side_effect_profile | 可能修改的资源类别及副作用边界 |
| execution_profile_ref | 环境、隔离、文件范围、命令、网络等执行条件 |
| limits_profile_ref | 时限、输入输出大小和资源上限 |
| idempotency_policy | 可直接复用已确认结果，或须先核对副作用 |
| stop_query_policy_ref | 查询、停止能力及无法确认时的处理 |
| owner_ref、review_refs | 内容主责、评审和实现证据 |

定义描述能力上限，实际授权仍取项目、阶段、Agent 定义、本次派发及当前租约的交集。输出结果也须通过 output_schema 校验。

### 2.2 注册、发布与禁用

1. 主责块提交定义、驱动和参数／副作用说明。
2. B04 校验字段、依赖、版本、参数与结果契约，并验证执行能力。
3. B02/B03 确认资源和操作记录接口，B06 检查异常与隔离反例，消费方评审。
4. B03 保存不可变定义；完成指定确认后发布新目录版本。
5. Workflow 通过 tool_config_ref 选择可用版本，runner 仅向模型描述实际授权工具。

目录管理可记录 draft、validated、published、deprecated、disabled 等发布状态。发布控制记录与不可变定义分别保存；弃用不自动修改已冻结配置，禁用或撤销授权则阻止新操作，运行中操作按停止流程核对。

模型及产品规格不能调用管理接口来注册新驱动、发布版本或扩大权限。名称与已注册工具相似不代表同一版本或同等授权。

### 2.3 注册定义示例

本文件所有 JSON 均为设计模板。逻辑引用、占位校验值和结果须由真实配置与执行记录替换，不表示接口已存在或验收已完成。

```json
{
  "tool_name": "run_check",
  "tool_version": "1",
  "driver_ref": "tool-driver:command-check@1",
  "capability_refs": [
    "capability:check-execution@1"
  ],
  "input_schema_ref": "schema:run-check-input@1",
  "output_schema_ref": "schema:check-tool-result@1",
  "permission_classes": [
    "workspace_read",
    "workspace_write",
    "process_execute"
  ],
  "side_effect_profile": "effects:isolated-check-workspace@1",
  "execution_profile_ref": "execution:isolated-project-check@1",
  "limits_profile_ref": "limits:bounded-check@1",
  "idempotency_policy": "reconcile_before_reexecute",
  "stop_query_policy_ref": "stop-query:process-tree@1",
  "owner_ref": "B04",
  "review_refs": [
    "<tool_review_ref>",
    "<isolation_evidence_ref>"
  ]
}
```
run_check 的输入包含 command_profile_ref 和受约束的参数值。命令 profile 在第 7 节定义，不接受直接传入任意可执行文件或 shell 脚本。

## 3 接口与操作身份

### 3.1 运行接口

与 agent_runner v0.1.1 的 ToolExecutorPort 对齐，以下为逻辑异步接口：

```text
describe_tool(tool_name, tool_version, access_context) -> ToolDescription
validate_tool_request(request, tool_control) -> ToolValidationResult
execute_tool(request, tool_control) -> ToolResult
get_operation(operation_ref, access_context) -> OperationSnapshot
stop_operation(operation_ref, reason, tool_control) -> ToolStopResult
```

| 方法 | 要求 |
| --- | --- |
| describe_tool | 只返回可见定义、契约和限制，不暴露凭据或未授权配置 |
| validate_tool_request | 预检参数、范围和能力，不产生业务副作用，不占用实际执行次数 |
| execute_tool | 执行前重新校验可变控制；基础接口等待完成或明确返回未知／超时；同号请求仍运行时返回 in_progress 的 ToolResult |
| get_operation | 返回原操作状态和结果，查询不重新执行命令或读取新版本 |
| stop_operation | 停止指定操作，回执区分 confirmed、pending、unknown，不直接取消全局任务 |

tool_control 由可信 runner 环境提供，采用协议第 14.2 节共享 ControlContext 基础结构，解析身份、有效权限、预算票据、停止信号和配置。它不是模型可通过 arguments 自行构造的授权。

控制对象遵循 B04 协议第 14 节。execute_tool 使用 execute 授权和当前租约；get_operation 使用 observe，stop_operation 使用 cleanup，结果及故障追加使用 report。旧执行租约过期时仍可按独立授权查询、停止和记录原资源；这些权限不允许新建进程、重做写入或发布业务候选。

### 3.2 管理接口

register_tool(definition, management_context)、publish_tool(definition_ref, review_context) 及发布控制由配置管理路径调用，不进入 model_adapter 的 tools 描述。

发布结果说明登记或配置状态，不能用来证明真实任务已经执行。新增驱动须验证其声明能力，尤其是停止、隔离、输出约束和副作用核对能力。

### 3.3 操作身份和去重

operation_ref 使用协议第 14.1 节 OperationRef，即完整 invocation_ref 加 operation_id；InvocationRef 中 task_id 键必需但可为 null。operation_id 由 runner 分配，绑定工具、版本、有效参数、目标、配置和输入快照。

- 同编号同指纹：只返回 ToolResult。已完成复用原结果，确认运行中返回 status=in_progress，确实无法确认返回 unknown；不返回未声明的 OperationSnapshot／Handle，不执行第二次。
- 同编号异指纹：拒绝并保留冲突证据。
- 已发送命令但结果未知：先查询和停止，不因重传请求再次启动。
- 同一已完成读取请求重传：返回原观察结果；若要读取当前新内容，须由 runner 分配新操作并满足输入规则。
- 新 attempt 的相似操作：先核对旧副作用，不能把新编号当作盲目重做的理由。

指纹使用冻结请求与配置，排除动态查询时间、剩余额度和凭据明文。模型 tool_call_id 只作来源关联，不作为跨项目或跨尝试的操作唯一键。

## 4 请求与权限校验

### 4.1 ToolRequest

| 字段 | 含义 |
| --- | --- |
| tool_contract_version、protocol_version | 模块契约 b04.tool.v0.1 与上层 b04.exec.v0.2 |
| execution_mode | mock 或 live，返回与证据不得改写模式 |
| invocation_ref、operation_id | runner 核验的调用和操作身份 |
| tool_binding_ref、tool_name、tool_version、arguments | 绑定到冻结工具配置的唯一版本，arguments 为已归一的执行参数 |
| input_snapshot_id、input_snapshot_sha256 | 冻结输入身份 |
| lease_ref、tool_config_ref | 有效执行权与工具配置引用 |
| workspace_ref | 对文件或进程操作必需，纯产物读取按契约可为空 |
| timeout_seconds、deadline_at | 请求时限与不可被重传延长的截止点 |
| origin | model、runner 或 self_check，及适用的模型调用／意图／检查引用 |

write_scope 不由 arguments 声明。executor 通过调用快照和可信 ToolControl 解析有效范围；请求体中的路径只是待检查的目标，不是授权本身。

### 4.2 校验顺序

1. 校验版本、类型、必填字段和工具参数结构。
2. 核验调用者、项目、当前 attempt／dispatch、控制状态与租约。
3. 核验工具及指定版本已发布、未被禁用，并在 tool_config 中。
4. 对照角色所需能力与实际授权，解析读、写、命令和环境范围。
5. 解析资源真实标识，检查路径、产物、命令 profile 和参数约束。
6. 核验环境确实具备必要隔离、停止和资源控制能力。
7. 原子登记／核对操作指纹，申请已有预算，记录执行意图。
8. 在实际读写或启动进程前复核会变化的授权和资源条件。

任何条件不足都明确拒绝或报告能力缺口，不用更宽配置补猜。工具存在、路径能打开或命令能启动都不是授权依据。

### 4.3 有效权限

| 资源 | 来源与校验 |
| --- | --- |
| 产物读取 | 已授权输入引用、明确允许的检索范围及项目隔离规则 |
| 文件读取 | 工具配置与工作区 profile 允许的路径；不默认读取整个主机 |
| 文件写入 | 上层 write_scope.workspace_paths 与项目、阶段、定义、工具约束的交集 |
| 对象写入 | write_scope.artifact_namespaces 和 B03 当前授权 |
| 命令执行 | 明确授权的 command_profile_ref、固定入口和参数 schema |
| 执行环境 | 指定工作区、可读／可写资源、网络与凭据策略等 profile |
| 临时数据和日志 | 环境声明的命名空间与生命周期，不借临时目录扩大权限 |

读取范围与写入范围分别解析；具备文件写入权限不意味着能读取任意其他资源。上述读取范围是 ToolControl 内部的权限解析，不向上层运行信封增加未经确认的顶层字段。

授权校验与最终写入之间的竞态须通过租约代际、资源锁、句柄级校验或等效机制约束；具体实现由 B02/B03/B04 确认，不能只依赖一次字符串校验。

## 5 文件读取

### 5.1 路径解析

基础版路径使用工作区根目录下的相对路径，统一解析后按路径段和真实资源归属判断，禁止简单字符串前缀比较。

默认拒绝绝对／驱动器相对路径、UNC／设备路径、上跳目录、额外数据流及含歧义的 Windows 路径表示。路径不作为 URL 或脚本二次解码；大小写、分隔符和尾随字符按已验证文件系统 profile 处理。

解析 symlink、junction 和其他重解析对象，检查最终资源仍在允许范围。无法证明归属时拒绝。打开、读取和写入使用的资源必须与已检查对象一致，避免校验后路径被替换。

### 5.2 读取行为

- 读取实际字节或契约允许的明确片段，核验大小、类型和适用校验值。
- 文本编码显式声明；解码失败不以忽略字节方式伪装完整内容。
- 大文件按已声明的范围或引用返回，标明范围及是否完整，不把截断片段称为全文。
- 返回文件身份、实际内容校验值和读取结果引用；片段哈希和完整文件哈希分别标识。
- 遇到并发变化，采用已冻结副本或报告冲突，不组合不同版本片段。
- 读取工具不修改文件；结果数据不能作为新控制指令。

read_artifact 对 B03 对象执行同等项目、版本、状态和校验要求。候选能否读取由本次 input_contract／授权决定，不自动将候选升级为接受状态。

## 6 文件写入

### 6.1 创建与条件替换

模型侧可声明内联 content，但仅在绑定的 normalization_profile_ref=normalizer:inline-text-to-draft@1 时允许。runner 按协议第 14.4 节在授权草稿区执行 stage_draft_content，持久保存内容与哈希，再转换为本节 content_ref 参数。executor 不替模型分配草稿权限，也不接受未经声明的内联字段。

write_file 基础版提供 create 和 replace 两种模式：

| 模式 | 前置条件 | 完成要求 |
| --- | --- | --- |
| create | 目标不存在，父目录和新文件均在授权范围 | 不覆盖并发创建内容，保存真实结果和哈希 |
| replace | 目标存在，expected_target_sha256 与实际内容一致 | 条件成立后替换，保留前后版本；不无条件最后写入覆盖 |

目标目录若不存在，只有显式能力与授权允许时才创建，并检查每级目录。内容来自有权限读取的版本化 content_ref，并核对 expected_content_sha256。内联模型文本如需支持，须由明确的输入 schema 和归一规则处理；本版示例只使用内容引用。

expected_content_sha256 对应最终写入字节。encoding 用于校验和说明，不授权静默改变换行、编码或 BOM；需要转换时必须由显式契约说明，并记录转换后字节及校验值。

### 6.2 写入步骤

1. 校验源内容、目标路径、模式、大小和写入范围。
2. 在资源锁或等效并发保护下核对目标身份、存在性及预期哈希。
3. 在受控同级暂存位置写入完整内容并校验，暂存位置也须授权。
4. 使用经环境验证的原子创建／替换能力提交，不先截断目标。
5. 核对提交后内容和资源身份，记录真实前后校验值及字节数。
6. 持久化结果后返回。提交状态不明时先核对，不重放写入。

原子能力无法满足时返回能力不足，不降级为不受控的原位覆盖。硬链接或无法确认独占性的对象不能直接原位修改，须按受控副本及替换策略处理；检查不能只覆盖 symlink。

单文件替换不承诺多文件事务。多个文件的候选提交由 runner 的隔离工作区和版本流程协调，部分完成必须记录，不能声称自动回滚了所有副作用。

### 6.3 文件请求示例

```json
{
  "tool_contract_version": "b04.tool.v0.1",
  "protocol_version": "b04.exec.v0.2",
  "execution_mode": "mock",
  "invocation_ref": {
    "project_id": "product-cli-demo",
    "run_id": "run-tool-demo-001",
    "invocation_id": "invoke-implement-001",
    "task_id": "CLI-PARSE",
    "attempt_id": 1,
    "dispatch_id": "dispatch-tool-001"
  },
  "operation_id": "op-write-parser-001",
  "tool_name": "write_file",
  "tool_version": "1",
  "arguments": {
    "path": "src/parser.py",
    "mode": "create",
    "content_ref": "draft:product-cli-demo/parser@1",
    "expected_content_sha256": "<content_sha256>",
    "expected_target_sha256": null,
    "encoding": "utf-8"
  },
  "input_snapshot_id": "snapshot-tool-001",
  "input_snapshot_sha256": "<snapshot_sha256>",
  "lease_ref": "<active_lease_ref>",
  "tool_config_ref": "tools:cli-implementation@1",
  "workspace_ref": "workspace:product-cli-demo/attempt-1",
  "timeout_seconds": 10,
  "deadline_at": "2026-11-16T02:10:10.000Z",
  "origin": {
    "source": "model",
    "model_call_id": "mc-implement-001",
    "tool_call_id": "mc-implement-001:tool:1",
    "check_ref": null
  },
  "tool_binding_ref": "binding:cli-write-file@1"
}
```
source content_ref 须为本次授权可读草稿，实际路径与内容归一由程序校验。mock 写入也应在隔离夹具中产生可核对的真实结果，不以模型回复充当文件存在。

## 7 命令执行

### 7.1 CommandProfile

| 字段 | 要求 |
| --- | --- |
| command_profile_ref | 不可变、已授权的命令配置引用 |
| executable_ref | 受控运行时的明确执行入口，不从模型参数或不受控 PATH 选择 |
| argv_template | 固定参数结构和声明的值槽位，不是自由命令字符串 |
| parameter_schema_ref | 值类型、枚举、路径及相互约束，防止选项或入口替换 |
| cwd_policy | 明确工作目录，核验实际路径 |
| environment_policy_ref | 最小必要环境及凭据注入规则 |
| resource_policy_ref | 时限、进程、内存、输出和工作区限制 |
| exit_code_policy_ref | 哪些退出属于检查结果、哪些属于执行故障 |
| side_effect_policy_ref | 可读、可写、外部访问及核对范围 |
| process_control_ref | 子进程管理、停止和未知状态能力 |

模型只提供该 profile 允许的参数值，不能自行添加可执行文件、解释器选项或环境。即使使用 argv，程序自己的选项、配置、插件和输入代码仍能影响行为，必须由参数规则和环境约束共同控制。

下面是第 7.5 节所用的逻辑命令配置示例；runtime 引用指向待实现的检查夹具入口，不是当前项目已有程序。

```json
{
  "command_profile_ref": "command:project-checks@1",
  "executable_ref": "runtime:project-checker@1",
  "argv_template": [
    "--suite",
    "{{suite}}",
    "--report",
    "{{report_path}}"
  ],
  "parameter_schema_ref": "schema:check-command-parameters@1",
  "cwd_policy": {
    "workspace_relative_path": "."
  },
  "environment_policy_ref": "environment:minimal-project-check@1",
  "resource_policy_ref": "resource:bounded-project-check@1",
  "exit_code_policy_ref": "exit-policy:project-check@1",
  "side_effect_policy_ref": "effects:check-report-only@1",
  "process_control_ref": "process-control:isolated-tree@1"
}
```
本例参数 schema 约束 suite 为 unit 或 contract，report_path 为有效授权报告路径。构造器保留各 argv 元素的参数边界，不将槽位拼接为 shell 文本。

### 7.2 命令构造与启动

1. 核对 profile、执行入口、参数及工作目录均属于冻结授权。
2. 由参数构造器生成 argv，不通过 shell 字符串拼接，也不执行模型插入的管道、重定向或命令替换。
3. profile 如确需脚本，由受审查的固定脚本入口和类型化参数表达，不能将自由文本放到解释器执行参数。
4. 按 environment_policy 创建必要环境；不完整继承主机凭据和未声明环境变量。
5. 绑定当前操作与受控进程树／执行单元，记录进程引用及实际启动状态。
6. 持续采集 stdout／stderr 和控制信号，完成后核对退出、子进程及实际变更。

注册配置若需要联网或访问额外服务，应显式声明并具备相应隔离与授权；不能由业务输入默认启用。

### 7.3 进程权限与隔离

文件 API 的路径检查不能限制子进程任意读写主机资源。受控 argv 和事后差异检查也不能替代进程隔离。

命令能力启用前，执行环境须验证其能约束所声明的可读／可写资源、凭据、网络、子进程和资源使用，并阻止越界副作用。源代码、测试、构建插件和脚本都属于实际执行内容，不能因入口名称为“测试”而默认无副作用。

隔离实现可按环境选型，但未验证或达不到任务要求时，返回 TOOL_PROFILE_UNSUPPORTED，不在具有更宽主机权限的环境中直接运行。执行后差异用于证据与补充检测，不作为“从未越界”的唯一证明。

### 7.4 退出结果与日志

命令退出码的语义由 profile 明确。例如本文件的检查夹具约定：0 表示规定检查通过，1 表示检查执行完成但产品检查失败，其他值按工具故障规则解释。该规则不是所有测试工具的通用事实。

stdout 和 stderr 均有独立上限与受控日志引用。达到上限后按 profile 停止操作，或继续排空但不再保留，并标 truncated，避免采集阻塞。必要报告缺失、格式不符或输出不完整时，不能据退出码为 0 就声称完整验收通过。

日志、报告和临时文件写入环境声明的区域。对外结果仅提供有界摘要和引用，正文与敏感内容按 B03 权限保存。

### 7.5 命令请求模板

本例的 profile 参数只允许已注册的 suite 值和授权报告路径，不允许任意追加选项。

```json
{
  "tool_contract_version": "b04.tool.v0.1",
  "protocol_version": "b04.exec.v0.2",
  "execution_mode": "mock",
  "invocation_ref": {
    "project_id": "product-cli-demo",
    "run_id": "run-tool-demo-001",
    "invocation_id": "invoke-implement-001",
    "task_id": "CLI-PARSE",
    "attempt_id": 1,
    "dispatch_id": "dispatch-tool-001"
  },
  "operation_id": "op-check-parser-001",
  "tool_name": "run_check",
  "tool_version": "1",
  "arguments": {
    "command_profile_ref": "command:project-checks@1",
    "parameters": {
      "suite": "unit",
      "report_path": "reports/unit-result.json"
    }
  },
  "input_snapshot_id": "snapshot-tool-001",
  "input_snapshot_sha256": "<snapshot_sha256>",
  "lease_ref": "<active_lease_ref>",
  "tool_config_ref": "tools:cli-implementation@1",
  "workspace_ref": "workspace:product-cli-demo/attempt-1",
  "timeout_seconds": 30,
  "deadline_at": "2026-11-16T02:11:30.000Z",
  "origin": {
    "source": "self_check",
    "model_call_id": null,
    "tool_call_id": null,
    "check_ref": "check:cli-parser-unit@1"
  },
  "tool_binding_ref": "binding:cli-run-check@1"
}
```
## 8 超时、停止与预算

### 8.1 有效时限

有效截止取请求 timeout、deadline、attempt 剩余期限、工具／命令 profile 上限及租约有效条件的最严格约束。排队与准备时间是否占用须在 profile 固定；基础版从首次接收时计入，不因重新查询或请求重传重置。

超时或控制撤销后不再启动新操作。文件操作在实际提交前复核；若已提交但响应丢失，记录未知并核对，不能声称请求超时意味着文件未写入。

### 8.2 停止流程

1. 持久化停止原因、时间和操作身份，禁止新副作用。
2. 对可中断操作发停止信号，对命令控制整个执行单元及子进程。
3. 在有界清理时间内核查实际结束、输出、部分写入及外部副作用。
4. 确认全部结束且无未明执行时返回 confirmed；可确认仍在停止时为 pending，状态无法判定时为 unknown。
5. 继续保存查询与迟到结果，不用第二次操作覆盖原结果。

正常完成的 stop_status=confirmed 表示已经确认操作结束，不表示曾发送停止命令。进程入口退出但子进程或外部副作用未核清时，不能据此确认操作全部结束。

清理可以在执行时限之后进行，但只用于停止和核对，不是延长命令正常运行时间。无法确认停止时隔离工作区和结果，B02 核对后才能安全释放资源或重派。

### 8.3 资源与重试

预算使用协议第 14.3 节 BudgetTicket。调用包 limits 是 attempt 上限，父 invocation 额度跨 attempt 保留；executor 按 OperationRef 原子预留和结算，runner 不另扣同一次执行。observe／report／cleanup／transport 使用独立有限额度，不能用业务额度耗尽阻断停止核对。

工具实际执行和自检按 runner 的共享预算记账；预检明确未执行不记实际执行次数。未知操作保留预留或未结算记录，不能当作零消耗。

executor 默认不自动重试命令、替换目标或重新分配 operation_id。局部安全重读或其他恢复只有在明确策略与真实状态下允许；结果不明的写入和命令先核对。失败重派和 retry_count 由 B02 管理。

## 9 统一结果与反馈

### 9.1 ToolResult

| 字段 | 说明 |
| --- | --- |
| tool_contract_version、protocol_version、execution_mode | 模块与上层版本及模式 |
| invocation_ref、operation_id、tool_binding_ref、tool_name、tool_version | 与请求一致的真实操作及绑定身份 |
| input_snapshot_id、input_snapshot_sha256 | 与请求一致的冻结输入；runner 反馈和证据须保持关联 |
| status | completed、in_progress、rejected、failed、timed_out、stopped 或 unknown |
| result_code | 完成标识或具体 TOOL_ 分类 |
| payload | completed 时为经输出 schema 校验的内容；in_progress／故障／未知时可为 null |
| output_refs、changes | 实际输出与变更引用、前后校验值，不依据模型声明生成 |
| exit_code | 实际进程退出码，文件工具或不可得时为 null |
| timing | 实际起止、执行及清理耗时 |
| stop_status | 已结束为 confirmed；未请求停止且运行中为 null；停止核对使用 confirmed／pending／unknown |
| side_effects_state | none、verified、partial 或 unknown，说明副作用核对情况 |
| error | 统一错误及阶段、证据和恢复建议，或 null |
| operation_record_ref | 持久记录引用 |

completed 只表示工具操作按其契约完成。payload 中的 check_outcome 仍可能是 failed；它不代表 Agent 任务成功或独立验收通过。业务检查失败与工具执行故障分开。

### 9.2 检查失败结果模板

本例与第 7.5 节请求对应：检查程序完整运行并返回夹具定义的 1，故工具状态为 completed，自检结论为 failed。

```json
{
  "tool_contract_version": "b04.tool.v0.1",
  "protocol_version": "b04.exec.v0.2",
  "execution_mode": "mock",
  "invocation_ref": {
    "project_id": "product-cli-demo",
    "run_id": "run-tool-demo-001",
    "invocation_id": "invoke-implement-001",
    "task_id": "CLI-PARSE",
    "attempt_id": 1,
    "dispatch_id": "dispatch-tool-001"
  },
  "operation_id": "op-check-parser-001",
  "tool_name": "run_check",
  "tool_version": "1",
  "status": "completed",
  "input_snapshot_id": "snapshot-tool-001",
  "input_snapshot_sha256": "<snapshot_sha256>",
  "result_code": "TOOL_COMPLETED",
  "payload": {
    "check_ref": "check:cli-parser-unit@1",
    "check_outcome": "failed",
    "stdout_ref": "<stdout_ref>",
    "stderr_ref": "<stderr_ref>",
    "report_ref": "<check_report_ref>",
    "stdout_truncated": false,
    "stderr_truncated": false
  },
  "output_refs": [
    "<check_report_ref>"
  ],
  "changes": [
    {
      "path": "reports/unit-result.json",
      "change_type": "created",
      "before_sha256": null,
      "after_sha256": "<report_sha256>"
    }
  ],
  "exit_code": 1,
  "timing": {
    "started_at": "2026-11-16T02:11:00.000Z",
    "finished_at": "2026-11-16T02:11:01.500Z",
    "execution_duration_ms": 1500,
    "cleanup_duration_ms": 0
  },
  "stop_status": "confirmed",
  "side_effects_state": "verified",
  "error": null,
  "operation_record_ref": "<completed_operation_record_ref>",
  "tool_binding_ref": "binding:cli-run-check@1"
}
```
verified 表示在已执行隔离约束下，声明副作用与记录已核对，不是仅靠本地目录差异推断主机全部未变。

### 9.3 超时及停止未知模板

这是同类请求的独立超时夹具，使用不同 operation_id。执行到 30 秒触发停止，再进行 5 秒清理，仍不能确认全部结束。清理不赋予继续业务执行的权限。

```json
{
  "tool_contract_version": "b04.tool.v0.1",
  "protocol_version": "b04.exec.v0.2",
  "execution_mode": "mock",
  "invocation_ref": {
    "project_id": "product-cli-demo",
    "run_id": "run-tool-demo-001",
    "invocation_id": "invoke-implement-001",
    "task_id": "CLI-PARSE",
    "attempt_id": 1,
    "dispatch_id": "dispatch-tool-001"
  },
  "operation_id": "op-check-timeout-001",
  "tool_name": "run_check",
  "tool_version": "1",
  "status": "timed_out",
  "input_snapshot_id": "snapshot-tool-001",
  "input_snapshot_sha256": "<snapshot_sha256>",
  "result_code": "TOOL_TIMEOUT",
  "payload": null,
  "output_refs": [
    "<partial_stdout_ref>"
  ],
  "changes": [],
  "exit_code": null,
  "timing": {
    "started_at": "2026-11-16T02:12:00.000Z",
    "finished_at": "2026-11-16T02:12:35.000Z",
    "execution_duration_ms": 30000,
    "cleanup_duration_ms": 5000
  },
  "stop_status": "unknown",
  "side_effects_state": "unknown",
  "error": {
    "code": "TOOL_TIMEOUT",
    "category": "timeout",
    "message": "检查超时，停止与副作用尚未确认",
    "stage": "process_cleanup",
    "recoverability": "reconcile_required",
    "requested_action": "query_and_isolate_before_retry",
    "evidence_refs": [
      "<timeout_record_ref>"
    ]
  },
  "operation_record_ref": "<timeout_operation_record_ref>",
  "tool_binding_ref": "binding:cli-run-check@1"
}
```
changes=[] 仅表示没有已确认的变更条目，side_effects_state=unknown 时不能解释为“未写入任何内容”。该夹具请求应使用其自身 deadline，不复用前一请求已经过期的时间。

### 9.4 runner 与外部反馈

所有结果及 ToolFeedback 状态、字段按协议第 14.1、14.5 节。in_progress 的 payload、error、finished_at 和最终耗时为 null，stop_status 可为 null；runner 仅查询原操作，不把它标成未知失败或完成。

runner 核验身份、绑定、结构和版本，从真实结果及原模型意图生成完整 ToolFeedback，保留 status、result_code、error、exit_code、stop_status、side_effects_state、变化和引用；不能只回填 payload。不可信 stdout／文件内容保持为数据。

- completed 且检查失败：形成 failed 自检证据，按规则可提交候选，不伪报工具故障或业务通过。
- in_progress：仅查询原 OperationRef，不重发、不生成完成的 tool 消息。
- rejected／failed：按协议第 14.6 节映射字段和处置，保留操作和副作用情况。
- timed_out／unknown：停止新副作用，查询／隔离，不用新编号重试。
- stopped：核验停止范围，由 runner 处理 StopReceipt 与收尾。
- 结果内容或报告不完整：明确标记，不能生成虚构通过记录。

executor 不直接调用 B02 的 submit_event，也不关闭缺陷、接受产物或更新全局状态。runner 将结果关联到自检、Manifest 和事件；B06 独立判断，B02 决定后续。

### 9.5 进行中返回模板

同号重传确认原请求仍在执行时，返回固定 Result 类型；下面是前述成功夹具完成前的观察，不是第二次执行或另一个终结结果。runner 仅查询原引用，不重发或把它回填为完成。

```json
{
  "tool_contract_version": "b04.tool.v0.1",
  "protocol_version": "b04.exec.v0.2",
  "execution_mode": "mock",
  "invocation_ref": {
    "project_id": "product-cli-demo",
    "run_id": "run-tool-demo-001",
    "invocation_id": "invoke-implement-001",
    "task_id": "CLI-PARSE",
    "attempt_id": 1,
    "dispatch_id": "dispatch-tool-001"
  },
  "operation_id": "op-check-parser-001",
  "tool_name": "run_check",
  "tool_version": "1",
  "status": "in_progress",
  "input_snapshot_id": "snapshot-tool-001",
  "input_snapshot_sha256": "<snapshot_sha256>",
  "result_code": "TOOL_IN_PROGRESS",
  "payload": null,
  "output_refs": [],
  "changes": [],
  "exit_code": null,
  "timing": {
    "started_at": "2026-11-16T02:11:00.000Z",
    "finished_at": null,
    "execution_duration_ms": null,
    "cleanup_duration_ms": null
  },
  "stop_status": null,
  "side_effects_state": "unknown",
  "error": null,
  "operation_record_ref": "<running_operation_record_ref>",
  "tool_binding_ref": "binding:cli-run-check@1"
}
```

## 10 错误分类与映射

| TOOL_ 分类 | 情况 | 上层处理 |
| --- | --- | --- |
| TOOL_REQUEST_INVALID | 内部参数、类型或版本字段不合法 | 已接收 invocation 使用 EXEC_TOOL_ERROR，保留原 code，不追溯改成同步拒收 |
| TOOL_NOT_REGISTERED／TOOL_DISABLED | 版本未发布、已禁用或不可解析 | EXEC_CAPABILITY_UNAVAILABLE |
| TOOL_PROFILE_UNSUPPORTED | 必要隔离、环境、停止或原子能力无法满足 | EXEC_CAPABILITY_UNAVAILABLE |
| TOOL_LEASE_INVALID | 授权、attempt 或租约失效 | EXEC_LEASE_INVALID，禁止新执行 |
| TOOL_SCOPE_DENIED／TOOL_PATH_INVALID | 路径、资源、命令或参数超出有效范围 | 写操作使用 EXEC_WRITE_SCOPE；读取／执行拒绝使用 EXEC_TOOL_ERROR 并保留 permission 分类 |
| TOOL_OPERATION_CONFLICT | 同 operation_id 对应不同指纹 | EXEC_TOOL_ERROR，明确属于操作层冲突 |
| TOOL_FILE_CONFLICT | 创建目标已存在或替换前置哈希不匹配 | EXEC_TOOL_ERROR，保留并发证据，不覆盖 |
| TOOL_IO_ERROR | 实际读写失败，副作用须核对 | EXEC_TOOL_ERROR |
| TOOL_COMMAND_START_FAILED | 进程入口或环境启动失败 | EXEC_TOOL_ERROR |
| TOOL_COMMAND_FAILED | 不属于声明检查结论的命令失败 | EXEC_TOOL_ERROR |
| TOOL_OUTPUT_INVALID | 结果、报告或元数据无法满足工具契约 | EXEC_TOOL_ERROR，不能伪造结果 |
| TOOL_OUTPUT_LIMIT | 输出超过约束且不能提供规定证据 | EXEC_TOOL_ERROR 或由 runner 标记检查证据不全 |
| TOOL_TIMEOUT | 操作达到时限 | EXEC_TIMEOUT，核对停止情况 |
| TOOL_BUDGET_EXHAUSTED | 工具、资源或输出额度不足 | EXEC_BUDGET_EXHAUSTED |
| TOOL_RESULT_UNKNOWN | 不能确定操作结果或副作用 | EXEC_TOOL_ERROR，停止盲目重放 |
| TOOL_STOPPED | 确认停止后的结果标识 | 不新增全局错误，由 runner 按停止流程处理 |
| TOOL_COMPLETED | 工具契约意义上完成 | 由 payload 判断专业结果，不自动标成功 |
| TOOL_IN_PROGRESS | 确认原操作仍在执行 | 返回 in_progress 的 ToolResult，仅查询，不映射成执行故障 |

上层现有 EXEC_WRITE_SCOPE 不覆盖所有读取／执行拒绝。基础设计采用上述兼容映射，并记录 denied_action／resource 和原始 TOOL_ 分类；是否增加通用权限错误由 B02/B04/B06 确认，不静默修改协议。

错误与恢复建议不授予重派权限。检查工具的 1 只有在当前 exit_code_policy 明确规定时才解释为业务失败，不能对所有命令统一推断。

## 11 操作记录、恢复与一致性

### 11.1 OperationSnapshot

至少返回 operation_ref、指纹、注册版本、阶段、执行资源、实际结果／日志引用、停止与副作用状态、预算结算和最近核对时间。

本地阶段可为 prepared、running、stop_pending、finished 或 unknown；ToolResult.status 表达该次返回结论，二者不替代任务状态。后续取得停止或副作用依据时追加核对记录，保留原未知结果，不篡改历史。

### 11.2 恢复流程

| 检查点 | 恢复动作 |
| --- | --- |
| 已登记但未执行，授权有效 | 核对意图和预算后按同一操作继续 |
| 文件替换已确认、结果未回传 | 核对实际身份／哈希与原记录，返回原结果 |
| 文件提交可能完成 | 查询目标与独占控制证据，不能直接重复写 |
| 进程已启动，结果未记录 | 核对受控执行单元、日志和副作用，不再启动第二个 |
| 已确认完成 | 复用结果，不重新执行命令 |
| 停止或外部副作用未知 | 隔离资源并交 runner/B02 核对 |
| 旧 attempt 迟到结果 | 保存历史，不能覆盖新 attempt 或继续写入 |

内容哈希相同本身不能证明整个命令已执行，也不能证明无其他副作用。文件系统提交与共享记录不一定构成跨系统事务，无法恢复确定性时必须报告 unknown。

### 11.3 日志与审计

记录身份、注册与配置版本、有效授权摘要、请求指纹、执行意图、实际参数结构、工作区、时序、资源、变更、停止和结果引用。凭据不写入；必要敏感参数采用受控引用或脱敏标记，不能在公共摘要回显。

公共记录可追溯而不需要完整原始正文。日志截断、失效、缺失或脱敏均显式标记，不能通过空日志推断无错误。

## 12 场景与验收

### 12.1 典型场景

1. **PM 规划**：只有产物读取或结构检查工具，无业务代码写入权限；无 Git 不阻断合法调用。
2. **代码实现**：在隔离工作区创建／条件替换文件，真实变更交 runner 封存候选。
3. **独立检查**：按配置运行检查，检查不通过仍与工具故障分开；独立性由 Workflow/B06 保障。
4. **跨产品**：CLI、Web 或其他产品更换工具与命令配置，不在核心中写 lost_at、固定接口或任务编号。
5. **取消与恢复**：停止父入口但未核清执行单元时不能报告全部停止，未知副作用不能重放。

### 12.2 验收项

下表为拟议 TE 检查项，使用隔离夹具及独立证据，不在用户主机上无约束执行反例。

| 编号 | 动作 | 通过标准 |
| --- | --- | --- |
| B04-TE-01 | 注册、发布、弃用和禁用工具版本 | 定义不可变，目录状态与新操作授权正确 |
| B04-TE-02 | 模型尝试注册或调用未授权工具 | 管理／运行分离，未授权调用被拒绝 |
| B04-TE-03 | 相同操作编号重传及异参数请求 | 复用已确认结果或拒绝冲突，无重复副作用 |
| B04-TE-04 | 过期 lease、旧 attempt 和跨项目目标 | 拒绝新执行，保留可查原因 |
| B04-TE-05 | 文件上跳、绝对／歧义路径、symlink／junction | 真实目标越界被阻止，不依赖字符串前缀 |
| B04-TE-06 | 路径校验后替换对象、硬链接或并发变更 | 不原位修改不受控目标，资源身份和条件有效 |
| B04-TE-07 | 文本解码、片段读取和大小超限 | 返回真实范围与完整性，编码错误不被掩盖 |
| B04-TE-08 | 创建冲突及条件替换哈希不符 | 不覆盖他人内容，前后证据完整 |
| B04-TE-09 | 原子文件提交或记录阶段中断 | 按实际结果核对，无盲目二次写入 |
| B04-TE-10 | 命令入口、参数、cwd 或环境注入 | 只执行已授权 profile，未声明选项被拒绝 |
| B04-TE-11 | 固定命令尝试写范围外资源 | 已验证隔离阻止越界；环境无能力时拒绝启动 |
| B04-TE-12 | 命令退出 0、规定检查失败和异常退出 | 语义按 profile 分类，检查失败不冒充工具故障或通过 |
| B04-TE-13 | stdout／stderr 大量输出 | 有界采集与正确截断／停止，必要证据不伪造 |
| B04-TE-14 | 超时、停止及子进程未结束 | 不误报 confirmed，保留部分或未知副作用 |
| B04-TE-15 | 重传超时请求或查询 | 不延长原截止，不启动第二个未知操作 |
| B04-TE-16 | 预算不足和未结算操作 | 无新执行或零消耗伪装，计量与 runner 一致 |
| B04-TE-17 | 结果 schema、变更与实际哈希核对 | 不接受虚假文件、退出码或完整性声明 |
| B04-TE-18 | 只读／命令工具被拒绝与错误映射 | 原因和资源动作可追溯，上层不误改全局状态 |
| B04-TE-19 | mock／live 及两种产品配置 | 模式清晰，核心不绑定业务，模拟不冒充真实证据 |
| B04-TE-20 | 已完成操作后迟到停止或旧结果 | 历史追加，不覆盖新 attempt 或触发重复副作用 |
| B04-TE-21 | 同号工具请求仍在执行 | 返回 in_progress 的 ToolResult，未请求停止时 stop_status 为 null |
| B04-TE-22 | 工具别名、版本和内容暂存 | 绑定唯一，显式归一与执行 schema 一致，重复意图复用草稿 |
| B04-TE-23 | 执行授权撤销后查询、停止和诊断 | 对应独立 grant 有效时可处理原资源，不得新执行业务 |
| B04-TE-24 | 完整反馈及执行阶段参数错误 | 不只回填 payload，内部请求错误不改为顶层同步拒收 |

B04 自检，B05 交叉评审展示与反馈，B02/B03 确认控制和存储，B06 独立验证，专业块确认检查语义。静态解析 JSON、读取文档和进程能够启动均不能代替隔离及真实行为验收。

## 13 实现计划与待确认

### 13.1 后续顺序

1. 确认工具定义、运行请求、授权解析和结果 schema。
2. 实现目录、校验、去重记录与确定性 mock。
3. 实现产物／文件读取、原子创建和条件替换。
4. 选型并验证命令隔离、argv 构造、输出采集及进程控制。
5. 与 runner 完成操作查询、停止、检查语义及恢复。
6. 通过独立反例和跨产品验证后，再发布真实支持能力。

本文仅交付设计，没有创建驱动、执行命令、改写业务文件、运行隔离反例或修改四份依据文档。

### 13.2 待确认事项

| 编号 | 内容 | 确认方 |
| --- | --- | --- |
| B04-TE-OQ-01 | 工具定义、目录发布和实际授权管理接口 | B02/B03/B04 |
| B04-TE-OQ-02 | 读取范围、租约代际、资源锁及路径身份机制 | B02/B03/B04 |
| B04-TE-OQ-03 | 原子文件提交、并发条件与未知结果核对 | B03/B04/B06 |
| B04-TE-OQ-04 | 命令配置、环境隔离、网络及子进程控制实现 | B02/B04/B06 |
| B04-TE-OQ-05 | 退出码、输出契约、截断与独立检查规则 | B01/B06及专业块 |
| B04-TE-OQ-06 | 请求期限、清理时间、预算与未结算状态 | B02/B03/B04 |
| B04-TE-OQ-07 | 通用权限错误映射与 runner 反馈契约 | B02/B04/B06 |
| B04-TE-OQ-08 | 日志访问、展示及工具能力验收发布 | B03/B05/B06 |

平台共同接口按总设计评审，B04/B05 固定交叉评审。用户产品授权与审批遵循其 Workflow，不能把待实现或未经验证的隔离能力标为已支持。

## 14 修订记录

| 版本 | 日期 | 内容 | 状态 |
| --- | --- | --- | --- |
| v0.1 | 2026-11-16 | 明确工具注册、授权、文件读写、命令、超时停止、结果及恢复设计 | 原草案 |
| v0.1.1 | 2026-11-16 | 对齐独立控制授权、工具绑定、内容暂存、in_progress、完整反馈、预算和阶段错误契约 | 待评审 |
