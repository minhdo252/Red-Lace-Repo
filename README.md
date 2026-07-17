# AITravelMate (Nón AI)

Backend + agent for the 48h MVP described in `NON_AI~1.MD`: a travel companion
and interpreter for tourists in **Hanoi / Sapa / Hoi An** that translates, flags
price anomalies, and flags scams. Structured data lives in Postgres; vector
lookups live in Qdrant; the AI touchpoints call real hosted models (Qwen2.5-VL,
FPT Cloud embeddings) directly.

> ⚠️ **Current status — AI layer mid-migration.** The old mock/live `AIClient`
> (`backend/app/ai/client.py`) has been **removed** in favour of per-provider
> modules. The **menu → price data pipeline works** end-to-end on real
> providers. The **conversational `/chat` orchestrator does not currently boot**:
> `orchestrator`, `critic`, `pricing`, `translation`, `scam_detection`, and
> `image_reader` still import the deleted `app.ai.client` and need rewiring onto
> the real providers (a chat provider, e.g. `GLM_API_KEY`, is not wired yet). The
> FastAPI app therefore fails to import until those references are updated; the
> standalone pipeline/tool scripts below are unaffected.

## Stack (`docker-compose.yml`)

- `postgres` — structured rows: `price_references`, `geo_regions`,
  `emergency_hotlines`, `embassies`, `sessions` (schema: `db/init.sql`)
- `qdrant` — vector collections: `item_names`, `scam_patterns`,
  `unmatched_reports` (bootstrapped on backend startup)
- `adminer` — Postgres UI at http://localhost:8080 (server: `postgres`,
  user/pass from `.env`)
- `backend` — FastAPI app (orchestrator + REST). Built from a Playwright base
  image so it doubles as the crawler/seeder runtime.
