"""Versioned, authorised, at-most-once tool execution with honest uncertainty."""
from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import dataclass,field
from datetime import timedelta
from uuid import uuid4

from b04.model_adapter.contracts import canonical,digest,parse_time,stamp,utc_now
from b04.model_adapter.errors import ModelAdapterError
from .contracts import OPERATION_SCHEMA,TOOL_REQUEST_SCHEMA,TOOL_RESULT_SCHEMA,ToolExecutorError,operation_ref,op_key,validate


@dataclass
class Active:
    session:object
    start_task:asyncio.Task|None=None
    unit:object=None
    stop_lock:asyncio.Lock=field(default_factory=asyncio.Lock)


class Session:
    def __init__(self,executor,request,resolved,policy,control,started_at,record):
        self.executor,self.request,self.resolved,self.control,self.record=executor,request,resolved,control,record
        self.registry,self.artifacts,self.sandboxes=executor.registry,executor.artifacts,executor.sandboxes
        self.grant,self.binding=policy['grant'],policy['binding'];self.limits=resolved['limits'];self.effects='none'
        self.executed=False;self.outcome=None;self.cleanup_ms=0
        self.ref=operation_ref(request)
        self.deadline=min(parse_time(request['deadline_at']),parse_time(control.context['deadline_at']),parse_time(self.grant['deadline_at']),
                          parse_time(started_at)+timedelta(seconds=min(request['timeout_seconds'],self.limits['max_timeout_seconds'])))

    def guard(self):
        self.executor._authorize(self.control,'execute',self.ref)
        self.executor.policy.check_current(self.request,self.control)
        if self.executor.store.stopped(self.ref) or self.control.cancel_signal is not None and self.control.cancel_signal.is_set():raise ToolExecutorError('TOOL_STOPPED',stage='stop_requested')
        if utc_now()>=self.deadline:raise ToolExecutorError('TOOL_TIMEOUT',stage='effective_deadline')

    def workspace(self):
        return self.executor.workspaces.get(self.request['workspace_ref'],self.request['invocation_ref']['project_id'],self.grant['workspace_lease_ref'])

    def save(self,name,kind,body,*,media_type='application/json'):
        context=self.executor._aux(self.control,'report',self.ref)
        return self.artifacts.put_object(self.ref['invocation_ref'],'tool:'+self.ref['operation_id']+':'+name,kind,body,context,media_type=media_type)

    async def run_command(self,backend,backend_ref,spec):
        active=self.executor._active[op_key(self.ref)]
        unit_ref='b04-'+uuid4().hex
        self.executor.store.append(self.ref,'unit_allocated',dict(backend_ref=backend_ref,unit_ref=unit_ref))
        self.executor._units[op_key(self.ref)]=(backend_ref,unit_ref)
        active.start_task=asyncio.create_task(asyncio.to_thread(backend.start,spec,unit_ref))
        try:
            while not active.start_task.done():
                self.guard();await asyncio.sleep(self.executor.poll_interval)
            active.unit=active.start_task.result()
            self.executor.store.append(self.ref,'unit_started',dict(backend_ref=backend_ref,unit_ref=unit_ref))
            while True:
                self.guard()
                polling=asyncio.create_task(asyncio.to_thread(active.unit.poll))
                try:
                    while not polling.done():
                        self.guard();await asyncio.sleep(self.executor.poll_interval)
                    result=polling.result()
                finally:
                    if not polling.done():self.executor._retain(polling)
                if result is not None:return result
                await asyncio.sleep(self.executor.poll_interval)
        except BaseException:
            if not active.start_task.done():
                self.executor._background.add(active.start_task)
                def cleanup(future):
                    self.executor._background.discard(future)
                    try:
                        unit=future.result()
                        async def stop_late():
                            self.executor._aux(self.control,'cleanup',self.ref)
                            receipt=await self.executor._bounded_stop(self.ref,unit.stop,self.executor.cleanup_timeout)
                            self.executor._aux(self.control,'report',self.ref)
                            self.executor.store.append(self.ref,'late_start_cleanup',receipt)
                            closing=asyncio.create_task(asyncio.to_thread(unit.close))
                            try:await asyncio.wait_for(asyncio.shield(closing),self.executor.cleanup_timeout)
                            except TimeoutError:self.executor._retain(closing)
                        task=asyncio.create_task(stop_late());self.executor._retain(task)
                    except BaseException:pass
                active.start_task.add_done_callback(cleanup)
            raise


