# Coding Conventions

Status: authoritative
Last verified: 2026-08-19

How to write **new and changed** code so types, states, and trust boundaries
stay explicit. This is not a backlog and not a mass-migration plan.

Related documents:

- [Architecture](../../ARCHITECTURE.md) — dependency direction and ownership
- [Data model](../architecture/payment-portal-data-model.md) — persistence
  invariants
- [DDD-lite audit](../architecture/ddd-lite-audit.md) — smell catalog; not a
  burn-down list
- [API agent guide](../../apps/api/AGENTS.md) and
  [web agent guide](../../apps/web/AGENTS.md) — MUST digests for each subtree

## Ratchet

Rules apply to new and changed code. Fixing existing debt requires its own
Linear ticket. Do not expand a feature PR into a conventions cleanup.

When the OpenAPI guardrail lands, two route lists live **next to that
architecture test**, not in this file:

- `legacy_untyped_routes` — existing untyped JSON debt. New entries are
  forbidden. Removing an entry is welcome. Each entry is a route plus a Linear
  ticket.
- `raw_response_routes` — permanent exceptions: webhook responses, metrics,
  readiness, and other raw `Response` objects.

Do not put dates on either list.

Frontend `eslint --max-warnings=0` makes `warn` equal `error`. Enable the
unsafe-assertion rule as `error` only after current `json()` /
`JSON.parse` assertions are removed.

## Common

1. Validate external data once at the system boundary. Interior code uses the
   checked type.
2. Define a finite business state next to the code that owns it. Do not create
   global enum or error-code catalogs.
3. Extract a constant when the value repeats, sets policy, or its unit is
   otherwise unclear. Do not name obvious `0` / `1`, HTTP markup, SVG geometry,
   or local CSS.
4. Do not add an abstraction, helper, or type before a current consumer exists.
5. A change to branching, a parser, a decoder, or money logic gets one focused
   test. Every decoder has a test that rejects an invalid value.
6. Required production configuration and invalid boundary data must fail
   validation; do not invent fallback domain values. Catch an exception only
   when converting it, recovering safely, or adding necessary context.
   Unhandled exceptions are logged once at the system boundary without raw
   inputs or secrets.

## API / Python

1. JSON request bodies and ordinary JSON responses use Pydantic models. FastAPI
   must expose a named response schema through `response_model=` **or** a
   Pydantic return annotation. Check the generated OpenAPI schema, not the
   keyword alone.
2. `dict[str, Any]` is allowed only at the provider boundary. Convert to a
   validated model before business logic.
3. Use `StrEnum` for states the slice compares or transitions. A one-off
   discriminator may stay `Literal`.
4. ORM columns keep evolving statuses as `Text`. Do not introduce PostgreSQL
   enums. See the [data model](../architecture/payment-portal-data-model.md).
5. Transitions for one state live in one owner module. See
   [architecture](../../ARCHITECTURE.md) and the
   [data model](../architecture/payment-portal-data-model.md).
6. Represent money as `amount_minor: int` or `Decimal`. The unit is visible in
   the name.
7. New or changed API errors use `detail: {"code": "<stable_id>"}`. String
   `detail` is legacy and migrates with the slice that touches it. Codes are
   feature-owned and stable; do not require a feature-name prefix.

## Web / TypeScript

1. `response.json()`, `JSON.parse`, storage, and query parameters are
   `unknown` until a decoder succeeds.
2. `as SomeResponse` is not validation. A type assertion inside a decoder is
   not a decoder. The decoder must throw or otherwise fail on mismatch.
3. Shared HTTP helpers accept a decoder or return `unknown`. A generic type
   parameter without a decoder is forbidden. Keep existing auth-token
   parameters; do not drop them to insert the decoder.
4. Place API types in `shared/api` or the feature API module. A component must
   not declare its own copy of a response type.
5. Model UI states as a union or `as const` vocabulary and handle them
   exhaustively.
6. Inspect errors through `ApiError.status` and `detail.code`, never
   `message.includes(...)`.
7. Define a repeated timeout, storage key, or poll interval once, with the
   unit in the name.
8. Do not add a schema library or OpenAPI client generator for a single
   contract.

## Planned guardrails

These checks are **not** implemented by this documentation change. They need
separate Linear tickets:

1. Architecture test: every JSON route has a named response schema in generated
   OpenAPI, or appears on `raw_response_routes` or the frozen
   `legacy_untyped_routes` list beside that test.
2. ESLint/AST: forbid `response.json() as T` and `JSON.parse(...) as T` in
   production `src/` after those call sites use decoders.
3. The decoder rejection test in Common item 5 applies as soon as a decoder is
   added.
