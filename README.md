# AnytoolAI Payment Portal

The Payment Portal is the identity, legal-consent, checkout, and access-entry
service for AnytoolAI products. Each production deployment is one contour
(compliance zone). This repository currently ships the `ru` contour.

It contains a Next.js web application, a FastAPI API, PostgreSQL persistence,
and the `ru` CloudPayments adapter. Catalog products and plans, local
subscriptions, entitlement rules, entitlements, and subscription audit are
implemented. The private regional entitlement/access API for Platform Kernel
is still planned. Platform Kernel code is maintained in the separate
[anytoolai-platform](https://github.com/gushinets/anytoolai-platform) repository.

Payment Portal is still under development and is not running as a production
billing service. Direct CloudPayments support is a transitional Portal-managed
direct-provider capability; there are no production CloudPayments subscribers
or subscriptions to migrate, and the product will most likely launch with an
external billing system. See the current [product scope](docs/PRODUCT.md),
[billing authority](docs/architecture/billing-authority.md), and contour and
Region Resolver architecture in [ARCHITECTURE.md](ARCHITECTURE.md).

## Start here

1. Read [AGENTS.md](AGENTS.md) for the repository map and non-negotiable rules.
2. Read [ARCHITECTURE.md](ARCHITECTURE.md) for current system boundaries.
3. Run the environment diagnostic:

   ```bash
   npm run repo:doctor
   ```

4. Install dependencies and create local configuration:

   ```bash
   npm run repo:setup
   ```

5. Start an isolated worktree environment:

   ```bash
   npm run repo:up
   ```

6. Run the canonical checks:

   ```bash
   npm run check:fast
   npm run check
   ```

Runtime state and test evidence are written to the ignored `.harness/`
directory. Each Git worktree receives an isolated Compose project, database,
ports, logs, and browser artifacts.

## API development workflow

The API uses uv `0.12.7`. The dependency source of truth is
`apps/api/pyproject.toml` plus `apps/api/uv.lock`.

Install and verify the required uv version:

```bash
python -m pip install "uv==0.12.7"
uv --version
```

Repository tooling explicitly selects the repository-root `.venv` as the only
canonical local API environment. Do not create `apps/api/.venv`; normal
commands do not require shell activation.

Use the root npm aliases for the normal API workflow:

```bash
npm run sync:api
npm run lock:api
npm run lock:check:api
npm run dev:api
npm run migrate:api
npm run test:api:fast
npm run test:api:postgres
npm run test:api
npm run build:api
```

The API test boundaries are intentional: `test:api:fast` is PostgreSQL-free,
`test:api:postgres` runs the PostgreSQL tests, and `test:api` runs the complete
backend suite. Frontend tests and browser E2E remain separate commands.

For local PostgreSQL tests on Unix/WSL, start and stop only the worktree-local
server through the minimal Makefile shortcuts:

```bash
make test_db_up
npm run test:api:postgres
make test_db_stop
```

The cross-platform equivalents are `python scripts/repo.py test-db up` and
`python scripts/repo.py test-db stop`. Compose and `repo.py` own the server
container; pytest creates, migrates, resets, and drops the disposable
`_tests` database. Developers must not manually create or drop that database.

Test database configuration takes precedence in this order: an explicit
`TEST_POSTGRES_DATABASE_URL`; a complete explicit `POSTGRES_*_TEST`
configuration (partial configuration fails clearly); then the current
worktree runtime configuration, with the mapped host port and an automatically
derived database name ending in `_tests`.

## Runtime baseline

- Node.js: `24.x` LTS for local development, CI, and the production web image.
  The production Docker image is pinned to `node:24.18.0-alpine3.24` plus its
  multi-architecture digest.
  The production web image uses Next.js standalone output and starts the traced
  workspace server directly with `node apps/web/server.js`; npm and other build
  tooling are not part of the runtime image.
- PostgreSQL: `18.4` for local development, CI, pre-production, and the first
  production deployment. Compose uses the PostgreSQL 18 Docker volume layout:
  named volumes mount at `/var/lib/postgresql`, while the image-owned `PGDATA`
  remains `/var/lib/postgresql/18/docker`.
- Caddy: production and local Compose pin `caddy:2.11.4-alpine` plus its
  multi-architecture digest.

The first production deployment has no existing data to migrate. Older local
development/test PostgreSQL major-version volumes are intentionally not reused;
recreate the development database with `npm run repo:reset` or
`docker compose down -v` before starting the PostgreSQL 18 stack.

## Repository layout

- `apps/web` — Next.js portal UI. Current routes are the `ru` contour and its
  legal-page renderer.
- `apps/api` — FastAPI identity, legal, checkout, payment, and webhook API.
- `apps/api/alembic` — PostgreSQL schema and first-install legal seed.
- `docs` — authoritative product, architecture, design, reliability, security,
  legal, planning, and generated documentation.
- `scripts/repo.py` — cross-platform development and agent harness.

## Direct development commands

The harness commands are canonical. These lower-level commands remain useful
while diagnosing a subsystem:

```bash
npm run dev:web
npm run dev:api
npm run lint:web
npm run build:web
npm run test:api
npm run migrate:api
```

## Local Compose workflow

Local Compose runs PostgreSQL, a one-shot Alembic migration service, the FastAPI
API, and Caddy. Next.js stays on the host so it can use the normal development
server:

```bash
docker compose up --build
npm run dev:web
```

Local addresses:

- App through Caddy: http://localhost:8080
- API directly for debugging: http://localhost:8000
- PostgreSQL for local DB clients: localhost:5432

The `migrate` service waits for healthy PostgreSQL and applies Alembic
migrations once. The API starts only after that service completes successfully;
the API container command does not mutate the schema. The internal
`DATABASE_URL` must use the Docker service name `postgres:5432`; host tools use
the loopback PostgreSQL port instead.

Canonical health endpoints are `/api/health/live` for process liveness and
`/api/health/ready` for PostgreSQL-backed readiness. Docker and external
monitoring use readiness. These are the complete supported health surface;
the older `/health`, `/health/live`, and `/health/ready` paths are removed and
return HTTP 404.

Local API configuration uses the same environment variable names as production,
with development values supplied by `.env.example`, local `.env`, or the
worktree harness. Set `APP_ENV=development` for local Compose and keep
`DATABASE_URL`, `APP_PUBLIC_BASE_URL`, `CORS_ALLOW_ORIGINS`, and
`CLOUDPAYMENTS_ENABLED` explicit.

## Production Compose workflow

Copy `.env.production.example` to `.env.production`, supply production secrets,
and run:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

Production Compose runs PostgreSQL, the one-shot migration service, API, web,
and Caddy. Migration failure prevents API startup. Only Caddy publishes host
ports (`80` and `443`); API, web, and PostgreSQL stay on the internal Docker
network. Set `CADDY_DOMAIN` and `NEXT_PUBLIC_API_BASE_URL` to the public HTTPS
origin before building because `NEXT_PUBLIC_*` values are captured in the
Next.js production image. External monitors such as HetrixTools can use
`https://<CADDY_DOMAIN>/api/health/ready`.

Set `APP_ENV=production` in the external production env file. Production uses
the same variable names as local development, but required API values must be
provided explicitly; `docker-compose.prod.yml` does not provide fallback values
for `APP_ENV`, `APP_PUBLIC_BASE_URL`, `CORS_ALLOW_ORIGINS`, or
`CLOUDPAYMENTS_ENABLED`, and it also requires explicit `POSTGRES_DB`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `CADDY_DOMAIN`, and
`NEXT_PUBLIC_API_BASE_URL`. Production Compose derives the API `DATABASE_URL`
from `POSTGRES_*` so PostgreSQL initialization and API migrations cannot drift.
Keep `.env.production` outside Git and use `.env.production.example` only as a
template.

Never commit production secrets. Card data is handled by the responsible
external payment boundary and must not be collected or stored by this
repository. For the current transitional direct-provider flow, that boundary
is CloudPayments.

## Current limitations

- Implemented routes and legal documents are the `ru` contour only.
- Password-based demo authentication with SMTP-backed password reset;
  production email verification is planned.
- Contour confirmation via Region Resolver is planned and not implemented.
- The private regional entitlement/access API for Platform Kernel is planned
  and not implemented yet.
- Legal documents are drafts until reviewed and approved by counsel.
