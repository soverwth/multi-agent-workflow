import asyncio
import copy
import pytest
from b04.tool_executor import ToolExecutor,ToolExecutorError
from b04.tool_executor.contracts import operation_ref
from b04.tool_executor.testing import tool_request
from .support import run,admit,SimulatedSandbox,command_request


def configured(runtime_factory,backend,configure_tools=None):return runtime_factory(auto_start=False,sandboxes={'sandbox:test@1':backend},configure_tools=configure_tools)


def test_no_sandbox_never_falls_back_to_host_command(runtime):
    async def scenario():
        await admit(runtime);result=await runtime.tools.execute_tool(command_request(runtime),runtime.issued_controls.tool)
        assert result['result_code']=='TOOL_PROFILE_UNSUPPORTED' and result['status']=='rejected'
        assert runtime.tool_store.ticket('budget:tool-child')['consumed']['max_tool_calls']==0
    run(scenario())


@pytest.mark.parametrize('missing',['filesystem_isolation','network_isolation','process_tree_stop','memory_limit','pid_limit','tmpfs_limit'])
def test_partial_isolation_is_not_accepted(runtime_factory,missing):
    backend=SimulatedSandbox(capability_override={missing:False});r=configured(runtime_factory,backend)
    async def scenario():
        await admit(r);result=await r.tools.execute_tool(command_request(r),r.issued_controls.tool)
        assert result['result_code']=='TOOL_PROFILE_UNSUPPORTED' and not backend.units
    run(scenario())


@pytest.mark.parametrize('target',['-c','../secret','C:/secret','src/../../secret','other/file'])
def test_typed_parameters_and_path_permissions(runtime_factory,target):
    backend=SimulatedSandbox();r=configured(runtime_factory,backend)
    req=command_request(r);req['arguments']['parameters']['target']=target
    async def scenario():
        await admit(r);result=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert result['status']=='rejected' and not backend.units
    run(scenario())


def test_command_uses_fixed_argv_minimal_environment_and_separate_logs(runtime_factory):
    backend=SimulatedSandbox(files={'src/result.txt':b'checked\r\n'});r=configured(runtime_factory,backend)
    async def scenario():
        await admit(r);req=command_request(r);result=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert result['status']=='completed',result
        unit=backend.units[0];assert unit.spec['argv']==['/usr/local/bin/python','-I','-B','/opt/check.py','src']
        assert unit.spec['environment']=={'LANG':'C.UTF-8'} and unit.closed
        assert (r.workspace.root/'src/result.txt').read_bytes()==b'checked\r\n'
        assert result['payload']['stdout_ref']!=result['payload']['stderr_ref']
        for name,body in [('stdout',backend.stdout),('stderr',backend.stderr)]:assert r.store.read_object(result['payload'][name+'_ref'],r.issued_controls.observe.context)['body']==body
        assert await r.tools.execute_tool(req,r.issued_controls.tool)==result and len(backend.units)==1
    run(scenario())


@pytest.mark.parametrize('exit_code,status,outcome',[(0,'completed','passed'),(1,'completed','failed'),(2,'failed',None)])
def test_exit_policy_preserves_business_failure(runtime_factory,exit_code,status,outcome):
    backend=SimulatedSandbox(exit_code=exit_code);r=configured(runtime_factory,backend)
    async def scenario():
        await admit(r);result=await r.tools.execute_tool(command_request(r),r.issued_controls.tool)
        assert result['status']==status and result['exit_code']==exit_code,result
        if outcome:assert result['payload']['check_outcome']==outcome and result['error'] is None
        else:assert result['result_code']=='TOOL_COMMAND_FAILED' and len(result['output_refs'])==2
    run(scenario())


@pytest.mark.parametrize('receipt,expected',[({'stop_status':'confirmed','evidence_refs':['fixture:tree-empty']},'timed_out'),({'stop_status':'unknown','evidence_refs':[]},'unknown'),({'stop_status':'confirmed','evidence_refs':[]},'unknown')])
def test_deadline_and_stop_evidence(runtime_factory,receipt,expected):
    backend=SimulatedSandbox(never=True,receipt=receipt);r=configured(runtime_factory,backend)
    async def scenario():
        await admit(r);req=command_request(r,timeout_seconds=.08);result=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert result['status']==expected and result['result_code']=='TOOL_TIMEOUT',result
        assert backend.units[0].stopped and result['timing']['cleanup_duration_ms']>0
        ticket=r.tool_store.ticket('budget:tool-parent')
        assert ticket['consumed']['max_tool_calls']==(1 if expected=='timed_out' else 0)
        assert ticket['unsettled']['max_tool_calls']==(0 if expected=='timed_out' else 1)
        assert await r.tools.execute_tool(req,r.issued_controls.tool)==result
    run(scenario())


