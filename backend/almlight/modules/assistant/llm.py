"""The language model behind the assistant: Azure OpenAI chat completions with tool calling.

Only this module knows the provider. It is configured with ``ALMLIGHT_AZURE_OPENAI_*`` (endpoint, key, deployment);
without them the assistant stays switched off. The key never leaves this module and never appears in an error
message, a log line or an answer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from almlight.core.config import get_settings
from almlight.core.errors import ValidationFailed

log = logging.getLogger("almlight.assistant")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Reply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


def enabled() -> bool:
    return get_settings().assistant_enabled


def model_name() -> str | None:
    return get_settings().azure_openai_deployment


def _url() -> str:
    s = get_settings()
    base = (s.azure_openai_endpoint or "").rstrip("/")
    return (f"{base}/openai/deployments/{s.azure_openai_deployment}/chat/completions"
            f"?api-version={s.azure_openai_api_version}")


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string; a model may produce something that is not an object."""
    import json

    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        return {"__invalid__": str(raw)[:500]}
    return value if isinstance(value, dict) else {"__invalid__": value}


def chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, *,
         temperature: float = 0.1) -> Reply:
    """One round with the model. Raises ValidationFailed with a message the person can act on."""
    s = get_settings()
    if not s.assistant_enabled:
        raise ValidationFailed("The AI assistant is not configured on this installation "
                               "(endpoint, key and deployment of the language model are missing)")
    body: dict[str, Any] = {"messages": messages, "temperature": temperature}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    try:
        resp = httpx.post(_url(), json=body, headers={"api-key": s.azure_openai_api_key or "",
                                                      "Content-Type": "application/json"},
                          timeout=httpx.Timeout(s.assistant_timeout_seconds, connect=10.0))
    except httpx.TimeoutException:
        raise ValidationFailed("The language model did not answer in time — try again or ask something smaller") \
            from None
    except httpx.HTTPError as exc:
        log.warning("assistant: the language model is not reachable: %s", exc)
        raise ValidationFailed("The language model is not reachable from this installation") from None
    if resp.status_code == 401 or resp.status_code == 403:
        raise ValidationFailed("The language model refused the key — check the assistant configuration")
    if resp.status_code == 404:
        raise ValidationFailed("The language model deployment does not exist — check the assistant configuration")
    if resp.status_code == 429:
        raise ValidationFailed("The language model is busy (rate limit) — try again in a moment")
    if resp.status_code >= 400:
        log.warning("assistant: the language model answered %s: %s", resp.status_code, resp.text[:500])
        raise ValidationFailed(f"The language model answered with an error ({resp.status_code})")
    try:
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
    except ValueError:
        raise ValidationFailed("The language model did not answer with JSON") from None
    if data.get("error"):  # some gateways answer 200 with an error body
        raise ValidationFailed("The language model answered with an error")
    calls = [ToolCall(id=c.get("id") or f"call_{n}", name=(c.get("function") or {}).get("name") or "",
                      arguments=_parse_arguments((c.get("function") or {}).get("arguments")))
             for n, c in enumerate(message.get("tool_calls") or []) if isinstance(c, dict)]
    return Reply(content=(message.get("content") or "").strip(), tool_calls=[c for c in calls if c.name],
                 finish_reason=choice.get("finish_reason"), usage=data.get("usage") or {})
