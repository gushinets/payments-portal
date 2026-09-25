# ANY-408 — Consolidate Post-Reset Baseline & Remove Compatibility Debt

## Plan Overview

| Field | Value |
| --- | --- |
| Program | `ANY-504` |
| Ticket | `ANY-408` / Step 4A |
| Baseline | `main` after merged `ANY-522` / PR #119 (`f6feebdacee856d543d8cf3e9d5b009040c7dd84`) |
| Overall status | `done` |
| Execution order | Sequential: implement one step -> manual verification -> commit -> next step |
| Steps / commits | 6 |
| Fixed predecessor baseline | `ANY-505`, `ANY-509`, `ANY-510`, `ANY-522` |
| Successor boundary | `ANY-525` / Step 4B and later `ANY-504` LBX work remain out of scope |

## Execution Contract

1. Start from the current `ANY-408` branch based on merged `ANY-522`.
2. Give the execution model this plan and ask it to implement only the selected step.
3. Do not redo broad architecture research. Inspect only directly relevant current files and consumers needed for the selected step.
4. The execution model must not run tests, linters, formatters, generators, stage files, or create commits.
5. After implementation, review the diff and run the listed verification commands manually.
6. Commit only after focused verification passes.
7. If current code materially contradicts a fixed assumption, stop and report the contradiction instead of redesigning the architecture.

## Context and Locked Decisions

`ANY-408` is a bounded provider-independent cleanup after the clean persistence reset. It consolidates the repository after `ANY-522`; it does not redesign Payments Portal and must not pull forward `ANY-525`, LBX Phase 0, or later paid-access runtime work.

The current baseline already establishes:

- `settings.instance_tenant_id` and `settings.instance_region` as authoritative runtime contour scope;
- `app.models` as the canonical ORM and persisted-enum import surface;
- Presentation may receive a request-scoped SQLAlchemy `Session` through FastAPI DI and pass it inward;
- Application/service use cases may own outer commit/rollback;
- `app.infrastructure.queries` owns focused query mechanics;
- `app.infrastructure.persistence` owns focused storage-specific mechanics and never owns the outer transaction;
- no repository-per-model, generic Unit of Work, command bus, DI container, or parallel domain-entity graph is required;
- the provider-neutral external-billing persistence model remains persistence-only in this ticket;
- existing public auth/session/legal/password-reset/health/metrics behavior must remain compatible;
- `ANY-525` owns internationalization and localization.

No database migration is expected from this plan. Moving SQLAlchemy model definitions between Python modules must leave physical schema and generated database artifacts unchanged.

## Global Invariants

Every step must preserve:

- public endpoint paths and HTTP status behavior;
- existing JSON field names and values;
- identity/session/legal transaction ownership and failure semantics;
- legal acceptance text/hash/version semantics;
- `/api/health/live`, `/api/health/ready`, and `/metrics`;
- metrics exclusion from OpenAPI;
- readiness `503` behavior and safe response;
- `app.models` as the canonical persisted model/enum surface;
- provider-neutral persistence schema and constraints;
- Presentation -> Application/service -> focused query/persistence dependency direction;
- infrastructure helpers not owning outer commit/rollback.

Do not implement LBX/provider runtime semantics, paid-access delivery, Platform Kernel runtime work, new persistence schema, i18n/localization, UI redesign, broad typing migration, unrelated repository cleanup, or replacement architecture for completed predecessor decisions.

---

## Step 1 — Consolidate API structure and remove compatibility debt

**Status:** `done`

### Goal

Bring the API source layout into the approved post-reset architecture: remove obsolete compatibility facades, normalize canonical imports, remove confirmed pass-through/dead compatibility code, consolidate cross-cutting HTTP Presentation concerns, and leave `main.py` composition-only.

### Scope

Primary compatibility candidates:

- `apps/api/app/auth.py`
- `apps/api/app/database.py`
- `apps/api/app/legal.py`
- `apps/api/app/legal_consents.py`
- `apps/api/app/settings.py`
- `apps/api/app/domains/identity/session.py`
- `apps/api/app/domains/identity/models.py`
- `apps/api/app/domains/legal/models.py`

