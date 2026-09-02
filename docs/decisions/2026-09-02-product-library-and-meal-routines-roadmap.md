# Decision Record — Product Library and Meal Routines Roadmap

- **Occurred:** 2026-09-02 (architecture approved and implemented)
- **Documented:** 2026-09-02 (Europe/Lisbon)
- **Verified:** 2026-09-02 (local tests, production build, PostgreSQL migrations, and review stack)
- **Status:** Implemented; real push delivery, iOS, and production deployment remain unverified
- **Recall tags:** PlateOS, product library, barcode, routines, schedules, occurrences, notifications, offline, D41

## D41 — Reviewed products and scheduled routines remain proposals until confirmed

### Context

PlateOS currently has a global `food_items` table containing both user-entered
items and Open Food Facts (OFF) barcode results. A local barcode miss causes the
OFF result to be inserted immediately. There are no separate product-candidate,
routine, schedule, occurrence, or notification domains. D36 kept the food
library global while making meals, chat, and mutation ledgers account-scoped.

The next roadmap needs a trustworthy, reusable product library and recurring
meal planning without weakening D39's constrained proposal boundary, D24's
replay safety, or D14's timezone rules.

### Decision

The product library is barcode-first and contains products a user has reviewed
and accepted. Barcode decoding remains deterministic through the D7 scanner
path; an LLM must not infer or decode a barcode.

A barcode lookup follows this order:

1. Search the accepted local product library.
2. On a miss, request an external OFF candidate.
3. If OFF is missing, incomplete, stale, disputed, or the user requests a
   package check, offer nutrition-label vision as the next acquisition path.

External and vision-derived candidates are proposals, not accepted products.
They remain structurally separate from the reviewed library until the user
reviews and explicitly confirms persistence. Name search is an explicit user-
selected fallback when barcode lookup is unavailable or unsuccessful, not an
automatic substitute for a barcode match. Candidate acquisition may prefill an
editable Proposal Card but cannot silently save a product or meal.

Meal planning uses separate concepts:

- A **routine** is a reusable meal intention or template.
- A **schedule** attaches recurrence rules and local wall-clock timing to a
  routine.
- An **occurrence** represents one due instance of a schedule and its lifecycle.
- A **meal log** remains evidence of food the user explicitly confirmed as
  consumed; it is not a plan, reminder, or generated occurrence.

Routines support two explicit plan modes. A rough plan preserves an
intentionally incomplete meal idea for later review. A defined plan contains
structured accepted products and quantities. Neither mode writes meal logs
automatically. Acting on either mode produces an editable Proposal Card, and
only user confirmation enters the existing meal-log persistence path.

Recurrence is defined in the user's wall-clock terms using an IANA timezone,
not as repeated fixed UTC durations. The server derives due state, next due
time, and countdown values from the schedule and authoritative current time;
clients do not persist an independently ticking countdown as truth.

Notifications use standards-based Web Push behind a transport-neutral intent
and delivery outbox. A separate worker owns the VAPID private key, sends only
generic lock-screen text, and treats a push-service 2xx as accepted rather than
proof that a device displayed it. Subscription endpoints are cookie-session-only,
encrypted at rest, and restricted to public HTTPS port 443 destinations. The
routine domain does not depend on Web Push, so another transport such as ntfy
can be added without changing schedules or occurrences.

Before product or routine mutations can rely on offline replay, the Dexie queue
must be partitioned by account. A queued mutation must retain its owning account
and may flush only under that same authenticated account. This is a prerequisite
created by D36, not an implementation claim in this record.

### Rationale

- A reviewed local match is faster and more trustworthy than repeatedly using
  crowd-sourced or inferred data.
- Separating candidates from accepted products makes provenance and user
  consent explicit and avoids treating retrieval as approval.
- Deterministic barcode decoding prevents probabilistic identity errors; vision
  is useful for nutrition extraction only after product lookup fails.
- Separate routines, schedules, occurrences, and meal logs preserve the
  distinction between intent, recurrence, a due event, and confirmed history.
- Wall-clock recurrence matches how people describe meals and avoids drift when
  UTC offsets change.
