"""全量验证脚本：一次跑完所有工作块 + 跨块闭环。

用法（仓库根目录）：
    python workflow_runtime/run_all_checks.py

CI 中分工作块运行（便于定位失败），本地用它一把梭。
任一步失败即以非零退出，并打印失败步骤。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

STEPS = [
    ("B01 生成/校验/基线", REPO / "b01-spec-planner", ["python", "run_checks.py", "all", "--allow-reference"]),
    ("B01 单元测试", REPO / "b01-spec-planner", ["python", "-m", "pytest", "-q"]),
    # 注意：不要传 --previous-plan 指向不存在的文件，否则会把已入库的 fixture
    # 当成“新区划”而递增 plan_version，导致每次跑检查都产生无意义 diff。
    ("B01 动态计划", REPO / "b01-spec-planner", [
        "python", "run_checks.py", "plan",
        "--spec", "docs/fixtures/campus-lost-found.spec.json",
        "--out-dir", "docs/fixtures",
        "--plan-name", "campus-lost-found.plan.json",
        "--traceability-name", "campus-lost-found.traceability.json",
    ]),
    ("B02 单元测试", REPO / "b02-workflow-agent", ["python", "-m", "unittest", "discover", "-s", "tests"]),
    ("B03 单元测试", REPO, ["python", "-m", "pytest", "b03/b03_implementation", "-q"]),
    ("B04 单元测试", REPO / "b04-agent-integration", ["python", "-m", "pytest", "-q"]),
    ("B06 单元测试", REPO / "b06-quality-consensus", ["python", "-m", "pytest", "-q"]),
    ("B06 冒烟", REPO / "b06-quality-consensus", ["python", "-m", "tests.smoke"]),
    ("跨块闭环测试", REPO, ["python", "-m", "pytest", "workflow_runtime/test_closed_loop.py", "-q"]),
    ("契约一致性检查", REPO, ["python", "workflow_runtime/verify_contracts.py"]),
    # 最终验收 13 项；--skip-ci 因为本脚本要在无 token 的 CI 环境里也能跑。
    # 声明“全部完成”前请单独运行不带 --skip-ci 的版本。
    ("最终验收（除 CI 外）", REPO, ["python", "workflow_runtime/verify_acceptance.py", "--skip-ci"]),
    ("闭环演示（成功）", REPO, ["python", "-m", "workflow_runtime", "pipeline", "--scenario", "success"]),
    ("闭环演示（重试）", REPO, ["python", "-m", "workflow_runtime", "pipeline", "--scenario", "retry"]),
    ("闭环演示（阻断）", REPO, ["python", "-m", "workflow_runtime", "pipeline", "--scenario", "blocked"]),
    ("闭环演示（缺证据）", REPO, ["python", "-m", "workflow_runtime", "pipeline", "--scenario", "evidence"]),
]


def main() -> int:
    failures: list[str] = []
    for label, cwd, command in STEPS:
        print(f"\n=== {label} ===")
        print(f"$ cd {cwd.relative_to(REPO) if cwd != REPO else '.'} && {' '.join(command)}")
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()][-6:]
        for line in tail:
            print(f"  {line}")
        if result.returncode != 0:
            failures.append(label)
            print(f"  !! 失败 (exit {result.returncode})")

    print()
    if failures:
        print(f"FAILED: {len(failures)} 个步骤失败 -> {', '.join(failures)}")
        return 1
    print(f"OK: {len(STEPS)} 个步骤全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
