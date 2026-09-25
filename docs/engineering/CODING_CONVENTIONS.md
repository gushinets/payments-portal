# Coding Conventions

Status: authoritative
Last verified: 2026-09-24

How to write **new and changed** code so types, states, and trust boundaries
stay explicit. This is not a backlog and not a mass-migration plan.

Related documents:

- [Architecture](../../ARCHITECTURE.md) — dependency direction and ownership
- [ADR 0005](../architecture/decisions/0005-external-billing-boundary.md) and
  the accepted [External Billing Boundary Design](../superpowers/specs/2026-09-15-external-billing-boundary-design.md)
  and [Portal-Kernel Access Contract Design](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md)
  — target billing ownership, authoritative facts, and implementation baselines
- [Billing authority](../architecture/billing-authority.md) —
  historical/superseded only; neither current-state nor target authority
- [Data model](../architecture/payment-portal-data-model.md) — authoritative
  current as-built schema and persistence invariants
- [DDD-lite audit](../architecture/ddd-lite-audit.md) — smell catalog; not a
  burn-down list
- [API agent guide](../../apps/api/AGENTS.md) and
  [web agent guide](../../apps/web/AGENTS.md) — MUST digests for each subtree

## Ratchet

Rules apply to new and changed code. Fixing existing debt requires its own
Linear ticket. Do not expand a feature PR into a conventions cleanup.

All new or materially changed Python functions and methods must have explicit
parameter and return annotations. Untouched Python code does not require a
typing migration, and this ratchet does not introduce or require a
type-checking tool.

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
2. `dict[str, Any]` is allowed only at a genuinely untrusted raw external or
   Integration boundary. Convert to a validated internal model before
   Application or Domain logic.
3. Use `StrEnum` for states the slice compares or transitions. A one-off
   discriminator may stay `Literal`.
4. Persisted Python attributes use the canonical enums exported by
   `app.models`. Physical PostgreSQL columns keep evolving statuses as
   `TEXT`/`VARCHAR`; that storage choice does not permit callers to bypass the
   canonical enums with raw strings. Do not introduce PostgreSQL enums. See the
   [data model](../architecture/payment-portal-data-model.md).
5. Transitions for one state live in one owner module. See
   [architecture](../../ARCHITECTURE.md) and the
   [data model](../architecture/payment-portal-data-model.md).
6. Represent money as `amount_minor: int` or `Decimal`. The unit is visible in
   the name.
7. New or changed API errors use `detail: {"code": "<stable_id>"}`. String
   `detail` is legacy and migrates with the slice that touches it. Codes are
   feature-owned and stable; do not require a feature-name prefix.
8. Application, Domain, Persistence, synchronous SQLAlchemy, and current
   synchronous integrations default to ordinary synchronous functions. Use
   `async def` only when that exact boundary must await framework operations or
   genuinely asynchronous outer I/O. A future integration may select either
   modality from its actual I/O client, but must not propagate it into
   Application, Domain, or Persistence.
9. Use normal FastAPI `def` endpoints for flows built on synchronous database or
   network libraries. Never execute blocking SQLAlchemy, synchronous HTTP
   clients, blocking sleeps, or similar work directly on an event-loop path.
10. Exact raw request bytes are a Presentation/HTTP concern. Routes with a
    concrete exact-bytes requirement reuse
    `app.http_dependencies.get_raw_request_body`; integration routers do not
    create local body readers when it applies. The dependency owns only ASGI
    body acquisition. Ordinary JSON APIs continue to use FastAPI/Pydantic
    request models rather than manual raw-body parsing.
11. When an async framework boundary must invoke blocking work, send a complete
    resource-owning synchronous unit through the framework worker mechanism.
    Do not create a request-scoped resource such as a SQLAlchemy `Session` and
    move it through a manually introduced thread bridge.
12. Cancellation of the async waiter does not mean delegated synchronous work
    was forcibly stopped. The delegated unit creates, owns, and closes its
    complete resources, and cancellation must not cause unsafe reuse or an
    overlapping duplicate operation.
13. Do not use `asyncio.run()` to bridge application layers, create duplicate
    sync/async application services, or introduce generic sync/async adapters.
14. Request ID and trace/span/log context must remain correlated across
    framework worker boundaries. New or materially changed functions retain
    explicit parameter and return annotations without unintentionally changing
    FastAPI response-model inference.

