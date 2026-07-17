"""Critic pass (doc section 3): a second LLM call sanity-checking any risk
conclusion before it's surfaced, to control the false-alarm rate."""

from __future__ import annotations

from typing import Any

from app.ai.client import ai_client

CRITIC_SYSTEM_PROMPT = (
    "You are reviewing a risk conclusion (price anomaly or scam pattern match) before "
    "it is shown to a tourist. Answer only two questions: is the evidence strong enough, "
    "and is there a plausible alternative explanation? Do not add new conclusions."
)


async def critic_pass(conclusion: str, evidence: dict[str, Any]) -> dict[str, Any]:
    response = await ai_client.chat(
        [
            {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
            {"role": "user", "content": f"Conclusion: {conclusion}\nEvidence: {evidence}"},
        ]
    )
    return {"notes": response.content}
