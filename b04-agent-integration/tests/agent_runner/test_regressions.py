import asyncio
import copy
import json
from dataclasses import replace

import pytest

from b04.agent_runner import RunnerError,SQLiteRunnerStore
from b04.agent_runner.testing import configure_runtime
from b04.model_adapter import MockDriver,ModelAdapterError
from b04.model_adapter.contracts import canonical,invocation_ref
from .support import error,execute,manifest,run
from .test_recovery import fresh_runner


@pytest.mark.parametrize("mutation",["check_status","required_checks","input_summary","output_kind"])
def test_commit_revalidates_manifest_instead_of_trusting_runner_summary(runtime,mutation):
    runtime.tools.check_outcomes["check:quality@1"]="failed"
    commit=runtime.store.commit_terminal
    def tamper(draft,context,**kwargs):
        if draft["terminal_kind"]=="candidate_submitted":
            doc=json.loads(runtime.store.read_object(draft["manifest_ref"],runtime.issued_controls.observe.context)["body"])
            if mutation=="check_status":doc["self_check_status"]="passed"
            elif mutation=="required_checks":doc["required_check_refs"]=[]
            elif mutation=="input_summary":doc["input_refs"][0]["sha256"]="b"*64
            else:doc["artifacts"][0]["kind"]="unexpected_kind"
            saved=runtime.store.put_object(draft["invocation_ref"],"tampered-manifest","manifest",canonical(doc).encode(),context)
            draft={**draft,"manifest_ref":saved["artifact_ref"],"manifest_sha256":saved["sha256"]}
        return commit(draft,context,**kwargs)
    runtime.store.commit_terminal=tamper
    _,snapshot=run(execute(runtime))
    assert snapshot["terminal"]["draft"]["terminal_kind"]=="execution_failed" and error(runtime,snapshot)["code"]=="EXEC_ARTIFACT_INVALID"
    assert not any(e["event_type"]=="candidate_submitted" for e in snapshot["events"])


def test_tool_error_keeps_raw_record_but_does_not_publish_sensitive_payload(runtime):
    sensitive="untrusted-sensitive-output"
    runtime.driver.response=MockDriver.tool_calls([dict(name="read_artifact",arguments=dict(artifact_ref=runtime.envelope["spec_ref"]))])
    runtime.tools.handlers["binding:read_artifact@1"]=lambda req,c:runtime.tools.result(req,status="failed",code="TOOL_IO_ERROR",payload={"stdout":sensitive},error={"code":"TOOL_IO_ERROR","message":sensitive})
    _,snapshot=run(execute(runtime));fault=error(runtime,snapshot)
    assert fault["details"]["tool"]["code"]=="TOOL_IO_ERROR" and sensitive not in json.dumps(snapshot)
    private=runtime.store.read_object(fault["details"]["tool"]["raw_result_ref"],runtime.issued_controls.observe.context)
    assert sensitive in private["body"].decode()


def test_model_in_progress_reads_original_result_record_without_resending(runtime):
    generate=runtime.runner.model.generate;queried=[];query=runtime.runner.model.get_call
    async def progress(req,c):
        result=await generate(req,c);result.update(status="in_progress",response=None,error=None,finish_reason=None)
        result["timing"].update(finished_at=None,duration_ms=None)
        return result
    async def observe(ref,c):queried.append(copy.deepcopy(ref));return await query(ref,c)
    runtime.runner.model.generate=progress;runtime.runner.model.get_call=observe
    _,snapshot=run(execute(runtime))
    assert snapshot["terminal"]["draft"]["terminal_kind"]=="candidate_submitted" and len(queried)==1 and runtime.driver.send_count==1


