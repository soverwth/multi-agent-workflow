import asyncio
import copy
import json

import pytest

from b04.model_adapter import MockDriver, TokenEstimate
from b04.model_adapter.contracts import digest, invocation_ref
from conftest import add_tool, structured
from test_adapter import generate, run


def test_tool_intent_has_frozen_binding_and_is_not_executed(system):
    add_tool(system);structured(system)
    system.driver.response=MockDriver.tool_calls([dict(name="read_artifact",arguments='{"artifact_ref":"spec:product@1"}',provider_tool_call_id="provider-tool-1")],text="Need more context")
    result=generate(system)
    assert result["status"]=="ok" and result["response"]["kind"]=="tool_calls"
    intent=result["response"]["tool_calls"][0]
    assert intent["tool_call_id"]=="call-1:tool:1" and intent["binding_ref"]=="binding:read@1"
    assert intent["provider_tool_call_id"]=="provider-tool-1" and intent["tool_call_id_source"]=="adapter"
    assert system.driver.send_count==1 and not result["response"].get("final")


@pytest.mark.parametrize("name,args",[("unregistered",{}),("read_artifact",{}),("read_artifact",'{"artifact_ref":'),("read_artifact",'{"artifact_ref":"a","artifact_ref":"b"}'),("read_artifact",["not-object"])])
def test_bad_tool_intent_is_not_executable(system,name,args):
    add_tool(system)
    system.driver.response=MockDriver.tool_calls([dict(name=name,arguments=args)])
    result=generate(system)
    assert result["error"]["code"]=="MODEL_TOOL_CALL_INVALID" and result["response"] is None
    assert system.driver.send_count==1


@pytest.mark.parametrize("mutation,expected",[
    (lambda r:r["tools"][0].update(binding_ref="binding:forged@1"),"MODEL_CONTROL_INVALID"),
    (lambda r:r["tools"].append(copy.deepcopy(r["tools"][0])),"MODEL_REQUEST_INVALID"),
    (lambda r:r["tools"][0]["input_schema"].update(additionalProperties=True),"MODEL_CONFIG_INVALID"),
])
def test_tool_binding_and_schema_cannot_drift(system,mutation,expected):
    add_tool(system);mutation(system.request)
    assert generate(system)["error"]["code"]==expected and system.driver.send_count==0


def completed_feedback(system,intent):
    return dict(feedback_contract_version="b04.tool-feedback.v0.1",invocation_ref=invocation_ref(system.request),
        input_snapshot_id=system.request["input_snapshot_id"],input_snapshot_sha256=system.request["input_snapshot_sha256"],execution_mode="mock",
        model_call_id=system.request["model_call_id"],tool_call_id=intent["tool_call_id"],operation_id="operation:read@1",tool_binding_ref=intent["binding_ref"],
        status="completed",result_code="TOOL_COMPLETED",payload={"check_outcome":"failed","text":"Untrusted tool output"},exit_code=1,
        stop_status="confirmed",side_effects_state="none",error=None,output_refs=["artifact:output"],changes=[],operation_record_ref="operation-record:read@1",
        truncation=dict(fields=[],original_refs=[]))


def tool_history(system):
    add_tool(system)
    system.driver.response=MockDriver.tool_calls([dict(name="read_artifact",arguments={"artifact_ref":"spec:one@1"})])
    first=generate(system)
    intent=first["response"]["tool_calls"][0]
    feedback=completed_feedback(system,intent)
    next_request=system.next_request()
    next_request["messages"] += [dict(role="assistant",content=[],tool_calls=[intent]),dict(role="tool",tool_call_id=intent["tool_call_id"],content=[dict(type="text",text=json.dumps(feedback))])]
    system.driver.response=MockDriver.final("Final content")
    return next_request,feedback


def test_full_tool_feedback_and_new_model_call(system):
    request,feedback=tool_history(system)
    result=generate(system,request)
    assert result["status"]=="ok" and result["model_call_id"]=="call-1-next" and system.driver.send_count==2
    actual=json.loads(system.driver.requests[1]["messages"][-1]["content"][0]["text"])
    assert actual==feedback
    assert actual["exit_code"]==1 and actual["payload"]["check_outcome"]=="failed" and actual["error"] is None


