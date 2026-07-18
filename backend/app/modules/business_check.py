"""Google Places existence/reputation check (doc section 7, signal 3).

Real HTTP integration — needs GOOGLE_PLACES_API_KEY set. Returns a clear
"not_configured" status instead of failing when the key is absent, so the
orchestrator can surface that gracefully rather than crash the turn.

Google's Places API always answers with HTTP 200 and puts the real outcome
in a `status` field inside the body — a request rejected for billing
("REQUEST_DENIED"), rate-limited ("OVER_QUERY_LIMIT"), etc. comes back with
the same empty `results: []` as a business that genuinely doesn't exist
("ZERO_RESULTS"). Only `status` distinguishes them; `raise_for_status()`
never fires for any of these since they're all HTTP 200. Treating every
empty-results response as "not_found" (as this file used to) means an API
misconfiguration silently reads as "this business doesn't exist" — a false
risk signal for every business checked while the key/billing is broken.

MOCK_GOOGLE_PLACES (server env var, never client input — see app/config.py)
bypasses the real API entirely and serves canned responses from
mock_data/google_places_fixtures.json, for developing/testing the rest of
the pipeline while a real GOOGLE_PLACES_API_KEY/project is still being
sorted out (API restrictions, billing propagation, etc.). It is NOT a
substitute for the real signal — every mock response carries
`"data_source": "mock"` so nothing downstream can mistake it for a real
Google Places result, and every mock-served request is logged.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# --- review-burst detection (doc section 7, module 2.2 — reuses the same
# up-to-5 recent_reviews Google Places already returns here) ---
#
# Google's Places API surfaces at most 5 reviews per business through this
# endpoint — there is no way to see the full history, so this can only ever
# be a weak, suggestive signal on a tiny non-random sample, never proof of
# review-buying. Threshold chosen the same way Z90 was in pricing.py: no
# labeled fake-review cases exist yet to calibrate against, so pick the
# simplest defensible rule and document the reasoning for later revision.
#
#   - Only 5-star reviews count toward a "burst" — genuine mixed feedback
#     (3s and 4s mixed in) is itself evidence against a bought/scripted
#     batch, so counting all ratings would blur the signal.
#   - >=3 of the visible (<=5) reviews landing within a 3-day window is the
#     trigger. Organic reviews for a real, modestly-trafficked tourism
#     business arrive on visitors' own schedules — days to weeks apart —
#     so 3 timestamps clustering within 72 hours in a sample this small is
#     already an unusual concentration, without requiring an extreme
#     window (e.g. same-day) that would miss slower-paced fake-review runs.
REVIEW_BURST_MIN_COUNT = 3
REVIEW_BURST_WINDOW_DAYS = 3
REVIEW_BURST_MIN_RATING = 5


def _detect_review_burst(recent_reviews: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = sorted(
        r["time_unix"]
        for r in recent_reviews
        if r.get("time_unix") and r.get("rating") == REVIEW_BURST_MIN_RATING
    )
    window_seconds = REVIEW_BURST_WINDOW_DAYS * 86400

    if len(timestamps) < REVIEW_BURST_MIN_COUNT:
        return {
            "detected": False,
            "reason": (
                f"fewer than {REVIEW_BURST_MIN_COUNT} five-star reviews with a timestamp "
                "in the visible sample"
            ),
        }

    for i in range(len(timestamps) - REVIEW_BURST_MIN_COUNT + 1):
        span = timestamps[i + REVIEW_BURST_MIN_COUNT - 1] - timestamps[i]
        if span <= window_seconds:
            return {
                "detected": True,
                "reason": (
                    f"{REVIEW_BURST_MIN_COUNT}+ five-star reviews within "
                    f"{REVIEW_BURST_WINDOW_DAYS} days (visible sample only, max 5 reviews — weak signal)"
                ),
            }

    return {"detected": False, "reason": "no cluster of five-star reviews within the burst window"}

MOCK_FIXTURES_PATH = Path(__file__).parent / "mock_data" / "google_places_fixtures.json"

if settings.mock_google_places:
    logger.warning(
        "=" * 70 + "\n"
        "  MOCK_GOOGLE_PLACES=true — check_business_existence() is serving\n"
        "  CANNED data from %s\n"
        "  instead of calling the real Google Places API. Every response\n"
        "  will carry data_source=\"mock\". Do NOT use this for a real demo.\n" % MOCK_FIXTURES_PATH
        + "=" * 70
    )


def _load_mock_fixtures() -> dict[str, Any]:
    if not MOCK_FIXTURES_PATH.exists():
        logger.warning("MOCK_GOOGLE_PLACES is on but %s doesn't exist — treating as empty.", MOCK_FIXTURES_PATH)
        return {}
    return json.loads(MOCK_FIXTURES_PATH.read_text(encoding="utf-8"))


async def _resolve_facebook_redirect(url: str) -> str | None:
    """Facebook's short `/share/<id>` links carry no page name at all — the
    slug only exists on the far side of a redirect. Follow exactly one hop
    (Facebook always answers share links with a single 302) and pull a key
    out of the Location header. `profile.php?id=...` pages have no
    human-readable slug either way, so the numeric id is the best stable
    identifier available."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
    except httpx.HTTPError as exc:
        logger.warning("could not resolve Facebook share link %r: %s", url, exc)
        return None

    location = resp.headers.get("location")
    if not location:
        logger.warning("Facebook share link %r did not redirect (no Location header)", url)
        return None

    parsed = urlparse(location)
    segments = [s for s in parsed.path.split("/") if s]
    if not segments:
        return None
    if segments[0] == "profile.php":
        page_id = parse_qs(parsed.query).get("id", [None])[0]
        return f"profile.php?id={page_id}" if page_id else None
    return segments[0]


