import pytest
from b04.tool_executor.testing import build_tool_demo_runtime


@pytest.fixture
def runtime_factory(tmp_path):
    values=[]
    def factory(**kwargs):
        runtime=build_tool_demo_runtime(tmp_path/('case-'+str(len(values))),**kwargs)
        values.append(runtime);return runtime
    yield factory
    for r in values:
        r.tool_store.close();r.store.close();r.model_ledger.close()


@pytest.fixture
def runtime(runtime_factory):return runtime_factory(auto_start=False)
