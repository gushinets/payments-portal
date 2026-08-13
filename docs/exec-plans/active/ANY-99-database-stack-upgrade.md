# ANY-99 - Upgrade SQLAlchemy, Alembic, and Psycopg

Status: active
Owner: repository maintainers
Started: 2026-08-13

## Objective

Upgrade the database stack to SQLAlchemy 2.0.51, Alembic 1.18.5, and
psycopg 3.3.4 while proving that ORM metadata, production migrations, webhook
persistence, and the API production image remain compatible with PostgreSQL
18.4.

## Non-goals

- Upgrade FastAPI, Uvicorn, or unrelated direct dependencies.
- Change the public API, PostgreSQL schema, migration history, webhook
  semantics, or deployment contract.
- Refactor application transaction boundaries or replace the current test
  persistence architecture.

## Decisions

- Pin the latest stable releases in the requested major/minor lines; do not use
  the SQLAlchemy 2.1 prerelease.
- Keep ORM metadata validation and production Alembic DDL validation as
  complementary tests.
- Require destructive PostgreSQL tests to target a dedicated database whose
  name ends with `_test` or `_tests`.
- Treat any required schema, migration, API, or runtime contract change as a
  reason to stop and revise the plan before implementation.

## Progress

- [x] Read the issue scope, repository guidance, data model, runtime contract,
  dependency configuration, migrations, persistence code, and tests.
- [x] Record the pre-upgrade unit/API and PostgreSQL 18.4 baseline.
- [x] Strengthen PostgreSQL schema-contract coverage and destructive-test
  safety.
- [ ] Upgrade the three direct dependencies and regenerate the Poetry lock.
- [ ] Run the complete compatibility and production-image validation matrix.

## Baseline Evidence

- Branch `ANY-99` started clean at `origin/main` commit `1a9d798`.
- Current versions are SQLAlchemy 2.0.36, Alembic 1.14.0, and psycopg 3.2.3.
- Alembic has one linear head at `20260729_0004`.
- Unit/API baseline: 128 passed and 11 PostgreSQL-only tests skipped.
- PostgreSQL 18.4 migration, ORM, and webhook baseline: 15 passed, including
  clean upgrade/downgrade/upgrade and both concurrent duplicate webhook tests.
- `poetry --directory apps/api check --lock` passed.

## Validation Plan

- Assert ORM and migrated PostgreSQL contracts for JSONB, foreign keys, partial
  indexes, and rollback behavior.
- Run the clean Alembic upgrade/downgrade/upgrade cycle and verify one head.
- Run unit/API and PostgreSQL integration suites, including repeated focused
  concurrent webhook checks.
- Validate a clean Poetry install and reproduce the lock without a diff.
- Run canonical checks, validate Compose, build the production API image, and
  confirm migration startup plus `/health/ready` against PostgreSQL 18.4.

## Step 1 Evidence

- Destructive schema-reset helpers now reject any PostgreSQL database whose
  name does not end with `_test` or `_tests` before opening a connection.
- PostgreSQL URL resolution, physical database lifecycle, engine ownership, and
  session creation are centralized in `conftest.py`. Alembic and webhook tests
  now consume the same fixtures with either `TEST_POSTGRES_DATABASE_URL` or the
  local `POSTGRES_*_TEST` variables.
- The authoritative testing guide now requires reuse of shared fixtures and
  places reusable resource lifecycle in `conftest.py`.
- ORM metadata checks cover PostgreSQL JSONB compilation, the payment partial
  unique index, and the payment-to-order foreign key. The ORM round trip also
  proves PostgreSQL foreign-key enforcement and recovery after rollback.
- The Alembic cycle inspects migrated DDL for JSONB columns, payment foreign
  keys, all six expected partial indexes, and the provider-payment predicate.
  Its shared Alembic context also preserves pytest logging handlers so migration
  execution cannot break later `caplog` assertions.
- Focused safety tests: 9 passed.
- PostgreSQL 18.4 ORM, migration, and webhook suite: 15 passed with the explicit
  CI URL and 15 passed with the local-variable fallback, including clean
  upgrade/downgrade/upgrade and concurrent duplicate delivery.
- `npm run check:fast`: passed; all 140 API tests passed, including 11 webhook
  PostgreSQL tests that now use the available local fixture configuration. The
  existing SQLite datetime adapter warning remained visible.
- The exact `make test_api` command passed all 142 tests after the Alembic
  logging-isolation regression was fixed.
- Python compilation and `git diff --check`: passed.
