"""Local reference integrations; production services implement the ports instead."""
from __future__ import annotations

import base64
import copy
import re
import subprocess
import threading
from pathlib import Path, PurePosixPath

from b04.model_adapter.contracts import canonical, digest, parse_time, utc_now
from b04.model_adapter.errors import ModelAdapterError
from b04.model_adapter.schemas import CALL_REF_SCHEMA, validate as validate_model
from .contracts import RunnerControls, RunnerError, sha_bytes


class RegisteredControlProvider:
    def __init__(self):
        self._controls={}

    def register(self,ref,controls:RunnerControls):
        if any(c.context["invocation_ref"]!=ref for c in [controls.model,controls.tool,controls.observe,controls.report,controls.cleanup]):
            raise ValueError("Control identities differ")
        self._controls[canonical(ref)]=controls

    def acquire(self,invocation_ref):
        try:
            return self._controls[canonical(invocation_ref)]
        except KeyError:
            raise RunnerError("EXEC_LEASE_INVALID",stage="dispatch_authority") from None


class ModelAdapterBridge:
    """The five designed methods plus B03's protected result-record read."""
    def __init__(self,adapter):
        self.adapter=adapter

    async def describe_model(self,*args):return await self.adapter.describe_model(*args)
    async def validate_request(self,*args):return await self.adapter.validate_request(*args)
    async def generate(self,*args):return await self.adapter.generate(*args)
    async def get_call(self,*args):return await self.adapter.get_call(*args)
    async def cancel_call(self,*args):return await self.adapter.cancel_call(*args)

    async def read_result(self,call_ref,result_ref,control):
        validate_model(call_ref,CALL_REF_SCHEMA)
        self.adapter.authority.authorize(control.context,"observe",utc_now())
        if control.context["invocation_ref"]!=call_ref["invocation_ref"]:
            raise ModelAdapterError("MODEL_CONTROL_INVALID")
        self.adapter.budget.consume_control(control.context["budget_ticket_ref"],call_ref["invocation_ref"],utc_now())
        record=self.adapter.ledger.get(call_ref)
        if not record or not record["result"] or result_ref!=record["record_ref"]+":result":
            raise ModelAdapterError("MODEL_NETWORK_UNCERTAIN",stage="result_record",delivery="unknown")
        if any(record["result"][k]!=control.context[k] for k in ["input_snapshot_id","input_snapshot_sha256"]):
            raise ModelAdapterError("MODEL_CONTROL_INVALID")
        return copy.deepcopy(record["result"])


class LocalTransportBudget:
    """Independent finite transport allowance for demos/tests, not model quota."""
    def __init__(self):
        self._tickets={}
        self._lock=threading.RLock()

    def register(self,ticket_ref,invocation_ref,limit,expires_at):
        if type(limit) is not int or limit<0:
            raise ValueError("Invalid transport limit")
        with self._lock:
            if ticket_ref in self._tickets:
                raise ValueError("Transport consumption cannot be reset")
            self._tickets[ticket_ref]=dict(invocation_ref=copy.deepcopy(invocation_ref),limit=limit,consumed=0,expires_at=expires_at)

    def consume_transport(self,ticket_ref,invocation_ref):
        with self._lock:
            ticket=self._tickets.get(ticket_ref)
            if not ticket or any(ticket["invocation_ref"][k]!=invocation_ref[k] for k in ["project_id","run_id","invocation_id"]) or parse_time(ticket["expires_at"])<=utc_now() or ticket["consumed"]>=ticket["limit"]:
                raise RunnerError("EXEC_BUDGET_EXHAUSTED",stage="transport_budget")
            ticket["consumed"]+=1

    def consumed(self,ticket_ref):
        return self._tickets[ticket_ref]["consumed"]


def scoped_path(path,allowed):
    """Portable workspace path check; executors still validate actual OS handles."""
    if not isinstance(path,str) or not path or "\\" in path or ":" in path or "\x00" in path:
        return False
    candidate=PurePosixPath(path)
    if candidate.is_absolute() or any(p in {"..","."} for p in path.split("/")):
        return False
    return any(path==prefix.rstrip("/") or path.startswith(prefix.rstrip("/")+"/") for prefix in allowed if prefix)


