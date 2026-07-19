"""Ghost-tour / homestay-scam composite trust score (doc section 7, signal 6).

Combines whatever of the other 5 module-2.2 signals is available for a
given check into one weighted score with a transparent per-signal
breakdown — never a single opaque number, per the doc's explicit design
principle. A signal with no usable data (missing input, an unconfigured
API key, a failed lookup, a VLM parse failure) is excluded from the
weighted average entirely rather than counted as "safe": renormalizing
over only the signals actually evaluated avoids quietly under-counting risk
just because, say, GOOGLE_PLACES_API_KEY isn't set yet.

Default weights/thresholds below are a reasonable starting point, not a
tuned product decision — see the README in this patch for what to adjust
once real check data exists.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.modules.business_check import check_business_existence, extract_business_key_from_url
from app.modules.domain_check import check_domain_age
from app.modules.pricing import estimate_fair_price
from app.modules.scam_detection import UNMATCHED_THRESHOLD, match_scam_pattern

SIGNAL_WEIGHTS: dict[str, float] = {
    "domain_age": 0.15,
    "page_transparency": 0.20,
    "business_existence": 0.15,
    "review_burst": 0.05,
    "price_anomaly": 0.25,
    "scam_pattern": 0.25,
}

# (min_score_inclusive, label) — checked in order, first match wins.
RISK_LEVEL_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (0.66, "high"),
    (0.33, "medium"),
)

_UNAVAILABLE = "signal unavailable (required input missing, or the lookup failed/isn't configured)"

# Model-hallucinated placeholders for "I don't actually have this" — a live
# model asked for suspicious_text/name/url/item it doesn't have will often
# write one of these instead of simply omitting the argument. Checking
# `if field:` alone treats any non-empty string as real data, so a
# placeholder silently becomes a real (and wrong) signal input: e.g.
# "No suspicious text provided" gets embedded and matched against
# scam_patterns as if it were an actual quote from a seller, dragging the
# composite score around based on nothing, and (for match_scam_pattern
# specifically) gets written into Qdrant's unmatched_reports collection as
# a bogus new-pattern candidate. Matched case-insensitively after
# strip() — anything left blank after stripping is caught before this set
# is even consulted.
_PLACEHOLDER_TEXTS: frozenset[str] = frozenset(
    {
        "no suspicious text provided",
        "no suspicious text",
        "none provided",
        "none",
        "n/a",
        "na",
        "not applicable",
        "not provided",
        "no url provided",
        "no name provided",
        "no data",
        "không có",
        "không có gì",
        "không có thông tin",
        "khong co",
        "khong co gi",
        "khong co thong tin",
    }
)


def _normalize_optional_text(text: str | None) -> str | None:
    """Collapse "" / whitespace-only / any string in _PLACEHOLDER_TEXTS to
    None, so `if field:` downstream means "the model actually gave us
    something" rather than "the model wrote *some* non-empty string"."""
    if text is None:
        return None
    stripped = text.strip()
    if not stripped or stripped.lower() in _PLACEHOLDER_TEXTS:
        return None
    return stripped


async def _safe(coro: Any) -> Any:
    """A single signal erroring (network hiccup, expired key, ...) must not
    take down the whole composite check — treat it the same as "no data"."""
    try:
        return await coro
    except Exception:  # noqa: BLE001 - deliberately broad, see docstring
        return None


def _score_domain_age(result: dict[str, Any] | None) -> tuple[float | None, dict[str, Any]]:
    if result is None or result.get("risk") == "unknown":
        return None, {"available": False, "reason": _UNAVAILABLE}
    risk = 0.9 if result["risk"] == "high" else 0.1
    return risk, {"available": True, "detail": result}


def _score_page_transparency(result: dict[str, Any] | None) -> tuple[float | None, dict[str, Any]]:
    if result is None:
        return None, {"available": False, "reason": "no Page Transparency screenshot provided"}
    if result.get("parse_error") or result.get("risk") == "unknown":
        return None, {
            "available": False,
            "reason": "could not read a page-creation date from the screenshot",
            "detail": result,
        }
    risk = 0.9 if result["risk"] == "high" else 0.1
    if result.get("recent_name_change"):
        risk = min(1.0, risk + 0.2)
    return risk, {"available": True, "detail": result}


