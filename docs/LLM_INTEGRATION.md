# 大模型 API 接入说明

第一阶段现在支持 OpenAI-compatible Chat Completions 接口。默认配置指向 DeepSeek，
也可以填写其他兼容服务或局域网模型。模型只负责生成结构化 R1 需求，B02 仍负责讨论状态、
六人确认和阶段迁移，B01 负责把确认后的 design spec 转成任务计划，B02 编排器负责执行。

## 方式一：统一工作台配置

启动 B02 后，在 B05 的“统一 SE Workflow 工作台”中填写：

- 模型 API 地址：`https://api.deepseek.com`
- 模型名称：`deepseek-chat`
- API Key：个人密钥

点击“保存并启用”。密钥只保存在当前 B02 进程的内存中，服务重启后需要重新填写。
页面显示“模型已连接”后，新建的第一阶段运行会调用模型生成 R1 草案。

## 方式二：启动前设置环境变量

PowerShell 示例：

```powershell
$env:SE_WORKFLOW_LLM_ENABLED = "true"
$env:SE_WORKFLOW_LLM_API_KEY = "你的 API Key"
$env:SE_WORKFLOW_LLM_BASE_URL = "https://api.deepseek.com"
$env:SE_WORKFLOW_LLM_MODEL = "deepseek-chat"
python -m backend.app --host 127.0.0.1 --port 7100
```

也可以使用 `DEEPSEEK_API_KEY` 作为 API Key 环境变量名。密钥不会写入仓库，
不要把它放入 README、截图或提交记录。

## 运行逻辑

```text
用户想法 + Proposal + 观点 + 异议
    ↓
OpenAI-compatible API 输出 JSON requirements
    ↓
B01 六人确认门槛
    ↓
R1 → design spec
    ↓
B01 动态任务计划 → B02 编排器 → B05 DAG
```

模型返回必须包含 `requirements` 数组。每项需要 `req_id`、`description`、`priority`、
`acceptance` 和可选 `constraints`。服务端会拒绝缺少验收条件、重复编号或超过 8 项的结果。

没有 API Key 时，系统使用本地领域规则兜底。聊天社交、失物招领、设备预约和通用系统会生成
不同的需求集合，方便离线演示。页面会显示“本地规则兜底”，不会把本地结果伪装成模型输出。

## API 状态接口

```text
GET  /api/llm/config
POST /api/llm/config
```

状态接口只返回 `key_configured`，不会返回密钥本身。`POST` 可以传入 `base_url`、`model`、
`api_key` 和 `enabled`，配置只对当前后端进程有效。
