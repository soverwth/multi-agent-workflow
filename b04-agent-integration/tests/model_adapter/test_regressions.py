import asyncio
import copy
import json
from dataclasses import replace

import pytest

from b04.model_adapter import CallControl, MappingCredentialResolver, MockDriver, ModelAdapterError, ProviderFailure, to_exec_error
from b04.model_adapter.contracts import invocation_ref, stamp, unavailable_usage, utc_now
from conftest import add_tool, structured
from test_adapter import generate, run


def test_unknown_terminal_can_be_reconciled_by_later_stop_evidence(system):
    def fail(_):raise ProviderFailure("MODEL_NETWORK_UNCERTAIN",delivery="unknown",stop_status="unknown")
    system.driver.handler=fail
    result=generate(system)
    receipt=run(system.adapter.cancel_call(system.ref,"reconcile stop",system.controls["cleanup"]))
    assert receipt["stop_status"]=="confirmed" and system.driver.cancel_count==1
    assert system.ledger.get(system.ref)["result"]==result  # Historical result is immutable.
    assert run(system.adapter.get_call(system.ref,system.controls["observe"]))["stop_status"]=="confirmed"


def test_format_failure_preserves_provider_request_id_and_usage(system):
    structured(system)
    raw=MockDriver.final('not JSON',usage=dict(input_tokens=3,output_tokens=2,total_tokens=5,source="fixture",availability="observed"))
    raw.update(provider_request_id="service-request-123",provider_finish_reason="normal-end")
    system.driver.response=raw
    result=generate(system)
    assert result["error"]["code"]=="MODEL_OUTPUT_FORMAT" and result["provider_request_id"]=="service-request-123"
    assert result["provider_finish_reason"]=="normal-end" and result["usage"]["total_tokens"]==5


def test_known_secret_in_error_usage_source_is_redacted(system):
    secret="long-provider-secret"
    system.resolver._models[system.config["model_config_ref"]][0]["credential_ref"]="credential:one"
    system.adapter.credentials=MappingCredentialResolver({"credential:one":secret})
    system.driver.response=MockDriver.final("safe text",usage=dict(input_tokens=None,output_tokens=None,total_tokens=None,source=secret,availability="unavailable"))
    result=generate(system)
    assert result["error"]["code"]=="MODEL_RESPONSE_MALFORMED" and secret not in json.dumps(result)


@pytest.mark.parametrize("reason",[[],{},123])
def test_malformed_finish_reason_is_response_error(system,reason):
    system.driver.response=MockDriver.final("text",finish_reason=reason)
    assert generate(system)["error"]["code"]=="MODEL_RESPONSE_MALFORMED"


def test_empty_schema_capability_is_not_interpreted_as_unlimited(system):
    structured(system)
    system.resolver._models[system.config["model_config_ref"]][2]["schema_keywords"]=[]
    assert generate(system)["error"]["code"]=="MODEL_CAPABILITY_UNSUPPORTED" and system.driver.send_count==0


def test_two_frozen_versions_need_different_public_aliases(system):
    add_tool(system)
    frozen=system.resolver._bindings[next(iter(system.resolver._bindings))]["tool_bindings"]
    alternate=copy.deepcopy(frozen[0]);alternate.update(binding_ref="binding:read-v2@1",tool_version="2")
    frozen.append(alternate)
    assert generate(system)["error"]["code"]=="MODEL_CONFIG_INVALID" and system.driver.send_count==0


def test_cleanup_has_independent_bounded_timeout(system):
    async def scenario():
        async def slow(_):await asyncio.sleep(10)
        async def slow_cancel(*_):await asyncio.sleep(10)
        system.driver.handler=slow;system.driver.cancel=slow_cancel
        system.adapter.cleanup_timeout_seconds=0.01
        system.request["call_limits"]["timeout_seconds"]=0.01
        result=await asyncio.wait_for(system.adapter.generate(system.request,system.control),0.5)
        assert result["status"]=="unknown" and result["error"]["stop_status"]=="unknown"
    run(scenario())


def test_caller_task_cancellation_still_records_stop_and_result(system):
    async def scenario():
        entered=asyncio.Event()
        async def slow(_):entered.set();await asyncio.sleep(10)
        system.driver.handler=slow
        task=asyncio.create_task(system.adapter.generate(system.request,system.control))
        await entered.wait();task.cancel()
        result=await task
        assert result["status"]=="cancelled" and system.driver.cancel_count==1
        assert system.ledger.get(system.ref)["result"]==result
    run(scenario())


def test_cancel_signal_before_send_releases_all_resources(system):
    async def scenario():
        signal=asyncio.Event();signal.set()
        control=replace(system.control,cancel_signal=signal)
        result=await system.adapter.generate(system.request,control)
        assert result["status"]=="cancelled" and system.driver.send_count==0
        assert system.budget.snapshot("budget:parent")["reserved"]["max_model_calls"]==0
    run(scenario())


def test_control_rechecked_after_atomic_reservation(system):
    reserve=system.budget.reserve
    def revoke_after_reserve(*args,**kwargs):
        reserve(*args,**kwargs)
        system.authority.invalidate_execution(invocation_ref(system.request))
    system.budget.reserve=revoke_after_reserve
    result=generate(system)
    assert result["error"]["code"]=="MODEL_CONTROL_INVALID" and system.driver.send_count==0
    assert system.budget.snapshot("budget:parent")["reserved"]["max_model_calls"]==0


