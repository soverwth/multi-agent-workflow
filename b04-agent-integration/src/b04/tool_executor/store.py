"""Durable tool catalog, claims, stop tombstones and parent/attempt quota ledger."""
from __future__ import annotations

import copy
import json
import sqlite3
import threading
from contextlib import contextmanager
from uuid import uuid4

from b04.model_adapter.contracts import canonical,digest,parse_time,stamp,utc_now
from .contracts import ToolExecutorError,op_key


class SQLiteToolStore:
    def __init__(self,path=":memory:"):
        self._lock=threading.RLock()
        self._db=sqlite3.connect(str(path),isolation_level=None,check_same_thread=False,timeout=5)
        self._db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS tools (name TEXT NOT NULL, version TEXT NOT NULL, definition TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY(name,version));
        CREATE TABLE IF NOT EXISTS tool_ops (key TEXT PRIMARY KEY, ref TEXT NOT NULL, fingerprint TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tool_stops (key TEXT PRIMARY KEY, ref TEXT NOT NULL, receipt TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tool_tickets (ref TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tool_reservations (key TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tool_diagnostics (ref TEXT PRIMARY KEY, body TEXT NOT NULL);
        """)

    def close(self):self._db.close()

    def diagnostic(self,ref,request,code):
        """Service-private audit, including denials that cannot claim a business operation."""
        record_ref='tool-diagnostic:'+uuid4().hex
        with self.transaction():
            self._db.execute('INSERT INTO tool_diagnostics VALUES (?,?)',(record_ref,canonical(dict(operation_ref=ref,request_sha256=digest(request),code=code,at=stamp()))))
        return dict(operation_record_ref=record_ref)

    def diagnostic_record(self,record_ref):
        with self._lock:
            row=self._db.execute('SELECT body FROM tool_diagnostics WHERE ref=?',(record_ref,)).fetchone()
            return json.loads(row[0]) if row else None

    @contextmanager
    def transaction(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:yield;self._db.execute("COMMIT")
            except BaseException:self._db.execute("ROLLBACK");raise

    def put_definition(self,definition):
        with self.transaction():
            key=(definition["tool_name"],definition["tool_version"])
            old=self._db.execute("SELECT definition FROM tools WHERE name=? AND version=?",key).fetchone()
            if old and json.loads(old[0])!=definition:raise ToolExecutorError("TOOL_OPERATION_CONFLICT",stage="immutable_tool_version")
            self._db.execute("INSERT OR IGNORE INTO tools VALUES (?,?,?,?)",(*key,canonical(definition),"draft"))

    def definition(self,name,version):
        with self._lock:
            row=self._db.execute("SELECT definition,state FROM tools WHERE name=? AND version=?",(name,version)).fetchone()
            if row is None:raise ToolExecutorError("TOOL_NOT_REGISTERED")
            return json.loads(row[0]),row[1]

    def catalog_state(self,name,version,state):
        with self.transaction():
            old=self._db.execute("SELECT state FROM tools WHERE name=? AND version=?",(name,version)).fetchone()
            transitions={"draft":{"validated"},"validated":{"published","disabled"},"published":{"deprecated","disabled"},"deprecated":{"disabled"},"disabled":set()}
            if old is None:raise ToolExecutorError("TOOL_NOT_REGISTERED")
            if state!=old[0] and state not in transitions[old[0]]:raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="publication_transition")
            self._db.execute("UPDATE tools SET state=? WHERE name=? AND version=?",(state,name,version))

    def _get(self,ref):
        row=self._db.execute("SELECT ref,fingerprint,data FROM tool_ops WHERE key=?",(op_key(ref),)).fetchone()
        if row is None:return None
        if json.loads(row[0])!=ref:raise ToolExecutorError("TOOL_OPERATION_CONFLICT")
        return dict(ref=json.loads(row[0]),fingerprint=row[1],**json.loads(row[2]))

    def get(self,ref):
        with self._lock:return copy.deepcopy(self._get(ref))

    def _write(self,ref,data):
        self._db.execute("UPDATE tool_ops SET data=? WHERE key=?",(canonical({k:v for k,v in data.items() if k not in {"ref","fingerprint"}}),op_key(ref)))

    def claim(self,ref,fingerprint,request,metadata,resources,*,started_at=None):
        with self.transaction():
            old=self._get(ref)
            if old:
                if old["fingerprint"]!=fingerprint:raise ToolExecutorError("TOOL_OPERATION_CONFLICT",stop_status="unknown" if old["state"]!="finished" else "confirmed")
                return False,old
            # Unresolved side effects fence new operation IDs, including a new attempt.
            for (raw,) in self._db.execute("SELECT data FROM tool_ops"):
                other=json.loads(raw)
                overlap=any(a==b or a.startswith(b+'/') or b.startswith(a+'/') for a in resources for b in other['resources'])
                if other["state"] in {"running","unknown","stop_pending"} and overlap:
                    raise ToolExecutorError("TOOL_RESULT_UNKNOWN",stage="resource_quarantine",stop_status="unknown",effects="unknown")
            data=dict(request=copy.deepcopy(request),metadata=copy.deepcopy(metadata),resources=resources,state="prepared",started_at=started_at or stamp(),updated_at=stamp(),
                      operation_record_ref="tool-record:"+uuid4().hex,result_ref="tool-result:"+uuid4().hex,result=None,unit=None,notes=[])
            self._db.execute("INSERT INTO tool_ops VALUES (?,?,?,?)",(op_key(ref),canonical(ref),fingerprint,canonical(data)))
            return True,self._get(ref)

    def mark_running(self,ref,unit=None):
        with self.transaction():
            row=self._get(ref)
            if self._db.execute("SELECT 1 FROM tool_stops WHERE key=?",(op_key(ref),)).fetchone():raise ToolExecutorError("TOOL_STOPPED")
            if not row or row["state"]!="prepared":raise ToolExecutorError("TOOL_OPERATION_CONFLICT")
            for (raw,) in self._db.execute('SELECT data FROM tool_ops WHERE key<>?',(op_key(ref),)):
                other=json.loads(raw)
                overlap=any(a==b or a.startswith(b+'/') or b.startswith(a+'/') for a in row['resources'] for b in other['resources'])
                if overlap and other['state'] in {'running','unknown','stop_pending'}:raise ToolExecutorError('TOOL_OPERATION_CONFLICT',stage='resource_claim_lost')
            row.update(state="running",unit=unit,updated_at=stamp());self._write(ref,row)

    def finish(self,ref,result):
        with self.transaction():
            row=self._get(ref)
            if row["result"] is not None:
                if row["result"]!=result:raise ToolExecutorError("TOOL_OPERATION_CONFLICT")
                return
            row.update(result=copy.deepcopy(result),state="unknown" if result["stop_status"] in {"unknown","pending"} or result["side_effects_state"]=="unknown" else "finished",updated_at=stamp())
            self._write(ref,row)

    def append(self,ref,kind,payload):
        with self.transaction():
            row=self._get(ref)
            if row:
                row["notes"].append(dict(kind=kind,payload=copy.deepcopy(payload),at=stamp()));row["updated_at"]=stamp();self._write(ref,row)

    def request_stop(self,ref):
        with self.transaction():
            old=self._db.execute("SELECT ref,receipt FROM tool_stops WHERE key=?",(op_key(ref),)).fetchone()
            if old:
                if json.loads(old[0])!=ref:raise ToolExecutorError("TOOL_OPERATION_CONFLICT")
                return json.loads(old[1])
            receipt="tool-stop-record:"+uuid4().hex
            self._db.execute("INSERT INTO tool_stops VALUES (?,?,?)",(op_key(ref),canonical(ref),canonical(receipt)))
            return receipt

    def stopped(self,ref):
        with self._lock:
            row=self._db.execute("SELECT ref FROM tool_stops WHERE key=?",(op_key(ref),)).fetchone()
            if row and json.loads(row[0])!=ref:raise ToolExecutorError("TOOL_OPERATION_CONFLICT")
            return bool(row)

    def register_ticket(self,ticket):
        required={"ticket_ref","ledger_ref","invocation_ref","scope","purpose","parent_ticket_ref","limits","reserved","consumed","unsettled","expires_at","state"}
        if set(ticket)!=required or ticket["purpose"]!="tool_execute" or ticket["scope"] not in {"attempt","invocation"}:raise ValueError("Invalid tool BudgetTicket")
        keys=set(ticket["limits"])
        if "max_tool_calls" not in keys:raise ValueError("Missing tool quota")
        for field in ["limits","reserved","consumed","unsettled"]:
            if set(ticket[field])!=keys or any(type(v) is not int or v<0 for v in ticket[field].values()):raise ValueError("Invalid budget counters")
        if ticket["scope"]=="attempt" and not ticket["parent_ticket_ref"]:raise ValueError("Attempt quota requires parent")
        if any(ticket["unsettled"][k]>ticket["reserved"][k] for k in keys):raise ValueError("Unsettled is part of reserved")
        if ticket['state'] not in {'active','exhausted','expired','closed'} or not all(isinstance(ticket[k],str) and ticket[k] for k in ['ticket_ref','ledger_ref']):raise ValueError('Invalid ticket identity/state')
        from .contracts import validate,OPERATION_SCHEMA
        validate(dict(invocation_ref=ticket['invocation_ref'],operation_id='quota'),OPERATION_SCHEMA)
        if any(ticket['consumed'][k]+ticket['reserved'][k]>ticket['limits'][k] for k in keys):raise ValueError('Quota already over limit')
        parse_time(ticket["expires_at"])
        with self.transaction():
            if self._db.execute("SELECT 1 FROM tool_tickets WHERE ref=?",(ticket["ticket_ref"],)).fetchone():raise ValueError("Cannot reset quota")
            self._db.execute("INSERT INTO tool_tickets VALUES (?,?)",(ticket["ticket_ref"],canonical(ticket)))

    def ticket(self,ticket_ref):
        with self._lock:
            row=self._db.execute("SELECT body FROM tool_tickets WHERE ref=?",(ticket_ref,)).fetchone()
            if not row:raise ToolExecutorError("TOOL_BUDGET_EXHAUSTED")
            return json.loads(row[0])

    def reservation(self,ref):
        with self._lock:
            row=self._db.execute('SELECT body FROM tool_reservations WHERE key=?',(op_key(ref),)).fetchone()
            if row:
                operation=self._get(ref)
                if operation and operation['ref']!=ref:raise ToolExecutorError('TOOL_OPERATION_CONFLICT')
            return json.loads(row[0]) if row else None

    def reserve(self,ticket_ref,ref):
        with self.transaction():
            key=op_key(ref)
            old=self._db.execute("SELECT body FROM tool_reservations WHERE key=?",(key,)).fetchone()
            if old:
                if json.loads(old[0])["ticket_ref"]!=ticket_ref:raise ToolExecutorError("TOOL_OPERATION_CONFLICT")
                return
            chain=[];seen=set();current=ticket_ref
            while current:
                if current in seen:raise ToolExecutorError("TOOL_BUDGET_EXHAUSTED")
                seen.add(current);ticket=self.ticket(current)
                keys=["project_id","run_id","invocation_id"]+(["attempt_id","dispatch_id","task_id"] if ticket["scope"]=="attempt" else [])
                if ticket["purpose"]!="tool_execute" or ticket["state"]!="active" or parse_time(ticket["expires_at"])<=utc_now() or any(ticket["invocation_ref"][k]!=ref["invocation_ref"][k] for k in keys):raise ToolExecutorError("TOOL_BUDGET_EXHAUSTED")
                if ticket["consumed"]["max_tool_calls"]+ticket["reserved"]["max_tool_calls"]>=ticket["limits"]["max_tool_calls"]:raise ToolExecutorError("TOOL_BUDGET_EXHAUSTED")
                chain.append(ticket);current=ticket["parent_ticket_ref"]
                if current and self.ticket(current)["scope"]!="invocation":raise ToolExecutorError("TOOL_BUDGET_EXHAUSTED")
                if current and self.ticket(current)['ledger_ref']!=ticket['ledger_ref']:raise ToolExecutorError('TOOL_BUDGET_EXHAUSTED')
            for t in chain:
                t["reserved"]["max_tool_calls"]+=1;self._db.execute("UPDATE tool_tickets SET body=? WHERE ref=?",(canonical(t),t["ticket_ref"]))
            self._db.execute("INSERT INTO tool_reservations VALUES (?,?)",(key,canonical(dict(ticket_ref=ticket_ref,chain=[t["ticket_ref"] for t in chain],settled=False))))

    def settle(self,ref,*,executed,unknown=False):
        with self.transaction():
            row=self._db.execute("SELECT body FROM tool_reservations WHERE key=?",(op_key(ref),)).fetchone()
            if not row:return
            reservation=json.loads(row[0])
            if reservation["settled"]:return
            for ticket_ref in reservation["chain"]:
                t=self.ticket(ticket_ref)
                if unknown:t["unsettled"]["max_tool_calls"]+=1
                else:t["reserved"]["max_tool_calls"]-=1;t["consumed"]["max_tool_calls"]+=int(executed)
                self._db.execute("UPDATE tool_tickets SET body=? WHERE ref=?",(canonical(t),ticket_ref))
            reservation["settled"]=True
            reservation.update(settlement='unsettled' if unknown else 'consumed' if executed else 'released',executed=bool(executed),updated_at=stamp())
            self._db.execute("UPDATE tool_reservations SET body=? WHERE key=?",(canonical(reservation),op_key(ref)))
