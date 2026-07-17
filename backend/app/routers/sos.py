"""Hardcoded emergency endpoint, deliberately outside the agent tool set."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from app.db.postgres import get_pool
from app.modules.geo import nearest_location_text, resolve_region, validate_lat_lon
from app.modules.sos_routing import sort_hotlines_by_threat
from app.schemas.chat import SosRequest, SosResponse

router = APIRouter()

NATIONAL_REGION = "Vietnam"
SOS_RATE_LIMIT_SECONDS = 5
ALLOWED_SOS_SOURCES = {"manual", "smart_trigger"}


def _has_gps(request: SosRequest) -> bool:
    return request.lat is not None and request.lon is not None


def _coerce_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _source(raw_source: str | None) -> str:
    source = (raw_source or "manual").strip().lower()
    if source not in ALLOWED_SOS_SOURCES:
        raise HTTPException(status_code=400, detail="source must be manual or smart_trigger")
    return source


async def _existing_response_for_key(pool: Any, session_id: uuid.UUID, idempotency_key: str | None) -> SosResponse | None:
    if not idempotency_key:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT response_payload
            FROM sos_events
            WHERE session_id = $1 AND idempotency_key = $2
            ORDER BY id DESC
            LIMIT 1
            """,
            session_id,
            idempotency_key,
        )
    if not row:
        return None
    payload = _coerce_json(row["response_payload"], None)
    return SosResponse(**payload) if isinstance(payload, dict) else None


async def _recent_rate_limited_response(pool: Any, session_id: uuid.UUID) -> SosResponse | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT response_payload
            FROM sos_events
            WHERE session_id = $1
              AND created_at > now() - ($2::int * interval '1 second')
            ORDER BY id DESC
            LIMIT 1
            """,
            session_id,
            SOS_RATE_LIMIT_SECONDS,
        )
    if not row:
        return None
    payload = _coerce_json(row["response_payload"], None)
    if not isinstance(payload, dict):
        return None
    payload["rate_limited"] = True
    return SosResponse(**payload)


async def _update_event_response_payload(pool: Any, event_id: int, response: SosResponse) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sos_events SET response_payload = $1 WHERE id = $2",
            json.dumps(response.model_dump(), ensure_ascii=False),
            event_id,
        )


async def _log_sos_event(
    pool: Any,
    session_id: uuid.UUID,
    request: SosRequest,
    response: SosResponse,
    lookup_region: str,
    source: str,
) -> SosResponse | None:
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO sos_events
                    (session_id, lat, lon, region, nationality, threat_category, threat_level,
                     source, idempotency_key, client_timestamp, location_text_vi, location_text_en,
                     contacts_returned, response_payload, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                ON CONFLICT (session_id, idempotency_key)
                WHERE idempotency_key IS NOT NULL
                DO NOTHING
                RETURNING id
                """,
                session_id,
                request.lat,
                request.lon,
                lookup_region,
                response.nationality,
                request.threat_category,
                request.threat_level,
                source,
                request.idempotency_key,
                request.client_timestamp,
                response.location_text_vi,
                response.location_text_en,
                json.dumps([contact.model_dump() for contact in response.contacts], ensure_ascii=False),
                json.dumps(response.model_dump(), ensure_ascii=False),
                datetime.now(timezone.utc),
            )
        if row:
            response.event_id = row["id"]
            await _update_event_response_payload(pool, row["id"], response)
            return None
        if request.idempotency_key:
            return await _existing_response_for_key(pool, session_id, request.idempotency_key)
    except Exception:
        return None
    return None


@router.post("/sos", response_model=SosResponse)
async def sos(request: SosRequest) -> SosResponse:
    try:
        session_id = uuid.UUID(request.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="session_id must be a valid UUID") from exc

    if (request.lat is None) != (request.lon is None):
        raise HTTPException(status_code=400, detail="lat and lon must be provided together")
    if _has_gps(request):
        try:
            validate_lat_lon(request.lat, request.lon)  # type: ignore[arg-type]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    source = _source(request.source)
    pool = get_pool()

    async with pool.acquire() as conn:
        session_row = await conn.fetchrow("SELECT nationality FROM sessions WHERE id = $1", session_id)
    if session_row is None:
        raise HTTPException(status_code=404, detail="session not found")

    existing_response = await _existing_response_for_key(pool, session_id, request.idempotency_key)
    if existing_response is not None:
        return existing_response

    recent_response = await _recent_rate_limited_response(pool, session_id)
    if recent_response is not None:
        return recent_response

    resolved_region = request.region.strip() if request.region else None
    if not resolved_region and _has_gps(request):
        resolved_region = await resolve_region(request.lat, request.lon)  # type: ignore[arg-type]
    lookup_region = resolved_region or NATIONAL_REGION
    region_fallback_used = resolved_region is None

    nationality = request.nationality.strip().upper() if request.nationality else None
    if not nationality:
        nationality = session_row["nationality"]
    if not nationality:
        raise HTTPException(status_code=400, detail="nationality is required or must exist on the session")

    async with pool.acquire() as conn:
        hotlines = await conn.fetch(
            "SELECT service_type, phone_number, notes FROM emergency_hotlines WHERE region = $1 ORDER BY id",
            lookup_region,
        )
        embassy = await conn.fetchrow(
            "SELECT country_name, phone_number, address, region_hint FROM embassies WHERE nationality = $1",
            nationality,
        )

    if not hotlines and embassy is None:
        raise HTTPException(status_code=404, detail="no emergency contacts found")

    contacts = sort_hotlines_by_threat(
        hotlines=[dict(row) for row in hotlines],
        embassy=dict(embassy) if embassy else None,
        threat_category=request.threat_category,
    )

    location_text_vi = None
    location_text_en = None
    if _has_gps(request):
        location_text_vi, location_text_en = await nearest_location_text(
            request.lat,  # type: ignore[arg-type]
            request.lon,  # type: ignore[arg-type]
        )

    response = SosResponse(
        contacts=contacts,
        location_text_vi=location_text_vi,
        location_text_en=location_text_en,
        resolved_region=resolved_region,
        region_fallback_used=region_fallback_used,
        nationality=nationality,
        idempotency_key=request.idempotency_key,
    )

    duplicate_response = await _log_sos_event(pool, session_id, request, response, lookup_region, source)
    return duplicate_response or response
