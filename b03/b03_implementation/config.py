"""B03 实现配置。

存储选型（开放问题 1 的当前假设）：
- 使用 Python 标准库 sqlite3，无需外部依赖。
- 黑板过程数据与校园业务数据分别落在两个独立数据库文件，
  满足主文档 3.3 的“两类数据分开管理”。
- 检查点同时可导出为 JSON，兼容“检查点文件”的调度基线。
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BLACKBOARD_DB = BASE_DIR / "blackboard.db"
CAMPUS_DB = BASE_DIR / "campus.db"
CHECKPOINT_JSON = BASE_DIR / "checkpoint.json"

MIGRATIONS_DIR = BASE_DIR / "migrations"

DEFAULT_LEASE_TTL_SECONDS = 300
DEFAULT_EVENT_PAGE_SIZE = 100
