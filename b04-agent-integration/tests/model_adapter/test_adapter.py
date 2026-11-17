from __future__ import annotations

import asyncio
import copy
import json
from datetime import timedelta

import pytest

from b04.model_adapter import CallControl, MockDriver, ModelAdapterError, ProviderFailure, to_exec_error
from b04.model_adapter.contracts import digest, invocation_ref, model_call_ref, stamp, utc_now
from b04.model_adapter.schemas import RESULT_SCHEMA, validate
from conftest import add_tool, structured


def run(awaitable):
    return asyncio.run(awaitable)


def generate(system, request=None):
    result=run(system.adapter.generate(system.request if request is None else request, system.control))
    validate(result, RESULT_SCHEMA)
    return result


def test_text_contract_and_pm_null_task(system):
    result=generate(system)
    assert result["status"]=="ok"
    assert result["task_id"] is None
    assert result["response"]["text"]=="mock response"
    assert result["selected_model"]["model_config_ref"]==system.config["model_config_ref"]
    assert result["call_record_ref"] and result["raw_response_ref"]
    assert "event_id" not in result
    assert system.driver.send_count==1


def test_describe_is_sanitized_and_preflight_does_not_reserve(system):
    description=run(system.adapter.describe_model(system.config["model_config_ref"], system.control))
    validation=run(system.adapter.validate_request(system.request, system.control))
    assert validation["valid"] and len(validation["request_fingerprint"])==64
    assert "credential_ref" not in description and "endpoint_ref" not in description
    assert system.driver.send_count==0
    assert system.budget.snapshot(system.request["budget_ticket_ref"])["reserved"]["max_model_calls"]==0


@pytest.mark.parametrize("mode,text,expected",[("json_object",'{"ok": true}',{"ok":True}),("json_schema",'{"tasks": []}',{"tasks":[]})])
def test_structured_output(system,mode,text,expected):
    structured(system,mode)
    system.driver.response=MockDriver.final(text)
    result=generate(system)
    assert result["status"]=="ok" and result["response"]["json_value"]==expected
    assert result["response"]["text"]==text


@pytest.mark.parametrize("text",['```json\n{"tasks": []}\n```','{"tasks":','{"tasks": [], "tasks": []}','{"tasks": NaN}','{"tasks": [], "extra": 1}','[]','{"tasks": 1e999}'])
def test_structured_output_is_never_repaired(system,text):
    structured(system)
    system.driver.response=MockDriver.final(text)
    result=generate(system)
    assert result["status"]=="error" and result["error"]["code"]=="MODEL_OUTPUT_FORMAT"
    assert result["response"] is None and result["raw_response_ref"]
    assert result["error"]["request_delivery"]=="sent"
    assert system.driver.send_count==1


def test_business_dependency_cycle_is_not_adapter_failure(system):
    structured(system)
    system.driver.response=MockDriver.final('{"tasks": [{"id": "A", "depends_on": ["B"]}, {"id": "B", "depends_on": ["A"]}]}')
    assert generate(system)["status"]=="ok"


@pytest.mark.parametrize("reason,code",[("length","MODEL_OUTPUT_TRUNCATED"),("refusal","MODEL_REFUSED"),("content_filter","MODEL_CONTENT_FILTERED"),("unrecognized","MODEL_RESPONSE_MALFORMED")])
def test_finish_reasons(system,reason,code):
    system.driver.response=MockDriver.final('{"tasks": []}',finish_reason=reason)
    result=generate(system)
    assert result["error"]["code"]==code and result["response"] is None


@pytest.mark.parametrize("text",["", "   ", None])
def test_empty_response(system,text):
    system.driver.response=MockDriver.final(text)
    assert generate(system)["error"]["code"]=="MODEL_EMPTY_RESPONSE"


def test_duplicate_returns_original_result_without_new_send_or_cost(system):
    first=generate(system)
    before=system.budget.snapshot(system.request["budget_ticket_ref"])
    second=generate(system)
    assert first==second and system.driver.send_count==1
    assert before==system.budget.snapshot(system.request["budget_ticket_ref"])


