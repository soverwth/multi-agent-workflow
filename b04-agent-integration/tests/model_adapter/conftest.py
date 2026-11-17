from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import timedelta

import pytest

from b04.model_adapter import (CallControl, InMemoryAuthority, InMemoryBudget, InMemoryConfigResolver, MockDriver,
    ModelAdapterFacade, ProviderDriverRegistry, SQLiteCallLedger, mock_capabilities)
from b04.model_adapter.contracts import digest, invocation_ref, model_call_ref, stamp, utc_now


@dataclass
class System:
    adapter: ModelAdapterFacade
    request: dict
    controls: dict
    authority: InMemoryAuthority
    budget: InMemoryBudget
    resolver: InMemoryConfigResolver
    registry: ProviderDriverRegistry
    ledger: SQLiteCallLedger
    driver: MockDriver
    config: dict
    policy: dict
    caps: dict
    binding: dict

    @property
    def control(self):
        return self.controls["execute"]

    @property
    def ref(self):
        return model_call_ref(self.request)

    def next_request(self):
        result = copy.deepcopy(self.request)
        result["call_seq"] += 1
        result["model_call_id"] += "-next"
        return result


@pytest.fixture
def system_factory(tmp_path):
    ledgers = []

    def build(*, driver=None, model="mock-one", attempt=1, project="product-one", ledger_path=None, parent_calls=10, child_calls=10, tokens=1000000, controls=200, provider="mock"):
        driver = driver or MockDriver()
        resolver, registry, authority, budget = InMemoryConfigResolver(), ProviderDriverRegistry(), InMemoryAuthority(), InMemoryBudget()
        config_ref = "model:" + model + "@1"
        caps = mock_capabilities("model-capability:" + model + "@1")
        config = dict(model_config_ref=config_ref, provider=provider, model_id=model, driver_ref="driver:" + model + "@1",
                      model_capability_ref=caps["model_capability_ref"], endpoint_ref=None, credential_ref=None,
                      generation_defaults={"temperature": 0.2}, provider_options={}, transport_policy_ref="transport:single-send@1")
        policy = dict(model_policy_ref="model-policy:generic@1", allowed_model_config_refs=[config_ref],
                      allowed_parameter_overrides=["temperature", "seed"], allow_local_validation=True, strict_token_budget=True)
        request = dict(adapter_contract_version="b04.model.v0.1", protocol_version="b04.exec.v0.2", execution_mode=provider,
                       project_id=project, run_id="run-one", invocation_id="invocation-one", task_id=None, attempt_id=attempt,
                       dispatch_id="dispatch-" + str(attempt), model_call_id="call-1", call_seq=1,
                       input_snapshot_id="snapshot-" + str(attempt), input_snapshot_sha256="a"*64,
                       agent_definition_ref="agent:pm@1", prompt_template_ref="prompt:pm@1",
                       model_policy_ref=policy["model_policy_ref"], model_config_ref=config_ref,
                       messages=[dict(role="system", content=[dict(type="text", text="Follow the product contract.")]),
                                 dict(role="user", content=[dict(type="text", text="Create a product plan.")])],
                       response_spec=dict(mode="text", schema_ref=None, enforcement="local_validation"), tools=[], tool_choice="none",
                       parameters={}, call_limits=dict(timeout_seconds=2, deadline_at=stamp(utc_now()+timedelta(minutes=2)), max_output_tokens=1000),
                       budget_ticket_ref="budget:attempt-" + str(attempt))
        ref = invocation_ref(request)
        plan_schema = dict(type="object", properties={"tasks": {"type": "array", "items": {"type": "object"}}}, required=["tasks"], additionalProperties=False)
        input_schema = dict(type="object", properties={"artifact_ref": {"type": "string"}}, required=["artifact_ref"], additionalProperties=False)
        tool_binding = dict(binding_ref="binding:read@1", model_tool_name="read_artifact", tool_name="read_artifact", tool_version="1",
                            driver_ref="tool-driver:read@1", model_input_schema_ref="schema:read@1", executor_input_schema_ref="schema:read@1",
                            normalization_profile_ref=None, command_profile_refs=[], model_input_schema_sha256=digest(input_schema), executor_input_schema_sha256=digest(input_schema))
        binding = {k: copy.deepcopy(request[k]) for k in ["model_config_ref", "model_policy_ref", "agent_definition_ref", "prompt_template_ref", "input_snapshot_id", "input_snapshot_sha256", "execution_mode"]}
        binding.update(tool_binding_set_ref="tool-set:read@1", tool_bindings=[tool_binding], schema_refs=["schema:plan@1", "schema:read@1"])
        resolver.register_schema("schema:plan@1", plan_schema)
        resolver.register_schema("schema:read@1", input_schema)
        resolver.register_model(config, policy, caps)
        resolver.bind(ref, binding)
        registry.register(config["driver_ref"], driver)
        expires = stamp(utc_now()+timedelta(minutes=5))
        def ticket(ticket_ref, scope, purpose, parent, limits):
            return dict(ticket_ref=ticket_ref, ledger_ref="ledger:budget", invocation_ref=ref, scope=scope, purpose=purpose,
                        parent_ticket_ref=parent, limits=limits, reserved=dict.fromkeys(limits, 0), consumed=dict.fromkeys(limits, 0),
                        unsettled=dict.fromkeys(limits, 0), expires_at=expires, state="active")
        budget.register(ticket("budget:parent", "invocation", "model_send", None, dict(max_model_calls=parent_calls, max_total_tokens=tokens)))
        budget.register(ticket(request["budget_ticket_ref"], "attempt", "model_send", "budget:parent", dict(max_model_calls=child_calls, max_total_tokens=tokens)))
        budget.register(ticket("budget:control", "invocation", "control", None, dict(max_control_actions=controls)))
        contexts = {}
        for purpose in ["execute", "observe", "report", "cleanup"]:
            context = dict(control_contract_version="b04.control.v0.1", context_ref="context:"+purpose+":"+str(attempt), subject_ref="service:runner",
                           invocation_ref=ref, input_snapshot_id=request["input_snapshot_id"], input_snapshot_sha256=request["input_snapshot_sha256"],
                           purpose=purpose, execute_grant_ref=None, lease_ref="lease:"+str(attempt), observe_grant_ref=None, report_grant_ref=None, cleanup_grant_ref=None,
                           control_generation=1, read_scope_ref="read-scope:one" if purpose=="execute" else None,
                           write_scope={"workspace_paths": [], "artifact_namespaces": ["candidate:one"]} if purpose=="execute" else None,
                           tool_binding_set_ref=binding["tool_binding_set_ref"] if purpose=="execute" else None,
                           draft_namespace_ref=None, budget_ticket_ref=request["budget_ticket_ref"] if purpose=="execute" else "budget:control",
                           deadline_at=expires, cancel_signal_ref=None)
            context[purpose+"_grant_ref"]="grant:"+purpose
            authority.register(context)
            contexts[purpose]=context
        runtime_controls={p:CallControl(copy.deepcopy(c), "budget:control", cleanup_context=copy.deepcopy(contexts["cleanup"]), report_context=copy.deepcopy(contexts["report"])) for p,c in contexts.items()}
        ledger=SQLiteCallLedger(ledger_path or tmp_path / ("calls-"+str(len(ledgers))+".sqlite3"))
        ledgers.append(ledger)
        adapter=ModelAdapterFacade(resolver=resolver, registry=registry, ledger=ledger, budget=budget, authority=authority)
        return System(adapter, request, runtime_controls, authority, budget, resolver, registry, ledger, driver, config, policy, caps, binding)

    yield build
    for ledger in ledgers:
        ledger.close()


@pytest.fixture
def system(system_factory):
    return system_factory()


def add_tool(system, request=None):
    req=request if request is not None else system.request
    req["tools"]=[dict(name="read_artifact", description="Read an authorized artifact", input_schema=system.resolver.schema("schema:read@1", system.control.context), binding_ref="binding:read@1")]
    req["tool_choice"]="auto"
    return req


def structured(system, mode="json_schema", enforcement="local_validation"):
    system.request["response_spec"]=dict(mode=mode, schema_ref="schema:plan@1" if mode=="json_schema" else None, enforcement=enforcement)
    return system.request

