# Orchestrator + Tools Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `app/agent/tools.py` and `app/agent/orchestrator.py` so the agent's price tool calls the real module-2.1 function (`compare_price`) and the orchestrator loop is a clean, three-stage implementation faithful to `orchestration_flow.md`.

**Architecture:** Keep the 7-tool surface. Fix the one mis-wired tool: swap the agent-facing price tool from the placeholder `pricing.py::estimate_fair_price` to `price_comparison.py::compare_price` (real embeddings, 0.75 gate, head-phrase gate, web fallback). Rewrite the orchestrator as three isolated stages — upfront VLM parse, bounded tool loop, risk gate + critic — preserving the `handle_turn(...) -> {reply, tools_invoked, critic}` contract that `chat.py` depends on.

**Tech Stack:** Python 3, FastAPI, asyncio, Qdrant, Postgres, the mock/live `AIClient` gateway. Tests are standalone asyncio smoke scripts (no pytest in this repo).

## Global Constraints

- `AI_MODE=mock` is the default and must keep working with no API key.
- Tests are standalone asyncio scripts under `test/`, run inside Docker with `--no-deps`. There is no pytest.
- `app/modules/pricing.py` MUST NOT be edited — it stays the internal bait-price signal inside `check_ghost_tour`.
- `app/modules/ghost_tour_score.py`, `app/routers/chat.py`, and `app/ai/client.py` MUST NOT be edited.
- SOS (`trigger_sos`) MUST remain absent from `TOOL_SPECS` / `TOOL_DISPATCH`.
- `handle_turn` MUST keep the signature `handle_turn(user_text, history=None, images=None) -> dict` returning keys `reply`, `tools_invoked`, and optional `critic`.
- Test run command (stack already up, or images built):
  ```bash
  docker compose run --rm --no-deps -e PYTHONPATH=/app -v "$(pwd)/test:/app/test" \
      --entrypoint python backend test/<script>.py
  ```

---

## File Structure

- Modify: `backend/app/agent/tools.py` — swap the price tool spec + dispatch to `compare_price`.
- Rewrite: `backend/app/agent/orchestrator.py` — three-stage loop.
- Create: `test/tools_wiring_test.py` — asserts the price tool routes to `compare_price`.
- Create: `test/orchestrator_rewrite_test.py` — asserts loop behavior (no-tool, image parse, risk→critic).
- Modify: `orchestration_flow.md` — fix the node label `estimate_fair_price` → `compare_price`.

---

## Task 1: Rewire the price tool to `compare_price`

**Files:**
- Modify: `backend/app/agent/tools.py`
- Test: `test/tools_wiring_test.py`

**Interfaces:**
- Consumes: `app/modules/price_comparison.py::compare_price(item: str, region: str, category: str = "food", observed_price: float | None = None) -> dict`
- Produces: `TOOL_SPECS` list containing a spec named `"compare_price"` (no spec named `"estimate_fair_price"`); `TOOL_DISPATCH["compare_price"]` dispatching to `compare_price`; `call_tool(name, arguments)` unchanged.

- [ ] **Step 1: Write the failing test**

Create `test/tools_wiring_test.py`:

