# Coding Conventions

Status: authoritative
Last verified: 2026-11-03

How to write **new and changed** code so types, states, and trust boundaries
stay explicit. This is not a backlog and not a mass-migration plan.

Related documents:

- [Architecture](../../ARCHITECTURE.md) — dependency direction and ownership
- [ADR 0005](../architecture/decisions/0005-external-billing-boundary.md) and
  the accepted [External Billing Boundary Design](../superpowers/specs/2026-09-15-external-billing-boundary-design.md)
  and [Portal-Kernel Access Contract Design](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md)
  — target billing ownership, authoritative facts, and implementation baselines
- [Accepted live-source admission amendment](../superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md)
  — narrow source-read/new-operation supersession; paid-access rules unchanged
- [Billing authority](../architecture/billing-authority.md) —
  historical/superseded only; neither current-state nor target authority
- [Data model](../architecture/payment-portal-data-model.md) — authoritative
  current as-built schema and persistence invariants
- [API agent guide](../../apps/api/AGENTS.md) and
  [web agent guide](../../apps/web/AGENTS.md) — MUST digests for each subtree

## Ratchet

Rules apply to new or materially changed contracts and their affected producers
and consumers, not every untouched declaration in a touched file. Keep existing
debt under its owning delivery; unrelated cleanup requires its own Linear scope.
Do not expand a feature PR into a conventions cleanup.

All new or materially changed Python functions and methods must have explicit
parameter and return annotations. Untouched Python code does not require a
typing migration, and this ratchet does not introduce or require a
type-checking tool.

The API OpenAPI guard requires every active ordinary JSON success response to
reference a named component schema. Readiness explicitly documents both its
named `200` and `503` bodies, and metrics remains excluded from OpenAPI. There
is no legacy untyped-route escape list.

Frontend ESLint rejects direct type assertions on `response.json()` and
`JSON.parse(...)` results in production `src/`. Boundary values remain
`unknown` when read. Successful same-service HTTP JSON is trusted only in the
shared API transport boundary described below; other untrusted inputs require
boundary validation.

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

## Internal contracts

These rules govern Portal-owned shared structures and finite decision values.
Start with a current consumer, invariant and concrete failure or drift risk.
Use KISS/YAGNI; apply DRY to repeated knowledge and invariants rather than
similar syntax. A sufficient primitive or small typed result needs no wrapper.

### Structure, validation and construction

- Known shared inputs, results and snapshots declare required and optional
  fields, including the nested shapes actually consumed. Use a concrete
  dataclass/value object, an owning-boundary model/decoder, or a serialized
  `TypedDict` as appropriate. Bare dictionaries, broad aliases and erased
  dataclass fields do not establish a contract.
- Validate external data and structurally consumed retained data once at their
  actual boundary. Preserve useful nested, argument, result, helper and callable
  types inward instead of erasing them with `Any`, broad aliases or casts.
  Annotations and `frozen=True` do not validate runtime input. Do not revalidate
  every trusted internal call or decode retained data that no consumer reads.
- Give repeated related identity and initialization invariants one concrete
  construction owner. Direct ORM construction remains appropriate when no
  shared invariant justifies extraction. Preserve intentional use-case
  differences and Application ownership of transitions and transactions.
- Genuine maps, opaque original-request snapshots, physical JSON storage and
  necessary SDK/raw-decoding/redaction seams may stay broad with an identifiable
  owner, consumer and reason. A known-key object is not a genuine map.
  Preserve empty stored payloads as `{}` absent an actual consumer requirement.

### One owner for finite meanings

- Closed states, outcomes, kinds, scopes and other finite decision vocabularies
  have an owning enum. Textual Python vocabularies use `StrEnum`. All
  Portal-owned ORM, dataclass and boundary/response model status/state fields
  use enums, including singleton states and fields without transition code.
  This covers queue, review, observation, operator, catalog, health,
  diagnostics/metrics and local UI concepts wherever the slice owns finite
  meanings.
