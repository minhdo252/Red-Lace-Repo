"""Mock-only tests for app.modules.pricing.estimate_fair_price's
`price_direction` classification (doc section 7, signal 4) — covers the
pre-existing "high" (ripoff) branch and the new "low" (bait-price) branch
added alongside it, plus the "normal" no-flag case.

No real Qdrant or Postgres connection is used — get_client()/get_pool() are
monkeypatched to force the "no historical reference matched" fallback path,
which then goes through AIClient's built-in mock prior (deterministic:
p10=20000, p50=40000, p90=80000, confidence="low" VND — see
app/ai/client.py::_get_llm_prior's mock fallback). AI_MODE defaults to
"mock" so ai_client.chat/embed need no patching either — this only exists
to reach a deterministic prior, not to test the AI client itself.

With that prior, prior_from_percentiles + fuse(n=0) collapse to mu_post=mu0,
tau_post=sigma0**2, giving a fair-price estimate centered near 40,000 VND.
Observed prices below are chosen well outside the +/-Z90 band around that
center so the classification isn't sensitive to minor arithmetic drift:
  - 42,000 VND  -> z ~= 0.06  -> "normal"
  - 300,000 VND -> z ~= 3.4   -> "high"
  - 3,000 VND   -> z ~= -4.5  -> "low"

Run:
    cd backend && python tests/test_pricing.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules import pricing  # noqa: E402


class _FakeQdrantClient:
    async def query_points(self, **kwargs):
        # Empty hits -> estimate_fair_price falls back to the LLM-prior-only
        # path instead of trying to read a matched Postgres row.
        return SimpleNamespace(points=[])


class _FakePool:
    """get_pool() is called unconditionally in estimate_fair_price, but
    .acquire() is only ever used on the (never-taken, here) matched-row
    path, so this fake needs no real behavior."""


def _patched_backends():
    return (
        patch.object(pricing, "get_client", lambda: _FakeQdrantClient()),
        patch.object(pricing, "get_pool", lambda: _FakePool()),
    )


async def _run_with_price(observed_price: float) -> dict:
    patch_client, patch_pool = _patched_backends()
    with patch_client, patch_pool:
        return await pricing.estimate_fair_price("homestay 1 night", "Sapa", observed_price)


async def test_normal_price_stays_normal() -> None:
    result = await _run_with_price(42000)
    assert result["price_direction"] == "normal", result
    assert result["flag"] is None, result
    print("[PASS] test_normal_price_stays_normal")


async def test_high_price_flagged_high() -> None:
    # Pre-existing branch (module 2.1 ripoff-pricing) — confirms it's still
    # intact after adding the "low" branch alongside it.
    result = await _run_with_price(300000)
    assert result["price_direction"] == "high", result
    assert result["flag"] and "cao hơn" in result["flag"], result
    print("[PASS] test_high_price_flagged_high")


async def test_low_price_flagged_low() -> None:
    # New branch (module 2.2 signal 4 — bait-price caution).
    result = await _run_with_price(3000)
    assert result["price_direction"] == "low", result
    assert result["flag"] and "mồi câu giá rẻ" in result["flag"], result
    print("[PASS] test_low_price_flagged_low")


async def main() -> None:
    tests = [
        test_normal_price_stays_normal,
        test_high_price_flagged_high,
        test_low_price_flagged_low,
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
