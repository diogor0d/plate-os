# Production Operations

## Status and evidence boundary

- Desired state: `INTENDED`; no PlateOS production deployment is recorded.
- Intended target: the operator's approved Ubuntu Docker host. Hostnames,
  addresses, and tunnel specifics live in the operator's private homelab
  inventory, deliberately outside this public repository.
- `VERIFIED` locally on 2026-08-25: hardened images/Compose, populated migration
  `0001` to `0002`, request and auth boundaries, synthetic encrypted backup, and
  isolated application restore. This is workstation evidence, not production
  deployment or recoverability evidence.
- Target runtime expectation (private snapshot 2026-07-16): x86_64 Linux host
  with Docker Engine and Compose available. Re-verify actual versions during
  the authorized pre-deployment inspection.
- `UNVERIFIED`: current capacity, checkout path, free listener, firewall,
  tunnel/proxy route, access policy, monitoring, secret store, backup
  destination, schedule, retention, RPO, RTO, and production restore evidence.
- Before choosing `PLATEOS_PORT`, perform an authorized current-listener check
  on the target host and record the binding in an exposure matrix; never assume
  a documented or previously seen port is still free.

This runbook prepares safe commands but does not authorize server access,
deployment, migration, backup access, DNS, firewall, Cloudflare, or deletion.

## Intended architecture

| Service | Runtime boundary | Persistence and access |
| --- | --- | --- |
| `db` | Pinned PostgreSQL 17, UID 70, read-only root, no capabilities | `pgdata`; internal `data` network only; no host port |
| `api` | Pinned non-root Python image, read-only root, no capabilities | Secret files read-only; `app_settings` volume for Settings-screen state; `data` and `app` networks; outbound access for OFF/LLM |
| `web` | Pinned non-root Caddy image, read-only root, no capabilities | `app` network; fixed IPv4-loopback address and configurable port |
| `backup` | Opt-in operations profile, pinned PostgreSQL client plus verified age binary | Reads DB; writes encrypted dumps to a configured bind destination |

Docker logs are bounded to three 10 MB files per service. CPU, memory, PID, and
I/O limits remain `TBD` until normal and peak usage are measured. The external
TLS proxy must reach only the loopback web origin. The database never joins the
ingress-facing network.

`GET /api/health` is process liveness. `GET /api/ready` returns success only
when the current schema can be queried and exactly one profile exists. Compose
orders DB, API, and web startup through those readiness checks.

## Secret files

`PLATEOS_SECRETS_DIR` must be outside the Git checkout, owned by root and a
dedicated host group, mode `0750`; contained files must be `root:<secret-group>`
mode `0440`. Compose adds that numeric `PLATEOS_SECRETS_GID` as a supplementary
group only to DB, API, and backup. This permits non-root consumers to read their
bind mounts without making secrets world-readable. The directory is an
injection mechanism, not an authoritative secret store; storage, backup,
rotation, and recovery remain `TBD`.

| File | Consumer | Requirement |
| --- | --- | --- |
| `plateos_database_password` | DB, API, backup | Unique, random, at least 24 characters |
| `plateos_app_password` | API | Unique, at least 16 characters; store in password manager |
| `plateos_session_secret` | API | Random, at least 32 characters |
| `plateos_llm_api_key` | API | Optional; only for a provider requiring a key |
| `plateos_api_token` | API | Optional; random, at least 32 characters; full API access |
| `plateos_backup_recipient` | Backup job | age public recipient only, never the private identity |

Production validation rejects defaults, low-diversity secrets, insecure
cookies, short optional API tokens, and incomplete/non-async PostgreSQL URLs.
The age private identity must be generated and recovered independently of the
production host and backup destination.

On a trusted recovery workstation with age installed:

```bash
umask 077
age-keygen -o plateos-backup-identity.txt
age-keygen -y plateos-backup-identity.txt > plateos_backup_recipient
```

What it does: Creates the private decryption identity and derives the public
recipient used by the production backup job. Protect and independently back up
the identity; transfer only `plateos_backup_recipient` to production.

After production access, the host group, and the secret path are explicitly
authorized, generate credentials without putting values in command arguments:

```bash
sudo groupadd --system plateos-secrets
sudo install -d -o root -g plateos-secrets -m 0750 /approved/path/plateos-secrets
sudo openssl rand -base64 -out /approved/path/plateos-secrets/plateos_database_password 32
sudo openssl rand -base64 -out /approved/path/plateos-secrets/plateos_app_password 24
sudo openssl rand -base64 -out /approved/path/plateos-secrets/plateos_session_secret 48
sudo chown root:plateos-secrets /approved/path/plateos-secrets/*
sudo chmod 0440 /approved/path/plateos-secrets/*
getent group plateos-secrets
```

