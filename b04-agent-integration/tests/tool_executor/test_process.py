import os
import sys
import time
from uuid import uuid4

import pytest
from b04.tool_executor import WindowsJobUnit
from b04.tool_executor.process import BoundedBuffer


def test_bounded_buffer_retains_prefix_and_tracks_overflow():
    buffer=BoundedBuffer(4);buffer.add(b'abc');buffer.add(b'def')
    assert buffer.get()==b'abcd' and buffer.truncated


def test_job_primitive_does_not_claim_filesystem_or_network_sandbox():
    caps=WindowsJobUnit.capabilities()
    assert not caps['filesystem_isolation'] and not caps['network_isolation']


HELPER='''import os,sys,time,subprocess
from pathlib import Path
mode=sys.argv[1]
if mode=='child':
    Path('child.pid').write_text(str(os.getpid()))
    time.sleep(30)
elif mode=='tree':
    subprocess.Popen([sys.executable,__file__,'child'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    Path('parent.done').write_text('done')
elif mode=='logs':
    os.write(1,b'x'*200000);os.write(2,b'y'*100000)
elif mode=='259':sys.exit(259)
'''


def unit(tmp_path,mode):
    helper=tmp_path/'reviewed_helper.py';helper.write_text(HELPER)
    env={k:os.environ[k] for k in ['SystemRoot','WINDIR','TEMP','TMP'] if k in os.environ}
    return WindowsJobUnit([sys.executable,'-I','-B',str(helper),mode],cwd=tmp_path,environment=env,unit_ref='b04-test-'+uuid4().hex,stdout_limit=1024,stderr_limit=512)


@pytest.mark.skipif(os.name!='nt',reason='Windows Job Object process-tree integration')
def test_actual_descendant_stays_tracked_after_parent_exit_and_is_stopped(tmp_path):
    process=unit(tmp_path,'tree')
    try:
        end=time.monotonic()+5
        while not (tmp_path/'child.pid').exists() and time.monotonic()<end:time.sleep(.01)
        assert (tmp_path/'parent.done').exists() and (tmp_path/'child.pid').exists()
        assert process.poll() is None and process.active_processes()>0
        receipt=process.stop(2)
        assert receipt['stop_status']=='confirmed' and receipt['evidence_refs'] and process.active_processes()==0
    finally:process.close()


@pytest.mark.skipif(os.name!='nt',reason='Windows Job Object process integration')
@pytest.mark.parametrize('mode,code',[('logs',0),('259',259)])
def test_actual_process_exit_and_bounded_separate_streams(tmp_path,mode,code):
    process=unit(tmp_path,mode)
    try:
        end=time.monotonic()+5;result=None
        while result is None and time.monotonic()<end:result=process.poll();time.sleep(.01)
        assert result is not None and result['exit_code']==code
        if mode=='logs':
            assert result['stdout']==b'x'*1024 and result['stderr']==b'y'*512
            assert result['stdout_truncated'] and result['stderr_truncated']
    finally:process.close()
