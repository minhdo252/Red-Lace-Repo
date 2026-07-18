# NónAI — AITravelMate (monorepo)

Travel-safety companion for foreign tourists in **Vietnam**. This one repo holds both
halves of the app so a single `git pull` gets everything:

- **`backend/`** — FastAPI + agent (Postgres + Qdrant). Translates tourist conversations,
  parses receipts/images, flags price/scam risks, scores ghost-tour composite risk, and
  routes emergency contacts through the SOS endpoint.
- **`frontend/`** — Next.js 16 PWA ("Tourist Shield"). Talks to the backend through
  same-origin `/api/*` proxy routes and **falls back to built-in mock data whenever no
  backend is configured**, so the UI works standalone.

Structured data lives in Postgres; vector lookups live in Qdrant; all main model calls go
through the single `AIClient` gateway which is explicitly configured for different
modalities (Chat, Vision, Embedding).

> **Integration handoff:** the full plan is in
> [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md); live status / where-to-continue is
> in [`PROGRESS.md`](./PROGRESS.md). Read those before continuing the integration.

## Monorepo layout

```
Red-Lace-Repo/
  backend/      # FastAPI + agent
  frontend/     # Next.js PWA (same-origin proxy → backend; mock fallback)
  db/           # Postgres schema + seed (db/init.sql)
  docker-compose.yml
  IMPLEMENTATION_PLAN.md   # integration plan (portable handoff)
  PROGRESS.md              # living status
```

## Frontend ↔ backend integration

The browser only ever calls relative **`/api/*`** routes on the Next.js server, which
proxy to FastAPI — so there is **no CORS** and the backend URL stays server-side. Each
proxy route reads `process.env.BACKEND_URL`; when it is unset or the backend errors, the
route returns the frontend's **mock data** (`source:"mock"`) so the deployed app never
breaks even before the backend is up.

- **Session:** the frontend bootstraps a backend session via `POST /sessions`
  (`{native_language, nationality}`) and persists the id in `localStorage`
  (`nonai.sessionId`). Nationality is locale-derived by default and user-selectable from
  the Profile country picker; changing language or country resets the session.
- **Wired features** (each keeps its mock as the fallback): Home chat (text / voice /
  photo), Translate (per-utterance audio), **Price-check** (receipt photo → receipt-mode
  parse → `reply` + normalized prices), Tour-check (URL → `check_ghost_tour`), and SOS
  (live hotlines + embassy). The Map already calls SerpApi directly.
- **Locale map:** frontend `en/vi/zh/ko/ru` → backend `native_language` `vi/en/ko/zh/ja`
  (`ru → en`; no `RU` embassy is seeded, so SOS still returns hotlines for Russian users).

### Run the frontend

```bash
cd frontend
npm install            # once (node_modules may already be linked on the dev machine)
npm run dev            # http://localhost:3000 — works on mock data with no BACKEND_URL
```

Copy `frontend/.env.example` → `frontend/.env.local` and set `BACKEND_URL` to the deployed
backend to switch every feature to live AI. Typecheck with `cd frontend && npx tsc --noEmit`.

## Stack

- `postgres` — structured rows: `sessions`, `chat_turns`, `threat_risk_state`, `sos_events`, `geo_regions`, `emergency_hotlines`, `embassies`, `price_references`.
- `qdrant` — vector collections: `item_names`, `scam_patterns`, `unmatched_reports`.
- `adminer` — Postgres UI at http://localhost:8080.
- `backend` — FastAPI app with `/sessions`, `/chat`, `/sos`, and `/health`.
- `seed-crawler` — one-shot job that seeds `price_references` before backend startup when needed.
- `seed-scam-patterns` — one-shot job that seeds Qdrant `scam_patterns` for Modules 2.1 & 2.2.
- `crawler` / `playwright-crawler` / `playwright-full-crawler` — optional profile-gated crawl/debug tools.

## Run the backend

```bash
cp .env.example .env
docker compose up --build
```

API:
- `GET /health`
- `POST /sessions` — create onboarding session.
- `POST /chat` — translate text/audio, parse images, run scam prefilter, calculate risk scores, run threat detection.
- `POST /sos` — return prioritized emergency contacts and embassy data.

