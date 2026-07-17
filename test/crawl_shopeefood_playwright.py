"""
crawl_shopeefood_playwright.py
------------------------------
Crawl https://shopeefood.vn/ha-noi/food/danh-sach-dia-diem-giao-tan-noi
using a real headless Chromium via Playwright so all JS-rendered content
(restaurant cards, ratings, delivery times, images) is captured.

Run via Docker:
    docker compose --profile playwright run --rm playwright-crawler

Output (written to test/output/):
    shopeefood_rendered.html       – full rendered DOM
    shopeefood_screenshot.png      – full-page screenshot
    shopeefood_restaurants.json    – structured restaurant list
"""

import asyncio
import json
import sys
import time
from pathlib import Path

try:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit(
        "[ERROR] playwright not found.\n"
        "This script is meant to run inside the playwright-crawler Docker container.\n"
        "Run:  docker compose --profile playwright run --rm playwright-crawler"
    )

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TARGET_URL = "https://shopeefood.vn/ha-noi/food/danh-sach-dia-diem-giao-tan-noi"

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# How long to wait (ms) for the restaurant list to appear
PAGE_LOAD_TIMEOUT   = 30_000   # 30s overall navigation
CONTENT_TIMEOUT     = 20_000   # 20s waiting for cards
SCROLL_PAUSE        = 1.5      # seconds between scroll steps

