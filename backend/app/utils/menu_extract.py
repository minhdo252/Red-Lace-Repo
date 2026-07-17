"""
menu_extract.py
----------------
Shared menu-extraction logic for ShopeeFood restaurant detail pages, used by
both crawl_menu_dom_explorer.py and crawl_shopeefood_full.py.

Selectors below are CONFIRMED against the real rendered DOM (see
test/output/menu_dom_classes.txt, captured by crawl_menu_dom_explorer.py):

    Item card:  .item-restaurant-row
    Name:       .item-restaurant-name
    Desc:       .item-restaurant-desc
    Price:      .current-price          (inside .product-price)
    Image:      .item-restaurant-img img
    Category:   .title-menu             (header, inside .menu-group wrapper)

Items are SIBLINGS of .menu-group, not children of it — .menu-group only
wraps the category header; the item list that follows is a separate
sibling element, so extraction walks forward from each .menu-group to the
next one, collecting every .item-restaurant-row it passes.
"""

from __future__ import annotations

try:
    from playwright.async_api import TimeoutError as PWTimeout
except ImportError:
    PWTimeout = Exception  # importable for non-playwright contexts (e.g. tests)

MENU_ITEM_SELECTORS = [
    ".item-restaurant-row",
    "[class*='item-restaurant-row']",
    # fallback patterns for layouts that differ from the confirmed one
    ".item-food",
    ".dish-item",
    ".food-item",
    "[class*='item-food']",
    "[class*='dish-item']",
    "ul li:has(img)",
]

_EXTRACT_JS = """(sel) => {
    const results = [];

    // --- Strategy 1: sibling-walk from .menu-group to its following .menu-restaurant-list ---
    const groups = document.querySelectorAll('.menu-group');
    if (groups.length > 0) {
        groups.forEach(group => {
            const catEl   = group.querySelector('.title-menu');
            const catName = catEl ? catEl.innerText.trim() : 'Menu';

            // Walk forward siblings until the next .menu-group
            let sibling = group.nextElementSibling;
            while (sibling && !sibling.classList.contains('menu-group')) {
                sibling.querySelectorAll(sel).forEach(el => {
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
                    results.push({
                        category:    catName,
                        name:        name,
                        description: descEl  ? descEl.innerText.trim()  : '',
                        price_raw:   priceEl ? priceEl.innerText.trim() : '',
                        image:       imgEl   ? (imgEl.src || imgEl.dataset.src || '') : '',
                    });
                });
                sibling = sibling.nextElementSibling;
            }
        });
    }

    // --- Strategy 2: flat list fallback (no .menu-group found, or items not in siblings) ---
    if (results.length === 0) {
        document.querySelectorAll(sel).forEach(el => {
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
            results.push({
                category:    'Menu',
                name:        name,
                description: descEl  ? descEl.innerText.trim()  : '',
                price_raw:   priceEl ? priceEl.innerText.trim() : '',
                image:       imgEl   ? (imgEl.src || imgEl.dataset.src || '') : '',
            });
        });
    }

    return results;
}"""

_JS_FALLBACK = """() => {
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
}"""


async def extract_menu_items(page, restaurant_url: str) -> list[dict]:
    """
    Try each confirmed selector until items are found, grouped by category.
    Returns a flat list of {category, name, description, price_raw, image, source_url}.
    """
    working_sel = None
    for sel in MENU_ITEM_SELECTORS:
        try:
            await page.wait_for_selector(sel, timeout=5_000)
            if await page.locator(sel).count() > 0:
                working_sel = sel
                break
        except PWTimeout:
            continue

    if not working_sel:
        items = await page.evaluate(_JS_FALLBACK)
    else:
        items = await page.evaluate(_EXTRACT_JS, working_sel)

    for it in items:
        it["source_url"] = restaurant_url
    return items
