import pytest
from b04.agent_runner.testing import build_demo_runtime


@pytest.fixture
def runtime_factory(tmp_path):
    values=[]
    def factory(**kwargs):
        kwargs.setdefault("root",tmp_path/("case-"+str(len(values))))
        runtime=build_demo_runtime(**kwargs)
        values.append(runtime)
        return runtime
    yield factory
    for runtime in values:
        runtime.store.close()
        runtime.model_ledger.close()


@pytest.fixture
def runtime(runtime_factory):return runtime_factory()