def test_different_content_same_call_is_conflict_and_preserves_original(system):
    original=generate(system)
    changed=copy.deepcopy(system.request)
    changed["messages"][-1]["content"][0]["text"]="A changed product"
    result=generate(system,changed)
    assert result["error"]["code"]=="MODEL_CALL_CONFLICT"
    assert system.ledger.get(system.ref)["result"]==original
    assert system.driver.send_count==1


def test_request_fingerprint_ignores_elapsed_time_and_remaining_budget(system):
    a=run(system.adapter.validate_request(system.request,system.control))
    b=run(system.adapter.validate_request(system.request,system.control))
    assert a["request_fingerprint"]==b["request_fingerprint"]


def test_same_seq_with_new_id_rejected(system):
    generate(system)
    changed=copy.deepcopy(system.request);changed["model_call_id"]="other"
    result=generate(system,changed)
    assert result["error"]["code"]=="MODEL_CALL_CONFLICT" and system.driver.send_count==1


@pytest.mark.parametrize("change,code",[
    (lambda r:r["parameters"].update(temperature=3),"MODEL_CAPABILITY_UNSUPPORTED"),
    (lambda r:r["parameters"].update(temperature=None),"MODEL_CAPABILITY_UNSUPPORTED"),
    (lambda r:r["parameters"].update(stream=True),"MODEL_CAPABILITY_UNSUPPORTED"),
    (lambda r:r.update(model_config_ref="model:unauthorized@1"),"MODEL_CONFIG_INVALID"),
    (lambda r:r.update(prompt_template_ref="prompt:changed@1"),"MODEL_CONFIG_INVALID"),
    (lambda r:r.update(input_snapshot_sha256="b"*64),"MODEL_CONTROL_INVALID"),
    (lambda r:r.update(automatic_fallback=True),"MODEL_REQUEST_INVALID"),
    (lambda r:r["response_spec"].update(mode="json_schema"),"MODEL_REQUEST_INVALID"),
    (lambda r:r["messages"][0]["content"][0].update(type="image"),"MODEL_REQUEST_INVALID"),
])
def test_invalid_requests_never_send(system,change,code):
    change(system.request)
    result=generate(system)
    assert result["status"]=="error" and result["error"]["code"]==code
    assert result["error"]["request_delivery"]=="not_sent" and system.driver.send_count==0
    assert result["error"]["stop_status"]=="confirmed"
    assert to_exec_error(result["error"],system.ref)["code"]!="EXEC_INVALID_ENVELOPE"


def test_zero_parameter_is_not_replaced_by_default(system):
    system.request["parameters"]={"temperature":0,"seed":0}
    assert generate(system)["status"]=="ok"
    assert system.driver.requests[0]["parameters"]=={"temperature":0,"seed":0}


@pytest.mark.parametrize("field,value",[("attempt_id",True),("call_seq",0),("input_snapshot_sha256","<sha256>"),("task_id",4)])
def test_unrepresentable_identity_raises_typed_error_without_fake_ids(system,field,value):
    system.request[field]=value
    with pytest.raises(ModelAdapterError) as caught:
        run(system.adapter.generate(system.request,system.control))
    assert caught.value.code=="MODEL_REQUEST_INVALID" and system.driver.send_count==0


def test_missing_message_is_runtime_model_error(system):
    del system.request["messages"]
    result=generate(system)
    error=to_exec_error(result["error"],system.ref)
    assert error["code"]=="EXEC_MODEL_ERROR"
    assert error["cause_ref"]=={"layer":"model","ref":system.ref}


@pytest.mark.parametrize("code,delivery,stop,expected",[
    ("MODEL_RATE_LIMITED","not_sent","confirmed","error"),
    ("MODEL_AUTH_FAILED","not_sent","confirmed","error"),
    ("MODEL_PROVIDER_UNAVAILABLE","sent","confirmed","error"),
    ("MODEL_NETWORK_UNCERTAIN","unknown","unknown","unknown"),
])
def test_provider_failures_are_classified_without_retry(system,code,delivery,stop,expected):
    def fail(_):
        raise ProviderFailure(code,delivery=delivery,stop_status=stop,retry_after_seconds=2)
    system.driver.handler=fail
    result=generate(system)
    assert result["status"]==expected and result["error"]["code"]==code
    assert result["error"]["retry_after_seconds"]==2 and system.driver.send_count==1
    assert generate(system)==result and system.driver.send_count==1


