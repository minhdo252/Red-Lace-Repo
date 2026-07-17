# AITravelMate (Nón AI) — infra scaffold

Docker infrastructure + orchestrator agent for the 48h MVP described in
`NON_AI~1.MD`. Runs end-to-end with mocked AI responses out of the box; no
API key required to boot the stack.

## Stack

- `postgres` — structured data: `price_references`, `geo_regions`,
  `emergency_hotlines`, `embassies`, `sessions` (schema: `db/init.sql`)
- `qdrant` — vector collections: `item_names`, `scam_patterns`,
  `unmatched_reports` (bootstrapped on backend startup)
- `adminer` — Postgres UI at http://localhost:8080 (system: PostgreSQL,
  server: `postgres`, user/pass from `.env`)
- `backend` — FastAPI app with the single orchestrator agent
- `seed-crawler` — one-shot job, runs before `backend` on first boot to
  populate `price_references` (see [Crawler agents](#crawler-agents))
- `crawler` / `playwright-crawler` / `playwright-full-crawler` — manual,
  profile-gated crawl/debug tools (`docker compose --profile <name> run --rm <service>`)

## Run it

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000
- `GET /health`
- `POST /chat` — `{"session_id": "...", "text": "...", "history": []}`
- `POST /sos` — `{"session_id": "...", "region": "Old Quarter", "nationality": "..."}`
  (hardcoded lookup, deliberately not reachable from the agent — see below)

## Where the AI goes

Every model call (chat/tool-calling reasoning, vision, embeddings) is routed
through `backend/app/ai/client.py::AIClient`. With `AI_MODE=mock` (the
`.env.example` default) it returns canned responses so the whole
orchestrator loop, tool dispatch, and DB plumbing are runnable and testable
today. Swap in your own LLM API call at the three `TODO` markers in that
file, flip `AI_MODE=live`, and the orchestrator loop (`app/agent/orchestrator.py`)
starts actually calling tools based on real model output.

## Orchestrator agent

`app/agent/orchestrator.py` implements the doc's section-3 design: **single
orchestrator + tool-calling**, not a multi-agent swarm.

- `app/agent/tools.py` — the 6 tool specs exposed to the model
  (`estimate_fair_price`, `read_image`, `match_scam_pattern`,
  `check_domain_age`, `check_business_existence`, `translate_or_get_hotline`)
  and their dispatch to `app/modules/*`.
- `app/agent/critic.py` — second-pass check run whenever a tool raises a
  price-anomaly or scam-pattern flag, before it's surfaced.
- **Hard safety rule, enforced structurally, not just by prompt**:
  `trigger_sos` is not in `TOOL_SPECS` and not in `TOOL_DISPATCH` — the
  agent has no code path to place an emergency call. `/sos` is a separate
  endpoint the frontend hits directly on a user tap.

## Module implementation status

| Module | File | Status |
|---|---|---|
| Bayesian fair-price fusion (6.1) | `modules/pricing.py` | Real math, wired to Postgres + Qdrant |
| PII redaction (6.3) | `modules/pii.py` | Real regex pass |
| Domain age (WHOIS) | `modules/domain_check.py` | Real, no key needed |
| Scam pattern kNN + unmatched capture (6.2) | `modules/scam_detection.py` | Real, needs `AIClient.embed` wired |
| Business existence (Google Places) | `modules/business_check.py` | Real HTTP call, needs `GOOGLE_PLACES_API_KEY` |
| Image reading (6.4) | `modules/image_reader.py` | Delegates to `AIClient.vision` (placeholder) |
| Translation + hotline/embassy | `modules/translation.py` | Hotline/embassy lookup real; translation via `AIClient.chat` (placeholder) |

## Seeding data

`db/init.sql` seeds `geo_regions` for Hanoi/Sapa/Hoi An and the
`price_references` schema (now with a `price_vnd` column alongside
`mu_post`/`tau_post` for display). `price_references` itself is no longer
manual-only: the `seed-crawler` service (below) populates it automatically
on first boot. `emergency_hotlines`, `embassies`, and the Qdrant
`item_names`/`scam_patterns` collections still need real MVP data loaded —
that part of the 0-6h roadmap step remains manual.

## Crawler agents

The doc's section 2 originally scoped real crawlers out of the 48h MVP
(manual entry + LLM synthesis instead) because ShopeeFood/TripAdvisor/Grab
looked ToS-gated. Investigation (`test/crawl_shopeefood_playwright.py`,
`test/crawl_menu_dom_explorer.py`) found ShopeeFood's *listing* page is a
client-rendered SPA but each restaurant's *menu* page is reachable with a
plain headless-Chromium render (Playwright) — no signed internal API
needed — so a real per-dish price crawler turned out to be feasible within
scope after all, and module 2.1's price data no longer depends on manual
entry.

| File | Role |
|---|---|
| `backend/app/utils/menu_extract.py` | DOM selectors for menu items on a restaurant page (verified against real rendered DOM via `crawl_menu_dom_explorer.py`) |
| `backend/app/utils/menu_normalize.py` | Cleans item names, parses VND prices, drops noise rows |
| `backend/app/tools/crawl_shopeefood_full.py` | Paginates the full Hanoi listing, scrapes every restaurant's menu, writes JSON (`test/output/shopeefood_full.json`, `price_references_seed.json`) — run this directly to inspect crawl output without touching Postgres |
| `backend/app/agent/seed_price_references.py` | Reuses the crawler above, groups observations per item, merges them into one posterior per `(item_name, region, category)`, and inserts straight into `price_references` |
| `test/crawl_shopeefood_playwright.py` | Early listing-page render spike (superseded by the full crawler above; kept for reference) |
| `test/crawl_menu_dom_explorer.py` | Dev/debug tool: dumps one restaurant's rendered DOM + CSS classes to reverse-engineer selectors |

**Automatic on boot**: `docker compose up` runs `seed-crawler` before
`backend` starts (`depends_on: condition: service_completed_successfully`).
It skips crawling entirely if `price_references` already has rows, and
otherwise seeds from the committed
`backend/app/agent/output/crawled_restaurants_cache.json` snapshot instead
of hitting ShopeeFood live — keeps builds fast and network-independent.
Delete that file, or set `FORCE_LIVE_CRAWL=1`, to force a fresh live crawl
(re-writes the cache on success). A crawl failure never blocks the stack:
the seeder always exits 0, leaving `price_references` empty and
`estimate_fair_price()` falling back to an LLM-only prior (`n=0`).

```bash
# manual re-run
docker compose run --rm seed-crawler

# fast local test: fewer listing pages -> fewer restaurants discovered
CRAWL_MAX_PAGES=1 docker compose run --rm seed-crawler

# inspect crawl output as JSON instead of writing to Postgres
docker compose --profile playwright-full run --rm playwright-full-crawler
```

Business-existence/reputation data for module 2.2 (ghost-tour detector)
still has no crawler — `check_business_existence` depends on
`GOOGLE_PLACES_API_KEY` being set and calls the live Google Places API
per-request rather than a seeded table.

**Known issue**: an earlier crawler run under the old root-only backend
image left `test/output/` root-owned, which will block new writes with a
`PermissionError`. Fix once with:
```bash
sudo chown -R $USER:$USER test/output
```
