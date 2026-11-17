"""Local test/demo implementations of trusted B02/B03 ports.

These in-memory services are deliberately not a distributed authorization/budget
service. Production users inject their own Authority, ConfigResolver and BudgetPort.
"""
from __future__ import annotations

import copy
import threading
from datetime import datetime

from .contracts import ControlContext, InvocationRef, JSON, attempt_key, canonical, parse_time
from .errors import ModelAdapterError
from .ports import ResolvedModel
from .schemas import CONTROL_SCHEMA, INVOCATION_SCHEMA, validate


class InMemoryAuthority:
    def __init__(self):
        self._contexts = {}
        self._revoked = set()
        self._invalid_executions = set()
        self._lock = threading.RLock()

    def register(self, context: ControlContext) -> None:
        validate(context, CONTROL_SCHEMA, "MODEL_CONTROL_INVALID")
        with self._lock:
            ref = context["context_ref"]
            if ref in self._contexts and self._contexts[ref] != context:
                raise ValueError("Context references are immutable")
            self._contexts[ref] = copy.deepcopy(context)

    def revoke(self, context_ref: str) -> None:
        with self._lock:
            self._revoked.add(context_ref)

    def invalidate_execution(self, ref: InvocationRef) -> None:
        with self._lock:
            self._invalid_executions.add(attempt_key(ref))

    def authorize(self, context: ControlContext, purpose: str, now: datetime) -> None:
        validate(context, CONTROL_SCHEMA, "MODEL_CONTROL_INVALID")
        with self._lock:
            valid = self._contexts.get(context["context_ref"]) == context and context["context_ref"] not in self._revoked
            valid = valid and context["purpose"] == purpose and parse_time(context["deadline_at"]) > now
            valid = valid and bool(context.get(purpose + "_grant_ref"))
            if purpose == "execute":
                valid = valid and bool(context["lease_ref"]) and attempt_key(context["invocation_ref"]) not in self._invalid_executions
            if not valid:
                raise ModelAdapterError("MODEL_CONTROL_INVALID", stage="control")


class InMemoryConfigResolver:
    def __init__(self):
        self._models, self._schemas, self._bindings = {}, {}, {}

    @staticmethod
    def _put(store, key, value):
        if key in store and store[key] != value:
            raise ValueError("Versioned references cannot be overwritten")
        store[key] = copy.deepcopy(value)

    def register_model(self, config: JSON, policy: JSON, capabilities: JSON) -> None:
        canonical([config, policy, capabilities])
        self._put(self._models, config["model_config_ref"], (config, policy, capabilities))

    def register_schema(self, ref: str, schema) -> None:
        canonical(schema)
        self._put(self._schemas, ref, schema)

    def bind(self, ref: InvocationRef, binding: JSON) -> None:
        """Trusted frozen invocation metadata, never derived from a model request."""
        self._put(self._bindings, attempt_key(ref), binding)

    def resolve(self, model_config_ref: str, context: ControlContext) -> ResolvedModel:
        try:
            binding = self._bindings[attempt_key(context["invocation_ref"])]
            if binding["model_config_ref"] != model_config_ref:
                raise KeyError("Different frozen model")
            config, policy, capabilities = self._models[model_config_ref]
            if config["model_capability_ref"] != capabilities["model_capability_ref"] or binding["model_policy_ref"] != policy["model_policy_ref"]:
                raise KeyError("Invalid capability/policy reference")
            return ResolvedModel(*copy.deepcopy((config, policy, capabilities, binding)))
        except (KeyError, TypeError):
            raise ModelAdapterError("MODEL_CONFIG_INVALID", stage="config") from None

    def schema(self, schema_ref: str, context: ControlContext):
        try:
            binding = self._bindings[attempt_key(context["invocation_ref"])]
            if schema_ref not in binding["schema_refs"]:
                raise KeyError("Schema not authorized")
            return copy.deepcopy(self._schemas[schema_ref])
        except KeyError:
            raise ModelAdapterError("MODEL_CONFIG_INVALID", stage="schema") from None


