import base64
import copy
import json
import re
import subprocess
from pathlib import Path

import pytest

from b04.agent_runner import GitWorkspaceSource,RunnerError
from b04.model_adapter import MockDriver
from b04.model_adapter.contracts import canonical,invocation_ref
from .support import error,execute,manifest,object_json,run


def git(root,*args):
    return subprocess.run(["git","-c","core.hooksPath="+str(root/".empty-test-hooks"),"-c","commit.gpgsign=false","-c","core.autocrlf=false","-C",str(root),*args],check=True,capture_output=True,timeout=5).stdout.decode().strip()


def commit(root,text):
    (root/"src").mkdir(exist_ok=True)
    (root/"src/module.py").write_text(text,encoding="utf-8",newline="\n")
    git(root,"add","src/module.py")
    git(root,"-c","user.name=B04 Test","-c","user.email=b04@example.invalid","commit","-qm","isolated test commit")
    return git(root,"rev-parse","HEAD")


def source_runtime(factory,tmp_path):
    workspace=tmp_path/"repository";workspace.mkdir();git(workspace,"init","-q")
    base=commit(workspace,"value = 1\n");head=commit(workspace,"value = 2\n")
    def setup(r):
        r.envelope.update(invocation_kind="implement",task_id="TASK-CODE",workspace_ref="workspace:repository",source_control=dict(repository_ref="repository:test",base_commit=base))
        plan_ref="plan:"+r.envelope["project_id"]+"@1"
        metadata=r.store.register_input(r.envelope["project_id"],plan_ref,"task_plan",b'{"tasks":[{"id":"TASK-CODE"}]}')
        r.envelope["inputs"].append(dict(artifact_ref=plan_ref,kind="task_plan"));r.envelope["plan_ref"]=plan_ref
        r.bundle["input_refs"].append({k:metadata[k] for k in ["artifact_ref","kind","sha256","state"]})
        r.bundle["input_contract"]["allowed_states_by_kind"]["task_plan"]=["accepted"]
        r.bundle["input_contract"]["requires_plan"]=True
        r.bundle["input_contract"]["requires_task"]=True
        r.bundle["output_contract"]["response_spec"]=dict(mode="text",schema_ref=None,enforcement="local_validation")
        slot=r.bundle["output_contract"]["slots"][0]
        slot.update(kind="source_bundle",schema_ref=None,source=dict(type="repository_bundle",paths=["src"]))
        r.driver.response=MockDriver.final("Candidate files are committed in the registered workspace.")
    r=factory(setup=setup)
    source=GitWorkspaceSource(authority=r.authority);source.register("workspace:repository",r.envelope["project_id"],"repository:test",workspace)
    r.runner.artifacts.source=source
    return r,workspace,head


def test_real_git_source_bundle_is_bound_to_actual_commit_and_bytes(runtime_factory,tmp_path):
    r,workspace,head=source_runtime(runtime_factory,tmp_path)
    _,snapshot=run(execute(r));saved=manifest(r,snapshot)
    assert saved["source_control"]["candidate_commit"]==head and saved["source_control"]["base_commit"]!=head
    body=object_json(r,saved["artifacts"][0]["artifact_ref"])
    assert body["candidate_commit"]==head and base64.b64decode(body["files"][0]["content_base64"])==b"value = 2\n"
    assert saved["review_status"]=="pending" and "accepted_commit" not in saved["source_control"]


def test_check_mutation_invalidates_old_proof_and_refreezes_real_commit(runtime_factory,tmp_path):
    r,workspace,head=source_runtime(runtime_factory,tmp_path)
    original=r.tools.execute_tool;mutated=False
    async def check(req,control):
        nonlocal mutated
        result=await original(req,control)
        if req["origin"]["source"]=="self_check" and not mutated:
            mutated=True;commit(workspace,"value = 3\n")
        return result
    r.tools.execute_tool=check
    _,snapshot=run(execute(r));saved=manifest(r,snapshot)
    assert saved["source_control"]["candidate_commit"]==git(workspace,"rev-parse","HEAD")!=head
    assert len([q for q in r.tools.requests if q["origin"]["source"]=="self_check"])==2
    assert any(n["code"]=="self_check_invalidated" for n in snapshot["notes"])
    assert r.driver.send_count==1 and saved["self_check_status"]=="passed"


def test_dirty_repository_is_not_published_as_committed_evidence(runtime_factory,tmp_path):
    r,workspace,head=source_runtime(runtime_factory,tmp_path)
    (workspace/"src/module.py").write_text("dirty = True\n")
    _,snapshot=run(execute(r))
    assert error(r,snapshot)["code"]=="EXEC_INPUT_INVALID" and r.driver.send_count==0


