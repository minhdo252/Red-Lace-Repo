"""Standalone tests for the voice-route fair-price check.

Covers two units:
  - app.modules.transcript_price_extract: (item, price) extraction from a
    transcript — the deterministic heuristic and the hallucination guard on the
    LLM path.
  - app.routers.chat._run_voice_price_check: turning extracted pairs +
    compare_price results into a price_scam flag, a price_analysis verdict, and a
    native-language warning note, plus graceful degradation.

No Postgres/Qdrant/live AI needed: compare_price and extract_priced_items are
patched, and AI_MODE defaults to "mock". Same runner shape as test_pricing.py.

Run:
    cd backend && python tests/test_voice_price_check.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules import transcript_price_extract as tpe  # noqa: E402
from app.routers import chat as chat_module  # noqa: E402


# ----- transcript_price_extract: heuristic ------------------------------------

def test_heuristic_pairs_bun_cha_digit() -> None:
    pairs = tpe.heuristic_priced_items("cô bán bún chả này 200k")
    assert pairs == [{"item": "bún chả", "price_vnd": 200000, "source": "heuristic"}], pairs
    print("[PASS] test_heuristic_pairs_bun_cha_digit")


def test_heuristic_pairs_bun_cha_spelled() -> None:
    pairs = tpe.heuristic_priced_items("bún chả này hai trăm nghìn")
    assert pairs == [{"item": "bún chả", "price_vnd": 200000, "source": "heuristic"}], pairs
    print("[PASS] test_heuristic_pairs_bun_cha_spelled")


def test_heuristic_ignores_priceless_text() -> None:
    assert tpe.heuristic_priced_items("cảm ơn cô nhiều nhé") == []
    # A phone number is not a price.
    assert tpe.heuristic_priced_items("số điện thoại của tôi là 0903 123 456") == []
    print("[PASS] test_heuristic_ignores_priceless_text")


# ----- transcript_price_extract: LLM path + hallucination guard ---------------

async def test_llm_price_rejected_when_not_in_text() -> None:
    # Model proposes a price that the deterministic normaliser never saw -> reject
    # the LLM output and fall back to the heuristic (which finds the real 200000).
    fake = SimpleNamespace(
        chat=lambda **_kwargs: _async_return(
            SimpleNamespace(content='{"items": [{"item": "bún chả", "price_vnd": 999000}]}')
        )
    )
    with patch.object(tpe, "ai_client", fake):
        pairs = await tpe.extract_priced_items("cô bán bún chả này 200k")
    assert pairs == [{"item": "bún chả", "price_vnd": 200000, "source": "heuristic"}], pairs
    print("[PASS] test_llm_price_rejected_when_not_in_text")


async def test_llm_price_accepted_when_in_text() -> None:
    fake = SimpleNamespace(
        chat=lambda **_kwargs: _async_return(
            SimpleNamespace(content='{"items": [{"item": "Bún Chả", "price_vnd": 200000}]}')
        )
    )
    with patch.object(tpe, "ai_client", fake):
        pairs = await tpe.extract_priced_items("cô bán bún chả này 200k")
    assert pairs == [{"item": "bún chả", "price_vnd": 200000, "source": "llm"}], pairs
    print("[PASS] test_llm_price_accepted_when_in_text")


async def test_extract_no_price_is_noop() -> None:
    # Gate: no explicit amount -> zero AI work, empty result. ai_client must not
    # be touched; a raising fake proves the gate short-circuits before the call.
    boom = SimpleNamespace(chat=lambda **_kwargs: _raise(AssertionError("chat should not be called")))
    with patch.object(tpe, "ai_client", boom):
        assert await tpe.extract_priced_items("cho tôi hỏi đường ra hồ") == []
    print("[PASS] test_extract_no_price_is_noop")


# ----- chat._run_voice_price_check --------------------------------------------

_OVERPRICED = {
    "reference_price": 62000,
    "reference_price_range": [59000, 69000],
    "price_diff_pct": 222.6,
    "flag": "cao hơn giá tham chiếu 223% — trung bình có trọng số 3 món gần nhất giá 62,000 VND",
}


async def test_voice_price_check_flags_overpriced() -> None:
    with patch.object(chat_module, "extract_priced_items", lambda _t: _async_return(
        [{"item": "bún chả", "price_vnd": 200000, "source": "llm"}]
    )), patch.object(chat_module, "compare_price", lambda **_k: _async_return(dict(_OVERPRICED))):
        result = await chat_module._run_voice_price_check("cô bán bún chả này 200k", "Hanoi", "en")

    flags = result["scam_flags"]
    assert len(flags) == 1, flags
    assert flags[0]["category"] == "price_scam", flags
    assert flags[0]["source"] == "price_comparison", flags
    assert flags[0]["best_score"] >= 0.72, flags
    assert result["price_analysis"]["overall_overpriced"] is True, result["price_analysis"]
    tools = [t.get("tool") for t in result["tools_invoked"]]
    assert tools == ["compare_price"], tools
    assert result["reply_note"] and "bún chả" in result["reply_note"], result["reply_note"]
    assert result["degraded"] is False, result
    print("[PASS] test_voice_price_check_flags_overpriced")


async def test_voice_price_check_fair_price_no_flag() -> None:
    fair = {"reference_price": 60000, "reference_price_range": [55000, 65000], "price_diff_pct": 5.0, "flag": None}
    with patch.object(chat_module, "extract_priced_items", lambda _t: _async_return(
        [{"item": "bún chả", "price_vnd": 63000, "source": "llm"}]
    )), patch.object(chat_module, "compare_price", lambda **_k: _async_return(dict(fair))):
        result = await chat_module._run_voice_price_check("bún chả này 63k", "Hanoi", "en")
    assert result["scam_flags"] == [], result
    assert result["price_analysis"]["overall_overpriced"] is False, result
    assert result["reply_note"] is None, result
    print("[PASS] test_voice_price_check_fair_price_no_flag")


async def test_voice_price_check_compare_error_does_not_crash() -> None:
    with patch.object(chat_module, "extract_priced_items", lambda _t: _async_return(
        [{"item": "bún chả", "price_vnd": 200000, "source": "llm"}]
    )), patch.object(chat_module, "compare_price", lambda **_k: _raise(RuntimeError("qdrant down"))):
        result = await chat_module._run_voice_price_check("cô bán bún chả này 200k", "Hanoi", "vi")
    # compare failed for the single item -> no flag, but a benign (non-degraded)
    # envelope with the item recorded and no reference price.
    assert result["scam_flags"] == [], result
    assert result["price_analysis"] is not None, result
    assert result["price_analysis"]["items"][0]["reference_price"] is None, result
    assert result["degraded"] is False, result
    print("[PASS] test_voice_price_check_compare_error_does_not_crash")


async def test_voice_price_check_times_out_degrades() -> None:
    async def _slow(_t):
        await asyncio.sleep(0.5)
        return []

    with patch.object(chat_module, "settings", SimpleNamespace(price_check_deadline_seconds=0.05)), \
            patch.object(chat_module, "extract_priced_items", _slow):
        result = await chat_module._run_voice_price_check("cô bán bún chả này 200k", "Hanoi", "en")
    assert result["degraded"] is True, result
    assert result["degradation_reason"] == "price_check_timeout", result
    assert result["scam_flags"] == [] and result["price_analysis"] is None, result
    print("[PASS] test_voice_price_check_times_out_degrades")


# ----- helpers ----------------------------------------------------------------

async def _async_return(value):
    return value


def _raise(exc):
    async def _coro():
        raise exc
    return _coro()


async def main() -> None:
    tests = [
        test_heuristic_pairs_bun_cha_digit,
        test_heuristic_pairs_bun_cha_spelled,
        test_heuristic_ignores_priceless_text,
        test_llm_price_rejected_when_not_in_text,
        test_llm_price_accepted_when_in_text,
        test_extract_no_price_is_noop,
        test_voice_price_check_flags_overpriced,
        test_voice_price_check_fair_price_no_flag,
        test_voice_price_check_compare_error_does_not_crash,
        test_voice_price_check_times_out_degrades,
    ]
    failures = 0
    for test in tests:
        try:
            result = test()
            if asyncio.iscoroutine(result):
                await result
        except AssertionError as exc:
            failures += 1
            print(f"[FAIL] {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface any unexpected error in the test itself
            failures += 1
            print(f"[ERROR] {test.__name__}: {type(exc).__name__}: {exc}")

    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
