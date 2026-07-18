"""
price_web_fallback_test.py
--------------------------
Smoke test WITH ASSERTIONS for the web-search fallback stage of
app/modules/price_comparison.py::compare_price (see
docs/superpowers/specs/2026-07-18-web-search-mcp-design.md).

Unlike price_comparison_test.py (read-only, print-only), this exercises the
NEW behaviour: when the local kNN over Qdrant item_names misses at the raised
MATCH_THRESHOLD (0.75), compare_price falls back to a live web search
(Tavily) + Qwen-VL price extraction, returns the web-derived reference price
to the caller IMMEDIATELY, and then persists it back to Postgres +
Qdrant on a deferred (fire-and-forget) task.

Contract under test (result dict from compare_price):
  - result["reference_source"] in {"local", "websearch", "none"}
      "local"     -> a comparable neighbour was found in the seeded DB
      "websearch" -> local miss, web fallback produced a price
      "none"      -> local miss AND web fallback found no defensible price
  - a "websearch" result carries a numeric reference_price and a source_url.
  - after the deferred write-back settles, a price_references row with
    source='websearch' exists for the queried item, and a matching Qdrant
    item_names point exists.

LIVE test — requires a running Postgres/Qdrant stack AND real keys:
  TAVILY_API_KEY (web search) and QWEN_VL_API_KEY (price extraction).
It also WRITES to the DB (that's the point). Re-running turns a previously
web-sourced item into a local hit on the next run — expected, per the
self-enriching design (accepted duplicate-row risk in the spec).

Prices are in VND. Python floats have no thousands separator: 45000, not 45.000.

Run via Docker (bypass the seed-crawler gate with --no-deps):
    docker compose run --rm --no-deps -e PYTHONPATH=/app \\
        -v "$(pwd)/test:/app/test" \\
        --entrypoint python backend test/price_web_fallback_test.py

Run locally (from backend/, so `app` resolves as a package):
    cd backend && PYTHONPATH=. python ../test/price_web_fallback_test.py
"""

import asyncio
import sys

from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.db.postgres import close_pool, get_pool, init_pool
from app.db.qdrant import get_client
from app.modules.price_comparison import compare_price

REGION = "Hanoi"
CATEGORY = "food"

# How long to wait for the deferred (fire-and-forget) write-back to land
# before checking Postgres/Qdrant. Poll rather than a single long sleep.
WRITEBACK_POLL_SECONDS = 2.0
WRITEBACK_POLL_ATTEMPTS = 6  # ~12s total budget

# --- collected pass/fail so the script exits non-zero on any failure --------
_failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"    [{status}] {msg}")
    if not cond:
        _failures.append(msg)


# ---------------------------------------------------------------------------
# Scenarios that MUST trigger the web fallback: real, web-searchable foods
# that are NOT in the ShopeeFood-Hanoi seed, so the local kNN misses at 0.75.
# ---------------------------------------------------------------------------
FALLBACK_ITEMS: list[str] = [
    "sushi cá hồi",          # Japanese — not in the Hanoi street-food seed
    "pizza hải sản",         # Italian — not seeded
    "mì cay Hàn Quốc",       # Korean — not seeded
]

# Controls that MUST stay local (seeded Hanoi dishes) — the fallback must NOT
# fire for these, or we've broken the fast path / lowered precision.
LOCAL_ITEMS: list[str] = [
    "bún chả",
    "phở bò tái",
]


async def _writeback_landed(item: str) -> tuple[bool, bool]:
    """Poll Postgres + Qdrant for the deferred write-back. Returns
    (pg_row_exists, qdrant_point_exists)."""
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


async def _run_fallback_case(item: str) -> None:
    print(f"\n=== FALLBACK expected: {item!r} ({REGION}/{CATEGORY}) ===")
    result = await compare_price(item, region=REGION, category=CATEGORY, observed_price=None)

    source = result.get("reference_source")
    print(f"    reference_source : {source!r}")
    print(f"    reference_price  : {result.get('reference_price')!r}")
    print(f"    source_url       : {result.get('source_url')!r}")

    check(source != "local", f"{item!r}: did NOT resolve locally (source={source!r})")
    check(
        source in {"websearch", "none"},
        f"{item!r}: reference_source is a valid fallback outcome (got {source!r})",
    )

    if source == "websearch":
        check(
            isinstance(result.get("reference_price"), (int, float))
            and result["reference_price"] > 0,
            f"{item!r}: websearch produced a positive reference_price",
        )
        check(bool(result.get("source_url")), f"{item!r}: websearch result carries a source_url")

        # Deferred write-back must eventually persist to BOTH stores.
        pg_ok, qdrant_ok = await _writeback_landed(item)
        check(pg_ok, f"{item!r}: price_references row with source='websearch' was written")
        check(qdrant_ok, f"{item!r}: matching Qdrant item_names point was upserted")
    else:
        print("    (web fallback found no defensible price — write-back correctly skipped)")


async def _run_local_case(item: str) -> None:
    print(f"\n=== LOCAL expected: {item!r} ({REGION}/{CATEGORY}) ===")
    result = await compare_price(item, region=REGION, category=CATEGORY, observed_price=None)
    source = result.get("reference_source")
    print(f"    reference_source : {source!r}")
    print(f"    reference_price  : {result.get('reference_price')!r}")
    check(source == "local", f"{item!r}: resolved from the seeded DB, not the web (got {source!r})")


async def main() -> None:
    await init_pool()
    try:
        for item in FALLBACK_ITEMS:
            await _run_fallback_case(item)
        for item in LOCAL_ITEMS:
            await _run_local_case(item)
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