def _score_business_existence(result: dict[str, Any] | None) -> tuple[float | None, dict[str, Any]]:
    # "unknown" means the Google Places call itself failed/was rejected
    # (REQUEST_DENIED, OVER_QUERY_LIMIT, ...) — see business_check.py. That's
    # an infra problem, not a signal that the business is suspicious, so it
    # must be excluded the same way "not_configured" already is, not fall
    # through to the review_count/rating scoring below.
    if result is None or result.get("status") in ("not_configured", "unknown"):
        detail = {"reason": _UNAVAILABLE}
        if result is not None and result.get("status") == "unknown":
            detail = {
                "reason": f"Google Places lookup failed: {result.get('api_status')} — {result.get('error_message')}",
            }
        return None, {"available": False, **detail}
    # Gemini web-reputation signal (no Google Places key): score on the verdict's
    # legitimacy / scam-report findings rather than Google's review_count/rating.
    if result.get("data_source") == "gemini_web":
        status = result.get("status")
        if result.get("scam_reports") or result.get("legitimacy") == "suspicious" or status == "not_found":
            return 0.85, {"available": True, "detail": result}
        if status == "found" and result.get("legitimacy") == "legitimate":
            return 0.15, {"available": True, "detail": result}
        return 0.5, {"available": True, "detail": result}  # uncertain / unknown
    if result.get("status") == "not_found":
        return 0.8, {"available": True, "detail": result}
    review_count = result.get("review_count") or 0
    rating = result.get("rating")
    if review_count < 5:
        risk = 0.7
    elif rating is not None and rating < 3.0:
        risk = 0.6
    else:
        risk = 0.15
    return risk, {"available": True, "detail": result}


def _score_review_burst(business_existence: dict[str, Any] | None) -> tuple[float | None, dict[str, Any]]:
    """Reuses the up-to-5 recent_reviews already fetched for
    business_existence (see business_check.py::_detect_review_burst) —
    doesn't make any call of its own. Deliberately low weight
    (SIGNAL_WEIGHTS["review_burst"] = 0.05, vs 0.15-0.25 for the others):
    Google Places only ever surfaces 5 reviews through this API tier, so
    "burst detected" is a pattern glimpsed in a tiny, non-random sample —
    suggestive, never conclusive. `confidence: "low"` is tagged explicitly
    in the returned detail for the same reason, so nothing downstream
    displays this next to business_existence as if they were equally
    trustworthy."""
    if business_existence is None or business_existence.get("status") != "found":
        return None, {"available": False, "reason": "requires business_existence status=found with review data"}
    burst = business_existence.get("review_burst")
    if burst is None:
        return None, {"available": False, "reason": "no review timestamp data available"}
    risk = 0.6 if burst.get("detected") else 0.1
    return risk, {"available": True, "detail": burst, "confidence": "low"}


def _score_price_anomaly(result: dict[str, Any] | None) -> tuple[float | None, dict[str, Any]]:
    if result is None:
        return None, {"available": False, "reason": _UNAVAILABLE}
    if "price_direction" not in result:
        # Covers both "estimate_fair_price was never called" (missing
        # item/observed_price) and "it was skipped because region was
        # missing" (see check_ghost_tour) — the latter carries its own
        # specific `reason`, which must win over the generic _UNAVAILABLE
        # text so it's clear *why* (not just *that*) this signal is missing.
        return None, {"available": False, "reason": result.get("reason", _UNAVAILABLE)}
    # This composite specifically targets "too cheap to be real" bait pricing
    # (doc section 7, signal 4) — a plain "high" (overpriced) flag is a
    # different phenomenon (module 2.1 ripoff-pricing), not evidence of a
    # ghost tour.
    risk = 0.85 if result["price_direction"] == "low" else 0.15
    return risk, {"available": True, "detail": result}


def _score_scam_pattern(result: dict[str, Any] | None) -> tuple[float | None, dict[str, Any]]:
    if result is None:
        return None, {"available": False, "reason": _UNAVAILABLE}
    # best_score is kNN similarity to known ghost_tour_pressure phrasing.
    # NOT the same thing as flagged_as_new_candidate (which only means "no
    # good match in the library yet" and drives unmatched-report capture,
    # doc section 6.2) — using that field here would misread "unfamiliar
    # wording" as "safe wording".
    risk = result.get("best_score", 0.0)
    return risk, {"available": True, "detail": result}


def _domain_or_page_recently_created(breakdown_by_signal: dict[str, dict[str, Any]]) -> bool:
    """domain_age takes priority over page_transparency whenever domain_age
    itself has data, even if that data says "low risk" — a WHOIS record is
    an authoritative registry lookup for the business's own domain, while a
    Page Transparency read depends on a VLM correctly parsing a screenshot
    of a Facebook page that could have been renamed/transferred. page_age is
    only consulted as a fallback when domain_age has nothing to say at all
    (no url given, or the WHOIS lookup itself failed)."""
    domain = breakdown_by_signal.get("domain_age", {})
    if domain.get("available"):
        return domain.get("detail", {}).get("risk") == "high"
    page = breakdown_by_signal.get("page_transparency", {})
    if page.get("available"):
        return page.get("detail", {}).get("risk") == "high"
    return False


