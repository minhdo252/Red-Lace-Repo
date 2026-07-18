"""
price_comparison.py
--------------------
Direct neighbor-price comparison for a dish name. Embeds the name
(vn_embedding.py, query side), kNN's it against Qdrant's item_names
collection, applies a head-phrase gate to filter out neighbors that share
only a modifier or a random keyword (e.g. "pizza hải sản" scoring high
against "cơm trộn hải sản" purely on the shared word), then aggregates
the surviving neighbors' Postgres prices as a similarity-weighted mean
to form a reference "fair" price.

Two-stage gating (kept simple for MVP explainability):

  1. Similarity gate: cosine similarity >= MATCH_THRESHOLD. Cheap, coarse.
     A single scalar isn't discriminative enough on its own — the embedding
     over-weights shared modifiers ("đặc biệt", "hải sản", "combo") and
     lets cross-category neighbors ride in on top-K.

  2. Head-phrase gate: the leading dish-type phrase of the query and the
     candidate must be prefix-compatible. "phở bò" vs "phở gà" -> mismatch;
     "bún chả" vs "bánh mì" -> mismatch; "pizza" vs "cơm trộn" -> mismatch.
     A vague query "phở" is still allowed to match "phở bò trộn" because
     one head is a token prefix of the other.

The reference price is a similarity-weighted mean rather than a plain
mean, so a loose neighbor doesn't drag the estimate as much as a tight
one. `reference_price_range` (min–max of the neighbors' raw prices) is
included so a human reviewer can see how tight the estimate actually is.

Read-only: only queries Qdrant and Postgres, never writes.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from typing import Any

logger = logging.getLogger(__name__)

from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.ai.vn_embedding import embed_query_texts
from app.db.postgres import get_pool
from app.db.qdrant import get_client
from app.modules.price_web_fallback import web_fallback_price

MATCH_THRESHOLD = 0.75   # a hit must clear this to count as a comparable neighbor
MARKUP_THRESHOLD = 0.30  # observed price this fraction above the reference -> flag as overpriced
NEIGHBOR_LIMIT = 10      # kNN candidates pulled per query (widened; head-phrase gate will trim)
COMPARE_K = 3            # aggregate the nearest COMPARE_K comparable neighbors' price_vnd


# ----- Head-phrase extraction -------------------------------------------------
# A dish name in Vietnamese food data usually starts with a category word.
# When that category word commonly forms a 2-word compound ("bánh mì",
# "cà phê", "bún chả"), the head phrase is 2 tokens; otherwise 1 token.
# The set below is intentionally coarse — it only exists to catch obvious
# cross-category false positives, not to build a full taxonomy.
_COMPOUND_STARTERS: frozenset[str] = frozenset({
    # rice, noodles, staples
    "cơm", "bún", "phở", "miến", "mì", "mỳ", "xôi", "cháo",
    # bread & wraps
    "bánh",
    # small dishes / meat cuts
    "chả", "nem", "chân", "cánh", "đùi", "má", "sườn", "ba", "lòng",
    "lưỡi", "tim", "vai", "bắp", "nầm",
    # tubers / veg
    "khoai",
    # animals commonly used as a category head
    "cá", "gà", "bò", "vịt", "tôm", "ngan", "hàu", "ngao", "ốc", "lươn",
    # drinks & drink compounds
    "cà", "trà", "sữa", "sinh", "nước", "hồng", "ô", "kim", "ca",
    # egg / other
    "trứng",
    # foreign / other dishes that take a vietnamese modifier
    "hot", "bít",
})

# Words that appear before the real dish name — quantity, packaging, ordinals.
_QUANTITY_LEADS: frozenset[str] = frozenset({
    "combo", "suất", "phần", "hộp", "set", "gói", "ly", "cốc", "chai",
    "cái", "chiếc", "đĩa", "bát", "tô", "khay",
})

_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")
_NUM_RE = re.compile(r"^\d+[a-zà-ỹ]*$", flags=re.IGNORECASE)  # 5, 10, 5c, 10c...


def _normalize(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, NFC unicode. No
    diacritic stripping — "bò" and "bô" must stay distinct."""
    s = unicodedata.normalize("NFC", name).lower()
    s = _PUNCT_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()


def head_phrase(name: str) -> str:
    """Leading dish-type phrase of a name — 1 or 2 tokens depending on
    whether the first content token is a known compound starter.

    Leading quantity words ("combo", "suất"...) and pure numbers ("5", "10c")
    are skipped, so "combo 5 bánh gà thường" -> "bánh gà"."""
    tokens = _normalize(name).split()
    i = 0
    while i < len(tokens) and (tokens[i] in _QUANTITY_LEADS or _NUM_RE.match(tokens[i])):
        i += 1
    tokens = tokens[i:]
    if not tokens:
        return ""
    if tokens[0] in _COMPOUND_STARTERS and len(tokens) >= 2:
        return f"{tokens[0]} {tokens[1]}"
    return tokens[0]


def _heads_compatible(query_head: str, cand_head: str) -> bool:
    """Prefix-compatible: one head is a token prefix of the other. Lets a
    vague query "phở" match "phở bò trộn" while still rejecting "phở gà"
    when the query is the more specific "phở bò"."""
    if not query_head or not cand_head:
        return False
    q, c = query_head.split(), cand_head.split()
    n = min(len(q), len(c))
    return q[:n] == c[:n]


# ----- Postgres access --------------------------------------------------------

