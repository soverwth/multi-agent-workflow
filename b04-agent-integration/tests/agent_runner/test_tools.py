import asyncio
import copy
import json

import pytest

from b04.model_adapter import MockDriver
from b04.model_adapter.contracts import canonical,invocation_ref
from .support import error,execute,manifest,run


def test_tool_round_trip_preserves_full_feedback_and_unique_model_ids(runtime):
    def handler(request):
        return MockDriver.tool_calls([dict(name="read_artifact",arguments={"artifact_ref":runtime.envelope["spec_ref"]})]) if runtime.driver.send_count==1 else MockDriver.final('{"tasks":[]}')
    runtime.driver.handler=handler
    _,snapshot=run(execute(runtime))
    assert snapshot["terminal"]["draft"]["terminal_kind"]=="candidate_submitted"
    assert runtime.driver.send_count==2 and len(runtime.tools.requests)==2
    second=runtime.driver.requests[1]
    feedback=json.loads(second["messages"][-1]["content"][0]["text"])
    assert feedback["status"]=="completed" and feedback["result_code"]=="TOOL_COMPLETED" and feedback["error"] is None
    assert feedback["stop_status"]=="confirmed" and feedback["side_effects_state"]=="none"
    assert feedback["operation_record_ref"] and feedback["tool_binding_ref"]=="binding:read_artifact@1"
    assert feedback["truncation"]==dict(fields=[],original_refs=[])
    actions=runtime.store.actions(invocation_ref(runtime.envelope),runtime.issued_controls.observe.context)
    calls=[a["request"] for a in actions if a["kind"]=="model"]
    assert len({c["model_call_id"] for c in calls})==2 and [c["call_seq"] for c in calls]==[1,2]
    assert len(set(c["model_config_ref"] for c in calls))==1
    assert runtime.model_budget.snapshot("budget:model-parent")["consumed"]["max_model_calls"]==2


def test_inline_write_is_staged_hashed_and_really_written_in_isolated_workspace(runtime_factory,tmp_path):
    workspace=tmp_path/"workspace";workspace.mkdir()
    runtime=runtime_factory(workspace=workspace)
    content="print('configured product')\n"
    def handler(_):
        return MockDriver.tool_calls([dict(name="write_file",arguments=dict(path="src/main.py",mode="create",content=content,encoding="utf-8",expected_target_sha256=None))]) if runtime.driver.send_count==1 else MockDriver.final('{"tasks":[]}')
    runtime.driver.handler=handler
    _,snapshot=run(execute(runtime))
    assert snapshot["terminal"]["draft"]["terminal_kind"]=="candidate_submitted" and (workspace/"src/main.py").read_text()==content
    req=runtime.tools.requests[0]
    assert "content" not in req["arguments"] and req["arguments"]["content_ref"] and req["arguments"]["expected_content_sha256"]
    body=runtime.store.read_object(req["arguments"]["content_ref"],runtime.issued_controls.observe.context)
    assert body["body"]==content.encode() and body["metadata"]["sha256"]==req["arguments"]["expected_content_sha256"]
    assert req["origin"]["source"]=="model" and req["tool_binding_ref"]=="binding:write_file@1"


@pytest.mark.parametrize("path",["../outside.py","/outside.py","src/../../outside.py","other/main.py","C:/outside.py"])
def test_write_scope_is_enforced_before_executor_call(runtime_factory,tmp_path,path):
    workspace=tmp_path/"workspace";workspace.mkdir()
    runtime=runtime_factory(workspace=workspace)
    runtime.driver.response=MockDriver.tool_calls([dict(name="write_file",arguments=dict(path=path,mode="create",content="x",encoding="utf-8",expected_target_sha256=None))])
    _,snapshot=run(execute(runtime))
    assert error(runtime,snapshot)["code"]=="EXEC_WRITE_SCOPE" and not runtime.tools.requests


def test_self_check_origin_does_not_forge_model_tool_call_id(runtime):
    run(execute(runtime))
    req=runtime.tools.requests[0]
    assert req["origin"]==dict(source="self_check",model_call_id=None,tool_call_id=None,check_ref="check:quality@1")


