# AnytoolAI Payment Portal

The Payment Portal is the RU payment, identity, legal-consent, and access-entry
service for AnytoolAI products. It contains a Next.js web application, a FastAPI
API, PostgreSQL persistence, and CloudPayments webhook handling.

The current release scope is the RU CloudPayments MVP. Platform Kernel code is
maintained in the separate
[anytoolai-platform](https://github.com/gushinets/anytoolai-platform) repository.
Planned Payment Portal catalog, subscription, and entitlement work is tracked by
[Linear ANY-71](https://linear.app/paveldik/issue/ANY-71/prorabotat-model-dannyh-payment-portal).

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

## Repository layout

- `apps/web` — Next.js RU portal and legal-page renderer.
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

Never commit production secrets. Card data is handled by CloudPayments and must
not be collected or stored by this repository.

## Current limitations

- RU routes and RU legal documents only.
- Password-based demo authentication; production email verification is planned.
- Payment confirmation is webhook-driven, but the target subscription and
  entitlement model belongs to ANY-71 and is not implemented here yet.
- Legal documents are drafts until reviewed and approved by counsel.