- Reuse symbolic members in annotations, construction, client/server defaults,
  assignments/transitions, comparisons, membership, `match`, queries,
  DML/upserts and results. `str`, `Mapped[str]` or a parallel
  `Literal["resolved", "already_resolved"]` business vocabulary is insufficient.
  `Literal[ResolutionOutcome.RESOLVED]` can narrow a variant. Boolean literals
  and actual fixed schema/protocol tags remain legitimate; an owner constant
  can suffice for a single tag or diagnostic identifier. A singleton response
  status/outcome is not a schema-tag exception.
- Persisted vocabularies reuse the canonical `app.models` owner and existing
  `PersistedEnumType`. Physical PostgreSQL columns remain TEXT/VARCHAR, not
  native ENUM. Enums define vocabulary; Application still owns valid
  transitions, related fields, transactions, leases and fencing.
- Review the complete use path, including positive factories/fixtures,
  serialization and UI consumers. Active ORM CHECK constraints and partial-index
  SQL derive relevant values from their owner or have focused parity checks
  when literal DDL is necessary. Use existing SQLAlchemy facilities, not a
  generic SQL generator. Frozen migrations and independent expected wire/history
  assertions retain literals where they protect compatibility.

### Source ownership and compatibility

- Portal contracts express provider-neutral Portal concepts across regional
  contours. Integrations own vendor DTOs, numeric protocol symbols (`IntEnum`
  where appropriate), normalization and unknown-value handling. Raw external
  strings/numbers stay raw until their owning decoder. Do not duplicate a whole
  vendor DTO in Domain or make LBX fields, calendars or currency policy
  universal Portal requirements.
- Opaque IDs, arbitrary source codes/currencies, user text and ordinary
  quantities are not automatically enums. A locally recognized decision subset
  has an explicit owner. Legal, locale and capability values retain their
  existing source/generation ownership.
- Preserve the backend → OpenAPI → generated frontend wire authority and shared
  transport boundary described below. Local UI finite vocabularies use local
  symbols with exhaustive handling; backend wire enums are not hand-copied.
  Existing type-only frontend enum generation is explicit debt, not a reason
  to create another wire authority or force a generator migration in this step.
- Preserve serialized keys, omitted/null distinctions, spelling, versions,
  equality/coalescing, digests/fingerprints, original identities, receipts,
  immutable history, transactions, leases/fences, enqueue generations, counters
  and deadlines. Do not merge or rename `done`/`completed`. A meaning or
  representation change requires an explicit decision and relevant tests.

### Examples

Use symbolic outcomes and explicit optionality for a known serialized result:

```python
from enum import StrEnum
from typing import NotRequired, TypedDict


class ResolutionOutcome(StrEnum):
    RESOLVED = "resolved"
    ALREADY_RESOLVED = "already_resolved"


class ResolutionResult(TypedDict):
    review_case_id: str
    outcome: ResolutionOutcome
    observation_id: NotRequired[str | None]


result: ResolutionResult = {
    "review_case_id": str(case_id),
    "outcome": ResolutionOutcome.RESOLVED,
}
```

Omitting `observation_id` differs from sending it as null; the type permits both
without instructing a producer to add a key. The existing canonical model
pattern also applies to singleton statuses such as `UserStatus.ACTIVE`:

```python
status: Mapped[UserStatus] = mapped_column(
    PersistedEnumType(UserStatus), nullable=False
)
user.status = UserStatus.ACTIVE
```

The following patterns erase a known contract or scatter its vocabulary:

```python
from dataclasses import dataclass
from typing import Any

outcome = "resolved"
case.case_state = "done"
if result["outcome"] == "already_resolved":
    pass

snapshot: dict[str, Any] = {
    "review_case_id": str(case_id),
    "outcome": "resolved",
}


@dataclass(frozen=True)
class ErasedEvidence:
    subject: Any
    observation: dict
```

Retain consumed nested fields; these trusted dataclasses still need validation
when their values originate at an untrusted boundary:

```python
@dataclass(frozen=True)
class ObservationEvidence:
    observation_id: str
    generation: int


@dataclass(frozen=True)
class ResolutionEvidence:
    observation: ObservationEvidence
```

A mapping with arbitrary metric keys is a genuine map. An Integration-owned
retained request may remain opaque while the envelope and consumed evidence
are concrete; decode the consumed facts once when needed and export only their
normalized meaning inward, without mirroring the whole vendor DTO in Domain:

