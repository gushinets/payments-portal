# ANY-99 - Upgrade SQLAlchemy, Alembic, and Psycopg

Status: completed
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
- [x] Upgrade the three direct dependencies and regenerate the Poetry lock.
- [x] Run the complete compatibility and production-image validation matrix.

## Baseline Evidence

- Branch `ANY-99` started clean at `origin/main` commit `1a9d798`.
- Baseline versions were SQLAlchemy 2.0.36, Alembic 1.14.0, and psycopg 3.2.3.
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

## Step 2 Evidence

- Direct pins and the lock now resolve SQLAlchemy 2.0.51, Alembic 1.18.5,
  psycopg 3.3.4, and psycopg-binary 3.3.4. FastAPI remains at 0.141.1 and
  Uvicorn remains at 0.52.1.
- The lock diff changes package versions only for the three requested packages
  and the binary distribution required by the Psycopg extra. Re-running
  `poetry lock --no-update` preserved lock SHA-256
  `c55710400134f81cd2433f33f699f8818916bcb40bce22e908c27974e25cb018`,
  and `poetry check --lock` passed.
- Alembic configuration now uses `path_separator = os`, replacing the
  deprecated `version_path_separator` option required by Alembic 1.18 while
  preserving the existing `prepend_sys_path` behavior.
- Focused PostgreSQL ORM, migration, and webhook compatibility tests passed:
  14 passed. The clean Alembic upgrade/downgrade/upgrade cycle reached the
  single head `20260729_0004`, and the concurrent duplicate webhook scenarios
  passed repeatedly across focused and broader suites.
- `make test_api`: 142 passed. The only warnings are the pre-existing Python
  3.12 SQLite datetime adapter deprecations, which are outside this ticket.
- The fast canonical runner passed documentation, architecture, web boundary,
  component and lint checks plus 140 API tests. The full canonical runner also
  passed the production web build.
- The review follow-up removed the runner's `TEST_POSTGRES_DATABASE_URL`-only
  gate and delegated PostgreSQL configuration to the shared pytest fixture.
  With that variable unset and only the local `POSTGRES_*_TEST` fallback
  configured, `npm run check` passed 141 API tests and then ran the standalone
  Alembic phase successfully: 2 passed on PostgreSQL 18.4.
- Production Compose configuration validated. The production API image built
  from a clean dependency layer and installed the requested database versions
  without changing FastAPI or Uvicorn.
- An isolated production smoke stack on PostgreSQL 18.4 started healthy. API
  startup applied every migration to `20260729_0004`, both `alembic current`
  and `alembic heads` reported that single head, and `/health/ready` returned
  `{"status": "ready"}`. The isolated containers, networks, and test volume
  were removed after verification.
- A second production image build with Docker layer caching disabled installed
  all dependencies from the lock. It started against a newly created PostgreSQL
  18.4 volume, and `alembic current --check-heads` confirmed the database was at
  the single head. Real HTTP smoke covered health, legal document discovery,
  registration, session and login, the required-document checkout guard, legal
  acceptances, checkout creation, pending payment status, logout, and rejected
  session reuse. After an API restart, login and the pending product state were
  still available, proving persistence across process lifecycle.
- Public API, PostgreSQL schema and migration history, webhook semantics, env
  variables, and deployment entrypoints are unchanged.
