# PROGRESS — NónAI integration (living status)

> Read **[IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)** for the full plan. This file is the
> **where-are-we-now** log. It is updated and pushed at every checkpoint so any machine/account
> can pull and continue exactly where the last one stopped.

**Last updated:** 2026-07-18 · **Overall:** **ALL PHASES DONE — DEPLOYED & LIVE.** Phases 0–4 (integration) + Phase 5 (pushed) + **Phase 6 (deploy) complete**. Backend is live on **Railway** with real AI (`AI_MODE=live`, GLM-5.2 + Qwen-VL + Whisper + VN-embedding via FPT Cloud), Postgres, and Qdrant; frontend is live on **Vercel** wired to it through `BACKEND_URL`.
> - **Frontend (production):** https://nonai-three.vercel.app
> - **Backend (Railway):** https://nonai-backend-production.up.railway.app  (`/health` → `{"status":"ok"}`)
>
> Verified end-to-end on the live site: `POST /api/session` → real UUID (`source:"backend"`); `POST /api/chat` → real GLM reply (`source:"backend"`); `POST /api/sos` → 6 prioritized hotlines + correct embassy (`source:"backend"`); `GET /api/nearby` → `source:"serpapi"`. With `BACKEND_URL` unset every screen still falls back to mock.

## Status by phase
- [x] **Phase 0 — Monorepo setup**
  - [x] Cloned `Red-Lace-Repo` (backend) to an ASCII path locally.
  - [x] Moved the finished frontend (`nonai/`) into this repo as **`frontend/`** (excluded
        `node_modules`, `.next`; `.env.local` + `.vercel` are present locally but gitignored).
  - [x] Wrote `IMPLEMENTATION_PLAN.md` + this `PROGRESS.md`.
  - [ ] First push to GitHub (this checkpoint).
- [x] **Phase 1 — Backend unblock**: created `backend/app/ai/glm_chat.py` (GLM-5.2 OpenAI-compatible
      chat + tool-calling; `glm_chat()` + `has_api_key()`). Matches the `client.py` / `critic.py`
      call sites; `py_compile` clean. Full runtime import validates on Railway (deps not installed locally).
- [x] **Phase 2 — Frontend integration layer** (typechecks clean, `tsc --noEmit` = 0):
      `frontend/src/lib/backend.ts` (server helper), proxy routes `/api/session` + `/api/chat`
      (text/audio/images, self-heals session on 404) + `/api/sos`, `frontend/src/lib/api.ts`
      (fetch wrappers, `localeToNativeLanguage`/`localeToNationality`, `toAssistantMessage`/
      `toTranslateTurn` mappers, base64 helpers), `sessionId` + `ensureSession` in
      `i18n/index.tsx` (+ locale-derived nationality default), `useGeolocation` in `lib/hooks.ts`,
      `frontend/.env.example`. Profile country picker lands with Phase 3.
- [x] **Phase 3 — Feature wiring** (mock stays as the fallback everywhere; all typecheck clean):
  - [x] Home chat — text + real MediaRecorder voice + photo scan → `/api/chat` (`frontend/src/app/(tabs)/home/page.tsx`)
  - [x] SOS — live prioritized hotlines + embassy + resolved location, real `tel:` dialing → `/api/sos` (`frontend/src/app/sos/page.tsx`)
  - [x] Translate — real audio per utterance → `/api/chat`, accumulates turns + summary (`frontend/src/app/translate/page.tsx`, `components/translate/TranscriptSummary.tsx`)
  - [x] Tour-check — URL → `/api/chat` (triggers `check_ghost_tour`); verdict + advice from the AI answer (`frontend/src/app/tour-check/page.tsx`)
  - [x] **Price-check** — receipt photo → `/api/chat` (images, `mode:"receipt"`); on `source==="backend"` shows the AI `reply` + `normalized_prices_vnd`, otherwise the mock gauge/`PriceTable` fallback. The analysis animation is now purely visual; the real transition is driven by the awaited turn (mirrors tour-check). FileReader is read before the loader shows so a read failure can't strand the spinner. (`frontend/src/app/price-check/page.tsx`)
  - [x] **Profile country picker** — the "Home country" row opens a `BottomSheet` listing `COUNTRIES` and calls `useApp().setCountry(c)` (mirrors `LanguageSwitcher`), so nationality (embassy/SOS) is user-chosen, not just the locale-derived default. `setCountry` already resets the session. (`frontend/src/app/(tabs)/profile/page.tsx`)
