"""Chat endpoint for live translation, scam pre-filter, and threat detection."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.agent.orchestrator import handle_turn
from app.ai.client import ai_client
from app.db.postgres import get_pool
from app.modules.audio_pipe import preprocess_audio_for_stt
from app.modules.geo import resolve_region, validate_lat_lon
from app.modules.memory import trigger_background_compression
from app.modules.pii import redact_pii
from app.modules.scam_detection import match_scam_pattern
from app.modules.threat_detection import detect_threat
from app.modules.translation import translate_text
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()

SCAM_PREFILTER_THRESHOLD = 0.6
DEFAULT_REGION = "Hanoi"
SERVER_HISTORY_LIMIT = 12
ALLOWED_SPEAKER_ROLES = {"tourist", "vendor", "unknown"}

REGION_GLOSSARY: dict[str, list[str]] = {
    "Hanoi": ["Pho Thin", "bun cha", "Hoan Kiem", "Old Quarter", "xich lo", "dong", "nghin", "trieu"],
    "Sapa": ["Fansipan", "Ham Rong", "Cat Cat", "Ta Van", "bac ha", "dong", "nghin", "trieu"],
    "Hoi An": ["cao lau", "banh mi", "Ancient Town", "An Bang", "Thu Bon", "dong", "nghin", "trieu"],
}

FALLBACK_SCAM_RULES: list[dict[str, Any]] = [
    {
        "category": "price_scam",
        "confidence": 0.72,
        "patterns": [
            r"\b[5-9]\d{2}\s*k\b.*\b(1|2|3|4|5)\s*km\b",
            r"\b(pay|charge|cost)\b.*\b(500k|600k|700k|800k|900k|million)\b",
            r"\b(too expensive|overcharge|rip\s*off)\b",
            r"\b(gấp|gap)\s*(5|10|mười|muoi)\b",
        ],
    },
    {
        "category": "ghost_tour_pressure",
        "confidence": 0.68,
        "patterns": [
            r"\b(pay|deposit|transfer)\b.*\b(now|right now|immediately)\b",
            r"\b(only today|last chance|no refund|private deal)\b",
            r"\b(zalo|telegram|whatsapp)\b.*\b(deposit|transfer|pay)\b",
            r"\b(đặt cọc|dat coc|chuyển khoản|chuyen khoan)\b.*\b(ngay|liền|lien)\b",
        ],
    },
]


def _coerce_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _coerce_history(value: Any) -> list[dict[str, Any]]:
    parsed = _coerce_json(value, [])
    return parsed if isinstance(parsed, list) else []


def _travel_glossary_prompt(region: str, native_language: str, nationality: str) -> str:
    terms = REGION_GLOSSARY.get(region, []) + REGION_GLOSSARY.get(DEFAULT_REGION, [])
    unique_terms = ", ".join(dict.fromkeys(terms))
    return (
        "Vietnam travel conversation. Preserve menu item names, place names, "
        f"prices, and currency units. Region={region}; tourist_language={native_language}; "
        f"tourist_nationality={nationality}. Common local terms: {unique_terms}."
    )


def _speaker_role(raw_role: str | None) -> str:
    role = (raw_role or "unknown").strip().lower()
    if role not in ALLOWED_SPEAKER_ROLES:
        raise HTTPException(
            status_code=400,
            detail="speaker_role must be one of: tourist, vendor, unknown",
        )
    return role


def _audio_language_hint(request: ChatRequest, speaker_role: str, native_language: str) -> str | None:
    if request.audio_language_hint:
        hint = request.audio_language_hint.strip().lower()
        return None if hint in {"auto", "none", "unknown"} else hint
    if speaker_role == "vendor":
        return "vi"
    if speaker_role == "tourist":
        return native_language
    return None


def _rule_based_scam_flags(text: str) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    text_lower = text.lower()
    for rule in FALLBACK_SCAM_RULES:
        for pattern in rule["patterns"]:
            match = re.search(pattern, text_lower, flags=re.IGNORECASE)
            if match:
                flags.append(
                    {
                        "category": rule["category"],
                        "best_score": rule["confidence"],
                        "source": "rule_fallback",
                        "matched_text": match.group(0),
                    }
                )
                break
    return flags


async def _scan_single_scam_category(text: str, category: str, region: str | None) -> dict[str, Any]:
    try:
        result = await match_scam_pattern(text, category=category, region=region)
        result["status"] = "ok"
        return result
    except Exception as exc:  # noqa: BLE001 - pre-filter should not block chat
        return {"category": category, "error": str(exc), "matches": [], "best_score": 0.0, "status": "error"}


def _merge_scam_flags(vector_flags: list[dict[str, Any]], rule_flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for flag in vector_flags + rule_flags:
        category = str(flag.get("category") or "unknown")
        current = merged.get(category)
        if current is None or float(flag.get("best_score") or 0.0) > float(current.get("best_score") or 0.0):
            merged[category] = flag
    return list(merged.values())


async def _scan_scam_prefilter(text: str, region: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    price_result, pressure_result = await asyncio.gather(
        _scan_single_scam_category(text, "price_scam", region),
        _scan_single_scam_category(text, "ghost_tour_pressure", region),
    )

    vector_flags: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for result in (price_result, pressure_result):
        if result.get("status") == "error":
            errors.append({"category": str(result.get("category")), "error": str(result.get("error"))})
        best_score = float(result.get("best_score") or 0.0)
        if best_score >= SCAM_PREFILTER_THRESHOLD:
            matches = result.get("matches") or []
            vector_flags.append(
                {
                    "category": result.get("category"),
                    "best_score": best_score,
                    "source": "qdrant_vector",
                    "top_match": matches[0].get("payload") if matches else None,
                }
            )

    rule_flags = _rule_based_scam_flags(text)
    flags = _merge_scam_flags(vector_flags, rule_flags)
    status = {
        "mode": "qdrant_vector_plus_rule_fallback",
        "qdrant_ok": not errors,
        "errors": errors,
        "rule_fallback_used": bool(rule_flags),
        "categories_checked": ["price_scam", "ghost_tour_pressure"],
    }
    return flags, status


async def _load_recent_chat_history(pool: Any, session_id: uuid.UUID) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT source_text, reply
            FROM chat_turns
            WHERE session_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            session_id,
            SERVER_HISTORY_LIMIT,
        )
    messages: list[dict[str, Any]] = []
    for row in reversed(rows):
        messages.append({"role": "user", "content": row["source_text"]})
        if row["reply"]:
            messages.append({"role": "assistant", "content": row["reply"]})
    return messages


async def _fetch_existing_chunk_response(
    pool: Any,
    session_id: uuid.UUID,
    chunk_sequence_id: int | None,
) -> ChatResponse | None:
    if chunk_sequence_id is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT response_payload
            FROM chat_turns
            WHERE session_id = $1 AND chunk_sequence_id = $2
            """,
            session_id,
            chunk_sequence_id,
        )
    if not row:
        return None
    payload = _coerce_json(row["response_payload"], None)
    return ChatResponse(**payload) if isinstance(payload, dict) else None