- `seed-crawler` — one-shot job, runs before `backend` on first boot to populate
  `price_references` (see [Crawler agents](#crawler-agents))
- `crawler` / `playwright-crawler` / `playwright-full-crawler` — profile-gated
  crawl/debug tools (`docker compose --profile <name> run --rm <service>`)

## Run

```bash
cp .env.example .env       # fill in provider API keys (see "AI providers")
docker compose up --build
```

- API: http://localhost:8000 — `GET /health`, `POST /chat`, `POST /sos`
  (see the status note above re: `/chat`/`/sos`).
- Every compose service builds its **own** image from `./backend`; rebuilding
  `backend` does **not** rebuild `seed-crawler` — rebuild siblings explicitly
  (`docker compose build <service>`) after adding a dependency.

## AI providers

There is no longer a single mock AI client. Each model touchpoint calls its
provider directly, reading its key from the environment (`.env`, loaded by the
`backend`/seed services via `env_file`):

| Concern | Module | Provider / key |
|---|---|---|
| Menu-photo OCR (handwritten VN menus) | `app/ai/qwen_vl.py` | Qwen2.5-VL-7B via FPT Cloud — `QWEN_VL_API_KEY` |
| Text embeddings (Qdrant kNN) | `app/ai/vn_embedding.py` | `Vietnamese_Embedding` via FPT Cloud — `VN_EMBEDDING_API_KEY` |
| Chat / tool-calling reasoning | *(pending)* | not wired — `GLM_API_KEY` reserved |
| Speech-to-text | *(pending)* | not wired — `WHISPER_V3_API_KEY` reserved |

Keys are read with `os.getenv` and fail fast with a clear error if unset/blank.
`EMBEDDING_DIM` (`.env`) must match the embedding model's output (**1024** for
`Vietnamese_Embedding`); the `item_names` collection is created at that size on
first boot — changing it later means deleting and rebuilding the collection.

## Menu → price pipeline

`app/tools/menu_price_pipeline.py` is an end-to-end "conductor" that turns a
photographed menu into saved `price_references` observations by wiring four
existing pieces in one linear flow:

1. **OCR** — `app/ai/qwen_vl.py::ai_detect_menu`: image → Qwen2.5-VL → structured
   items, split into confident `ready_rows` and `needs_review` (uncertain reads
   never leave `needs_review`, so a misread price can't reach the pricing table
   without a human).
2. **Compare** — `app/modules/price_comparison.py::compare_price`: each confident
   dish name is embedded (`vn_embedding`, query side) and kNN'd against Qdrant
   `item_names`, then compared against the nearest comparable Postgres neighbors'
   prices (similarity + head-phrase gating, similarity-weighted mean reference).
3. **Filter** — keep only *matched* comparisons (`--save-which` can flip this to
   `unmatched`/`all`).
4. **Save** — `app/utils/to_postgree.py`: kept items are shaped into
   `price_references` rows (n=1 new observations, `sigma_data` derived from the
   live table) and INSERTed.

Note: this is a plain INSERT, not a merge — saving a *matched* dish appends a new
row next to the reference it matched rather than fusing into it. True online
fusion is `app/modules/pricing.py::record_observation` (out of scope here).

```bash
# run standalone (needs QWEN_VL_API_KEY + VN_EMBEDDING_API_KEY in .env,
# reachable Postgres + Qdrant). --no-save runs OCR→embed→compare without writing.
docker compose run --rm --no-deps -v "$(pwd)/test:/app/test" \
    --entrypoint python backend \
    -m app.tools.menu_price_pipeline "test/menu 1.jpg" Hanoi --no-save
```

Region note: pass the region **as stored in `price_references`** (e.g. `Hanoi`),
not qwen_vl's finer `KNOWN_REGIONS` taxonomy (`Hanoi/Old Quarter`) — the same
string filters Qdrant, so a mismatch silently yields zero matches.

## Orchestrator agent

`app/agent/orchestrator.py` implements the doc's section-3 design: **single
orchestrator + tool-calling**, not a multi-agent swarm.

- `app/agent/tools.py` — the 6 tool specs exposed to the model
  (`estimate_fair_price`, `read_image`, `match_scam_pattern`, `check_domain_age`,
  `check_business_existence`, `translate_or_get_hotline`) and their dispatch to
  `app/modules/*`.
- `app/agent/critic.py` — second-pass check run whenever a tool raises a
  price-anomaly or scam-pattern flag, before it's surfaced.
- **Hard safety rule, enforced structurally, not just by prompt**: `trigger_sos`
  is not in `TOOL_SPECS` and not in `TOOL_DISPATCH` — the agent has no code path
  to place an emergency call. `/sos` is a separate endpoint the frontend hits
  directly on a user tap.

The orchestrator/critic still call the removed `ai_client.chat` and are part of
the AI migration noted above.

## Module implementation status

| Module | File | Status |
|---|---|---|
| Menu-photo OCR (6.4) | `ai/qwen_vl.py` | **Real** — Qwen2.5-VL, deterministic decoding, strict JSON, uncertainty-flagged |
| Text embeddings (6.1 lookup) | `ai/vn_embedding.py` | **Real** — FPT Cloud, asymmetric query/passage |
| Menu→price pipeline | `tools/menu_price_pipeline.py` | **Real** — OCR → compare → save conductor |
| Direct neighbor-price compare | `modules/price_comparison.py` | **Real** — gated kNN, similarity-weighted reference |
| VLM rows → `price_references` | `utils/to_postgree.py` | **Real** — sync psycopg2, DB-derived sigma, sanity floor |
| PII redaction (6.3) | `modules/pii.py` | **Real** — regex pass |
| Domain age (WHOIS) | `modules/domain_check.py` | **Real** — no key needed |
| Business existence (Google Places) | `modules/business_check.py` | **Real HTTP** — needs `GOOGLE_PLACES_API_KEY` |
| Bayesian fair-price fusion (6.1) | `modules/pricing.py` | Real math; **imports removed `ai_client`** → pending rewire |
| Scam pattern kNN + capture (6.2) | `modules/scam_detection.py` | Real Qdrant logic; **`ai_client.embed`** → pending rewire |
| Image reading tool (6.4) | `modules/image_reader.py` | **`ai_client.vision`** → pending rewire |
| Translation + hotline/embassy | `modules/translation.py` | Hotline/embassy lookup real; **`ai_client.chat`** → pending rewire |

## Seeding data

`db/init.sql` seeds `geo_regions` for Hanoi/Sapa/Hoi An and the `price_references`
schema (raw `price_vnd` alongside the log-space posterior `mu_post`/`tau_post`).
`price_references` is populated automatically on first boot by the `seed-crawler`
service. `emergency_hotlines`, `embassies`, and the Qdrant `scam_patterns`
collection still need real MVP data loaded manually. The `item_names` vectors are
built from `price_references` by `python -m app.ai.vn_embedding`.

## Crawler agents

ShopeeFood's *listing* page is a client-rendered SPA, but each restaurant's
*menu* page renders with plain headless Chromium (Playwright) — no signed API
needed — so a real per-dish price crawler is feasible within scope.

| File | Role |
|---|---|
| `backend/app/utils/menu_extract.py` | DOM selectors for menu items on a restaurant page |
| `backend/app/utils/menu_normalize.py` | Cleans item names, parses VND prices, drops noise rows |
| `backend/app/tools/crawl_shopeefood_full.py` | Paginates the full Hanoi listing, scrapes every menu, writes JSON |
| `backend/app/agent/seed_price_references.py` | Reuses the crawler, merges observations per item, inserts into `price_references` |
| `test/crawl_menu_dom_explorer.py` | Dev tool: dumps one restaurant's rendered DOM/CSS to reverse-engineer selectors |

**Automatic on boot**: `docker compose up` runs `seed-crawler` before `backend`
(`depends_on: condition: service_completed_successfully`). It skips crawling if
`price_references` already has rows, otherwise seeds from the committed
`backend/app/agent/output/crawled_restaurants_cache.json` snapshot instead of
hitting ShopeeFood live. Delete that file (or set `FORCE_LIVE_CRAWL=1`) to force a
fresh live crawl. The seeder always exits 0 so a crawl failure never blocks the
stack.

```bash
docker compose run --rm seed-crawler                       # manual re-run
CRAWL_MAX_PAGES=1 docker compose run --rm seed-crawler      # fast: fewer pages
docker compose --profile playwright-full run --rm playwright-full-crawler  # JSON output only
```

Business-existence data for module 2.2 (ghost-tour detector) has no crawler —
`check_business_existence` calls the live Google Places API per request and needs
`GOOGLE_PLACES_API_KEY`.

## Known issues

- **Backend does not boot** until the six `app.ai.client` importers are rewired
  onto real providers (see status note at top).
- Each compose service builds its own image; a stale sibling image throws
  `ModuleNotFoundError` after a dependency is added — `docker compose build <svc>`.
- A crawler run under the old root-only image can leave `test/output/`
  root-owned, blocking new writes: `sudo chown -R $USER:$USER test/output`.
