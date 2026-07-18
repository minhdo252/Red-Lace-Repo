"""Mock-only tests for MOCK_GOOGLE_PLACES support in business_check.py:
  - URL -> fixture-key extraction for a normal Facebook page URL (pure
    string parsing, no network)
  - Facebook /share/<id> redirect resolution (httpx monkeypatched, no real
    network call to facebook.com)
  - check_business_existence() end-to-end in mock mode: found / not_found /
    an unmapped key defaulting to not_found — every mock response must
    carry data_source="mock"

Run:
    cd backend && python tests/test_business_check_mock.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules import business_check  # noqa: E402


class _FakeRedirectResponse:
    def __init__(self, location: str | None):
        self.headers = {"location": location} if location else {}


class _FakeRedirectClient:
    def __init__(self, location: str | None):
        self._location = location

    async def __aenter__(self) -> "_FakeRedirectClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def get(self, url: str, headers=None) -> _FakeRedirectResponse:
        return _FakeRedirectResponse(self._location)


def _patched_redirect(location: str | None):
    return patch.object(business_check.httpx, "AsyncClient", lambda timeout=None, follow_redirects=None: _FakeRedirectClient(location))


async def test_extract_key_from_normal_url_no_network() -> None:
    key = await business_check.extract_business_key_from_url(
        "https://www.facebook.com/VinpearlResotandSpaPhuQuoc/directory_category"
    )
    assert key == "VinpearlResotandSpaPhuQuoc", key
    print("[PASS] test_extract_key_from_normal_url_no_network")


async def test_resolve_share_link_to_profile_id() -> None:
    with _patched_redirect("https://www.facebook.com/profile.php?id=61553172142739&mibextid=wwXIfr"):
        key = await business_check.extract_business_key_from_url(
            "https://www.facebook.com/share/1BLRpkFw2C/?mibextid=wwXIfr"
        )
    assert key == "profile.php?id=61553172142739", key
    print("[PASS] test_resolve_share_link_to_profile_id")


async def test_resolve_share_link_to_slug() -> None:
    with _patched_redirect("https://www.facebook.com/TanTrao.Flamingoresorts.vn?mibextid=wwXIfr"):
        key = await business_check.extract_business_key_from_url(
            "https://www.facebook.com/share/1998PNFNX2/?mibextid=wwXIfr"
        )
    assert key == "TanTrao.Flamingoresorts.vn", key
    print("[PASS] test_resolve_share_link_to_slug")


async def test_resolve_share_link_no_redirect_returns_none() -> None:
    with _patched_redirect(None):
        key = await business_check.extract_business_key_from_url("https://www.facebook.com/share/deadend/")
    assert key is None, key
    print("[PASS] test_resolve_share_link_no_redirect_returns_none")


async def test_mock_mode_found_uses_committed_fixture() -> None:
    with patch.object(business_check.settings, "mock_google_places", True):
        with _patched_redirect("https://www.facebook.com/TanTrao.Flamingoresorts.vn?mibextid=wwXIfr"):
            result = await business_check.check_business_existence(
                name="unknown page name", region="Vietnam",
                url="https://www.facebook.com/share/1998PNFNX2/?mibextid=wwXIfr",
            )
    assert result["status"] == "found", result
    assert result["data_source"] == "mock", result
    assert result["review_count"] > 0, result
    print("[PASS] test_mock_mode_found_uses_committed_fixture")


async def test_mock_mode_not_found_uses_committed_fixture() -> None:
    with patch.object(business_check.settings, "mock_google_places", True):
        result = await business_check.check_business_existence(
            name="Vinpearl Resort and Spa Phu Quoc", region="Phu Quoc",
            url="https://www.facebook.com/VinpearlResotandSpaPhuQuoc/directory_category",
        )
    assert result["status"] == "not_found", result
    assert result["data_source"] == "mock", result
    print("[PASS] test_mock_mode_not_found_uses_committed_fixture")


async def test_mock_mode_unmapped_key_defaults_not_found() -> None:
    with patch.object(business_check.settings, "mock_google_places", True):
        result = await business_check.check_business_existence(
            name="Some Business Nobody Mocked", region="Nowhere",
            url="https://www.facebook.com/SomeRandomPageNotInFixtures",
        )
    assert result["status"] == "not_found", result
    assert result["data_source"] == "mock", result
    print("[PASS] test_mock_mode_unmapped_key_defaults_not_found")


async def main() -> None:
    tests = [
        test_extract_key_from_normal_url_no_network,
        test_resolve_share_link_to_profile_id,
        test_resolve_share_link_to_slug,
        test_resolve_share_link_no_redirect_returns_none,
        test_mock_mode_found_uses_committed_fixture,
        test_mock_mode_not_found_uses_committed_fixture,
        test_mock_mode_unmapped_key_defaults_not_found,
    ]
    failures = 0
    for test in tests:
        try:
            await test()
        except AssertionError as exc:
            failures += 1
            print(f"[FAIL] {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[ERROR] {test.__name__}: {type(exc).__name__}: {exc}")

    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