```python
allowance_by_metric: dict[str, int] = {"source-defined-metric": 10}


class ConsumedCreateEvidence(TypedDict):
    request_key: str
    provider_object_id: str | None


class RetainedRequest(TypedDict):
    # Integration owns retention; the request body is not inspected by this consumer.
    original_request: dict[str, object]
    consumed: ConsumedCreateEvidence
```

These examples describe patterns, not additional required production models.

### Proportionality, exceptions and evidence

Do not introduce speculative models, validators, factories, state machines,
retries, registries, adapters or configuration solely to satisfy rule wording.
Explain bounded technical exceptions near the code or in the PR, reusing
existing debt ownership. Do not add per-field waiver registries, blanket casts
or suppressions, or weaken required guarantees.

Resolve routine reversible implementation choices autonomously. Escalate only
an unresolved new decision about behavior, supported/retained values,
storage/wire compatibility, trust, authorization, ownership or unavoidable scope
growth. Present the smallest viable option and tradeoff, and continue independent
work. Do not ask again for an existing explicit decision.

Distinguish a confirmed rule/enforcement gap from a reproduced runtime defect.
A green suite or additional classes do not establish a missing guarantee.
Documentation alone does not install a Python checker or migrate runtime
contracts; the implemented guards and remaining limits are listed below.

## API / Python

1. JSON request bodies and ordinary JSON responses use Pydantic models. FastAPI
   must expose a named response schema through `response_model=` **or** a
   Pydantic return annotation. Check the generated OpenAPI schema, not the
   keyword alone.
2. Follow the internal-contract rules above for concrete shared shapes and
   bounded broad-data seams. Validate consumed external/retained structure at
   its owning boundary, then retain the type through Application and Domain.
3. Use owning enums for finite meanings and all Portal-owned model status/state
   fields, including singleton states. Textual Python vocabularies use
   `StrEnum`; Integration numeric protocols retain their own symbols. Use
   literal narrowing and schema/protocol tags only as described above.
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
10. Exact raw request bytes are a Presentation/HTTP concern. No active route
    currently requires exact raw bytes, so there is no shared raw-body helper.
    If a concrete requirement is introduced, keep ASGI body acquisition in a
    provider-neutral Presentation/HTTP dependency rather than duplicating local
    body readers in integration routers. Ordinary JSON APIs continue to use
    FastAPI/Pydantic request models rather than manual raw-body parsing.
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
2. Active domain Presentation and `app.http.dependencies` do not import
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

1. Read `response.json()` and `JSON.parse` results as `unknown`. Storage and
   query parameters require boundary validation before typed use.
2. `as SomeResponse` is not runtime validation. Trust successful JSON from our
   own FastAPI service once inside the documented shared API transport helper;
   do not cast API JSON in features/components.
3. Endpoint adapters reuse `getJson<T>` / `postJson<T>` from
   `shared/api/transport.ts` with generated response types above that single
   trust assertion. Keep existing auth-token parameters and malformed
   successful JSON error handling; do not add browser runtime wire schemas.
4. Import HTTP wire DTOs from generated contracts. A component must not declare
   its own copy of a backend response type.
5. Give local finite UI states/outcomes/kinds symbolic owners, such as an
   `as const` vocabulary with a derived union, and handle them exhaustively.
   Keep generated backend wire meanings under their existing authority.
6. Inspect errors through `ApiError.status` and `detail.code`, never
   `message.includes(...)`.
7. Define a repeated timeout, storage key, or poll interval once, with the
   unit in the name.
8. Do not add a schema library or OpenAPI client generator for a single
   contract.

### HTTP API contract boundary

For a value crossing the backend/frontend HTTP boundary, use the repository
authority chain:

```text
FastAPI/Pydantic
  → app.openapi()
  → docs/generated/openapi.json
  → generated TypeScript wire contracts in apps/web/src/generated/api-contracts/
  → shared API transport trust boundary
  → endpoint adapters
  → features/UI and view state
```

