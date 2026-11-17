"""Wire types and runtime-only control. No provider SDK types cross this boundary."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

ADAPTER_VERSION = "b04.model.v0.1"
PROTOCOL_VERSION = "b04.exec.v0.2"
IDENTITY_FIELDS = ("project_id", "run_id", "invocation_id", "task_id", "attempt_id", "dispatch_id")
CALL_FIELDS = IDENTITY_FIELDS + ("model_call_id", "call_seq")
JSON = dict[str, Any]


class InvocationRef(TypedDict):
    project_id: str
    run_id: str
    invocation_id: str
    task_id: str | None
    attempt_id: int
    dispatch_id: str


class ModelCallRef(TypedDict):
    invocation_ref: InvocationRef
    model_call_id: str
    call_seq: int


class ControlContext(TypedDict):
    control_contract_version: str
    context_ref: str
    subject_ref: str
    invocation_ref: InvocationRef
    input_snapshot_id: str
    input_snapshot_sha256: str
    purpose: Literal["execute", "observe", "report", "cleanup"]
    execute_grant_ref: str | None
    lease_ref: str | None
    observe_grant_ref: str | None
    report_grant_ref: str | None
    cleanup_grant_ref: str | None
    control_generation: int
    read_scope_ref: str | None
    write_scope: JSON | None
    tool_binding_set_ref: str | None
    draft_namespace_ref: str | None
    budget_ticket_ref: str
    deadline_at: str
    cancel_signal_ref: str | None


@dataclass(frozen=True)
class CallControl:
    """Issued by trusted runner code; serialized fields alone grant no authority.

    The extra control ticket is a runtime allowance for preflight/dedup queries.
    It does not extend the serialized ControlContext or business model budget.
    """

    context: ControlContext
    control_budget_ticket_ref: str | None = None
    cancel_signal: asyncio.Event | None = None
    cleanup_context: ControlContext | None = None
    report_context: ControlContext | None = None


class ModelRequest(TypedDict):
    adapter_contract_version: str
    protocol_version: str
    execution_mode: Literal["mock", "live"]
    project_id: str
    run_id: str
    invocation_id: str
    task_id: str | None
    attempt_id: int
    dispatch_id: str
    model_call_id: str
    call_seq: int
    input_snapshot_id: str
    input_snapshot_sha256: str
    agent_definition_ref: str
    prompt_template_ref: str
    model_policy_ref: str
    model_config_ref: str
    messages: list[JSON]
    response_spec: JSON
    tools: list[JSON]
    tool_choice: str
    parameters: JSON
    call_limits: JSON
    budget_ticket_ref: str


class ModelError(TypedDict):
    code: str
    category: str
    message: str
    stage: str
    retry_advice: str
    retry_after_seconds: float | None
    request_delivery: Literal["not_sent", "sent", "unknown"]
    stop_status: Literal["confirmed", "pending", "unknown"]
    provider_error_code: str | None
    evidence_refs: list[str]
    details: JSON


class ModelResult(TypedDict):
    adapter_contract_version: str
    protocol_version: str
    execution_mode: str
    project_id: str
    run_id: str
    invocation_id: str
    task_id: str | None
    attempt_id: int
    dispatch_id: str
    model_call_id: str
    call_seq: int
    input_snapshot_id: str
    input_snapshot_sha256: str
    status: Literal["ok", "in_progress", "error", "cancelled", "unknown"]
    selected_model: JSON
    provider_request_id: str | None
    response: JSON | None
    finish_reason: str | None
    provider_finish_reason: str | None
    usage: JSON
    timing: JSON
    error: ModelError | None
    raw_response_ref: str | None
    partial_response_ref: str | None
    call_record_ref: str | None


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("UTC timestamp required")
    return parsed


def invocation_ref(request: JSON) -> InvocationRef:
    return {key: copy.deepcopy(request[key]) for key in IDENTITY_FIELDS}


def model_call_ref(request: JSON) -> ModelCallRef:
    return {"invocation_ref": invocation_ref(request), "model_call_id": request["model_call_id"], "call_seq": request["call_seq"]}


def attempt_key(ref: InvocationRef) -> tuple:
    return tuple(ref[key] for key in IDENTITY_FIELDS)


def unavailable_usage() -> JSON:
    return dict(input_tokens=None, output_tokens=None, total_tokens=None, source="unavailable", availability="unavailable")

