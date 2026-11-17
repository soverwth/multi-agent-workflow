"""b04.tool.v0.1 wire types; share the existing runner/model identity contracts."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Protocol, TypedDict

from b04.agent_runner.contracts import TOOL_REQUEST_SCHEMA, TOOL_RESULT_SCHEMA
from b04.model_adapter.contracts import CallControl, IDENTITY_FIELDS, canonical, digest, utc_now
from b04.model_adapter.errors import ModelAdapterError
from b04.model_adapter.schemas import INVOCATION_SCHEMA, STRING, obj, validate as validate_json

OPERATION_SCHEMA=obj(dict(invocation_ref=INVOCATION_SCHEMA,operation_id=STRING))
CODES={
    "TOOL_REQUEST_INVALID":"validation", "TOOL_NOT_REGISTERED":"capability", "TOOL_DISABLED":"capability",
    "TOOL_PROFILE_UNSUPPORTED":"capability", "TOOL_LEASE_INVALID":"permission", "TOOL_SCOPE_DENIED":"permission",
    "TOOL_PATH_INVALID":"permission", "TOOL_OPERATION_CONFLICT":"conflict", "TOOL_FILE_CONFLICT":"conflict",
    "TOOL_IO_ERROR":"execution", "TOOL_COMMAND_START_FAILED":"execution", "TOOL_COMMAND_FAILED":"execution",
    "TOOL_OUTPUT_INVALID":"output", "TOOL_OUTPUT_LIMIT":"output", "TOOL_TIMEOUT":"timeout",
    "TOOL_BUDGET_EXHAUSTED":"budget", "TOOL_RESULT_UNKNOWN":"execution", "TOOL_STOPPED":"control",
}


class ToolExecutorError(Exception):
    def __init__(self,code,*,stage="validation",stop_status="confirmed",effects="none",details=None):
        if code not in CODES:raise ValueError("Unregistered tool error")
        super().__init__(code)
        self.code,self.stage,self.stop_status,self.effects=code,stage,stop_status,effects
        self.details=details or {}

    def wire(self,operation_ref,evidence=()):
        return dict(code=self.code,category=CODES[self.code],message=self.code,stage=self.stage,
                    operation_ref=copy.deepcopy(operation_ref),evidence_refs=list(evidence),
                    recoverability="reconcile_required" if self.stop_status!="confirmed" or self.effects in {"unknown","partial"} else "requires_decision",
                    details=copy.deepcopy(self.details))


def validate(value,schema,code="TOOL_REQUEST_INVALID"):
    try:validate_json(value,schema)
    except ModelAdapterError:raise ToolExecutorError(code) from None


def operation_ref(request):
    return dict(invocation_ref=copy.deepcopy(request["invocation_ref"]),operation_id=request["operation_id"])


def op_key(ref):
    invocation=ref["invocation_ref"]
    return canonical([invocation[k] for k in ["project_id","run_id","invocation_id","attempt_id"]]+[ref["operation_id"]])


@dataclass(frozen=True)
class ManagementContext:
    subject_ref: str
    grant_ref: str


@dataclass
class DriverOutcome:
    payload: dict
    changes: list
    output_refs: list
    exit_code: int | None = None
    effects: str = "none"


class ArtifactPort(Protocol):
    def read_input(self,artifact_ref,project_id,context): ...
    def read_object(self,artifact_ref,context): ...
    def put_object(self,ref,name,kind,body,context,**kwargs): ...


class PolicyPort(Protocol):
    def resolve(self,request,control:CallControl)->dict: ...
    def check_current(self,request,control:CallControl)->None: ...


class ProcessUnit(Protocol):
    unit_ref: str
    def poll(self)->dict | None: ...
    def stop(self,timeout_seconds:float)->dict: ...
    def close(self)->None: ...


class SandboxBackend(Protocol):
    def describe(self)->dict: ...
    def verify(self,spec:dict)->None: ...
    def start(self,spec:dict,unit_ref:str)->ProcessUnit: ...
    def stop_existing(self,unit_ref:str,timeout_seconds:float)->dict: ...
