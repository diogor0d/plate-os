# AGENTS.md — PlateOS Context for Agents

**Last updated:** 2026-08-21 (Europe/Lisbon)
**Maintainer rule:** any agent (or human) that changes the architecture, stack, schema, conventions, or completes a roadmap phase MUST (a) update this file in the same change and (b) record the reasoning in a new dated file under `docs/decisions/`. Never rewrite decision history — supersede it.

---

## 1. What PlateOS is

PlateOS is a **mobile-first, self-hosted PWA for daily nutrition tracking and body recomposition**, built for a single user (Diogo) on an iOS-first device. It removes tracking friction with three input paths:

1. **Barcode scan** → Open Food Facts lookup (server-cached in Postgres)
2. **Label photo** → Vision LLM extracts the nutrition table
3. **Freeform text** → conversational AI coach parses the meal ("1.5 cans of drained tuna with 100g pasta")

Everything funnels through an **editable Proposal Card** that the user confirms before anything touches the database.

**User & hosting context:** homelab deployment, Docker-only on servers (decision D17), TLS terminates at an existing reverse proxy. Privacy matters: the LLM backend is env-swappable so inference can stay fully local via Ollama.

## 2. Non-negotiable invariants

These are product laws, not preferences. If a change violates one, stop and reconsider:

1. **LLM extracts; the app computes.** The LLM returns raw reference values (per 100g or per serving, with an explicit `basis`) and never does arithmetic. All scaling lives in `backend/app/services/nutrition.py` and its client mirror `frontend/src/lib/nutrition.ts` — **keep these two in sync** (same fields `calories, protein_g, carbs_g, fat_g, fiber_g`, same 1-decimal rounding). `POST /api/meal-logs` always recomputes totals server-side from density × quantity; client-sent totals are ignored.
2. **Zero silent database mutations.** Vision parsing and chat return *proposals* only (`LogProposalResponse`). Persistence happens exclusively via explicit `POST /api/meal-logs` after user confirmation (the Proposal Card). Never add a code path where an LLM response writes to `meal_logs` directly.
3. **Client-side image downscaling.** Every image is canvas-downscaled to ≤1280px longest edge, WebP (JPEG fallback) q=0.7 (~150KB) in `frontend/src/lib/image.ts` before hitting the network. Label capture uses `<input type="file" capture="environment">` for focus quality on small text.
4. **Offline-first.** Failed meal-log POSTs queue in IndexedDB (Dexie) and flush on reconnect; the SPA shell precaches via Workbox. New features must not assume connectivity.
5. **Server-side = containers only.** Anything that runs on a server runs in Docker (compose services: `db`, `api`, `web`). Dev tooling (venv, node) lives on workstations only.
6. **Timezone-correct rollups.** Daily budgets group by the user's local midnight (`user_profile.timezone`, IANA, via `zoneinfo`), never UTC `date_trunc`. All new aggregation code must use `day_bounds()` in `backend/app/api/routes/meals.py`.

## 3. Architecture

```
┌────────────────────────────────────────────────────┐
│        Client — iOS PWA (Vite + React 19 SPA)      │
│  Tailwind v4 · @zxing/browser · Dexie queue        │
│  canvas downscale ≤1280px WebP 0.7 · Workbox SW    │
└───────────────┬────────────────────▲───────────────┘
                │ REST + SSE (HTTPS via external proxy)
┌───────────────▼────────────────────┴───────────────┐
│          web (Caddy :8080) — static SPA + /api/*   │
│                    reverse_proxy (SSE flush)       │
└───────────────┬────────────────────────────────────┘
┌───────────────▼────────────────────────────────────┐
│       api — FastAPI (Python 3.12, uvicorn)         │
│  nutrition math · LLM gateway (OpenAI-compatible)  │
│  OFF lookup+cache · HMAC cookie auth · SSE chat    │
└──────┬──────────────────────────┬──────────────────┘
┌──────▼──────────┐    ┌──────────▼──────────────────┐
│ db — Postgres 17│    │ LLM: OpenAI / Gemini-compat │
│ (no Timescale)  │    │ / Ollama — env-selected     │
└─────────────────┘    └─────────────────────────────┘
```

**Stack** (rationale and rejected alternatives: `docs/decisions/2026-08-21-initial-stack-architecture.md`):

