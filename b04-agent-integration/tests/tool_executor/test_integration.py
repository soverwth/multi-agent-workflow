import json
import asyncio
import copy
import pytest
from b04.model_adapter import MockDriver
from b04.model_adapter.contracts import invocation_ref,canonical
from b04.tool_executor.contracts import operation_ref
from b04.tool_executor.testing import tool_request
from .support import run,admit,SimulatedSandbox


async def execute(r):
    receipt=await r.runner.invoke_agent(r.envelope)
    assert receipt['accepted'],receipt
    snapshot=await r.runner.wait_invocation(invocation_ref(r.envelope))
    return snapshot


def read(r,ref):return json.loads(r.store.read_object(ref,r.issued_controls.observe.context)['body'])


@pytest.mark.parametrize('product',['product-cli','product-lost-and-found'])
def test_three_modules_use_generic_product_spec_and_actual_schema_check(runtime_factory,product):
    r=runtime_factory(project=product)
    snapshot=run(execute(r));draft=snapshot['terminal']['draft']
    assert draft['terminal_kind']=='candidate_submitted',read(r,draft['error_ref']) if draft['error_ref'] else snapshot
    manifest=read(r,draft['manifest_ref'])
    assert manifest['self_check_status']=='passed' and manifest['review_status']=='pending'
    assert manifest['project_id']==product and r.driver.send_count==1
    assert r.tool_store.ticket('budget:tool-parent')['consumed']['max_tool_calls']==1
    actions=r.store.actions(invocation_ref(r.envelope),r.issued_controls.observe.context)
    check=next(a for a in actions if a['kind']=='check')
    result=check['result'];report=read(r,result['payload']['report_ref'])
    assert report['actual'][0]['schema_ref']=='schema:plan@1' and report['evidence_kind']=='tool_execution'
    assert report['subjects']==check['request']['arguments']['subjects']
    assert result['operation_record_ref'] in manifest['tool_operation_refs']


def test_model_read_tool_feedback_preserves_complete_tool_result(runtime_factory):
    r=runtime_factory()
    def response(_):return MockDriver.tool_calls([dict(name='read_artifact',arguments={'artifact_ref':r.envelope['spec_ref']})]) if r.driver.send_count==1 else MockDriver.final('{"tasks":[]}')
    r.driver.handler=response;snapshot=run(execute(r))
    assert snapshot['terminal']['draft']['terminal_kind']=='candidate_submitted'
    feedback=json.loads(r.driver.requests[1]['messages'][-1]['content'][0]['text'])
    assert feedback['status']=='completed' and feedback['result_code']=='TOOL_COMPLETED' and feedback['stop_status']=='confirmed'
    assert feedback['operation_record_ref'].startswith('tool-record:') and feedback['output_refs'] and feedback['changes']==[]
    assert json.loads(feedback['payload']['content'])['product']==r.envelope['project_id']
    assert r.tool_store.ticket('budget:tool-parent')['consumed']['max_tool_calls']==2


def test_runner_normalizes_inline_write_to_owned_staged_content(runtime_factory):
    r=runtime_factory();content='print("通用产品")\r\n'
    def response(_):return MockDriver.tool_calls([dict(name='write_file',arguments=dict(path='src/main.py',mode='create',content=content,encoding='utf-8',expected_target_sha256=None))]) if r.driver.send_count==1 else MockDriver.final('{"tasks":[]}')
    r.driver.handler=response;snapshot=run(execute(r))
    assert snapshot['terminal']['draft']['terminal_kind']=='candidate_submitted'
    assert (r.workspace.root/'src/main.py').read_bytes()==content.encode()
    actions=r.store.actions(invocation_ref(r.envelope),r.issued_controls.observe.context)
    action=next(a for a in actions if a['kind']=='tool' and a['request']['tool_name']=='write_file')
    assert 'content' not in action['request']['arguments'] and action['request']['arguments']['content_ref']
    assert action['result']['changes'][0]['change_type']=='created'


