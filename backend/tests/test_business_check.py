"""Mock-only tests for app.modules.business_check.check_business_existence.

No real Google Places API call is made — httpx.AsyncClient is monkeypatched
with a fake client that returns canned response bodies, so this runs
without a GOOGLE_PLACES_API_KEY or network access. Covers the 3 states the
Text Search `status` field must be split into (see business_check.py's
module docstring for why the old code collapsed all of these into one):

  1. status=OK            -> "found", with review_count + up to 5 reviews
  2. status=ZERO_RESULTS   -> "not_found" (a real risk signal)
  3. status=REQUEST_DENIED -> "unknown" (an API/infra problem, not a signal)

Run:
    cd backend && PYTHONPATH=. python tests/test_business_check.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules import business_check  # noqa: E402


def _fake_api_key():
    return patch.object(business_check.settings, "google_places_api_key", "fake-key")


class FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        # Google Places answers with HTTP 200 even for REQUEST_DENIED/
        # OVER_QUERY_LIMIT/etc — the real outcome is in the body's `status`
        # field, never the HTTP status code. Nothing under test should ever
        # hit a non-2xx here; that's exactly the bug being fixed.
        if self.status_code >= 400:
            raise RuntimeError(f"unexpected HTTP {self.status_code} in test fixture")

    def json(self) -> dict:
        return self._json


class FakeAsyncClient:
    """Stands in for `async with httpx.AsyncClient(...) as client`. Returns
    the queued responses in call order (Text Search first, then Details)."""

    def __init__(self, responses: list[FakeResponse]):
        self._responses = responses
        self._i = 0

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def get(self, url: str, params: dict | None = None) -> FakeResponse:
        resp = self._responses[self._i]
        self._i += 1
        return resp


def _patched_client(responses: list[FakeResponse]):
    return patch.object(business_check.httpx, "AsyncClient", lambda timeout=None: FakeAsyncClient(responses))


async def test_ok_returns_found_with_reviews() -> None:
    text_search = FakeResponse(
        {"status": "OK", "results": [{"place_id": "place123"}]}
    )
    details = FakeResponse(
        {
            "status": "OK",
            "result": {
                "name": "Vinpearl Resort & Spa Phu Quoc",
                "rating": 4.5,
                "user_ratings_total": 12345,
                "reviews": [{"rating": 5, "text": f"great {i}", "relative_time_description": "a week ago"} for i in range(8)],
            },
        }
    )
    with _fake_api_key():
        with _patched_client([text_search, details]):
            result = await business_check.check_business_existence("Vinpearl Resort and Spa Phu Quoc", "Phu Quoc")

    assert result["status"] == "found", result
    assert result["review_count"] == 12345, result
    assert len(result["recent_reviews"]) == 5, "must cap at 5 most recent reviews"
    assert result["rating"] == 4.5
    print("[PASS] test_ok_returns_found_with_reviews")


async def test_zero_results_returns_not_found() -> None:
    text_search = FakeResponse({"status": "ZERO_RESULTS", "results": []})
    with _fake_api_key():
        with _patched_client([text_search]):
            result = await business_check.check_business_existence("Totally Fake Ghost Tour Co", "Nowhereland")

    assert result["status"] == "not_found", result
    assert "api_status" not in result, "not_found must not carry a spurious api_status field"
    print("[PASS] test_zero_results_returns_not_found")


async def test_request_denied_returns_unknown_not_not_found() -> None:
    text_search = FakeResponse(
        {
            "status": "REQUEST_DENIED",
            "results": [],
            "error_message": "You must enable Billing on the Google Cloud Project ...",
        }
    )
    with _fake_api_key():
        with _patched_client([text_search]):
            result = await business_check.check_business_existence("Vinpearl Resort and Spa Phu Quoc", "Phu Quoc")

    assert result["status"] == "unknown", result
    assert result["api_status"] == "REQUEST_DENIED", result
    assert "Billing" in result["error_message"], result
    print("[PASS] test_request_denied_returns_unknown_not_not_found")


async def test_over_query_limit_also_returns_unknown() -> None:
    text_search = FakeResponse({"status": "OVER_QUERY_LIMIT", "results": []})
    with _fake_api_key():
        with _patched_client([text_search]):
            result = await business_check.check_business_existence("Any Business", "Any Region")

    assert result["status"] == "unknown", result
    assert result["api_status"] == "OVER_QUERY_LIMIT", result
    print("[PASS] test_over_query_limit_also_returns_unknown")


async def test_details_request_denied_also_returns_unknown() -> None:
    # Text Search succeeds and finds a candidate, but the follow-up Details
    # call is the one that gets rejected — must not be misread as "found".
    text_search = FakeResponse({"status": "OK", "results": [{"place_id": "place123"}]})
    details = FakeResponse({"status": "REQUEST_DENIED", "error_message": "denied on details call"})
    with _fake_api_key():
        with _patched_client([text_search, details]):
            result = await business_check.check_business_existence("Some Business", "Some Region")

    assert result["status"] == "unknown", result
    assert result["api_status"] == "REQUEST_DENIED", result
    print("[PASS] test_details_request_denied_also_returns_unknown")


async def main() -> None:
    tests = [
        test_ok_returns_found_with_reviews,
        test_zero_results_returns_not_found,
        test_request_denied_returns_unknown_not_not_found,
        test_over_query_limit_also_returns_unknown,
        test_details_request_denied_also_returns_unknown,
    ]
    failures = 0
    for test in tests:
        try:
            await test()
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
