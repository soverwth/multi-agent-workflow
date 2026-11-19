"""OpenAI-compatible large-language-model adapter used by the first stage.

The adapter deliberately speaks the small, widely supported Chat Completions
HTTP contract.  DeepSeek, OpenAI-compatible gateways and local model servers
can therefore be selected with environment variables or the runtime config
endpoint without coupling the workflow controller to one vendor.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import AgentExecutionError


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LLMConfig:
    """Runtime settings.  The API key is never included in public status."""

    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    api_key: str = ""
    timeout_seconds: float = 45.0
    enabled: bool = False

    @classmethod
    def from_env(cls) -> "LLMConfig":
        key = os.getenv("SE_WORKFLOW_LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or ""
        raw_timeout = os.getenv("SE_WORKFLOW_LLM_TIMEOUT", "45")
        try:
            timeout = max(5.0, min(float(raw_timeout), 180.0))
        except ValueError:
            timeout = 45.0
        return cls(
            base_url=os.getenv("SE_WORKFLOW_LLM_BASE_URL", "https://api.deepseek.com").strip().rstrip("/"),
            model=os.getenv("SE_WORKFLOW_LLM_MODEL", "deepseek-chat").strip() or "deepseek-chat",
            api_key=key.strip(),
            timeout_seconds=timeout,
            enabled=_env_bool("SE_WORKFLOW_LLM_ENABLED", bool(key.strip())),
        )

    def public(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled and self.api_key),
            "provider": "OpenAI-compatible",
            "base_url": self.base_url,
            "model": self.model,
            "key_configured": bool(self.api_key),
            "timeout_seconds": self.timeout_seconds,
        }


class OpenAICompatibleClient:
    """Small synchronous client for structured JSON generation."""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.from_env()

    def configure(self, **changes: Any) -> LLMConfig:
        allowed = {"base_url", "model", "api_key", "timeout_seconds", "enabled"}
        unknown = set(changes) - allowed
        if unknown:
            raise AgentExecutionError(f"未知模型配置字段: {', '.join(sorted(unknown))}")
        values = dict(changes)
        if "base_url" in values:
            values["base_url"] = str(values["base_url"]).strip().rstrip("/")
        if "model" in values:
            values["model"] = str(values["model"]).strip()
        if "api_key" in values:
            values["api_key"] = str(values["api_key"]).strip()
        if "timeout_seconds" in values:
            values["timeout_seconds"] = max(5.0, min(float(values["timeout_seconds"]), 180.0))
        self.config = replace(self.config, **values)
        return self.config

    def enabled(self) -> bool:
        return bool(self.config.enabled and self.config.api_key and self.config.base_url and self.config.model)

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        if not self.enabled():
            raise AgentExecutionError("大模型 API 未启用或缺少 API Key。")
        payload = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": 1800,
            "response_format": {"type": "json_object"},
        }
        request = Request(
            f"{self.config.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise AgentExecutionError(f"大模型 API 返回 HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise AgentExecutionError(f"大模型 API 连接失败: {error}") from error
        except json.JSONDecodeError as error:
            raise AgentExecutionError("大模型 API 返回的不是合法 JSON。") from error

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise AgentExecutionError("大模型 API 响应缺少 choices[0].message.content。") from error
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
        text = str(content).strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        try:
            result = json.loads(text)
        except json.JSONDecodeError as error:
            raise AgentExecutionError(f"大模型输出不是合法 JSON: {text[:300]}") from error
        if not isinstance(result, dict):
            raise AgentExecutionError("大模型输出必须是 JSON 对象。")
        return result
