"""LLM price-advice pass (GLM-5.2): turns a Module 2.1 price comparison into
short, warm, tier-appropriate advice written in the tourist's language.

The tier is decided DETERMINISTICALLY from the price gap so the rules are exact
(an LLM can't miscategorize); GLM only writes the prose for that tier. Across a
menu the worst item's tier wins and is named. Returns None when GLM is
unavailable or errors, so the caller can fall back to its deterministic reply —
graceful degradation, never a fabricated verdict.

Called directly through app/ai/glm_chat.py (same as app/agent/critic.py), off the
event loop via asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.ai.glm_chat import glm_chat, has_api_key

# Tourist native_language code -> language name for the prompt.
_LANG_NAMES = {
    "en": "English",
    "vi": "Vietnamese",
    "ko": "Korean",
    "zh": "Chinese",
    "ja": "Japanese",
}

# Gradable tiers, worst first (used to pick a menu's overall verdict).
_TIER_ORDER = ["avoid", "caution", "reasonable"]

_TIER_STANCE = {
    "avoid": (
        "The observed price is MORE THAN 100% above the local reference (more than "
        "double). Strongly recommend the customer consider another place."
    ),
    "caution": (
        "The observed price is 50-100% above the local reference. Explain that this "
        "CAN be legitimate — the shop's location, reputation, or quality — but still "
        "recommend the customer reconsider before paying."
    ),
    "reasonable": (
        "The observed price is less than 50% above the local reference (or is fair / "
        "cheaper). Reassure the customer this is a reasonable price; the small "
        "difference can come from factors like location, ingredients, portion size, "
        "or service."
    ),
    "info": (
        "No price was stated — simply tell the customer the typical local price, "
        "warmly and briefly."
    ),
    "unknown": (
        "There is no local reference to compare against. Tell the customer we could "
        "not find a typical local price for this, so we cannot judge whether it is "
        "fair."
    ),
}

_SYSTEM_PROMPT = (
    "You are a friendly, trustworthy price advisor for foreign tourists in Vietnam. "
    "Given a price comparison from local data, write SHORT (2-4 sentences), warm, "
    "practical advice. Use light markdown: **bold** for the single key takeaway, and "
    "'- ' bullets only if they genuinely help. Use ONLY the numbers provided — never "
    "invent or change a price. Follow the given stance exactly. No greeting, no sign-off."
)


def _item_tier(item: dict[str, Any]) -> str | None:
    """Tier for one compared item, or None when it can't be graded (no reference)."""
    observed = item.get("observed_price")
    reference = item.get("reference_price")
    if observed is None:
        return "info" if reference is not None else None
    if reference is None:
        return None
    pct = item.get("price_diff_pct")
    if pct is None:
        return None
    if pct > 100:
        return "avoid"
    if pct >= 50:
        return "caution"
    return "reasonable"


def overall_tier(items: list[dict[str, Any]]) -> str:
    """The verdict for the whole turn: the worst gradable item wins; else info/unknown."""
    tiers = [_item_tier(it) for it in items]
    for tier in _TIER_ORDER:  # worst first
        if tier in tiers:
            return tier
    if "info" in tiers:
        return "info"
    return "unknown"


def _worst_item(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    gradable = [
        it for it in items if _item_tier(it) in _TIER_ORDER and it.get("price_diff_pct") is not None
    ]
    if not gradable:
        return None
    return max(gradable, key=lambda it: it["price_diff_pct"])


def _format_items(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for it in items:
        parts = [f"item={it.get('item')}"]
        if it.get("observed_price") is not None:
            parts.append(f"observed={float(it['observed_price']):.0f} VND")
        if it.get("reference_price") is not None:
            parts.append(f"local_reference={float(it['reference_price']):.0f} VND")
        if it.get("price_diff_pct") is not None:
            parts.append(f"diff={float(it['price_diff_pct']):.0f}%")
        lines.append(" · ".join(parts))
    return "\n".join(lines)


async def price_advice(items: list[dict[str, Any]], native_language: str = "en") -> str | None:
    """Write tourist-facing price advice for `items` in `native_language`, or None
    when GLM is unavailable/errors (caller falls back to a deterministic reply)."""
    if not items or not has_api_key():
        return None

    tier = overall_tier(items)
    language = _LANG_NAMES.get((native_language or "en").lower(), "English")
    stance = _TIER_STANCE.get(tier, _TIER_STANCE["reasonable"])

    user_content = (
        f"Write the advice in {language}.\n"
        f"Tier: {tier}. Stance to follow exactly: {stance}\n\n"
        f"Price comparison ({len(items)} item(s)):\n{_format_items(items)}\n"
    )
    worst = _worst_item(items)
    if worst is not None and len(items) > 1:
        user_content += f"\nName the most-overpriced item: {worst.get('item')}.\n"
    user_content += "\nWrite the tourist-facing advice now."

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    try:
        # Reasoning model: budget must cover the reasoning trace AND reach the final
        # answer (mirrors critic.py's 2048).
        response = await asyncio.to_thread(glm_chat, messages, temperature=0.4, max_tokens=2048)
    except Exception:  # noqa: BLE001 - fall back to the deterministic reply, never fabricate
        return None

    text = (response.content or "").strip()
    return text or None
