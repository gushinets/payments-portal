# API Agent Guide

Read the root `AGENTS.md`, `ARCHITECTURE.md`, and the canonical data-model
document before backend work.

## Boundaries

- `core` contains configuration, database, logging, telemetry, and shared
  security helpers.
- `domains` contains identity, legal, and billing models and behavior.
- `integrations` translates provider-specific input into domain operations.
- Routers validate HTTP input and delegate to services.

Domain modules must not import routers or provider integrations. CloudPayments
payloads must be verified, redacted, normalized, and processed idempotently.

## Safety

- Payment success comes only from verified provider state.
- Never log authentication tokens, authorization headers, secrets, card fields,
  or unredacted webhook bodies.
- Legal acceptance records are append-only.
- Use forward migrations after the corrected initial baseline is frozen.
- Add PostgreSQL coverage for schema or migration changes.

## Checks

```bash
npm run test:api
python scripts/repo.py architecture check
python -m alembic -c apps/api/alembic.ini upgrade head
```
