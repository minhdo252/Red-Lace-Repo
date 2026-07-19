"""
gemini_search.py
-----------------
Gemini 2.0 Flash + Google Search fallback for menu price lookup.

When the local kNN over Qdrant's item_names collection misses (no
comparable neighbor at the raised MATCH_THRESHOLD), the price pipeline
needs a web-derived reference price. This module replaces the previous
two-step Tavily search → Qwen-VL extraction with a single Gemini call
that has Google Search built in as a tool.

Output shape matches the Qwen VL menu extraction format so downstream
consumers (comparison, to_postgres, Qdrant upsert) don't need changes:

    {
        "name_raw": "<dish name>",
        "price_raw": "<price as found on the web>",
        "price_vnd": <integer VND or null>,
        "uncertain": <bool>,
        "notes": "<source info or reason for uncertainty>"
    }

Reads GEMINI_API_KEY from the environment (.env loaded by docker-compose).
"""

from __future__ import annotations

import json
import logging
import os
import re

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


def _require_api_key() -> str:
    """Read GEMINI_API_KEY from the environment. Fails clearly if unset OR
    empty, rather than letting a blank key surface as an opaque auth error."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to .env (loaded by the backend "
            "service via env_file) or export it in the environment."
        )
    return key


def _build_prompt(item: str, region: str) -> str:
    """Build the search prompt. Asks Gemini to Google-search for the item's
    price in the given region and return a JSON matching the Qwen VL menu
    extraction output shape."""
    return f"""\
Search the web for the current menu price of "{item}" at restaurants in {region}, Vietnam.

Find the most common/representative price in Vietnamese đồng (VND) from
real restaurant menus, food delivery platforms (ShopeeFood, GrabFood),
or review sites.

RULES:
1. Use ONLY prices you actually find in web search results. NEVER invent a price.
2. EXACT MATCHING: Ensure the price belongs to the exact item "{item}". Do not confuse luxury ingredients with basic ones (e.g., "tôm hùm" / lobster vs "tôm" / shrimp, or "wagyu" vs regular beef).
3. PORTION SIZE: Always price a standard, single-person serving (e.g., 1 glass/cup for drinks, 1 bowl/plate for food). Ignore prices for 1-liter bottles, pitchers, family sizes, bulk packs, or combos.
4. AMBIGUOUS ITEMS: If the item name is extremely generic (e.g., just "cơm" or "nước") and lacks specific qualifiers, it is impossible to price accurately. Set "price_vnd": null and "uncertain": true.
4. TICKET/SERVICE PRICES: For entrance tickets ("vé tham quan"), look for the standard adult entry fee. Do NOT use bundled tour prices or guided packages.
5. If multiple valid prices are found, use a representative mid-range value.
6. Normalize to integer VND: "45k" → 45000, "45.000đ" → 45000.
7. If no defensible price is found, set "price_vnd": null and "uncertain": true.
8. In "notes", include the source URL or site name where you found the price, and briefly explain what the price represents if there was ambiguity.

Return ONLY valid JSON matching exactly this schema, with no text before
or after the JSON:

{{
  "name_raw": "{item}",
  "price_raw": "<price exactly as shown on the source, e.g. '45.000đ'>",
  "price_vnd": <integer VND if unambiguous, otherwise null>,
  "uncertain": <true if no clear price found or price is doubtful, false if confident>,
  "notes": "<source site/URL where the price was found, or reason for uncertainty>"
}}
"""


async def gemini_search_price(
    item: str,
    region: str = "Hanoi",
) -> dict:
    """Search the web for a reference price of ``item`` in ``region`` using
    Gemini 2.0 Flash with the Google Search tool.

    Returns a dict in Qwen VL menu-item shape:
        {name_raw, price_raw, price_vnd, uncertain, notes}

    Always returns a dict — on failure, ``uncertain`` is True and
    ``price_vnd`` is None, so the caller can safely check those fields
    without try/except.
    """
    api_key = _require_api_key()
    client = genai.Client(api_key=api_key)

    prompt = _build_prompt(item, region)

    try:
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
    except Exception as exc:
        logger.error("Gemini search failed for %r: %s", item, exc)
        return {
            "name_raw": item,
            "price_raw": "",
            "price_vnd": None,
            "uncertain": True,
            "notes": f"gemini_search_error: {exc}",
        }

    raw_text = response.text or ""
    logger.debug("Gemini raw response for %r: %s", item, raw_text[:500])

    # Extract JSON from the response (model may wrap it in markdown fences
    # or add explanatory text despite instructions).
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        return {
            "name_raw": item,
            "price_raw": "",
            "price_vnd": None,
            "uncertain": True,
            "notes": "no_json_in_response",
        }

    try:
        data = json.loads(match.group())
    except (json.JSONDecodeError, TypeError):
        return {
            "name_raw": item,
            "price_raw": "",
            "price_vnd": None,
            "uncertain": True,
            "notes": "json_parse_error",
        }

    # Validate and normalize the parsed output.
    price_vnd = data.get("price_vnd")
    if isinstance(price_vnd, bool) or not isinstance(price_vnd, (int, float)):
        price_vnd = None
    elif price_vnd <= 0:
        price_vnd = None

    return {
        "name_raw": data.get("name_raw") or item,
        "price_raw": data.get("price_raw", ""),
        "price_vnd": int(price_vnd) if price_vnd is not None else None,
        "uncertain": bool(data.get("uncertain", price_vnd is None)),
        "notes": data.get("notes", ""),
    }


def _build_business_prompt(name: str, url: str | None, region: str) -> str:
    target = f'"{name}"' + (f" (link: {url})" if url else "")
    return f"""\