Directly affected code may include identity/legal/password-reset Presentation and services, `scripts/repo.py`, focused tests/guards, `main.py`, `health.py`, `http_dependencies.py`, `http_errors.py`, and `architecture-limits.json`.

### Implementation Decisions

1. Move remaining consumers from compatibility modules to canonical owners before deleting facades.
2. Canonical ownership remains: ORM/persisted enums -> `app.models`; database -> `app.core.database`; settings -> `app.core.settings`; identity/legal behavior -> owning feature/service module.
3. Remove the accidental Presentation-level `normalize_email` re-export and update direct consumers to the service owner.
4. If `load_account_session()` and its result type still only copy already-available `User` fields, remove them and map the authenticated `User` directly into Presentation output.
5. Import legal acceptance helpers/constants from `domains.legal.acceptance_text` rather than using `domains.legal.service` as an import facade.
6. Delete `present_required_document()` only if the final local consumer scan confirms it is unused.
7. If `legal_seed.DEFAULT_TENANT_ID` still represents legal-manifest identity, rename it accordingly; do not replace it with runtime `settings.instance_tenant_id`.
8. Add a bounded architecture/import guard preventing removed compatibility paths from returning.
9. Remove the stale identity-router source-size exception once the router fits the default limit.
10. Introduce a small cross-cutting `app.http` package, intended as `dependencies.py`, `errors.py`, `health.py`, and `metrics.py`.
11. Keep identity, password-reset, and legal routers with their feature slices.
12. Move the metrics router/handler out of `main.py`.
13. Leave `main.py` responsible only for application/lifespan composition, middleware/exception registration, router registration, and top-level observability composition.
14. Preserve health/metrics paths, metrics OpenAPI exclusion, readiness DB probe behavior, readiness `503`, redaction, failure-location diagnostics, and single reporting ownership.
15. When moving `http_errors.py` under `app/http/`, preserve path-anchor semantics explicitly: `APPLICATION_ROOT` must still resolve to `apps/api/app`, `REPOSITORY_ROOT` must still resolve to the repository root, and reported failure locations must remain repository-relative paths such as `apps/api/app/...`. Do not derive `APPLICATION_ROOT` from the new module's immediate parent. Add focused regression coverage using an exception raised from outside `app/http`.
16. Do not introduce typed response-contract cleanup yet; Step 2 owns it.

### AI Prompt

Implement only Step 1 of `ANY-408`: consolidate the API structure and remove remaining post-reset compatibility debt.

Use the current repository state after merged `ANY-522` as the implementation baseline. Do not redo broad architecture research.

Migrate remaining consumers away from compatibility-only modules to canonical owners, delete unused facades, remove the accidental identity-router `normalize_email` re-export, remove pure pass-through account-session mapping if still present, import legal acceptance helpers from their actual owner, delete confirmed unused touched helpers, and rename the legal-manifest tenant constant if its current name remains misleading.

Add a bounded guard preventing removed compatibility paths from returning and remove the obsolete identity-router line-limit exception.

Move shared HTTP dependencies/errors/health/metrics into a small `app.http` package, move the metrics endpoint out of `main.py`, keep feature routers in their current domain slices, and leave `main.py` composition-only.

When moving the HTTP error module, preserve its existing root semantics explicitly: the application root must remain `apps/api/app`, the repository root must remain the repository root, and failure-location diagnostics must continue to report paths such as `apps/api/app/...` even though the module now lives under `app/http/`. Add focused regression coverage for a failure originating outside `app/http`.

Preserve public API behavior, health/metrics behavior, readiness behavior, diagnostics/redaction, transaction semantics, and persistence semantics. Do not create new architecture abstractions or facade layers.

Do not run tests, linters, formatters, generators, stage files, or create commits. After implementation, report changed/deleted/moved files, summarize the resulting canonical API/module structure, and report the exact verification commands I should run manually.

### Manual Verification

```bash
npm run architecture:check
npm run test:api:fast
```

Additionally verify by repository search that no imports of deleted compatibility modules remain.

### Expected Completion

