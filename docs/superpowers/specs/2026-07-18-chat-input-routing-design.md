# Design: Input-type routing for `/chat`

**Date:** 2026-07-18
**Status:** Approved (design); ready for implementation plan
**Area:** `backend/app/routers/chat.py`, `backend/app/schemas/chat.py`, `frontend` Home chatbot + `api.ts` + price-check page

## Problem

The Home chatbot "is not functioning well." Root cause: the backend `/chat` endpoint runs **every** input type — text, voice, and image — through the **same** unified pipeline. It fires the chatbot orchestrator LLM (`handle_turn`, with images parsed upfront) **plus** translation **plus** scam-prefilter **plus** threat-detection in one parallel `asyncio.gather`, and the reply the user sees is whatever the **orchestrator** produced (`app/routers/chat.py:502-515`).

Consequences:

- A **menu photo** does not go "straight to Module 2.1." It gets OCR'd and `compare_price` runs, but the result is then fed to the chatbot LLM, which writes a free-form reply and may call other tools. Behavior is non-deterministic.
- **Voice** is transcribed, then also run through the full chatbot orchestrator instead of being treated as a translation.

## Goal

Route each of the three input types deterministically, so the right module owns the reply:

- **Image → Module 2.1** (price/receipt parsing) only. If Qwen-VL cannot read a menu, return a signal so the chatbot asks the user to retake the photo.
- **Voice → Module 1** (translate) for the reply, **while keeping** the safety layer (scam-prefilter + threat-detection). Drop only the chatbot orchestrator.
- **Text → orchestrator** (unchanged).

## Module map (confirmed from `README.md`)

- **Module 1** — translation / STT (`app/modules/translation.py::translate_text`, STT via `ai_client.transcribe`).
- **Module 2.1** — price/receipt image parsing (`app/ai/qwen_vl.py::ai_detect_menu` → `app/modules/image_reader.py::read_image` → `app/modules/price_comparison.py::compare_price`).
- **Module 2.2** — ghost-tour scam score (not in scope; text-only via `check_ghost_tour`).
- **Module 3** — threat detection / SOS (`app/modules/threat_detection.py::detect_threat`; `/sos` is a separate router).

## Decisions (from brainstorming)

1. **Routing lives in the `/chat` router** (Approach A), not in separate endpoints or inside `handle_turn`. The router already holds every input, the session, the resolved region, STT, PII redaction, and the persistence/dedupe logic; the frontend proxy already sends distinct shapes, so no proxy endpoint changes are needed.
2. **Image = hard short-circuit to Module 2.1.** No orchestrator, translate, scam, or threat. Module 2.1 is itself a price/scam detector, and a photo is not an expected SOS trigger. The `module13_synthetic` test pack explicitly excludes image/vision, so there is no test conflict.
3. **Voice = Module 1 reply + keep safety.** Voice runs `translate_text` (produces the reply) **plus** scam-prefilter **plus** threat-detection, and **drops only the orchestrator**. Evidence: the `test/module13_synthetic` audio suite asserts safety-critical detection on voice — W006 (spoken "call the police, I'm being held") → `threat=CRITICAL`; W002 → `price_scam`; W005 → `ghost_tour_pressure`. All of these are produced by translate/scam/threat, **not** the orchestrator, so dropping only the orchestrator satisfies the user's request AND keeps all 125 audio assertions green (`test/module13_synthetic/RESULTS.md`).
4. **Scope = backend + frontend**, so the retake prompt / clean price result / clean translation are actually visible.
5. **No mock — real input end-to-end.** The real photo/voice/text captured in the frontend always goes to the real backend modules; there are **no** canned/demo answers. The only fallback is a graceful "try again" error state when the backend is unreachable — never a fabricated reply. (See memory `no-mock-real-input`.)

## Routing design

Dispatch in `chat()` after validation, session load, region resolution, and STT. Precedence **image → voice → text**:

```
if request.images:        route = "image"   # Module 2.1 only
elif audio_supplied:      route = "voice"   # Module 1 translate + scam + threat, no orchestrator
else:                     route = "text"    # existing full pipeline (unchanged)
```