def translate_to_safety_label(ghost_tour_result: dict[str, Any]) -> dict[str, Any]:
    """Presentation-only layer on top of an already-computed
    compute_ghost_tour_score() result — reads breakdown/composite_score,
    never recomputes or overrides them. Produces a plain-language
    "An toàn"/"Không an toàn" label plus every reason that's simultaneously
    true (not just the first/strongest one), per the rule that "An toàn"
    must be an earned, positively-confirmed state, not a default for
    "nothing bad was found because nothing was actually checked."
    """
    breakdown_by_signal = {b["signal"]: b for b in ghost_tour_result.get("breakdown", [])}
    business = breakdown_by_signal.get("business_existence", {})

    if not business.get("available"):
        # business_existence was never configured, errored, or the model
        # never called the tool with a name at all — there is no positive
        # confirmation to build "An toàn" on, and no risk signal was
        # actually checked either. This is its own distinct outcome, never
        # merged with the concrete reasons below: "we didn't verify this"
        # is not the same claim as "we verified this and found it clean/
        # dirty".
        return {"label": "Không an toàn", "reasons": ["Chưa đủ dữ liệu để xác minh"]}

    reasons: list[str] = []

    if _domain_or_page_recently_created(breakdown_by_signal):
        reasons.append("Thời điểm tạo web gần đây")

    business_detail = business.get("detail", {})
    business_status = business_detail.get("status")
    if business_detail.get("data_source") == "gemini_web":
        if business_detail.get("scam_reports") or business_detail.get("legitimacy") == "suspicious":
            reasons.append("Có báo cáo/dấu hiệu lừa đảo khi tìm trên web")
        elif business_status == "not_found":
            reasons.append("Không tìm thấy dấu vết đáng tin cậy trên web")
        elif business_status == "uncertain":
            reasons.append("Chưa xác minh được độ tin cậy trên web")
    elif business_status == "not_found":
        reasons.append("Không khớp với link trên Google Map")

    review_burst = breakdown_by_signal.get("review_burst", {})
    if review_burst.get("available") and review_burst.get("detail", {}).get("detected"):
        reasons.append("Nhiều lượt review 5 sao cùng lúc")

    price = breakdown_by_signal.get("price_anomaly", {})
    if price.get("available"):
        direction = price.get("detail", {}).get("price_direction")
        if direction == "low":
            reasons.append("Giá thấp bất thường so với mặt bằng")
        elif direction == "high":
            reasons.append("Giá cao bất thường so với mặt bằng")

    scam = breakdown_by_signal.get("scam_pattern", {})
    if scam.get("available") and scam.get("detail", {}).get("best_score", 0.0) >= UNMATCHED_THRESHOLD:
        reasons.append("Phát hiện ngôn ngữ thúc giục/mồi câu thường gặp ở lừa đảo")

    if reasons:
        return {"label": "Không an toàn", "reasons": reasons}

    # business_existence is available and none of the above triggered.
    if business_detail.get("data_source") == "gemini_web":
        return {"label": "An toàn", "reasons": ["Có hiện diện web và đánh giá đáng tin cậy"]}
    return {"label": "An toàn", "reasons": ["Khớp với link trên Google Map"]}