- obsolete compatibility facades are gone;
- consumers use canonical owners directly;
- removed paths are protected by a static guard;
- stale identity-router size exception is gone;
- cross-cutting HTTP Presentation lives under `app.http`;
- `main.py` contains no endpoint/router handlers;
- health/metrics/failure behavior remains compatible.

### Proposed Commit

`refactor(api): consolidate post-reset presentation structure`

---

## Step 2 — Make API response contracts explicit and enforce OpenAPI guardrails

**Status:** `done`

### Goal

Make every active ordinary JSON API response explicit and named in OpenAPI while preserving the exact existing public wire behavior. Split the oversized mixed API test surface already touched by this work.

### Implementation Decisions

1. Add Presentation-owned Pydantic response DTOs for register, login, session, logout, password-reset request/confirm, legal required-documents/acceptance, liveness, readiness success, and readiness `503`.
2. Preserve every existing path, HTTP status, field name, and JSON value.
3. Existing presenter-generated wire strings are compatibility behavior. Fields currently emitted using `str(...)` or `.isoformat()` must remain wire-compatible with the current JSON output; do not silently switch representation through default Pydantic/FastAPI serialization.
4. DTOs remain Presentation-owned; Application/services must not depend on transport contracts.
5. Readiness may continue using explicit `JSONResponse` for 200/503, but OpenAPI must describe named response bodies for both statuses.
6. Metrics remains excluded from OpenAPI.
7. Add a focused guard requiring named success-response schemas for ordinary JSON endpoints and the intentional readiness `503` schema. Do not create a broad permanent legacy escape hatch.
8. Split `apps/api/tests/test_api.py` into a small set of concern-oriented modules: identity/session, password reset, legal, health/system. Reuse existing shared fixtures/helpers.
9. Tests must verify exact runtime payload/status compatibility and generated named OpenAPI schemas.
10. Update coding conventions only where this guard is still described as future work.

### AI Prompt

Implement only Step 2 of `ANY-408`: make the current ordinary JSON API response contracts explicit and enforce them through a focused OpenAPI guard.

Step 1 is assumed complete. Add Presentation-owned Pydantic response DTOs for register, login, session, logout, password-reset request/confirm, legal required-documents/acceptance, liveness, and readiness.

Preserve every existing public route, status, field name, and JSON value. Existing explicit wire serialization is part of the compatibility contract: where the current presenter uses `str(...)` or `.isoformat()`, keep the resulting JSON representation unchanged.

Readiness may continue using `JSONResponse` to select `200` versus `503`, but both bodies must have named documented OpenAPI schemas. Metrics remains excluded from OpenAPI.

Add a focused guard requiring named success-response schemas for ordinary JSON routes. Do not mass-model unrelated framework error responses and do not introduce a broad legacy escape hatch.

Split the current oversized `apps/api/tests/test_api.py` into a small set of concern-oriented modules covering identity/session, password reset, legal, and health/system behavior. Update focused tests to prove exact runtime compatibility and OpenAPI schemas. Update coding conventions only where the guard is still described as planned.

Do not change Application/service transaction behavior or transport coupling. Do not run tests, linters, formatters, generators, stage files, or create commits. After implementation, report changed/new/moved files and the exact verification commands I should run manually.

### Manual Verification

```bash
npm run test:api:fast
npm run architecture:check
npm run generate:check
```

If only intentional OpenAPI metadata changed:

```bash
npm run generate
npm run generate:check
```

Review the generated OpenAPI diff before committing.

### Expected Completion

- active ordinary JSON routes have named success schemas;
- readiness documents 200 and 503 bodies;
- metrics stays outside OpenAPI;
- exact runtime JSON behavior remains compatible;
- mixed API tests are split by concern;
- the OpenAPI guard is implemented and documented.

### Proposed Commit

`refactor(api): make json response contracts explicit`

---

## Step 3 — Harden the web JSON boundary

**Status:** `done`

### Goal

Runtime-validate external auth/password-reset JSON before typed consumption and remove unsafe assertion-based shared HTTP helpers without changing current UI behavior.

### Implementation Decisions

