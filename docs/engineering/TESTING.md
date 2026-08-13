# Testing Strategy

Status: authoritative
Last verified: 2026-08-13

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
npm run test:api
npm run test:e2e
npm run check
```

Tests use synthetic users and payment payloads. A skipped PostgreSQL or browser
suite must be stated explicitly in handoff evidence.

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