def test_multitype_document_outputs_use_declared_slots_and_exact_text(runtime_factory):
    def setup(r):
        r.bundle["schemas"]["schema:docs@1"]=dict(type="object",properties={"design":{"type":"string"},"review":{"type":"string"}},required=["design","review"],additionalProperties=False)
        r.bundle["output_contract"]["response_spec"]["schema_ref"]="schema:docs@1"
        original=r.bundle["output_contract"]["slots"][0]
        r.bundle["output_contract"]["slots"]=[dict(**{k:v for k,v in original.items() if k not in {"name","kind","source","media_type","schema_ref"}},name=key,kind=kind,media_type="text/markdown",schema_ref=None,source=dict(type="model_json",pointer="/"+key)) for key,kind in [("design","design_document"),("review","review_report")]]
        r.bundle["output_contract"]["required_checks"][0]["slots"]=["design","review"]
        r.driver.response=MockDriver.final('{"design":"# Design\\nActual design","review":"Review with unresolved issue"}')
    r=runtime_factory(setup=setup)
    _,snapshot=run(execute(r));saved=manifest(r,snapshot)
    assert {a["kind"] for a in saved["artifacts"]}=={"design_document","review_report"}
    doc=r.store.read_object(saved["artifacts"][0]["artifact_ref"],r.issued_controls.observe.context)["body"]
    assert doc==b"# Design\nActual design"


def test_model_cannot_submit_predicted_test_report(runtime_factory):
    r=runtime_factory(setup=lambda r:r.bundle["output_contract"]["slots"][0].update(kind="test_report"))
    receipt=run(r.runner.invoke_agent(r.envelope))
    assert not receipt["accepted"] and receipt["reason_code"]=="EXEC_INPUT_INVALID" and r.driver.send_count==0


def test_tool_execution_can_supply_actual_test_report_artifact(runtime_factory):
    def setup(r):
        r.bundle["output_contract"]["slots"][0].update(kind="test_report",schema_ref=None,source=dict(type="tool_report",binding_ref="binding:run_check@1"))
        r.bundle["output_contract"]["required_checks"]=[]
        r.bundle["tool_config"]["model_binding_refs"].append("binding:run_check@1")
    r=runtime_factory(setup=setup)
    args=dict(check_ref="check:execution@1",subjects=[{k:r.bundle["input_refs"][0][k] for k in ["artifact_ref","kind","sha256"]}],environment_ref="environment:test@1",expected="Registered test executes")
    r.driver.handler=lambda _:MockDriver.tool_calls([dict(name="run_check",arguments=args)]) if r.driver.send_count==1 else MockDriver.final('{"tasks":[]}')
    _,snapshot=run(execute(r));saved=manifest(r,snapshot)
    report=object_json(r,saved["artifacts"][0]["artifact_ref"])
    assert report["actual"]=="Deterministic check fixture: passed" and report["check_ref"]=="check:execution@1"
    assert r.driver.send_count==2 and len(r.tools.requests)==1


def test_manifest_matches_protocol_example_mandatory_field_set(runtime):
    _,snapshot=run(execute(runtime));saved=manifest(runtime,snapshot)
    root=Path(__file__).resolve().parents[2]
    protocol_doc=next(p for p in root.glob("B04_*.md") if "protocol_version" in p.read_text(encoding="utf-8"))
    samples=[json.loads(t) for t in re.findall(r'```json\s*\n(.*?)\n```',protocol_doc.read_text(encoding="utf-8"),re.S)]
    template=next(s for s in samples if "manifest_contract_version" in s)
    assert set(saved)==set(template)


@pytest.mark.parametrize("accepted",[True,False])
def test_candidate_input_is_only_allowed_by_explicit_review_contract(runtime_factory,accepted):
    def setup(r):
        r.envelope["invocation_kind"]="review"
        first=r.bundle["input_refs"][0];first["state"]="candidate"
        row=r.store._db.execute("SELECT metadata FROM runner_objects WHERE ref=?",(first["artifact_ref"],)).fetchone()
        data=json.loads(row[0]);data["state"]="candidate"
        r.store._db.execute("UPDATE runner_objects SET metadata=? WHERE ref=?",(canonical(data),first["artifact_ref"]))
        if accepted:r.bundle["input_contract"]["allowed_states_by_kind"]["design_spec"]=["candidate"]
    r=runtime_factory(setup=setup)
    if accepted:
        _,snapshot=run(execute(r));assert manifest(r,snapshot)["input_refs"][0]["state"]=="candidate"
    else:
        receipt=run(r.runner.invoke_agent(r.envelope));assert not receipt["accepted"] and r.driver.send_count==0


def test_same_project_unregistered_input_is_not_read_through_tool(runtime):
    runtime.store.register_input(runtime.envelope["project_id"],"spec:unrelated@1","design_spec",b'{"secret":"not authorized"}')
    runtime.driver.response=MockDriver.tool_calls([dict(name="read_artifact",arguments=dict(artifact_ref="spec:unrelated@1"))])
    _,snapshot=run(execute(runtime));fault=error(runtime,snapshot)
    assert fault["code"]=="EXEC_TOOL_ERROR" and fault["category"]=="permission" and runtime.driver.send_count==1
    assert "not authorized" not in json.dumps(snapshot)


def test_registered_capability_catalog_reports_actual_modes(runtime):
    catalog=run(runtime.runner.describe_capabilities(runtime.envelope["inputs"][1]["artifact_ref"]))
    assert catalog["execution_modes"]==["mock"] and catalog["deterministic_agents"] is False
    with pytest.raises(RunnerError):run(runtime.runner.describe_capabilities("unregistered-catalog"))

