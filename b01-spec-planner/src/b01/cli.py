"""B01 参考实现命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .baseline import BaselineError, register_baseline
from .design import C1_CONTRACT, DESIGN_ENTRIES, R1, S1
from .plan_validator import validate_plan
from .task_planner import build_plan, build_traceability

DOCS = Path(__file__).resolve().parents[2] / "docs"


def _write_json(name: str, payload: Any) -> Path:
    DOCS.mkdir(parents=True, exist_ok=True)
    path = DOCS / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(name: str) -> Any:
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


def cmd_generate(_: argparse.Namespace) -> int:
    plan = build_plan()
    written = [
        _write_json("r1.json", R1),
        _write_json("s1.json", S1),
        _write_json("c1.json", C1_CONTRACT),
        _write_json("design_entries.json", DESIGN_ENTRIES),
        _write_json("plan.json", plan),
        _write_json("traceability.json", build_traceability(plan)),
    ]
    for path in written:
        print(f"generated {path.relative_to(DOCS.parent)}")
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    plan = _read_json("plan.json")
    report = validate_plan(plan)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


def cmd_baseline(args: argparse.Namespace) -> int:
    try:
        manifest = register_baseline(
            plan=_read_json("plan.json"),
            contract=_read_json("c1.json"),
            r1=_read_json("r1.json"),
            s1=_read_json("s1.json"),
            allow_reference=args.allow_reference,
        )
    except BaselineError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    path = _write_json("baseline_manifest.json", manifest)
    print(f"frozen {path.relative_to(DOCS.parent)} status={manifest['status']}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    rc = cmd_generate(args)
    if rc:
        return rc
    rc = cmd_validate(args)
    if rc:
        return rc
    return cmd_baseline(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="b01", description="B01 SpecPlannerAgent 参考实现")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate", help="生成 R1/S1/C1/设计条目/计划/追溯 JSON").set_defaults(func=cmd_generate)
    sub.add_parser("validate", help="校验任务计划").set_defaults(func=cmd_validate)

    baseline = sub.add_parser("baseline", help="执行 T01 基线登记")
    baseline.add_argument(
        "--allow-reference",
        action="store_true",
        help="允许在无真实六人确认时生成 REFERENCE_FROZEN 参考基线",
    )
    baseline.set_defaults(func=cmd_baseline)

    all_cmd = sub.add_parser("all", help="生成、校验并冻结参考基线")
    all_cmd.add_argument("--allow-reference", action="store_true")
    all_cmd.set_defaults(func=cmd_all)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
