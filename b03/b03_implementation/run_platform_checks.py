"""B03 平台核心存储自检入口。

在 b03 目录运行：python -m b03_implementation.run_platform_checks
只跑 test_platform_store.py，不影响原有 19 项。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
ROOT = PKG_DIR.parent


def main() -> int:
    suite = unittest.defaultTestLoader.discover(
        str(PKG_DIR / "tests"), pattern="test_platform_store.py", top_level_dir=str(ROOT)
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
