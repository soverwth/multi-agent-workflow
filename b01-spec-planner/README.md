# B01 规格规划 Agent 参考实现

本目录是第 10 组 B01（SpecPlannerAgent）的参考交付包，依据桌面《项目实践》中两份以“第10组”开头的团队文档生成：

- `docs/sources/第10组_第一部分_多智能体讨论与需求确认(1).docx`
- `docs/sources/第10组_第二部分_设计规格与开发任务编排(1).docx`

## 重要边界

团队文档明确说明案例推演不构成真实六人确认记录。因此本包默认生成 **REFERENCE_FROZEN** 参考基线，只用于设计、联调和评审，不得作为真实任务派发或“已确认 R1”的证据。真实使用前必须由六人填写确认状态，并重新运行基线冻结。

B01 不负责：流程调度状态写入（B02）、黑板持久化（B03）、Agent/模型执行（B04）、界面控制（B05）、测试结果宣布（B06）。

## 目录

```text
b01-spec-planner/
├── README.md
├── pyproject.toml
├── run_checks.py
├── B01_设计说明.md
├── B01_交付清单.md
├── B01_实验验收说明.md
├── docs/
│   ├── r1.json                       # 案例需求基线参考草案
│   ├── s1.json                       # 设计规格
│   ├── c1.json                       # 接口契约
│   ├── design_entries.json           # 设计条目
│   ├── plan.json                     # T01—T11 标准任务包与 DAG
│   ├── traceability.json             # 需求—设计—契约—测试—任务映射
│   ├── baseline_manifest.json        # T01 冻结登记清单
│   ├── change_request_template.md
│   ├── B03-B01_对齐回执摘要.md
│   └── sources/                      # 两份原始 DOCX 来源快照
├── src/b01/
│   ├── design.py                     # 文档转录的常量数据
│   ├── task_planner.py               # 任务生成与拓扑排序
│   ├── plan_validator.py             # 计划校验
│   ├── baseline.py                   # T01 基线登记
│   ├── cli.py                        # 命令行入口
│   └── __main__.py
└── tests/
```

## 快速开始

无需安装依赖，Python 3.10+：

```powershell
cd b01-spec-planner
python run_checks.py all --allow-reference
python -m unittest discover -s tests -v
```

预期：

- `all` 生成 6 个 JSON 资产、校验计划通过、冻结 `baseline_manifest.json`。
- 单元测试全部通过。
- `baseline_manifest.json` 的 `status` 为 `REFERENCE_FROZEN`，并带未确认警告。

如果想验证真实冻结门槛，去掉 `--allow-reference`，命令应以“六人确认未完成”失败退出。

安装为包（可选）：

```powershell
python -m pip install -e .
b01 all --allow-reference
```

## 输出接口

| 消费方 | 输入文件 | 说明 |
| --- | --- | --- |
| B02 | `docs/plan.json` | `spec_version`、`contract_version`、`tasks[]`、`topological_order` |
| B03 | `docs/c1.json`、`docs/design_entries.json`、`docs/plan.json` | 字段边界、事件/任务 schema 来源与 T01 冻结引用 |
| B04 | `docs/c1.json`、`docs/plan.json` | 11 个操作、错误映射、T03—T05 任务包 |
| B05 | `docs/c1.json`、`docs/traceability.json` | 展示字段与导出清单来源 |
| B06 | `docs/plan.json`、`docs/traceability.json` | 兼容只读计划校验；T09/T10 复核证据来源 |

## 任务包字段

每个任务包含文档 4.3.1 要求的字段：

`task_id`、`project_id`、`req_refs`、`design_refs`、`spec_version`、`contract_version`、`goal`、`inputs`、`outputs`、`depends_on`、`capability`、`write_scope`、`acceptance`、`required_test_ids`、`priority`、`timeout`、`retry_budget`，以及统一指令字段 `role_id`、`block_id`、`escalation_target`。

派发记录字段 `attempt_id`、`retry_count`、`revalidation_id` 和提交引用由 B02/B03 在执行阶段追加，B01 任务包不预填。
