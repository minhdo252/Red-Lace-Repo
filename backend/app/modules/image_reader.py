"""Generic vision tool (doc section 3): one tool, mode-dispatched output schema.

mode="page_transparency" gets extra post-processing here for module 2.2
signal 2 (doc section 7): the raw VLM read of a Facebook Page Transparency
screenshot is turned into the same page_age_days/risk shape
app/modules/domain_check.py already uses for WHOIS domain age, plus a
recent_name_change flag, so app/modules/ghost_tour_score.py can consume
both signals identically without doing its own date parsing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dateutil import parser as dateutil_parser

from app.ai.client import ai_client

VALID_MODES = {"receipt", "dish", "page_transparency", "chat_screenshot"}

# Mirrors app/modules/domain_check.py's WHOIS threshold — a Facebook page
# younger than this is treated as suspicious the same way a freshly
# registered domain is.
RISK_THRESHOLD_DAYS = 180


async def read_image(image_bytes: bytes, mode: str) -> dict[str, Any]:
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode {mode!r}, must be one of {sorted(VALID_MODES)}")
    result = await ai_client.vision(image_bytes, mode)
    if mode == "page_transparency":
        result = _postprocess_page_transparency(result)
    return result


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
