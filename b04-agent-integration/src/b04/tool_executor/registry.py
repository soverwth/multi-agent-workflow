"""Management-only publication and immutable versioned runtime configuration."""
from __future__ import annotations

import copy
import re
from uuid import uuid4

from b04.model_adapter.contracts import canonical,digest,utc_now
from b04.model_adapter.schemas import check_output_schema
from b04.model_adapter.errors import ModelAdapterError
from .contracts import ManagementContext,ToolExecutorError


class ManagementAuthority:
    def __init__(self):self._grants={}
    def issue(self,subject_ref,permissions,*,tool_names=None):
        context=ManagementContext(subject_ref,"tool-management:"+uuid4().hex)
        self._grants[context.grant_ref]=(context,frozenset(permissions),frozenset(tool_names) if tool_names is not None else None)
        return context
    def authorize(self,context,permission,tool_name):
        grant=self._grants.get(getattr(context,"grant_ref",None))
        if not grant or context!=grant[0] or permission not in grant[1] or grant[2] is not None and tool_name not in grant[2]:raise ToolExecutorError("TOOL_SCOPE_DENIED",stage="management_authority")


class ToolRegistry:
    DEFINITION_FIELDS={"tool_name","tool_version","driver_ref","capability_refs","input_schema_ref","output_schema_ref","permission_classes","side_effect_profile","execution_profile_ref","limits_profile_ref","idempotency_policy","stop_query_policy_ref","owner_ref","review_refs"}
    def __init__(self,*,store,management_authority):
        self.store,self.management=store,management_authority
        self.schemas={};self.profiles={};self.drivers={};self.commands={};self.runtimes={}

    @staticmethod
    def _immutable(mapping,ref,value):
        canonical(value)
        if not isinstance(ref,str) or not ref:raise ValueError("Reference required")
        if ref in mapping and mapping[ref]!=value:raise ValueError("Immutable reference cannot be overwritten")
        mapping[ref]=copy.deepcopy(value)

    def register_schema(self,ref,schema,context):
        self.management.authorize(context,"configure","*")
        try:check_output_schema(schema)
        except ModelAdapterError:raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="schema_profile") from None
        self._immutable(self.schemas,ref,schema)

    def register_profile(self,ref,profile,context):
        self.management.authorize(context,"configure","*");self._immutable(self.profiles,ref,profile)

    def register_command(self,ref,profile,context):
        self.management.authorize(context,"configure","*")
        if profile.get("command_profile_ref")!=ref:raise ToolExecutorError("TOOL_REQUEST_INVALID")
        self._immutable(self.commands,ref,profile)

    def register_runtime(self,ref,runtime,context):
        self.management.authorize(context,"configure","*");self._immutable(self.runtimes,ref,runtime)

    def register_driver(self,ref,driver,context):
        self.management.authorize(context,"configure","*")
        if ref in self.drivers:raise ValueError("Driver reference already registered")
        self.drivers[ref]=driver

    def register_tool(self,definition,management_context):
        self.management.authorize(management_context,"register",definition.get("tool_name"))
        if set(definition)!=self.DEFINITION_FIELDS or any(not isinstance(definition[k],str) or not definition[k] for k in self.DEFINITION_FIELDS-{"capability_refs","permission_classes","review_refs"}):raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="definition")
        if definition["tool_version"].lower() in {"latest","*"} or not re.fullmatch(r"[A-Za-z0-9_.-]+",definition["tool_version"]):raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="explicit_version")
        for key in ["capability_refs","permission_classes","review_refs"]:
            if not isinstance(definition[key],list) or any(not isinstance(v,str) or not v for v in definition[key]):raise ToolExecutorError("TOOL_REQUEST_INVALID")
        self.store.put_definition(definition)
        return dict(definition_ref=self.ref(definition),publication_state=self.store.definition(definition["tool_name"],definition["tool_version"])[1])

    @staticmethod
    def ref(definition):return "tool:"+definition["tool_name"]+"@"+definition["tool_version"]

    def validate_tool(self,name,version,context):
        self.management.authorize(context,"validate",name)
        definition,_=self.store.definition(name,version)
        if definition["driver_ref"] not in self.drivers or any(definition[k] not in self.schemas for k in ["input_schema_ref","output_schema_ref"]) or any(definition[k] not in self.profiles for k in ["execution_profile_ref","limits_profile_ref","stop_query_policy_ref","side_effect_profile"]):raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="definition_dependencies")
        self.drivers[definition["driver_ref"]].validate_definition(definition,self)
        self.store.catalog_state(name,version,"validated")
        return dict(definition_ref=self.ref(definition),publication_state="validated")

    def publish_tool(self,definition_ref,review_context):
        if not isinstance(definition_ref,str) or not definition_ref.startswith("tool:") or "@" not in definition_ref:raise ToolExecutorError("TOOL_REQUEST_INVALID")
        name,version=definition_ref[5:].rsplit("@",1)
        self.management.authorize(review_context,"publish",name)
        definition,state=self.store.definition(name,version)
        if not definition["review_refs"]:raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="missing_review_evidence")
        self.store.catalog_state(name,version,"published")
        return dict(definition_ref=definition_ref,publication_state="published")

    def deprecate_tool(self,name,version,context):
        self.management.authorize(context,"deprecate",name);self.store.catalog_state(name,version,"deprecated")

    def disable_tool(self,name,version,context):
        self.management.authorize(context,"disable",name);self.store.catalog_state(name,version,"disabled")

    def resolve(self,name,version):
        definition,state=self.store.definition(name,version)
        try:
            return dict(definition=definition,state=state,input_schema=self.schemas[definition["input_schema_ref"]],output_schema=self.schemas[definition["output_schema_ref"]],
                execution_profile=self.profiles[definition["execution_profile_ref"]],limits=self.profiles[definition["limits_profile_ref"]],
                effects=self.profiles[definition["side_effect_profile"]],stop_policy=self.profiles[definition["stop_query_policy_ref"]])
        except KeyError:raise ToolExecutorError("TOOL_PROFILE_UNSUPPORTED",stage="definition_resolution") from None

    def frozen_configuration(self,binding):
        try:return self._frozen_configuration(binding)
        except (KeyError,TypeError):raise ToolExecutorError('TOOL_PROFILE_UNSUPPORTED',stage='frozen_configuration_dependencies') from None

    def _frozen_configuration(self,binding):
        value={k:v for k,v in self.resolve(binding['tool_name'],binding['tool_version']).items() if k!='state'}
        value['model_input_schema']=self.schemas[binding['model_input_schema_ref']]
        value['commands']=[]
        for ref in binding['command_profile_refs']:
            command=self.commands[ref]
            value['commands'].append(dict(command=command,runtime=self.runtimes[command['executable_ref']],parameter_schema=self.schemas[command['parameter_schema_ref']],
                profiles={k:self.profiles[command[k]] for k in ['environment_policy_ref','resource_policy_ref','exit_code_policy_ref','side_effect_policy_ref','process_control_ref']}))
        value['check_schemas']={rule['schema_ref']:self.schemas[rule['schema_ref']] for rule in value['execution_profile'].get('check_rules',{}).values()}
        return value


