"""Windows process-tree primitive. It deliberately claims no FS/network sandbox.

Tool commands requiring isolation use a verified SandboxBackend instead. This
primitive is also exercised with fixed, reviewed test helpers for stop evidence.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time

from .contracts import ToolExecutorError


class BoundedBuffer:
    def __init__(self,limit):self.limit=limit;self.body=bytearray();self.truncated=False;self._lock=threading.Lock()
    def add(self,data):
        with self._lock:
            room=max(0,self.limit-len(self.body));self.body.extend(data[:room]);self.truncated|=len(data)>room
    def get(self):
        with self._lock:return bytes(self.body)


if os.name=='nt':
    import _winapi
    import ctypes
    import msvcrt
    from ctypes import wintypes as w
    K=ctypes.WinDLL('kernel32',use_last_error=True)
    class IO(ctypes.Structure):
        _fields_=[(n,ctypes.c_ulonglong) for n in ['ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount']]
    class LIMIT(ctypes.Structure):
        _fields_=[('ProcessTime',ctypes.c_longlong),('JobTime',ctypes.c_longlong),('Flags',w.DWORD),('MinWorkingSet',ctypes.c_size_t),('MaxWorkingSet',ctypes.c_size_t),('ActiveProcessLimit',w.DWORD),('Affinity',ctypes.c_size_t),('Priority',w.DWORD),('Scheduling',w.DWORD)]
    class EXTENDED(ctypes.Structure):
        _fields_=[('Basic',LIMIT),('Io',IO),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemory',ctypes.c_size_t),('PeakJobMemory',ctypes.c_size_t)]
    class ACCOUNTING(ctypes.Structure):
        _fields_=[(n,ctypes.c_longlong) for n in ['UserTime','KernelTime','PeriodUser','PeriodKernel']]+[(n,w.DWORD) for n in ['PageFaults','TotalProcesses','ActiveProcesses','TerminatedProcesses']]
    K.CreateJobObjectW.argtypes=[w.LPVOID,w.LPCWSTR];K.CreateJobObjectW.restype=w.HANDLE
    K.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD];K.SetInformationJobObject.restype=w.BOOL
    K.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];K.AssignProcessToJobObject.restype=w.BOOL
    K.QueryInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD,w.LPVOID];K.QueryInformationJobObject.restype=w.BOOL
    K.TerminateJobObject.argtypes=[w.HANDLE,w.UINT];K.TerminateJobObject.restype=w.BOOL
    K.ResumeThread.argtypes=[w.HANDLE];K.ResumeThread.restype=w.DWORD
    K.CloseHandle.argtypes=[w.HANDLE];K.CloseHandle.restype=w.BOOL


class WindowsJobUnit:
    @staticmethod
    def capabilities():return dict(process_tree_stop=os.name=='nt',filesystem_isolation=False,network_isolation=False)

    def __init__(self,argv,*,cwd,environment,unit_ref,stdout_limit=65536,stderr_limit=65536,max_processes=16,memory_bytes=256*1024*1024):
        if os.name!='nt':raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="windows_job")
        self.unit_ref=unit_ref;self.stdout=BoundedBuffer(stdout_limit);self.stderr=BoundedBuffer(stderr_limit)
        self.job=K.CreateJobObjectW(None,'Local\\'+unit_ref)
        if not self.job:raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="create_job")
        self.process=None;self.threads=[];self._closed=False
        limits=EXTENDED();limits.Basic.Flags=0x2000|0x8|0x200;limits.Basic.ActiveProcessLimit=max_processes;limits.JobMemoryLimit=memory_bytes
        if not K.SetInformationJobObject(self.job,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            self.close();raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="job_limits")
        fds=[];thread_handle=None
        try:
            out_r,out_w=os.pipe();err_r,err_w=os.pipe();stdin=os.open(os.devnull,os.O_RDONLY)
            fds=[out_r,out_w,err_r,err_w,stdin]
            startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESTDHANDLES
            startup.hStdOutput=msvcrt.get_osfhandle(out_w);startup.hStdError=msvcrt.get_osfhandle(err_w);startup.hStdInput=msvcrt.get_osfhandle(stdin)
            handles=[startup.hStdOutput,startup.hStdError,startup.hStdInput]
            for handle in handles:os.set_handle_inheritable(handle,True)
            startup.lpAttributeList={'handle_list':handles}
            self.process,thread_handle,self.pid,_=_winapi.CreateProcess(argv[0],subprocess.list2cmdline(argv),None,None,True,0x08000000|0x4|0x400,environment,str(cwd),startup)
            if not K.AssignProcessToJobObject(self.job,self.process):
                _winapi.TerminateProcess(self.process,1);raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="assign_job_before_resume")
            if K.ResumeThread(thread_handle)==0xFFFFFFFF:raise ToolExecutorError("TOOL_COMMAND_START_FAILED",stage="resume_job")
            K.CloseHandle(thread_handle);thread_handle=None
            for fd in [out_w,err_w,stdin]:os.close(fd);fds.remove(fd)
            for fd,buffer in [(out_r,self.stdout),(err_r,self.stderr)]:
                def drain(stream_fd=fd,sink=buffer):
                    with os.fdopen(stream_fd,'rb') as stream:
                        while True:
                            chunk=stream.read(4096)
                            if not chunk:break
                            sink.add(chunk)
                thread=threading.Thread(target=drain,daemon=True);thread.start();self.threads.append(thread);fds.remove(fd)
        except BaseException:
            if thread_handle:K.CloseHandle(thread_handle)
            for fd in fds:
                try:os.close(fd)
                except OSError:pass
            self.close();raise

    def active_processes(self):
        data=ACCOUNTING()
        if not K.QueryInformationJobObject(self.job,1,ctypes.byref(data),ctypes.sizeof(data),None):raise ToolExecutorError("TOOL_RESULT_UNKNOWN",stop_status="unknown")
        return data.ActiveProcesses

    def poll(self):
        if self.active_processes()!=0:return None
        for thread in self.threads:thread.join(.1)
        if any(t.is_alive() for t in self.threads):return None
        code=_winapi.GetExitCodeProcess(self.process)
        # An empty job proves exit, including the valid process exit code 259.
        return dict(exit_code=code,stdout=self.stdout.get(),stderr=self.stderr.get(),stdout_truncated=self.stdout.truncated,stderr_truncated=self.stderr.truncated,files={})

    def stop(self,timeout_seconds):
        if not K.TerminateJobObject(self.job,1):return dict(stop_status="unknown",evidence_refs=[])
        end=time.monotonic()+timeout_seconds
        while time.monotonic()<end:
            if self.active_processes()==0:
                for thread in self.threads:thread.join(min(.1,max(0,end-time.monotonic())))
                return dict(stop_status="confirmed",evidence_refs=["windows-job-empty:"+self.unit_ref])
            time.sleep(.005)
        return dict(stop_status="unknown",evidence_refs=[])

    def close(self):
        if self._closed:return
        self._closed=True
        if self.job:K.CloseHandle(self.job);self.job=None  # KILL_ON_JOB_CLOSE
        if self.process:K.CloseHandle(self.process);self.process=None
