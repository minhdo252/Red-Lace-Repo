"""Hardcoded emergency endpoint, deliberately outside the agent tool set."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from app.db.postgres import get_pool
from app.modules.geo import nearest_location_text, resolve_region, validate_lat_lon
from app.modules.sos_routing import THREAT_TO_SERVICE_PRIORITY, sort_hotlines_by_threat
from app.schemas.chat import SosRequest, SosResponse

router = APIRouter()
logger = logging.getLogger(__name__)

NATIONAL_REGION = "Vietnam"
SOS_RATE_LIMIT_SECONDS = 5
ALLOWED_SOS_SOURCES = {"manual", "smart_trigger"}
ALLOWED_THREAT_LEVELS = {"NONE", "MEDIUM", "HIGH", "CRITICAL"}
ALLOWED_THREAT_CATEGORIES = frozenset(
    category for category in THREAT_TO_SERVICE_PRIORITY if category is not None
)
_sos_session_locks: dict[uuid.UUID, asyncio.Lock] = {}
SUPPORTED_REGIONS = {
    "hanoi": "Hanoi",
    "ha noi": "Hanoi",
    "sapa": "Sapa",
    "sa pa": "Sapa",
    "hoi an": "Hoi An",
    "h\u1ed9i an": "Hoi An",
}


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


def _threat_level(raw_level: str | None) -> str | None:
    if raw_level is None:
        return None
    level = raw_level.strip().upper()
    if level not in ALLOWED_THREAT_LEVELS:
        raise HTTPException(status_code=400, detail="threat_level must be NONE, MEDIUM, HIGH, or CRITICAL")
    return level


def _nationality(raw_nationality: str | None) -> str | None:
    if raw_nationality is None:
        return None
    nationality = raw_nationality.strip().upper()
    if re.fullmatch(r"[A-Z]{2}", nationality) is None:
        raise HTTPException(status_code=400, detail="nationality must be a two-letter country code")
    return nationality


def _threat_category(raw_category: str | None) -> str | None:
    if raw_category is None:
        return None
    category = raw_category.strip().lower()
    if not category:
        return None
    if category not in ALLOWED_THREAT_CATEGORIES:
        supported = ", ".join(sorted(ALLOWED_THREAT_CATEGORIES))
        raise HTTPException(status_code=400, detail=f"threat_category must be one of: {supported}")
    return category


def _supported_region(raw_region: str | None) -> str | None:
    if not raw_region or not raw_region.strip():
        return None
    key = " ".join(raw_region.strip().casefold().split())
    return SUPPORTED_REGIONS.get(key)


async def _existing_response_for_key(
    pool: Any,
    session_id: uuid.UUID,
    idempotency_key: str | None,
) -> SosResponse | None:
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


async def _recent_rate_limited_response(
    pool: Any,
    session_id: uuid.UUID,
    *,
    lookup_region: str,
    nationality: str,
    threat_category: str | None,
    threat_level: str | None,
    source: str,
    lat: float | None,
    lon: float | None,
) -> SosResponse | None:
    """Reuse only a recent response generated from exactly the same SOS context."""

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT response_payload
            FROM sos_events
            WHERE session_id = $1
              AND region = $2
              AND nationality = $3
              AND threat_category IS NOT DISTINCT FROM $4
              AND threat_level IS NOT DISTINCT FROM $5
              AND source = $6
              AND lat IS NOT DISTINCT FROM $7
              AND lon IS NOT DISTINCT FROM $8
              AND created_at > now() - ($9::int * interval '1 second')
            ORDER BY id DESC
            LIMIT 1
            """,
            session_id,
            lookup_region,
            nationality,
            threat_category,
            threat_level,
            source,
            lat,
            lon,
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
            json.dumps(response.model_dump(), ensure_ascii=False, default=str),
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
                json.dumps(
                    [contact.model_dump() for contact in response.contacts],
                    ensure_ascii=False,
                    default=str,
                ),
                json.dumps(response.model_dump(), ensure_ascii=False, default=str),
                datetime.now(timezone.utc),
            )
        if row:
            response.event_id = row["id"]
            await _update_event_response_payload(pool, row["id"], response)
            return None
        if request.idempotency_key:
            return await _existing_response_for_key(pool, session_id, request.idempotency_key)
    except Exception:
        logger.exception("failed to persist SOS event for session %s", session_id)
    return None


