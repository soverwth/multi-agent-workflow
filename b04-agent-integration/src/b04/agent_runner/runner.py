"""One admitted Agent attempt: execute, check, submit once, and report honestly."""
from __future__ import annotations

import asyncio
import copy
import re
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from b04.model_adapter import ModelAdapterError, to_exec_error
from b04.model_adapter.contracts import (CALL_FIELDS, IDENTITY_FIELDS, canonical, digest, invocation_ref, model_call_ref,
                                        parse_time, stamp, utc_now)
from b04.model_adapter.schemas import FEEDBACK_SCHEMA, RESULT_SCHEMA, conforms
from .artifacts import ArtifactCoordinator, CheckCoordinator
from .context import ContextAssembler
from .contracts import (AlreadyTerminal, COMMIT_SCHEMA, CommitUncertain, ENVELOPE_SCHEMA, INVOCATION_SCHEMA, PendingStop, RunnerControls,
                        RunnerError, StopRequested, TOOL_REQUEST_SCHEMA, TOOL_RESULT_SCHEMA, key_of, validate)
from .outbox import EventOutbox
from .runtime import scoped_path


class AgentRunner:
    def __init__(self,*,store,catalog,controls,authority,model_adapter,tool_executor,event_sink,
                 control_budget,transport_budget,source=None,auto_start=True,poll_interval_seconds=0.01,cleanup_timeout_seconds=0.5):
        if poll_interval_seconds<=0 or cleanup_timeout_seconds<=0:raise ValueError("Timeouts must be positive")
        self.store,self.catalog,self.controls,self.authority=store,catalog,controls,authority
        self.model,self.tools=model_adapter,tool_executor
        self.control_budget,self.auto_start=control_budget,auto_start
        self.poll_interval,self.cleanup_timeout=poll_interval_seconds,cleanup_timeout_seconds
        self.assembler=ContextAssembler(store)
        self.artifacts=ArtifactCoordinator(store,source)
        self.checks=CheckCoordinator(store)
        self.outbox=EventOutbox(store=store,sink=event_sink,transport_budget=transport_budget,control_budget=control_budget)
        self._workers,self._cancel_events,self._stop_locks,self._background={},{},{},set()

    def _authorize(self,control,purpose,ref):
        try:
            self.authority.authorize(control.context,purpose,utc_now())
            if control.context["invocation_ref"]!=ref:raise KeyError("Wrong identity")
        except (ModelAdapterError,KeyError,TypeError):
            raise RunnerError("EXEC_LEASE_INVALID",stage="runner_authority") from None

    def _controls(self,ref,envelope=None):
        controls=self.controls.acquire(ref)
        for control,purpose in [(controls.model,"execute"),(controls.tool,"execute"),(controls.observe,"observe"),(controls.report,"report"),(controls.cleanup,"cleanup")]:
            if envelope is not None:
                self._authorize(control,purpose,ref)
                if any(control.context[k]!=envelope[k] for k in ["input_snapshot_id","input_snapshot_sha256"]):
                    raise RunnerError("EXEC_LEASE_INVALID",stage="control_snapshot")
        if envelope is not None:
            if any(c.context["lease_ref"]!=envelope["lease_ref"] for c in [controls.model,controls.tool]):
                raise RunnerError("EXEC_LEASE_INVALID",stage="dispatch_lease")
            if any(c.context["write_scope"]!=envelope["write_scope"] for c in [controls.model,controls.tool]):
                raise RunnerError("EXEC_WRITE_SCOPE",stage="dispatch_scope")
        return controls

    @staticmethod
    def _receipt(accepted,duplicate,ref,reason=None):
        return dict(accepted=accepted,duplicate=duplicate,invocation_ref=copy.deepcopy(ref),reason_code=reason,
                    message="Invocation persisted" if accepted else "Invocation rejected")

    async def invoke_agent(self,envelope):
        envelope=copy.deepcopy(envelope);ref=None
        try:
            validate(envelope,ENVELOPE_SCHEMA)
            ref=invocation_ref(envelope)
            if envelope["retry_count"]>envelope["retry_budget"]:
                raise RunnerError("EXEC_INVALID_ENVELOPE",stage="retry_budget")
            controls=self._controls(ref,envelope)
            fingerprint=digest(envelope)
            try:
                previous=self.store.get(ref,controls.observe.context)
                if previous["fingerprint"]!=fingerprint:
                    raise RunnerError("EXEC_DISPATCH_CONFLICT",stage="duplicate_dispatch")
                return self._receipt(True,True,ref)
            except RunnerError as fault:
                if fault.stage!="not_found":raise
            bundle=self.catalog.load(envelope,controls.model.context)
            self.assembler.inputs(envelope,bundle,controls.model.context)
            if any(s["source"]["type"]=="repository_bundle" for s in bundle["output_contract"]["slots"]) and self.artifacts.source is None:
                raise RunnerError("EXEC_CAPABILITY_UNAVAILABLE",stage="source_port",blocked=True)
            description=await self.model.describe_model(envelope["model_config_ref"],controls.model)
            if description["model_config_ref"]!=envelope["model_config_ref"] or envelope["execution_mode"] not in description["execution_modes"]:
                raise RunnerError("EXEC_CAPABILITY_UNAVAILABLE",stage="model_mode",blocked=True)
            created,row=self.store.admit(envelope,fingerprint,controls.model.context)
            if created and self.auto_start:self._schedule(ref,controls)
            return self._receipt(True,not created,ref)
        except ModelAdapterError as fault:
            return self._receipt(False,False,ref,"EXEC_CAPABILITY_UNAVAILABLE" if fault.code!="MODEL_CONTROL_INVALID" else "EXEC_LEASE_INVALID")
        except RunnerError as fault:
            return self._receipt(False,False,ref,fault.code)
        except (KeyError,TypeError,ValueError):
            return self._receipt(False,False,ref,"EXEC_INVALID_ENVELOPE")

    def _schedule(self,ref,controls,*,recover=False):
        key=key_of(ref)
        if key in self._workers and not self._workers[key].done():return self._workers[key]
        signal=controls.model.cancel_signal or asyncio.Event()
        self._cancel_events[key]=signal
        runtime=replace(controls,model=replace(controls.model,cancel_signal=signal),tool=replace(controls.tool,cancel_signal=signal))
        task=asyncio.create_task(self._worker(copy.deepcopy(ref),runtime,recover=recover))
        self._workers[key]=task
        def complete(future):
            try:future.result()
            except BaseException:pass  # Durable checkpoints, not task exceptions, drive recovery.
        task.add_done_callback(complete)
        return task

    async def wait_invocation(self,ref,timeout=5):
        task=self._workers.get(key_of(ref))
        if task is not None:await asyncio.wait_for(asyncio.shield(task),timeout)
        return await self.get_invocation(ref)

    async def get_invocation(self,ref):
        validate(ref,INVOCATION_SCHEMA)
        controls=self._controls(ref)
        self._authorize(controls.observe,"observe",ref)
        self.control_budget.consume_control(controls.observe.context["budget_ticket_ref"],ref,utc_now())
        row=self.store.get(ref,controls.observe.context)
        events=self.store.events(ref,controls.observe.context)
        return dict(invocation_ref=copy.deepcopy(ref),phase=row["phase"],terminal=copy.deepcopy(row["terminal"]),stop_status=row["stop_status"],
                    stop_requested=row["stop_requested"],recovery_required=row["recovery_required"],execution_record_ref=row["execution_record_ref"],
                    context_record_ref=row["checkpoint"].get("context",{}).get("context_record_ref"),
                    recent_model_ref=row["checkpoint"].get("pending_model"),recent_operation_ref=row["checkpoint"].get("pending_operation"),
                    events=[dict(event_id=e["event"]["event_id"],event_seq=e["event"]["event_seq"],event_type=e["event"]["event_type"],
                                 delivery=e["delivery"],receipt=e["receipt"],reconciliation=e["reconciliation"]) for e in events],notes=copy.deepcopy(row["notes"]))

    async def describe_capabilities(self,catalog_ref):
        return self.catalog.describe(catalog_ref)

    async def flush_events(self,ref):
        await self.outbox.flush(ref,self._controls(ref))

    def _guard(self,ref,owner,controls):
        row=self.store.get(ref,controls.observe.context)
        if row["terminal"]:raise AlreadyTerminal()
        if row["owner"]!=owner:raise RunnerError("EXEC_LEASE_INVALID",stage="execution_fence")
        if row["stop_requested"] or controls.model.cancel_signal is not None and controls.model.cancel_signal.is_set():
            if not row["stop_requested"]:self.store.request_stop(ref,"control_cancel_signal",controls.cleanup.context)
            raise StopRequested()
        self._authorize(controls.model,"execute",ref)
        if parse_time(row["deadline_at"])<=utc_now():raise RunnerError("EXEC_TIMEOUT",stage="execution_deadline")
        bundle=self.catalog.load(row["envelope"],controls.model.context)
        self.assembler.inputs(row["envelope"],bundle,controls.model.context)
        return row

    def _save(self,ref,owner,phase,cp,controls,*,diagnostic=False):
        self.store.checkpoint(ref,owner,phase,cp,controls.report.context if diagnostic else controls.model.context)

    async def _bounded(self,awaitable,ref,owner,controls,*,deadline=None):
        task=asyncio.create_task(awaitable)
        try:
            while True:
                done,_=await asyncio.wait([task],timeout=self.poll_interval)
                if task in done:return task.result()
                self._guard(ref,owner,controls)
                if deadline is not None and parse_time(deadline)<=utc_now():
                    raise RunnerError("EXEC_TIMEOUT",stage="operation_deadline",stop_status="unknown")
        finally:
            if not task.done():
                task.cancel();self._retain(task)

    def _retain(self,task):
        self._background.add(task)
        def complete(future):
            self._background.discard(future)
            try:future.result()
            except BaseException:pass
        task.add_done_callback(complete)

    async def _worker(self,ref,controls,*,recover=False):
        owner="runner-owner:"+uuid4().hex
        try:
            row=self.store.claim_execution(ref,owner,controls.model.context,recover=recover)
        except AlreadyTerminal:
            await self.outbox.flush(ref,controls);return
        except RunnerError as fault:
            row=self.store.get(ref,controls.observe.context)
            if row["owner"] is not None:raise
            try:await self._fail(ref,None,controls,fault)
            except CommitUncertain:self.store.mark_recovery(ref,None,"commit_unknown",controls.report.context)
            await self.outbox.flush(ref,controls)
            return
        envelope=row["envelope"]
        cp=copy.deepcopy(row["checkpoint"])
        try:
            self._guard(ref,owner,controls)
            bundle=self.catalog.load(envelope,controls.model.context)
            if "context" not in cp:
                self._save(ref,owner,"PREPARING",cp,controls)
                if any(slot["source"]["type"]=="repository_bundle" for slot in bundle["output_contract"]["slots"]):
                    if not hasattr(self.artifacts.source,"prepare"):raise RunnerError("EXEC_CAPABILITY_UNAVAILABLE",stage="workspace_preparation",blocked=True)
                    workspace=self.artifacts.source.prepare(envelope,controls.model.context)
                    record=self.store.put_object(ref,"workspace-preparation","workspace_record",canonical(workspace).encode(),controls.model.context)
                    cp["workspace_record_ref"]=record["artifact_ref"]
                cp.update(context=self.assembler.assemble(envelope,bundle,controls.model.context),call_seq=0,model_refs=[],tool_refs=[],
                          corrections=0,final=None,pending_model=None,pending_operation=None)
                cp["messages"]=copy.deepcopy(cp["context"]["messages"])
                self._save(ref,owner,"EXECUTING",cp,controls)
            self.store.emit(ref,"execution_started",dict(agent_definition_ref=envelope["agent_definition_ref"]),controls.model.context)
            while True:
                final=await self._model_loop(envelope,bundle,cp,owner,controls)
                try:
                    self._guard(ref,owner,controls)
                    frozen=cp.get("frozen") or self.artifacts.freeze(envelope,bundle,final,controls)
                    break
                except RunnerError as fault:
                    if fault.code!="EXEC_ARTIFACT_INVALID" or cp["corrections"]>=bundle["profile"]["max_output_corrections"]:raise
                    cp["corrections"]+=1;cp["final"]=None
                    cp["messages"].append(dict(role="user",content=[dict(type="text",text=canonical(dict(kind="artifact_validation_feedback",code=fault.code)))]))
                    self._save(ref,owner,"EXECUTING",cp,controls)
            cp["frozen"]=frozen
            self._save(ref,owner,"SELF_CHECKING",cp,controls)
            refreezes=cp.get("refreezes",0)
            while True:
                self._guard(ref,owner,controls)
                async def execute(binding,args,origin,name):
                    return await self._tool(envelope,bundle,cp,owner,controls,binding,args,origin,name)
                report,report_ref=await self.checks.run(envelope,bundle,frozen,controls,execute,lambda:self._guard(ref,owner,controls))
                self._guard(ref,owner,controls)
                if self.artifacts.verify(envelope,bundle,frozen,controls):break
                self.store.note(ref,"self_check_invalidated",dict(report_ref=report_ref,responsible=envelope["escalation_target"]),controls.report.context)
                if refreezes>=bundle["profile"]["max_refreezes"]:raise RunnerError("EXEC_ARTIFACT_INVALID",stage="unstable_checked_content")
                refreezes+=1
                frozen=self.artifacts.freeze(envelope,bundle,final,controls)
                cp.update(frozen=frozen,refreezes=refreezes)
                self._save(ref,owner,"SELF_CHECKING",cp,controls)
            self._guard(ref,owner,controls)
            cp.update(check_report_ref=report_ref)
            row=self.store.get(ref,controls.observe.context)
            manifest=self.artifacts.manifest(envelope,bundle,row,frozen,report,report_ref,cp["model_refs"],cp["tool_refs"])
            meta=self.store.put_object(ref,"manifest","manifest",canonical(manifest).encode(),controls.model.context)
            draft=self._draft(row,"candidate_submitted",manifest_ref=meta["artifact_ref"],manifest_sha256=meta["sha256"])
            cp["draft"]=draft
            self._save(ref,owner,"SUBMITTING",cp,controls)
            await self._commit(draft,controls,owner=owner)
        except AlreadyTerminal:
            pass
        except CommitUncertain:
            self.store.mark_recovery(ref,owner,"commit_unknown",controls.report.context)
        except (StopRequested,PendingStop):
            stop=await self._stop_all(ref,controls)
            if stop["stop_status"]=="confirmed":await self._finish_stop(ref,controls)
            else:self.store.mark_recovery(ref,owner,"stop_unconfirmed",controls.report.context)
        except asyncio.CancelledError:
            self.store.mark_recovery(ref,owner,"worker_interrupted",controls.report.context)
            await self._stop_all(ref,controls)
            raise
        except Exception as exc:
            fault=exc if isinstance(exc,RunnerError) else RunnerError(stage="runner_exception")
            try:
                row=self.store.get(ref,controls.observe.context)
                if row["stop_requested"]:
                    stop=await self._stop_all(ref,controls)
                    if stop["stop_status"]=="confirmed":await self._finish_stop(ref,controls)
                    else:self.store.mark_recovery(ref,owner,"stop_unconfirmed",controls.report.context)
                else:await self._fail(ref,owner,controls,fault)
            except AlreadyTerminal:pass
            except CommitUncertain:self.store.mark_recovery(ref,owner,"commit_unknown",controls.report.context)
        finally:
            await self.outbox.flush(ref,controls)

    def _model_request(self,envelope,bundle,cp,row,controls):
        seq=cp["call_seq"]+1
        return dict(adapter_contract_version="b04.model.v0.1",protocol_version=envelope["protocol_version"],execution_mode=envelope["execution_mode"],**invocation_ref(envelope),
            model_call_id="model-call:"+digest([invocation_ref(envelope),seq]),call_seq=seq,input_snapshot_id=envelope["input_snapshot_id"],input_snapshot_sha256=envelope["input_snapshot_sha256"],
            agent_definition_ref=envelope["agent_definition_ref"],prompt_template_ref=bundle["template"]["prompt_template_ref"],model_policy_ref=bundle["agent"]["model_policy_ref"],
            model_config_ref=envelope["model_config_ref"],messages=copy.deepcopy(cp["messages"]),response_spec=bundle["output_contract"]["response_spec"],
            tools=self.assembler.tool_descriptions(bundle),tool_choice=bundle["profile"]["tool_choice"],parameters=copy.deepcopy(bundle["profile"]["parameters"]),
            call_limits=dict(timeout_seconds=envelope["limits"]["model_call_timeout_seconds"],deadline_at=row["deadline_at"],max_output_tokens=bundle["profile"]["max_output_tokens"]),
            budget_ticket_ref=controls.model.context["budget_ticket_ref"])

    @staticmethod
    def _model_fault(error,request):
        execution=to_exec_error(error,model_call_ref(request))
        fault=RunnerError(execution["code"],stage=execution["stage"],blocked=execution["code"] in {"EXEC_INPUT_INVALID","EXEC_CAPABILITY_UNAVAILABLE"},stop_status=execution["stop_status"],details=execution["details"],evidence_refs=execution["evidence_refs"])
        fault.exec_error=execution
        return fault

    def _validate_model(self,result,request):
        validate(result,RESULT_SCHEMA,"EXEC_MODEL_ERROR",stage="model_result")
        if any(result[k]!=request[k] for k in CALL_FIELDS+("execution_mode","input_snapshot_id","input_snapshot_sha256")) or result["selected_model"]["model_config_ref"] not in ({request["model_config_ref"]} if result["status"]=="ok" else {request["model_config_ref"],None}):
            raise RunnerError("EXEC_MODEL_ERROR",stage="model_result_identity",stop_status="unknown")

    async def _poll_model(self,request,ref,owner,controls):
        call=model_call_ref(request)
        while True:
            self._guard(ref,owner,controls)
            snap=await self._bounded(self.model.get_call(call,controls.observe),ref,owner,controls,deadline=request["call_limits"]["deadline_at"])
            if snap["model_call_ref"]!=call:raise RunnerError("EXEC_MODEL_ERROR",stage="model_snapshot_identity",stop_status="unknown")
            if snap.get("result_ref"):
                return await self._bounded(self.model.read_result(call,snap["result_ref"],controls.observe),ref,owner,controls,deadline=request["call_limits"]["deadline_at"])
            if snap["call_state"]=="unknown":
                raise RunnerError("EXEC_MODEL_ERROR",stage="model_state_unknown",stop_status="unknown")
            await asyncio.sleep(self.poll_interval)

    async def _model_loop(self,envelope,bundle,cp,owner,controls):
        ref=invocation_ref(envelope)
        while cp.get("final") is None:
            row=self._guard(ref,owner,controls)
            seq=cp["call_seq"]+1;name="model:"+str(seq)
            if seq>envelope["limits"]["max_model_calls"]:raise RunnerError("EXEC_BUDGET_EXHAUSTED",stage="model_calls")
            if len(canonical(cp["messages"]).encode())>bundle["profile"]["max_context_bytes"]:
                raise RunnerError("EXEC_CAPABILITY_UNAVAILABLE",stage="context_limit",blocked=True)
            action=self.store.action(ref,name,controls.observe.context)
            request=action["request"] if action else self._model_request(envelope,bundle,cp,row,controls)
            if action is None:action=self.store.reserve_action(ref,owner,name,"model",request,controls.model.context)
            cp["pending_model"]=model_call_ref(request)
            self._save(ref,owner,"EXECUTING",cp,controls)
            if action["state"]=="done":result=action["result"]
            elif action["state"]=="called":
                result=await self._poll_model(request,ref,owner,controls)
                self.store.set_action(ref,owner,name,"done",result,controls.report.context)
            else:
                preflight=await self._bounded(self.model.validate_request(request,controls.model),ref,owner,controls)
                if not preflight["valid"]:
                    result=dict(preflight_only=True,status="error",error=preflight["issues"][0],call_record_ref=None)
                else:
                    self._guard(ref,owner,controls)
                    self.store.set_action(ref,owner,name,"called",None,controls.model.context)
                    try:
                        result=await self._bounded(self.model.generate(request,controls.model),ref,owner,controls,deadline=request["call_limits"]["deadline_at"])
                    except ModelAdapterError as fault:
                        result=dict(preflight_only=True,status="error",error=fault.to_dict(),call_record_ref=None)
                    self._validate_model(result,request)
                    if result["status"]=="in_progress":result=await self._poll_model(request,ref,owner,controls)
                self.store.set_action(ref,owner,name,"done",result,controls.report.context)
            if result.get("preflight_only"):
                raise self._model_fault(result["error"],request)
            self._validate_model(result,request)
            if result["status"]!="ok":
                if result["status"]=="cancelled":
                    self.store.request_stop(ref,"model_cancelled",controls.cleanup.context);raise StopRequested()
                raw=result["error"]
                if raw["code"] in {"MODEL_OUTPUT_FORMAT","MODEL_OUTPUT_TRUNCATED"} and raw["stop_status"]=="confirmed" and raw["request_delivery"]!="unknown" and cp["corrections"]<bundle["profile"]["max_output_corrections"]:
                    cp["corrections"]+=1;cp["call_seq"]=seq;cp["pending_model"]=None
                    if result["call_record_ref"]:cp["model_refs"].append(result["call_record_ref"])
                    cp["messages"].append(dict(role="user",content=[dict(type="text",text=canonical(dict(kind="output_validation_feedback",code=raw["code"])))]))
                    self._save(ref,owner,"EXECUTING",cp,controls);continue
                raise self._model_fault(raw,request)
            if result["response"]["kind"]=="tool_calls":
                feedback=[]
                for intent in result["response"]["tool_calls"]:
                    origin=dict(source="model",model_call_id=request["model_call_id"],tool_call_id=intent["tool_call_id"],check_ref=None)
                    tool=await self._tool(envelope,bundle,cp,owner,controls,intent["binding_ref"],intent["arguments"],origin,"intent:"+request["model_call_id"]+":"+intent["tool_call_id"],public_name=intent["name"])
                    value=dict(feedback_contract_version="b04.tool-feedback.v0.1",invocation_ref=ref,input_snapshot_id=envelope["input_snapshot_id"],input_snapshot_sha256=envelope["input_snapshot_sha256"],
                        execution_mode=envelope["execution_mode"],model_call_id=request["model_call_id"],tool_call_id=intent["tool_call_id"],operation_id=tool["operation_id"],tool_binding_ref=tool["tool_binding_ref"],
                        **{k:copy.deepcopy(tool[k]) for k in ["status","result_code","payload","exit_code","stop_status","side_effects_state","error","output_refs","changes","operation_record_ref"]},truncation=dict(fields=[],original_refs=[]))
                    validate(value,FEEDBACK_SCHEMA,"EXEC_TOOL_ERROR",stage="tool_feedback")
                    feedback.append(dict(role="tool",tool_call_id=intent["tool_call_id"],content=[dict(type="text",text=canonical(value))]))
                cp["messages"].append(dict(role="assistant",content=[],tool_calls=copy.deepcopy(result["response"]["tool_calls"])))
                cp["messages"].extend(feedback)
            elif result["response"]["kind"]=="final":cp["final"]=copy.deepcopy(result)
            else:raise RunnerError("EXEC_MODEL_ERROR",stage="model_branch")
            if result["call_record_ref"] and result["call_record_ref"] not in cp["model_refs"]:cp["model_refs"].append(result["call_record_ref"])
            cp["call_seq"]=seq;cp["pending_model"]=None
            self._save(ref,owner,"EXECUTING",cp,controls)
            self.store.emit(ref,"execution_progress",dict(agent_definition_ref=envelope["agent_definition_ref"],model_call_id=request["model_call_id"],call_seq=seq),controls.model.context)
        return cp["final"]

    async def _tool(self,envelope,bundle,cp,owner,controls,binding_ref,args,origin,name,public_name=None):
        ref=invocation_ref(envelope);row=self._guard(ref,owner,controls)
        bindings=[b for b in bundle["tool_config"]["bindings"] if b["binding_ref"]==binding_ref]
        if len(bindings)!=1 or public_name is not None and (binding_ref not in bundle["tool_config"]["model_binding_refs"] or bindings[0]["model_tool_name"]!=public_name):
            raise RunnerError("EXEC_TOOL_ERROR",stage="tool_binding")
        binding=bindings[0]
        schema=bundle["schemas"][binding["model_input_schema_ref"] if origin["source"]=="model" else binding["executor_input_schema_ref"]]
        if not conforms(args,schema):raise RunnerError("EXEC_TOOL_ERROR",stage="tool_parameters")
        raw_fp=digest([binding_ref,args,origin])
        intent_name="mapping:"+name
        intent=self.store.action(ref,intent_name,controls.observe.context)
        if intent:
            original=intent["request"]
            if original["raw_fingerprint"]!=raw_fp:raise RunnerError("EXEC_TOOL_ERROR",stage="intent_conflict")
        else:
            original=dict(operation_id="operation:"+digest([ref,name]),raw_fingerprint=raw_fp,arguments=copy.deepcopy(args),origin=copy.deepcopy(origin),binding_ref=binding_ref,
                          timeout_seconds=min(bundle["profile"]["tool_timeout_seconds"],max(0.001,(parse_time(row["deadline_at"])-utc_now()).total_seconds())),
                          deadline_at=stamp(min(parse_time(row["deadline_at"]),utc_now()+timedelta(seconds=bundle["profile"]["tool_timeout_seconds"]))))
            self.store.reserve_action(ref,owner,intent_name,"intent",original,controls.model.context)
        op_ref=dict(invocation_ref=ref,operation_id=original["operation_id"])
        normalized=copy.deepcopy(original["arguments"])
        definition=bundle["tool_config"]["definitions"][binding_ref]
        if "file_write" in definition["permission_classes"]:
            if not scoped_path(normalized.get("path"),controls.tool.context["write_scope"]["workspace_paths"]):
                raise RunnerError("EXEC_WRITE_SCOPE",stage="file_target",operation_ref=op_ref)
        if "command_profile_ref" in normalized and normalized["command_profile_ref"] not in binding["command_profile_refs"]:
            raise RunnerError("EXEC_TOOL_ERROR",stage="command_profile",operation_ref=op_ref)
        if binding["normalization_profile_ref"]=="normalizer:inline-text-to-draft@1":
            try:
                if normalized["encoding"]!="utf-8" or not isinstance(normalized["content"],str):raise ValueError("Unsupported encoding")
                draft=self.store.stage_draft_content(ref,op_ref,raw_fp,normalized.pop("content").encode("utf-8"),"text/plain",controls.tool.context)
                normalized.update(content_ref=draft["content_ref"],expected_content_sha256=draft["sha256"])
            except (KeyError,ValueError,UnicodeError):raise RunnerError("EXEC_TOOL_ERROR",stage="draft_normalization",operation_ref=op_ref) from None
        if not conforms(normalized,bundle["schemas"][binding["executor_input_schema_ref"]]):
            raise RunnerError("EXEC_TOOL_ERROR",stage="normalized_parameters",operation_ref=op_ref)
        request=dict(tool_contract_version="b04.tool.v0.1",protocol_version=envelope["protocol_version"],execution_mode=envelope["execution_mode"],invocation_ref=ref,
            operation_id=op_ref["operation_id"],tool_binding_ref=binding_ref,tool_name=binding["tool_name"],tool_version=binding["tool_version"],arguments=normalized,
            input_snapshot_id=envelope["input_snapshot_id"],input_snapshot_sha256=envelope["input_snapshot_sha256"],lease_ref=envelope["lease_ref"],tool_config_ref=envelope["tool_config_ref"],
            workspace_ref=envelope["workspace_ref"],timeout_seconds=original["timeout_seconds"],deadline_at=original["deadline_at"],origin=origin)
        validate(request,TOOL_REQUEST_SCHEMA,"EXEC_TOOL_ERROR",stage="tool_request")
        action=self.store.action(ref,name,controls.observe.context)
        if action is None:
            used=sum(a["kind"] in {"tool","check"} and a["state"] in {"called","done"} for a in self.store.actions(ref,controls.observe.context))
            if used>=envelope["limits"]["max_tool_calls"]:raise RunnerError("EXEC_BUDGET_EXHAUSTED",stage="tool_calls")
            action=self.store.reserve_action(ref,owner,name,"check" if origin["source"]=="self_check" else "tool",request,controls.model.context)
        elif action["request"]!=request:raise RunnerError("EXEC_TOOL_ERROR",stage="operation_conflict",operation_ref=op_ref)
        cp["pending_operation"]=op_ref
        self._save(ref,owner,"SELF_CHECKING" if origin["source"]=="self_check" else "EXECUTING",cp,controls)
        if action["state"]=="done":result=action["result"]
        elif action["state"]=="called":
            result=await self._poll_tool(request,ref,owner,controls)
            self.store.set_action(ref,owner,name,"done",result,controls.report.context)
        else:
            if parse_time(request["deadline_at"])<=utc_now():raise RunnerError("EXEC_TIMEOUT",stage="tool_deadline",operation_ref=op_ref)
            self._authorize(controls.tool,"execute",ref)
            self._guard(ref,owner,controls)
            self.store.set_action(ref,owner,name,"called",None,controls.model.context)
            try:
                result=await self._bounded(self.tools.execute_tool(request,controls.tool),ref,owner,controls,deadline=request["deadline_at"])
            except RunnerError as fault:
                if fault.operation_ref is None:fault.operation_ref=op_ref
                raise
            except (StopRequested,AlreadyTerminal):raise
            except Exception:
                stop=await self._cleanup_call(self.tools.stop_operation(op_ref,"tool_transport_failure",controls.cleanup))
                status=self._verified_stop(stop,"operation_ref",op_ref)
                record=self.store.put_object(ref,"tool-transport-failure:"+request["operation_id"],"tool_failure_record",canonical(dict(operation_ref=op_ref,stop_receipt=stop)).encode(),controls.report.context)
                result=dict(transport_failure=True,stop_status=status,operation_record_ref=record["artifact_ref"])
                self.store.set_action(ref,owner,name,"done",result,controls.report.context)
                raise RunnerError("EXEC_TOOL_ERROR",stage="tool_transport",stop_status=status,operation_ref=op_ref,evidence_refs=[record["artifact_ref"]]) from None
            self._validate_tool(result,request,bundle,definition,allow_in_progress=True)
            if result.get("status")=="in_progress":result=await self._poll_tool(request,ref,owner,controls)
            self.store.set_action(ref,owner,name,"done",result,controls.report.context)
        if result.get("transport_failure"):
            raise RunnerError("EXEC_TOOL_ERROR",stage="tool_transport",stop_status=result["stop_status"],operation_ref=op_ref,evidence_refs=[result["operation_record_ref"]])
        self._validate_tool(result,request,bundle,definition)
        if result["operation_record_ref"] not in cp["tool_refs"]:cp["tool_refs"].append(result["operation_record_ref"])
        cp["pending_operation"]=None
        self._save(ref,owner,"SELF_CHECKING" if origin["source"]=="self_check" else "EXECUTING",cp,controls,diagnostic=True)
        if result["status"]!="completed" or result["stop_status"]!="confirmed" or result["side_effects_state"]=="unknown":
            raw=result.get("error") or {}
            code="EXEC_TIMEOUT" if result["status"]=="timed_out" else "EXEC_BUDGET_EXHAUSTED" if result["result_code"]=="TOOL_BUDGET_EXHAUSTED" else "EXEC_LEASE_INVALID" if result["result_code"]=="TOOL_LEASE_INVALID" else "EXEC_WRITE_SCOPE" if result["result_code"]=="TOOL_SCOPE_DENIED" and "file_write" in definition["permission_classes"] else "EXEC_TOOL_ERROR"
            unavailable=result['result_code'] in {'TOOL_NOT_REGISTERED','TOOL_DISABLED','TOOL_PROFILE_UNSUPPORTED'}
            if unavailable:code='EXEC_CAPABILITY_UNAVAILABLE'
            permission_denied=result['result_code'] in {'TOOL_SCOPE_DENIED','TOOL_PATH_INVALID'}
            write_tool=bool({'file_write','workspace_write'}&set(definition['permission_classes']))
            if permission_denied and write_tool:code='EXEC_WRITE_SCOPE'
            protected=self.store.put_object(ref,"tool-result:"+result["operation_id"],"tool_result",canonical(result).encode(),controls.report.context)
            raw_code=raw.get("code",result["result_code"])
            safe_code=raw_code if isinstance(raw_code,str) and re.fullmatch(r"[A-Z0-9_]{1,64}",raw_code) else "TOOL_RESULT_UNKNOWN"
            details=dict(tool=dict(code=safe_code,result_code=result["result_code"],status=result["status"],exit_code=result["exit_code"],
                                   side_effects_state=result["side_effects_state"],raw_result_ref=protected["artifact_ref"]))
            if permission_denied:details["denied_action"]='write' if write_tool else 'read_or_execute'
            raise RunnerError(code,stage="tool_execution",blocked=unavailable,stop_status=result["stop_status"] or "unknown",operation_ref=op_ref,details=details,evidence_refs=[result["operation_record_ref"],protected["artifact_ref"]])
        return result

    @staticmethod
    def _validate_tool(result,request,bundle,definition,*,allow_in_progress=False):
        validate(result,TOOL_RESULT_SCHEMA,"EXEC_TOOL_ERROR",stage="tool_result")
        for key in ["invocation_ref","operation_id","tool_binding_ref","tool_name","tool_version","input_snapshot_id","input_snapshot_sha256","execution_mode"]:
            if result[key]!=request[key]:raise RunnerError("EXEC_TOOL_ERROR",stage="tool_result_identity",stop_status="unknown")
        if result["status"]=="completed" and (result["error"] is not None or not conforms(result["payload"],bundle["schemas"][definition["output_schema_ref"]])):
            raise RunnerError("EXEC_TOOL_ERROR",stage="tool_result_schema")
        if result["status"]=="in_progress":
            if not allow_in_progress or result["payload"] is not None or result["error"] is not None or result["timing"]["finished_at"] is not None or result["timing"]["execution_duration_ms"] is not None or result["stop_status"]=="confirmed":
                raise RunnerError("EXEC_TOOL_ERROR",stage="invalid_in_progress",stop_status="unknown")

    async def _poll_tool(self,request,ref,owner,controls):
        op=dict(invocation_ref=ref,operation_id=request["operation_id"])
        while True:
            self._guard(ref,owner,controls)
            if parse_time(request["deadline_at"])<=utc_now():raise RunnerError("EXEC_TIMEOUT",stage="tool_deadline",stop_status="unknown",operation_ref=op)
            snapshot=await self._bounded(self.tools.get_operation(op,controls.observe),ref,owner,controls,deadline=request["deadline_at"])
            if snapshot["operation_ref"]!=op:raise RunnerError("EXEC_TOOL_ERROR",stage="operation_snapshot_identity",stop_status="unknown")
            if snapshot.get("result_ref"):
                return await self._bounded(self.tools.read_result(op,snapshot["result_ref"],controls.observe),ref,owner,controls,deadline=request["deadline_at"])
            if snapshot["state"]=="unknown":raise RunnerError("EXEC_TOOL_ERROR",stage="operation_unknown",stop_status="unknown",operation_ref=op)
            await asyncio.sleep(self.poll_interval)

    @staticmethod
    def _draft(row,kind,manifest_ref=None,manifest_sha256=None,error_ref=None):
        return dict(submission_id=row["submission_id"],invocation_ref=invocation_ref(row["envelope"]),input_snapshot_id=row["envelope"]["input_snapshot_id"],input_snapshot_sha256=row["envelope"]["input_snapshot_sha256"],
                    terminal_kind=kind,manifest_ref=manifest_ref,manifest_sha256=manifest_sha256,error_ref=error_ref)

    async def _commit(self,draft,controls,*,owner=None):
        context=controls.model.context if draft["terminal_kind"]=="candidate_submitted" else controls.report.context
        try:
            receipt=self.store.commit_terminal(draft,context,owner=owner)
            validate(receipt,COMMIT_SCHEMA,"EXEC_RUNNER_ERROR",stage="commit_receipt")
            if receipt["submission_id"]!=draft["submission_id"]:raise CommitUncertain()
        except Exception as exc:
            try:known=self.store.get_terminal_submission(draft["submission_id"],controls.observe.context)
            except Exception:raise CommitUncertain() from None
            if known:return known["receipt"]
            if isinstance(exc,RunnerError) and exc.stage!="commit_receipt":raise
            raise CommitUncertain() from None
        if receipt["commit_status"] in {"committed","duplicate"}:return receipt
        try:known=self.store.get_terminal_submission(draft["submission_id"],controls.observe.context)
        except Exception:raise CommitUncertain() from None
        if known:return known["receipt"]
        if receipt["commit_status"]=="rejected":raise RunnerError("EXEC_LEASE_INVALID" if receipt["reason_code"]=="LEASE_INVALID" else "EXEC_ARTIFACT_INVALID",stage="terminal_rejected")
        raise CommitUncertain()

    async def _fail(self,ref,owner,controls,fault):
        stop=await self._stop_all(ref,controls)
        if stop["stop_status"]!="confirmed":fault.stop_status=stop["stop_status"]
        row=self.store.get(ref,controls.observe.context)
        if row["terminal"]:return
        error=copy.deepcopy(getattr(fault,"exec_error",fault.to_dict(row["execution_record_ref"])))
        error["stop_status"]=fault.stop_status
        if fault.stop_status!="confirmed":error.update(recoverability="requires_reconciliation",requested_action="reconcile_then_decide")
        self.control_budget.consume_control(controls.report.context["budget_ticket_ref"],ref,utc_now())
        meta=self.store.put_object(ref,"execution-error","exec_error",canonical(error).encode(),controls.report.context)
        draft=self._draft(row,"execution_blocked" if fault.blocked else "execution_failed",error_ref=meta["artifact_ref"])
        cp=copy.deepcopy(row["checkpoint"]);cp["draft"]=draft
        self._save(ref,owner,"SUBMITTING",cp,controls,diagnostic=True)
        await self._commit(draft,controls,owner=owner)

    async def _cleanup_call(self,awaitable):
        task=asyncio.create_task(awaitable)
        try:
            done,_=await asyncio.wait([task],timeout=self.cleanup_timeout)
            if task in done:return task.result()
            return dict(stop_status="unknown",evidence_refs=[])
        finally:
            if not task.done():task.cancel();self._retain(task)

    async def _stop_all(self,ref,controls):
        evidence=[];states=[]
        for action in self.store.actions(ref,controls.observe.context):
            if action["kind"] not in {"model","tool","check"} or action["state"]=="prepared":continue
            result=action["result"]
            if action["state"]=="done" and result:
                if action["kind"]=="model":
                    stopped=result.get("error",{}).get("stop_status") if result.get("error") else "confirmed"
                else:stopped=result.get("stop_status")
                if stopped=="confirmed":continue
            try:
                if action["kind"]=="model":
                    expected=model_call_ref(action["request"])
                    receipt=await self._cleanup_call(self.model.cancel_call(expected,"runner_cleanup",controls.cleanup))
                    state=self._verified_stop(receipt,"model_call_ref",expected)
                else:
                    expected=dict(invocation_ref=ref,operation_id=action["request"]["operation_id"])
                    receipt=await self._cleanup_call(self.tools.stop_operation(expected,"runner_cleanup",controls.cleanup))
                    state=self._verified_stop(receipt,"operation_ref",expected)
                states.append(state if state in {"confirmed","pending","unknown"} else "unknown")
                evidence.append(receipt)
            except Exception:states.append("unknown")
        state="unknown" if "unknown" in states else "pending" if "pending" in states else "confirmed"
        self.store.record_stop(ref,state,evidence,controls.cleanup.context)
        return dict(stop_status=state,evidence_refs=evidence)

    @staticmethod
    def _verified_stop(receipt,identity_key,expected):
        if not isinstance(receipt,dict) or receipt.get(identity_key)!=expected:return "unknown"
        state=receipt.get("stop_status","unknown")
        evidence=receipt.get("evidence_refs")
        if state not in {"confirmed","pending","unknown"}:return "unknown"
        if state=="confirmed" and (not isinstance(evidence,list) or not evidence or any(not isinstance(e,str) or not e for e in evidence)):return "unknown"
        return state

    async def stop_invocation(self,ref,reason):
        validate(ref,INVOCATION_SCHEMA)
        if not isinstance(reason,str) or not reason:raise RunnerError("EXEC_INVALID_ENVELOPE",stage="stop_reason")
        controls=self._controls(ref)
        self._authorize(controls.cleanup,"cleanup",ref)
        lock=self._stop_locks.setdefault(key_of(ref),asyncio.Lock())
        async with lock:
            self.store.request_stop(ref,reason,controls.cleanup.context)
            if key_of(ref) in self._cancel_events:self._cancel_events[key_of(ref)].set()
            stop=await self._stop_all(ref,controls)
            if stop["stop_status"]=="confirmed":await self._finish_stop(ref,controls)
            return dict(invocation_ref=copy.deepcopy(ref),stop_status=stop["stop_status"],evidence_refs=stop["evidence_refs"])

    async def _finish_stop(self,ref,controls):
        row=self.store.get(ref,controls.observe.context)
        if row["terminal"]:return
        await self._commit(self._draft(row,"execution_stopped"),controls)

    async def recover_invocation(self,ref):
        validate(ref,INVOCATION_SCHEMA)
        controls=self._controls(ref)
        row=self.store.get(ref,controls.observe.context)
        if row["terminal"]:
            await self.outbox.flush(ref,controls)
        elif row["stop_requested"]:
            await self.stop_invocation(ref,"recovery_of_stop")
        elif row["checkpoint"].get("draft"):
            draft=row["checkpoint"]["draft"]
            try:await self._commit(draft,controls,owner=row["owner"])
            except CommitUncertain:self.store.mark_recovery(ref,row["owner"],"commit_unknown",controls.report.context)
            except RunnerError as fault:await self._fail(ref,row["owner"],controls,fault)
            await self.outbox.flush(ref,controls)
        else:
            task=self._schedule(ref,controls,recover=True)
            await asyncio.shield(task)
        return await self.get_invocation(ref)

