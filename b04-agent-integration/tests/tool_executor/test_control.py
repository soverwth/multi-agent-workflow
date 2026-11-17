import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest
from b04.model_adapter.contracts import invocation_ref,stamp,utc_now
from b04.tool_executor import ToolExecutorError,ToolExecutor,SQLiteToolStore
from b04.tool_executor.contracts import operation_ref,op_key
from b04.tool_executor.testing import tool_request
from .support import run,admit,call,SimulatedSandbox,command_request


@pytest.mark.parametrize('field,value',[('lease_ref','foreign'),('input_snapshot_id','foreign'),('input_snapshot_sha256','0'*64),('tool_binding_ref','foreign'),('tool_version','2'),('tool_config_ref','foreign'),('workspace_ref','foreign'),('execution_mode','live')])
def test_frozen_request_binding_is_authoritative(runtime,field,value):
    req=tool_request(runtime);req[field]=value
    result=run(call(runtime,req))
    assert result['result_code'] in {'TOOL_SCOPE_DENIED','TOOL_LEASE_INVALID'} and result['side_effects_state']=='none'
    assert runtime.tool_store.ticket('budget:tool-parent')['consumed']['max_tool_calls']==0


def test_forged_control_cannot_expand_write_scope(runtime):
    async def scenario():
        r=runtime;await admit(r);ctx=copy.deepcopy(r.issued_controls.tool.context);ctx['write_scope']['workspace_paths']=['other']
        result=await r.tools.execute_tool(tool_request(r),replace(r.issued_controls.tool,context=ctx))
        assert result['result_code']=='TOOL_LEASE_INVALID'
    run(scenario())


@pytest.mark.parametrize('origin',[dict(source='model',model_call_id=None,tool_call_id='t',check_ref=None),dict(source='model',model_call_id='m',tool_call_id='t',check_ref='c'),dict(source='runner',model_call_id='m',tool_call_id=None,check_ref=None),dict(source='self_check',model_call_id=None,tool_call_id=None,check_ref=None)])
def test_conditional_origin_fields(runtime,origin):
    assert run(call(runtime,tool_request(runtime,origin=origin)))['result_code']=='TOOL_REQUEST_INVALID'


def test_model_cannot_invoke_hidden_checker(runtime):
    req=tool_request(runtime,'run_check',dict(check_ref='check:quality@1',subjects=[],environment_ref='environment:test@1',expected='Declared professional rule holds'),origin=dict(source='model',model_call_id='m',tool_call_id='t',check_ref=None))
    assert run(call(runtime,req))['result_code']=='TOOL_SCOPE_DENIED'


def test_model_cannot_read_arbitrary_artifact(runtime):
    result=run(call(runtime,tool_request(runtime,arguments={'artifact_ref':'other-product/accepted-secret'})))
    assert result['result_code']=='TOOL_SCOPE_DENIED' and 'accepted-secret' not in str(result['error'])


def test_duplicate_in_progress_is_not_reexecuted(runtime):
    async def scenario():
        r=runtime;await admit(r);req=tool_request(r);driver=r.tool_registry.drivers['builtin:read_artifact@1'];original=driver.run
        entered=asyncio.Event();release=asyncio.Event();count=0
        async def delayed(*args):
            nonlocal count
            count+=1;entered.set();await release.wait();return await original(*args)
        driver.run=delayed
        task=asyncio.create_task(r.tools.execute_tool(req,r.issued_controls.tool));await entered.wait()
        replay=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert replay['status']=='in_progress' and replay['stop_status'] is None and replay['timing']['finished_at'] is None
        assert r.tool_store.ticket('budget:tool-child')['reserved']['max_tool_calls']==1
        release.set();result=await task
        assert result['status']=='completed' and count==1
    run(scenario())


def test_same_id_changed_arguments_conflicts_and_preserves_original(runtime):
    async def scenario():
        r=runtime;await admit(r);req=tool_request(r);first=await r.tools.execute_tool(req,r.issued_controls.tool)
        changed=copy.deepcopy(req);changed['timeout_seconds']=2
        result=await r.tools.execute_tool(changed,r.issued_controls.tool)
        assert result['result_code']=='TOOL_OPERATION_CONFLICT'
        assert r.tool_store.get(operation_ref(req))['result']==first
        assert r.tool_store.ticket('budget:tool-child')['consumed']['max_tool_calls']==1
    run(scenario())


