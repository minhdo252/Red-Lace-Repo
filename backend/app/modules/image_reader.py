"""Generic vision tool (doc section 3): one entrypoint, mode-dispatched output.

receipt/dish are handwritten-menu reads: they ALWAYS go through the real
Qwen2.5-VL menu OCR (app/ai/qwen_vl.py::ai_detect_menu), returning `ready_items`
already shaped for app/modules/price_comparison.py::compare_price (item_name +
price_vnd). Module 2.1 never falls back to the generic/mock ai_client.vision
stub for menu reads — a missing vision key (QWEN_VL_API_KEY or AI_VISION_API_KEY)
or region raises a clear error (surfaced upstream as a retake/degradation)
rather than fabricating a price.

qwen_vl is left exactly as-is: it is synchronous and reads from an image
*path*, so read_image writes the incoming bytes to a temp file and runs the
blocking OCR in a worker thread (asyncio.to_thread) to avoid stalling the
event loop.

mode="page_transparency" still goes through ai_client.vision and gets extra
post-processing here for module 2.2 signal 2 (doc section 7): the raw VLM read
of a Facebook Page Transparency screenshot is turned into the same
page_age_days/risk shape app/modules/domain_check.py already uses for WHOIS
domain age, plus a recent_name_change flag, so app/modules/ghost_tour_score.py
can consume both signals identically without doing its own date parsing.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as dateutil_parser

from app.ai.client import ai_client
from app.ai.qwen_vl import ai_detect_menu

VALID_MODES = {"receipt", "dish", "page_transparency", "chat_screenshot"}

# Menu-OCR modes: a photographed bill/menu (receipt) or a dish/menu shot (dish).
# These are the ones that carry dish names + prices worth extracting with the
# tuned Qwen VL menu OCR.
MENU_OCR_MODES = {"receipt", "dish"}

# Mirrors app/modules/domain_check.py's WHOIS threshold — a Facebook page
# younger than this is treated as suspicious the same way a freshly
# registered domain is.
RISK_THRESHOLD_DAYS = 180


async def read_image(
    image_bytes: bytes,
    mode: str,
    region: str | None = None,
    category: str = "food",
) -> dict[str, Any]:
    """Read an image and return structured text.

    receipt/dish → the real tuned Qwen VL menu OCR (Module 2.1), always. This is
    never the mock/generic ai_client.vision fallback: a missing vision key or
    region raises a clear error (surfaced upstream as a retake/degradation), so
    Module 2.1 never fabricates a price. The OCR key is resolved inside qwen_vl
    and accepts either QWEN_VL_API_KEY or the split AI_VISION_API_KEY.
    page_transparency/chat_screenshot → ai_client.vision (page_transparency is
    then post-processed into the domain-age-shaped trust signal).
    """
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode {mode!r}, must be one of {sorted(VALID_MODES)}")

    if mode in MENU_OCR_MODES:
        if not region:
            raise ValueError(f"region is required for menu OCR mode {mode!r}")
        return await _read_menu_ocr(image_bytes, mode, region, category)

    result = await ai_client.vision(image_bytes, mode)
    if mode == "page_transparency":
        result = _postprocess_page_transparency(result)
    return result


def _image_suffix(image_bytes: bytes) -> str:
    """Pick a file suffix from the image's magic bytes so qwen_vl's
    mimetype-by-extension detection (app/ai/qwen_vl.py::_encode_image) gets the
    right content-type hint instead of blindly assuming JPEG."""
    if image_bytes.startswith(b"\x89PNG"):
        return ".png"
    if image_bytes.startswith(b"\xff\xd8"):
        return ".jpg"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


async def _read_menu_ocr(
    image_bytes: bytes,
    mode: str,
    region: str,
    category: str,
) -> dict[str, Any]:
    """Bridge read_image's async, bytes-based contract to qwen_vl's synchronous,
    path-based ai_detect_menu. qwen_vl is not modified: the bytes are written to
    a temp file and the blocking OCR runs in a worker thread. Returns confident
    priced rows as `ready_items` (already in compare_price's item_name/price_vnd
    shape) and everything else as `needs_review`."""
    fd, path = tempfile.mkstemp(suffix=_image_suffix(image_bytes))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(image_bytes)
        extraction = await asyncio.to_thread(ai_detect_menu, path, region, category)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    return {
        "mode": mode,
        "source": "qwen_vl",
        "region": region,
        "category": category,
        "parse_error": extraction.parse_error,
        "unreadable_regions": extraction.unreadable_regions,
        # Confident + priced rows, already in compare_price(item, observed_price)
        # shape: item_name -> item, price_vnd -> observed_price.
        "ready_items": [
            {"item_name": row.item_name, "price_vnd": row.price_vnd}
            for row in extraction.ready_rows
        ],
        # Uncertain / unpriced reads — never auto-fed to pricing; kept so a human
        # or the model can see what could not be confidently read.
        "needs_review": [
            {
                "name_raw": item.name_raw,
                "price_raw": item.price_raw,
                "price_vnd": item.price_vnd,
                "uncertain": item.uncertain,
                "notes": item.notes,
            }
            for item in extraction.needs_review
        ],
    }


def _postprocess_page_transparency(result: dict[str, Any]) -> dict[str, Any]:
    """The VLM only reports what it can literally read off the screenshot
    (creation_date_text as free text, name_history as a list) — the actual
    age-in-days/risk-bucket arithmetic and the "has this page been renamed"
    boolean are computed here, once, rather than inside every caller."""
    creation_date_text = result.get("creation_date_text")
    name_history = result.get("name_history") or []

    page_created_date: str | None = None
    page_age_days: int | None = None
    risk = "unknown"

    if creation_date_text:
        try:
            parsed = dateutil_parser.parse(creation_date_text, fuzzy=True)
        except (ValueError, OverflowError):
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            page_created_date = parsed.isoformat()
            page_age_days = (datetime.now(timezone.utc) - parsed).days
            risk = "high" if page_age_days < RISK_THRESHOLD_DAYS else "low"

    result["page_created_date"] = page_created_date
    result["page_age_days"] = page_age_days
    result["risk"] = risk
    result["recent_name_change"] = bool(name_history)
    return result
