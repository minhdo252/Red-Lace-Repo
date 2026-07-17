"""
crawl_menu_dom_explorer.py
--------------------------
Automatically opens test/output/shopeefood_full_checkpoint.json,
picks the first restaurant (or --index N), renders its page with
headless Chromium, dumps the full DOM class tree, then extracts
the menu and maps it to the SQL price_references schema.

Run via Docker (default: first restaurant):
    docker compose --profile playwright run --rm playwright-crawler

Change restaurant index:
    docker compose --profile playwright run --rm playwright-crawler \
        python test/crawl_menu_dom_explorer.py --index 3

Output (test/output/):
    menu_dom_dump.html        – full rendered HTML
    menu_dom_classes.txt      – all CSS classes sorted by frequency
    menu_dom_screenshot.png   – full-page screenshot
    menu_schema_rows.json     – price_references rows ready to INSERT
"""

import argparse
import asyncio
import json
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

# ---------------------------------------------------------------------------
# Config — auto-loaded; override with CLI flags
# ---------------------------------------------------------------------------
CHECKPOINT = Path(__file__).parent / "output" / "shopeefood_full_checkpoint.json"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

NAV_TIMEOUT  = 30_000
WAIT_TIMEOUT = 15_000
SCROLL_PAUSE = 1.2

REGION   = "Hanoi"
CATEGORY = "food"

# Parse --index CLI arg (default 0 = first restaurant in checkpoint)
_parser = argparse.ArgumentParser(description="ShopeeFood menu DOM explorer")
_parser.add_argument("--index", type=int, default=0,
                     help="Restaurant index in checkpoint JSON (default: 0)")