# Candidate CSS selectors for restaurant card containers
# Discovered by inspecting the rendered DOM of shopeefood_rendered.html
CARD_SELECTORS = [
    ".item-restaurant",             # ← exact match from rendered HTML (25 cards)
    "[class='item-restaurant']",
    "[class*='item-restaurant']",
    ".restaurant-item",
    "[class*='restaurant-item']",
    "[class*='shop-item']",
    "[class*='food-card']",
    "ul li a:has(img)",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def scroll_to_bottom(page, steps: int = 5) -> None:
    """Slowly scroll down to trigger lazy-loading."""
    for i in range(steps):
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await asyncio.sleep(SCROLL_PAUSE)
        print(f"  [scroll] step {i+1}/{steps}")


async def find_working_selector(page) -> str | None:
    """Return the first CSS selector that matches at least one element."""
    for sel in CARD_SELECTORS:
        count = await page.locator(sel).count()
        if count > 0:
            print(f"  [selector] '{sel}' matched {count} element(s)")
            return sel
    return None


async def extract_restaurants(page, selector: str) -> list:
    """Extract structured data from all matched card elements."""
    cards = page.locator(selector)
    count = await cards.count()
    print(f"  [extract] {count} cards found with selector '{selector}'")

    restaurants = []
    for i in range(count):
        card = cards.nth(i)
        try:
            # Name — exact class from ShopeeFood DOM
            name = ""
            for name_sel in [".name-res", ".restaurant-name", "[class*='name-res']",
                              "[class*='name']", "h4", "h3", "strong"]:
                name_el = card.locator(name_sel).first
                if await name_el.count() > 0:
                    name = (await name_el.inner_text()).strip()
                    if name:
                        break

            # Address
            address = ""
            for a_sel in [".address-res", "[class*='address']", "[class*='location']"]:
                a_el = card.locator(a_sel).first
                if await a_el.count() > 0:
                    address = (await a_el.inner_text()).strip()
                    if address:
                        break

            # Promotion / discount text
            promotion = ""
            for p_sel in [".content-promotion", "[class*='promotion']", "[class*='discount']",
                          "[class*='voucher']", ".fas.fa-tag"]:
                p_el = card.locator(p_sel).first
                if await p_el.count() > 0:
                    promotion = (await p_el.inner_text()).strip()
                    if promotion:
                        break

            # Status (open/closed)
            status = ""
            for s_sel in [".opentime-status", "[class*='status']", "[class*='open']"]:
                s_el = card.locator(s_sel).first
                if await s_el.count() > 0:
                    status = (await s_el.inner_text()).strip()
                    if status:
                        break

            # Image src
            img_src = ""
            for img_sel in [".img-restaurant img", "img"]:
                img_el = card.locator(img_sel).first
                if await img_el.count() > 0:
                    img_src = (await img_el.get_attribute("src") or
                               await img_el.get_attribute("data-src") or "")
                    if img_src:
                        break

            # Link href
            href = ""
            a_el = card.locator("a").first
            if await a_el.count() > 0:
                href = await a_el.get_attribute("href") or ""
            if not href:
                tag = await card.evaluate("el => el.tagName")
                if tag.lower() == "a":
                    href = await card.get_attribute("href") or ""

            # Raw text fallback for name
            if not name:
                name = (await card.inner_text()).strip()[:80]

            restaurants.append({
                "name": name,
                "address": address,
                "promotion": promotion,
                "status": status,
                "image_src": img_src,
                "href": href,
            })
        except Exception as e:
            print(f"  [!] Error extracting card {i}: {e}")
            continue

    return restaurants


async def dump_dom_snapshot(page) -> dict:
    """Capture lightweight DOM statistics from the rendered page."""
    return await page.evaluate("""() => {
        const all = document.querySelectorAll('*');
        const tagCounts = {};
        all.forEach(el => {
            const t = el.tagName.toLowerCase();
            tagCounts[t] = (tagCounts[t] || 0) + 1;
        });
        const sorted = Object.entries(tagCounts)
            .sort((a,b) => b[1]-a[1])
            .slice(0, 20);
        return {
            total_elements: all.length,
            top_tags: Object.fromEntries(sorted),
            title: document.title,
            url: window.location.href,
        };
    }""")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print(f"\n{'='*60}")
    print("  SHOPEEFOOD PLAYWRIGHT CRAWLER")
    print(f"{'='*60}")
    print(f"  URL: {TARGET_URL}\n")

    async with async_playwright() as pw:
        print("[~] Launching headless Chromium...")
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="vi-VN",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
        )
        page = await context.new_page()

        # ── Navigate ──────────────────────────────────────────────────────
        print(f"[~] Navigating to {TARGET_URL} ...")
        try:
            await page.goto(TARGET_URL, timeout=PAGE_LOAD_TIMEOUT, wait_until="networkidle")
        except PWTimeout:
            print("[!] networkidle timed out — proceeding with what loaded")
        print("[✓] Page navigation complete")

        # ── Scroll to load lazy content ───────────────────────────────────
        print("[~] Scrolling to trigger lazy loading...")
        await scroll_to_bottom(page, steps=6)

        # ── Wait for any card selector ─────────────────────────────────────
        print("[~] Searching for restaurant card selectors...")
        working_selector = None
        for sel in CARD_SELECTORS:
            try:
                await page.wait_for_selector(sel, timeout=CONTENT_TIMEOUT)
                count = await page.locator(sel).count()
                if count > 0:
                    working_selector = sel
                    print(f"[✓] Selector found: '{sel}' ({count} elements)")
                    break
            except PWTimeout:
                print(f"  [skip] '{sel}' — timeout")
                continue

        # ── Screenshot ────────────────────────────────────────────────────
        ss_path = OUTPUT_DIR / "shopeefood_screenshot.png"
        await page.screenshot(path=str(ss_path), full_page=True)
        print(f"[✓] Screenshot saved -> {ss_path}")

        # ── Save rendered HTML ────────────────────────────────────────────
        rendered_html = await page.content()
        html_path = OUTPUT_DIR / "shopeefood_rendered.html"
        html_path.write_text(rendered_html, encoding="utf-8")
        print(f"[✓] Rendered HTML saved -> {html_path}  ({len(rendered_html):,} bytes)")

        # ── DOM snapshot ──────────────────────────────────────────────────
        dom_snapshot = await dump_dom_snapshot(page)

        # ── Extract restaurant cards ──────────────────────────────────────
        restaurants = []
        if working_selector:
            restaurants = await extract_restaurants(page, working_selector)
        else:
            print("[!] No card selector matched.")
            print("[~] Falling back: collecting all <a> tags with images...")
            restaurants = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a')).filter(a => a.querySelector('img')).map(a => {
                    const img = a.querySelector('img');
                    const textEls = a.querySelectorAll('[class*="name"],[class*="title"],h3,h4,strong');
                    const name = textEls.length ? textEls[0].innerText.trim() : a.innerText.trim().slice(0, 80);
                    return {
                        name: name,
                        rating: '',
                        delivery_time: '',
                        image_src: img ? (img.src || img.dataset.src || '') : '',
                        href: a.href || '',
                    };
                }).filter(r => r.href.includes('shopeefood')).slice(0, 50);
            }""")

        await browser.close()

    # ── Build report ──────────────────────────────────────────────────────
    report = {
        "url": TARGET_URL,
        "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rendered_html_bytes": len(rendered_html),
        "dom_snapshot": dom_snapshot,
        "selector_used": working_selector or "fallback (a:has(img))",
        "restaurant_count": len(restaurants),
        "restaurants": restaurants,
    }

    json_path = OUTPUT_DIR / "shopeefood_restaurants.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[✓] Restaurant JSON saved -> {json_path}")

    # ── Pretty print ──────────────────────────────────────────────────────
    sep = "-" * 60
    print(f"\n{'='*60}")
    print("  RESULTS")
    print(f"{'='*60}")
    print(f"\n{sep}")
    print("  DOM SNAPSHOT (rendered)")
    print(sep)
    print(f"  Page title      : {dom_snapshot.get('title', 'N/A')}")
    print(f"  Total elements  : {dom_snapshot.get('total_elements', 0):,}")
    print(f"  Top tags        : {dom_snapshot.get('top_tags', {})}")

    print(f"\n{sep}")
    print(f"  RESTAURANTS FOUND: {len(restaurants)}")
    print(sep)
    if restaurants:
        for i, r in enumerate(restaurants[:25], 1):
            promo = f"  [{r['promotion']}]" if r.get('promotion') else ""
            print(f"  {i:>2}. {r['name'][:50]:<50}  {r.get('address','')[:40]}{promo}")
    else:
        print("  [!] No restaurants extracted.")
        print("  [~] Check test/output/shopeefood_screenshot.png to see what loaded.")
        print("  [~] Check test/output/shopeefood_rendered.html for the full DOM.")

    print(f"\n{'='*60}")
    print(f"  Crawled    : {report['crawled_at']}")
    print(f"  HTML size  : {len(rendered_html):,} bytes")
    print(f"  Selector   : {report['selector_used']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