| Layer | Choice | Decision |
| --- | --- | --- |
| Frontend | Vite 6 + React 19 SPA, TanStack Query | D2 |
| Styling | Tailwind CSS v4 + shadcn-style local primitives, zinc/emerald on `#09090b` | D10 |
| Backend | FastAPI + Pydantic v2 | D1 |
| ORM/migrations | SQLAlchemy 2.0 async + Alembic + asyncpg | D3 |
| Database | PostgreSQL 17, plain | D4 |
| LLM | one OpenAI-compatible client, env-selected (OpenAI / Gemini compat / Ollama) | D5 |
| Auth | password + HMAC-signed HttpOnly cookie, single user | D6, D11 |
| Barcode | @zxing/browser primary; BarcodeDetector fast path | D7 |
| Offline | Dexie queue, poison-pill protected | D8 |
| Streaming | SSE (single structured call; deltas server-chunked) | D9 |
| Deploy | Docker Compose (db + api + web/Caddy), external TLS | D12, D17 |

## 4. Repository layout

```
plate-os/
├── AGENTS.md                  ← you are here; keep updated
├── docker-compose.yml         ← db + api + web (Caddy)
├── .env.example               ← all PLATEOS_* vars documented
├── docs/decisions/            ← dated, immutable decision records (ADR-style)
├── scripts/generate_icons.py  ← stdlib PWA icon generator
├── backend/
│   ├── app/
│   │   ├── main.py            ← FastAPI app, CORS (dev), profile seeding
│   │   ├── config.py          ← pydantic-settings, PLATEOS_* env prefix
│   │   ├── db.py              ← async engine + session dependency
│   │   ├── models.py          ← SQLAlchemy 2.0 typed models (4 tables)
│   │   ├── schemas/           ← llm_contracts.py (LLM I/O) · api.py (DTOs)
│   │   ├── api/
│   │   │   ├── deps.py        ← cookie auth + profile dependency
│   │   │   └── routes/        ← auth · profile · food · meals · vision · chat
│   │   └── services/
│   │       ├── nutrition.py   ← ALL macro math (server side)
│   │       ├── llm.py         ← OpenAI-compatible gateway, JSON+Pydantic+retry
│   │       └── openfoodfacts.py
│   ├── alembic/               ← env.py (async) + versions/0001_initial.py
│   ├── tests/                 ← pure unit tests for nutrition math
│   ├── Dockerfile             ← slim; entrypoint: alembic upgrade head && uvicorn
│   └── requirements*.txt
└── frontend/
    ├── vite.config.ts         ← plugins (PWA manifest, Tailwind) + dev proxy
    ├── Caddyfile              ← static SPA + /api proxy (flush_interval -1)
    ├── Dockerfile             ← node build → caddy
    └── src/
        ├── App.tsx            ← tab shell, login gate, offline banner
        ├── lib/
        │   ├── nutrition.ts   ← client mirror of backend math (KEEP IN SYNC)
        │   ├── api.ts         ← fetch wrapper (ApiError with status)
        │   ├── types.ts       ← TS mirrors of backend schemas (KEEP IN SYNC)
        │   ├── image.ts       ← canvas downscale
        │   ├── barcode.ts     ← ZXing primary / BarcodeDetector fast path
        │   └── offline/db.ts  ← Dexie pending-queue + flush
        └── components/        ├── ui/ (Button, Card) · TargetBars · MealList
                                · ProposalCard · ScanSheet (lazy) · Assistant
                                · Analytics (lazy, Recharts) · ManualEntry · BottomNav
```

## 5. API surface (all under `/api`)

| Endpoint | Purpose |
| --- | --- |
| `POST /auth/login` · `POST /auth/logout` | cookie session |
| `GET/PUT /profile` | targets, anthropometrics, timezone |
| `GET/POST /food-items`, `GET /food-items/barcode/{code}` | library + OFF cache-aside |
| `GET/POST /meal-logs`, `PATCH/DELETE /meal-logs/{id}` | CRUD; totals always server-computed |
| `GET /daily-summary?day=&tz=` | tz-local targets/consumed/remaining |
| `GET /analytics/daily?days=` | tz-aware grouped per-day history + 7-day rolling avg (D20) |
| `POST /vision/parse-label` | LLM extraction → normalized per-100g; **stateless, never writes** |
| `POST /chat/stream` | SSE: `delta` → `proposal` → `done` (or `error`); persists chat only |
| `GET /health` | liveness |