def test_tool_unknown_does_not_trigger_another_model_round(runtime):
    runtime.driver.response=MockDriver.tool_calls([dict(name="read_artifact",arguments={"artifact_ref":runtime.envelope["spec_ref"]})])
    runtime.tools.confirm_stop=False
    runtime.tools.handlers["binding:read_artifact@1"]=lambda req,c:runtime.tools.result(req,status="unknown",code="TOOL_RESULT_UNKNOWN",stop="unknown",effects="unknown",error={"code":"TOOL_RESULT_UNKNOWN"})
    _,snapshot=run(execute(runtime))
    fault=error(runtime,snapshot)
    assert fault["code"]=="EXEC_TOOL_ERROR" and fault["stop_status"]=="unknown" and fault["recoverability"]=="requires_reconciliation"
    assert runtime.driver.send_count==1 and len(runtime.tools.requests)==1


def test_tool_in_progress_only_queries_original_operation(runtime):
    def model(_):return MockDriver.tool_calls([dict(name="read_artifact",arguments={"artifact_ref":runtime.envelope["spec_ref"]})]) if runtime.driver.send_count==1 else MockDriver.final('{"tasks":[]}')
    runtime.driver.handler=model
    def tool(req,c):return runtime.tools.result(req,status="in_progress",code="TOOL_IN_PROGRESS",stop=None)
    runtime.tools.handlers["binding:read_artifact@1"]=tool
    original=runtime.tools.get_operation
    async def query(ref,c):
        req=next(r for r in runtime.tools.requests if r["operation_id"]==ref["operation_id"])
        runtime.tools.results[runtime.tools._key(req)]=runtime.tools.result(req,payload={"content":"real query completion"})
        return await original(ref,c)
    runtime.tools.get_operation=query
    _,snapshot=run(execute(runtime))
    assert snapshot["terminal"]["draft"]["terminal_kind"]=="candidate_submitted"
    assert len([r for r in runtime.tools.requests if r["tool_name"]=="read_artifact"])==1 and runtime.tools.query_count==1


def test_foreign_tool_result_cannot_become_feedback(runtime):
    runtime.driver.response=MockDriver.tool_calls([dict(name="read_artifact",arguments={"artifact_ref":runtime.envelope["spec_ref"]})])
    def wrong(req,c):
        result=runtime.tools.result(req,payload={"content":"foreign"});result["invocation_ref"]["project_id"]="other-project";return result
    runtime.tools.handlers["binding:read_artifact@1"]=wrong
    _,snapshot=run(execute(runtime))
    assert error(runtime,snapshot)["code"]=="EXEC_TOOL_ERROR" and runtime.driver.send_count==1


def test_unproven_pass_is_incomplete(runtime):
    runtime.tools.handlers["binding:run_check@1"]=lambda req,c:runtime.tools.result(req,payload=dict(check_outcome="passed",report_ref="invented"),output_refs=["invented"])
    _,snapshot=run(execute(runtime))
    assert manifest(runtime,snapshot)["self_check_status"]=="incomplete"


def test_required_checks_keep_missing_list_even_when_another_fails(runtime_factory):
    def setup(r):
        other=copy.deepcopy(r.bundle["output_contract"]["required_checks"][0]);other["check_ref"]="check:missing@1"
        r.bundle["output_contract"]["required_checks"].append(other)
    runtime=runtime_factory(setup=setup)
    runtime.tools.check_outcomes["check:quality@1"]="failed"
    original=runtime.tools.execute_tool
    async def tool(req,c):
        if req["origin"]["check_ref"]=="check:missing@1":raise RuntimeError("unavailable")
        return await original(req,c)
    runtime.tools.execute_tool=tool
    _,snapshot=run(execute(runtime));saved=manifest(runtime,snapshot)
    assert saved["self_check_status"]=="failed" and saved["missing_check_refs"]==["check:missing@1"]

