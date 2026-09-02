# AGENTS.md — PlateOS Context for Agents

**Last updated:** 2026-09-02 (Europe/Lisbon)
**Maintainer rule:** any agent (or human) that changes the architecture, stack, schema, conventions, or completes a roadmap phase MUST (a) update this file in the same change and (b) record the reasoning in a new dated file under `docs/decisions/`. Never rewrite decision history — supersede it.

---

## 1. What PlateOS is

PlateOS is a **mobile-first, self-hosted PWA for daily nutrition tracking and body recomposition**, built for household accounts on an iOS-first device. It removes tracking friction with three input paths:

1. **Barcode scan** → accepted library lookup, then an ephemeral Open Food Facts candidate
2. **Label photo** → Vision LLM extracts the nutrition table
3. **Freeform text** → conversational AI coach parses the meal ("1.5 cans of drained tuna with 100g pasta")

Every meal acquisition path funnels through an **editable Proposal Card** before a meal log is persisted.

**User & hosting context:** homelab deployment, Docker-only on servers (decision D17), TLS terminates at an existing reverse proxy, and the origin is loopback-only (D31). Privacy matters: the LLM backend is env-swappable so inference can stay fully local via Ollama.

## 2. Non-negotiable invariants

These are product laws, not preferences. If a change violates one, stop and reconsider:

1. **LLM extracts; the app computes.** The LLM returns raw reference values (per 100g or per serving, with an explicit `basis`) and never does arithmetic. All scaling lives in `backend/app/services/nutrition.py` and its client mirror `frontend/src/lib/nutrition.ts` — **keep these two in sync** (same fields `calories, protein_g, carbs_g, fat_g, fiber_g`, positive `ROUND_HALF_UP` to 1 decimal). `POST /api/meal-logs` always recomputes totals server-side from density × quantity; client-sent totals are ignored.
2. **Zero silent database mutations.** Vision parsing and chat return *proposals* only (`LogProposalResponse`). Persistence happens exclusively via explicit `POST /api/meal-logs` after user confirmation (the Proposal Card). Never add a code path where an LLM response writes to `meal_logs` directly.
3. **Client-side image downscaling.** Every image is canvas-downscaled to ≤1280px longest edge, WebP (JPEG fallback) q=0.7 (~150KB) in `frontend/src/lib/image.ts` before hitting the network. Label capture uses `<input type="file" capture="environment">` for focus quality on small text.
4. **Offline-first.** Every confirmed meal gets a client UUID and confirmation timestamp before its first POST. Retryable failures queue in IndexedDB (Dexie) and replay idempotently; permanent queued 4xx failures remain visible for explicit discard instead of being silently deleted. The SPA shell precaches via Workbox. New features must not assume connectivity.
5. **Server-side = containers only.** Anything that runs on a server runs in Docker (runtime services: `db`, `api`, `web`; the push worker and backup/restore jobs are opt-in containers). Dev tooling (venv, node) lives on workstations only.
6. **Timezone-correct rollups.** Daily budgets group by the user's local midnight (`user_profile.timezone`, IANA, via `zoneinfo`), never UTC `date_trunc`. All new aggregation code must use `day_bounds()` in `backend/app/api/routes/meals.py`.
7. **Production fails closed.** Compose forces production mode, file-injected strong secrets, Secure cookies, DB-backed readiness, and a loopback-only origin. Never weaken these to make deployment convenient; keep workstation defaults in development mode instead (D29-D31).

## 3. Architecture

```
┌────────────────────────────────────────────────────┐
│        Client — iOS PWA (Vite + React 19 SPA)      │
│  Tailwind v4 · @zxing/browser · Dexie queue        │
│  canvas downscale ≤1280px WebP 0.7 · Workbox SW    │
└───────────────┬────────────────────▲───────────────┘
                │ REST + SSE (HTTPS via external proxy)
┌───────────────▼────────────────────┴───────────────┐
│ web (Caddy :8080 internal) — static SPA + /api/*   │
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
          │
┌─────────▼──────────────────────────────────────────┐
│ opt-in push worker — leased Web Push outbox (D41) │
└────────────────────────────────────────────────────┘
```

Production hardcodes `web` to IPv4 loopback with only the port configurable. `db` is
on an internal network; an opt-in job produces age-encrypted PostgreSQL dumps,
and restore drills use a separate internal-only Compose project (D31-D33).

