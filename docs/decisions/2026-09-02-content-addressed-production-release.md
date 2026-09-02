# Decision Record — Content-Addressed Production Release

- **Occurred:** 2026-09-02 (Europe/Lisbon)
- **Documented:** 2026-09-02 (Europe/Lisbon)
- **Verified:** 2026-09-02 (authorized production deployment and read-only smoke checks)
- **Status:** Implemented; source commit, iOS validation, push delivery, monitoring, and production restore remain open
- **Recall tags:** PlateOS, production, deployment, rollback, artifact, D42

## D42 — Preserve the prior checkout and deploy the reviewed working tree as a content-addressed release

### Context

The completed D41 implementation had passed local backend, frontend, migration,
and Docker review checks but had not been committed. Production was running the
clean `fb589e3` checkout at schema `0003`. Deployment was authorized, while a Git
commit or push was not.

Overwriting the production checkout would destroy a useful rollback artifact and
leave a large ambiguous dirty tree. Committing merely to obtain a deployment tag
would exceed the Git authorization boundary.

### Decision

Package only tracked and non-ignored working-tree files, identify the archive by
its SHA-256 digest, and extract it into a separate production release directory.
Build API, web, and backup images with the short content-addressed tag
`d41-5bccac401913`, retain the prior checkout and images, and keep the existing
Compose project and named volumes.

Before migration, create and checksum an encrypted schema-`0003` database
archive. Start only `db`, `api`, and `web`; do not enable the optional Web Push
worker without its separately protected key set. After migration and health
checks, create and checksum a second encrypted schema-`0005` archive.

### Rationale

- The full archive digest identifies the exact deployed source without inventing
  Git history or modifying the reviewed production checkout.
- A separate release directory and retained image tags keep application rollback
  artifacts available.
- The pre-migration encrypted archive is required because migration `0004`
  removes `food_items.is_verified`; restarting the old API against schema `0005`
  is not an accepted rollback method.
- Keeping Web Push disabled avoids partial key configuration and preserves the
  isolated worker/private-key boundary.

### Rejected Alternatives

- Commit or push D41 solely for deployment: not authorized as part of the
  production mutation.
- Overlay the working tree onto the existing server checkout: obscures provenance
  and weakens rollback.
- Reuse the prior commit hash as the new image tag: falsely identifies changed
  content.
- Enable the push profile with generated ad hoc keys: creates an unreviewed
  recovery and secret-management dependency.

### Verified Outcome

- Production migrated transactionally from `0003` through `0004` to `0005`.
- Core containers became healthy on the existing database and settings volumes.
- Local origin liveness/readiness, authenticated profile/product/routine reads,
  password login, cookie-only disabled-push status, PWA assets, and all 30 OpenAPI
  paths passed.
- The external TLS route returned the expected Access challenge rather than an
  origin failure.
- Both encrypted archives passed ciphertext checksum validation.

### Remaining Limits

The release is not yet represented by a Git commit. Authenticated browser access
through the edge, denied direct-origin paths, physical iPhone/PWA behavior, real
LLM and Web Push round-trips, monitored backup scheduling, independent retention,
and isolated restore from a production archive remain unverified.
