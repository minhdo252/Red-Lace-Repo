"""PII redaction (doc section 6.3): regex pass over OCR'd text before it goes to the LLM."""

import re

CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
VN_ID_RE = re.compile(r"\b\d{9}\b|\b\d{12}\b")


def redact_pii(text: str) -> str:
    text = CREDIT_CARD_RE.sub("[REDACTED_CARD]", text)
    text = VN_ID_RE.sub("[REDACTED_ID]", text)
    return text
