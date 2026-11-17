"""Offline B04 runner pipeline: real SQLite/model_adapter, simulated B02/tools."""
import asyncio
import json

from b04.agent_runner.testing import build_demo_runtime
from b04.model_adapter.contracts import invocation_ref


async def main():
    runtime=build_demo_runtime(project="demo-cli-product")
    try:
        receipt=await runtime.runner.invoke_agent(runtime.envelope)
        duplicate=await runtime.runner.invoke_agent(runtime.envelope)
        snapshot=await runtime.runner.wait_invocation(invocation_ref(runtime.envelope))
        draft=snapshot["terminal"]["draft"]
        record=runtime.store.read_object(draft["manifest_ref"],runtime.issued_controls.observe.context)
        manifest=json.loads(record["body"])
        assert receipt["accepted"] and duplicate["duplicate"] and draft["terminal_kind"]=="candidate_submitted"
        assert runtime.driver.send_count==1 and manifest["review_status"]=="pending"
        print(json.dumps(dict(receipt=receipt,duplicate_receipt=duplicate,phase=snapshot["phase"],terminal_kind=draft["terminal_kind"],
            actual_model_sends=runtime.driver.send_count,actual_tool_operations=len(runtime.tools.charged),manifest=manifest,
            events=[dict(event_id=e["event_id"],event_seq=e["event_seq"],event_type=e["event_type"],delivery=e["delivery"]) for e in snapshot["events"]]),ensure_ascii=False,indent=2))
    finally:
        runtime.store.close()
        runtime.model_ledger.close()


if __name__=="__main__":asyncio.run(main())

