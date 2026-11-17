"""Local Docker Linux sandbox: pinned image, scoped snapshot, tmpfs and no network.

No daemon is started and no image is pulled. A missing local engine/image is an
explicit unsupported capability. Docker itself remains a deployment dependency.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path,PurePosixPath

from .contracts import ToolExecutorError
from .files import relative_parts

# Trusted PID-1 control code. Untrusted work runs under uid/gid 1000, cannot modify
# the root-only control mount, and is killed before the completion marker is sealed.
SUPERVISOR=r'''
import os,sys,json,base64,subprocess,threading,signal,time,shutil
s=json.loads(base64.b64decode(sys.argv[1]));ctl='/b04-control'
for rel in s['write_paths']:
    src='/b04-input/'+rel;dst='/workspace/'+rel
    if os.path.isdir(src):shutil.copytree(src,dst,dirs_exist_ok=True)
    for parent,dirs,files in os.walk(dst):
        os.chown(parent,1000,1000);os.chmod(parent,0o700)
        for name in files:os.chown(parent+'/'+name,1000,1000);os.chmod(parent+'/'+name,0o600)
os.chown('/tmp',1000,1000);os.chmod('/tmp',0o700)
def lower():os.setgroups([]);os.setgid(1000);os.setuid(1000)
p=subprocess.Popen(s['argv'],cwd='/workspace',env=s['environment'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,preexec_fn=lower,start_new_session=True)
truncated={'stdout':False,'stderr':False};limit_hit=threading.Event()
def drain(stream,name,limit):
    kept=0
    with open(ctl+'/'+name,'wb') as out:
        while True:
            block=stream.read(4096)
            if not block:break
            part=block[:max(0,limit-kept)];out.write(part);kept+=len(part)
            if len(part)!=len(block):truncated[name]=True;limit_hit.set()
threads=[threading.Thread(target=drain,args=(p.stdout,'stdout',s['stdout_limit'])),threading.Thread(target=drain,args=(p.stderr,'stderr',s['stderr_limit']))]
for t in threads:t.start()
while p.poll() is None:
    if limit_hit.is_set() and s['output_policy']=='stop':
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    time.sleep(.01)
code=p.wait()
def remaining():
    while True:
        try:
            if os.waitpid(-1,os.WNOHANG)[0]==0:break
        except ChildProcessError:break
    found=[]
    for pid in os.listdir('/proc'):
        if pid.isdigit():
            try:
                if os.stat('/proc/'+pid).st_uid==1000:found.append(int(pid))
            except FileNotFoundError:pass
    return found
end=time.monotonic()+2
while remaining() and time.monotonic()<end:
    for pid in remaining():
        try:os.kill(pid,signal.SIGKILL)
        except ProcessLookupError:pass
    time.sleep(.01)
for t in threads:t.join(.5)
state={'exit_code':code,'stdout_truncated':truncated['stdout'],'stderr_truncated':truncated['stderr'],'tree_stopped':not remaining() and not any(t.is_alive() for t in threads)}
with open(ctl+'/state.tmp','w') as out:json.dump(state,out);out.flush();os.fsync(out.fileno())
os.replace(ctl+'/state.tmp',ctl+'/state.json')
while True:time.sleep(10)
'''


class DockerSandboxBackend:
    def __init__(self,*,docker_executable,endpoint,private_root):
        self.executable=str(Path(docker_executable).resolve(strict=True))
        if not (endpoint.startswith('npipe:////./pipe/') or endpoint.startswith('unix:///')):raise ValueError("Only an explicitly local Docker endpoint is allowed")
        self.endpoint=endpoint;self.private_root=Path(private_root).resolve();self.private_root.mkdir(parents=True,exist_ok=True)
        self.config_dir=self.private_root/'docker-config';self.config_dir.mkdir(exist_ok=True)
        self._units={}

    def describe(self):
        return dict(kind="docker-linux",execution_modes=["mock","live"],filesystem_isolation=True,network_isolation=True,process_tree_stop=True,
                    memory_limit=True,pid_limit=True,tmpfs_limit=True,available=self.available())

    def _run(self,args,*,limit=1024*1024,timeout=5):
        # Only the local client API uses this function; argv is never shell text.
        env={k:os.environ[k] for k in ['SystemRoot','WINDIR','TEMP','TMP'] if k in os.environ}
        process=subprocess.Popen([self.executable,'--host',self.endpoint,'--config',str(self.config_dir),*args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),shell=False)
        from .process import BoundedBuffer
        import threading,time
        out,err=BoundedBuffer(limit),BoundedBuffer(8192)
        def read(stream,buffer):
            while True:
                data=stream.read(65536)
                if not data:break
                buffer.add(data)
        threads=[threading.Thread(target=read,args=(process.stdout,out),daemon=True),threading.Thread(target=read,args=(process.stderr,err),daemon=True)]
        for t in threads:t.start()
        end=time.monotonic()+timeout
        try:
            while process.poll() is None:
                if out.truncated or time.monotonic()>end:process.kill();raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="sandbox_api_limit")
                time.sleep(.005)
            for t in threads:t.join(.5)
            if any(t.is_alive() for t in threads) or out.truncated:raise ToolExecutorError("TOOL_OUTPUT_LIMIT",stage="sandbox_api_output")
            if process.returncode!=0:raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="local_sandbox_unavailable")
            return out.get()
        finally:
            if process.poll() is None:process.kill()
            process.wait(timeout=2)
            process.stdout.close();process.stderr.close()

    def available(self):
        try:return self._run(['info','--format','{{.OSType}}'],limit=100,timeout=2).strip()==b'linux'
        except (OSError,ToolExecutorError,subprocess.SubprocessError):return False

    def verify(self,spec):
        runtime=spec['runtime']
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',runtime['image_id']):raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="pinned_image_required")
        if not self.available():raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="local_sandbox_unavailable")
        data=json.loads(self._run(['image','inspect',runtime['image_id']]))
        if len(data)!=1 or data[0]['Id']!=runtime['image_id'] or data[0]['Os']!='linux':raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="cached_linux_image_required")
        for p in spec['write_paths']:
            relative_parts(p)
        paths=spec['write_paths']
        if any(a==b or a.startswith(b+'/') or b.startswith(a+'/') for i,a in enumerate(paths) for b in paths[i+1:]):raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="overlapping_write_mounts")

    def start(self,spec,unit_ref):
        self.verify(spec)
        if not re.fullmatch(r'b04-[a-f0-9]{32}',unit_ref):raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="unit_identity")
        root=Path(tempfile.mkdtemp(prefix=unit_ref+'-',dir=self.private_root));view=root/'view';view.mkdir()
        self._units[unit_ref]=root
        for path,body in spec['input_files'].items():
            relative_parts(path);target=view/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
        for path in spec['write_paths']:(view/path).mkdir(parents=True,exist_ok=True)
        for parent,dirs,files in os.walk(view):
            os.chmod(parent,0o755)
            for name in files:os.chmod(Path(parent)/name,0o644)
        resource=spec['resource'];control_size=max(1024*1024,resource['stdout_bytes']+resource['stderr_bytes']+65536)
        output_size=resource['filesystem_bytes']-control_size-resource['tmp_bytes']
        if output_size<=0:raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="filesystem_quota_partition")
        payload=dict(argv=spec['argv'],environment=spec['environment'],write_paths=spec['write_paths'],stdout_limit=resource['stdout_bytes'],stderr_limit=resource['stderr_bytes'],output_policy=resource['output_policy'])
        encoded=base64.b64encode(json.dumps(payload).encode()).decode('ascii')
        args=['create','--pull','never','--name',unit_ref,'--label','b04.unit='+unit_ref,'--network','none','--read-only','--cap-drop','ALL','--cap-add','CHOWN','--cap-add','SETUID','--cap-add','SETGID','--cap-add','KILL',
              '--security-opt','no-new-privileges=true','--pids-limit',str(resource['max_processes']),'--memory',str(resource['memory_bytes']),'--memory-swap',str(resource['memory_bytes']),
              '--cpus',str(resource['cpus']),'--user','0:0','--workdir','/workspace','--log-driver','none',
              '--mount','type=bind,source='+str(view)+',target=/workspace,readonly',
              '--mount','type=bind,source='+str(view)+',target=/b04-input,readonly',
              '--tmpfs','/b04-control:rw,noexec,nosuid,nodev,size='+str(control_size)+',mode=0700',
              '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size='+str(resource['tmp_bytes'])+',mode=0700']
        if ',' in str(view):raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="mount_path")
        for path in spec['write_paths']:
            args+=['--tmpfs','/workspace/'+path+':rw,noexec,nosuid,nodev,size='+str(max(1,output_size//max(1,len(spec['write_paths']))))+',mode=0700']
        args+=['--entrypoint',spec['runtime']['supervisor_python'],spec['runtime']['image_id'],'-I','-B','-c',SUPERVISOR,encoded]
        spec['guard']();self._run(args,limit=4096)
        unit=DockerUnit(self,unit_ref,spec,root)
        try:spec['guard']();self._run(['start',unit_ref],limit=4096);return unit
        except BaseException:
            unit.stop(2);unit.close();raise

    def stop_existing(self,unit_ref,timeout_seconds):
        return DockerUnit(self,unit_ref,None,self._units.get(unit_ref)).stop(timeout_seconds)


class DockerUnit:
    def __init__(self,backend,unit_ref,spec,root):self.backend,self.unit_ref,self.spec,self.root=backend,unit_ref,spec,root;self._result=None;self._closed=False

    def _inspect(self):
        info=json.loads(self.backend._run(['inspect',self.unit_ref],limit=32768))[0]
        if info['Config']['Labels'].get('b04.unit')!=self.unit_ref:raise ToolExecutorError("TOOL_RESULT_UNKNOWN",stage="sandbox_unit_identity",stop_status="unknown")
        return info

    @staticmethod
    def _tar(body,limit,max_files):
        files={};total=0
        with tarfile.open(fileobj=io.BytesIO(body),mode='r:*') as archive:
            for member in archive:
                parts=PurePosixPath(member.name).parts
                if not parts or member.name.startswith('/') or '..' in parts or member.issym() or member.islnk() or not (member.isdir() or member.isfile()):raise ToolExecutorError("TOOL_OUTPUT_INVALID",stage="sandbox_archive_member")
                if member.isdir():continue
                total+=member.size
                if total>limit or len(files)>=max_files:raise ToolExecutorError("TOOL_OUTPUT_LIMIT",stage="sandbox_export")
                data=archive.extractfile(member).read(member.size+1)
                if len(data)!=member.size:raise ToolExecutorError("TOOL_OUTPUT_INVALID")
                name='/'.join(parts)
                if name in files:raise ToolExecutorError("TOOL_OUTPUT_INVALID")
                files[name]=data
        return files

    def _copy(self,path,limit,max_files=1000):
        body=self.backend._run(['cp',self.unit_ref+':'+path,'-'],limit=limit+max_files*2048+32768)
        return self._tar(body,limit,max_files)

    def poll(self):
        if self._result is not None:return self._result
        info=self._inspect()
        if not info['State']['Running']:raise ToolExecutorError("TOOL_RESULT_UNKNOWN",stage="sandbox_exited_without_completion",stop_status="confirmed")
        try:state_files=self._copy('/b04-control/state.json',4096,1)
        except ToolExecutorError as fault:
            if fault.stage=='local_sandbox_unavailable':return None
            raise
        state=json.loads(next(iter(state_files.values())))
        if not state['tree_stopped']:raise ToolExecutorError("TOOL_RESULT_UNKNOWN",stage="sandbox_descendants",stop_status="unknown")
        resource=self.spec['resource'];logs={}
        for name in ['stdout','stderr']:logs[name]=next(iter(self._copy('/b04-control/'+name,resource[name+'_bytes'],1).values()))
        files={}
        for path in self.spec['write_paths']:
            exported=self._copy('/workspace/'+path,resource['max_output_bytes'],resource['max_files'])
            for name,body in exported.items():
                parts=name.split('/');rel=path+('/'+'/'.join(parts[1:]) if len(parts)>1 else '')
                if rel in files:raise ToolExecutorError("TOOL_OUTPUT_INVALID",stage="duplicate_sandbox_export")
                files[rel]=body
        if sum(map(len,files.values()))>resource['max_output_bytes']:raise ToolExecutorError("TOOL_OUTPUT_LIMIT")
        receipt=self.stop(2)
        if receipt['stop_status']!='confirmed':raise ToolExecutorError("TOOL_RESULT_UNKNOWN",stage="sandbox_shutdown",stop_status="unknown")
        self._result=dict(exit_code=state['exit_code'],**logs,stdout_truncated=state['stdout_truncated'],stderr_truncated=state['stderr_truncated'],files=files)
        return self._result

    def stop(self,timeout_seconds):
        try:
            info=self._inspect()
            if info['State']['Running']:self.backend._run(['kill',self.unit_ref],timeout=max(.1,timeout_seconds),limit=4096)
            if self._inspect()['State']['Running']:return dict(stop_status="unknown",evidence_refs=[])
            return dict(stop_status="confirmed",evidence_refs=['docker-unit-stopped:'+self.unit_ref])
        except (ToolExecutorError,OSError,subprocess.SubprocessError):return dict(stop_status="unknown",evidence_refs=[])

    def close(self):
        if self._closed:return
        self._closed=True
        try:self.backend._run(['rm','-f',self.unit_ref],limit=4096)
        except (ToolExecutorError,OSError):return
        if self.root is not None:
            # Only the exact owned TemporaryDirectory is removed, never a workspace.
            root=self.root.resolve();parent=self.backend.private_root.resolve()
            if root.parent==parent and root.name.startswith(self.unit_ref+'-'):shutil.rmtree(root)
