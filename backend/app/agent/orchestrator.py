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
    region: str | None = None,
) -> tuple[list[str], dict[str, Any] | None, list[dict[str, Any]]]:
    """Stage 1. Read every attached image up front and, for menu OCR reads
    (receipt/dish), deterministically compare each confidently-priced item
    against local references via compare_price — the fair-price verdict the OCR
    already handed us shouldn't wait on the model to re-request it.

    Returns (context notes for the model, the most recent successful
    page_transparency read — check_ghost_tour only takes one, the compare_price
    invocations run from OCR items). `region` is threaded from the chat request:
    read_image needs it to run the real Qwen VL OCR, and compare_price needs it
    to scope the kNN lookup. A bad image is surfaced as an error note, same
    philosophy as call_tool()'s error-as-data handling, rather than crashing the
    turn."""
    notes: list[str] = []
    page_transparency_result: dict[str, Any] | None = None
    image_invocations: list[dict[str, Any]] = []

    for img in images:
        mode = img.get("mode")
        try:
            image_bytes = base64.b64decode(img["image_base64"])
            result = await read_image(image_bytes, mode, region=region)
        except Exception as exc:  # noqa: BLE001 - surface as data, don't crash the turn
            result = {"error": str(exc)}

        if mode == "page_transparency" and isinstance(result, dict) and "error" not in result:
            page_transparency_result = result
        notes.append(f"[read_image mode={mode}] {result}")

        # Menu OCR hands back ready_items already shaped for compare_price
        # (item_name -> item, price_vnd -> observed_price). Run them now so the
        # fair-price judgement is in context before the model reasons. Needs a
        # region (compare_price scopes its kNN by region); without one the OCR
        # path didn't run either, so there's nothing to compare.
        if region and isinstance(result, dict):
            for item in result.get("ready_items") or []:
                args = {
                    "item": item["item_name"],
                    "region": region,
                    "category": result.get("category", "food"),
                    "observed_price": item["price_vnd"],
                }
                comparison = await call_tool("compare_price", args)
                image_invocations.append({"tool": "compare_price", "arguments": args, "result": comparison})
                notes.append(f"[compare_price item={args['item']}] {comparison}")

    return notes, page_transparency_result, image_invocations


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
    region: str | None = None,
) -> dict[str, Any]:
    """Run one orchestrator turn. `history` is the already-compressed transcript
    (summary + last N turns) — compression itself is a session/frontend concern, not the
    orchestrator's. `images` are VLM-read before this turn's model call. `region` is the
    resolved chat region; it lets the upfront image stage run the real menu OCR and
    compare the extracted prices against local references."""

    image_notes, page_transparency_result, image_invocations = await _parse_images_upfront(
        images or [], region
    )

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history or [])
    if image_notes:
        messages.append({"role": "user", "content": "\n".join(image_notes)})
    messages.append({"role": "user", "content": user_text})

    final_text, tools_invoked, risk_flag_raised = await _run_tool_loop(
        messages, page_transparency_result
    )

    # OCR-driven price comparisons are part of the turn's evidence and can raise a
    # risk flag of their own (an overpriced menu item), same as an in-loop tool call.
    all_invocations = image_invocations + tools_invoked
    image_risk = any(_is_risk_flag(inv["tool"], inv["result"]) for inv in image_invocations)

    result: dict[str, Any] = {"reply": final_text, "tools_invoked": all_invocations}
    if risk_flag_raised or image_risk:
        result["critic"] = await critic_pass(final_text, {"tools_invoked": all_invocations})

    return result
