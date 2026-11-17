"""Real immutable candidate bytes, mandatory checks, and canonical Manifest."""
from __future__ import annotations

import copy

from b04.model_adapter.contracts import canonical, invocation_ref
from b04.model_adapter.schemas import conforms, strict_loads
from .contracts import MANIFEST_SCHEMA, RunnerError, pointer, sha_bytes, validate


class ArtifactCoordinator:
    def __init__(self,store,source=None):
        self.store,self.source=store,source

    def freeze(self,envelope,bundle,final,controls):
        ref=invocation_ref(envelope)
        slots=bundle["output_contract"]["slots"]
        repo=[s for s in slots if s["source"]["type"]=="repository_bundle"]
        source_control,payloads=None,{}
        if repo:
            if self.source is None:
                raise RunnerError("EXEC_CAPABILITY_UNAVAILABLE",stage="source_port",blocked=True)
            source_control,payloads=self.source.capture(envelope,repo,controls.model.context)
        artifacts={}
        for slot in slots:
            source=slot["source"]
            try:
                if source["type"]=="repository_bundle":
                    body=payloads[slot["name"]]
                elif source["type"]=="model_text":
                    body=final["response"]["text"].encode("utf-8")
                elif source["type"]=="tool_report":
                    actions=self.store.actions(ref,controls.observe.context)
                    candidates=[a for a in actions if a["kind"] in {"tool","check"} and a["state"]=="done" and a["request"].get("tool_binding_ref")==source["binding_ref"] and a["result"]["status"]=="completed"]
                    if not candidates:raise ValueError("No real report operation")
                    result=candidates[-1]["result"]
                    report_ref=result["payload"]["report_ref"]
                    if report_ref not in result["output_refs"]:raise ValueError("Missing report evidence")
                    original=self.store.read_object(report_ref,controls.observe.context)
                    report=strict_loads(original["body"].decode("utf-8"))
                    if report["invocation_ref"]!=ref or report["execution_mode"]!=envelope["execution_mode"] or report["input_snapshot_sha256"]!=envelope["input_snapshot_sha256"]:
                        raise ValueError("Wrong report origin")
                    body=original["body"]
                else:
                    parsed=strict_loads(final["response"]["text"])
                    if parsed!=final["response"].get("json_value"):
                        raise ValueError("Final text/JSON mismatch")
                    value=pointer(parsed,source.get("pointer",""))
                    if slot["media_type"]=="application/json":body=canonical(value).encode("utf-8")
                    elif isinstance(value,str):body=value.encode("utf-8")
                    else:raise ValueError("Text artifact requires a string")
                self._validate_content(body,slot,bundle)
            except RunnerError:raise
            except (KeyError,TypeError,ValueError,UnicodeError):
                raise RunnerError("EXEC_ARTIFACT_INVALID",stage="output_content") from None
            meta=self.store.put_object(ref,"candidate:"+slot["name"],slot["kind"],body,controls.model.context,
                namespace=slot["namespace"],media_type=slot["media_type"],schema_ref=slot["schema_ref"])
            artifacts[slot["name"]]=meta
        return dict(artifacts=artifacts,source_control=source_control)

    @staticmethod
    def _validate_content(body,slot,bundle):
        if not isinstance(body,bytes) or not body:
            raise RunnerError("EXEC_ARTIFACT_INVALID",stage="empty_artifact")
        if slot["media_type"]=="application/json" or slot["schema_ref"] is not None:
            try:
                text=body.decode("utf-8")
                value=strict_loads(text) if slot["media_type"]=="application/json" else text
                if slot["schema_ref"] is not None and not conforms(value,bundle["schemas"][slot["schema_ref"]]):
                    raise ValueError("Basic schema failed")
            except (ValueError,UnicodeError,KeyError):
                raise RunnerError("EXEC_ARTIFACT_INVALID",stage="artifact_schema") from None

    def verify(self,envelope,bundle,frozen,controls):
        for slot in bundle["output_contract"]["slots"]:
            expected=frozen["artifacts"][slot["name"]]
            actual=self.store.read_object(expected["artifact_ref"],controls.observe.context)
            if actual["metadata"]!=expected or sha_bytes(actual["body"])!=expected["sha256"]:
                raise RunnerError("EXEC_ARTIFACT_INVALID",stage="checked_content_changed")
            self._validate_content(actual["body"],slot,bundle)
        repo=[s for s in bundle["output_contract"]["slots"] if s["source"]["type"]=="repository_bundle"]
        if repo:
            source,body=self.source.capture(envelope,repo,controls.model.context)
            return source==frozen["source_control"] and all(sha_bytes(body[s["name"]])==frozen["artifacts"][s["name"]]["sha256"] for s in repo)
        return True

    def manifest(self,envelope,bundle,row,frozen,check_report,check_ref,model_refs,tool_refs):
        report=check_report
        result=dict(manifest_contract_version="b04.manifest.v0.2",protocol_version="b04.exec.v0.2",execution_mode=envelope["execution_mode"],
            **invocation_ref(envelope),submission_id=row["submission_id"],input_snapshot_id=envelope["input_snapshot_id"],input_snapshot_sha256=envelope["input_snapshot_sha256"],
            input_refs=copy.deepcopy(bundle["input_refs"]),workflow_definition_ref=envelope["workflow_definition_ref"],agent_definition_ref=envelope["agent_definition_ref"],
            prompt_template_ref=bundle["template"]["prompt_template_ref"],model_config_ref=envelope["model_config_ref"],tool_config_ref=envelope["tool_config_ref"],output_contract_ref=envelope["output_contract_ref"],
            author="service:agent_runner",started_at=row["started_at"],finished_at=report["finished_at"],change_summary="Saved declared candidate artifacts: "+", ".join(frozen["artifacts"]),
            model_call_refs=list(dict.fromkeys(model_refs)),tool_operation_refs=list(dict.fromkeys(tool_refs)),artifacts=list(frozen["artifacts"].values()),
            required_check_refs=report["required_check_refs"],self_check_refs=[check_ref],self_check_status=report["overall_status"],missing_check_refs=report["missing_check_refs"],
            known_issue_refs=report["known_issue_refs"],open_questions=[],source_control=frozen["source_control"],review_status="pending",execution_record_ref=row["execution_record_ref"])
        validate(result,MANIFEST_SCHEMA,"EXEC_ARTIFACT_INVALID",stage="manifest")
        return result


