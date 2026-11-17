"""Offline PM-planning example. Run after installing the package, or set PYTHONPATH=src."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta

from b04.model_adapter import (CallControl, InMemoryAuthority, InMemoryBudget, InMemoryConfigResolver, MockDriver,
                             ModelAdapterFacade, ProviderDriverRegistry, SQLiteCallLedger, mock_capabilities)
from b04.model_adapter.contracts import invocation_ref, model_call_ref, stamp, utc_now


def build_runtime(product_id="demo-cli-product"):
    resolver, authority, budget, registry = InMemoryConfigResolver(), InMemoryAuthority(), InMemoryBudget(), ProviderDriverRegistry()
    config = dict(model_config_ref="model:mock-planner@1",provider="mock",model_id="mock-planner",driver_ref="driver:mock@1",
                  model_capability_ref="model-capability:mock@1",endpoint_ref=None,credential_ref=None,
                  generation_defaults={"temperature":0.2},provider_options={},transport_policy_ref="transport:single-send@1")
    policy = dict(model_policy_ref="model-policy:planning@1",allowed_model_config_refs=[config["model_config_ref"]],
                  allowed_parameter_overrides=["temperature"],allow_local_validation=True,strict_token_budget=True)
    schema = {"type":"object","properties":{"tasks":{"type":"array","items":{"type":"object","properties":{"id":{"type":"string"},"goal":{"type":"string"}},"required":["id","goal"],"additionalProperties":False}}},"required":["tasks"],"additionalProperties":False}
    expires = stamp(utc_now()+timedelta(minutes=5))
    request = dict(adapter_contract_version="b04.model.v0.1",protocol_version="b04.exec.v0.2",execution_mode="mock",
        project_id=product_id,run_id="demo-run",invocation_id="pm-plan",task_id=None,attempt_id=1,dispatch_id="demo-dispatch",
        model_call_id="pm-model-call-1",call_seq=1,input_snapshot_id="demo-input-snapshot",input_snapshot_sha256="a"*64,
        agent_definition_ref="agent:pm@1",prompt_template_ref="prompt:pm@1",model_policy_ref=policy["model_policy_ref"],model_config_ref=config["model_config_ref"],
        messages=[{"role":"system","content":[{"type":"text","text":"Produce a candidate task plan for the supplied product specification."}]},
                  {"role":"user","content":[{"type":"text","text":"Design Spec: build a command-line CSV summary tool."}]}],
        response_spec=dict(mode="json_schema",schema_ref="schema:demo-plan@1",enforcement="local_validation"),tools=[],tool_choice="none",
        parameters={"temperature":0},call_limits=dict(timeout_seconds=2,deadline_at=expires,max_output_tokens=1000),budget_ticket_ref="budget:attempt")
    ref=invocation_ref(request)
    binding={k:request[k] for k in ["model_config_ref","model_policy_ref","agent_definition_ref","prompt_template_ref","input_snapshot_id","input_snapshot_sha256","execution_mode"]}
    binding.update(tool_binding_set_ref="tool-set:empty@1",tool_bindings=[],schema_refs=["schema:demo-plan@1"])
    resolver.register_model(config,policy,mock_capabilities())
    resolver.register_schema("schema:demo-plan@1",schema)
    resolver.bind(ref,binding)
    driver=MockDriver(MockDriver.final(json.dumps({"tasks":[{"id":"parse-csv","goal":"Parse and validate CSV input"},{"id":"summarize","goal":"Compute summary statistics"}]},ensure_ascii=False)))
    registry.register("driver:mock@1",driver)

    def register_ticket(ticket_ref,scope,purpose,parent,limits):
        budget.register(dict(ticket_ref=ticket_ref,ledger_ref="ledger:demo",invocation_ref=ref,scope=scope,purpose=purpose,parent_ticket_ref=parent,
                             limits=limits,reserved=dict.fromkeys(limits,0),consumed=dict.fromkeys(limits,0),unsettled=dict.fromkeys(limits,0),expires_at=expires,state="active"))
    register_ticket("budget:invocation","invocation","model_send",None,dict(max_model_calls=3,max_total_tokens=100000))
    register_ticket("budget:attempt","attempt","model_send","budget:invocation",dict(max_model_calls=3,max_total_tokens=100000))
    register_ticket("budget:control","invocation","control",None,dict(max_control_actions=30))
    contexts={}
    for purpose in ["execute","observe","report","cleanup"]:
        context=dict(control_contract_version="b04.control.v0.1",context_ref="context:"+purpose,subject_ref="service:demo-runner",invocation_ref=ref,
            input_snapshot_id=request["input_snapshot_id"],input_snapshot_sha256=request["input_snapshot_sha256"],purpose=purpose,
            execute_grant_ref=None,lease_ref="lease:demo",observe_grant_ref=None,report_grant_ref=None,cleanup_grant_ref=None,control_generation=1,
            read_scope_ref="read-scope:demo" if purpose=="execute" else None,
            write_scope={"workspace_paths":[],"artifact_namespaces":["candidate:demo"]} if purpose=="execute" else None,
            tool_binding_set_ref="tool-set:empty@1" if purpose=="execute" else None,draft_namespace_ref=None,
            budget_ticket_ref="budget:attempt" if purpose=="execute" else "budget:control",deadline_at=expires,cancel_signal_ref=None)
        context[purpose+"_grant_ref"]="grant:"+purpose
        authority.register(context)
        contexts[purpose]=context
    control=CallControl(contexts["execute"],control_budget_ticket_ref="budget:control",cleanup_context=contexts["cleanup"],report_context=contexts["report"])
    ledger=SQLiteCallLedger()
    adapter=ModelAdapterFacade(resolver=resolver,registry=registry,ledger=ledger,budget=budget,authority=authority)
    return adapter,request,control,contexts,ledger,driver


async def main():
    adapter,request,control,contexts,ledger,driver=build_runtime()
    try:
        validation=await adapter.validate_request(request,control)
        result=await adapter.generate(request,control)
        duplicate=await adapter.generate(request,control)
        snapshot=await adapter.get_call(model_call_ref(request),CallControl(contexts["observe"]))
        assert validation["valid"] and result["status"]=="ok" and duplicate==result and driver.send_count==1
        print(json.dumps(dict(validation=validation,result=result,duplicate_reused=duplicate==result,actual_sends=driver.send_count,snapshot=snapshot),ensure_ascii=False,indent=2))
    finally:
        ledger.close()


if __name__=="__main__":
    asyncio.run(main())

