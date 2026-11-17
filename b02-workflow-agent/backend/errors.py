from __future__ import annotations


class WorkflowError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class InvalidTransition(WorkflowError):
    pass


class AgentExecutionError(WorkflowError):
    pass
