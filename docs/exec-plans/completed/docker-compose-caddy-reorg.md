# Docker Compose Caddy Reorganization

## Objective

Deliver the first bounded Docker reorganization stage: local development runs
PostgreSQL, API, and Caddy while Next.js stays on the host; production runs
PostgreSQL, API, web, and Caddy with Caddy as the only public HTTP entrypoint.

## Non-goals

- Docker secrets or `*_FILE` support.
- A separate one-shot migration service.
- Backup automation.
- Full production fail-fast validation for CloudPayments secrets.

## Decisions

- Keep Alembic migrations in API container startup for this stage.
- Use separate API Docker targets for development and production.
- Use separate Caddyfiles for local HTTP and production automatic HTTPS.
- Keep local API and PostgreSQL loopback ports for debugging.

## Progress

- [x] Split API Dockerfile into development and production targets.
- [x] Extend local Compose with API and Caddy.
- [x] Update production Compose to route only through Caddy.
- [x] Add environment templates and README workflow notes.
- [x] Run Compose config checks and focused tests/builds where supported.

## Validation

- `docker compose config`
- `docker compose --env-file .env.example config`
- `docker compose --env-file .env.production.example -f docker-compose.prod.yml config`
- `docker compose --env-file .env.production.example -f docker-compose.prod.yml config --services`
- `python3 -m py_compile scripts/repo.py`
- `.venv/bin/python -m pytest apps/api/tests` — 32 passed, 3 skipped.
- `npm run lint:web`
- `npm run build:web`
- `docker compose --env-file .env.example build api`
- `docker compose --env-file .env.production.example -f docker-compose.prod.yml build api`
- Dev image dependency check: `pytest` and `httpx` installed.
- Production image dependency check: `pytest` and `httpx` not installed.
- Local smoke: `docker compose up -d --build postgres api caddy`; API became
  healthy, Alembic ran initial migration, direct `GET /health/ready` returned
  200, Caddy `GET /api/auth/session` returned the API's 401, and Caddy
  `GET /ru` returned 200 while `npm run dev:web` was running.
- Production smoke:
  `docker compose --env-file .env.production.example -f docker-compose.prod.yml up -d --build`;
  postgres and API became healthy, web and Caddy started, and `ps` showed only
  Caddy publishing host ports `80` and `443`.

Note: runtime smoke used the developer's current `.env`, where `POSTGRES_PORT`
is `5433` because local host port `5432` was already occupied. `.env.example`
keeps the required default `5432`.
