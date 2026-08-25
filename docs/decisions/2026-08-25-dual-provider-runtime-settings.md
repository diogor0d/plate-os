# Decision Record — Dual-Provider LLM Routing and UI-Managed Runtime Settings

- **Occurred:** 2026-08-25 (cost-optimization pass requested before deployment)
- **Documented:** 2026-08-25T22:40:00+01:00 (Europe/Lisbon)
- **Verified:** 2026-08-25 — see [Evidence](#evidence)
- **Status:** Implemented; container smoke of settings endpoints recorded in evidence
- **Recall tags:** PlateOS, LLM, dual provider, vision, runtime settings, API
  keys, cost, August 2026

This record continues the numbering from D33 in
`2026-08-25-production-hardening.md`.

## D34 — Text and vision resolve providers independently

**Context.** A single env-selected provider forced one model to serve both the
coach chat and nutrition-label vision. Cost-optimal setups differ: a cheap
text model for conversation and a stronger (or local) vision model for label
OCR, or a fully local Ollama pair.

**Decision.** The gateway resolves `(base_url, model, api_key)` per task:
`text` (chat) and `vision` (label parsing). Resolution order per field is
Settings-screen override → inherited values → env default. Vision inherits the
resolved text configuration unless explicitly split; when split, any field left
empty continues to inherit that single field from text. Env vars remain the
bootstrap defaults so a fresh deployment works with zero UI interaction.
Clients are pooled by `(base_url, key)` and dropped on settings changes, so
edits apply on the next request without a restart.

**Rejected.** Two separate SDKs or provider-specific APIs (violates the
OpenAI-compatible-only rule); baking the split into prompts instead of routing
(cannot change models without deploys); requiring both providers to be
configured (inheritance covers the common case).

## D35 — Operational settings are UI-managed and stored outside the database

**Context.** Swapping providers previously required editing `.env` and
restarting containers. The user asked for as much configuration as possible in
a Settings menu to optimize costs interactively.

**Decision.** New cookie-authenticated endpoints `GET/PUT /api/settings` and
`POST /api/settings/test` manage: text provider (endpoint/model/key), vision
provider (endpoint/model/key/inherit flag), and the Open Food Facts base URL.
State is a single JSON file (`PLATEOS_RUNTIME_SETTINGS_FILE`) written
atomically with a `.bak` of the previous version. It deliberately lives
outside PostgreSQL:

- Provider API keys never enter meal data, so encrypted `pg_dump` backups stay
  secret-free and restore drills do not silently carry credentials.
- The cost is explicit: after a disaster recovery, provider config must be
  re-entered in Settings (env defaults still apply).

API keys are **write-only**: responses carry only `has_api_key`; a PUT omits
the field to keep the stored key, sends `""` to clear it, or sends a value to
replace it. Security-critical infrastructure stays env/file-only and cannot be
changed at runtime: environment mode, database coordinates, session secret,
cookie security, bearer token, body limits, port binding. Settings routes use
a new cookie-only dependency — the D19 automation bearer token can read/write
meals but cannot rewrite provider endpoints, preventing a leaked token from
redirecting LLM traffic (prompt/image exfiltration). The Test action performs
one minimal completion against the resolved provider and surfaces the raw
error so bad configs fail loudly in the UI, not silently in chat/vision.

**Rejected.** Storing keys in the database (spreads secrets into backups and
the restore chain); encrypting keys with a host-derived key (same restore
friction with more machinery); allowing the bearer token to mutate settings
(widens blast radius of a leaked long-lived token); making cookies/auth
UI-configurable (self-lockout and fail-closed violations).

## Evidence

| Check | Result |
| --- | --- |
| Backend tests | 58 passed, including file fallback/corruption, tri-state key semantics, inheritance resolution, cache reset, redaction, and cookie-only authz |
| Frontend | typecheck + production build clean; Settings ships as its own lazy chunk (~12.5 kB), main chunk ~382 kB |
| Container smoke | Login → GET (redacted) → PUT override → GET reflects state → omitted key preserved → `""` clears → bearer-token read/mutation rejected 401 → Test against unreachable endpoint returns controlled failure without key echo → state file on volume owned by UID 10001, mode 0600 inside dir 0750 |
