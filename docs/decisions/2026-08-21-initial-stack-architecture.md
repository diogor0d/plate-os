# Decision Record — Initial Stack & Architecture

- **Occurred:** 2026-08-21 (stack review of the original mission brief, followed by scaffold implementation)
- **Documented:** 2026-08-21T19:53:31+01:00 (Europe/Lisbon)
- **Verified:** 2026-08-21 — see [Evidence](#evidence) below
- **Status:** Implemented (initial scaffold). Supersede entries here with a new dated record; never edit history.
- **Recall tags:** PlateOS, stack, architecture, FastAPI, Vite, PostgreSQL, LLM gateway, August 2026

This record resolves the internal contradictions found in the original mission
brief and locks in the replacements. Each decision lists the alternatives that
were rejected and why. **AGENTS.md** is the living context document; this file
is the immutable audit trail of *why*.

---

## D1 — Backend runtime: FastAPI (Python 3.12)

**Context.** The brief said "FastAPI (Python 3.12) **or** Next.js Server Actions" — an unresolved choice that blocked everything downstream.

**Decision.** FastAPI. Pydantic v2 is the strongest structured-output validation story for LLM parsing, the brief's own schema examples were Pydantic, and Python's ecosystem (zoneinfo, httpx) covers the remaining needs.

**Rejected.**
- *Next.js Server Actions* — incompatible with the offline-first PWA requirement (an SSR/actions app degrades behind a service worker); also would have forced Node ORMs.
- *Dual backend (Next + FastAPI)* — doubles operational surface for a single-user self-hosted app.

**Consequences.** Server-side code is Python-only; frontend talks to it over REST + SSE. See D3 for the ORM implication.

## D2 — Frontend: Vite 6 + React 19 SPA (not Next.js)

**Context.** Brief specified Next.js 15 App Router. An offline-capable, installable PWA gains nothing from SSR and pays for it (runtime weight, service-worker/SSR friction, iOS standalone quirks).

**Decision.** Vite + React 19 SPA, statically served by Caddy in production. Navigation is currently a simple 4-tab state switch (Today / Scan / Coach / Stats); introduce TanStack Router only when views multiply.

**Rejected.** Next.js App Router (see D1); React Native/Expo (app-store friction the brief explicitly avoids).

**Consequences.** Vite 6 chosen over 7 for confirmed plugin compatibility (`vite-plugin-pwa`, `@tailwindcss/vite`). Known improvement: main bundle is ~792 kB minified (ZXing is heavy); code-split the scanner via dynamic `import()` later.

## D3 — ORM: SQLAlchemy 2.0 (async) + Alembic

**Context.** Brief said "Prisma / Drizzle" — both Node-only, impossible to combine with FastAPI. This was contradiction #1 of the brief.

**Decision.** SQLAlchemy 2.0 typed declarative models, `asyncpg` driver, async sessions; Alembic for migrations with the URL injected from `PLATEOS_DATABASE_URL`.

**Rejected.** Prisma / Drizzle (wrong runtime); raw SQL (loses type-sightlines); SQLModel (adds little over SQLAlchemy 2.0 typed mappings).

**Consequences.** Migration workflow: edit `app/models.py` → hand-write/autogenerate revision → `alembic upgrade head` (runs automatically in the API container entrypoint).

## D4 — Database: plain PostgreSQL 17

**Context.** Brief specified "PostgreSQL 16 + TimescaleDB" and offered "SQLite with WAL via LiteFS" as an alternative.

**Decision.** Plain PostgreSQL 17 (Alpine image), no TimescaleDB. One index that matters: `ix_meal_logs_user_logged_at (user_id, logged_at)`.

**Rejected.**
- *TimescaleDB* — hypertables for a single user's daily `SUM()` rollups is pure operational overhead; a b-tree range scan over one user's rows is microsecond-scale.
- *SQLite + LiteFS* — LiteFS exists to replicate SQLite across nodes; meaningless on a single homelab host. (Plain SQLite+WAL remains a viable future option if a single-container build is ever wanted, but it is not worth the JSONB/UUID downgrade today.)

**Consequences.** JSONB and `gen_random_uuid()` available; Postgres 17 over 16 simply for currency.

## D5 — LLM gateway: one OpenAI-compatible client, selected by env

**Context.** Brief hardcoded "OpenAI / Gemini Flash 2.0 (or Ollama)" — a lock-in with already-stale model names, and a contradiction with its own "air-gappable, zero telemetry" requirement (label photos to a cloud API are the largest telemetry surface in the system).

**Decision.** A single `LLMService` speaking the OpenAI Chat Completions protocol, configured by `PLATEOS_LLM_BASE_URL` / `PLATEOS_LLM_API_KEY` / `PLATEOS_LLM_MODEL`. Works unchanged against OpenAI, Gemini's OpenAI-compat endpoint, and local Ollama — making local-only mode (e.g. a Qwen-VL class model) an env change, not a refactor. Structured output = JSON response mode + local Pydantic validation + one corrective retry (uniform across all three providers, unlike provider-specific structured-output APIs).

**Rejected.** Provider-specific SDK paths per vendor; LiteLLM proxy (extra container, not needed for one app).

**Consequences.** Privacy stance documented in `.env.example`: pointing `PLATEOS_LLM_BASE_URL` at Ollama keeps all inference on-host.

## D6 — Auth: single password + HMAC-signed HttpOnly cookie

**Context.** Brief said "JWT / Session Tokens".

**Decision.** One password from env (`PLATEOS_APP_PASSWORD`), one HMAC-SHA256-signed HttpOnly `SameSite=Strict` cookie with 1-year TTL (right-sized for a single-user standalone PWA), `PLATEOS_COOKIE_SECURE=true` behind TLS.

**Rejected.** JWT — refresh-token dance buys nothing single-user, and JS-readable token storage is an XSS liability.

## D7 — Barcode: ZXing primary, BarcodeDetector only a fast path

**Context.** Brief assumed `BarcodeDetector` primary with ZXing fallback. **Safari does not implement the BarcodeDetector API** — it is Chromium-only, so on this iOS-first app the "fallback" is actually the primary. Also `@zxing/library` is deprecated for browser use.

**Decision.** `@zxing/browser` (`BrowserMultiFormatReader`) as the default engine; `BarcodeDetector` used opportunistically where present. Camera stream attached manually via `getUserMedia({facingMode: 'environment'})` in both paths.

## D8 — Offline queue: Dexie (IndexedDB) with poison-pill protection

**Decision.** Failed meal-log POSTs enqueue into Dexie (`pendingMealLogs`), flushed on app mount and on the `online` event. Permanent 4xx validation failures are dropped instead of retried forever; 401/429/5xx and network errors retry later. The UI shows an "offline — logging queued" banner.

**Rejected.** Raw IndexedDB (verbose, error-prone); RxDB (heavy); TanStack Query mutation persistence alone (doesn't own the queue semantics).

## D9 — Chat streaming: SSE carrying one structured call

**Context.** Brief demanded SSE token streaming *and* a structured tool-call (`LogProposalResponse`). JSON response mode returns one blob — you can't token-stream it.

**Decision.** One structured LLM call per turn; the SSE channel then emits the assistant message as `delta` word-chunks (20 ms cadence) and the proposal as a discrete `proposal` event, closing with `done`. Single round-trip (no doubled latency/cost), fully provider-agnostic, and the transport is already SSE for the day a provider's native streaming is wired in. `X-Accel-Buffering: no` set; Caddy `flush_interval -1`.

**Rejected.** Two-call flow (freeform stream + structured follow-up) — doubles cost/latency on every turn.

## D10 — Styling: Tailwind CSS v4 + hand-rolled shadcn-style primitives

**Decision.** Tailwind v4 via `@tailwindcss/vite`, zinc/emerald dark palette on `#09090b`, small local `Button`/`Card` primitives (cva + cn). Full shadcn/ui CLI pull was unnecessary for the scaffold; adopt more primitives organically as screens grow.

## D11 — Data model: single-user, global food library

**Context.** Brief hedged between single- and multi-user (auth + `user_id` FKs, but a globally-shared `food_items` with globally-unique barcodes).

**Decision.** Commit to single-user v1: exactly one seeded `user_profile` row (defaults 2400/140/280/65 kcal/P/C/F); `food_items` is a global shared library (cached Open Food Facts entries + user items). Auth exists to keep the homelab port from being open to the LAN, not to model multiple users.

**Consequences.** If multi-user ever matters, this decision and D6 must be superseded by a new dated record (user scoping of `food_items`, per-user barcode caches, real accounts).

## D12 — Deployment: 3-container Docker Compose, TLS external

**Decision.** `db` (postgres:17-alpine) + `api` (python:3.12-slim; entrypoint runs `alembic upgrade head` then uvicorn) + `web` (multi-stage node:22-alpine build → caddy:2-alpine serving the SPA with history fallback and proxying `/api/*` with `flush_interval -1` for SSE). TLS terminates at the existing homelab reverse proxy, which forwards to `web:8080`.

## D13 — Invariant: LLM extracts, the app computes

**Decision.** The LLM returns raw reference values exactly as printed/estimated (with an explicit `basis`); `app/services/nutrition.py` does ALL scaling/normalization server-side, and `frontend/src/lib/nutrition.ts` mirrors the same deterministic math for instant proposal-card recomputation. **These two files must stay in sync — same fields, same 1-decimal rounding.** `POST /api/meal-logs` ignores any client-sent totals and recomputes from density × quantity.

## D14 — Invariant: timezone-local daily rollups

**Decision.** `user_profile.timezone` (IANA) drives midnight-to-midnight bounds via `zoneinfo`; range predicates compare against `timestamptz`. Never `date_trunc` on UTC. The contextual injector also renders datetimes in the user's tz.

## D15 — Schema deviations from the brief (deliberate)

1. `meal_logs.calculated_fiber` added — the brief extracted fiber but never persisted it.
2. `chat_messages.session_id` added — conversation threading.
3. `user_profile.timezone` added — required by D14.
4. `NutritionLabelExtraction` uses a `basis` field (`per_100g` | `per_serving`) + `serving_size_g` instead of per-100g-only fields, with server-side normalization — real labels are frequently per-serving.
5. `ProposalItem`s carry `per100` density so quantity edits recompute without server round-trips.

## D16 — iOS PWA specifics

**Decision.** `manifest` inline via vite-plugin-pwa (`standalone`, `portrait`, `#09090b`); `viewport-fit=cover` + `.pt-safe`/`.pb-safe` (`env(safe-area-inset-*)`) on header/bottom nav/sheets; `touch-action: manipulation` on all buttons/steppers; label capture via `<input type="file" capture="environment">` (brief constraint #5) with the 1280px/WebP-0.7 canvas downscale before upload.

## D17 — Everything server-side is containerized

**Context.** Explicit user directive, 2026-08-21: "any supporting structure in a server should be docker containerized".

**Decision.** No bare-metal processes on any host. All server components run as containers: `db`, `api`, `web` (see D12). Dev-time tooling (venv, node) is workstation-only and never assumed on servers.

## D18 — Deferred by design

- Analytics charts (Recharts, 7-day rolling) — Phase 4 placeholder tab exists.
- Apple Shortcuts webhook/API-token endpoint — Phase 4.
- Effective-dated target history (cut/bulk periods) — revisit when wanted.
- Code-splitting the ZXing scanner; TanStack Router adoption.

---

## Evidence (verified 2026-08-21, Europe/Lisbon)

| Check | Result |
| --- | --- |
| Backend unit tests (`pytest`) | 6 passed (normalization, scaling, rounding, totals) |
| App import + OpenAPI generation | OK; 11 API paths listed |
| Alembic | single head `0001`; `compileall` clean |
| Frontend | `tsc --noEmit` clean; `vite build` OK; SW + manifest precached (11 entries) |
| Icons | generated via `scripts/generate_icons.py` (stdlib PNG writer) |

**Not yet verified:** full Docker Compose stack up (requires Docker host),
migration against a live Postgres, LLM round-trips against a real provider,
and end-to-end iOS camera/PWA install behavior. These are the first items for
the next session.
