"""AI client — chat/tool-calling, vision, and text-embedding, all routed
through a single OpenAI-compatible endpoint (FPT Cloud Marketplace by
default, see AI_BASE_URL in app/config.py). Nothing else in the app should
import an LLM SDK directly — swap providers by editing this file only.

Two modes, controlled by AI_MODE in .env:
  - "mock" (default): deterministic canned responses, no API key needed.
  - "live": real calls via the `openai` SDK against AI_BASE_URL, with one
    API key + model per capability (chat/vision/embed can be different
    models — even different providers — as long as each speaks the
    OpenAI-compatible Chat Completions / Embeddings API).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

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


def _to_openai_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """TOOL_SPECS entries are already {name, description, parameters} — that's
    exactly the OpenAI "function" object, just missing the
    {"type": "function", "function": ...} wrapper the Chat Completions API expects."""
    if not tools:
        return None
    return [{"type": "function", "function": spec} for spec in tools]


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the orchestrator's internal message shape (assistant
    tool_calls as plain {id, name, arguments} dicts, tool content as a raw
    dict) into the OpenAI Chat Completions schema (tool_calls nested under
    function.arguments as a JSON string, tool content as a JSON string)."""
    converted: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            converted.append(
                {
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                            },
                        }
                        for tc in msg["tool_calls"]
                    ],
                }
            )
        elif role == "tool":
            content = msg.get("content")
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": msg["tool_call_id"],
                    "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                }
            )
        else:
            converted.append({"role": role, "content": msg.get("content")})
    return converted


def _extract_json(text: str) -> dict[str, Any] | None:
    """Vision prompts ask the model for strict JSON, but models sometimes
    wrap it in ```json fences or add stray text around it — pull out the
    first {...} block and parse that as a fallback."""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


VISION_PROMPTS: dict[str, str] = {
    "receipt": (
        "You are reading a photo of a restaurant/tour receipt or menu. "
        "Respond with strict JSON only, no prose, matching exactly this shape: "
        '{"detected_price_text": string|null, "dish_candidates": string[], "portion_cues": string}'
    ),
    "dish": (
        "You are reading a photo of a dish/meal to help estimate a fair price. "
        "Respond with strict JSON only, no prose, matching exactly this shape: "
        '{"detected_price_text": string|null, "dish_candidates": string[], "portion_cues": string}'
    ),
    "page_transparency": (
        "You are reading a screenshot of a Facebook Page's 'Page Transparency' section, "
        "used to assess how old and consistent a tourism business's Facebook page is. "
        "Respond with strict JSON only, no prose, matching exactly this shape: "
        '{"page_name": string|null, "creation_date_text": string|null, '
        '"name_history": string[], "primary_location": string|null, "raw_text": string}. '
        "creation_date_text should be the page-creation date exactly as shown on screen "
        "(any language/format, e.g. 'Page created April 3, 2019' or '3 thg 4, 2019'). "
        "name_history should list any previous page names shown under 'Page history' or "
        "similar — empty array if none are shown or the section isn't visible. Never "
        "invent a date or name you cannot actually see in the image."
    ),
    "chat_screenshot": (
        "You are transcribing a screenshot of a chat/DM conversation with a tour or "
        "homestay seller, to check it against known scam-pressure phrasing. Respond "
        "with strict JSON only, no prose, matching exactly this shape: "
        '{"transcript_text": string}. Transcribe only the seller\'s messages, in the '
        "original language, concatenated with newlines."
    ),
}


class AIClient:
    def __init__(self) -> None:
        self.mode = settings.ai_mode
        self._chat_client: AsyncOpenAI | None = None
        self._vision_client: AsyncOpenAI | None = None
        self._embed_client: AsyncOpenAI | None = None

    def _get_chat_client(self) -> AsyncOpenAI:
        if self._chat_client is None:
            self._chat_client = AsyncOpenAI(api_key=settings.ai_chat_api_key, base_url=settings.ai_base_url)
        return self._chat_client

    def _get_vision_client(self) -> AsyncOpenAI:
        if self._vision_client is None:
            self._vision_client = AsyncOpenAI(api_key=settings.ai_vision_api_key, base_url=settings.ai_base_url)
        return self._vision_client

    def _get_embed_client(self) -> AsyncOpenAI:
        if self._embed_client is None:
            self._embed_client = AsyncOpenAI(api_key=settings.ai_embed_api_key, base_url=settings.ai_base_url)
        return self._embed_client

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

        client = self._get_chat_client()
        response = await client.chat.completions.create(
            model=settings.ai_chat_model,
            messages=_to_openai_messages(messages),
            tools=_to_openai_tools(tools),
        )
        message = response.choices[0].message

        if message.tool_calls:
            calls = []
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
            return ChatResponse(content=message.content, tool_calls=calls)

        return ChatResponse(content=message.content or "")

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

        prompt = VISION_PROMPTS.get(mode, VISION_PROMPTS["receipt"])
        b64 = base64.b64encode(image_bytes).decode("ascii")

        client = self._get_vision_client()
        response = await client.chat.completions.create(
            model=settings.ai_vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
        )
        raw_text = response.choices[0].message.content or ""
        parsed = _extract_json(raw_text)
        if parsed is None:
            # Model didn't return parseable JSON — surface the raw text instead
            # of silently dropping it, so callers/downstream logic can see why.
            return {"mode": mode, "raw_text": raw_text, "parse_error": True}
        parsed["mode"] = mode
        return parsed

    async def embed(self, text: str) -> list[float]:
        """Text embedding for Qdrant kNN lookups."""
        if self.mode == "mock":
            return _mock_embedding(text, settings.embedding_dim)

        client = self._get_embed_client()
        response = await client.embeddings.create(
            model=settings.ai_embed_model,
            input=[text],
            dimensions=settings.embedding_dim,
            encoding_format="float",
        )
        return response.data[0].embedding


def _mock_embedding(text: str, dim: int) -> list[float]:
    """Deterministic pseudo-embedding so mock mode's kNN calls don't crash.
    Not semantically meaningful — only for exercising the plumbing."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [(digest[i % len(digest)] / 127.5) - 1.0 for i in range(dim)]
    norm = sum(v * v for v in values) ** 0.5 or 1.0
    return [v / norm for v in values]


ai_client = AIClient()
