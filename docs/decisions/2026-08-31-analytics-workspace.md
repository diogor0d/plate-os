# Decision Record — Filterable Analytics Workspace

- **Occurred:** 2026-08-31 (statistics toolset review)
- **Documented:** 2026-08-31 (Europe/Lisbon)
- **Verified:** 2026-08-31 — see [Evidence](#evidence)
- **Status:** Implemented; extends D20 without a schema migration
- **Recall tags:** PlateOS, analytics, date range, filters, insights, D38

## D38 — Derive richer statistics from existing meal snapshots

**Context.** The Phase 4 Stats view hardcoded a 14-day window and exposed two
averages, one calorie chart, and one macro chart. It had no range selection,
filters, meal counts, food ranking, or day-of-week analysis despite those
dimensions already being available in confirmed meal logs.

**Decision.** `GET /api/analytics/daily` accepts preset windows up to 366 days
or inclusive custom local dates, repeated source filters, and an optional
literal food-name filter. Every query remains scoped to the authenticated user
and bounded by `day_bounds()` local midnights. The response adds meal counts,
active-day/calendar-day summaries, source composition, and the top ten foods by
calories. The frontend provides 7/14/30/90-day presets, custom dates, source and
food filters, a selectable nutrient trend with target and moving-average lines,
macro energy share, weekday averages, source mix, and top-food drill-down.
Recharts remains lazy-loaded and no database migration or dependency is added.

Current profile targets are reference lines, not historical target claims.
Body-weight trends and target-era comparisons remain out of scope because the
database has neither body-measurement history nor effective-dated targets.

**Rejected.** Downloading raw meal rows for client aggregation (larger sensitive
payload and duplicated timezone logic); adding TimescaleDB or another analytics
library (unnecessary at household scale); inferring meal categories with an LLM
(nondeterministic and unsupported by persisted data).

## Evidence

| Check | Result |
| --- | --- |
| Backend | 81 tests passed, including range and summary boundaries |
| Frontend | 13 tests passed, including query, rolling average, macro share, and weekday helpers |
| TypeScript/build | `tsc --noEmit` and production/PWA build clean |
| API contract | OpenAPI exposes bounded days, custom dates, source list, and food query |
