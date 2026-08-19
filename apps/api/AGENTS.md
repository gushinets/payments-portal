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
