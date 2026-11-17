import asyncio
import copy

import pytest

from b04.model_adapter.contracts import invocation_ref
from .support import execute,manifest,run


def test_lost_delivery_keeps_outbox_and_reuses_original_event(runtime):
    async def scenario():
        def offline(event):raise OSError("offline")
        runtime.sink.before_submit=offline
        _,snapshot=await execute(runtime)
        assert snapshot["phase"]=="TERMINAL" and all(e["delivery"]=="pending" for e in snapshot["events"])
        original=[e["event_id"] for e in snapshot["events"]]
        runtime.sink.before_submit=None
        await runtime.runner.flush_events(invocation_ref(runtime.envelope))
        delivered=await runtime.runner.get_invocation(invocation_ref(runtime.envelope))
        assert [e["event_id"] for e in delivered["events"]]==original and all(e["delivery"]=="recorded" for e in delivered["events"])
        assert runtime.driver.send_count==1 and len(runtime.tools.requests)==1
    run(scenario())


def test_transport_budget_is_independent_and_bounded(runtime_factory):
    runtime=runtime_factory(transport_limit=1)
    _,snapshot=run(execute(runtime))
    assert snapshot["phase"]=="TERMINAL" and snapshot["terminal"]["draft"]["terminal_kind"]=="candidate_submitted"
    assert runtime.transport.consumed("budget:transport")==1
    assert snapshot["events"][0]["delivery"]=="recorded" and snapshot["events"][-1]["delivery"]=="pending"
    assert any(n["code"]=="delivery_or_reconciliation_pending" for n in snapshot["notes"])
    assert runtime.driver.send_count==1


@pytest.mark.parametrize("resolution,status",[("recorded","reconciled"),("stale","stale"),("retry_delivery","pending"),("new_attempt_required","new_attempt_required"),("manual_required","manual_required")])
def test_terminal_rejection_has_closed_reconciliation_outcome(runtime,resolution,status):
    runtime.sink.status_by_type["candidate_submitted"]="rejected";runtime.sink.resolution=resolution
    _,snapshot=run(execute(runtime))
    terminal=snapshot["events"][-1]
    assert terminal["delivery"]==status and terminal["receipt"]["receipt_status"]=="rejected"
    assert terminal["reconciliation"]["decision_ref"] and len(runtime.sink.reconciliations)==1
    request=runtime.sink.reconciliations[0]
    assert request["original_event_id"]==terminal["event_id"] and request["submission_id"]==snapshot["terminal"]["draft"]["submission_id"]
    assert len([e for e in snapshot["events"] if e["event_type"]=="candidate_submitted"])==1 and runtime.driver.send_count==1


def test_nonterminal_rejection_never_fabricates_terminal_submission_id(runtime):
    runtime.sink.status_by_type["execution_accepted"]="rejected"
    _,snapshot=run(execute(runtime))
    assert not runtime.sink.reconciliations and snapshot["events"][0]["delivery"]=="rejected"
    assert any(n["code"]=="nonterminal_event_rejected" and n["payload"]["responsible"]=="B02" for n in snapshot["notes"])
    assert snapshot["terminal"]["draft"]["terminal_kind"]=="candidate_submitted"


def test_invalid_receipt_cannot_acknowledge_another_event(runtime):
    submit=runtime.sink.submit_event
    async def wrong(event):
        receipt=await submit(event);receipt["event_id"]="foreign-event";return receipt
    runtime.sink.submit_event=wrong
    _,snapshot=run(execute(runtime))
    assert all(e["delivery"]=="pending" for e in snapshot["events"]) and runtime.driver.send_count==1


def test_stale_event_only_records_history(runtime):
    runtime.sink.status_by_type["candidate_submitted"]="stale"
    _,snapshot=run(execute(runtime))
    assert snapshot["events"][-1]["delivery"]=="stale" and not runtime.sink.reconciliations
    assert manifest(runtime,snapshot)["review_status"]=="pending"


def test_reconciliation_failure_keeps_original_terminal_and_owner_for_followup(runtime):
    runtime.sink.status_by_type["candidate_submitted"]="rejected"
    async def fail(*_):raise OSError("reconcile unavailable")
    runtime.sink.reconcile_terminal=fail
    _,snapshot=run(execute(runtime))
    assert snapshot["terminal"]["draft"]["terminal_kind"]=="candidate_submitted" and snapshot["events"][-1]["delivery"]=="rejected"
    assert any(n["code"]=="delivery_or_reconciliation_pending" and n["payload"]["responsible"]=="B02" for n in snapshot["notes"])


def test_deliveries_do_not_create_second_terminal_after_repeated_flush(runtime):
    async def scenario():
        _,first=await execute(runtime)
        count=len(runtime.sink.received)
        for _ in range(3):await runtime.runner.flush_events(invocation_ref(runtime.envelope))
        final=await runtime.runner.get_invocation(invocation_ref(runtime.envelope))
        assert final["terminal"]==first["terminal"] and len(runtime.sink.received)==count and runtime.driver.send_count==1
    run(scenario())

