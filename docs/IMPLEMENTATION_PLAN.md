# NónAI — Backend ↔ Frontend Integration Plan (portable handoff)

> **Read this first if you are picking up this work on another machine/account.**
> It is self-contained: it tells you the goal, what's already true, exactly what to build,
> and how to deploy. The live status of *how far it's gotten* is in **[PROGRESS.md](./PROGRESS.md)** —
> always read that too.

## Goal

Connect the finished **frontend** (Next.js 16 PWA "Tourist Shield" for foreign tourists in
Vietnam) to the real **backend** (this repo's FastAPI + Postgres + Qdrant service), so every
feature works against real AI instead of mock data. Then deploy: backend → **Railway**,
frontend → **Vercel**. Everything lives in this one repo (monorepo) so a single `git pull`
gets it all.

```
Red-Lace-Repo/
  backend/      # FastAPI + agent (existed before this work)
  frontend/     # Next.js app (was the separate `nonai/` folder; moved in here)
  db/           # Postgres schema + seed (db/init.sql)
  docker-compose.yml
  IMPLEMENTATION_PLAN.md   <- this file
  PROGRESS.md              <- living status / where to continue
```

## Architecture of the integration

Client → **same-origin Next.js proxy route** → FastAPI backend. This mirrors the one real
network call the frontend already had (`frontend/src/app/api/nearby/route.ts` → SerpApi):
the browser only ever calls relative `/api/*`, so there is **no CORS** and the backend URL
stays server-side. Every proxy route reads `process.env.BACKEND_URL`; when it is unset or the
backend errors, the route **falls back to the existing mock data** — so the deployed frontend
never breaks even before the backend is up.

Backend endpoints (see `backend/app/routers/`, `backend/app/schemas/chat.py`):
- `POST /sessions` `{native_language, nationality}` → `{session_id}` (UUID; required by all
  chat/sos calls).
- `POST /chat` — `{session_id, text | audio_base64, images[], speaker_role, lat, lon, region,
  history}` → `ChatResponse`.
- `POST /chat/text` — typed convenience variant of `/chat`.
- `POST /sos` — `{session_id, lat, lon, region, nationality, threat_category, threat_level,
  source}` → `{contacts[], location_text_vi/en, resolved_region}`.
- `GET /health`, `GET /ready`.

`ChatResponse` fields used by the UI: `reply`, `translation`, `translation_details`,
`scam_flags[]`, `threat`, `tools_invoked[]`, `normalized_prices_vnd[]`, `resolved_region`,
`degraded_components[]`.

## Key findings (why the work is shaped this way)

1. **Backend blocker — `backend/app/ai/glm_chat.py` was MISSING** but is imported by
   `backend/app/ai/client.py::chat()` (the `AI_MODE=live` path) and
   `backend/app/agent/critic.py`. Without it, live chat + the critic pass crash with
   `ImportError`. **It must be created.** Contract (from the two call sites):
   - `glm_chat(messages, tools=None, response_format=None, temperature=0.2, max_tokens=2048)`
     — **blocking/sync** (callers wrap in `asyncio.to_thread`). Returns an object with
     `.content: str|None`, `.reasoning: str|None`, `.tool_calls: list` (each item has `.id`,
     `.name`, `.arguments: dict`).
   - `has_api_key() -> bool`.
   - Implement with the OpenAI SDK (already in `requirements.txt`) against
     `settings.ai_base_url` (`https://mkp-api.fptcloud.com`), key =
     `settings.ai_chat_api_key or settings.glm_api_key`, model `settings.ai_chat_model`
     (`GLM-5.2`). Read `message.content`, `message.reasoning_content`, and
     `message.tool_calls[].function.{name, arguments}`.

2. **AI key wiring** (`backend/app/ai/client.py` + repo `CLAUDE.md`): split clients fall back to
   legacy env names, and the "real" modules (`qwen_vl.py`, `vn_embedding.py`,
   `utils/gemini_search.py`) read their own keys straight from `os.environ`. So `backend/.env`
   sets **both** the split and legacy names:
   | Capability | env names (set both) | model |
   |---|---|---|
   | Chat | `AI_CHAT_API_KEY`, `GLM_API_KEY` | `AI_CHAT_MODEL=GLM-5.2` |
   | Vision | `AI_VISION_API_KEY`, `QWEN_VL_API_KEY` | `Qwen2.5-VL-7B-Instruct` |
   | Embed | `AI_EMBED_API_KEY`, `VN_EMBEDDING_API_KEY` | `Vietnamese_Embedding`, `EMBEDDING_DIM=1024` |
   | STT | `AI_STT_API_KEY`, `WHISPER_V3_API_KEY` | `FPT.AI-whisper-large-v3-turbo` |
   Plus `GEMINI_API_KEY`, `TAVILY_API_KEY` (os.environ), `AI_MODE=live`,
   `AI_BASE_URL=https://mkp-api.fptcloud.com`. `GOOGLE_PLACES_API_KEY` is empty → set
   `MOCK_GOOGLE_PLACES=true` so business-existence checks degrade cleanly. **All key values are
   held privately (backend/.env locally + Railway vars) and are NEVER committed** — `.env` is
   gitignored.

3. **Frontend had no `session_id`.** Must bootstrap one via `POST /sessions` and persist it
   (localStorage `nonai.sessionId`, alongside the existing `nonai.*` keys in
   `frontend/src/i18n/index.tsx`).

4. **Nationality was never captured** — `country` in `frontend/src/i18n/index.tsx` defaults to
   `KR` and `setCountry` is never called. Fix: derive a default from the chosen language
   (`ko→KR, zh→CN, en→US, vi→VN, ru→RU`) **and** add a small country picker in Profile. No
   onboarding redesign (the design is locked/final).

5. **Locale mismatch** — frontend locales `en/vi/zh/ko/ru`; backend `native_language` accepts
   `vi/en/ko/zh/ja`. Map `ru → en` (backend has no `ru`); note **no `RU` embassy is seeded**
   (`db/init.sql` seeds KR/CN/US/GB/AU/JP/SG/TW) — SOS still returns hotlines, just no embassy
   card for RU. Graceful, documented.

6. **Integration seam already anticipated**: `frontend/src/mocks/types.ts` domain types
   (`AssistantMessage`, `TranslateTurn`, `PriceAnalysis`, `Hotline`, …) are the exact target
   shapes to map responses into. Identity/localStorage convention = the `nonai.*` keys.

## What to build

**Backend**
- Create `backend/app/ai/glm_chat.py` (contract in finding #1).

**Frontend integration layer**
- `frontend/src/lib/api.ts` — typed client (`createSession`, `sendChat`, `requestSos`) + mappers
  (`localeToNativeLanguage`, `localeToNationality`, `toAssistantMessage`, `toTranslateTurns`,
  `toPriceAnalysis`).
- Proxy routes (`export const runtime = "nodejs"`, POST; read `process.env.BACKEND_URL`; mock
  fallback): `frontend/src/app/api/session/route.ts`, `.../api/chat/route.ts` (text + audio +
  images), `.../api/sos/route.ts`.
- Session identity: extend `LanguageProvider` in `frontend/src/i18n/index.tsx` with `sessionId`
  (+ `nonai.sessionId`), real `setCountry` usage, and a locale→nationality default.
- `useGeolocation` hook in `frontend/src/lib/hooks.ts` (factor out the `navigator.geolocation`
  logic currently duplicated in the two map components).

**Feature wiring** (replace the mock body, keep the component + animations; mock stays as fallback):
| Feature | File | Replace | Call |
|---|---|---|---|
| Home text | `frontend/src/app/(tabs)/home/page.tsx` `onSend` | `routeThread()` | `/api/chat` (text) → `toAssistantMessage` |
| Home voice | `home/page.tsx` `onMic` | fake listen + `taxiThread` | MediaRecorder→base64 → `/api/chat` (audio) |
| Home photo | `home/page.tsx` `onPickPhoto` | `photoScanReply` | FileReader→base64 → `/api/chat` (images) |
| Translate | `frontend/src/app/translate/page.tsx` `stop()` | `conversation`+`summary` | MediaRecorder→base64 → `/api/chat` → `toTranslateTurns` (pass summary as a prop to `TranscriptSummary`) |
| Price-check | `frontend/src/app/price-check/page.tsx` `onFile` | `receiptAnalysis` | FileReader→base64 → `/api/chat` (images) → `toPriceAnalysis` |
| Tour-check | `frontend/src/app/tour-check/page.tsx` | static result | `/api/chat` text/url (triggers `check_ghost_tour`) |
| SOS | `frontend/src/app/sos/page.tsx` | static `hotlines` + `country.embassy` | `/api/sos` → `contacts[]`, embassy card, `location_text_*` |
| Map | `frontend/src/app/api/nearby/route.ts` | — | leave as-is (already real) |

**Threat→SOS**: `/chat` returns a `threat` block; when `threat.level` is HIGH/CRITICAL, surface
the existing `ScamBanner` (`frontend/src/components/translate/ScamBanner.tsx`) / an SOS prompt
whose action routes to the SOS screen. `trigger_sos` is deliberately NOT an agent tool — the
emergency call always needs a user tap.

## Deploy recipe

**Backend → Railway** (Docker isn't needed locally; Railway builds the image in the cloud):
1. New Railway project from this GitHub repo; service root directory = `backend/`, build with
   `backend/Dockerfile`.
2. Add a **Postgres** plugin. After it's up, run the schema once:
   `psql "$DATABASE_URL" -f db/init.sql` (seeds regions, hotlines, embassies).
3. Add a **Qdrant** service (image `qdrant/qdrant:latest`, expose 6333).
4. Set env vars on the backend service: `AI_MODE=live`, `AI_BASE_URL=https://mkp-api.fptcloud.com`,
   `POSTGRES_DSN` (= Railway Postgres URL), `QDRANT_URL` (= internal Qdrant URL), `EMBEDDING_DIM=1024`,
   `MOCK_GOOGLE_PLACES=true`, and all AI keys from finding #2.
5. Seed Qdrant + prices once (one-off jobs against the deployed DB/Qdrant):
   `python -m app.agent.seed_scam_patterns` and `python -m app.agent.seed_price_references`
   (the latter reads the committed `backend/app/agent/output/crawled_restaurants_cache.json`).
6. Verify: `GET https://<railway-url>/health` → `{"status":"ok"}`.
> Railway CLI login (`railway login`) is interactive — the account owner must do it.

**Frontend → Vercel** (existing project `nonai`, projectId `prj_nHImfGpuP8LHiiAVmvlMXKS9mH9I`,
orgId `team_cdmOkWuR97A5rxthTxrn8VaE`, scope `mdsat-s-projects`):
1. Set `BACKEND_URL` = the Railway URL (Production + Preview).
2. `cd frontend && npx vercel --prod --yes --scope mdsat-s-projects`.
3. `.vercel` is gitignored; on a fresh machine run `cd frontend && npx vercel link` and pick the
   project above. Also set `SERPAPI_KEY` (existing, for the map).

## Verification (end-to-end)
- Backend imports: from `backend/`, `python -c "import app.ai.glm_chat, app.agent.critic"`.
- Deployed: `/health` ok; `POST /sessions` → UUID; `POST /chat/text` with that id → non-empty
  `reply`; `POST /sos` with that id → `contacts[]`.
- Frontend build/typecheck: `cd frontend && npm install && npm run build`.
- With `BACKEND_URL` set + backend up: onboarding → home chat returns a real reply; translate
  transcribes real audio; price-check reads a real receipt; SOS lists real hotlines + the right
  embassy; map still returns `source:"serpapi"`. With `BACKEND_URL` unset: every screen still
  works on mock fallback.

## Known gaps / risks (documented, not blockers)
- `ru` locale → `native_language=en`; no `RU` embassy seeded (SOS still returns hotlines).
- Backend can't be run locally without Docker; first true end-to-end test is on Railway.
- Railway login and (if needed) a Vercel token are interactive — deploy needs the account owner.
- `threat_category`/`threat_level` come from the `/chat` response, not invented client-side.

## Working notes for whoever continues
- **git auth in this environment**: the repo is private; git's HTTPS transport hangs on the `gh`
  credential helper. Clone/push with the helper disabled and the token in the URL:
  `git -c credential.helper= push "https://x-access-token:$(gh auth token)@github.com/minhdo252/Red-Lace-Repo.git" HEAD:main`
  (then `git remote set-url origin https://github.com/minhdo252/Red-Lace-Repo.git` to keep the
  stored remote clean).
- Frontend was developed under a non-ASCII parent folder; this monorepo lives at an ASCII path to
  avoid tooling issues.
