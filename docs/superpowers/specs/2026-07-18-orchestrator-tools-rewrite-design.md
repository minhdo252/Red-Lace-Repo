# Design: Orchestrator + Tools Rewrite (module 2.x wiring)

Date: 2026-07-18

## Problem

`app/agent/orchestrator.py` and `app/agent/tools.py` are placeholder scaffolds. They
run, but:

1. **The price tool is mis-wired.** `tools.py` exposes `estimate_fair_price` and
   dispatches it to `app/modules/pricing.py::estimate_fair_price` — the placeholder
   Bayesian path that uses the mock `AIClient.embed` and a 0.55 similarity gate. The
   *real* module-2.1 price tool is `app/modules/price_comparison.py::compare_price`:
   real `vn_embedding` query embeddings, a 0.75 similarity gate, a head-phrase prefix
   gate, and a live web-search fallback (`price_web_fallback.py`) with deferred
   write-back to Postgres + Qdrant.

2. **The orchestrator is a tangled placeholder.** It implements the right shape but is
   to be rebuilt cleanly against `orchestration_flow.md`.

This rewrite makes both files call the real modules the project actually uses, faithful
to `orchestration_flow.md`, without regressing the contracts around them.

## Scope

In scope:
- Rewrite `app/agent/tools.py` — keep all 7 tools; fix the one mis-wired price tool to
  call `compare_price`.
- Rewrite `app/agent/orchestrator.py` from scratch as three isolated stages.
- Fix the `orchestration_flow.md` node label `estimate_fair_price` → `compare_price`.
- A standalone asyncio smoke script under `test/`.

Out of scope (explicitly not touched):
- `app/modules/pricing.py` — left as-is. It stays the *internal* bait-price signal
  inside `check_ghost_tour` (the only price path that emits `price_direction`).
- `app/modules/ghost_tour_score.py` — unchanged; keeps calling `estimate_fair_price`
  internally.
- `app/routers/chat.py` — unchanged; the deterministic pre/post pipeline (STT,
  PII redaction, parallel translate/scam-prefilter/threat, compose, persist) already
  matches the flow doc.
- `app/ai/client.py` (`AIClient`) — the restored central AI gateway; not deleted, still
  used by the orchestrator's chat loop, the critic, scam matching, and pricing.
- SOS — stays structurally absent from the tool set.

## The 7 tools and their real modules

| Tool spec name        | Dispatches to                                         | Change |
|-----------------------|-------------------------------------------------------|--------|
| `compare_price`       | `app/modules/price_comparison.py::compare_price`      | **NEW wiring** (was `estimate_fair_price` → `pricing.py`) |
| `read_image`          | `app/modules/image_reader.py::read_image`             | unchanged |
| `match_scam_pattern`  | `app/modules/scam_detection.py::match_scam_pattern`   | unchanged |
| `check_domain_age`    | `app/modules/domain_check.py::check_domain_age`       | unchanged |
| `check_business_existence` | `app/modules/business_check.py::check_business_existence` | unchanged |
| `check_ghost_tour`    | `app/modules/ghost_tour_score.py::check_ghost_tour`   | unchanged |
| `translate_or_get_hotline` | `app/modules/translation.py::translate_or_get_hotline` | unchanged |

### `compare_price` tool spec

```
name: compare_price
description: Compare an observed price for a dish/item against a similarity-weighted
  reference from comparable local listings (Qdrant kNN over real embeddings, 0.75 gate
  + head-phrase gate). Falls back to a live web search when no confident local
  comparable exists. Only ever raises a "higher than reference" flag with a percentage
  — never concludes scam on its own.
parameters:
  item: string (required)
  region: string (required)
  category: string (optional, default "food")
  observed_price: number (optional; VND. Omit for a reference-only lookup.)
```

Dispatch: `lambda args: compare_price(**args)`. `compare_price`'s return dict still
carries a `flag` key, so the orchestrator's risk-flag detection is unaffected.

## Orchestrator design

Three isolated, independently-testable stages, faithful to the `ORCH` subgraph of
`orchestration_flow.md`.

### Stage 1 — `_parse_images_upfront(images) -> (notes, latest_page_transparency)`
Reads every attached image *before* the tool loop (a model cannot request raw image
bytes as a tool call). Each image → `read_image(bytes, mode)`. A decode/parse failure
becomes an error-as-data note, never crashes the turn. The most recent successful
`page_transparency` read is captured and later injected into `check_ghost_tour` as
`_page_transparency_result`.

### Stage 2 — `_run_tool_loop(messages) -> (final_text, tools_invoked, risk_flag_raised)`
Bounded loop, `MAX_TOOL_ITERATIONS = 5`. Each iteration:
1. `ai_client.chat(messages, tools=TOOL_SPECS)`.
2. No tool calls → `response.content` is the final answer; exit.
3. Otherwise: append the assistant tool-call message, dispatch every call via
   `call_tool`, append each tool result message. When dispatching `check_ghost_tour`,
   inject the captured `page_transparency` result. Track whether any `RISK_TOOLS`
   result raised a `flag` / `flagged_as_new_candidate`.

`RISK_TOOLS = {"compare_price", "match_scam_pattern", "check_ghost_tour"}` (price tool
renamed from `estimate_fair_price`).

Loop exhausted with no final text → deterministic Vietnamese "took too long, ask again
more briefly" reply.

### Stage 3 — risk gate + critic (in `handle_turn`)
If any risk flag was raised, run `critic_pass(final_text, {"tools_invoked": ...})` and
attach it under `critic`. Return `{"reply", "tools_invoked", "critic"?}`.

### Preserved contract
`handle_turn(user_text, history=None, images=None) -> dict` with keys `reply`,
`tools_invoked`, and optional `critic` — exactly what `app/routers/chat.py`'s
`_run_orchestrator_for_chat` reads. `SYSTEM_PROMPT` (including the `check_ghost_tour`
`risk_level` vs `safety.label` guidance) preserved verbatim.

## Testing

A standalone asyncio smoke script `test/orchestrator_rewrite_test.py`, run with
`AI_MODE=mock`, exercising:
1. Plain text turn, no tool call → returns a `reply`, no `critic`.
2. Image turn → asserts VLM `read_image` notes are injected into context before the loop.
3. A turn whose tool result raises a risk flag → asserts `critic` is present in the result.

No pytest (repo convention: standalone asyncio smoke scripts under `test/`).

## Risks / notes
- `compare_price` and `estimate_fair_price` are NOT interchangeable inside
  `check_ghost_tour`: the bait-price scorer reads `price_direction`, which only
  `estimate_fair_price` emits. That is why `ghost_tour_score.py` is deliberately left
  untouched.
- `AIClient` is a shared, actively-maintained gateway (parallel collaborators flip its
  direction); this rewrite only *consumes* it and changes nothing in `client.py`.
