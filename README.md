# AITravelMate (Non AI)

Backend + agent for the travel companion MVP in **Hanoi / Sapa / Hoi An**.
The app translates tourist conversations, flags price/scam risks, and routes
emergency contacts through a hardcoded SOS endpoint. Structured data lives in
Postgres; vector lookups live in Qdrant; all main model calls go through the
single `AIClient` gateway.

## Stack

- `postgres` — structured rows: `sessions`, `chat_turns`,
  `threat_risk_state`, `sos_events`, `geo_regions`, `emergency_hotlines`,
  `embassies`, `price_references`.
- `qdrant` — vector collections: `item_names`, `scam_patterns`,
  `unmatched_reports`.
- `adminer` — Postgres UI at http://localhost:8080.
- `backend` — FastAPI app with `/sessions`, `/chat`, `/sos`, and `/health`.
- `seed-crawler` — one-shot job that seeds `price_references` before backend
  startup when needed.
- `crawler` / `playwright-crawler` / `playwright-full-crawler` — optional
  profile-gated crawl/debug tools.

## Run

```bash
cp .env.example .env
docker compose up --build
```

API:

- `GET /health`
- `POST /sessions` — create onboarding session.
- `POST /chat` — translate text/audio, run scam prefilter, run threat detection.
- `POST /sos` — return prioritized emergency contacts and embassy data.

Every compose service builds its own image from `./backend`. If a dependency is
added, rebuild any sibling service you use directly, for example
`docker compose build backend seed-crawler`.

## Environment

The backend reads `.env` through Docker Compose. `docker-compose.yml` overrides
the in-container Postgres DSN and Qdrant URL so services can talk over the
Compose network.

Important defaults:

```env
AI_MODE=mock
AI_MARKETPLACE_BASE_URL=https://mkp-api.fptcloud.com
AI_API_KEY=
AI_MODEL=Llama-3.3-70B-Instruct
STT_MODEL=FPT.AI-whisper-large-v3-turbo
EMBEDDING_MODEL=Vietnamese_Embedding
VISION_MODEL=Qwen2.5-VL-7B-Instruct
AI_REQUEST_TIMEOUT_SECONDS=60
EMBEDDING_DIM=1024
GOOGLE_PLACES_API_KEY=
```

With `AI_MODE=mock`, the backend runs without external model keys. To call AI
Marketplace live, set `AI_MODE=live` and fill `AI_API_KEY`.

Standalone menu/VLM utilities may also use these optional keys:

```env
QWEN_VL_API_KEY=
WHISPER_V3_API_KEY=
VN_EMBEDDING_API_KEY=
GLM_API_KEY=
```

Those optional keys do not replace the main Module 1/3 `AIClient` flow.

## AI Gateway

Main model touchpoints are routed through `backend/app/ai/client.py::AIClient`:

- `chat()` — orchestrator, structured translation, threat context assessment.
- `transcribe()` — STT via Whisper-compatible AI Marketplace API.
- `embed()` — text embeddings for Qdrant kNN lookups.
- `vision()` — image-reading tool for receipt/dish/page/chat screenshots.

This keeps mock/live behavior centralized and prevents feature modules from
creating separate SDK clients.

## Module 1: Translation, STT, Context, Scam Signals

Module 1 is centered on `POST /chat`.

Backend behavior:

- Validates a real `session_id`.
- Accepts either `text` or `audio_base64`.
- Converts browser audio to WAV 16kHz mono before STT.
- Uses `speaker_role`, `audio_language_hint`, and region glossary for STT.
- Redacts PII before model/scam/threat processing.
- Loads server-side chat history from `chat_turns`.
- Runs deterministic structured translation in parallel with the orchestrator.
- Runs Qdrant scam prefilter plus rule fallback.
- Runs threat detection and persists cumulative session risk.
- Stores response payload for chunk idempotency by `session_id + chunk_sequence_id`.

Typical request:

```json
{
  "session_id": "...",
  "text": "How much is this taxi ride?",
  "region": "Hanoi",
  "speaker_role": "tourist",
  "chunk_sequence_id": 1,
  "is_final_chunk": true
}
```

Important response fields:

- `source_text`
- `translation`
- `translation_details`
- `scam_flags`
- `scam_prefilter_status`
- `threat`
- `chunk_sequence_id`
- `resolved_region`
- `server_turn_id`

