import io
import json
import os
from pathlib import Path
import tarfile
from uuid import uuid4
import time

import pytest
from b04.tool_executor import ToolExecutorError,DockerSandboxBackend
from b04.tool_executor.sandbox import DockerUnit


def archive(name,body=b'data',kind=tarfile.REGTYPE):
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w') as tar:
        item=tarfile.TarInfo(name);item.type=kind;item.linkname='/outside';item.size=len(body) if kind==tarfile.REGTYPE else 0
        tar.addfile(item,io.BytesIO(body) if item.isfile() else None)
    return output.getvalue()


@pytest.mark.parametrize('name,kind',[('../escape',tarfile.REGTYPE),('/absolute',tarfile.REGTYPE),('link',tarfile.SYMTYPE),('hardlink',tarfile.LNKTYPE),('device',tarfile.CHRTYPE)])
def test_sandbox_export_rejects_unsafe_tar_members(name,kind):
    with pytest.raises(ToolExecutorError,match='TOOL_OUTPUT_INVALID'):DockerUnit._tar(archive(name,kind=kind),1024,10)


def test_sandbox_export_is_bounded_and_never_extracts_paths():
    assert DockerUnit._tar(archive('src/result.json',b'{}'),1024,1)=={'src/result.json':b'{}'}
    with pytest.raises(ToolExecutorError,match='TOOL_OUTPUT_LIMIT'):DockerUnit._tar(archive('src/result',b'x'*20),10,1)


class RecordingDocker(DockerSandboxBackend):
    def __init__(self,root):
        # No CLI or daemon; this test inspects control-plane argv only.
        self.private_root=root;root.mkdir();self._units={};self.commands=[]
    def available(self):return True
    def _run(self,args,**kwargs):
        self.commands.append(args)
        if args[:2]==['image','inspect']:return json.dumps([{'Id':'sha256:'+'1'*64,'Os':'linux'}]).encode()
        if args[0]=='inspect':return json.dumps([{'Config':{'Labels':{'b04.unit':args[1]}},'State':{'Running':False}}]).encode()
        return b'created'


def spec():
    return dict(runtime=dict(image_id='sha256:'+'1'*64,executable='/usr/local/bin/python',argv_prefix=[],supervisor_python='/usr/local/bin/python'),argv=['/usr/local/bin/python','/opt/check.py'],environment={'LANG':'C.UTF-8'},read_paths=['inputs'],write_paths=['src'],input_files={'inputs/readme':b'scoped','src/seed':b'seed'},guard=lambda:None,
        resource=dict(max_processes=16,memory_bytes=128*1024*1024,filesystem_bytes=16*1024*1024,tmp_bytes=1024*1024,cpus=1,max_snapshot_bytes=1024*1024,max_output_bytes=1024*1024,max_files=100,stdout_bytes=1024,stderr_bytes=512,output_policy='truncate'))


def test_docker_control_plane_uses_pinned_image_and_explicit_isolation(tmp_path):
    backend=RecordingDocker(tmp_path/'sandbox');s=spec();unit=backend.start(s,'b04-'+uuid4().hex)
    try:
        args=next(a for a in backend.commands if a[0]=='create')
        for name,value in [('--network','none'),('--read-only',None),('--cap-drop','ALL'),('--security-opt','no-new-privileges=true'),('--pull','never'),('--user','0:0'),('--pids-limit','16')]:
            assert name in args and (value is None or args[args.index(name)+1]==value)
        assert not any('docker.sock' in a for a in args)
        assert unit.root.parent==backend.private_root and (unit.root/'view/inputs/readme').read_bytes()==b'scoped'
        assert '--tmpfs' in args and s['runtime']['image_id'] in args
    finally:unit.close()


@pytest.mark.parametrize('image',['python:latest','python:3.11','sha256:bad'])
def test_mutable_or_invalid_images_are_refused(tmp_path,image):
    backend=RecordingDocker(tmp_path/'sandbox');s=spec();s['runtime']['image_id']=image
    with pytest.raises(ToolExecutorError,match='TOOL_PROFILE_UNSUPPORTED'):backend.verify(s)


def test_unavailable_local_engine_is_not_started_or_replaced(tmp_path):
    backend=RecordingDocker(tmp_path/'sandbox');backend.available=lambda:False
    with pytest.raises(ToolExecutorError,match='TOOL_PROFILE_UNSUPPORTED'):backend.verify(spec())
    assert backend.commands==[]


def test_stop_requires_owned_unit_identity(tmp_path):
    backend=RecordingDocker(tmp_path/'sandbox')
    backend._run=lambda *args,**kw:json.dumps([{'Config':{'Labels':{'b04.unit':'other'}},'State':{'Running':False}}]).encode()
    assert backend.stop_existing('b04-'+uuid4().hex,.1)['stop_status']=='unknown'


@pytest.mark.skipif(not os.environ.get('B04_TEST_DOCKER_IMAGE'),reason='Requires explicitly configured cached pinned Linux image and running local Docker; never pulls images or starts Docker')
def test_optional_real_docker_filesystem_network_and_descendant_isolation(tmp_path):
    executable=os.environ['B04_TEST_DOCKER_EXE'];endpoint=os.environ['B04_TEST_DOCKER_ENDPOINT']
    backend=DockerSandboxBackend(docker_executable=executable,endpoint=endpoint,private_root=tmp_path/'docker-private')
    s=spec();s['runtime']['image_id']=os.environ['B04_TEST_DOCKER_IMAGE']
    # Fixed reviewed probe bypasses CommandDriver only for backend integration QA.
    probe='''import json,subprocess,sys,os
result={}
for path in ['/workspace/inputs/readme','/outside']:
    try:open(path,'wb').write(b'escape');result[path]=True
    except OSError:result[path]=False
routes=open('/proc/net/route').read().splitlines()[1:]
result['has_default_route']=any(line.split()[1]=='00000000' for line in routes)
subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
open('/workspace/src/result.json','w').write(json.dumps(result))
os.write(1,b'x'*100000);os.write(2,b'y'*100000)
'''
    s['argv']=['/usr/local/bin/python','-I','-B','-c',probe]
    backend.verify(s);unit=backend.start(s,'b04-'+uuid4().hex)
    try:
        result=None;end=time.monotonic()+15
        while result is None and time.monotonic()<end:result=unit.poll();time.sleep(.01)
        assert result is not None and result['exit_code']==0
        evidence=json.loads(result['files']['src/result.json'])
        assert not any(evidence.values())
        assert result['stdout']==b'x'*1024 and result['stderr']==b'y'*512
        assert result['stdout_truncated'] and result['stderr_truncated']
    finally:unit.stop(2);unit.close()
