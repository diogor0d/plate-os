# Decision Record - Production Hardening

- **Occurred:** 2026-08-25 (pre-homelab production review)
- **Documented:** 2026-08-25T16:21:41+01:00 (Europe/Lisbon)
- **Verified:** 2026-08-25 - local Docker evidence only; see [Evidence](#evidence)
- **Status:** Implemented and runtime-verified locally. Homelab ingress,
  production deployment, and production recovery operations remain unverified.
- **Recall tags:** PlateOS, production, Compose, secrets, readiness, age, backup,
  restore, homelab, August 2026

This record continues the numbering from D28 in
`2026-08-25-meal-log-integrity-hardening.md`.

## D29 - Production configuration fails closed

**Context.** Development defaults (`changeme`, an insecure cookie, and local DB
credentials) were convenient but could silently reach production.

**Decision.** `PLATEOS_ENVIRONMENT=production` rejects default, short, or
low-diversity application/signing/database credentials; short optional bearer
tokens; non-Secure cookies; and incomplete/non-async PostgreSQL URLs. Compose
forces production mode and Secure cookies. Secrets are loaded as UTF-8 files
from `/run/secrets`; Compose mounts a protected host directory rather than
putting values in container configuration. A dedicated host GID is added as a
supplementary group only to secret consumers; root/group `0750` directories and
`0440` files remain readable to non-root containers without world access.

Development and tests retain explicit local defaults. This avoids making the
workstation workflow depend on production secret infrastructure.

**Rejected.** Removing all defaults globally (needlessly breaks development);
passing secrets through Compose environment variables (visible in container
configuration); selecting a secret-management product before the homelab's
authoritative mechanism is decided.

## D30 - Readiness proves the current data contract

**Decision.** `/api/health` remains dependency-free liveness. `/api/ready`
queries the single profile and columns introduced by migration `0002`, returning
503 without database details on any failure. Production startup fails when
profile seeding cannot reach the DB; development may still boot while a local DB
starts. DB, API, and web Compose dependencies use health conditions.

**Rejected.** Process-only health for every service (admits traffic before
migrations/data are usable); exposing raw DB errors (unnecessary information
leak); querying only `SELECT 1` (does not prove expected schema).

## D31 - The origin and containers use least privilege

**Decision.** Web publishes only on fixed IPv4 loopback `127.0.0.1`, with the
host port configurable. PostgreSQL
has a separate internal network and no host port. API and Caddy run as UID 10001;
PostgreSQL uses its image UID 70. Runtime roots are read-only with explicit
volumes/tmpfs, all capabilities are dropped, new privileges are disabled, and
Docker logs are bounded. Caddy sets a restrictive CSP and browser security
headers while preserving camera, PWA, and SSE behavior. Caddy and FastAPI both
cap request bodies at 2 MB; the base64 label field is capped below that for JSON
overhead.

No CPU, memory, PID, or I/O limits are set until observed normal and peak use can
justify them. TLS and HSTS remain the external proxy's responsibility.

**Rejected.** Wildcard host publication; placing DB/web/API on one network;
guessing resource limits; setting HSTS at a plain-HTTP origin without owning the
external hostname policy.

## D32 - Production artifacts are pinned and reproducible

**Decision.** Python, Node, Caddy, and PostgreSQL bases use multi-platform index
digests. Python's complete production resolver output is locked in
`backend/requirements.lock`; frontend builds use `npm ci` and its integrity
lock, with lifecycle scripts disabled. Build contexts exclude local environments,
dependencies, tests, and secrets. Locally built app images carry the clean source
commit as their tag and their resulting image IDs must be recorded at deployment.

**Limitation.** Application images are not yet published to an immutable
registry. A recorded clean source revision plus digest-pinned inputs and retained
local image ID is the current boundary.

## D33 - Backups encrypt before durable storage; restores are isolated

**Decision.** The opt-in backup job uses PostgreSQL 17 `pg_dump` custom format
and passes it through a FIFO to age 1.3.1. No plaintext dump reaches the backup
filesystem. The age release archive is version/checksum pinned. Ciphertext gets
a SHA-256 sidecar; automatic retention is deliberately absent until RPO,
destination, and policy are chosen. The decryption identity never belongs on the
production host.

The destination is mandatory, and the job refuses an uninitialized or
unsupported schema and a database without exactly one PlateOS profile. The
checksum is published before the final archive name so interrupted publication
cannot leave a normal-looking ciphertext without its sidecar.

PostgreSQL 17 runtime testing showed that `pg_dump --file=<FIFO>` attempts to
`fsync` the named pipe and fails. The dump and restore scripts therefore attach
the FIFO through standard output/input redirection while retaining explicit
producer and consumer status checks and partial-output cleanup.

`docker-compose.restore.yml` requires a unique separate project ID, internal
network, fixed restore database name, and no host ports. Restore requires an
explicit phrase and refuses another or non-empty DB target. Source revisions
`0001` and `0002` are accepted so a pre-upgrade backup can prove the normal
migration path. Compose requires successful restore completion before starting a
restore-only API, which migrates to head and verifies readiness, unauthenticated
denial, login, and representative reads with new drill credentials.

A synthetic local backup and isolated application restore completed
successfully. This proves the tooling path, not that production data is
protected. Production scheduling, off-host isolation, monitoring, retention,
destination, and restore evidence remain `TBD`/`UNVERIFIED`.

**Rejected.** Archiving a live PostgreSQL volume (not application-consistent);
password-encrypted dumps with a production-host decryption secret; automatic
pruning before retention is decided; restore into the production Compose project.

## Evidence

| Check | Result |
| --- | --- |
| Backend tests | 45 passed, including fail-closed settings, weak-pattern rejection, secret files, request limits, and readiness |
| Frontend | 8 tests passed; strict TypeScript production build and PWA generation passed; production dependency audit found 0 vulnerabilities |
| Python compile | Application, Alembic, tests, and restore verifier compile cleanly |
| Compose parsing | Main and isolated restore definitions pass `config --quiet` with protected local test paths |
| Image builds | API, web, and backup images build from digest-pinned bases and locked dependencies |
| Runtime privilege | DB, API, and web run healthy as non-root with read-only roots, all capabilities dropped, and `no-new-privileges` enabled |
| Live migration | Populated PostgreSQL revision `0001` upgraded to `0002`; all five density snapshots and the mutation ledger were verified |
| HTTP boundary | Health/readiness, auth, Secure/HttpOnly/SameSite cookie, security headers, absent production CORS, direct/proxied 2,000,001-byte rejection, and unbuffered SSE error delivery passed |
| Idempotency race | Concurrent identical mutation keys returned one meal ID; changed reuse and replay after deletion returned 409 |
| Encrypted backup | Refused an uninitialized DB; the valid synthetic custom-format dump encrypted directly to age ciphertext, SHA-256 passed, and no plaintext dump remained |
| Isolated restore | Unique internal-only project restored the ciphertext, migrated to head, passed API/auth/read verification, matched source integrity counts, refused repeat restore, and detected large-object-only and `pg_catalog`-only contaminated targets |
| Dependency lock | Python 3.12 resolves the recorded production versions and `pip check` passes |
| Source hygiene | `git diff --check` clean; backend/frontend Docker contexts exclude local secrets and dependencies |
| Base provenance | Registry index digests captured for Python 3.12 slim, Node 22 Alpine, Caddy 2 Alpine, PostgreSQL 17 Alpine |
| age provenance | GitHub release v1.3.1 archive SHA-256 pinned for x86_64 and arm64 |

The runtime checks used Docker Desktop Engine 29.7.2, loopback-only test ingress,
fresh generated credentials, and synthetic data. They do not verify homelab
capacity or listeners, external TLS/Cloudflare routing, production secret and
backup stores, monitoring, retention, physical iOS behavior, or real LLM calls.
