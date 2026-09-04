# API Agent Guide

Read the root `AGENTS.md`, `ARCHITECTURE.md`, [contours](../../docs/architecture/contours.md),
[payment providers](../../docs/architecture/payment-providers.md), the
[billing authority](../../docs/architecture/billing-authority.md), the
canonical data-model document, and the
[API section of coding conventions](../../docs/engineering/CODING_CONVENTIONS.md#api--python)
before backend work.

## Conventions

- JSON request bodies and ordinary JSON responses use Pydantic models; response
  schemas are exposed in OpenAPI. Untyped routes belong only on the frozen
  legacy list or the raw-response list beside the architecture test.
- Keep `dict[str, Any]` only at an untrusted external/integration edge; decode
  to a validated internal type before Application or Domain logic.
- New or changed errors use `detail: {"code": "..."}`. Use `StrEnum` only for
  states the slice compares or transitions. Persisted Python attributes use
  the canonical enums exported by `app.models`, while physical evolving
  database status columns remain `TEXT`/`VARCHAR`.
- New or materially changed Python functions and methods must have explicit
  parameter and return annotations. Untouched code does not require a typing
  sweep.
- Do not invent fallback domain values. One module owns a given state
  transition.

## Boundaries

These are logical responsibilities; current physical packages are transitional
and do not yet map one-to-one to every layer:

- **Presentation** owns HTTP, webhook, CLI, and job entrypoints and delegates to
  Application use cases.
- **Application** owns use-case orchestration, transaction boundaries,
  idempotency, recovery, and normalized internal contracts.
- **Domain** owns business invariants, valid transitions, and entitlement
  rules without transport, vendor, or persistence dependencies.
- **Persistence / Infrastructure** owns database mechanics used by Application,
  not billing or entitlement decisions.
- **Integrations** own external protocols, authenticity checks, parsing,
  redaction, vendor vocabularies, and normalization, not a second local state
  machine.
- **Core / Composition** owns shared infrastructure and concrete wiring, not
  business logic.

Domain modules must not import routers or external integrations. Raw external
payloads must be authenticated or verified, validated, redacted, and
normalized at the owning Integration boundary. CloudPayments is the current
`ru` direct-provider integration; an external billing system is a distinct
boundary and is not another `PaymentProviderAdapter`.

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

- Paid access changes only from verified authoritative billing facts. Current
  CloudPayments supplies those facts through verified webhooks; a browser
  return remains informational.
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