```python
"""Smoke test: the agent's price tool is wired to the real module-2.1
compare_price, not the placeholder estimate_fair_price."""

import asyncio

import app.agent.tools as tools


def test_price_tool_spec_is_compare_price():
    names = {spec["name"] for spec in tools.TOOL_SPECS}
    assert "compare_price" in names, names
    assert "estimate_fair_price" not in names, names
    # Still exactly the 7-tool surface.
    assert names == {
        "compare_price",
        "read_image",
        "match_scam_pattern",
        "check_domain_age",
        "check_business_existence",
        "check_ghost_tour",
        "translate_or_get_hotline",
    }, names


def test_dispatch_routes_to_compare_price(monkeypatch=None):
    seen = {}

    async def fake_compare_price(**kwargs):
        seen.update(kwargs)
        return {"flag": None, "reference_price": 40000}

    # Patch the symbol tools.py dispatches through.
    tools.compare_price = fake_compare_price

    result = asyncio.run(
        tools.call_tool("compare_price", {"item": "pho bo", "region": "Hanoi", "observed_price": 90000})
    )
    assert seen == {"item": "pho bo", "region": "Hanoi", "observed_price": 90000}, seen
    assert result == {"flag": None, "reference_price": 40000}, result


if __name__ == "__main__":
    test_price_tool_spec_is_compare_price()
    test_dispatch_routes_to_compare_price()
    print("OK tools_wiring_test")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
docker compose run --rm --no-deps -e PYTHONPATH=/app -v "$(pwd)/test:/app/test" \
    --entrypoint python backend test/tools_wiring_test.py
```
Expected: FAIL — `AssertionError` on `"compare_price" in names` (spec is still `estimate_fair_price`), or `AttributeError: module 'app.agent.tools' has no attribute 'compare_price'`.

- [ ] **Step 3: Edit `tools.py` — import**

Replace the pricing import:
```python
from app.modules.pricing import estimate_fair_price
```
with:
```python
from app.modules.price_comparison import compare_price
```

- [ ] **Step 4: Edit `tools.py` — the price tool spec**

Replace the first entry of `TOOL_SPECS` (the `estimate_fair_price` block) with:
```python
    {
        "name": "compare_price",
        "description": (
            "Compare an observed price for a dish/item against a similarity-weighted "
            "reference from comparable local listings (Qdrant kNN over real embeddings, "
            "0.75 similarity gate + head-phrase gate). Falls back to a live web search "
            "when no confident local comparable exists. Only ever raises a 'higher than "
            "reference' flag with a percentage — never concludes scam on its own."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item": {"type": "string"},
                "region": {"type": "string"},
                "category": {
                    "type": "string",
                    "description": "Item category filter, e.g. 'food'. Defaults to 'food'.",
                },
                "observed_price": {
                    "type": "number",
                    "description": "Observed price in VND. Omit for a reference-only lookup.",
                },
            },
            "required": ["item", "region"],
        },
    },
```

- [ ] **Step 5: Edit `tools.py` — the dispatch entry**

In `TOOL_DISPATCH`, replace:
```python
    "estimate_fair_price": lambda args: estimate_fair_price(**args),
```
with:
```python
    "compare_price": lambda args: compare_price(**args),
```

- [ ] **Step 6: Run test to verify it passes**

Run:
```bash
docker compose run --rm --no-deps -e PYTHONPATH=/app -v "$(pwd)/test:/app/test" \
    --entrypoint python backend test/tools_wiring_test.py
```
Expected: `OK tools_wiring_test`

- [ ] **Step 7: Commit**

```bash
git add backend/app/agent/tools.py test/tools_wiring_test.py
git commit -m "feat(agent): wire price tool to real compare_price (module 2.1)"
```

---

## Task 2: Rewrite the orchestrator as three stages

**Files:**
- Rewrite: `backend/app/agent/orchestrator.py`
- Test: `test/orchestrator_rewrite_test.py`

**Interfaces:**
- Consumes: `app.agent.tools.TOOL_SPECS`, `app.agent.tools.call_tool`, `app.ai.client.ai_client.chat(messages, tools=...)` returning an object with `.content: str | None` and `.tool_calls` (each call has `.id`, `.name`, `.arguments: dict`), `app.agent.critic.critic_pass(conclusion, evidence) -> dict`, `app.modules.image_reader.read_image(bytes, mode) -> dict`.
- Produces: `handle_turn(user_text: str, history: list | None = None, images: list | None = None) -> dict` with keys `reply`, `tools_invoked`, optional `critic`; module constants `MAX_TOOL_ITERATIONS = 5`, `RISK_TOOLS = {"compare_price", "match_scam_pattern", "check_ghost_tour"}`; helpers `_parse_images_upfront(images) -> (notes, latest_page_transparency)` and `_run_tool_loop(messages, page_transparency_result) -> (final_text, tools_invoked, risk_flag_raised)`.