class InMemoryBudget:
    """Atomic parent/child reservations; unsettled is a subset of reserved."""
    def __init__(self):
        self._tickets, self._reservations = {}, {}
        self._lock = threading.RLock()

    def register(self, ticket: JSON) -> None:
        required = {"ticket_ref", "ledger_ref", "invocation_ref", "scope", "purpose", "parent_ticket_ref", "limits", "reserved", "consumed", "unsettled", "expires_at", "state"}
        if set(ticket) != required or ticket["scope"] not in {"invocation", "attempt"} or ticket["purpose"] not in {"model_send", "tool_execute", "control", "transport"}:
            raise ValueError("Invalid BudgetTicket")
        validate(ticket["invocation_ref"], INVOCATION_SCHEMA, "MODEL_REQUEST_INVALID")
        keys = set(ticket["limits"])
        for field in ["limits", "reserved", "consumed", "unsettled"]:
            if set(ticket[field]) != keys or any(type(x) is not int or x < 0 for x in ticket[field].values()):
                raise ValueError("Invalid budget counters")
        if ticket["scope"] == "attempt" and not ticket["parent_ticket_ref"]:
            raise ValueError("Attempt ticket requires parent")
        if ticket["state"] not in {"active", "exhausted", "expired", "closed"}:
            raise ValueError("Invalid ticket state")
        if any(ticket["unsettled"][k] > ticket["reserved"][k] for k in keys):
            raise ValueError("Unsettled is a subset of reserved")
        parse_time(ticket["expires_at"])
        with self._lock:
            if ticket["ticket_ref"] in self._tickets:
                raise ValueError("Ticket already registered; cannot reset consumption")
            self._tickets[ticket["ticket_ref"]] = copy.deepcopy(ticket)

    def snapshot(self, ticket_ref: str) -> JSON:
        with self._lock:
            return copy.deepcopy(self._tickets[ticket_ref])

    def _chain(self, ticket_ref, ref, purpose, now):
        chain, seen = [], set()
        while ticket_ref:
            if ticket_ref in seen or ticket_ref not in self._tickets:
                raise ModelAdapterError("MODEL_BUDGET_EXHAUSTED", stage="budget")
            seen.add(ticket_ref)
            ticket = self._tickets[ticket_ref]
            binding_keys = ["project_id", "run_id", "invocation_id"]
            if ticket["scope"] == "attempt":
                binding_keys += ["attempt_id", "dispatch_id", "task_id"]
            if ticket["purpose"] != purpose or any(ticket["invocation_ref"][k] != ref[k] for k in binding_keys):
                raise ModelAdapterError("MODEL_BUDGET_EXHAUSTED", stage="budget")
            if ticket["state"] != "active" or parse_time(ticket["expires_at"]) <= now:
                raise ModelAdapterError("MODEL_BUDGET_EXHAUSTED", stage="budget")
            chain.append(ticket)
            ticket_ref = ticket["parent_ticket_ref"]
            if ticket_ref and self._tickets.get(ticket_ref, {}).get("scope") != "invocation":
                raise ModelAdapterError("MODEL_BUDGET_EXHAUSTED", stage="budget")
        return chain

    @staticmethod
    def _fits(chain, amounts):
        return all(k in t["limits"] and t["consumed"][k] + t["reserved"][k] + v <= t["limits"][k]
                   for t in chain for k, v in amounts.items())

    def consume_control(self, ticket_ref, invocation_ref, now):
        with self._lock:
            chain = self._chain(ticket_ref, invocation_ref, "control", now)
            if not self._fits(chain, {"max_control_actions": 1}):
                raise ModelAdapterError("MODEL_BUDGET_EXHAUSTED", stage="control_budget")
            for ticket in chain:
                ticket["consumed"]["max_control_actions"] += 1

    def reserve(self, ticket_ref, transport_id, invocation_ref, tokens, now):
        with self._lock:
            if transport_id in self._reservations:
                old = self._reservations[transport_id]
                if old["ticket_ref"] != ticket_ref or old["tokens"] != tokens or old["invocation_ref"] != invocation_ref:
                    raise ModelAdapterError("MODEL_CALL_CONFLICT", stage="budget")
                return
            chain = self._chain(ticket_ref, invocation_ref, "model_send", now)
            amounts = {"max_model_calls": 1, "max_total_tokens": tokens}
            if not self._fits(chain, amounts):
                raise ModelAdapterError("MODEL_BUDGET_EXHAUSTED", stage="budget")
            for ticket in chain:
                for k, v in amounts.items():
                    ticket["reserved"][k] += v
            self._reservations[transport_id] = dict(ticket_ref=ticket_ref, tokens=tokens, invocation_ref=copy.deepcopy(invocation_ref),
                                                     chain=[t["ticket_ref"] for t in chain], settled=False)

    def settle(self, transport_id, *, delivery, usage):
        with self._lock:
            reservation = self._reservations[transport_id]
            if reservation["settled"]:
                return
            for ref in reservation["chain"]:
                ticket = self._tickets[ref]
                for key, amount in [("max_model_calls", 1), ("max_total_tokens", reservation["tokens"])]:
                    known = delivery == "not_sent" or (delivery == "sent" and (key == "max_model_calls" or usage["availability"] == "observed" and usage["total_tokens"] is not None))
                    if known:
                        actual = 0 if delivery == "not_sent" else 1 if key == "max_model_calls" else usage["total_tokens"]
                        ticket["reserved"][key] -= amount
                        ticket["consumed"][key] += actual
                        if ticket["consumed"][key] + ticket["reserved"][key] > ticket["limits"][key]:
                            ticket["state"] = "exhausted"
                    else:
                        ticket["unsettled"][key] += amount
            reservation["settled"] = True


class MappingCredentialResolver:
    def __init__(self, secrets: dict[str, str]):
        self._secrets = dict(secrets)

    def resolve(self, credential_ref, context):
        try:
            secret = self._secrets[credential_ref]
            if not isinstance(secret, str) or not secret:
                raise KeyError(credential_ref)
            return secret
        except KeyError:
            raise ModelAdapterError("MODEL_AUTH_FAILED", stage="credentials") from None

