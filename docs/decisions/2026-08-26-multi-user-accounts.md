# Decision Record — Multi-User Accounts and Local Credential Management

- **Occurred:** 2026-08-26 (household rollout requested pre-deployment)
- **Documented:** 2026-08-26T01:30:00+01:00 (Europe/Lisbon)
- **Verified:** 2026-08-26 — see [Evidence](#evidence)
- **Status:** Implemented; supersedes the single-user scope of D11
- **Recall tags:** PlateOS, multi-user, accounts, scrypt, admin, D36

## D36 — Household accounts with local-only credential management

**Context.** PlateOS assumed exactly one profile: login compared one global
password, readiness and both recovery guards asserted `count == 1`, and the
bearer token resolved "the" profile. The operator wanted household accounts
with passwords changeable/resettable locally — explicitly without email
flows.

**Decision.** `user_profile` gains `username` (unique), a scrypt
(`N=2^15, r=8, p=1`, per-user salt, `maxmem=64MiB`) `password_hash`,
`is_admin`, and `created_at`. Login accepts an optional username: omitted is
tolerated only while exactly one account exists, preserving Shortcuts-style
password-only logins until a second account appears. The D19 bearer token now
acts as the primary admin account. The first account is admin; admins list and
create accounts (`POST /api/users`) and reset any password except their own;
every user changes their own password with re-authentication
(`PATCH /api/users/me/password`). Provider settings become admin-gated via
`require_admin`. Startup bootstrap seeds the admin from env secrets, or
backfills credentials onto a pre-0003 row so upgrades keep working passwords.
Readiness and both recovery guards relax to "at least one account"; the
restore verifier sends a configurable username
(`PLATEOS_VERIFY_USERNAME`, default `admin`). The food library stays global
(shared household cache), while meals/chat/ledger remain per-user via existing
cascade FKs. No password policy beyond length/entropy heuristics and no
lockouts: Cloudflare Access fronts the deployment edge.

**Rejected.** Separate `users` table joined to profiles (two rows per person,
no benefit at this scale); bcrypt/argon2 dependencies (stdlib scrypt suffices);
email verification or self-registration (operator explicitly declined);
per-user food libraries (duplicates OFF cache entries for zero gain).

## Evidence

| Check | Result |
| --- | --- |
| Backend tests | 71 passed, including scrypt round-trip/salting/policy and username rules |
| Frontend | typecheck + build clean; Settings ships admin-gated provider/user cards plus self-service password change; desktop rail layout added |
| Migration | Pure schema change; credential backfill lives in app bootstrap, never in Alembic |
