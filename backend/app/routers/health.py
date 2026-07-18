from typing import Any

from fastapi import APIRouter, HTTPException

from app.db.postgres import get_pool
from app.db.qdrant import get_client

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, Any]:
    dependencies: dict[str, str] = {}
    try:
        async with get_pool().acquire() as conn:
            await conn.fetchval("SELECT 1")
        dependencies["postgres"] = "ok"
    except Exception:
        dependencies["postgres"] = "unavailable"

    try:
        await get_client().get_collections()
        dependencies["qdrant"] = "ok"
    except Exception:
        dependencies["qdrant"] = "unavailable"

    if any(status != "ok" for status in dependencies.values()):
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "dependencies": dependencies},
        )
    return {"status": "ready", "dependencies": dependencies}