async def extract_business_key_from_url(url: str) -> str | None:
    """Same slug a human would read off the URL for a normal page link
    (facebook.com/<Slug>/...); resolves the redirect first for share links
    (facebook.com/share/<id>/...), where the slug isn't in the URL at all."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    segments = [s for s in parsed.path.split("/") if s]
    if not segments:
        return None
    if segments[0].lower() == "share":
        return await _resolve_facebook_redirect(url)
    return segments[0]


def _unknown(api_status: str | None, error_message: str | None, name: str, region: str, where: str) -> dict[str, Any]:
    logger.warning(
        "check_business_existence: Google Places %s returned status=%s error_message=%s (name=%r region=%r)",
        where, api_status, error_message, name, region,
    )
    return {
        "status": "unknown",
        "name": name,
        "region": region,
        "api_status": api_status,
        "error_message": error_message,
        "data_source": "real",
    }


async def _check_business_existence_mock(name: str, region: str | None, url: str | None) -> dict[str, Any]:
    key = await extract_business_key_from_url(url) if url else None
    if key is None:
        key = name

    logger.warning(
        "[MOCK_GOOGLE_PLACES] check_business_existence: serving mock fixture for key=%r "
        "(name=%r region=%r url=%r)",
        key, name, region, url,
    )

    fixtures = _load_mock_fixtures()
    entry = fixtures.get(key)
    if entry is None:
        logger.warning("[MOCK_GOOGLE_PLACES] no fixture for key=%r — defaulting to mock not_found", key)
        return {"status": "not_found", "name": name, "region": region, "data_source": "mock"}

    result = dict(entry)
    result["data_source"] = "mock"
    result.setdefault("name", name)
    result.setdefault("region", region)
    if result.get("status") == "found":
        result["review_burst"] = _detect_review_burst(result.get("recent_reviews", []))
    return result


async def check_business_existence(name: str, region: str | None = None, url: str | None = None) -> dict[str, Any]:
    """`region` is optional (doc section 7's ghost-tour composite check
    works without it — see app/modules/ghost_tour_score.py::check_ghost_tour
    — Google Places Text Search itself just gets a less specific query when
    it's missing). `url` is optional too and only consulted in
    MOCK_GOOGLE_PLACES mode, to derive the fixture lookup key (see module
    docstring) — it has no effect on the real Google Places call."""
    if settings.mock_google_places:
        return await _check_business_existence_mock(name, region, url)

    if not settings.google_places_api_key:
        return {"status": "not_configured", "reason": "GOOGLE_PLACES_API_KEY not set"}

    query = f"{name} {region}" if region else name

    async with httpx.AsyncClient(timeout=10) as client:
        search = await client.get(
            TEXT_SEARCH_URL,
            params={"query": query, "key": settings.google_places_api_key},
        )
        search.raise_for_status()
        search_body = search.json()
        api_status = search_body.get("status")

        if api_status == "ZERO_RESULTS":
            return {"status": "not_found", "name": name, "region": region, "data_source": "real"}

        if api_status != "OK":
            # REQUEST_DENIED, OVER_QUERY_LIMIT, INVALID_REQUEST, UNKNOWN_ERROR, ...
            # — an API-level problem, not evidence the business doesn't exist.
            return _unknown(api_status, search_body.get("error_message"), name, region, "Text Search")

        results = search_body.get("results", [])
        if not results:
            # Google's own contract says status=OK implies non-empty results;
            # don't guess "not found" if the status itself didn't say so.
            return _unknown(api_status, "status=OK but no results returned", name, region, "Text Search")

        details_resp = await client.get(
            DETAILS_URL,
            params={
                "place_id": results[0]["place_id"],
                "fields": "name,rating,user_ratings_total,reviews",
                "key": settings.google_places_api_key,
            },
        )
        details_resp.raise_for_status()
        details_body = details_resp.json()
        details_status = details_body.get("status")
        if details_status != "OK":
            return _unknown(details_status, details_body.get("error_message"), name, region, "Details")
        details = details_body.get("result", {})

    reviews = details.get("reviews", [])[:5]
    recent_reviews = [
        {
            "rating": r.get("rating"),
            "text": r.get("text"),
            "time": r.get("relative_time_description"),
            # Google's raw Unix-epoch timestamp — kept separate from the
            # human-readable "time" above because review-burst detection
            # (see _detect_review_burst) needs an actual comparable instant,
            # not a vague string like "a week ago".
            "time_unix": r.get("time"),
        }
        for r in reviews
    ]
    return {
        "status": "found",
        "name": details.get("name", name),
        "rating": details.get("rating"),
        "review_count": details.get("user_ratings_total"),
        "recent_reviews": recent_reviews,
        "review_burst": _detect_review_burst(recent_reviews),
        "data_source": "real",
    }