class ToolExecutor:
    def __init__(self,*,registry,store,authority,policy,artifacts,workspaces,control_budget,sandboxes=None,poll_interval_seconds=.01,cleanup_timeout_seconds=.5):
        if poll_interval_seconds<=0 or cleanup_timeout_seconds<=0:raise ValueError('Positive time limits required')
        self.registry,self.store,self.authority,self.policy=registry,store,authority,policy
        self.artifacts,self.workspaces,self.control_budget=artifacts,workspaces,control_budget
        self.sandboxes=sandboxes or {};self.poll_interval=poll_interval_seconds;self.cleanup_timeout=cleanup_timeout_seconds
        self._active={};self._units={};self._background=set()

    def _retain(self,task):
        self._background.add(task)
        def done(future):
            self._background.discard(future)
            try:future.result()
            except BaseException:pass
        task.add_done_callback(done)

    def _authorize(self,control,purpose,ref):
        try:
            self.authority.authorize(control.context,purpose,utc_now())
            if control.context['invocation_ref']!=ref['invocation_ref']:raise KeyError('Wrong invocation')
            grant=self.policy.for_ref(ref['invocation_ref'])
            if any(control.context[k]!=grant[k] for k in ['input_snapshot_id','input_snapshot_sha256']):raise KeyError('Wrong snapshot')
        except (ModelAdapterError,KeyError,TypeError):raise ToolExecutorError('TOOL_LEASE_INVALID',stage='authority') from None

    def _aux(self,control,purpose,ref):
        context=control.report_context if purpose=='report' else control.cleanup_context
        if context is None:raise ToolExecutorError('TOOL_LEASE_INVALID',stage=purpose+'_grant')
        from b04.model_adapter.contracts import CallControl
        auxiliary=CallControl(context)
        self._authorize(auxiliary,purpose,ref)
        return context

    def _control_debit(self,control):
        ticket=control.control_budget_ticket_ref if control.context['purpose']=='execute' else control.context['budget_ticket_ref']
        try:self.control_budget.consume_control(ticket,control.context['invocation_ref'],utc_now())
        except (ModelAdapterError,KeyError):raise ToolExecutorError('TOOL_BUDGET_EXHAUSTED',stage='control_budget') from None

    def _base(self,request,control):
        validate(request,TOOL_REQUEST_SCHEMA)
        ref=operation_ref(request);self._authorize(control,'execute',ref)
        origin=request['origin']
        if origin['source']=='model' and (not origin['model_call_id'] or not origin['tool_call_id'] or origin['check_ref'] is not None) or origin['source']=='self_check' and (not origin['check_ref'] or origin['model_call_id'] is not None or origin['tool_call_id'] is not None) or origin['source']=='runner' and any(origin[k] is not None for k in ['model_call_id','tool_call_id','check_ref']):raise ToolExecutorError('TOOL_REQUEST_INVALID',stage='origin')
        policy=self.policy.resolve(request,control)
        resolved=self.registry.resolve(request['tool_name'],request['tool_version'])
        if not set(resolved['definition']['permission_classes'])<=set(policy['grant']['permission_classes']):raise ToolExecutorError('TOOL_SCOPE_DENIED',stage='permission_classes')
        if request['execution_mode'] not in resolved['execution_profile']['execution_modes']:raise ToolExecutorError('TOOL_PROFILE_UNSUPPORTED',stage='execution_mode')
        if origin['source']=='self_check' and policy['grant']['self_check_bindings'].get(origin['check_ref'])!=request['tool_binding_ref']:raise ToolExecutorError('TOOL_SCOPE_DENIED',stage='self_check_binding')
        if not conforms_safe(request['arguments'],resolved['input_schema']):raise ToolExecutorError('TOOL_REQUEST_INVALID',stage='tool_arguments')
        limits=resolved['limits']
        if any(type(limits[k]) is not int or limits[k]<0 for k in ['max_file_bytes','max_inline_bytes']) or type(limits['max_timeout_seconds']) not in {int,float} or limits['max_timeout_seconds']<=0:raise ToolExecutorError('TOOL_PROFILE_UNSUPPORTED',stage='tool_limits')
        fingerprint=digest([request,self.registry.frozen_configuration(policy['binding']),policy['grant'],{k:control.context[k] for k in ['read_scope_ref','write_scope','draft_namespace_ref','deadline_at']}])
        return resolved,policy,fingerprint

    async def describe_tool(self,tool_name,tool_version,access_context):
        context=access_context.context;ref=dict(invocation_ref=context['invocation_ref'],operation_id='description')
        if context['purpose'] not in {'execute','observe'}:raise ToolExecutorError('TOOL_SCOPE_DENIED')
        self._authorize(access_context,context['purpose'],ref);self._control_debit(access_context)
        grant=self.policy.for_ref(context['invocation_ref'])
        if not any(b['tool_name']==tool_name and b['tool_version']==tool_version for b in grant['bindings']):raise ToolExecutorError('TOOL_SCOPE_DENIED')
        resolved=self.registry.resolve(tool_name,tool_version)
        return dict(definition=copy.deepcopy(resolved['definition']),publication_state=resolved['state'],execution_modes=resolved['execution_profile']['execution_modes'])

    async def validate_tool_request(self,request,tool_control):
        validate(request,TOOL_REQUEST_SCHEMA)
        self._authorize(tool_control,'execute',operation_ref(request));self._control_debit(tool_control)
        try:
            resolved,policy,fingerprint=self._base(copy.deepcopy(request),tool_control)
            self.policy.check_current(request,tool_control)
            session=Session(self,request,resolved,policy,tool_control,stamp(),None)
            self.registry.drivers[resolved['definition']['driver_ref']].prepare(request,resolved,session)
            session.guard()
            return dict(valid=True,request_fingerprint=fingerprint,issues=[])
        except ToolExecutorError as fault:return dict(valid=False,request_fingerprint=None,issues=[fault.wire(operation_ref(request))])

    def _result(self,request,started,record,*,status,code,payload=None,error=None,stop='confirmed',effects='none',outcome=None,cleanup_ms=0):
        if record is None:record=self.store.diagnostic(operation_ref(request),request,code)
        outcome_refs=outcome.output_refs if outcome else getattr(error,'output_refs',[])
        changes=outcome.changes if outcome else getattr(error,'changes',[])
        result=dict(tool_contract_version='b04.tool.v0.1',protocol_version='b04.exec.v0.2',execution_mode=request['execution_mode'],
            **{k:copy.deepcopy(request[k]) for k in ['invocation_ref','operation_id','tool_binding_ref','tool_name','tool_version','input_snapshot_id','input_snapshot_sha256']},
            status=status,result_code=code,payload=payload,output_refs=outcome_refs,changes=changes,exit_code=outcome.exit_code if outcome else getattr(error,'exit_code',None),
            timing=dict(started_at=started,finished_at=None if status=='in_progress' else stamp(),execution_duration_ms=None if status=='in_progress' else max(0,(utc_now()-parse_time(started)).total_seconds()*1000-cleanup_ms),cleanup_duration_ms=None if status=='in_progress' else cleanup_ms),
            stop_status=stop,side_effects_state=effects,error=error.wire(operation_ref(request),[record['operation_record_ref']] if record else []) if error else None,
            operation_record_ref=record['operation_record_ref'])
        return result

    async def execute_tool(self,request,tool_control):
        request=copy.deepcopy(request)
        try:canonical(request)
        except (ValueError,TypeError):raise ToolExecutorError('TOOL_REQUEST_INVALID',stage='wire_json') from None
        # Reject unrepresentable identities rather than inventing a valid ToolResult.
        identity={k:v for k,v in TOOL_REQUEST_SCHEMA['properties'].items() if k in {'invocation_ref','operation_id','tool_binding_ref','tool_name','tool_version','input_snapshot_id','input_snapshot_sha256','execution_mode'}}
        validate(request,dict(type='object',properties=identity,required=list(identity)))
        ref=operation_ref(request);started=stamp();record=None;created=False;session=None;outcome=None;reserved=False
        try:
            resolved,policy,fingerprint=self._base(request,tool_control)
            existing=self.store.get(ref)
            if existing:
                if existing['fingerprint']!=fingerprint:raise ToolExecutorError('TOOL_OPERATION_CONFLICT',stop_status='confirmed' if existing['state']=='finished' else 'unknown')
                self._control_debit(tool_control)
                if existing['result'] is not None:return copy.deepcopy(existing['result'])
                return self._result(request,existing['started_at'],existing,status='in_progress' if op_key(ref) in self._active else 'unknown',code='TOOL_IN_PROGRESS' if op_key(ref) in self._active else 'TOOL_RESULT_UNKNOWN',stop=None if op_key(ref) in self._active else 'unknown',error=None if op_key(ref) in self._active else ToolExecutorError('TOOL_RESULT_UNKNOWN',stop_status='unknown',effects='unknown'),effects='unknown' if existing['resources'] or op_key(ref) not in self._active else 'none')
            self._aux(tool_control,'report',ref);self._aux(tool_control,'cleanup',ref)
            self.policy.check_current(request,tool_control)
            resources=[]
            definition=resolved['definition'];driver=self.registry.drivers[definition['driver_ref']]
            session=Session(self,request,resolved,policy,tool_control,started,None)
            session.guard();prepared=driver.prepare(request,resolved,session);session.guard()
            if 'workspace_write' in definition['permission_classes'] or 'process_execute' in definition['permission_classes']:
                workspace=session.workspace();root=workspace.root.as_posix().casefold() if __import__('os').name=='nt' else workspace.root.as_posix()
                resources=[root] if 'process_execute' in definition['permission_classes'] else [root+'/'+request['arguments']['path'].casefold()]
            created,record=self.store.claim(ref,fingerprint,request,dict(definition_ref=self.registry.ref(definition),driver_ref=definition['driver_ref'],configuration_sha256=digest(self.registry.frozen_configuration(policy['binding']))),resources,started_at=started)
            if not created:
                # Another process won the claim; never start a second side effect.
                if record['result'] is not None:return copy.deepcopy(record['result'])
                return self._result(request,record['started_at'],record,status='unknown',code='TOOL_RESULT_UNKNOWN',stop='unknown',effects='unknown',error=ToolExecutorError('TOOL_RESULT_UNKNOWN',stop_status='unknown',effects='unknown'))
            session.record=record;session.guard()
            self.store.reserve(tool_control.context['budget_ticket_ref'],ref);reserved=True
            session.guard();self.store.mark_running(ref)
            active=Active(session);self._active[op_key(ref)]=active;session.executed=True
            outcome=await driver.run(request,prepared,session)
            session.outcome=outcome
            if not conforms_safe(outcome.payload,resolved['output_schema']):raise ToolExecutorError('TOOL_OUTPUT_INVALID',stage='tool_output_schema',effects=outcome.effects)
            result=self._result(request,started,record,status='completed',code='TOOL_COMPLETED',payload=outcome.payload,outcome=outcome,effects=outcome.effects)
        except asyncio.CancelledError:
            fault=ToolExecutorError('TOOL_STOPPED',stage='caller_cancelled',stop_status='unknown' if session and session.executed else 'confirmed',effects=session.effects if session else 'none')
            result=await self._failure(request,tool_control,started,record,session,fault,outcome)
        except Exception as exc:
            if isinstance(exc,OSError) and session and session.effects=='none':
                import errno
                fault=ToolExecutorError('TOOL_PATH_INVALID' if exc.errno in {errno.ELOOP,errno.ENOTDIR} else 'TOOL_IO_ERROR',stage='file_io')
            else:fault=exc if isinstance(exc,ToolExecutorError) else ToolExecutorError('TOOL_RESULT_UNKNOWN' if session and session.executed else 'TOOL_REQUEST_INVALID',stage='tool_execution' if session and session.executed else 'tool_preparation',stop_status='unknown' if session and session.executed else 'confirmed',effects='unknown' if session and session.executed else 'none')
            result=await self._failure(request,tool_control,started,record,session,fault,outcome)
        try:
            validate(result,TOOL_RESULT_SCHEMA,'TOOL_OUTPUT_INVALID')
            if created:
                self._aux(tool_control,'report',ref)
                self.store.settle(ref,executed=session.executed,unknown=result['stop_status']!='confirmed' or result['side_effects_state']=='unknown')
                self.store.finish(ref,result)
        except Exception:
            result=self._result(request,started,record,status='unknown',code='TOOL_RESULT_UNKNOWN',stop='unknown',effects='unknown',error=ToolExecutorError('TOOL_RESULT_UNKNOWN',stage='result_recording',stop_status='unknown',effects='unknown'))
        finally:
            if created:
                active=self._active.pop(op_key(ref),None)
                if active and active.unit:
                    try:
                        closing=asyncio.create_task(asyncio.to_thread(active.unit.close))
                        try:await asyncio.wait_for(asyncio.shield(closing),self.cleanup_timeout)
                        except TimeoutError:self._retain(closing)
                    except Exception:pass
        return result

    async def _failure(self,request,control,started,record,session,fault,outcome):
        ref=operation_ref(request)
        if session and session.effects!='none' and fault.effects=='none':fault.effects=session.effects
        active=self._active.get(op_key(ref))
        if active and (active.unit or active.start_task):
            cleanup_started=time.monotonic()
            receipt=await self._stop_active(ref,control)
            session.cleanup_ms=max(0.001,session.cleanup_ms+(time.monotonic()-cleanup_started)*1000)
            fault.stop_status=receipt['stop_status']
            if fault.stop_status!='confirmed':fault.effects='unknown'
        status='unknown' if fault.stop_status!='confirmed' or fault.effects=='unknown' else 'timed_out' if fault.code=='TOOL_TIMEOUT' else 'stopped' if fault.code=='TOOL_STOPPED' else 'failed' if session and session.executed else 'rejected'
        return self._result(request,started,record,status=status,code=fault.code,error=fault,stop=fault.stop_status,effects=fault.effects,outcome=outcome,cleanup_ms=session.cleanup_ms if session else 0)

    async def get_operation(self,ref,access_context):
        validate(ref,OPERATION_SCHEMA);self._authorize(access_context,'observe',ref);self._control_debit(access_context)
        row=self.store.get(ref)
        state=row['state'] if row else 'unknown'
        if row and state in {'prepared','running'} and op_key(ref) not in self._active:state='unknown'
        result=row['result'] if row else None
        return dict(operation_ref=copy.deepcopy(ref),state=state,request_fingerprint=row['fingerprint'] if row else None,
            tool_version=row['request']['tool_version'] if row else None,operation_record_ref=row['operation_record_ref'] if row else None,result_ref=row['result_ref'] if result else None,
            stop_status=result['stop_status'] if result else 'unknown',side_effects_state=result['side_effects_state'] if result else 'unknown',
            resource_refs=[digest(r) for r in row['resources']] if row else [],updated_at=row['updated_at'] if row else None,
            budget_ticket_ref=self.policy.for_ref(ref['invocation_ref'])['budget_ticket_ref'],budget=self.store.reservation(ref),reconciliation=row['notes'] if row else [])

    async def read_result(self,ref,result_ref,access_context):
        validate(ref,OPERATION_SCHEMA);self._authorize(access_context,'observe',ref);self._control_debit(access_context)
        row=self.store.get(ref)
        if not row or row['result_ref']!=result_ref or row['result'] is None:raise ToolExecutorError('TOOL_RESULT_UNKNOWN',stop_status='unknown')
        return copy.deepcopy(row['result'])

    async def _stop_active(self,ref,control):
        active=self._active.get(op_key(ref))
        if active is None:return dict(stop_status='unknown',evidence_refs=[])
        async with active.stop_lock:
            try:
                self._aux(control,'cleanup',ref)
                if active.start_task and not active.start_task.done():
                    # The backend may publish a unit before its start call
                    # returns.  Stop that unit through the durable backend
                    # reference instead of reporting uncertainty prematurely.
                    unit_info=self._units.get(op_key(ref))
                    if unit_info:
                        backend_ref,unit_ref=unit_info
                        backend=self.sandboxes.get(backend_ref)
                        if backend is not None:
                            receipt=await self._bounded_stop(ref,backend.stop_existing,unit_ref,self.cleanup_timeout)
                            self.store.append(ref,'stop_observation',receipt)
                            return receipt
                    return dict(stop_status='unknown',evidence_refs=[])
                if active.unit is None and active.start_task:active.unit=active.start_task.result()
                if active.unit:
                    receipt=await self._bounded_stop(ref,active.unit.stop,self.cleanup_timeout)
                    self.store.append(ref,'stop_observation',receipt)
                    return receipt
            except Exception:return dict(stop_status='unknown',evidence_refs=[])
            return dict(stop_status='unknown',evidence_refs=[])

    async def _bounded_stop(self,ref,method,*args):
        """A stalled backend cannot extend the declared cleanup wait indefinitely."""
        task=asyncio.create_task(asyncio.to_thread(method,*args))
        try:return valid_receipt(await asyncio.wait_for(asyncio.shield(task),self.cleanup_timeout))
        except TimeoutError:
            def observed(future):
                try:self.store.append(ref,'late_stop_observation',valid_receipt(future.result()))
                except BaseException:pass
            task.add_done_callback(observed);self._retain(task)
            return dict(stop_status='unknown',evidence_refs=[])

    async def stop_operation(self,ref,reason,tool_control):
        validate(ref,OPERATION_SCHEMA);self._authorize(tool_control,'cleanup',ref);self._control_debit(tool_control)
        if not isinstance(reason,str) or not reason:raise ToolExecutorError('TOOL_REQUEST_INVALID',stage='stop_reason')
        proof=self.store.request_stop(ref);row=self.store.get(ref)
        if row is None or row['state']=='prepared' or row['result'] and row['result']['stop_status']=='confirmed':receipt=dict(stop_status='confirmed',evidence_refs=[proof])
        elif op_key(ref) in self._active:
            active=self._active[op_key(ref)];active.session.control=replace_cleanup(active.session.control,tool_control.context)
            receipt=await self._stop_active(ref,active.session.control)
        else:
            receipt=dict(stop_status='unknown',evidence_refs=[])
            notes=[n['payload'] for n in row['notes'] if n['kind'] in {'unit_started','unit_allocated'}]
            if notes:
                unit=notes[-1]
                try:receipt=await self._bounded_stop(ref,self.sandboxes[unit['backend_ref']].stop_existing,unit['unit_ref'],self.cleanup_timeout)
                except Exception:pass
        receipt=valid_receipt(receipt)
        self.store.append(ref,'stop_observation',receipt)
        return dict(operation_ref=copy.deepcopy(ref),**receipt)

    async def aclose(self):
        """Stop local units; retain durable uncertainty if a start has no receipt."""
        for active in list(self._active.values()):
            self.store.request_stop(active.session.ref)
            await self._stop_active(active.session.ref,active.session.control)
        if self._background:
            await asyncio.wait(list(self._background),timeout=self.cleanup_timeout)


def valid_receipt(receipt):
    if not isinstance(receipt,dict) or receipt.get('stop_status') not in {'confirmed','pending','unknown'}:return dict(stop_status='unknown',evidence_refs=[])
    evidence=receipt.get('evidence_refs')
    if not isinstance(evidence,list) or any(not isinstance(v,str) or not v for v in evidence) or receipt['stop_status']=='confirmed' and not evidence:return dict(stop_status='unknown',evidence_refs=[])
    return dict(stop_status=receipt['stop_status'],evidence_refs=evidence)


def replace_cleanup(control,context):
    from dataclasses import replace
    return replace(control,cleanup_context=context)


def conforms_safe(value,schema):
    from b04.model_adapter.schemas import conforms
    try:canonical(value);return conforms(value,schema)
    except (ValueError,TypeError):return False
