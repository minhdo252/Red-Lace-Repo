"""Generic vision tool (doc section 3): one tool, mode-dispatched output schema."""

from __future__ import annotations

from typing import Any

from app.ai.client import ai_client

VALID_MODES = {"receipt", "dish", "page_transparency", "chat_screenshot"}


async def read_image(image_bytes: bytes, mode: str) -> dict[str, Any]:
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode {mode!r}, must be one of {sorted(VALID_MODES)}")
    return await ai_client.vision(image_bytes, mode)
