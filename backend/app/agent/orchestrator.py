"""Single orchestrator + tool-calling agent (doc section 3).

Deliberately not a multi-agent swarm: one model loop that calls tools and
reasons over their results, with a critic pass gating any risk conclusion,
and a hard safety rule that keeps emergency dialing out of the agent's reach
entirely (trigger_sos is not in its tool set — see app/agent/tools.py).
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
RISK_TOOLS = {"estimate_fair_price", "match_scam_pattern", "check_ghost_tour"}

SYSTEM_PROMPT = """\
You are the AITravelMate orchestrator: a travel companion and interpreter for tourists \
in Hanoi, Sapa, and Hoi An. You help translate, flag price anomalies, and flag scam \
patterns using your tools. You never invent prices, hotlines, or embassy contacts — \
always use the tools for that.

Hard safety rule: you have no way to place emergency calls or contact authorities \
yourself, and must never claim otherwise. If risk looks high, say so and suggest the \
user tap the SOS button in the app — the call itself always requires their tap.
"""


def _is_risk_flag(tool_name: str, result: dict[str, Any]) -> bool:
    if tool_name not in RISK_TOOLS:
        return False
    return bool(result.get("flag")) or bool(result.get("flagged_as_new_candidate"))


async def _read_images(images: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any] | None]:
    """Read every attached image up front. Returns (context notes for the
    model, the most recent page_transparency read — check_ghost_tour only
    takes one). A bad image is surfaced as an error note, same philosophy
    as call_tool()'s error-as-data handling, rather than crashing the turn."""
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


async def handle_turn(
    user_text: str,
    history: list[dict[str, Any]] | None = None,
    images: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one orchestrator turn. `history` is the already-compressed transcript
    (summary + last N turns) — compression itself is a session/frontend concern,
    not the orchestrator's (doc section 4). `images` are read before this turn's
    model call."""

    image_notes, page_transparency_result = await _read_images(images or [])

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history or [])
    if image_notes:
        messages.append({"role": "user", "content": "\n".join(image_notes)})
    messages.append({"role": "user", "content": user_text})

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
        final_text = "Xin lỗi, mình xử lý hơi lâu — bạn thử hỏi lại ngắn gọn hơn nhé."

    result: dict[str, Any] = {"reply": final_text, "tools_invoked": tools_invoked}

    if risk_flag_raised:
        result["critic"] = await critic_pass(final_text, {"tools_invoked": tools_invoked})

    return result