The current parallel `asyncio.gather` of orchestrator + translate + scam + threat becomes the **text route only**. `image` and `voice` each call a dedicated helper. Persistence, dedupe (`chunk_sequence_id`), and PII redaction stay shared across all three.

Note on precedence: the frontend never mixes image + audio, but the proxy's audio branch does forward `images`. Defining `image` as highest precedence keeps behavior deterministic if both ever arrive.

### Route table

| Route | Trigger | Modules run | Reply source | Safety envelope |
|---|---|---|---|---|
| **Image** | `request.images` non-empty | Module 2.1 (`read_image` → `compare_price`) | Deterministic price verdict | Module 2.1's own price flag; `needs_retake` when not a menu |
| **Voice** | `audio_base64` present, no images | Module 1 `translate_text` **+** `_scan_scam_prefilter` **+** `detect_threat` | Module 1 `translated_text` | Full (threat→SOS, scam flags) |
| **Text** | text only | Orchestrator + translate + scam + threat (unchanged) | Orchestrator `reply` | Full |

## Image route (Module 2.1)

1. For each image with a menu-OCR mode (`receipt`/`dish`), run `read_image(image_bytes, mode, region)` (Qwen-VL menu OCR). Reuse the extraction logic that already lives in `orchestrator._parse_images_upfront`, but **without** feeding results to the LLM. This logic should be factored into a reusable function so both the (now text-only) orchestrator upfront path and the image route can call it; the orchestrator upfront-image path is no longer reached for image turns (those short-circuit), but keep it intact for any future text+image case.
2. Run `compare_price(item, region, category, observed_price)` per confidently-priced `ready_item`.
3. **Not-a-menu / retake detection** — set `needs_retake=True` when the OCR yields nothing usable:
   - `parse_error` present, **or** zero items extracted (no `ready_items` and no `needs_review`) → `retake_reason = "no_menu_detected"`, message ≈ "I couldn't find a menu in that photo — please retake."
   - items found but **no** confidently-priced `ready_items` → `retake_reason = "unreadable"`, message ≈ "The menu is hard to read — retake a clearer, closer photo."
   - (Rule is tunable; the threshold is "no confidently-priced item to compare.")
4. **Reply** built deterministically from `compare_price` results (no LLM). Per priced item: name · observed price · reference price · overpriced % when `compare_price.flag` is set. Populate `normalized_prices_vnd` and a structured `price_analysis` block for the frontend.
5. Persist the turn (shared persistence). Skip orchestrator / translate / scam / threat entirely.
6. Degradation: an OCR/compare exception surfaces as `needs_retake` with `retake_reason="unreadable"` rather than crashing the turn (same error-as-data philosophy as `call_tool`). This is a real error path, not a mock — the route never fabricates a price.

## Voice route (Module 1 + safety)

1. STT already produced the transcript (`raw_text`) upstream — unchanged.
2. Run in parallel: `translate_text` (Module 1, produces the reply) + `_scan_scam_prefilter` + `detect_threat`.
3. `reply = translated_text`. Populate `translation`, `translation_details`, `detected_language`, `target_language`, `normalized_prices_vnd`, `speaker_split`, `scam_flags`, `scam_prefilter_status`, `threat`.
4. **Do not** run `handle_turn` — this is the only behavioral change vs. today.
5. The Home UI already swaps the user's bubble to the transcript (`updateUserFromTranscript`), so: user bubble = what they said, AI reply = the translation.
6. Degradation reuses the existing `_translate_for_chat` fallback envelope.

## Text route

`input_route = "text"`. A **deterministic price-check intent pre-check** runs first
(`app/modules/price_intent.py::detect_price_intent`, no model call); if it doesn't
fire, the turn goes through the unchanged full pipeline: orchestrator + translate +
scam + threat, `reply = orchestrator reply or translation`. `check_ghost_tour`
(tour-check URLs) continues to work on the orchestrator path.

