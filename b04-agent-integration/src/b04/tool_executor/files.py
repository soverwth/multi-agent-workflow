"""Scoped byte I/O, reparse-resistant handles, and atomic sibling-file commits.

Conditional replacement requires an exclusively leased workspace: every writer must
honour the same resource lock. This is not a sandbox for arbitrary host processes.
"""
from __future__ import annotations

import os
import re
import stat
import time
import threading
import unicodedata
from contextlib import contextmanager,ExitStack
from pathlib import Path
from uuid import uuid4

from .contracts import ToolExecutorError


def relative_parts(path):
    if not isinstance(path,str) or not path or len(path)>220 or unicodedata.normalize("NFC",path)!=path or any(c in path for c in ['\\',':','\x00','~','\r','\n']):raise ToolExecutorError("TOOL_PATH_INVALID")
    parts=path.split('/')
    for part in parts:
        if not part or part in {'.','..'} or part[-1] in {' ','.'} or any(c in part for c in '<>"|?*') or any(ord(c)<32 for c in part):raise ToolExecutorError("TOOL_PATH_INVALID")
        if re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?",part):raise ToolExecutorError("TOOL_PATH_INVALID")
    return parts


def allowed(path,prefixes):
    relative_parts(path)
    transform=str.casefold if os.name=='nt' else lambda x:x
    path=transform(path)
    return any(path==transform(p.rstrip('/')) or path.startswith(transform(p.rstrip('/'))+'/') for p in prefixes)


if os.name=='nt':
    import ctypes
    import msvcrt
    from ctypes import wintypes as w
    K=ctypes.WinDLL('kernel32',use_last_error=True)
    K.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE];K.CreateFileW.restype=w.HANDLE
    K.CloseHandle.argtypes=[w.HANDLE];K.CloseHandle.restype=w.BOOL
    K.CreateMutexW.argtypes=[w.LPVOID,w.BOOL,w.LPCWSTR];K.CreateMutexW.restype=w.HANDLE
    K.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];K.WaitForSingleObject.restype=w.DWORD
    K.ReleaseMutex.argtypes=[w.HANDLE];K.ReleaseMutex.restype=w.BOOL
    K.MoveFileExW.argtypes=[w.LPCWSTR,w.LPCWSTR,w.DWORD];K.MoveFileExW.restype=w.BOOL
    K.ReplaceFileW.argtypes=[w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,w.DWORD,w.LPVOID,w.LPVOID];K.ReplaceFileW.restype=w.BOOL
    INVALID=ctypes.c_void_p(-1).value


