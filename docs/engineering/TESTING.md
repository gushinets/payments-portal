# Testing Strategy

Status: authoritative
Last verified: 2026-07-11

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
