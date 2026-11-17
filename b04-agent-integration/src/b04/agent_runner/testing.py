"""Explicitly simulated B02/tool services and a complete offline integration fixture.

The write_file fixture performs real writes only in its registered workspace.
It executes no shell commands or generated code. This is not tool_executor itself.
"""
from __future__ import annotations

import asyncio
import copy
import inspect
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from b04.model_adapter import (CallControl, InMemoryAuthority, InMemoryBudget, InMemoryConfigResolver, MockDriver,
                              ModelAdapterFacade, ProviderDriverRegistry, SQLiteCallLedger, mock_capabilities)
from b04.model_adapter.contracts import canonical, digest, invocation_ref, stamp, utc_now
from b04.model_adapter.schemas import conforms, strict_loads
from .contracts import RunnerControls, RunnerError, VARIABLES, sha_bytes
from .context import InMemoryFrozenCatalog
from .runner import AgentRunner
from .runtime import LocalTransportBudget, ModelAdapterBridge, RegisteredControlProvider, scoped_path
from .store import SQLiteRunnerStore


class RecordingEventSink:
    def __init__(self):
        self.received=[];self.reconciliations=[];self.recorded={};self.status_by_type={}
        self.resolution="recorded";self.before_submit=None

    async def submit_event(self,event):
        self.received.append(copy.deepcopy(event))
        if self.before_submit:
            value=self.before_submit(event)
            if inspect.isawaitable(value):await value
        status=self.status_by_type.get(event["event_type"],"recorded")
        if event["event_id"] in self.recorded and self.recorded[event["event_id"]]!=event:raise ValueError("Event identity conflict")
        if status=="recorded":self.recorded[event["event_id"]]=copy.deepcopy(event)
        return dict(event_id=event["event_id"],receipt_status=status,reason_code="TEST_REJECTION" if status=="rejected" else None,
                    receipt_ref="event-receipt:"+digest([event["event_id"],status]),reconciliation_required=status=="rejected")

    async def reconcile_terminal(self,request,report_context):
        self.reconciliations.append(copy.deepcopy(request))
        return dict(submission_id=request["submission_id"],resolution=self.resolution,reason_code="TEST_DECISION",decision_ref="test-decision:"+digest(request),next_action_ref=None)


