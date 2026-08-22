# PlateOS

Self-hosted, iOS-first PWA for daily nutrition tracking and body recomposition.
Barcode scans (Open Food Facts), label-photo parsing and a conversational AI
coach all funnel through an editable **Proposal Card** — nothing is logged
until you confirm it.

> **For AI agents and contributors:** read [`AGENTS.md`](AGENTS.md) first —
> it contains the project invariants, architecture, conventions and roadmap.
> Decision history with rationale lives in
> [`docs/decisions/`](docs/decisions/).

## Quickstart (development)

Prerequisites: Python 3.12, Node 22, a reachable PostgreSQL (any Postgres 16+).

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt      # Windows Git Bash
cp ../.env.example .env                                          # adjust vars
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:app --reload            # http://localhost:8000

# Frontend (other terminal)
cd frontend
npm install
npm run dev                                                      # http://localhost:5173 (proxies /api)
```

Sign in with `PLATEOS_APP_PASSWORD` from your `.env` (default `changeme`).

## Production (fully containerized)

```bash
cp .env.example .env    # set PLATEOS_APP_PASSWORD, PLATEOS_SESSION_SECRET, LLM vars
docker compose up --build -d
# → http://localhost:8080  (put your reverse proxy with TLS in front of it;
#   set PLATEOS_COOKIE_SECURE=true when serving over HTTPS)
```

Services: `db` (PostgreSQL 17), `api` (FastAPI; runs migrations on boot),
`web` (Caddy serving the built SPA and proxying `/api` with SSE streaming).

## Choosing the LLM backend

The gateway speaks the OpenAI-compatible protocol — switch by env only:

| Backend | `PLATEOS_LLM_BASE_URL` | Model example |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Gemini (compat) | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-2.0-flash` |
| Ollama (local, fully private) | `http://localhost:11434/v1` | `qwen2.5vl:7b` |

## Logging from Apple Shortcuts

Set `PLATEOS_API_TOKEN` in `.env`, then call any API endpoint from a Shortcut
with the header `Authorization: Bearer <token>` (full API access — treat like
a password). Example "Log food" shortcut: *Get Contents of URL* →

```
POST https://your-host/api/meal-logs
{"custom_name": "Whey shake", "quantity_g": 30,
 "per100": {"calories": 400, "protein_g": 80, "carbs_g": 8, "fat_g": 6, "fiber_g": 0},
 "source_type": "manual"}
```

Totals are always computed server-side; `GET /api/daily-summary` works the
same way for reading back the day's budget.

## Tests / checks

```bash
cd backend && .venv/Scripts/python -m pytest        # nutrition math unit tests
cd frontend && npm run typecheck                    # strict TS
cd frontend && npm run build                        # typecheck + production build + PWA
```
