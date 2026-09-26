# Decision Record — Deploy Review Flows and Readiness Improvements

- **Occurred:** 2026-09-26 (Europe/Lisbon)
- **Documented:** 2026-09-26T02:05:00+01:00
- **Verified:** 2026-09-26T02:05:00+01:00 (production checks listed below)
- **Status:** Deployed and runtime healthy; authenticated post-release browser QA pending
- **Recall tags:** PlateOS, production, deployment, AI, camera, readiness, backup, D55

## D55 — Deploy commit cb41cd7

### Context and decision

The release adds a saved label-image input, protects label parsing from stale
responses, improves camera error text and mobile Coach scrolling, updates the
DeepSeek Flash preset after a real vision round-trip, fixes sign-in transition,
and consolidates DB-backed readiness probes. It also retains earlier account
ownership, date-display, and meal-delete improvements from the working tree.

Commit `cb41cd77f84765028ddbfe2c7d0ed97e71745e02` passed 217 backend tests,
61 frontend tests, TypeScript checking, a production PWA build, and review of the
intended diff. The isolated local Compose stack passed readiness and browser UI
checks. The user authorized commit, push, and deployment to `diogoserver`.

Deploy this immutable commit into a fresh release directory. Preserve the
existing database and Settings volumes, loopback origin, and disabled optional
push worker. Update API first, check readiness, then update web.

### Verified deployment evidence

- Before rollout, `db`, `api`, and `web` were healthy on `539d17b`; the origin
  was `127.0.0.1:18100` and `/api/ready` returned ready.
- Fresh pre-change archive `plateos-20260926T004643Z.dump.age` was 45,770 bytes
  and passed its ciphertext SHA-256 check.
- The pushed commit was downloaded into a new commit-addressed release directory.
  Its source archive SHA-256 was
  `dd391285f7ebf44cec3040a8b689b988c2899e29f8829a991129075649d4d80c`.
  Compose configuration validated with the exact commit-tagged API/web images.
- API and web were built on `diogoserver` and replaced in that order. Both
  became healthy; PostgreSQL remained running. The web host publication stayed
  at `127.0.0.1:18100` and `/api/ready` returned ready.
- Schema remained `0007`. Unauthenticated profile and Settings requests returned
  401. The service worker returned 200, and the served web bundle contained the
  full release commit. The public hostname returned a Cloudflare Access 302.
- Post-change archive `plateos-20260926T010414Z.dump.age` was 45,770 bytes and
  passed its ciphertext SHA-256 check.
- At the final check, web and API had been healthy for five and six minutes;
  DB remained healthy. Liveness and readiness passed, and a filtered count of
  API `ERROR`/`Traceback` markers over the previous five minutes was zero.

### Limits and rollback

The checks above establish a healthy forward deployment, not database
recoverability. Neither archive was decrypted or restored in isolation. The D53
pre-migration backup sequencing anomaly, independent retention, monitoring,
RPO/RTO, and iPhone camera/offline checks remain open. The DeepSeek photo and
Coach round-trips were verified before this release; they were not repeated
against `cb41cd7` during this deployment. The browser-control helper could not
start for authenticated post-release UI QA; the live UI therefore remains
unverified on this exact commit.

The prior `539d17b` release directory and API/web images remain available. This
release introduces no migration, so an application rollback targets the same
schema `0007` without restoring the database. Do not delete volumes or archives.

### Alternatives considered

- Deploy from the dirty workstation tree: rejected because it lacks an immutable
  identity and could absorb unrelated files.
- Reuse the September 12 archive as the pre-change checkpoint: rejected because
  it is not a fresh recovery point for this release.
- Recreate PostgreSQL with API and web: rejected because neither schema nor DB
  configuration changed and the existing data must remain mounted.
