"""
qwen_vl.py
----------
Menu photo -> dish name/price detection using Qwen2.5-VL-7B-Instruct,
served through FPT Cloud's OpenAI-compatible endpoint.

Tuned specifically for HANDWRITTEN VIETNAMESE menus, optimized to
minimize hallucination:
  - Deterministic decoding (temperature=0, top_p tightened) instead of
    the original creative-writing defaults (0.7 / 0.9 / top_k=50).
  - Strict JSON schema output instead of freeform text, so every field
    can be validated instead of trusted blindly.
  - Explicit "do not guess" instruction: the model is required to mark
    unreadable/uncertain items instead of inventing a plausible-looking
    dish or price. This is the single biggest lever against
    hallucination for handwritten OCR — bigger than any sampling
    parameter.
  - Correct image MIME detection (was hardcoded to image/jpeg
    regardless of actual file type).

NOTE: "zero hallucination" is not an achievable target for VL OCR on
handwritten text. What this module optimizes for instead is: never
silently fabricate — always surface uncertainty so a human/downstream
step can review flagged items.

Standalone module — not yet wired into app/ai/client.py's AIClient.vision().
"""

from __future__ import annotations

import base64
import json
import math
import mimetypes
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from openai import OpenAI

BASE_URL = "https://mkp-api.fptcloud.com"
MODEL_NAME = "Qwen2.5-VL-7B-Instruct"

# Regions the price_references table was seeded with. Not a hard DB
# constraint (region is plain TEXT, indexed), but region CANNOT be
# inferred from a menu photo reliably — a handwritten menu almost never
# states its own neighborhood. Treat this as a caller-supplied fact
# about where the photo was taken, not something the model guesses.
KNOWN_REGIONS = {"Hanoi/Old Quarter", "Sapa/Town Center", "Hoi An/Ancient Town"}

DEFAULT_CATEGORY = "food"
# Matches price_references.sigma_data default (assumed observation noise
# in log-space).
DEFAULT_SIGMA_DATA = 0.3

# ----------------------------------------------------------------------
# System prompt: sets hard rules that apply to every request. Keeping
# these rules in the system message (rather than burying them in the
# user prompt) makes the model weight them more consistently.
# ----------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are a data extraction system (OCR + parsing) for handwritten \
Vietnamese restaurant menus. You are NOT a conversational assistant: do \
not interpret, do not guess, do not "clean up" or embellish data.

MANDATORY RULES (violating any of these counts as a serious error):

1. Extract ONLY what is actually visible in the image. NEVER add a dish, \
   a price, or any character that does not appear in the image, even if \
   you believe "this is probably the dish/price" based on general \
   knowledge of typical menus.
2. If handwriting is not clearly legible (smudged, obscured, ambiguous \
   strokes, could plausibly be more than one character): do NOT pick one \
   option arbitrarily. Set "uncertain": true and write your best-effort \
   reading into "name_raw" (or "price_raw" for prices), using "?" in \
   place of characters you cannot confirm (e.g. "Cơm g? xào").
3. Preserve Vietnamese diacritics exactly as written (tone marks: sắc, \
   huyền, hỏi, ngã, nặng; letter marks: â, ă, ê, ô, ơ, ư, đ). Do NOT \
   auto-correct spelling unless you are 100% certain it is a missing-\
   diacritic typo — even then, keep the literal reading in "name_raw".
4. For prices: keep the original format exactly as written in \
   "price_raw" (e.g. "25k", "45.000đ", "120,000"). Only populate \
   "price_vnd" (integer, VND) when the conversion is UNAMBIGUOUS (e.g. \
   "25k" -> 25000, "45.000đ" -> 45000). If the unit or digits are unclear, \
   set "price_vnd": null.
5. Do not infer categories or add descriptions that are not present in \
   the image.
6. Before returning your final answer, re-check every line against the \
   image one more time: if there is any doubt at all, mark it uncertain \
   rather than guessing.
7. Return ONLY valid JSON matching the requested schema. No explanation, \
   no markdown code fences, no text outside the JSON.
"""

MENU_DETECT_PROMPT = """\
Read the entire handwritten menu in this image and extract ALL dishes/\
drinks together with their corresponding prices.

Return JSON matching exactly this schema, with no text other than the \
JSON:

{
  "items": [
    {
      "name_raw": "<dish name, exactly as handwritten in the image, including any spelling as written>",
      "price_raw": "<price, exactly as written in the image, original format preserved>",
      "price_vnd": <integer VND value if the conversion is unambiguous, otherwise null>,
      "uncertain": <true if the name or price is not clearly legible, false if confident>,
      "notes": "<short note if part of the entry could not be read, e.g. 'price is smudged'; empty string if none>"
    }
  ],
  "unreadable_regions": <integer count of lines/areas that are completely illegible and were skipped entirely>
}