class FrozenToolPolicy:
    """B02/B03-issued grants. Snapshot/model text cannot create these entries."""
    def __init__(self,registry,*,current_check=None):
        self.registry=registry;self._grants={};self.current_check=current_check

    def register(self,ref,grant):
        value=copy.deepcopy(grant)
        if value["invocation_ref"]!=ref:raise ValueError("Grant identity mismatch")
        key=canonical(ref)
        value['_configuration_sha256']=digest([self.registry.frozen_configuration(b) for b in value['bindings']])
        if key in self._grants:
            if self._grants[key]!=value:raise ValueError("Grant cannot silently change")
            return
        refs=[];names=[]
        for binding in value["bindings"]:
            definition,state=self.registry.store.definition(binding["tool_name"],binding["tool_version"])
            if state!="published":raise ToolExecutorError("TOOL_DISABLED" if state=="disabled" else "TOOL_NOT_REGISTERED",stage="new_frozen_binding")
            if binding["driver_ref"]!=definition["driver_ref"] or binding["executor_input_schema_ref"]!=definition["input_schema_ref"] or digest(self.registry.schemas[definition["input_schema_ref"]])!=binding["executor_input_schema_sha256"] or digest(self.registry.schemas[binding["model_input_schema_ref"]])!=binding["model_input_schema_sha256"]:raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="binding_schema")
            refs.append(binding["binding_ref"]);names.append(binding["model_tool_name"])
        if len(refs)!=len(set(refs)) or len(names)!=len(set(names)):raise ToolExecutorError("TOOL_REQUEST_INVALID",stage="ambiguous_alias")
        self._grants[key]=value

    def resolve(self,request,control):
        try:
            grant=copy.deepcopy(self._grants[canonical(request["invocation_ref"])])
            if grant['_configuration_sha256']!=digest([self.registry.frozen_configuration(b) for b in grant['bindings']]):raise ToolExecutorError('TOOL_REQUEST_INVALID',stage='frozen_configuration_changed')
            for key in ["input_snapshot_id","input_snapshot_sha256","lease_ref","tool_config_ref","workspace_ref"]:
                if request[key]!=grant[key]:raise KeyError("Frozen binding")
            if request["execution_mode"]!=grant["execution_mode"] or control.context["tool_binding_set_ref"]!=grant["tool_binding_set_ref"] or control.context["budget_ticket_ref"]!=grant["budget_ticket_ref"]:raise KeyError("Frozen control")
            if control.context["invocation_ref"]!=request["invocation_ref"] or any(control.context[k]!=grant[k] for k in ["input_snapshot_id","input_snapshot_sha256","lease_ref"]):raise KeyError("Context identity")
            if control.context["write_scope"]!=grant["write_scope"]:raise KeyError("Write scope")
            bindings=[b for b in grant["bindings"] if b["binding_ref"]==request["tool_binding_ref"] and b["tool_name"]==request["tool_name"] and b["tool_version"]==request["tool_version"]]
            if len(bindings)!=1:raise KeyError("Tool binding")
            if request["origin"]["source"]=="model" and request["tool_binding_ref"] not in grant["model_binding_refs"]:raise KeyError("Not model-visible")
            return dict(grant=grant,binding=bindings[0])
        except (KeyError,TypeError):raise ToolExecutorError("TOOL_SCOPE_DENIED",stage="frozen_authorization",details={"denied_action":"execute"}) from None

    def for_ref(self,ref):
        try:return copy.deepcopy(self._grants[canonical(ref)])
        except KeyError:raise ToolExecutorError('TOOL_SCOPE_DENIED',stage='operation_scope') from None

    def check_current(self,request,control):
        self.resolve(request,control)
        _,state=self.registry.store.definition(request["tool_name"],request["tool_version"])
        if state=="disabled":raise ToolExecutorError("TOOL_DISABLED",stage="disabled_during_execution")
        if state not in {"published","deprecated"}:raise ToolExecutorError("TOOL_NOT_REGISTERED")
        if parse_deadline(self._grants[canonical(request["invocation_ref"])]["deadline_at"])<=utc_now():raise ToolExecutorError("TOOL_TIMEOUT",stage="attempt_deadline")
        if self.current_check:
            try:self.current_check(request,control)
            except ToolExecutorError:raise
            except Exception:raise ToolExecutorError('TOOL_LEASE_INVALID',stage='authority_revalidation') from None


def parse_deadline(value):
    from b04.model_adapter.contracts import parse_time
    return parse_time(value)
