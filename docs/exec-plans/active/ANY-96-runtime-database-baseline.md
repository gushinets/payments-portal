# ANY-96 Runtime and Database Baseline

Status: active
Started: 2026-07-27
Linear: ANY-96

## Goal

Freeze the pre-production baseline before the first production deployment:
Node.js 24 LTS and PostgreSQL 18 across local development, CI, and production
Compose.

## Scope

- Replace the previous Node.js baseline with Node.js 24 in package engines, CI,
  and the production web image.
- Update `@types/node` to the Node 24 type baseline without changing other
  application libraries.
- Replace the previous PostgreSQL baseline with PostgreSQL 18.4 in local, CI,
  and production Compose.
- Use the PostgreSQL 18 Docker volume layout by mounting volumes at
  `/var/lib/postgresql`.
- Pin exact image tags and multi-architecture digests for baseline images.
- Update README and environment examples with the new baseline and local volume
  reset guidance.

## Evidence

- `npm install --package-lock-only --ignore-scripts`: updated
  `package-lock.json` for `@types/node@24.13.3`; local Node 23 emitted the
  expected new engine warning.
- Focused search across Dockerfiles, CI, Compose, README, environment examples,
  and docs found no previous Node.js or PostgreSQL baseline references.
- `docker compose -f docker-compose.yml config --quiet`: passed.
- `docker compose --env-file .env.production.example -f docker-compose.prod.yml
  config --quiet`: passed.
- PostgreSQL 18 image architecture check: `postgres:18.4-alpine3.22` manifest
  digest `sha256:774521500f4c22761b25a6bdb772a0a3c2e8dd32468210bdad9231c5752ea398`
  includes `linux/amd64` and `linux/arm64/v8`.
- PostgreSQL 18.4 container check: `docker inspect` reported
  `PG_VERSION=18.4` and `PGDATA=/var/lib/postgresql/18/docker`.
- Node image architecture check: `node:24.18.0-alpine3.24` manifest includes
  `linux/amd64` and `linux/arm64/v8`.
- `TEST_POSTGRES_DATABASE_URL=...5433 ./.venv/bin/python -m pytest
  apps/api/tests/test_alembic_postgres.py
  apps/api/tests/test_cloudpayments_webhook_postgres.py`: passed, 4 tests on
  PostgreSQL 18.4.
- `./.venv/bin/python -m pytest apps/api/tests`: passed, 42 passed and 4
  PostgreSQL-specific tests skipped because they were run separately on
  PostgreSQL 18.
- Node 24 container check using the pinned Node image: `npm ci`, web boundary
  tests, lint, typecheck, and build passed.
- `docker compose --env-file .env.production.example -p
  payment-portal-baseline-prod-18-4 -f docker-compose.prod.yml build api web`:
  passed.
- Production image smoke: API `/health/ready` returned `ready`; web `/ru`
  returned `200` inside the production Compose stack.
- Local Caddy/API/web smoke using pinned Caddy on loopback port `18080`: `/ru`
  returned `200`; `/api/auth/session` returned expected `401` through Caddy.
- `TEST_POSTGRES_DATABASE_URL=...55432 ./.venv/bin/python scripts/repo.py
  check`: passed; browser suite skipped because `RUN_E2E=true` was not set and
  the harness stack was not running.
