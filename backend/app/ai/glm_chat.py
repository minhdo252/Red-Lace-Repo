"""Direct GLM-5.2 chat gateway (doc section 3).

The orchestrator (`app/ai/client.py::AIClient.chat`, live path) and the critic
(`app/agent/critic.py`) both call GLM-5.2 through this single blocking helper —
kept separate from the mock/live `AIClient` switch so the reasoning-model payload
(reasoning trace + final answer + tool calls) lives in one place.

GLM-5.2 is an OpenAI-compatible reasoning model on the FPT Cloud AI Marketplace
(`settings.ai_base_url`). It streams its chain-of-thought into
`message.reasoning_content` and the user-facing answer into `message.content`; a
too-small `max_tokens` yields an empty `content` (all budget spent reasoning),
which is why callers pass a generous budget and fall back to `.reasoning` only
for structured/critic reads.

Contract used by the callers:
    resp = glm_chat(messages, tools=None, response_format=None,
                    temperature=0.2, max_tokens=2048)
    resp.content        -> str | None   (final answer)
    resp.reasoning      -> str | None   (chain-of-thought, if exposed)
    resp.tool_calls     -> list[GlmToolCall]  (.id, .name, .arguments: dict)

This is a *blocking* SDK call — callers wrap it in `asyncio.to_thread`. Exceptions
propagate so the callers' retry/degradation logic can handle them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from app.config import settings


@dataclass
class GlmToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class GlmResponse:
    content: str | None = None
    reasoning: str | None = None
    tool_calls: list[GlmToolCall] = field(default_factory=list)


_client: OpenAI | None = None


def _api_key() -> str | None:
    """Chat key, honoring the split name first then the legacy GLM name."""
    return settings.ai_chat_api_key or settings.glm_api_key or settings.ai_api_key


def has_api_key() -> bool:
    return bool(_api_key())


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        key = _api_key()
        if not key:
            raise RuntimeError("GLM chat API key is not configured (AI_CHAT_API_KEY / GLM_API_KEY)")
        _client = OpenAI(
            api_key=key,
            base_url=settings.ai_base_url,
            timeout=settings.ai_request_timeout_seconds,
        )
    return _client


def _wrap_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Adapt the orchestrator's flat TOOL_SPECS ({name, description, parameters})
    to the OpenAI tool schema ({"type": "function", "function": {...}}). Specs that
    are already wrapped are passed through untouched."""
    if not tools:
        return None
    wrapped: list[dict[str, Any]] = []
    for spec in tools:
        if "function" in spec and spec.get("type") == "function":
            wrapped.append(spec)
        else:
            wrapped.append({"type": "function", "function": spec})
    return wrapped


def _loads_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def glm_chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    response_format: dict[str, Any] | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> GlmResponse:
    """Run one GLM-5.2 chat/tool-calling turn. Blocking; wrap in a thread from async code."""
    kwargs: dict[str, Any] = {
        "model": settings.ai_chat_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    wrapped_tools = _wrap_tools(tools)
    if wrapped_tools:
        kwargs["tools"] = wrapped_tools
        kwargs["tool_choice"] = "auto"
    if response_format:
        kwargs["response_format"] = response_format

    response = _get_client().chat.completions.create(**kwargs)
    message = response.choices[0].message

    tool_calls: list[GlmToolCall] = []
    for call in getattr(message, "tool_calls", None) or []:
        function = getattr(call, "function", None)
        if function is None:
            continue
        tool_calls.append(
            GlmToolCall(
                id=getattr(call, "id", "") or "",
                name=getattr(function, "name", "") or "",
                arguments=_loads_arguments(getattr(function, "arguments", None)),
            )
        )

    content = getattr(message, "content", None)
    reasoning = getattr(message, "reasoning_content", None)
    return GlmResponse(content=content, reasoning=reasoning, tool_calls=tool_calls)
