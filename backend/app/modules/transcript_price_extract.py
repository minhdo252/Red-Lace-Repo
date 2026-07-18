"""
transcript_price_extract.py
---------------------------
Extract (dish item, price) pairs from a spoken/typed transcript so the voice
route can run the fair-price comparison (compare_price) the same way the image
route does for a menu photo.

A bare spoken price ("cô bán bún chả này 200k") carries the dish name and the
amount in one breath. The Module 1 price normaliser (translation.extract_
normalized_prices_vnd) already turns "200k" / "hai trăm nghìn" into 200000, but
it drops the dish name — so the number alone can't be compared to a reference.
This module pairs each amount back with the dish it belongs to.

Primary path: one small GLM JSON-extraction call (live mode). Fallback: a
deterministic token-lookback heuristic (used when the model is unavailable, in
AI_MODE=mock, or when the model returns nothing usable). Both are gated by the
deterministic price normaliser: no explicit amount in the text -> no work, and
a model-proposed price is only trusted when it matches a deterministically
extracted amount (kills hallucinated numbers).

Never raises: any failure degrades to [] so the voice reply is unaffected.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

from app.ai.client import ai_client
from app.modules.price_comparison import _COMPOUND_STARTERS
from app.modules.translation import (
    _VN_AMOUNT_TOKENS,
    _VN_NUMBER_WORDS,
    _fold_vietnamese,
    _json_object,
    extract_normalized_prices_vnd,
)
from app.utils.menu_normalize import normalize_item_name

logger = logging.getLogger(__name__)

# Words that sit between a dish name and its price but are not part of the name.
_STOPWORDS: frozenset[str] = frozenset(
    {"này", "kia", "đó", "đấy", "giá", "chỉ", "có", "là", "hết", "lấy", "khoảng", "tầm"}
)

# How many tokens to look back from a price for the dish it belongs to.
_LOOKBACK = 6

_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)
# A single token that already encodes a price, e.g. "200k".
_K_TOKEN_RE = re.compile(r"^\d+(?:[.,]\d+)?k$")
_UNIT_TOKENS: frozenset[str] = frozenset({"trieu", "million", "nghin", "ngan"})

_EXTRACTION_SYSTEM_PROMPT = (
    "You extract goods or services that are quoted with an explicit price from a "
    "short Vietnamese or mixed Vietnamese/English transcript of a market or street "
    "conversation. Return ONLY one JSON object of the form "
    '{"items": [{"item": "<dish or service name in Vietnamese>", "price_vnd": <integer VND>}]}. '
    "Normalise spoken amounts to an integer number of Vietnamese dong "
    '("200k" and "hai trăm nghìn" both become 200000). '
    "Do not invent items or prices. If no item has an explicit price, return "
    '{"items": []}. Never treat phone numbers, OTP codes, addresses, room numbers, '
    "or times as prices."
)


def _lower_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower()


def _dish_from_lookback(raw_tokens: list[str], price_index: int) -> str | None:
    """Find the dish name in the up-to-_LOOKBACK tokens before a price token.

    Matches the diacritic-bearing NFC tokens (not the folded ones) against
    _COMPOUND_STARTERS, since that set is stored with diacritics ("bún", "phở").
    Builds a 1- or 2-token head phrase the same way price_comparison.head_phrase
    would, then cleans it with the shared menu-name normaliser.
    """
    start = max(0, price_index - _LOOKBACK)
    window = raw_tokens[start:price_index]
    head_pos: int | None = None
    for offset, token in enumerate(window):
        # A few dish-head words double as number words ("ba"); those are part of a
        # spoken amount ("ba trăm nghìn"), not a dish, so don't treat them as a head.
        if token in _COMPOUND_STARTERS and _fold_vietnamese(token) not in _VN_NUMBER_WORDS:
            head_pos = offset
            break
    if head_pos is None:
        return None

    head = window[head_pos]
    phrase_tokens = [head]
    nxt = window[head_pos + 1] if head_pos + 1 < len(window) else None
    if nxt is not None and nxt not in _STOPWORDS and not nxt.isdigit() and not _K_TOKEN_RE.match(nxt):
        phrase_tokens.append(nxt)
    cleaned = normalize_item_name(" ".join(phrase_tokens))
    return cleaned or None


def _price_anchor_indices(folded_tokens: list[str]) -> list[int]:
    """Indices of tokens that end a price mention, left to right.

    Three shapes are recognised, mirroring translation.extract_normalized_prices_vnd:
      - a "k"-suffixed number in one token: "200k"
      - a number token followed by a unit word: "200 nghin" (anchor = the unit)
      - a spelled amount ending in a scale word: "hai tram nghin" (anchor = "nghin")
    """
    anchors: list[int] = []
    for i, tok in enumerate(folded_tokens):
        if _K_TOKEN_RE.match(tok):
            anchors.append(i)
        elif tok in _UNIT_TOKENS and tok in _VN_AMOUNT_TOKENS:
            anchors.append(i)
    return anchors


def heuristic_priced_items(text: str) -> list[dict[str, Any]]:
    """Deterministic fallback: pair each detected amount with the nearest dish
    name that precedes it. Order-aligned with the deterministic price list."""
    prices = extract_normalized_prices_vnd(text)
    if not prices:
        return []

    raw_tokens = _WORD_RE.findall(_lower_nfc(text))
    folded_tokens = [_fold_vietnamese(tok) for tok in raw_tokens]
    anchors = _price_anchor_indices(folded_tokens)

    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for anchor, price in zip(anchors, prices):
        dish = _dish_from_lookback(raw_tokens, anchor)
        if not dish:
            continue
        key = (dish, price)
        if key in seen:
            continue
        seen.add(key)
        pairs.append({"item": dish, "price_vnd": price, "source": "heuristic"})
    return pairs


async def extract_priced_items(text: str) -> list[dict[str, Any]]:
    """(item, price) pairs from a transcript. Primary GLM extraction with a
    deterministic heuristic fallback; both gated by the price normaliser so a
    text with no explicit amount does zero AI work. Never raises."""
    allowed = set(extract_normalized_prices_vnd(text))
    if not allowed:
        return []

    try:
        response = await ai_client.chat(
            messages=[
                {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
        )
        parsed = _json_object(response.content or "")
    except Exception:  # noqa: BLE001 - extraction must never break the voice reply
        parsed = None

    items: list[dict[str, Any]] = []
    if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        seen: set[tuple[str, int]] = set()
        for entry in parsed["items"]:
            if not isinstance(entry, dict):
                continue
            raw_name = entry.get("item")
            raw_price = entry.get("price_vnd")
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            try:
                price = int(raw_price)
            except (TypeError, ValueError):
                continue
            # Only trust a model price that a deterministic pass also found.
            if price not in allowed:
                continue
            name = normalize_item_name(raw_name)
            if not name:
                continue
            key = (name, price)
            if key in seen:
                continue
            seen.add(key)
            items.append({"item": name, "price_vnd": price, "source": "llm"})

    if items:
        return items
    return heuristic_priced_items(text)