class ScriptedToolExecutor:
    def __init__(self,*,store,authority,bundle,workspace=None):
        self.store,self.authority,self.bundle=store,authority,bundle
        self.workspace=Path(workspace).resolve() if workspace else None
        self.requests=[];self.results={};self.handlers={};self.stop_receipts={};self.confirm_stop=True
        self.check_outcomes={};self.query_count=0;self.stop_count=0;self.charged=set();self._report_contexts={}

    def _key(self,request):return digest([request["invocation_ref"],request["operation_id"]])

    def _auth(self,control,ref,purpose):
        self.authority.authorize(control.context,purpose,utc_now())
        if control.context["invocation_ref"]!=ref:raise RunnerError("EXEC_TOOL_ERROR",stage="test_tool_identity")

    def result(self,request,*,payload=None,status="completed",code="TOOL_COMPLETED",stop="confirmed",effects="none",error=None,output_refs=None,exit_code=None):
        record=self.store.put_object(request["invocation_ref"],"tool-record:"+request["operation_id"],"tool_operation",canonical(dict(request=request,status=status,code=code)).encode(),self._report_contexts[canonical(request["invocation_ref"])])
        return dict(tool_contract_version="b04.tool.v0.1",protocol_version="b04.exec.v0.2",execution_mode=request["execution_mode"],
            **{k:copy.deepcopy(request[k]) for k in ["invocation_ref","operation_id","tool_binding_ref","tool_name","tool_version","input_snapshot_id","input_snapshot_sha256"]},
            status=status,result_code=code,payload=payload,output_refs=output_refs or [],changes=[],exit_code=exit_code,
            timing=dict(started_at=stamp(),finished_at=None if status=="in_progress" else stamp(),execution_duration_ms=None if status=="in_progress" else 0,cleanup_duration_ms=None if status=="in_progress" else 0),
            stop_status=stop,side_effects_state=effects,error=error,operation_record_ref=record["artifact_ref"])

    async def execute_tool(self,request,control):
        ref=request["invocation_ref"];self._auth(control,ref,"execute")
        self._report_contexts[canonical(ref)]=control.report_context or control.context
        key=self._key(request)
        if key in self.stop_receipts or control.cancel_signal is not None and control.cancel_signal.is_set():
            raise RunnerError("EXEC_LEASE_INVALID",stage="test_operation_already_stopped")
        old=next((r for r in self.requests if self._key(r)==key),None)
        if old:
            if old!=request:raise RunnerError("EXEC_TOOL_ERROR",stage="test_operation_conflict")
            return copy.deepcopy(self.results[key])
        definition=self.bundle["tool_config"]["definitions"][request["tool_binding_ref"]]
        if not conforms(request["arguments"],self.bundle["schemas"][definition["input_schema_ref"]]):raise RunnerError("EXEC_TOOL_ERROR",stage="test_tool_parameters")
        row=self.store.get(ref,control.context)
        if len([r for r in self.requests if r["invocation_ref"]==ref])>=row["envelope"]["limits"]["max_tool_calls"]:raise RunnerError("EXEC_BUDGET_EXHAUSTED",stage="test_tool_budget")
        self.requests.append(copy.deepcopy(request));self.charged.add(key)
        handler=self.handlers.get(request["tool_binding_ref"])
        if handler:
            value=handler(request,control)
            result=await value if inspect.isawaitable(value) else value
        elif request["tool_name"]=="read_artifact":
            item=self.store.read_input(request["arguments"]["artifact_ref"],ref["project_id"],control.context)
            result=self.result(request,payload=dict(content=item["body"].decode("utf-8")))
        elif request["tool_name"]=="write_file":
            args=request["arguments"]
            if self.workspace is None or not scoped_path(args["path"],control.context["write_scope"]["workspace_paths"]):raise RunnerError("EXEC_WRITE_SCOPE",stage="test_file_target")
            target=(self.workspace/args["path"]).resolve()
            if not target.is_relative_to(self.workspace):raise RunnerError("EXEC_WRITE_SCOPE",stage="test_symlink")
            body=self.store.read_object(args["content_ref"],control.context)["body"]
            if sha_bytes(body)!=args["expected_content_sha256"]:raise RunnerError("EXEC_TOOL_ERROR",stage="test_content_hash")
            if args["mode"]=="create" and target.exists():raise RunnerError("EXEC_TOOL_ERROR",stage="test_file_conflict")
            if args["mode"]=="replace" and (not target.is_file() or sha_bytes(target.read_bytes())!=args["expected_target_sha256"]):raise RunnerError("EXEC_TOOL_ERROR",stage="test_file_precondition")
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
            result=self.result(request,payload=dict(path=args["path"],sha256=sha_bytes(target.read_bytes())),effects="verified")
            result["changes"]=[dict(path=args["path"],change_type="created",before_sha256=None,after_sha256=sha_bytes(body))]
        else:
            args=request["arguments"];outcome=self.check_outcomes.get(args["check_ref"],"passed")
            report=dict(check_ref=args["check_ref"],invocation_ref=ref,input_snapshot_id=request["input_snapshot_id"],input_snapshot_sha256=request["input_snapshot_sha256"],
                execution_mode=request["execution_mode"],subjects=args["subjects"],environment_ref=args["environment_ref"],expected=args["expected"],result=outcome,actual="Deterministic check fixture: "+outcome)
            evidence=self.store.put_object(ref,"tool-check-report:"+request["operation_id"],"check_evidence",canonical(report).encode(),self._report_contexts[canonical(ref)])
            result=self.result(request,payload=dict(report_ref=evidence["artifact_ref"],check_ref=args["check_ref"],check_outcome=outcome),output_refs=[evidence["artifact_ref"]],exit_code=0 if outcome=="passed" else 1)
        self.results[key]=copy.deepcopy(result)
        return result

    async def get_operation(self,operation_ref,control):
        self._auth(control,operation_ref["invocation_ref"],"observe");self.query_count+=1
        key=self._key(operation_ref);result=self.results.get(key)
        return dict(operation_ref=copy.deepcopy(operation_ref),state="running" if result and result["status"]=="in_progress" else "finished" if result else "unknown",
                    result_ref=result["operation_record_ref"]+":result" if result and result["status"]!="in_progress" else None)

    async def read_result(self,operation_ref,result_ref,control):
        self._auth(control,operation_ref["invocation_ref"],"observe")
        result=self.results[self._key(operation_ref)]
        if result_ref!=result["operation_record_ref"]+":result":raise RunnerError("EXEC_TOOL_ERROR",stage="test_tool_result_ref")
        return copy.deepcopy(result)

    async def stop_operation(self,operation_ref,reason,control):
        self._auth(control,operation_ref["invocation_ref"],"cleanup");self.stop_count+=1
        receipt=dict(operation_ref=copy.deepcopy(operation_ref),stop_status="confirmed" if self.confirm_stop else "unknown",
                     evidence_refs=["test-tool-stop:"+self._key(operation_ref)] if self.confirm_stop else [])
        self.stop_receipts[self._key(operation_ref)]=receipt
        return receipt


