"""
price_web_fallback.py
---------------------
Web-search fallback for compare_price (app/modules/price_comparison.py).

When the local kNN over Qdrant's item_names misses at the raised
MATCH_THRESHOLD, this module derives a reference price from a live web
search instead:

  1. gemini_search_price(item, region)    -> Gemini 2.0 Flash + Google Search
                                             returns Qwen VL-shaped dict
  2. return that reference price to the caller IMMEDIATELY
  3. persist the row to Postgres + Qdrant on a DEFERRED (fire-and-forget)
     task, so the response latency the chatbot sees is only one Gemini
     call — not the embed + two DB writes.

Step 1 is the critical path (awaited). Step 3 runs detached: the DB
self-enriches so the next lookup of the same item is a local hit, but the
current caller doesn't wait for it.

The Gemini search replaces the earlier two-step Tavily→Qwen-VL pipeline.
The embedding for write-back still uses the blocking OpenAI SDK, so it's
pushed to a worker thread (asyncio.to_thread) to avoid stalling the event
loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from qdrant_client.models import PointStruct

from app.ai.vn_embedding import embed_passage_texts
from app.db.postgres import get_pool
from app.db.qdrant import get_client
from app.utils.gemini_search import gemini_search_price

logger = logging.getLogger(__name__)

# Strong references to in-flight write-back tasks. Without this, asyncio only
# keeps a weak reference and the task can be garbage-collected mid-write.
_writeback_tasks: set[asyncio.Task] = set()


async def web_fallback_price(item: str, region: str, category: str) -> dict[str, Any] | None:
    """Derive a reference price for ``item`` from a live web search.

    Returns ``{reference_price, source_url, reference_item_name}`` when a
    defensible price is found (and schedules the deferred write-back), or
    ``None`` when the web search / extraction yields no usable price.
    """
    # Single Gemini call with Google Search — replaces the earlier
    # Tavily search + Qwen-VL extraction two-step.
    result = await gemini_search_price(item, region=region)

    # The Gemini module returns Qwen VL-shaped output: check price_vnd.
    if result.get("uncertain") or not result.get("price_vnd"):
        return None

    price_vnd = result["price_vnd"]
    if not isinstance(price_vnd, (int, float)) or price_vnd <= 0:
        return None

    # Build the row dict for the deferred write-back (same shape the
    # _writeback function expects: item_name, region, category, price_vnd,
    # source_url).
    source_url = None
    notes = result.get("notes", "")
    # Try to extract a URL from the notes field if Gemini included one.
    if notes:
        import re
        url_match = re.search(r"https?://\S+", notes)
        if url_match:
            source_url = url_match.group().rstrip(".,;)")

    writeback_row = {
        "item_name": result.get("name_raw") or item,
        "region": region,
        "category": category,
        "price_vnd": float(price_vnd),
        "source_url": source_url,
    }

    _schedule_writeback(writeback_row)

    return {
        "reference_price": float(price_vnd),
        "source_url": source_url,
        "reference_item_name": result.get("name_raw") or item,
    }


def _schedule_writeback(row: dict[str, Any]) -> None:
    """Fire-and-forget the persistence so it never blocks the response."""
    task = asyncio.create_task(_writeback(row))
    _writeback_tasks.add(task)
    task.add_done_callback(_on_writeback_done)


def _on_writeback_done(task: asyncio.Task) -> None:
    _writeback_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        # A detached task's failure can't propagate to the request — log it so
        # a broken write-back is visible instead of silently swallowed.
        logger.error("web-fallback write-back failed: %s", exc, exc_info=exc)


async def _writeback(row: dict[str, Any]) -> None:
    """Persist a web-sourced price into Postgres (price_references, tagged
    source='websearch') and Qdrant (item_names), so future lookups hit it
    locally. Runs detached from the request."""
    vector = (await asyncio.to_thread(embed_passage_texts, [row["item_name"]]))[0]

    pool = get_pool()
    async with pool.acquire() as conn:
        new_id = await conn.fetchval(
            "INSERT INTO price_references "
            "(item_name, region, category, price_vnd, source, source_url) "
            "VALUES ($1, $2, $3, $4, 'websearch', $5) RETURNING id",
            row["item_name"],
            row["region"],
            row["category"],
            row["price_vnd"],
            row.get("source_url"),
        )

    qclient = get_client()
    await qclient.upsert(
        collection_name="item_names",
        points=[
            PointStruct(
                id=new_id,
                vector=vector,
                payload={
                    "region": row["region"],
                    "category": row["category"],
                    "postgres_id": new_id,
                },
            )
        ],
    )
