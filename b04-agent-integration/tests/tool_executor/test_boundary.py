import asyncio
import copy
import pytest
from b04.tool_executor import ToolExecutorError
from b04.tool_executor.testing import tool_request
from .support import run,admit,call,write_request,command_request,SimulatedSandbox


@pytest.mark.parametrize('value',[float('nan'),float('inf'),{1,2}])
def test_non_json_request_is_a_typed_boundary_error(runtime,value):
    request=tool_request(runtime);request['arguments']['invalid']=value
    with pytest.raises(ToolExecutorError,match='TOOL_REQUEST_INVALID'):run(call(runtime,request))


@pytest.mark.parametrize('field',['protocol_version','tool_contract_version','origin','timeout_seconds'])
def test_representable_invalid_request_returns_complete_result(runtime,field):
    request=tool_request(runtime)
    if field=='timeout_seconds':request[field]=-1
    elif field=='origin':request[field]['model_call_id']='unexpected'
    else:request[field]='unsupported'
    result=run(call(runtime,request))
    assert result['status']=='rejected' and result['result_code']=='TOOL_REQUEST_INVALID'
    assert result['protocol_version']=='b04.exec.v0.2' and result['tool_contract_version']=='b04.tool.v0.1'
    assert runtime.tool_store.diagnostic_record(result['operation_record_ref'])


def test_binary_file_read_does_not_force_text_decode(runtime):
    (runtime.workspace.root/'src/binary').write_bytes(b'\xff\x00\x81')
    result=run(call(runtime,tool_request(runtime,'read_file',dict(path='src/binary',encoding='binary'))))
    assert result['status']=='completed' and result['payload']['text'] is None and result['payload']['encoding']=='binary'


def test_invalid_utf8_file_does_not_invent_decoded_text(runtime):
    (runtime.workspace.root/'src/text').write_bytes(b'\xff')
    result=run(call(runtime,tool_request(runtime,'read_file',dict(path='src/text',encoding='utf-8'))))
    assert result['result_code']=='TOOL_OUTPUT_INVALID' and result['payload'] is None


def test_large_file_read_requires_reference_instead_of_false_complete_inline(runtime):
    body=b'x'*70000;(runtime.workspace.root/'src/large').write_bytes(body)
    result=run(call(runtime,tool_request(runtime,'read_file',dict(path='src/large'))))
    payload=result['payload']
    assert result['status']=='completed' and payload['text'] is None and payload['complete'] and not payload['inline_complete']
    assert runtime.store.read_object(payload['content_ref'],runtime.issued_controls.observe.context)['body']==body


def test_log_truncation_is_bounded_even_if_backend_returns_too_many_bytes(runtime_factory):
    backend=SimulatedSandbox();backend.stdout=b'x'*10000;backend.stderr=b'y'*9000
    r=runtime_factory(auto_start=False,sandboxes={'sandbox:test@1':backend})
    async def scenario():
        await admit(r);result=await r.tools.execute_tool(command_request(r),r.issued_controls.tool)
        assert result['status']=='completed' and result['payload']['stdout_truncated'] and result['payload']['stderr_truncated']
        for name in ['stdout','stderr']:assert len(r.store.read_object(result['payload'][name+'_ref'],r.issued_controls.observe.context)['body'])==4096
    run(scenario())


def test_caller_cancellation_stops_controlled_unit(runtime_factory):
    backend=SimulatedSandbox(never=True);r=runtime_factory(auto_start=False,sandboxes={'sandbox:test@1':backend})
    async def scenario():
        await admit(r);task=asyncio.create_task(r.tools.execute_tool(command_request(r),r.issued_controls.tool))
        while not backend.units:await asyncio.sleep(.005)
        task.cancel();result=await task
        assert result['status']=='stopped' and result['stop_status']=='confirmed' and backend.units[0].stopped
    run(scenario())
