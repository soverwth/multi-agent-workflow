"""无需安装即可运行 B01 自检：python run_checks.py all|validate|baseline。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from b01.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["all", "--allow-reference"]))
