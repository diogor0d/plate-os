# 2026-09-02 - Isolated local-review Compose stack

- **Occurred:** 2026-09-02 (Europe/Lisbon)
- **Status:** Implemented and locally verified
- **Decision:** D40

## Context

The hardened production Compose file deliberately fails closed unless its
external secret files, ownership group, backup destination, and production
settings are present. That is the correct deployment behavior, but it made a
routine workstation review require reconstructing production-only variables or
manually starting PostgreSQL, FastAPI, and Vite.

## Decision

Add `docker-compose.dev.yml` as a separate `plateos-dev` project. It builds the
same API and web Dockerfiles, runs migrations through the API image's normal
startup command, persists its own database and provider-settings volumes, and
binds only the Caddy origin to `127.0.0.1:8081` by default. The host port remains
overrideable through `PLATEOS_DEV_PORT`.

The file explicitly uses development mode and disposable `admin` / `changeme`
credentials. It does not import, override, or weaken `docker-compose.yml`, and
its volumes cannot collide with the production project's named volumes.

## Consequences

- Local review starts with one command and needs only Docker Compose.
- Rebuilds preserve test data unless the developer explicitly removes the
  `plateos-dev` volumes.
- Provider keys entered in this stack remain in its local settings volume and
  are not production configuration.
- Production deployment and recovery commands continue to use the hardened
  Compose files and their required secret mounts.

## Verification

`docker compose -f docker-compose.dev.yml config --quiet` succeeded. A clean
project built both application images, initialized PostgreSQL, applied all
migrations, passed API and web health checks, and served the login page through
the loopback-only Caddy origin.