def test_slow_poll_cannot_extend_execution_deadline(runtime_factory):
    backend=SimulatedSandbox(poll_delay=.2);r=configured(runtime_factory,backend)
    async def scenario():
        await admit(r);result=await r.tools.execute_tool(command_request(r,timeout_seconds=.06),r.issued_controls.tool)
        assert result['status']=='timed_out' and backend.units[0].stopped,result
        await asyncio.sleep(.21)
    run(scenario())


def test_start_timeout_is_unknown_and_late_unit_is_cleaned(runtime_factory):
    backend=SimulatedSandbox(start_delay=.18,never=True);r=configured(runtime_factory,backend)
    async def scenario():
        await admit(r);result=await r.tools.execute_tool(command_request(r,timeout_seconds=.05),r.issued_controls.tool)
        assert result['status']=='unknown' and result['stop_status']=='unknown'
        await asyncio.sleep(.2)
        assert backend.units[0].stopped and backend.units[0].closed
        assert r.tool_store.get(operation_ref(command_request(r,timeout_seconds=.05)))['result']==result
    run(scenario())


def test_slow_stop_is_bounded_and_late_proof_is_appended(runtime_factory):
    backend=SimulatedSandbox(never=True);r=configured(runtime_factory,backend);r.tools.cleanup_timeout=.05
    async def scenario():
        import time
        await admit(r);req=command_request(r,timeout_seconds=.15)
        task=asyncio.create_task(r.tools.execute_tool(req,r.issued_controls.tool))
        while not backend.units:await asyncio.sleep(.005)
        original=backend.units[0].stop
        def slow_stop(timeout):time.sleep(.2);return original(timeout)
        backend.units[0].stop=slow_stop
        result=await task
        assert result['status']=='unknown' and result['stop_status']=='unknown' and result['side_effects_state']=='unknown'
        assert result['timing']['cleanup_duration_ms']<150
        await asyncio.sleep(.22)
        row=r.tool_store.get(operation_ref(req))
        assert row['result']==result and any(n['kind']=='late_stop_observation' for n in row['notes'])
    run(scenario())


def test_external_cleanup_and_cross_instance_reconciliation(runtime_factory):
    backend=SimulatedSandbox(never=True);r=configured(runtime_factory,backend)
    async def scenario():
        await admit(r);req=command_request(r);task=asyncio.create_task(r.tools.execute_tool(req,r.issued_controls.tool))
        while not backend.units:await asyncio.sleep(.005)
        other=ToolExecutor(registry=r.tool_registry,store=r.tool_store,authority=r.authority,policy=r.tool_policy,artifacts=r.store,workspaces=r.tools.workspaces,control_budget=r.model_budget,sandboxes={'sandbox:test@1':backend})
        receipt=await other.stop_operation(operation_ref(req),'cancel',r.issued_controls.cleanup)
        assert receipt['stop_status']=='confirmed'
        result=await task;assert result['status']=='stopped' and result['stop_status']=='confirmed'
    run(scenario())


def test_unresolved_operation_quarantines_other_ids(runtime_factory):
    backend=SimulatedSandbox(never=True,receipt={'stop_status':'unknown','evidence_refs':[]});r=configured(runtime_factory,backend)
    async def scenario():
        await admit(r);first=await r.tools.execute_tool(command_request(r,timeout_seconds=.05),r.issued_controls.tool)
        assert first['status']=='unknown'
        second=await r.tools.execute_tool(command_request(r,operation_id='different'),r.issued_controls.tool)
        assert second['status']=='unknown' and len(backend.units)==1
        assert r.tool_store.ticket('budget:tool-parent')['reserved']['max_tool_calls']==1
    run(scenario())


@pytest.mark.parametrize('files',[{'outside/x':b'x'},{'src/report.json':b'not-json'}])
def test_undeclared_or_invalid_report_does_not_export(runtime_factory,files):
    def configure(reg,admin,r):reg.commands['command:check@1']['required_report']={'path':'src/report.json','schema_ref':'schema:plan@1'}
    backend=SimulatedSandbox(files=files);r=configured(runtime_factory,backend,configure)
    async def scenario():
        await admit(r);result=await r.tools.execute_tool(command_request(r),r.issued_controls.tool)
        assert result['result_code']=='TOOL_OUTPUT_INVALID' and not (r.workspace.root/'src/report.json').exists()
    run(scenario())


def test_truncated_logs_are_explicit_and_stop_policy_is_enforced(runtime_factory):
    def configure(reg,admin,r):reg.profiles['resources:small@1']['output_policy']='stop'
    backend=SimulatedSandbox();backend.truncated=True;r=configured(runtime_factory,backend,configure)
    async def scenario():
        await admit(r);result=await r.tools.execute_tool(command_request(r),r.issued_controls.tool)
        assert result['result_code']=='TOOL_OUTPUT_LIMIT' and len(result['output_refs'])==2 and result['exit_code']==0
    run(scenario())