def test_two_concurrent_stops_share_one_provider_cancel(system):
    async def scenario():
        entered=asyncio.Event()
        async def slow(_):entered.set();await asyncio.sleep(10)
        system.driver.handler=slow
        pending=asyncio.create_task(system.adapter.generate(system.request,system.control))
        await entered.wait()
        a,b=await asyncio.gather(*[system.adapter.cancel_call(system.ref,"stop",system.controls["cleanup"]) for _ in range(2)])
        assert a["stop_status"]==b["stop_status"]=="confirmed" and system.driver.cancel_count==1
        assert (await pending)["status"]=="cancelled"
    run(scenario())


def test_different_products_use_same_interface_and_driver(system_factory):
    a,b=system_factory(project="cli-product"),system_factory(project="inventory-product")
    result_a,result_b=generate(a),generate(b)
    assert result_a["project_id"]=="cli-product" and result_b["project_id"]=="inventory-product"
    assert result_a["status"]==result_b["status"]=="ok"


def test_registered_alternative_driver_normalizes_its_own_wire_format(system_factory):
    class AlternativeDriver(MockDriver):
        async def send_once(self,prepared,credential,timeout_seconds):
            self.send_count+=1
            return {"custom_provider_text":"converted by registered driver"}
        def normalize(self,raw):return MockDriver.final(raw["custom_provider_text"])
    system=system_factory(driver=AlternativeDriver(),model="alternate-driver")
    result=generate(system)
    assert result["response"]["text"]=="converted by registered driver" and system.driver.send_count==1


def test_bare_call_id_cannot_query(system):
    with pytest.raises(ModelAdapterError):run(system.adapter.get_call("call-1",system.controls["observe"]))


def test_unsafe_provider_error_metadata_is_rejected():
    with pytest.raises(ValueError):ProviderFailure("MODEL_RATE_LIMITED",retry_after_seconds=float("nan"))
    with pytest.raises(ValueError):ProviderFailure("MODEL_RATE_LIMITED",stage="Authorization: secret")


def test_cancelled_model_error_uses_runner_stop_flow(system):
    with pytest.raises(ValueError):to_exec_error(ModelAdapterError("MODEL_CANCELLED").to_dict(),system.ref)


@pytest.mark.parametrize("invalid",[[],None,{"messages": []}])
def test_preflight_handles_untyped_invalid_payloads_without_send(system,invalid):
    result=run(system.adapter.validate_request(invalid,system.control))
    assert result["valid"] is False and result["issues"][0]["code"]=="MODEL_REQUEST_INVALID" and system.driver.send_count==0


@pytest.mark.parametrize("value",[None,True,0])
def test_unknown_or_invalid_context_capacity_never_uses_a_guess(system,value):
    system.resolver._models[system.config["model_config_ref"]][2]["context_window_tokens"]=value
    assert generate(system)["error"]["code"]=="MODEL_CAPABILITY_UNSUPPORTED" and system.driver.send_count==0


def test_parameter_schema_cannot_trigger_remote_resolution(system):
    system.resolver._models[system.config["model_config_ref"]][2]["supported_parameters"]["temperature"]={"$ref":"https://not-accessed.invalid/schema"}
    assert generate(system)["error"]["code"]=="MODEL_CAPABILITY_UNSUPPORTED" and system.driver.send_count==0


def test_observed_usage_exceeding_reserved_bound_is_not_accepted(system):
    system.driver.response=MockDriver.final("text",usage=dict(input_tokens=99999,output_tokens=1,total_tokens=100000,source="fixture",availability="observed"))
    result=generate(system)
    assert result["error"]["code"]=="MODEL_BUDGET_EXHAUSTED" and result["response"] is None
    assert result["usage"]["total_tokens"]==100000
    assert system.budget.snapshot("budget:parent")["consumed"]["max_total_tokens"]==100000


def test_conflicting_inflight_request_never_claims_original_is_stopped(system):
    async def scenario():
        entered,release=asyncio.Event(),asyncio.Event()
        async def wait(_):entered.set();await release.wait();return MockDriver.final("original")
        system.driver.handler=wait
        pending=asyncio.create_task(system.adapter.generate(system.request,system.control))
        await entered.wait()
        changed=copy.deepcopy(system.request);changed["parameters"]={"temperature":1}
        conflict=await system.adapter.generate(changed,system.control)
        assert conflict["error"]["code"]=="MODEL_CALL_CONFLICT" and conflict["error"]["stop_status"]=="unknown"
        assert system.ledger.get(system.ref)["result"] is None
        release.set();assert (await pending)["status"]=="ok" and system.driver.send_count==1
    run(scenario())


@pytest.mark.parametrize("case",["local_only","no_evidence"])
def test_local_cancel_or_missing_evidence_cannot_confirm_remote_stop(system,case):
    async def scenario():
        async def slow(_):await asyncio.sleep(10)
        system.driver.handler=slow
        system.request["call_limits"]["timeout_seconds"]=0.01
        if case=="local_only":
            describe=system.driver.describe
            system.driver.describe=lambda:{**describe(),"cancellation":"local_only"}
        else:
            async def cancel(*_):return dict(stop_status="confirmed",local_request_state="closed",remote_execution_state="stopped",evidence_refs=[])
            system.driver.cancel=cancel
        result=await system.adapter.generate(system.request,system.control)
        assert result["status"]=="unknown" and result["error"]["stop_status"]=="unknown"
    run(scenario())



