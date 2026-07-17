"""Translation + hotline/embassy lookup (doc sections 4, 8).

Embassy routed by nationality, hotlines routed by region — never by language.
"""

from __future__ import annotations

from typing import Any

from app.ai.client import ai_client
from app.db.postgres import get_pool


async def translate_or_get_hotline(text: str, region: str, nationality: str) -> dict[str, Any]:
    translation = await _translate(text)
    pool = get_pool()
    async with pool.acquire() as conn:
        hotlines = await conn.fetch(
            "SELECT service_type, phone_number, notes FROM emergency_hotlines WHERE region = $1",
            region,
        )
        embassy = await conn.fetchrow(
            "SELECT country_name, phone_number, address FROM embassies WHERE nationality = $1",
            nationality,
        )
    return {
        "translation": translation,
        "hotlines": [dict(r) for r in hotlines],
        "embassy": dict(embassy) if embassy else None,
    }


async def _translate(text: str) -> str:
    response = await ai_client.chat(
        [
            {"role": "system", "content": "Translate the user's message faithfully, preserve meaning."},
            {"role": "user", "content": text},
        ]
    )
    return response.content or text
