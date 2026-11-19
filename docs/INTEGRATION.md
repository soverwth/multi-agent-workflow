# integration 集成运行说明

`integration` 是项目的跨工作块联调分支。当前包含 B01—B06 六个工作块，并通过
`workflow_runtime/` 装配成完整闭环。项目总体说明见根目录 [`README.md`](../README.md)，
跨块字段与接口契约见 [`docs/TASK_ORCHESTRATION.md`](TASK_ORCHESTRATION.md)。

## 一键集成验证

```powershell
# 契约一致性检查：B01 计划 ↔ B02 编排 ↔ B03 状态 ↔ B04 执行 ↔ B06 验收
python workflow_runtime/verify_contracts.py

# 闭环演示（四个场景）
python -m workflow_runtime pipeline --scenario success
python -m workflow_runtime pipeline --scenario retry
python -m workflow_runtime pipeline --scenario blocked
python -m workflow_runtime pipeline --scenario evidence
```

`verify_contracts.py` 与 CI 中 `Integration checks` 的
`Verify second-stage closed loop` 步骤是同一个脚本，因此本地通过即代表 CI 该步通过。

## B02/B05 单端口运行

集成演示由 B02 的 HTTP 服务同时提供 API 和 B05 页面，统一使用 `7100` 端口：

```powershell
cd frontend
npm ci
npm run build
cd ..\b02-workflow-agent
python -m backend.app --host 127.0.0.1 --port 7100
```

浏览器访问 `http://127.0.0.1:7100/`。B05 的 API 默认使用当前页面同源地址；
单独启动 Vite 只用于热更新，不属于正式集成启动路径。

## 各工作块验证

```powershell
# B01
cd b01-spec-planner
python run_checks.py all --allow-reference
python -m pytest -q

# B02
cd ..\b02-workflow-agent
python -m unittest discover -s tests -v

# B03
cd ..\b03\b03_implementation
python -m pytest -q

# B04
cd ..\..\b04-agent-integration
python -m pip install -e ".[test]"
python -m pytest -q

# B05
cd ..\..\frontend
npm ci
npm run build
npm run lint

# B06
cd ..\b06-quality-consensus
python -m pytest -q
python -m tests.smoke
```

## 跨块联调要点

1. **唯一状态写入者**：只有 B02 修改任务状态。B04 只返回执行结果，B06 只返回判定与事件。
   事件流中状态类事件（`TASK_ACCEPTED` 等）的 `producer` 恒为 `B02`；
   B06 的结论通过 `payload.gate` 和独立的 `DEFECT_CREATED` / `DEFECT_CLOSED` 事件体现。
2. **哈希格式统一**：B04 `SHA256_PATTERN` 与 B06 `SHA256_PATTERN` 都是
   `^[0-9a-f]{64}$`，避免“执行通过、验收必然拒绝”的错位。
3. **缺陷单点登记**：B06 的每条阻断 finding 只在 `_open_defects_for_findings`
   登记一次，去重键为 `(code, ref)`，不同测试编号的同类违规仍各自成条。
4. **模拟与真实分离**：B05 的「模拟推演」展示真实编排器产出的历史快照，
   「真实接口」实时读取 B02；连接失败时显示错误，不静默回退成模拟数据。

## 接口契约冒烟

B02 的 HTTP 接口由 `b02-workflow-agent/tests/test_task_api.py` 用真实服务器覆盖，
包括状态码（400/404/409）、事件绑定字段、事件游标分页、DAG 结构与回放一致性。

## 集成规则

先分别通过各工作块测试，再运行跨模块检查。集成分支只用于联调，不替代 `main` 的稳定发布；
通过 Pull Request 合并到 `main` 前应保留测试命令和结果。