def test_unexpected_provider_exception_is_sanitized_and_uncertain(system):
    def fail(_):
        raise RuntimeError("Authorization: Bearer very-sensitive-secret")
    system.driver.handler=fail
    result=generate(system)
    assert result["status"]=="unknown" and result["error"]["code"]=="MODEL_INTERNAL_ERROR"
    assert "very-sensitive-secret" not in json.dumps(result)


def test_inflight_duplicate_is_fixed_model_result(system):
    async def scenario():
        entered,release=asyncio.Event(),asyncio.Event()
        async def handler(_):
            entered.set();await release.wait();return MockDriver.final("done")
        system.driver.handler=handler
        first=asyncio.create_task(system.adapter.generate(system.request,system.control))
        await entered.wait()
        duplicate=await system.adapter.generate(system.request,system.control)
        assert duplicate["status"]=="in_progress"
        assert duplicate["response"] is None and duplicate["error"] is None
        assert duplicate["timing"]["finished_at"] is None and duplicate["timing"]["duration_ms"] is None
        validate(duplicate,RESULT_SCHEMA)
        snapshot=await system.adapter.get_call(system.ref,system.controls["observe"])
        assert snapshot["call_state"]=="sent" and snapshot["result_ref"] is None
        release.set()
        result=await first
        assert result["status"]=="ok" and system.driver.send_count==1
    run(scenario())


def test_budget_blocks_first_send(system_factory):
    system=system_factory(parent_calls=0)
    result=generate(system)
    assert result["error"]["code"]=="MODEL_BUDGET_EXHAUSTED" and system.driver.send_count==0


def test_known_not_sent_releases_reservation(system):
    def fail(_):raise ProviderFailure("MODEL_AUTH_FAILED")
    system.driver.handler=fail
    generate(system)
    ticket=system.budget.snapshot(system.request["budget_ticket_ref"])
    assert ticket["reserved"]["max_model_calls"]==ticket["consumed"]["max_model_calls"]==0


def test_unknown_delivery_retains_reserved_and_unsettled(system):
    def fail(_):raise ProviderFailure("MODEL_NETWORK_UNCERTAIN",delivery="unknown")
    system.driver.handler=fail
    generate(system)
    ticket=system.budget.snapshot("budget:parent")
    assert ticket["reserved"]["max_model_calls"]==ticket["unsettled"]["max_model_calls"]==1
    assert ticket["reserved"]["max_total_tokens"]==ticket["unsettled"]["max_total_tokens"]>0


def test_real_usage_is_settled_once(system):
    system.driver.response=MockDriver.final("done",usage=dict(input_tokens=3,output_tokens=2,total_tokens=5,source="mock_test_measurement",availability="observed"))
    result=generate(system)
    assert result["usage"]["total_tokens"]==5
    assert system.budget.snapshot("budget:parent")["consumed"]=={"max_model_calls":1,"max_total_tokens":5}
    generate(system)
    assert system.budget.snapshot("budget:parent")["consumed"]["max_total_tokens"]==5


def test_estimated_or_unavailable_tokens_do_not_become_zero(system):
    generate(system)
    ticket=system.budget.snapshot("budget:parent")
    assert ticket["consumed"]["max_model_calls"]==1
    assert ticket["reserved"]["max_total_tokens"]==ticket["unsettled"]["max_total_tokens"]>0


@pytest.mark.parametrize("field",["deadline_at","timeout_seconds"])
def test_timeout_keeps_remote_uncertainty(system,field):
    async def scenario():
        system.driver.confirm_cancel=False
        async def slow(_):await asyncio.sleep(10)
        system.driver.handler=slow
        if field=="deadline_at":system.request["call_limits"][field]=stamp(utc_now()+timedelta(milliseconds=30))
        else:system.request["call_limits"][field]=0.03
        result=await system.adapter.generate(system.request,system.control)
        assert result["status"]=="unknown" and result["error"]["code"]=="MODEL_TIMEOUT"
        assert result["error"]["stop_status"]=="unknown" and result["response"] is None
        assert system.driver.send_count==system.driver.cancel_count==1
        assert (await system.adapter.generate(system.request,system.control))==result
    run(scenario())


