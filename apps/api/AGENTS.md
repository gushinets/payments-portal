# API Agent Guide

Read the root `AGENTS.md`, `ARCHITECTURE.md`,
[contours](../../docs/architecture/contours.md), and the
[API section of coding conventions](../../docs/engineering/CODING_CONVENTIONS.md#api--python)
before backend work.

For new billing work, follow the target authority chain before consulting any
retained billing document:

1. [ADR 0005](../../docs/architecture/decisions/0005-external-billing-boundary.md)
2. [External Billing Boundary Design](../../docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md)
3. [Portal ↔ Kernel Access Contract Design](../../docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md)

The [payment-provider document](../../docs/architecture/payment-providers.md)
is historical characterization of the physically removed direct-provider
boundary, the
[billing-authority document](../../docs/architecture/billing-authority.md) is
historical/superseded only, not current-state or target authority, and the
[data-model document](../../docs/architecture/payment-portal-data-model.md) is
the authoritative current as-built schema reference. None overrides the target
authority chain or defines later external-billing runtime behavior.

## Conventions

- JSON request bodies and ordinary JSON responses use Pydantic models; response
  schemas are exposed as named OpenAPI components. The architecture test
  rejects active ordinary JSON success responses without a named component,
  explicitly covers readiness `503`, and keeps metrics outside OpenAPI. There
  is no legacy untyped-route escape list.
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
normalized at the owning Integration boundary. CloudPayments, the direct-
provider adapter/registry, and the Portal-owned
`Product`/`Plan`/`Order`/`Payment`/`Subscription`/`Entitlement` runtime are
physically removed. An external billing system is a distinct boundary; do not
recreate those abstractions for it.
Provider-independent clean pre-production cleanup may precede Phase 0;
provider-dependent LBX production semantics and paid-access derivation remain
Phase 0 gated under `ANY-504`.

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

- Target paid access changes only from the authoritative sources
  permitted by ADR 0005 and the accepted designs; a browser return, Widget
  callback, webhook, outbound request success, or payment state alone is not
  access authority. No billing producer/callback runtime is currently present.
- Never log authentication tokens, authorization headers, secrets, card fields,
  or unredacted webhook bodies.
- Legal acceptance records are append-only.
- Use forward migrations after the clean first-install baseline is frozen.
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
