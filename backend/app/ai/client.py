"""Single AI gateway for chat, vision, embeddings, and speech-to-text.

All model touchpoints in the app go through this file. `AI_MODE=mock` keeps
the stack deterministic and runnable without API keys; `AI_MODE=live` uses the
OpenAI-compatible AI Marketplace endpoint configured in app.config.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

try:  # Keep mock mode importable even before dependencies are installed locally.
    from openai import (
        APIConnectionError,
        APITimeoutError,
        AsyncOpenAI,
        BadRequestError,
        InternalServerError,
        RateLimitError,
    )

    TRANSIENT_AI_ERRORS = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)
except ImportError:  # pragma: no cover - exercised only in bare local envs
    AsyncOpenAI = None  # type: ignore[assignment]

    class BadRequestError(Exception):
        pass

    TRANSIENT_AI_ERRORS = (ConnectionError, TimeoutError)

try:
    from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
except ImportError:  # pragma: no cover

    def retry(*_args: Any, **_kwargs: Any):
        def _decorator(fn: Any) -> Any:
            return fn

        return _decorator

    def stop_after_attempt(_attempts: int) -> None:
        return None

    def wait_exponential(**_kwargs: Any) -> None:
        return None

    def retry_if_exception_type(_types: Any) -> None:
        return None

from app.config import settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


def _loads_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"_raw": value}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _message_response_text(message: Any, *, allow_reasoning_fallback: bool) -> str:
    """Read GLM structured output without leaking reasoning in normal replies."""

    content = _content_to_text(getattr(message, "content", ""))
    if not content.strip() and allow_reasoning_fallback:
        return _content_to_text(getattr(message, "reasoning_content", ""))
    return content


def _mock_embedding(text: str, dim: int) -> list[float]:
    """Deterministic pseudo-embedding so mock mode's kNN calls don't crash."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [(digest[i % len(digest)] / 127.5) - 1.0 for i in range(dim)]
    norm = sum(v * v for v in values) ** 0.5 or 1.0
    return [v / norm for v in values]


