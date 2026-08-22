# Decision Record — End-to-End Verification & Phase 4 Features

- **Occurred:** 2026-08-21 (continuation session: Docker verification + Phase 4 implementation)
- **Documented:** 2026-08-21T20:16:21+01:00 (Europe/Lisbon)
- **Verified:** 2026-08-21 — see [Evidence](#evidence)
- **Status:** Implemented and verified against a live `docker compose` stack on the dev workstation.
- **Recall tags:** PlateOS, verification, smoke test, analytics, Apple Shortcuts, API token, code splitting, August 2026

Companion to `2026-08-21-initial-stack-architecture.md` (D1–D18). This record
covers the continuation session; numbering continues from D18.

---

## D19 — Apple Shortcuts auth: static bearer token

**Context.** Phase 4 called for "an authenticated Webhook / API token endpoint
for external Apple Shortcuts logging". The app already has cookie sessions,
but Shortcuts can't do interactive login flows.

**Decision.** Optional static token `PLATEOS_API_TOKEN` (env). When set,
`Authorization: Bearer <token>` authenticates as the default profile on ANY
API endpoint — not just logging — so Shortcuts can also read summaries.
`hmac.compare_digest` comparison; absent/empty setting disables the path
entirely. Cookie auth is checked first; bearer is the fallback.

**Rejected.** Per-request HMAC signing (overkill for one trusted device);
a separate token table with rotation (no UI to manage it — YAGNI until asked).

**Consequences.** Token = full account access; documented as such in
`.env.example` and README. Rotate by changing the env var.

**Defect found & fixed during verification:** the token was initially missing
from `.env.example`, so the first smoke run silently ran without it (bearer
401). Rule going forward: **every new `Settings` field must land in
`.env.example` in the same change.**

## D20 — Analytics endpoint: one timezone-aware grouped query

**Decision.** `GET /api/analytics/daily?days=1..90` computes per-day totals in
a single SQL query using Postgres `timezone(tz, logged_at)` (timestamptz →
local timestamp, matching invariant #6), then zero-fills missing days for a
contiguous series and returns `rolling_avg_calories_7d` over the last 7 days
(including zero days — adherence semantics). Targets included for chart
reference lines.

**Rejected.** Per-day loop of `consumed_for_day` (N queries — fine at this
scale, but the grouped query is the pattern to reuse for any future
aggregation).

## D21 — Code splitting: route-level lazy chunks

**Context.** The initial build had a 792 kB main bundle (ZXing + later
Recharts), with a Vite warning.

**Decision.** `React.lazy` + `Suspense` per bottom-nav route: the Scan sheet
(ZXing, ~416 kB) and Analytics (Recharts, ~447 kB) load on demand. Main
bundle: **376 kB** (120 kB gzip) — a 52% cut, warning gone.

## D22 — Recharts pinned to ^2.15.3

**Decision.** Recharts 2.15.x for confirmed React 19 compatibility; v3 exists
but offers nothing this dashboard needs. Revisit if a v3 feature matters.

## D23 — Manual Quick Log fills the brief's third input path

**Decision.** The brief's bottom nav promised Scan / Quick Log / Analytics;
Quick Log is now a compact per-100g form (Today tab → "Quick log") that
funnels through the same Proposal Card confirmation + offline queue as vision
and chat. No new persistence paths — invariant #2 preserved.

---

## Evidence (verified 2026-08-21, live `docker compose up --build` on the dev workstation)

| Check | Result |
| --- | --- |
| Unit tests | 14 passed (nutrition 6, LLM gateway 4 w/ stubbed client, session tokens 4) |
| Container build & boot | db healthy → api migrations auto-applied (5 tables incl. alembic_version) → web serving |
| Auth | wrong password 401; login sets cookie; unauthenticated 401; tamper/expiry tests pass |
| Seeding | profile auto-created with 2400/140/280/65, tz Europe/Lisbon |
| Meal math (server-side) | 100g oats@379 → 379.0 kcal; 200g chicken@165 → 330 kcal/62g P; PATCH 200→300g rescaled proportionally (495 kcal) ✓ |
| Aggregation | daily-summary sums correct; analytics rolling-7 avg correct incl. zero-fill |
| Bearer token | good→200, bad→401, Shortcuts-style POST logged correctly |
| Open Food Facts | live lookup 3017620422003 → "Nutella", 539 kcal/100g, cached (`is_verified=false`) |
| SSE | streams through Caddy (`flush_interval -1`); no-LLM-key case emits graceful `event: error` |
| Frontend | tsc clean; main 376 kB + ScanSheet 416 kB + Analytics 447 kB lazy chunks; SW precache OK |
| Cleanup | smoke-test meal logs deleted; consumed back to 0.0 kcal |

**Still not verified:** real LLM round-trips (needs an API key or local
Ollama), iOS camera/PWA-install behavior on a physical device, and the
homelab's external TLS proxy hop. The first can be tested by pointing
`PLATEOS_LLM_BASE_URL` at any OpenAI-compatible endpoint.
