"""Deterministic price-check intent detector for typed chat (chat-input-routing).

Recognizes when a typed message is really a price question about a menu item, so
the text route can answer it via Module 2.1 (compare_price) directly — no chatbot
LLM, no image OCR:

  - item + stated price:      "bún đậu 200k", "cơm rang 100k có đắt không"
  - price question, no price:  "how much is bún đậu?", "giá bún đậu bao nhiêu?"

Detection is pure regex/heuristics (no model call). The extracted item keeps its
Vietnamese diacritics so compare_price's embedding stays accurate.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.modules.translation import extract_normalized_prices_vnd


@dataclass
class PriceIntent:
    item: str
    observed_price: int | None  # None => a "how much" question with no stated price


# Price-question cues, matched on diacritic-folded lowercase text.
_CUE_RE = re.compile(
    r"how much|expensive|rip[\s-]?off|overpriced|worth it|"
    r"gia bao nhieu|bao nhieu|may tien|bao tien|dat khong|co dat|mac khong|co mac",
)

# Strip visible price tokens ("200k", "100.000đ", "1 trieu") for item extraction.
_PRICE_STRIP_RE = re.compile(
    r"\d[\d.,]*\s*(?:k|nghìn|nghin|ngàn|ngan|triệu|trieu|tr|đồng|dong|đ|vnd)\b"
    r"|\d[\d.,]{2,}\d"
    r"|\b\d{2,}\b",
    re.IGNORECASE,
)

# Strip cue phrases (diacritic + ASCII forms) for item extraction.
_CUE_STRIP_RE = re.compile(
    r"(?:có\s+)?(?:đắt|dat|mắc|mac)\s+(?:không|khong)"
    r"|gi[aá]\s+bao\s+nhi[êe]u"
    r"|bao\s+nhi[êe]u(?:\s+ti[eề]n)?"
    r"|m[aấ]y\s+ti[eề]n"
    r"|how\s+much(?:\s+(?:is|does|are|for))?"
    r"|is\s+(?:it|this|that)\s+expensive"
    r"|(?:too\s+)?expensive"
    r"|worth\s+it|rip[\s-]?off|overpriced"
    r"|gi[aá]\b",
    re.IGNORECASE,
)

# Filler words trimmed from the ENDS of the item phrase (folded/ASCII forms).
_EDGE_FILLERS = {
    "cho", "toi", "minh", "hoi", "xem", "giup", "oi", "cai", "nay", "mot",
    "phan", "the", "a", "an", "is", "of", "for", "me", "please", "nhe",
    "vay", "khong", "do", "does", "this", "that",
}


def _fold(text: str) -> str:
    text = text.lower().replace("đ", "d")
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def _extract_item(text: str) -> str:
    s = _PRICE_STRIP_RE.sub(" ", text)
    s = _CUE_STRIP_RE.sub(" ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = s.split()
    while tokens and _fold(tokens[0]) in _EDGE_FILLERS:
        tokens.pop(0)
    while tokens and _fold(tokens[-1]) in _EDGE_FILLERS:
        tokens.pop()
    return " ".join(tokens)


def detect_price_intent(text: str) -> PriceIntent | None:
    """Return a PriceIntent when `text` reads as a price question about an item,
    else None (so the caller falls through to the normal chatbot).

    Fires on: (a) an item plus a stated price when a price cue is present or the
    item phrase is short (<= 5 words), or (b) a price cue with no stated price and
    a short item phrase ("how much is X")."""
    if not text or not text.strip():
        return None

    prices = extract_normalized_prices_vnd(text)
    has_cue = bool(_CUE_RE.search(_fold(text)))
    item = _extract_item(text)

    if not item or not re.search(r"[a-zà-ỹ]", item.lower()):
        return None

    word_count = len(item.split())
    if prices:
        if has_cue or word_count <= 5:
            return PriceIntent(item=item, observed_price=prices[0])
        return None
    if has_cue and word_count <= 5:
        return PriceIntent(item=item, observed_price=None)
    return None