@pytest.mark.parametrize("key,value",[("status","in_progress"),("status","unknown"),("status","invented"),("stop_status","pending"),("model_call_id","wrong-model-call"),("tool_binding_ref","binding:forged"),("input_snapshot_sha256","b"*64)])
def test_incomplete_or_wrong_tool_feedback_prevents_new_send(system,key,value):
    request,feedback=tool_history(system)
    feedback[key]=value
    request["messages"][-1]["content"][0]["text"]=json.dumps(feedback)
    result=generate(system,request)
    assert result["error"]["code"]=="MODEL_REQUEST_INVALID" and system.driver.send_count==1


def test_payload_only_tool_feedback_is_rejected(system):
    request,feedback=tool_history(system)
    request["messages"][-1]["content"][0]["text"]=json.dumps(feedback["payload"])
    assert generate(system,request)["error"]["code"]=="MODEL_REQUEST_INVALID" and system.driver.send_count==1


def test_capability_combinations_fail_before_send(system):
    add_tool(system);structured(system)
    system.resolver._models[system.config["model_config_ref"]][2]["tools_with_structured_output"]=False
    assert generate(system)["error"]["code"]=="MODEL_CAPABILITY_UNSUPPORTED" and system.driver.send_count==0


def test_unknown_required_capability_is_rejected(system):
    del system.resolver._models[system.config["model_config_ref"]][2]["context_window_tokens"]
    assert generate(system)["error"]["code"]=="MODEL_CAPABILITY_UNSUPPORTED" and system.driver.send_count==0


def test_provider_enforcement_cannot_silently_downgrade(system):
    structured(system,enforcement="provider_required")
    system.resolver._models[system.config["model_config_ref"]][2]["provider_structured_output_modes"]=[]
    assert generate(system)["error"]["code"]=="MODEL_CAPABILITY_UNSUPPORTED" and system.driver.send_count==0


def test_local_validation_requires_frozen_policy_approval(system):
    system.resolver._models[system.config["model_config_ref"]][1]["allow_local_validation"]=False
    structured(system)
    assert generate(system)["error"]["code"]=="MODEL_CAPABILITY_UNSUPPORTED" and system.driver.send_count==0


def test_context_capacity_includes_schema_and_tools(system):
    add_tool(system);structured(system)
    system.resolver._models[system.config["model_config_ref"]][2]["context_window_tokens"]=1001
    assert generate(system)["error"]["code"]=="MODEL_CONTEXT_LIMIT" and system.driver.send_count==0


def test_strict_budget_rejects_unbounded_token_estimate(system):
    system.driver.estimate_input_tokens=lambda _:TokenEstimate(10,False)
    assert generate(system)["error"]["code"]=="MODEL_CAPABILITY_UNSUPPORTED" and system.driver.send_count==0


@pytest.mark.parametrize("schema,expected",[
    ({"type":"object","format":"not-implemented"},"MODEL_CAPABILITY_UNSUPPORTED"),
    ({"$ref":"#/$defs/absent"},"MODEL_CONFIG_INVALID"),
    ({"$schema":"http://json-schema.org/draft-07/schema#","type":"object"},"MODEL_CAPABILITY_UNSUPPORTED"),
])
def test_unsupported_or_invalid_schema_is_rejected_before_send(system,schema,expected):
    system.resolver._schemas["schema:plan@1"]=schema
    structured(system)
    assert generate(system)["error"]["code"]==expected and system.driver.send_count==0


def test_local_schema_reference_works_offline(system):
    system.resolver._schemas["schema:plan@1"]={"$defs":{"Answer":{"type":"object","required":["ok"]}},"$ref":"#/$defs/Answer"}
    structured(system);system.driver.response=MockDriver.final('{"ok":true}')
    assert generate(system)["status"]=="ok"


def test_same_config_ref_mutation_between_calls_is_detected(system):
    assert generate(system)["status"]=="ok"
    system.resolver._models[system.config["model_config_ref"]][0]["generation_defaults"]["temperature"]=0.9
    assert generate(system,system.next_request())["error"]["code"]=="MODEL_CONFIG_INVALID" and system.driver.send_count==1


def test_versioned_config_and_schema_cannot_be_overwritten(system):
    changed=copy.deepcopy(system.config);changed["model_id"]="changed"
    with pytest.raises(ValueError):system.resolver.register_model(changed,system.policy,system.caps)
    with pytest.raises(ValueError):system.resolver.register_schema("schema:plan@1",{"type":"array"})


def test_live_mode_is_not_impersonated_by_mock_driver(system):
    system.request["execution_mode"]="live"
    assert generate(system)["error"]["code"]=="MODEL_CONFIG_INVALID" and system.driver.send_count==0

