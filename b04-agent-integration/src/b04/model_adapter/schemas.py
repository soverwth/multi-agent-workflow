"""Executable wire contracts and an offline-only JSON Schema profile."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote

from jsonschema import Draft202012Validator, FormatChecker

from .contracts import ADAPTER_VERSION, PROTOCOL_VERSION, IDENTITY_FIELDS, parse_time, canonical
from .errors import ModelAdapterError

STRING = {"type": "string", "minLength": 1}
NULL_STRING = {"anyOf": [STRING, {"type": "null"}]}
POSITIVE = {"type": "integer", "minimum": 1}
COUNT = {"type": "integer", "minimum": 0}
HASH = {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"}
UTC = {"type": "string", "format": "utc-time"}
CHECKER = FormatChecker()


@CHECKER.checks("utc-time", raises=(ValueError, TypeError, AttributeError, OverflowError))
def _utc(value):
    if not isinstance(value, str):
        return True
    parse_time(value)
    return True


def obj(properties, *, optional=()):
    return dict(type="object", properties=properties,
                required=[k for k in properties if k not in optional], additionalProperties=False)


INVOCATION_SCHEMA = obj({k: (NULL_STRING if k == "task_id" else POSITIVE if k == "attempt_id" else STRING) for k in IDENTITY_FIELDS})
CALL_REF_SCHEMA = obj(dict(invocation_ref=INVOCATION_SCHEMA, model_call_id=STRING, call_seq=POSITIVE))
CONTROL_SCHEMA = obj(dict(
    control_contract_version={"const": "b04.control.v0.1"}, context_ref=STRING, subject_ref=STRING,
    invocation_ref=INVOCATION_SCHEMA, input_snapshot_id=STRING, input_snapshot_sha256=HASH,
    purpose={"enum": ["execute", "observe", "report", "cleanup"]},
    **{k: NULL_STRING for k in ["execute_grant_ref", "lease_ref", "observe_grant_ref", "report_grant_ref", "cleanup_grant_ref",
                               "read_scope_ref", "tool_binding_set_ref", "draft_namespace_ref", "cancel_signal_ref"]},
    control_generation=COUNT, write_scope={"type": ["object", "null"]}, budget_ticket_ref=STRING, deadline_at=UTC))
TEXT_PART = obj(dict(type={"const": "text"}, text={"type": "string"}))
TOOL_INTENT = obj(dict(tool_call_id=STRING, tool_call_id_source={"enum": ["adapter", "provider"]},
                      provider_tool_call_id=NULL_STRING, name=STRING, binding_ref=STRING, arguments={"type": "object"}))
MESSAGE_SCHEMA = obj(dict(role={"enum": ["system", "user", "assistant", "tool"]},
                          content={"type": "array", "items": TEXT_PART},
                          tool_calls={"type": "array", "minItems": 1, "items": TOOL_INTENT}, tool_call_id=STRING),
                     optional=("tool_calls", "tool_call_id"))
TOOL_SCHEMA = obj(dict(name=STRING, description={"type": "string"}, input_schema={"type": ["object", "boolean"]}, binding_ref=STRING))
REQUEST_SCHEMA = obj(dict(
    adapter_contract_version={"const": ADAPTER_VERSION}, protocol_version={"const": PROTOCOL_VERSION},
    execution_mode={"enum": ["mock", "live"]}, **INVOCATION_SCHEMA["properties"], model_call_id=STRING, call_seq=POSITIVE,
    input_snapshot_id=STRING, input_snapshot_sha256=HASH, agent_definition_ref=STRING, prompt_template_ref=STRING,
    model_policy_ref=STRING, model_config_ref=STRING, messages={"type": "array", "minItems": 1, "items": MESSAGE_SCHEMA},
    response_spec=obj(dict(mode={"enum": ["text", "json_object", "json_schema"]}, schema_ref=NULL_STRING,
                           enforcement={"enum": ["provider_required", "local_validation"]})),
    tools={"type": "array", "items": TOOL_SCHEMA}, tool_choice=STRING, parameters={"type": "object"},
    call_limits=obj(dict(timeout_seconds={"type": "number", "exclusiveMinimum": 0}, deadline_at=UTC, max_output_tokens=POSITIVE)),
    budget_ticket_ref=STRING))
ERROR_SCHEMA = obj(dict(code=STRING, category=STRING, message=STRING, stage=STRING, retry_advice=STRING,
                        retry_after_seconds={"type": ["number", "null"], "minimum": 0},
                        request_delivery={"enum": ["not_sent", "sent", "unknown"]}, stop_status={"enum": ["confirmed", "pending", "unknown"]},
                        provider_error_code=NULL_STRING, evidence_refs={"type": "array", "items": STRING}, details={"type": "object"}))
USAGE_SCHEMA = obj(dict(**{k: {"anyOf": [COUNT, {"type": "null"}]} for k in ["input_tokens", "output_tokens", "total_tokens"]},
                        source=STRING, availability={"enum": ["observed", "estimated", "unavailable"]}))
RESULT_SCHEMA = obj(dict(
    adapter_contract_version={"const": ADAPTER_VERSION}, protocol_version={"const": PROTOCOL_VERSION},
    execution_mode={"enum": ["mock", "live"]}, **INVOCATION_SCHEMA["properties"], model_call_id=STRING, call_seq=POSITIVE,
    input_snapshot_id=STRING, input_snapshot_sha256=HASH, status={"enum": ["ok", "in_progress", "error", "cancelled", "unknown"]},
    selected_model=obj(dict(model_config_ref=NULL_STRING, provider=NULL_STRING, model_id=NULL_STRING, driver_ref=NULL_STRING, reported_model_version=NULL_STRING)),
    provider_request_id=NULL_STRING, response={"type": ["object", "null"]},
    finish_reason={"enum": ["stop", "tool_calls", "length", "refusal", "content_filter", "other", None]}, provider_finish_reason=NULL_STRING,
    usage=USAGE_SCHEMA, timing=obj(dict(started_at=UTC, finished_at={"anyOf": [UTC, {"type": "null"}]}, duration_ms={"type": ["number", "null"], "minimum": 0})),
    error={"anyOf": [ERROR_SCHEMA, {"type": "null"}]}, raw_response_ref=NULL_STRING, partial_response_ref=NULL_STRING, call_record_ref=NULL_STRING))
RESULT_SCHEMA["allOf"] = [
    {"if": {"properties": {"status": {"const": "in_progress"}}}, "then": {"properties": {
        "response": {"type": "null"}, "error": {"type": "null"}, "finish_reason": {"type": "null"},
        "timing": {"properties": {"finished_at": {"type": "null"}, "duration_ms": {"type": "null"}}}}}},
    {"if": {"properties": {"status": {"const": "ok"}}}, "then": {"properties": {"response": {"type": "object"}, "error": {"type": "null"}}}},
    {"if": {"properties": {"status": {"enum": ["error", "cancelled", "unknown"]}}}, "then": {"properties": {"response": {"type": "null"}, "error": ERROR_SCHEMA}}},
]
FEEDBACK_SCHEMA = obj(dict(feedback_contract_version={"const": "b04.tool-feedback.v0.1"}, invocation_ref=INVOCATION_SCHEMA,
    input_snapshot_id=STRING, input_snapshot_sha256=HASH, execution_mode={"enum": ["mock", "live"]},
    model_call_id=STRING, tool_call_id=STRING, operation_id=STRING, tool_binding_ref=STRING,
    status={"enum": ["completed", "in_progress", "rejected", "failed", "timed_out", "stopped", "unknown"]},
    result_code=STRING, payload={}, exit_code={"type": ["integer", "null"]}, stop_status={"enum": ["confirmed", "pending", "unknown", None]},
    side_effects_state={"enum": ["none", "verified", "partial", "unknown"]}, error={"type": ["object", "null"]},
    output_refs={"type": "array"}, changes={"type": "array"}, operation_record_ref=STRING,
    truncation=obj(dict(fields={"type": "array", "items": STRING}, original_refs={"type": "array"}))))


def validate(data: Any, schema: dict, code: str = "MODEL_REQUEST_INVALID") -> None:
    try:
        canonical(data)  # JSON only; rejects NaN and Infinity, including nested parameters.
        errors = list(Draft202012Validator(schema, format_checker=CHECKER).iter_errors(data))
        if errors:
            raise ValueError("Contract validation failed")
    except (ValueError, TypeError, RecursionError):
        raise ModelAdapterError(code) from None


def strict_loads(text: str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("Non-finite JSON number")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    # A huge exponent such as 1e999 also becomes a non-finite float.
    canonical(value)
    return value


# Supported offline profile. Remote references cannot trigger network/file retrieval.
SCHEMA_KEYWORDS = frozenset("$schema $id $defs $ref $comment title description default examples deprecated readOnly writeOnly type properties patternProperties additionalProperties required enum const items prefixItems minItems maxItems uniqueItems contains minContains maxContains minLength maxLength pattern minimum maximum exclusiveMinimum exclusiveMaximum multipleOf minProperties maxProperties propertyNames allOf anyOf oneOf not if then else dependentRequired dependentSchemas unevaluatedProperties unevaluatedItems".split())


def check_output_schema(schema: Any, allowed_keywords=None) -> None:
    allowed = set(SCHEMA_KEYWORDS if allowed_keywords is None else allowed_keywords)

    def walk(node):
        if isinstance(node, bool):
            return
        if not isinstance(node, dict) or set(node) - allowed:
            raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED")
        if "$schema" in node and node["$schema"] != "https://json-schema.org/draft/2020-12/schema":
            raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED")
        if "$ref" in node and not node["$ref"].startswith("#"):
            raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED")
        if "$ref" in node:
            pointer = unquote(node["$ref"][1:])
            if pointer and not pointer.startswith("/"):
                raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED")
            target = schema
            for component in pointer.split("/")[1:]:
                component = component.replace("~1", "/").replace("~0", "~")
                target = target[int(component)] if isinstance(target, list) else target[component]
            if not isinstance(target, (dict, bool)):
                raise ModelAdapterError("MODEL_CONFIG_INVALID")
        if "$id" in node:  # External base URI changes would alter local reference resolution.
            raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED")
        for key in ["properties", "patternProperties", "$defs", "dependentSchemas"]:
            for child in node.get(key, {}).values():
                walk(child)
        for key in ["items", "additionalProperties", "contains", "propertyNames", "not", "if", "then", "else", "unevaluatedProperties", "unevaluatedItems"]:
            if key in node:
                walk(node[key])
        for key in ["allOf", "anyOf", "oneOf", "prefixItems"]:
            for child in node.get(key, []):
                walk(child)

    try:
        canonical(schema)
        Draft202012Validator.check_schema(schema)
        walk(schema)
    except ModelAdapterError:
        raise
    except Exception:
        raise ModelAdapterError("MODEL_CONFIG_INVALID") from None


def conforms(value: Any, schema: Any) -> bool:
    try:
        return Draft202012Validator(schema).is_valid(value)
    except Exception:
        return False

