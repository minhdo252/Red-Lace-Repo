"""
seed_price_references.py
-------------------------
One-shot seeding agent: crawls ShopeeFood Ha Noi restaurant menus and
inserts the cleaned results directly into Postgres `price_references`.

Reuses existing crawling logic rather than duplicating it:
    - collect_all_restaurants() / scrape_menu()    <- app/tools/crawl_shopeefood_full.py
    - extract_menu_items() (proven DOM selectors)  <- app/utils/menu_extract.py
      (the same selectors crawl_menu_dom_explorer.py discovered and verified
      against the real rendered DOM — see test/output/menu_dom_classes.txt)
    - normalize_item_name() / parse_price_vnd()    <- app/utils/menu_normalize.py

Multiple restaurants often sell the "same" dish at different prices (e.g.
"bun cha" at 5 different places). Rather than inserting one row per raw
observation — which would violate the one-row-per-(item_name, region,
category) design in db/init.sql and break the Qdrant kNN -> Postgres row
lookup — observations are grouped by normalized item_name first, then
merged into a single posterior per item via merge_observations() below.
This is a simplified empirical-Bayes bootstrap (sample mean/variance
straight from the crawled data) rather than the full LLM-prior fusion in
app/modules/pricing.py::fuse() — reasonable for bulk-seeding many points at
once; per-query online updates still go through the real fusion logic.

WHEN THIS RUNS
    Wired into docker-compose.yml as the `seed-crawler` service, which
    `backend` depends on with `condition: service_completed_successfully`
    — so it runs automatically as part of `docker compose up`.

    Two layers of "don't re-do slow work":
      1. If price_references already has rows, skip everything and exit —
         only the very first `docker compose up` against an empty DB does
         any work at all.
      2. Otherwise, if output/crawled_restaurants_cache.json exists (a
         committed, pre-crawled snapshot next to this file), seed straight
         from that instead of hitting ShopeeFood live. Delete that file
         (or set FORCE_LIVE_CRAWL=1) to force a fresh live crawl, which
         re-writes the cache on success.

    Safety: a live external crawl can fail (site layout change, network
    issue, temporary block) — this script always exits 0 so a crawl
    failure never blocks the rest of the stack from starting. Worst case,
    price_references stays empty and estimate_fair_price() falls back to
    an LLM-only prior with n=0 until data is seeded some other way.

Run standalone (needs Postgres reachable + playwright installed, run from
the backend/app directory so `app` resolves as a package):
    POSTGRES_DSN=postgresql://user:pass@localhost:5432/db \\
        python -m app.agent.seed_price_references

Run via Docker (automatic on `docker compose up`, or manually):
    docker compose run --rm seed-crawler

Limit crawl scope for a fast local test run (fewer listing pages, so
fewer restaurants get discovered in the first place):
    CRAWL_MAX_PAGES=1 docker compose run --rm seed-crawler
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
from pathlib import Path

try:
    import asyncpg
except ImportError:
    sys.exit("[ERROR] Run inside seed-crawler/playwright container (needs asyncpg).")

try:
    from playwright.async_api import async_playwright
except ImportError:
    sys.exit("[ERROR] Run inside seed-crawler/playwright container (needs playwright).")

from app.tools.crawl_shopeefood_full import collect_all_restaurants, scrape_menu, REGION, CATEGORY
from app.ai.vn_embedding import embed_price_references
from app.db.postgres import close_pool as close_shared_pool

POSTGRES_DSN = os.environ.get(
    "POSTGRES_DSN", "postgresql://aitravelmate:aitravelmate@postgres:5432/aitravelmate"
)
# Crawl scope is controlled by CRAWL_MAX_PAGES (read directly by
# crawl_shopeefood_full.py's MAX_PAGES) — how many listing pages to
# paginate through, not a restaurant-count cutoff after the fact.

CACHE_PATH = Path(__file__).parent / "output" / "crawled_restaurants_cache.json"
FORCE_LIVE_CRAWL = os.environ.get("FORCE_LIVE_CRAWL", "") not in ("", "0", "false")

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def compute_category_spread(groups: dict[str, list[float]]) -> float:
    """
    Pool observed within-item variance across every item in this crawl that
    DOES have n>=2 real price points, to get an empirical "how much do
    prices for this kind of dish vary across vendors" estimate.

    A single crawled price, however accurate, is one draw from an unknown
    distribution — it cannot tell you anything about that distribution's
    spread (sample variance with n=1 is mathematically undefined). Rather
    than assume a fixed spread constant, borrow the spread actually observed
    on other items in the same crawl that do have multiple vendors, and use
    that as the sigma_data for items caught with n==1. Falls back to 0.3
    only if no item in the crawl has n>=2 (no empirical signal at all).
    """
    variances = []
    for prices in groups.values():
        if len(prices) >= 2:
            logs = [math.log(p) for p in prices]
            mean = sum(logs) / len(logs)
            variances.append(sum((y - mean) ** 2 for y in logs) / (len(logs) - 1))
    return math.sqrt(sum(variances) / len(variances)) if variances else 0.3


def merge_observations(prices_vnd: list[float], sigma_data: float = 0.3) -> tuple[float, float, int, float]:
    """
    Collapse N raw price observations for the same item into one posterior.
    Returns (mu_post, tau_post, n, sum_y) — see db/init.sql price_references.

    n == 1: no real spread to estimate from, so tau_post falls back to
    sigma_data**2, which callers should pass in as an empirical estimate
    (see compute_category_spread) rather than an arbitrary constant.
    n >= 2: tau_post is the standard error of the sample mean in log-space,
    floored to avoid zero-variance overconfidence when prices happen to
    match exactly.
    """
    n = len(prices_vnd)
    log_prices = [math.log(p) for p in prices_vnd]
    sum_y = sum(log_prices)
    mu_post = sum_y / n
    if n >= 2:
        variance = sum((y - mu_post) ** 2 for y in log_prices) / (n - 1)
        tau_post = max(variance / n, 1e-4)
    else:
        tau_post = sigma_data ** 2
    return mu_post, tau_post, n, sum_y


async def already_seeded(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT count(*) FROM price_references")


async def insert_rows(pool: asyncpg.Pool, rows: list[dict]) -> int:
    if not rows:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO price_references
                (item_name, region, category, price_vnd, mu_post, tau_post, sigma_data, n, sum_y)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            [
                (
                    r["item_name"], r["region"], r["category"], r["price_vnd"],
                    r["mu_post"], r["tau_post"], r["sigma_data"], r["n"], r["sum_y"],
                )
                for r in rows
            ],
        )
    return len(rows)


def load_cache() -> list[dict] | None:
    if FORCE_LIVE_CRAWL or not CACHE_PATH.exists():
        return None
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        restaurants = data["restaurants"]
        print(f"[✓] Using cached crawl data ({len(restaurants)} restaurants) from {CACHE_PATH}")
        return restaurants
    except Exception as e:
        print(f"[!] Cache at {CACHE_PATH} is unreadable ({e}) — falling back to a live crawl.")
        return None


def save_cache(restaurants: list[dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps({"restaurants": restaurants}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[✓] Cached crawl data -> {CACHE_PATH}")


async def load_or_crawl_restaurants() -> list[dict]:
    cached = load_cache()
    if cached is not None:
        return cached
    print("[~] No usable cache — crawling ShopeeFood live...")
    restaurants = await crawl_all_menus()
    save_cache(restaurants)
    return restaurants


async def crawl_all_menus() -> list[dict]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = await browser.new_context(
            user_agent=UA,
            locale="vi-VN",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8"},
        )
        page = await context.new_page()

        restaurants = await collect_all_restaurants(page)

        total = len(restaurants)
        print(f"[~] Crawling menus for {total} restaurants...")
        for idx, restaurant in enumerate(restaurants, 1):
            await scrape_menu(page, restaurant, idx, total)

        await browser.close()
    return restaurants


def build_seed_rows(restaurants: list[dict]) -> list[dict]:
    """Group cleaned items by item_name and merge each group's prices into
    one price_references row (see merge_observations)."""
    groups: dict[str, list[float]] = {}
    for r in restaurants:
        for it in (r.get("menu_clean") or []):
            price = it.get("price_vnd")
            if not price or price < 1000:
                continue  # no real Hanoi menu item costs <1000 VND — catches parse bugs
            groups.setdefault(it["name_clean"], []).append(price)

    category_spread = compute_category_spread(groups)

    rows = []
    for item_name, prices in groups.items():
        mu_post, tau_post, n, sum_y = merge_observations(prices, sigma_data=category_spread)
        rows.append(
            {
                "item_name": item_name,
                "region": REGION,
                "category": CATEGORY,
                "price_vnd": sum(prices) / len(prices),  # mean, for display
                "mu_post": mu_post,
                "tau_post": tau_post,
                "sigma_data": category_spread,
                "n": n,
                "sum_y": sum_y,
            }
        )
    return rows


async def main() -> None:
    print("=" * 60)
    print("  price_references SEEDING AGENT")
    print("=" * 60)

    try:
        pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=1, max_size=3)
    except Exception as e:
        print(f"[!] Could not connect to Postgres ({e}) — skipping seed.")
        return  # exit 0: never block the stack from starting

    try:
        existing = await already_seeded(pool)
        if existing > 0:
            print(f"[✓] price_references already has {existing} rows — skipping crawl.")
            return

        print("[~] price_references is empty — sourcing seed data...")
        try:
            restaurants = await load_or_crawl_restaurants()
        except Exception as e:
            print(f"[!] Crawl failed ({e}) — leaving price_references empty for this run.")
            return

        seed_rows = build_seed_rows(restaurants)
        inserted = await insert_rows(pool, seed_rows)
        print(f"[✓] Inserted {inserted} unique-item price_references rows "
              f"from {len(restaurants)} restaurants.")

        # --- Step 2: Embed all price_references and push to Qdrant ---
        if inserted > 0:
            print("[~] Embedding price_references into Qdrant via vn_embedding...")
            try:
                total_embedded = await embed_price_references()
                print(f"[✓] Embedded {total_embedded} item_names into Qdrant.")
            except Exception as e:
                print(f"[!] Embedding into Qdrant failed ({e}) — "
                      "price_references are in Postgres; run vn_embedding manually later.")
            finally:
                await close_shared_pool()  # clean up the pool embed_price_references() opened

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