def build_demo_runtime(*,project="demo-product",root=None,workspace=None,auto_start=True,checks=True,max_model_calls=4,max_tool_calls=10,execution_timeout=10,model_timeout=2,tool_timeout=1,transport_limit=100,response=None,setup=None):
    """Creates isolated fake services and a real ModelAdapterFacade/SQLite runner."""
    authority=InMemoryAuthority();catalog=InMemoryFrozenCatalog();control_provider=RegisteredControlProvider()
    model_budget=InMemoryBudget();resolver=InMemoryConfigResolver();registry=ProviderDriverRegistry();transport=LocalTransportBudget()
    root=Path(root) if root else None
    if root:root.mkdir(parents=True,exist_ok=True)
    store=SQLiteRunnerStore(root/"runner.sqlite3" if root else ":memory:",authority=authority)
    model_ledger=SQLiteCallLedger(root/"model.sqlite3" if root else ":memory:")
    namespace=project+"/candidates"
    envelope=dict(protocol_version="b04.exec.v0.2",execution_mode="mock",project_id=project,run_id="demo-run",invocation_id="plan-invocation",task_id=None,attempt_id=1,dispatch_id="dispatch-1",
        idempotency_key=project+":demo-run:plan-invocation:1",retry_count=0,retry_budget=2,revalidation_id=None,
        workflow_definition_ref="workflow:generic@1",invocation_kind="plan",agent_definition_ref="agent:planner@1",model_config_ref="model:mock@1",goal="Create the current product's candidate plan",
        input_contract_ref="contract:input@1",output_contract_ref="contract:output@1",input_snapshot_id="snapshot:1",input_snapshot_sha256="",
        inputs=[dict(artifact_ref="spec:"+project+"@1",kind="design_spec"),dict(artifact_ref="catalog:"+project+"@1",kind="capability_catalog")],spec_ref="spec:"+project+"@1",plan_ref=None,
        lease_ref="lease:1",tool_config_ref="tools:generic@1",write_scope=dict(workspace_paths=["src"],artifact_namespaces=[namespace]),workspace_ref="workspace:1" if workspace else None,source_control=None,
        limits=dict(execution_timeout_seconds=execution_timeout,model_call_timeout_seconds=model_timeout,max_model_calls=max_model_calls,max_total_tokens=200000,max_tool_calls=max_tool_calls),escalation_target="B01")
    input_refs=[]
    for inp in envelope["inputs"]:
        body=canonical(dict(product=project,requirements=["Parse configured input"]) if inp["kind"]=="design_spec" else dict(available_roles=["planner","designer"])).encode()
        meta=store.register_input(project,inp["artifact_ref"],inp["kind"],body)
        input_refs.append({k:meta[k] for k in ["artifact_ref","kind","sha256","state"]})
    plan_schema=dict(type="object",properties={"tasks":dict(type="array",items={"type":"object"})},required=["tasks"],additionalProperties=False)
    read_schema=dict(type="object",properties={"artifact_ref":{"type":"string"}},required=["artifact_ref"],additionalProperties=False)
    write_properties=dict(path={"type":"string"},mode={"enum":["create","replace"]},content={"type":"string"},encoding={"const":"utf-8"},expected_target_sha256={"type":["string","null"]})
    write_schema=dict(type="object",properties=write_properties,required=list(write_properties),additionalProperties=False)
    executor_properties={k:v for k,v in write_properties.items() if k!="content"};executor_properties.update(content_ref={"type":"string"},expected_content_sha256={"type":"string"})
    write_exec=dict(type="object",properties=executor_properties,required=list(executor_properties),additionalProperties=False)
    check_props=dict(check_ref={"type":"string"},subjects={"type":"array"},environment_ref={"type":"string"},expected={"type":"string"})
    check_schema=dict(type="object",properties=check_props,required=list(check_props),additionalProperties=False)
    schemas={"schema:plan@1":plan_schema,"schema:read@1":read_schema,"schema:write-model@1":write_schema,"schema:write-executor@1":write_exec,"schema:check@1":check_schema,"schema:tool-output@1":{"type":"object"}}
    bindings=[];definitions={}
    for name,model_schema,executor_schema,permissions,normalizer in [("read_artifact","schema:read@1","schema:read@1",["artifact_read"],None),("write_file","schema:write-model@1","schema:write-executor@1",["file_write"],"normalizer:inline-text-to-draft@1"),("run_check","schema:check@1","schema:check@1",["check_execute"],None)]:
        binding=dict(binding_ref="binding:"+name+"@1",model_tool_name=name,tool_name=name,tool_version="1",driver_ref="test-tool:"+name+"@1",model_input_schema_ref=model_schema,executor_input_schema_ref=executor_schema,
            normalization_profile_ref=normalizer,command_profile_refs=[],model_input_schema_sha256=digest(schemas[model_schema]),executor_input_schema_sha256=digest(schemas[executor_schema]))
        bindings.append(binding);definitions[binding["binding_ref"]]=dict(tool_name=name,tool_version="1",input_schema_ref=executor_schema,output_schema_ref="schema:tool-output@1",description="Registered "+name,permission_classes=permissions)
    bundle=dict(agent=dict(agent_definition_ref=envelope["agent_definition_ref"],input_contract_ref=envelope["input_contract_ref"],output_contract_ref=envelope["output_contract_ref"],prompt_template_ref="prompt:planner@1",model_policy_ref="policy:mock@1",capability_refs=["capability:planning@1"]),
        workflow=dict(workflow_definition_ref=envelope["workflow_definition_ref"],allowed_invocation_kinds=["plan","review","implement","test","custom"]),
        input_contract=dict(input_contract_ref=envelope["input_contract_ref"],requires_task=False,requires_plan=False,required_kinds=["design_spec","capability_catalog"],allowed_states_by_kind={"design_spec":["accepted"],"capability_catalog":["accepted"]}),
        output_contract=dict(output_contract_ref=envelope["output_contract_ref"],response_spec=dict(mode="json_schema",schema_ref="schema:plan@1",enforcement="local_validation"),
            slots=[dict(name="plan",kind="task_plan",media_type="application/json",schema_ref="schema:plan@1",namespace=namespace,source=dict(type="model_json",pointer=""))],
            required_checks=[dict(check_ref="check:quality@1",binding_ref="binding:run_check@1",slots=["plan"],arguments={},expected="Declared professional rule holds",environment_ref="environment:test@1")] if checks else []),
        template=dict(prompt_template_ref="prompt:planner@1",component_refs=["prompt:common@1","prompt:planner-fragment@1"],variables=list(VARIABLES),common_prefix="Respect {{invocation_context}} and {{limits}}.",professional_fragment="Plan from {{spec_context}} using {{capability_catalog}} and {{output_contract}}."),
        tool_config=dict(tool_config_ref=envelope["tool_config_ref"],tool_binding_set_ref="tool-set:generic@1",bindings=bindings,definitions=definitions,model_binding_refs=["binding:read_artifact@1","binding:write_file@1"]),
        schemas=schemas,input_refs=input_refs,profile=dict(max_context_bytes=128000,max_output_tokens=2000,max_output_corrections=0,max_refreezes=1,tool_timeout_seconds=tool_timeout,parameters={"temperature":0},tool_choice="auto",environment_ref="environment:test@1"))
    config=dict(model_config_ref="model:mock@1",provider="mock",model_id="mock-runner",driver_ref="driver:mock@1",model_capability_ref="capability:mock@1",endpoint_ref=None,credential_ref=None,generation_defaults={"temperature":0.2},provider_options={},transport_policy_ref="transport:single-send@1")
    policy=dict(model_policy_ref="policy:mock@1",allowed_model_config_refs=["model:mock@1"],allowed_parameter_overrides=["temperature"],allow_local_validation=True,strict_token_budget=True)
    caps=mock_capabilities("capability:mock@1")
    driver=MockDriver(response if response is not None else MockDriver.final('{"tasks":[{"id":"parse"}]}'))
    registry.register("driver:mock@1",driver);resolver.register_model(config,policy,caps)
    tools=ScriptedToolExecutor(store=store,authority=authority,bundle=bundle,workspace=workspace);sink=RecordingEventSink()
    model=ModelAdapterFacade(resolver=resolver,registry=registry,ledger=model_ledger,budget=model_budget,authority=authority)
    runner=AgentRunner(store=store,catalog=catalog,controls=control_provider,authority=authority,model_adapter=ModelAdapterBridge(model),tool_executor=tools,event_sink=sink,control_budget=model_budget,transport_budget=transport,auto_start=auto_start)
    runtime=SimpleNamespace(runner=runner,envelope=envelope,bundle=bundle,store=store,catalog=catalog,controls_provider=control_provider,authority=authority,
        model=model,model_ledger=model_ledger,model_budget=model_budget,resolver=resolver,registry=registry,driver=driver,tools=tools,sink=sink,transport=transport,config=config,policy=policy,caps=caps,transport_limit=transport_limit)
    if setup:setup(runtime)
    configure_runtime(runtime)
    return runtime