- [x] **Phase 4 — Docs + build check**: top-level `README.md` updated (monorepo layout +
      frontend↔backend integration + frontend run steps); `frontend/.env.example` already
      complete (Phase 2 — documents `BACKEND_URL`/`SERPAPI_KEY`/`NEXT_PUBLIC_GOOGLE_MAPS_KEY`).
      `backend/.env` stays local + gitignored (private FPT/Gemini/Tavily keys — see the key
      table in the plan; not created here). Verification: `cd frontend && npx tsc --noEmit`
      clean. `npm run build` (Turbopack) can't complete on this machine — the
      `frontend/node_modules` junction "points out of the filesystem root"; the real
      production build runs clean on Vercel's fresh `npm install` at deploy.
- [x] **Phase 5 — Push full integration checkpoint.** All Phase 0–4 commits are on `origin/main`
      (verified: remote `main` == local `37bbddf`; `FETCH_HEAD..HEAD` empty).
- [x] **Phase 6 — Deploy — DONE.** Backend → **Railway** (project `nonai-backend`), frontend →
      **Vercel** (`nonai`), wired via `BACKEND_URL`. See the "Deployment" section below for the full
      topology, URLs, and how to redeploy.

## API keys — status
The account owner supplied FPT Cloud keys (GLM chat, Qwen-VL vision, Whisper STT, VN embedding),
plus Gemini and Tavily. `GOOGLE_PLACES_API_KEY` is empty → use `MOCK_GOOGLE_PLACES=true`.
Keys go into `backend/.env` (gitignored) and Railway env vars — **never committed**. If you are a
new machine and don't have them, ask the account owner.

