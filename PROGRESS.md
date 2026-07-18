# PROGRESS — NónAI integration (living status)

> Read **[IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)** for the full plan. This file is the
> **where-are-we-now** log. It is updated and pushed at every checkpoint so any machine/account
> can pull and continue exactly where the last one stopped.

**Last updated:** 2026-07-18 · **Overall:** Phases 0–1 complete; starting Phase 2 (frontend integration layer).

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
- [ ] **Phase 2 — Frontend integration layer**: `frontend/src/lib/api.ts`, proxy routes
      (`/api/session`, `/api/chat`, `/api/sos`), `sessionId` in `i18n/index.tsx`,
      `useGeolocation`, nationality derive + Profile picker, response mappers.
- [ ] **Phase 3 — Feature wiring**: home chat/voice/photo, translate, price-check, tour-check,
      SOS (each keeps its mock as fallback).
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

## Blockers / needs the account owner
- **Railway login** is interactive → the owner runs `railway login` before Phase 6 (backend deploy).
- **Vercel**: `.vercel` link is gitignored; re-link with the project IDs in the plan, or the owner
  runs the deploy. Backend must be deployed first so `BACKEND_URL` exists.

## Change log
- 2026-07-18: Repo cloned; frontend moved into `frontend/`; plan + progress docs written; first push.
- 2026-07-18: Phase 1 — added `backend/app/ai/glm_chat.py` (unblocks live chat + critic).
