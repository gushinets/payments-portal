# Testing Strategy

Status: authoritative
Last verified: 2026-08-28

## Layers

- Static: documentation, generated-artifact, import-boundary, lint, and build
  checks.
- Unit/API: fast FastAPI behavior tests using isolated in-memory state.
- PostgreSQL: real Alembic upgrade/downgrade, seed, constraint, and idempotency
  checks.
- Browser: Playwright journeys against an isolated full stack.
- Runtime: assertions against structured logs, metrics, and traces.

## Commands

```bash
npm run check:fast
npm run test:api:fast
npm run test:api:postgres
npm run test:api
npm run test:e2e
npm run check
```

Tests use synthetic users and payment payloads. A skipped PostgreSQL or browser
suite must be stated explicitly in handoff evidence.

`test:api:fast` excludes PostgreSQL and can run without a database server.
`test:api:postgres` runs the PostgreSQL layer. `test:api` runs the complete
backend suite, including PostgreSQL coverage.

On Unix/WSL, use the repository's worktree-scoped PostgreSQL server lifecycle:

```bash
make test_db_up
npm run test:api:postgres
npm run test:api
make test_db_stop
```

The cross-platform equivalents are `python scripts/repo.py test-db up` and
`python scripts/repo.py test-db stop`. Compose owns the PostgreSQL
server/container, `repo.py` owns worktree-specific server orchestration, and
pytest owns creation, migration, schema reset, and teardown of the disposable
`_tests` database. Developers must not manually create or drop the physical
test database.

Test database configuration is resolved in this order: an explicit
`TEST_POSTGRES_DATABASE_URL`; a complete explicit `POSTGRES_*_TEST`
configuration (partial configuration is rejected); then the current worktree
runtime configuration, using its mapped host port and a derived database name
ending in `_tests`. Credentials remain environment-provided and are not shown
in documentation.

## Test fixtures

`apps/api/tests/conftest.py` is the shared API test-resource composition root.
Before creating test setup code, reuse its existing fixtures, including the
PostgreSQL URL, engine, session factory, migrated database, and rollback-safe
session fixtures.

When multiple test modules need a missing resource or lifecycle, add a typed
fixture to `conftest.py` with explicit scope, setup, and teardown so the resource
has one owner. Keep a fixture inside a test module only when its setup is truly
specific to that module, and compose it from shared fixtures rather than
creating a second database, engine, or session lifecycle.

PostgreSQL tests must not resolve database environment variables or perform
physical database lifecycle independently when a shared fixture already owns
that responsibility. Every destructive database or schema operation must pass
the shared test-database safety validation before connecting or executing SQL.

## Test data factories

New API tests should build Pydantic DTOs, ORM models, and reusable payloads
through typed factories under `apps/api/tests/factories/`. Existing tests may
continue using inline setup until they are touched for a related change, then
they should migrate only the affected setup to factories.

Use factories for object shape and default test data. Use fixtures for resource
lifecycle, dependency overrides, environment changes, database sessions, and
other setup that requires teardown. Put a fixture in `apps/api/tests/conftest.py`
only when multiple test modules need it; keep module-specific setup as a
module-local fixture near the tests that use it.
