"""
seed_scam_patterns.py
----------------------
One-shot seeding agent: loads the draft scam-pattern corpus in
agent/seed_data/*.json, embeds each phrase, and upserts them into the
Qdrant `scam_patterns` collection (payload: category, text, lang).

Feeds:
    - category="price_scam"          (doc section 6.2 — was never actually
      seeded by anything in the original repo)
    - category="ghost_tour_pressure" (module 2.2 signal 5, doc section 7)

WHEN THIS RUNS
    Wired into docker-compose.yml as the `seed-scam-patterns` service,
    which `backend` depends on completing — same pattern as `seed-crawler`
    (app/agent/seed_price_references.py).

    "Don't re-do slow work": for each category, skip embedding+upserting
    if that category already has at least as many points in Qdrant as the
    corpus file has entries. Always exits 0 — a seeding failure never
    blocks the rest of the stack from starting.

Run standalone (needs Qdrant reachable):
    QDRANT_URL=http://localhost:6333 python -m app.agent.seed_scam_patterns

Run via Docker:
    docker compose run --rm seed-scam-patterns

IMPORTANT: the corpus files in seed_data/ are a Claude-drafted starting
point ("người hiểu thực tế duyệt lại" per the plan this patch implements),
not vetted ground truth — review/edit them before relying on this for a
real demo. See this patch's README.md.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct

from app.ai.client import ai_client
from app.db.qdrant import ensure_collections, get_client

SEED_DATA_DIR = Path(__file__).parent / "seed_data"
CORPUS_FILES = ["price_scam.json", "ghost_tour_pressure.json"]


def load_corpus() -> list[dict]:
    entries: list[dict] = []
    for filename in CORPUS_FILES:
        path = SEED_DATA_DIR / filename
        if not path.exists():
            print(f"[!] {path} not found — skipping.")
            continue
        entries.extend(json.loads(path.read_text(encoding="utf-8")))
    return entries


async def already_seeded(client, category: str) -> int:
    result = await client.count(
        collection_name="scam_patterns",
        count_filter=Filter(must=[FieldCondition(key="category", match=MatchValue(value=category))]),
    )
    return result.count


async def seed_category(client, category: str, entries: list[dict]) -> int:
    existing = await already_seeded(client, category)
    if existing >= len(entries):
        print(
            f"[✓] scam_patterns/{category} already has {existing} points "
            f"(corpus has {len(entries)}) — skipping."
        )
        return 0

    points = []
    for entry in entries:
        vector = await ai_client.embed(entry["text"])
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload={"category": category, "text": entry["text"], "lang": entry.get("lang")},
            )
        )
    await client.upsert(collection_name="scam_patterns", points=points)
    print(f"[✓] Seeded {len(points)} {category} patterns.")
    return len(points)


async def main() -> None:
    print("=" * 60)
    print("  scam_patterns SEEDING AGENT")
    print("=" * 60)

    entries = load_corpus()
    if not entries:
        print("[!] No corpus entries found — nothing to seed.")
        return

    by_category: dict[str, list[dict]] = {}
    for entry in entries:
        by_category.setdefault(entry["category"], []).append(entry)

    try:
        client = get_client()
        await ensure_collections()
    except Exception as e:
        print(f"[!] Could not reach Qdrant ({e}) — skipping seed.")
        return  # exit 0: never block the stack from starting

    total = 0
    for category, category_entries in by_category.items():
        try:
            total += await seed_category(client, category, category_entries)
        except Exception as e:
            print(f"[!] Failed seeding category={category} ({e}) — continuing with other categories.")

    print(f"[✓] Done. {total} new points inserted this run.")


if __name__ == "__main__":
    asyncio.run(main())