async def _fetch_prices(ids: list[int]) -> dict[int, Any]:
    """Batch-fetch price_references rows (name + raw price) by id, keyed by id."""
    if not ids:
        return {}
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, item_name, price_vnd FROM price_references WHERE id = ANY($1::int[])",
            ids,
        )
    return {row["id"]: row for row in rows}


# ----- Public API -------------------------------------------------------------

async def compare_price(
    item: str,
    region: str,
    category: str = "food",
    observed_price: float | None = None,
) -> dict[str, Any]:
    """Compare `observed_price` against the similarity-weighted mean price_vnd
    of the nearest comparable dishes in Postgres — see module docstring for
    the gating and aggregation logic."""
    # Offload the blocking HTTP request to FPT Cloud embedding API to a background thread
    # so we don't stall the async event loop if the API hangs.
    try:
        vector = (await asyncio.to_thread(embed_query_texts, [item]))[0]
        qclient = get_client()
        hits = (
            await qclient.query_points(
                collection_name="item_names",
                query=vector,
                query_filter=Filter(
                    must=[
                        FieldCondition(key="region", match=MatchValue(value=region)),
                        FieldCondition(key="category", match=MatchValue(value=category)),
                    ]
                ),
                limit=NEIGHBOR_LIMIT,
            )
        ).points
    except Exception as e:
        # If the embedding times out or Qdrant fails, we can't do local kNN.
        # Just set hits to empty, which naturally falls through to the websearch fallback.
        logger.warning("Embedding/Qdrant failed for %r, forcing web fallback. Error: %s", item, e)
        hits = []

    top_score = hits[0].score if hits else 0.0

    # Stage 1 — similarity gate (Qdrant already returns hits sorted by score).
    sim_pass = [h for h in hits if h.score >= MATCH_THRESHOLD]

    # Need Postgres rows to gate on the actual item_name text.
    rows_by_id = await _fetch_prices([h.payload["postgres_id"] for h in sim_pass])

    # Stage 2 — head-phrase gate. Keep the nearest COMPARE_K that survive.
    query_head = head_phrase(item)
    gated: list[tuple[Any, dict]] = []  # (hit, pg_row)
    for h in sim_pass:
        row = rows_by_id.get(h.payload["postgres_id"])
        if row is None or row["price_vnd"] is None:
            continue
        if query_head and not _heads_compatible(query_head, head_phrase(row["item_name"])):
            continue
        gated.append((h, row))
        if len(gated) >= COMPARE_K:
            break

    neighbor_names = [row["item_name"] for _, row in gated]
    neighbor_prices = [float(row["price_vnd"]) for _, row in gated]
    neighbor_sims = [float(h.score) for h, _ in gated]

    # Similarity-weighted mean: a loose neighbor pulls less weight than a
    # tight one, so one accidental match doesn't dominate the K=3 aggregate.
    if neighbor_prices:
        w_sum = sum(neighbor_sims)
        reference_price: float | None = (
            sum(w * p for w, p in zip(neighbor_sims, neighbor_prices)) / w_sum
            if w_sum > 0
            else sum(neighbor_prices) / len(neighbor_prices)
        )
        reference_range: tuple[float, float] | None = (
            min(neighbor_prices),
            max(neighbor_prices),
        )
        reference_source = "local"
    else:
        reference_price = None
        reference_range = None
        reference_source = "none"

    # Web-search fallback: no confident local comparable -> derive a reference
    # price from a live web search. Returns to the caller immediately; the
    # write-back into Postgres/Qdrant happens on a deferred task (so the next
    # lookup of this item is a local hit). See price_web_fallback.py.
    source_url: str | None = None
    if reference_price is None:
        fallback = await web_fallback_price(item, region, category)
        if fallback is not None:
            reference_price = fallback["reference_price"]
            reference_range = None
            reference_source = "websearch"
            source_url = fallback.get("source_url")

    result: dict[str, Any] = {
        "item": item,
        "region": region,
        "category": category,
        "query_head_phrase": query_head,
        "top_similarity": round(top_score, 3),
        "matched": reference_price is not None,
        # where the reference came from: "local" | "websearch" | "none"
        "reference_source": reference_source,
        "source_url": source_url,
        "neighbors_used": len(gated),
        "matched_item_names": neighbor_names,
        "matched_item_similarities": [round(s, 3) for s in neighbor_sims],
        # similarity-weighted mean of the gated neighbors' Postgres prices
        # (or the web-derived reference when reference_source == "websearch")
        "reference_price": round(reference_price) if reference_price is not None else None,
        "reference_price_range": (
            [round(reference_range[0]), round(reference_range[1])]
            if reference_range is not None
            else None
        ),
        # kept for backward compatibility with downstream consumers
        "fair_price_estimate": round(reference_price) if reference_price is not None else None,
    }

    if observed_price is not None:
        result["observed_price"] = observed_price
        if reference_price is not None:
            diff = observed_price - reference_price
            diff_pct = diff / reference_price * 100
            result["price_diff_vnd"] = round(diff)
            result["price_diff_pct"] = round(diff_pct, 1)
            basis = (
                f"tìm kiếm web giá {reference_price:,.0f} VND"
                if reference_source == "websearch"
                else f"trung bình có trọng số {len(gated)} món gần nhất giá {reference_price:,.0f} VND"
            )
            result["flag"] = (
                f"cao hơn giá tham chiếu {diff_pct:.0f}% — {basis}"
                if diff_pct > MARKUP_THRESHOLD * 100
                else None
            )
        else:
            # no comparable neighbor and no web price -> can't judge fairness
            result["flag"] = None

    return result