## Module 3: Threat Detection and Smart SOS

Threat detection runs inside `/chat`, while emergency contact lookup is isolated
in `POST /sos`.

Safety invariant:

- The agent has no `trigger_sos` tool.
- `/sos` is only called by frontend/user action.
- Backend returns contacts and location text; it never places a phone call.

`/chat` may return:

```json
{
  "threat": {
    "final_level": "CRITICAL",
    "show_sos_button": true,
    "auto_open_sos_modal": true,
    "primary_threat_category": "physical_violence",
    "sos_reason": "CRITICAL: physical_violence"
  }
}
```

Frontend should then open an SOS modal and call `/sos` only after explicit user
confirmation.

Typical `/sos` request:

```json
{
  "session_id": "...",
  "lat": 22.336,
  "lon": 103.843,
  "threat_category": "medical_emergency",
  "threat_level": "CRITICAL",
  "source": "smart_trigger",
  "idempotency_key": "sos-unique-key"
}
```

Backend behavior:

- Validates the session.
- Resolves GPS to `Hanoi`, `Sapa`, or `Hoi An` when possible.
- Falls back to national `Vietnam` hotlines if GPS cannot resolve.
- Gets nationality from request or session.
- Sorts contacts by `threat_category`.
- Adds embassy data when available.
- Logs `sos_events`.
- Replays existing response for duplicate `idempotency_key`.
- Soft rate-limits repeated SOS calls in a short window.

Important response fields:

- `contacts`
- `location_text_vi`
- `location_text_en`
- `resolved_region`
- `region_fallback_used`
- `event_id`
- `rate_limited`

## API Quickstart

Create session:

```bash
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"native_language":"ko","nationality":"KR"}'
```

Chat:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "<SESSION_ID>",
    "text": "help me, he has a knife",
    "lat": 22.336,
    "lon": 103.843,
    "speaker_role": "tourist",
    "chunk_sequence_id": 1
  }'
```

SOS:

```bash
curl -X POST http://localhost:8000/sos \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "<SESSION_ID>",
    "lat": 22.336,
    "lon": 103.843,
    "threat_category": "medical_emergency",
    "threat_level": "CRITICAL",
    "source": "smart_trigger",
    "idempotency_key": "test-sos-001"
  }'
```

## Data Seeding

`db/init.sql` creates runtime tables and seeds:

- `geo_regions` for Hanoi/Sapa/Hoi An.
- national and city-level emergency hotlines.
- embassy contacts for MVP nationalities.
- `price_references` schema.

The `seed-crawler` service populates `price_references` when the table is
empty. Qdrant `item_names` and `scam_patterns` still need real MVP vector data
for highest quality. If `scam_patterns` is empty or Qdrant is degraded, `/chat`
still returns rule fallback results and `scam_prefilter_status` so the UI can
show degraded-state behavior instead of silently assuming no risk.

## Crawler Agents

ShopeeFood listing pages are client-rendered, but restaurant menu pages render
with Playwright. The crawler stack is retained for price reference data.

Useful files:

- `backend/app/utils/menu_extract.py`
- `backend/app/utils/menu_normalize.py`
- `backend/app/tools/crawl_shopeefood_full.py`
- `backend/app/agent/seed_price_references.py`
- `test/crawl_menu_dom_explorer.py`

Manual runs:

```bash
docker compose run --rm seed-crawler
CRAWL_MAX_PAGES=1 docker compose run --rm seed-crawler
docker compose --profile playwright-full run --rm playwright-full-crawler
```

## Frontend Integration Docs

Detailed Module 1/3 frontend contract lives in:

```txt
MODULE_1_3_FRONTEND_INTEGRATION.md
```

It covers request/response shapes, TypeScript fetch helpers, audio base64
handling, smart SOS modal behavior, and frontend checklists.

## Known Notes

- Local host audio decoding needs `ffmpeg` in PATH if running outside Docker.
  The backend Docker image installs `ffmpeg`.
- `EMBEDDING_DIM` must stay `1024` for `Vietnamese_Embedding`. If a Qdrant
  collection was created with the wrong dimension, delete and recreate it.
- A crawler run under an old root-owned image can leave `test/output/`
  unwritable; fix once with `sudo chown -R $USER:$USER test/output` on Linux.
