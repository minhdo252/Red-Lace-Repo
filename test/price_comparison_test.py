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
import time

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

    # --- EDGE: rare/niche dishes unlikely in seeded DB -> should trigger Gemini fallback ---
    ("bánh cuốn Phủ Lý", None),          # fresh name
    ("bún đậu mắm tôm thập cẩm", 250000), # fresh name
    ("phở cuốn Ngũ Xã", None),            # fresh name
    ("bánh tôm Hồ Tây", None),            # fresh name

    # --- EDGE: misspellings / missing diacritics ---
    ("xoi xeo", None),                      # fresh name
    ("banh mi pate", 60000),                # fresh name

    # --- EDGE: very cheap items (sanity floor test) ---
    ("trà râu ngô", None),                  # fresh name, testing portion size rule
    ("trà chanh", None),                    # fresh name

    # --- EDGE: expensive items ---
    ("tôm hùm hấp bia", 1500000),           # fresh name, testing exact match rule
    ("cua hoàng đế hấp", None),             # fresh name, testing exact match rule

    # --- EDGE: non-food / service items ---
    ("vé xe buýt 2 tầng", 300000),          # fresh name
    ("vé tham quan Hoàng Thành", 30000),    # fresh name, testing ticket rule

    # --- EDGE: ambiguous / compound names ---
    ("mì", None),                           # fresh name, generic
    ("nước ép", None),                      # fresh name, generic
    ("thập cẩm", None),                     # fresh name, modifier

    # --- NEW EDGE: Trendy / Viral street foods ---
    ("lạp xưởng nướng đá", None),           # trendy street food
    ("bánh đồng xu phô mai", None),         # viral snack
    ("trà sữa nướng", None),                # specific milk tea type
    ("gà ủ muối hoa tiêu", 250000),         # whole chicken dish

    # --- NEW EDGE: Regional dishes in Hanoi ---
    ("hủ tiếu nam vang", None),             # southern dish sold in Hanoi
    ("mì quảng ếch", None),                 # central dish sold in Hanoi

    # --- NEW EDGE: Branded items / specific cuts ---
    ("bia heineken chai", 25000),           # branded drink
    ("nước ngọt coca cola", None),          # branded drink
    ("lõi rùa bò", None),                   # specific premium beef cut
]



def _print_result(result: dict, elapsed_s: float) -> None:
    print(f"\n=== {result['item']!r}  ({result['region']}/{result['category']}) === [{elapsed_s:.3f}s]")
    print(f"  matched          : {result['matched']}")
    print(f"  neighbors_used   : {result['neighbors_used']}")
    print(f"  matched_item_names: {result['matched_item_names']!r}")
    print(f"  top_similarity   : {result['top_similarity']}")
    print(f"  reference_source : {result.get('reference_source', '—')}")
    print(f"  elapsed          : {elapsed_s:.3f}s")

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
        timings = []
        total_start = time.perf_counter()

        for item, observed_price in SCENARIOS:
            t0 = time.perf_counter()
            result = await compare_price(
                item,
                region=REGION,
                category=CATEGORY,
                observed_price=observed_price,
            )
            elapsed = time.perf_counter() - t0
            _print_result(result, elapsed)
            results.append(result)
            timings.append(elapsed)

        total_elapsed = time.perf_counter() - total_start

        print("\n\n=== Summary (mean-of-top-K reference price per query) ===")
        for result, elapsed in zip(results, timings):
            obs = f"{result['observed_price']:,} VND" if "observed_price" in result else "—"
            ref = (
                f"{result['reference_price']:>8,} VND"
                if result["reference_price"] is not None
                else f"{'—':>12}"
            )
            status = "matched " if result["matched"] else "no-match"
            src = result.get('reference_source', '—')
            print(
                f"  {status}  sim={result['top_similarity']:<5} k={result['neighbors_used']} "
                f"ref={ref}  obs={obs:>12}  src={src:<10} "
                f"t={elapsed:.3f}s  {result['item']!r}"
            )
        print(f"\n  Total elapsed: {total_elapsed:.3f}s")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
