"""Provider-neutral driver registry and an explicitly simulated driver."""
from __future__ import annotations

import copy
import inspect

from .contracts import JSON, canonical, digest, unavailable_usage
from .errors import ModelAdapterError
from .ports import ProviderDriver, TokenEstimate
from .schemas import SCHEMA_KEYWORDS


class ProviderDriverRegistry:
    def __init__(self):
        self._drivers: dict[str, ProviderDriver] = {}

    def register(self, driver_ref: str, driver: ProviderDriver):
        if not driver_ref or driver_ref in self._drivers:
            raise ValueError("Driver reference is empty or already registered")
        self._drivers[driver_ref] = driver

    def get(self, driver_ref: str) -> ProviderDriver:
        try:
            return self._drivers[driver_ref]
        except KeyError:
            raise ModelAdapterError("MODEL_CAPABILITY_UNSUPPORTED", stage="driver_registry") from None


def mock_capabilities(ref="model-capability:mock@1") -> JSON:
    return dict(model_capability_ref=ref, input_modalities=["text"], instruction_roles=["system", "user", "assistant", "tool"],
                structured_output_modes=["text", "json_object", "json_schema"], provider_structured_output_modes=["json_object", "json_schema"],
                native_tool_calls=True, parallel_tool_calls=False, tools_with_structured_output=True,
                supported_parameters={"temperature": {"type": "number", "minimum": 0, "maximum": 2}, "seed": {"type": "integer"}},
                provider_option_schema={"type": "object", "properties": {}, "additionalProperties": False},
                schema_keywords=sorted(SCHEMA_KEYWORDS), context_window_tokens=100000, max_output_tokens=8192,
                token_upper_bound=True, cancellation="remote_confirmed", usage_reporting=["estimated"])


class MockDriver:
    """A deterministic simulation, not evidence of provider-side schema enforcement.

    `handler` can be async to inject delays/failures. It receives prepared content,
    never credentials. It is called at most once per claimed model_call_id.
    """
    execution_modes = frozenset({"mock"})

    def __init__(self, response: JSON | None = None, *, handler=None, confirm_cancel=True):
        self.response = copy.deepcopy(self.final("mock response") if response is None else response)
        self.handler = handler
        self.confirm_cancel = confirm_cancel
        self.send_count = 0
        self.cancel_count = 0
        self.requests = []

    @staticmethod
    def final(text: str, *, finish_reason="stop", usage=None):
        return dict(text=text, tool_calls=[], finish_reason=finish_reason, provider_finish_reason=None,
                    provider_request_id=None, reported_model_version=None, usage=unavailable_usage() if usage is None else usage)

    @staticmethod
    def tool_calls(calls, *, text=None):
        reply = MockDriver.final(text)
        reply.update(tool_calls=copy.deepcopy(calls), finish_reason="tool_calls")
        return reply

    def describe(self):
        return mock_capabilities()

    def validate_mapping(self, prepared):
        if prepared["execution_mode"] != "mock":
            raise ModelAdapterError("MODEL_CONFIG_INVALID", stage="driver_mode")

    def estimate_input_tokens(self, prepared):
        # Mock-only deterministic accounting. This is not a provider tokenizer.
        return TokenEstimate(len(canonical({k: prepared[k] for k in ["messages", "tools", "response_spec", "schema"]}).encode("utf-8")), True)

    async def send_once(self, prepared, credential, timeout_seconds):
        self.send_count += 1
        self.requests.append(copy.deepcopy(prepared))
        raw = self.handler(copy.deepcopy(prepared)) if self.handler else copy.deepcopy(self.response)
        if inspect.isawaitable(raw):
            raw = await raw
        return raw

    def normalize(self, raw):
        return copy.deepcopy(raw)

    async def cancel(self, call_ref, provider_request_id):
        self.cancel_count += 1
        return dict(stop_status="confirmed" if self.confirm_cancel else "unknown",
                    local_request_state="cancel_requested", remote_execution_state="stopped" if self.confirm_cancel else "unknown",
                    evidence_refs=["mock-stop:" + digest(call_ref)] if self.confirm_cancel else [])