Remember: if unsure, set uncertain=true instead of guessing. Do not \
fabricate any dish that is not present in the image.
"""


@dataclass
class MenuItem:
    name_raw: str
    price_raw: str
    price_vnd: int | None
    uncertain: bool
    notes: str = ""


@dataclass
class PriceReferenceRow:
    """One row shaped exactly like price_references, ready for a
    straight INSERT. `id`, `created_at`, `updated_at` are intentionally
    omitted — those are DB-generated (SERIAL / default now()).

    IMPORTANT: mu_post / tau_post / sum_y here describe this single new
    observation in isolation (n=1). If a row for the same
    (item_name, region, category) already exists in the table, do NOT
    blindly INSERT this — run the actual Bayesian fusion update against
    the existing row instead (that logic lives wherever
    seed_price_references.py does its online updates, not in this
    OCR module). This module's job stops at producing a valid,
    single-observation candidate row.
    """

    item_name: str
    region: str
    category: str
    price_vnd: float
    mu_post: float
    tau_post: float
    sigma_data: float
    n: int
    sum_y: float
    source: str = "menu_photo_ocr"  # not a DB column — strip before INSERT if schema is strict
    ocr_notes: str = ""            # not a DB column — strip before INSERT if schema is strict


@dataclass
class MenuExtractionResult:
    ready_rows: list[PriceReferenceRow] = field(default_factory=list)
    needs_review: list[MenuItem] = field(default_factory=list)
    unreadable_regions: int = 0
    region: str = ""
    category: str = ""
    raw_response: str = ""
    parse_error: str | None = None
    extracted_at: str = ""

    def to_json_package(self, strip_non_db_fields: bool = False) -> str:
        """Serialize into the JSON package intended for the DB-write step.

        strip_non_db_fields=True drops `source`/`ocr_notes` from
        ready_rows so the dicts match price_references columns exactly
        (use this right before doing the INSERT). Keep it False when you
        still want provenance for logging/debugging.
        """
        rows = []
        for row in self.ready_rows:
            d = asdict(row)
            if strip_non_db_fields:
                d.pop("source", None)
                d.pop("ocr_notes", None)
            rows.append(d)

        package = {
            "table": "price_references",
            "region": self.region,
            "category": self.category,
            "extracted_at": self.extracted_at,
            "ready_rows": rows,
            "needs_review": [asdict(it) for it in self.needs_review],
            "unreadable_regions": self.unreadable_regions,
            "parse_error": self.parse_error,
        }
        return json.dumps(package, ensure_ascii=False, indent=2)


def _encode_image(path: str) -> tuple[str, str]:
    """Return (base64_data, mime_type). Detects actual MIME instead of
    assuming JPEG, since the model receiving the wrong content-type
    hint for the actual encoding can degrade image understanding."""
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type is None or not mime_type.startswith("image/"):
        mime_type = "image/jpeg"  # fallback only, not a blind default
    with open(path, "rb") as image_file:
        data = base64.b64encode(image_file.read()).decode("utf-8")
    return data, mime_type


def _strip_code_fence(text: str) -> str:
    """Model is instructed not to use markdown fences, but strip them
    defensively in case it does anyway — cheap safety net."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()


def _require_api_key() -> str:
    """Read QWEN_VL_API_KEY from the environment (the backend/seed services
    load it from .env via env_file). Fails clearly if it is unset OR empty,
    rather than letting a blank key surface as an opaque auth error later."""
    key = os.getenv("QWEN_VL_API_KEY")
    if not key:
        raise RuntimeError(
            "QWEN_VL_API_KEY is not set. Add it to .env (loaded by the backend "
            "service via env_file) or export it in the environment."
        )
    return key


