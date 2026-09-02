<div align="center">

<img src="docs/design/plate-prompt-readme.svg" width="88" alt="PlateOS Plate Prompt logo" />

# PlateOS

**Self-hosted nutrition tracking for one person — or a whole household.**

Barcode · Label photo · Conversational coach → one editable **Proposal Card**.
Nothing is logged until you confirm it.

[![License](https://img.shields.io/badge/license-Apache--2.0-emerald)](LICENSE)
![Self-hosted](https://img.shields.io/badge/self--hosted-Docker-blue)
![PWA](https://img.shields.io/badge/installable-PWA-525252)

</div>

---

PlateOS is a mobile-first **and** desktop PWA for daily nutrition tracking and
body recomposition. Three fast input paths remove the friction:

The **Plate Prompt** mark combines a shallow dish with a command prompt: meals
go in, structured and reviewable nutrition data comes out. It reflects the
product's core idea — nutrition tracking treated as a dependable personal
system rather than a stream of guesses.

| | Input path | How it works |
|---|---|---|
| 📷 | **Barcode scan** | Accepted library first → ephemeral Open Food Facts candidate → explicit review |
| 🏷️ | **Label photo** | Vision LLM reads the nutrition table exactly as printed |
| 💬 | **Freeform text** | *"1.5 cans of drained tuna with 100g pasta"* → parsed by the AI coach |

Every path ends in an editable **Proposal Card**: adjust grams, watch totals
recompute instantly, then confirm.

## Why it's different

- **The LLM extracts; the app computes.** Models return raw printed values —
  never arithmetic. All scaling/rounding is deterministic code mirrored
  byte-for-byte between Python and TypeScript, covered by shared boundary tests.
- **Two providers, zero redeploy.** Route coach text and label vision to
  *different* OpenAI-compatible providers from the in-app Settings screen — a
  cheap text model plus a strong vision model, or everything on local Ollama.
  Vision inherits the text provider until you split it. Keys are write-only:
  stored server-side, never echoed back.
- **Offline-first.** Confirmed meals queue in IndexedDB when offline and replay
  idempotently; permanent rejections stay visible for explicit discard.
  The server-side mutation ledger makes retries safe across tabs and deletes.
- **Multi-user, single file.** Household accounts with local scrypt-hashed
  passwords. Admins create accounts and reset passwords on the server — no
  email infrastructure, no recovery links, nothing leaves your host.
- **Timezone-correct days.** Daily budgets group by *your* local midnight
  (IANA tz), never UTC.
- **Filterable statistics.** Explore custom date ranges, input sources, foods,
  nutrient trends, weekday patterns, macro share, and top contributors without
  exporting sensitive meal data to another service.
- **AI as a constrained harness.** The coach can turn trusted context into meal
  drafts, plan drafts, goal reviews, evidence callouts, and filtered Stats actions. Models
  never choose endpoints or write meals/goals without explicit confirmation.
- **Plans are not meals.** Rough or product-defined routines use timezone-aware
  schedules and occurrences; only a confirmed Proposal Card becomes intake.
- **Private reminders.** An opt-in isolated Web Push worker sends generic text
  from a leased outbox. Browser subscriptions are encrypted at rest.
- **Desktop-grade UI.** A horizontal control deck, full-width work area, and
  two-column layouts on wide screens; the same installable PWA stays
  pocket-first with bottom navigation on phones.

## Architecture

```text
┌────────────────────────────────────────────────────┐
│      Client — iOS/Android/Desktop PWA (React 19)   │
│  Tailwind v4 · ZXing · Dexie offline queue         │
│  canvas downscale ≤1280px WebP · Workbox SW        │
└───────────────┬────────────────────────────────────┘
                │ REST + SSE (HTTPS via your reverse proxy)
┌───────────────▼────────────────────────────────────┐
│ web (Caddy) — static SPA + /api/* reverse proxy    │
└───────────────┬────────────────────────────────────┘
┌───────────────▼────────────────────────────────────┐
│ api — FastAPI · nutrition math · per-task LLM      │
│ reviewed products · routines · scrypt · SSE chat   │
└──────┬─────────────────────────┬───────────────────┘
┌──────▼──────────┐   ┌──────────▼───────────────────┐
│ db — PostgreSQL │   │ LLM: OpenAI / Gemini /       │
│ 17 (plain)      │   │ DeepSeek / Ollama via Settings│
└─────────────────┘   └──────────────────────────────┘
             │ opt-in leased outbox
       ┌─────▼──────────────┐
       │ Web Push worker    │
       └────────────────────┘
```

## Security posture

| Control | Implementation |
| --- | --- |
| Origin | Caddy binds `127.0.0.1` only; TLS terminates at your reverse proxy/tunnel |
| Containers | Non-root, read-only rootfs, `cap_drop: ALL`, `no-new-privileges`, digest-pinned bases, bounded logs |
| Accounts | scrypt (N=2¹⁵) hashed passwords; session = HMAC-signed HttpOnly `Secure` cookie |
| Admin surface | User management + provider settings are admin-only and cookie-only — the automation bearer token cannot reach them |
| Provider keys | Write-only over the API; live outside the DB/backups in a `0600` file |
| Backups | Opt-in job: `pg_dump` → FIFO → age encryption, ciphertext published only after its checksum sidecar; guarded isolated restore drill included |
| Inputs | 2 MB body cap (proxy + app), strict Pydantic bounds, IANA tz validation |

> **Privacy:** label photos go to the configured vision provider — they may
> leave your host unless that endpoint points at Ollama. Settings shows
> exactly which endpoint each task uses.

## Quickstart (Docker)

Prerequisite: Docker with Compose.

```bash
docker compose -f docker-compose.dev.yml up --build --wait
```

What it does: builds and starts an isolated local-review stack at
<http://127.0.0.1:8081>. Sign in with `admin` / `changeme`; test data and local
provider settings persist across restarts.

Stop it without deleting its data:

```bash
docker compose -f docker-compose.dev.yml down
```

What it does: stops the local-review containers while preserving their named
volumes. This stack is development-only; production uses the hardened workflow
below.

## Source Development

Prerequisites: Python 3.12, Node 22, any PostgreSQL 16+.

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

Sign in with username `admin` and `PLATEOS_APP_PASSWORD` (default `changeme`).
On first boot the app seeds that admin account — change the password in
**Settings → Your password**, then add household accounts as you like.

## Production (fully containerized)

```bash
docker compose --profile operations build --pull
docker compose up --wait
```

Services: `db` (PostgreSQL 17), `api` (FastAPI; runs migrations on boot),
`web` (Caddy SPA + SSE proxy), an opt-in `push` profile, and an opt-in `backup`
profile producing age-encrypted dumps. Production mode fails closed on weak/default credentials,
insecure cookies, and unusable database config; it serves a loopback-only
origin behind your TLS proxy.

The full procedure — secret files and permissions, backup/restore drills,
validation matrix, abort conditions, rollback — lives in
[`docs/operations/production.md`](docs/operations/production.md).

After any restore from backup, re-enter provider credentials in Settings;
they deliberately live outside the database so backups stay secret-free.

## Choosing LLM backends

Configure per task in **Settings** (applied instantly) or set env bootstrap
defaults:

| Backend | Endpoint | Model examples |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` / `gpt-4o` |
| Gemini (OpenAI compat) | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-3.6-flash` |
| Ollama (local, fully private) | `http://localhost:11434/v1` | `qwen2.5:7b` / `qwen2.5vl:7b` |

Use **Test connection** to validate a swap before relying on it — failures
surface there instead of silently breaking scan/coach features.

## Logging from Apple Shortcuts

Set `PLATEOS_API_TOKEN`, then call any data endpoint with
`Authorization: Bearer <token>` (acts as the admin account). Example:

```http
POST https://your-host/api/meal-logs

{"custom_name": "Whey shake", "quantity_g": 30,
 "per100": {"calories": 400, "protein_g": 80, "carbs_g": 8, "fat_g": 6, "fiber_g": 0},
 "source_type": "manual"}
```

For retry-safe writes, generate a UUID once per intended log as
`client_mutation_id` and send an offset-aware `logged_at`. If your host sits
behind Cloudflare Access Service Auth, also attach the
`CF-Access-Client-Id` / `CF-Access-Client-Secret` headers.

## Tests

```bash
cd backend  && .venv/bin/python -m pytest    # 188 unit/contract/integrity tests
cd frontend && npm test                      # 43 math/domain/offline tests
cd frontend && npm run typecheck             # strict TS
cd frontend && npm run build                 # typecheck + build + PWA generation
```

## Project layout & decisions

[`AGENTS.md`](AGENTS.md) carries the architecture map, invariants, conventions
and roadmap — written to onboard humans and AI agents alike. Dated, ADR-style
decision records with rejected alternatives live in
[`docs/decisions/`](docs/decisions/).

## License

[Apache-2.0](LICENSE)
