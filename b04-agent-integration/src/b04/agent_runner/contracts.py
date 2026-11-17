"""Executable B04 runner wire contracts; shared identities come from model_adapter."""
from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from typing import Any, TypedDict

from b04.model_adapter.contracts import CallControl, IDENTITY_FIELDS, JSON, PROTOCOL_VERSION, canonical, invocation_ref
from b04.model_adapter.schemas import (COUNT, HASH, INVOCATION_SCHEMA, NULL_STRING, POSITIVE, STRING, UTC,
                                       obj, validate as validate_model)
from b04.model_adapter.errors import ModelAdapterError

VARIABLES = ("invocation_context", "goal", "agent_definition", "input_contract", "output_contract", "context_items",
             "spec_context", "plan_context", "capability_catalog", "tool_descriptions", "write_scope", "limits", "required_checks", "feedback_context")
TERMINALS = frozenset({"candidate_submitted", "execution_failed", "execution_blocked", "execution_stopped"})
PHASES = ("ACCEPTED", "PREPARING", "EXECUTING", "SELF_CHECKING", "SUBMITTING", "TERMINAL")
WRITE_SCOPE_SCHEMA = obj(dict(workspace_paths={"type": "array", "items": STRING, "uniqueItems": True},
                              artifact_namespaces={"type": "array", "items": STRING, "uniqueItems": True}))
ENVELOPE_SCHEMA = obj(dict(
    protocol_version={"const": PROTOCOL_VERSION}, execution_mode={"enum": ["mock", "live"]}, **INVOCATION_SCHEMA["properties"],
    idempotency_key=STRING, retry_count=COUNT, retry_budget=COUNT, revalidation_id=NULL_STRING,
    workflow_definition_ref=STRING, invocation_kind=STRING, agent_definition_ref=STRING, model_config_ref=NULL_STRING,
    goal=STRING, input_contract_ref=STRING, output_contract_ref=STRING, input_snapshot_id=STRING, input_snapshot_sha256=HASH,
    inputs={"type": "array", "items": obj(dict(artifact_ref=STRING, kind=STRING, selector=STRING), optional=("selector",))},
    spec_ref=NULL_STRING, plan_ref=NULL_STRING, lease_ref=STRING, tool_config_ref=STRING, write_scope=WRITE_SCOPE_SCHEMA,
    workspace_ref=NULL_STRING, source_control={"type": ["object", "null"]},
    limits=obj(dict(execution_timeout_seconds={"type": "number", "exclusiveMinimum": 0}, model_call_timeout_seconds={"type": "number", "exclusiveMinimum": 0},
                    max_model_calls=COUNT, max_total_tokens=COUNT, max_tool_calls=COUNT)),
    ownership={"type": "object"}, escalation_target=STRING), optional=("ownership",))
ARTIFACT_SCHEMA = obj(dict(artifact_ref=STRING, kind=STRING, version=STRING, media_type=STRING, schema_ref=NULL_STRING, sha256=HASH, size_bytes=COUNT))
INPUT_REF_SCHEMA = obj(dict(artifact_ref=STRING, kind=STRING, sha256=HASH, state=STRING, selector=STRING), optional=("selector",))
MANIFEST_SCHEMA = obj(dict(manifest_contract_version={"const": "b04.manifest.v0.2"}, protocol_version={"const": PROTOCOL_VERSION},
    execution_mode={"enum": ["mock", "live"]}, **INVOCATION_SCHEMA["properties"], submission_id=STRING,
    input_snapshot_id=STRING, input_snapshot_sha256=HASH, input_refs={"type": "array", "items": INPUT_REF_SCHEMA},
    workflow_definition_ref=STRING, agent_definition_ref=STRING, prompt_template_ref=STRING, model_config_ref=NULL_STRING,
    tool_config_ref=STRING, output_contract_ref=STRING, author=STRING, started_at=UTC, finished_at=UTC, change_summary=STRING,
    model_call_refs={"type": "array", "items": STRING}, tool_operation_refs={"type": "array", "items": STRING},
    artifacts={"type": "array", "minItems": 1, "items": ARTIFACT_SCHEMA}, required_check_refs={"type": "array", "items": STRING},
    self_check_refs={"type": "array", "items": STRING}, self_check_status={"enum": ["passed", "failed", "incomplete"]},
    missing_check_refs={"type": "array", "items": STRING}, known_issue_refs={"type": "array", "items": STRING}, open_questions={"type": "array"},
    source_control={"anyOf": [{"type": "null"}, {"type": "object", "properties": {k: STRING for k in ["repository_ref", "base_commit", "candidate_commit"]}, "required": ["repository_ref", "base_commit", "candidate_commit"]}]},
    review_status={"const": "pending"}, execution_record_ref=STRING))