1. Treat `JSON.parse(...)` and `response.json()` results as `unknown`.
2. A shared helper may require a decoder for typed output or return `unknown`; a generic type parameter alone must never claim runtime validation.
3. Add/reuse small decoders for register/login `AuthResponse`, auth session, logout/status responses, password-reset request/confirm responses, and structured API error envelopes where needed.
4. Invalid successful payloads must fail at the API boundary rather than flow into typed UI code.
5. Preserve request paths, authorization headers, timeout/abort behavior, token storage, session-change behavior, and existing Russian presentation strings.
6. Localization remains owned by `ANY-525`.
7. Add focused valid/invalid decoder tests and a bounded existing-style lint/AST guard against unchecked JSON assertions in the covered production API boundary.

### AI Prompt

Implement only Step 3 of `ANY-408`: harden the shared web JSON boundary.

Treat `response.json()` and `JSON.parse(...)` as `unknown`, remove assertion-only typing patterns, require a decoder for typed helper output or return `unknown`, add/reuse focused decoders for auth/session/status/password-reset responses and structured API errors where required, reject malformed successful payloads at the boundary, and preserve URLs, headers, abort/timeout handling, token storage/events, and existing user-facing strings. Add focused decoder tests and the bounded existing-style guard against unsafe JSON assertions.

Do not start internationalization or move Russian strings into locale dictionaries; that belongs to `ANY-525`. Do not change styling or split CSS in this step.

Do not perform unrelated web/component cleanup. Do not run tests, linters, type checks, Playwright, formatters, generators, stage files, or create commits. After implementation, report changed/new files, decoder contracts, and the exact verification commands I should run manually.

### Manual Verification

```bash
npm --workspace @anytoolai/web run test:components
npm run test:boundaries:web
npm run lint:web
npm run typecheck:web
```

### Expected Completion

- external JSON remains `unknown` until decoded;
- typed shared helpers cannot bypass runtime validation;
- malformed payload rejection is covered;
- auth/password-reset behavior remains compatible;
- the unsafe-JSON boundary guard is active.

### Proposed Commit

`refactor(web): validate api json boundaries`

---

## Step 4 — Split global stylesheet without visual changes

**Status:** `done`

### Goal

Restore stylesheet source-size headroom by splitting `globals.css` into cohesive global style files while preserving the existing cascade and rendered behavior.

### Scope

- `apps/web/src/app/globals.css`;
- new cohesive global CSS files under the existing app styling structure;
- the root layout/import point for global styles;
- `architecture-limits.json`.

### Implementation Decisions

1. Split `globals.css` along existing responsibility groups already visible in the file.
2. Keep the current global-CSS approach.
3. Preserve selector order, specificity, media-query ordering, cascade relationships, tokens, and rendered behavior.
4. Do not introduce CSS Modules, Tailwind, CSS-in-JS, selector renames, component rewrites, or visual redesign.
5. Consolidate duplicate selectors only when equivalence is obvious; otherwise move rules unchanged.
6. Remove the `globals.css` line-limit exception once all resulting files fit the default architecture guard.

### AI Prompt

Implement only Step 4 of `ANY-408`: split `apps/web/src/app/globals.css` into a small number of cohesive global CSS files based on responsibilities already present.

Preserve selector order, specificity, media-query ordering, cascade behavior, tokens, routes, and rendered behavior. Keep the current global-CSS mechanism and remove the line-limit exception once the new files fit the normal limit. Do not redesign the UI, rename selectors, rewrite components, introduce a new styling framework, or touch the JSON/API boundary from Step 3.

Do not perform unrelated web cleanup. Do not run tests, linters, type checks, Playwright, formatters, generators, stage files, or create commits. After implementation, report changed/new files, CSS file responsibilities/import order, and the exact verification commands I should run manually.

### Manual Verification

```bash
npm run architecture:check
npm --workspace @anytoolai/web run test:components
npm run test:boundaries:web
npm run lint:web
npm run typecheck:web
npm run test:e2e
```

Review representative desktop/mobile browser evidence for the touched screens when reviewing the Playwright result. Do not introduce a new visual-regression framework solely for this structural cleanup.

### Expected Completion

- global CSS is split by coherent responsibility;
- existing visual/cascade behavior remains unchanged;
- the special `globals.css` size exception is gone.

### Proposed Commit

`refactor(web): split global styles`

---

## Step 5 — Split reconciliation ORM source without schema changes