def compute_ghost_tour_score(
    domain_age: dict[str, Any] | None = None,
    page_transparency: dict[str, Any] | None = None,
    business_existence: dict[str, Any] | None = None,
    price_anomaly: dict[str, Any] | None = None,
    scam_pattern: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scorers = {
        "domain_age": (_score_domain_age, domain_age),
        "page_transparency": (_score_page_transparency, page_transparency),
        "business_existence": (_score_business_existence, business_existence),
        # review_burst reuses business_existence's own recent_reviews —
        # not a separate lookup, see _score_review_burst's docstring.
        "review_burst": (_score_review_burst, business_existence),
        "price_anomaly": (_score_price_anomaly, price_anomaly),
        "scam_pattern": (_score_scam_pattern, scam_pattern),
    }

    breakdown: list[dict[str, Any]] = []
    weighted_sum = 0.0
    weight_used = 0.0

    for signal_name, (scorer, raw) in scorers.items():
        weight = SIGNAL_WEIGHTS[signal_name]
        risk, detail = scorer(raw)
        entry = {"signal": signal_name, "weight": weight, **detail}
        if risk is not None:
            entry["risk_contribution"] = round(risk, 3)
            weighted_sum += risk * weight
            weight_used += weight
        breakdown.append(entry)

    if weight_used <= 0:
        result = {
            "composite_score": None,
            "risk_level": "insufficient_data",
            "signals_used": 0.0,
            "breakdown": breakdown,
            "flag": None,
        }
        result["safety"] = translate_to_safety_label(result)
        return result

    composite_score = weighted_sum / weight_used

    risk_level = "low"
    for threshold, label in RISK_LEVEL_THRESHOLDS:
        if composite_score >= threshold:
            risk_level = label
            break

    flag = None
    if risk_level in ("high", "medium"):
        n_available = sum(1 for b in breakdown if b.get("available"))
        flag = (
            f"Rủi ro ghost-tour/homestay {risk_level.upper()} "
            f"({composite_score:.2f}/1.0, dựa trên {n_available}/{len(SIGNAL_WEIGHTS)} tín hiệu) — cẩn trọng. "
            "Đây là gợi ý dựa trên bằng chứng gián tiếp, không phải kết luận lừa đảo."
        )

    result = {
        "composite_score": round(composite_score, 3),
        "risk_level": risk_level,
        "signals_used": round(weight_used, 3),
        "breakdown": breakdown,
        "flag": flag,
    }
    result["safety"] = translate_to_safety_label(result)
    return result


async def check_ghost_tour(
    region: str | None = None,
    name: str | None = None,
    url: str | None = None,
    item: str | None = None,
    observed_price: float | None = None,
    suspicious_text: str | None = None,
    _page_transparency_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Tool entrypoint (app/agent/tools.py): runs whichever of the 5
    sub-signals has enough input, in parallel, then composites them.

    Only `url` or `name` is truly required to start (see the tool's
    `anyOf` schema in app/agent/tools.py) — `region` is optional:
    business_existence, page_transparency, and scam_pattern all work fine
    without it. Only the price signal genuinely needs it (estimate_fair_price
    looks up region-specific reference prices); when region is missing and
    a price check was otherwise requested (item + observed_price given),
    that signal reports itself as unavailable with an explicit reason
    instead of silently skipping or guessing a region.

    If `name` is missing but `url` is present, business_existence isn't
    just skipped — extract_business_key_from_url() (app/modules/
    business_check.py) is tried first to derive a stand-in name from the
    URL itself (resolving a Facebook /share/ redirect if needed). Only
    when that also comes back empty (non-Facebook URL, dead redirect,
    request failure) does business_existence fall through to unavailable.

    _page_transparency_result is deliberately not part of the tool's
    LLM-facing JSON schema. A Page Transparency screenshot is read via
    read_image() *before* the tool-calling loop starts (see
    app/agent/orchestrator.py) — a model can't round-trip raw image bytes
    back to itself as a tool-call argument — and the orchestrator injects
    the already-computed result here instead of this function calling
    read_image() again.
    """
    name = _normalize_optional_text(name)
    url = _normalize_optional_text(url)
    item = _normalize_optional_text(item)
    suspicious_text = _normalize_optional_text(suspicious_text)

    tasks: dict[str, Any] = {}
    results: dict[str, Any] = {}

    if url:
        tasks["domain_age"] = _safe(check_domain_age(url))

    # A share-link-only input (url with no name — e.g. a bare Facebook
    # facebook.com/share/<id> link) means the model genuinely has nothing
    # to call it. Rather than skipping business_existence entirely, try the
    # same URL->slug resolver business_check.py already uses to key its
    # mock fixtures (works for real Google Places lookups too, since a
    # resolved Facebook slug is at least *something* to search on — weaker
    # than a real business name, but strictly better than not checking at
    # all). Only genuinely falls through to "unavailable" when there's no
    # name AND no url, or the resolver itself can't make sense of the url
    # (not a Facebook link, no redirect found, request failed).
    resolved_name = name
    if not resolved_name and url:
        resolved_name = await _safe(extract_business_key_from_url(url))

    if resolved_name:
        # url is passed through too: check_business_existence only consults
        # it in MOCK_GOOGLE_PLACES mode (to key its fixture lookup) — the
        # real Google Places call still uses name+region exactly as before.
        tasks["business_existence"] = _safe(check_business_existence(resolved_name, region, url=url))
    if item and observed_price is not None:
        if region:
            tasks["price_anomaly"] = _safe(estimate_fair_price(item, region, observed_price))
        else:
            results["price_anomaly"] = {
                "reason": "cần region để tra cứu mức giá tham khảo (estimate_fair_price yêu cầu region)",
            }
    if suspicious_text:
        tasks["scam_pattern"] = _safe(
            match_scam_pattern(suspicious_text, category="ghost_tour_pressure", region=region)
        )

    if tasks:
        values = await asyncio.gather(*tasks.values())
        results.update(dict(zip(tasks.keys(), values)))

    return compute_ghost_tour_score(
        domain_age=results.get("domain_age"),
        page_transparency=_page_transparency_result,
        business_existence=results.get("business_existence"),
        price_anomaly=results.get("price_anomaly"),
        scam_pattern=results.get("scam_pattern"),
    )
