"""Canonical language codes supported by the Module 1 translation contract."""

from __future__ import annotations


SUPPORTED_NATIVE_LANGUAGES = frozenset({"vi", "en", "ko", "zh", "ja"})
LANGUAGE_ALIASES = {
    "vi-vn": "vi",
    "en-us": "en",
    "en-gb": "en",
    "ko-kr": "ko",
    "zh-cn": "zh",
    "zh-tw": "zh",
    "ja-jp": "ja",
    "vietnamese": "vi",
    "english": "en",
    "korean": "ko",
    "chinese": "zh",
    "japanese": "ja",
}


def canonical_language_code(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    return LANGUAGE_ALIASES.get(normalized, normalized)


def is_supported_native_language(value: str) -> bool:
    return canonical_language_code(value) in SUPPORTED_NATIVE_LANGUAGES