- [ ] **Step 1: Write the failing test**

Create `test/orchestrator_rewrite_test.py`:

```python
"""Smoke test for the three-stage orchestrator. Drives handle_turn with a
fake ai_client / call_tool / read_image / critic_pass so it exercises the
loop logic without the Qdrant/Postgres stack or a live model."""

import asyncio

import app.agent.orchestrator as orch


class _FakeCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.name = name
        self.arguments = arguments


class _FakeResponse:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _ScriptedClient:
    """Returns queued responses in order, one per chat() call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def chat(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])
        return self._responses.pop(0)


def test_plain_text_turn_no_tools_no_critic():
    orch.ai_client = _ScriptedClient([_FakeResponse(content="Xin chào!")])
    result = asyncio.run(orch.handle_turn("hello"))
    assert result["reply"] == "Xin chào!", result
    assert result["tools_invoked"] == [], result
    assert "critic" not in result, result


def test_image_notes_injected_before_loop():
    captured = {}

    async def fake_read_image(image_bytes, mode):
        return {"mode": mode, "text": "MENU: pho 40k"}

    client = _ScriptedClient([_FakeResponse(content="done")])
    orch.read_image = fake_read_image
    orch.ai_client = client

    import base64
    img = {"image_base64": base64.b64encode(b"x").decode(), "mode": "dish"}
    asyncio.run(orch.handle_turn("what is this", images=[img]))

    # The first chat() call must already contain the read_image note as a user message.
    first_messages = client.calls[0]
    assert any("read_image mode=dish" in str(m.get("content")) for m in first_messages), first_messages


def test_risk_flag_triggers_critic():
    async def fake_call_tool(name, arguments):
        return {"flag": "cao hơn giá tham chiếu 80%"}

    async def fake_critic_pass(conclusion, evidence):
        return {"notes": "reviewed"}

    responses = [
        _FakeResponse(tool_calls=[_FakeCall("c1", "compare_price", {"item": "pho", "region": "Hanoi", "observed_price": 90000})]),
        _FakeResponse(content="Giá này cao hơn bình thường."),
    ]
    orch.ai_client = _ScriptedClient(responses)
    orch.call_tool = fake_call_tool
    orch.critic_pass = fake_critic_pass

    result = asyncio.run(orch.handle_turn("is 90k for pho fair?"))
    assert result["critic"] == {"notes": "reviewed"}, result
    assert result["tools_invoked"][0]["tool"] == "compare_price", result


if __name__ == "__main__":
    test_plain_text_turn_no_tools_no_critic()
    test_image_notes_injected_before_loop()
    test_risk_flag_triggers_critic()
    print("OK orchestrator_rewrite_test")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
docker compose run --rm --no-deps -e PYTHONPATH=/app -v "$(pwd)/test:/app/test" \
    --entrypoint python backend test/orchestrator_rewrite_test.py
```
Expected: FAIL — with the current orchestrator, `RISK_TOOLS` still contains `estimate_fair_price` (not `compare_price`), so `test_risk_flag_triggers_critic` fails its `result["critic"]` assertion (no critic attached for a `compare_price` flag).

- [ ] **Step 3: Rewrite `orchestrator.py`**

Replace the entire file with:

```python
"""Single orchestrator + tool-calling agent (orchestration_flow.md, ORCH subgraph).

Deliberately not a multi-agent swarm: one bounded model loop that calls tools and
reasons over their results, with a critic pass gating any risk conclusion, and a hard
safety rule that keeps emergency dialing out of the agent's reach entirely (trigger_sos
is not in its tool set — see app/agent/tools.py).

The loop is wrapped by a deterministic pre/post pipeline in app/routers/chat.py (STT,
PII redaction, parallel translate / scam-prefilter / threat, compose, persist) — none of
that is the orchestrator's concern.

Three stages:
  1. _parse_images_upfront — VLM-read every attached image BEFORE the loop. A model can't
     round-trip raw image bytes back to itself as a tool-call argument, so image *input*
     is read up front and injected into the conversation as context.
  2. _run_tool_loop       — the bounded LLM tool-calling loop.
  3. handle_turn          — runs the two stages, then the risk gate + critic pass.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from app.agent.critic import critic_pass
from app.agent.tools import TOOL_SPECS, call_tool
from app.ai.client import ai_client
from app.modules.image_reader import read_image

MAX_TOOL_ITERATIONS = 5

# Tool outcomes that count as a "risk conclusion" and must go through the critic pass.
RISK_TOOLS = {"compare_price", "match_scam_pattern", "check_ghost_tour"}

TOOL_LOOP_TIMEOUT_REPLY = (
    "Xin lỗi, mình xử lý hơi lâu — bạn thử hỏi lại ngắn gọn hơn nhé."
)

SYSTEM_PROMPT = """\
You are the AITravelMate orchestrator: a travel companion and interpreter for tourists \
in Hanoi, Sapa, and Hoi An. You help translate, flag price anomalies, and flag scam \
patterns using your tools. You never invent prices, hotlines, or embassy contacts — \
always use the tools for that.

Hard safety rule: you have no way to place emergency calls or contact authorities \
yourself, and must never claim otherwise. If risk looks high, say so and suggest the \
user tap the SOS button in the app — the call itself always requires their tap.

check_ghost_tour returns two independent layers — do not treat a mismatch between \
them as an error or something to point out as confusing: risk_level (low/medium/high/ \
insufficient_data) is an internal multi-level score; safety.label (An toàn/Không an \
toàn) is a separate binary display label driven by its own fixed rule (business found \
with nothing else triggered = An toàn; anything else = Không an toàn with its own \
reasons). They are allowed to disagree — e.g. risk_level=medium alongside \
safety.label=Không an toàn is normal, not a bug. When telling the user whether \
something looks safe, defer to safety.label and its reasons, not to risk_level.
"""


def _is_risk_flag(tool_name: str, result: dict[str, Any]) -> bool:
    if tool_name not in RISK_TOOLS:
        return False
    return bool(result.get("flag")) or bool(result.get("flagged_as_new_candidate"))


async def _parse_images_upfront(
    images: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any] | None]:
    """Stage 1. Read every attached image up front. Returns (context notes for the
    model, the most recent successful page_transparency read — check_ghost_tour only
    takes one). A bad image is surfaced as an error note, same philosophy as
    call_tool()'s error-as-data handling, rather than crashing the turn."""
    notes: list[str] = []
    page_transparency_result: dict[str, Any] | None = None

    for img in images:
        mode = img.get("mode")
        try:
            image_bytes = base64.b64decode(img["image_base64"])
            result = await read_image(image_bytes, mode)
        except Exception as exc:  # noqa: BLE001 - surface as data, don't crash the turn
            result = {"error": str(exc)}

        if mode == "page_transparency" and "error" not in result:
            page_transparency_result = result
        notes.append(f"[read_image mode={mode}] {result}")

    return notes, page_transparency_result


async def _run_tool_loop(
    messages: list[dict[str, Any]],
    page_transparency_result: dict[str, Any] | None,
) -> tuple[str, list[dict[str, Any]], bool]:
    """Stage 2. Bounded tool-calling loop. Returns (final_text, tools_invoked,
    risk_flag_raised)."""
    tools_invoked: list[dict[str, Any]] = []
    risk_flag_raised = False
    final_text = ""

    for _ in range(MAX_TOOL_ITERATIONS):
        response = await ai_client.chat(messages, tools=TOOL_SPECS)

        if not response.tool_calls:
            final_text = response.content or ""
            break

        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": json.dumps(c.arguments, ensure_ascii=False),
                        },
                    }
                    for c in response.tool_calls
                ],
            }
        )
        for call in response.tool_calls:
            dispatch_args = dict(call.arguments)
            if call.name == "check_ghost_tour" and page_transparency_result is not None:
                dispatch_args["_page_transparency_result"] = page_transparency_result

            result = await call_tool(call.name, dispatch_args)
            tools_invoked.append({"tool": call.name, "arguments": call.arguments, "result": result})
            if _is_risk_flag(call.name, result):
                risk_flag_raised = True
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )
    else:
        final_text = TOOL_LOOP_TIMEOUT_REPLY

    return final_text, tools_invoked, risk_flag_raised


async def handle_turn(
    user_text: str,
    history: list[dict[str, Any]] | None = None,
    images: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one orchestrator turn. `history` is the already-compressed transcript
    (summary + last N turns) — compression itself is a session/frontend concern, not the
    orchestrator's. `images` are VLM-read before this turn's model call."""

    image_notes, page_transparency_result = await _parse_images_upfront(images or [])

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history or [])
    if image_notes:
        messages.append({"role": "user", "content": "\n".join(image_notes)})
    messages.append({"role": "user", "content": user_text})

    final_text, tools_invoked, risk_flag_raised = await _run_tool_loop(
        messages, page_transparency_result
    )

    result: dict[str, Any] = {"reply": final_text, "tools_invoked": tools_invoked}
    if risk_flag_raised:
        result["critic"] = await critic_pass(final_text, {"tools_invoked": tools_invoked})

    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
docker compose run --rm --no-deps -e PYTHONPATH=/app -v "$(pwd)/test:/app/test" \
    --entrypoint python backend test/orchestrator_rewrite_test.py
```
Expected: `OK orchestrator_rewrite_test`

