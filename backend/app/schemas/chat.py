from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: Any


class SessionCreateRequest(BaseModel):
    native_language: str = Field(..., min_length=2, max_length=32)
    nationality: str = Field(..., min_length=2, max_length=8)


class SessionCreateResponse(BaseModel):
    session_id: str
    native_language: str
    nationality: str


class ChatRequest(BaseModel):
    session_id: str
    text: str | None = None
    audio_base64: str | None = None
    audio_format: str = "webm"
    audio_language_hint: str | None = None
    speaker_role: str | None = None
    chunk_sequence_id: int | None = None
    is_final_chunk: bool = True
    lat: float | None = None
    lon: float | None = None
    region: str | None = None
    history: list[ChatMessage] = Field(default_factory=list)
    images: list[ImagePayload] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    tools_invoked: list[dict[str, Any]] = Field(default_factory=list)
    critic: dict[str, Any] | None = None
    source_text: str | None = None
    translation: str | None = None
    translation_details: dict[str, Any] | None = None
    detected_language: str | None = None
    target_language: str | None = None
    speaker_split: list[dict[str, Any]] = Field(default_factory=list)
    normalized_prices_vnd: list[int] = Field(default_factory=list)
    scam_flags: list[dict[str, Any]] = Field(default_factory=list)
    scam_prefilter_status: dict[str, Any] | None = None
    threat: dict[str, Any] | None = None
    chunk_sequence_id: int | None = None
    is_final_chunk: bool = True
    resolved_region: str | None = None
    server_turn_id: str | None = None


class SosRequest(BaseModel):
    session_id: str
    lat: float | None = None
    lon: float | None = None
    region: str | None = None
    nationality: str | None = None
    threat_category: str | None = None
    threat_level: str | None = None
    source: str | None = None
    idempotency_key: str | None = None
    client_timestamp: datetime | None = None


class SosContact(BaseModel):
    service_type: str
    phone_number: str
    notes: str | None = None
    country_name: str | None = None
    address: str | None = None
    region_hint: str | None = None
    is_primary: bool = False
    priority_rank: int = 99


class SosResponse(BaseModel):
    contacts: list[SosContact]
    location_text_vi: str | None = None
    location_text_en: str | None = None
    resolved_region: str | None = None
    region_fallback_used: bool = False
    nationality: str | None = None
    event_id: int | None = None
    idempotency_key: str | None = None
    rate_limited: bool = False
