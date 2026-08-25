# Decision Record — Meal-Log Integrity Hardening

- **Occurred:** 2026-08-25 (post-MVP audit remediation)
- **Documented:** 2026-08-25T12:38:44+01:00 (Europe/Lisbon)
- **Verified:** 2026-08-25 — see [Evidence](#evidence)
- **Status:** Implemented and runtime-verified locally; physical iOS validation
  and production deployment remain pending.
- **Recall tags:** PlateOS, idempotency, offline queue, nutrition snapshots, rounding, timezone, August 2026

This record continues the numbering from D23 in
`2026-08-21-verification-and-phase4.md`.

---

## D24 — Meal writes use a durable idempotency ledger

**Context.** A POST can commit successfully while its response is lost. The
Dexie queue would then replay the request and create a duplicate. Keeping a
client key only on `meal_logs` would not be sufficient because hard deletion
would erase the key and a delayed replay could recreate the deleted meal.

**Decision.** The first-party client assigns one UUID per proposed item before
its first POST and reuses that UUID for every retry. `meal_log_mutations` uses
`(user_id, client_mutation_id)` as its primary key and stores a SHA-256
fingerprint of the canonical request plus the resulting meal ID. Creation of
the meal and ledger row is one transaction. Concurrent conflicts roll back and
load the winner. Reusing a key with changed data returns 409.

The meal foreign key uses `ON DELETE SET NULL`, retaining a tombstone after a
hard delete. Replaying a consumed key after deletion returns 409 rather than
resurrecting the meal. The request field remains optional for compatibility
with the documented Apple Shortcuts API; omitted keys are not replay-safe.

**Rejected.** A key only on `meal_logs` (deletion loses the record); soft-delete
of all meals (changes every read/aggregation path and retains user data); a
frontend-only mutex (cannot coordinate tabs or ambiguous server responses).

## D25 — Meal logs retain immutable source density

**Context.** PATCH previously multiplied already-rounded totals by the new
quantity ratio. Once a small value rounded to zero, no later quantity could
recover it.

**Decision.** Each meal stores an immutable four-decimal per-100 snapshot for
all five nutrition fields. POST and PATCH compute from that snapshot and a
two-decimal quantity. Calculated totals are widened and remain one-decimal
application results. Existing rows are backfilled from
`calculated_total * 100 / quantity`; the migration aborts if any historical
quantity is non-positive.

**Limitation.** Historical source precision was already lost. Backfill
preserves the old effective proportional behavior but cannot recover a small
nutrient that had rounded to zero.

## D26 — Positive nutrition ties round half-up everywhere

**Context.** Python `round` uses ties-to-even while JavaScript `Math.round`
rounds positive ties up. Proposal totals could therefore differ from persisted
totals.

**Decision.** Server arithmetic converts canonical operands to `Decimal`
before multiplication and uses `ROUND_HALF_UP`. The TypeScript mirror uses the
same positive-half-up rule with a bounded epsilon appropriate to four-decimal
density and two-decimal quantity inputs. Both suites carry the same boundary
vectors, including 209 kcal/100g at 5g → 10.5 kcal.

## D27 — Confirmation time belongs to the queued payload

**Context.** Dexie stored a local `createdAt`, but the payload omitted
`logged_at`. Replaying after local midnight assigned the flush time and moved
the meal to another day.

**Decision.** The client stamps one aware UTC `logged_at` before the first POST
and stores it in the payload. Legacy queue rows derive the timestamp from their
existing `createdAt` and receive a UUID atomically in IndexedDB before sending.
Same-context flushes share one promise; server idempotency is the cross-context
boundary.

Only network, 429, and 5xx failures queue. Direct permanent 4xx responses keep
the Proposal Card open. A queued row later rejected with a permanent 4xx moves
to a visible failed state, does not block later rows, and requires explicit
discard.

## D28 — Validation matches persisted representation

**Decision.** Meal quantities are 0.01–10,000 with at most two decimals;
per-100 nutrition is finite and domain-bounded; strings mirror database
lengths; custom meals require a name and density; and food-library references
must not also submit ignored density. Create/PATCH timestamps must carry an
offset. Profile timezones are validated as IANA identifiers, and `tzdata` is a
runtime dependency so the documented Windows development environment behaves
like the Linux container.

---

## Evidence

| Check | Result |
| --- | --- |
| Backend tests | 45 passed, including 6 meal-integrity tests |
| Frontend tests | 8 passed (nutrition mirror + IndexedDB queue) |
| TypeScript | `tsc --noEmit` clean |
| Alembic | Populated PostgreSQL revision `0001` upgraded to `0002`; density backfill and mutation ledger verified |
| Timezone runtime | `ZoneInfo("Europe/Lisbon")` succeeds on Windows after declared install |
| OpenAPI | 13 paths; meal timestamps are date-time and daily query parameters are dates |
| Live HTTP idempotency | Two concurrent identical POSTs returned one meal ID; changed reuse and replay after delete returned 409 |
| Compose runtime | Hardened DB, API, and web became healthy; restored backup retained the meal and mutation tombstone |

**Still required before release:** repeat the physical iOS offline/reconnect
flow. Production deployment and migration require their own authorized backup,
rollback, ingress, and post-deployment evidence.