class SecureWorkspace:
    def __init__(self,root,*,project_id,read_paths,write_paths,exclusive_lease_ref,allow_mkdir=False):
        self.root=Path(root).absolute()
        if os.name=='nt' and str(self.root).startswith('\\\\'):raise ToolExecutorError('TOOL_PROFILE_UNSUPPORTED',stage='local_workspace_required')
        if not self.root.is_dir() or not exclusive_lease_ref:raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="exclusive_workspace_required")
        if allow_mkdir:raise ToolExecutorError('TOOL_PROFILE_UNSUPPORTED',stage='directories_must_be_preprovisioned')
        current=Path(self.root.anchor)
        for part in self.root.parts[1:]:
            current/=part
            if self._reparse(current):raise ToolExecutorError("TOOL_PATH_INVALID",stage="workspace_reparse")
        self.root=self.root.resolve(strict=True)
        self.project_id,self.read_paths,self.write_paths=project_id,list(read_paths),list(write_paths)
        self.exclusive_lease_ref,self.allow_mkdir=exclusive_lease_ref,allow_mkdir
        for p in self.read_paths+self.write_paths:relative_parts(p.rstrip('/'))
        self.before_commit=None  # Test fault injection; never supplied by a tool request.
        self._local=threading.local()

    @staticmethod
    def _reparse(path):
        try:
            info=path.lstat()
            return stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&0x400)
        except FileNotFoundError:return False

    @contextmanager
    def locked(self,guard):
        from b04.model_adapter.contracts import digest
        if getattr(self._local,'depth',0):
            guard();yield;return
        if os.name=='nt':
            handle=K.CreateMutexW(None,False,'Local\\B04-workspace-'+digest(str(self.root).casefold()))
            if not handle:raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="workspace_mutex")
            acquired=False
            try:
                while True:
                    guard();status=K.WaitForSingleObject(handle,20)
                    if status in {0,0x80}:acquired=True;break
                    if status!=0x102:raise ToolExecutorError("TOOL_IO_ERROR",stage="workspace_mutex")
                self._local.depth=1
                yield
            finally:
                self._local.depth=0
                if acquired:K.ReleaseMutex(handle)
                K.CloseHandle(handle)
        else:
            import fcntl
            lock=Path(os.environ.get('TMPDIR','/tmp'))/('b04-workspace-'+digest(str(self.root))+'.lock')
            fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
            try:
                while True:
                    guard()
                    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                    except BlockingIOError:time.sleep(.01)
                self._local.depth=1;yield
            finally:self._local.depth=0;fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)

    @contextmanager
    def parents(self,path,guard,*,create=False):
        parts=relative_parts(path)
        with ExitStack() as stack:
            current=self.root
            if os.name=='nt':
                def protect(directory):
                    handle=K.CreateFileW(str(directory),0x80,3,None,3,0x02200000,None)  # attributes, no delete sharing, no reparse traversal
                    if handle==INVALID:raise ToolExecutorError("TOOL_PATH_INVALID",stage="directory_handle")
                    stack.callback(K.CloseHandle,handle)
                    if self._reparse(directory) or not directory.is_dir():raise ToolExecutorError("TOOL_PATH_INVALID",stage="directory_reparse")
                protect(current)
                for part in parts[:-1]:
                    guard();current/=part
                    if not current.exists():
                        if not create or not self.allow_mkdir:raise ToolExecutorError("TOOL_PATH_INVALID",stage="missing_parent")
                        current.mkdir()
                    protect(current)
                yield current/parts[-1],None
            else:
                fd=os.open(current,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);stack.callback(os.close,fd)
                for part in parts[:-1]:
                    guard()
                    try:new=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                    except FileNotFoundError:
                        if not create or not self.allow_mkdir:raise ToolExecutorError("TOOL_PATH_INVALID",stage="missing_parent")
                        os.mkdir(part,dir_fd=fd);new=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                    stack.callback(os.close,new);fd=new;current/=part
                yield current/parts[-1],fd

    def _read(self,target,dir_fd,guard,limit):
        if os.name=='nt':
            handle=K.CreateFileW(str(target),0x80000000,1,None,3,0x00200000,None)
            if handle==INVALID:
                error=ctypes.get_last_error()
                if error in {2,3}:raise FileNotFoundError(str(target))
                raise ToolExecutorError("TOOL_FILE_CONFLICT",stage="file_handle")
            try:fd=msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY)
            except BaseException:K.CloseHandle(handle);raise
        else:fd=os.open(target.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=dir_fd)
        with os.fdopen(fd,'rb') as stream:
            before=os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or getattr(before,'st_file_attributes',0)&0x400:raise ToolExecutorError("TOOL_PATH_INVALID",stage="file_identity")
            if before.st_size>limit:raise ToolExecutorError("TOOL_BUDGET_EXHAUSTED",stage="file_size")
            chunks=[];size=0
            while True:
                guard();chunk=stream.read(min(65536,limit-size+1))
                if not chunk:break
                chunks.append(chunk);size+=len(chunk)
                if size>limit:raise ToolExecutorError("TOOL_BUDGET_EXHAUSTED",stage="file_size")
            after=os.fstat(stream.fileno())
            if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ToolExecutorError("TOOL_FILE_CONFLICT",stage="concurrent_read")
            return b''.join(chunks),(before.st_dev,before.st_ino)

    def read(self,path,guard,limit,*,read_paths=None):
        if not allowed(path,self.read_paths) or read_paths is not None and not allowed(path,read_paths):raise ToolExecutorError("TOOL_SCOPE_DENIED",details={"denied_action":"read","resource":path})
        with self.locked(guard),self.parents(path,guard) as (target,fd):
            return self._read(target,fd,guard,limit)[0]

    def write(self,path,body,mode,expected_hash,guard,limit,*,write_paths):
        from .contracts import digest
        import hashlib
        sha=lambda value:hashlib.sha256(value).hexdigest()
        if not allowed(path,self.write_paths) or not allowed(path,write_paths):raise ToolExecutorError("TOOL_SCOPE_DENIED",details={"denied_action":"write","resource":path})
        if len(body)>limit:raise ToolExecutorError("TOOL_BUDGET_EXHAUSTED",stage="write_size")
        with self.locked(guard),self.parents(path,guard,create=True) as (target,fd):
            try:before,identity=self._read(target,fd,guard,limit)
            except FileNotFoundError:before,identity=None,None
            if mode=='create' and before is not None or mode=='replace' and (before is None or sha(before)!=expected_hash):raise ToolExecutorError("TOOL_FILE_CONFLICT",stage="write_precondition")
            temp=target.parent/('.b04-'+uuid4().hex+'.tmp');backup=target.parent/('.b04-'+uuid4().hex+'.bak')
            committed=False;verified=False
            try:
                flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)
                temp_fd=os.open(str(temp) if fd is None else temp.name,flags,0o600,**({"dir_fd":fd} if fd is not None else {}))
                with os.fdopen(temp_fd,'wb') as stream:
                    for start in range(0,len(body),65536):guard();stream.write(body[start:start+65536])
                    stream.flush();os.fsync(stream.fileno())
                if self.before_commit:self.before_commit(target)
                guard()
                if mode=='replace':
                    actual,actual_identity=self._read(target,fd,guard,limit)
                    if actual_identity!=identity or sha(actual)!=expected_hash:raise ToolExecutorError("TOOL_FILE_CONFLICT",stage="changed_before_commit")
                if os.name=='nt':
                    ok=K.MoveFileExW(str(temp),str(target),8) if mode=='create' else K.ReplaceFileW(str(target),str(temp),str(backup),0,None,None)
                    if not ok:raise ToolExecutorError("TOOL_FILE_CONFLICT",stage="atomic_commit")
                elif mode=='create':
                    os.link(temp.name,target.name,src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False);os.unlink(temp.name,dir_fd=fd)
                else:os.replace(temp.name,target.name,src_dir_fd=fd,dst_dir_fd=fd)
                committed=True
                # No timeout check may hide a commit that has already happened.
                after,_=self._read(target,fd,lambda:None,limit)
                if after!=body:raise ToolExecutorError("TOOL_RESULT_UNKNOWN",stage="post_commit_integrity",effects="unknown")
                if backup.exists():
                    saved=backup.read_bytes()
                    if sha(saved)!=expected_hash:raise ToolExecutorError("TOOL_RESULT_UNKNOWN",stage="unexpected_replaced_version",effects="partial")
                verified=True
                return dict(before=before,after=after,before_sha256=sha(before) if before is not None else None,after_sha256=sha(after))
            except ToolExecutorError:raise
            except OSError:raise ToolExecutorError("TOOL_RESULT_UNKNOWN" if committed else "TOOL_IO_ERROR",stage="file_commit",effects="unknown" if committed else "none") from None
            finally:
                for owned in [temp]+([backup] if verified else []):
                    try:
                        if owned.exists():owned.unlink()
                    except OSError:pass

    def snapshot(self,paths,guard,*,max_bytes,max_files,include_write_baseline=False):
        result={};total=0
        def walk(path):
            nonlocal total
            guard();target=self.root/path
            if self._reparse(target):raise ToolExecutorError("TOOL_PATH_INVALID",stage="snapshot_reparse")
            if not target.exists():return
            if target.is_dir():
                with self.parents(path+'/_probe',guard):
                    names=[p.name for p in os.scandir(target)]
                    for name in names:walk(path+'/'+name)
            else:
                if path in result:return
                scopes=self.read_paths+(self.write_paths if include_write_baseline else [])
                if not allowed(path,scopes):raise ToolExecutorError('TOOL_SCOPE_DENIED',stage='snapshot_scope')
                with self.parents(path,guard) as (file_target,fd):body=self._read(file_target,fd,guard,max_bytes-total)[0]
                total+=len(body)
                if len(result)>=max_files or total>max_bytes:raise ToolExecutorError("TOOL_BUDGET_EXHAUSTED",stage="snapshot_size")
                result[path]=body
        with self.locked(guard):
            for path in paths:relative_parts(path);walk(path)
        return result
