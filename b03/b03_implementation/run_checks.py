"""B03 实现自检入口。

在工作区根目录运行：python -m b03_implementation.run_checks
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
ROOT = PKG_DIR.parent


def main() -> int:
    suite = unittest.defaultTestLoader.discover(
        str(PKG_DIR / "tests"), pattern="test_*.py", top_level_dir=str(ROOT)
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