**Stack** (rationale and rejected alternatives: `docs/decisions/2026-08-21-initial-stack-architecture.md`):

| Layer | Choice | Decision |
| --- | --- | --- |
| Frontend | Vite 6 + React 19 SPA, TanStack Query | D2 |
| Styling | Tailwind CSS v4 + shadcn-style local primitives, zinc/emerald on `#09090b` | D10 |
| Backend | FastAPI + Pydantic v2 | D1 |
| ORM/migrations | SQLAlchemy 2.0 async + Alembic + asyncpg | D3 |
| Database | PostgreSQL 17, plain | D4 |
| LLM | one OpenAI-compatible client per task; text (coach) and vision (labels) resolve independently — UI overrides then env defaults, vision inherits text unless split (D34/D35) | D5, D34 |
| Auth | password + HMAC-signed HttpOnly cookie; multi-user accounts with scrypt hashes, first account admin (D11 → D36) | D6, D11, D36 |
| Barcode | @zxing/browser primary; BarcodeDetector fast path | D7 |
| Offline | Dexie queue, poison-pill protected | D8 |
| Streaming | SSE (single structured call; deltas server-chunked) | D9 |
| Deploy | Hardened Docker Compose (db + api + web/Caddy), loopback origin, external TLS | D12, D17, D29-D33 |

## 4. Repository layout

```
plate-os/
├── AGENTS.md                  ← you are here; keep updated
├── docker-compose.yml         ← hardened db + api + web; opt-in push/backup profiles
├── docker-compose.dev.yml     ← isolated one-command workstation review stack
├── docker-compose.restore.yml ← isolated restore + API verification project
├── .env.example               ← all PLATEOS_* vars documented
├── docs/decisions/            ← dated, immutable decision records (ADR-style)
├── docs/operations/           ← production/backup/restore runbook
├── ops/backup/                ← encrypted pg_dump, guarded restore, verifier
├── scripts/generate_icons.py  ← stdlib PWA icon generator
├── backend/
│   ├── app/
│   │   ├── main.py            ← lifespan, liveness/readiness, profile seeding
│   │   ├── config.py          ← env + /run/secrets; fail-closed production mode
│   │   ├── db.py              ← async engine + session dependency
│   │   ├── middleware.py      ← streaming-safe 2 MB request-body limit
│   │   ├── models.py          ← SQLAlchemy 2.0 typed models (16 tables)
│   │   ├── schemas/           ← llm_contracts.py (LLM I/O) · api.py (DTOs)
│   │   ├── api/
│   │   │   ├── deps.py        ← cookie auth + profile dependency
│   │   │   └── routes/        ← auth · profile · products · meals · routines · push · AI
│   │   └── services/
│   │       ├── nutrition.py   ← ALL macro math (server side)
│   │       ├── runtime_settings.py ← Settings-screen provider state (file-backed)
│   │       ├── llm.py         ← OpenAI-compatible gateway, per-task routing
│   │       ├── openfoodfacts.py
│   │       ├── routines.py
│   │       └── web_push.py
│   ├── alembic/               ← env.py (async) + revisions 0001-0005
│   ├── tests/                 ← math, validation, auth, LLM, integrity, runtime tests
│   ├── Dockerfile             ← pinned non-root image; migrations then uvicorn
│   ├── requirements.lock      ← exact production dependency resolution
│   └── requirements*.txt      ← direct dev/runtime requirements
└── frontend/
    ├── vite.config.ts         ← plugins (PWA manifest, Tailwind) + dev proxy
    ├── Caddyfile              ← static SPA + /api proxy (flush_interval -1)
    ├── Dockerfile             ← node build → caddy
    └── src/
        ├── App.tsx            ← responsive tab shell, login gate, offline banner
        ├── lib/
        │   ├── nutrition.ts   ← client mirror of backend math (KEEP IN SYNC)
        │   ├── api.ts         ← fetch wrapper (ApiError with status)
        │   ├── types.ts       ← TS mirrors of backend schemas (KEEP IN SYNC)
        │   ├── image.ts       ← canvas downscale
        │   ├── barcode.ts     ← ZXing primary / BarcodeDetector fast path
        │   └── offline/db.ts  ← Dexie pending-queue + flush
        └── components/        ├── ui/ (Button, Card) · TargetBars · MealList
                                · ProposalCard · ScanSheet (lazy) · Assistant
                                · Analytics (lazy, Recharts) · AssistantBlocks
                                · GoalChangeReview · ProductLibrary · Routines
                                · PushSettings · ManualEntry
                                · DesktopHeader (md+) · BottomNav (mobile only)
```

