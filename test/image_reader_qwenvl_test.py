"""Tests for image_reader.read_image now routing receipt/dish through the real
Qwen VL menu OCR (ai_detect_menu) and returning compare_price-ready items.

Fakes ai_detect_menu (sync) and ai_client.vision (async) so no live key,
network, or FPT endpoint is touched.

Run:
  docker compose run --rm --no-deps -e PYTHONPATH=/app -v "$(pwd)/test:/app/test" \
      --entrypoint python backend test/image_reader_qwenvl_test.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys

import app.modules.image_reader as image_reader
from app.ai.qwen_vl import MenuExtractionResult, MenuItem, PriceReferenceRow

_MISSING = object()
JPEG_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-body"


@contextlib.contextmanager
def patched(module, **attrs):
    originals = {name: getattr(module, name, _MISSING) for name in attrs}
    for name, value in attrs.items():
        setattr(module, name, value)
    try:
        yield
    finally:
        for name, original in originals.items():
            if original is _MISSING:
                delattr(module, name)
            else:
                setattr(module, name, original)


@contextlib.contextmanager
def env(**kwargs):
    originals = {k: os.environ.get(k, _MISSING) for k in kwargs}
    for k, v in kwargs.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, original in originals.items():
            if original is _MISSING:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original


def aio(coro):
    return asyncio.run(coro)


def _sample_extraction(region, category):
    return MenuExtractionResult(
        ready_rows=[
            PriceReferenceRow(
                item_name="phở bò",
                region=region,
                category=category,
                price_vnd=60000.0,
                mu_post=0.0,
                tau_post=0.09,
                sigma_data=0.3,
                n=1,
                sum_y=0.0,
            )
        ],
        needs_review=[
            MenuItem(name_raw="Cơm g? xào", price_raw="?", price_vnd=None, uncertain=True, notes="smudged"),
        ],
        unreadable_regions=1,
        region=region,
        category=category,
        parse_error=None,
    )


class _StubVision:
    """Stand-in for ai_client — records vision() calls, returns a canned dict."""

    def __init__(self, result):
        self._result = result
        self.calls = []

    async def vision(self, image_bytes, mode):
        self.calls.append(mode)
        return dict(self._result)


# ===========================================================================
# receipt/dish -> qwen_vl OCR
# ===========================================================================

def test_receipt_routes_to_qwen_vl_and_shapes_ready_items():
    captured = {}

    def fake_detect(image_path, region, category="food"):
        captured["path"] = image_path
        captured["exists_during"] = os.path.exists(image_path)
        with open(image_path, "rb") as fh:
            captured["bytes"] = fh.read()
        captured["region"] = region
        captured["category"] = category
        return _sample_extraction(region, category)

    class _NoVision:
        async def vision(self, image_bytes, mode):
            raise AssertionError("ai_client.vision must NOT be called for a menu OCR path")

    with env(QWEN_VL_API_KEY="test-key"), patched(image_reader, ai_detect_menu=fake_detect, ai_client=_NoVision()):
        result = aio(image_reader.read_image(JPEG_BYTES, "receipt", region="Hanoi", category="food"))

    # qwen_vl actually got the bytes, via a real temp file, with the right context.
    assert captured["bytes"] == JPEG_BYTES
    assert captured["exists_during"] is True
    assert captured["region"] == "Hanoi"
    assert captured["category"] == "food"

    assert result["source"] == "qwen_vl"
    assert result["mode"] == "receipt"
    # ready_items are already in compare_price(item, observed_price) shape.
    assert result["ready_items"] == [{"item_name": "phở bò", "price_vnd": 60000.0}]
    assert result["needs_review"][0]["uncertain"] is True
    assert result["unreadable_regions"] == 1


def test_ready_items_fit_compare_price_signature():
    def fake_detect(image_path, region, category="food"):
        return _sample_extraction(region, category)

    with env(QWEN_VL_API_KEY="test-key"), patched(image_reader, ai_detect_menu=fake_detect):
        result = aio(image_reader.read_image(JPEG_BYTES, "dish", region="Sapa"))

    for item in result["ready_items"]:
        assert isinstance(item["item_name"], str) and item["item_name"]
        assert isinstance(item["price_vnd"], (int, float)) and item["price_vnd"] > 0


def test_temp_file_cleaned_up_after_ocr():
    seen_path = {}

    def fake_detect(image_path, region, category="food"):
        seen_path["path"] = image_path
        return _sample_extraction(region, category)

    with env(QWEN_VL_API_KEY="test-key"), patched(image_reader, ai_detect_menu=fake_detect):
        aio(image_reader.read_image(JPEG_BYTES, "receipt", region="Hanoi"))

    assert not os.path.exists(seen_path["path"]), "temp OCR file must be removed after read_image returns"


def test_png_bytes_get_png_suffix():
    seen = {}
    png_bytes = b"\x89PNG\r\n\x1a\nrest"

    def fake_detect(image_path, region, category="food"):
        seen["path"] = image_path
        return _sample_extraction(region, category)

    with env(QWEN_VL_API_KEY="test-key"), patched(image_reader, ai_detect_menu=fake_detect):
        aio(image_reader.read_image(png_bytes, "receipt", region="Hanoi"))
    assert seen["path"].endswith(".png")


# ===========================================================================
# Fallbacks: no region / no key -> generic ai_client.vision stub
# ===========================================================================

def test_no_region_falls_back_to_vision_stub():
    def must_not_run(*a, **k):
        raise AssertionError("qwen_vl must not run without a region")

    stub = _StubVision({"mode": "receipt", "note": "stub"})
    with env(QWEN_VL_API_KEY="test-key"), patched(image_reader, ai_detect_menu=must_not_run, ai_client=stub):
        result = aio(image_reader.read_image(JPEG_BYTES, "receipt"))  # region omitted
    assert result == {"mode": "receipt", "note": "stub"}
    assert stub.calls == ["receipt"]


def test_no_api_key_falls_back_to_vision_stub():
    def must_not_run(*a, **k):
        raise AssertionError("qwen_vl must not run without QWEN_VL_API_KEY")

    stub = _StubVision({"mode": "dish", "note": "stub"})
    with env(QWEN_VL_API_KEY=None), patched(image_reader, ai_detect_menu=must_not_run, ai_client=stub):
        result = aio(image_reader.read_image(JPEG_BYTES, "dish", region="Hanoi"))
    assert result["note"] == "stub"
    assert stub.calls == ["dish"]


# ===========================================================================
# page_transparency / chat_screenshot unchanged
# ===========================================================================

def test_page_transparency_still_uses_vision_and_postprocesses():
    def must_not_run(*a, **k):
        raise AssertionError("qwen_vl must not run for page_transparency")

    stub = _StubVision({"creation_date_text": "January 2025", "name_history": ["Old Name"]})
    with env(QWEN_VL_API_KEY="test-key"), patched(image_reader, ai_detect_menu=must_not_run, ai_client=stub):
        result = aio(image_reader.read_image(JPEG_BYTES, "page_transparency", region="Hanoi"))
    assert stub.calls == ["page_transparency"]
    # _postprocess_page_transparency added the derived fields.
    assert "page_age_days" in result and result["page_age_days"] is not None
    assert result["risk"] in {"high", "low"}
    assert result["recent_name_change"] is True


def test_chat_screenshot_uses_vision_stub():
    stub = _StubVision({"mode": "chat_screenshot", "risk_notes": "pressure to pay"})
    with env(QWEN_VL_API_KEY="test-key"), patched(image_reader, ai_client=stub):
        result = aio(image_reader.read_image(JPEG_BYTES, "chat_screenshot", region="Hanoi"))
    assert stub.calls == ["chat_screenshot"]
    assert result["risk_notes"] == "pressure to pay"


def test_invalid_mode_raises():
    try:
        aio(image_reader.read_image(JPEG_BYTES, "bogus"))
    except ValueError as exc:
        assert "invalid mode" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid mode")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    tests = [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]
    failures = []
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failures.append((name, f"AssertionError: {exc}"))
            print(f"FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append((name, f"{type(exc).__name__}: {exc}"))
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok    {name}")

    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")
    if failures:
        print("FAILURES:")
        for name, msg in failures:
            print(f"  - {name}: {msg}")
        return 1
    print("OK image_reader_qwenvl_test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