## Environment & AI Config

The AI Gateway has been updated to use split keys for different models (allowing seamless routing to different providers for different capabilities).

```env
AI_MODE=live
AI_MARKETPLACE_BASE_URL=https://mkp-api.fptcloud.com

# Explicit Split Keys
AI_CHAT_API_KEY=your_chat_key
AI_VISION_API_KEY=your_vision_key
AI_EMBED_API_KEY=your_embed_key

AI_MODEL=Llama-3.3-70B-Instruct
STT_MODEL=FPT.AI-whisper-large-v3-turbo
EMBEDDING_MODEL=Vietnamese_Embedding
VISION_MODEL=Qwen2.5-VL-7B-Instruct
AI_REQUEST_TIMEOUT_SECONDS=60
EMBEDDING_DIM=1024

# Google / Gemini Setup (for Web Fallback & Places APIs)
GOOGLE_PLACES_API_KEY=your_places_key
GEMINI_API_KEY=your_gemini_key
```

## AI Gateway & Orchestrator Workflow

Main model touchpoints route through `backend/app/ai/client.py::AIClient`, which lazily initializes clients per modality.

The `orchestrator.py` agent manages a single tool-calling loop with the following flow:
1. **Upfront Image Parsing:** Any uploaded images (receipts, dish photos, or Facebook Page Transparency screenshots) are processed via `Qwen2.5-VL-7B-Instruct` *before* the model starts. The structured JSON (e.g. `detected_price_text`, `portion_cues`) is injected directly into the LLM context.
2. **Tool Iterations:** The orchestrator invokes tools (`estimate_fair_price`, `match_scam_pattern`, `check_ghost_tour`) up to 5 times.
3. **Critic Pass:** Tools labeled as `RISK_TOOLS` (which includes ghost tours and price anomalies) trigger an asynchronous Critic pass if they return a flagged risk. The Critic reviews the final draft to ensure the LLM explicitly warned the tourist.

## Module 2.1: Price Comparison & Receipt Parsing

- **Image Parsing:** Extracts text from receipts or dish photos using VLM.
- **Local kNN Search:** Embeds the item name and runs a kNN search in Qdrant against local `item_names`, guarded by a strict Similarity Gate (0.75) and Head-Phrase prefix gate (e.g. "phở bò" vs "phở gà").
- **Aggregation:** Calculates a similarity-weighted mean of surviving Postgres neighbors.
- **Web Fallback:** If local data fails, delegates a live search to `gemini-3.1-flash-lite`. The newly discovered price is returned instantly and then cached to Postgres & Qdrant in the background for future local lookups.

## Module 2.2: Ghost Tour & Homestay Scam Score

Computes a transparent composite trust score across 6 distinct signals without hallucinating unavailable data:
1. **Domain Age** (`check_domain_age`): WHOIS lookup for recently created sites.
2. **Page Transparency**: VLM parsing of Facebook Page Transparency screenshots.
3. **Business Existence** (`check_business_existence`): Google Places lookup to verify mapping.
4. **Review Burst**: Analysis of recent review clustering.
5. **Price Anomaly**: Checks if prices are unnaturally low (baiting).
6. **Scam Pattern**: Qdrant kNN search for high-pressure or manipulative text.

The system outputs a transparent breakdown showing exactly which signals contributed to a `high`/`medium`/`low` risk, ultimately rolling up to a clean `An toàn` or `Không an toàn` safety label.

## Module 3: Threat Detection and Smart SOS

- Threat detection runs inside `/chat`, computing physical or immediate risk (e.g. `medical_emergency`, `physical_violence`).
- The agent has *no* `trigger_sos` tool. If a threat is CRITICAL, it flips a flag for the frontend to show an SOS modal.
- `POST /sos` resolves the user's GPS (falling back to 45km radius defaults) and returns prioritized local emergency hotlines and embassy contacts.

## Data Seeding

`db/init.sql` creates runtime tables and seeds regions and hotlines.
- `seed-crawler` populates `price_references` (menus).
- `seed-scam-patterns` embeds and populates Qdrant `scam_patterns` (e.g. `ghost_tour_pressure`, `price_scam`). 

Both run automatically on startup via Docker Compose.