## 5. API surface (all under `/api`)

| Endpoint | Purpose |
| --- | --- |
| `POST /auth/login` · `POST /auth/logout` | username-aware cookie session; password-only allowed while one account exists |
| `GET /auth/me` · `GET/POST /users`, `PATCH /users/me/password`, `PATCH /users/{id}/password` | account identity; admin-only household management + local resets (D36) |
| `GET/PUT /profile` | targets, anthropometrics, timezone |
| `GET/POST/PATCH /food-items`, `POST /food-items/{id}/archive`, `GET /food-items/barcode/{code}` | reviewed library + ephemeral OFF candidates |
| `GET/POST /meal-logs`, `PATCH/DELETE /meal-logs/{id}` | CRUD; server-computed totals; optional replay-safe mutation UUID |
| `GET /daily-summary?day=` | tz-local targets/consumed/remaining |
| `GET /analytics/daily` | tz-aware ranges + source/food filters, summaries, history, source mix, top foods (D20/D38) |
| `POST /vision/parse-label` | LLM extraction → normalized per-100g; **stateless, never writes** |
| `GET/PUT /settings`, `POST /settings/test` | UI-managed provider config; keys write-only; cookie-session-only |
| `POST /chat/stream` | SSE harness: `meta` → `delta` → typed `block` → `done`; persists chat only (D39) |
| `GET/POST/PUT /routines`, schedule state, `POST /agenda/refresh`, occurrence complete/skip | user-owned plans, wall-clock recurrence, explicit lifecycle |
| `GET/PUT/DELETE /push` | cookie-only encrypted browser subscription management |
| `GET /health` · `GET /ready` | dependency-free liveness · DB/schema/profile readiness |