**Status:** `done`

### Goal

Create structural headroom in the reconciliation persistence source before later billing implementation grows it, while preserving the exact ANY-509/ANY-522 database model.

### Scope

- `apps/api/app/models/billing_reconciliation.py`
- new concern-oriented modules under `apps/api/app/models/`
- `apps/api/app/models/__init__.py`
- directly relevant schema/model/architecture tests/imports

### Implementation Decisions

1. Split models only along coherent persistence concepts already present in the file.
2. Do not redesign the target persistence model.
3. Preserve exactly table names, columns/types/nullability, defaults/server defaults, persisted enum mappings, foreign keys, unique/check constraints, indexes, relationships, and SQLAlchemy metadata semantics.
4. Keep `app.models` as the unchanged canonical public import surface; callers must not need new internal module names.
5. Do not add or modify Alembic migrations.
6. Do not add runtime billing behavior, provider semantics, repositories, UoW, service abstractions, or domain mirrors.
7. Generated database/schema artifacts must remain unchanged.

### AI Prompt

Implement only Step 5 of `ANY-408`: split `apps/api/app/models/billing_reconciliation.py` into a small number of coherent persistence modules without changing database schema, persistence semantics, or the canonical `app.models` public surface.

Use the existing SQLAlchemy definitions as authoritative. Move existing classes/enums/helpers only along clear persistence responsibilities already present in the file. Preserve every table, column, type, nullability, default, persisted enum mapping, foreign key, unique/check constraint, index, relationship, and SQLAlchemy metadata semantic.

Update `apps/api/app/models/__init__.py` so `app.models` remains the canonical import surface and current callers do not need the new internal module paths.

Do not create or modify an Alembic migration. Do not add billing runtime behavior, provider semantics, repositories, Unit of Work, services, or parallel domain entities.

Do not run tests, linters, formatters, generators, stage files, or create commits. After implementation, report changed/new files, which model responsibilities moved where, explicitly state that no intended schema change was made, and report the exact verification commands I should run manually.

### Manual Verification

```bash
npm run architecture:check
npm run test:api:fast
npm run generate:check
npm run test:api:postgres
```

If `generate:check` shows database-schema drift, do not regenerate or accept it. Fix the source move until the generated database schema remains unchanged.

### Expected Completion

- reconciliation persistence modules have structural headroom;
- `app.models` remains the canonical external model surface;
- no migration exists for this refactor;
- generated DB schema is unchanged;
- PostgreSQL persistence tests pass.

### Proposed Commit

`refactor(models): split billing reconciliation models`

---

## Step 6 — Reconcile affected docs, remove obsolete active plans, and finalize the baseline

**Status:** `done`

### Goal

Bring only directly affected documentation, generated artifacts, and repository guards in line with the completed Step-4A implementation, remove obsolete execution plans from the active planning surface, and perform final verification.

### Scope

Directly affected documentation/guards may include:

- `docs/engineering/CODING_CONVENTIONS.md`;
- `ARCHITECTURE.md`;
- directly affected current-state architecture docs;
- `docs/architecture/ddd-lite-audit.md` only because it is still linked from active guidance while describing obsolete CloudPayments-era findings;
- generated OpenAPI/schema artifacts;
- existing docs/architecture guards;
- obsolete execution-plan files for `ANY-83`, `ANY-314`, and `ANY-84` that must no longer remain under `docs/exec-plans/active/`.

### Implementation Decisions

1. Update only documentation made stale by Steps 1-4.
2. Remove active references to deleted compatibility paths or old cross-cutting HTTP module locations.
3. Ensure coding conventions describe the implemented OpenAPI and frontend JSON-boundary guards as current behavior rather than planned work.
4. Preserve the established architecture authority chain; do not create another authority document.
5. Treat `docs/architecture/ddd-lite-audit.md` as a historical CloudPayments-era investigation. If it is still linked as active guidance, move it to the established historical/superseded location or delete it if it has no useful historical value. Do not rewrite it into another current architecture source.
6. Remove the obsolete `ANY-83`, `ANY-314`, and `ANY-84` execution-plan files from `docs/exec-plans/active/`. If the repository convention is to retain completed plans, move them to `docs/exec-plans/completed/`; otherwise remove the stale active copies. They must not remain in `active/` and must not be treated as implementation inputs for ANY-408.
7. Do not research, reopen, or reclassify these tickets during execution; their plan cleanup is repository hygiene only.
8. Do not research or reclassify unrelated Linear tickets or execution plans.
9. Update current-state architecture documentation only for concrete Step-4A module/path/guard changes; do not broadly reorganize documentation.
10. Generated OpenAPI changes caused by explicit response-contract metadata are allowed. Step 4A must introduce no intended database-schema change.

