"""SQLite B03 reference backend with atomic admission, terminal CAS and Outbox.

This local backend stores protected content. Production B03 owns service identity,
distributed fencing, retention and shared database availability.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

from b04.model_adapter.contracts import IDENTITY_FIELDS, canonical, digest, invocation_ref, parse_time, stamp, utc_now
from b04.model_adapter.errors import ModelAdapterError
from .contracts import (AlreadyTerminal, DRAFT_SCHEMA, EVENT_SCHEMA, INVOCATION_SCHEMA, MANIFEST_SCHEMA,
                        RunnerError, TERMINALS, key_of, sha_bytes, validate)


class SQLiteRunnerStore:
    def __init__(self, path=":memory:", *, authority, max_object_bytes=4 * 1024 * 1024, max_draft_bytes=16 * 1024 * 1024):
        self.authority = authority
        self.max_object_bytes, self.max_draft_bytes = max_object_bytes, max_draft_bytes
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False, timeout=5)
        self._db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS runner_invocations (key TEXT PRIMARY KEY, ref TEXT NOT NULL, envelope TEXT NOT NULL, fingerprint TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runner_admission_keys (project TEXT NOT NULL, idempotency_key TEXT NOT NULL, invocation TEXT NOT NULL, PRIMARY KEY(project,idempotency_key));
        CREATE TABLE IF NOT EXISTS runner_read_scopes (invocation TEXT NOT NULL, scope TEXT NOT NULL, allowed TEXT NOT NULL, PRIMARY KEY(invocation,scope));
        CREATE TABLE IF NOT EXISTS runner_events (id TEXT PRIMARY KEY, key TEXT NOT NULL, seq INTEGER NOT NULL, event TEXT NOT NULL, delivery TEXT NOT NULL, receipt TEXT, reconciliation TEXT, UNIQUE(key,seq));
        CREATE TABLE IF NOT EXISTS runner_actions (key TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, fingerprint TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(key,name));
        CREATE TABLE IF NOT EXISTS runner_objects (ref TEXT PRIMARY KEY, project TEXT NOT NULL, invocation TEXT, name TEXT NOT NULL, kind TEXT NOT NULL, namespace TEXT, metadata TEXT NOT NULL, body BLOB NOT NULL);
        """)

    def close(self):
        with self._lock:
            self._db.close()

    @contextmanager
    def _tx(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def _auth(self, ref, context, purpose=None):
        validate(ref, INVOCATION_SCHEMA)
        try:
            self.authority.authorize(context, purpose or context["purpose"], utc_now())
        except (ModelAdapterError, KeyError, TypeError):
            raise RunnerError("EXEC_LEASE_INVALID", stage="store_authorization") from None
        if context["invocation_ref"] != ref:
            raise RunnerError("EXEC_LEASE_INVALID", stage="store_identity")

    def _row(self, ref):
        row = self._db.execute("SELECT ref,envelope,fingerprint,data FROM runner_invocations WHERE key=?", (key_of(ref),)).fetchone()
        if row is None:
            return None
        if json.loads(row[0]) != ref:
            raise RunnerError("EXEC_DISPATCH_CONFLICT", stage="identity_conflict")
        return dict(invocation_ref=json.loads(row[0]), envelope=json.loads(row[1]), fingerprint=row[2], **json.loads(row[3]))

    def _write(self, ref, data):
        self._db.execute("UPDATE runner_invocations SET data=? WHERE key=?", (canonical({k:v for k,v in data.items() if k not in {"invocation_ref", "envelope", "fingerprint"}}), key_of(ref)))

    def _require(self, ref, context, *, owner=None, execute=False, allow_terminal=False):
        self._auth(ref, context, "execute" if execute else None)
        row = self._row(ref)
        if row is None:
            raise RunnerError("EXEC_INPUT_INVALID", stage="not_found")
        if any(row["envelope"][k] != context[k] for k in ["input_snapshot_id", "input_snapshot_sha256"]):
            raise RunnerError("EXEC_LEASE_INVALID", stage="snapshot_binding")
        if owner is not None and row["owner"] != owner:
            raise RunnerError("EXEC_LEASE_INVALID", stage="execution_fence")
        if not allow_terminal and row["terminal"] is not None:
            raise AlreadyTerminal()
        if execute and row["stop_requested"]:
            raise RunnerError("EXEC_LEASE_INVALID", stage="stop_requested")
        if execute and context["control_generation"]<row["generation"]:
            raise RunnerError("EXEC_LEASE_INVALID",stage="generation_fence")
        if execute and parse_time(row["deadline_at"])<=utc_now():
            raise RunnerError("EXEC_TIMEOUT",stage="store_execution_deadline")
        return row

    def admit(self, envelope, fingerprint, context):
        ref = invocation_ref(envelope)
        with self._tx():
            self._auth(ref, context, "execute")
            alias=self._db.execute("SELECT invocation FROM runner_admission_keys WHERE project=? AND idempotency_key=?",(ref["project_id"],envelope["idempotency_key"])).fetchone()
            if alias and alias[0]!=canonical(ref):
                raise RunnerError("EXEC_DISPATCH_CONFLICT",stage="idempotency_namespace")
            old = self._row(ref)
            if old:
                if old["fingerprint"] != fingerprint:
                    raise RunnerError("EXEC_DISPATCH_CONFLICT", stage="admission")
                return False, copy.deepcopy(old)
            now = utc_now()
            data = dict(phase="ACCEPTED", owner=None, generation=-1, checkpoint={}, terminal=None,
                        submission_id="submission:"+uuid4().hex, execution_record_ref="runner-record:"+uuid4().hex,
                        started_at=stamp(now), deadline_at=stamp(min(now+timedelta(seconds=envelope["limits"]["execution_timeout_seconds"]), parse_time(context["deadline_at"]))),
                        stop_requested=False, stop_reason=None, stop_status="confirmed", recovery_required=None, notes=[])
            self._db.execute("INSERT INTO runner_invocations VALUES (?,?,?,?,?)", (key_of(ref),canonical(ref),canonical(envelope),fingerprint,canonical(data)))
            self._db.execute("INSERT INTO runner_admission_keys VALUES (?,?,?)",(ref["project_id"],envelope["idempotency_key"],canonical(ref)))
            self._event(ref, envelope, "execution_accepted", {"agent_definition_ref":envelope["agent_definition_ref"],"execution_record_ref":data["execution_record_ref"]})
            return True, self._row(ref)

    def get(self, ref, context):
        with self._lock:
            return copy.deepcopy(self._require(ref, context, allow_terminal=True))

    def read_execution_record(self,record_ref,context):
        """Resolve Manifest.execution_record_ref through a protected B03 log view."""
        ref=context["invocation_ref"]
        with self._lock:
            self._auth(ref,context,"observe")
            row=self._require(ref,context,allow_terminal=True)
            if row["execution_record_ref"]!=record_ref:raise RunnerError("EXEC_INPUT_INVALID",stage="execution_record_ref")
            return dict(execution_record_ref=record_ref,invocation_ref=copy.deepcopy(ref),envelope=row["envelope"],checkpoint=row["checkpoint"],
                        actions=self.actions(ref,context),events=self.events(ref,context),terminal=row["terminal"],notes=row["notes"])

    def claim_execution(self, ref, owner, context, *, recover=False):
        with self._tx():
            row = self._require(ref, context, execute=True)
            if row["owner"] is not None and row["owner"] != owner and (not recover or context["control_generation"] <= row["generation"]):
                raise RunnerError("EXEC_LEASE_INVALID", stage="recovery_fence")
            row.update(owner=owner,generation=context["control_generation"],recovery_required=None)
            self._write(ref,row)
            return row

    def checkpoint(self, ref, owner, phase, checkpoint, context):
        with self._tx():
            if context["purpose"] not in {"execute","report"}:raise RunnerError("EXEC_LEASE_INVALID",stage="checkpoint_authority")
            row=self._require(ref,context,owner=owner)
            if owner is None and row["owner"] is not None:raise RunnerError("EXEC_LEASE_INVALID",stage="checkpoint_owner_fence")
            if context["purpose"]=="report" and context["control_generation"]<row["generation"]:raise RunnerError("EXEC_LEASE_INVALID",stage="checkpoint_fence")
            row.update(phase=phase,checkpoint=copy.deepcopy(checkpoint))
            self._write(ref,row)

    def mark_recovery(self, ref, owner, code, context):
        with self._tx():
            self._auth(ref,context,"report")
            row=self._require(ref,context,owner=owner,allow_terminal=True)
            if owner is None and row["owner"] is not None:raise RunnerError("EXEC_LEASE_INVALID",stage="recovery_owner_fence")
            row["recovery_required"]=code
            self._write(ref,row)

    def _event(self, ref, envelope, event_type, payload):
        seq=self._db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM runner_events WHERE key=?",(key_of(ref),)).fetchone()[0]
        event=dict(protocol_version="b04.exec.v0.2",event_id="event:"+uuid4().hex,event_type=event_type,**ref,
                   input_snapshot_id=envelope["input_snapshot_id"],input_snapshot_sha256=envelope["input_snapshot_sha256"],
                   event_seq=seq,occurred_at=stamp(),execution_mode=envelope["execution_mode"],producer="B04",payload=copy.deepcopy(payload))
        validate(event,EVENT_SCHEMA)
        self._db.execute("INSERT INTO runner_events VALUES (?,?,?,?,?,?,?)",(event["event_id"],key_of(ref),seq,canonical(event),"pending",None,None))
        return event

    def emit(self, ref, event_type, payload, context):
        if event_type in TERMINALS or event_type=="execution_accepted":
            raise RunnerError("EXEC_RUNNER_ERROR",stage="event_atomicity")
        with self._tx():
            row=self._require(ref,context,execute=True)
            if event_type=="execution_started":
                existing=self._db.execute("SELECT event FROM runner_events WHERE key=? AND json_extract(event,'$.event_type')='execution_started'",(key_of(ref),)).fetchone()
                if existing:return json.loads(existing[0])
            return self._event(ref,row["envelope"],event_type,payload)

    def events(self, ref, context):
        with self._lock:
            self._require(ref,context,allow_terminal=True)
            return [dict(event=json.loads(r[0]),delivery=r[1],receipt=json.loads(r[2]) if r[2] else None,reconciliation=json.loads(r[3]) if r[3] else None)
                    for r in self._db.execute("SELECT event,delivery,receipt,reconciliation FROM runner_events WHERE key=? ORDER BY seq",(key_of(ref),)).fetchall()]

    def delivery(self,event_id,status,receipt,context,*,reconciliation=None):
        with self._tx():
            record=self._db.execute("SELECT event FROM runner_events WHERE id=?",(event_id,)).fetchone()
            if record is None:
                raise RunnerError("EXEC_INPUT_INVALID",stage="event_not_found")
            event=json.loads(record[0]);ref=invocation_ref(event)
            self._require(ref,context,allow_terminal=True)
            if context["purpose"]!="report":
                raise RunnerError("EXEC_LEASE_INVALID",stage="delivery_authority")
            self._db.execute("UPDATE runner_events SET delivery=?,receipt=?,reconciliation=? WHERE id=?",(status,canonical(receipt) if receipt is not None else None,canonical(reconciliation) if reconciliation is not None else None,event_id))

    def register_input(self,project_id,artifact_ref,kind,body,*,media_type="application/json",state="accepted",version="1"):
        """Trusted B03 fixture/configuration path, not a runner/model write API."""
        if not isinstance(body,bytes):
            raise TypeError("Input content must be bytes")
        meta=dict(artifact_ref=artifact_ref,kind=kind,version=version,media_type=media_type,schema_ref=None,sha256=sha_bytes(body),size_bytes=len(body),state=state)
        with self._lock:
            old=self._db.execute("SELECT metadata,body FROM runner_objects WHERE ref=?",(artifact_ref,)).fetchone()
            if old and (json.loads(old[0])!=meta or bytes(old[1])!=body):
                raise ValueError("Versioned input cannot be overwritten")
            self._db.execute("INSERT OR IGNORE INTO runner_objects VALUES (?,?,?,?,?,?,?,?)",(artifact_ref,project_id,None,artifact_ref,kind,None,canonical(meta),body))
        return meta

    def read_input(self,artifact_ref,project_id,context):
        self._auth(context["invocation_ref"],context)
        if context["purpose"] not in {"execute","observe"} or context["invocation_ref"]["project_id"]!=project_id:
            raise RunnerError("EXEC_INPUT_INVALID",stage="input_access",blocked=True)
        with self._lock:
            if context["purpose"]=="execute":
                scope=self._db.execute("SELECT allowed FROM runner_read_scopes WHERE invocation=? AND scope=?",(canonical(context["invocation_ref"]),context["read_scope_ref"])).fetchone()
                allowed=json.loads(scope[0]) if scope else []
            else:
                invocation=self._row(context["invocation_ref"])
                allowed=[i["artifact_ref"] for i in invocation["envelope"]["inputs"]] if invocation else []
            if artifact_ref not in allowed:
                raise RunnerError("EXEC_TOOL_ERROR" if self._row(context["invocation_ref"]) else "EXEC_INPUT_INVALID",stage="input_read_scope",details={"denied_action":"read"})
            row=self._db.execute("SELECT project,metadata,body FROM runner_objects WHERE ref=? AND invocation IS NULL",(artifact_ref,)).fetchone()
            if row is None or row[0]!=project_id:
                raise RunnerError("EXEC_INPUT_INVALID",stage="input_missing_or_foreign",blocked=True)
            meta=json.loads(row[1]);body=bytes(row[2])
            if sha_bytes(body)!=meta["sha256"] or len(body)!=meta["size_bytes"]:
                raise RunnerError("EXEC_INPUT_INVALID",stage="input_integrity",blocked=True)
            return dict(metadata=meta,body=body)

    def register_read_scope(self,ref,scope,artifact_refs):
        """Trusted configuration API. A context's scope string cannot self-authorize."""
        allowed=canonical(sorted(set(artifact_refs)))
        with self._lock:
            old=self._db.execute("SELECT allowed FROM runner_read_scopes WHERE invocation=? AND scope=?",(canonical(ref),scope)).fetchone()
            if old and old[0]!=allowed:raise ValueError("Read scope cannot silently expand")
            self._db.execute("INSERT OR IGNORE INTO runner_read_scopes VALUES (?,?,?)",(canonical(ref),scope,allowed))

    def _put(self,ref,name,kind,body,*,namespace=None,media_type="application/json",schema_ref=None):
        if not isinstance(body,bytes) or len(body)>self.max_object_bytes:
            raise RunnerError("EXEC_BUDGET_EXHAUSTED",stage="object_size")
        artifact_ref=(namespace+"/" if namespace else "runner-private:")+digest([ref,name,kind,sha_bytes(body)])
        meta=dict(artifact_ref=artifact_ref,kind=kind,version=sha_bytes(body),media_type=media_type,schema_ref=schema_ref,sha256=sha_bytes(body),size_bytes=len(body))
        self._db.execute("INSERT OR IGNORE INTO runner_objects VALUES (?,?,?,?,?,?,?,?)",(artifact_ref,ref["project_id"],canonical(ref),name,kind,namespace,canonical(meta),body))
        return meta

    def put_object(self,ref,name,kind,body,context,*,namespace=None,media_type="application/json",schema_ref=None):
        with self._tx():
            self._require(ref,context,allow_terminal=True)
            if namespace is not None:
                row=self._require(ref,context,execute=True)
                if namespace not in context["write_scope"]["artifact_namespaces"] or namespace not in row["envelope"]["write_scope"]["artifact_namespaces"]:
                    raise RunnerError("EXEC_WRITE_SCOPE",stage="artifact_namespace")
            elif context["purpose"] not in {"execute","report"}:
                raise RunnerError("EXEC_LEASE_INVALID",stage="private_write")
            return self._put(ref,name,kind,body,namespace=namespace,media_type=media_type,schema_ref=schema_ref)

    def _read_object(self,artifact_ref,ref):
        row=self._db.execute("SELECT project,invocation,metadata,body FROM runner_objects WHERE ref=?",(artifact_ref,)).fetchone()
        if row is None or row[0]!=ref["project_id"] or row[1]!=canonical(ref):
            raise RunnerError("EXEC_ARTIFACT_INVALID",stage="artifact_access")
        meta=json.loads(row[2]);body=bytes(row[3])
        if sha_bytes(body)!=meta["sha256"] or len(body)!=meta["size_bytes"]:
            raise RunnerError("EXEC_ARTIFACT_INVALID",stage="artifact_integrity")
        return dict(metadata=meta,body=body)

    def read_object(self,artifact_ref,context):
        with self._lock:
            ref=context["invocation_ref"]
            if context["purpose"] not in {"execute","observe"}:raise RunnerError("EXEC_LEASE_INVALID",stage="object_read_authority")
            self._require(ref,context,allow_terminal=True)
            return self._read_object(artifact_ref,ref)

    def reserve_action(self,ref,owner,name,kind,request,context):
        with self._tx():
            self._require(ref,context,owner=owner,execute=True)
            old=self._db.execute("SELECT fingerprint,data FROM runner_actions WHERE key=? AND name=?",(key_of(ref),name)).fetchone()
            if old:
                if old[0]!=digest(request):
                    raise RunnerError("EXEC_MODEL_ERROR" if kind=="model" else "EXEC_TOOL_ERROR",stage="action_conflict")
                return json.loads(old[1])
            data=dict(name=name,kind=kind,request=copy.deepcopy(request),state="prepared",result=None)
            self._db.execute("INSERT INTO runner_actions VALUES (?,?,?,?,?)",(key_of(ref),name,kind,digest(request),canonical(data)))
            return data

    def action(self,ref,name,context):
        with self._lock:
            self._require(ref,context,allow_terminal=True)
            row=self._db.execute("SELECT data FROM runner_actions WHERE key=? AND name=?",(key_of(ref),name)).fetchone()
            return json.loads(row[0]) if row else None

    def actions(self,ref,context):
        with self._lock:
            self._require(ref,context,allow_terminal=True)
            return [json.loads(row[0]) for row in self._db.execute("SELECT data FROM runner_actions WHERE key=? ORDER BY rowid",(key_of(ref),)).fetchall()]

    def set_action(self,ref,owner,name,state,result,context):
        with self._tx():
            if context["purpose"] not in {"execute","report"}:raise RunnerError("EXEC_LEASE_INVALID",stage="action_authority")
            self._require(ref,context,owner=owner,execute=state=="called",allow_terminal=state=="done")
            old=self._db.execute("SELECT data FROM runner_actions WHERE key=? AND name=?",(key_of(ref),name)).fetchone()
            if old is None:
                raise RunnerError("EXEC_RUNNER_ERROR",stage="action_not_reserved")
            data=json.loads(old[0])
            if data["state"]=="done" and (state!="done" or data["result"]!=result):
                raise RunnerError("EXEC_RUNNER_ERROR",stage="immutable_action_result")
            data.update(state=state,result=copy.deepcopy(result))
            self._db.execute("UPDATE runner_actions SET data=? WHERE key=? AND name=?",(canonical(data),key_of(ref),name))

    def stage_draft_content(self,ref,operation_ref,origin_fingerprint,body,media_type,context):
        with self._tx():
            self._require(ref,context,execute=True)
            if operation_ref["invocation_ref"]!=ref or not context["draft_namespace_ref"]:
                raise RunnerError("EXEC_WRITE_SCOPE",stage="draft_namespace")
            name="draft:"+operation_ref["operation_id"]
            old=self._db.execute("SELECT metadata,body FROM runner_objects WHERE invocation=? AND name=?",(canonical(ref),name)).fetchone()
            if old:
                meta=json.loads(old[0])
                if bytes(old[1])!=body or meta.get("origin_fingerprint")!=origin_fingerprint:
                    raise RunnerError("EXEC_TOOL_ERROR",stage="draft_conflict")
                return dict(content_ref=meta["artifact_ref"],sha256=meta["sha256"],size_bytes=meta["size_bytes"])
            total=self._db.execute("SELECT COALESCE(SUM(length(body)),0) FROM runner_objects WHERE invocation=? AND kind='draft_content'",(canonical(ref),)).fetchone()[0]
            if total+len(body)>self.max_draft_bytes:
                raise RunnerError("EXEC_BUDGET_EXHAUSTED",stage="draft_storage")
            meta=self._put(ref,name,"draft_content",body,namespace=context["draft_namespace_ref"],media_type=media_type)
            stored={**meta,"origin_fingerprint":origin_fingerprint}
            self._db.execute("UPDATE runner_objects SET metadata=? WHERE ref=?",(canonical(stored),meta["artifact_ref"]))
            return dict(content_ref=meta["artifact_ref"],sha256=meta["sha256"],size_bytes=meta["size_bytes"])

    def commit_terminal(self,draft,context,*,owner=None):
        validate(draft,DRAFT_SCHEMA,code="EXEC_RUNNER_ERROR",stage="terminal_draft")
        ref=draft["invocation_ref"]
        with self._tx():
            self._auth(ref,context,"execute" if draft["terminal_kind"]=="candidate_submitted" else "report")
            row=self._require(ref,context,owner=owner,execute=draft["terminal_kind"]=="candidate_submitted",allow_terminal=True)
            if owner is None and row["owner"] is not None and draft["terminal_kind"] in {"execution_failed","execution_blocked"}:raise RunnerError("EXEC_LEASE_INVALID",stage="terminal_owner_fence")
            if draft["terminal_kind"] in {"execution_failed","execution_blocked"} and context["control_generation"]<row["generation"]:raise RunnerError("EXEC_LEASE_INVALID",stage="terminal_report_fence")
            if draft["submission_id"]!=row["submission_id"] or any(draft[k]!=row["envelope"][k] for k in ["input_snapshot_id","input_snapshot_sha256"]):
                return self._commit_receipt(draft,"rejected",reason="SUBMISSION_IDENTITY_CONFLICT")
            if row["terminal"] is not None:
                if row["terminal"]["draft"]==draft:
                    return {**row["terminal"]["receipt"],"commit_status":"duplicate"}
                return self._commit_receipt(draft,"rejected",reason="TERMINAL_CONFLICT",terminal=row["terminal"])
            terminal_ref="terminal:"+uuid4().hex
            payload=dict(submission_id=draft["submission_id"],terminal_record_ref=terminal_ref,agent_definition_ref=row["envelope"]["agent_definition_ref"])
            if draft["terminal_kind"]=="candidate_submitted":
                obj=self._read_object(draft["manifest_ref"],ref)
                if obj["metadata"]["sha256"]!=draft["manifest_sha256"]:
                    raise RunnerError("EXEC_ARTIFACT_INVALID",stage="manifest_hash")
                manifest=json.loads(obj["body"]);validate(manifest,MANIFEST_SCHEMA,"EXEC_ARTIFACT_INVALID",stage="manifest")
                if any(manifest[k]!=row["envelope"][k] for k in IDENTITY_FIELDS+("input_snapshot_id","input_snapshot_sha256","agent_definition_ref","model_config_ref","workflow_definition_ref","tool_config_ref","output_contract_ref")) or manifest["submission_id"]!=draft["submission_id"]:
                    raise RunnerError("EXEC_ARTIFACT_INVALID",stage="manifest_identity")
                for artifact in manifest["artifacts"]:
                    actual=self._read_object(artifact["artifact_ref"],ref)
                    if actual["metadata"]!=artifact:
                        raise RunnerError("EXEC_ARTIFACT_INVALID",stage="manifest_artifact")
                    namespace=self._db.execute("SELECT namespace FROM runner_objects WHERE ref=?",(artifact["artifact_ref"],)).fetchone()[0]
                    if namespace not in row["envelope"]["write_scope"]["artifact_namespaces"] or namespace not in context["write_scope"]["artifact_namespaces"]:
                        raise RunnerError("EXEC_WRITE_SCOPE",stage="manifest_artifact_namespace")
                if row["envelope"]["source_control"] is not None and any(manifest["source_control"] is None or manifest["source_control"].get(k)!=row["envelope"]["source_control"][k] for k in ["repository_ref","base_commit"]):
                    raise RunnerError("EXEC_ARTIFACT_INVALID",stage="manifest_repository")
                self._check_manifest_evidence(manifest,row,ref)
                payload.update(manifest_ref=draft["manifest_ref"],manifest_sha256=draft["manifest_sha256"],artifact_kinds=[a["kind"] for a in manifest["artifacts"]],
                               self_check_status=manifest["self_check_status"],missing_check_refs=manifest["missing_check_refs"])
            elif draft["terminal_kind"] in {"execution_failed","execution_blocked"}:
                error=json.loads(self._read_object(draft["error_ref"],ref)["body"])
                payload.update(error_ref=draft["error_ref"],**error)
            else:
                if not row["stop_requested"] or row["stop_status"]!="confirmed":
                    raise RunnerError("EXEC_RUNNER_ERROR",stage="unconfirmed_stop")
                payload.update(stop_status="confirmed",reason=row["stop_reason"],resource_refs=row["checkpoint"].get("resource_refs",[]))
            event=self._event(ref,row["envelope"],draft["terminal_kind"],payload)
            receipt=dict(submission_id=draft["submission_id"],commit_status="committed",terminal_record_ref=terminal_ref,event_ref=event["event_id"],commit_receipt_ref="commit:"+uuid4().hex,reason_code=None)
            row.update(phase="TERMINAL",terminal=dict(draft=copy.deepcopy(draft),receipt=receipt,event_id=event["event_id"]),recovery_required=None)
            self._write(ref,row)
            return receipt

    @staticmethod
    def _commit_receipt(draft,status,reason=None,terminal=None):
        old=terminal["receipt"] if terminal else {}
        return dict(submission_id=draft["submission_id"],commit_status=status,terminal_record_ref=old.get("terminal_record_ref"),event_ref=old.get("event_ref"),commit_receipt_ref=old.get("commit_receipt_ref"),reason_code=reason)

    def get_terminal_submission(self,submission_id,context):
        with self._lock:
            ref=context["invocation_ref"]
            self._auth(ref,context,"observe")
            row=self._require(ref,context,allow_terminal=True)
            if row["submission_id"]!=submission_id:
                raise RunnerError("EXEC_INPUT_INVALID",stage="submission_lookup")
            return copy.deepcopy(row["terminal"])

    def request_stop(self,ref,reason,context):
        with self._tx():
            self._auth(ref,context,"cleanup")
            row=self._require(ref,context,allow_terminal=True)
            row.update(stop_requested=True,stop_reason=reason)
            self._write(ref,row)

    def record_stop(self,ref,status,evidence,context):
        with self._tx():
            self._auth(ref,context,"cleanup")
            row=self._require(ref,context,allow_terminal=True)
            row["stop_status"]=status
            row["notes"].append(dict(code="stop_evidence",payload=copy.deepcopy(evidence)))
            self._write(ref,row)

    def note(self,ref,code,payload,context):
        with self._tx():
            self._auth(ref,context,"report")
            row=self._require(ref,context,allow_terminal=True)
            note_ref="runner-note:"+uuid4().hex
            row["notes"].append(dict(note_ref=note_ref,code=code,payload=copy.deepcopy(payload)))
            self._write(ref,row)
            return note_ref

    def _check_manifest_evidence(self,manifest,row,ref):
        try:
            bindings_ref=row["checkpoint"]["context"]["record"]["bindings_ref"]
            bindings=json.loads(self._read_object(bindings_ref,ref)["body"])
            expected_inputs=[{k:v for k,v in item.items() if k!="content"} for item in bindings["context_items"]]
            if manifest["input_refs"]!=expected_inputs or manifest["prompt_template_ref"]!=bindings["agent_definition"]["prompt_template_ref"]:raise ValueError("Manifest frozen inputs")
            for expected in expected_inputs:
                current=self._db.execute("SELECT project,metadata,body FROM runner_objects WHERE ref=? AND invocation IS NULL",(expected["artifact_ref"],)).fetchone()
                if current is None or current[0]!=ref["project_id"] or any(json.loads(current[1])[k]!=expected[k] for k in ["kind","sha256","state"]) or sha_bytes(bytes(current[2]))!=expected["sha256"]:
                    raise RunnerError("EXEC_INPUT_INVALID",stage="input_invalidated_at_publish",blocked=True)
            slots=bindings["output_contract"]["slots"]
            if len(slots)!=len(manifest["artifacts"]) or any(a["kind"]!=s["kind"] or a["media_type"]!=s["media_type"] or a["schema_ref"]!=s["schema_ref"] for a,s in zip(manifest["artifacts"],slots)):raise ValueError("Manifest output contract")
            required=[c["check_ref"] for c in bindings["required_checks"]]
            if manifest["required_check_refs"]!=required or not manifest["self_check_refs"]:raise ValueError("Missing required checks")
            for report_ref in manifest["self_check_refs"]:
                report=json.loads(self._read_object(report_ref,ref)["body"])
                if report["evidence_kind"]!="self_check" or report["invocation_ref"]!=ref or report["subjects"]!=manifest["artifacts"] or any(report[k]!=manifest[k] for k in ["input_snapshot_id","input_snapshot_sha256","execution_mode"]):raise ValueError("Wrong evidence subject")
                if report["required_check_refs"]!=required or [r["check_ref"] for r in report["results"]]!=required:raise ValueError("Check set mismatch")
                results=[r["result"] for r in report["results"]]
                missing=[r["check_ref"] for r in report["results"] if r["result"]=="not_run"]
                overall="failed" if "failed" in results else "incomplete" if missing else "passed"
                if any(r not in {"passed","failed","not_run"} for r in results) or report["overall_status"]!=overall or manifest["self_check_status"]!=overall or report["missing_check_refs"]!=missing or manifest["missing_check_refs"]!=missing or manifest["known_issue_refs"]!=report["known_issue_refs"]:raise ValueError("Check status mismatch")
        except (KeyError,ValueError,TypeError):
            raise RunnerError("EXEC_ARTIFACT_INVALID",stage="manifest_check_evidence") from None