def ai_detect_menu(
    image_path: str,
    region: str,
    category: str = DEFAULT_CATEGORY,
    max_tokens: int = 4096,
    strict_region: bool = False,
) -> MenuExtractionResult:
    """Detect dish names and prices from a handwritten Vietnamese menu
    photo at `image_path`, and package confident results into rows
    ready to insert into price_references.

    `region` and `category` are caller-supplied context (e.g. "the
    person photographed this menu in Hanoi/Old Quarter") — they are
    NOT detected from the image. The model has no reliable way to know
    where a menu photo was taken, so guessing region from pixels would
    just be a different flavor of hallucination.

    Set strict_region=True to raise if `region` isn't one of
    KNOWN_REGIONS (Hanoi/Old Quarter, Sapa/Town Center,
    Hoi An/Ancient Town) — off by default since the table isn't
    enum-constrained and new regions may legitimately get added.

    Reads the API key from the QWEN_VL_API_KEY environment variable.
    Streams the model's response, parses it, then splits items into:
      - ready_rows: uncertain=False AND price_vnd present -> safe to
        insert as a new price_references observation.
      - needs_review: everything else -> must be confirmed by a human
        before ever reaching the pricing table, so a misread price
        can't quietly poison the Bayesian prior.
    """
    if not region:
        raise ValueError(
            "region is required — it cannot be inferred from the menu "
            "photo. Pass the region the photo was taken in."
        )
    if strict_region and region not in KNOWN_REGIONS:
        raise ValueError(
            f"region={region!r} is not in KNOWN_REGIONS={KNOWN_REGIONS}. "
            "Pass strict_region=False if this is an intentional new region."
        )

    api_key = _require_api_key()
    client = OpenAI(api_key=api_key, base_url=BASE_URL)

    base64_image, mime_type = _encode_image(image_path)

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": MENU_DETECT_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}"
                        },
                    },
                ],
            },
        ],
        # --- Deterministic decoding: this is the core fix. ---
        # temperature=0 removes the model's freedom to pick a plausible
        # but unverified token when handwriting is ambiguous. For
        # extraction/OCR tasks there is no upside to sampling diversity;
        # any variance here is a source of hallucination, not creativity.
        temperature=0,
        # top_p left tight as a safety net in case the backend doesn't
        # fully honor temperature=0 as pure greedy decoding.
        top_p=0.1,
        max_tokens=max_tokens,
        # No penalties: dish lists legitimately repeat tokens (e.g. many
        # dishes containing "gà", "cơm", "k" for giá). Penalizing
        # repetition here would push the model AWAY from correctly
        # repeating what's actually on the menu — i.e. it would
        # increase hallucination, not reduce it.
        presence_penalty=0,
        frequency_penalty=0,
        stop=None,
        stream=True,
    )

    result_text = ""
    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            piece = chunk.choices[0].delta.content
            print(piece, end="", flush=True)
            result_text += piece

    return _build_result(result_text, region, category)


def _build_result(raw_text: str, region: str, category: str) -> MenuExtractionResult:
    """Parse the model's JSON and split items into ready_rows vs needs_review.

    ready_rows: confident (uncertain=False) AND a usable price_vnd — packaged
    as single-observation (n=1) PriceReferenceRow candidates using the module
    default sigma_data. needs_review: everything else, so a misread name/price
    can't quietly reach the pricing table without a human confirming it.
    """
    extracted_at = datetime.now(timezone.utc).isoformat()
    cleaned = _strip_code_fence(raw_text)
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError) as exc:
        # Model failed to follow the JSON schema. Surface this loudly instead
        # of silently returning an empty/guessed result — a parse failure
        # should never be presented as "no items found".
        return MenuExtractionResult(
            region=region,
            category=category,
            raw_response=raw_text,
            parse_error=str(exc),
            extracted_at=extracted_at,
        )

    items = [
        MenuItem(
            name_raw=it.get("name_raw", ""),
            price_raw=it.get("price_raw", ""),
            price_vnd=it.get("price_vnd"),
            uncertain=bool(it.get("uncertain", False)),
            notes=it.get("notes", ""),
        )
        for it in data.get("items", [])
    ]

    ready_rows: list[PriceReferenceRow] = []
    needs_review: list[MenuItem] = []
    for it in items:
        if it.uncertain or not it.price_vnd or it.price_vnd <= 0:
            needs_review.append(it)
            continue
        sum_y = math.log(it.price_vnd)
        ready_rows.append(
            PriceReferenceRow(
                item_name=it.name_raw,
                region=region,
                category=category,
                price_vnd=float(it.price_vnd),
                mu_post=sum_y,
                tau_post=DEFAULT_SIGMA_DATA ** 2,  # n=1: variance of a single obs
                sigma_data=DEFAULT_SIGMA_DATA,
                n=1,
                sum_y=sum_y,
                ocr_notes=it.notes,
            )
        )

    return MenuExtractionResult(
        ready_rows=ready_rows,
        needs_review=needs_review,
        unreadable_regions=data.get("unreadable_regions", 0),
        region=region,
        category=category,
        raw_response=raw_text,
        parse_error=None,
        extracted_at=extracted_at,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        sys.exit('usage: python -m app.ai.qwen_vl "<image_path>" "<region>"')
    image_path, region = sys.argv[1], sys.argv[2]
    result = ai_detect_menu(image_path, region=region)
    print("\n\n--- Parsed result ---")
    if result.parse_error:
        print(f"PARSE ERROR: {result.parse_error}")
        print("Raw response:", result.raw_response)
    else:
        print(f"Ready rows ({len(result.ready_rows)}):")
        for row in result.ready_rows:
            print(f"  {row.item_name} - {row.price_vnd} VND")
        print(f"Needs review ({len(result.needs_review)}):")
        for item in result.needs_review:
            flag = " [UNCERTAIN]" if item.uncertain else ""
            print(f"  {item.name_raw} - {item.price_raw} ({item.price_vnd}){flag}")
        print(f"Unreadable regions skipped: {result.unreadable_regions}")