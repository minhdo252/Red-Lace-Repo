"""
crawl_shopeefood_full.py
------------------------
Full crawler for ShopeeFood Hà Nội delivery list:
  https://shopeefood.vn/ha-noi/food/danh-sach-dia-diem-giao-tan-noi

Lives in backend/app/tools/ — uses backend/app/utils/menu_extract.py (DOM
selectors) and menu_normalize.py (noise-reduction layer). collect_all_restaurants()
and scrape_menu() are also imported directly by
backend/app/agent/seed_price_references.py, which is the one that actually
runs automatically on `docker compose up`. Run this file directly when you
want JSON output to inspect instead of a straight-to-Postgres write.

Steps:
  1. Paginate through ALL result pages  → collect every restaurant URL
  2. Visit each restaurant detail page  → extract full menu (categories + items)
  3. Save results to test/output/shopeefood_full.json

Run via Docker:
    docker compose --profile playwright-full run --rm playwright-full-crawler

Output:
    test/output/shopeefood_full.json        – all restaurants with menus
    test/output/shopeefood_full_page_N.png  – screenshot of each listing page
    test/output/price_references_seed.json  – cleaned rows, ready to import
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

try:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit("[ERROR] Run inside playwright-crawler container.")

from app.utils.menu_normalize import (
    normalize_item_name,
    is_empty_after_cleaning,
    parse_price_vnd,
    to_price_reference_row,
)
from app.utils.menu_extract import extract_menu_items

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL     = "https://shopeefood.vn"
LIST_URL     = f"{BASE_URL}/ha-noi/food/danh-sach-dia-diem-giao-tan-noi"
OUTPUT_DIR   = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

NAV_TIMEOUT     = 30_000   # ms – page navigation
CONTENT_TIMEOUT = 15_000   # ms – wait for a selector
SCROLL_PAUSE    = 1.2      # s  – between scroll steps
DELAY_BETWEEN   = 1.5      # s  – polite delay between restaurant requests
MAX_PAGES       = int(os.environ.get("CRAWL_MAX_PAGES", "2"))  # max listing pages to crawl

REGION   = "Hanoi"        # matches menu_normalize / db/init.sql geo_regions
CATEGORY = "food"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def slow_scroll(page, steps: int = 4) -> None:
    for _ in range(steps):
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await asyncio.sleep(SCROLL_PAUSE)


async def wait_for_first(page, selectors: list, timeout: int = CONTENT_TIMEOUT) -> str | None:
    """Return the first selector that resolves within timeout."""
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, timeout=timeout)
            if await page.locator(sel).count() > 0:
                return sel
        except PWTimeout:
            continue
    return None


# ---------------------------------------------------------------------------
# Phase 1 – collect all restaurant cards across pages
# ---------------------------------------------------------------------------

async def collect_all_restaurants(page) -> list[dict]:
    """Navigate the listing pages and collect all restaurant cards."""
    restaurants = []
    page_num = 1

    while MAX_PAGES is None or page_num <= MAX_PAGES:
        print(f"\n[Page {page_num}] Loading {LIST_URL} ...")
        if page_num == 1:
            await page.goto(LIST_URL, timeout=NAV_TIMEOUT, wait_until="networkidle")
        # (subsequent pages are handled by clicking Next)

        # Wait for cards
        sel = await wait_for_first(page, [".item-restaurant", "[class*='item-restaurant']"])
        if not sel:
            print(f"  [!] No cards on page {page_num} – stopping pagination.")
            break

        await slow_scroll(page, steps=3)

        # Screenshot this listing page
        ss = OUTPUT_DIR / f"shopeefood_full_page_{page_num}.png"
        await page.screenshot(path=str(ss), full_page=True)

        # Extract cards on this page
        cards = page.locator(sel)
        count = await cards.count()
        print(f"  [✓] Found {count} cards on page {page_num}")

        for i in range(count):
            card = cards.nth(i)
            try:
                name = ""
                for ns in [".name-res", "[class*='name-res']", "h4", "h3"]:
                    el = card.locator(ns).first
                    if await el.count() > 0:
                        name = (await el.inner_text()).strip()
                        if name:
                            break

                address = ""
                for as_ in [".address-res", "[class*='address']"]:
                    el = card.locator(as_).first
                    if await el.count() > 0:
                        address = (await el.inner_text()).strip()
                        if address:
                            break

                promotion = ""
                for ps in [".content-promotion", "[class*='promotion']"]:
                    el = card.locator(ps).first
                    if await el.count() > 0:
                        promotion = (await el.inner_text()).strip()
                        if promotion:
                            break

                image_src = ""
                img = card.locator(".img-restaurant img, img").first
                if await img.count() > 0:
                    image_src = (await img.get_attribute("src") or
                                 await img.get_attribute("data-src") or "")

                href = ""
                a_el = card.locator("a").first
                if await a_el.count() > 0:
                    href = await a_el.get_attribute("href") or ""
                    if href and not href.startswith("http"):
                        href = BASE_URL + href

                restaurants.append({
                    "name": name,
                    "address": address,
                    "promotion": promotion,
                    "image_src": image_src,
                    "url": href,
                    "menu": [],        # filled in phase 2
                    "crawl_status": "pending",
                })
            except Exception as e:
                print(f"  [!] Card {i} error: {e}")

        # ── Try to click the "next page" button ──
        next_sel = await wait_for_first(page, [
            ".pagination .next:not(.disabled)",
            "a[aria-label='Next']",
            ".page-next:not(.disabled)",
            "[class*='pagination'] a:last-child:not([class*='disabled'])",
            # Arrow / chevron button at the end of pagination
            ".pagination li:last-child a",
            "nav[aria-label*='pagination'] a:last-child",
        ], timeout=3_000)

        # Also try clicking by evaluating the DOM directly
        next_clicked = False
        if next_sel:
            next_btn = page.locator(next_sel).last
            is_disabled = await next_btn.get_attribute("class") or ""
            if "disabled" not in is_disabled:
                await next_btn.click()
                await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT)
                page_num += 1
                next_clicked = True

        if not next_clicked:
            # Try JS-based: find the active page number and click page+1
            advanced = await page.evaluate(f"""() => {{
                const active = document.querySelector('.pagination .active, .page-item.active');
                if (!active) return false;
                const items = document.querySelectorAll('.pagination li, .pagination .page-item');
                const idx = Array.from(items).indexOf(active);
                if (idx < 0 || idx >= items.length - 1) return false;
                const nextItem = items[idx + 1];
                const link = nextItem.querySelector('a');
                if (!link || link.classList.contains('disabled')) return false;
                link.click();
                return true;
            }}""")
            if advanced:
                await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT)
                page_num += 1
            else:
                print(f"  [✓] No more pages after page {page_num}.")
                break

    print(f"\n[✓] Total restaurants collected: {len(restaurants)}")
    return restaurants


# ---------------------------------------------------------------------------
# Phase 2 – crawl each restaurant's menu
# ---------------------------------------------------------------------------

async def scrape_menu(page, restaurant: dict, idx: int, total: int) -> None:
    """Navigate to restaurant page and extract menu categories + items."""
    url = restaurant["url"]
    name = restaurant["name"]
    print(f"\n[{idx}/{total}] {name}")
    print(f"  URL: {url}")

    if not url:
        restaurant["crawl_status"] = "skipped (no url)"
        return

    try:
        await page.goto(url, timeout=NAV_TIMEOUT, wait_until="networkidle")
        await slow_scroll(page, steps=4)

        # ── Extract menu items using the confirmed selectors (menu_extract.py) ──
        flat_items = await extract_menu_items(page, url)

        if not flat_items:
            all_classes = await page.evaluate("""() => {
                const cls = new Set();
                document.querySelectorAll('[class]').forEach(el => {
                    el.className.split(' ').forEach(c => { if(c) cls.add(c); });
                });
                return Array.from(cls).join(' | ');
            }""")
            print(f"  [!] No menu items found.")
            print(f"  [~] Available classes (sample): {all_classes[:300]}")
            restaurant["crawl_status"] = "no_menu_selector"
            restaurant["available_classes_sample"] = all_classes[:500]
            return

        # Regroup the flat item list back into categories (for restaurant["menu"])
        categories_map: dict[str, list[dict]] = {}
        for it in flat_items:
            categories_map.setdefault(it.get("category", "Menu"), []).append(it)
        categories = [{"category": cat, "items": items} for cat, items in categories_map.items()]

        total_items = len(flat_items)
        restaurant["menu"] = categories
        print(f"  [✓] {len(categories)} categor{'y' if len(categories)==1 else 'ies'}, {total_items} raw items")

        # ── Noise-reduction layer ──────────────────────────────────────────
        # Strip marketing words (combo, flash sale, khuyến mãi, % off, ...)
        # from item names in place — quantities and the rest of the name are
        # left untouched (see menu_normalize.py).
        clean_items = []
        for cat in categories:
            for it in cat["items"]:
                raw_name = it.get("name", "")
                if not raw_name:
                    continue
                clean_name = normalize_item_name(raw_name)
                if is_empty_after_cleaning(clean_name):
                    continue
                clean_items.append({
                    "category": cat["category"],
                    "name_raw": raw_name,
                    "name_clean": clean_name,
                    "price_raw": it.get("price_raw", ""),
                    "price_vnd": parse_price_vnd(it.get("price_raw", "")),
                    "description": it.get("description", ""),
                    "image": it.get("image", ""),
                })
        restaurant["menu_clean"] = clean_items

        restaurant["crawl_status"] = "ok"
        print(
            f"  [✓] {len(categories)} categor{'y' if len(categories)==1 else 'ies'}, "
            f"{total_items} raw items -> {len(clean_items)} clean"
        )

    except PWTimeout:
        print(f"  [!] Timeout navigating to {url}")
        restaurant["crawl_status"] = "timeout"
    except Exception as e:
        print(f"  [!] Error: {e}")
        restaurant["crawl_status"] = f"error: {e}"

    await asyncio.sleep(DELAY_BETWEEN)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print(f"\n{'='*60}")
    print("  SHOPEEFOOD FULL CRAWLER  (list + menus)")
    print(f"{'='*60}")
    print(f"  Listing URL : {LIST_URL}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = await browser.new_context(
            user_agent=UA,
            locale="vi-VN",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8"},
        )
        page = await context.new_page()

        # ── Phase 1: collect all restaurants ──────────────────────────────
        restaurants = await collect_all_restaurants(page)

        # Checkpoint – save list before crawling menus (safe against crashes)
        checkpoint = OUTPUT_DIR / "shopeefood_full_checkpoint.json"
        checkpoint.write_text(
            json.dumps({"restaurants": restaurants}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[✓] Checkpoint saved → {checkpoint}")

        # ── Phase 2: crawl menus ──────────────────────────────────────────
        total = len(restaurants)
        print(f"\n[~] Crawling menus for {total} restaurants …")
        for idx, restaurant in enumerate(restaurants, 1):
            await scrape_menu(page, restaurant, idx, total)

            # Save progress every 5 restaurants
            if idx % 5 == 0 or idx == total:
                checkpoint.write_text(
                    json.dumps({"restaurants": restaurants}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"  [💾] Progress saved ({idx}/{total})")

        await browser.close()

    # ── Final report ──────────────────────────────────────────────────────
    ok     = sum(1 for r in restaurants if r["crawl_status"] == "ok")
    failed = total - ok

    report = {
        "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "listing_url": LIST_URL,
        "total_restaurants": total,
        "menus_ok": ok,
        "menus_failed": failed,
        "restaurants": restaurants,
    }

    out_path = OUTPUT_DIR / "shopeefood_full.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[✓] Full report saved → {out_path}")

    # ── price_references seed: flatten clean items across all restaurants ──
    seed_rows = []
    total_raw = total_clean = 0
    for r in restaurants:
        total_raw += sum(len(c["items"]) for c in r.get("menu", []))
        for it in r.get("menu_clean", []):
            total_clean += 1
            row = to_price_reference_row(it["name_clean"], it["price_vnd"], REGION, CATEGORY)
            row["item_name_raw"] = it["name_raw"]
            row["restaurant"] = r["name"]
            row["source_url"] = r["url"]
            row["menu_category"] = it["category"]
            row["raw_price_text"] = it["price_raw"]
            seed_rows.append(row)

    seed_path = OUTPUT_DIR / "price_references_seed.json"
    seed_path.write_text(
        json.dumps(
            {
                "target_table": "price_references",
                "schema_columns": [
                    "item_name", "region", "category", "price_vnd",
                    "mu_post", "tau_post", "sigma_data", "n", "sum_y",
                ],
                "rows": seed_rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[✓] price_references seed saved → {seed_path}")

    # ── Pretty summary ────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    print(f"  Restaurants   : {total}")
    print(f"  Menus OK      : {ok}")
    print(f"  Failed/empty  : {failed}")
    print(f"\n  Noise-reduction layer:")
    print(f"  Raw items     : {total_raw}")
    print(f"  Clean seed rows : {total_clean}")
    print(f"\n  Top restaurants:")
    for i, r in enumerate(restaurants[:10], 1):
        n_clean = len(r.get("menu_clean", []))
        print(f"  {i:>2}. {r['name'][:45]:<45}  {n_clean} clean items  [{r['crawl_status']}]")
    print(f"\n  Output : {out_path}")
    print(f"  Seed   : {seed_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
