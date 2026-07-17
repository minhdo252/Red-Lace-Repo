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

`db/init.sql` seeds `geo_regions` for Hanoi/Sapa/Hoi An only. You still need
to load `price_references`, `emergency_hotlines`, `embassies`, and the
Qdrant `item_names`/`scam_patterns` collections with real MVP data — that's
the 0-6h roadmap step in the doc, not something this scaffold can invent.

## Crawler agent

`test/crawl_google_places.py` is the first data-collection agent: it pulls
real restaurant listings (name, address, rating, review count, price level,
recent reviews) for the three MVP regions via the official Google Places
API.

```bash
# needs GOOGLE_PLACES_API_KEY set in .env
docker compose run --rm crawler
```

Output lands in `test/output/places_<region_slug>.json`, one file per
region — review before importing into Postgres.

**Why Google Places and not ShopeeFood/TripAdvisor/Grab** (the sources
named in the doc's section 2): `test/crawl_shopeefood.py` documents the
investigation — ShopeeFood is a client-rendered SPA behind an internal,
header-signed API that actively redirects automated navigation away from
listing pages; TripAdvisor and Grab are gated similarly. Places is the only
one with an official, ToS-compliant public API. Trade-off: it has no
per-dish menu pricing, so it seeds business-existence/reputation data for
module 2.2 (ghost-tour detector) — the item-level price data module 2.1
needs still has to come from manual entry + LLM synthesis, per the doc's
original fallback plan.

**Known issue**: an earlier `docker compose run --rm crawler` invocation
(before the backend `Dockerfile` was switched to a non-root user) left
`test/output/` root-owned, which will block new writes with a
`PermissionError`. Fix once with:
```bash
sudo chown -R $USER:$USER test/output
```
