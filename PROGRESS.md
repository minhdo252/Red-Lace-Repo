# PROGRESS — NónAI integration (living status)

> Read **[IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)** for the full plan. This file is the
> **where-are-we-now** log. It is updated and pushed at every checkpoint so any machine/account
> can pull and continue exactly where the last one stopped.

**Last updated:** 2026-07-18 · **Overall:** Phases 0–5 done — Phase 3 feature wiring complete (Home, SOS, Translate, Tour-check, Price-check, Profile country picker) + Phase 4 docs + **Phase 5 pushed** (all Phase 0–4 commits verified on `origin/main`, remote `main` == local `37bbddf`). `tsc --noEmit` clean; local Turbopack `npm run build` is blocked by the `node_modules` junction (builds clean on Vercel). **Phase 6 (deploy) is BLOCKED on two owner-only prerequisites** (see Blockers): interactive `railway login` (this session can't drive a browser OAuth) **and** the private FPT/Gemini/Tavily API keys (not present on this machine — `backend/.env` is absent). No Railway URL exists yet, so `BACKEND_URL` can't be set on Vercel. Nothing is deployed.

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
- [ ] **Phase 6 — Deploy** — **BLOCKED, needs the account owner** (see Blockers). Backend → Railway
      requires interactive `railway login` + the private FPT/Gemini/Tavily keys (neither available to a
      non-interactive session with no `backend/.env`). Frontend → Vercel is otherwise ready (CLI
      authed as `minh070607`, project linked, `SERPAPI_KEY` present) but `BACKEND_URL` can't be set
      until the Railway URL exists. Nothing is deployed.

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

## Blockers / needs the account owner
Phase 6 confirmed blocked on **owner-only** prerequisites (a non-interactive assistant session cannot
clear these). Exact remediation:

1. **Interactive `railway login`.** The Railway CLI auth is a browser OAuth flow; it can't be driven
   headlessly here. On the owner's machine: `npm i -g @railway/cli` (CLI isn't installed), then
   `railway login` (or `railway login --browserless` and open the printed URL). Alternatively, create
   a project token in the Railway dashboard and export `RAILWAY_TOKEN` for CI-style non-interactive use.
2. **Private API keys are not on this machine.** `backend/.env` is absent and no FPT Cloud / Gemini /
   Tavily key material exists locally, so `AI_MODE=live` can't be configured from here. The owner must
   supply the values and set the Railway env vars using **both** the split + legacy names (plan
   finding #2 table): `AI_CHAT_API_KEY`+`GLM_API_KEY`, `AI_VISION_API_KEY`+`QWEN_VL_API_KEY`,
   `AI_EMBED_API_KEY`+`VN_EMBEDDING_API_KEY`, `AI_STT_API_KEY`+`WHISPER_V3_API_KEY`, plus
   `GEMINI_API_KEY`, `TAVILY_API_KEY`, and `AI_MODE=live`,
   `AI_BASE_URL=https://mkp-api.fptcloud.com`, `POSTGRES_DSN`, `QDRANT_URL`, `EMBEDDING_DIM=1024`,
   `MOCK_GOOGLE_PLACES=true`.
3. **`psql` isn't installed** for the one-time schema load (`psql "$DATABASE_URL" -f db/init.sql`).
   Install `psql`, or run it via `railway run psql ...`, or use the Railway Postgres data console.
4. **Seed jobs** (`python -m app.agent.seed_scam_patterns`, `python -m app.agent.seed_price_references`)
   run once against the deployed DB/Qdrant after the backend deps are installed (Docker/Railway env).
5. **Vercel is ready except `BACKEND_URL`.** CLI is authed (`minh070607`), `frontend/.vercel` is linked
   to `nonai` (`prj_nHImfGpuP8LHiiAVmvlMXKS9mH9I` / `team_cdmOkWuR97A5rxthTxrn8VaE`), and `SERPAPI_KEY`
   is set locally. Once the Railway URL exists: set `BACKEND_URL` (Production + Preview) + `SERPAPI_KEY`,
   then `cd frontend && npx vercel --prod --yes --scope mdsat-s-projects`. Note the live
   `nonai-three.vercel.app` currently serves the **pre-integration** frontend; this deploy ships the
   integration build (works on mock when `BACKEND_URL` is unset).

## Change log
- 2026-07-18: Repo cloned; frontend moved into `frontend/`; plan + progress docs written; first push.
- 2026-07-18: Phase 1 — added `backend/app/ai/glm_chat.py` (unblocks live chat + critic).
- 2026-07-18: Phase 2 — frontend integration layer (proxy routes + api client + session context + geolocation); `tsc --noEmit` clean.
- 2026-07-18: Phase 3 (partial) — wired Home chat, SOS, Translate, Tour-check to the backend (mock fallback intact); `tsc --noEmit` clean. **Remaining: price-check, profile country picker** (recipes above), then Phase 4 docs + Phase 6 deploy.
- 2026-07-18: Phase 3 — wired **price-check** (receipt photo → `/api/chat` receipt mode; backend `reply` + `normalized_prices_vnd`, mock gauge/`PriceTable` fallback); `tsc --noEmit` clean. Remaining: profile country picker.
- 2026-07-18: Phase 3 — wired **profile country picker** (`BottomSheet` over `COUNTRIES` → `setCountry`, mirrors `LanguageSwitcher`); **Phase 3 feature wiring complete**; `tsc --noEmit` clean. Next: Phase 4 docs.
- 2026-07-18: Phase 4 — docs: top-level `README.md` now documents the monorepo + frontend↔backend integration + run steps (`.env.example` already complete from Phase 2). `tsc --noEmit` clean; local `npm run build` blocked by the `node_modules` junction under Turbopack (builds clean on Vercel). Deploy (Phases 5–6) deferred to the account owner.
- 2026-07-18: Phase 5 — **verified** all Phase 0–4 commits are on `origin/main` (remote `main` == local `37bbddf`; the local tracking ref was stale, showing a false "ahead 9"). Phase 5 ticked. **Phase 6 (deploy) confirmed BLOCKED on owner-only prerequisites** — interactive `railway login` (non-interactive session can't drive browser OAuth) + the private FPT/Gemini/Tavily keys (no `backend/.env` on this machine); `railway`/`psql` also not installed. Frontend/Vercel is ready except `BACKEND_URL` (no Railway URL yet). Full remediation added to Blockers. Nothing deployed.
