# API Agent Guide

Read the root `AGENTS.md`, `ARCHITECTURE.md`, [contours](../../docs/architecture/contours.md),
[payment providers](../../docs/architecture/payment-providers.md), the
canonical data-model document, and the
[API section of coding conventions](../../docs/engineering/CODING_CONVENTIONS.md#api--python)
before backend work.

## Conventions

- JSON request bodies and ordinary JSON responses use Pydantic models; response
  schemas are exposed in OpenAPI. Untyped routes belong only on the frozen
  legacy list or the raw-response list beside the architecture test.
- Keep `dict[str, Any]` at the provider edge; decode before domain logic.
- New or changed errors use `detail: {"code": "..."}`. Use `StrEnum` only for
  states the slice compares or transitions; keep ORM statuses as `Text`.
- Do not invent fallback domain values. One module owns a given state
  transition.

## Boundaries

- `core` contains configuration, database, logging, telemetry, and shared
  security helpers.
- `domains` contains identity, legal, and billing models and behavior.
- `integrations` translates provider-specific input into domain operations.
- Routers validate HTTP input and delegate to services.

Domain modules must not import routers or provider integrations. Provider
payloads must be verified, redacted, normalized, and processed idempotently
inside the adapter. CloudPayments is the current `ru` adapter.

## Tooling

The API uses uv `0.12.7`, with `apps/api/pyproject.toml` and
`apps/api/uv.lock` as its dependency source of truth. Repository tooling
explicitly selects the repository-root `.venv`; do not create `apps/api/.venv`
or require shell activation. Use the root npm aliases for dependency and API
operations.

PostgreSQL tests use the current worktree's test server. Start it with
`make test_db_up` on Unix/WSL or `python scripts/repo.py test-db up`, then run
the PostgreSQL or complete API test alias and stop it with the matching
`test_db_stop` command. pytest remains the owner of the physical `_tests`
database lifecycle.

## Safety

- Payment success comes only from verified provider state.
- Never log authentication tokens, authorization headers, secrets, card fields,
  or unredacted webhook bodies.
- Legal acceptance records are append-only.
- Use forward migrations after the corrected initial baseline is frozen.
- Add PostgreSQL coverage for schema or migration changes.

## Checks

```bash
npm run test:api:fast
npm run architecture:check
npm run migrate:api
```

Use `npm run test:api:postgres` for PostgreSQL-only coverage and
`npm run test:api` for the complete backend suite after starting the local test
server or supplying explicit test database configuration.
