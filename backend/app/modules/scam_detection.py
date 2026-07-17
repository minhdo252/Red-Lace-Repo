"""Scam pattern matching + new-pattern candidate capture (doc sections 3, 6.2)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct

from app.ai.client import ai_client
from app.db.qdrant import get_client

UNMATCHED_THRESHOLD = 0.6


async def match_scam_pattern(text: str, category: str, region: str | None = None) -> dict[str, Any]:
    vector = await ai_client.embed(text)
    client = get_client()
    hits = (
        await client.query_points(
            collection_name="scam_patterns",
            query=vector,
            query_filter=Filter(must=[FieldCondition(key="category", match=MatchValue(value=category))]),
            limit=5,
        )
    ).points

    best_score = hits[0].score if hits else 0.0
    result: dict[str, Any] = {
        "category": category,
        "matches": [{"score": h.score, "payload": h.payload} for h in hits],
        "best_score": best_score,
        "flagged_as_new_candidate": best_score < UNMATCHED_THRESHOLD,
    }

    if result["flagged_as_new_candidate"]:
        await client.upsert(
            collection_name="unmatched_reports",
            points=[
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={
                        "transcript": text,
                        "region": region,
                        "category_guess": category,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            ],
        )

    return result
