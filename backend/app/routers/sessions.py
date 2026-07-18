"""Session onboarding endpoint."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from app.db.postgres import get_pool
from app.modules.language import (
    SUPPORTED_NATIVE_LANGUAGES,
    canonical_language_code,
    is_supported_native_language,
)
from app.schemas.chat import SessionCreateRequest, SessionCreateResponse

router = APIRouter()


@router.post("/sessions", response_model=SessionCreateResponse)
async def create_session(request: SessionCreateRequest) -> SessionCreateResponse:
    native_language = canonical_language_code(request.native_language)
    nationality = request.nationality.strip().upper()

    if not is_supported_native_language(native_language):
        supported = ", ".join(sorted(SUPPORTED_NATIVE_LANGUAGES))
        raise HTTPException(status_code=400, detail=f"native_language must be one of: {supported}")
    if re.fullmatch(r"[A-Z]{2}", nationality) is None:
        raise HTTPException(status_code=400, detail="nationality must be a two-letter country code")

    pool = get_pool()
    async with pool.acquire() as conn:
        session_id = await conn.fetchval(
            """
            INSERT INTO sessions (native_language, nationality)
            VALUES ($1, $2)
            RETURNING id
            """,
            native_language,
            nationality,
        )

    return SessionCreateResponse(
        session_id=str(session_id),
        native_language=native_language,
        nationality=nationality,
    )
