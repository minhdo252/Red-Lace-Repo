"""Tool specs + dispatch for the orchestrator agent (doc section 3).

trigger_sos is intentionally absent from this file. It is a hardcoded,
user-clicked shortcut only (see app/routers/sos.py) — the hard safety rule
is enforced structurally: the agent has no way to call it even if a live
model hallucinates the tool name, because call_tool() only recognizes
the names below.
"""

from __future__ import annotations

import base64
from typing import Any, Awaitable, Callable

from app.modules.business_check import check_business_existence
from app.modules.domain_check import check_domain_age
from app.modules.image_reader import read_image
from app.modules.pricing import estimate_fair_price
from app.modules.scam_detection import match_scam_pattern
from app.modules.translation import translate_or_get_hotline

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "estimate_fair_price",
        "description": (
            "Estimate whether an observed price is fair for an item in a region using "
            "Bayesian fusion of an LLM prior and historical data. Only ever raises a "
            "'higher than reference' flag with a confidence level — never concludes "
            "scam or not-scam on its own."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item": {"type": "string"},
                "region": {"type": "string"},
                "observed_price": {
                    "type": "number",
                    "description": "Observed price in VND. Omit for a quote-only lookup.",
                },
            },
            "required": ["item", "region"],
        },
    },
    {
        "name": "read_image",
        "description": (
            "Read an image and return structured text. mode=receipt|dish reads a "
            "bill/menu/dish photo; mode=page_transparency reads a Facebook Page "
            "Transparency screenshot; mode=chat_screenshot reads a suspicious DM screenshot."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image_base64": {"type": "string", "description": "Base64-encoded image bytes"},
                "mode": {
                    "type": "string",
                    "enum": ["receipt", "dish", "page_transparency", "chat_screenshot"],
                },
            },
            "required": ["image_base64", "mode"],
        },
    },
    {
        "name": "match_scam_pattern",
        "description": "kNN match free text against known scam patterns for a category.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "category": {"type": "string", "enum": ["price_scam", "ghost_tour_pressure"]},
                "region": {"type": "string"},
            },
            "required": ["text", "category"],
        },
    },
    {
        "name": "check_domain_age",
        "description": "WHOIS lookup: domain registration age, as a ghost-business risk signal.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "check_business_existence",
        "description": "Google Places lookup: rating, review count, recent reviews for a named business.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "region": {"type": "string"}},
            "required": ["name", "region"],
        },
    },
    {
        "name": "translate_or_get_hotline",
        "description": (
            "Translate text and look up emergency hotlines (by region) and embassy "
            "contact (by nationality — never inferred from language)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "region": {"type": "string"},
                "nationality": {"type": "string"},
                "native_language": {
                    "type": "string",
                    "description": "Tourist's preferred/native language from session context, e.g. ko, en, zh, ja.",
                },
            },
            "required": ["text", "region", "nationality"],
        },
    },
]


async def _dispatch_read_image(args: dict[str, Any]) -> dict[str, Any]:
    image_bytes = base64.b64decode(args["image_base64"])
    return await read_image(image_bytes, args["mode"])


TOOL_DISPATCH: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "estimate_fair_price": lambda args: estimate_fair_price(**args),
    "read_image": _dispatch_read_image,
    "match_scam_pattern": lambda args: match_scam_pattern(**args),
    "check_domain_age": lambda args: check_domain_age(**args),
    "check_business_existence": lambda args: check_business_existence(**args),
    "translate_or_get_hotline": lambda args: translate_or_get_hotline(**args),
}


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOL_DISPATCH:
        return {"error": f"unknown or disallowed tool: {name}"}
    try:
        return await TOOL_DISPATCH[name](arguments)
    except Exception as exc:  # noqa: BLE001 - surface tool errors to the agent as data, don't crash the turn
        return {"error": str(exc)}