Search the web to judge whether {target}, a tour/homestay/travel operator in \
{region}, Vietnam, is a REAL and TRUSTWORTHY business or a likely SCAM ("ghost \
tour"). Look for: an established web/social presence, genuine reviews on \
Google/TripAdvisor/Facebook, official listings, AND any scam reports, \
complaints, or fraud warnings about it.

RULES:
1. Use ONLY what you actually find in search results. Never invent reviews or reports.
2. "status": "found" if it has a real, verifiable presence; "not_found" if you find \
   essentially nothing credible about it; "uncertain" if evidence is thin/mixed.
3. "legitimacy": "legitimate" (well-established, positively reviewed), "suspicious" \
   (thin presence, red flags, or fits ghost-tour patterns), or "unknown".
4. "scam_reports": true ONLY if the ESTABLISHED operator itself is reported as fraudulent. Do \
   NOT set it true merely because copycats/imitators use a similar name — a famous, well-\
   reviewed operator with impostors is still "legitimate".
5. "rating": an approximate overall rating (0-5) if you can find one, else null.
6. In "reasoning", give 1-2 concrete sentences citing what you found (site/source names).

Return ONLY valid JSON matching exactly this schema, no text before or after:

{{
  "status": "found" | "not_found" | "uncertain",
  "legitimacy": "legitimate" | "suspicious" | "unknown",
  "scam_reports": <true|false>,
  "rating": <number 0-5 or null>,
  "reasoning": "<1-2 sentences with sources>",
  "source_url": "<a representative source URL you found, or empty string>"
}}
"""


async def gemini_verify_business(name: str, url: str | None = None, region: str = "Hanoi") -> dict:
    """Verify a tour/homestay operator via Gemini + Google Search — the real,
    key-free (uses GEMINI_API_KEY) stand-in for a Google Places business check.

    Always returns a dict; on any failure ``status`` is "uncertain" and
    ``legitimacy`` "unknown" so the caller can treat it as an inconclusive
    signal without try/except.
    """
    import asyncio

    def _run() -> dict:
        api_key = _require_api_key()
        client = genai.Client(api_key=api_key)
        prompt = _build_business_prompt(name, url, region)
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        raw = response.text or ""
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {"status": "uncertain", "legitimacy": "unknown", "scam_reports": False,
                    "rating": None, "reasoning": "no_json_in_response", "source_url": ""}
        data = json.loads(match.group())
        status = data.get("status")
        if status not in ("found", "not_found", "uncertain"):
            status = "uncertain"
        legitimacy = data.get("legitimacy")
        if legitimacy not in ("legitimate", "suspicious", "unknown"):
            legitimacy = "unknown"
        rating = data.get("rating")
        if not isinstance(rating, (int, float)):
            rating = None
        return {
            "status": status,
            "legitimacy": legitimacy,
            "scam_reports": bool(data.get("scam_reports", False)),
            "rating": rating,
            "reasoning": str(data.get("reasoning", "")),
            "source_url": str(data.get("source_url", "")),
        }

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001 - inconclusive, never crash the composite
        logger.error("Gemini business verify failed for %r: %s", name, exc)
        return {"status": "uncertain", "legitimacy": "unknown", "scam_reports": False,
                "rating": None, "reasoning": f"gemini_verify_error: {exc}", "source_url": ""}