def test_runtime_invalid_model_request_is_execution_error_not_admission_rejection(runtime):
    async def bad(req,c):return dict(valid=False,request_fingerprint=None,model_config_ref=req["model_config_ref"],model_capability_ref=None,issues=[ModelAdapterError("MODEL_REQUEST_INVALID").to_dict()])
    runtime.runner.model.validate_request=bad
    receipt,snapshot=run(execute(runtime));fault=error(runtime,snapshot)
    assert receipt["accepted"] and fault["code"]=="EXEC_MODEL_ERROR" and fault["details"]["model"]["code"]=="MODEL_REQUEST_INVALID"
    assert runtime.driver.send_count==0 and snapshot["events"][0]["event_type"]=="execution_accepted"


def test_input_becoming_invalid_after_acceptance_blocks_without_model_call(runtime):
    async def scenario():
        receipt=await runtime.runner.invoke_agent(runtime.envelope);assert receipt["accepted"]
        row=runtime.store._db.execute("SELECT metadata FROM runner_objects WHERE ref=?",(runtime.envelope["spec_ref"],)).fetchone()
        meta=json.loads(row[0]);meta["state"]="stale"
        runtime.store._db.execute("UPDATE runner_objects SET metadata=? WHERE ref=?",(canonical(meta),runtime.envelope["spec_ref"]))
        snapshot=await runtime.runner.wait_invocation(invocation_ref(runtime.envelope))
        assert snapshot["terminal"]["draft"]["terminal_kind"]=="execution_blocked" and runtime.driver.send_count==0
    run(scenario())


def test_authorized_output_correction_uses_new_call_id(runtime_factory):
    r=runtime_factory(setup=lambda r:r.bundle["profile"].update(max_output_corrections=1))
    r.driver.handler=lambda _:MockDriver.final('not JSON' if r.driver.send_count==1 else '{"tasks":[]}')
    _,snapshot=run(execute(r))
    assert snapshot["terminal"]["draft"]["terminal_kind"]=="candidate_submitted" and r.driver.send_count==2
    actions=[a for a in r.store.actions(invocation_ref(r.envelope),r.issued_controls.observe.context) if a["kind"]=="model"]
    assert actions[0]["request"]["model_call_id"]!=actions[1]["request"]["model_call_id"]


def test_default_policy_does_not_correct_or_fallback(runtime):
    runtime.driver.response=MockDriver.final("not JSON")
    _,snapshot=run(execute(runtime))
    assert error(runtime,snapshot)["code"]=="EXEC_MODEL_ERROR" and runtime.driver.send_count==1


def test_actual_sqlite_reopen_preserves_terminal_objects_and_event_ids(runtime):
    async def scenario():
        _,before=await execute(runtime)
        path=runtime.store._db.execute("PRAGMA database_list").fetchone()[2]
        runtime.store.close()
        reopened=SQLiteRunnerStore(path,authority=runtime.authority)
        runtime.store=reopened;runtime.tools.store=reopened
        other=fresh_runner(runtime)
        after=await other.recover_invocation(invocation_ref(runtime.envelope))
        assert after["terminal"]==before["terminal"] and [e["event_id"] for e in after["events"]]==[e["event_id"] for e in before["events"]]
        assert runtime.driver.send_count==1
    run(scenario())


def test_observe_grant_cannot_write_checkpoint_or_diagnostic(runtime):
    async def scenario():
        await execute(runtime)
        ref=invocation_ref(runtime.envelope)
        with pytest.raises(RunnerError):runtime.store.note(ref,"bad_write",{},runtime.issued_controls.observe.context)
        with pytest.raises(RunnerError):runtime.store.put_object(ref,"bad","exec_error",b"{}",runtime.issued_controls.observe.context)
    run(scenario())


def test_cross_product_and_custom_role_use_same_core(runtime_factory):
    def setup(r):
        r.envelope.update(agent_definition_ref="agent:custom-analyzer@1",invocation_kind="custom")
        r.bundle["agent"]["agent_definition_ref"]=r.envelope["agent_definition_ref"]
    a=runtime_factory(project="csv-product");b=runtime_factory(project="inventory-product",setup=setup)
    _,sa=run(execute(a));_,sb=run(execute(b))
    assert manifest(a,sa)["project_id"]=="csv-product" and manifest(b,sb)["agent_definition_ref"]=="agent:custom-analyzer@1"


