import asyncio
import json
from b04.model_adapter.contracts import invocation_ref


def run(awaitable):return asyncio.run(awaitable)


async def execute(runtime):
    receipt=await runtime.runner.invoke_agent(runtime.envelope)
    assert receipt["accepted"],receipt
    snapshot=await runtime.runner.wait_invocation(invocation_ref(runtime.envelope))
    return receipt,snapshot


def object_json(runtime,ref):
    return json.loads(runtime.store.read_object(ref,runtime.issued_controls.observe.context)["body"])


def manifest(runtime,snapshot):
    return object_json(runtime,snapshot["terminal"]["draft"]["manifest_ref"])


def error(runtime,snapshot):return object_json(runtime,snapshot["terminal"]["draft"]["error_ref"])