- [ ] **Step 5: Re-run Task 1's test to confirm no regression**

Run:
```bash
docker compose run --rm --no-deps -e PYTHONPATH=/app -v "$(pwd)/test:/app/test" \
    --entrypoint python backend test/tools_wiring_test.py
```
Expected: `OK tools_wiring_test`

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/orchestrator.py test/orchestrator_rewrite_test.py
git commit -m "feat(agent): rewrite orchestrator as three-stage tool loop"
```

---

## Task 3: Fix the flow-doc node label

**Files:**
- Modify: `orchestration_flow.md`

**Interfaces:**
- Consumes: nothing.
- Produces: doc consistency — the mermaid node that reads `estimate_fair_price` now reads `compare_price`.

- [ ] **Step 1: Edit the mermaid node**

In `orchestration_flow.md`, replace the line:
```
        K --> L["estimate_fair_price<br/>Qdrant kNN, gate 0.75 + prefix"]
```
with:
```
        K --> L["compare_price<br/>Qdrant kNN, gate 0.75 + head-phrase prefix"]
```

- [ ] **Step 2: Update the two references in the L2 fallback edge (if present)**

Confirm the below-gate fallback edge still reads correctly — the `L -- below gate --> L2` and `L2 --> K` edges need no name change, but verify the surrounding prose (line 3 and the intro) does not say "estimate_fair_price" anywhere. If it does, change it to "compare_price". As of writing, only node `L` names the tool.

- [ ] **Step 3: Commit**

```bash
git add orchestration_flow.md
git commit -m "docs: rename flow-doc price node to compare_price"
```

---

## Self-Review

**Spec coverage:**
- tools.py rewrite (price tool → compare_price) → Task 1. ✓
- orchestrator.py three-stage rewrite → Task 2. ✓
- pricing.py / ghost_tour_score.py / chat.py / client.py untouched → enforced by Global Constraints; no task edits them. ✓
- SOS absent → preserved (no `trigger_sos` added). ✓
- `handle_turn` contract preserved → Task 2 Interfaces + test. ✓
- doc label fix → Task 3. ✓
- standalone smoke tests → `test/tools_wiring_test.py`, `test/orchestrator_rewrite_test.py`. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows full code. ✓

**Type consistency:** `RISK_TOOLS` uses `compare_price` in both Task 2's code and its test; `compare_price` signature matches Task 1's Interfaces and the real module; `handle_turn` / `_parse_images_upfront` / `_run_tool_loop` names consistent across code and Interfaces blocks. ✓