class CheckCoordinator:
    def __init__(self,store):
        self.store=store

    async def run(self,envelope,bundle,frozen,controls,execute_tool,guard):
        from b04.model_adapter.contracts import stamp
        refs,results,issues=[],[],[]
        ref=invocation_ref(envelope)
        for check in bundle["output_contract"]["required_checks"]:
            guard()
            refs.append(check["check_ref"])
            subjects=[{k:frozen["artifacts"][slot][k] for k in ["artifact_ref","kind","sha256"]} for slot in check["slots"]]
            actual=None;evidence=[];status="not_run";reason=None;operation_id=None
            try:
                args=copy.deepcopy(check["arguments"])
                args.update(check_ref=check["check_ref"],subjects=subjects,environment_ref=check["environment_ref"],expected=check["expected"])
                tool=await execute_tool(check["binding_ref"],args,dict(source="self_check",model_call_id=None,tool_call_id=None,check_ref=check["check_ref"]),"check:"+check["check_ref"]+":"+sha_bytes(canonical(subjects).encode("utf-8")))
                operation_id=tool["operation_id"]
                if tool["status"]!="completed":
                    raise ValueError("Checker did not complete")
                report_ref=tool["payload"]["report_ref"]
                if report_ref not in tool["output_refs"]:
                    raise ValueError("Missing check report")
                report=strict_loads(self.store.read_object(report_ref,controls.observe.context)["body"].decode("utf-8"))
                report_subjects=report.get("subjects",[report.get("subject")])
                if report_subjects!=subjects or report["invocation_ref"]!=ref or any(report[k]!=envelope[k] for k in ["input_snapshot_id","input_snapshot_sha256","execution_mode"]):
                    raise ValueError("Wrong check subject or input")
                if report["check_ref"]!=check["check_ref"] or report["environment_ref"]!=check["environment_ref"] or report["expected"]!=check["expected"] or report["result"] not in {"passed","failed"} or report["actual"] is None or tool["payload"]["check_outcome"]!=report["result"]:
                    raise ValueError("No valid professional conclusion")
                status,actual=report["result"],report["actual"]
                evidence=[report_ref,tool["operation_record_ref"]]
            except RunnerError as fault:
                if fault.blocked or fault.code in {"EXEC_LEASE_INVALID","EXEC_WRITE_SCOPE","EXEC_TIMEOUT","EXEC_BUDGET_EXHAUSTED"} or fault.stop_status!="confirmed":
                    raise
                reason=fault.code
            except (KeyError,ValueError,TypeError,UnicodeError):
                reason="CHECK_EVIDENCE_UNAVAILABLE"
            if status!="passed":
                issue=self.store.put_object(ref,"check-issue:"+check["check_ref"]+":"+sha_bytes(canonical(subjects).encode()),"check_issue",
                    canonical(dict(check_ref=check["check_ref"],subjects=subjects,result=status,reason=reason)).encode(),controls.report.context)
                issues.append(issue["artifact_ref"])
                if not evidence:evidence=[issue["artifact_ref"]]
            results.append(dict(check_ref=check["check_ref"],subjects=subjects,result=status,expected=check["expected"],actual=actual,
                                operation_id=operation_id,evidence_refs=evidence,reason=reason))
        missing=[r["check_ref"] for r in results if r["result"]=="not_run"]
        status="failed" if any(r["result"]=="failed" for r in results) else "incomplete" if missing else "passed"
        report=dict(check_report_contract_version="b04.self-check.v0.1",evidence_kind="self_check",execution_mode=envelope["execution_mode"],invocation_ref=ref,
                    input_snapshot_id=envelope["input_snapshot_id"],input_snapshot_sha256=envelope["input_snapshot_sha256"],subjects=list(frozen["artifacts"].values()),
                    environment_ref=bundle["profile"]["environment_ref"],required_check_refs=refs,results=results,overall_status=status,
                    missing_check_refs=missing,known_issue_refs=issues,finished_at=stamp())
        saved=self.store.put_object(ref,"self-check:"+sha_bytes(canonical(frozen).encode()),"self_check_report",canonical(report).encode(),controls.report.context)
        return report,saved["artifact_ref"]

