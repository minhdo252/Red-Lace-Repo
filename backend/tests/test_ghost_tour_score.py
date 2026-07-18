"""Mock-only tests for app/modules/ghost_tour_score.py covering this round's
changes: placeholder-text filtering, region becoming optional, the new
review_burst signal, and the An toàn/Không an toàn safety-label layer.

No network/DB — check_domain_age / check_business_existence /
estimate_fair_price / match_scam_pattern are monkeypatched where
check_ghost_tour() needs to call them; compute_ghost_tour_score() and
translate_to_safety_label() are pure functions and need no patching at all.

Run:
    cd backend && python tests/test_ghost_tour_score.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules import ghost_tour_score as gts  # noqa: E402


# --- Việc 1: placeholder-text normalization ---------------------------------

async def test_normalize_optional_text_catches_placeholders() -> None:
    placeholders = [
        "No suspicious text provided", "  NONE  ", "n/a", "N/A", "not provided",
        "không có", "Không Có Gì", "", "   ",
    ]
    for p in placeholders:
        assert gts._normalize_optional_text(p) is None, f"{p!r} should normalize to None"
    assert gts._normalize_optional_text("book ngay hom nay, giu cho gap!") == "book ngay hom nay, giu cho gap!"
    assert gts._normalize_optional_text(None) is None
    print("[PASS] test_normalize_optional_text_catches_placeholders")


async def test_check_ghost_tour_ignores_placeholder_suspicious_text() -> None:
    called = {"match_scam_pattern": False}

    async def fake_match_scam_pattern(*args, **kwargs):
        called["match_scam_pattern"] = True
        return {"category": "ghost_tour_pressure", "matches": [], "best_score": 0.0, "flagged_as_new_candidate": True}

    async def fake_check_domain_age(url):
        return {"domain": "example.com", "created": "2020-01-01T00:00:00+00:00", "age_days": 2000, "risk": "low"}

    with patch.object(gts, "match_scam_pattern", fake_match_scam_pattern), \
         patch.object(gts, "check_domain_age", fake_check_domain_age):
        result = await gts.check_ghost_tour(
            region="Vietnam", url="https://example.com", suspicious_text="No suspicious text provided"
        )

    assert called["match_scam_pattern"] is False, "placeholder text must not reach match_scam_pattern"
    scam_entry = next(b for b in result["breakdown"] if b["signal"] == "scam_pattern")
    assert scam_entry["available"] is False, scam_entry
    print("[PASS] test_check_ghost_tour_ignores_placeholder_suspicious_text")


# --- follow-up: auto-resolve name from url when name is missing -------------

async def test_check_ghost_tour_resolves_name_from_url_when_missing() -> None:
    captured = {}

    async def fake_extract_business_key_from_url(url):
        return "profile.php?id=61553172142739"

    async def fake_check_business_existence(name, region=None, url=None):
        captured["name"] = name
        return {"status": "found", "name": name, "review_count": 10, "recent_reviews": [], "data_source": "mock"}

    with patch.object(gts, "extract_business_key_from_url", fake_extract_business_key_from_url), \
         patch.object(gts, "check_business_existence", fake_check_business_existence):
        result = await gts.check_ghost_tour(url="https://www.facebook.com/share/1BLRpkFw2C/?mibextid=wwXIfr")

    assert captured["name"] == "profile.php?id=61553172142739", captured
    business_entry = next(b for b in result["breakdown"] if b["signal"] == "business_existence")
    assert business_entry["available"] is True, business_entry
    print("[PASS] test_check_ghost_tour_resolves_name_from_url_when_missing")


async def test_check_ghost_tour_business_existence_unavailable_when_resolver_fails() -> None:
    async def fake_extract_business_key_from_url(url):
        return None  # not a Facebook URL, or the redirect couldn't be resolved

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("check_business_existence must not be called when no name could be resolved")

    with patch.object(gts, "extract_business_key_from_url", fake_extract_business_key_from_url), \
         patch.object(gts, "check_business_existence", fail_if_called):
        result = await gts.check_ghost_tour(url="https://example.com/not-a-facebook-link")

    business_entry = next(b for b in result["breakdown"] if b["signal"] == "business_existence")
    assert business_entry["available"] is False, business_entry
    print("[PASS] test_check_ghost_tour_business_existence_unavailable_when_resolver_fails")


# --- Việc 3: region optional --------------------------------------------------

async def test_price_anomaly_missing_region_reports_specific_reason() -> None:
    result = await gts.check_ghost_tour(region=None, name=None, url=None, item="homestay 1 night", observed_price=100000)
    price_entry = next(b for b in result["breakdown"] if b["signal"] == "price_anomaly")
    assert price_entry["available"] is False, price_entry
    assert "region" in price_entry["reason"], price_entry
    print("[PASS] test_price_anomaly_missing_region_reports_specific_reason")


async def test_business_existence_runs_without_region() -> None:
    async def fake_check_business_existence(name, region=None, url=None):
        assert region is None, "region should be passed through as None, not substituted"
        return {"status": "found", "name": name, "rating": 4.5, "review_count": 100, "recent_reviews": [], "data_source": "mock"}

    with patch.object(gts, "check_business_existence", fake_check_business_existence):
        result = await gts.check_ghost_tour(region=None, name="Some Homestay")

    business_entry = next(b for b in result["breakdown"] if b["signal"] == "business_existence")
    assert business_entry["available"] is True, business_entry
    print("[PASS] test_business_existence_runs_without_region")


# --- Việc 4: review_burst signal ---------------------------------------------

def test_review_burst_detected_scores_as_available_low_confidence() -> None:
    result = gts.compute_ghost_tour_score(
        business_existence={"status": "found", "review_burst": {"detected": True, "reason": "test"}},
    )
    entry = next(b for b in result["breakdown"] if b["signal"] == "review_burst")
    assert entry["available"] is True, entry
    assert entry["confidence"] == "low", entry
    assert entry["risk_contribution"] == 0.6, entry
    print("[PASS] test_review_burst_detected_scores_as_available_low_confidence")


def test_review_burst_not_detected_scores_low_risk() -> None:
    result = gts.compute_ghost_tour_score(
        business_existence={"status": "found", "review_burst": {"detected": False, "reason": "test"}},
    )
    entry = next(b for b in result["breakdown"] if b["signal"] == "review_burst")
    assert entry["available"] is True, entry
    assert entry["risk_contribution"] == 0.1, entry
    print("[PASS] test_review_burst_not_detected_scores_low_risk")


def test_review_burst_unavailable_when_business_not_found() -> None:
    result = gts.compute_ghost_tour_score(business_existence={"status": "not_found"})
    entry = next(b for b in result["breakdown"] if b["signal"] == "review_burst")
    assert entry["available"] is False, entry
    print("[PASS] test_review_burst_unavailable_when_business_not_found")


# --- Việc 5: safety label -----------------------------------------------------

def test_safety_label_an_toan_when_found_and_nothing_else_triggers() -> None:
    result = gts.compute_ghost_tour_score(business_existence={"status": "found", "review_burst": {"detected": False}})
    assert result["safety"]["label"] == "An toàn", result["safety"]
    assert result["safety"]["reasons"] == ["Khớp với link trên Google Map"]
    print("[PASS] test_safety_label_an_toan_when_found_and_nothing_else_triggers")


def test_safety_label_insufficient_data_when_business_existence_unavailable() -> None:
    result = gts.compute_ghost_tour_score(domain_age={"risk": "low"})  # business_existence never checked
    assert result["safety"]["label"] == "Không an toàn", result["safety"]
    assert result["safety"]["reasons"] == ["Chưa đủ dữ liệu để xác minh"]
    print("[PASS] test_safety_label_insufficient_data_when_business_existence_unavailable")


def test_safety_label_lists_every_triggered_reason_simultaneously() -> None:
    result = gts.compute_ghost_tour_score(
        domain_age={"risk": "high", "domain": "fake.com", "age_days": 10},
        business_existence={"status": "not_found"},
        price_anomaly={"price_direction": "low"},
        scam_pattern={"best_score": 0.9, "matches": [], "flagged_as_new_candidate": False},
    )
    reasons = set(result["safety"]["reasons"])
    assert result["safety"]["label"] == "Không an toàn"
    assert reasons == {
        "Thời điểm tạo web gần đây",
        "Không khớp với link trên Google Map",
        "Giá thấp bất thường so với mặt bằng",
        "Phát hiện ngôn ngữ thúc giục/mồi câu thường gặp ở lừa đảo",
    }, reasons
    print("[PASS] test_safety_label_lists_every_triggered_reason_simultaneously")


def test_safety_label_domain_age_takes_priority_over_page_transparency() -> None:
    # domain_age says low risk (old domain); page_transparency disagrees (says
    # recently created) — domain_age must win, so no "recently created" reason.
    result = gts.compute_ghost_tour_score(
        domain_age={"risk": "low", "domain": "real.com", "age_days": 5000},
        page_transparency={"risk": "high", "page_age_days": 10, "recent_name_change": False},
        business_existence={"status": "found"},
    )
    assert "Thời điểm tạo web gần đây" not in result["safety"]["reasons"], result["safety"]
    assert result["safety"]["label"] == "An toàn", result["safety"]
    print("[PASS] test_safety_label_domain_age_takes_priority_over_page_transparency")


def test_safety_label_falls_back_to_page_transparency_when_domain_age_missing() -> None:
    result = gts.compute_ghost_tour_score(
        page_transparency={"risk": "high", "page_age_days": 10, "recent_name_change": False},
        business_existence={"status": "found"},
    )
    assert "Thời điểm tạo web gần đây" in result["safety"]["reasons"], result["safety"]
    assert result["safety"]["label"] == "Không an toàn", result["safety"]
    print("[PASS] test_safety_label_falls_back_to_page_transparency_when_domain_age_missing")


TESTS = [
    test_normalize_optional_text_catches_placeholders,
    test_check_ghost_tour_ignores_placeholder_suspicious_text,
    test_check_ghost_tour_resolves_name_from_url_when_missing,
    test_check_ghost_tour_business_existence_unavailable_when_resolver_fails,
    test_price_anomaly_missing_region_reports_specific_reason,
    test_business_existence_runs_without_region,
    test_review_burst_detected_scores_as_available_low_confidence,
    test_review_burst_not_detected_scores_low_risk,
    test_review_burst_unavailable_when_business_not_found,
    test_safety_label_an_toan_when_found_and_nothing_else_triggers,
    test_safety_label_insufficient_data_when_business_existence_unavailable,
    test_safety_label_lists_every_triggered_reason_simultaneously,
    test_safety_label_domain_age_takes_priority_over_page_transparency,
    test_safety_label_falls_back_to_page_transparency_when_domain_age_missing,
]


async def main() -> None:
    failures = 0
    for test in TESTS:
        try:
            if asyncio.iscoroutinefunction(test):
                await test()
            else:
                test()
        except AssertionError as exc:
            failures += 1
            print(f"[FAIL] {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[ERROR] {test.__name__}: {type(exc).__name__}: {exc}")

    print(f"\n{len(TESTS) - failures}/{len(TESTS)} passed")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
