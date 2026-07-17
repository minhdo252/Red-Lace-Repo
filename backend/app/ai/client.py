"""Placeholder AI client.

Every model touchpoint in this codebase (chat/tool-calling reasoning, vision
reads, text embedding) goes through this single class. Nothing else in the
app should import an LLM SDK directly — swap providers by editing this file
only.

Two modes, controlled by AI_MODE in .env:
  - "mock" (default): returns deterministic canned responses so the
    orchestrator loop, tool-calling flow, and API endpoints are fully
    runnable and testable with `docker compose up` and no API key.
  - "live": each method raises NotImplementedError at the marked TODO —
    replace the body with your existing API call.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

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


class AIClient:
    def __init__(self) -> None:
        self.mode = settings.ai_mode

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """Reasoning + tool-calling turn.

        `messages` follows the OpenAI-style chat schema (role/content, plus
        role="tool" results appended by the orchestrator). `tools` is the
        JSON-schema tool spec list from app/agent/tools.py.
        """
        if self.mode == "mock":
            return ChatResponse(
                content="[mock] Đã ghi nhận. (Wire a real LLM call into "
                "AIClient.chat to get real responses.)"
            )

        # TODO: plug in your own LLM API call here (Gemini / OpenAI / other).
        # Must return a ChatResponse with either `content` (final text) or
        # `tool_calls` (list of ToolCall) when the model wants to call a tool.
        raise NotImplementedError("AIClient.chat: wire your LLM API call here")

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

        # TODO: plug in your own vision-capable LLM call here.
        raise NotImplementedError("AIClient.vision: wire your vision API call here")

    async def embed(self, text: str) -> list[float]:
        """Text embedding for Qdrant kNN lookups."""
        if self.mode == "mock":
            return _mock_embedding(text, settings.embedding_dim)

        # TODO: plug in your own embedding API call (or local sentence-transformers) here.
        raise NotImplementedError("AIClient.embed: wire your embedding call here")


def _mock_embedding(text: str, dim: int) -> list[float]:
    """Deterministic pseudo-embedding so mock mode's kNN calls don't crash.
    Not semantically meaningful — only for exercising the plumbing."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [(digest[i % len(digest)] / 127.5) - 1.0 for i in range(dim)]
    norm = sum(v * v for v in values) ** 0.5 or 1.0
    return [v / norm for v in values]


ai_client = AIClient()
