# PROGRESS — NónAI integration (living status)

> Read **[IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)** for the full plan. This file is the
> **where-are-we-now** log. It is updated and pushed at every checkpoint so any machine/account
> can pull and continue exactly where the last one stopped.

**Last updated:** 2026-07-18 · **Overall:** Phases 0–2 done. Phase 3 IN PROGRESS — Home, SOS, Translate, Tour-check wired ✅ (typechecks clean); **Price-check + Profile country picker REMAINING**. Deploy (Phase 6) not started.

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
- [~] **Phase 3 — Feature wiring** (mock stays as the fallback everywhere; all typecheck clean):
  - [x] Home chat — text + real MediaRecorder voice + photo scan → `/api/chat` (`frontend/src/app/(tabs)/home/page.tsx`)
  - [x] SOS — live prioritized hotlines + embassy + resolved location, real `tel:` dialing → `/api/sos` (`frontend/src/app/sos/page.tsx`)
  - [x] Translate — real audio per utterance → `/api/chat`, accumulates turns + summary (`frontend/src/app/translate/page.tsx`, `components/translate/TranscriptSummary.tsx`)
  - [x] Tour-check — URL → `/api/chat` (triggers `check_ghost_tour`); verdict + advice from the AI answer (`frontend/src/app/tour-check/page.tsx`)
  - [ ] **Price-check — NOT STARTED** (`frontend/src/app/price-check/page.tsx`). Recipe: make `onFile` async →
        `fileToBase64(f)` → `chatRequest({ session_id: await ensureSession(), native_language, nationality, images:[{image_base64, mode:"receipt"}] })`;
        on `env.source==="backend"` show `env.reply` + `normalized_prices_vnd` in the result card; keep the mock gauge/`PriceTable` as the fallback. (Home photo scan already does this AI-native path.)
  - [ ] **Profile country picker — NOT STARTED** (`frontend/src/app/(tabs)/profile/page.tsx`). Add a country selector calling `useApp().setCountry(c)` (the `COUNTRIES` list lives in `frontend/src/i18n/index.tsx`) so nationality (embassy/SOS) is user-chosen, not just the locale-derived default. `setCountry` already resets the session.
- [ ] **Phase 4 — Docs + build check**: `backend/.env` (local, gitignored), update
      `.env.example`, top-level README; `cd frontend && npm run build`.
- [ ] **Phase 5 — Push full integration checkpoint.**
- [ ] **Phase 6 — Deploy** (deferred): backend → Railway, frontend → Vercel with `BACKEND_URL`.

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
- **Railway login** is interactive → the owner runs `railway login` before Phase 6 (backend deploy).
- **Vercel**: `.vercel` link is gitignored; re-link with the project IDs in the plan, or the owner
  runs the deploy. Backend must be deployed first so `BACKEND_URL` exists.

## Change log
- 2026-07-18: Repo cloned; frontend moved into `frontend/`; plan + progress docs written; first push.
- 2026-07-18: Phase 1 — added `backend/app/ai/glm_chat.py` (unblocks live chat + critic).
- 2026-07-18: Phase 2 — frontend integration layer (proxy routes + api client + session context + geolocation); `tsc --noEmit` clean.
- 2026-07-18: Phase 3 (partial) — wired Home chat, SOS, Translate, Tour-check to the backend (mock fallback intact); `tsc --noEmit` clean. **Remaining: price-check, profile country picker** (recipes above), then Phase 4 docs + Phase 6 deploy.
