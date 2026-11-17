"""Safe errors: never publish arbitrary provider exception text or credentials."""
from __future__ import annotations

import copy
import math
import re

from .contracts import JSON, ModelCallRef, ModelError

MESSAGES = {
    "MODEL_REQUEST_INVALID": ("validation", "标准模型请求不符合契约"),
    "MODEL_CALL_CONFLICT": ("conflict", "模型调用编号或序号与已有内容冲突"),
    "MODEL_CONFIG_INVALID": ("configuration", "冻结配置、策略或输入绑定不一致"),
    "MODEL_CONTROL_INVALID": ("permission", "控制授权、调用归属或执行租约无效"),
    "MODEL_CAPABILITY_UNSUPPORTED": ("capability", "请求能力、参数或组合未获支持"),
    "MODEL_CONTEXT_LIMIT": ("capability", "请求超过声明的上下文上限"),
    "MODEL_AUTH_FAILED": ("authentication", "模型服务凭据或授权不可用"),
    "MODEL_RATE_LIMITED": ("transport", "模型服务限流"),
    "MODEL_PROVIDER_UNAVAILABLE": ("transport", "模型服务不可用"),
    "MODEL_NETWORK_UNCERTAIN": ("transport", "请求发送或远端结果无法确认"),
    "MODEL_TIMEOUT": ("transport", "模型调用达到时限"),
    "MODEL_CANCELLED": ("control", "本次调用已确认停止"),
    "MODEL_BUDGET_EXHAUSTED": ("budget", "模型或控制资源额度不足"),
    "MODEL_OUTPUT_FORMAT": ("output", "输出不符合声明的结构化格式"),
    "MODEL_OUTPUT_TRUNCATED": ("output", "模型输出被截断"),
    "MODEL_TOOL_CALL_INVALID": ("output", "工具意图名称、参数或关联不合法"),
    "MODEL_REFUSED": ("output", "模型明确拒绝生成"),
    "MODEL_CONTENT_FILTERED": ("output", "模型服务过滤了输出"),
    "MODEL_RESPONSE_MALFORMED": ("output", "模型响应无法可靠归一"),
    "MODEL_EMPTY_RESPONSE": ("output", "模型没有返回可用内容"),
    "MODEL_INTERNAL_ERROR": ("internal", "模型适配层发生内部异常"),
}


class ModelAdapterError(Exception):
    """Typed boundary error, also used when invalid identity cannot form ModelResult."""

    def __init__(self, code: str, *, stage: str = "validation", delivery: str = "not_sent",
                 stop_status: str | None = None, retry_after_seconds: float | None = None,
                 provider_error_code: str | None = None):
        if code not in MESSAGES:
            raise ValueError("Unregistered model error")
        if delivery not in {"not_sent", "sent", "unknown"}:
            raise ValueError("Invalid delivery state")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", stage):
            raise ValueError("Stage must be a registered-style identifier")
        if retry_after_seconds is not None and (type(retry_after_seconds) not in {int, float} or not math.isfinite(retry_after_seconds) or retry_after_seconds < 0):
            raise ValueError("Retry delay must be a finite nonnegative number")
        self.code = code
        self.stage = stage
        self.delivery = delivery
        self.stop_status = stop_status or ("confirmed" if delivery == "not_sent" else "unknown")
        if self.stop_status not in {"confirmed", "pending", "unknown"}:
            raise ValueError("Invalid stop state")
        self.retry_after_seconds = retry_after_seconds
        self.provider_error_code = provider_error_code
        super().__init__(MESSAGES[code][1])

    def to_dict(self, evidence_refs: list[str] | None = None) -> ModelError:
        category, message = MESSAGES[self.code]
        advice = "reconcile_before_retry" if self.delivery == "unknown" or self.stop_status != "confirmed" else "requires_decision"
        provider_code = self.provider_error_code
        if provider_code is not None and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", provider_code):
            provider_code = None
        return dict(code=self.code, category=category, message=message, stage=self.stage,
                    retry_advice=advice, retry_after_seconds=self.retry_after_seconds,
                    request_delivery=self.delivery, stop_status=self.stop_status,
                    provider_error_code=provider_code, evidence_refs=evidence_refs or [], details={})


class ProviderFailure(ModelAdapterError):
    """Drivers classify failures explicitly; facade never guesses from HTTP status."""


def to_exec_error(error: ModelError, call_ref: ModelCallRef, *, policy_retry_allowed: bool = False) -> JSON:
    """Protocol §14.6 mapping after invocation admission; creates no event or retry."""
    mapping = {
        "MODEL_CONFIG_INVALID": "EXEC_INPUT_INVALID", "MODEL_CONTROL_INVALID": "EXEC_LEASE_INVALID",
        "MODEL_CAPABILITY_UNSUPPORTED": "EXEC_CAPABILITY_UNAVAILABLE", "MODEL_CONTEXT_LIMIT": "EXEC_CAPABILITY_UNAVAILABLE",
        "MODEL_TIMEOUT": "EXEC_TIMEOUT", "MODEL_BUDGET_EXHAUSTED": "EXEC_BUDGET_EXHAUSTED",
    }
    if error["code"] == "MODEL_CANCELLED":
        raise ValueError("Confirmed cancellation uses runner stop flow, not ExecError")
    if error["request_delivery"] == "unknown" or error["stop_status"] != "confirmed" or error["retry_advice"] in {"reconcile_before_retry", "reconcile_required"}:
        recovery, action = "requires_reconciliation", "reconcile_then_decide"
    elif error["code"] in {"MODEL_CONFIG_INVALID", "MODEL_AUTH_FAILED", "MODEL_CAPABILITY_UNSUPPORTED", "MODEL_CONTEXT_LIMIT", "MODEL_CONTROL_INVALID"}:
        recovery, action = "requires_decision", "request_responsible_decision"
    elif error["retry_advice"] == "not_retryable":
        recovery, action = "not_retryable", "report_failure"
    elif policy_retry_allowed:
        recovery, action = "policy_retry_allowed", "runner_policy_decision"
    else:
        recovery, action = "requires_decision", "request_responsible_decision"
    return dict(code=mapping.get(error["code"], "EXEC_MODEL_ERROR"), category=error["category"],
                message=error["message"], stage=error["stage"], operation_ref=None,
                cause_ref={"layer": "model", "ref": copy.deepcopy(call_ref)}, origin_layer="model",
                evidence_refs=list(error["evidence_refs"]), recoverability=recovery,
                requested_action=action, stop_status=error["stop_status"], details={"model": copy.deepcopy(error)})