- Server-derived countdowns avoid stale or contradictory client state.
- Transport-neutral reminder intents isolate recurrence from delivery policy,
  while an opt-in Web Push worker provides a standards-based first transport.

### Rejected Alternatives

- Treat OFF lookup results as accepted products on retrieval: external data has
  not been reviewed and may be incomplete or wrong.
- Store external candidates and accepted products as indistinguishable rows:
  this erases approval and provenance boundaries.
- Use vision or an LLM to decode barcodes: product identity should remain
  deterministic.
- Make name search the automatic primary fallback: ambiguous text matching must
  be an explicit user choice.
- Represent schedules as future meal logs or log meals when reminders fire:
  plans are not evidence of consumption and this violates Proposal Card
  confirmation.
- Model recurrence as fixed UTC intervals or make the client countdown
  authoritative: both produce incorrect or stale wall-clock behavior.
- Put delivery inside the API: this would expose the VAPID private key to a
  broader process and couple request latency to push providers.
- Send meal details in notifications: lock-screen disclosure is unnecessary;
  generic text is safer for a household nutrition application.

### Consequences

- Product acceptance and meal logging remain separate explicit mutations, even
  when one review flow presents both.
- Candidate provenance and review state must be representable without polluting
  the accepted library.
- Defined routines reference structured product data, while meal logs continue
  to preserve immutable nutrition snapshots under D25.
- Schedule evaluation needs timezone-aware server logic and test coverage for
  civil-time transitions before release.
- Occurrences require their own lifecycle and idempotency rules; they cannot
  borrow meal-log semantics implicitly.
- Offline work must not cross household-account boundaries after logout or
  account switching.
- Push-service acceptance is recorded separately from device display; PlateOS
  does not claim an end-to-end delivery guarantee.

### Phased Order

1. Partition offline mutation storage and replay by authenticated account.
2. Introduce the accepted-product boundary and migrate direct external caching
   without claiming cached candidates were user-approved.
3. Build barcode-first resolution: local accepted product, OFF candidate, then
   vision, with explicit name search and user-confirmed product persistence.
4. Add rough and defined routines without recurrence or automatic meal writes.
5. Add schedules and occurrences with wall-clock timezone recurrence and
   server-derived due/countdown state.
6. Add transport-neutral intents and an isolated, opt-in Web Push worker; retain
   ntfy as a possible later transport.

### Unresolved Policy Choices

- Candidate caching and explicit external name-search ranking are deferred;
  current OFF and vision candidates are ephemeral.
- Editing schedule fields after creation and snoozing occurrences are deferred;
  schedules can currently be enabled or disabled and occurrences completed or
  skipped.
- Real iOS standalone permission, push-provider acceptance, and lock-screen
  display behavior require physical-device evidence.
- A later ntfy transport remains optional; it must consume the existing intent
  domain rather than changing routine semantics.

### Implementation Status

Implemented in migrations `0004` and `0005`, the product/routine APIs, account-
partitioned Dexie v4 queues, Plan and Product Library workspaces, constrained AI
`meal_plan_draft`, and an opt-in Web Push worker. Important enforcement details:

- Legacy unreviewed products are retained as archived rows instead of deleted.
- OFF and vision results carry short-lived, account-bound HMAC acceptance proofs;
  edited candidates fall back to manual provenance.
- Composite account foreign keys protect routine, schedule, occurrence,
  notification, occurrence-log, and meal-log relationships.
- Occurrence confirmations persist exact mutation IDs in IndexedDB before the
  first meal POST and resume idempotently after reload or network ambiguity.
- Queue replay sends the expected account UUID and the API rejects cookie/account
  mismatches, including mid-flush account switches.
- The worker derives a bounded reminder horizon independently of agenda views,
  leases deliveries with `SKIP LOCKED`, retries transient failures, disables
  expired subscriptions, and does not receive API/session/LLM secrets.

Local verification passed with 184 backend tests, 43 frontend tests, strict
TypeScript, the production PWA build, a healthy Docker review stack, and a
populated PostgreSQL `0004 → 0005` upgrade. Real push-provider delivery, iOS
standalone behavior, and production deployment are explicitly not verified.
