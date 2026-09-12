# Decision Record - Deploy Fiber and Official-Food Search

- **Occurred:** 2026-09-12 (Europe/Lisbon)
- **Documented:** 2026-09-12 (Europe/Lisbon)
- **Verified:** 2026-09-12T17:52:01+01:00 (authorized production deployment and read-only validation)
- **Status:** Implemented with an unresolved backup-gate discrepancy
- **Recall tags:** PlateOS, production, deployment, fiber, Ciqual, Swedish Food Agency, backup, D53

## D53 - Deploy commit 539d17b and retain the failed pre-migration gate as an incident

### Context

Commit `539d17bbdf9d0d53ab730c561fdbf4f2ef7a833b` adds the persisted
fiber target from D51 and the versioned official-food catalogues from D52. It
passed 214 backend tests, 58 frontend tests, TypeScript checking, the production
PWA build, deterministic catalogue regeneration, OpenAPI generation, and offline
Alembic SQL generation before deployment.

The authorized upgrade plan required a fresh encrypted schema-`0005` archive
before migrations `0006` and `0007`. The old backup image instead rejected the
database as unsupported because the schema was already `0007`; API and web were
also absent when inspected. Available Docker event evidence did not establish
which preceding operation advanced the schema or removed those containers.

### Decision

Record the failed pre-migration gate rather than treating an older archive as a
fresh checkpoint. Reconcile production forward on the already-migrated database,
deploy the commit-tagged API and web images, validate the changed behavior, and
create a checksum-verified post-migration encrypted archive. Retain the previous
release directory and images, but do not represent an application-only rollback
to `5cdce9a` as safe against schema `0007`.

### Verified Outcome

- The release archive SHA-256 is
  `85579c38347caee47af64eb7ceb18aa8936dc6532fe08b8028f71c53c72d3e7b`.
- API and web run the full `539d17bbdf9d0d53ab730c561fdbf4f2ef7a833b`
  tag; PostgreSQL 17, API, and web were healthy after 18 minutes at the final
  check. Both persistent volumes remained present and the optional push worker
  remained disabled.
- Database schema is `0007`. The sole existing profile has a 25 g fiber target
  with no null fiber values; existing food-item and meal-log counts remained zero.
  All five food density columns have precision 14 and scale 4.
- Production Ciqual and Swedish Food Agency searches returned proof-bound records
  with the shipped source/version identifiers. The daily summary returned the
  25 g fiber target and zero consumed fiber.
- Liveness and DB-backed readiness passed. Password login succeeded and issued a
  Secure, HttpOnly, SameSite=Strict cookie; unauthenticated profile access and
  bearer access to cookie-only settings returned 401.
- The PWA service worker returned 200 and the web bundle contained the full
  release identity. OpenAPI exposed 32 paths and recent API/web logs contained no
  error markers.
- The origin remained bound only to `127.0.0.1:18100`; a LAN-origin request timed
  out and the external HTTPS route returned the expected Cloudflare Access 302.
- Post-migration archive `plateos-20260912T163200Z.dump.age` is 44,302 bytes and
  passed its ciphertext SHA-256 check.

### Consequences and Limits

- Production now exposes D51 and D52 behavior on schema `0007`.
- There is no fresh schema-`0005` checkpoint for this deployment. Older encrypted
  archives exist, but their restore point predates this operation and no
  production archive has passed an isolated restore drill.
- The prior API/web images remain useful diagnostic artifacts, not a verified
  application-only rollback path. Any database restoration is destructive,
  requires separate authorization, and must state the selected recovery point and
  expected data loss.
- The cause and exact duration of the unexpected migration/container absence are
  unresolved. Monitoring, scheduled independently retained backups, RPO/RTO,
  authenticated edge traversal, VPN/IPv6 bypass checks, real push delivery, and
  remaining physical iPhone flows remain open.

### Rejected Alternatives

- Claim the 2026-09-02 schema-`0005` archive as the required fresh pre-change
  backup: rejected because it is a different recovery point.
- Downgrade the live database to rerun the planned sequence: rejected as an
  unnecessary destructive mutation after additive migrations had completed.
- Restart `5cdce9a` against schema `0007`: rejected because backward application
  compatibility with the new non-null profile field was not established.
- Omit the anomaly after successful forward recovery: rejected because it would
  conceal a failed production safety gate and overstate rollback confidence.
