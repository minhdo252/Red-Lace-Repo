"""
price_comparison_test.py
------------------------
Manual smoke test (not pass/fail) for app/modules/price_comparison.py::
compare_price — the direct neighbor-price lookup. It runs the whole
function end to end and prints what a caller actually gets back: whether
any comparable neighbors were found, the mean of the nearest few dishes'
Postgres prices (the reference "fair" price), and — when an observed price
is supplied — how far above/below that reference it sits and whether that
trips the overpricing flag.

The SCENARIOS below exercise both outcomes:
  - likely-seeded Hanoi dishes            -> matched (top_similarity >= 0.6)
  - foreign-cuisine & nonsense strings    -> not matched (< 0.6, or no hits)
and each known dish is queried three ways: no observed price, a fair
observed price, and an inflated one (to trip the flag).

Prices are in VND. Note Python floats have no thousands separator: a fair
bún chả is 45000, not 45.000 (which is the float 45.0).

Read-only: compare_price only queries Postgres/Qdrant. Never writes.

Run via Docker (same env as the backend service; PYTHONPATH=/app matches
the other test/ scripts):
    docker compose run --rm -e PYTHONPATH=/app -v "$(pwd)/test:/app/test" \\
        --entrypoint python backend test/price_comparison_test.py

Run locally (from backend/, so `app` resolves as a package):
    cd backend && PYTHONPATH=. python ../test/price_comparison_test.py
"""

import asyncio

from app.db.postgres import close_pool, init_pool
from app.modules.price_comparison import compare_price

REGION = "Hanoi"
CATEGORY = "food"

# (item, observed_price) — observed_price=None means "just fetch the neighbor's
# reference price"; a number also asks "is this specific price a rip-off?". The
# trailing comment is the *expected* outcome, so a mismatch at runtime is
# immediately visible against MATCH_THRESHOLD in price_comparison.py.
SCENARIOS: list[tuple[str, float | None]] = [
    # --- likely matched: exact/known dishes, priced fair then gouged ---
    ("bún chả", None),          # expect: matched
    ("bún chả", 45000),         # fair-ish -> small diff, no flag
    ("bún chả", 150000),        # tourist markup -> large diff, flagged
    ("phở bò tái", None),       # expect: matched
    ("bún chả Hà Nội đặc biệt", 90000),   # near-variant -> matched to nearest neighbor
    ("phở bò chín nạm", None),             # near-variant -> matched to nearest neighbor

    # --- likely not matched: foreign cuisine + nonsense, no close neighbors ---
    ("sushi cá hồi", 200000),    # expect: not matched
    ("pizza hải sản", None),     # expect: not matched
    ("máy bay phản lực", None),  # nonsense -> not matched (or no hits)
]


def _print_result(result: dict) -> None:
    print(f"\n=== {result['item']!r}  ({result['region']}/{result['category']}) ===")
    print(f"  matched          : {result['matched']}")
    print(f"  neighbors_used   : {result['neighbors_used']}")
    print(f"  matched_item_names: {result['matched_item_names']!r}")
    print(f"  top_similarity   : {result['top_similarity']}")

    if result["reference_price"] is not None:
        print(f"  reference_price  : {result['reference_price']:,} VND (mean of {result['neighbors_used']})")
    else:
        print("  reference_price  : — (no comparable neighbor)")

    if "observed_price" in result:
        print(f"  observed_price   : {result['observed_price']:,} VND")
        if "price_diff_vnd" in result:
            print(f"  price_diff       : {result['price_diff_vnd']:+,} VND ({result['price_diff_pct']:+}%)")
        flag = result["flag"]
        print(f"  flag             : {flag if flag else '— (within reference range)'}")


async def main() -> None:
    await init_pool()
    try:
        results = []
        for item, observed_price in SCENARIOS:
            result = await compare_price(
                item,
                region=REGION,
                category=CATEGORY,
                observed_price=observed_price,
            )
            _print_result(result)
            results.append(result)

        print("\n\n=== Summary (mean-of-top-K reference price per query) ===")
        for result in results:
            obs = f"{result['observed_price']:,} VND" if "observed_price" in result else "—"
            ref = (
                f"{result['reference_price']:>8,} VND"
                if result["reference_price"] is not None
                else f"{'—':>12}"
            )
            status = "matched " if result["matched"] else "no-match"
            print(
                f"  {status}  sim={result['top_similarity']:<5} k={result['neighbors_used']} "
                f"ref={ref}  obs={obs:>12}  {result['item']!r}"
            )
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
