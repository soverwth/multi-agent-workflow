"""案例 T02 数据层：User / LostItem / ClaimApplication。

约束来源：主文档 2.2.2 / 2.2.3。
- 与本包其他模块分离：只连 CAMPUS_DB，不写黑板状态。
- 凭据不可逆、不出现在公开响应；公开详情统一 LostView。
- 业务失败不产生部分写入；认领的状态/权限/插入在同一事务内完成。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import CAMPUS_DB, MIGRATIONS_DIR
from .errors import (
    DuplicateAccount,
    DuplicateClaim,
    Forbidden,
    InvalidField,
    InvalidState,
    NotFound,
    RequiredField,
)

_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _validate_str(value, field: str, lo: int, hi: int, *, required: bool = True) -> str | None:
    if value is None or value == "":
        if required:
            raise RequiredField(field)
        return None
    if not isinstance(value, str):
        raise InvalidField(field)
    stripped = value.strip()
    if not stripped or len(stripped) < lo or len(stripped) > hi:
        raise InvalidField(field)
    return stripped


def _validate_account(value) -> str:
    account = _validate_str(value, "account", 3, 64)
    if not _ACCOUNT_RE.fullmatch(account):  # type: ignore[arg-type]
        raise InvalidField("account")
    return account.lower()


def _validate_lost_at(value) -> str:
    if value is None or value == "":
        raise RequiredField("lost_at")
    if not isinstance(value, str):
        raise InvalidField("lost_at")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidField("lost_at") from exc
    if dt.tzinfo is None:
        raise InvalidField("lost_at")
    return dt.isoformat()


def hash_password(password: str, salt: str | None = None) -> str:
    """PBKDF2 不可逆哈希；示例用途，生产项目应使用更严格密钥管理。"""
    if not isinstance(password, str) or len(password) < 1:
        raise RequiredField("password")
    salt = salt or _uuid()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def _lost_view(row: sqlite3.Row | dict) -> dict:
    """公开视图：不含 publisher_id、联系方式或凭据。"""
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "location": row["location"],
        "lost_at": row["lost_at"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _claim_view(row: sqlite3.Row | dict) -> dict:
    return {
        "id": row["id"],
        "lost_item_id": row["lost_item_id"],
        "applicant_id": row["applicant_id"],
        "statement": row["statement"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


class CampusDB:
    """案例业务数据服务。"""

    def __init__(self, db_path=CAMPUS_DB, migrations_dir=MIGRATIONS_DIR):
        self.db_path = str(db_path)
        self.migrations_dir = Path(migrations_dir)
        self.initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._connect() as conn:
            for sql_file in sorted(self.migrations_dir.glob("*.sql")):
                conn.executescript(sql_file.read_text(encoding="utf-8"))
            conn.commit()

    # ---------- User ----------

    def register_user(self, account: str, password: str, nickname: str) -> dict:
        normalized = _validate_account(account)
        nickname_value = _validate_str(nickname, "nickname", 1, 30)
        user_id = _uuid()
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (id, account, password_hash, nickname, created_at) VALUES (?,?,?,?,?)",
                    (user_id, normalized, hash_password(password), nickname_value, _now()),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise DuplicateAccount("account") from exc
        return self.get_user_profile(user_id)  # type: ignore[return-value]

    def get_user_profile(self, user_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, account, nickname, created_at FROM users WHERE id=?", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    def update_nickname(self, user_id: str, nickname: str) -> dict:
        value = _validate_str(nickname, "nickname", 1, 30)
        with self._connect() as conn:
            cur = conn.execute("UPDATE users SET nickname=? WHERE id=?", (value, user_id))
            if cur.rowcount == 0:
                raise NotFound("user_id")
            conn.commit()
        return self.get_user_profile(user_id)  # type: ignore[return-value]

    def verify_password(self, account: str, password: str) -> str | None:
        normalized = _validate_account(account)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, password_hash FROM users WHERE account=?", (normalized,)
            ).fetchone()
        if row is None:
            return None
        try:
            algorithm, salt, expected = row["password_hash"].split("$", 2)
            if algorithm != "pbkdf2_sha256":
                return None
        except ValueError:
            return None
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
        ).hex()
        return row["id"] if actual == expected else None

    # ---------- LostItem ----------

    def publish_lost(
        self,
        *,
        publisher_id: str,
        name: str,
        description: str,
        location: str,
        lost_at: str,
    ) -> dict:
        name_value = _validate_str(name, "name", 1, 80)
        description_value = _validate_str(description, "description", 1, 1000)
        location_value = _validate_str(location, "location", 1, 120)
        lost_at_value = _validate_lost_at(lost_at)
        item_id = _uuid()
        with self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO lost_items
                       (id, publisher_id, name, description, location, lost_at, status, created_at)
                       VALUES (?,?,?,?,?,?, 'waiting', ?)""",
                    (
                        item_id,
                        publisher_id,
                        name_value,
                        description_value,
                        location_value,
                        lost_at_value,
                        _now(),
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise InvalidField("publisher_id") from exc
        return self.get_lost(item_id)  # type: ignore[return-value]

    def get_lost(self, lost_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM lost_items WHERE id=?", (lost_id,)).fetchone()
            return _lost_view(row) if row else None

    def search_lost(
        self,
        *,
        keyword: str | None = None,
        location: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list = []
        if keyword:
            clauses.append("(name LIKE ? OR description LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if location:
            clauses.append("location LIKE ?")
            params.append(f"%{location}%")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM lost_items{where} ORDER BY created_at, id LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            return [_lost_view(r) for r in rows]

    # ---------- ClaimApplication ----------

    def create_claim(self, *, lost_item_id: str, applicant_id: str, statement: str) -> dict:
        statement_value = _validate_str(statement, "statement", 1, 500)
        claim_id = _uuid()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                item = conn.execute(
                    "SELECT publisher_id, status FROM lost_items WHERE id=?", (lost_item_id,)
                ).fetchone()
                if item is None:
                    raise NotFound("lost_item_id")
                if item["status"] != "waiting":
                    raise InvalidState("lost_item_id")
                if item["publisher_id"] == applicant_id:
                    raise Forbidden("self_claim")
                user = conn.execute("SELECT 1 FROM users WHERE id=?", (applicant_id,)).fetchone()
                if user is None:
                    raise NotFound("applicant_id")
                conn.execute(
                    """INSERT INTO claim_applications
                       (id, lost_item_id, applicant_id, statement, status, created_at)
                       VALUES (?,?,?,?, 'pending', ?)""",
                    (claim_id, lost_item_id, applicant_id, statement_value, _now()),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise DuplicateClaim("lost_item_id, applicant_id") from exc
            except Exception:
                conn.rollback()
                raise
        return self.get_claim(claim_id)  # type: ignore[return-value]

    def get_claim(self, claim_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM claim_applications WHERE id=?", (claim_id,)
            ).fetchone()
            return _claim_view(row) if row else None

    def list_my_claims(self, applicant_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM claim_applications WHERE applicant_id=? ORDER BY created_at, id",
                (applicant_id,),
            ).fetchall()
            return [_claim_view(r) for r in rows]

    def list_my_published(self, publisher_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM lost_items WHERE publisher_id=? ORDER BY created_at, id",
                (publisher_id,),
            ).fetchall()
            return [_lost_view(r) for r in rows]

    # ---------- 测试数据（虚构/脱敏） ----------

    def load_test_data(self) -> dict:
        """装载样例数据；重复调用会先清空业务表，仅限测试环境。"""
        with self._connect() as conn:
            conn.execute("DELETE FROM claim_applications")
            conn.execute("DELETE FROM lost_items")
            conn.execute("DELETE FROM users")
            conn.commit()

        u001 = self.register_user("u001", "pass-u001", "测试用户甲")["id"]
        u002 = self.register_user("u002", "pass-u002", "测试用户乙")["id"]
        i001 = self.publish_lost(
            publisher_id=u001,
            name="钥匙串",
            description="蓝色挂饰，三把钥匙",
            location="图书馆一楼",
            lost_at="2026-11-16T10:30:00+08:00",
        )["id"]
        c001 = self.create_claim(
            lost_item_id=i001, applicant_id=u002, statement="我在自习室捡到，特征一致。"
        )["id"]
        return {"users": [u001, u002], "lost_items": [i001], "claims": [c001]}

    def export_test_data(self, path: Path) -> str:
        """导出测试数据；不输出 password_hash，避免凭据进入公共记录。"""
        with self._connect() as conn:
            users = conn.execute(
                "SELECT id, account, nickname, created_at FROM users"
            ).fetchall()
        data = {
            "users": [dict(r) for r in users],
            "lost_items": self._raw_rows("lost_items"),
            "claim_applications": self._raw_rows("claim_applications"),
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def _raw_rows(self, table: str) -> list[dict]:
        if table not in {"users", "lost_items", "claim_applications"}:
            raise InvalidField("table")
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            return [dict(r) for r in rows]