Conventions: DTOs live under `app/schemas`; the current account profile is resolved by `get_current_profile`; 401 means re-login. Auth accepts the session cookie **or** — except for cookie-only settings, account-management, and push surfaces — `Authorization: Bearer $PLATEOS_API_TOKEN` when configured (decision D19; full data API access, rotate the production secret file and restart the API). **Every new `Settings` field must be added to `.env.example` in the same change** (rule from D19's postmortem).

## 6. LLM integration rules

- Two tasks route independently (`get_llm("text")` / `get_llm("vision")`): resolution is Settings-screen override → inheritance (vision from text) → env default (`PLATEOS_LLM_BASE_URL/_API_KEY/_MODEL`). Never import provider-specific SDKs beyond the OpenAI one.
- Settings presets include OpenAI, Gemini, Ollama, and DeepSeek. DeepSeek text uses `deepseek-v4-flash`; official hosted vision uses the experimental `deepseek-v4-flash-vision-exp` and must be configured as a separate vision provider rather than inheriting the text model.
- Runtime provider config lives in `PLATEOS_RUNTIME_SETTINGS_FILE` (JSON, outside the DB/backups). API keys are write-only over the API; Settings mutations are cookie-session-only — the bearer token cannot reach them. After a restore drill, re-enter provider config (D35).
- New LLM tasks = new Pydantic contract in `schemas/llm_contracts.py` + call via `LLMService.extract_json()` (JSON mode → validate → one corrective retry).
- Assistant output is a strict D39/D41 block union (`meal_proposal`, `meal_plan_draft`, `goal_draft`, `analytics_navigation`, `evidence_insight`). Never add generic URL/method/payload actions or execute model output directly. Context is server-built, user-scoped, and mode-minimized; body measurements are goals-only.
- The chat system prompt gets fresh context injected per turn (`build_context` in `routes/chat.py`): local datetime, today's consumed/remaining, last-3-days trend. Extend there, not by hand-editing prompts elsewhere.
- Privacy: default assumption is that label photos may leave the host unless the resolved vision endpoint points at Ollama. Say this in any UI/docs touching vision features.

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

**Local review stack:** `docker compose -f docker-compose.dev.yml up --build --wait` serves `http://127.0.0.1:8081` with disposable `admin` / `changeme` credentials and isolated `plateos-dev` volumes (D40). Use `down` without `-v` to preserve review data.

**Production stack:** hardened Compose requires the files documented in `docs/operations/production.md` under `PLATEOS_SECRETS_DIR`; `docker compose up --build` then serves the configured loopback origin. API runs migrations on boot. Never reuse development credentials in this flow. Production runs commit `8c3357e` without the optional push profile; it supersedes the initial content-addressed D41 artifact recorded by D42.

**Verification expectations:** 188 pytest tests and 43 Vitest tests cover math, validation, integrity, analytics, AI contracts, reviewed products, recurrence/DST, account-owned offline replay, Web Push encryption/ownership/leases/SSRF guards, auth, readiness, provider error feedback, and recovery guards; `tsc --noEmit` is clean; OpenAPI lists 30 paths. Compose must boot db→migration→API readiness→web readiness; encrypted backup and isolated restore verification must pass before a recoverability claim. The review database upgraded through `0005` and the local stack/build passed 2026-09-02. Production also upgraded `0003 → 0005`, reached healthy readiness, and passed authenticated read-only API checks on 2026-09-02 (D42). Real push delivery, authenticated edge access, production restore, and iOS evidence remain separate.

## 8. Conventions & gotchas

- **Python:** 3.12, full type hints, SQLAlchemy 2.0 `Mapped[]` style; no business logic in route files (services only); `zoneinfo` everywhere for tz math.
- **TypeScript:** strict mode, no `any`; components small; Tailwind utility classes inline; new UI primitives follow the `ui/Button` cva+cn pattern.
- **Windows dev host (Git Bash):** venv binaries at `.venv/Scripts/`, not `bin/`. npm may block postinstall scripts (esbuild) via `allow-scripts` — the build still works because platform binaries ship as optional deps; if a tool complains, `npm approve-scripts` it.
- **iOS:** Safari has no `BarcodeDetector` (hence D7); camera requires HTTPS in production (fine behind the proxy, use `localhost` in dev); respect safe-area classes; keep `touch-action: manipulation` on interactive controls.
- **Mobile shell:** below `md`, the app owns a flex viewport (`100dvh` in-browser, `100lvh` in standalone mode); only its content pane scrolls, while `BottomNav` remains a normal-flow non-scrolling sibling. Do not restore viewport-fixed mobile navigation; page-height changes make it unstable in iOS standalone mode (D44-D46).
- **SSE:** any new proxy layer in front must disable buffering (Caddy `flush_interval -1`, `X-Accel-Buffering: no` header already set).
- **Dexie queue:** only 429/5xx/network failures enqueue or retry. Direct permanent 4xx errors keep the Proposal Card open; queued permanent 4xx entries move to a visible failed state and do not block later rows. The backend mutation ledger is the cross-tab duplicate boundary.
- **Migrations:** edit `models.py`, then write a revision (hand-written is the norm here — keep `compare_type` friendly types); the API container applies revisions at boot, so never write a revision that can't run against live data. New revisions must also update readiness probes and the supported revision cases in both backup/restore scripts.
- **Meal-log snapshots:** `meal_logs.*_per_100` is immutable source density for PATCH recomputation. Never rescale from `calculated_*`; those totals are rounded display/persistence values.
- **Idempotency:** frontend writes always include a stable `client_mutation_id`. `meal_log_mutations` retains fingerprints and deletion tombstones; reuse with changed data or after deletion returns 409. External clients may omit the key but then rely on their own transport for duplicate prevention.
- **Bundle layout:** main chunk must stay lean — new heavy deps (charting, ML, camera) go behind `React.lazy` routes like ScanSheet/Analytics (decision D21).
- **Release identity:** production web builds receive the existing `PLATEOS_IMAGE_TAG` as `VITE_PLATEOS_VERSION`; the mobile header shows its seven-character prefix so an installed PWA's active release can be identified without exposing configuration.
- **Production config:** secrets are lowercase `plateos_*` files under `/run/secrets`; Compose mounts root/dedicated-group `0440` files from a `0750` `PLATEOS_SECRETS_DIR` and grants only consumers the supplementary `PLATEOS_SECRETS_GID`. Production rejects weak/default credentials and non-Secure cookies. Keep secret values out of `.env`, Compose output, logs, and commands.
- **Containers:** base images use multi-platform index digests, Python production installs `requirements.lock`, frontend uses `npm ci --ignore-scripts`, and runtimes are non-root/read-only with bounded logs. Update pins and lockfiles intentionally together.
- **Recovery:** never archive live `pgdata`. Use the opt-in encrypted `pg_dump` job and the separate restore project. The backup refuses an uninitialized/unsupported DB or invalid single-profile state and publishes ciphertext only after its checksum sidecar. Restore emptiness inspection relies on PostgreSQL's normal-object OID boundary and must be revalidated with a database major-version pin change. A synthetic local drill passes, but tooling/local evidence is not a production backup; do not say "backed up" until monitored production backups, independent retention, and an isolated application restore are verified.

## 9. Roadmap status (as of 2026-09-02)

- [x] Phase 1 — scaffold, data layer, CRUD, auth, docker-compose
- [x] Phase 2 — barcode + label pipelines, vision endpoint, downscaler *(live OFF lookup verified)*
- [x] Phase 3 — SSE chat, context injection, proposal cards, offline queue
- [x] Phase 4 — Recharts analytics (daily kcal vs target, 7-day rolling avg, macro distribution), Apple Shortcuts bearer token, code splitting (main 381 kB), manual Quick Log
- [x] Full-stack smoke test via `docker compose up --build` (2026-08-21)
- [x] Meal-log integrity hardening: idempotent replay, confirmation timestamps, density snapshots, matched rounding, retained queue failures (2026-08-25)
- [x] Production-hardening implementation and local runtime verification: fail-closed settings, readiness, loopback origin, pinned/non-root containers, request/security policy (2026-08-25)
- [x] Hardened Compose smoke: built images, initialized PostgreSQL as non-root/read-only, applied populated `0001 → 0002`, verified headers/body limits/SSE/readiness (2026-08-25)
- [x] Synthetic encrypted backup and isolated application restore drill, including checksum, restored reads, source-count comparison, and non-empty-target refusal (2026-08-25)
- [x] Dual-provider LLM routing + Settings screen: per-task providers, write-only keys, cookie-only mutations, runtime file outside DB/backups (2026-08-25)
- [x] Multi-user household accounts: scrypt credentials, admin management, local password reset, admin-gated provider settings, desktop navigation layout (D36, 2026-08-26)
- [x] Desktop navigation redesign: horizontal control deck, mobile-only bottom navigation, natural document scrolling (D37, 2026-08-31)
- [x] Filterable analytics workspace: custom ranges, source/food filters, nutrient and weekday trends, source mix, top foods (D38, 2026-08-31)
- [x] Constrained AI harness: contextual meal ideas, goal drafts, evidence insights, and safe Stats navigation (D39, 2026-08-31)
- [x] Isolated one-command local review Compose stack (D40, 2026-09-02)
- [x] Account-owned offline meal and occurrence replay with durable, idempotent completion attempts (D41, 2026-09-02)
- [x] Reviewed product library and local → OFF candidate → optional label proof → explicit save/log pipeline (D41, 2026-09-02)
- [x] Rough/defined routines, schedules, DST-aware occurrences, agenda/countdown, and Proposal Card completion (D41, 2026-09-02)
- [x] Constrained AI meal-plan drafts with explicit routine/schedule confirmation (D41, 2026-09-02)
- [x] Transport-neutral notification outbox and isolated opt-in Web Push worker with generic payloads (D41, 2026-09-02)
- [x] Homelab production deployment: commit `8c3357e`, `0003 → 0005`, loopback origin, TLS/Access challenge, and pre/post encrypted backup checksums (D42, 2026-09-02)
- [ ] Production recovery operations: choose destination, schedule, retention, RPO/RTO, monitoring, and execute an authorized restore drill from a production backup
- [ ] Real LLM round-trips (point `PLATEOS_LLM_BASE_URL` at OpenAI/Gemini/DeepSeek/Ollama and exercise vision + chat)
- [ ] iOS device testing: camera in standalone PWA, install/offline behavior, safe areas
- [ ] Optional later: effective-dated target history, food search-as-you-type in Quick Log

## 10. Documentation conventions

- **Decisions** live in `docs/decisions/YYYY-MM-DD-title.md`, date-addressed (ISO heading with offset; Occurred/Documented/Verified distinguished; rejected alternatives recorded). Supersede, never rewrite.
- **This file** carries current state; when they disagree, the newest decision record wins and AGENTS.md must be brought up to date.
- Do not commit secrets; `.env` is gitignored, `.env.example` is the documented surface.
