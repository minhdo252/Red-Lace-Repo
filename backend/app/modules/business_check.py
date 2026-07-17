"""Google Places existence/reputation check (doc section 7, signal 3).

Real HTTP integration — needs GOOGLE_PLACES_API_KEY set. Returns a clear
"not_configured" status instead of failing when the key is absent, so the
orchestrator can surface that gracefully rather than crash the turn.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings

TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


async def check_business_existence(name: str, region: str) -> dict[str, Any]:
    if not settings.google_places_api_key:
        return {"status": "not_configured", "reason": "GOOGLE_PLACES_API_KEY not set"}

    async with httpx.AsyncClient(timeout=10) as client:
        search = await client.get(
            TEXT_SEARCH_URL,
            params={"query": f"{name} {region}", "key": settings.google_places_api_key},
        )
        search.raise_for_status()
        results = search.json().get("results", [])
        if not results:
            return {"status": "not_found", "name": name, "region": region}

        details_resp = await client.get(
            DETAILS_URL,
            params={
                "place_id": results[0]["place_id"],
                "fields": "name,rating,user_ratings_total,reviews",
                "key": settings.google_places_api_key,
            },
        )
        details_resp.raise_for_status()
        details = details_resp.json().get("result", {})

    reviews = details.get("reviews", [])[:5]
    return {
        "status": "found",
        "name": details.get("name", name),
        "rating": details.get("rating"),
        "review_count": details.get("user_ratings_total"),
        "recent_reviews": [
            {
                "rating": r.get("rating"),
                "text": r.get("text"),
                "time": r.get("relative_time_description"),
            }
            for r in reviews
        ],
    }