DRAFT_SCHEMA = obj(dict(submission_id=STRING, invocation_ref=INVOCATION_SCHEMA, input_snapshot_id=STRING, input_snapshot_sha256=HASH,
                        terminal_kind={"enum": sorted(TERMINALS)}, manifest_ref=NULL_STRING, manifest_sha256={"anyOf": [HASH, {"type": "null"}]}, error_ref=NULL_STRING))
DRAFT_SCHEMA["allOf"]=[
    {"if":{"properties":{"terminal_kind":{"const":"candidate_submitted"}}},"then":{"properties":{"manifest_ref":STRING,"manifest_sha256":HASH,"error_ref":{"type":"null"}}}},
    {"if":{"properties":{"terminal_kind":{"enum":["execution_failed","execution_blocked"]}}},"then":{"properties":{"manifest_ref":{"type":"null"},"manifest_sha256":{"type":"null"},"error_ref":STRING}}},
    {"if":{"properties":{"terminal_kind":{"const":"execution_stopped"}}},"then":{"properties":{"manifest_ref":{"type":"null"},"manifest_sha256":{"type":"null"},"error_ref":{"type":"null"}}}},
]
EVENT_SCHEMA = obj(dict(protocol_version={"const": PROTOCOL_VERSION}, event_id=STRING,
    event_type={"enum": sorted(TERMINALS | {"execution_accepted", "execution_started", "execution_progress"})},
    **INVOCATION_SCHEMA["properties"], input_snapshot_id=STRING, input_snapshot_sha256=HASH, event_seq=POSITIVE, occurred_at=UTC,
    execution_mode={"enum": ["mock", "live"]}, producer={"const": "B04"}, payload={"type": "object"}))
RECEIPT_SCHEMA = obj(dict(event_id=NULL_STRING, receipt_status={"enum": ["recorded", "stale", "rejected"]},
                          reason_code=NULL_STRING, receipt_ref=STRING, reconciliation_required={"type": "boolean"}))
RECONCILE_SCHEMA = obj(dict(submission_id=STRING, resolution={"enum": ["recorded", "stale", "retry_delivery", "new_attempt_required", "manual_required"]},
                            reason_code=NULL_STRING, decision_ref=STRING, next_action_ref=NULL_STRING))
COMMIT_SCHEMA=obj(dict(submission_id=STRING,commit_status={"enum":["committed","duplicate","rejected","unknown"]},terminal_record_ref=NULL_STRING,event_ref=NULL_STRING,commit_receipt_ref=NULL_STRING,reason_code=NULL_STRING))
COMMIT_SCHEMA["allOf"]=[{"if":{"properties":{"commit_status":{"enum":["committed","duplicate"]}}},"then":{"properties":{"terminal_record_ref":STRING,"event_ref":STRING,"commit_receipt_ref":STRING,"reason_code":{"type":"null"}}}}]
TOOL_REQUEST_SCHEMA = obj(dict(tool_contract_version={"const": "b04.tool.v0.1"}, protocol_version={"const": PROTOCOL_VERSION},
    execution_mode={"enum": ["mock", "live"]}, invocation_ref=INVOCATION_SCHEMA, operation_id=STRING, tool_binding_ref=STRING,
    tool_name=STRING, tool_version=STRING, arguments={"type": "object"}, input_snapshot_id=STRING, input_snapshot_sha256=HASH,
    lease_ref=STRING, tool_config_ref=STRING, workspace_ref=NULL_STRING, timeout_seconds={"type": "number", "exclusiveMinimum": 0}, deadline_at=UTC,
    origin=obj(dict(source={"enum": ["model", "runner", "self_check"]}, model_call_id=NULL_STRING, tool_call_id=NULL_STRING, check_ref=NULL_STRING))))
