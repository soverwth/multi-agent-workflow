import asyncio
import copy
import threading
import time
from b04.model_adapter.contracts import invocation_ref,digest
from b04.tool_executor.contracts import operation_ref
from b04.tool_executor.drivers import sha
from b04.tool_executor.testing import tool_request


def run(awaitable):return asyncio.run(awaitable)


async def admit(r):
    receipt=await r.runner.invoke_agent(r.envelope)
    assert receipt['accepted'],receipt
    return receipt


async def call(r,request):
    await admit(r)
    return await r.tools.execute_tool(request,r.issued_controls.tool)


def write_request(r,body=b'hello\r\n',*,path='src/main.txt',mode='create',expected=None,operation_id='write:1'):
    ref=invocation_ref(r.envelope);op=dict(invocation_ref=ref,operation_id=operation_id)
    staged=r.store.stage_draft_content(ref,op,digest(body.hex()),body,'text/plain',r.issued_controls.tool.context)
    return tool_request(r,'write_file',dict(path=path,mode=mode,content_ref=staged['content_ref'],expected_content_sha256=sha(body),encoding='utf-8',expected_target_sha256=expected),operation_id=operation_id)


class SimulatedUnit:
    """Mock only: no host command is launched and no isolation claim is live."""
    def __init__(self,backend,spec,unit_ref):
        self.backend,self.spec,self.unit_ref=backend,spec,unit_ref
        self.stopped=False;self.closed=False;self.created=time.monotonic()
    def poll(self):
        if self.backend.poll_delay:time.sleep(self.backend.poll_delay)
        if self.backend.never or time.monotonic()-self.created<self.backend.delay:return None
        files={p:b for p,b in self.spec['input_files'].items() if any(p==w or p.startswith(w+'/') for w in self.spec['write_paths'])}
        files.update(self.backend.files)
        return dict(exit_code=self.backend.exit_code,stdout=self.backend.stdout,stderr=self.backend.stderr,
                    stdout_truncated=self.backend.truncated,stderr_truncated=False,files=files)
    def stop(self,timeout_seconds):
        self.stopped=True
        return copy.deepcopy(self.backend.receipt) if self.backend.receipt is not None else dict(stop_status='confirmed',evidence_refs=['fixture-stopped:'+self.unit_ref])
    def close(self):self.closed=True


class SimulatedSandbox:
    def __init__(self,*,files=None,exit_code=0,never=False,delay=0,start_delay=0,poll_delay=0,receipt=None,capability_override=None):
        self.files=files or {};self.exit_code=exit_code;self.never=never;self.delay=delay;self.start_delay=start_delay;self.poll_delay=poll_delay
        self.receipt=receipt;self.capability_override=capability_override or {};self.units=[];self.stdout=b'check stdout';self.stderr=b'check stderr';self.truncated=False
        self.started=threading.Event()
    def describe(self):
        return dict(kind='test-double-only',execution_modes=['mock'],filesystem_isolation=True,network_isolation=True,process_tree_stop=True,memory_limit=True,pid_limit=True,tmpfs_limit=True,**self.capability_override) if not self.capability_override else {**dict(kind='test-double-only',execution_modes=['mock'],filesystem_isolation=True,network_isolation=True,process_tree_stop=True,memory_limit=True,pid_limit=True,tmpfs_limit=True),**self.capability_override}
    def verify(self,spec):pass
    def start(self,spec,unit_ref):
        self.started.set()
        if self.start_delay:time.sleep(self.start_delay)
        unit=SimulatedUnit(self,spec,unit_ref);self.units.append(unit);return unit
    def stop_existing(self,unit_ref,timeout_seconds):
        return next(u for u in self.units if u.unit_ref==unit_ref).stop(timeout_seconds)


def command_request(r,**overrides):
    return tool_request(r,'run_command',dict(command_profile_ref='command:check@1',parameters={'target':'src'}),**overrides)
