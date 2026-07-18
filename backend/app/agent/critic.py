"""Critic pass (doc section 3): a second GLM-5.2 call that sanity-checks a risk
conclusion before it is surfaced, given EVERY module output the turn produced.

The orchestrator hands over `evidence["tools_invoked"]` — the full list of tool/
module invocations (compare_price, match_scam_pattern, check_ghost_tour, the
OCR-driven price comparisons, ...), each with its input args and raw result.
The critic formats all of them into the prompt so GLM-5.2 judges the warning
against the actual evidence, not a summary of it.

GLM-5.2 is called directly (app/ai/glm_chat.py) rather than through the mock/live
AIClient switch — the key is read from the environment. When no GLM key is
configured, the critic degrades to an explicit "unreviewed" note instead of
failing, so the keyless mock stack still runs end to end.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.ai.glm_chat import glm_chat, has_api_key

CRITIC_SYSTEM_PROMPT = (
    "You are the critic reviewing a risk conclusion (price anomaly, scam-pattern match, "
    "or ghost-tour/homestay composite) before it is shown to a tourist in Vietnam. You "
    "are given the assistant's draft reply plus the raw output of every tool/module that "
    "ran this turn. Answer only two things, concisely: (1) is the evidence strong enough "
    "to justify warning the user, and (2) is there a plausible innocent explanation? Do "
    "not invent new conclusions or new numbers — judge only what the module outputs "
    "actually support. Keep your answer to 2-4 sentences."
)


def _format_module_outputs(tools_invoked: list[dict[str, Any]]) -> str:
    """Render each module's input + raw output as its own labeled block, so the
    critic sees the concrete evidence rather than a stringified blob."""
    if not tools_invoked:
        return "(no module outputs this turn)"
    blocks: list[str] = []
    for index, invocation in enumerate(tools_invoked, start=1):
        tool = invocation.get("tool", "unknown")
        args = json.dumps(invocation.get("arguments", {}), ensure_ascii=False, default=str)
        result = json.dumps(invocation.get("result", {}), ensure_ascii=False, default=str)
        blocks.append(f"[{index}] module={tool}\n    input:  {args}\n    output: {result}")
    return "\n".join(blocks)


async def critic_pass(conclusion: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """Review `conclusion` against every module output in
    `evidence["tools_invoked"]`. Returns {notes, verdict, reasoning?} (or a
    degraded 'unreviewed' note when no GLM key is configured)."""
    tools_invoked = (evidence or {}).get("tools_invoked", []) or []
    module_block = _format_module_outputs(tools_invoked)

    user_content = (
        f"Assistant draft reply to the tourist:\n{conclusion or '(empty)'}\n\n"
        f"Raw module outputs this turn:\n{module_block}\n\n"
        "Given only this evidence: is the warning justified, and is there a plausible "
        "innocent explanation? Answer in 2-4 sentences."
    )

    if not has_api_key():
        return {
            "notes": (
                "[critic unavailable] GLM_API_KEY not set — the risk conclusion was "
                "surfaced without a second-model review."
            ),
            "verdict": "unreviewed",
            "degraded": True,
        }

    messages = [
        {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    # Reasoning model: the budget must cover the full reasoning trace AND still
    # reach the final answer — too small and content comes back empty (all budget
    # spent thinking). 1024 was occasionally short; 2048 lands the verdict reliably.
    response = await asyncio.to_thread(glm_chat, messages, temperature=0.3, max_tokens=2048)

    notes = (response.content or "").strip()
    if not notes:
        notes = "[critic returned no final answer — reasoning-only; treat as unreviewed]"
    return {"notes": notes, "verdict": "reviewed", "reasoning": response.reasoning}
