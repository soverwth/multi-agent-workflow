import asyncio
import copy

import pytest

from b04.agent_runner import AgentRunner, ModelAdapterBridge, RunnerError
from b04.agent_runner.testing import configure_runtime
from b04.model_adapter import MockDriver
from b04.model_adapter.contracts import invocation_ref
from .support import error,execute,manifest,run


def fresh_runner(r):
    return AgentRunner(store=r.store,catalog=r.catalog,controls=r.controls_provider,authority=r.authority,model_adapter=ModelAdapterBridge(r.model),
                       tool_executor=r.tools,event_sink=r.sink,control_budget=r.model_budget,transport_budget=r.transport,source=r.runner.artifacts.source)


def test_commit_response_lost_after_actual_commit_queries_original(runtime):
    commit=runtime.store.commit_terminal;seen=[]
    def lose(draft,context,**kwargs):
        receipt=commit(draft,context,**kwargs);seen.append(draft["terminal_kind"]);raise OSError("lost response")
    runtime.store.commit_terminal=lose
    _,snapshot=run(execute(runtime))
    assert snapshot["terminal"]["draft"]["terminal_kind"]=="candidate_submitted" and seen==["candidate_submitted"]
    assert runtime.driver.send_count==1


def test_unknown_commit_before_write_is_not_replaced_with_failure(runtime):
    async def scenario():
        commit=runtime.store.commit_terminal
        runtime.store.commit_terminal=lambda *a,**k:(_ for _ in ()).throw(OSError("unknown commit boundary"))
        _,snapshot=await execute(runtime)
        assert snapshot["terminal"] is None and snapshot["phase"]=="SUBMITTING" and snapshot["recovery_required"]=="commit_unknown"
        row=runtime.store.get(invocation_ref(runtime.envelope),runtime.issued_controls.observe.context)
        submission_id=row["submission_id"]
        runtime.store.commit_terminal=commit
        other=fresh_runner(runtime)
        result=await other.recover_invocation(invocation_ref(runtime.envelope))
        assert result["terminal"]["draft"]["submission_id"]==submission_id and result["terminal"]["draft"]["terminal_kind"]=="candidate_submitted"
        assert runtime.driver.send_count==1 and len(runtime.tools.charged)==1
    run(scenario())


def test_lease_revoked_at_publish_reports_failure_using_independent_grant(runtime):
    commit=runtime.store.commit_terminal
    def revoke(draft,context,**kwargs):
        if draft["terminal_kind"]=="candidate_submitted":runtime.authority.invalidate_execution(invocation_ref(runtime.envelope))
        return commit(draft,context,**kwargs)
    runtime.store.commit_terminal=revoke
    _,snapshot=run(execute(runtime))
    assert snapshot["terminal"]["draft"]["terminal_kind"]=="execution_failed" and error(runtime,snapshot)["code"]=="EXEC_LEASE_INVALID"
    assert len([e for e in snapshot["events"] if e["event_type"] in {"candidate_submitted","execution_failed"}])==1


@pytest.mark.parametrize("stage",["model","tool","check"])
def test_interrupt_after_persisted_result_resumes_without_duplicate_send(runtime,stage):
    async def scenario():
        if stage=="tool":
            runtime.driver.handler=lambda _:MockDriver.tool_calls([dict(name="read_artifact",arguments={"artifact_ref":runtime.envelope["spec_ref"]})]) if runtime.driver.send_count==1 else MockDriver.final('{"tasks":[]}')
        checkpoint=runtime.store.checkpoint;interrupted=False
        def crash(ref,owner,phase,cp,context):
            nonlocal interrupted
            actions=runtime.store.actions(ref,runtime.issued_controls.observe.context)
            ready=any(a["kind"]==stage and a["state"]=="done" for a in actions)
            if ready and not interrupted:
                interrupted=True;raise asyncio.CancelledError()
            return checkpoint(ref,owner,phase,cp,context)
        runtime.store.checkpoint=crash
        receipt=await runtime.runner.invoke_agent(runtime.envelope);assert receipt["accepted"]
        with pytest.raises(asyncio.CancelledError):await runtime.runner.wait_invocation(invocation_ref(runtime.envelope))
        runtime.store.checkpoint=checkpoint
        before=runtime.driver.send_count
        configure_runtime(runtime,generation=2)
        recovered=await fresh_runner(runtime).recover_invocation(invocation_ref(runtime.envelope))
        assert recovered["terminal"]["draft"]["terminal_kind"]=="candidate_submitted"
        assert runtime.driver.send_count==(2 if stage=="tool" else 1)
        assert len([r for r in runtime.tools.requests if r["tool_name"]=="read_artifact"])==(1 if stage=="tool" else 0)
        assert len([r for r in runtime.tools.requests if r["origin"]["source"]=="self_check"])==1
    run(scenario())


