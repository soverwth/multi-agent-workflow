import asyncio
import copy
from datetime import timedelta

import pytest
from b04.model_adapter.contracts import canonical,invocation_ref,stamp,utc_now
from b04.tool_executor import ToolExecutorError
from b04.tool_executor.contracts import DriverOutcome,operation_ref
from b04.tool_executor.testing import tool_request
from .support import run,admit,call,write_request,SimulatedSandbox,command_request


def test_result_storage_failure_never_repeats_committed_write(runtime):
    async def scenario():
        r=runtime;await admit(r);req=write_request(r,b'committed');original=r.tool_store.finish
        def fail(*args):raise OSError('private sensitive storage path')
        r.tool_store.finish=fail
        first=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert first['status']=='unknown' and (r.workspace.root/'src/main.txt').read_bytes()==b'committed'
        r.tool_store.finish=original
        replay=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert replay['status']=='unknown' and 'private sensitive' not in canonical(replay)
        assert (r.workspace.root/'src/main.txt').read_bytes()==b'committed'
        assert r.tool_store.ticket('budget:tool-parent')['consumed']['max_tool_calls']==1
    run(scenario())


def test_report_storage_failure_after_write_is_unknown_and_fenced(runtime):
    async def scenario():
        r=runtime;await admit(r);req=write_request(r,b'committed');original=r.store.put_object
        def fail(*args,**kwargs):raise OSError('sensitive')
        r.store.put_object=fail
        result=await r.tools.execute_tool(req,r.issued_controls.tool);r.store.put_object=original
        assert result['status']=='unknown' and result['side_effects_state']=='unknown'
        assert (r.workspace.root/'src/main.txt').read_bytes()==b'committed'
        assert r.tool_store.ticket('budget:tool-parent')['unsettled']['max_tool_calls']==1
        assert await r.tools.execute_tool(req,r.issued_controls.tool)==result
    run(scenario())


def test_prepared_intent_after_owner_loss_is_queried_not_reexecuted(runtime):
    async def scenario():
        r=runtime;await admit(r);req=tool_request(r);resolved,policy,fp=r.tools._base(req,r.issued_controls.tool)
        r.tool_store.claim(operation_ref(req),fp,req,{},[])
        result=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert result['status']=='unknown' and r.tool_store.ticket('budget:tool-child')['consumed']['max_tool_calls']==0
    run(scenario())


def test_two_prepared_owners_cannot_both_start_same_resource(runtime):
    r=runtime;a=tool_request(r,operation_id='a');b=tool_request(r,operation_id='b');root=r.workspace.root.as_posix()
    r.tool_store.claim(operation_ref(a),'a',a,{},[root]);r.tool_store.claim(operation_ref(b),'b',b,{},[root+'/src'])
    r.tool_store.mark_running(operation_ref(a))
    with pytest.raises(ToolExecutorError,match='TOOL_OPERATION_CONFLICT'):r.tool_store.mark_running(operation_ref(b))


def test_changed_task_or_dispatch_cannot_alias_existing_operation(runtime):
    r=runtime;req=tool_request(r);ref=operation_ref(req);r.tool_store.claim(ref,'original',req,{},[])
    for field,value in [('task_id','foreign-task'),('dispatch_id','foreign-dispatch')]:
        wrong=copy.deepcopy(ref);wrong['invocation_ref'][field]=value
        with pytest.raises(ToolExecutorError,match='TOOL_OPERATION_CONFLICT'):r.tool_store.get(wrong)


