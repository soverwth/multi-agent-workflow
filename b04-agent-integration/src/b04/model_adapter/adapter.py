"""Async facade: one authorized request, at most one actual transport send."""
from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
from typing import Any

from .contracts import (ADAPTER_VERSION, PROTOCOL_VERSION, CALL_FIELDS, IDENTITY_FIELDS, CallControl,
                        JSON, ModelRequest, ModelResult, canonical, digest, invocation_ref,
                        model_call_ref, parse_time, stamp, unavailable_usage, utc_now)
from .errors import ModelAdapterError
from .ports import Authority, BudgetPort, CallLedger, ConfigResolver, CredentialResolver
from .schemas import (CALL_REF_SCHEMA, FEEDBACK_SCHEMA, REQUEST_SCHEMA,
                      RESULT_SCHEMA, USAGE_SCHEMA, check_output_schema, conforms, strict_loads, validate)


@dataclass
class _Active:
    driver: Any
    prepared: JSON
    control: CallControl
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    stop_info: JSON | None = None
    provider_request_id: str | None = None
    secret: str | None = field(default=None, repr=False)
    stop_task: asyncio.Task | None = None


class ModelAdapterFacade:
    def __init__(self, *, resolver: ConfigResolver, registry, ledger: CallLedger, budget: BudgetPort,
                 authority: Authority, credentials: CredentialResolver | None = None, cleanup_timeout_seconds: float = 1.0):
        if cleanup_timeout_seconds <= 0:
            raise ValueError("Cleanup timeout must be positive")
        self.resolver, self.registry, self.ledger = resolver, registry, ledger
        self.budget, self.authority, self.credentials = budget, authority, credentials
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self._active: dict[str, _Active] = {}
        self._background: set[asyncio.Task] = set()

    def _authorize(self, control, purpose, ref=None):
        if not isinstance(control, CallControl) or not isinstance(control.context, dict):
            raise ModelAdapterError("MODEL_CONTROL_INVALID", stage="control_context")
        self.authority.authorize(control.context, purpose, utc_now())
        if ref is not None and control.context["invocation_ref"] != ref:
            raise ModelAdapterError("MODEL_CONTROL_INVALID", stage="identity")

    def _control_debit(self, control):
        ticket = control.context["budget_ticket_ref"] if control.context["purpose"] != "execute" else control.control_budget_ticket_ref
        if not ticket:
            raise ModelAdapterError("MODEL_BUDGET_EXHAUSTED", stage="control_budget")
        self.budget.consume_control(ticket, control.context["invocation_ref"], utc_now())

    def _auxiliary(self, control, purpose, ref):
        context = control.cleanup_context if purpose == "cleanup" else control.report_context
        if context is None:
            raise ModelAdapterError("MODEL_CONTROL_INVALID", stage=purpose + "_grant")
        self.authority.authorize(context, purpose, utc_now())
        if context["invocation_ref"] != ref or any(context[k] != control.context[k] for k in ["input_snapshot_id", "input_snapshot_sha256"]):
            raise ModelAdapterError("MODEL_CONTROL_INVALID", stage=purpose + "_binding")
        return context

    async def describe_model(self, model_config_ref, call_context: CallControl) -> JSON:
        purpose = call_context.context.get("purpose") if isinstance(call_context, CallControl) and isinstance(call_context.context, dict) else None
        if purpose not in {"execute", "observe"}:
            raise ModelAdapterError("MODEL_CONTROL_INVALID")
        self._authorize(call_context, purpose)
        self._control_debit(call_context)
        resolved = self.resolver.resolve(model_config_ref, call_context.context)
        driver = self.registry.get(resolved.config["driver_ref"])
        return dict(model_config_ref=model_config_ref, provider=resolved.config["provider"], model_id=resolved.config["model_id"],
                    driver_ref=resolved.config["driver_ref"], model_capability_ref=resolved.config["model_capability_ref"],
                    capabilities=copy.deepcopy(resolved.capabilities), driver_capabilities=copy.deepcopy(driver.describe()),
                    execution_modes=sorted(driver.execution_modes))

    async def validate_request(self, request: ModelRequest, call_context: CallControl) -> JSON:
        self._authorize(call_context, "execute")
        self._control_debit(call_context)
        try:
            prepared = self._prepare(copy.deepcopy(request), call_context)
            return dict(valid=True, request_fingerprint=prepared["fingerprint"], model_config_ref=request["model_config_ref"],
                        model_capability_ref=prepared["config"]["model_capability_ref"], issues=[])
        except ModelAdapterError as exc:
            return dict(valid=False, request_fingerprint=None, model_config_ref=request.get("model_config_ref") if isinstance(request,dict) else None,
                        model_capability_ref=None, issues=[exc.to_dict()])
        except Exception:
            return dict(valid=False, request_fingerprint=None, model_config_ref=request.get("model_config_ref") if isinstance(request,dict) else None,
                        model_capability_ref=None, issues=[ModelAdapterError("MODEL_INTERNAL_ERROR", stage="preflight").to_dict()])

    def _prepare(self, request, control):
        validate(request, REQUEST_SCHEMA)
        self._authorize(control, "execute", invocation_ref(request))
        if any(request[k] != control.context[k] for k in ["input_snapshot_id", "input_snapshot_sha256", "budget_ticket_ref"]):
            raise ModelAdapterError("MODEL_CONTROL_INVALID", stage="snapshot")
        resolved = self.resolver.resolve(request["model_config_ref"], control.context)
        config, policy, caps, binding = resolved.config, resolved.policy, resolved.capabilities, resolved.binding
        required_config = {"model_config_ref", "provider", "model_id", "driver_ref", "model_capability_ref", "credential_ref", "endpoint_ref", "generation_defaults", "provider_options", "transport_policy_ref"}
        if not required_config <= set(config) or not {"allowed_model_config_refs", "allowed_parameter_overrides"} <= set(policy):
            raise ModelAdapterError("MODEL_CONFIG_INVALID", stage="configuration")
        if config["transport_policy_ref"] != "transport:single-send@1":
            raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="transport_policy")
        for key in ["model_config_ref", "model_policy_ref", "agent_definition_ref", "prompt_template_ref", "input_snapshot_id", "input_snapshot_sha256", "execution_mode"]:
            if request[key] != binding[key]:
                raise ModelAdapterError("MODEL_CONFIG_INVALID", stage="frozen_binding")
        if control.context["tool_binding_set_ref"] != binding["tool_binding_set_ref"]:
            raise ModelAdapterError("MODEL_CONTROL_INVALID", stage="tool_bindings")
        if request["model_config_ref"] not in policy["allowed_model_config_refs"]:
            raise ModelAdapterError("MODEL_CONFIG_INVALID", stage="model_policy")
        driver = self.registry.get(config["driver_ref"])
        if request["execution_mode"] not in driver.execution_modes:
            raise ModelAdapterError("MODEL_CONFIG_INVALID", stage="execution_mode")
        driver_caps = driver.describe()
        required_capabilities = {"input_modalities", "structured_output_modes", "instruction_roles", "supported_parameters", "provider_option_schema", "schema_keywords", "context_window_tokens", "max_output_tokens"}
        if any(not required_capabilities <= set(c) for c in [caps, driver_caps]):
            raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="unknown_capability")
        for capability in [caps, driver_caps]:
            if any(not isinstance(capability[k],list) or any(not isinstance(v,str) for v in capability[k]) for k in ["input_modalities","structured_output_modes","instruction_roles","schema_keywords"]):
                raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="capability_profile")
            if any(type(capability[k]) is not int or capability[k] <= 0 for k in ["context_window_tokens","max_output_tokens"]):
                raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="capability_profile")
            if not isinstance(capability["supported_parameters"],dict) or not isinstance(capability["provider_option_schema"],(dict,bool)):
                raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="capability_profile")
        mode = request["response_spec"]["mode"]
        for capability in [caps, driver_caps]:
            if "text" not in capability["input_modalities"] or mode not in capability["structured_output_modes"]:
                raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED")
            if any(m["role"] not in capability["instruction_roles"] for m in request["messages"]):
                raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED")
            if request["tools"] and (capability.get("native_tool_calls") is not True or mode != "text" and capability.get("tools_with_structured_output") is not True):
                raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="feature_combination")
            if request["response_spec"]["enforcement"] == "provider_required" and mode != "text" and (not isinstance(capability.get("provider_structured_output_modes"),list) or mode not in capability["provider_structured_output_modes"]):
                raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="enforcement")
        if request["response_spec"]["enforcement"] == "local_validation" and not policy.get("allow_local_validation", False):
            raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="enforcement_policy")
        if request["tool_choice"] not in {"auto", "none", "required"} | {t["name"] for t in request["tools"]} or not request["tools"] and request["tool_choice"] not in {"none", "auto"}:
            raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="tool_choice")
        tools = {}
        frozen_tools = binding["tool_bindings"]
        required_tool_fields = {"binding_ref", "model_tool_name", "tool_name", "tool_version", "driver_ref", "model_input_schema_ref", "executor_input_schema_ref", "normalization_profile_ref", "command_profile_refs", "model_input_schema_sha256", "executor_input_schema_sha256"}
        if any(not required_tool_fields <= set(b) for b in frozen_tools) or len({b["model_tool_name"] for b in frozen_tools}) != len(frozen_tools) or len({b["binding_ref"] for b in frozen_tools}) != len(frozen_tools):
            raise ModelAdapterError("MODEL_CONFIG_INVALID", stage="tool_bindings")
        for tool in request["tools"]:
            if tool["name"] in tools:
                raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="tool_binding")
            matching = [b for b in binding["tool_bindings"] if b["model_tool_name"] == tool["name"] and b["binding_ref"] == tool["binding_ref"]]
            if len(matching) != 1:
                raise ModelAdapterError("MODEL_CONTROL_INVALID", stage="tool_binding")
            frozen = matching[0]
            schema = self.resolver.schema(frozen["model_input_schema_ref"], control.context)
            executor_schema = self.resolver.schema(frozen["executor_input_schema_ref"], control.context)
            if schema != tool["input_schema"] or digest(schema) != frozen["model_input_schema_sha256"] or digest(executor_schema) != frozen["executor_input_schema_sha256"]:
                raise ModelAdapterError("MODEL_CONFIG_INVALID", stage="tool_schema")
            for capability in [caps, driver_caps]:
                check_output_schema(schema, capability["schema_keywords"])
            tools[tool["name"]] = tool
        schema = None
        schema_ref = request["response_spec"]["schema_ref"]
        if mode == "json_schema":
            if schema_ref is None:
                raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="response_spec")
            schema = self.resolver.schema(schema_ref, control.context)
            for capability in [caps, driver_caps]:
                check_output_schema(schema, capability["schema_keywords"])
        elif schema_ref is not None:
            raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="response_spec")
        parameters = copy.deepcopy(config["generation_defaults"])
        if set(request["parameters"]) - set(policy["allowed_parameter_overrides"]):
            raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="parameters")
        parameters.update(request["parameters"])
        for capability in [caps, driver_caps]:
            for name, value in parameters.items():
                rule = capability["supported_parameters"].get(name)
                if rule is None:
                    raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="parameters")
                check_output_schema(rule, capability["schema_keywords"])
                if not conforms(value, rule):
                    raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="parameters")
            check_output_schema(capability["provider_option_schema"], capability["schema_keywords"])
            if not conforms(config["provider_options"], capability["provider_option_schema"]):
                raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="provider_options")
        self._validate_history(request, tools, caps, driver_caps)
        max_output = request["call_limits"]["max_output_tokens"]
        if max_output > min(caps["max_output_tokens"], driver_caps["max_output_tokens"]):
            raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="output_limit")
        prepared = dict(execution_mode=request["execution_mode"], config=config, messages=request["messages"], tools=request["tools"],
                        response_spec=request["response_spec"], schema=schema, schema_sha256=digest(schema) if schema is not None else None,
                        tool_choice=request["tool_choice"], parameters=parameters, max_output_tokens=max_output)
        driver.validate_mapping(copy.deepcopy(prepared))
        estimate = driver.estimate_input_tokens(copy.deepcopy(prepared))
        if type(estimate.tokens) is not int or estimate.tokens < 0 or type(estimate.upper_bound) is not bool:
            raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="token_estimate")
        if policy.get("strict_token_budget", True) and (not estimate.upper_bound or caps.get("token_upper_bound") is not True or driver_caps.get("token_upper_bound") is not True):
            raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="token_accounting")
        if estimate.tokens + max_output > min(caps["context_window_tokens"], driver_caps["context_window_tokens"]):
            raise ModelAdapterError("MODEL_CONTEXT_LIMIT", stage="context")
        frozen_control = {k: control.context[k] for k in ["read_scope_ref", "write_scope", "tool_binding_set_ref", "deadline_at", "cancel_signal_ref"]}
        prepared["fingerprint"] = digest([request, prepared, policy, caps, binding, frozen_control])
        prepared["attempt_fingerprint"] = digest([config, policy, caps, binding])
        prepared["token_reservation"] = estimate.tokens + max_output
        prepared["driver"] = driver
        return prepared

    def _validate_history(self, request, tools, *capabilities):
        pending, seen = {}, set()
        for message in request["messages"]:
            role = message["role"]
            intents = message.get("tool_calls", [])
            if intents:
                if role != "assistant" or pending:
                    raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="tool_history")
                for intent in intents:
                    ident, name = intent["tool_call_id"], intent["name"]
                    if ident in seen or name not in tools or intent["binding_ref"] != tools[name]["binding_ref"] or not conforms(intent["arguments"], tools[name]["input_schema"]):
                        raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="tool_history")
                    pending[ident] = intent
                    seen.add(ident)
            if role == "tool":
                ident = message.get("tool_call_id")
                if ident not in pending or intents:
                    raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="tool_history")
                try:
                    feedback = strict_loads("".join(part["text"] for part in message["content"]))
                except (ValueError, TypeError, RecursionError):
                    raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="tool_feedback") from None
                validate(feedback, FEEDBACK_SCHEMA)
                intent = pending.pop(ident)
                if feedback["invocation_ref"] != invocation_ref(request) or feedback["tool_call_id"] != ident or feedback["tool_binding_ref"] != intent["binding_ref"]:
                    raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="tool_feedback_identity")
                if intent["tool_call_id_source"] == "adapter" and not ident.startswith(feedback["model_call_id"] + ":tool:"):
                    raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="tool_feedback_model_call")
                if any(feedback[k] != request[k] for k in ["input_snapshot_id", "input_snapshot_sha256", "execution_mode"]):
                    raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="tool_feedback_snapshot")
                if feedback["status"] in {"in_progress", "unknown"} or feedback["stop_status"] != "confirmed" or feedback["side_effects_state"] == "unknown":
                    raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="tool_feedback_unsettled")
            elif "tool_call_id" in message or pending and not intents:
                raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="tool_history")
        if pending:
            raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="tool_history_incomplete")

    def _result(self, request, prepared, started_at, *, record_ref=None, status="error", error=None):
        config = prepared.get("config", {})
        result = {k: copy.deepcopy(request[k]) for k in CALL_FIELDS}
        result.update(adapter_contract_version=ADAPTER_VERSION, protocol_version=PROTOCOL_VERSION,
            execution_mode=request.get("execution_mode", "mock"), input_snapshot_id=request["input_snapshot_id"],
            input_snapshot_sha256=request["input_snapshot_sha256"], status=status,
            selected_model={k: config.get(k) for k in ["model_config_ref", "provider", "model_id", "driver_ref"]} | {"reported_model_version": None},
            provider_request_id=None, response=None, finish_reason=None, provider_finish_reason=None, usage=unavailable_usage(),
            timing=dict(started_at=started_at, finished_at=None if status == "in_progress" else stamp(), duration_ms=None if status == "in_progress" else max(0, (utc_now() - parse_time(started_at)).total_seconds() * 1000)),
            error=error.to_dict([record_ref] if record_ref else []) if error else None,
            raw_response_ref=None, partial_response_ref=None, call_record_ref=record_ref)
        return result

    async def generate(self, request: ModelRequest, call_control: CallControl) -> ModelResult:
        request = copy.deepcopy(request)
        # Never invent identity/snapshot fields for a malformed internal request.
        # These typed boundary errors map to EXEC_MODEL_ERROR in an admitted runner.
        identity_schema = {"type": "object", "properties": {k: REQUEST_SCHEMA["properties"][k] for k in CALL_FIELDS + ("input_snapshot_id", "input_snapshot_sha256", "execution_mode")},
                           "required": list(CALL_FIELDS) + ["input_snapshot_id", "input_snapshot_sha256", "execution_mode"]}
        validate(request, identity_schema)
        started_at, prepared, record, active, created = stamp(), {}, None, None, False
        ref, transport_id, reserved, delivery = model_call_ref(request), None, False, "not_sent"
        raw_ref, usage, normalized = None, unavailable_usage(), None
        credential = None
        try:
            prepared = self._prepare(request, call_control)
            self._auxiliary(call_control, "report", invocation_ref(request))
            self._auxiliary(call_control, "cleanup", invocation_ref(request))
            created, record = self.ledger.claim(request, prepared["fingerprint"], prepared["attempt_fingerprint"],
                dict(model_config_ref=request["model_config_ref"], driver_ref=prepared["config"]["driver_ref"],
                     input_snapshot_id=request["input_snapshot_id"], input_snapshot_sha256=request["input_snapshot_sha256"],
                     schema_sha256=prepared["schema_sha256"], token_reservation=prepared["token_reservation"],
                     configuration_sha256=digest(prepared["config"])))
            started_at = record["started_at"]
            if not created:
                self._control_debit(call_control)
                if record["result"] is not None:
                    return copy.deepcopy(record["result"])
                if digest(ref) in self._active:
                    return self._result(request, prepared, started_at, record_ref=record["record_ref"], status="in_progress")
                return self._result(request, prepared, started_at, record_ref=record["record_ref"], status="unknown",
                                    error=ModelAdapterError("MODEL_NETWORK_UNCERTAIN", stage="recovery", delivery="unknown"))
            config, driver = prepared["config"], prepared["driver"]
            if config["credential_ref"] is not None:
                if self.credentials is None:
                    raise ModelAdapterError("MODEL_AUTH_FAILED", stage="credentials")
                credential = self.credentials.resolve(config["credential_ref"], call_control.context)
            wire = {k: copy.deepcopy(v) for k, v in prepared.items() if k not in {"driver", "fingerprint", "attempt_fingerprint", "token_reservation"}}
            request_ref = self.ledger.put_private(invocation_ref(request), "effective_request", self._redact([request, wire], credential))
            self.ledger.append(ref, "effective_request", {"request_ref": request_ref})
            self._check_current(request, call_control)
            transport_id = "transport:" + digest(ref) + ":1"
            self.budget.reserve(request["budget_ticket_ref"], transport_id, invocation_ref(request), prepared["token_reservation"], utc_now())
            reserved = True
            self._check_current(request, call_control)
            self.ledger.mark_sent(ref, transport_id)
            active = _Active(driver, wire, call_control, secret=credential)
            self._active[digest(ref)] = active
            delivery = "unknown"
            remaining = min(request["call_limits"]["timeout_seconds"], (parse_time(request["call_limits"]["deadline_at"]) - utc_now()).total_seconds(),
                            (parse_time(call_control.context["deadline_at"]) - utc_now()).total_seconds())
            active.task = asyncio.create_task(driver.send_once(copy.deepcopy(wire), credential, remaining))
            raw = await self._wait(active, ref, remaining)
            delivery = "sent"
            self._auxiliary(call_control, "report", invocation_ref(request))
            raw_ref = self.ledger.put_private(invocation_ref(request), "raw_response", self._redact(raw, credential))
            normalized = driver.normalize(raw)
            if isinstance(normalized, dict) and isinstance(normalized.get("provider_request_id"), str):
                active.provider_request_id = normalized["provider_request_id"]
            # Retain trustworthy usage even when the content itself is malformed.
            if isinstance(normalized, dict) and isinstance(normalized.get("usage"), dict):
                try:
                    validate(normalized["usage"], USAGE_SCHEMA, "MODEL_RESPONSE_MALFORMED")
                    usage = copy.deepcopy(normalized["usage"])
                except ModelAdapterError:
                    pass
            self._check_current(request, call_control, after_send=True)
            result = self._normalize(request, prepared, normalized, started_at, record["record_ref"], credential)
            result["raw_response_ref"] = raw_ref
        except asyncio.CancelledError:
            stop = await self._stop(active, ref) if active else {"stop_status": "confirmed"}
            fault = ModelAdapterError("MODEL_CANCELLED" if stop["stop_status"] == "confirmed" else "MODEL_NETWORK_UNCERTAIN", stage="caller_cancel", delivery=delivery, stop_status=stop["stop_status"])
            result = self._result(request, prepared, started_at, record_ref=record["record_ref"] if record else None,
                                  status="cancelled" if stop["stop_status"] == "confirmed" else "unknown", error=fault)
        except Exception as exc:
            fault = exc if isinstance(exc, ModelAdapterError) else ModelAdapterError("MODEL_INTERNAL_ERROR", stage="adapter", delivery=delivery)
            if record is not None and not created and record["result"] is None:
                fault = ModelAdapterError(fault.code, stage=fault.stage, delivery="not_sent", stop_status="unknown")
            # An output/normalization failure follows a completed response.
            if delivery == "sent" and fault.delivery == "not_sent":
                fault = ModelAdapterError(fault.code, stage=fault.stage, delivery="sent", stop_status="confirmed",
                                          retry_after_seconds=fault.retry_after_seconds, provider_error_code=fault.provider_error_code)
            elif active and active.task and not active.task.done():
                stop = await self._stop(active, ref)
                fault = ModelAdapterError(fault.code, stage=fault.stage, delivery=delivery, stop_status=stop["stop_status"])
            if active and isinstance(exc, ModelAdapterError) and exc.code in {"MODEL_NETWORK_UNCERTAIN", "MODEL_TIMEOUT", "MODEL_CANCELLED"}:
                # _wait already recorded the actual stop result and delivery ambiguity.
                fault = exc
            status = "cancelled" if fault.code == "MODEL_CANCELLED" and fault.stop_status == "confirmed" else "unknown" if fault.delivery == "unknown" or fault.stop_status != "confirmed" else "error"
            result = self._result(request, prepared, started_at, record_ref=record["record_ref"] if record else None, status=status, error=fault)
            delivery = fault.delivery
        result["raw_response_ref"] = raw_ref
        if raw_ref and result["status"] != "ok":
            result["partial_response_ref"] = raw_ref
        if result["status"] != "ok":
            result["usage"] = self._redact(usage, credential)
            if isinstance(normalized, dict):
                reason = normalized.get("finish_reason")
                result["finish_reason"] = reason if isinstance(reason, str) and reason in {"stop", "tool_calls", "length", "refusal", "content_filter", "other"} else None
                for key in ["provider_request_id", "provider_finish_reason"]:
                    value = normalized.get(key)
                    if isinstance(value, str) and value and (not credential or credential not in value):
                        result[key] = value
        if credential and result["error"]:
            result["error"] = self._redact(result["error"], credential)
        try:
            if reserved:
                self.budget.settle(transport_id, delivery=delivery, usage=result["usage"])
            validate(result, RESULT_SCHEMA, "MODEL_INTERNAL_ERROR")
            if created and record is not None and record["result"] is None:
                context = self._auxiliary(call_control, "report", invocation_ref(request))
                self.budget.consume_control(context["budget_ticket_ref"], invocation_ref(request), utc_now())
                self.ledger.finish(ref, result, "response_recorded" if result["status"] == "ok" else "cancelled" if result["status"] == "cancelled" else "unknown" if result["status"] == "unknown" else "failed")
        except Exception:
            # Lost recording/settlement is never a license to resend. The durable
            # send intent remains and a later instance reports unknown.
            result = self._result(request, prepared, started_at, record_ref=record["record_ref"] if record else None, status="unknown",
                                  error=ModelAdapterError("MODEL_INTERNAL_ERROR", stage="settlement_or_record", delivery="unknown"))
        finally:
            if created:
                self._active.pop(digest(ref), None)
                if active:
                    active.secret = None
        return result

    def _check_current(self, request, control, *, after_send=False):
        self._authorize(control, "execute", invocation_ref(request))
        delivery = "sent" if after_send else "not_sent"
        if control.cancel_signal is not None and control.cancel_signal.is_set():
            raise ModelAdapterError("MODEL_CANCELLED", stage="control", delivery=delivery, stop_status="confirmed")
        if min(parse_time(request["call_limits"]["deadline_at"]), parse_time(control.context["deadline_at"])) <= utc_now():
            raise ModelAdapterError("MODEL_TIMEOUT", stage="deadline", delivery=delivery, stop_status="confirmed")

    async def _wait(self, active, ref, remaining):
        waiters = [asyncio.create_task(active.stop_event.wait())]
        if active.control.cancel_signal is not None:
            waiters.append(asyncio.create_task(active.control.cancel_signal.wait()))
        try:
            deadline = asyncio.get_running_loop().time() + max(0, remaining)
            while True:
                left = deadline - asyncio.get_running_loop().time()
                done, _ = await asyncio.wait([active.task, *waiters], timeout=max(0, min(left, 0.05)), return_when=asyncio.FIRST_COMPLETED)
                if done or left <= 0:
                    break
                try:
                    self._authorize(active.control, "execute", ref["invocation_ref"])
                except ModelAdapterError:
                    stop = await self._stop(active, ref)
                    raise ModelAdapterError("MODEL_CONTROL_INVALID", stage="control_revoked", delivery="unknown", stop_status=stop["stop_status"])
            cancelled = any(w in done for w in waiters)
            if active.task in done and not cancelled:
                return active.task.result()
            stop = active.stop_info or await self._stop(active, ref)
            code = "MODEL_CANCELLED" if cancelled and stop["stop_status"] == "confirmed" else "MODEL_NETWORK_UNCERTAIN" if cancelled else "MODEL_TIMEOUT"
            raise ModelAdapterError(code, stage="waiting_response", delivery="unknown", stop_status=stop["stop_status"])
        finally:
            for task in waiters:
                task.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)

    async def _stop(self, active, ref, *, debit=True):
        if active is None:
            return dict(stop_status="unknown", local_request_state="unknown", remote_execution_state="unknown", evidence_refs=[])
        if active.stop_task is None:
            active.stop_task = asyncio.create_task(self._perform_stop(active, ref, debit=debit))
        return await asyncio.shield(active.stop_task)

    async def _perform_stop(self, active, ref, *, debit=True):
        if active.stop_info is not None:
            return active.stop_info
        info = dict(stop_status="unknown", local_request_state="cancel_requested", remote_execution_state="unknown", evidence_refs=[])
        try:
            context = self._auxiliary(active.control, "cleanup", ref["invocation_ref"])
            if debit:
                self.budget.consume_control(context["budget_ticket_ref"], ref["invocation_ref"], utc_now())
            task = asyncio.create_task(active.driver.cancel(ref, active.provider_request_id))
            done, _ = await asyncio.wait([task], timeout=min(self.cleanup_timeout_seconds, max(0, (parse_time(context["deadline_at"]) - utc_now()).total_seconds())))
            if task in done and not task.cancelled():
                candidate = task.result()
                if isinstance(candidate, dict) and candidate.get("stop_status") in {"confirmed", "pending", "unknown"} and all(isinstance(candidate.get(k), str) and candidate[k] for k in ["local_request_state", "remote_execution_state"]) and isinstance(candidate.get("evidence_refs"), list) and all(isinstance(x,str) and x for x in candidate["evidence_refs"]):
                    info = self._redact({k:candidate[k] for k in info}, active.secret)
                    if info["stop_status"] == "confirmed" and (active.driver.describe().get("cancellation") != "remote_confirmed" or not info["evidence_refs"]):
                        info.update(stop_status="unknown", remote_execution_state="unknown")
            else:
                task.cancel()
                self._retain(task)
        except Exception:
            pass
        active.stop_info = info
        active.stop_event.set()
        try:
            self.ledger.append(ref, "stop", info)
        except Exception:
            pass
        if active.task is not None:
            if not active.task.done():
                active.task.cancel()  # Local cancellation does not confirm a remote stop.
            self._retain(active.task, active, ref)
        return info

    def _retain(self, task, active=None, ref=None):
        self._background.add(task)
        def completed(done):
            self._background.discard(done)
            try:
                value = done.result()
                if active and ref:
                    self._auxiliary(active.control, "report", ref["invocation_ref"])
                    self.budget.consume_control(active.control.report_context["budget_ticket_ref"], ref["invocation_ref"], utc_now())
                    # Do not persist arbitrary late text here: it may contain credentials.
                    self.ledger.append(ref, "late_response", {"observed": True, "response_sha256": digest(value)})
            except BaseException:
                pass
        task.add_done_callback(completed)

    def _normalize(self, request, prepared, value, started_at, record_ref, credential):
        if not isinstance(value, dict) or not {"text", "tool_calls", "finish_reason", "provider_finish_reason", "provider_request_id", "reported_model_version", "usage"} <= set(value):
            raise ModelAdapterError("MODEL_RESPONSE_MALFORMED", stage="normalize")
        validate(value["usage"], USAGE_SCHEMA, "MODEL_RESPONSE_MALFORMED")
        usage = value["usage"]
        if usage["availability"] == "unavailable" and any(usage[k] is not None for k in ["input_tokens", "output_tokens", "total_tokens"]):
            raise ModelAdapterError("MODEL_RESPONSE_MALFORMED", stage="usage")
        if all(usage[k] is not None for k in ["input_tokens", "output_tokens", "total_tokens"]) and usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
            raise ModelAdapterError("MODEL_RESPONSE_MALFORMED", stage="usage")
        if usage["availability"] == "observed" and usage["total_tokens"] is not None and usage["total_tokens"] > prepared["token_reservation"]:
            raise ModelAdapterError("MODEL_BUDGET_EXHAUSTED", stage="token_accounting")
        reason = value["finish_reason"]
        if not isinstance(reason, str):
            raise ModelAdapterError("MODEL_RESPONSE_MALFORMED", stage="finish_reason")
        codes = {"length": "MODEL_OUTPUT_TRUNCATED", "refusal": "MODEL_REFUSED", "content_filter": "MODEL_CONTENT_FILTERED"}
        if reason in codes:
            raise ModelAdapterError(codes[reason], stage="normalize")
        if reason not in {"stop", "tool_calls"}:
            raise ModelAdapterError("MODEL_RESPONSE_MALFORMED", stage="finish_reason")
        if credential and credential in canonical(value):
            raise ModelAdapterError("MODEL_RESPONSE_MALFORMED", stage="secret_in_response")
        result = self._result(request, prepared, started_at, record_ref=record_ref, status="ok")
        for key in ["provider_request_id", "provider_finish_reason", "reported_model_version"]:
            if value[key] is not None and (not isinstance(value[key], str) or not value[key]):
                raise ModelAdapterError("MODEL_RESPONSE_MALFORMED", stage="provider_metadata")
        result["provider_request_id"] = value["provider_request_id"]
        result["provider_finish_reason"] = value["provider_finish_reason"]
        result["selected_model"]["reported_model_version"] = value["reported_model_version"]
        result["usage"] = copy.deepcopy(usage)
        result["finish_reason"] = reason
        text, calls = value["text"], value["tool_calls"]
        if text is not None and not isinstance(text, str) or not isinstance(calls, list):
            raise ModelAdapterError("MODEL_RESPONSE_MALFORMED", stage="content")
        if calls:
            if reason != "tool_calls" or request["tool_choice"] == "none":
                raise ModelAdapterError("MODEL_TOOL_CALL_INVALID", stage="tool_choice")
            mapped, provider_ids = [], set()
            tools = {t["name"]: t for t in request["tools"]}
            for index, call in enumerate(calls, 1):
                try:
                    name, arguments = call["name"], call["arguments"]
                    tool = tools[name]
                    if request["tool_choice"] not in {"auto", "required", name}:
                        raise ValueError("Wrong forced tool")
                    if isinstance(arguments, str):
                        arguments = strict_loads(arguments)
                    if not isinstance(arguments, dict) or not conforms(arguments, tool["input_schema"]):
                        raise ValueError("Invalid arguments")
                    provider_id = call.get("provider_tool_call_id")
                    if provider_id is not None:
                        if not isinstance(provider_id, str) or not provider_id or provider_id in provider_ids:
                            raise ValueError("Invalid provider association")
                        provider_ids.add(provider_id)
                    mapped.append(dict(tool_call_id=request["model_call_id"] + ":tool:" + str(index), tool_call_id_source="adapter",
                                       provider_tool_call_id=provider_id, name=name, arguments=arguments, binding_ref=tool["binding_ref"]))
                except (ValueError, TypeError, KeyError, RecursionError):
                    raise ModelAdapterError("MODEL_TOOL_CALL_INVALID", stage="tool_arguments") from None
            result["response"] = dict(kind="tool_calls", tool_calls=mapped, auxiliary_text=text)
        else:
            if reason != "stop":
                raise ModelAdapterError("MODEL_TOOL_CALL_INVALID", stage="empty_tool_intent")
            if request["tool_choice"] == "required" or request["tool_choice"] not in {"auto", "none"}:
                raise ModelAdapterError("MODEL_TOOL_CALL_INVALID", stage="required_tool")
            if text is None or not text.strip():
                raise ModelAdapterError("MODEL_EMPTY_RESPONSE", stage="content")
            mode, parsed = request["response_spec"]["mode"], None
            if mode != "text":
                try:
                    parsed = strict_loads(text)
                    if mode == "json_object" and not isinstance(parsed, dict) or mode == "json_schema" and not conforms(parsed, prepared["schema"]):
                        raise ValueError("Invalid structured output")
                except (ValueError, TypeError, RecursionError):
                    raise ModelAdapterError("MODEL_OUTPUT_FORMAT", stage="structured_output") from None
            result["response"] = dict(kind="final", text=text, json_value=parsed, format=mode)
        return result

    async def get_call(self, model_call_ref, call_context: CallControl) -> JSON:
        validate(model_call_ref, CALL_REF_SCHEMA)
        self._authorize(call_context, "observe", model_call_ref["invocation_ref"])
        self._control_debit(call_context)
        record = self.ledger.get(model_call_ref)
        self._record_context(record, call_context)
        result = record["result"] if record else None
        stop_notes = [n["payload"] for n in record["notes"] if n["kind"] == "stop"] if record else []
        stop = stop_notes[-1]["stop_status"] if stop_notes else result["error"]["stop_status"] if result and result["error"] else "confirmed" if result else "unknown"
        return dict(model_call_ref=copy.deepcopy(model_call_ref), call_state=record["state"] if record else "unknown",
                    request_fingerprint=record["fingerprint"] if record else None, result_ref=record["record_ref"] + ":result" if result else None,
                    call_record_ref=record["record_ref"] if record else None, stop_status=stop,
                    usage_reconciliation=result["usage"] if result else unavailable_usage(), updated_at=record["updated_at"] if record else None,
                    reconciliation_refs=[n["payload"] for n in record["notes"] if n["kind"] in {"stop", "late_response"}] if record else [])

    async def cancel_call(self, model_call_ref, reason, call_context: CallControl) -> JSON:
        validate(model_call_ref, CALL_REF_SCHEMA)
        if not isinstance(reason, str) or not reason:
            raise ModelAdapterError("MODEL_REQUEST_INVALID", stage="cancel_reason")
        self._authorize(call_context, "cleanup", model_call_ref["invocation_ref"])
        self._control_debit(call_context)
        record = self.ledger.get(model_call_ref)
        self._record_context(record, call_context)
        active = self._active.get(digest(model_call_ref))
        if active:
            # Use the caller's independently authorized current cleanup grant.
            active.control = CallControl(active.control.context, active.control.control_budget_ticket_ref,
                                         active.control.cancel_signal, call_context.context, active.control.report_context)
            return {"model_call_ref": copy.deepcopy(model_call_ref), **(await self._stop(active, model_call_ref, debit=False))}
        if record and record["result"]:
            result = record["result"]
            stop = result["error"]["stop_status"] if result["error"] else "confirmed"
            info = dict(stop_status=stop, local_request_state=record["state"], remote_execution_state="finished" if stop == "confirmed" else "unknown", evidence_refs=[record["record_ref"]])
            if stop != "confirmed" and record["metadata"].get("driver_ref"):
                resolved = self.resolver.resolve(record["metadata"]["model_config_ref"], call_context.context)
                secret = self.credentials.resolve(resolved.config["credential_ref"], call_context.context) if resolved.config["credential_ref"] and self.credentials else None
                recovered = _Active(self.registry.get(record["metadata"]["driver_ref"]), {},
                    CallControl(call_context.context, cleanup_context=call_context.context),
                    provider_request_id=result["provider_request_id"], secret=secret)
                info = await self._stop(recovered, model_call_ref, debit=False)
                return {"model_call_ref":copy.deepcopy(model_call_ref), **info}
        else:
            info = dict(stop_status="unknown", local_request_state=record["state"] if record else "unknown", remote_execution_state="unknown", evidence_refs=[record["record_ref"]] if record else [])
        if record:
            self.ledger.append(model_call_ref, "stop", info)
        return {"model_call_ref": copy.deepcopy(model_call_ref), **info}

    @staticmethod
    def _record_context(record, control):
        if record and any(key in record["metadata"] and record["metadata"][key] != control.context[key] for key in ["input_snapshot_id", "input_snapshot_sha256"]):
            raise ModelAdapterError("MODEL_CONTROL_INVALID", stage="record_snapshot")

    @staticmethod
    def _redact(value, secret):
        if isinstance(value, str):
            return value.replace(secret, "[REDACTED]") if secret else value
        if isinstance(value, dict):
            return {ModelAdapterFacade._redact(k,secret): "[REDACTED]" if isinstance(k,str) and k.lower() in {"authorization", "api_key", "password", "secret", "access_token"} else ModelAdapterFacade._redact(v, secret) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [ModelAdapterFacade._redact(v, secret) for v in value]
        return value

