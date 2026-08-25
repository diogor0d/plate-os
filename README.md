# PlateOS

Self-hosted, mobile-first PWA for daily nutrition tracking and body
recomposition — built for one person, running on your own hardware.

Three fast input paths remove tracking friction:

1. **Barcode scan** → Open Food Facts lookup (cached server-side)
2. **Label photo** → vision LLM extracts the nutrition table
3. **Freeform text** → the AI coach parses *"1.5 cans of drained tuna with 100g pasta"*

Everything lands in an editable **Proposal Card**. Nothing touches the database
until you confirm it.

```text
┌────────────────────────────────────────────────────┐
│        Client — iOS/Android PWA (Vite + React 19)  │
│  Tailwind v4 · ZXing barcode · Dexie offline queue │
│  canvas downscale ≤1280px WebP · Workbox SW        │
└───────────────┬────────────────────────────────────┘
                │ REST + SSE (HTTPS via your reverse proxy)
┌───────────────▼────────────────────────────────────┐
│ web (Caddy) — static SPA + /api/* reverse proxy    │
└───────────────┬────────────────────────────────────┘
┌───────────────▼────────────────────────────────────┐
│ api — FastAPI · nutrition math · LLM gateway       │
│ OFF lookup+cache · HMAC cookie auth · SSE chat     │
└──────┬─────────────────────────┬───────────────────┘
┌──────▼──────────┐   ┌──────────▼───────────────────┐
│ db — PostgreSQL │   │ LLM: OpenAI / Gemini-compat /│
│ 17 (plain)      │   │ Ollama — per-task, UI-swapped│
└─────────────────┘   └──────────────────────────────┘
```

## Highlights

- **LLM extracts; the app computes.** The model returns raw label values with
  an explicit basis; all scaling, rounding, and totals are deterministic code,
  mirrored byte-for-byte between Python and TypeScript and covered by shared
  boundary tests.
- **Dual providers, zero redeploy.** Route coach text and label vision to two
  different OpenAI-compatible providers (e.g., a cheap text model + a strong
  vision model, or everything on local Ollama) from the in-app Settings
  screen. Vision inherits the text provider unless you split it.
- **Offline-first.** Every confirmed meal gets a client UUID before its first
  POST. Failed writes queue in IndexedDB and replay idempotently; permanent
  rejections stay visible for explicit discard instead of vanishing.
- **Idempotent by design.** A server-side mutation ledger makes replays safe
  across tabs, retries, and deletes — reuse of a consumed key with changed
  data, or after deletion, returns `409`.
- **Timezone-correct days.** Daily budgets group by *your* local midnight
  (IANA tz), never UTC.
- **Fail-closed production.** Default or weak credentials, insecure cookies,
  and incomplete database configs are rejected at boot. Secrets are files
  under `/run/secrets`, never env vars in container config.

## Security posture

| Control | Implementation |
| --- | --- |
| Origin | Caddy binds `127.0.0.1` only; TLS terminates at your reverse proxy/tunnel |
| Containers | Non-root, read-only rootfs, `cap_drop: ALL`, `no-new-privileges`, bounded logs, digest-pinned base images |
| Auth | Single-user HMAC-signed HttpOnly cookie (`Secure` forced in production) |
| Provider keys | Write-only over the API; stored outside the DB/backups in a `0600` file; Settings mutations require the session cookie — the automation token cannot reach them |
| Backups | Opt-in job: `pg_dump` → FIFO → age encryption; ciphertext published only after its checksum sidecar; guarded isolated restore drill included |
| Inputs | 2 MB request-body cap (proxy + app), strict Pydantic bounds, IANA timezone validation |

Label photos are sent to the configured vision provider — they may leave your
host unless that provider points at a local service such as Ollama. The
Settings screen shows exactly which endpoint each task uses.

## Quickstart (development)

Prerequisites: Python 3.12, Node 22, any PostgreSQL 16+ reachable.

```bash
# Backend
cd backend
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt        # Windows: .venv\Scripts\python
cp ../.env.example .env                                        # adjust vars
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --reload              # http://localhost:8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev                                                    # http://localhost:5173
```

Sign in with `PLATEOS_APP_PASSWORD` from your `.env` (default `changeme`).

## Production (fully containerized)

```bash
docker compose --profile operations build --pull
docker compose up --wait
```

Services: `db` (PostgreSQL 17), `api` (FastAPI; runs migrations on boot),
`web` (Caddy SPA + SSE proxy), plus an opt-in `backup` profile for age-encrypted
dumps. Production mode requires strong file-injected secrets and serves a
loopback-only origin — put your TLS proxy in front of it.

The full procedure — secret files and permissions, backup/restore drills,
validation matrix, abort conditions, and rollback — is documented in
[`docs/operations/production.md`](docs/operations/production.md).

After any restore from backup, re-enter provider credentials in the Settings
screen; they deliberately live outside the database so backups stay secret-free.

## Choosing LLM backends

Configure per task in **Settings** (in-app, applied instantly), or set
bootstrap defaults via env:

| Backend | Endpoint | Model example |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` / `gpt-4o` |
| Gemini (OpenAI compat) | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-2.0-flash` |
| Ollama (local, fully private) | `http://localhost:11434/v1` | `qwen2.5:7b` / `qwen2.5vl:7b` |

Use **Test connection** in Settings to validate a swap before relying on it;
failures surface there instead of silently breaking scan/coach features.

## Logging from Apple Shortcuts

Set `PLATEOS_API_TOKEN`, then call any endpoint with
`Authorization: Bearer <token>` (full API access — treat like a password).
Example "Log food" action (*Get Contents of URL*):

```http
POST https://your-host/api/meal-logs

{"custom_name": "Whey shake", "quantity_g": 30,
 "per100": {"calories": 400, "protein_g": 80, "carbs_g": 8, "fat_g": 6, "fiber_g": 0},
 "source_type": "manual"}
```

Totals are always computed server-side. For retry-safe writes, generate a UUID
once per intended log as `client_mutation_id` and send an offset-aware
`logged_at`; both stay optional for simple shortcuts. Note: this bearer token
cannot read or change the Settings screen by design.

## Tests / checks

```bash
cd backend  && .venv/bin/python -m pytest    # 58 unit/contract/integrity tests
cd frontend && npm test                      # mirrored math + offline queue
cd frontend && npm run typecheck             # strict TS
cd frontend && npm run build                 # typecheck + build + PWA generation
```

## Project layout & decisions

[`AGENTS.md`](AGENTS.md) carries the architecture map, invariants, conventions,
and roadmap — written to onboard humans and AI agents alike. Dated,
ADR-style decision records with rejected alternatives live in
[`docs/decisions/`](docs/decisions/).

## License

[Apache-2.0](LICENSE)
