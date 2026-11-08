"""The language model behind the assistant: Azure OpenAI with tool calling.

Only this module knows the provider. It is configured with ``ALMLIGHT_AZURE_OPENAI_*`` (endpoint, key, deployment);
without them the assistant stays switched off. The key never leaves this module and never appears in an error
message, a log line or an answer.

Azure offers two surfaces, and which one a deployment needs depends on the model: classic **chat completions**
(GPT-4o and the like) and the **responses** API, which reasoning models require for tool calling. The module
starts with chat completions and switches when the answer says so, so an installation does not have to know.
"""

from __future__ import annotations

import json
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


# What this deployment needs or refuses, learned from its answers (per process, per deployment).
_quirks: dict[str, dict[str, Any]] = {}


def _deployment_quirks() -> dict[str, Any]:
    s = get_settings()
    quirks = _quirks.setdefault(s.azure_openai_deployment or "", {})
    if s.assistant_api in ("chat", "responses"):
        quirks["api"] = s.assistant_api
    if s.assistant_reasoning_effort:
        quirks["reasoning_effort"] = s.assistant_reasoning_effort
    return quirks


def _adapt(error: dict[str, Any], quirks: dict[str, Any]) -> str | None:
    """Models differ in which surface and which parameters they take. Read the refusal and say what to change."""
    if get_settings().assistant_api in ("chat", "responses"):
        return None  # the installation pinned the surface; do not argue with it
    text = f"{error.get('param') or ''} {error.get('message') or ''}"
    if "responses" in text and quirks.get("api") != "responses":
        quirks["api"] = "responses"  # reasoning models take tools only on the responses API
        return "the responses API"
    if "reasoning_effort" in text and quirks.get("reasoning_effort") != "none":
        quirks["reasoning_effort"] = "none"
        return "reasoning_effort=none"
    if "temperature" in text and not quirks.get("no_temperature"):
        quirks["no_temperature"] = True  # some models accept the default temperature only
        return "without temperature"
    return None


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string; a model may produce something that is not an object."""
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        return {"__invalid__": str(raw)[:500]}
    return value if isinstance(value, dict) else {"__invalid__": value}


# --- chat completions -----------------------------------------------------------------------------------


def _chat_request(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, temperature: float,
                  quirks: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    s = get_settings()
    url = (f"{(s.azure_openai_endpoint or '').rstrip('/')}/openai/deployments/{s.azure_openai_deployment}"
           f"/chat/completions?api-version={s.azure_openai_api_version}")
    body: dict[str, Any] = {"messages": messages}
    if not quirks.get("no_temperature"):
        body["temperature"] = temperature
    if quirks.get("reasoning_effort"):
        body["reasoning_effort"] = quirks["reasoning_effort"]
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    return url, body


def _parse_chat(data: dict[str, Any]) -> Reply:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    calls = [ToolCall(id=c.get("id") or f"call_{n}", name=(c.get("function") or {}).get("name") or "",
                      arguments=_parse_arguments((c.get("function") or {}).get("arguments")))
             for n, c in enumerate(message.get("tool_calls") or []) if isinstance(c, dict)]
    return Reply(content=(message.get("content") or "").strip(), tool_calls=[c for c in calls if c.name],
                 finish_reason=choice.get("finish_reason"), usage=data.get("usage") or {})


# --- responses API --------------------------------------------------------------------------------------


def _responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same conversation in the shape the responses API takes."""
    items: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            items.append({"type": "function_call_output", "call_id": m.get("tool_call_id") or "",
                          "output": m.get("content") or ""})
        elif role == "assistant" and m.get("tool_calls"):
            if m.get("content"):
                items.append({"role": "assistant", "content": m["content"]})
            for c in m["tool_calls"]:
                items.append({"type": "function_call", "call_id": c["id"], "name": c["function"]["name"],
                              "arguments": c["function"]["arguments"]})
        elif m.get("content"):
            items.append({"role": role, "content": m["content"]})
    return items


def _responses_request(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                       quirks: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    s = get_settings()
    url = (f"{(s.azure_openai_endpoint or '').rstrip('/')}/openai/responses"
           f"?api-version={s.azure_openai_responses_api_version}")
    # store=false: the conversation stays in this installation and is not kept at the provider
    body: dict[str, Any] = {"model": s.azure_openai_deployment, "input": _responses_input(messages), "store": False}
    if tools:
        body["tools"] = [{"type": "function", "name": t["function"]["name"],
                          "description": t["function"].get("description", ""),
                          "parameters": t["function"].get("parameters") or {}} for t in tools]
    effort = quirks.get("reasoning_effort")
    if effort and effort != "none":
        body["reasoning"] = {"effort": effort}
    return url, body


def _parse_responses(data: dict[str, Any]) -> Reply:
    text: list[str] = []
    calls: list[ToolCall] = []
    for out in data.get("output") or []:
        if not isinstance(out, dict):
            continue
        if out.get("type") == "message":
            text += [c.get("text") or "" for c in out.get("content") or []
                     if isinstance(c, dict) and c.get("type") == "output_text"]
        elif out.get("type") == "function_call":
            calls.append(ToolCall(id=out.get("call_id") or out.get("id") or "call",
                                  name=out.get("name") or "", arguments=_parse_arguments(out.get("arguments"))))
    usage = data.get("usage") or {}
    return Reply(content="\n".join(t for t in text if t).strip(), tool_calls=[c for c in calls if c.name],
                 finish_reason=data.get("status"),
                 usage={"total_tokens": usage["total_tokens"]} if usage.get("total_tokens") else {})


# --- one round ------------------------------------------------------------------------------------------


def chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, *,
         temperature: float = 0.1) -> Reply:
    """One round with the model. Raises ValidationFailed with a message the person can act on."""
    s = get_settings()
    if not s.assistant_enabled:
        raise ValidationFailed("The AI assistant is not configured on this installation "
                               "(endpoint, key and deployment of the language model are missing)")
    quirks = _deployment_quirks()
    resp: httpx.Response | None = None
    used_responses = False
    for attempt in (1, 2, 3):
        used_responses = quirks.get("api") == "responses"
        url, body = (_responses_request(messages, tools, quirks) if used_responses
                     else _chat_request(messages, tools, temperature, quirks))
        try:
            resp = httpx.post(url, json=body, headers={"api-key": s.azure_openai_api_key or "",
                                                       "Content-Type": "application/json"},
                              timeout=httpx.Timeout(s.assistant_timeout_seconds, connect=10.0))
        except httpx.TimeoutException:
            raise ValidationFailed("The language model did not answer in time — try again or ask something "
                                   "smaller") from None
        except httpx.HTTPError as exc:
            log.warning("assistant: the language model is not reachable: %s", exc)
            raise ValidationFailed("The language model is not reachable from this installation") from None
        if resp.status_code != 400 or attempt == 3:
            break
        try:
            error = (resp.json() or {}).get("error") or {}
        except ValueError:
            error = {}
        changed = _adapt(error, quirks)
        if not changed:
            break
        log.info("assistant: %s needs %s — repeating the request", s.azure_openai_deployment, changed)
    if resp is None:  # pragma: no cover — the loop always sends at least once
        raise ValidationFailed("The language model is not reachable from this installation")
    if resp.status_code in (401, 403):
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
    except ValueError:
        raise ValidationFailed("The language model did not answer with JSON") from None
    if data.get("error"):  # some gateways answer 200 with an error body
        raise ValidationFailed("The language model answered with an error")
    return _parse_responses(data) if used_responses else _parse_chat(data)
