import asyncio
import copy
import json
from dataclasses import replace
from datetime import timedelta

import pytest

from b04.model_adapter import CallControl, MappingCredentialResolver, MockDriver, ModelAdapterFacade, ModelAdapterError, SQLiteCallLedger
from b04.model_adapter.contracts import digest, invocation_ref, stamp, utc_now
from conftest import structured
from test_adapter import generate, run


def facade(system,ledger):
    return ModelAdapterFacade(resolver=system.resolver,registry=system.registry,ledger=ledger,budget=system.budget,authority=system.authority)


def test_completed_record_survives_new_adapter_instance(system):
    first=generate(system)
    other=facade(system,system.ledger)
    assert run(other.generate(system.request,system.control))==first and system.driver.send_count==1


def test_durable_sent_intent_does_not_send_again_after_restart(system,tmp_path):
    path=tmp_path/"crashed.sqlite3"
    ledger=SQLiteCallLedger(path)
    try:
        prepared=system.adapter._prepare(copy.deepcopy(system.request),system.control)
        ledger.claim(system.request,prepared["fingerprint"],prepared["attempt_fingerprint"],{})
        ledger.mark_sent(system.ref,"transport:crash")
    finally:ledger.close()
    restarted=SQLiteCallLedger(path)
    try:
        result=run(facade(system,restarted).generate(system.request,system.control))
        assert result["status"]=="unknown" and result["error"]["code"]=="MODEL_NETWORK_UNCERTAIN"
        assert system.driver.send_count==0
    finally:restarted.close()


def test_two_facades_share_atomic_claim_without_second_send(system):
    async def scenario():
        entered,release=asyncio.Event(),asyncio.Event()
        async def wait(_):entered.set();await release.wait();return MockDriver.final("done")
        system.driver.handler=wait
        first=asyncio.create_task(system.adapter.generate(system.request,system.control))
        await entered.wait()
        other=await facade(system,system.ledger).generate(system.request,system.control)
        assert other["status"]=="unknown"  # Other owner cannot assert liveness.
        release.set()
        assert (await first)["status"]=="ok" and system.driver.send_count==1
    run(scenario())


def test_failed_duplicate_query_does_not_finalize_or_remove_running_owner(system):
    async def scenario():
        entered,release=asyncio.Event(),asyncio.Event()
        async def wait(_):entered.set();await release.wait();return MockDriver.final("original")
        system.driver.handler=wait
        ticket=system.budget.snapshot("budget:control");ticket["ticket_ref"]="budget:no-queries";ticket["limits"]["max_control_actions"]=0
        system.budget.register(ticket)
        limited=replace(system.control,control_budget_ticket_ref="budget:no-queries")
        first=asyncio.create_task(system.adapter.generate(system.request,system.control))
        await entered.wait()
        result=await system.adapter.generate(system.request,limited)
        assert result["error"]["code"]=="MODEL_BUDGET_EXHAUSTED"
        assert system.ledger.get(system.ref)["result"] is None
        assert (await system.adapter.generate(system.request,system.control))["status"]=="in_progress"
        release.set();assert (await first)["status"]=="ok" and system.driver.send_count==1
    run(scenario())


def test_revocation_inflight_stops_and_reports_with_independent_grants(system):
    async def scenario():
        entered=asyncio.Event()
        async def wait(_):entered.set();await asyncio.sleep(10)
        system.driver.handler=wait
        pending=asyncio.create_task(system.adapter.generate(system.request,system.control))
        await entered.wait()
        system.authority.invalidate_execution(invocation_ref(system.request))
        result=await asyncio.wait_for(pending,0.5)
        assert result["error"]["code"]=="MODEL_CONTROL_INVALID" and result["response"] is None
        assert system.driver.cancel_count==1 and system.ledger.get(system.ref)["result"]==result
        assert (await system.adapter.get_call(system.ref,system.controls["observe"]))["call_state"]=="unknown"
    run(scenario())


def test_late_response_never_replaces_original_unknown_result(system):
    async def scenario():
        release=asyncio.Event()
        async def ignore_local_cancel(_):
            try:await asyncio.sleep(10)
            except asyncio.CancelledError:await release.wait()
            return MockDriver.final("late response")
        system.driver.handler=ignore_local_cancel;system.driver.confirm_cancel=False
        system.request["call_limits"]["timeout_seconds"]=0.02
        result=await system.adapter.generate(system.request,system.control)
        assert result["status"]=="unknown"
        release.set();await asyncio.sleep(0.02)
        record=system.ledger.get(system.ref)
        assert record["result"]==result and any(n["kind"]=="late_response" for n in record["notes"])
        assert (await system.adapter.generate(system.request,system.control))==result
    run(scenario())


