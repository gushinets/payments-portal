# AnytoolAI Payment Portal

The Payment Portal is the identity, legal-consent, checkout, and access-entry
service for AnytoolAI products. Each production deployment is one contour
(compliance zone). This repository currently ships the `ru` contour.

It contains a Next.js web application, a FastAPI API, PostgreSQL persistence,
and the `ru` CloudPayments adapter. Platform Kernel code is maintained in the
separate
[anytoolai-platform](https://github.com/gushinets/anytoolai-platform) repository.
Planned Payment Portal catalog, subscription, and entitlement work is tracked by
[Linear ANY-71](https://linear.app/paveldik/issue/ANY-71/prorabotat-model-dannyh-payment-portal).
Contour and Region Resolver architecture is documented in
[ARCHITECTURE.md](ARCHITECTURE.md).

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
python -m alembic -c apps/api/alembic.ini upgrade head
```

## Local Compose workflow

Local Compose runs PostgreSQL, the FastAPI API, and Caddy. Next.js stays on the
host so it can use the normal development server:

```bash
docker compose up --build
npm run dev:web
```

Local addresses:

- App through Caddy: http://localhost:8080
- API directly for debugging: http://localhost:8000
- PostgreSQL for local DB clients: localhost:5432

The API container applies Alembic migrations before starting. Its internal
`DATABASE_URL` must use the Docker service name `postgres:5432`; host tools use
the loopback PostgreSQL port instead.

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

Production Compose runs PostgreSQL, API, web, and Caddy. Only Caddy publishes
host ports (`80` and `443`); API, web, and PostgreSQL stay on the internal
Docker network. Set `CADDY_DOMAIN` and `NEXT_PUBLIC_API_BASE_URL` to the public
HTTPS origin before building because `NEXT_PUBLIC_*` values are captured in the
Next.js production image.

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

Never commit production secrets. Card data is handled by the contour's payment
provider and must not be collected or stored by this repository.

## Current limitations

- Implemented routes and legal documents are the `ru` contour only.
- Password-based demo authentication with SMTP-backed password reset;
  production email verification is planned.
- Contour confirmation via Region Resolver is planned and not implemented.
- Payment confirmation is webhook-driven, but the target subscription and
  entitlement model belongs to ANY-71 and is not implemented here yet.
- Legal documents are drafts until reviewed and approved by counsel.
