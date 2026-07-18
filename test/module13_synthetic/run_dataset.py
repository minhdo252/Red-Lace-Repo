"""Reusable synthetic integration and quality runner for backend Modules 1 and 3."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
DATASET_PATH = Path(__file__).with_name("dataset.json")
sys.path.insert(0, str(BACKEND_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402
from openai import OpenAI  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client.models import PointIdsList, PointStruct  # noqa: E402

from app.ai.client import _message_response_text, ai_client  # noqa: E402
from app.config import settings  # noqa: E402
from app.db.postgres import get_pool  # noqa: E402
from app.main import app  # noqa: E402
from app.modules import memory as memory_module  # noqa: E402
from app.modules.audio_pipe import normalize_transcribed_text, preprocess_audio_for_stt  # noqa: E402
from app.modules.pii import redact_pii  # noqa: E402
from app.modules.translation import (  # noqa: E402
    extract_normalized_prices_vnd,
    resolve_translation_target,
    translate_text,
)
from app.modules.threat_detection import (  # noqa: E402
    _fallback_context_assessment,
    scan_threat_keywords,
    update_session_risk,
)
from app.routers.chat import _rule_based_scam_flags  # noqa: E402


REQUIRED_CHAT_FIELDS = {
    "reply",
    "tools_invoked",
    "source_text",
    "translation",
    "translation_details",
    "detected_language",
    "target_language",
    "speaker_split",
    "normalized_prices_vnd",
    "scam_flags",
    "scam_prefilter_status",
    "threat",
    "chunk_sequence_id",
    "is_final_chunk",
    "resolved_region",
    "server_turn_id",
    "degraded_components",
    "processing_time_ms",
}


@dataclass
class ResultBook:
    suite: str
    passed: int = 0
    failed: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.perf_counter)

    def check(
        self,
        condition: bool,
        label: str,
        *,
        expected: Any = None,
        actual: Any = None,
    ) -> bool:
        if condition:
            self.passed += 1
            print(f"[PASS] {label}")
            return True

        self.failed += 1
        failure = {"label": label, "expected": expected, "actual": actual}
        self.failures.append(failure)
        print(
            f"[FAIL] {label} | expected={json.dumps(expected, ensure_ascii=False)} "
            f"actual={json.dumps(actual, ensure_ascii=False)}"
        )
        return False

    def metric(self, name: str, value: Any) -> None:
        self.metrics[name] = value

    def finish(self) -> int:
        elapsed = round(time.perf_counter() - self.started_at, 3)
        summary = {
            "suite": self.suite,
            "passed": self.passed,
            "failed": self.failed,
            "elapsed_seconds": elapsed,
            "metrics": self.metrics,
            "failures": self.failures,
        }
        print("\n=== RESULT SUMMARY ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if self.failed == 0 else 1


def load_dataset() -> dict[str, Any]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def word_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFC", text).casefold()
    cleaned = "".join(char if char.isalnum() else " " for char in normalized)
    return cleaned.split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref = word_tokens(reference)
    hyp = word_tokens(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0

    previous = list(range(len(hyp) + 1))
    for ref_index, ref_word in enumerate(ref, start=1):
        current = [ref_index]
        for hyp_index, hyp_word in enumerate(hyp, start=1):
            substitution = previous[hyp_index - 1] + (ref_word != hyp_word)
            insertion = current[hyp_index - 1] + 1
            deletion = previous[hyp_index] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1] / len(ref)


def create_session(
    client: TestClient,
    book: ResultBook,
    native_language: str,
    nationality: str,
    label: str,
) -> str:
    response = client.post(
        "/sessions",
        json={"native_language": native_language, "nationality": nationality},
    )
    book.check(response.status_code == 200, f"{label}: create session", expected=200, actual=response.status_code)
    if response.status_code != 200:
        raise RuntimeError(f"Cannot create session for {label}: {response.text}")
    return str(response.json()["session_id"])


def scam_categories(payload: dict[str, Any]) -> set[str]:
    return {str(flag.get("category")) for flag in payload.get("scam_flags", []) if flag.get("category")}


def point_id_map(client: QdrantClient, collection_name: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    offset: Any = None
    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            limit=256,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        for point in points:
            found[str(point.id)] = point.id
        if offset is None:
            return found


def fixture_vectors(patterns: list[dict[str, Any]]) -> list[list[float]]:
    if ai_client.mode == "mock":

        async def embed_all() -> list[list[float]]:
            return list(await asyncio.gather(*(ai_client.embed(item["text"]) for item in patterns)))

        return asyncio.run(embed_all())

    api_key = settings.ai_embed_api_key or settings.vn_embedding_api_key or settings.ai_api_key
    if not api_key:
        raise RuntimeError("Live Qdrant fixtures require VN_EMBEDDING_API_KEY or AI_API_KEY")
    with OpenAI(
        api_key=api_key,
        base_url=settings.ai_base_url,
        timeout=settings.ai_request_timeout_seconds,
    ) as client:
        return [
            client.embeddings.create(model=settings.ai_embed_model, input=[item["text"]]).data[0].embedding
            for item in patterns
        ]


@contextmanager
def temporary_qdrant_patterns(
    dataset: dict[str, Any],
    book: ResultBook,
) -> Iterator[None]:
    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    patterns = dataset["qdrant_patterns"]
    fixture_ids = [item["id"] for item in patterns]
    unmatched_before = point_id_map(client, "unmatched_reports")
    seeded = False
    try:
        vectors = fixture_vectors(patterns)
        client.upsert(
            collection_name="scam_patterns",
            points=[
                PointStruct(
                    id=item["id"],
                    vector=vector,
                    payload={
                        "text": item["text"],
                        "category": item["category"],
                        "region": item["region"],
                        "fixture_namespace": dataset["namespace"],
                    },
                )
                for item, vector in zip(patterns, vectors, strict=True)
            ],
            wait=True,
        )
        seeded = True
        book.check(True, "Qdrant: temporary scam fixtures seeded")
        yield
    finally:
        cleanup_errors: list[str] = []
        try:
            client.delete(
                collection_name="scam_patterns",
                points_selector=PointIdsList(points=fixture_ids),
                wait=True,
            )
        except Exception as exc:  # noqa: BLE001 - cleanup must report and continue
            cleanup_errors.append(f"scam_patterns: {exc}")

        try:
            unmatched_after = point_id_map(client, "unmatched_reports")
            generated_ids = [
                original_id
                for key, original_id in unmatched_after.items()
                if key not in unmatched_before
            ]
            if generated_ids:
                client.delete(
                    collection_name="unmatched_reports",
                    points_selector=PointIdsList(points=generated_ids),
                    wait=True,
                )
        except Exception as exc:  # noqa: BLE001 - cleanup must report and continue
            cleanup_errors.append(f"unmatched_reports: {exc}")

        try:
            remaining = point_id_map(client, "scam_patterns")
            remaining_fixture_ids = [point_id for point_id in fixture_ids if point_id in remaining]
            book.check(
                not remaining_fixture_ids,
                "Qdrant: temporary fixture cleanup",
                expected=[],
                actual=remaining_fixture_ids,
            )
        except Exception as exc:  # noqa: BLE001 - verification failure is a test failure
            cleanup_errors.append(f"cleanup verification: {exc}")

        if not seeded:
            cleanup_errors.append("fixtures were not fully seeded")
        book.check(
            not cleanup_errors,
            "Qdrant: cleanup completed without errors",
            expected=[],
            actual=cleanup_errors,
        )
        client.close()


def run_pure_contract_cases(dataset: dict[str, Any], book: ResultBook) -> None:
    print("\n--- Pure Module 1 logic ---")
    for case in dataset["normalization_cases"]:
        actual = normalize_transcribed_text(case["input"])
        book.check(actual == case["expected"], f"{case['id']}: transcript normalization", expected=case["expected"], actual=actual)

    for case in dataset["pii_cases"]:
        actual = redact_pii(case["input"])
        valid = case["expected_contains"] in actual and case["expected_absent"] not in actual
        book.check(valid, f"{case['id']}: PII redaction", expected=case, actual=actual)

    for case in dataset["price_normalization_cases"]:
        actual = extract_normalized_prices_vnd(case["input"])
        book.check(actual == case["expected"], f"{case['id']}: deterministic VND normalization", expected=case["expected"], actual=actual)

    direction_cases = [
        ("tourist", "en", "hello", "vi", "tourist_to_vendor"),
        ("vendor", "ko", "xin chao", "ko", "vendor_to_tourist"),
        ("unknown", "ja", "gi\u00e1 bao nhi\u00eau", "ja", "inferred_vendor_to_tourist"),
        ("unknown", "en", "how much", "vi", "inferred_tourist_to_vendor"),
    ]
    for role, native_language, text, expected_target, expected_direction in direction_cases:
        target, direction = resolve_translation_target(
            speaker_role=role,
            nationality="US",
            native_language=native_language,
            text=text,
        )
        book.check(
            (target, direction) == (expected_target, expected_direction),
            f"translation direction: {role}/{native_language}",
            expected=[expected_target, expected_direction],
            actual=[target, direction],
        )

    original_chat = ai_client.chat

    async def noncanonical_translation_response(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            content=json.dumps(
                {
                    "detected_language": "English",
                    "source_text_clean": "Where is the station?",
                    "translated_text": "Nh\u00e0 ga \u1edf \u0111\u00e2u?",
                    "target_language": "Vietnamese",
                    "key_entities": ["station"],
                    "normalized_prices_vnd": [],
                    "speaker_split": [{"speaker": "Speaker 1", "text": "Where is the station?"}],
                },
                ensure_ascii=False,
            )
        )

    try:
        ai_client.chat = noncanonical_translation_response  # type: ignore[method-assign]
        normalized_translation = asyncio.run(
            translate_text(
                "Where is the station?",
                nationality="US",
                native_language="en",
                speaker_role="tourist",
            )
        )
    finally:
        ai_client.chat = original_chat  # type: ignore[method-assign]
    book.check(
        normalized_translation["degraded"] is False
        and normalized_translation["detected_language"] == "en"
        and normalized_translation["target_language"] == "vi"
        and normalized_translation["speaker_split"][0]["speaker"] == "tourist"
        and bool(normalized_translation["speaker_split"][0]["translated"]),
        "translation contract: normalize noncanonical GLM JSON",
        expected="canonical successful translation",
        actual=normalized_translation,
    )

    audio_guard_errors: list[str] = []
    for label, kwargs in [
        ("unsupported format", {"audio_base64": base64.b64encode(b"abc").decode(), "input_format": "exe"}),
        (
            "encoded size limit",
            {
                "audio_base64": base64.b64encode(b"abc").decode(),
                "input_format": "wav",
                "max_bytes": 2,
            },
        ),
    ]:
        try:
            preprocess_audio_for_stt(**kwargs)
        except ValueError:
            continue
        audio_guard_errors.append(label)
    book.check(
        not audio_guard_errors,
        "audio admission: format and pre-decode size guards",
        expected=[],
        actual=audio_guard_errors,
    )

    structured_message = SimpleNamespace(content=None, reasoning_content='{"status":"ok"}')
    normal_message = SimpleNamespace(content="final", reasoning_content="internal reasoning")
    book.check(
        _message_response_text(structured_message, allow_reasoning_fallback=True) == '{"status":"ok"}',
        "AI gateway: GLM structured reasoning_content compatibility",
        expected='{"status":"ok"}',
        actual=_message_response_text(structured_message, allow_reasoning_fallback=True),
    )
    book.check(
        _message_response_text(normal_message, allow_reasoning_fallback=True) == "final"
        and _message_response_text(structured_message, allow_reasoning_fallback=False) == "",
        "AI gateway: final content precedence and reasoning isolation",
        expected="final content only",
        actual={
            "normal": _message_response_text(normal_message, allow_reasoning_fallback=True),
            "unstructured_empty": _message_response_text(structured_message, allow_reasoning_fallback=False),
        },
    )

    original_compressor = memory_module._compress_history
    logger_was_disabled = memory_module.logger.disabled

    async def failing_compressor(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("synthetic background failure")

    background_error: str | None = None
    try:
        memory_module._compress_history = failing_compressor
        memory_module.logger.disabled = True
        asyncio.run(memory_module._do_compress_history(str(uuid.uuid4()), [{"role": "user", "content": "old"}], []))
    except Exception as exc:  # noqa: BLE001 - the assertion records unexpected propagation
        background_error = f"{type(exc).__name__}: {exc}"
    finally:
        memory_module._compress_history = original_compressor
        memory_module.logger.disabled = logger_was_disabled
    book.check(
        background_error is None,
        "memory compression: background exception isolation",
        expected=None,
        actual=background_error,
    )

    for case in dataset["scam_rule_cases"]:
        actual = {item["category"] for item in _rule_based_scam_flags(case["text"])}
        expected = set(case["expected_categories"])
        book.check(actual == expected, f"{case['id']}: deterministic scam rule", expected=sorted(expected), actual=sorted(actual))

    print("\n--- Pure Module 3 threat scan ---")
    for case in dataset["threat_scan_cases"]:
        scan = scan_threat_keywords(case["text"])
        categories = {item["category"] for item in scan.matched_categories}
        book.check(scan.has_threat is case["expected_threat"], f"{case['id']}: threat presence", expected=case["expected_threat"], actual=scan.has_threat)
        book.check(scan.max_level == case["expected_level"], f"{case['id']}: Tier-1 threat level", expected=case["expected_level"], actual=scan.max_level)
        expected_category = case["expected_category"]
        book.check(
            (expected_category in categories) if expected_category else not categories,
            f"{case['id']}: threat category",
            expected=expected_category,
            actual=sorted(categories),
        )
        if "expected_context_level" in case:
            assessment = _fallback_context_assessment(scan, [case["text"]])
            book.check(
                assessment["recommended_level"] == case["expected_context_level"],
                f"{case['id']}: false-alarm context downgrade",
                expected=case["expected_context_level"],
                actual=assessment,
            )


def check_chat_payload(
    book: ResultBook,
    case: dict[str, Any],
    payload: dict[str, Any],
    *,
    check_prices: bool = False,
    require_semantic_translation: bool = False,
) -> None:
    case_id = case["id"]
    missing = sorted(REQUIRED_CHAT_FIELDS - payload.keys())
    book.check(not missing, f"{case_id}: complete /chat response contract", expected=[], actual=missing)
    expected_target = case.get("expected_target_language", case["native_language"])
    book.check(payload.get("target_language") == expected_target, f"{case_id}: target language", expected=expected_target, actual=payload.get("target_language"))
    book.check(payload.get("resolved_region") == case["region"], f"{case_id}: resolved region", expected=case["region"], actual=payload.get("resolved_region"))
    book.check(bool(payload.get("server_turn_id")), f"{case_id}: persisted server turn id", expected="non-empty UUID", actual=payload.get("server_turn_id"))
    details = payload.get("translation_details") or {}
    expected_direction = "tourist_to_vendor" if case["speaker_role"] == "tourist" else "vendor_to_tourist"
    book.check(
        details.get("speaker_role") == case["speaker_role"]
        and details.get("translation_direction") == expected_direction,
        f"{case_id}: explicit translation direction",
        expected={"speaker_role": case["speaker_role"], "translation_direction": expected_direction},
        actual=details,
    )
    book.check(
        isinstance(payload.get("degraded_components"), list)
        and isinstance(payload.get("processing_time_ms"), int),
        f"{case_id}: resilience metadata",
        expected="list + integer latency",
        actual={
            "degraded_components": payload.get("degraded_components"),
            "processing_time_ms": payload.get("processing_time_ms"),
        },
    )
    if require_semantic_translation:
        book.check(
            details.get("degraded") is False,
            f"{case_id}: translation provider completed",
            expected=False,
            actual=details.get("degraded"),
        )
        if payload.get("detected_language") != expected_target:
            source = " ".join(str(payload.get("source_text") or "").casefold().split())
            translated = " ".join(str(payload.get("translation") or "").casefold().split())
            book.check(
                bool(translated) and translated != source,
                f"{case_id}: semantic translation changed language",
                expected=f"non-source text in {expected_target}",
                actual=payload.get("translation"),
            )

    categories = scam_categories(payload)
    expected_scam = case.get("expected_scam")
    book.check(
        (expected_scam in categories) if expected_scam else not categories,
        f"{case_id}: scam classification",
        expected=expected_scam,
        actual=sorted(categories),
    )
    book.check(
        payload.get("threat", {}).get("final_level") == case["expected_threat"],
        f"{case_id}: final threat level",
        expected=case["expected_threat"],
        actual=payload.get("threat"),
    )
    prefilter = payload.get("scam_prefilter_status") or {}
    if require_semantic_translation and prefilter.get("qdrant_ok") is not True:
        errors = prefilter.get("errors") or []
        safe_error_codes = {"scam_embedding_timeout", "scam_embedding_unavailable"}
        valid_degraded_fallback = (
            prefilter.get("mode") == "rule_fallback_only"
            and "scam_prefilter" in (payload.get("degraded_components") or [])
            and bool(errors)
            and all(item.get("error") in safe_error_codes for item in errors if isinstance(item, dict))
        )
        book.check(
            valid_degraded_fallback,
            f"{case_id}: scam prefilter explicit degraded fallback",
            expected="rule fallback + sanitized error + degraded component",
            actual={"prefilter": prefilter, "degraded_components": payload.get("degraded_components")},
        )
    else:
        book.check(
            prefilter.get("qdrant_ok") is True,
            f"{case_id}: Qdrant prefilter healthy",
            expected=True,
            actual=prefilter,
        )

    expected_detected_language = case.get("expected_detected_language")
    if expected_detected_language:
        book.check(
            payload.get("detected_language") == expected_detected_language,
            f"{case_id}: detected source language",
            expected=expected_detected_language,
            actual=payload.get("detected_language"),
        )

    expected_source = case.get("expected_scam_source")
    if expected_source:
        sources = {
            flag.get("source")
            for flag in payload.get("scam_flags", [])
            if flag.get("category") == expected_scam
        }
        book.check(expected_source in sources, f"{case_id}: scam evidence source", expected=expected_source, actual=sorted(sources))

    if check_prices:
        expected_prices = case.get("expected_prices", [])
        book.check(
            payload.get("normalized_prices_vnd") == expected_prices,
            f"{case_id}: normalized VND prices",
            expected=expected_prices,
            actual=payload.get("normalized_prices_vnd"),
        )


def run_chat_contract_cases(client: TestClient, dataset: dict[str, Any], book: ResultBook) -> None:
    print("\n--- Module 1 /chat contract ---")
    first_request: dict[str, Any] | None = None
    first_payload: dict[str, Any] | None = None
    first_session_id: str | None = None

    for sequence, case in enumerate(dataset["chat_contract_cases"], start=1):
        session_id = create_session(client, book, case["native_language"], case["nationality"], case["id"])
        request_payload = {
            "session_id": session_id,
            "text": case["text"],
            "speaker_role": case["speaker_role"],
            "region": case["region"],
            "chunk_sequence_id": sequence,
            "is_final_chunk": True,
        }
        response = client.post("/chat", json=request_payload)
        book.check(response.status_code == 200, f"{case['id']}: /chat status", expected=200, actual=response.status_code)
        if response.status_code != 200:
            continue
        payload = response.json()
        book.check(payload.get("source_text") == case["text"], f"{case['id']}: source text preserved", expected=case["text"], actual=payload.get("source_text"))
        check_chat_payload(book, case, payload)
        if case["id"] == "C002":
            first_request = request_payload
            first_payload = payload
            first_session_id = session_id

    if first_request and first_payload:
        replay = client.post("/chat", json=first_request)
        book.check(replay.status_code == 200, "C002: idempotent replay status", expected=200, actual=replay.status_code)
        book.check(replay.json() == first_payload, "C002: idempotent replay body", expected=first_payload, actual=replay.json())

    validation_session = first_session_id or create_session(client, book, "en", "US", "chat-validation")
    validation_cases = [
        ("unknown session", {"session_id": str(uuid.uuid4()), "text": "hello"}, 404),
        ("invalid UUID", {"session_id": "not-a-uuid", "text": "hello"}, 400),
        ("empty input", {"session_id": validation_session}, 400),
        ("partial GPS", {"session_id": validation_session, "text": "hello", "lat": 21.03}, 400),
        ("invalid role", {"session_id": validation_session, "text": "hello", "speaker_role": "driver"}, 400),
        ("negative chunk", {"session_id": validation_session, "text": "hello", "chunk_sequence_id": -1}, 400),
        (
            "both text and audio",
            {"session_id": validation_session, "text": "hello", "audio_base64": "AAAA"},
            400,
        ),
        (
            "unsupported audio format",
            {"session_id": validation_session, "audio_base64": "AAAA", "audio_format": "exe"},
            400,
        ),
    ]
    for label, request_payload, expected_status in validation_cases:
        response = client.post("/chat", json=request_payload)
        book.check(response.status_code == expected_status, f"/chat validation: {label}", expected=expected_status, actual=response.status_code)

    normalized = client.post("/sessions", json={"native_language": " EN ", "nationality": " us "})
    book.check(normalized.status_code == 200, "session normalization: status", expected=200, actual=normalized.status_code)
    if normalized.status_code == 200:
        payload = normalized.json()
        book.check(payload["native_language"] == "en" and payload["nationality"] == "US", "session normalization: values", expected={"native_language": "en", "nationality": "US"}, actual=payload)

    alias = client.post("/sessions", json={"native_language": "en-US", "nationality": "GB"})
    book.check(
        alias.status_code == 200 and alias.json().get("native_language") == "en",
        "session normalization: language alias",
        expected={"status": 200, "native_language": "en"},
        actual={"status": alias.status_code, "body": alias.json()},
    )
    for label, request_payload in [
        ("unsupported native language", {"native_language": "fr", "nationality": "FR"}),
        ("invalid nationality", {"native_language": "en", "nationality": "USA"}),
    ]:
        response = client.post("/sessions", json=request_payload)
        book.check(response.status_code == 400, f"/sessions validation: {label}", expected=400, actual=response.status_code)


def run_sos_contract_cases(client: TestClient, dataset: dict[str, Any], book: ResultBook) -> None:
    print("\n--- Module 3 /sos routing contract ---")
    run_token = uuid.uuid4().hex[:10]
    rate_limit_session: str | None = None
    first_request: dict[str, Any] | None = None
    first_payload: dict[str, Any] | None = None

    for case in dataset["sos_routing_cases"]:
        session_id = create_session(client, book, "en", case["nationality"], case["id"])
        request_payload = {
            "session_id": session_id,
            "region": case["region"],
            "threat_category": case["threat_category"],
            "threat_level": "CRITICAL" if case["expected_primary"] != "tourist_police" else "HIGH",
            "source": case["source"],
            "idempotency_key": f"MODULE13-{run_token}-{case['id']}",
        }
        response = client.post("/sos", json=request_payload)
        book.check(response.status_code == 200, f"{case['id']}: /sos status", expected=200, actual=response.status_code)
        if response.status_code != 200:
            continue
        payload = response.json()
        contacts = payload.get("contacts", [])
        primary = contacts[0].get("service_type") if contacts else None
        has_embassy = any(item.get("service_type") == "embassy" for item in contacts)
        general_emergency = next(
            (item for item in contacts if item.get("service_type") == "general_emergency"),
            None,
        )
        ranks = [item.get("priority_rank") for item in contacts]

        book.check(primary == case["expected_primary"], f"{case['id']}: primary contact", expected=case["expected_primary"], actual=primary)
        book.check(len(contacts) >= case["min_contacts"], f"{case['id']}: contact coverage", expected=f">={case['min_contacts']}", actual=len(contacts))
        book.check(has_embassy is case["expected_embassy"], f"{case['id']}: embassy routing", expected=case["expected_embassy"], actual=has_embassy)
        book.check(payload.get("region_fallback_used") is case["expected_fallback"], f"{case['id']}: region fallback", expected=case["expected_fallback"], actual=payload.get("region_fallback_used"))
        expected_resolved_region = None if case["expected_fallback"] else case["region"]
        book.check(
            payload.get("resolved_region") == expected_resolved_region,
            f"{case['id']}: resolved supported region",
            expected=expected_resolved_region,
            actual=payload.get("resolved_region"),
        )
        book.check(
            general_emergency is not None and general_emergency.get("phone_number") == "112",
            f"{case['id']}: national 112 coverage",
            expected="112",
            actual=general_emergency,
        )
        book.check(
            bool(general_emergency)
            and general_emergency.get("verification_status") == "verified"
            and bool(general_emergency.get("source_url"))
            and bool(general_emergency.get("verified_at")),
            f"{case['id']}: 112 verification metadata",
            expected="verified source metadata",
            actual=general_emergency,
        )
        book.check(ranks == list(range(1, len(contacts) + 1)), f"{case['id']}: stable priority ranks", expected=list(range(1, len(contacts) + 1)), actual=ranks)
        book.check(sum(bool(item.get("is_primary")) for item in contacts) == 1, f"{case['id']}: exactly one primary contact", expected=1, actual=sum(bool(item.get("is_primary")) for item in contacts))
        book.check(bool(payload.get("event_id")), f"{case['id']}: SOS event persisted", expected="positive event id", actual=payload.get("event_id"))

        if case["id"] == "R001":
            rate_limit_session = session_id
            first_request = request_payload
            first_payload = payload

    if first_request and first_payload and rate_limit_session:
        replay = client.post("/sos", json=first_request)
        book.check(replay.status_code == 200, "R001: idempotent SOS replay status", expected=200, actual=replay.status_code)
        book.check(replay.json() == first_payload, "R001: idempotent SOS replay body", expected=first_payload, actual=replay.json())

        rate_limited_request = dict(first_request)
        rate_limited_request["idempotency_key"] = f"MODULE13-{run_token}-R001-RATE"
        rate_limited = client.post("/sos", json=rate_limited_request)
        book.check(rate_limited.status_code == 200, "R001: SOS rate-limit status", expected=200, actual=rate_limited.status_code)
        if rate_limited.status_code == 200:
            rate_limited_payload = rate_limited.json()
            book.check(rate_limited_payload.get("rate_limited") is True, "R001: SOS rate-limit flag", expected=True, actual=rate_limited_payload)
            book.check(
                rate_limited_payload.get("idempotency_key") == rate_limited_request["idempotency_key"]
                and rate_limited_payload.get("event_id") != first_payload.get("event_id"),
                "R001: rate-limited alias persisted independently",
                expected="new key and event id",
                actual=rate_limited_payload,
            )
            alias_replay = client.post("/sos", json=rate_limited_request)
            book.check(
                alias_replay.status_code == 200 and alias_replay.json() == rate_limited_payload,
                "R001: rate-limited alias replay is idempotent",
                expected=rate_limited_payload,
                actual=alias_replay.json(),
            )

        changed_region_request = dict(first_request)
        changed_region_request.update(
            {
                "region": "Sapa",
                "idempotency_key": f"MODULE13-{run_token}-R001-REGION-CHANGE",
            }
        )
        changed_region = client.post("/sos", json=changed_region_request)
        changed_region_payload = changed_region.json()
        book.check(
            changed_region.status_code == 200
            and changed_region_payload.get("rate_limited") is False
            and changed_region_payload.get("resolved_region") == "Sapa",
            "R001: changed region bypasses stale rate-limit payload",
            expected={"status": 200, "rate_limited": False, "resolved_region": "Sapa"},
            actual={"status": changed_region.status_code, "body": changed_region_payload},
        )

        changed_threat_request = dict(first_request)
        changed_threat_request.update(
            {
                "threat_category": "medical_emergency",
                "idempotency_key": f"MODULE13-{run_token}-R001-THREAT-CHANGE",
            }
        )
        changed_threat = client.post("/sos", json=changed_threat_request)
        changed_threat_payload = changed_threat.json()
        primary = changed_threat_payload.get("contacts", [{}])[0].get("service_type")
        book.check(
            changed_threat.status_code == 200
            and changed_threat_payload.get("rate_limited") is False
            and primary == "medical",
            "R001: changed threat bypasses stale rate-limit payload",
            expected={"status": 200, "rate_limited": False, "primary": "medical"},
            actual={"status": changed_threat.status_code, "body": changed_threat_payload},
        )

    gps_cases = [
        ("Hanoi", 21.0333, 105.8500),
        ("Sapa", 22.3364, 103.8438),
        ("Hoi An", 15.8801, 108.3380),
        (None, 10.8231, 106.6297),
    ]
    for index, (expected_region, lat, lon) in enumerate(gps_cases, start=1):
        gps_session = create_session(client, book, "en", "US", f"GPS{index}")
        response = client.post(
            "/sos",
            json={
                "session_id": gps_session,
                "lat": lat,
                "lon": lon,
                "threat_category": "universal_distress",
                "source": "manual",
                "idempotency_key": f"MODULE13-{run_token}-GPS-{index}",
            },
        )
        payload = response.json()
        book.check(
            response.status_code == 200
            and payload.get("resolved_region") == expected_region
            and payload.get("region_fallback_used") is (expected_region is None),
            f"GPS{index}: region resolution and national fallback",
            expected={"status": 200, "resolved_region": expected_region, "fallback": expected_region is None},
            actual={"status": response.status_code, "body": payload},
        )
        book.check(
            bool(payload.get("location_text_vi")) and bool(payload.get("location_text_en")),
            f"GPS{index}: bilingual location readout",
            expected="both location strings",
            actual={"vi": payload.get("location_text_vi"), "en": payload.get("location_text_en")},
        )

    validation_session = rate_limit_session or create_session(client, book, "en", "US", "sos-validation")
    validation_cases = [
        ("unknown session", {"session_id": str(uuid.uuid4())}, 404),
        ("invalid UUID", {"session_id": "not-a-uuid"}, 400),
        ("partial GPS", {"session_id": validation_session, "lat": 21.03}, 400),
        ("invalid source", {"session_id": validation_session, "source": "agent"}, 400),
        ("invalid threat level", {"session_id": validation_session, "threat_level": "urgent"}, 400),
        ("invalid nationality", {"session_id": validation_session, "nationality": "USA"}, 400),
        ("blank idempotency key", {"session_id": validation_session, "idempotency_key": "   "}, 400),
    ]
    for label, request_payload, expected_status in validation_cases:
        response = client.post("/sos", json=request_payload)
        book.check(response.status_code == expected_status, f"/sos validation: {label}", expected=expected_status, actual=response.status_code)


def run_risk_concurrency_case(client: TestClient, book: ResultBook) -> None:
    print("\n--- Module 3 concurrent risk state ---")
    session_id = create_session(client, book, "en", "US", "risk-concurrency")
    assessment = {
        "recommended_level": "HIGH",
        "threat_category": "harassment_sexual",
    }
    errors: list[str] = []

    def update_once() -> tuple[str, float]:
        if client.portal is None:
            raise RuntimeError("TestClient portal is unavailable")
        return client.portal.call(update_session_risk, session_id, assessment)

    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(update_once) for _ in range(5)]
            for future in futures:
                try:
                    future.result(timeout=10)
                except Exception as exc:  # noqa: BLE001 - capture every concurrent failure
                    errors.append(f"{type(exc).__name__}: {exc}")

        async def read_and_cleanup() -> Any:
            async with get_pool().acquire() as connection:
                row = await connection.fetchrow(
                    """
                    SELECT total_score, jsonb_array_length(escalation_history) AS history_length
                    FROM threat_risk_state
                    WHERE session_id = $1
                    """,
                    uuid.UUID(session_id),
                )
                await connection.execute("DELETE FROM sessions WHERE id = $1", uuid.UUID(session_id))
                return row

        if client.portal is None:
            raise RuntimeError("TestClient portal is unavailable")
        row = client.portal.call(read_and_cleanup)
        actual = {
            "errors": errors,
            "total_score": float(row["total_score"]) if row else None,
            "history_length": int(row["history_length"]) if row else None,
        }
        book.check(
            not errors
            and row is not None
            and float(row["total_score"]) == 100.0
            and int(row["history_length"]) == 5,
            "risk state: concurrent updates are not lost",
            expected={"errors": [], "total_score": 100.0, "history_length": 5},
            actual=actual,
        )
    finally:
        if errors:
            try:
                async def cleanup() -> None:
                    async with get_pool().acquire() as connection:
                        await connection.execute("DELETE FROM sessions WHERE id = $1", uuid.UUID(session_id))

                if client.portal is not None:
                    client.portal.call(cleanup)
            except Exception:
                pass


def run_contract(dataset: dict[str, Any]) -> int:
    book = ResultBook("contract")
    previous_mode = ai_client.mode
    ai_client.mode = "mock"
    try:
        run_pure_contract_cases(dataset, book)
        with TestClient(app) as client:
            health = client.get("/health")
            book.check(health.status_code == 200, "application startup and health", expected=200, actual=health.status_code)
            readiness = client.get("/ready")
            book.check(
                readiness.status_code == 200
                and readiness.json().get("dependencies") == {"postgres": "ok", "qdrant": "ok"},
                "application dependency readiness",
                expected={"postgres": "ok", "qdrant": "ok"},
                actual={"status": readiness.status_code, "body": readiness.json()},
            )
            with temporary_qdrant_patterns(dataset, book):
                run_chat_contract_cases(client, dataset, book)
                run_risk_concurrency_case(client, book)
                run_sos_contract_cases(client, dataset, book)
    finally:
        ai_client.mode = previous_mode
    return book.finish()


def require_live_keys(book: ResultBook, *, audio: bool) -> bool:
    required = {
        "GLM API key": settings.ai_chat_api_key or settings.glm_api_key or settings.ai_api_key,
        "Vietnamese embedding API key": (
            settings.ai_embed_api_key or settings.vn_embedding_api_key or settings.ai_api_key
        ),
    }
    if audio:
        required["Whisper API key"] = (
            settings.ai_stt_api_key
            or settings.whisper_v3_api_key
            or settings.ai_chat_api_key
            or settings.ai_api_key
        )
    for label, value in required.items():
        book.check(bool(value), f"configuration: {label} present", expected=True, actual=bool(value))
    return all(required.values())


def run_live(dataset: dict[str, Any]) -> int:
    book = ResultBook("live")
    previous_mode = ai_client.mode
    ai_client.mode = "live"
    if not require_live_keys(book, audio=False):
        ai_client.mode = previous_mode
        return book.finish()

    case_metrics: list[dict[str, Any]] = []
    try:
        with TestClient(app) as client:
            with temporary_qdrant_patterns(dataset, book):
                replay_request: dict[str, Any] | None = None
                replay_payload: dict[str, Any] | None = None
                for sequence, case in enumerate(dataset["chat_live_cases"], start=1001):
                    session_id = create_session(client, book, case["native_language"], case["nationality"], case["id"])
                    request_payload = {
                        "session_id": session_id,
                        "text": case["text"],
                        "speaker_role": case["speaker_role"],
                        "region": case["region"],
                        "chunk_sequence_id": sequence,
                    }
                    started = time.perf_counter()
                    try:
                        response = client.post("/chat", json=request_payload)
                    except Exception as exc:  # noqa: BLE001 - quality run must continue after one provider failure
                        elapsed = round(time.perf_counter() - started, 3)
                        error = f"{type(exc).__name__}: {exc}"
                        book.check(False, f"{case['id']}: live /chat request exception", expected="HTTP response", actual=error)
                        metric = {"id": case["id"], "elapsed_seconds": elapsed, "status": "exception", "error": error}
                        case_metrics.append(metric)
                        print(f"[METRIC] {json.dumps(metric, ensure_ascii=False)}")
                        continue
                    elapsed = round(time.perf_counter() - started, 3)
                    book.check(response.status_code == 200, f"{case['id']}: live /chat status", expected=200, actual=response.status_code)
                    metric: dict[str, Any] = {"id": case["id"], "elapsed_seconds": elapsed, "status": response.status_code}
                    if response.status_code == 200:
                        payload = response.json()
                        check_chat_payload(
                            book,
                            case,
                            payload,
                            check_prices=True,
                            require_semantic_translation=True,
                        )
                        metric.update(
                            {
                                "prices": payload.get("normalized_prices_vnd"),
                                "scam_categories": sorted(scam_categories(payload)),
                                "threat_level": payload.get("threat", {}).get("final_level"),
                                "scam_prefilter_mode": payload.get("scam_prefilter_status", {}).get("mode"),
                                "degraded_components": payload.get("degraded_components"),
                                "detected_language": payload.get("detected_language"),
                            }
                        )
                        if replay_request is None:
                            replay_request = request_payload
                            replay_payload = payload
                    case_metrics.append(metric)
                    print(f"[METRIC] {json.dumps(metric, ensure_ascii=False)}")

                if replay_request and replay_payload:
                    replay = client.post("/chat", json=replay_request)
                    book.check(replay.status_code == 200, "L001: live idempotent replay status", expected=200, actual=replay.status_code)
                    book.check(replay.json() == replay_payload, "L001: live idempotent replay body", expected=replay_payload, actual=replay.json())
    finally:
        ai_client.mode = previous_mode
    book.metric("cases", case_metrics)
    return book.finish()


def resolve_audio_path(relative_path: str) -> Path:
    return (DATASET_PATH.parent / relative_path).resolve()


def run_audio(dataset: dict[str, Any]) -> int:
    book = ResultBook("audio")
    previous_mode = ai_client.mode
    ai_client.mode = "live"
    if not require_live_keys(book, audio=True):
        ai_client.mode = previous_mode
        return book.finish()

    case_metrics: list[dict[str, Any]] = []
    wers: list[float] = []
    replay_request: dict[str, Any] | None = None
    replay_payload: dict[str, Any] | None = None
    try:
        with TestClient(app) as client:
            with temporary_qdrant_patterns(dataset, book):
                session_id = create_session(client, book, "en", "US", "audio-suite")
                for sequence, case in enumerate(dataset["audio_cases"], start=2001):
                    audio_path = resolve_audio_path(case["file"])
                    exists = audio_path.is_file()
                    book.check(exists, f"{case['id']}: audio fixture exists", expected=True, actual=exists)
                    if not exists:
                        continue
                    request_payload = {
                        "session_id": session_id,
                        "audio_base64": base64.b64encode(audio_path.read_bytes()).decode("ascii"),
                        "audio_format": "wav",
                        "speaker_role": "vendor",
                        "region": "Hanoi",
                        "chunk_sequence_id": sequence,
                        "is_final_chunk": True,
                    }
                    started = time.perf_counter()
                    try:
                        response = client.post("/chat", json=request_payload)
                    except Exception as exc:  # noqa: BLE001 - preserve the rest of the audio benchmark
                        elapsed = round(time.perf_counter() - started, 3)
                        error = f"{type(exc).__name__}: {exc}"
                        book.check(False, f"{case['id']}: full audio request exception", expected="HTTP response", actual=error)
                        metric = {"id": case["id"], "elapsed_seconds": elapsed, "status": "exception", "error": error}
                        case_metrics.append(metric)
                        print(f"[METRIC] {json.dumps(metric, ensure_ascii=False)}")
                        continue
                    elapsed = round(time.perf_counter() - started, 3)
                    book.check(response.status_code == 200, f"{case['id']}: full audio /chat status", expected=200, actual=response.status_code)
                    metric: dict[str, Any] = {"id": case["id"], "elapsed_seconds": elapsed, "status": response.status_code}
                    if response.status_code == 200:
                        payload = response.json()
                        transcript = payload.get("source_text") or ""
                        wer = word_error_rate(case["reference"], transcript)
                        wers.append(wer)
                        metric.update(
                            {
                                "wer": round(wer, 4),
                                "max_wer": case["max_wer"],
                                "transcript": transcript,
                                "prices": payload.get("normalized_prices_vnd"),
                                "scam_categories": sorted(scam_categories(payload)),
                                "threat_level": payload.get("threat", {}).get("final_level"),
                                "scam_prefilter_mode": payload.get("scam_prefilter_status", {}).get("mode"),
                                "degraded_components": payload.get("degraded_components"),
                            }
                        )
                        book.check(wer <= case["max_wer"], f"{case['id']}: WER threshold", expected=f"<={case['max_wer']}", actual=round(wer, 4))
                        missing = sorted(REQUIRED_CHAT_FIELDS - payload.keys())
                        book.check(not missing, f"{case['id']}: complete audio /chat response contract", expected=[], actual=missing)
                        book.check(bool(payload.get("translation")), f"{case['id']}: audio translation present", expected="non-empty", actual=payload.get("translation"))
                        book.check(payload.get("target_language") == "en", f"{case['id']}: audio target language", expected="en", actual=payload.get("target_language"))
                        translation_details = payload.get("translation_details") or {}
                        book.check(
                            translation_details.get("speaker_role") == "vendor"
                            and translation_details.get("translation_direction") == "vendor_to_tourist",
                            f"{case['id']}: audio translation direction",
                            expected={"speaker_role": "vendor", "translation_direction": "vendor_to_tourist"},
                            actual=translation_details,
                        )
                        book.check(
                            translation_details.get("degraded") is False,
                            f"{case['id']}: audio translation provider completed",
                            expected=False,
                            actual=translation_details.get("degraded"),
                        )
                        if payload.get("detected_language") != "en":
                            book.check(
                                " ".join(str(payload.get("translation") or "").casefold().split())
                                != " ".join(transcript.casefold().split()),
                                f"{case['id']}: audio semantic translation changed language",
                                expected="English text distinct from Vietnamese transcript",
                                actual=payload.get("translation"),
                            )
                        book.check(payload.get("detected_language") == case["expected_detected_language"], f"{case['id']}: audio detected language", expected=case["expected_detected_language"], actual=payload.get("detected_language"))
                        book.check(payload.get("resolved_region") == "Hanoi", f"{case['id']}: audio resolved region", expected="Hanoi", actual=payload.get("resolved_region"))
                        book.check(bool(payload.get("server_turn_id")), f"{case['id']}: audio turn persisted", expected="non-empty UUID", actual=payload.get("server_turn_id"))
                        book.check(payload.get("threat", {}).get("final_level") == case["expected_threat"], f"{case['id']}: audio threat level", expected=case["expected_threat"], actual=payload.get("threat"))
                        prefilter = payload.get("scam_prefilter_status") or {}
                        qdrant_or_safe_fallback = prefilter.get("qdrant_ok") is True or (
                            prefilter.get("mode") == "rule_fallback_only"
                            and "scam_prefilter" in (payload.get("degraded_components") or [])
                            and bool(prefilter.get("errors"))
                        )
                        book.check(
                            qdrant_or_safe_fallback,
                            f"{case['id']}: audio scam prefilter available or explicitly degraded",
                            expected="Qdrant result or marked rule fallback",
                            actual={"prefilter": prefilter, "degraded_components": payload.get("degraded_components")},
                        )
                        if "expected_prices" in case:
                            book.check(payload.get("normalized_prices_vnd") == case["expected_prices"], f"{case['id']}: audio normalized VND prices", expected=case["expected_prices"], actual=payload.get("normalized_prices_vnd"))
                        if "expected_scam" in case:
                            categories = scam_categories(payload)
                            book.check(case["expected_scam"] in categories, f"{case['id']}: audio scam classification", expected=case["expected_scam"], actual=sorted(categories))
                        if case["id"] == "W002":
                            replay_request = request_payload
                            replay_payload = payload
                    case_metrics.append(metric)
                    print(f"[METRIC] {json.dumps(metric, ensure_ascii=False)}")

                if replay_request and replay_payload:
                    replay = client.post("/chat", json=replay_request)
                    book.check(replay.status_code == 200, "W002: audio idempotent replay status", expected=200, actual=replay.status_code)
                    book.check(replay.json() == replay_payload, "W002: audio idempotent replay body", expected=replay_payload, actual=replay.json())
    finally:
        ai_client.mode = previous_mode

    mean_wer = sum(wers) / len(wers) if wers else 1.0
    book.check(len(wers) == len(dataset["audio_cases"]), "audio suite: all cases produced transcripts", expected=len(dataset["audio_cases"]), actual=len(wers))
    book.check(mean_wer <= 0.35, "audio suite: mean WER", expected="<=0.35", actual=round(mean_wer, 4))
    book.metric("mean_wer", round(mean_wer, 4))
    book.metric("cases", case_metrics)
    return book.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("contract", "live", "audio"), required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = load_dataset()
    print(f"Dataset: {dataset['namespace']} v{dataset['version']}")
    print(f"Suite: {args.suite}")
    if args.suite == "contract":
        return run_contract(dataset)
    if args.suite == "live":
        return run_live(dataset)
    return run_audio(dataset)


if __name__ == "__main__":
    raise SystemExit(main())
