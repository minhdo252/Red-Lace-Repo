"""
web_search.py
-------------
The single web-search primitive for the app. Given a query string, hits
Tavily's search API and returns the top 5–7 results as plain dicts
(``{title, url, content, score}``). Every web-search consumer goes through
this one function:

  - the MCP server (app/utils/mcp_search_server.py) wraps it as a tool for
    external MCP clients,
  - the orchestrator agent exposes it as the ``search_web`` tool
    (app/agent/tools.py),
  - the price-comparison web fallback (app/modules/price_web_fallback.py)
    calls it when the local kNN over Qdrant misses.

Live-only by design: it reads TAVILY_API_KEY directly from the environment
(the new-provider convention used by vn_embedding.py / qwen_vl.py — NOT via
app/config.py::Settings). No mock path. A missing key raises RuntimeError,
which the agent's call_tool() surfaces as ``{"error": ...}`` rather than
crashing the turn.
"""

from __future__ import annotations

import os

import httpx

TAVILY_URL = "https://api.tavily.com/search"

# The result count is deliberately clamped to a narrow band: enough snippets
# for an LLM to triangulate a price, few enough to keep the prompt tight.
MIN_RESULTS = 5
MAX_RESULTS = 7
TIMEOUT_SECONDS = 15.0


def _require_api_key() -> str:
    """Read TAVILY_API_KEY from the environment. Fails clearly if unset OR
    empty, rather than letting a blank key surface as an opaque auth error."""
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        raise RuntimeError(
            "TAVILY_API_KEY is not set. Add it to .env (loaded by the backend "
            "service via env_file) or export it in the environment. Web search "
            "is live-only — there is no mock fallback."
        )
    return key


async def search_web(
    query: str,
    region: str | None = None,
    max_results: int = MAX_RESULTS,
) -> list[dict]:
    """Search the web for ``query`` and return 5–7 results.

    ``region`` (e.g. "Hanoi") is appended to the query as a soft bias, not a
    hard filter. ``max_results`` is clamped into [MIN_RESULTS, MAX_RESULTS].
    Returns a list of ``{title, url, content, score}`` dicts; an empty result
    set returns ``[]`` (not an error). Raises on a missing key or a Tavily
    non-2xx / timeout.
    """
    api_key = _require_api_key()
    n = max(MIN_RESULTS, min(MAX_RESULTS, max_results))
    q = f"{query} {region}".strip() if region else query.strip()

    payload = {
        "query": q,
        "max_results": n,
        "search_depth": "basic",
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        resp = await client.post(TAVILY_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
            "score": r.get("score"),
        }
        for r in data.get("results", [])
    ]