def test_reopened_store_replays_completed_result(runtime):
    async def scenario():
        r=runtime;await admit(r);req=tool_request(r);first=await r.tools.execute_tool(req,r.issued_controls.tool)
        store=SQLiteToolStore(r.tool_store._db.execute('PRAGMA database_list').fetchone()[2])
        other=ToolExecutor(registry=r.tool_registry,store=store,authority=r.authority,policy=r.tool_policy,artifacts=r.store,workspaces=r.tools.workspaces,control_budget=r.model_budget)
        try:assert await other.execute_tool(req,r.issued_controls.tool)==first
        finally:store.close()
    run(scenario())


def test_execution_lease_loss_does_not_block_observe_cleanup_or_report(runtime):
    async def scenario():
        r=runtime;await admit(r);req=tool_request(r);first=await r.tools.execute_tool(req,r.issued_controls.tool)
        r.authority.invalidate_execution(req['invocation_ref'])
        denied=await r.tools.execute_tool(tool_request(r,operation_id='new'),r.issued_controls.tool)
        assert denied['result_code']=='TOOL_LEASE_INVALID'
        snapshot=await r.tools.get_operation(operation_ref(req),r.issued_controls.observe)
        assert snapshot['budget']['settlement']=='consumed'
        assert await r.tools.read_result(operation_ref(req),snapshot['result_ref'],r.issued_controls.observe)==first
        assert (await r.tools.stop_operation(operation_ref(req),'cancel',r.issued_controls.cleanup))['stop_status']=='confirmed'
        assert r.store.put_object(req['invocation_ref'],'late-diagnostic','diagnostic',b'{}',r.issued_controls.report.context)['artifact_ref']
    run(scenario())


def test_cross_invocation_observation_and_result_substitution_are_denied(runtime):
    async def scenario():
        r=runtime;await admit(r);req=tool_request(r);await r.tools.execute_tool(req,r.issued_controls.tool);ref=operation_ref(req)
        with pytest.raises(ToolExecutorError):await r.tools.read_result(ref,'foreign-result',r.issued_controls.observe)
        wrong=copy.deepcopy(ref);wrong['invocation_ref']['project_id']='other'
        with pytest.raises(ToolExecutorError):await r.tools.get_operation(wrong,r.issued_controls.observe)
        with pytest.raises(ToolExecutorError):await r.tools.stop_operation(wrong,'cancel',r.issued_controls.cleanup)
    run(scenario())


def test_stop_tombstone_prevents_late_start(runtime):
    async def scenario():
        r=runtime;await admit(r);req=tool_request(r)
        stopped=await r.tools.stop_operation(operation_ref(req),'cancel before start',r.issued_controls.cleanup)
        assert stopped['stop_status']=='confirmed' and stopped['evidence_refs']
        result=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert result['status']=='stopped' and result['side_effects_state']=='none'
        assert r.tool_store.ticket('budget:tool-parent')['consumed']['max_tool_calls']==0
    run(scenario())


def test_parent_budget_and_duplicate_query_do_not_double_charge(runtime_factory):
    r=runtime_factory(auto_start=False,max_tool_calls=1)
    async def scenario():
        await admit(r);req=tool_request(r);result=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert await r.tools.execute_tool(req,r.issued_controls.tool)==result
        await r.tools.get_operation(operation_ref(req),r.issued_controls.observe)
        assert (await r.tools.execute_tool(tool_request(r,operation_id='2'),r.issued_controls.tool))['result_code']=='TOOL_BUDGET_EXHAUSTED'
        for name in ['budget:tool-parent','budget:tool-child']:
            t=r.tool_store.ticket(name);assert t['consumed']['max_tool_calls']==1 and t['reserved']['max_tool_calls']==0
        assert (await r.tools.stop_operation(operation_ref(req),'cancel',r.issued_controls.cleanup))['stop_status']=='confirmed'
    run(scenario())


def test_atomic_quota_reservation(runtime_factory):
    r=runtime_factory(auto_start=False,max_tool_calls=3);ref=invocation_ref(r.envelope)
    def reserve(i):
        try:r.tool_store.reserve('budget:tool-child',dict(invocation_ref=ref,operation_id=str(i)));return True
        except ToolExecutorError:return False
    with ThreadPoolExecutor(max_workers=8) as pool:assert sum(pool.map(reserve,range(20)))==3
    assert r.tool_store.ticket('budget:tool-parent')['reserved']['max_tool_calls']==3


def test_control_actions_have_independent_finite_budget(runtime):
    async def scenario():
        r=runtime;await admit(r);r.model_budget._tickets['budget:control']['consumed']['max_control_actions']=5000
        with pytest.raises(ToolExecutorError,match='TOOL_BUDGET_EXHAUSTED'):await r.tools.get_operation(operation_ref(tool_request(r)),r.issued_controls.observe)
    run(scenario())
