# Web Search Fallback for Price Comparison — Design

**Date:** 2026-07-18
**Status:** Implemented

> **Revision (post-implementation):** the standalone MCP server was **removed**.
> The in-app orchestrator is not an MCP client (not Claude Desktop/Code), so an
> MCP transport had no consumer. Web search is now consumed only via (a) the
> automatic price-comparison fallback and (b) the internal `search_web`
> `TOOL_SPEC` (ordinary OpenAI-style tool-calling, model-agnostic — not MCP).

## Goal

1. Give the app a **web search** capability (search an item name, get **5–7
   results**) behind one shared `search_web` function — consumed by the
   price-comparison fallback and, optionally, the orchestrator's internal
   tool-calling. No duplicated logic.
2. Use that search as a **fallback stage in the price-comparison pipeline**:
   raise the local-match threshold; on a confident-match miss, fall back to LLM
   web search to derive a reference price; **persist** the web-sourced value
   back into Postgres + Qdrant so the DB self-enriches and next lookup is local.
3. **Minimize response latency:** return the price comparison to the chatbot
   *before* the DB write. Persistence happens off the critical path.

## Decisions (locked)

| Decision                 | Choice                                                       |
|--------------------------|-------------------------------------------------------------|
| Search packaging         | ~~MCP server~~ **removed** — plain `search_web` function    |
| Search consumers         | Price-comparison fallback + internal `search_web` TOOL_SPEC |
| Search provider          | **Tavily** (`https://api.tavily.com/search`) via `httpx`    |
| Search mode              | **Live only** — requires `TAVILY_API_KEY`; no mock path     |
| Result count             | Clamped to **[5, 7]**, default 7                            |
| Fallback pipeline        | **`modules/price_comparison.py::compare_price`**            |
| Local-match threshold    | `MATCH_THRESHOLD` raised **0.6 → 0.75** (tunable)          |
| Price extraction         | **Qwen-VL text-only** (`qwen_vl.py`, `QWEN_VL_API_KEY`)     |
| Extraction output shape  | Full `price_references` row: `{item_name, region, category, price_vnd, source_url}` |
| Write-back provenance    | New row tagged **`source='websearch'`** (+ `source_url`)   |
| Write-back timing        | **Deferred** (fire-and-forget) — after price is returned    |

## Architecture

```
external MCP client ─┐
                     ├─► search_item (FastMCP tool) ─┐
orchestrator loop ───┴─► "search_web" TOOL_SPEC ─────┴─► web_search.search_web() ─► Tavily REST ─► [5–7 results]
                                                                     ▲
compare_price() local miss (score < 0.75) ─► price_web_fallback() ───┘
        │  (Tavily does the search; Qwen-VL only reads the returned snippets — it cannot browse)
        ├─(critical path)─► Qwen-VL extract {item_name, region, category, price_vnd, source_url} ─► return reference price to chatbot
        └─(deferred task)─► embed passage ─► INSERT price_references(source='websearch') + upsert Qdrant item_names
```

`web_search.search_web` is the single source of truth for search. The MCP
server and the agent tool are ~10-line adapters over it. The pricing fallback
also calls it in-process. Rejected: duplicating search logic; and having the
agent round-trip to the MCP server as a subprocess client for an in-process call.

## Components

### 1. `backend/app/utils/web_search.py` — search core

```python
async def search_web(query: str, region: str | None = None, max_results: int = 7) -> list[dict]
```
- Reads `TAVILY_API_KEY` from `os.environ` (new-provider convention like
  `vn_embedding.py` / `qwen_vl.py`; **not** `config.py::Settings`).
- `max_results` clamped into `[5, 7]`.
- `region`, when given, appended to the query text as a soft bias
  (`"phở bò Hà Nội"`), not a hard filter.
- POST to Tavily via `httpx.AsyncClient`, ~15s timeout.
- Returns `list[{title, url, content, score}]` (`content` = snippet).
- Errors: missing/empty key → `RuntimeError`; Tavily non-200/timeout → raised
  with status text; zero results → `[]` (not an error).

### 2. `backend/app/utils/mcp_search_server.py` — MCP server

- `mcp` SDK `FastMCP`. One tool:
  `search_item(query, region=None, max_results=7) -> list[dict]` → awaits
  `search_web(...)`.
- Runnable over stdio: `python -m app.utils.mcp_search_server`. Lives in
  `app/utils/` per request ("build a MCP in utils").

### 3. In-app search tool — `backend/app/agent/tools.py`

- `TOOL_SPECS` entry `search_web`: `query` (required), `region` (optional),
  `max_results` (optional).
- `TOOL_DISPATCH`: `lambda args: search_web(**args)`.
- Plain info tool: **not** in `RISK_TOOLS` (no critic gate). Missing key
  surfaces as `{"error": ...}` via the existing `call_tool` guard.

### 4. `backend/app/modules/price_web_fallback.py` — the fallback (NEW)

