"""Structured translation + hotline/embassy lookup."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.ai.client import ai_client
from app.db.postgres import get_pool
from app.modules.pii import redact_pii


class TranslationResult(BaseModel):
    detected_language: str = Field(default="unknown")
    source_text_clean: str
    translated_text: str
    target_language: str
    key_entities: list[str] = Field(default_factory=list)
    normalized_prices_vnd: list[int] = Field(default_factory=list)
    speaker_split: list[dict[str, Any]] = Field(default_factory=list)


NATIONALITY_TO_LANGUAGE = {
    "KR": "ko",
    "CN": "zh",
    "TW": "zh",
    "JP": "ja",
    "US": "en",
    "GB": "en",
    "AU": "en",
    "SG": "en",
}


def _target_language(nationality: str | None, native_language: str | None = None) -> str:
    if native_language:
        return native_language.lower()
    return NATIONALITY_TO_LANGUAGE.get((nationality or "").upper(), "en")


async def translate_or_get_hotline(
    text: str,
    region: str,
    nationality: str,
    native_language: str | None = None,
) -> dict[str, Any]:
    safe_text = redact_pii(text)
    translation = await translate_text(
        safe_text,
        nationality=nationality,
        native_language=native_language,
    )
    pool = get_pool()
    async with pool.acquire() as conn:
        hotlines = await conn.fetch(
            "SELECT service_type, phone_number, notes FROM emergency_hotlines WHERE region = $1 ORDER BY id",
            region,
        )
        embassy = await conn.fetchrow(
            "SELECT country_name, phone_number, address, region_hint FROM embassies WHERE nationality = $1",
            nationality,
        )
    return {
        "translation": translation,
        "hotlines": [dict(r) for r in hotlines],
        "embassy": dict(embassy) if embassy else None,
    }


async def translate_text(
    text: str,
    nationality: str,
    native_language: str | None = None,
    history_context: list[str] | None = None,
) -> dict[str, Any]:
    """Translate a chat turn deterministically for Module 1's backend contract."""
    return await _translate_advanced(
        text,
        target_language=_target_language(nationality, native_language),
        history_context=history_context,
    )


async def _translate_advanced(
    text: str,
    target_language: str = "en",
    history_context: list[str] | None = None,
) -> dict[str, Any]:
    """Translate code-switched travel conversation into a structured object."""
    context = "\n".join(history_context[-3:]) if history_context else "(no recent context)"
    prompt = f"""You are a live interpreter for tourists in Vietnam.
Return only valid JSON matching this schema:
{{
  "detected_language": "vi|en|ko|zh|ja|mixed|unknown",
  "source_text_clean": "cleaned original text",
  "translated_text": "faithful natural translation",
  "target_language": "{target_language}",
  "key_entities": ["food, place, business, product names"],
  "normalized_prices_vnd": [integer prices in VND],
  "speaker_split": [{{"speaker": "tourist|vendor|unknown", "text": "...", "translated": "..."}}]
}}

Rules:
- If the source is mostly Vietnamese/vendor speech, translate to {target_language}.
- If the source is mostly tourist language or English/Korean/Chinese/Japanese, translate to Vietnamese for the local vendor.
- Preserve prices and normalize slang such as k, ngàn, nghìn, triệu, USD to VND integers when clear.
- Use recent context only to repair cut-off audio chunks, never invent missing facts.

Recent context:
{context}
"""
    response = await ai_client.chat(
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
    )

    if response.content:
        try:
            parsed = json.loads(response.content)
            validated = TranslationResult(**parsed)
            return validated.model_dump()
        except Exception:
            pass

    fallback = TranslationResult(
        detected_language="unknown",
        source_text_clean=text,
        translated_text=text if (response.content or "").startswith("[mock]") else (response.content or text),
        target_language=target_language,
    )
    return fallback.model_dump()