## How to continue (exact steps for the next machine)
1. `git clone` this repo (private — see git-auth note in the plan's "Working notes").
2. Read `IMPLEMENTATION_PLAN.md`, then continue at the first unchecked phase above.
3. Backend deps for import checks: Python 3.11+; `pip install -r backend/requirements.txt` (or
   just create `glm_chat.py` and validate on Railway, since a full local run needs Docker).
4. Frontend: `cd frontend && npm install && npm run dev` (works on mock data with no
   `BACKEND_URL`). Set `BACKEND_URL` in `frontend/.env.local` to point at the backend.
5. Commit + push after each phase; update this file's checkboxes + "Last updated".

## Environment notes (this Windows machine — save the next session time)
- Local clone lives at `C:\Users\ADM\Documents\RedLace\Red-Lace-Repo` (ASCII path on purpose).
  Working tree is clean — everything is committed + pushed to `main`.
- `git` is installed but **not on PATH**: prepend `C:\Program Files\Git\cmd`. The **Bash tool does
  not work** here (git-bash is a partial install) — use **PowerShell**.
- The repo is **private**; git's HTTPS transport hangs on the `gh` credential helper. Push/pull with
  the helper disabled and the token in the URL:
  `git -c credential.helper= push "https://x-access-token:$(gh auth token)@github.com/minhdo252/Red-Lace-Repo.git" HEAD:main`
  (`gh` is already logged in as `minh070607`).
- Frontend `node_modules` is a **junction** to the old `nonai` install, so `cd frontend; npx tsc --noEmit`
  works without `npm install`. If it's missing, run `npm install` in `frontend/`.
- **Docker is not installed** → the backend can't run locally; validate backend changes on Railway.

## Ready-to-paste prompt for the continuing (2nd) account
> Read `C:\Users\ADM\Documents\RedLace\Red-Lace-Repo\IMPLEMENTATION_PLAN.md` and `PROGRESS.md`.
> Continue Phase 3: wire **price-check** and add the **Profile country picker** (recipes are in
> PROGRESS.md), keeping every mock as the fallback. Typecheck with `cd frontend; npx tsc --noEmit`,
> then commit + push each to `main` and tick the boxes in PROGRESS.md. Then do Phase 4 (write
> `frontend/README` notes / top-level README). **Do NOT deploy** — the owner deploys from another
> account. Use PowerShell, and the git push command in PROGRESS.md's environment notes.

## Deployment (Phase 6 — LIVE)

**URLs**
- Frontend (Vercel `nonai`, prod): **https://nonai-three.vercel.app**
- Backend (Railway `nonai-backend`, prod): **https://nonai-backend-production.up.railway.app**

**Railway project `nonai-backend`** (workspace `minh070607's Projects`, id `4f35d7e2-6ed1-44e4-b4cb-0eb8e9749ff9`), environment `production`, three services:
- `nonai-backend` — FastAPI, built from `backend/Dockerfile`, deployed via `railway up ./backend`.
  Public domain on target port 8000; `PORT=8000` pinned (the Dockerfile now binds `${PORT:-8000}`).
- `Postgres` — Railway PostgreSQL plugin. `POSTGRES_DSN=${{Postgres.DATABASE_URL}}` (internal).
- `qdrant` — `qdrant/qdrant:latest`. `QDRANT_URL=http://qdrant.railway.internal:6333` (internal).

**Schema:** no external `psql` needed — `app/db/postgres.py::ensure_runtime_schema()` now creates the
base tables too (see the Phase 6 code commit), so the app self-bootstraps its full schema + seeds the
hotlines/embassies on first boot against a fresh managed Postgres.

**Seeds (Qdrant `scam_patterns` + Postgres `price_references`):** baked into the deploy via
`backend/railway.json` `startCommand` — they run in the background on container start (idempotent,
always exit 0, read the committed `seed_data/` + `output/crawled_restaurants_cache.json`), so they
never block the `/health` check. Re-run manually with
`railway ssh --service nonai-backend "python -m app.agent.seed_scam_patterns"` (needs a registered SSH key).

**Backend env vars set on Railway** (values held privately — set from `backend/.env`, never committed):
`AI_MODE=live`, `AI_BASE_URL=https://mkp-api.fptcloud.com`, both split + legacy key names
(`AI_CHAT_API_KEY`+`GLM_API_KEY`, `AI_VISION_API_KEY`+`QWEN_VL_API_KEY`,
`AI_EMBED_API_KEY`+`VN_EMBEDDING_API_KEY`, `AI_STT_API_KEY`+`WHISPER_V3_API_KEY`), `GEMINI_API_KEY`,
`TAVILY_API_KEY`, `EMBEDDING_DIM=1024`, `MOCK_GOOGLE_PLACES=true`, `POSTGRES_DSN`, `QDRANT_URL`, `PORT=8000`.

**Vercel `nonai`** (`prj_nHImfGpuP8LHiiAVmvlMXKS9mH9I` / `team_cdmOkWuR97A5rxthTxrn8VaE`, scope
`mdsat-s-projects`): `BACKEND_URL` set for Production + Preview = the Railway URL above; `SERPAPI_KEY`
already present. Deployed with `cd frontend && vercel --prod --yes --scope mdsat-s-projects`.

**Redeploy cheat-sheet**
- Backend: `cd backend && railway up --service nonai-backend` (or `railway redeploy --service nonai-backend`).
- Frontend: `cd frontend && vercel --prod --yes --scope mdsat-s-projects`.
- Change a backend key: `railway variables --service nonai-backend --set 'NAME=value'` then redeploy.

## Change log
- 2026-07-18: Repo cloned; frontend moved into `frontend/`; plan + progress docs written; first push.
- 2026-07-18: Phase 1 — added `backend/app/ai/glm_chat.py` (unblocks live chat + critic).
- 2026-07-18: Phase 2 — frontend integration layer (proxy routes + api client + session context + geolocation); `tsc --noEmit` clean.
- 2026-07-18: Phase 3 (partial) — wired Home chat, SOS, Translate, Tour-check to the backend (mock fallback intact); `tsc --noEmit` clean. **Remaining: price-check, profile country picker** (recipes above), then Phase 4 docs + Phase 6 deploy.
- 2026-07-18: Phase 3 — wired **price-check** (receipt photo → `/api/chat` receipt mode; backend `reply` + `normalized_prices_vnd`, mock gauge/`PriceTable` fallback); `tsc --noEmit` clean. Remaining: profile country picker.
- 2026-07-18: Phase 3 — wired **profile country picker** (`BottomSheet` over `COUNTRIES` → `setCountry`, mirrors `LanguageSwitcher`); **Phase 3 feature wiring complete**; `tsc --noEmit` clean. Next: Phase 4 docs.
- 2026-07-18: Phase 4 — docs: top-level `README.md` now documents the monorepo + frontend↔backend integration + run steps (`.env.example` already complete from Phase 2). `tsc --noEmit` clean; local `npm run build` blocked by the `node_modules` junction under Turbopack (builds clean on Vercel). Deploy (Phases 5–6) deferred to the account owner.
- 2026-07-18: Phase 5 — **verified** all Phase 0–4 commits are on `origin/main` (remote `main` == local `37bbddf`; the local tracking ref was stale, showing a false "ahead 9"). Phase 5 ticked.
- 2026-07-18: **Phase 6 — DEPLOYED.** Owner logged into Railway (interactive) and supplied the FPT/Gemini/Tavily keys → `backend/.env` (gitignored). Backend deploy fixes committed: `ensure_runtime_schema()` self-bootstraps the base tables (no external `psql`), Dockerfile binds `${PORT:-8000}`, and `backend/railway.json` runs the two seeds in the background on startup. Provisioned Railway `nonai-backend` + `Postgres` + `qdrant`, set all env vars, deployed → **https://nonai-backend-production.up.railway.app** (`/health` ok). Set `BACKEND_URL` on Vercel (Prod+Preview) and deployed the integration frontend → **https://nonai-three.vercel.app**. Verified live end-to-end: `/api/session`, `/api/chat` (real GLM), `/api/sos` (hotlines + correct embassy) all `source:"backend"`; `/api/nearby` `source:"serpapi"`. Mock fallback intact when `BACKEND_URL` is unset.