def test_revoked_execution_still_allows_independent_observe_and_cleanup(system):
    result=generate(system)
    system.authority.invalidate_execution(invocation_ref(system.request))
    assert generate(system)["error"]["code"]=="MODEL_CONTROL_INVALID"
    snapshot=run(system.adapter.get_call(system.ref,system.controls["observe"]))
    stopped=run(system.adapter.cancel_call(system.ref,"stop requested",system.controls["cleanup"]))
    assert snapshot["call_state"]=="response_recorded" and stopped["stop_status"]=="confirmed"
    assert system.ledger.get(system.ref)["result"]==result


def test_context_cannot_self_authorize_by_changing_purpose(system):
    changed=copy.deepcopy(system.control.context);changed["purpose"]="observe";changed["observe_grant_ref"]="grant:observe"
    with pytest.raises(ModelAdapterError) as caught:run(system.adapter.get_call(system.ref,CallControl(changed)))
    assert caught.value.code=="MODEL_CONTROL_INVALID"


def test_foreign_invocation_cannot_query_or_cancel(system):
    foreign=copy.deepcopy(system.ref);foreign["invocation_ref"]["project_id"]="other-project"
    for operation in [system.adapter.get_call(foreign,system.controls["observe"]),system.adapter.cancel_call(foreign,"stop",system.controls["cleanup"])]:
        with pytest.raises(ModelAdapterError):run(operation)


def test_explicit_cancellation_uses_confirmed_driver_evidence(system):
    async def scenario():
        entered=asyncio.Event()
        async def slow(_):entered.set();await asyncio.sleep(10)
        system.driver.handler=slow
        pending=asyncio.create_task(system.adapter.generate(system.request,system.control))
        await entered.wait()
        receipt=await system.adapter.cancel_call(system.ref,"cancel requested",system.controls["cleanup"])
        result=await pending
        assert receipt["stop_status"]=="confirmed" and result["status"]=="cancelled"
        assert result["error"]["stop_status"]=="confirmed" and system.driver.send_count==1
    run(scenario())


def test_model_switch_requires_new_frozen_attempt(system_factory):
    a,b=system_factory(model="model-a"),system_factory(model="model-b",attempt=2)
    result_a,result_b=generate(a),generate(b)
    assert result_a["selected_model"]["model_id"]=="model-a"
    assert result_b["selected_model"]["model_id"]=="model-b"
    changed=a.next_request();changed["model_config_ref"]=b.request["model_config_ref"]
    assert generate(a,changed)["error"]["code"]=="MODEL_CONFIG_INVALID"
    assert a.driver.send_count==b.driver.send_count==1


def test_missing_call_is_unknown_without_sending(system):
    snapshot=run(system.adapter.get_call(system.ref,system.controls["observe"]))
    assert snapshot["call_state"]=="unknown" and snapshot["result_ref"] is None and system.driver.send_count==0


def test_output_schema_cannot_fetch_external_resources(system):
    system.resolver.register_schema("schema:remote@1",{"$ref":"https://not-accessed.invalid/schema"})
    # Modify only the trusted fixture before its first invocation.
    system.resolver._bindings[next(iter(system.resolver._bindings))]["schema_refs"].append("schema:remote@1")
    structured(system);system.request["response_spec"]["schema_ref"]="schema:remote@1"
    assert generate(system)["error"]["code"]=="MODEL_CAPABILITY_UNSUPPORTED"
    assert system.driver.send_count==0


def test_control_budget_is_separate_and_bounded(system_factory):
    system=system_factory(controls=1)
    assert run(system.adapter.validate_request(system.request,system.control))["valid"]
    with pytest.raises(ModelAdapterError) as caught:run(system.adapter.describe_model(system.request["model_config_ref"],system.control))
    assert caught.value.code=="MODEL_BUDGET_EXHAUSTED" and system.driver.send_count==0


def test_exec_mapping_preserves_cause_and_retry_advice(system):
    raw=ProviderFailure("MODEL_TIMEOUT",delivery="unknown",retry_after_seconds=1.5).to_dict(["evidence:1"])
    error=to_exec_error(raw,system.ref,policy_retry_allowed=True)
    assert error["code"]=="EXEC_TIMEOUT" and error["recoverability"]=="requires_reconciliation"
    assert error["details"]["model"]["retry_after_seconds"]==1.5
    assert error["cause_ref"]["ref"]==system.ref and error["operation_ref"] is None

