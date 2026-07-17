"""
vn_embedding.py
---------------
Embeds price_references.item_name (Postgres) via FPT Cloud's
Vietnamese_Embedding model and upserts the vectors into Qdrant's
item_names collection.

This is the lookup step doc section 6.1 depends on: an OCR/VLM-read dish
name rarely matches a price_references.item_name string exactly (e.g.
"Phở Bò" vs "pho bo tai dac biet"), so estimate_fair_price()
(app/modules/pricing.py) does a Qdrant kNN over these vectors, filtered by
region, to find the closest priced item, then reads mu_post/tau_post back
from Postgres using the payload's postgres_id.

One Qdrant point per price_references row: point id = row id, vector =
embedding of item_name, payload = {region, category, postgres_id}.

EMBEDDING_DIM (.env) must equal this model's output size (1024) — the
item_names collection is created at that size by ensure_collections();
if it already exists at a different size, delete it first (it only holds
a derived index, safe to rebuild from Postgres).

Reads the API key from VN_EMBEDDING_API_KEY. Run standalone (from
backend/, so `app` resolves as a package):
    POSTGRES_DSN=... QDRANT_URL=... VN_EMBEDDING_API_KEY=... \\
        python -m app.ai.vn_embedding

Or via Docker:
    docker compose run --rm backend python -m app.ai.vn_embedding
"""

from __future__ import annotations

import asyncio
import os

from openai import OpenAI
from qdrant_client.models import PointStruct

from app.config import settings
from app.db.postgres import close_pool, get_pool, init_pool
from app.db.qdrant import ensure_collections, get_client

BASE_URL = "https://mkp-api.fptcloud.com"
MODEL_NAME = "Vietnamese_Embedding"
BATCH_SIZE = 64  # item_names per embedding API call / Qdrant upsert


def _embed_batch(client: OpenAI, texts: list[str], input_type: str = "passage") -> list[list[float]]:
    """input_type='passage' for text being indexed (embed_price_references),
    'query' for text being searched with (embed_qwen_vl_ready_rows) — this
    model does asymmetric retrieval, so the two sides are embedded
    differently even though the API call shape is otherwise identical."""
    response = client.embeddings.create(
        model=MODEL_NAME,
        input=texts,
        dimensions=settings.embedding_dim,
        encoding_format="float",
        # input_text_truncate/input_type aren't part of the standard OpenAI
        # embeddings schema — FPT Cloud's endpoint reads them as extra body
        # fields, so they must go through extra_body rather than as direct
        # kwargs (the SDK validates top-level kwargs against the standard
        # schema and rejects unknown ones).
        extra_body={"input_text_truncate": "none", "input_type": input_type},
    )
    return [d.embedding for d in response.data]


def _require_api_key() -> str:
    """Read VN_EMBEDDING_API_KEY from the environment (loaded from .env by the
    backend/seed services via env_file). Fails clearly if unset OR empty,
    rather than letting a blank key surface as an opaque auth error later."""
    key = os.getenv("VN_EMBEDDING_API_KEY")
    if not key:
        raise RuntimeError(
            "VN_EMBEDDING_API_KEY is not set. Add it to .env (loaded by the "
            "backend service via env_file) or export it in the environment."
        )
    return key


def embed_query_texts(texts: list[str]) -> list[list[float]]:
    """Embed arbitrary strings as Qdrant *query* vectors (input_type='query'),
    e.g. a dish name being looked up against item_names before/without it
    necessarily being its own price_references row yet. Use this — not
    embed_price_references()'s passage path — for anything that's
    searching rather than being indexed; this model does asymmetric
    retrieval, so mixing the two up degrades matching quality.
    """
    if not texts:
        return []
    api_key = _require_api_key()
    client = OpenAI(api_key=api_key, base_url=BASE_URL)
    return _embed_batch(client, texts, input_type="query")


def embed_qwen_vl_ready_rows(ready_rows: list) -> list[list[float]]:
    """Embed item_name from qwen_vl.py::ai_detect_menu()'s
    MenuExtractionResult.ready_rows (list[PriceReferenceRow]) as Qdrant
    query vectors — see embed_query_texts(). Returns one vector per
    ready_row, in the same order; does not touch Qdrant/Postgres itself.
    """
    if not ready_rows:
        return []
    return embed_query_texts([row.item_name for row in ready_rows])


async def _ensure_item_names_dimension(qdrant) -> None:
    """ensure_collections() only creates item_names if it's missing — if it
    already exists at a stale vector size (e.g. the backend service started
    up once before EMBEDDING_DIM was set to match this model), recreate it.
    It only holds a derived index over price_references, so rebuilding it
    from scratch here is always safe (no data lives in it that isn't
    already in Postgres)."""
    info = await qdrant.get_collection("item_names")
    current_size = info.config.params.vectors.size
    if current_size != settings.embedding_dim:
        print(f"[!] item_names was {current_size}-dim, recreating at {settings.embedding_dim}-dim")
        await qdrant.delete_collection("item_names")
        await ensure_collections()


async def embed_price_references() -> int:
    """Embed every price_references row's item_name and upsert into
    Qdrant's item_names collection. Returns the number of points upserted."""
    api_key = _require_api_key()
    openai_client = OpenAI(api_key=api_key, base_url=BASE_URL)

    await init_pool()
    await ensure_collections()
    pool = get_pool()
    qdrant = get_client()
    await _ensure_item_names_dimension(qdrant)

    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, item_name, region, category FROM price_references")

    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        vectors = _embed_batch(openai_client, [row["item_name"] for row in batch])
        points = [
            PointStruct(
                id=row["id"],
                vector=vector,
                payload={
                    "region": row["region"],
                    "category": row["category"],
                    "postgres_id": row["id"],
                },
            )
            for row, vector in zip(batch, vectors)
        ]
        await qdrant.upsert(collection_name="item_names", points=points)
        total += len(points)
        print(f"[~] Embedded + upserted {total}/{len(rows)} item_names")

    return total


async def main() -> None:
    try:
        total = await embed_price_references()
        print(f"[✓] Done — {total} price_references rows embedded into Qdrant item_names.")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