def test_foreign_stop_receipt_cannot_make_checker_failure_look_stopped(runtime):
    runtime.tools.handlers["binding:run_check@1"]=lambda *args:(_ for _ in ()).throw(RuntimeError("lost checker response"))
    async def wrong(ref,reason,control):
        foreign=copy.deepcopy(ref);foreign["operation_id"]="another-operation"
        return dict(operation_ref=foreign,stop_status="confirmed",evidence_refs=["unrelated-proof"])
    runtime.tools.stop_operation=wrong
    _,snapshot=run(execute(runtime))
    assert snapshot["terminal"]["draft"]["terminal_kind"]=="execution_failed" and error(runtime,snapshot)["stop_status"]=="unknown"


def test_malformed_successful_commit_receipt_is_queried_and_kept_unknown(runtime):
    async def scenario():
        commit=runtime.store.commit_terminal
        runtime.store.commit_terminal=lambda *args,**kwargs:dict(commit_status="committed")
        _,snapshot=await execute(runtime)
        assert snapshot["terminal"] is None and snapshot["recovery_required"]=="commit_unknown"
        runtime.store.commit_terminal=commit
        recovered=await runtime.runner.recover_invocation(invocation_ref(runtime.envelope))
        assert recovered["terminal"]["draft"]["terminal_kind"]=="candidate_submitted" and runtime.driver.send_count==1
    run(scenario())


def test_revocation_after_acceptance_before_worker_ownership_reports_failure(runtime):
    async def scenario():
        receipt=await runtime.runner.invoke_agent(runtime.envelope);assert receipt["accepted"]
        runtime.authority.invalidate_execution(invocation_ref(runtime.envelope))
        snapshot=await runtime.runner.wait_invocation(invocation_ref(runtime.envelope))
        assert snapshot["terminal"]["draft"]["terminal_kind"]=="execution_failed" and error(runtime,snapshot)["code"]=="EXEC_LEASE_INVALID" and runtime.driver.send_count==0
    run(scenario())


def test_input_invalidated_inside_terminal_transaction_cannot_publish_candidate(runtime):
    commit=runtime.store.commit_terminal
    def invalidate(draft,context,**kwargs):
        if draft["terminal_kind"]=="candidate_submitted":
            row=runtime.store._db.execute("SELECT metadata FROM runner_objects WHERE ref=?",(runtime.envelope["spec_ref"],)).fetchone()
            meta=json.loads(row[0]);meta["state"]="stale"
            runtime.store._db.execute("UPDATE runner_objects SET metadata=? WHERE ref=?",(canonical(meta),runtime.envelope["spec_ref"]))
        return commit(draft,context,**kwargs)
    runtime.store.commit_terminal=invalidate
    _,snapshot=run(execute(runtime))
    assert snapshot["terminal"]["draft"]["terminal_kind"]=="execution_blocked" and error(runtime,snapshot)["code"]=="EXEC_INPUT_INVALID"
    assert not any(e["event_type"]=="candidate_submitted" for e in snapshot["events"])


def test_manifest_execution_record_ref_resolves_to_protected_real_log(runtime):
    _,snapshot=run(execute(runtime));saved=manifest(runtime,snapshot)
    log=runtime.store.read_execution_record(saved["execution_record_ref"],runtime.issued_controls.observe.context)
    assert log["checkpoint"]["context"]["record"]["binding_names"] and log["actions"] and log["terminal"]==snapshot["terminal"]
    assert "owner" not in log
    with pytest.raises(RunnerError):runtime.store.read_execution_record(saved["execution_record_ref"],runtime.issued_controls.report.context)