What it does: Creates a dedicated supplementary group and three independent
random credentials readable only by root and that group, then prints group
metadata needed for `PLATEOS_SECRETS_GID`. This changes host accounts/files and
requires an approved GID, secret path, ownership, recovery plan, and explicit
production authorization. Reuse an approved dedicated group instead of running
`groupadd` when one already exists.

## Non-secret configuration

Production `.env` should contain only non-secret Compose settings:

- `PLATEOS_IMAGE_TAG`: full clean source commit used for the local builds.
- `PLATEOS_PORT`: currently `TBD`; select only after an authorized listener check.
- `PLATEOS_SECRETS_DIR`: approved protected host directory.
- `PLATEOS_SECRETS_GID`: numeric dedicated group allowed to read secret files.
- `PLATEOS_BACKUP_DIR`: approved encrypted-backup staging/destination path.
- `PLATEOS_BACKUP_UID` and `PLATEOS_BACKUP_GID`: owner of that destination.
- `POSTGRES_USER` and `POSTGRES_DB`: non-secret logical names.
- LLM endpoint/model, OFF endpoint, timezone, and profile seed defaults.

Do not place application, database, LLM, API-token, or backup private keys in
`.env`. Compose forces `PLATEOS_ENVIRONMENT=production`, Secure cookies, and the
host address `127.0.0.1`; only the host port is configurable.

## Runtime provider settings

LLM providers per task (coach text, label vision) and the Open Food Facts base
URL are edited in the app's Settings screen at runtime and stored as JSON in
the `app_settings` volume (`PLATEOS_RUNTIME_SETTINGS_FILE`). Provider API keys
are write-only over the API and are never included in database backups;
consequences:

- After any restore drill or disaster recovery, re-enter provider credentials
  in Settings; env defaults apply until then.
- Settings mutations require the browser session cookie. The Apple Shortcuts
  bearer token cannot read or change them (D35).
- Use Settings → Test connection to validate a swap before relying on it; a
  bad endpoint fails loudly there instead of silently breaking chat/vision.

## Preparation checks

Run on a workstation or authorized deployment host without printing rendered
configuration:

```bash
docker compose config --quiet
docker compose config --services
docker compose config --images
```

What it does: Validates Compose syntax and lists the reviewed service/image
surface without emitting interpolated configuration or secret contents.

Run application verification before building:

```bash
cd backend
.venv/Scripts/python -m pytest
cd ../frontend
npm test
npm run build
```

What it does: Runs backend contracts, frontend math/offline tests, strict
TypeScript checking, the production frontend build, and PWA generation.

Build only from a clean, recorded source revision:

```bash
docker compose --profile operations build --pull
```

What it does: Creates local API, web, and operations images from digest-pinned
bases and locked dependencies. It changes the local Docker image store; on a
production host it requires explicit build/deployment authorization. Record the
resulting image IDs and retain the previous known-good images.

## Backup procedure

The backup job uses `pg_dump --format=custom` for a transactionally consistent
database export. A FIFO passes the dump directly to age; no plaintext dump is
written to the backup filesystem. A SHA-256 sidecar is written after encryption,
and the ciphertext becomes visible at its final path only after that sidecar.
The job refuses an uninitialized/unsupported schema or anything other than the
single PlateOS profile.

After backup access, destination, recipient, ownership, and capacity are
authorized and verified:

```bash
docker compose --profile operations run --rm backup
```

What it does: Reads the live PlateOS database and creates one encrypted
`plateos-<UTC timestamp>.dump.age` plus checksum in `PLATEOS_BACKUP_DIR`. It does
not prune older backups. Reading/exporting production data requires explicit
authorization even though the database is not mutated.

Validate the new ciphertext without decrypting it:

```bash
cd /approved/backup/path
sha256sum -c plateos-<UTC timestamp>.dump.age.sha256
```

What it does: Detects ciphertext corruption against the generated checksum. It
does not establish decryptability, application usability, off-host isolation,
retention, or restore success.

If a killed host/container leaves `.plateos-backup.lock`, first verify that no
backup job remains active:

```bash
docker compose --profile operations ps --all backup
```

What it does: Lists only the backup service's current and exited containers. It
does not print container environments or secret contents.

Only after confirming no backup is running and preserving failure evidence:

```bash
rmdir /approved/backup/path/.plateos-backup.lock
```

What it does: Removes only the empty concurrency lock so future backups can run.
This changes production backup state and requires explicit authorization and an
exact reviewed destination path; never remove it while a backup may be active.

Do not call PlateOS backed up until a scheduled job, monitored age/failure,
approved retention, an independently protected copy, and the restore drill below
have production evidence. Those operational gates remain `UNVERIFIED` or `TBD`;
the successful synthetic local drill does not satisfy them.

## Isolated restore drill