### API Presentation and dependency composition

1. Active domain routers parse and validate transport input, invoke an inward
   Application/service use case, and map its result or semantic errors to the
   public HTTP contract. They do not own use-case orchestration.
2. Active domain Presentation and `app.http_dependencies` do not import
   `app.infrastructure.queries` or `app.infrastructure.persistence` and do not
   call SQLAlchemy Session query or persistence mechanics directly. Importing
   `Session` for a FastAPI dependency annotation and passing it inward is
   allowed.
3. Response presenters are pure mappings. They do not receive a Session, issue
   queries, or intentionally trigger ORM lazy loading.
4. FastAPI dependency injection composes explicit resources and context, such
   as the request-scoped Session, authenticated context, and application-scoped
   infrastructure adapters. Stateless Application/service functions remain
   ordinary direct calls and are not placed behind `Depends()` only for
   testability.
5. Public Pydantic request/response DTOs are owned by Presentation. Inward use
   cases accept validated primitives or their own small concrete typed contract
   when structured input/output warrants it; they do not accept router-owned
   DTOs or introduce generic command/query abstractions.
6. Application, Domain, and focused persistence code remain transport-neutral:
   no FastAPI/Starlette request, response, dependency, or `HTTPException`
   types cross inward.
7. When distinct Application/Domain failure meanings require different HTTP
   treatment, Presentation dispatches on concrete feature-owned exception
   types, not arbitrary `.code` strings. Stable codes remain payload or
   diagnostic identifiers; do not create a global class-per-code hierarchy.
   Preserve legacy response shapes in Presentation when compatibility requires it.
8. The outer failure boundary for an operation owns application error
   reporting. Do not report a failure in a lower layer when it will continue
   propagating to that boundary. A bounded operation that intentionally catches
   and absorbs a failure reports it at that catch boundary. Domain and
   Application logic do not import or call `sentry_sdk`; all SDK access stays
   behind `app.infrastructure.sentry`. Keep one reporting owner per failure so
   application reporting and Sentry capture are not duplicated.

### API persistence

1. `app.models` is the canonical persisted ORM model contract. Use its models
   and closed persisted vocabularies; do not create parallel domain entities
   merely to hide SQLAlchemy.
2. Put concern-oriented SQLAlchemy read mechanics in
   `app.infrastructure.queries`: query construction, filtering, joins,
   ordering, loading strategy, and row locking. Prefer focused functions or
   query objects when sufficient; do not require a repository per model or
   table.
3. Reserve `app.infrastructure.persistence` for focused storage-specific write
   mechanics justified by an active use case, such as raw SQL, bulk DML,
   PostgreSQL-specific atomic operations, physical constraint interpretation,
   or storage-specific savepoint behavior.
4. Application retains business decisions and canonical ORM state transitions.
   A SQLAlchemy `Session` may pass through Application or session orchestration.
   Do not add wrappers whose only purpose is replacing `db.add(entity)`,
   `db.delete(entity)`, or direct canonical model mutation.
5. Application orchestration owns the outer business transaction and its
   commit/rollback decision. Focused query and persistence helpers may query,
   lock, flush, execute atomic DML, interpret storage exceptions, and use
   targeted `begin_nested()` savepoints; they must not call `begin()`,
   `commit()`, or `rollback()` to own or finalize the outer transaction.
   SQLAlchemy `Session` autobegin is a database/session mechanism, not an
   application ownership signal.
6. Future provider-neutral billing mutations participate in a caller-owned
   transaction. The caller establishes the transaction boundary and may not
   rely on a focused helper to commit partial work. Use the approved durable
   operation identity, row-lock order, post-lock idempotency recheck, and
   database uniqueness assigned by the owning runtime step.
7. Retry a definitely rolled-back database operation only as the complete
   logical operation, with the same operation identity where one exists. If the
   commit result is uncertain, inspect authoritative persisted state before
   deciding whether replay is safe. Do not add a generic automatic retry loop.
8. CloudPayments/direct-provider persistence has been removed and is not the
   template for external billing. Persistence helpers remain provider-neutral;
   do not recreate direct-provider behavior or a Portal-owned commercial model.

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

1. ESLint/AST: forbid `response.json() as T` and `JSON.parse(...) as T` in
   production `src/` after those call sites use decoders.
2. The decoder rejection test in Common item 5 applies as soon as a decoder is
   added.
