"""
menu_price_pipeline.py
----------------------
End-to-end "conductor" that turns a photographed menu into saved
price_references observations, wiring together four existing pieces in one
linear flow:

  1. OCR      app/ai/qwen_vl.py::ai_detect_menu
              image -> Qwen2.5-VL -> structured menu items (the "json"),
              already split into confident `ready_rows` (uncertain=False and
              a usable price) and `needs_review` (everything else).
  2. Compare  app/modules/price_comparison.py::compare_price
              each confident dish name is embedded (vn_embedding, query side)
              and kNN'd against Qdrant `item_names`, then compared against the
              nearest comparable Postgres neighbors' prices.
  3. Filter   keep ONLY matched comparisons — dishes the region already has
              price data for. (`save_which` can flip this; see below.)
  4. Save     app/utils/to_postgree.py
              the kept items are shaped into price_references rows (n=1 new
              observations, sigma_data derived from the live table) and
              INSERTed.

Design notes / gotchas this conductor reconciles:

  * Uncertain OCR reads never leave qwen_vl's `needs_review`, so a misread
    price can't reach the pricing table without a human — this pipeline only
    ever touches `ready_rows`.
  * `compare_price` is async (asyncpg) but `to_postgree` is sync (psycopg2),
    so stage 4 opens its own psycopg2 connection while stages 2-3 use the
    shared asyncpg pool. Fine for a one-shot batch tool; don't call this from
    inside a request handler untimed.
  * `region`/`category` MUST be the values price_references actually uses
    (e.g. "Hanoi"/"food"), NOT qwen_vl's finer KNOWN_REGIONS taxonomy
    ("Hanoi/Old Quarter") — the same string filters Qdrant, so a mismatch
    silently yields zero matches. That's why strict_region defaults False.
  * Plain INSERT, no merge: saving *matched* items appends a second n=1 row
    next to the reference they matched rather than fusing into it. True
    fusion is app/modules/pricing.py::record_observation (needs the Qdrant
    match first) and is intentionally out of scope here.

Requires QWEN_VL_API_KEY + VN_EMBEDDING_API_KEY (external APIs) and a
reachable Postgres + Qdrant.

Run standalone (from backend/, so `app` resolves as a package):
    cd backend && PYTHONPATH=. python -m app.tools.menu_price_pipeline "../test/menu 1.jpg" Hanoi

Or via Docker (skip the seed-crawler startup gate with --no-deps):
    docker compose run --rm --no-deps \\
        -e QWEN_VL_API_KEY=... -e VN_EMBEDDING_API_KEY=... \\
        -v "$(pwd)/test:/app/test" --entrypoint python backend \\
        -m app.tools.menu_price_pipeline "test/menu 1.jpg" Hanoi
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import psycopg2

from app.ai.qwen_vl import PriceReferenceRow, ai_detect_menu
from app.config import settings
from app.db.postgres import close_pool, init_pool
from app.modules.price_comparison import compare_price
from app.utils.menu_normalize import normalize_item_name
from app.utils.to_postgree import (
    push_ready_rows_to_postgres,
    vlm_ready_items_to_postgres_rows,
)


def _ready_row_to_vlm_item(row: PriceReferenceRow) -> dict[str, Any]:
    """Shape a qwen_vl PriceReferenceRow (already confident + priced) into the
    VLM-item dict to_postgree expects. price_vnd passes straight through
    (parse_price_vnd_fn=None downstream); to_postgree normalizes the name."""
    return {
        "name_raw": row.item_name,
        "price_raw": str(int(row.price_vnd)),
        "price_vnd": row.price_vnd,
        "uncertain": False,
        "notes": row.ocr_notes,
    }


async def run_pipeline(
    image_path: str,
    region: str,
    category: str = "food",
    save: bool = True,
    save_which: str = "matched",  # "matched" | "unmatched" | "all"
    strict_region: bool = False,
    dsn: str | None = None,
) -> dict[str, Any]:
    """Run the four-stage menu -> price_references pipeline and return a
    report. Assumes the asyncpg pool is already initialized (compare_price
    needs it); the CLI main() below handles init/close."""

    # --- Stage 1: OCR the menu photo -------------------------------------
    extraction = ai_detect_menu(
        image_path, region=region, category=category, strict_region=strict_region
    )
    if extraction.parse_error:
        return {
            "image": image_path,
            "region": region,
            "category": category,
            "ocr_parse_error": extraction.parse_error,
            "raw_response": extraction.raw_response,
        }

    # --- Stage 2+3: compare each confident dish; keep matched ------------
    # Keep (comparison, source_row) paired so two dishes that normalize to the
    # same name can't collide when we go to save.
    matched: list[tuple[dict[str, Any], PriceReferenceRow]] = []
    unmatched: list[tuple[dict[str, Any], PriceReferenceRow]] = []
    for row in extraction.ready_rows:
        query_name = normalize_item_name(row.item_name)
        comparison = await compare_price(
            query_name,
            region=region,
            category=category,
            observed_price=float(row.price_vnd),
        )
        (matched if comparison["matched"] else unmatched).append((comparison, row))

    # --- Stage 4: save via to_postgree -----------------------------------
    to_save = {"matched": matched, "unmatched": unmatched, "all": matched + unmatched}[save_which]

    saved_rows = 0
    save_blocked: list[dict[str, Any]] = []
    if save and to_save:
        vlm_items = [_ready_row_to_vlm_item(row) for _, row in to_save]
        conn = psycopg2.connect(dsn or settings.postgres_dsn)
        try:
            prepared = vlm_ready_items_to_postgres_rows(
                vlm_items,
                conn,
                region=region,
                category=category,
                normalize_item_name_fn=normalize_item_name,
                parse_price_vnd_fn=None,  # price_vnd already clean from OCR
            )
            saved_rows = push_ready_rows_to_postgres(prepared["ready_rows"], conn)
            save_blocked = prepared["needs_review"]
        finally:
            conn.close()

    return {
        "image": image_path,
        "region": region,
        "category": category,
        "ocr": {
            "ready": len(extraction.ready_rows),
            "needs_review": len(extraction.needs_review),
            "unreadable_regions": extraction.unreadable_regions,
        },
        "compared": len(extraction.ready_rows),
        "matched": [c for c, _ in matched],  # only-matched comparisons, per spec
        "unmatched_count": len(unmatched),
        "save_which": save_which,
        "saved_rows": saved_rows,
        "save_blocked_at_floor": save_blocked,
        "ocr_needs_review": [
            {"name_raw": it.name_raw, "price_raw": it.price_raw,
             "uncertain": it.uncertain, "notes": it.notes}
            for it in extraction.needs_review
        ],
    }


def _print_report(report: dict[str, Any]) -> None:
    if report.get("ocr_parse_error"):
        print(f"[OCR PARSE ERROR] {report['ocr_parse_error']}")
        print("Raw response:", report.get("raw_response"))
        return

    ocr = report["ocr"]
    print("=" * 64)
    print(f"  MENU -> PRICE PIPELINE   ({report['region']}/{report['category']})")
    print(f"  image: {report['image']}")
    print("=" * 64)
    print(f"OCR      : {ocr['ready']} confident, {ocr['needs_review']} need review, "
          f"{ocr['unreadable_regions']} unreadable region(s)")
    print(f"Compared : {report['compared']} confident dishes -> "
          f"{len(report['matched'])} matched, {report['unmatched_count']} unmatched\n")

    for c in report["matched"]:
        print(f"  ✓ {c['item']!r}")
        print(f"      observed  : {c.get('observed_price', 0):,.0f} VND")
        if c.get("reference_price") is not None:
            print(f"      reference : {c['reference_price']:,} VND "
                  f"(k={c['neighbors_used']}, top_sim={c['top_similarity']})")
        if c.get("price_diff_pct") is not None:
            print(f"      diff      : {c['price_diff_pct']:+}%")
        print(f"      neighbors : {c['matched_item_names']}")
        print(f"      flag      : {c.get('flag') or '—'}")

    print(f"\nSaved ({report['save_which']}): {report['saved_rows']} row(s) inserted into price_references")
    if report["save_blocked_at_floor"]:
        print(f"  {len(report['save_blocked_at_floor'])} item(s) blocked at save (sanity floor)")


async def _amain(argv: list[str]) -> None:
    if len(argv) < 2:
        sys.exit(
            'usage: python -m app.tools.menu_price_pipeline "<image_path>" '
            "<region> [category] [--no-save] [--save-which=matched|unmatched|all]"
        )
    image_path, region = argv[0], argv[1]
    category = argv[2] if len(argv) > 2 and not argv[2].startswith("-") else "food"
    save = "--no-save" not in argv
    save_which = next(
        (a.split("=", 1)[1] for a in argv if a.startswith("--save-which=")), "matched"
    )

    await init_pool()
    try:
        report = await run_pipeline(
            image_path, region=region, category=category, save=save, save_which=save_which
        )
    finally:
        await close_pool()

    _print_report(report)


def main() -> None:
    asyncio.run(_amain(sys.argv[1:]))


if __name__ == "__main__":
    main()