TOOL_RESULT_SCHEMA = obj(dict(tool_contract_version={"const": "b04.tool.v0.1"}, protocol_version={"const": PROTOCOL_VERSION},
    execution_mode={"enum": ["mock", "live"]}, invocation_ref=INVOCATION_SCHEMA, operation_id=STRING, tool_binding_ref=STRING,
    tool_name=STRING, tool_version=STRING, input_snapshot_id=STRING, input_snapshot_sha256=HASH,
    status={"enum": ["completed", "in_progress", "rejected", "failed", "timed_out", "stopped", "unknown"]}, result_code=STRING,
    payload={}, output_refs={"type": "array"}, changes={"type": "array"}, exit_code={"type": ["integer", "null"]},
    timing=obj(dict(started_at=UTC, finished_at={"anyOf": [UTC, {"type": "null"}]}, execution_duration_ms={"type": ["number", "null"], "minimum": 0}, cleanup_duration_ms={"type": ["number", "null"], "minimum": 0})),
    stop_status={"enum": ["confirmed", "pending", "unknown", None]}, side_effects_state={"enum": ["none", "verified", "partial", "unknown"]},
    error={"type": ["object", "null"]}, operation_record_ref=STRING))


class InvocationReceipt(TypedDict):
    accepted: bool
    duplicate: bool
    invocation_ref: dict | None
    reason_code: str | None
    message: str


@dataclass(frozen=True)
class RunnerControls:
    """Trusted runtime injection; none of these grants are taken from model output."""
    model: CallControl
    tool: CallControl
    observe: CallControl
    report: CallControl
    cleanup: CallControl
    transport_ticket_ref: str


class RunnerError(Exception):
    def __init__(self, code="EXEC_RUNNER_ERROR", *, stage="runner", blocked=False, stop_status="confirmed", operation_ref=None, details=None, evidence_refs=None):
        super().__init__(code)
        self.code, self.stage, self.blocked, self.stop_status = code, stage, blocked, stop_status
        self.operation_ref, self.details, self.evidence_refs = operation_ref, details or {}, evidence_refs or []

    def to_dict(self, record_ref):
        layer = "tool" if self.operation_ref else "runner"
        category = "permission" if self.code in {"EXEC_WRITE_SCOPE", "EXEC_LEASE_INVALID"} or self.details.get("denied_action") else "input" if self.blocked else "execution"
        return dict(code=self.code, category=category, message=self.code, stage=self.stage, operation_ref=copy.deepcopy(self.operation_ref),
                    cause_ref=dict(layer=layer, ref=copy.deepcopy(self.operation_ref) if self.operation_ref else record_ref), origin_layer=layer,
                    evidence_refs=list(self.evidence_refs), recoverability="requires_reconciliation" if self.stop_status != "confirmed" else "requires_decision",
                    requested_action="reconcile_then_decide" if self.stop_status != "confirmed" else "request_responsible_decision",
                    stop_status=self.stop_status, details=copy.deepcopy(self.details))


class CommitUncertain(Exception):
    pass


class PendingStop(Exception):
    pass


class StopRequested(Exception):
    pass


class AlreadyTerminal(Exception):
    pass


def validate(value, schema, code="EXEC_INVALID_ENVELOPE", *, stage="validation"):
    try:
        validate_model(value, schema)
    except ModelAdapterError:
        raise RunnerError(code, stage=stage) from None


def sha_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def key_of(ref):
    return canonical([ref[k] for k in ["project_id", "run_id", "invocation_id", "attempt_id"]])


def pointer(value: Any, selector: str):
    if selector == "":
        return copy.deepcopy(value)
    if not selector.startswith("/"):
        raise RunnerError("EXEC_INPUT_INVALID", stage="selector", blocked=True)
    try:
        for component in selector.split("/")[1:]:
            component = component.replace("~1", "/").replace("~0", "~")
            if isinstance(value,list):
                if not re.fullmatch(r"0|[1-9][0-9]*",component):
                    raise ValueError("Noncanonical array selector")
                value=value[int(component)]
            else:
                value=value[component]
        return copy.deepcopy(value)
    except (KeyError, IndexError, TypeError, ValueError):
        raise RunnerError("EXEC_INPUT_INVALID", stage="selector", blocked=True) from None