Conventions: DTOs in `app/schemas/api.py`; the single profile row is resolved by the `get_current_profile` dependency; 401 means re-login. Auth accepts the session cookie **or** — for Apple Shortcuts/automation — `Authorization: Bearer $PLATEOS_API_TOKEN` when that env var is set (decision D19; full API access, rotate by changing the env). **Every new `Settings` field must be added to `.env.example` in the same change** (rule from D19's postmortem).

## 6. LLM integration rules

- Swap providers via env only: `PLATEOS_LLM_BASE_URL`, `PLATEOS_LLM_API_KEY`, `PLATEOS_LLM_MODEL`. Never import provider-specific SDKs beyond the OpenAI one.
- New LLM tasks = new Pydantic contract in `schemas/llm_contracts.py` + call via `LLMService.extract_json()` (JSON mode → validate → one corrective retry).
- The chat system prompt gets fresh context injected per turn (`build_context` in `routes/chat.py`): local datetime, today's consumed/remaining, last-3-days trend. Extend there, not by hand-editing prompts elsewhere.
- Privacy: default assumption is that label photos may leave the host unless `PLATEOS_LLM_BASE_URL` points at Ollama. Say this in any UI/docs touching vision features.

## 7. Running & verifying

**Backend (dev):**
```bash
cd backend
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt   # Windows Git Bash
# start a Postgres (docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=plateos ...)
cp ../.env.example .env   # adjust
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:app --reload
.venv/Scripts/python -m pytest
```

**Frontend (dev):** `cd frontend && npm install && npm run dev` (proxies `/api` → :8000). `npm run build` = typecheck + build. `npm run typecheck` alone is fast.

**Full stack:** `docker compose up --build` from repo root (needs `.env`) → http://localhost:8080. API container runs migrations on boot.

**Verification expectations:** 14 pytest unit tests (nutrition math, LLM gateway with stubbed client, session tokens); `tsc --noEmit` clean; OpenAPI lists 12 paths; `docker compose up --build` boots db→migrations→api→web and `GET :8080/api/health` returns ok. A full smoke checklist (login, meal math, analytics, bearer auth, OFF lookup, SSE error path) was executed 2026-08-21 — see the Evidence section of `docs/decisions/2026-08-21-verification-and-phase4.md`; re-run it after touching auth, math, or aggregation code.

## 8. Conventions & gotchas

- **Python:** 3.12, full type hints, SQLAlchemy 2.0 `Mapped[]` style; no business logic in route files (services only); `zoneinfo` everywhere for tz math.
- **TypeScript:** strict mode, no `any`; components small; Tailwind utility classes inline; new UI primitives follow the `ui/Button` cva+cn pattern.
- **Windows dev host (Git Bash):** venv binaries at `.venv/Scripts/`, not `bin/`. npm may block postinstall scripts (esbuild) via `allow-scripts` — the build still works because platform binaries ship as optional deps; if a tool complains, `npm approve-scripts` it.
- **iOS:** Safari has no `BarcodeDetector` (hence D7); camera requires HTTPS in production (fine behind the proxy, use `localhost` in dev); respect safe-area classes; keep `touch-action: manipulation` on interactive controls.
- **SSE:** any new proxy layer in front must disable buffering (Caddy `flush_interval -1`, `X-Accel-Buffering: no` header already set).
- **Dexie queue:** on POST failure, only 401/429/5xx/network errors retry; other 4xx are dropped (poison-pill rule). Don't add side effects to the flush loop.
- **Migrations:** edit `models.py`, then write a revision (hand-written is the norm here — keep `compare_type` friendly types); the API container applies revisions at boot, so never write a revision that can't run against live data.
- **`proposal_totals`** in `nutrition.py` is currently unused server-side (kept for the confirm-flow); remove or use when that flow lands.
- **Bundle layout:** main chunk must stay lean — new heavy deps (charting, ML, camera) go behind `React.lazy` routes like ScanSheet/Analytics (decision D21).

## 9. Roadmap status (as of 2026-08-21, evening)

- [x] Phase 1 — scaffold, data layer, CRUD, auth, docker-compose
- [x] Phase 2 — barcode + label pipelines, vision endpoint, downscaler *(live OFF lookup verified)*
- [x] Phase 3 — SSE chat, context injection, proposal cards, offline queue
- [x] Phase 4 — Recharts analytics (daily kcal vs target, 7-day rolling avg, macro distribution), Apple Shortcuts bearer token, code splitting (main 376 kB), manual Quick Log
- [x] Full-stack smoke test via `docker compose up --build` (2026-08-21)
- [ ] Real LLM round-trips (point `PLATEOS_LLM_BASE_URL` at OpenAI/Gemini/Ollama and exercise vision + chat)
- [ ] iOS device testing: camera in standalone PWA, install/offline behavior, safe areas
- [ ] Homelab deployment behind TLS proxy (set `PLATEOS_COOKIE_SECURE=true`)
- [ ] Optional later: effective-dated target history, food search-as-you-type in Quick Log

## 10. Documentation conventions

- **Decisions** live in `docs/decisions/YYYY-MM-DD-title.md`, date-addressed (ISO heading with offset; Occurred/Documented/Verified distinguished; rejected alternatives recorded). Supersede, never rewrite.
- **This file** carries current state; when they disagree, the newest decision record wins and AGENTS.md must be brought up to date.
- Do not commit secrets; `.env` is gitignored, `.env.example` is the documented surface.