def test_parent_invocation_quota_survives_new_attempt(runtime_factory):
    r=runtime_factory(auto_start=False,max_tool_calls=1);ref=invocation_ref(r.envelope)
    r.tool_store.reserve('budget:tool-child',dict(invocation_ref=ref,operation_id='first'));r.tool_store.settle(dict(invocation_ref=ref,operation_id='first'),executed=True)
    ticket=r.tool_store.ticket('budget:tool-child');ticket['ticket_ref']='budget:new-attempt';ticket['invocation_ref']['attempt_id']=2;ticket['invocation_ref']['dispatch_id']='dispatch:2'
    ticket['reserved']['max_tool_calls']=0;ticket['consumed']['max_tool_calls']=0
    r.tool_store.register_ticket(ticket)
    with pytest.raises(ToolExecutorError,match='TOOL_BUDGET_EXHAUSTED'):r.tool_store.reserve(ticket['ticket_ref'],dict(invocation_ref=ticket['invocation_ref'],operation_id='second'))


@pytest.mark.parametrize('field',['expires_at','state','ledger_ref','invocation_ref'])
def test_budget_parent_binding_is_verified(runtime,field):
    r=runtime;ticket=r.tool_store.ticket('budget:tool-child');ticket['ticket_ref']='new'
    if field=='expires_at':ticket[field]=stamp(utc_now()-timedelta(seconds=1))
    elif field=='state':ticket[field]='closed'
    elif field=='ledger_ref':ticket[field]='foreign'
    else:ticket[field]['project_id']='foreign'
    r.tool_store.register_ticket(ticket)
    with pytest.raises(ToolExecutorError,match='TOOL_BUDGET_EXHAUSTED'):r.tool_store.reserve('new',operation_ref(tool_request(r)))


def test_invalid_output_payload_is_not_reported_as_success(runtime):
    async def scenario():
        r=runtime;await admit(r);driver=r.tool_registry.drivers['builtin:read_artifact@1']
        async def wrong(*args):return DriverOutcome('wrong-payload-type',[],[])
        driver.run=wrong
        result=await r.tools.execute_tool(tool_request(r),r.issued_controls.tool)
        assert result['result_code']=='TOOL_OUTPUT_INVALID' and result['status']=='failed'
    run(scenario())


def test_missing_file_reports_io_error_without_fabricated_side_effects(runtime):
    result=run(call(runtime,tool_request(runtime,'read_file',{'path':'src/missing'})))
    assert result['result_code']=='TOOL_IO_ERROR' and result['stop_status']=='confirmed' and result['side_effects_state']=='none'


def test_late_stop_appends_history_without_changing_original_result(runtime):
    async def scenario():
        r=runtime;await admit(r);req=tool_request(r);original=await r.tools.execute_tool(req,r.issued_controls.tool)
        receipt=await r.tools.stop_operation(operation_ref(req),'late cancellation',r.issued_controls.cleanup)
        assert receipt['stop_status']=='confirmed' and r.tool_store.get(operation_ref(req))['result']==original
        assert r.tool_store.get(operation_ref(req))['notes'][-1]['kind']=='stop_observation'
    run(scenario())


def test_disable_active_command_stops_unit(runtime_factory):
    backend=SimulatedSandbox(never=True);r=runtime_factory(auto_start=False,sandboxes={'sandbox:test@1':backend})
    async def scenario():
        await admit(r);task=asyncio.create_task(r.tools.execute_tool(command_request(r),r.issued_controls.tool))
        while not backend.units:await asyncio.sleep(.005)
        r.tool_registry.disable_tool('run_command','1',r.admin)
        result=await task
        assert result['result_code']=='TOOL_DISABLED' and result['stop_status']=='confirmed' and backend.units[0].stopped
    run(scenario())


def test_report_grant_loss_leaves_queryable_intent_and_no_false_success(runtime):
    async def scenario():
        r=runtime;await admit(r);req=tool_request(r);driver=r.tool_registry.drivers['builtin:read_artifact@1'];original=driver.run
        async def revoke(*args):
            value=await original(*args);r.authority.revoke(r.issued_controls.report.context['context_ref']);return value
        driver.run=revoke
        result=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert result['status']=='unknown' and r.tool_store.get(operation_ref(req))['result'] is None
        assert (await r.tools.get_operation(operation_ref(req),r.issued_controls.observe))['state']=='unknown'
    run(scenario())
