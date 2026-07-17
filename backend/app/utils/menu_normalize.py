"""
menu_normalize.py
------------------
Shared noise-reduction layer for crawled ShopeeFood menu items, used by both
crawl_menu_dom_explorer.py (single-restaurant exploration) and
crawl_shopeefood_full.py (full-batch crawler).

Strips marketing/promo text glued onto a real item's name (combo, flash
sale, khuyến mãi, % off, ...) in place, without dropping the rest of the
name (quantities, item text, etc. are left untouched).

Run standalone for a quick regex sanity check:
    python backend/app/agent/menu_normalize.py
"""

from __future__ import annotations

import math
import re

# Vietnamese food-delivery marketing words/phrases to strip. Deliberately
# excludes common descriptive words ("mới", "hot", "new") that are too
# likely to be part of a genuine dish name (e.g. "bún mới") — only
# unambiguous promo phrasing is targeted, to avoid corrupting real names.
_RE_NOISE_WORDS = re.compile(
    r'\b(?:'
    r'combo|flasale|flash\s*sale|super\s*sale|mega\s*sale|sale\s*sốc|giá\s*sốc|'
    r'giảm\s*giá|mã\s*giảm(?:\s*giá)?|khuyến\s*mãi|ưu\s*đãi|deal\s*sốc|'
    r'freeship|miễn\s*phí(?:\s*giao\s*hàng)?|mua\s*1\s*tặng\s*1|quà\s*tặng|tặng'
    r')\b',
    re.IGNORECASE | re.UNICODE,
)
_RE_PERCENT_OFF = re.compile(r'\b\d{1,3}\s*%')  # no trailing \b: '%' isn't a word char, so %<space> never satisfies \b
_RE_EXTRA_SPACE = re.compile(r'\s{2,}')
_RE_TRAILING_DASH_NOISE = re.compile(r'^[\s\-–—.,+&]+|[\s\-–—.,+&]+$')


def normalize_item_name(raw: str) -> str:
    """
    Strip marketing noise words from a dish name. Only the noise words
    themselves are removed — quantities and the rest of the name are left
    intact.

    Examples:
        "Combo 5 bánh gà thường"           -> "5 bánh gà thường"
        "Thịt xiên flasale"                -> "thịt xiên"
        "Nem chua rán -Khuyến mãi-"        -> "nem chua rán"
        "Mã giảm 11% Bún chả"              -> "bún chả"
        "Ly nước đá"                       -> "ly nước đá"
    """
    name = raw.strip()
    name = _RE_NOISE_WORDS.sub('', name)
    name = _RE_PERCENT_OFF.sub('', name)
    name = _RE_EXTRA_SPACE.sub(' ', name)
    name = _RE_TRAILING_DASH_NOISE.sub('', name)
    return name.strip().lower()


def is_empty_after_cleaning(clean_name: str) -> bool:
    """True if nothing meaningful survived cleaning (pure-noise entry)."""
    return len(clean_name) < 2


# ---------------------------------------------------------------------------
# Price parsing + price_references row shaping
# ---------------------------------------------------------------------------

def parse_price_vnd(raw: str) -> float | None:
    """
    Convert Vietnamese price strings to a float (VND).
    Examples: '45.000đ' -> 45000.0, '120,000' -> 120000.0
    When two prices are shown (original + discounted), takes the discounted
    (last) one. Returns None if not parseable.
    """
    if not raw:
        return None
    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    prices = []
    for line in lines:
        cleaned = line.replace("đ", "").replace("₫", "").replace(",", "").replace(".", "").strip()
        try:
            val = float(cleaned)
            if val > 0:
                prices.append(val)
        except ValueError:
            continue
    if not prices:
        return None
    return prices[-1] if len(prices) > 1 else prices[0]


def to_price_reference_row(item_name: str, price_vnd: float | None, region: str, category: str) -> dict:
    """Build a price_references-shaped dict (db/init.sql) from one cleaned item."""
    if price_vnd and price_vnd > 0:
        ln_price = math.log(price_vnd)
        return {
            "item_name": item_name,
            "region": region,
            "category": category,
            "price_vnd": price_vnd,
            "mu_post": ln_price,
            "tau_post": None,
            "sigma_data": 0.3,
            "n": 1,
            "sum_y": ln_price,
        }
    return {
        "item_name": item_name,
        "region": region,
        "category": category,
        "price_vnd": None,
        "mu_post": None,
        "tau_post": None,
        "sigma_data": 0.3,
        "n": 0,
        "sum_y": 0.0,
    }


if __name__ == "__main__":
    samples = [
        "Combo 5 bánh gà thường",
        "combo 10 nem chua rán + Khoai tây chiên",
        "Thịt xiên flasale",
        "Ly nước đá",
        "Nem chua rán -Khuyến mãi-",
        "Mã giảm 11% Bún chả",
        "Set 2 người ăn",
    ]
    for s in samples:
        print(f"{s!r:45} -> clean={normalize_item_name(s)!r}")
