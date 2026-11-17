"""Offline three-module pipeline: deterministic model, actual byte I/O and check."""
import asyncio
import json
from pathlib import Path
import tempfile

from b04.model_adapter import MockDriver
from b04.model_adapter.contracts import invocation_ref
from b04.tool_executor.testing import build_tool_demo_runtime


async def main():
    with tempfile.TemporaryDirectory(prefix='b04-tool-demo-') as root:
        r=build_tool_demo_runtime(Path(root),project='demo-configurable-product')
        def respond(_):
            if r.driver.send_count==1:
                return MockDriver.tool_calls([dict(name='write_file',arguments=dict(path='src/readme.txt',mode='create',content='Configured product artifact\r\n',encoding='utf-8',expected_target_sha256=None))])
            return MockDriver.final('{"tasks":[{"id":"implement-configured-product"}]}')
        r.driver.handler=respond
        try:
            receipt=await r.runner.invoke_agent(r.envelope)
            snapshot=await r.runner.wait_invocation(invocation_ref(r.envelope))
            draft=snapshot['terminal']['draft']
            assert receipt['accepted'] and draft['terminal_kind']=='candidate_submitted',snapshot
            manifest=json.loads(r.store.read_object(draft['manifest_ref'],r.issued_controls.observe.context)['body'])
            written=(r.workspace.root/'src/readme.txt').read_bytes()
            assert written==b'Configured product artifact\r\n'
            print(json.dumps(dict(execution_mode='mock',model_backend='deterministic mock',tool_backend='actual scoped files and JSON Schema check',
                terminal_kind=draft['terminal_kind'],self_check_status=manifest['self_check_status'],review_status=manifest['review_status'],actual_model_sends=r.driver.send_count,
                actual_tool_operations=r.tool_store.ticket('budget:tool-parent')['consumed']['max_tool_calls'],written_bytes=len(written),tool_operation_refs=manifest['tool_operation_refs']),ensure_ascii=False,indent=2))
        finally:
            await r.tools.aclose();r.tool_store.close();r.store.close();r.model_ledger.close()


if __name__=='__main__':asyncio.run(main())
