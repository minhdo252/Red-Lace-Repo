# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AITravelMate (Nón AI) — a FastAPI backend + single orchestrator agent that helps tourists in Hanoi/Sapa/Hoi An translate, flag price anomalies, and flag scams. It is the 48h-MVP infra scaffold described in `NON_AI~1.MD`; the README maps modules to doc sections. It boots and is fully testable with mocked AI responses (`AI_MODE=mock`, the default) — no API key required.

## Commands

Everything runs through Docker Compose from the repo root. There is no local Python env, lint config, or pytest setup — tests are standalone asyncio smoke scripts under `test/`, not pass/fail suites.

```bash
# Boot the whole stack (API on :8000, Adminer on :8080)
cp .env.example .env
docker compose up --build

# Run a single manual test script against already-running postgres/qdrant.
# --no-deps is important: it skips the seed-crawler startup gate (see Gotchas).
docker compose run --rm --no-deps -e PYTHONPATH=/app -v "$(pwd)/test:/app/test" \
    --entrypoint python backend test/price_comparison_test.py

# Run an AI/data module standalone (module form; cwd is /app so `app.` resolves)
docker compose run --rm backend python -m app.ai.vn_embedding

# Seeding (idempotent: skips if price_references already has rows)
docker compose run --rm seed-crawler
CRAWL_MAX_PAGES=1 docker compose run --rm seed-crawler   # fast: fewer listing pages

# Inspect crawl output as JSON without touching Postgres
docker compose --profile playwright-full run --rm playwright-full-crawler
```

API endpoints: `GET /health`, `POST /chat` (`{session_id, text, history}`), `POST /sos` (`{session_id, region, nationality}`).

## Architecture

### Single orchestrator + tool-calling (not a multi-agent swarm)
`app/agent/orchestrator.py::handle_turn` runs one model loop (`MAX_TOOL_ITERATIONS = 5`): call `ai_client.chat` with `TOOL_SPECS`, dispatch any tool calls, feed results back, repeat until the model returns final text. `app/agent/tools.py` holds the 6 tool specs + `TOOL_DISPATCH` into `app/modules/*`. `call_tool` catches exceptions and returns them as `{"error": ...}` data rather than crashing the turn.

**Structural SOS safety (not just prompt-based):** `trigger_sos` is deliberately absent from `TOOL_SPECS`/`TOOL_DISPATCH`, so a live model cannot place an emergency call even if it hallucinates the tool name. `/sos` is a separate router (`app/routers/sos.py`) the frontend hits directly on a user tap. Do not add emergency dialing to the agent's tool set.

**Critic gate:** when a `RISK_TOOLS` result (`estimate_fair_price`, `match_scam_pattern`) raises a `flag`/`flagged_as_new_candidate`, `handle_turn` runs `app/agent/critic.py::critic_pass` before the conclusion is surfaced.

### The AI abstraction is mid-migration — two generations coexist
- **Old / placeholder:** `app/ai/client.py::AIClient` (the singleton `ai_client`) routes chat + vision + embed through one class with `mock`/`live` modes. `mock` returns canned responses (and a deterministic pseudo-embedding) so the whole loop is runnable with no key; `live` raises `NotImplementedError` at three `TODO` markers. The orchestrator and `modules/pricing.py` still go through this.
- **New / real providers:** `app/ai/vn_embedding.py` (FPT Cloud `Vietnamese_Embedding`, called via the OpenAI SDK against a custom `base_url`) and `app/ai/qwen_vl.py` (Qwen2.5-VL menu OCR) call their providers **directly**, bypassing `AIClient`. `client.py` is slated for deletion — **do not make new AI modules conform to the `AIClient` interface.** Provider keys (`VN_EMBEDDING_API_KEY`, `QWEN_VL_API_KEY`, …) are read directly via `os.environ` inside those modules, *not* through `app/config.py::Settings` (which only knows postgres/qdrant/`ai_*`/`google_places_api_key`/`embedding_dim`).

### Two parallel fair-price implementations
Both exist; know which is which:
- `modules/pricing.py::estimate_fair_price` — the one **wired into the agent** (`tools.py`). Bayesian log-space Normal-Normal fusion of an LLM-elicited prior with observed data, using `AIClient.embed` (mock). Also has `record_observation` for online O(1) updates.
- `modules/price_comparison.py::compare_price` — newer, **not wired into the agent**. Direct comparison: embeds via the real `vn_embedding.embed_query_texts`, kNN's `item_names`, and averages the nearest comparable neighbors' raw `price_vnd` as the reference. Its smoke test is `test/price_comparison_test.py`.

The `price_references` row carries **both** representations: raw `price_vnd` (display / direct compare) and the log-space posterior `mu_post`/`tau_post`/`sigma_data`/`n`/`sum_y` (Bayesian path).

### Data split: Postgres = rows, Qdrant = vectors
Postgres (`db/init.sql`) holds structured rows: `price_references`, `geo_regions`, `emergency_hotlines`, `embassies`, `sessions`. Qdrant holds vector collections: `item_names`, `scam_patterns`, `unmatched_reports`, bootstrapped by `ensure_collections()` in the FastAPI `lifespan` on startup. **No vectors in Postgres, no structured payload duplicated in Qdrant** — a Qdrant point's payload carries `postgres_id` and the lookup flow is *kNN in Qdrant → fetch the row from Postgres by that id*.

### Crawler / seeding pipeline
`seed-crawler` runs before `backend` on first boot and populates `price_references` from ShopeeFood Hanoi menus. It reuses `app/tools/crawl_shopeefood_full.py` (Playwright; menu pages render with plain headless Chromium, no signed API) + `app/utils/menu_extract.py` (DOM selectors) + `app/utils/menu_normalize.py` (name cleanup / VND parsing). It's idempotent (skips if rows exist) and seeds from the committed `backend/app/agent/output/crawled_restaurants_cache.json` snapshot unless `FORCE_LIVE_CRAWL=1`. It always exits 0 so a crawl failure never blocks the stack.

## Gotchas

- **Each compose service builds its own image from the shared `./backend` Dockerfile.** `backend`, `seed-crawler`, `crawler`, and the `playwright-*` services are separate images. Rebuilding `backend` does **not** rebuild `seed-crawler` — after adding a dependency to `requirements.txt`, an un-rebuilt sibling image throws `ModuleNotFoundError` at import. Fix with `docker compose build <service>` (or `docker compose build` for all).
- **`backend` has `depends_on: seed-crawler: condition: service_completed_successfully`.** A failing `seed-crawler` blocks `docker compose up` *and* `docker compose run backend`. For one-off scripts/tests against an already-running stack, add `--no-deps` to bypass the gate.
- **`EMBEDDING_DIM` must match the embedding model's output** (1024 for `Vietnamese_Embedding`; note `config.py`'s default is 384, and `.env.example` overrides to 1024). The `item_names` collection is created at whatever `EMBEDDING_DIM` is on first boot — changing it later requires deleting and rebuilding the collection.
- The Docker image is the Playwright base; `backend` runs as `pwuser` (UID 1000), while the crawler/seed services override back to `root` at runtime because Chromium in Docker needs it. A crawler run under an old root-only image can leave `test/output/` root-owned — `sudo chown -R $USER:$USER test/output` if writes start failing.
- Several `app/ai/*` modules named in `.env.example` (`whisper_v3.py`, `embedding.py`, `glm_chat.py`) are planned but not yet present — only `client.py`, `qwen_vl.py`, `vn_embedding.py` exist.
