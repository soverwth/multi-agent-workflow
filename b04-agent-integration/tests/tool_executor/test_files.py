import os
import pytest
from b04.tool_executor import ToolExecutorError,SecureWorkspace
from b04.tool_executor.files import relative_parts
from b04.tool_executor.drivers import sha
from b04.tool_executor.testing import tool_request
from b04.tool_executor.contracts import operation_ref,validate,TOOL_RESULT_SCHEMA
from .support import run,admit,call,write_request


@pytest.mark.parametrize('path',['../x','/x','src/../x','src//x','src/./x','C:/x',r'\\server\x','src/a:stream','src/a.','src/a ','src/NUL.txt','src/COM1','src/a~1','src/a\x00','src/a\n','src/a?','src/a\\b'])
def test_path_ambiguities_are_rejected(path):
    with pytest.raises(ToolExecutorError,match='TOOL_PATH_INVALID'):relative_parts(path)


def test_create_exact_utf8_bytes_and_replay_without_overwrite(runtime):
    async def scenario():
        r=runtime;await admit(r);body=b'\xef\xbb\xbfhello\r\n\xe4\xb8\xad\xe6\x96\x87\n';req=write_request(r,body)
        result=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert result['status']=='completed',result
        validate(result,TOOL_RESULT_SCHEMA)
        assert (r.workspace.root/'src/main.txt').read_bytes()==body
        assert result['changes']==[dict(path='src/main.txt',change_type='created',before_sha256=None,after_sha256=sha(body))]
        assert await r.tools.execute_tool(req,r.issued_controls.tool)==result
        assert r.tool_store.ticket('budget:tool-parent')['consumed']['max_tool_calls']==1
        snapshot=await r.tools.get_operation(operation_ref(req),r.issued_controls.observe)
        assert await r.tools.read_result(operation_ref(req),snapshot['result_ref'],r.issued_controls.observe)==result
    run(scenario())


@pytest.mark.parametrize('mode,expected,success',[('create',None,False),('replace',None,False),('replace','0'*64,False),('replace',sha(b'old'),True)])
def test_preconditions_and_conditional_replace(runtime,mode,expected,success):
    async def scenario():
        r=runtime;await admit(r);target=r.workspace.root/'src/main.txt';target.write_bytes(b'old')
        result=await r.tools.execute_tool(write_request(r,b'new',mode=mode,expected=expected),r.issued_controls.tool)
        assert (result['status']=='completed')==success,result
        assert target.read_bytes()==(b'new' if success else b'old')
        if success:assert result['changes'][0]['before_sha256']==sha(b'old')
    run(scenario())


def test_target_change_between_read_and_commit_does_not_overwrite(runtime):
    async def scenario():
        r=runtime;await admit(r);target=r.workspace.root/'src/main.txt';target.write_bytes(b'old')
        r.workspace.before_commit=lambda path:path.write_bytes(b'concurrent')
        result=await r.tools.execute_tool(write_request(r,b'new',mode='replace',expected=sha(b'old')),r.issued_controls.tool)
        assert result['result_code']=='TOOL_FILE_CONFLICT' and target.read_bytes()==b'concurrent'
        assert not list(target.parent.glob('.b04-*'))
    run(scenario())


@pytest.mark.parametrize('change',['hash','foreign','inline','kind'])
def test_untrusted_content_is_not_written(runtime,change):
    async def scenario():
        r=runtime;await admit(r);req=write_request(r)
        if change=='hash':req['arguments']['expected_content_sha256']='0'*64
        elif change=='foreign':req['arguments']['content_ref']='other/drafts/x'
        elif change=='inline':req['arguments']['content']='inline'
        else:
            from b04.model_adapter.contracts import canonical
            meta=r.store.read_object(req['arguments']['content_ref'],r.issued_controls.tool.context)['metadata'];meta['kind']='other'
            r.store._db.execute('UPDATE runner_objects SET metadata=? WHERE ref=?',(canonical(meta),meta['artifact_ref']))
        result=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert result['status']!='completed' and not (r.workspace.root/'src/main.txt').exists()
    run(scenario())


def test_file_read_range_references_actual_bytes(runtime):
    r=runtime;body=b'zero\r\none\r\n';(r.workspace.root/'src/file').write_bytes(body)
    result=run(call(r,tool_request(r,'read_file',dict(path='src/file',start_byte=6,end_byte=9,expected_sha256=sha(body)))))
    assert result['status']=='completed',result
    payload=result['payload'];assert payload['text']=='one' and not payload['complete'] and payload['full_sha256']==sha(body) and payload['range_sha256']==sha(b'one')
    assert r.store.read_object(payload['content_ref'],r.issued_controls.observe.context)['body']==b'one'


@pytest.mark.parametrize('args',[dict(path='other/file'),dict(path='src/file',start_byte=-1),dict(path='src/file',end_byte=100),dict(path='src/file',expected_sha256='0'*64),dict(path='src/file',encoding='gbk')])
def test_read_constraints(runtime,args):
    (runtime.workspace.root/'src/file').write_bytes(b'abc')
    assert run(call(runtime,tool_request(runtime,'read_file',args)))['status']!='completed'


def test_hardlink_cannot_bypass_workspace_identity(runtime,tmp_path):
    outside=tmp_path/'outside';outside.write_bytes(b'secret');os.link(outside,runtime.workspace.root/'src/link')
    result=run(call(runtime,tool_request(runtime,'read_file',dict(path='src/link'))))
    assert result['result_code']=='TOOL_PATH_INVALID' and result['side_effects_state']=='none'


def test_junction_or_symlink_does_not_escape_workspace(runtime,tmp_path):
    target=tmp_path/'outside';target.mkdir();(target/'secret').write_bytes(b'secret')
    link=runtime.workspace.root/'src/link'
    if os.name=='nt':
        import subprocess
        p=subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(link),str(target)],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        assert p.returncode==0
    else:link.symlink_to(target,target_is_directory=True)
    result=run(call(runtime,tool_request(runtime,'read_file',dict(path='src/link/secret'))))
    assert result['result_code']=='TOOL_PATH_INVALID'


def test_missing_parent_is_explicit_and_has_no_directory_side_effect(runtime):
    async def scenario():
        r=runtime;await admit(r);req=write_request(r,path='src/missing/file')
        result=await r.tools.execute_tool(req,r.issued_controls.tool)
        assert result['result_code']=='TOOL_PATH_INVALID' and not (r.workspace.root/'src/missing').exists()
    run(scenario())


def test_automatic_directory_creation_requires_a_separate_capability(runtime):
    with pytest.raises(ToolExecutorError,match='TOOL_PROFILE_UNSUPPORTED'):
        SecureWorkspace(runtime.workspace.root,project_id='x',read_paths=['src'],write_paths=['src'],exclusive_lease_ref='x',allow_mkdir=True)
