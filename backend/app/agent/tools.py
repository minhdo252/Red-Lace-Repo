"""Tool specs + dispatch for the orchestrator agent (doc section 3).

trigger_sos is intentionally absent from this file. It is a hardcoded,
user-clicked shortcut only (see app/routers/sos.py) — the hard safety rule
is enforced structurally: the agent has no way to call it even if a live
model hallucinates the tool name, because call_tool() only recognizes
the names below.

check_ghost_tour (module 2.2, doc section 7) is a composite tool that runs
the 5 underlying ghost-tour signals itself and returns one weighted
breakdown, rather than leaving the model to call check_domain_age /
check_business_existence / estimate_fair_price / match_scam_pattern
separately and average them by hand — the weighting is a deterministic
calculation (app/modules/ghost_tour_score.py), not something that should
vary turn to turn based on how a model happens to add up five numbers.
The individual tools stay available too, for narrower one-off questions.
"""

from __future__ import annotations

import base64
from typing import Any, Awaitable, Callable

from app.modules.business_check import check_business_existence
from app.modules.domain_check import check_domain_age
from app.modules.ghost_tour_score import check_ghost_tour
from app.modules.image_reader import read_image
from app.modules.price_comparison import compare_price
from app.modules.scam_detection import match_scam_pattern
from app.modules.translation import translate_or_get_hotline

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "compare_price",
        "description": (
            "Compare an observed price for a dish/item against a similarity-weighted "
            "reference from comparable local listings (Qdrant kNN over real embeddings, "
            "0.75 similarity gate + head-phrase gate). Falls back to a live web search "
            "when no confident local comparable exists. Only ever raises a 'higher than "
            "reference' flag with a percentage — never concludes scam on its own."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item": {"type": "string"},
                "region": {"type": "string"},
                "category": {
                    "type": "string",
                    "description": "Item category filter, e.g. 'food'. Defaults to 'food'.",
                },
                "observed_price": {
                    "type": "number",
                    "description": "Observed price in VND. Omit for a reference-only lookup.",
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
            "Transparency screenshot; mode=chat_screenshot reads a suspicious DM screenshot. "
            "Note: images attached to the current turn are already read automatically before "
            "you see this turn — only call this yourself if the user references an image from "
            "earlier in the conversation that hasn't been read yet."
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
        "name": "check_ghost_tour",
        "description": (
            "Run the full ghost-tour/homestay-scam composite check (doc section 7): combines "
            "whatever of domain age, a Page Transparency read, Google Places existence, price "
            "anomaly, and scam-pressure-language matching is available for this business/tour, "
            "and returns a weighted trust-score breakdown. Call this instead of the individual "
            "signal tools whenever the user is asking 'is this tour/homestay legit'. Never "
            "concludes scam on its own — always present the breakdown, not just the number.\n"
            "region is OPTIONAL — only the price check needs it, and that signal just reports "
            "itself unavailable (with a reason) if region is missing; every other signal works "
            "fine without it. Call this tool with whatever you actually have (even just a bare "
            "url, e.g. a Facebook link with no visible name/region) instead of asking the user "
            "for more information first — omit fields you don't have rather than filling them "
            "with a placeholder like 'N/A' or 'not provided', which would be read as real input."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "description": "Optional — only used by the price check."},
                "name": {"type": "string", "description": "Business/tour/homestay name, for the Google Places check."},
                "url": {"type": "string", "description": "Website/Facebook URL, for the WHOIS domain-age check."},
                "item": {"type": "string", "description": "What was priced (e.g. 'homestay 1 night'), for the price check."},
                "observed_price": {"type": "number", "description": "Observed/quoted price in VND, for the price check."},
                "suspicious_text": {
                    "type": "string",
                    "description": "Any pressure-sounding text from the seller, for scam-pattern matching.",
                },
            },
            # No field is unconditionally required — but at least one of
            # url/name has to be present or there's nothing to check at all.
            "anyOf": [{"required": ["url"]}, {"required": ["name"]}],
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
    "compare_price": lambda args: compare_price(**args),
    "read_image": _dispatch_read_image,
    "match_scam_pattern": lambda args: match_scam_pattern(**args),
    "check_domain_age": lambda args: check_domain_age(**args),
    "check_business_existence": lambda args: check_business_existence(**args),
    "check_ghost_tour": lambda args: check_ghost_tour(**args),
    "translate_or_get_hotline": lambda args: translate_or_get_hotline(**args),
}


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOL_DISPATCH:
        return {"error": f"unknown or disallowed tool: {name}"}
    try:
        return await TOOL_DISPATCH[name](arguments)
    except Exception as exc:  # noqa: BLE001 - surface tool errors to the agent as data, don't crash the turn
        return {"error": str(exc)}
