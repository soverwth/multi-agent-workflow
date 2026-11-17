"""B04 model adapter, wire contracts b04.model.v0.1 / b04.exec.v0.2."""
from .adapter import ModelAdapterFacade
from .contracts import CallControl, ControlContext, InvocationRef, ModelCallRef, ModelError, ModelRequest, ModelResult
from .drivers import MockDriver, ProviderDriverRegistry, mock_capabilities
from .errors import ModelAdapterError, ProviderFailure, to_exec_error
from .ledger import SQLiteCallLedger
from .ports import Authority, BudgetPort, CallLedger, ConfigResolver, CredentialResolver, ProviderDriver, ResolvedModel, TokenEstimate
from .runtime import InMemoryAuthority, InMemoryBudget, InMemoryConfigResolver, MappingCredentialResolver

__all__ = ["ModelAdapterFacade", "CallControl", "ControlContext", "InvocationRef", "ModelCallRef", "ModelRequest", "ModelResult", "ModelError",
           "ProviderDriverRegistry", "ProviderDriver", "MockDriver", "mock_capabilities", "ModelAdapterError", "ProviderFailure", "to_exec_error",
           "SQLiteCallLedger", "InMemoryAuthority", "InMemoryBudget", "InMemoryConfigResolver", "MappingCredentialResolver",
           "Authority", "BudgetPort", "CallLedger", "ConfigResolver", "CredentialResolver", "ResolvedModel", "TokenEstimate"]

