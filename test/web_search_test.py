"""
web_search_test.py
------------------
Feature + fallback smoke test (with assertions) for the web-search stack:

  A. search_web core (app/utils/web_search.py) — 5–7 results, shape, clamping
  B. missing-key error handling (live-only contract)
  C. agent tool dispatch (app/agent/tools.py::call_tool "search_web")
  D. Qwen-VL extractor null-safety on empty input (no network)
  E. compare_price fallback outcomes: "local" (seeded) and "websearch"
     (non-seeded item -> web fallback -> deferred write-back to PG + Qdrant)

LIVE test — requires a running Postgres/Qdrant stack AND real keys
(TAVILY_API_KEY for search, QWEN_VL_API_KEY for extraction).
Section E WRITES to the DB. To keep the fallback path deterministic across
re-runs, it first deletes any prior source='websearch' rows (+ their Qdrant
points) for its test items, then re-derives them from scratch.

Run via Docker (bypass the seed-crawler gate with --no-deps):
    docker compose run --rm --no-deps -e PYTHONPATH=/app \\
        -v "$(pwd)/test:/app/test" \\
        --entrypoint python backend test/web_search_test.py
"""

import asyncio
import os
import sys

from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.db.postgres import close_pool, get_pool, init_pool
from app.db.qdrant import get_client

REGION = "Hanoi"
CATEGORY = "food"
WRITEBACK_POLL_SECONDS = 2.0
WRITEBACK_POLL_ATTEMPTS = 6

_failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"    [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _failures.append(msg)


def _valid_result(r: dict) -> bool:
    return all(k in r for k in ("title", "url", "content", "score"))


# ---------------------------------------------------------------------------
# A. search_web core
# ---------------------------------------------------------------------------
async def section_search_core() -> None:
    print("\n=== A. search_web core ===")
    from app.utils.web_search import MAX_RESULTS, MIN_RESULTS, search_web

    results = await search_web("phở bò", region=REGION)
    print(f"    default query -> {len(results)} results")
    check(MIN_RESULTS <= len(results) <= MAX_RESULTS, f"default returns {MIN_RESULTS}–{MAX_RESULTS} results")
    check(all(_valid_result(r) for r in results), "each result has title/url/content/score")

    high = await search_web("cà phê", region=REGION, max_results=50)
    check(len(high) <= MAX_RESULTS, f"max_results=50 clamped to <= {MAX_RESULTS} (got {len(high)})")

    low = await search_web("bánh mì", region=REGION, max_results=1)
    check(len(low) <= MAX_RESULTS, f"max_results=1 stays <= {MAX_RESULTS} (got {len(low)})")


# ---------------------------------------------------------------------------
# B. missing-key error handling
# ---------------------------------------------------------------------------
async def section_missing_key() -> None:
    print("\n=== B. missing TAVILY_API_KEY -> RuntimeError ===")
    from app.utils.web_search import search_web

    saved = os.environ.pop("TAVILY_API_KEY", None)
    try:
        raised = False
        try:
            await search_web("test")
        except RuntimeError:
            raised = True
        check(raised, "search_web raises RuntimeError when TAVILY_API_KEY is unset")
    finally:
        if saved is not None:
            os.environ["TAVILY_API_KEY"] = saved


# ---------------------------------------------------------------------------
# C. agent tool dispatch
# ---------------------------------------------------------------------------
async def section_agent_tool() -> None:
    print("\n=== C. agent tool dispatch (call_tool 'search_web') ===")
    from app.agent.tools import TOOL_SPECS, call_tool

    check("search_web" in {s["name"] for s in TOOL_SPECS}, "search_web is registered in TOOL_SPECS")

    res = await call_tool("search_web", {"query": "trà sữa", "region": REGION})
    check("results" in res and "count" in res, "call_tool returns {results, count}")
    check(1 <= res.get("count", 0) <= 7, f"count within 1–7 (got {res.get('count')})")

    err = await call_tool("definitely_not_a_tool", {})
    check("error" in err, "unknown tool name returns an {error} payload, not a crash")