def configure_runtime(runtime,*,generation=1):
    """Trusted fixture setup, used before admission or with a new recovery grant."""
    r=runtime;e=r.envelope;bundle=r.bundle;ref=invocation_ref(e)
    r.store.register_read_scope(ref,"read-scope:demo",[i["artifact_ref"] for i in e["inputs"]]+bundle["tool_config"].get("allowed_additional_read_refs",[]))
    if hasattr(r,"issued_controls") and generation>r.issued_controls.model.context["control_generation"]:
        for control in [r.issued_controls.model,r.issued_controls.tool]:r.authority.revoke(control.context["context_ref"])
    e["input_snapshot_sha256"]=r.catalog.register(e["input_snapshot_id"],e,bundle)
    for schema_ref,schema in bundle["schemas"].items():r.resolver.register_schema(schema_ref,schema)
    binding={k:e[k] for k in ["model_config_ref","agent_definition_ref","input_snapshot_id","input_snapshot_sha256","execution_mode"]}
    binding.update(model_policy_ref=bundle["agent"]["model_policy_ref"],prompt_template_ref=bundle["template"]["prompt_template_ref"],tool_binding_set_ref=bundle["tool_config"]["tool_binding_set_ref"],tool_bindings=bundle["tool_config"]["bindings"],schema_refs=list(bundle["schemas"]))
    r.resolver.bind(ref,binding)
    expires=stamp(utc_now()+timedelta(minutes=5))
    if not hasattr(r,"issued_controls"):
        for ticket_ref,scope,purpose,parent,limits in [("budget:model-parent","invocation","model_send",None,dict(max_model_calls=e["limits"]["max_model_calls"],max_total_tokens=e["limits"]["max_total_tokens"])),
            ("budget:model-child","attempt","model_send","budget:model-parent",dict(max_model_calls=e["limits"]["max_model_calls"],max_total_tokens=e["limits"]["max_total_tokens"])),
            ("budget:control","invocation","control",None,dict(max_control_actions=5000))]:
            r.model_budget.register(dict(ticket_ref=ticket_ref,ledger_ref="budget-ledger:demo",invocation_ref=ref,scope=scope,purpose=purpose,parent_ticket_ref=parent,limits=limits,
                reserved=dict.fromkeys(limits,0),consumed=dict.fromkeys(limits,0),unsettled=dict.fromkeys(limits,0),expires_at=expires,state="active"))
        r.transport.register("budget:transport",ref,r.transport_limit,expires)
    contexts={}
    for name,purpose in [("model","execute"),("tool","execute"),("observe","observe"),("report","report"),("cleanup","cleanup")]:
        context=dict(control_contract_version="b04.control.v0.1",context_ref="context:"+name+":"+str(generation),subject_ref="service:runner",invocation_ref=ref,input_snapshot_id=e["input_snapshot_id"],input_snapshot_sha256=e["input_snapshot_sha256"],purpose=purpose,
            execute_grant_ref=None,lease_ref=e["lease_ref"],observe_grant_ref=None,report_grant_ref=None,cleanup_grant_ref=None,control_generation=generation,
            read_scope_ref="read-scope:demo" if purpose=="execute" else None,write_scope=copy.deepcopy(e["write_scope"]) if purpose=="execute" else None,
            tool_binding_set_ref=bundle["tool_config"]["tool_binding_set_ref"] if purpose=="execute" else None,draft_namespace_ref=e["project_id"]+"/drafts" if purpose=="execute" else None,
            budget_ticket_ref="budget:model-child" if name=="model" else "budget:tool-child" if name=="tool" else "budget:control",deadline_at=expires,cancel_signal_ref=None)
        context[purpose+"_grant_ref"]="grant:"+name+":"+str(generation)
        r.authority.register(context);contexts[name]=context
    controls={name:CallControl(c,control_budget_ticket_ref="budget:control",cleanup_context=contexts["cleanup"],report_context=contexts["report"]) for name,c in contexts.items()}
    r.issued_controls=RunnerControls(**controls,transport_ticket_ref="budget:transport")
    r.controls_provider.register(ref,r.issued_controls)

