"""Built-in real byte drivers and controlled command/check adapters."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import PurePosixPath

from b04.model_adapter.contracts import canonical
from b04.model_adapter.schemas import conforms,strict_loads
from .contracts import DriverOutcome,ToolExecutorError
from .files import allowed,relative_parts


def sha(body):return hashlib.sha256(body).hexdigest()


class WorkspaceRegistry:
    def __init__(self):self._workspaces={}
    def register(self,workspace_ref,workspace):
        if workspace_ref in self._workspaces:raise ValueError("Workspace reference already registered")
        self._workspaces[workspace_ref]=workspace
    def get(self,workspace_ref,project_id,lease_ref):
        workspace=self._workspaces.get(workspace_ref)
        if workspace is None or workspace.project_id!=project_id or workspace.exclusive_lease_ref!=lease_ref:raise ToolExecutorError("TOOL_SCOPE_DENIED",stage="workspace_ownership")
        return workspace


class BaseDriver:
    permissions=set()
    def validate_definition(self,definition,registry):
        if not self.permissions<=set(definition['permission_classes']):raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="driver_permissions")
    def prepare(self,request,resolved,session):return {}


class ArtifactReadDriver(BaseDriver):
    permissions={'artifact_read'}
    def prepare(self,request,resolved,session):
        if request['arguments']['artifact_ref'] not in session.grant['read_artifacts']:raise ToolExecutorError("TOOL_SCOPE_DENIED",details={'denied_action':'read'})
        return {}
    async def run(self,request,prepared,session):
        session.guard();ref=request['arguments']['artifact_ref'];expected=session.grant['read_artifacts'][ref]
        try:item=session.artifacts.read_input(ref,request['invocation_ref']['project_id'],session.control.context)
        except Exception:raise ToolExecutorError("TOOL_SCOPE_DENIED",stage="artifact_access",details={'denied_action':'read'}) from None
        meta,body=item['metadata'],item['body']
        if any(meta[k]!=expected[k] for k in ['kind','state','sha256']) or sha(body)!=meta['sha256']:raise ToolExecutorError("TOOL_OUTPUT_INVALID",stage="artifact_integrity")
        if len(body)>session.limits['max_file_bytes']:raise ToolExecutorError("TOOL_BUDGET_EXHAUSTED")
        saved=session.save('artifact-observation','artifact_observation',body,media_type=meta['media_type'])
        text=None
        if len(body)<=session.limits['max_inline_bytes']:
            try:text=body.decode('utf-8')
            except UnicodeError:raise ToolExecutorError("TOOL_OUTPUT_INVALID",stage="artifact_encoding") from None
        return DriverOutcome(dict(artifact_ref=ref,kind=meta['kind'],version=meta['version'],state=meta['state'],sha256=meta['sha256'],size_bytes=len(body),content=text,content_ref=saved['artifact_ref'],inline_complete=text is not None),[],[saved['artifact_ref']])


class FileReadDriver(BaseDriver):
    permissions={'workspace_read'}
    def prepare(self,request,resolved,session):
        workspace=session.workspace();path=request['arguments']['path']
        if not allowed(path,session.grant['read_paths']) or not allowed(path,resolved['execution_profile']['read_paths']):raise ToolExecutorError("TOOL_SCOPE_DENIED",details={'denied_action':'read','resource':path})
        return dict(workspace=workspace)
    async def run(self,request,prepared,session):
        args=request['arguments'];path=args['path']
        body=prepared['workspace'].read(path,session.guard,session.limits['max_file_bytes'],read_paths=session.grant['read_paths'])
        if args.get('expected_sha256') is not None and args['expected_sha256']!=sha(body):raise ToolExecutorError("TOOL_FILE_CONFLICT",stage="read_expected_version")
        start=args.get('start_byte',0);end=args.get('end_byte',len(body))
        if type(start) is not int or type(end) is not int or start<0 or end<start or end>len(body):raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="byte_range")
        part=body[start:end];encoding=args.get('encoding','utf-8');text=None
        if encoding not in {'utf-8','binary'}:raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="encoding")
        if encoding=='utf-8':
            try:text=part.decode('utf-8')
            except UnicodeError:raise ToolExecutorError("TOOL_OUTPUT_INVALID",stage="file_encoding") from None
        saved=session.save('file-observation','file_observation',part,media_type='application/octet-stream' if encoding=='binary' else 'text/plain')
        return DriverOutcome(dict(path=path,full_sha256=sha(body),range_sha256=sha(part),size_bytes=len(part),start_byte=start,end_byte=end,complete=start==0 and end==len(body),
            text=text if len(part)<=session.limits['max_inline_bytes'] else None,content_ref=saved['artifact_ref'],encoding=encoding,inline_complete=text is not None and len(part)<=session.limits['max_inline_bytes']),[],[saved['artifact_ref']])


class FileWriteDriver(BaseDriver):
    permissions={'workspace_write'}
    def prepare(self,request,resolved,session):
        args=request['arguments'];workspace=session.workspace();path=args['path']
        if not allowed(path,session.grant['write_scope']['workspace_paths']) or not allowed(path,resolved['execution_profile']['write_paths']):raise ToolExecutorError("TOOL_SCOPE_DENIED",details={'denied_action':'write','resource':path})
        if args['mode'] not in {'create','replace'} or args.get('encoding') not in {'utf-8','binary'} or args['mode']=='replace' and not re.fullmatch('[a-fA-F0-9]{64}',str(args.get('expected_target_sha256'))):raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="write_mode")
        if 'content' in args:raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="unstaged_content")
        return dict(workspace=workspace)
    async def run(self,request,prepared,session):
        args=request['arguments'];ref=args['content_ref']
        prefix=session.control.context['draft_namespace_ref']
        if not prefix or not ref.startswith(prefix+'/'):raise ToolExecutorError("TOOL_SCOPE_DENIED",stage="draft_access")
        try:item=session.artifacts.read_object(ref,session.control.context)
        except Exception:raise ToolExecutorError("TOOL_SCOPE_DENIED",stage="draft_access") from None
        body=item['body']
        if item['metadata']['kind']!='draft_content' or sha(body)!=args['expected_content_sha256'] or sha(body)!=item['metadata']['sha256']:raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="content_integrity")
        if args['encoding']=='utf-8':
            try:body.decode('utf-8')
            except UnicodeError:raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="content_encoding") from None
        result=prepared['workspace'].write(args['path'],body,args['mode'],args['expected_target_sha256'],session.guard,session.limits['max_file_bytes'],write_paths=session.grant['write_scope']['workspace_paths'])
        session.effects='verified'
        after=session.save('written-file','file_version',result['after'],media_type='application/octet-stream')
        refs=[after['artifact_ref']]
        if result['before'] is not None:refs.append(session.save('prior-file','file_version',result['before'],media_type='application/octet-stream')['artifact_ref'])
        change=dict(path=args['path'],change_type='created' if result['before'] is None else 'replaced',before_sha256=result['before_sha256'],after_sha256=result['after_sha256'])
        return DriverOutcome(dict(path=args['path'],sha256=result['after_sha256'],size_bytes=len(body),content_ref=after['artifact_ref']),[change],refs,effects='verified')


class SchemaCheckDriver(BaseDriver):
    permissions={'check_execute'}
    def prepare(self,request,resolved,session):
        args=request['arguments'];rules=resolved['execution_profile']['check_rules'];rule=rules.get(args['check_ref'])
        if not rule or args['expected']!=rule['expected'] or args['environment_ref']!=rule['environment_ref']:raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="check_rule_binding")
        if not args['subjects'] or len(args['subjects'])>32:raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="check_subjects")
        if rule['schema_ref'] not in session.registry.schemas:raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="check_schema")
        return dict(rule=rule)
    async def run(self,request,prepared,session):
        args=request['arguments'];passed=True;actual=[]
        for subject in args['subjects']:
            session.guard()
            if not any(subject['artifact_ref'].startswith(p+'/') for p in session.grant['candidate_read_namespaces']):raise ToolExecutorError("TOOL_SCOPE_DENIED",stage="check_subject_access")
            item=session.artifacts.read_object(subject['artifact_ref'],session.control.context)
            if item['metadata']['kind']!=subject['kind'] or item['metadata']['sha256']!=subject['sha256'] or sha(item['body'])!=subject['sha256']:raise ToolExecutorError("TOOL_OUTPUT_INVALID",stage="check_subject_integrity")
            try:valid=conforms(strict_loads(item['body'].decode('utf-8')),session.registry.schemas[prepared['rule']['schema_ref']])
            except (ValueError,UnicodeError):valid=False
            passed&=valid;actual.append(dict(artifact_ref=subject['artifact_ref'],sha256=subject['sha256'],schema_ref=prepared['rule']['schema_ref'],result='passed' if valid else 'failed'))
        session.guard();outcome='passed' if passed else 'failed'
        report=dict(check_ref=args['check_ref'],invocation_ref=request['invocation_ref'],input_snapshot_id=request['input_snapshot_id'],input_snapshot_sha256=request['input_snapshot_sha256'],
                    execution_mode=request['execution_mode'],subjects=args['subjects'],environment_ref=args['environment_ref'],expected=args['expected'],actual=actual,result=outcome,evidence_kind='tool_execution')
        saved=session.save('check-report','check_evidence',canonical(report).encode())
        return DriverOutcome(dict(check_ref=args['check_ref'],check_outcome=outcome,report_ref=saved['artifact_ref']),[],[saved['artifact_ref']],exit_code=0 if passed else 1)


class CommandDriver(BaseDriver):
    permissions={'process_execute'}
    def prepare(self,request,resolved,session):
        args=request['arguments'];ref=args['command_profile_ref']
        if ref not in session.binding['command_profile_refs'] or ref not in session.grant['command_profile_refs']:raise ToolExecutorError("TOOL_SCOPE_DENIED",stage="command_profile")
        try:
            command=session.registry.commands[ref];runtime=session.registry.runtimes[command['executable_ref']]
            schema=session.registry.schemas[command['parameter_schema_ref']];parameters=args['parameters']
            if not conforms(parameters,schema):raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="command_parameters")
            executable=runtime['executable'];prefix=runtime['argv_prefix']
            if not executable.startswith('/') or PurePosixPath(executable).name.casefold() in {'sh','bash','dash','zsh','cmd.exe','powershell.exe','pwsh'}:raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="shell_entry")
            argv=[executable,*prefix]
            used=set()
            for token in command['argv_template']:
                match=re.fullmatch(r'\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}',token)
                if match:
                    used.add(match.group(1))
                    value=parameters[match.group(1)]
                    if type(value) not in {str,int,bool} or isinstance(value,str) and (value.startswith('-') or '\x00' in value or len(value)>1024):raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="command_argument")
                    argv.append(str(value).lower() if type(value) is bool else str(value))
                elif '{{' in token or '}}' in token:raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="argv_template")
                else:argv.append(token)
            if used!=set(parameters):raise ToolExecutorError('TOOL_REQUEST_INVALID',stage='unused_command_parameters')
            if any(v.casefold() in {'-c','/c','-command','--eval','-e'} for v in [*prefix,*command['argv_template']]):raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="dynamic_interpreter_entry")
            if command['cwd_policy']!={'workspace_relative_path':'.'}:raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="cwd_policy")
            environment=session.registry.profiles[command['environment_policy_ref']]['variables']
            if any(k.upper() in {'LD_PRELOAD','LD_LIBRARY_PATH','PYTHONPATH','PYTHONHOME','BASH_ENV','ENV'} for k in environment):raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="environment_injection")
            resource=session.registry.profiles[command['resource_policy_ref']]
            integers=['max_processes','memory_bytes','filesystem_bytes','tmp_bytes','max_snapshot_bytes','max_output_bytes','max_files','stdout_bytes','stderr_bytes']
            if any(type(resource.get(k)) is not int or resource[k]<=0 for k in integers) or type(resource.get('cpus')) not in {int,float} or not 0<resource['cpus']<=64 or resource.get('output_policy') not in {'truncate','stop'}:raise ToolExecutorError('TOOL_PROFILE_UNSUPPORTED',stage='resource_limits')
            effects=session.registry.profiles[command['side_effect_policy_ref']]
            process=session.registry.profiles[command['process_control_ref']]
            backend=session.sandboxes[process['backend_ref']]
            caps=backend.describe()
            if request['execution_mode'] not in caps['execution_modes'] or any(caps.get(k) is not True for k in ['filesystem_isolation','network_isolation','process_tree_stop','memory_limit','pid_limit','tmpfs_limit']):raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="required_process_isolation")
            workspace=session.workspace()
            write_paths=effects['write_paths'];read_paths=effects['read_paths']
            for path in write_paths:
                if not allowed(path,workspace.write_paths) or not allowed(path,session.grant['write_scope']['workspace_paths']):raise ToolExecutorError("TOOL_SCOPE_DENIED",stage="command_write_scope")
            for path in read_paths:
                if not allowed(path,workspace.read_paths) or not allowed(path,session.grant['read_paths']):raise ToolExecutorError("TOOL_SCOPE_DENIED",stage="command_read_scope")
            for name,access in command.get('path_parameters',{}).items():
                path=parameters[name];relative_parts(path)
                scopes=write_paths if access=='write' else read_paths if access=='read' else []
                if not allowed(path,scopes):raise ToolExecutorError('TOOL_SCOPE_DENIED',stage='command_path_parameter')
            spec=dict(runtime=runtime,argv=argv,environment=environment,resource=resource,write_paths=write_paths,read_paths=read_paths)
            backend.verify(spec)
            return dict(command=command,backend=backend,backend_ref=process['backend_ref'],spec=spec,workspace=workspace)
        except ToolExecutorError:raise
        except (KeyError,TypeError,ValueError):raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="command_configuration") from None

    async def run(self,request,prepared,session):
        spec=copy.deepcopy(prepared['spec']);workspace=prepared['workspace'];resource=spec['resource']
        snapshot_paths=list(dict.fromkeys([*spec['read_paths'],*spec['write_paths']]))
        # Write paths are intentionally readable only inside this controlled
        # baseline capture; normal read_file still requires separate read grant.
        inputs=workspace.snapshot(snapshot_paths,session.guard,max_bytes=resource['max_snapshot_bytes'],max_files=resource['max_files'],include_write_baseline=True)
        spec.update(input_files=inputs,guard=session.guard)
        raw=await session.run_command(prepared['backend'],prepared['backend_ref'],spec)
        if not isinstance(raw,dict) or type(raw.get('exit_code')) is not int or not isinstance(raw.get('files'),dict) or any(type(raw.get(n)) is not bytes or type(raw.get(n+'_truncated')) is not bool for n in ['stdout','stderr']):raise ToolExecutorError('TOOL_OUTPUT_INVALID',stage='backend_result')
        for name in ['stdout','stderr']:
            if len(raw[name])>resource[name+'_bytes']:
                raw[name]=raw[name][:resource[name+'_bytes']];raw[name+'_truncated']=True
        if any(not isinstance(p,str) or type(body) is not bytes for p,body in raw['files'].items()):raise ToolExecutorError('TOOL_OUTPUT_INVALID',stage='backend_files')
        logs=[];log_refs={}
        for name in ['stdout','stderr']:
            meta=session.save(name,'command_log',raw[name],media_type='application/octet-stream');logs.append(meta['artifact_ref']);log_refs[name+'_ref']=meta['artifact_ref']
        if resource['output_policy']=='stop' and (raw['stdout_truncated'] or raw['stderr_truncated']):
            fault=ToolExecutorError("TOOL_OUTPUT_LIMIT",stage="command_logs");fault.output_refs=logs;fault.exit_code=raw['exit_code'];raise fault
        exit_policy=session.registry.profiles[prepared['command']['exit_code_policy_ref']]
        outcome=exit_policy['outcomes'].get(str(raw['exit_code']))
        if outcome not in {'passed','failed','completed'}:
            fault=ToolExecutorError("TOOL_COMMAND_FAILED",stage="command_exit");fault.exit_code=raw['exit_code'];fault.output_refs=logs;raise fault
        files=raw['files'];changes=[]
        for path,body in files.items():
            if not allowed(path,spec['write_paths']):raise ToolExecutorError("TOOL_OUTPUT_INVALID",stage="undeclared_command_output")
        baseline={p:b for p,b in inputs.items() if any(p==w or p.startswith(w+'/') for w in spec['write_paths'])}
        if set(baseline)-set(files):raise ToolExecutorError("TOOL_OUTPUT_INVALID",stage="undeclared_deletion")
        if sum(map(len,files.values()))>resource['max_output_bytes'] or len(files)>resource['max_files']:raise ToolExecutorError("TOOL_OUTPUT_LIMIT",stage="command_files")
        required=prepared['command'].get('required_report')
        if required:
            path=required['path']
            try:
                if not conforms(strict_loads(files[path].decode('utf-8')),session.registry.schemas[required['schema_ref']]):raise ValueError("Report schema")
            except (KeyError,UnicodeError,ValueError):raise ToolExecutorError("TOOL_OUTPUT_INVALID",stage="required_command_report") from None
        try:
            for path,body in files.items():
                if baseline.get(path)==body:continue
                before=baseline.get(path)
                actual=workspace.write(path,body,'replace' if before is not None else 'create',sha(before) if before is not None else None,session.guard,session.limits['max_file_bytes'],write_paths=session.grant['write_scope']['workspace_paths'])
                session.effects='verified';changes.append(dict(path=path,change_type='replaced' if before is not None else 'created',before_sha256=actual['before_sha256'],after_sha256=actual['after_sha256']))
        except ToolExecutorError as fault:
            if changes:fault.effects='partial';fault.changes=changes
            raise
        payload=dict(exit_code=raw['exit_code'],**log_refs,stdout_truncated=raw['stdout_truncated'],stderr_truncated=raw['stderr_truncated'])
        if outcome in {'passed','failed'}:
            args=request['arguments'];check_ref=args.get('check_ref') or request['origin']['check_ref']
            report=dict(check_ref=check_ref,invocation_ref=request['invocation_ref'],input_snapshot_id=request['input_snapshot_id'],input_snapshot_sha256=request['input_snapshot_sha256'],execution_mode=request['execution_mode'],
                        subjects=args.get('subjects',[]),environment_ref=args.get('environment_ref',prepared['command']['environment_policy_ref']),expected=args.get('expected','Registered exit code policy'),
                        result=outcome,actual=dict(exit_code=raw['exit_code'],**log_refs),evidence_kind='tool_execution')
            saved=session.save('command-report','check_evidence',canonical(report).encode());logs.append(saved['artifact_ref']);payload.update(check_ref=check_ref,check_outcome=outcome,report_ref=saved['artifact_ref'])
        return DriverOutcome(payload,changes,logs,exit_code=raw['exit_code'],effects='verified')
