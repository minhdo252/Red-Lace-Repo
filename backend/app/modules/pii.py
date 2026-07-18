"""PII redaction (doc section 6.3): regex pass over OCR'd text before it goes to the LLM."""

import re

CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
VN_ID_RE = re.compile(r"\b\d{9}\b|\b\d{12}\b")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
API_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}={0,2}\b")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?84|0)(?:[\s.-]?\d){8,10}(?!\d)")
PASSPORT_RE = re.compile(
    r"\b((?:passport|ho chieu|h\u1ed9 chi\u1ebfu)"
    r"(?:\s*(?:number|no|so|s\u1ed1|is|la|l\u00e0|:))?\s*)"
    r"([A-Z0-9]{6,12})\b",
    re.IGNORECASE,
)
PRICE_AMOUNT_RE = re.compile(
    r"(?ix)"
    r"(?:"
    r"(?:\b(?:gia|gi\u00e1|price|cost|charge|total|t\u1ed5ng)\b[^\d\r\n]{0,20})"
    r"(?:\d{1,3}(?:[.,]\d{3})+|\d{4,19})"
    r"|(?:[$\u20ab]\s*)(?:\d{1,3}(?:[.,]\d{3})+|\d{4,19})"
    r"|(?:\d{1,3}(?:[.,]\d{3})+|\d{4,19})\s*"
    r"(?:vnd|vn\u0111|\u0111(?:\u1ed3ng)?|dong|nghin|ngan|trieu|million|k)\b"
    r")"
)


def _protect_explicit_prices(text: str) -> tuple[str, dict[str, str]]:
    """Temporarily mask explicit prices so numeric PII rules cannot erase them."""

    protected: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        token = f"__PRICE_TOKEN_{len(protected)}__"
        protected[token] = match.group(0)
        return token

    return PRICE_AMOUNT_RE.sub(replace, text), protected


def redact_pii(text: str) -> str:
    text, protected_prices = _protect_explicit_prices(text)
    text = CREDIT_CARD_RE.sub("[REDACTED_CARD]", text)
    text = API_KEY_RE.sub("[REDACTED_API_KEY]", text)
    text = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = PASSPORT_RE.sub(r"\1[REDACTED_PASSPORT]", text)
    text = PHONE_RE.sub("[REDACTED_PHONE]", text)
    text = VN_ID_RE.sub("[REDACTED_ID]", text)
    for token, price in protected_prices.items():
        text = text.replace(token, price)
    return text