Run the drill on an authorized recovery workstation or isolated host, never on
the production Compose project. `docker-compose.restore.yml` requires a unique
drill ID in its `plateos-restore-<ID>` project name, uses an internal-only
network, publishes no ports, and creates a project-specific volume. Its restore
script refuses any DB host/name other than `restore-db` / `plateos_restore`,
refuses a non-empty DB, and requires the exact confirmation phrase.

Prepare a temporary root-owned, dedicated-group directory with mode `0750` and
files mode `0440`, containing:

- `plateos_restore_identity`: recovered age private identity.
- `plateos_restore_database_password`: new random drill-only DB password.
- `plateos_app_password`: new drill-only application password.
- `plateos_session_secret`: new random drill-only signing secret.

The encrypted archive must also be readable by the restore supplementary group.
Never reuse production credentials in the drill. Set path/confirmation metadata
in the current shell, not secret values:

```bash
export PLATEOS_RESTORE_SECRETS_DIR=/approved/temporary/restore-secrets
export PLATEOS_RESTORE_SECRETS_GID=<numeric-restore-group-id>
export PLATEOS_RESTORE_ARCHIVE=/approved/backup/path/plateos-<timestamp>.dump.age
export PLATEOS_RESTORE_DRILL_ID=20260825t163000
export PLATEOS_RESTORE_CONFIRM=RESTORE_TO_ISOLATED_PLATEOS
set -eu
docker compose -f docker-compose.restore.yml --profile verification up --wait verify-api
docker compose -f docker-compose.restore.yml --profile verification run --rm --no-deps verify
```

What it does: Creates a fresh drill project, decrypts into a FIFO, restores only
into an empty isolated PostgreSQL volume, and requires restore success before the
API can start. It accepts source revisions `0001` and `0002`, migrates the
restored DB to current head through the normal API entrypoint, verifies readiness,
confirms unauthenticated denial, logs in with the drill credential, and performs
representative authenticated reads. `set -e` prevents verification after a
failed restore/startup; the second command returns the verifier status while
leaving the drill available for evidence collection.

After recording success/failure evidence, remove drill containers and network:

```bash
docker compose -f docker-compose.restore.yml --profile verification down
```

What it does: Removes all services in the uniquely named drill, including the
profile-gated verifier, plus its internal network. It deliberately retains the
restored volume for separately authorized retention or investigation.

Deleting the restore volume or recovered identity is a separate destructive
retention action requiring explicit authorization. Record archive timestamp,
image/source revision, duration, result, discrepancies, and application checks
without recording personal data or secret values. iOS/PWA behavior remains a
separate physical-device validation.

## Authorized deployment

Before first deployment or upgrade, verify current target capacity, port use,
Docker/Compose versions, checkout state, secret/destination permissions,
external proxy route, Access policy, firewall behavior, backup state, and
rollback artifact. An upgrade with existing data requires a successful
application-consistent pre-change backup and readable ciphertext.

Only after those gates and exact production mutation are authorized:

```bash
docker compose up --build -d
```

What it does: Builds/reconciles the PlateOS project, starts PostgreSQL, applies
Alembic migrations before API startup, then admits API and web only after
readiness succeeds. It mutates production containers, images, database schema,
and possibly seeded data; backup and rollback prerequisites must already pass.

Validate all of the following before completion:

- Containers reach healthy state without restart loops.
- `http://127.0.0.1:<selected-port>/api/ready` returns `{"status":"ready"}`.
- No database/API port and no wildcard web port is host-published.
- Intended TLS hostname succeeds through the external proxy; direct origin
  bypass from unintended interfaces fails.
- Unauthorized API access returns 401; authorized password and optional token
  paths succeed without exposing credentials.
- Login cookie carries Secure, HttpOnly, and SameSite=Strict attributes.
- `GET /api/settings` returns redacted config; a PUT round-trip applies without
  restart; the automation bearer token is rejected on all `/api/settings`
  routes.
- Meal creation/replay, daily summary, analytics, OFF lookup, and SSE error path
  pass the existing smoke checklist.
- Data survives a safe service recreation; Docker log growth remains bounded.
- Backup job/checksum succeeds and monitoring receives a controlled failure.

## Abort and rollback

Abort or roll back on migration differences, unexpected checkout changes,
missing/unreadable pre-change backup, unhealthy dependencies, failed auth,
unintended exposure, wrong mounts/ownership, threatening resource/log growth, or
an unusable previous artifact.

Prefer the previous recorded Compose/source/image revision without deleting the
current `pgdata` volume. Never use `docker compose down -v` in routine rollback.
Do not assume an older application is compatible with a newer schema. If data
restoration is required, state the recovery point and expected data loss, obtain
separate destructive authorization, and use a verified isolated restore before
touching production.