Backend owns runtime request/response validation, wire contracts, and OpenAPI.
Generated TypeScript provides compile-time ownership; it does not validate
JSON. The explicit same-service trust assertion lives only in
the private `decodeSuccessfulResponse<T>` in `shared/api/transport.ts`; no
second frontend runtime schema authority exists. Repository generation owns
the generated frontend TypeScript wire contracts and freshness
checking; the canonical commands are `npm run generate` and
`npm run generate:check`, and the generated API contracts live under
`apps/web/src/generated/api-contracts/`. Frontend owns transport, forms, view
models, presentation state, derived UI types, and endpoint adapters; it must
not independently redeclare backend DTO fields.

This boundary applies to HTTP API contracts, not every value shared by Python
and TypeScript. Route locales and mappings remain sourced by
`config/locales.json`, legal acceptance text remains sourced by the legal
source, and other shared non-HTTP constants may retain their own canonical
generation path. API statuses, enums, and values belong to the generated
Pydantic/OpenAPI contract only when they cross HTTP; frontend-only UI/view
state remains frontend-owned.

For each future Portal-owned, web-consumed API: define backend Pydantic
request/response models, expose durable named OpenAPI components, run
repository generation, consume the generated TypeScript contract, use the shared
API transport trust boundary, and keep form/UI/view state local.
Do not mirror External Billing commercial catalog/pricing/sellability truth,
future paid-access authority, or Platform Kernel usage/quota truth in the
Portal. Stop and obtain the owning architecture/API decision when the backend
API is missing, the OpenAPI schema is unnamed or unsuitable, generation cannot
faithfully generate the required TypeScript shape, the frontend would need to
redefine wire meaning, the data belongs to External Billing or Platform Kernel, or a
transport/auth redesign is required.

For the migrated auth surface, successful JSON is trusted once in shared
transport. Invalid JSON syntax still becomes `ApiContractError`; structural
validation remains backend-owned. `ApiError.detail` remains `unknown`, and
`apiErrorCode()` extracts only stable machine codes used by current UI, and no universal generated error model
is implied. The migrated production surface is registration, login, session,
logout, password reset, email verification, and the `email_verified`
session/user fact; account uses auth session/logout contracts, and no current
legal endpoint DTO needed migration because the legal frontend has no parallel
handwritten backend API wire DTO consumer. Web Sentry reporting remains
minimal and privacy-preserving: uncaught failures may reach the separate
`payment-portal-web` project when configured, handled contract failures may use
the sanitized reporter, expected application outcomes are not blanket-reported,
and events contain no payloads, tokens, identity, query/fragment data, or raw
error data. Exception names are normalized to `Error`; stack frames retain
only numeric/boolean location metadata, never free-form identifiers.

### Web locale routing and localization

1. `config/locales.json` is the single machine-readable locale contract. Run
   `npm run generate`; do not hand-edit the generated TypeScript or Python
   locale artifacts. The exact route locales are `en`, `fr`, `it`, `de`, `es`,
   `ru`, and `pt`.
2. Keep locale identities distinct. `routeLocale` is the URL/next-intl routing
   identity; `languageTag` sets the document language; `intlLocale` controls
   formatting. The `pt` route maps to `pt-BR` for both language and formatting.
   `useLocale` returns the `routeLocale`; formatting code must resolve the
   canonical `intlLocale` rather than use that value blindly with `Intl`.
3. Ordinary pages live below `app/[locale]`, and the localized root layout
   derives `<html lang>` from the locale contract. `/` is the only
   Accept-Language negotiation entry. An explicit locale-prefixed URL always
   wins, and arbitrary unprefixed app paths stay not-found.
4. Keep next-intl `localeDetection` and `localeCookie` disabled. Do not persist
   locale in a cookie, localStorage, a user record, or other application state.
   Locale never selects tenant, contour/region, identity, provider, currency,
   or timezone.
5. Use the locale-aware navigation exports in `src/i18n/navigation.ts` for
   normal links, redirects, and route construction. Do not hardcode `/ru` for
   ordinary application navigation. Generated canonical RU legal paths are the
   intentional exception.
6. Canonical and alternate metadata must use the explicit server/build-side
   `APP_PUBLIC_BASE_URL` origin; next-intl does not own alternate metadata.