# ---------------------------------------------------------------------------
# D. extractor null-safety (no network)
# ---------------------------------------------------------------------------
async def section_extractor_nullsafe() -> None:
    print("\n=== D. Qwen-VL extractor null-safety ===")
    from app.ai.qwen_vl import extract_price_from_web

    check(
        extract_price_from_web("x", REGION, CATEGORY, []) is None,
        "extract_price_from_web returns None on empty results (no guess, no network)",
    )


# ---------------------------------------------------------------------------
# E. compare_price fallback outcomes
# ---------------------------------------------------------------------------
async def _cleanup_websearch(item: str) -> None:
    """Delete any prior source='websearch' rows (+ Qdrant points) for `item`
    so the fallback is re-derived from scratch on every run."""
    pool = get_pool()
    qclient = get_client()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id FROM price_references WHERE item_name = $1 AND source = 'websearch'",
            item,
        )
        ids = [r["id"] for r in rows]
        if ids:
            await conn.execute("DELETE FROM price_references WHERE id = ANY($1::int[])", ids)
    if ids:
        await qclient.delete(collection_name="item_names", points_selector=ids)


async def _writeback_landed(item: str) -> tuple[bool, bool]:
    pool = get_pool()
    qclient = get_client()
    for _ in range(WRITEBACK_POLL_ATTEMPTS):
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM price_references "
                "WHERE item_name = $1 AND region = $2 AND source = 'websearch' "
                "ORDER BY id DESC LIMIT 1",
                item,
                REGION,
            )
        if row is not None:
            hits = (
                await qclient.query_points(
                    collection_name="item_names",
                    query_filter=Filter(
                        must=[FieldCondition(key="postgres_id", match=MatchValue(value=row["id"]))]
                    ),
                    limit=1,
                )
            ).points
            return True, len(hits) > 0
        await asyncio.sleep(WRITEBACK_POLL_SECONDS)
    return False, False


async def section_fallback() -> None:
    print("\n=== E. compare_price fallback outcomes ===")
    from app.modules.price_comparison import compare_price

    # F1 — seeded dish must resolve locally, fallback must NOT fire.
    local = await compare_price("bún chả", region=REGION, category=CATEGORY)
    print(f"    'bún chả' -> source={local.get('reference_source')!r} price={local.get('reference_price')!r}")
    check(local.get("reference_source") == "local", "seeded 'bún chả' resolves locally")

    # F2 — non-seeded dish must trigger the web fallback.
    item = "tteokbokki phô mai Hàn Quốc"
    await _cleanup_websearch(item)
    fb = await compare_price(item, region=REGION, category=CATEGORY, observed_price=500000)
    src = fb.get("reference_source")
    print(f"    {item!r} -> source={src!r} price={fb.get('reference_price')!r} url={fb.get('source_url')!r}")

    check(src != "local", f"{item!r} did not resolve locally (source={src!r})")
    check(src in {"websearch", "none"}, f"{item!r} produced a valid fallback outcome (got {src!r})")

    if src == "websearch":
        check(isinstance(fb.get("reference_price"), (int, float)) and fb["reference_price"] > 0,
              "websearch produced a positive reference_price")
        check(fb.get("matched") is True, "websearch result is marked matched=True")
        # observed 500k vs a web reference should trip the overpriced flag.
        check(fb.get("flag") is not None, "inflated observed_price trips the flag against the web reference")
        pg_ok, qdrant_ok = await _writeback_landed(item)
        check(pg_ok, "deferred write-back inserted a source='websearch' row")
        check(qdrant_ok, "deferred write-back upserted a matching Qdrant point")

        # F3 — after write-back, the SAME item should now resolve locally.
        again = await compare_price(item, region=REGION, category=CATEGORY)
        print(f"    re-query {item!r} -> source={again.get('reference_source')!r}")
        check(again.get("reference_source") == "local",
              "after write-back, the item is served locally (self-enriching)")
    else:
        print("    (web found no defensible price this run — write-back correctly skipped)")


async def main() -> None:
    await init_pool()
    try:
        await section_search_core()
        await section_missing_key()
        await section_agent_tool()
        await section_extractor_nullsafe()
        await section_fallback()
    finally:
        await close_pool()

    print("\n=== Summary ===")
    if _failures:
        print(f"  {len(_failures)} check(s) FAILED:")
        for msg in _failures:
            print(f"    - {msg}")
        sys.exit(1)
    print("  all checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
