# AI COLLAB LOG — NónAI (AITravelMate)

> A log of the **human ↔ Claude (Claude Code)** collaboration that built NónAI over the
> **Jul 17–19, 2026** sprint. This is the "how we worked with the AI" record — a companion to
> [PROGRESS.md](PROGRESS.md) (where-are-we-now) and [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
> (the plan). It is **reconstructed from the session's commit history and its planning docs**
> ([plan.md](plan.md), [PROGRESS.md](PROGRESS.md)), not from a saved chat transcript, so each entry
> is anchored to the artifacts it produced (commits + files) rather than to verbatim prompts.

**Sprint at a glance**

| Day | Theme | Commits | Churn |
|-----|-------|:-------:|-------|
| Jul 17 | Infra scaffold — Docker, orchestrator, crawler, Qwen-VL OCR | 6 | +20.4k / −1.3k |
| Jul 18 | Modules 1/2.1/2.2/3 integrated, frontend wired, **deployed live** | 26 | +25.7k / −1.2k |
| Jul 19 | Live-fix pass — voice price scam, ghost-tour URLs, deploy, UX tone | 12 | +0.4k / −39 |

Working model throughout: **plan-first, verify-before-claim.** The human set direction and supplied
the private FPT Cloud / Gemini / Tavily keys; Claude drafted plans into `plan.md` / `PROGRESS.md`,
implemented against them, and gated "done" on `py_compile` + standalone smoke scripts (full runtime
lives in Docker/Railway CI — deps aren't installed on the local box).

---

## Session 1 — Jul 17 · Infra scaffold from the 48h-MVP doc

**Goal (human):** stand up the backend skeleton described in `NON_AI~1.MD` — a FastAPI app + single
orchestrator agent that boots and is fully testable with **no API key** (`AI_MODE=mock`).

**Built (Claude):**
- `a0d2cdd` / `c228ee8` — Docker Compose stack (API :8000, Adminer :8080, Postgres, Qdrant) and the
  **single orchestrator + tool-calling** loop: [backend/app/agent/orchestrator.py](../backend/app/agent/orchestrator.py)
  (`handle_turn`, `MAX_TOOL_ITERATIONS = 5`) with the 6 tool specs in
  [backend/app/agent/tools.py](../backend/app/agent/tools.py).
- `85d6d08` / `12f10c2` — the ShopeeFood seed-crawler (Playwright) + the shared Playwright backend
  image, and README/plan docs for the crawl pipeline.
- `a6bd3db` — Qwen2.5-VL menu-photo OCR pipeline ([backend/app/ai/qwen_vl.py](../backend/app/ai/qwen_vl.py))
  plus a sanity-floor guard on parsed prices.
- `031b880` — the menu→price pipeline, and a deliberate architecture call: **new AI modules read
  keys directly via `os.environ`, not through `Settings`** — migrated key reads to `getenv`.

**Key decisions locked this session:**
- **Structural SOS safety:** `trigger_sos` is intentionally *absent* from the tool set so a live model
  can never place an emergency call; `/sos` is a separate router hit on a user tap.
- **Data split:** Postgres = rows, Qdrant = vectors; a Qdrant point carries `postgres_id` and the flow
  is *kNN in Qdrant → fetch the row from Postgres*.
- **Mock-first:** the whole loop runs with canned responses so it's demoable before any key exists.

---

## Session 2 — Jul 18 · Integrate the four modules, wire the frontend, ship it live

The big day (+25.7k lines). Split into three arcs.

### 2a — Modules 1/2.1/2.2/3 into one agent
- `636650c` — integrate Module 1 (translate) + Module 3 (SOS). *(This restored
  [backend/app/ai/client.py](../backend/app/ai/client.py) as the central AI gateway; per a standing
  team note it is **not** to be deleted.)*
- `4bc76e9` → `684f9da` — Module 2.2 ghost-tour/homestay scam detector built on a branch, then
  `1a3e315` enhanced the **Gemini web-search fallback** and fixed an embedding timeout, and the branch
  was merged to `main`.
- `4b97869` / `74b082b` — architecture docs: [module_2.1_architecture.md](module_2.1_architecture.md),
  a README rewrite, and a corrected [orchestration_flow.md](orchestration_flow.md) diagram.
- `88df6c7` — upgrade both price/scam modules; `8bf70da` — **switch the chat model to GLM-5.2**.

### 2b — Monorepo + frontend integration (mock stays as the fallback everywhere)
- `292b285` / `781419a` — pull the finished Next.js frontend into `frontend/`, and add
  [backend/app/ai/glm_chat.py](../backend/app/ai/glm_chat.py) to unblock live chat + the critic gate.
- `4451698` → `854a4a9` — the frontend integration layer ([frontend/src/lib/api.ts](../frontend/src/lib/api.ts),
  proxy routes for session/chat/sos) and feature wiring: Home chat + SOS (`e58e94b`), Translate +
  Tour-check (`7b00214`), Price-check receipt mode (`f6de0a2`), Profile country picker (`854a4a9`).
- `e1a85ad` / `340ee2b` — **drop the mock/canned answers**: route `/chat` by input type and always use
  the real Qwen menu OCR (never the vision fallback). This matches the standing directive:
  *real modules on real input, graceful "try again" only on error.*
- `2216256` / `b19aded` — text price-check intent → Module 2.1; fixed live STT and the threat→SOS path;
  refined chatbot routing.

### 2c — Deploy (Phase 6)
- `1946ca5` — make the backend run on managed Postgres + bind `$PORT`.
- `823b265` — **LIVE:** backend on Railway, frontend on Vercel, wired via `BACKEND_URL`.
- `d9834d6` — seed on boot via a `start.sh` entrypoint.
- `d514cfc` — [DEPLOY.md](DEPLOY.md): a secrets-free deploy/update guide for any machine.

**Verification (recorded in [PROGRESS.md](PROGRESS.md)):** end-to-end on the live site —
`/api/session` → real UUID, `/api/chat` → real GLM reply, `/api/sos` → prioritized hotlines + correct
embassy, all `source:"backend"`; with `BACKEND_URL` unset every screen still falls back to mock.

---

## Session 3 — Jul 19 · Live-fix pass (small diffs, high leverage)

Only +0.4k lines — surgical fixes against the deployed app.

**Voice price-scam detection** (`04ea144`, planned in [plan.md](plan.md)):
- The voice route transcribed fine but only gathered translate + prefilter + threat — it **never ran
  `compare_price`**, so *"cô bán bún chả này 200k"* (+~220% over the ~62k reference) raised no flag.
- Added [backend/app/modules/transcript_price_extract.py](../backend/app/modules/transcript_price_extract.py)
  (extract `(item, price)` pairs; GLM primary with a **hallucination guard** — only accept prices that
  are in the deterministic set — and a deterministic heuristic fallback), plus `_run_voice_price_check`
  in [backend/app/routers/chat.py](../backend/app/routers/chat.py) wrapped in a 10s deadline, never-raises.
- Verified: 8/8 extraction cases pass on real code, including the spelled-out *"hai trăm nghìn"* case,
  phone-number rejection, and the LLM-price guard.

**Ghost-tour URL detection made real** (`6d4753a` / `e25c4a8`):
- Real Gemini web-reputation check ([backend/app/utils/gemini_search.py](../backend/app/utils/gemini_search.py),
  [backend/app/modules/business_check.py](../backend/app/modules/business_check.py),
  [backend/app/modules/ghost_tour_score.py](../backend/app/modules/ghost_tour_score.py)) + a dedicated route.
- Follow-up fix: **derive a business name from bare domains** so the web check always runs.

**Deploy hardening** (`ff8e7af`, `5369ce9`, `5374133`, `87be714`, `48dac04`, `38e7f11`):
- A cluster of Railway build fights — RAILPACK didn't have `uvicorn` on `PATH`, so boot via
  `python -m uvicorn`; force the Dockerfile builder; skip the Playwright chromium download in the
  backend image (backend needs no browser). Classic ship-it iteration.

**UX tone fix** (`4b06e0a` / `c1f6605`):
- Overpricing was reading as "scam." Reframed it as a calm **"Price looks high"** caution across the
  Translate flow and assistant reply ([frontend/src/lib/api.ts](../frontend/src/lib/api.ts),
  [frontend/src/components/translate/ScamBanner.tsx](../frontend/src/components/translate/ScamBanner.tsx)) —
  a human judgment call Claude implemented: *high price ≠ fraud.*

---

## How the collaboration ran (patterns worth keeping)

- **Plan-first.** Non-trivial work started as a written plan ([plan.md](plan.md),
  [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)) with an explicit trace, changed-files list, and a
  risks section — so any machine/account could pull and continue mid-task.
- **Verify-before-claim.** "Done" meant `py_compile` clean + standalone asyncio smoke scripts under
  `test/` passing; full runtime is asserted in Docker/Railway CI, never faked locally.
- **Mock → live migration.** The stack was demoable on `AI_MODE=mock` from day one, then mocks were
  deliberately torn out (`e1a85ad`, `340ee2b`) once real providers (GLM-5.2, Qwen-VL, FPT Whisper,
  VN embedding, Gemini) were wired — per the human's standing "no mock, real input" directive.
- **Human owns the calls Claude can't make:** provided the private keys, chose the deploy targets, and
  made product judgments (overprice = caution, not scam). Claude carried the implementation and docs.
- **Structural safety over prompt safety:** emergency dialing was kept out of the model's reach by
  architecture, not by instruction.

*Anchored to commits `a0d2cdd … c1f6605`. Update this log at the end of each working session.*
