# ANY-92 — Mandatory CI Quality Gate

Status: completed
Owner: repository maintainers
Started: 2026-07-13

## Objective

Make code quality and production-readiness checks mandatory for every pull
request and push to `main`, while keeping the warm-cache required path within
15 minutes.

## Decisions

- `Code quality` and `Production gate` are the only new required checks.
- Existing browser and harness jobs remain additional non-blocking evidence.
- PostgreSQL 16, Python 3.12, and Node 20 remain the current runtime baseline.
- CI uses an ephemeral trust-authenticated PostgreSQL service and never prints
  or uploads database connection strings.

## Progress

- [x] Add the two required CI jobs and failure diagnostics.
- [x] Verify a single Alembic head and a full upgrade/downgrade/upgrade cycle.
- [x] Validate both Compose files, build production images, and smoke the API.
- [x] Record local and GitHub Actions evidence.
- [x] Configure the emitted checks as required for `main`.

## Completion evidence

- `npm run check:fast`: passed, 21 API tests with no PostgreSQL skip.
- `npm run typecheck:web`: passed.
- `npm run build:web`: passed, 14 static routes generated.
- PostgreSQL 16 migration cycle: passed, including the repeated upgrade.
- Development and production Compose validation: passed.
- Production API and web image builds: passed from a cold local Docker cache.
- Built API image smoke: `/health/ready` returned `ready`.

- GitHub Actions run 29241870479: `Code quality` passed in 58 seconds and
  `Production gate` passed in 67 seconds.
- `main` protection requires strict `Code quality`, `Production gate`, and
  `validate` checks, applies to administrators, and rejects force-pushes and
  branch deletion.
- Draft PR: https://github.com/gushinets/payments-portal/pull/5
