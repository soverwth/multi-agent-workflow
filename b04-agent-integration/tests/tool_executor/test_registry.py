import copy
import pytest
from b04.tool_executor import ToolExecutorError,ManagementContext,FrozenToolPolicy,SQLiteToolStore
from b04.model_adapter.contracts import invocation_ref
from b04.tool_executor.testing import tool_request
from .support import run,call,admit


def test_catalog_definition_is_immutable_and_persisted(runtime):
    reg=runtime.tool_registry;definition,state=reg.store.definition('write_file','1')
    assert state=='published'
    assert reg.register_tool(definition,runtime.admin)['publication_state']=='published'
    changed=copy.deepcopy(definition);changed['driver_ref']='other'
    with pytest.raises(ToolExecutorError,match='TOOL_OPERATION_CONFLICT'):reg.register_tool(changed,runtime.admin)
    other=SQLiteToolStore(runtime.tool_store._db.execute('PRAGMA database_list').fetchone()[2])
    try:assert other.definition('write_file','1')==(definition,'published')
    finally:other.close()


@pytest.mark.parametrize('version',['latest','LATEST','*','','1@2','a/b'])
def test_explicit_versions_only(runtime,version):
    d,_=runtime.tool_store.definition('write_file','1');d['tool_version']=version
    with pytest.raises(ToolExecutorError):runtime.tool_registry.register_tool(d,runtime.admin)


@pytest.mark.parametrize('action',['register','validate','publish','deprecate','disable','configure'])
def test_management_grant_required(runtime,action):
    reg=runtime.tool_registry;forged=ManagementContext('test:administrator','invented')
    d,_=reg.store.definition('write_file','1')
    funcs={'register':lambda:reg.register_tool(d,forged),'validate':lambda:reg.validate_tool('write_file','1',forged),'publish':lambda:reg.publish_tool('tool:write_file@1',forged),
           'deprecate':lambda:reg.deprecate_tool('write_file','1',forged),'disable':lambda:reg.disable_tool('write_file','1',forged),'configure':lambda:reg.register_profile('profile:new',{},forged)}
    with pytest.raises(ToolExecutorError,match='TOOL_SCOPE_DENIED'):funcs[action]()


def test_publish_requires_validation_and_review(runtime):
    reg=runtime.tool_registry;d,_=reg.store.definition('read_file','1');d['tool_version']='2';d['review_refs']=[]
    reg.register_tool(d,runtime.admin)
    with pytest.raises(ToolExecutorError):reg.publish_tool('tool:read_file@2',runtime.admin)
    reg.validate_tool('read_file','2',runtime.admin)
    with pytest.raises(ToolExecutorError):reg.publish_tool('tool:read_file@2',runtime.admin)


def test_deprecated_frozen_binding_works_but_cannot_be_newly_bound(runtime):
    r=runtime;r.tool_registry.deprecate_tool('read_artifact','1',r.admin)
    assert run(call(r,tool_request(r)))['status']=='completed'
    ref=invocation_ref(r.envelope);grant=r.tool_policy.for_ref(ref);grant.pop('_configuration_sha256')
    with pytest.raises(ToolExecutorError):FrozenToolPolicy(r.tool_registry).register(ref,grant)


def test_disabled_blocks_new_operation_without_business_charge(runtime):
    r=runtime;r.tool_registry.disable_tool('read_artifact','1',r.admin)
    result=run(call(r,tool_request(r)))
    assert result['result_code']=='TOOL_DISABLED' and result['status']=='rejected'
    assert r.tool_store.ticket('budget:tool-child')['consumed']['max_tool_calls']==0
    assert r.tool_store.diagnostic_record(result['operation_record_ref'])['code']=='TOOL_DISABLED'


def test_new_version_does_not_upgrade_frozen_binding(runtime):
    r=runtime;d,_=r.tool_store.definition('read_artifact','1');d['tool_version']='2'
    r.tool_registry.register_tool(d,r.admin);r.tool_registry.validate_tool('read_artifact','2',r.admin);r.tool_registry.publish_tool('tool:read_artifact@2',r.admin)
    assert run(call(r,tool_request(r)))['tool_version']=='1'


def test_preview_and_description_do_not_debit_business_budget(runtime):
    async def scenario():
        r=runtime;await admit(r)
        assert (await r.tools.describe_tool('read_artifact','1',r.issued_controls.observe))['publication_state']=='published'
        assert (await r.tools.validate_tool_request(tool_request(r),r.issued_controls.tool))['valid']
        assert r.tool_store.ticket('budget:tool-child')['consumed']['max_tool_calls']==0
    run(scenario())


def test_frozen_schema_configuration_cannot_silently_drift(runtime):
    r=runtime;r.tool_registry.schemas['schema:read@1']['additionalProperties']=True
    result=run(call(r,tool_request(r)))
    assert result['result_code']=='TOOL_REQUEST_INVALID' and result['side_effects_state']=='none'