def test_recovery_cannot_steal_same_generation_execution_owner(runtime):
    async def scenario():
        entered,release=asyncio.Event(),asyncio.Event()
        async def model(_):entered.set();await release.wait();return MockDriver.final('{"tasks":[]}')
        runtime.driver.handler=model
        await runtime.runner.invoke_agent(runtime.envelope);await entered.wait()
        with pytest.raises(RunnerError):await fresh_runner(runtime).recover_invocation(invocation_ref(runtime.envelope))
        release.set();await runtime.runner.wait_invocation(invocation_ref(runtime.envelope))
        assert runtime.driver.send_count==1
    run(scenario())


def test_confirmed_stop_has_one_terminal_and_never_claims_success(runtime):
    async def scenario():
        entered=asyncio.Event()
        async def model(_):entered.set();await asyncio.sleep(10)
        runtime.driver.handler=model
        await runtime.runner.invoke_agent(runtime.envelope);await entered.wait()
        receipt=await runtime.runner.stop_invocation(invocation_ref(runtime.envelope),"cancel_by_orchestrator")
        snapshot=await runtime.runner.wait_invocation(invocation_ref(runtime.envelope))
        assert receipt["stop_status"]=="confirmed" and snapshot["terminal"]["draft"]["terminal_kind"]=="execution_stopped"
        assert len([e for e in snapshot["events"] if e["event_type"] in {"execution_stopped","execution_failed","candidate_submitted"}])==1
    run(scenario())


def test_unknown_stop_preserves_reconciliation_without_stopped_terminal(runtime):
    async def scenario():
        entered=asyncio.Event()
        async def model(_):entered.set();await asyncio.sleep(10)
        runtime.driver.handler=model;runtime.driver.confirm_cancel=False
        await runtime.runner.invoke_agent(runtime.envelope);await entered.wait()
        receipt=await runtime.runner.stop_invocation(invocation_ref(runtime.envelope),"cancel")
        snapshot=await runtime.runner.wait_invocation(invocation_ref(runtime.envelope))
        assert receipt["stop_status"]=="unknown" and snapshot["terminal"] is None and snapshot["recovery_required"]=="stop_unconfirmed"
        assert not any(e["event_type"]=="execution_stopped" for e in snapshot["events"])
    run(scenario())


def test_execution_timeout_stops_new_calls_and_retains_remote_uncertainty(runtime_factory):
    # execution_timeout=0.15 是墙钟超时。若在慢速 CI runner 上，模型调用还没真正进入
    # handler 就先超时，走的是另一条清理路径，stop_status 会是 confirmed 而不是 unknown
    # （CI run 45838694925 的实际失败）。因此先让 handler 确认已进入，再等超时生效。
    runtime=runtime_factory(execution_timeout=0.15,model_timeout=2)
    entered=asyncio.Event()
    async def model(_):entered.set();await asyncio.sleep(10)
    runtime.driver.handler=model;runtime.driver.confirm_cancel=False
    async def scenario():
        receipt=await runtime.runner.invoke_agent(runtime.envelope)
        assert receipt["accepted"],receipt
        await asyncio.wait_for(entered.wait(),timeout=5)
        snapshot=await runtime.runner.wait_invocation(invocation_ref(runtime.envelope))
        return snapshot
    snapshot=run(scenario())
    assert error(runtime,snapshot)["code"]=="EXEC_TIMEOUT" and error(runtime,snapshot)["stop_status"]=="unknown" and runtime.driver.send_count==1


def test_stop_after_candidate_only_appends_cleanup(runtime):
    async def scenario():
        _,snapshot=await execute(runtime)
        receipt=await runtime.runner.stop_invocation(invocation_ref(runtime.envelope),"late stop")
        after=await runtime.runner.get_invocation(invocation_ref(runtime.envelope))
        assert receipt["stop_status"]=="confirmed" and after["terminal"]==snapshot["terminal"]
        assert not any(e["event_type"]=="execution_stopped" for e in after["events"])
    run(scenario())

