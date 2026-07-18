"""Chat endpoint for live translation, scam pre-filter, and threat detection."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
import unicodedata
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.agent.orchestrator import handle_turn
from app.agent.price_advisor import price_advice
from app.ai.client import ai_client
from app.config import settings
from app.db.postgres import get_pool
from app.modules.audio_pipe import normalize_transcribed_text, preprocess_audio_for_stt
from app.modules.geo import resolve_region, validate_lat_lon
from app.modules.image_reader import read_image
from app.modules.language import canonical_language_code, is_supported_native_language
from app.modules.memory import trigger_background_compression
from app.modules.pii import redact_pii
from app.modules.price_comparison import compare_price
from app.modules.price_intent import PriceIntent, detect_price_intent
from app.modules.scam_detection import match_scam_pattern
from app.modules.threat_detection import detect_threat
from app.modules.translation import resolve_translation_target, translate_text
from app.schemas.chat import ChatRequest, ChatResponse, TextChatRequest

router = APIRouter()

SCAM_PREFILTER_THRESHOLD = 0.6
DEFAULT_REGION = "Hanoi"
SERVER_HISTORY_LIMIT = 12
ALLOWED_SPEAKER_ROLES = {"tourist", "vendor", "unknown"}

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
            r"\bngay hom nay\b.*\bmat tien coc\b",
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


def _redact_history(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Treat every historical message as untrusted conversation data."""

    safe_messages: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            continue
        role = str(message.get("role") or "user").strip().lower()
        if role not in {"user", "assistant"}:
            role = "user"
        safe_messages.append({"role": role, "content": redact_pii(message["content"])})
    return safe_messages


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
        hint = canonical_language_code(request.audio_language_hint)
        if hint in {"auto", "none", "unknown"}:
            return None
        if not is_supported_native_language(hint):
            raise HTTPException(status_code=400, detail="audio_language_hint must be vi, en, ko, zh, ja, or auto")
        return hint
    if speaker_role == "vendor":
        return "vi"
    if speaker_role == "tourist":
        return native_language
    return None


def _rule_based_scam_flags(text: str) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    text_lower = text.lower()
    folded_text = "".join(
        character
        for character in unicodedata.normalize("NFD", text_lower).replace("đ", "d")
        if unicodedata.category(character) != "Mn"
    )
    for rule in FALLBACK_SCAM_RULES:
        for pattern in rule["patterns"]:
            match = re.search(pattern, text_lower, flags=re.IGNORECASE)
            if match is None:
                match = re.search(pattern, folded_text, flags=re.IGNORECASE)
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


async def _scan_single_scam_category(
    text: str,
    category: str,
    region: str | None,
    vector: list[float],
) -> dict[str, Any]:
    try:
        result = await asyncio.wait_for(
            match_scam_pattern(text, category=category, region=region, vector=vector),
            timeout=settings.scam_deadline_seconds,
        )
        result["status"] = "ok"
        return result
    except TimeoutError:
        error = "scam_prefilter_timeout"
    except Exception:  # noqa: BLE001 - pre-filter should not block chat
        error = "scam_prefilter_unavailable"
    return {"category": category, "error": error, "matches": [], "best_score": 0.0, "status": "error"}