async def _load_contacts(
    pool: Any,
    *,
    resolved_region: str | None,
    nationality: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    contact_columns = "service_type, phone_number, notes, source_url, verified_at, verification_status"
    async with pool.acquire() as conn:
        if resolved_region:
            hotlines = await conn.fetch(
                f"""
                SELECT {contact_columns}
                FROM emergency_hotlines
                WHERE region = $1 OR (region = $2 AND service_type = 'general_emergency')
                ORDER BY CASE WHEN region = $1 THEN 0 ELSE 1 END, id
                """,
                resolved_region,
                NATIONAL_REGION,
            )
        else:
            hotlines = await conn.fetch(
                f"""
                SELECT {contact_columns}
                FROM emergency_hotlines
                WHERE region = $1
                ORDER BY id
                """,
                NATIONAL_REGION,
            )
        embassy = await conn.fetchrow(
            """
            SELECT country_name, phone_number, address, region_hint,
                   source_url, verified_at, verification_status
            FROM embassies
            WHERE nationality = $1
            ORDER BY id
            LIMIT 1
            """,
            nationality,
        )
    return [dict(row) for row in hotlines], dict(embassy) if embassy else None


async def _handle_sos_request_locked(
    *,
    pool: Any,
    session_id: uuid.UUID,
    request: SosRequest,
    resolved_region: str | None,
    lookup_region: str,
    region_fallback_used: bool,
    nationality: str,
    threat_category: str | None,
    threat_level: str | None,
    source: str,
    idempotency_key: str | None,
) -> SosResponse:
    """Serialize same-session SOS requests so rate limiting has no check/insert race."""

    existing_response = await _existing_response_for_key(pool, session_id, idempotency_key)
    if existing_response is not None:
        return existing_response

    recent_response = await _recent_rate_limited_response(
        pool,
        session_id,
        lookup_region=lookup_region,
        nationality=nationality,
        threat_category=threat_category,
        threat_level=threat_level,
        source=source,
        lat=request.lat,
        lon=request.lon,
    )
    if recent_response is not None:
        recent_response.event_id = None
        recent_response.idempotency_key = idempotency_key
        recent_response.rate_limited = True
        duplicate = await _log_sos_event(pool, session_id, request, recent_response, lookup_region, source)
        return duplicate or recent_response

    hotlines, embassy = await _load_contacts(
        pool,
        resolved_region=resolved_region,
        nationality=nationality,
    )
    if not hotlines and embassy is None:
        raise HTTPException(status_code=404, detail="no emergency contacts found")

    contacts = sort_hotlines_by_threat(
        hotlines=hotlines,
        embassy=embassy,
        threat_category=threat_category,
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
        idempotency_key=idempotency_key,
    )

    duplicate_response = await _log_sos_event(pool, session_id, request, response, lookup_region, source)
    return duplicate_response or response


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
    threat_level = _threat_level(request.threat_level)
    threat_category = _threat_category(request.threat_category)
    idempotency_key = request.idempotency_key.strip() if request.idempotency_key else None
    if request.idempotency_key is not None and not idempotency_key:
        raise HTTPException(status_code=400, detail="idempotency_key cannot be blank")

    pool = get_pool()
    async with pool.acquire() as conn:
        session_row = await conn.fetchrow("SELECT nationality FROM sessions WHERE id = $1", session_id)
    if session_row is None:
        raise HTTPException(status_code=404, detail="session not found")

    nationality = _nationality(request.nationality) or _nationality(session_row["nationality"])
    if nationality is None:
        raise HTTPException(status_code=400, detail="nationality is required or must exist on the session")

    explicit_region = bool(request.region and request.region.strip())
    if explicit_region:
        resolved_region = _supported_region(request.region)
    elif _has_gps(request):
        resolved_region = await resolve_region(request.lat, request.lon)  # type: ignore[arg-type]
    else:
        resolved_region = None
    lookup_region = resolved_region or NATIONAL_REGION
    region_fallback_used = resolved_region is None

    request = request.model_copy(
        update={
            "nationality": nationality,
            "threat_category": threat_category,
            "threat_level": threat_level,
            "source": source,
            "idempotency_key": idempotency_key,
        }
    )

    session_lock = _sos_session_locks.setdefault(session_id, asyncio.Lock())
    async with session_lock:
        return await _handle_sos_request_locked(
            pool=pool,
            session_id=session_id,
            request=request,
            resolved_region=resolved_region,
            lookup_region=lookup_region,
            region_fallback_used=region_fallback_used,
            nationality=nationality,
            threat_category=threat_category,
            threat_level=threat_level,
            source=source,
            idempotency_key=idempotency_key,
        )
