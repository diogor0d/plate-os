# Add Daily Fiber Target

**Date:** 2026-09-11T20:25:00+01:00

**Status:** Accepted and implemented

**Decision:** D51

## Context

PlateOS already stores, scales, aggregates, and analyzes dietary fiber, but user
profiles define targets only for calories, protein, carbohydrates, and fat. The
home target display therefore makes fiber intake appear untracked, and goal
drafts cannot propose a fiber objective.

## Decision

Add `user_profile.target_fiber_g` as a non-null integer target. Migration `0006`
backfills existing profiles with 25 g and new profiles use the same default.
Profile updates accept values from 0 through 1,000 g; constrained AI goal drafts
must include all five targets and limit fiber proposals to 10 through 100 g.

Daily summaries expose fiber target, consumed, and remaining values. The home
target bars and analytics compare fiber intake with the current target. Assistant
context includes current and remaining fiber, and explicit goal confirmation can
persist a proposed fiber target.

Like the existing four targets, fiber is a current profile value rather than
effective-dated history. Historical analytics therefore compare recorded intake
against the user's current target.

## Consequences

- Existing profiles receive a visible 25 g daily fiber target after migration.
- Missing source fiber remains explicitly flagged; a zero placeholder can still
  undercount intake until the candidate is reviewed and corrected.
- Readiness probes the new column, and backup/restore guards accept schema
  revision `0006`.
- The goal-draft contract now requires five targets, so application and client
  code must deploy together.

## Rejected Alternatives

- A display-only 25 g constant was rejected because it could not be customized,
  persisted, included in AI drafts, or represented consistently through the API.
- Treating missing food fiber as known zero was rejected; source omissions remain
  visible review issues.
- Effective-dated target history was deferred because all existing targets use
  current-value semantics and changing that model is a separate feature.