def test_disabled_required_checker_blocks_execution(runtime_factory):
    r=runtime_factory();r.tool_registry.disable_tool('run_check','1',r.admin)
    snapshot=run(execute(r));draft=snapshot['terminal']['draft'];fault=read(r,draft['error_ref'])
    assert draft['terminal_kind']=='execution_blocked' and fault['code']=='EXEC_CAPABILITY_UNAVAILABLE',fault


def test_missing_command_backend_blocks_through_runner(runtime_factory):
    r=runtime_factory();r.driver.response=MockDriver.tool_calls([dict(name='run_command',arguments={'command_profile_ref':'command:check@1','parameters':{'target':'src'}})])
    snapshot=run(execute(r));draft=snapshot['terminal']['draft'];fault=read(r,draft['error_ref'])
    assert draft['terminal_kind']=='execution_blocked' and fault['code']=='EXEC_CAPABILITY_UNAVAILABLE'
    assert r.driver.send_count==1 and fault['details']['tool']['code']=='TOOL_PROFILE_UNSUPPORTED'


@pytest.mark.parametrize('valid',[True,False])
def test_schema_checker_returns_real_professional_conclusion(runtime,valid):
    async def scenario():
        r=runtime;await admit(r);ref=invocation_ref(r.envelope)
        artifact=r.store.put_object(ref,'subject','task_plan',canonical({'tasks':[]} if valid else {'unexpected':True}).encode(),r.issued_controls.tool.context,namespace=r.envelope['write_scope']['artifact_namespaces'][0])
        args=dict(check_ref='check:quality@1',subjects=[{k:artifact[k] for k in ['artifact_ref','kind','sha256']}],environment_ref='environment:test@1',expected='Declared professional rule holds')
        req=tool_request(r,'run_check',args,origin=dict(source='self_check',model_call_id=None,tool_call_id=None,check_ref='check:quality@1'))
        result=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert result['status']=='completed' and result['payload']['check_outcome']==('passed' if valid else 'failed'),result
        assert result['exit_code']==(0 if valid else 1) and result['error'] is None
        assert read(r,result['payload']['report_ref'])['actual'][0]['sha256']==artifact['sha256']
    run(scenario())


def test_snapshot_input_state_is_rechecked_during_tool_execution(runtime):
    async def scenario():
        r=runtime;await admit(r);ref=r.envelope['spec_ref']
        row=r.store._db.execute('SELECT metadata FROM runner_objects WHERE ref=?',(ref,)).fetchone();meta=json.loads(row[0]);meta['state']='rejected'
        r.store._db.execute('UPDATE runner_objects SET metadata=? WHERE ref=?',(canonical(meta),ref))
        result=await r.tools.execute_tool(tool_request(r),r.issued_controls.tool)
        assert result['status']=='rejected' and result['side_effects_state']=='none'
    run(scenario())


def test_runner_stop_uses_independent_cleanup_and_reaches_stopped_terminal(runtime_factory):
    backend=SimulatedSandbox(never=True);r=runtime_factory(sandboxes={'sandbox:test@1':backend})
    r.driver.response=MockDriver.tool_calls([dict(name='run_command',arguments={'command_profile_ref':'command:check@1','parameters':{'target':'src'}})])
    async def scenario():
        await r.runner.invoke_agent(r.envelope)
        while not backend.units:await asyncio.sleep(.005)
        ref=invocation_ref(r.envelope)
        receipt=await r.runner.stop_invocation(ref,'user requested stop')
        assert receipt['stop_status']=='confirmed' and backend.units[0].stopped
        snapshot=await r.runner.wait_invocation(ref)
        assert snapshot['terminal']['draft']['terminal_kind']=='execution_stopped'
        assert r.driver.send_count==1
    run(scenario())


def test_old_generation_is_fenced_even_if_original_authority_grant_was_not_revoked(runtime):
    async def scenario():
        r=runtime;await admit(r);ref=invocation_ref(r.envelope);context=copy.deepcopy(r.issued_controls.tool.context)
        context.update(context_ref='context:new-owner',control_generation=2)
        r.authority.register(context);r.store.claim_execution(ref,'new-owner',context,recover=True)
        result=await r.tools.execute_tool(tool_request(r),r.issued_controls.tool)
        assert result['result_code']=='TOOL_LEASE_INVALID' and result['status']=='rejected'
    run(scenario())