```python
async def web_fallback_price(item: str, region: str, category: str) -> dict | None
```
**Critical path (awaited, blocks the response):**
1. `results = await search_web(f"{item} giá", region, max_results=7)`.
2. `extract_price_from_web(item, region, category, results)` in `qwen_vl.py`
   (text-only Qwen-VL call) → parse
   `{item_name, region, category, price_vnd: float|null, source_url: str|null}`
   shaped to the `price_references` schema.
3. If `price_vnd` is null/unparseable → return `None` (no reference found).
4. **Schedule** the deferred write-back (below), then **return** the extracted
   row (`reference_price = price_vnd`, `source_url`) immediately.

**Deferred write-back (fire-and-forget `asyncio` task, NOT awaited):**
5. `vector = embed_passage_texts([item])[0]`.
6. `INSERT INTO price_references (item_name, region, category, price_vnd,
   source, source_url) VALUES (..., 'websearch', ...) RETURNING id`.
7. `qdrant.upsert("item_names", [PointStruct(id=new_id, vector=vector,
   payload={region, category, postgres_id: new_id})])`.

Detached-task safety: keep a module-level `set` of live tasks; each task's
`add_done_callback` discards it from the set **and** logs any exception (a
detached task's failure can't propagate to the request). Accepted MVP risk:
two lookups of the same item before write-back completes can create a duplicate
row.

### 5. `compare_price` change — `backend/app/modules/price_comparison.py`

- `MATCH_THRESHOLD` `0.6 → 0.75`.
- When the head-phrase-gated neighbor set is **empty**, call
  `web_fallback_price(item, region, category)`:
  - hit → `reference_price` from web, `reference_source: "websearch"`, plus
    `source_url`; recompute `flag`/`price_diff_*` against it.
  - miss (`None`) → `reference_source: "none"`, `matched: false`, `flag: null`.
- Local hits set `reference_source: "local"`.
- `reference_source ∈ {"local", "websearch", "none"}` is present in **every**
  return.

### 6. `embed_passage_texts()` — `backend/app/ai/vn_embedding.py` (NEW)

Mirrors `embed_query_texts` but `input_type="passage"`. Required: crawled rows
are indexed as passages, so web-sourced write-back rows must be too, or the
asymmetric-retrieval model's match quality degrades.

### 7. `extract_price_from_web()` — `backend/app/ai/qwen_vl.py` (NEW)

```python
def extract_price_from_web(item: str, region: str, category: str, results: list[dict]) -> dict | None
```
- Text-only call to Qwen2.5-VL via the existing FPT Cloud endpoint
  (`BASE_URL`, `MODEL_NAME`, `QWEN_VL_API_KEY` — reuses `_require_api_key()`).
  No image; the model reads the search snippets as text.
- Deterministic decoding + strict JSON output, mirroring `ai_detect_menu`'s
  anti-hallucination stance ("do not guess a price; return null if unclear").
- Prompt: given the query item + the 5–7 `{title, url, content}` snippets,
  return one JSON object shaped to `price_references`:
  `{item_name, region, category, price_vnd, source_url}`. `price_vnd` is null
  if no defensible price can be read.
- Returns the parsed dict, or `None` if `price_vnd` can't be determined.
- Qwen-VL is an *instruct* model that accepts text-only input, so no vision
  payload is needed — but it still cannot browse; Tavily supplies the content.

## Dependencies & config

- `backend/requirements.txt`: add `mcp>=1.2.0` (`httpx` already present).
  Only the `backend` image imports `mcp`; rebuild `backend` after adding.
- `.env.example`: add `TAVILY_API_KEY=` with a "search tool is live-only" note.
  (`.env` already has a working key.)
- Extraction reuses the existing `QWEN_VL_API_KEY` + FPT Cloud endpoint already
  wired in `qwen_vl.py` — no new AI config, no dependency on `AI_API_KEY` /
  AI Marketplace.

## Schema — `db/init.sql`

- Add to the `CREATE TABLE price_references` body:
  `source TEXT NOT NULL DEFAULT 'crawl'`, `source_url TEXT`.
- Add idempotent migration for existing DBs:
  ```sql
  ALTER TABLE price_references ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'crawl';
  ALTER TABLE price_references ADD COLUMN IF NOT EXISTS source_url TEXT;
  ```

## Testing

- `test/web_search_test.py` — asyncio smoke script (live, needs
  `TAVILY_API_KEY`): runs a sample Hanoi-dish query, prints the 5–7 results,
  asserts count ∈ [5,7] and expected keys per result.
- `test/price_web_fallback_test.py` — asyncio smoke script (live, needs Tavily
  + `QWEN_VL_API_KEY`): forces a miss (unknown item), asserts a `websearch` reference is
  returned, then (after a short await) asserts a `source='websearch'` row +
  Qdrant point were written.
- Run with `--no-deps` to bypass the seed-crawler gate (per CLAUDE.md).
- MCP server sanity-checked by launching over stdio and listing tools.

## Out of scope (YAGNI)

- No mock mode for search (explicitly live-only).
- No caching / rate-limiting / dedup layer (duplicate-row risk accepted).
- No SSE/HTTP MCP transport — stdio only.
- No change to the Bayesian `estimate_fair_price` path; fallback is
  `compare_price`-only.
