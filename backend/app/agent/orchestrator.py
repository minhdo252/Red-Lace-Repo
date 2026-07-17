"""Single orchestrator + tool-calling agent (doc section 3).

Deliberately not a multi-agent swarm: one model loop that calls tools and
reasons over their results, with a critic pass gating any risk conclusion,
and a hard safety rule that keeps emergency dialing out of the agent's reach
entirely (trigger_sos is not in its tool set — see app/agent/tools.py).
"""

from __future__ import annotations

import json
from typing import Any

from app.agent.critic import critic_pass
from app.agent.tools import TOOL_SPECS, call_tool
from app.ai.client import ai_client

MAX_TOOL_ITERATIONS = 5

# Tool outcomes that count as a "risk conclusion" and must go through the critic pass.
RISK_TOOLS = {"estimate_fair_price", "match_scam_pattern"}

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


async def handle_turn(
    user_text: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one orchestrator turn. `history` is the already-compressed transcript
    (summary + last N turns) — compression itself is a session/frontend concern,
    not the orchestrator's (doc section 4)."""

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history or [])
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
            result = await call_tool(call.name, call.arguments)
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
