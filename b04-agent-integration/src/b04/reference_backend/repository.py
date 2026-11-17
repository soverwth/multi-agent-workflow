"""B04-local reference adapter. Does not migrate or modify B03/T02 modules.

A production T02 adapter implements the same transaction/unit-of-work boundary;
in particular object/owner/state/duplicate checks and claim insert stay atomic.
"""
from __future__ import annotations

from contextlib import contextmanager, AbstractContextManager
from pathlib import Path
import sqlite3
import threading
from typing import Protocol


class DuplicateAccount(Exception):
    pass


class DuplicateClaim(Exception):
    pass


class UnitOfWork(Protocol):
    def user(self, user_id: str) -> dict | None: ...
    def user_by_account(self, account: str) -> dict | None: ...
    def add_user(self, row: dict) -> None: ...
    def update_nickname(self, user_id: str, nickname: str) -> dict: ...
    def session(self, token_hash: str) -> dict | None: ...
    def add_session(self, row: dict) -> None: ...
    def revoke_session(self, token_hash: str, at: str) -> None: ...
    def lost(self, item_id: str) -> dict | None: ...
    def add_lost(self, row: dict) -> None: ...
    def list_lost(self, page: int, page_size: int, *, publisher_id=None, keyword='', location='') -> tuple[list, int]: ...
    def claim(self, item_id: str, applicant_id: str) -> dict | None: ...
    def add_claim(self, row: dict) -> None: ...
    def list_claims(self, applicant_id: str, page: int, page_size: int) -> tuple[list, int]: ...


class Repository(Protocol):
    def transaction(self, *, write=False) -> AbstractContextManager[UnitOfWork]: ...


SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, account TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, nickname TEXT NOT NULL, created_at TEXT NOT NULL,
 CHECK(account=lower(account)), CHECK(length(account) BETWEEN 3 AND 64),
 CHECK(length(nickname) BETWEEN 1 AND 30)
);
CREATE TABLE IF NOT EXISTS lost_items (
 id TEXT PRIMARY KEY, publisher_id TEXT NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, description TEXT NOT NULL, location TEXT NOT NULL,
 lost_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status='waiting'), created_at TEXT NOT NULL,
 CHECK(length(name) BETWEEN 1 AND 80), CHECK(length(description) BETWEEN 1 AND 1000),
 CHECK(length(location) BETWEEN 1 AND 120)
);
CREATE TABLE IF NOT EXISTS claim_applications (
 id TEXT PRIMARY KEY, lost_item_id TEXT NOT NULL REFERENCES lost_items(id),
 applicant_id TEXT NOT NULL REFERENCES users(id), statement TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status='pending'), created_at TEXT NOT NULL,
 UNIQUE(lost_item_id, applicant_id), CHECK(length(statement) BETWEEN 1 AND 500)
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS lost_order ON lost_items(created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS lost_publisher ON lost_items(publisher_id,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS claim_applicant ON claim_applications(applicant_id,created_at DESC,id DESC);
'''


def _c1_character_length(value):
    """Count complete C1 TEXT, including embedded U+0000, like Python validation.

    SQLite's built-in length(TEXT) stops at U+0000. The reference schema uses
    length in CHECKs, so each reference connection deliberately supplies this
    C1 version. Existing reference files need no table rebuild or data rewrite.
    NULL/BLOB keep their usual length behavior; TEXT affinity applies before
    schema CHECKs. This function is not installed on B03 or other connections.
    """
    if value is None:
        return None
    return len(value) if isinstance(value, (str, bytes)) else len(str(value))


class SQLiteRepository:
    def __init__(self, path: str | Path = ':memory:'):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        self._db.execute('PRAGMA foreign_keys=ON')
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.create_function('length', 1, _c1_character_length, deterministic=True)
        # C1 ignores English letter case; other Unicode characters remain literal.
        fold = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')
        self._db.create_function('c1_contains', 2, lambda body, term: int(term.translate(fold) in body.translate(fold)), deterministic=True)
        self._db.executescript(SCHEMA)

    @contextmanager
    def transaction(self, *, write=False):
        with self._lock:
            self._db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            try:
                yield SQLiteUnitOfWork(self._db)
                self._db.execute('COMMIT')
            except BaseException:
                self._db.execute('ROLLBACK')
                raise

    def close(self):
        self._db.close()


class SQLiteUnitOfWork:
    def __init__(self, connection):
        self.db = connection

    def _one(self, sql, args):
        row = self.db.execute(sql, args).fetchone()
        return dict(row) if row else None

    def user(self, user_id):
        return self._one('SELECT * FROM users WHERE id=?', (user_id,))

    def user_by_account(self, account):
        return self._one('SELECT * FROM users WHERE account=?', (account,))

    def add_user(self, row):
        try:
            self.db.execute('INSERT INTO users VALUES (:id,:account,:password_hash,:nickname,:created_at)', row)
        except sqlite3.IntegrityError as exc:
            if exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise DuplicateAccount from None
            raise

    def update_nickname(self, user_id, nickname):
        self.db.execute('UPDATE users SET nickname=? WHERE id=?', (nickname, user_id))
        return self.user(user_id)

    def session(self, token_hash):
        return self._one('SELECT * FROM sessions WHERE token_hash=?', (token_hash,))

    def add_session(self, row):
        self.db.execute('INSERT INTO sessions VALUES (:token_hash,:user_id,:created_at,:expires_at,NULL)', row)

    def revoke_session(self, token_hash, at):
        self.db.execute('UPDATE sessions SET revoked_at=? WHERE token_hash=?', (at, token_hash))

    def lost(self, item_id):
        return self._one('SELECT * FROM lost_items WHERE id=?', (item_id,))

    def add_lost(self, row):
        self.db.execute('INSERT INTO lost_items VALUES (:id,:publisher_id,:name,:description,:location,:lost_at,:status,:created_at)', row)

    def _page(self, table, where, args, page, page_size):
        # table/where are fixed by this adapter; all external values are parameters.
        total = self.db.execute(f'SELECT count(*) FROM {table} WHERE {where}', args).fetchone()[0]
        offset = (page - 1) * page_size
        if offset >= total:
            return [], total
        rows = self.db.execute(f'SELECT * FROM {table} WHERE {where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', (*args, page_size, offset))
        return [dict(row) for row in rows], total

    def list_lost(self, page, page_size, *, publisher_id=None, keyword='', location=''):
        clauses = ["status='waiting'"]
        args = []
        if publisher_id is not None:
            clauses.append('publisher_id=?'); args.append(publisher_id)
        if keyword:
            clauses.append('(c1_contains(name,?)=1 OR c1_contains(description,?)=1)'); args.extend([keyword, keyword])
        if location:
            clauses.append('location=?'); args.append(location)
        return self._page('lost_items', ' AND '.join(clauses), tuple(args), page, page_size)

    def claim(self, item_id, applicant_id):
        return self._one('SELECT * FROM claim_applications WHERE lost_item_id=? AND applicant_id=?', (item_id, applicant_id))

    def add_claim(self, row):
        try:
            self.db.execute('INSERT INTO claim_applications VALUES (:id,:lost_item_id,:applicant_id,:statement,:status,:created_at)', row)
        except sqlite3.IntegrityError as exc:
            if exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise DuplicateClaim from None
            raise

    def list_claims(self, applicant_id, page, page_size):
        return self._page('claim_applications', 'applicant_id=?', (applicant_id,), page, page_size)