### Text price-check intent → Module 2.1 (no Qwen-VL, no chatbot LLM)

`detect_price_intent(text)` recognizes a typed price question about a menu item and
routes it straight to Module 2.1, reusing the image route's `compare_price` +
verdict — the item/price come from the text, so the OCR step is skipped entirely.

- **Item + stated price** ("bún đậu 200k", "cơm rang 100k có đắt không"): fire when a
  price is present, a non-empty item remains after stripping the price token + cues,
  and (a price cue is present **or** the item phrase is ≤ 5 words). → verdict vs the
  local/web reference ("looks fair" / "~X% over" / "no local reference").
- **No-price "how much"** ("how much is bún đậu?", "giá bún đậu bao nhiêu?"): fire on a
  price cue + short item, no price. → the fair reference price. If `compare_price`
  finds **no** reference, fall through to the orchestrator (don't answer with a bad
  "no price").
- Price extraction reuses `translation.py::extract_normalized_prices_vnd` (handles
  `k`/`nghìn`/`triệu`/spelled amounts; ignores phones/OTP). The extracted item keeps
  its Vietnamese diacritics for embedding accuracy.
- On fire: `reply` = verdict, `price_analysis` set, `tools_invoked = [compare_price]`,
  `input_route = "text"`; orchestrator + scam + threat skipped (the overpriced flag is
  the "is it expensive?" answer, same as the image route). Detection is deterministic
  and language-tolerant; a general question ("Where is Hoan Kiem Lake?") does not fire.

## Response schema additions (`app/schemas/chat.py::ChatResponse`)

All optional / defaulted so existing consumers and tests keep working:

- `input_route: Literal["text", "voice", "image"] | None = None`
- `needs_retake: bool = False`
- `retake_reason: str | None = None`  (`"no_menu_detected"` | `"unreadable"`)
- `price_analysis: dict[str, Any] | None = None`

`price_analysis` shape (from `compare_price` outputs):

```json
{
  "region": "Hanoi",
  "items": [
    {
      "item": "phở bò",
      "observed_price": 60000,
      "reference_price": 45000,
      "reference_price_range": [40000, 50000],
      "overpriced": true,
      "price_diff_pct": 33.3,
      "flag": "cao hơn giá tham chiếu 33% — ..."
    }
  ],
  "overall_overpriced": true
}
```

## Frontend changes (scope: backend + frontend) — real input, no mock

1. `frontend/src/lib/api.ts` — extend `ChatEnvelope` with `input_route`, `needs_retake`, `retake_reason`, `price_analysis`.
2. `frontend/src/app/(tabs)/home/page.tsx` — the real captured input (photo bytes / recorded audio / typed text) always goes to `/api/chat`:
   - **Remove the canned demo fallbacks** — `send()`'s `fallbackAi` callback and the `taxiThread` / `photoScanReply` / `routeThread` substitutions all go away.
   - When `env.needs_retake`, render a retake prompt message + a **"Retake photo"** action that reopens the camera (`fileRef`); otherwise render the real price reply / `price_analysis`.
   - Voice renders `env.reply` (the real translation); the user bubble already shows the real transcript.
   - When the backend is unreachable (`env.source !== "backend"` / `env.error`), show a graceful **"couldn't reach the assistant — try again"** message bubble. **Never** a fabricated answer.
3. `frontend/src/app/price-check/page.tsx` — consume real `needs_retake` (show a retake state; it already has a `reset`/retake affordance) and render `price_analysis` in the existing `PriceTable`. Drop the `receiptAnalysis` mock result; on unreachable-backend show the same graceful error.
4. **No mock content anywhere.** The `source:"mock"` envelope is repurposed to mean strictly "backend unreachable → show a try-again error," not "render canned data." The mock data modules (`frontend/src/mocks/*` demo threads) are no longer used as chat/price answers.

Frontend note: per `frontend/AGENTS.md`, this is a modified Next.js — read `node_modules/next/dist/docs/` before writing frontend code.

## Error handling

