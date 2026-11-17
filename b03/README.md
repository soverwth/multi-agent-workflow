# 第十组 · B03 黑板数据 Agent 交付包

> 负责人：陈怡雯 · 角色标识：`BlackboardAgent`
> 版本：v1.0 · 更新时间：2026-11-17
> 课程：软件工程与项目实践
> 案例：校园失物招领系统（多智能体协作开发平台贯穿案例）
> 上游基线：《第十组 设计规格与开发任务编排.docx》R1 / S1 / C1

本包是 B03 工作块的完整交付：设计文档、三份对接单、可运行实现、自检用例。

## 1. 交付清单

| 文件 | 说明 |
|---|---|
| `B03_黑板数据Agent_设计文档_v1.0.md` | B03 设计规格：存储/事件协议、状态迁移与快照、租约接口、T02 数据层、验收映射 |
| `B03-B01_规格与Schema对齐对接单_v1.0.md` | 对接 B01（蔡昀漪）：输入版本、字段边界、追溯编号，10 项待确认 |
| `B03-B02_状态与租约接口对接单_v1.0.md` | 对接 B02（陈昱希）：接口签名、幂等、回调、租约、恢复，8 项待确认 |
| `B03-B06_验收证据与测试数据对接单_v1.0.md` | 对接 B06（吴天昊）：证据字段、T09 覆盖、夹具隔离，9 项待确认 |
| `b03_implementation/` | 可运行实现与测试（见下） |

## 2. 目录结构

```text
.
├── README.md
├── .gitignore
├── B03_黑板数据Agent_设计文档_v1.0.md
├── B03-B01_规格与Schema对齐对接单_v1.0.md
├── B03-B02_状态与租约接口对接单_v1.0.md
├── B03-B06_验收证据与测试数据对接单_v1.0.md
└── b03_implementation/
    ├── __init__.py
    ├── config.py            # 双库路径、租约默认值
    ├── errors.py            # 领域错误码与 HTTP 映射
    ├── blackboard.py        # task_store：状态、租约、快照、事件、检查点、证据、只读视图
    ├── artifact_store.py    # artifact_store：只追加、版本绑定、快照有效才可读
    ├── campus_db.py         # 案例 T02 数据层：三张表、校验、隐私视图、事务、测试数据
    ├── run_checks.py        # 自检入口
    ├── migrations/
    │   ├── 001_create_user.sql
    │   ├── 002_create_lost_item.sql
    │   └── 003_create_claim_application.sql
    └── tests/
        ├── __init__.py
        ├── test_blackboard.py
        └── test_campus_db.py
```

## 3. 环境要求与快速开始

- Python 3.10+（开发验证版本 3.13.14）
- **仅使用 Python 标准库**，无需 `pip install` 任何第三方包

在工作区根目录执行：

```bash
python -m b03_implementation.run_checks
```

预期输出：`Ran 19 tests ... OK`

## 4. 关键设计约束

| 约束 | 落地方式 |
|---|---|
| B02 独占状态写入 | `cas_state` 用 `rev` 乐观锁，版本不符即拒绝 |
| 事件去重、过期回调不推进状态 | `event_id` 幂等；attempt/snapshot 不匹配打 `stale` 标记仅入日志 |
| 中断后可恢复、不重复执行 | 事件与检查点同事务；租约 TTL + 幂等派发键 + `reclaim_expired_leases` |
| 任务与产物版本一致 | 输入快照冻结；`get_artifacts_for_task` 只返回快照有效的产物 |
| 两类数据分开 | 黑板与校园业务分别使用 `blackboard.db` / `campus.db` |
| 凭据受保护 | PBKDF2 哈希；`LostView` 不含 `publisher_id`/联系方式/凭据；导出不含 `password_hash` |
| 防重复申请 | `(lost_item_id, applicant_id)` 唯一约束；资格检查与插入同一事务 |

## 5. 与组员对接

三份对接单均含**留空填写栏**，请对应负责人填入结论后回传：

- B01 蔡昀漪 → `B03-B01_规格与Schema对齐对接单_v1.0.md`
- B02 陈昱希 → `B03-B02_状态与租约接口对接单_v1.0.md`（固定交叉评审 `B02 ↔ B03`）
- B06 吴天昊 → `B03-B06_验收证据与测试数据对接单_v1.0.md`

B04/B05 的接口在 B02 对接单第 1、6 节一并定义，由 B02 转发对齐。

## 6. 合并到小组仓库的建议

1. 从共同仓库已接受提交创建独立分支：`feature/b03-blackboard`
2. 仅提交本包文件，不要覆盖受保护主线或他人文件
3. 通过合并请求（PR）接受 B02 交叉评审与 CI 检查后再合并
4. 接口变更须同步所有消费方，并在新提交上重跑受影响检查

## 7. 注意事项

- 测试数据为虚构/脱敏样例，不含真实个人信息。
- 运行时生成的 `*.db`、`checkpoint.json`、`__pycache__` 已由 `.gitignore` 排除，**不要提交**。
- 本实现采用设计文档开放问题 1 的当前假设（SQLite 标准库 + 双库分离）；若小组改选纯 JSON 检查点，接口层可保持不变，仅替换持久化实现。

## 8. 未决事项

租约 TTL 数值、事件 schema 最终字段、测试数据脱敏规则、`SUCCEEDED` 失效触发条件，分别待 B02/B01/B06/六人确认后更新版本。
