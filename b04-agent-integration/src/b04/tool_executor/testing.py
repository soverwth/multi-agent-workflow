"""Explicit demo composition: real runner/model facade/tools, deterministic model.

The policy/catalog/budget authorities are local fixtures, not production B02/B03.
No command backend is enabled unless one is explicitly supplied by the caller.
"""
from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path

from b04.agent_runner.testing import build_demo_runtime
from b04.model_adapter.contracts import invocation_ref,digest,stamp,utc_now,parse_time
from . import (ToolExecutor,SQLiteToolStore,ToolRegistry,ManagementAuthority,FrozenToolPolicy,
               SecureWorkspace,WorkspaceRegistry,ArtifactReadDriver,FileReadDriver,FileWriteDriver,SchemaCheckDriver,CommandDriver)
from .contracts import ToolExecutorError


def build_tool_demo_runtime(root,*,workspace=None,setup=None,configure_tools=None,sandboxes=None,**kwargs):
    root=Path(root);workspace=Path(workspace) if workspace else root/'workspace'
    workspace.mkdir(parents=True,exist_ok=True);(workspace/'src').mkdir(exist_ok=True)
    def configure(r):
        schemas=r.bundle['schemas']
        read_props=dict(path={'type':'string'},encoding={'enum':['utf-8','binary']},start_byte={'type':'integer'},end_byte={'type':'integer'},expected_sha256={'type':['string','null']})
        schemas['schema:file-read@1']=dict(type='object',properties=read_props,required=['path'],additionalProperties=False)
        cmd_props=dict(command_profile_ref={'type':'string'},parameters={'type':'object'},check_ref={'type':'string'},subjects={'type':'array'},environment_ref={'type':'string'},expected={'type':'string'})
        schemas['schema:command@1']=dict(type='object',properties=cmd_props,required=['command_profile_ref','parameters'],additionalProperties=False)
        cfg=r.bundle['tool_config']
        for binding in cfg['bindings']:
            binding['driver_ref']='builtin:'+binding['tool_name']+'@1'
            if binding['tool_name']=='write_file':cfg['definitions'][binding['binding_ref']]['permission_classes'].append('workspace_write')
        for name,schema,permission in [('read_file','schema:file-read@1','workspace_read'),('run_command','schema:command@1','process_execute')]:
            b=dict(binding_ref='binding:'+name+'@1',model_tool_name=name,tool_name=name,tool_version='1',driver_ref='builtin:'+name+'@1',model_input_schema_ref=schema,executor_input_schema_ref=schema,
                normalization_profile_ref=None,command_profile_refs=['command:check@1'] if name=='run_command' else [],model_input_schema_sha256=digest(schemas[schema]),executor_input_schema_sha256=digest(schemas[schema]))
            cfg['bindings'].append(b);cfg['model_binding_refs'].append(b['binding_ref'])
            cfg['definitions'][b['binding_ref']]=dict(tool_name=name,tool_version='1',input_schema_ref=schema,output_schema_ref='schema:tool-output@1',description='Registered '+name,permission_classes=[permission])
        if setup:setup(r)
    r=build_demo_runtime(root=root,workspace=workspace,setup=configure,**kwargs)
    ts=SQLiteToolStore(root/'tool.sqlite3');ma=ManagementAuthority();admin=ma.issue('test:administrator',['configure','register','validate','publish','deprecate','disable'])
    reg=ToolRegistry(store=ts,management_authority=ma)
    for ref,schema in r.bundle['schemas'].items():reg.register_schema(ref,schema,admin)
    reg.register_schema('schema:parameters@1',dict(type='object',properties={'target':{'type':'string'}},required=['target'],additionalProperties=False),admin)
    reg.register_runtime('runtime:reviewed@1',dict(image_id='sha256:'+'1'*64,executable='/usr/local/bin/python',argv_prefix=['-I','-B','/opt/check.py'],supervisor_python='/usr/local/bin/python'),admin)
    profiles={
        'execution:local@1':dict(execution_modes=['mock','live'],read_paths=['src'],write_paths=['src'],check_rules={'check:quality@1':dict(schema_ref='schema:plan@1',expected='Declared professional rule holds',environment_ref='environment:test@1')}),
        'limits:bounded@1':dict(max_file_bytes=4*1024*1024,max_inline_bytes=65536,max_timeout_seconds=5),
        'effects:files@1':{},'stop:bounded@1':{},'env:minimal@1':dict(variables={'LANG':'C.UTF-8'}),
        'resources:small@1':dict(max_processes=16,memory_bytes=128*1024*1024,filesystem_bytes=16*1024*1024,tmp_bytes=1024*1024,cpus=1,max_snapshot_bytes=1024*1024,max_output_bytes=1024*1024,max_files=100,stdout_bytes=4096,stderr_bytes=4096,output_policy='truncate'),
        'exit:check@1':dict(outcomes={'0':'passed','1':'failed'}),'effects:command@1':dict(read_paths=['src'],write_paths=['src']),
        'process:sandbox@1':dict(backend_ref='sandbox:test@1')}
    for ref,profile in profiles.items():reg.register_profile(ref,profile,admin)
    reg.register_command('command:check@1',dict(command_profile_ref='command:check@1',executable_ref='runtime:reviewed@1',argv_template=['{{target}}'],parameter_schema_ref='schema:parameters@1',path_parameters={'target':'read'},cwd_policy={'workspace_relative_path':'.'},
        environment_policy_ref='env:minimal@1',resource_policy_ref='resources:small@1',exit_code_policy_ref='exit:check@1',side_effect_policy_ref='effects:command@1',process_control_ref='process:sandbox@1'),admin)
    for name,driver in [('read_artifact',ArtifactReadDriver()),('read_file',FileReadDriver()),('write_file',FileWriteDriver()),('run_check',SchemaCheckDriver()),('run_command',CommandDriver())]:reg.register_driver('builtin:'+name+'@1',driver,admin)
    if configure_tools:configure_tools(reg,admin,r)
    for b in r.bundle['tool_config']['bindings']:
        legacy=r.bundle['tool_config']['definitions'][b['binding_ref']]
        d=dict(tool_name=b['tool_name'],tool_version=b['tool_version'],driver_ref=b['driver_ref'],capability_refs=['capability:generic-tool@1'],input_schema_ref=legacy['input_schema_ref'],output_schema_ref=legacy['output_schema_ref'],permission_classes=legacy['permission_classes'],
            side_effect_profile='effects:files@1',execution_profile_ref='execution:local@1',limits_profile_ref='limits:bounded@1',idempotency_policy='at-most-once',stop_query_policy_ref='stop:bounded@1',owner_ref='test:B04',review_refs=['test:reviewed-fixture'])
        reg.register_tool(d,admin);reg.validate_tool(d['tool_name'],d['tool_version'],admin);reg.publish_tool(reg.ref(d),admin)
    ws=SecureWorkspace(workspace,project_id=r.envelope['project_id'],read_paths=['src'],write_paths=['src'],exclusive_lease_ref='workspace-lease:demo')
    wr=WorkspaceRegistry();wr.register(r.envelope['workspace_ref'],ws)
    def current(request,control):
        # Authoritative runner state is checked on each byte/commit/poll boundary.
        row=r.store.get(request['invocation_ref'],control.context)
        if row and (row['stop_requested'] or row['terminal'] is not None):raise ToolExecutorError('TOOL_LEASE_INVALID',stage='runner_execution_closed')
        if row and control.context['control_generation']<row['generation']:raise ToolExecutorError('TOOL_LEASE_INVALID',stage='runner_generation_fence')
        if row and utc_now()>=parse_time(row['deadline_at']):raise ToolExecutorError('TOOL_TIMEOUT',stage='runner_deadline')
        r.runner.assembler.inputs(r.envelope,r.bundle,control.context)
    policy=FrozenToolPolicy(reg,current_check=current);e=r.envelope;ref=invocation_ref(e);ctx=r.issued_controls.tool.context
    grant=dict(invocation_ref=ref,input_snapshot_id=e['input_snapshot_id'],input_snapshot_sha256=e['input_snapshot_sha256'],lease_ref=e['lease_ref'],tool_config_ref=e['tool_config_ref'],workspace_ref=e['workspace_ref'],execution_mode=e['execution_mode'],
        tool_binding_set_ref=r.bundle['tool_config']['tool_binding_set_ref'],budget_ticket_ref=ctx['budget_ticket_ref'],write_scope=e['write_scope'],bindings=r.bundle['tool_config']['bindings'],model_binding_refs=r.bundle['tool_config']['model_binding_refs'],
        permission_classes=['artifact_read','workspace_read','workspace_write','file_write','process_execute','check_execute'],read_artifacts={i['artifact_ref']:i for i in r.bundle['input_refs']},read_paths=['src'],workspace_lease_ref=ws.exclusive_lease_ref,
        candidate_read_namespaces=e['write_scope']['artifact_namespaces'],command_profile_refs=['command:check@1'],self_check_bindings={'check:quality@1':'binding:run_check@1'},deadline_at=ctx['deadline_at'])
    policy.register(ref,grant)
    for ticket,scope,parent in [('budget:tool-parent','invocation',None),('budget:tool-child','attempt','budget:tool-parent')]:
        limits=dict(max_tool_calls=e['limits']['max_tool_calls'])
        ts.register_ticket(dict(ticket_ref=ticket,ledger_ref='budget-ledger:demo-tool',invocation_ref=ref,scope=scope,purpose='tool_execute',parent_ticket_ref=parent,limits=limits,reserved=dict.fromkeys(limits,0),consumed=dict.fromkeys(limits,0),unsettled=dict.fromkeys(limits,0),expires_at=stamp(utc_now()+timedelta(minutes=5)),state='active'))
    executor=ToolExecutor(registry=reg,store=ts,authority=r.authority,policy=policy,artifacts=r.store,workspaces=wr,control_budget=r.model_budget,sandboxes=sandboxes)
    r.tools=executor;r.runner.tools=executor;r.tool_store=ts;r.tool_registry=reg;r.tool_policy=policy;r.workspace=ws;r.management=ma;r.admin=admin
    return r


def tool_request(runtime,name='read_artifact',arguments=None,*,operation_id='operation:1',**overrides):
    e=runtime.envelope
    if arguments is None:arguments={'artifact_ref':e['spec_ref']}
    req=dict(tool_contract_version='b04.tool.v0.1',protocol_version='b04.exec.v0.2',execution_mode=e['execution_mode'],invocation_ref=invocation_ref(e),operation_id=operation_id,
        tool_binding_ref='binding:'+name+'@1',tool_name=name,tool_version='1',arguments=copy.deepcopy(arguments),input_snapshot_id=e['input_snapshot_id'],input_snapshot_sha256=e['input_snapshot_sha256'],
        lease_ref=e['lease_ref'],tool_config_ref=e['tool_config_ref'],workspace_ref=e['workspace_ref'],timeout_seconds=1,deadline_at=runtime.issued_controls.tool.context['deadline_at'],origin=dict(source='runner',model_call_id=None,tool_call_id=None,check_ref=None))
    req.update(overrides);return req
