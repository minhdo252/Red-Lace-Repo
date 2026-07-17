"""Background conversation compression for long live-translation sessions."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import BackgroundTasks
from pydantic import BaseModel, Field

from app.ai.client import ai_client
from app.db.postgres import get_pool

KEEP_RECENT_TURNS = 10
COMPRESSION_TRIGGER_TURNS = KEEP_RECENT_TURNS + 2


class StructuredSummary(BaseModel):
    summary_text: str = Field(..., description="Short conversation context summary")
    items_negotiated: list[dict[str, Any]] = Field(default_factory=list)
    safety_concerns: list[str] = Field(default_factory=list)
    prices_quoted: list[dict[str, Any]] = Field(default_factory=list)
    scam_flags: list[dict[str, Any]] = Field(default_factory=list)


def _turn_to_line(message: dict[str, Any]) -> str | None:
    role = message.get("role", "unknown")
    content = message.get("content")
    if content is None:
        return None
    return f"{role}: {content}"


async def _do_compress_history(
    session_id: str,
    old_turns: list[dict[str, Any]],
    recent_turns: list[dict[str, Any]],
) -> None:
    transcript = "\n".join(line for msg in old_turns if (line := _turn_to_line(msg)))
    if not transcript.strip():
        return

    prompt = (
        "Summarize old turns of this tourist travel negotiation into valid JSON. "
        "Preserve all items, prices, safety concerns, scam flags, people, places, "
        "and unresolved user needs. Required keys: summary_text, items_negotiated, "
        "prices_quoted, safety_concerns, scam_flags."
    )
    response = await ai_client.chat(
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": transcript},
        ],
        response_format={"type": "json_object"},
    )

    summary_content = "[CONVERSATION SUMMARY]: Old turns summarized."
    if response.content:
        try:
            data = json.loads(response.content)
            validated = StructuredSummary(**data)
            summary_content = f"[STRUCTURED SUMMARY]: {validated.model_dump_json()}"
        except Exception:
            summary_content = f"[SUMMARY]: {response.content}"

    compressed_history = [{"role": "system", "content": summary_content}] + recent_turns
    sid = uuid.UUID(session_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET compressed_history = $1 WHERE id = $2",
            json.dumps(compressed_history, ensure_ascii=False),
            sid,
        )


def trigger_background_compression(
    session_id: str,
    current_history: list[dict[str, Any]],
    background_tasks: BackgroundTasks,
) -> list[dict[str, Any]]:
    """Return recent context immediately and enqueue old-turn compression."""
    if len(current_history) <= COMPRESSION_TRIGGER_TURNS:
        return current_history

    old_turns = current_history[:-KEEP_RECENT_TURNS]
    recent_turns = current_history[-KEEP_RECENT_TURNS:]
    background_tasks.add_task(_do_compress_history, session_id, old_turns, recent_turns)
    return recent_turns
