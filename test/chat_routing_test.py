"""Smoke test: deterministic input-type routing in POST /chat.

Design: docs/superpowers/specs/2026-07-18-chat-input-routing-design.md

Drives the REAL /chat flow with REAL fixtures (text, a menu photo, a recorded
WAV) against a running backend and asserts each input type is dispatched to the
right route:

  - text  -> "text"  route (full orchestrator pipeline)
  - image -> "image" route (Module 2.1 only: no orchestrator; a price verdict
             via price_analysis, or a needs_retake signal when the menu can't
             be read)
  - voice -> "voice" route (Module 1 translate + scam + threat + fair-price check;
             NO orchestrator, so the only tool that may appear is compare_price)

This is a routing test: it asserts the dispatch + envelope shape, which holds in
both AI_MODE=mock and AI_MODE=live. The real-content assertions (a real price for
a real menu, W006 -> threat CRITICAL) are covered by the live run and by
test/module13_synthetic's audio/live suites.

Run against a running stack (host default localhost:8000):
    python test/chat_routing_test.py
    CHAT_ROUTING_BASE_URL=http://backend:8000 python test/chat_routing_test.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("CHAT_ROUTING_BASE_URL", "http://localhost:8000").rstrip("/")
REPO_ROOT = Path(__file__).resolve().parent.parent
MENU_IMAGE = REPO_ROOT / "test" / "menu 1.jpg"
VOICE_WAV = REPO_ROOT / "test" / "module13_whisper" / "audio" / "w006_sos_request.wav"

_failures: list[str] = []


def _post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, headers={"content-type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - local trusted URL
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # don't let one route's error abort the run
        return {"_http_status": exc.code, "_http_detail": exc.read().decode("utf-8", "replace")}


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        _failures.append(name)


def _new_session() -> str:
    resp = _post("/sessions", {"native_language": "en", "nationality": "US"})
    return resp["session_id"]


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def test_text_route(sid: str) -> None:
    print("text input -> text route")
    resp = _post(
        "/chat/text",
        {"session_id": sid, "text": "Where is Hoan Kiem Lake?", "speaker_role": "tourist", "region": "Hanoi"},
    )
    check("input_route == 'text'", resp.get("input_route") == "text", str(resp.get("input_route")))
    check("reply is a non-empty string", isinstance(resp.get("reply"), str) and bool(resp["reply"]))
    # A general question must NOT trip the price-check intent.
    check("general question: no price_analysis (orchestrator path)", resp.get("price_analysis") is None)


def test_price_intent_route(sid: str) -> None:
    print("typed price question -> Module 2.1 (no Qwen-VL, no orchestrator LLM)")
    resp = _post(
        "/chat/text",
        {"session_id": sid, "text": "bún đậu 200k có đắt không", "speaker_role": "tourist", "region": "Hanoi"},
    )
    check("price intent: input_route == 'text'", resp.get("input_route") == "text", str(resp.get("input_route")))
    check("price intent: price_analysis present", resp.get("price_analysis") is not None)
    tools = {t.get("tool") for t in resp.get("tools_invoked") or []}
    check("price intent: only compare_price ran (no orchestrator)", tools == {"compare_price"}, str(tools))


def test_image_route(sid: str) -> None:
    print("menu photo -> image route (Module 2.1 only)")
    if not MENU_IMAGE.exists():
        check("menu fixture exists", False, f"missing {MENU_IMAGE}")
        return
    resp = _post(
        "/chat",
        {
            "session_id": sid,
            "text": "Xem giúp tôi ảnh này.",
            "region": "Hanoi",
            "speaker_role": "tourist",
            "images": [{"image_base64": _b64(MENU_IMAGE), "mode": "receipt"}],
        },
    )
    check("input_route == 'image'", resp.get("input_route") == "image", str(resp.get("input_route")))
    # Module 2.1 only: the orchestrator never runs, so the only tool that may appear
    # is compare_price (invoked deterministically per priced item).
    tools = {t.get("tool") for t in resp.get("tools_invoked") or []}
    check("no orchestrator tools (only compare_price allowed)", tools <= {"compare_price"}, str(tools))
    # Either a real price verdict OR a retake signal — never both, never neither.
    has_verdict = resp.get("price_analysis") is not None
    needs_retake = bool(resp.get("needs_retake"))
    check("price verdict XOR needs_retake", has_verdict != needs_retake,
          f"price_analysis={has_verdict} needs_retake={needs_retake} reason={resp.get('retake_reason')}")


def test_voice_route(sid: str) -> None:
    print("recorded audio -> voice route (Module 1 + safety, no orchestrator)")
    if not VOICE_WAV.exists():
        check("voice fixture exists", False, f"missing {VOICE_WAV}")
        return
    resp = _post(
        "/chat",
        {
            "session_id": sid,
            "audio_base64": _b64(VOICE_WAV),
            "audio_format": "wav",
            "region": "Hanoi",
            "speaker_role": "tourist",
        },
    )
    if resp.get("_http_status") == 503:
        print(f"  [SKIP] voice route — STT unavailable on this backend (503): "
              f"{resp.get('_http_detail', '')[:90]}")
        return
    check("input_route == 'voice'", resp.get("input_route") == "voice", str(resp.get("input_route")))
    # Voice drops the orchestrator -> the only tool that may appear is compare_price,
    # invoked deterministically by the fair-price check when a spoken price is heard.
    tools = {t.get("tool") for t in resp.get("tools_invoked") or []}
    check("no orchestrator tools (only compare_price allowed)", tools <= {"compare_price"}, str(tools))
    # Safety envelope must still be present (this is the W006 SOS path).
    check("threat present (Module 3 ran)", isinstance(resp.get("threat"), dict))
    check("scam_flags present (scam prefilter ran)", isinstance(resp.get("scam_flags"), list))


def main() -> int:
    print(f"chat routing smoke test against {BASE_URL}\n")
    try:
        sid = _new_session()
    except Exception as exc:  # noqa: BLE001
        print(f"could not create a session ({exc}). Is the backend running at {BASE_URL}?")
        return 2
    print(f"session_id = {sid}\n")
    test_text_route(sid)
    test_price_intent_route(sid)
    test_image_route(sid)
    test_voice_route(sid)
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): {', '.join(_failures)}")
        return 1
    print("ALL ROUTING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