def _merge_scam_flags(vector_flags: list[dict[str, Any]], rule_flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for flag in vector_flags + rule_flags:
        category = str(flag.get("category") or "unknown")
        current = merged.get(category)
        if current is None or float(flag.get("best_score") or 0.0) > float(current.get("best_score") or 0.0):
            merged[category] = flag
    return list(merged.values())


async def _scan_scam_prefilter(text: str, region: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        vector = await asyncio.wait_for(
            ai_client.embed(text),
            timeout=settings.scam_deadline_seconds,
        )
    except TimeoutError:
        embedding_error = "scam_embedding_timeout"
    except Exception:
        embedding_error = "scam_embedding_unavailable"
    else:
        embedding_error = None

    if embedding_error:
        rule_flags = _rule_based_scam_flags(text)
        return rule_flags, {
            "mode": "rule_fallback_only",
            "qdrant_ok": False,
            "errors": [
                {"category": category, "error": embedding_error}
                for category in ("price_scam", "ghost_tour_pressure")
            ],
            "rule_fallback_used": bool(rule_flags),
            "categories_checked": ["price_scam", "ghost_tour_pressure"],
        }

    price_result, pressure_result = await asyncio.gather(
        _scan_single_scam_category(text, "price_scam", region, vector),
        _scan_single_scam_category(text, "ghost_tour_pressure", region, vector),
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
            SELECT clean_text, reply
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
        messages.append({"role": "user", "content": redact_pii(row["clean_text"])})
        if row["reply"]:
            messages.append({"role": "assistant", "content": redact_pii(row["reply"])})
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
    speaker_role: str,
) -> dict[str, Any]:
    try:
        return await translate_text(
            text,
            nationality=nationality,
            native_language=native_language,
            history_context=history_context,
            speaker_role=speaker_role,
        )
    except Exception:  # noqa: BLE001 - chat must return a deterministic translation envelope
        target_language, direction = resolve_translation_target(
            speaker_role=speaker_role,
            nationality=nationality,
            native_language=native_language,
            text=text,
        )
        return {
            "detected_language": "unknown",
            "source_text_clean": text,
            "translated_text": text,
            "target_language": target_language,
            "speaker_role": speaker_role,
            "translation_direction": direction,
            "key_entities": [],
            "normalized_prices_vnd": [],
            "speaker_split": [],
            "degraded": True,
            "degradation_reason": "translation_internal_error",
        }


async def _run_orchestrator_for_chat(
    text: str,
    history: list[dict[str, Any]],
    images: list[dict[str, Any]],
    region: str | None = None,
) -> dict[str, Any]:
    try:
        result = await asyncio.wait_for(
            handle_turn(text, history=history, images=images, region=region),
            timeout=settings.orchestrator_deadline_seconds,
        )
        result.setdefault("degraded", False)
        result.setdefault("degradation_reason", None)
        return result
    except TimeoutError:
        reason = "orchestrator_timeout"
    except Exception:
        reason = "orchestrator_unavailable"
    return {
        "reply": "",
        "tools_invoked": [],
        "critic": None,
        "degraded": True,
        "degradation_reason": reason,
    }


def _build_price_reply(
    items: list[dict[str, Any]],
    needs_retake: bool,
    retake_reason: str | None,
) -> str:
    """Deterministic, human-readable price verdict for the image route — no LLM.
    When the menu couldn't be read, this is the retake prompt the chatbot shows."""
    if needs_retake:
        if retake_reason == "no_menu_detected":
            return (
                "I couldn't find a menu or receipt in that photo. "
                "Please retake a clear, close-up photo of the menu."
            )
        return (
            "That photo was hard to read. "
            "Please retake a clearer, closer photo of the menu."
        )

    lines: list[str] = []
    for item in items:
        observed = item.get("observed_price")
        if observed is None:
            continue
        name = item.get("item") or "Item"
        reference = item.get("reference_price")
        if reference is None:
            lines.append(f"• {name}: {observed:,.0f}₫ — no local reference to compare")
        elif item.get("overpriced") and item.get("price_diff_pct") is not None:
            lines.append(
                f"• {name}: {observed:,.0f}₫ — reference ~{reference:,.0f}₫ "
                f"(about {item['price_diff_pct']:.0f}% higher)"
            )
        else:
            lines.append(f"• {name}: {observed:,.0f}₫ — looks fair (reference ~{reference:,.0f}₫)")

    if not lines:
        return (
            "I read the photo but couldn't find any priced items to compare. "
            "Please retake a clearer photo of the menu."
        )

    overpriced = any(item.get("overpriced") for item in items)
    footer = (
        "⚠️ Some items look higher than the typical local price."
        if overpriced
        else "✅ Prices look about fair for the area."
    )
    return "\n".join(["Here's what I read from the menu:", *lines, "", footer])


async def _run_image_route(
    images: list[dict[str, Any]], region: str, native_language: str = "en"
) -> dict[str, Any]:
    """Image route — Module 2.1 only. OCR each menu photo (Qwen-VL) and compare its
    confidently-priced items against local references (compare_price), producing a
    deterministic price verdict. When nothing readable/priced comes back, signal
    needs_retake so the chatbot asks for a clearer photo. Never runs the orchestrator,
    translate, scam-prefilter, or threat — and never fabricates a price: an OCR/compare
    failure surfaces as a retake, not a made-up answer."""
    analysis_items: list[dict[str, Any]] = []
    normalized_prices: list[int] = []
    tools_invoked: list[dict[str, Any]] = []
    saw_error = False
    saw_any_item = False
    saw_ready_item = False

    for img in images:
        mode = img.get("mode") or "receipt"
        try:
            image_bytes = base64.b64decode(img["image_base64"])
            result = await read_image(image_bytes, mode, region=region)
        except Exception:  # noqa: BLE001 - surface as retake, never crash/fabricate
            saw_error = True
            continue
        if not isinstance(result, dict) or result.get("error"):
            saw_error = True
            continue
        if result.get("parse_error"):
            saw_error = True

        ready = result.get("ready_items") or []
        review = result.get("needs_review") or []
        if ready:
            saw_ready_item = True
        if ready or review:
            saw_any_item = True

        category = result.get("category", "food")
        for item in ready:
            observed = item.get("price_vnd")
            args = {
                "item": item.get("item_name"),
                "region": region,
                "category": category,
                "observed_price": observed,
            }
            try:
                comparison = await compare_price(
                    item=args["item"], region=region, category=category, observed_price=observed
                )
            except Exception:  # noqa: BLE001 - a failed compare shouldn't sink the whole read
                comparison = {"error": "compare_failed"}
            tools_invoked.append({"tool": "compare_price", "arguments": args, "result": comparison})
            if isinstance(observed, (int, float)):
                normalized_prices.append(int(observed))
            analysis_items.append(
                {
                    "item": args["item"],
                    "observed_price": int(observed) if isinstance(observed, (int, float)) else None,
                    "reference_price": comparison.get("reference_price"),
                    "reference_price_range": comparison.get("reference_price_range"),
                    "overpriced": bool(comparison.get("flag")),
                    "price_diff_pct": comparison.get("price_diff_pct"),
                    "flag": comparison.get("flag"),
                }
            )

    needs_retake = not saw_ready_item
    retake_reason: str | None = None
    if needs_retake:
        retake_reason = "no_menu_detected" if (saw_error or not saw_any_item) else "unreadable"

    price_analysis: dict[str, Any] | None = None
    if not needs_retake:
        price_analysis = {
            "region": region,
            "items": analysis_items,
            "overall_overpriced": any(item["overpriced"] for item in analysis_items),
        }

    # Deterministic retake prompt stays deterministic; a real price verdict gets the
    # LLM friendly advice (falling back to the deterministic list if GLM is down).
    if needs_retake:
        reply = _build_price_reply(analysis_items, needs_retake, retake_reason)
    else:
        reply = await price_advice(analysis_items, native_language) or _build_price_reply(
            analysis_items, needs_retake, retake_reason
        )
    return {
        "reply": reply,
        "tools_invoked": tools_invoked,
        "normalized_prices_vnd": normalized_prices,
        "price_analysis": price_analysis,
        "needs_retake": needs_retake,
        "retake_reason": retake_reason,
        "degraded": saw_error and needs_retake,
    }


def _build_price_text_reply(analysis: dict[str, Any], intent: PriceIntent, region: str) -> str:
    """Human-readable verdict for a typed price question — no LLM. Handles both the
    'is this expensive?' case (a price was given) and the 'how much?' case (no price)."""
    name = intent.item
    reference = analysis.get("reference_price")

    if intent.observed_price is None:  # "how much" question
        if reference is None:
            return f"I couldn't find a typical local price for {name}."
        line = f"Typical price for {name} in {region} is about {reference:,.0f}₫"
        rng = analysis.get("reference_price_range")
        if rng:
            line += f" (usually {rng[0]:,.0f}–{rng[1]:,.0f}₫)"
        return line + "."

    observed = intent.observed_price
    if reference is None:
        return f"{name}: {observed:,.0f}₫ — I don't have a local reference to compare that against."
    if analysis.get("overpriced") and analysis.get("price_diff_pct") is not None:
        return (
            f"{name}: {observed:,.0f}₫ looks high — the typical local price is about "
            f"{reference:,.0f}₫ (~{analysis['price_diff_pct']:.0f}% more). ⚠️"
        )
    return f"{name}: {observed:,.0f}₫ looks about fair — the typical local price is ~{reference:,.0f}₫. ✅"


async def _run_price_text_route(
    intent: PriceIntent, region: str, native_language: str = "en"
) -> dict[str, Any] | None:
    """Text price-check route — Module 2.1 (compare_price) directly, no Qwen-VL OCR
    and no chatbot LLM. Returns response fields, or None to fall through to the
    orchestrator (a 'how much' question whose item has no local/web reference — let
    the general chatbot answer instead of a bad 'no price')."""
    try:
        comparison = await compare_price(
            item=intent.item, region=region, category="food", observed_price=intent.observed_price
        )
    except Exception:  # noqa: BLE001 - never fabricate; fall through to the orchestrator
        return None

    # "How much" question that found no comparable price -> let the orchestrator try.
    if intent.observed_price is None and not comparison.get("matched"):
        return None

    analysis = {
        "item": intent.item,
        "observed_price": intent.observed_price,
        "reference_price": comparison.get("reference_price"),
        "reference_price_range": comparison.get("reference_price_range"),
        "overpriced": bool(comparison.get("flag")),
        "price_diff_pct": comparison.get("price_diff_pct"),
        "flag": comparison.get("flag"),
    }
    args = {
        "item": intent.item,
        "region": region,
        "category": "food",
        "observed_price": intent.observed_price,
    }
    reply = await price_advice([analysis], native_language) or _build_price_text_reply(
        analysis, intent, region
    )
    return {
        "reply": reply,
        "tools_invoked": [{"tool": "compare_price", "arguments": args, "result": comparison}],
        "normalized_prices_vnd": [intent.observed_price] if intent.observed_price is not None else [],
        "price_analysis": {
            "region": region,
            "items": [analysis],
            "overall_overpriced": bool(comparison.get("flag")),
        },
    }


async def _persist_chat_turn(
    pool: Any,
    session_id: uuid.UUID,
    request: ChatRequest,
    source_text: str,
    clean_text: str,
    region: str,
    response: ChatResponse,
) -> tuple[ChatResponse | None, bool]:
    turn_id = uuid.uuid4()
    persisted_response = response.model_copy(update={"server_turn_id": str(turn_id)})
    payload = persisted_response.model_dump()
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
            response.server_turn_id = str(turn_id)
            return None, True
        existing = await _fetch_existing_chunk_response(pool, session_id, request.chunk_sequence_id)
        return existing, existing is not None
    except Exception:
        return None, False


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, background_tasks: BackgroundTasks) -> ChatResponse:
    started_at = time.perf_counter()
    text_supplied = request.text is not None
    audio_supplied = request.audio_base64 is not None
    if text_supplied == audio_supplied:
        raise HTTPException(status_code=400, detail="provide exactly one of text or audio_base64")

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
    if request.audio_base64 is not None:
        try:
            wav_bytes = preprocess_audio_for_stt(
                request.audio_base64,
                input_format=request.audio_format,
                max_bytes=settings.max_audio_bytes,
                max_duration_seconds=settings.max_audio_duration_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        language_hint = _audio_language_hint(request, speaker_role, native_language)
        try:
            # No initial_prompt: the FPT Whisper endpoint 500s on a term-list prompt
            # and even truncates the transcript when given one — it reads this audio
            # cleanly with no priming.
            raw_text = await asyncio.wait_for(
                ai_client.transcribe(wav_bytes, language_hint=language_hint),
                timeout=settings.stt_deadline_seconds,
            )
        except TimeoutError as exc:
            raise HTTPException(status_code=503, detail="speech transcription timed out") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="speech transcription is temporarily unavailable") from exc

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="text or audio_base64 is required")

    raw_text = normalize_transcribed_text(raw_text)
    clean_text = redact_pii(raw_text)
    request_history = _redact_history([message.model_dump() for message in request.history])
    server_history = await _load_recent_chat_history(pool, session_id)
    compressed_history = _redact_history(_coerce_history(session["compressed_history"]))
    compressed_summary = compressed_history[:1]
    base_history = compressed_summary + (request_history or server_history)
    active_history = trigger_background_compression(request.session_id, base_history, background_tasks)
    session_context = {
        "role": "system",
        "content": (
            "Session context for tool calls: "
            f"native_language={native_language}; "
            f"nationality={nationality}; "
            f"region={region}; "
            f"speaker_role={speaker_role}. "
            "Translation direction is strict: tourist speech targets Vietnamese; "
            "vendor speech targets native_language; infer direction only for unknown speakers. "
            "When looking up emergency contacts, use nationality and region exactly from this context."
        ),
    }
    orchestrator_history = [session_context] + active_history
    context_text = [str(message.get("content", "")) for message in active_history[-3:]]

    # Deterministic input-type routing (see the chat-input-routing design spec):
    #   image -> Module 2.1 only; voice -> Module 1 translate + scam + threat (no
    #   orchestrator); text -> the full orchestrator pipeline (unchanged). Precedence
    #   image > voice > text keeps behavior deterministic if both ever arrive.
    route = "image" if request.images else ("voice" if audio_supplied else "text")

    reply = ""
    translation_details: dict[str, Any] | None = None
    translation_text: str | None = None
    scam_flags: list[dict[str, Any]] = []
    scam_status: dict[str, Any] | None = None
    threat_payload: dict[str, Any] | None = None
    tools_invoked: list[dict[str, Any]] = []
    critic: dict[str, Any] | None = None
    normalized_prices: list[int] = []
    price_analysis: dict[str, Any] | None = None
    needs_retake = False
    retake_reason: str | None = None
    degraded_components: list[str] = []

    if route == "image":
        image_result = await _run_image_route(
            [image.model_dump() for image in request.images], region, native_language
        )
        reply = image_result["reply"]
        tools_invoked = image_result["tools_invoked"]
        normalized_prices = image_result["normalized_prices_vnd"]
        price_analysis = image_result["price_analysis"]
        needs_retake = image_result["needs_retake"]
        retake_reason = image_result["retake_reason"]
        if image_result.get("degraded"):
            degraded_components.append("image_pipeline")
    elif route == "voice":
        translation_details, scam_result, threat_result = await asyncio.gather(
            _translate_for_chat(clean_text, nationality, native_language, context_text, speaker_role),
            _scan_scam_prefilter(clean_text, region=region),
            detect_threat(clean_text, session_id=request.session_id, conversation_context=context_text + [clean_text]),
        )
        scam_flags, scam_status = scam_result
        translation_text = translation_details.get("translated_text")
        reply = translation_text or ""
        normalized_prices = translation_details.get("normalized_prices_vnd") or []
        threat_payload = threat_result.to_dict()
        if translation_details.get("degraded"):
            degraded_components.append("translation")
        if not scam_status.get("qdrant_ok"):
            degraded_components.append("scam_prefilter")
        if getattr(threat_result, "degraded", False):
            degraded_components.append("threat_assessment")
    else:  # text
        # Deterministic price-check intent ("bún đậu 200k", "cơm rang 100k có đắt
        # không", "how much is bún đậu?") -> Module 2.1 directly: no Qwen-VL OCR and
        # no chatbot LLM. None / a "how much" miss falls through to the orchestrator.
        price_intent = detect_price_intent(clean_text)
        price_result = (
            await _run_price_text_route(price_intent, region, native_language)
            if price_intent
            else None
        )
        if price_result is not None:
            reply = price_result["reply"]
            tools_invoked = price_result["tools_invoked"]
            normalized_prices = price_result["normalized_prices_vnd"]
            price_analysis = price_result["price_analysis"]
        else:  # normal chatbot — full orchestrator pipeline
            turn_result, translation_details, scam_result, threat_result = await asyncio.gather(
                _run_orchestrator_for_chat(
                    clean_text,
                    history=orchestrator_history,
                    images=[image.model_dump() for image in request.images],
                    region=region,
                ),
                _translate_for_chat(clean_text, nationality, native_language, context_text, speaker_role),
                _scan_scam_prefilter(clean_text, region=region),
                detect_threat(clean_text, session_id=request.session_id, conversation_context=context_text + [clean_text]),
            )
            scam_flags, scam_status = scam_result
            translation_text = translation_details.get("translated_text")
            reply = turn_result.get("reply") or translation_text or ""
            tools_invoked = turn_result.get("tools_invoked", [])
            critic = turn_result.get("critic")
            normalized_prices = translation_details.get("normalized_prices_vnd") or []
            threat_payload = threat_result.to_dict()
            if turn_result.get("degraded"):
                degraded_components.append("orchestrator")
            if translation_details.get("degraded"):
                degraded_components.append("translation")
            if not scam_status.get("qdrant_ok"):
                degraded_components.append("scam_prefilter")
            if getattr(threat_result, "degraded", False):
                degraded_components.append("threat_assessment")

    response = ChatResponse(
        reply=reply,
        tools_invoked=tools_invoked,
        critic=critic,
        source_text=raw_text,
        translation=translation_text,
        translation_details=translation_details,
        detected_language=(translation_details or {}).get("detected_language"),
        target_language=(translation_details or {}).get("target_language"),
        speaker_split=(translation_details or {}).get("speaker_split") or [],
        normalized_prices_vnd=normalized_prices,
        scam_flags=scam_flags,
        scam_prefilter_status=scam_status,
        threat=threat_payload,
        input_route=route,
        needs_retake=needs_retake,
        retake_reason=retake_reason,
        price_analysis=price_analysis,
        chunk_sequence_id=request.chunk_sequence_id,
        is_final_chunk=request.is_final_chunk,
        resolved_region=region,
        degraded_components=degraded_components,
        processing_time_ms=max(0, round((time.perf_counter() - started_at) * 1000)),
    )

    duplicate_response, persisted = await _persist_chat_turn(
        pool,
        session_id,
        request,
        raw_text,
        clean_text,
        region,
        response,
    )
    if duplicate_response is not None:
        return duplicate_response
    if not persisted:
        response.server_turn_id = None
        if "chat_persistence" not in response.degraded_components:
            response.degraded_components.append("chat_persistence")
    return response


@router.post("/chat/text", response_model=ChatResponse)
async def text_chat(request: TextChatRequest, background_tasks: BackgroundTasks) -> ChatResponse:
    """Typed chat with the same translation, scam, threat, memory, and persistence flow."""

    shared_request = ChatRequest(
        **request.model_dump(),
        audio_base64=None,
        is_final_chunk=True,
    )
    return await chat(shared_request, background_tasks)
