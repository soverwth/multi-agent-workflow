> 本文档已按 2026-11-27 的 `feat/` + `task/` 一人多分支模型更新。
> 分支归属与命名规则见 `TEAM_DIVISION.md` 第三节；本文只讲日常操作与合并顺序。

# GitHub 协作与分支流程

## 一、成员首次拉取

仓库是 public，直接 clone 即可：

```powershell
git clone https://github.com/soverwth/multi-agent-workflow.git
cd multi-agent-workflow
```

拉取后先确认基线是绿的，再动手：

```powershell
python workflow_runtime/verify_contracts.py     # 期望：OK: 6 项闭环检查全部通过
python -m workflow_runtime pipeline --scenario success   # 期望：24/24 SUCCEEDED
```

然后按 `TEAM_DIVISION.md` 第〇节读仓库（开工五步 + 首周深读清单），再读自己那份 `docs/team/<成员>.md`。

> 本机若遇到 `github.com` 解析异常导致 push/pull 失败，见 `STAGE2_STATUS.md` 第五节的
> `curloptResolve` 办法，或改用 GitHub 网页端操作。

## 二、分支模型（一人多分支）

| 类型 | 命名 | 谁推 |
|---|---|---|
| 主干 | `main` | 每周发布责任人（经 PR） |
| 集成 | `integration` | 全体可 PR；保持与 `main` 同步 |
| 个人功能分支 | `feat/<阶段>-<主题>` | 该分支属主 |
| 任务分支 | `task/<成员>-<编号>-<短名>` | 该分支属主 |
| 修复分支 | `fix/<主题>` | 任何人 |

每个人的功能分支归属见 `TEAM_DIVISION.md` 3.2 节。**不要**再向旧的 `b01-spec-planner`、`b06-quality-consensus` 等
工作块分支提交——它们只读待清理。

## 三、日常开发

```powershell
git fetch origin

# 第一次开工：功能分支还没建，由属主自己建并推送（分支名与归属见 TEAM_DIVISION.md 3.2）
git switch -c feat/p1-agent-consensus origin/integration
git push -u origin feat/p1-agent-consensus

# 之后每张任务卡：从自己的功能分支切任务分支
git switch -c task/a-1-remove-gates feat/p1-agent-consensus

# 实现 + 测试
python workflow_runtime/run_all_checks.py
git push -u origin HEAD
```

> 注意：`feat/p1-*`、`feat/p2-*`、`feat/p3-*` 这类功能分支**目前还不存在**，
> 是按 `TEAM_DIVISION.md` 3.2 规划的；每位属主在第一次开工时按上面第一条命令自建。

PR 描述必须写明：任务卡编号、需求/文档引用、修改范围、测试命令、测试结果、已知限制。

## 四、合并顺序

1. 任务分支完成实现与自测；PR 目标 = **自己的功能分支**，同组另一人必审。
2. 功能分支稳定后，PR 到 `integration`；CI 绿 + 对组复核后合并。
3. 在 `integration` 跑跨模块联调与回归（`run_all_checks.py` + `ui_smoke` + `ui_layout`）。
4. B01 检查需求追溯，B06 检查证据与验收结果。
5. 每周五由轮值组把 `integration` 合并到 `main` 并打 tag。

## 五、同步与冲突

- 功能分支**每周至少 rebase 一次** `origin/main`；落后超过 20 个 commit 必须先同步再继续。
- 冲突先按**冻结的接口契约与版本记录**判断谁对谁错，再改代码。
- 共享接口变更必须同步所有消费方，并在 `integration` 上重跑受影响测试。
- 同一文件的多人改动约定见 `TEAM_DIVISION.md` 4.3 的「同文件对撞点表」（如 `app.py` 路由段、
  `RoundTableView.tsx`、`TaskGraph.tsx`），改之前先打招呼。