_args, _ = _parser.parse_known_args()
TARGET_INDEX = _args.index

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Item-name normalization (bundle-deal exclusion, marketing-noise stripping,
# price parsing, price_references row shaping) now lives in menu_normalize.py
# and is imported above — shared with crawl_shopeefood_full.py so both tools
# apply the same noise-reduction rules.


async def slow_scroll(page, steps: int = 5) -> None:
    for _ in range(steps):
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await asyncio.sleep(SCROLL_PAUSE)


# ---------------------------------------------------------------------------
# DOM explorer
# ---------------------------------------------------------------------------

async def explore_dom(page) -> dict:
    """
    Collect DOM statistics from the rendered page:
    - All unique class names + counts
    - Tag-level counts
    - Potential menu selectors (any element with 'menu', 'dish', 'food', 'item' in class)
    """
    return await page.evaluate("""() => {
        const classCounts = {};
        const tagCounts   = {};
        const menuHints   = [];

        document.querySelectorAll('*').forEach(el => {
            // tag counts
            const tag = el.tagName.toLowerCase();
            tagCounts[tag] = (tagCounts[tag] || 0) + 1;

            // class counts
            (el.className || '').split(/\s+/).forEach(c => {
                if (!c) return;
                classCounts[c] = (classCounts[c] || 0) + 1;
            });

            // menu hints
            const cls = (el.className || '').toLowerCase();
            const id  = (el.id || '').toLowerCase();
            if (/menu|dish|food|mon-an|mon_an|item-food|list-food/.test(cls + id)) {
                const sample = el.innerText.trim().slice(0, 80);
                if (sample) {
                    menuHints.push({
                        tag,
                        class: el.className,
                        id:    el.id,
                        text:  sample,
                    });
                }
            }
        });

        return { classCounts, tagCounts, menuHints };
    }""")


# ---------------------------------------------------------------------------
# Menu extractor — guided by DOM explorer results
# ---------------------------------------------------------------------------

# ── Selectors discovered from DOM analysis of shopeefood_rendered.html ───────
# Item card:  .item-restaurant-row  (19 per page)
# Name:       .item-restaurant-name
# Desc:       .item-restaurant-desc
# Price:      .current-price  (inside .product-price)
# Image:      .item-restaurant-img img
# Category:   .title-menu  (header)  inside  .menu-group  (wrapper)
# -----------------------------------------------------------------------------
MENU_ITEM_SELECTORS = [
    # Confirmed exact matches from ShopeeFood DOM
    ".item-restaurant-row",
    "[class*='item-restaurant-row']",
    # Legacy / fallback patterns for other layouts
    ".item-food",
    ".dish-item",
    ".food-item",
    "[class*='item-food']",
    "[class*='dish-item']",
    "ul li:has(img)",
]

NAME_SELECTORS  = [".item-restaurant-name", "[class*='item-restaurant-name']",
                   ".food-name", ".dish-name", "h4", "h3", "strong", "b"]
PRICE_SELECTORS = [".current-price", ".product-price .current-price",
                   "[class*='current-price']", ".price", "[class*='price']"]
DESC_SELECTORS  = [".item-restaurant-desc", "[class*='item-restaurant-desc']",
                   ".description", "[class*='desc']"]
IMG_SELECTORS   = [".item-restaurant-img img", "img"]
CAT_SELECTORS   = [".title-menu", ".menu-group .title-menu",
                   "[class*='title-menu']", ".menu-restaurant-category .title-menu"]


async def extract_menu_items(page, restaurant_url: str) -> list[dict]:
    """
    Try each selector family until we find menu items.
    Returns a flat list of {category, name, price_raw, price_vnd}.
    """
    items = []

    # 1. Try to wait for a known menu selector
    working_sel = None
    for sel in MENU_ITEM_SELECTORS:
        try:
            await page.wait_for_selector(sel, timeout=5_000)
            count = await page.locator(sel).count()
            if count > 0:
                working_sel = sel
                print(f"  [selector] '{sel}' → {count} elements")
                break
        except PWTimeout:
            continue

    if not working_sel:
        print("  [!] No menu selector matched — trying JS fallback")
        items = await page.evaluate("""() => {
            const candidates = Array.from(document.querySelectorAll('[class]')).filter(el => {
                const c = el.className.toLowerCase();
                return /item-restaurant-row|dish|food/.test(c) && el.querySelector('img');
            });
            return candidates.map(el => {
                const nameEl  = el.querySelector('.item-restaurant-name,[class*="name"],h4,h3,strong');
                const priceEl = el.querySelector('.current-price,.product-price,[class*="price"]');
                return {
                    category:  '',
                    name:      nameEl  ? nameEl.innerText.trim() : el.innerText.trim().slice(0,80),
                    price_raw: priceEl ? priceEl.innerText.trim() : '',
                    image:     '',
                };
            }).filter(r => r.name);
        }""")
        for it in items:
            it["source_url"] = restaurant_url
        return items

    # 2. Extract with working selector, grouped by category
    # ShopeeFood DOM structure:
    #   .menu-restaurant-category
    #     .menu-group          ← category wrapper (3 total)
    #       .title-menu        ← category name
    #     .menu-restaurant-list
    #       .item-restaurant-row  ← dish card (items are SIBLINGS, not children of .menu-group)
    items = await page.evaluate(f"""(sel) => {{
        const results = [];

        // --- Strategy 1: sibling-walk from .menu-group to its following .menu-restaurant-list ---
        const groups = document.querySelectorAll('.menu-group');
        if (groups.length > 0) {{
            groups.forEach(group => {{
                const catEl   = group.querySelector('.title-menu');
                const catName = catEl ? catEl.innerText.trim() : 'Menu';

                // Walk forward siblings until the next .menu-group
                let sibling = group.nextElementSibling;
                while (sibling && !sibling.classList.contains('menu-group')) {{
                    sibling.querySelectorAll(sel).forEach(el => {{
                        const nameEl  = el.querySelector(
                            '.item-restaurant-name, [class*="item-restaurant-name"], h4, h3, strong'
                        );
                        const priceEl = el.querySelector(
                            '.current-price, [class*="current-price"]'
                        );
                        const descEl  = el.querySelector(
                            '.item-restaurant-desc, [class*="item-restaurant-desc"]'
                        );
                        const imgEl   = el.querySelector('.item-restaurant-img img, img');
                        const name = nameEl ? nameEl.innerText.trim() : el.innerText.trim().slice(0, 80);
                        if (!name) return;
                        results.push({{
                            category:    catName,
                            name:        name,
                            description: descEl  ? descEl.innerText.trim()  : '',
                            price_raw:   priceEl ? priceEl.innerText.trim() : '',
                            image:       imgEl   ? (imgEl.src || imgEl.dataset.src || '') : '',
                        }});
                    }});
                    sibling = sibling.nextElementSibling;
                }}
            }});
        }}

        // --- Strategy 2: flat list fallback (no .menu-group found, or items not in siblings) ---
        if (results.length === 0) {{
            document.querySelectorAll(sel).forEach(el => {{
                const nameEl  = el.querySelector(
                    '.item-restaurant-name, [class*="item-restaurant-name"], h4, h3, strong'
                );
                const priceEl = el.querySelector(
                    '.current-price, [class*="current-price"]'
                );
                const descEl  = el.querySelector(
                    '.item-restaurant-desc, [class*="item-restaurant-desc"]'
                );
                const imgEl   = el.querySelector('.item-restaurant-img img, img');
                const name = nameEl ? nameEl.innerText.trim() : el.innerText.trim().slice(0, 80);
                if (!name) return;
                results.push({{
                    category:    'Menu',
                    name:        name,
                    description: descEl  ? descEl.innerText.trim()  : '',
                    price_raw:   priceEl ? priceEl.innerText.trim() : '',
                    image:       imgEl   ? (imgEl.src || imgEl.dataset.src || '') : '',
                }});
            }});
        }}

        return results;
    }}""", working_sel)

    for it in items:
        it["source_url"] = restaurant_url

    return items


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    # ── Load checkpoint ───────────────────────────────────────────────────
    if not CHECKPOINT.exists():
        sys.exit(f"[ERROR] Checkpoint not found: {CHECKPOINT}\n"
                 "Run the full crawler first to generate it.")

    data = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    restaurants = data.get("restaurants", [])
    if not restaurants:
        sys.exit("[ERROR] No restaurants in checkpoint.")

    target = restaurants[TARGET_INDEX]
    url    = target["url"]
    name   = target["name"]

    print(f"\n{'='*60}")
    print("  SHOPEEFOOD MENU DOM EXPLORER")
    print(f"{'='*60}")
    print(f"  Restaurant  : {name}")
    print(f"  URL         : {url}")
    print(f"  Checkpoint  : {CHECKPOINT}")
    print(f"  Target idx  : {TARGET_INDEX}\n")

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

        print("[~] Navigating ...")
        try:
            await page.goto(url, timeout=NAV_TIMEOUT, wait_until="networkidle")
        except PWTimeout:
            print("[!] networkidle timed out — proceeding")

        print("[~] Scrolling to load lazy content ...")
        await slow_scroll(page, steps=5)

        # ── DOM snapshot ──────────────────────────────────────────────────
        print("[~] Exploring DOM tree ...")
        dom = await explore_dom(page)

        # Sort classes by frequency
        sorted_classes = sorted(dom["classCounts"].items(), key=lambda x: x[1], reverse=True)

        # Save class inventory
        cls_path = OUTPUT_DIR / "menu_dom_classes.txt"
        with cls_path.open("w", encoding="utf-8") as f:
            f.write(f"# DOM class inventory for: {name}\n")
            f.write(f"# URL: {url}\n")
            f.write(f"# Total unique classes: {len(sorted_classes)}\n\n")
            f.write(f"{'COUNT':>6}  CLASS\n")
            f.write("-" * 50 + "\n")
            for cls, cnt in sorted_classes:
                f.write(f"{cnt:>6}  {cls}\n")
        print(f"[✓] Class inventory saved → {cls_path}  ({len(sorted_classes)} classes)")

        # Save rendered HTML
        rendered = await page.content()
        html_path = OUTPUT_DIR / "menu_dom_dump.html"
        html_path.write_text(rendered, encoding="utf-8")
        print(f"[✓] Rendered HTML saved → {html_path}  ({len(rendered):,} bytes)")

        # Screenshot
        ss_path = OUTPUT_DIR / "menu_dom_screenshot.png"
        await page.screenshot(path=str(ss_path), full_page=True)
        print(f"[✓] Screenshot saved → {ss_path}")

        # ── Menu extraction ───────────────────────────────────────────────
        print("\n[~] Extracting menu items ...")
        raw_items = await extract_menu_items(page, url)
        print(f"[✓] {len(raw_items)} menu items extracted")

        await browser.close()

    # ── Map to price_references schema ────────────────────────────────────
    # Noise-reduction layer: marketing words (combo, flash sale, khuyến mãi,
    # % off, ...) are stripped from item names in place. See menu_normalize.py.
    schema_rows = []
    for it in raw_items:
        raw_name = it["name"]
        clean_name = normalize_item_name(raw_name)
        if is_empty_after_cleaning(clean_name):
            continue
        price_vnd = parse_price_vnd(it.get("price_raw", ""))
        row = to_price_reference_row(
            item_name=clean_name,          # normalized — used for DB key
            price_vnd=price_vnd,
            region=REGION,
            category=CATEGORY,
        )
        row["item_name_raw"]  = raw_name   # original scraped name (for audit)
        row["source_url"]     = url
        row["menu_category"]  = it.get("category", "")
        row["raw_price_text"] = it.get("price_raw", "")
        schema_rows.append(row)

    # Save schema rows
    schema_path = OUTPUT_DIR / "menu_schema_rows.json"
    schema_path.write_text(
        json.dumps({
            "restaurant": name,
            "url": url,
            "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "target_table": "price_references",
    "schema_columns": [
                "item_name", "region", "category",
                "price_vnd", "mu_post", "tau_post",
                "sigma_data", "n", "sum_y",
            ],
            "rows": schema_rows,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[✓] Schema rows saved → {schema_path}")
    print(f"    {len(raw_items)} raw items -> {len(schema_rows)} clean rows")

    # ── Pretty print ──────────────────────────────────────────────────────
    sep = "-" * 60
    print(f"\n{'='*60}")
    print("  DOM SUMMARY")
    print(f"{'='*60}")
    print(f"\n  Total tags      : {sum(dom['tagCounts'].values()):,}")
    print(f"  Unique tags     : {len(dom['tagCounts'])}")
    print(f"  Unique classes  : {len(sorted_classes)}")

    print(f"\n{sep}")
    print("  TOP 30 CLASSES (most frequent)")
    print(sep)
    for cls, cnt in sorted_classes[:30]:
        bar = "█" * min(cnt, 40)
        print(f"  {cnt:>4}  {cls:<35}  {bar}")

    print(f"\n{sep}")
    print("  MENU-RELATED CLASSES (keyword match)")
    print(sep)
    menu_cls = [(c, n) for c, n in sorted_classes
                if any(kw in c.lower() for kw in
                       ["menu", "dish", "food", "mon", "item", "list-", "category"])]
    if menu_cls:
        for cls, cnt in menu_cls[:20]:
            print(f"  {cnt:>4}  {cls}")
    else:
        print("  (none found)")

    if dom.get("menuHints"):
        print(f"\n{sep}")
        print("  ELEMENTS WITH MENU-LIKE CLASS/ID")
        print(sep)
        for h in dom["menuHints"][:15]:
            print(f"  <{h['tag']} class='{h['class'][:40]}'> {h['text'][:50]}")

    print(f"\n{sep}")
    print(f"  EXTRACTED MENU ITEMS: {len(raw_items)}")
    print(sep)
    prev_cat = None
    for it in raw_items[:40]:
        cat = it.get("category", "")
        if cat != prev_cat:
            print(f"\n  [{cat or 'Uncategorized'}]")
            prev_cat = cat
        price = it.get("price_raw", "—")
        print(f"    • {it['name'][:50]:<50}  {price}")

    print(f"\n{sep}")
    print("  PRICE_REFERENCES SCHEMA MAPPING")
    print(sep)
    print(f"  {'item_name':<40} {'price_vnd':>12}  {'mu_post':>10}  {'n':>3}")
    print(f"  {'-'*40} {'-'*12}  {'-'*10}  {'-'*3}")
    for row in schema_rows[:20]:
        pv = f"{row['price_vnd']:>12,.0f}" if row.get("price_vnd") else f"{'—':>12}"
        mu = f"{row['mu_post']:.4f}" if row.get("mu_post") else "—"
        print(f"  {row['item_name'][:40]:<40} {pv}  {mu:>10}  {row['n']:>3}")

    print(f"\n{'='*60}")
    print(f"  schema rows : {len(schema_rows)}")
    print(f"  with price  : {sum(1 for r in schema_rows if r.get('price_vnd'))}")
    print(f"  output      : {schema_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
