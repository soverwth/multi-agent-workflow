"""SQLite reference CallLedger. Atomic claims survive adapter/process restarts.

The database contains protected model content. B03 integrations must enforce access
and retention outside this local backend. No credentials belong in ledger values.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .contracts import JSON, canonical, digest, model_call_ref, stamp
from .errors import ModelAdapterError


class SQLiteCallLedger:
    def __init__(self, path: str | Path = ":memory:"):
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=5)
        self._lock = threading.RLock()
        self._db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS attempts (key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS calls (
                key TEXT PRIMARY KEY, attempt_key TEXT NOT NULL, call_seq INTEGER NOT NULL,
                call_ref TEXT NOT NULL, fingerprint TEXT NOT NULL, record_ref TEXT NOT NULL,
                state TEXT NOT NULL, started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                transport_id TEXT, result TEXT, metadata TEXT NOT NULL,
                UNIQUE(attempt_key, call_seq));
            CREATE TABLE IF NOT EXISTS notes (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, call_key TEXT NOT NULL,
                kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS artifacts (
                ref TEXT PRIMARY KEY, invocation_ref TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL);
        """)

    def close(self):
        with self._lock:
            self._db.close()

    @staticmethod
    def _key(ref):
        invocation = ref["invocation_ref"]
        # dispatch_id is verified in the stored full reference, not a second namespace.
        return canonical([invocation[k] for k in ["project_id", "run_id", "invocation_id", "attempt_id"]] + [ref["model_call_id"]])

    @staticmethod
    def _attempt(ref):
        return canonical([ref[k] for k in ["project_id", "run_id", "invocation_id", "attempt_id"]])

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def _read(self, key):
        row = self._db.execute("SELECT call_ref,fingerprint,record_ref,state,started_at,updated_at,transport_id,result,metadata FROM calls WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        names = ["call_ref", "fingerprint", "record_ref", "state", "started_at", "updated_at", "transport_id", "result", "metadata"]
        record = dict(zip(names, row))
        for k in ["call_ref", "metadata", "result"]:
            record[k] = json.loads(record[k]) if record[k] is not None else None
        record["notes"] = [dict(kind=r[0], payload=json.loads(r[1]), created_at=r[2]) for r in self._db.execute(
            "SELECT kind,payload,created_at FROM notes WHERE call_key=? ORDER BY seq", (key,)).fetchall()]
        return record

    def claim(self, request: JSON, fingerprint: str, attempt_fingerprint: str, metadata: JSON):
        ref = model_call_ref(request)
        key, attempt = self._key(ref), self._attempt(ref["invocation_ref"])
        with self._transaction():
            old = self._read(key)
            if old:
                if old["call_ref"] != ref or old["fingerprint"] != fingerprint:
                    original = old["result"]
                    stop = original["error"]["stop_status"] if original and original["error"] else "confirmed" if original else "unknown"
                    raise ModelAdapterError("MODEL_CALL_CONFLICT", stage="deduplication", stop_status=stop)
                return False, old
            frozen = self._db.execute("SELECT fingerprint FROM attempts WHERE key=?", (attempt,)).fetchone()
            if frozen and frozen[0] != attempt_fingerprint:
                raise ModelAdapterError("MODEL_CONFIG_INVALID", stage="attempt_binding")
            max_seq = self._db.execute("SELECT MAX(call_seq) FROM calls WHERE attempt_key=?", (attempt,)).fetchone()[0]
            if max_seq is not None and request["call_seq"] <= max_seq:
                raise ModelAdapterError("MODEL_CALL_CONFLICT", stage="call_sequence")
            self._db.execute("INSERT OR IGNORE INTO attempts VALUES (?,?)", (attempt, attempt_fingerprint))
            now, record_ref = stamp(), "model-record:" + uuid4().hex
            self._db.execute("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                key, attempt, request["call_seq"], canonical(ref), fingerprint, record_ref, "prepared", now, now, None, None, canonical(metadata)))
            return True, self._read(key)

    def get(self, call_ref):
        with self._lock:
            record = self._read(self._key(call_ref))
            if record and record["call_ref"] != call_ref:
                raise ModelAdapterError("MODEL_CALL_CONFLICT", stage="lookup")
            return record

    def mark_sent(self, call_ref, transport_id):
        with self._transaction():
            key = self._key(call_ref)
            row = self._read(key)
            if not row or row["state"] != "prepared" or row["transport_id"] is not None:
                raise ModelAdapterError("MODEL_CALL_CONFLICT", stage="send_intent")
            # "sent" means intent persisted before entering transport; a crash is uncertain.
            self._db.execute("UPDATE calls SET state='sent',transport_id=?,updated_at=? WHERE key=?", (transport_id, stamp(), key))

    def finish(self, call_ref, result, state):
        with self._transaction():
            key = self._key(call_ref)
            old = self._read(key)
            if old is None:
                raise ModelAdapterError("MODEL_INTERNAL_ERROR", stage="record_result")
            if old["result"] is not None:
                if old["result"] != result:
                    raise ModelAdapterError("MODEL_CALL_CONFLICT", stage="record_result")
                return
            self._db.execute("UPDATE calls SET result=?,state=?,updated_at=? WHERE key=?", (canonical(result), state, stamp(), key))

    def append(self, call_ref, kind, payload):
        with self._transaction():
            key = self._key(call_ref)
            if self._read(key) is None:
                raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="lookup")
            now = stamp()
            self._db.execute("INSERT INTO notes(call_key,kind,payload,created_at) VALUES (?,?,?,?)", (key, kind, canonical(payload), now))
            self._db.execute("UPDATE calls SET updated_at=? WHERE key=?", (now, key))

    def put_private(self, invocation_ref, kind, value):
        body = canonical(value)
        ref = "model-private:" + digest([invocation_ref, kind, value])
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?)", (ref, canonical(invocation_ref), kind, body))
        return ref

    def get_private(self, ref, invocation_ref):
        """B03-side primitive; caller must have independently authorized access."""
        with self._lock:
            row = self._db.execute("SELECT invocation_ref,body FROM artifacts WHERE ref=?", (ref,)).fetchone()
            if not row or json.loads(row[0]) != invocation_ref:
                raise ModelAdapterError("MODEL_CONTROL_INVALID", stage="artifact_access")
            return json.loads(row[1])

