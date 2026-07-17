"""Session onboarding endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.db.postgres import get_pool
from app.schemas.chat import SessionCreateRequest, SessionCreateResponse

router = APIRouter()


@router.post("/sessions", response_model=SessionCreateResponse)
async def create_session(request: SessionCreateRequest) -> SessionCreateResponse:
    native_language = request.native_language.strip().lower()
    nationality = request.nationality.strip().upper()

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