def test_missing_auxiliary_grants_block_send(system):
    missing=CallControl(system.control.context,"budget:control")
    result=run(system.adapter.generate(system.request,missing))
    assert result["error"]["code"]=="MODEL_CONTROL_INVALID" and result["status"]=="error" and system.driver.send_count==0


def test_report_grant_never_authorizes_generation(system):
    result=run(system.adapter.generate(system.request,system.controls["report"]))
    assert result["error"]["code"]=="MODEL_CONTROL_INVALID" and system.driver.send_count==0


def test_failed_result_recording_leaves_durable_send_intent(system):
    original=system.ledger.finish
    system.ledger.finish=lambda *args,**kwargs:(_ for _ in ()).throw(OSError("disk failure"))
    result=generate(system)
    assert result["status"]=="unknown" and system.driver.send_count==1
    system.ledger.finish=original
    second=run(facade(system,system.ledger).generate(system.request,system.control))
    assert second["status"]=="unknown" and system.driver.send_count==1


def test_secret_is_not_exposed_in_results_raw_artifacts_or_summary(system):
    secret="do-not-expose-secret-value"
    config,policy,caps=system.resolver._models[system.config["model_config_ref"]]
    config["credential_ref"]="credential:one"
    system.adapter.credentials=MappingCredentialResolver({"credential:one":secret})
    system.driver.response=MockDriver.final(secret)
    result=generate(system)
    assert result["error"]["code"]=="MODEL_RESPONSE_MALFORMED" and result["response"] is None
    assert secret not in json.dumps(result)
    raw=system.ledger.get_private(result["raw_response_ref"],invocation_ref(system.request))
    assert secret not in json.dumps(raw) and "[REDACTED]" in json.dumps(raw)
    description=run(system.adapter.describe_model(system.request["model_config_ref"],system.control))
    assert secret not in json.dumps(description) and "credential:one" not in json.dumps(description)


def test_missing_credential_is_auth_error_without_send(system):
    system.resolver._models[system.config["model_config_ref"]][0]["credential_ref"]="credential:absent"
    result=generate(system)
    assert result["error"]["code"]=="MODEL_AUTH_FAILED" and system.driver.send_count==0


def test_schema_change_changes_fingerprint_even_if_ref_is_same(system):
    structured(system)
    first=run(system.adapter.validate_request(system.request,system.control))
    system.resolver._schemas["schema:plan@1"]["maxProperties"]=1
    second=run(system.adapter.validate_request(system.request,system.control))
    assert first["request_fingerprint"]!=second["request_fingerprint"]


def test_private_records_are_project_bound(system):
    result=generate(system)
    foreign=invocation_ref(system.request);foreign["project_id"]="other"
    with pytest.raises(ModelAdapterError):system.ledger.get_private(result["raw_response_ref"],foreign)


def test_budget_parent_is_not_reset_by_new_attempt(system):
    request=system.request;ref=invocation_ref(request)
    tokens=10
    system.budget.reserve(request["budget_ticket_ref"],"transport:one",ref,tokens,utc_now())
    system.budget.settle("transport:one",delivery="sent",usage=dict(availability="observed",total_tokens=5))
    child=system.budget.snapshot(request["budget_ticket_ref"])
    child.update(ticket_ref="budget:attempt-2",invocation_ref={**ref,"attempt_id":2,"dispatch_id":"dispatch-2"})
    for key in ["consumed","reserved","unsettled"]:child[key]=dict.fromkeys(child["limits"],0)
    system.budget.register(child)
    system.budget.reserve(child["ticket_ref"],"transport:two",child["invocation_ref"],tokens,utc_now())
    assert system.budget.snapshot("budget:parent")["consumed"]["max_model_calls"]==1
    assert system.budget.snapshot("budget:parent")["reserved"]["max_model_calls"]==1


def test_preflight_does_not_authorize_later_revoked_send(system):
    assert run(system.adapter.validate_request(system.request,system.control))["valid"]
    system.authority.revoke(system.control.context["context_ref"])
    assert generate(system)["error"]["code"]=="MODEL_CONTROL_INVALID" and system.driver.send_count==0


def test_past_request_deadline_prevents_send(system):
    system.request["call_limits"]["deadline_at"]=stamp(utc_now()-timedelta(seconds=1))
    result=generate(system)
    assert result["error"]["code"]=="MODEL_TIMEOUT" and result["error"]["request_delivery"]=="not_sent" and system.driver.send_count==0