async def _translate_for_chat(
    text: str,
    nationality: str,
    native_language: str,
    history_context: list[str],
) -> dict[str, Any]:
    try:
        return await translate_text(
            text,
            nationality=nationality,
            native_language=native_language,
            history_context=history_context,
        )
    except Exception as exc:  # noqa: BLE001 - chat must return a deterministic translation envelope
        return {
            "detected_language": "unknown",
            "source_text_clean": text,
            "translated_text": text,
            "target_language": native_language,
            "key_entities": [],
            "normalized_prices_vnd": [],
            "speaker_split": [],
            "error": str(exc),
        }


async def _persist_chat_turn(
    pool: Any,
    session_id: uuid.UUID,
    request: ChatRequest,
    source_text: str,
    clean_text: str,
    region: str,
    response: ChatResponse,
) -> ChatResponse | None:
    turn_id = uuid.uuid4()
    response.server_turn_id = str(turn_id)
    payload = response.model_dump()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO chat_turns
                    (id, session_id, chunk_sequence_id, source_text, clean_text, reply,
                     translation, threat, scam_flags, region, response_payload)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (session_id, chunk_sequence_id)
                WHERE chunk_sequence_id IS NOT NULL
                DO NOTHING
                RETURNING id
                """,
                turn_id,
                session_id,
                request.chunk_sequence_id,
                source_text,
                clean_text,
                response.reply,
                json.dumps(response.translation_details or {}, ensure_ascii=False),
                json.dumps(response.threat or {}, ensure_ascii=False),
                json.dumps(response.scam_flags, ensure_ascii=False),
                region,
                json.dumps(payload, ensure_ascii=False),
            )
        if row:
            return None
        return await _fetch_existing_chunk_response(pool, session_id, request.chunk_sequence_id)
    except Exception:
        return None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, background_tasks: BackgroundTasks) -> ChatResponse:
    try:
        session_id = uuid.UUID(request.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="session_id must be a valid UUID") from exc

    if request.chunk_sequence_id is not None and request.chunk_sequence_id < 0:
        raise HTTPException(status_code=400, detail="chunk_sequence_id must be non-negative")

    speaker_role = _speaker_role(request.speaker_role)

    pool = get_pool()
    async with pool.acquire() as conn:
        session = await conn.fetchrow(
            "SELECT native_language, nationality, compressed_history FROM sessions WHERE id = $1",
            session_id,
        )
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    existing_response = await _fetch_existing_chunk_response(pool, session_id, request.chunk_sequence_id)
    if existing_response is not None:
        return existing_response

    if (request.lat is None) != (request.lon is None):
        raise HTTPException(status_code=400, detail="lat and lon must be provided together")
    if request.lat is not None and request.lon is not None:
        try:
            validate_lat_lon(request.lat, request.lon)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    region = request.region.strip() if request.region else None
    if not region and request.lat is not None and request.lon is not None:
        region = await resolve_region(request.lat, request.lon)
    region = region or DEFAULT_REGION

    native_language = session["native_language"]
    nationality = session["nationality"]
    raw_text = request.text or ""
    if request.audio_base64:
        try:
            wav_bytes = preprocess_audio_for_stt(request.audio_base64, input_format=request.audio_format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raw_text = await ai_client.transcribe(
            wav_bytes,
            language_hint=_audio_language_hint(request, speaker_role, native_language),
            initial_prompt=_travel_glossary_prompt(region, native_language, nationality),
        )

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="text or audio_base64 is required")

    clean_text = redact_pii(raw_text)
    request_history = [message.model_dump() for message in request.history]
    server_history = await _load_recent_chat_history(pool, session_id)
    base_history = request_history or server_history or _coerce_history(session["compressed_history"])
    active_history = trigger_background_compression(request.session_id, base_history, background_tasks)
    session_context = {
        "role": "system",
        "content": (
            "Session context for tool calls: "
            f"native_language={native_language}; "
            f"nationality={nationality}; "
            f"region={region}; "
            f"speaker_role={speaker_role}. "
            "When translating, use native_language as the tourist target language. "
            "When looking up emergency contacts, use nationality and region exactly from this context."
        ),
    }
    orchestrator_history = [session_context] + active_history
    context_text = [str(message.get("content", "")) for message in active_history[-3:]]

    turn_result, translation_details, scam_result, threat_result = await asyncio.gather(
        handle_turn(clean_text, history=orchestrator_history, images=[img.model_dump() for img in request.images]),
        _translate_for_chat(clean_text, nationality, native_language, context_text),
        _scan_scam_prefilter(clean_text, region=region),
        detect_threat(clean_text, session_id=request.session_id, conversation_context=context_text + [clean_text]),
    )
    scam_flags, scam_status = scam_result
    translation_text = translation_details.get("translated_text")
    reply = turn_result.get("reply") or translation_text or ""

    response = ChatResponse(
        reply=reply,
        tools_invoked=turn_result.get("tools_invoked", []),
        critic=turn_result.get("critic"),
        source_text=raw_text,
        translation=translation_text,
        translation_details=translation_details,
        detected_language=translation_details.get("detected_language"),
        target_language=translation_details.get("target_language"),
        speaker_split=translation_details.get("speaker_split") or [],
        normalized_prices_vnd=translation_details.get("normalized_prices_vnd") or [],
        scam_flags=scam_flags,
        scam_prefilter_status=scam_status,
        threat=threat_result.to_dict(),
        chunk_sequence_id=request.chunk_sequence_id,
        is_final_chunk=request.is_final_chunk,
        resolved_region=region,
    )

    duplicate_response = await _persist_chat_turn(pool, session_id, request, raw_text, clean_text, region, response)
    return duplicate_response or response
