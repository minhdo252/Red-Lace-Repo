from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

from app.config import settings

COLLECTIONS = {
    # payload: {region, category, postgres_id}
    "item_names": ["region", "category"],
    # payload: {category}  category in {price_scam, ghost_tour_pressure}
    "scam_patterns": ["category"],
    # payload: {region, category_guess, created_at} — reports that didn't match any
    # known scam_patterns point closely enough (see doc section 6.2)
    "unmatched_reports": ["region", "category_guess"],
}

_client: AsyncQdrantClient | None = None


def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    return _client


async def ensure_collections() -> None:
    client = get_client()
    existing = {c.name for c in (await client.get_collections()).collections}
    for name, payload_fields in COLLECTIONS.items():
        if name not in existing:
            await client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
            )
        for field in payload_fields:
            await client.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
