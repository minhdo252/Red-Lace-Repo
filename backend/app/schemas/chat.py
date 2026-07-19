from datetime import datetime
from typing import Any
from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=8000)


class ImagePayload(BaseModel):
    """Shared chat attachment contract required by the orchestrator."""

    image_base64: str
    mode: str


class SessionCreateRequest(BaseModel):
    native_language: str = Field(..., min_length=2, max_length=32)
    nationality: str = Field(..., min_length=2, max_length=8)


class SessionCreateResponse(BaseModel):
    session_id: str
    native_language: str
    nationality: str


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    text: str | None = Field(default=None, max_length=8000)
    audio_base64: str | None = Field(default=None, max_length=14_100_000)
    audio_format: str = Field(default="webm", min_length=1, max_length=32)
    audio_language_hint: str | None = Field(default=None, max_length=16)
    speaker_role: str | None = Field(default=None, max_length=16)
    chunk_sequence_id: int | None = None
    is_final_chunk: bool = True
    lat: float | None = None
    lon: float | None = None
    region: str | None = Field(default=None, max_length=64)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    images: list[ImagePayload] = Field(default_factory=list)


class TextChatRequest(BaseModel):
    """Typed-chat contract that shares Module 1's complete processing pipeline."""

    session_id: str = Field(..., min_length=1, max_length=64)
    text: str = Field(..., min_length=1, max_length=8000)
    speaker_role: str | None = Field(default=None, max_length=16)
    chunk_sequence_id: int | None = None
    lat: float | None = None
    lon: float | None = None
    region: str | None = Field(default=None, max_length=64)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


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
    # Input-type routing (see docs/superpowers/specs/2026-07-18-chat-input-routing-design.md):
    # which deterministic route handled the turn, and the image route's retake signal +
    # structured price verdict.
    input_route: Literal["text", "voice", "image"] | None = None
    needs_retake: bool = False
    retake_reason: str | None = None
    price_analysis: dict[str, Any] | None = None
    ghost_tour_analysis: dict[str, Any] | None = None
    chunk_sequence_id: int | None = None
    is_final_chunk: bool = True
    resolved_region: str | None = None
    server_turn_id: str | None = None
    degraded_components: list[str] = Field(default_factory=list)
    processing_time_ms: int | None = Field(default=None, ge=0)


class SosRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    lat: float | None = None
    lon: float | None = None
    region: str | None = Field(default=None, max_length=64)
    nationality: str | None = Field(default=None, max_length=8)
    threat_category: str | None = Field(default=None, max_length=64)
    threat_level: str | None = Field(default=None, max_length=16)
    source: str | None = Field(default=None, max_length=16)
    idempotency_key: str | None = Field(default=None, max_length=128)
    client_timestamp: datetime | None = None


class SosContact(BaseModel):
    service_type: str
    phone_number: str
    notes: str | None = None
    country_name: str | None = None
    address: str | None = None
    region_hint: str | None = None
    source_url: str | None = None
    verified_at: datetime | None = None
    verification_status: str = "unverified"
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