7. Generated legal routes remain canonical and RU-only and do not receive fake
   locale alternates or switch targets. Reset confirmation does not offer
   locale switching because its token remains fragment/client-only.
8. `apps/web/src/messages/*.json` owns canonical Portal UI and ordinary
   metadata copy. The seven catalogs must have exact leaf-key parity, valid ICU
   syntax, and matching argument and rich-text tag signatures. `pt` uses
   Brazilian Portuguese copy; `ru` is a complete catalog, not a missing-message
   fallback.
9. Translate in Server Components first. The localized root
   `NextIntlClientProvider` stays `messages={null}` and supplies locale/runtime
   context without the complete catalog. True Client Components receive only
   their required current-locale namespace or subset from the nearest server
   boundary. Do not serialize all locales or the full current-locale catalog.
10. `shared/api` owns language-neutral transport facts only. Stable status and
    error identifiers remain untranslated there; the owning web Presentation/UI
    maps them to localized human-readable messages.
11. Canonical RU legal title/body/version/path and generated registration
    acceptance evidence remain source-owned and retain `lang="ru"` where shown.
    Seller/provider facts, support addresses, identifiers, and user-entered
    content also stay outside ordinary message ownership; localize only their
    surrounding Portal labels.
12. Password-reset communication is the narrow locale-metadata exception. The
    forgot-password route derives the canonical `languageTag` from its explicit
    validated `routeLocale` through the generated locale mapping, then sends
    that value as `Accept-Language` metadata on the password-reset request only.
    Keep route-to-language mapping outside `shared/api`; generic transport may
    carry the already-canonical value but does not own localized presentation.
    API Presentation ignores malformed or unsupported candidates individually
    and passes only the winning canonical `RouteLocale` inward. It falls back
    to the generated default `ru` route locale only when normalization leaves
    no valid supported canonical language candidate, including a missing header
    or a header containing only malformed or unsupported candidates. Never
    derive or persist tenant, region, identity, provider, currency, timezone,
    or other application semantics from locale.

## Implemented contract guardrails

1. The API architecture test rejects active ordinary JSON success responses
   whose OpenAPI schema is not a named component reference. It also verifies
   the named readiness `503` response and metrics exclusion.
2. Web ESLint rejects direct TypeScript assertions on `response.json()` and
   `JSON.parse(...)` results in production `src/`.
3. Decoder tests cover both valid payloads and rejection of invalid payloads,
   as required by Common item 5.
4. Web lint rejects routing-owned literal `/ru` ordinary application paths
   while leaving generated canonical legal artifacts available.
5. Web i18n contract tests require exact seven-catalog key, ICU argument, and
   rich-text tag parity. Boundary tests keep localized auth presentation and
   next-intl/catalog dependencies out of `shared/api`.
6. Web i18n contract tests use the TypeScript AST to reject direct ordinary
   human-readable copy in active localized app, feature, and shared UI `.tsx`
   presentation. The guard covers JSX text, direct child string literals, and
   literal `aria-label`, `title`, `placeholder`, and `alt` values. Intentional
   source-owned brand/example exceptions are exact path/surface/value entries;
   new ordinary Portal copy belongs in the locale catalogs.
7. The canonical persisted-model guard derives names from top-level class
   declarations in `apps/api/app/models/enums.py` for the supplied root on each
   call. It rejects external duplicate definitions and protected billing-facade
   symbol imports, including future declarations without an export-list edit.
   Missing, invalid or empty authority fails visibly; historical removed-enum
   prohibitions remain independent.

This ownership guard is not runtime assignment analysis or a Python typechecker.
Existing plain-string state/kind/scope/classification paths remain representation
debt under ANY-800 and their owning runtime deliveries. The current three
plain-string ORM state fields are listed in the
[as-built data model](../architecture/payment-portal-data-model.md#persisted-vocabularies);
their presence does not permit new arbitrary states. Frontend generation still
produces type-only enum representations; lint and review do not prove symbolic
use of every backend or UI value. This delivery changes policy and ownership
enforcement, not those runtime representations or the generator.