### AI Prompt

Implement only Step 6 of `ANY-408`: reconcile directly affected documentation and guards with the completed Step-4A code, remove obsolete execution plans from the active folder, and prepare the repository for final verification.

Steps 1-5 are assumed complete.

Update only active documentation made stale by Step-4A code changes. Remove references that present deleted compatibility modules or old cross-cutting HTTP locations as current conventions. Ensure coding conventions describe the implemented OpenAPI and frontend JSON-boundary guards as current behavior. Preserve the existing architecture authority chain.

Treat `docs/architecture/ddd-lite-audit.md` as historical CloudPayments-era material and remove it from the active guidance surface if it is still presented as current.

Remove the obsolete `ANY-83`, `ANY-314`, and `ANY-84` execution-plan files from `docs/exec-plans/active/`. If completed plans are retained by repository convention, move them to `docs/exec-plans/completed/`; otherwise remove the stale active copies. Do not research or reopen these tickets, and do not inspect, research, reclassify, or move unrelated execution plans or Linear tickets.

Update current-state architecture docs only for concrete Step-4A path/module/guard changes. Do not implement `ANY-525`, LBX, or later billing runtime work.

Do not manually edit generated artifacts unless that is the repository's established pattern; report the generation command for me to run manually. Do not run tests, generators, linters, formatters, stage files, or create commits. After implementation, report changed/moved/deleted files, summarize affected guidance changes, and report the exact final verification commands I should run manually.

### Manual Verification

First refresh generated artifacts:

```bash
npm run generate
```

Review the generated diff. OpenAPI metadata changes may be intentional; database-schema changes are not.

Then run:

```bash
npm run docs:check
npm run architecture:check
npm run generate:check
npm run test:api:fast
npm run test:api:postgres
npm --workspace @anytoolai/web run test:components
npm run test:boundaries:web
npm run lint:web
npm run typecheck:web
npm run check:fast
```

Run the full repository gate only if this is the normal pre-merge check:

```bash
npm run check
```

### Expected Completion

- active docs describe the actual post-Step-4A code;
- removed compatibility paths are no longer presented as current;
- implemented guards are documented as implemented;
- obsolete CloudPayments-era audit material does not compete with current authority;
- `ANY-83`, `ANY-314`, and `ANY-84` no longer remain under `docs/exec-plans/active/`;
- generated artifacts are synchronized;
- no database schema change was introduced;
- the repository is a clean provider-independent baseline for `ANY-525` and later `ANY-504` implementation.

### Proposed Commit

`docs(architecture): finalize post-reset baseline cleanup`

---

## Final Plan Validation

The implementation sequence is intentionally compact:

1. **API structure** — remove compatibility debt and establish final HTTP/module layout.
2. **API contracts** — make response contracts explicit after the final Presentation layout exists.
3. **Web JSON boundary** — validate external JSON and remove unsafe typed assertions.
4. **Web stylesheet structure** — split global CSS while preserving cascade and rendered behavior.
5. **Persistence source cleanup** — reorganize ORM source while proving zero database drift.
6. **Finalization** — update only affected documentation/guards/generated artifacts and remove obsolete plans from the active execution surface.

The plan implements ANY-408 without reopening predecessor architecture, researching unrelated tickets, cleaning unrelated repository debt, implementing ANY-525/LBX Phase 0, introducing provider runtime semantics, or changing the target persistence model.

No unresolved business-rule, public-API, persistence, ownership, or architectural decision should need to be made by the execution model. If implementation exposes a material contradiction with the current baseline, report it instead of expanding the step or redesigning the system.
