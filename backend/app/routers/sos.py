"""Hardcoded emergency endpoint — deliberately NOT reachable from the agent
orchestrator. Only a direct user tap on the SOS button in the frontend should
ever call this (doc section 3 hard safety rule / section 8)."""

from fastapi import APIRouter, HTTPException

from app.db.postgres import get_pool
from app.schemas.chat import SosRequest, SosResponse

router = APIRouter()


@router.post("/sos", response_model=SosResponse)
async def sos(request: SosRequest) -> SosResponse:
    pool = get_pool()
    async with pool.acquire() as conn:
        hotlines = await conn.fetch(
            "SELECT service_type, phone_number, notes FROM emergency_hotlines WHERE region = $1",
            request.region,
        )
        embassy = await conn.fetchrow(
            "SELECT country_name, phone_number, address FROM embassies WHERE nationality = $1",
            request.nationality,
        )

    if not hotlines and embassy is None:
        raise HTTPException(status_code=404, detail="no hotline or embassy data for this region/nationality")

    return SosResponse(
        hotlines=[dict(r) for r in hotlines],
        embassy=dict(embassy) if embassy else None,
    )