- Each route degrades to a real error signal, not a fabricated reply. Failures append to `degraded_components` and (frontend) surface the graceful "try again" state.
- Image OCR/compare failure → `needs_retake` + `retake_reason="unreadable"` (a real "couldn't read it" outcome, never a made-up price).
- Voice translation failure → existing degraded translation envelope; scam/threat degradation appends to `degraded_components` as today.
- Persistence + dedupe (`chunk_sequence_id`) apply to all three routes.

## Testing (real inputs, no mock)

1. New `test/chat_routing_test.py` — asyncio smoke script (repo convention: standalone, not pytest) that drives the **real** `/chat` flow with **real fixtures** against the running stack (`docker compose run ... backend`), asserting the routing:
   - real menu photo → image route: `input_route=="image"`, `price_analysis` present + `normalized_prices_vnd`, **no** orchestrator `tools_invoked`; a non-menu photo → `needs_retake`.
   - real audio (reuse the `test/module13_whisper/audio/*.wav` fixtures) → voice route: `input_route=="voice"`, real translation reply, `threat` / `scam_flags` populated, orchestrator **not** called.
   - real text → text route: `input_route=="text"`, orchestrator called.
2. Regression: re-run the `test/module13_synthetic` `audio` (and `live`) suites — real STT + translate + scam + threat — and confirm the voice safety assertions still pass on the voice route: **W002** `price_scam`, **W005** `ghost_tour_pressure`, **W006** `threat=CRITICAL`, plus the text `live`/contract cases (C001–C008).
3. Frontend: `cd frontend && npx tsc --noEmit` clean.

Note: real end-to-end runs need the live stack (`docker compose` here, or the deployed Railway backend) and configured model keys — consistent with how the rest of the backend is verified (the app can't run keyless once mock is removed from these routes).

## Price advice (LLM, tiered) — image + price-text routes

Both Module 2.1 routes (menu photo, typed price) run their `compare_price` result
through `app/agent/price_advisor.py::price_advice` to produce the user-facing reply
(GLM-5.2 via `glm_chat`, same pattern as the critic):

- The **tier is computed deterministically** from `price_diff_pct` so the rules are
  exact — over a menu the worst item wins and is named:
  - `> 100%` over → **avoid** (strongly recommend another place)
  - `50–100%` over → **caution** (can be location / reputation / quality — but reconsider)
  - `< 50%` over / fair / cheaper → **reasonable** (small difference from location,
    ingredients, portion, service)
  - no observed price ("how much") → **info** (state the typical price)
  - no reference → **unknown** (couldn't compare)
- GLM writes short, warm **markdown** advice **in the tourist's `native_language`** for
  that tier. `price_advice` returns `None` on GLM failure / no key → the caller falls
  back to the deterministic `_build_price_reply` / `_build_price_text_reply` (graceful,
  not mock). `native_language` is threaded from the session into both routes.
- Frontend renders the markdown: `frontend/src/components/ui/Markdown.tsx` (a
  dependency-free renderer for `**bold**`, `*italic*`, `- ` bullets, line breaks) is
  used in `AssistantReply.tsx` (Home chat) and the price-check reply, so the model's
  `*` markers show as styling, not literal text.

## Out of scope

- No changes to Module 2.2 (`check_ghost_tour`) or the `/sos` router.
- No changes to STT itself or the audio preprocessing.
- No onboarding / design-system changes.
- No new price/translation model behavior — routes only re-wire existing modules.

## Accepted trade-offs

- **Image turns no longer run the general scam/threat layer.** Module 2.1 covers price/scam for menus, and an SOS trigger from a photo is not expected. Confirmed acceptable by the user; no image test asserts threat/scam.
- **Voice keeps full safety** (threat + scam), per the audio-suite evidence — only the orchestrator is dropped from voice.
- **No mock / canned answers on these flows.** Real input is always processed by the real modules; the only fallback is a graceful "backend unreachable → try again" error. Consequence: these chat/price flows require the live stack + model keys to return a real answer (they no longer produce anything keyless). The frontend's `frontend/src/mocks/*` demo threads are retired as chat/price answers.