class GitWorkspaceSource:
    """Reads real, clean candidate commits from registered isolated workspaces.

    This adapter never creates commits, executes generated code, or merges branches.
    Authorised tools own those actions. Every file byte is read from the commit.
    """
    def __init__(self,*,authority,timeout_seconds=3):
        self.authority=authority
        self.timeout_seconds=timeout_seconds
        self._roots={}

    def register(self,workspace_ref,project_id,repository_ref,root):
        root=Path(root).resolve(strict=True)
        if not root.is_dir():raise ValueError("Workspace must be a directory")
        self._roots[workspace_ref]=(project_id,repository_ref,root)

    def _git(self,root,*args):
        try:
            return subprocess.run(["git","-C",str(root),*args],check=True,capture_output=True,timeout=self.timeout_seconds,shell=False).stdout
        except (OSError,subprocess.SubprocessError):
            raise RunnerError("EXEC_ARTIFACT_INVALID",stage="repository_capture") from None

    def capture(self,envelope,slots,context):
        try:
            self.authority.authorize(context,"execute",utc_now())
            project,repository,root=self._roots[envelope["workspace_ref"]]
            source=envelope["source_control"]
            if context["invocation_ref"]["project_id"]!=project or envelope["project_id"]!=project or source["repository_ref"]!=repository:
                raise KeyError("Workspace ownership")
            base=source["base_commit"]
            if not isinstance(base,str) or not re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}",base):
                raise KeyError("Invalid base commit")
            head=self._git(root,"rev-parse","--verify","HEAD^{commit}").decode().strip()
            self._git(root,"merge-base","--is-ancestor",base,head)
            if self._git(root,"status","--porcelain","--untracked-files=all"):
                raise RunnerError("EXEC_ARTIFACT_INVALID",stage="uncommitted_checked_content")
            allowed=context["write_scope"]["workspace_paths"]
            changed=[p.decode("utf-8") for p in self._git(root,"diff","--name-only","-z",base,head).split(b"\0") if p]
            if any(not scoped_path(p,allowed) or not scoped_path(p,envelope["write_scope"]["workspace_paths"]) for p in changed):
                raise RunnerError("EXEC_WRITE_SCOPE",stage="repository_changes")
            entries=[]
            for line in self._git(root,"ls-tree","-r","-z","--full-tree",head).split(b"\0"):
                if not line:continue
                header,path=line.split(b"\t",1)
                mode,kind,blob=header.decode().split(" ")
                entries.append((path.decode("utf-8"),mode,kind,blob))
            payloads={}
            for slot in slots:
                files=[]
                paths=slot["source"]["paths"]
                for path,mode,kind,blob in entries:
                    if not any(path==p.rstrip("/") or path.startswith(p.rstrip("/")+"/") for p in paths):continue
                    if not scoped_path(path,allowed) or mode not in {"100644","100755"} or kind!="blob":
                        raise RunnerError("EXEC_WRITE_SCOPE",stage="repository_file")
                    body=self._git(root,"cat-file","blob",blob)
                    files.append(dict(path=path,sha256=sha_bytes(body),content_base64=base64.b64encode(body).decode("ascii")))
                if not files:
                    raise RunnerError("EXEC_ARTIFACT_INVALID",stage="empty_source_bundle")
                payloads[slot["name"]]=canonical(dict(candidate_commit=head,files=files)).encode("utf-8")
            return dict(repository_ref=repository,base_commit=base,candidate_commit=head),payloads
        except RunnerError:raise
        except (ModelAdapterError,KeyError,TypeError,UnicodeError,ValueError):
            raise RunnerError("EXEC_ARTIFACT_INVALID",stage="workspace_binding") from None

    def prepare(self,envelope,context):
        try:
            self.authority.authorize(context,"execute",utc_now())
            project,repository,root=self._roots[envelope["workspace_ref"]]
            base=envelope["source_control"]["base_commit"]
            if project!=envelope["project_id"] or context["invocation_ref"]["project_id"]!=project or repository!=envelope["source_control"]["repository_ref"] or not re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}",base):raise ValueError("Workspace binding")
            head=self._git(root,"rev-parse","--verify","HEAD^{commit}").decode().strip()
            self._git(root,"merge-base","--is-ancestor",base,head)
            if self._git(root,"status","--porcelain","--untracked-files=all"):raise ValueError("Dirty workspace baseline")
            return dict(workspace_ref=envelope["workspace_ref"],repository_ref=repository,base_commit=base,observed_start_commit=head)
        except (RunnerError,ModelAdapterError,KeyError,ValueError,TypeError):
            raise RunnerError("EXEC_INPUT_INVALID",stage="workspace_preparation",blocked=True) from None

