# Decision Record — Constrained AI Harness

- **Occurred:** 2026-08-31 (contextual AI/action request)
- **Documented:** 2026-08-31 (Europe/Lisbon)
- **Verified:** 2026-08-31 — see [Evidence](#evidence)
- **Status:** Implemented; extends D9 and corrects the meal-output contract under D13
- **Recall tags:** PlateOS, AI harness, generative UI, context, actions, goals, D39

## D39 — Models propose typed UI blocks; PlateOS owns capabilities and writes

**Context.** The Coach returned prose plus one meal-only proposal. It could not
use the active application surface, explain the current Stats view, draft goal
changes, or render safe navigation. The meal contract also asked the LLM for
scaled totals even though PlateOS ignored them and recomputed from density,
contradicting the application's arithmetic invariant.

**Decision.** Chat uses a versioned, discriminated output contract with four
allowlisted blocks: `meal_proposal`, `goal_draft`, `analytics_navigation`, and
`evidence_insight`. The server builds bounded user-scoped context from today's
budget, a selected analytics range, top foods, source mix, recent immutable
meal snapshots, current targets, and explicit data limitations. Body
measurements enter context only in goals mode. The frontend runtime-validates
every block and renders fixed React components; model output cannot provide a
URL, endpoint, method, database identifier, component name, or generic payload.

Meal drafts carry only per-100 density and quantity and enter the existing
Proposal Card confirmation path. Goal drafts compare current and proposed
targets and can be saved only through a separate explicit online action in the
review card. Analytics actions can only set bounded local filters and navigate
to Stats. The route persists chat messages and validated blocks, but never
writes meals or profiles itself. Provider errors exposed over SSE are
sanitized. `LLMService` now includes the exact JSON Schema and bounds output.

The harness surfaces logging coverage as a first-class limitation so absent
logs are not interpreted as zero intake. It also offers an AI-estimate audit
and contextual entry points from Today and the active Stats view.

**Rejected.** Arbitrary model tool calls or HTTP actions (confused-deputy and
prompt-injection risk); model-generated React/HTML (untrusted executable or
presentation code); direct goal/meal mutation (violates explicit confirmation);
raw history uploads (unnecessary sensitive context); autonomous medical or
weight-loss target claims (required data is not stored).

## Evidence

| Check | Result |
| --- | --- |
| Backend | 93 tests passed, including strict blocks, confirmation constants, invalid actions, context ranges, and bounded goal caveats |
| Frontend | 20 tests passed, including runtime block rejection, constrained analytics actions, and strict calendar validation |
| TypeScript/build | `tsc --noEmit` and production/PWA build clean |
| Mutation boundary | Chat route writes only `ChatMessage`; meal/profile writes remain in explicit review components |