def _image_mime(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _is_whisper_hallucination(text: str) -> bool:
    clean = text.strip().lower()
    hallucinations = [
        "subtitles by",
        "amara.org",
        "cảm ơn các bạn đã theo dõi",
        "xin chào và hẹn gặp lại",
        "[âm nhạc]",
        "tập tiếp theo",
    ]
    return len(clean) < 2 or any(item in clean for item in hallucinations)


class AIClient:
    def __init__(self) -> None:
        self.mode = settings.ai_mode.lower()
        self._chat_client: Any | None = None
        self._vision_client: Any | None = None
        self._embed_client: Any | None = None
        self._stt_client: Any | None = None

    def _get_chat_client(self) -> Any:
        if AsyncOpenAI is None:
            raise RuntimeError("openai package is not installed; install backend requirements first")
        if self._chat_client is None:
            self._chat_client = AsyncOpenAI(
                api_key=settings.ai_chat_api_key or settings.glm_api_key or settings.ai_api_key,
                base_url=settings.ai_base_url,
                timeout=settings.ai_request_timeout_seconds,
            )
        return self._chat_client

    def _get_vision_client(self) -> Any:
        if AsyncOpenAI is None:
            raise RuntimeError("openai package is not installed; install backend requirements first")
        if self._vision_client is None:
            self._vision_client = AsyncOpenAI(
                api_key=settings.ai_vision_api_key,
                base_url=settings.ai_base_url,
                timeout=settings.ai_request_timeout_seconds,
            )
        return self._vision_client

    def _get_embed_client(self) -> Any:
        if AsyncOpenAI is None:
            raise RuntimeError("openai package is not installed; install backend requirements first")
        if self._embed_client is None:
            self._embed_client = AsyncOpenAI(
                api_key=settings.ai_embed_api_key or settings.vn_embedding_api_key or settings.ai_api_key,
                base_url=settings.ai_base_url,
                timeout=settings.ai_request_timeout_seconds,
            )
        return self._embed_client

    def _get_stt_client(self) -> Any:
        if AsyncOpenAI is None:
            raise RuntimeError("openai package is not installed; install backend requirements first")
        if self._stt_client is None:
            api_key = settings.ai_stt_api_key or settings.whisper_v3_api_key or settings.ai_api_key
            if not api_key:
                raise RuntimeError("speech transcription API key is not configured")
            self._stt_client = AsyncOpenAI(
                api_key=api_key,
                base_url=settings.ai_base_url,
                timeout=settings.ai_request_timeout_seconds,
            )
        return self._stt_client

    @retry(
        retry=retry_if_exception_type(TRANSIENT_AI_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Run a chat/tool-calling turn through AI Marketplace."""
        if self.mode == "mock":
            return ChatResponse(
                content="[mock] Đã ghi nhận. (Sử dụng AI_MODE=live để kết nối AI Marketplace.)"
            )

        # Live: delegate to the shared GLM-5.2 client (app/ai/glm_chat.py) so the
        # orchestrator, critic, and every other chat caller use one payload. GLM-5.2
        # is a reasoning model, so max_tokens is set generously enough that the final
        # answer is reached after the reasoning tokens (a small budget => empty
        # content). glm_chat is a blocking SDK call; run it off the event loop.
        import asyncio

        from app.ai.glm_chat import glm_chat

        glm_response = await asyncio.to_thread(
            glm_chat,
            messages,
            tools=tools,
            response_format=response_format,
            temperature=0.2,
            max_tokens=2048,
        )

        if glm_response.tool_calls:
            return ChatResponse(
                tool_calls=[
                    ToolCall(id=call.id, name=call.name, arguments=call.arguments)
                    for call in glm_response.tool_calls
                ]
            )

        # Final answer is `content`; fall back to reasoning only for structured
        # (response_format) calls where an empty content would otherwise break a
        # downstream JSON parse.
        content = glm_response.content
        if not content and response_format:
            content = glm_response.reasoning
        return ChatResponse(content=content)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
    async def vision(self, image_bytes: bytes, mode: str) -> dict[str, Any]:
        """Multimodal image read. `mode` in {receipt, dish, page_transparency, chat_screenshot}."""
        if self.mode == "mock":
            return {
                "mode": mode,
                "note": "[mock] no vision model wired in yet",
                "detected_price_text": None,
                "dish_candidates": [],
                "portion_cues": "không rõ",
            }

        encoded = base64.b64encode(image_bytes).decode("ascii")
        mime = _image_mime(image_bytes)
        prompts = {
            "receipt": "Read this receipt/menu image and extract prices, item names, currencies, and anomalies.",
            "dish": "Identify the dish, likely portion size, visible menu clues, and any price text.",
            "page_transparency": "Read this page transparency screenshot and extract business trust signals.",
            "chat_screenshot": "Read this chat screenshot and extract suspicious payment or pressure signals.",
        }
        user_prompt = prompts.get(mode, "Read this image and return structured observations.")
        kwargs: dict[str, Any] = {
            "model": settings.ai_vision_model,
            "temperature": 0.0,
            "stream": False,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only a compact JSON object. Include mode, observed_text, "
                        "detected_price_text, dish_candidates, portion_cues, and risk_notes when relevant."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ],
        }

        client = self._get_vision_client()
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("response_format", None)
            response = await client.chat.completions.create(**kwargs)

        content = _content_to_text(response.choices[0].message.content)
        parsed = _loads_object(content)
        if "_raw" in parsed:
            return {"mode": mode, "raw": content}
        parsed.setdefault("mode", mode)
        return parsed

    @retry(
        retry=retry_if_exception_type(TRANSIENT_AI_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    async def embed(self, text: str) -> list[float]:
        """Text embedding for Qdrant kNN lookups."""
        if self.mode == "mock":
            return _mock_embedding(text, settings.embedding_dim)

        response = await self._get_embed_client().embeddings.create(
            model=settings.ai_embed_model,
            input=[text],
        )
        return response.data[0].embedding

    @retry(
        retry=retry_if_exception_type(TRANSIENT_AI_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    async def transcribe(
        self,
        audio_bytes: bytes,
        language_hint: str | None = None,
        initial_prompt: str | None = None,
    ) -> str:
        """Speech-to-text through AI Marketplace Whisper-compatible API."""
        if self.mode == "mock":
            return "[mock audio] How much for this bowl of beef pho?"

        kwargs: dict[str, Any] = {
            "model": settings.stt_model,
            "file": ("speech.wav", audio_bytes, "audio/wav"),
            "response_format": "json",
            "timeout": settings.ai_request_timeout_seconds,
        }
        if language_hint:
            kwargs["language"] = language_hint
        if initial_prompt:
            kwargs["prompt"] = initial_prompt

        response = await self._get_stt_client().audio.transcriptions.create(**kwargs)
        text = getattr(response, "text", "") or ""
        return "" if _is_whisper_hallucination(text) else text

    async def close(self) -> None:
        clients = {
            id(client): client
            for client in (self._chat_client, self._vision_client, self._embed_client, self._stt_client)
            if client
        }
        for client in clients.values():
            await client.close()
        self._chat_client = None
        self._vision_client = None
        self._embed_client = None
        self._stt_client = None


ai_client = AIClient()
