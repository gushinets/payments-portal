# ANY-490 — Establish Presentation Boundary & FastAPI DI — Implementation Plan

## Plan Overview

| Field | Value |
| --- | --- |
| Parent | `ANY-407` |
| Ticket | `ANY-490` |
| ANY-407 step | `7. Presentation Boundary & FastAPI DI` |
| Overall status | `done` |
| Execution order | Sequential only |
| Implementation steps / commits | 5 |
| Required predecessor | `ANY-489` review findings resolved/accepted; ANY-490 branches from the reviewed ANY-489 head |
| Stacked-branch strategy | Execute before ANY-489 merge if needed; rebase/retarget onto final `main` after ANY-489 merges |
| Database schema | No change |
| Alembic migrations | None |
| Public API | No intentional change |
| Web application | Out of scope |
| CloudPayments runtime | Must remain deactivated |
| ANY-407 Steps 8 / 9 | Explicitly deferred |

---

## How to Use This Plan

Execute one step at a time.

For every step:

1. Give the execution model only this plan plus repository access.
2. Ask it to implement the current step only.
3. The execution model must perform only a narrow local verification of the files and symbols named by the step. It must not repeat repository-wide research.
4. The execution model must not run automated checks, stage files, or create commits.
5. Review the diff.
6. Run the listed manual verification commands yourself.
7. Only after the step is accepted, create the proposed commit and continue to the next step.

Do not execute steps in parallel.

---

# Execution Precondition — Pin the Reviewed ANY-489 Baseline

This plan was researched against `ANY-489` PR #102.

ANY-490 **does not need to wait for ANY-489 to merge into `main`**. The implementation may proceed as a stacked branch as soon as the ANY-489 review findings are resolved or explicitly accepted and the reviewed baseline is pinned.

At this plan-validation point, the reviewed ANY-489 head is:

```text
156e5e07a7427aa44c550ab81762e54fe8f515d9
```

If the ANY-489 branch moves again before ANY-490 is created, use the newest reviewed/accepted ANY-489 head instead and record that SHA in the implementation handoff.

Before executing Step 1:

1. Create/switch to `ANY-490` **from the reviewed ANY-489 head**, not from the older `main`.
2. Record the exact inherited ANY-489 commit SHA. That commit is the authoritative predecessor baseline for Steps 1-5 until ANY-489 itself changes.
3. If an ANY-490 PR is opened while ANY-489 is still unmerged, use `ANY-489` as the PR base so the review diff contains only ANY-490 changes. Do not make reviewers re-review the predecessor diff.
4. Inspect only these directly relevant files on the inherited baseline:
   - `apps/api/app/core/database.py`
   - `apps/api/app/http_dependencies.py`
   - `apps/api/app/domains/identity/session.py`
   - `apps/api/app/domains/identity/router.py`
   - `apps/api/app/domains/identity/password_reset.py`
   - `apps/api/app/domains/identity/services/checkout.py`
   - `apps/api/app/domains/legal/router.py`
   - `apps/api/app/domains/legal/service.py`
   - `apps/api/app/domains/billing/router.py`
   - `apps/api/app/domains/billing/catalog.py`
   - `apps/api/app/payment_providers/registry.py`
   - `apps/api/app/main.py`
   - `apps/api/tests/test_architecture.py`
   - `scripts/repo.py`
5. Confirm that the inherited ANY-489 contract still has these semantics:
   - request-scoped SQLAlchemy `Session` lifetime does not imply transaction ownership;
   - Application orchestration owns outer business commit/rollback decisions;
   - focused query/persistence helpers participate in caller-owned transactions and do not finalize the outer transaction;
   - registration is one atomic `User + initial AuthSession` transaction;
   - authenticated-session `last_seen_at` bookkeeping remains its own transaction before the endpoint use case;
   - provider-neutral billing lifecycle operations remain caller-transaction participants.
6. Confirm that all **review-required** ANY-489 architecture-checker fixes are present in the inherited baseline. Explicitly accepted ANY-489 checker limitations are not blockers and must not be reopened by ANY-490.

If ANY-489 changes after ANY-490 has started:

- compare the predecessor delta from the pinned SHA;
- if it is unrelated or documentation-only and does not change an inherited contract, update the branch normally and continue;
- if it changes any directly relevant file, transaction rule, dependency rule, or architecture-checker behavior used by ANY-490, integrate the new ANY-489 head before the next ANY-490 step and revalidate only the affected assumptions;
- do not repeat repository-wide research.

Before ANY-490 is finally merged into `main`:

1. ANY-489 must be merged first.
2. Rebase/retarget the **ANY-490-only commits** onto the final `main` containing ANY-489. If ANY-489 is squash-merged, ensure the stacked history is rewritten cleanly so the ANY-490 PR does not contain duplicate predecessor changes.
3. Verify that the resulting PR diff contains only ANY-490 work.
4. Rerun the Step 5 focused architecture/DI checks and the final repository quality gate on that final integrated baseline.

ANY-489 merge is therefore a **final integration/merge precondition**, not an implementation-start precondition.

---

# Research Summary

## Already-correct architecture to preserve

### `app.main`

`app.main` is already the application/composition edge for:

- FastAPI app creation;
- lifespan;
- middleware;
- exception handlers;
- router mounting;
- app-scoped `PaymentProviderRegistry` construction.

Do not introduce a service container, service locator, or third-party DI framework.

### `app.core.database.get_db`

`get_db()` already owns only the request-scoped SQLAlchemy `Session` lifecycle:

```text
create Session
    ↓
yield Session
    ↓
close Session
```

It must stay that way.

It must not gain:

- automatic commit;
- request-wide automatic rollback as business policy;
- request-wide business transaction ownership;
- implicit Unit-of-Work semantics.

### `app.http_dependencies`

This is already the repository-owned HTTP dependency boundary. It currently owns exact raw-body acquisition and is the correct place for additional FastAPI-only dependency functions.

Do not create a second generic dependencies framework.

### Operational health and metrics endpoints

`app.health` readiness/liveness and the metrics endpoint are operational
Presentation/composition concerns, not domain use cases.

The readiness probe may intentionally acquire its own short-lived database
session and execute a direct readiness query. It is not an example of business
Presentation query orchestration and must not be pulled into the active-domain
Presentation refactor or blocked by the Step 5 domain-Presentation persistence
rule.

Metrics remain operational infrastructure exposure and likewise stay outside
the domain Presentation refactor unless the current implementation itself is
materially broken.

### Existing inward service packages

The repository already has transport-neutral service/application areas such as:

- `app.domains.identity.services`
- `app.domains.billing.service`
- `app.domains.legal.service`

Use and extend these existing areas. Do not perform a broad package rename or introduce a parallel `application/` hierarchy solely for aesthetic purity.

### Canonical ORM model contract

`app.models` remains the canonical persisted model layer.

Do not create a duplicate pure-domain entity hierarchy merely to avoid passing canonical persisted models internally.

For read use cases where Presentation must not depend on lazy ORM state, use small current-use-case result projections when justified. These are read results, not replacement persisted entities.

---

# Confirmed Boundary Violations

## Authentication dependency

`app.domains.identity.session.get_current_session()` currently mixes:

- FastAPI `Depends` / `Header`;
- `HTTPException`;
- bearer-token parsing;
- session lookup;
- user lookup;
- session validity rules;
- `last_seen_at` mutation;
- transaction commit/refresh.

The required split is:

```text
FastAPI dependency
    ↓
parse Authorization header
    ↓
transport-neutral auth/session operation
    ↓
lookup + validate + update last_seen
    ↓
preserve dedicated bookkeeping commit
    ↓
return authenticated context
```

## Identity router

The active identity router currently owns HTTP concerns together with:

- registration orchestration;
- login orchestration;
- logout mutation;
- product/account-state query composition;
- payment-status query composition;
- checkout orchestration;
- persistence query coordination;
- transaction ownership;
- provider-registry use.

## Password-reset router

The password-reset router currently mixes:

- FastAPI request/background-task concerns;
- rate-limit policy;
- persistence operations;
- intentionally separate transactions;
- reset-token creation;
- password mutation;
- session revocation;
- email-delivery scheduling.

## Legal router

`GET /api/legal/required-documents` is already close to the correct boundary.

`POST /api/legal/acceptances` still owns:

- persistence lookup;
- recurring-consent validation orchestration;
- acceptance mutation;
- commit/refresh;
- HTTP mapping.

## Billing/account and catalog routers

These active read endpoints currently own SQLAlchemy query composition and build response DTOs from persisted state in the same layer.

The target is not to hide SQLAlchemy everywhere. The target is that Presentation receives a complete read result and does not decide how to query, join, order, resolve related rows, or intentionally trigger lazy loading.

---

# Locked Architecture Decisions

These decisions are not left to the execution model.

1. **FastAPI DI composes explicit request/app-scoped resources and contexts.** It is not a replacement for ordinary function calls.
2. **Do not put every stateless service behind `Depends()`.** Transport-neutral application functions are called normally.
3. **`get_db()` owns Session lifetime only.** It never auto-commits or defines a request-wide business transaction.
4. **Application orchestration owns business commit/rollback decisions**, preserving ANY-489 exactly.
5. **A concrete SQLAlchemy `Session` may be passed into Application orchestration.** Do not add repository/UoW wrappers merely to conceal it.
6. **FastAPI/Starlette types and `HTTPException` remain outside inward service/application code.**
7. **Transport request DTOs remain in Presentation.** Do not pass router-owned request models into inward services when a use case needs independent typed input.
8. **For complex write use cases, use a small concrete typed command/result only when it prevents Presentation DTO leakage or an unmaintainable parameter list.** Do not build a generic command bus.
9. **For read use cases, prefer small immutable typed result projections containing the exact values needed by the current endpoint.** Do not create a generic mapper framework.
10. **Presenters may convert UUID/datetime/enum values into the existing API shape, but must not execute persistence queries or intentionally depend on lazy loading.**
11. **`PaymentProviderRegistry` stays app-scoped and is created by `create_app()`.** Only its `Request -> app.state` accessor belongs at the HTTP dependency boundary.
12. **FastAPI `get_current_session` belongs to `app.http_dependencies`; the transport-neutral authenticated-session operation belongs under `app.domains.identity.services`.** Do not keep an inward application operation in an arbitrary Presentation-adjacent module merely to preserve the old physical location.
13. **Authenticated-session `last_seen_at` bookkeeping remains a separate transaction before endpoint business work.** Do not merge it into logout, checkout, legal, or any request-wide transaction.
14. **Registration remains one atomic transaction containing `User` plus initial `AuthSession`.**
15. **Login updates `User.last_login_at` and creates the new `AuthSession` in one application-owned commit.**
16. **Password-reset request keeps its intentional multiple committed phases from ANY-489.**
17. **Password-reset confirm remains one logical transaction.**
18. **Legal acceptance remains append-only.**
19. **Checkout keeps its existing transaction and provider-configuration rollback semantics.**
20. **CloudPayments remains deactivated from normal runtime.** Do not modernize or reactivate retained provider-specific code.
21. **Existing public API paths, status codes, validation behavior, response bodies, error shapes, OpenAPI exposure, observability/privacy behavior, and business semantics must remain unchanged.**
22. **Legacy string-shaped HTTP errors remain legacy in this ticket where preserving them is required.** Do not opportunistically normalize them.
23. **ANY-407 Step 8 state-transition redesign and Step 9 subscription/entitlement lifecycle redesign are deferred.** Moving existing orchestration inward is allowed; changing transition semantics is not.
24. **No new ADR is expected.** ANY-490 implements architecture already accepted by ANY-407/ANY-411.

---

# Step 1 — Establish FastAPI DI and the Identity Authentication Boundary

**Status:** `done`

## Goal

Establish the request/app-scoped FastAPI composition boundary and move core authentication mutation orchestration out of the identity router in one coherent change.

After this step:

- FastAPI-specific dependency functions live at the HTTP edge;
- authentication/session resolution is transport-neutral;
- `PaymentProviderRegistry` implementation no longer imports FastAPI;
- register/login/logout handlers are thin HTTP adapters;
- transaction semantics established by ANY-489 are unchanged.

## Scope / affected code

Primary code:

- `apps/api/app/http_dependencies.py`
- `apps/api/app/domains/identity/session.py`
- `apps/api/app/domains/identity/services/` — add or extend a focused auth service module
- `apps/api/app/domains/identity/errors.py`
- `apps/api/app/domains/identity/router.py`
- `apps/api/app/domains/billing/router.py` — only to update the `get_current_session` dependency import/wiring; do not move billing read orchestration before Step 2
- `apps/api/app/domains/legal/router.py` — only to update the `get_current_session` dependency import/wiring; do not move legal acceptance orchestration before Step 4
- `apps/api/app/payment_providers/registry.py`
- `apps/api/app/http_errors.py`
- `apps/api/app/auth.py`
- `apps/api/app/main.py` only if an import/wiring adjustment is required

Focused tests:

- `apps/api/tests/test_presentation_di.py` — new focused DI boundary tests
- relevant auth tests already present in `apps/api/tests/test_api.py`
- existing architecture tests as needed for directly changed boundary assertions

## Implementation decisions

### A. Keep `get_db()` unchanged in responsibility

Do not add transaction policy to `get_db()`.

It continues to:

- create one request-scoped `Session`;
- yield it;
- close it.

Do not add commit-on-success or rollback-on-exception behavior.

### B. Make session authentication transport-neutral

Remove FastAPI/Starlette concerns from the inward session/auth operation.

Place the transport-neutral authenticated-session operation under the existing
`app.domains.identity.services` package. `app.domains.identity.session` must not
remain the owner of an application operation merely to preserve the old physical
location. It may retain only genuinely transport-neutral constants/helpers if
they still have a justified owner there.

The transport-neutral operation must accept:

- `Session`;
- an already extracted bearer token string.

It must own the current persisted authentication behavior:

1. hash token;
2. resolve `AuthSession`;
3. reject missing/revoked/expired persisted sessions;
4. resolve the associated `User`;
5. update `last_seen_at`;
6. `add()` / `commit()` / `refresh()` exactly as required by the existing ANY-489 bookkeeping transaction;
7. return the authenticated `(User, AuthSession)` context or an equivalent small typed internal result.

The inward operation must not import FastAPI/Starlette and must not raise `HTTPException`.

Add one transport-neutral invalid-auth-session error in the identity slice if needed.

Do **not** model a missing/malformed HTTP `Authorization` header as an Application error. That is a transport concern.

### C. Move `get_current_session` to `app.http_dependencies`

The FastAPI dependency owns:

- `Authorization` header extraction;
- `Bearer` prefix validation;
- use of `Depends(get_db)`;
- calling the transport-neutral session operation;
- mapping missing/malformed header to the exact existing `401` + `"missing_session"` detail;
- mapping invalid persisted session to the exact existing `401` + `"invalid_session"` detail.

Do not normalize these legacy error bodies in ANY-490.

Update every active `get_current_session` consumer to import the FastAPI
dependency from `app.http_dependencies`, including identity, billing/account,
and legal Presentation modules. This wiring-only change does not pull billing
read orchestration or legal write orchestration into Step 1.

Do not add an inward-to-Presentation compatibility re-export from
`app.domains.identity.session`; inward/domain service code must not depend on
`app.http_dependencies`.

### D. Move registry request access to `app.http_dependencies`

`PaymentProviderRegistry` remains in `app.payment_providers.registry` and remains app-scoped.

Move only the FastAPI accessor that reads:

```text
request.app.state.payment_provider_registry
```

to `app.http_dependencies`.

After this change `app.payment_providers.registry` must not import FastAPI/Starlette.

`create_app()` remains responsible for constructing `PaymentProviderRegistry`.

### E. Extract register/login/logout application orchestration

Use one focused identity auth service module under the existing `app.domains.identity.services` package.

Move inward:

- tenant/region/email normalization used by these auth use cases;
- session-token generation;
- duplicate-user lookup;
- personal/offer consent decisions;
- password verification;
- `User` and `AuthSession` construction/mutation;
- logout session deletion;
- application-owned commits.

Do not pass FastAPI `Request` or router-owned Pydantic DTOs into the inward service.

For register/login, pass explicit keyword values or a small concrete typed command only if needed to keep the signature readable. Do not introduce a generic command abstraction.

Presentation extracts and passes primitive request metadata:

- client IP;
- User-Agent.

### F. Preserve exact auth transactions

Registration remains:

```text
validate
    ↓
create User
    ↓
create initial AuthSession
    ↓
one atomic commit
```

Login remains:

```text
validate credentials
    ↓
update User.last_login_at
    ↓
create AuthSession
    ↓
one application-owned commit
```

Logout remains:

```text
current-session bookkeeping commit
    ↓
logout use case
    ↓
delete current AuthSession
    ↓
logout commit
```

Do not combine current-session bookkeeping with logout.

### G. Use transport-neutral identity errors for auth business failures

Move these decisions out of router `HTTPException` branches:

- personal consent missing;
- offer consent missing;
- email already registered;
- invalid credentials.

Use identity-owned transport-neutral errors and the existing centralized HTTP error mapping to reproduce the current public responses exactly.

Do not create a global error catalog.

### H. Keep response presentation at the router

Pure response mapping such as the existing user presentation remains at Presentation.

Do not create a generic mapper layer.

### I. Preserve the compatibility façade

Update `app.auth` so its compatibility exports point to the new ownership locations without reintroducing FastAPI into inward identity service code.

Do not remove this compatibility façade in ANY-490 unless it is already unused and its removal is independently required by existing authoritative cleanup instructions.

### J. Add focused DI override tests

Create `apps/api/tests/test_presentation_di.py`.

At minimum prove:

1. `get_current_session` can be replaced through `app.dependency_overrides` for a representative real active endpoint;
2. `get_db` can be overridden without monkeypatching its module global;
3. the app-scoped provider-registry dependency can be substituted through normal FastAPI dependency override mechanics in a focused test setup;
4. dependency overrides are cleared/restored after the test;
5. missing Authorization still returns the exact existing `missing_session` response.

Do not migrate the whole API suite in this step.

## Invariants

- No public auth route changes.
- No auth request/response schema changes.
- No token-format or session-TTL changes.
- `last_seen_at` still commits before the endpoint use case.
- Registration remains atomic.
- Login updates `User.last_login_at` and creates the new `AuthSession` in one application-owned commit.
- Logout remains a separate transaction after session bookkeeping.
- `get_db()` still does not own business transactions.
- `PaymentProviderRegistry` remains app-scoped.
- No CloudPayments registration is added.
- Sync-first behavior remains unchanged.

## Out of scope

- `/api/auth/session` product-state query extraction;
- `/api/auth/payment-status` query extraction;
- checkout orchestration;
- password-reset orchestration;
- legal acceptance;
- billing/catalog read extraction;
- architecture checker redesign beyond the minimum assertions needed for changed code;
- removal of retained CloudPayments source.

## AI prompt

Implement only Step 1 of ANY-490: establish the FastAPI DI boundary and move core authentication mutation orchestration behind a transport-neutral identity service.

Precondition: the current ANY-490 branch already inherits from the pinned reviewed ANY-489 baseline. ANY-489 does not need to be merged into `main` to execute this step. Before editing, inspect only the directly relevant current files named by this step and confirm that `get_db`, registration atomicity, and current-session `last_seen_at` bookkeeping still match the plan. Do not perform broad repository research.

Required implementation:

1. Keep `app.core.database.get_db` as a request-scoped Session lifetime dependency only. Do not add automatic commit, request-wide rollback policy, or request-wide transaction ownership.
2. Remove FastAPI/Starlette concerns from the inward current-session authentication operation. Place that transport-neutral operation under `app.domains.identity.services`. It must receive a Session and an already extracted bearer token, resolve and validate AuthSession/User state, update `last_seen_at`, and preserve the existing dedicated bookkeeping commit/refresh. It must not raise HTTPException. Do not leave the application operation in `app.domains.identity.session` merely to preserve the old physical location.
3. Put the FastAPI `get_current_session` dependency in `app.http_dependencies`. It must parse the Authorization header, use `Depends(get_db)`, call the transport-neutral session operation, and preserve the exact existing 401 response bodies for `missing_session` and `invalid_session`. Update every active consumer of this dependency, including identity, billing/account, and legal Presentation modules, to import it from `app.http_dependencies`. These billing/legal edits are wiring-only in Step 1; do not move their orchestration early. Do not add an inward-to-Presentation compatibility re-export from `app.domains.identity.session`.
4. Move the FastAPI Request accessor for `request.app.state.payment_provider_registry` into `app.http_dependencies`. Keep `PaymentProviderRegistry` itself app-scoped and created by `create_app()`. After the change, `app.payment_providers.registry` must not import FastAPI/Starlette.
5. Add or extend one focused identity auth service under `app.domains.identity.services` and move register/login/logout orchestration there: normalization, token generation, lookups, consent decisions, password verification, User/AuthSession mutation, logout deletion, and application-owned commit behavior.
6. Do not pass FastAPI Request or router-owned request DTOs inward. Pass explicit validated values and primitive request metadata. Use a small concrete typed command only if it is genuinely needed to avoid an unreadable function signature; do not create a generic command bus.
7. Use transport-neutral identity errors for missing personal consent, missing offer consent, duplicate registration, and invalid credentials. Map them through the existing HTTP error boundary while preserving the exact existing status codes and JSON shapes.
8. Keep pure response presentation at the router.
9. Update the `app.auth` compatibility façade to the new ownership locations without reintroducing transport dependencies inward.
10. Add focused FastAPI dependency-override tests proving supported substitution of `get_current_session`, `get_db`, and the app-scoped provider-registry dependency, plus preservation of the missing-session HTTP contract.

Preserve these transaction semantics exactly:
- registration: User + initial AuthSession -> one atomic commit;
- login: update `User.last_login_at` + create AuthSession -> one application-owned commit;
- current-session authentication: `last_seen_at` bookkeeping -> its own commit;
- logout: current-session bookkeeping commit first, then delete session + separate logout commit.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, generators, documentation checks, or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation, report:
- every changed file;
- which responsibilities moved from FastAPI Presentation into the identity service;
- the exact current-session, registration, login, and logout transaction ownership after the change;
- the exact manual verification commands I should run.

If the current inherited baseline materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
pytest apps/api/tests/test_presentation_di.py -q
pytest apps/api/tests/test_api.py -q -k "register or login or logout or session"
npm run architecture:check
```

## Expected completion

- FastAPI dependency composition is owned by `app.http_dependencies`.
- Generic provider registry code contains no FastAPI dependency.
- Register/login/logout handlers parse/map/delegate rather than orchestrate persistence.
- Inward auth/session code contains no FastAPI/Starlette/HTTPException dependency.
- Existing auth transaction and public API behavior are unchanged.

## Proposed commit

`refactor(identity): establish auth presentation boundary`

---

# Step 2 — Move Active Read Orchestration Behind Application Boundaries

**Status:** `done`

## Goal

Move the remaining active read-side persistence/query composition out of HTTP Presentation in one coherent read-oriented step.

This step covers:

- `/api/auth/session` product/account state;
- `/api/auth/payment-status`;
- `/api/account/subscriptions`;
- `/api/account/subscriptions/{subscription_id}`;
- `/api/catalog/products`.

The step is intentionally grouped because all affected use cases are read-side orchestration with no new business transaction ownership. Authenticated routes may still execute the already-established `last_seen_at` bookkeeping transaction in the Step 1 current-session dependency before the read use case starts.

## Scope / affected code

Identity read side:

- `apps/api/app/domains/identity/router.py`
- add/extend a focused module under `apps/api/app/domains/identity/services/`, e.g. `account.py`

Billing/account read side:

- `apps/api/app/domains/billing/router.py`
- add/extend focused read logic under `apps/api/app/domains/billing/service/`

Catalog read side:

- `apps/api/app/domains/billing/catalog.py`
- add/extend focused catalog read logic under `apps/api/app/domains/billing/service/`

Focused tests:

- relevant cases in `apps/api/tests/test_api.py`
- focused result/presenter tests only if required by the new result types

## Implementation decisions

### A. Use typed read results, not Presentation DTOs inward

Each inward read operation should return a small immutable typed result projection containing only values needed by the current endpoint.

Use standard dataclasses or an existing project-appropriate immutable typed model.

These result objects are **use-case read results**, not replacement persisted entities.

Do not:

- return router-owned Pydantic response models from Application;
- use `dict[str, Any]` as an internal read contract;
- create a generic mapper/read-model framework.

### B. `/api/auth/session`

Move inward:

- product/bundle resolution;
- latest Order resolution;
- active entitlement resolution;
- applicable Payment resolution;
- Plan resolution;
- existing access-state decision;
- existing fallback/default product metadata behavior.

Presentation owns only:

- route/query parsing;
- authenticated context dependency;
- response construction / primitive serialization.

If no `product` query is supplied, preserve the current no-product-state behavior without unnecessary queries.

### C. `/api/auth/payment-status`

Move inward:

- normalized email/tenant/region lookup logic required by this current endpoint;
- User lookup;
- Order lookup by the current invoice correlation contract;
- Payment selection, including canceled-order status handling;
- OrderItem lookup;
- Product/Bundle/all-access resolution;
- product-state loading required by the response.

The read operation returns either:

- a complete typed payment-status result; or
- an explicit not-found result.

Presentation maps not-found to the exact existing legacy response:

```text
404
"payment_not_found"
```

Do not redesign the public email/invoice lookup contract in ANY-490.

### D. Account subscription list/detail

Move inward:

- subscription lookup/listing;
- Plan batch/loading logic;
- relevant Entitlement loading;
- current bundle-product loading;
- missing-plan invariant detection.

Return typed subscription read results containing the exact scalar/enum/UUID/datetime values required by the existing response models.

The router keeps existing Pydantic response models and converts the read result into them.

The presenter must not accept `Session`, execute infrastructure queries, or intentionally cause new lazy loads.

Preserve exact error behavior:

- subscription missing -> `404` with `subscription_not_found`;
- persisted subscription missing its Plan -> existing `500` with `subscription_plan_missing`.

Represent the missing-plan condition as a transport-neutral billing/application failure or explicit result and map it in Presentation.

### E. Catalog

Move inward:

- sellable-offer loading;
- effective `now` use;
- existing one-sellable-offer-per-product ambiguity decision.

Return a typed list of current catalog offer results.

Keep existing `Catalog*Response` Pydantic models at Presentation.

For ambiguity, use a small transport-neutral billing-owned failure carrying only safe data required to reproduce the existing API response, including `product_code`.

### F. Preserve defaults and state semantics

Do not change:

- `PRODUCT_DEFAULTS` semantics;
- Order/Payment state meanings;
- entitlement access behavior;
- catalog sellability behavior;
- default tenant/region behavior;
- account-subscription semantics.

If a constant currently belongs to the decision logic being moved inward, relocate it unchanged rather than duplicating it.

## Invariants

- The extracted read use cases introduce no business writes or transaction ownership.
- Authenticated routes preserve the existing Step 1 current-session `last_seen_at` bookkeeping commit before the read use case; this is not part of the read service and must not be removed or merged.
- No new read-use-case commits/rollbacks are introduced.
- Public response/OpenAPI contracts remain unchanged.
- No Order/Payment transition logic changes.
- No Subscription/Entitlement transition logic changes.
- Presentation does not directly import/use `app.infrastructure.queries` for these active paths after the step.
- Presenters perform no database queries.
- No generic mapper/repository framework is introduced.

## Out of scope

- payment-status API redesign;
- replacing email as the current public endpoint lookup input;
- Order/Payment/Refund transitions from ANY-407 Step 8;
- Subscription/Entitlement lifecycle transitions from ANY-407 Step 9;
- cancellation/renewal mutations;
- catalog product redesign;
- schema changes.

## AI prompt

Implement only Step 2 of ANY-490: move all currently active read-side query composition out of FastAPI Presentation for identity account state, payment status, account subscriptions, and catalog.

Step 1 is already complete and verified.

Do not perform broad repository research. Inspect only the current router/service/query files directly involved in the named read use cases.

Required implementation:

1. Introduce small immutable typed application read results for the affected use cases. They must contain only values needed by the current endpoint. Do not pass router-owned Pydantic response models inward, do not use `dict[str, Any]` as the internal contract, and do not create a generic mapper framework.
2. For `/api/auth/session`, move product/bundle/order/payment/plan/entitlement query composition and the existing access-state decision into a focused identity read service. Preserve the existing fallback product metadata exactly. If no product is requested, avoid unnecessary product-state queries.
3. For `/api/auth/payment-status`, move User/Order/Payment/OrderItem/Product-or-Bundle resolution into the same identity read boundary. Preserve the exact current lookup behavior and return an explicit not-found result that Presentation maps to the existing `404` string detail `payment_not_found`.
4. For `/api/account/subscriptions` and `/api/account/subscriptions/{subscription_id}`, move subscription/plan/entitlement/bundle-product query composition into focused billing read service code. Return fully populated typed read results. Keep the existing Pydantic response schemas in Presentation. Preserve `subscription_not_found` and `subscription_plan_missing` responses exactly.
5. For `/api/catalog/products`, move sellable-offer loading and the existing ambiguous-offer invariant inward. Return typed catalog offer results and keep Catalog response schemas at Presentation. Use a small transport-neutral failure for ambiguity and preserve the current public payload including `product_code`.
6. After the change, the affected Presentation modules must not directly compose `app.infrastructure.queries` calls for these use cases. Presenters may convert UUIDs, datetimes, enums, and result fields into the existing API response shape, but they must not query persistence or intentionally trigger new lazy loads.
7. Preserve all current Order, Payment, Subscription, Entitlement, catalog, and fallback semantics. This step is read-side boundary extraction only. For authenticated endpoints, preserve the existing current-session `last_seen_at` bookkeeping transaction before the read service; do not remove it merely because the use case itself is read-only.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only directly relevant current files if needed to verify assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, generators, documentation checks, or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation, report:
- every changed file;
- the typed read-result structures introduced;
- which persistence-query imports were removed from Presentation;
- confirmation that no business write/transaction/state-transition semantics changed and that the existing auth `last_seen_at` bookkeeping transaction is still preserved;
- the exact manual verification commands I should run.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
pytest apps/api/tests/test_api.py -q -k "payment_status or subscription or catalog or session"
npm run architecture:check
```

## Expected completion

- Active read endpoints parse/map/delegate only.
- Query composition is owned inward.
- Presentation receives complete typed read results and does not query persistence.
- API contracts and business state semantics remain unchanged.

## Proposed commit

`refactor(api): extract active read orchestration`

---

# Step 3 — Extract Password Reset Application Orchestration

**Status:** `done`

## Goal

Separate FastAPI request/background-task concerns from password-reset policy, persistence, and transaction ownership while preserving the intentionally multi-phase workflow established by ANY-489.

## Scope / affected code

Primary code:

- `apps/api/app/domains/identity/password_reset.py`
- add `apps/api/app/domains/identity/services/password_reset.py` or the equivalent focused existing service location
- `apps/api/app/domains/identity/errors.py` only if current service imports need adjustment
- observability/email imports only where ownership moves

Focused tests:

- existing password-reset tests in `apps/api/tests/test_api.py`
- focused service tests only if required to cover behavior that can no longer be cleanly asserted through the current endpoint tests

## Implementation decisions

### A. Keep FastAPI-only concerns at Presentation

The router keeps:

- `PasswordResetRequest`;
- `PasswordResetConfirmRequest`;
- APIRouter declarations;
- `Request` metadata extraction;
- `BackgroundTasks`;
- HTTP response construction.

Do not pass `Request` or `BackgroundTasks` inward.

### B. Move request workflow inward

Move into the focused password-reset service:

- email normalization;
- rate-limit-key construction;
- cleanup decisions;
- IP/account rate-limit operations;
- reset-token generation;
- decoy-email identity generation;
- user lookup;
- `MagicLinkToken` construction;
- reset URL preparation data;
- transaction commit/rollback decisions.

Request metadata enters as primitives:

- client IP;
- User-Agent.

### C. Preserve exact request transaction phases

The service must preserve this sequence exactly:

```text
prune expired reset tokens/rate limits
    ↓
commit
    ↓
IP rate-limit mutation
    ↓
commit
    ↓
account rate-limit mutation
    ↓
commit
    ↓
create persisted reset token/decoy evidence
    ↓
commit
```

If a `PasswordResetError` occurs in these phases, preserve the existing rollback/failure behavior.

Do not collapse this into one transaction for architectural neatness.

### D. Return a small delivery result

The request use case returns a small typed result containing only what Presentation needs to schedule the background action, for example:

- recipient email;
- reset URL;
- whether the real delivery function or the no-op/decoy task must be scheduled.

Do not return a FastAPI `BackgroundTask` or callable container abstraction.

Presentation chooses the existing real-delivery vs decoy/no-op task based on this result and schedules it with `BackgroundTasks`.

### E. Preserve anti-enumeration

Known and unknown accounts must retain the same public behavior.

Do not leak account existence through:

- HTTP status;
- response body;
- error body;
- new logs;
- Sentry data;
- different externally visible control flow.

Preserve the decoy persisted evidence and background-task behavior that support this invariant.

### F. Move confirm workflow inward

The confirm use case owns:

- token hash calculation;
- atomic valid-token claim;
- reset-token lookup;
- user lookup;
- password hashing/mutation;
- outstanding reset-token invalidation;
- active auth-session revocation;
- one final application commit.

Keep the existing transport-neutral password-reset errors.

### G. Email delivery helper

The safe email-delivery helper may live with the password-reset service because it contains no FastAPI concern.

Preserve existing:

- observability outcome recording;
- safe logging;
- Sentry behavior;
- SMTP-disabled behavior.

Do not create a job framework.

## Invariants

- Password-reset request/confirm API contracts unchanged.
- Token TTL unchanged.
- Rate-limit values/policy unchanged.
- Anti-enumeration unchanged.
- Multi-phase request commits unchanged.
- Confirm remains one transaction.
- Reset confirmation still revokes active auth sessions.
- No secrets/tokens are added to telemetry.
- `BackgroundTasks` stays at Presentation.

## Out of scope

- new rate-limit algorithm;
- Redis/external rate limiter;
- SMTP redesign;
- durable job queue;
- changing reset-token schema;
- changing session semantics outside existing reset revocation.

## AI prompt

Implement only Step 3 of ANY-490: move password-reset policy, persistence orchestration, and transaction ownership out of FastAPI Presentation while keeping BackgroundTasks and request parsing at the HTTP boundary.

Steps 1 and 2 are already complete and verified.

Do not perform broad repository research. Inspect only the current password-reset router, its directly used identity query/persistence helpers, errors, and email/observability helpers.

Required implementation:

1. Keep the Pydantic request models, APIRouter declarations, Request metadata extraction, BackgroundTasks scheduling, and HTTP response construction in the Presentation module.
2. Create or extend one focused transport-neutral password-reset service under `app.domains.identity.services`.
3. Move email normalization, rate-limit-key construction, cleanup, rate-limit mutation, token generation, decoy identity generation, user lookup, MagicLinkToken creation, and transaction ownership into that service.
4. Preserve the ANY-489 password-reset request transaction phases exactly: cleanup -> commit; IP rate-limit -> commit; account rate-limit -> commit; reset-token/decoy evidence -> commit. Do not collapse them.
5. Preserve existing rollback behavior when PasswordResetError occurs.
6. Return a small typed delivery result containing the recipient/reset URL and whether the real delivery or decoy/no-op background task should be scheduled. Do not pass FastAPI BackgroundTasks or Request inward.
7. Preserve anti-enumeration exactly for unknown users.
8. Move password-reset confirmation orchestration inward: claim token, resolve token/user, update password, invalidate remaining reset tokens, revoke active auth sessions, then one final commit.
9. Keep or move the safe email-delivery helper to the transport-neutral service as appropriate, but preserve all existing logging, metrics, Sentry/privacy, and SMTP-disabled behavior.
10. Do not introduce a job framework, rate-limit redesign, or new persistence abstraction.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only directly relevant current files if needed to verify assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, generators, documentation checks, or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation, report:
- every changed file;
- the exact password-reset request transaction sequence;
- the exact confirm transaction;
- how BackgroundTasks is isolated at Presentation;
- how anti-enumeration remains preserved;
- the exact manual verification commands I should run.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
pytest apps/api/tests/test_api.py -q -k "password_reset"
npm run architecture:check
```

## Expected completion

- Password-reset routes own only HTTP parsing/mapping/background scheduling.
- Password-reset service owns policy, persistence flow, and accepted transaction phases.
- Public behavior and anti-enumeration remain unchanged.

## Proposed commit

`refactor(identity): extract password reset application flow`

---

# Step 4 — Move Legal Acceptance and Checkout Write Orchestration Inward

**Status:** `done`

## Goal

Complete the active write-side Presentation boundary for legal acceptance and checkout without changing legal, payment, provider, Order, or entitlement semantics.

These flows are grouped because checkout directly consumes the legal-consent boundary and both are part of the current commercial request path. Implement legal acceptance first inside this step, then checkout, so checkout uses the already-clean legal boundary.

## Scope / affected code

Legal:

- `apps/api/app/domains/legal/router.py`
- `apps/api/app/domains/legal/service.py`
- legal query helpers only if their existing service usage requires a narrow adjustment

Checkout:

- `apps/api/app/domains/identity/router.py`
- `apps/api/app/domains/identity/services/checkout.py`
- `apps/api/app/domains/identity/errors.py`
- `apps/api/app/http_errors.py` only if exact existing transport mapping requires adjustment
- provider-neutral registry/contracts only as existing dependencies, not redesign targets

Focused tests:

- legal acceptance / recurring-consent cases in `apps/api/tests/test_api.py`
- checkout cases in `apps/api/tests/test_api.py`

## Implementation decisions

## Part A — Legal acceptance

### A1. Keep the already-thin required-documents path simple

`GET /api/legal/required-documents` may continue to call the existing legal service and present the returned documents.

Do not add an extra application layer merely for symmetry.

### A2. Add one transport-neutral acceptance use case

Move inward from `POST /api/legal/acceptances`:

- active required-document lookup;
- authenticated user contour checks already encoded by the current query contract;
- recurring-consent context requirement;
- current sellable-plan validation;
- `create_document_acceptance(...)` orchestration;
- acceptance commit and refresh;
- semantic legal-acceptance outcome metrics currently tied to these decisions.

The use case receives:

- `Session`;
- authenticated `User`;
- explicit validated acceptance fields;
- client IP;
- User-Agent.

It must not receive:

- FastAPI `Request`;
- `HTTPException`;
- router-owned Pydantic request model.

Use explicit parameters or one small concrete typed acceptance command if needed to keep the signature readable.

### A3. Preserve legal failure contracts

Use existing `LegalAcceptanceError` or the minimum legal-owned semantic errors needed to represent:

- document not found;
- recurring-consent context missing;
- recurring-consent plan invalid;
- invalid acceptance text/hash.

Presentation maps them to the exact existing HTTP responses, including legacy string-detail responses where currently exposed.

Do not opportunistically normalize them.

### A4. Preserve append-only evidence

Do not introduce update/delete semantics for `DocumentAcceptance`.

## Part B — Checkout

### B1. Move public checkout DTOs to Presentation ownership

The current checkout module contains `CheckoutIntentRequest` and response DTOs used directly as HTTP API schemas.

For the final Step 7 boundary:

- HTTP request/response Pydantic models must be owned by Presentation (`identity.router` or a narrowly scoped Presentation schema module next to it);
- inward checkout orchestration must not accept or return router-owned HTTP DTOs.

Move the API DTO definitions without changing their field names, validation, defaults, generated OpenAPI shape, or public import compatibility if an existing internal caller requires a temporary compatibility export.

Do not create a broad `schemas` framework.

### B2. Define a concrete checkout application contract

The inward checkout service should accept one concrete typed command/result only because this use case has enough structured input/output that passing the HTTP DTO inward would violate the Presentation boundary.

The command contains only current use-case values such as:

- plan ID;
- auto-renew flag;
- recurring consent acceptance ID;
- entrypoint type/value;
- frontend ID;
- source URL;
- client IP;
- User-Agent.

Authenticated `User`, `Session`, and `PaymentProviderRegistry` remain explicit service dependencies/arguments rather than being hidden inside the command.

The result contains provider-neutral values required to build the existing `CheckoutIntentResponse`, including the current `CheckoutAction` contract.

Do not create a generic command/result base class or command bus.

### B3. Move checkout orchestration inward unchanged

Move from the router into the existing checkout service boundary:

- sellable-plan resolution;
- automatic-renewal eligibility validation;
- missing legal-document validation;
- recurring-consent resolution;
- provider-account/adapter resolution;
- provider currency validation;
- invoice/order-number generation;
- `EntrypointSession` creation;
- `CheckoutSession` creation;
- `Order` creation;
- provider checkout-action preparation;
- Order metadata update;
- `OrderItem` creation;
- final checkout commit;
- provider-configuration rollback behavior;
- semantic checkout metrics/logging currently associated with these decisions.

The router must not directly call infrastructure query helpers after this extraction.

### B4. Preserve provider failure behavior

If `PaymentProviderConfigurationError` requires an explicit rollback before leaving the application use case, perform that rollback at the application owner and re-raise the transport-neutral provider error.

Presentation maps it to the exact existing HTTP response.

Do not change the current public error body merely to standardize it.

### B5. Keep tracing/correlation safe

Preserve the existing trace operation and observability/privacy behavior.

Do not duplicate the same semantic metric/log at both service and route layers.

### B6. Preserve deactivated-provider runtime

Normal runtime remains intentionally without a registered CloudPayments adapter.

Do not:

- register CloudPayments;
- special-case RU to restore it;
- design LBX/Dodo/future billing;
- redesign `PaymentProviderAdapter` / registry abstractions.

## Invariants

- Legal acceptance remains append-only.
- Legal API contracts unchanged.
- Checkout API/OpenAPI contract unchanged.
- Recurring-consent rules unchanged.
- Checkout metadata contents unchanged unless a purely representational move is necessary and verified equivalent.
- Checkout commit/rollback semantics unchanged.
- No Order/Payment transition redesign.
- No Subscription/Entitlement lifecycle redesign.
- CloudPayments remains deactivated.
- No provider/vendor-specific payload enters Application.
- No new schema/migration.

## Out of scope

- ANY-407 Step 8 Order/Payment/Refund transition redesign;
- ANY-407 Step 9 Subscription/Entitlement transition redesign;
- future external billing;
- CloudPayments cleanup/reactivation;
- provider interface redesign;
- checkout endpoint redesign;
- recurring-consent policy redesign;
- legal schema changes.

## AI prompt

Implement only Step 4 of ANY-490: move legal-acceptance and checkout write orchestration behind transport-neutral application/service boundaries while preserving every current public and transaction semantic.

Steps 1-3 are already complete and verified.

Do not perform broad repository research. Inspect only the current legal router/service, identity checkout router/service, directly used query helpers, provider-neutral registry/contracts, errors, and focused tests.

Implement in this order inside the step:

A. Legal acceptance
1. Keep `GET /api/legal/required-documents` simple; do not add another layer merely for symmetry.
2. Add one transport-neutral acceptance use case to the existing legal service boundary. It owns active-document lookup, recurring-consent context validation, current sellable-plan validation, DocumentAcceptance creation, commit/refresh, and semantic legal-acceptance outcome recording.
3. The use case receives Session, authenticated User, explicit acceptance values, client IP, and User-Agent. It must not receive FastAPI Request, HTTPException, or the router-owned request DTO.
4. Preserve append-only legal evidence.
5. Represent legal failures with existing LegalAcceptanceError or the smallest legal-owned semantic extension required, and preserve the exact existing HTTP responses in Presentation, including legacy string-detail cases.

B. Checkout
6. Move checkout HTTP request/response Pydantic DTO ownership to Presentation without changing fields, defaults, validation, generated OpenAPI, or public behavior. If a compatibility import is required by a current internal caller, keep only the narrow compatibility export needed; do not leave Application depending on Presentation DTOs.
7. In the existing checkout service, define one concrete typed checkout command and one concrete typed checkout result because this use case has structured input/output. Do not create a generic command framework.
8. Keep Session, authenticated User, and PaymentProviderRegistry as explicit service arguments. The command contains current validated checkout values plus client IP/User-Agent primitives. Do not pass FastAPI Request inward.
9. Move the existing checkout orchestration inward unchanged: plan/legal/consent/provider validation; EntrypointSession, CheckoutSession, Order and OrderItem creation; provider checkout-action preparation; metadata updates; final commit; provider-configuration rollback behavior; and semantic checkout diagnostics.
10. If PaymentProviderConfigurationError requires rollback, perform the rollback at the application transaction owner and re-raise the transport-neutral provider error. Presentation must reproduce the exact existing HTTP response.
11. Keep the route trace/correlation behavior and avoid duplicate metrics/logging.
12. Do not register or reactivate CloudPayments and do not redesign provider abstractions.

Preserve all existing legal, checkout, Order, Payment, Subscription, Entitlement, provider, observability, privacy, and API semantics.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only directly relevant current files if needed to verify assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, generators, documentation checks, or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation, report:
- every changed file;
- the final legal acceptance responsibility split;
- the checkout command/result contract introduced;
- which HTTP DTOs remain at Presentation;
- the exact legal and checkout transaction ownership;
- confirmation that CloudPayments runtime remains deactivated;
- the exact manual verification commands I should run.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
pytest apps/api/tests/test_api.py -q -k "legal or acceptance or recurring or checkout"
npm run architecture:check
npm run generate:check
```

## Expected completion

- Legal acceptance route parses/maps/delegates and does not own persistence orchestration.
- Checkout route parses/maps/delegates and does not own persistence/provider orchestration.
- Public HTTP DTOs are Presentation-owned.
- Inward legal/checkout code is transport-neutral.
- Existing legal/checkout transaction and public behavior are preserved.

## Proposed commit

`refactor(checkout): establish legal and checkout application boundary`

---

# Step 5 — Enforce the Boundary, Document Lifetimes, and Run Final Verification

**Status:** `done`

## Goal

Protect the resulting Presentation/FastAPI DI architecture with the minimum semantic architecture ratchet, focused dependency-override coverage, and authoritative documentation.

No production business behavior should change in this step.

## Scope / affected code

Architecture checks:

- `scripts/repo.py`
- `apps/api/tests/test_architecture.py`
- `apps/api/app/http_dependencies.py` as an explicit HTTP Presentation/composition module protected by the resulting rule

DI regression coverage:

- `apps/api/tests/test_presentation_di.py`

Authoritative documentation:

- `ARCHITECTURE.md`
- `docs/engineering/CODING_CONVENTIONS.md`
- `docs/engineering/TESTING.md`
- `apps/api/AGENTS.md` only if its concise rules would otherwise contradict the resulting state

Execution-plan status/location only if required by the repository's final merged documentation convention.

## Implementation decisions

### A. Extend the inherited reviewed ANY-489 architecture checker — do not reopen predecessor scope

Step 5 may execute while ANY-489 is still unmerged, provided the ANY-490 branch inherits from the pinned reviewed/accepted ANY-489 head.

Extend the architecture checker exactly as it exists on that inherited predecessor baseline.

Do not use ANY-490 to repair or broaden ANY-489 transaction-checker behavior.

Distinguish between:

- a **review-required predecessor fix** that should already exist on the inherited ANY-489 head; and
- an **explicitly accepted predecessor limitation** that review intentionally left out of scope.

Only the first case is a blocker. An accepted ANY-489 limitation must not be silently pulled into ANY-490.

In particular, do not expand the ANY-489 transaction checker into full attribute/chained-expression Session-flow analysis unless a later approved change to ANY-489 explicitly requires it.

### B. Detect active domain Presentation semantically

Add a semantic rule for active FastAPI Presentation modules under `apps/api/app/domains/**`.

Prefer classifying a module as Presentation when it actually defines/owns an `APIRouter`, rather than maintaining a filename list such as only `router.py`.

This must cover current active modules such as:

- identity router;
- password-reset module;
- legal router;
- billing/account router;
- catalog module.

Do not apply the active-domain rule to retained provider-specific integration routers such as historical CloudPayments code.

Treat `app.http_dependencies` separately as a known HTTP Presentation/composition module. It does not own an `APIRouter`, but because ANY-490 establishes it as the canonical FastAPI dependency boundary, it must be protected from acquiring domain persistence-query orchestration.

Operational `app.health`/metrics endpoints are not active domain Presentation use cases. Their infrastructure readiness/metrics behavior is intentionally outside this domain rule.

### C. Forbid query/persistence orchestration in active domain Presentation and HTTP dependencies

For active domain Presentation modules, architecture checks must reject direct imports from:

- `app.infrastructure.queries`
- `app.infrastructure.persistence`

and reject direct Session query mechanics such as Presentation code calling query/execute/scalar/get-style persistence operations on its injected Session when detectable by the existing AST approach.

Apply the same persistence-orchestration prohibition to `app.http_dependencies` so the canonical FastAPI dependency boundary cannot become a new place for database query composition.

The guard must allow:

- importing `sqlalchemy.orm.Session` for DI type annotation;
- receiving `Session` through `Depends(get_db)`;
- passing that Session into an inward application/service use case;
- importing canonical enums/types required by API response schemas;
- FastAPI/Starlette imports at Presentation.

Do not ban SQLAlchemy `Session` itself from Presentation.

### D. Preserve inward transport guards

Keep the existing architecture rules that reject FastAPI/Starlette dependencies from domain service/application trees.

Ensure the new/changed inward modules created by this plan are covered by those existing semantic/path rules.

Do not add one-off exceptions for them.

### E. Protect provider composition ownership

Ensure `app.payment_providers.registry` no longer depends on FastAPI/Starlette.

The request-state accessor belongs to `app.http_dependencies`.

Do not build a generic rule that accidentally treats retained provider integration routers as active domain Presentation.

### F. Finalize DI override coverage

The focused DI tests must demonstrate the supported substitution model:

- `get_db` can be overridden;
- authenticated-current-session dependency can be overridden;
- app-scoped provider-registry dependency can be overridden;
- overrides are isolated/cleared between tests;
- endpoint tests do not need a new global monkeypatch when the dependency is already an explicit FastAPI dependency.

Do not mass-migrate unrelated historical tests just to eliminate every monkeypatch.

Do not introduce a universal service-container fixture.

### G. Update `ARCHITECTURE.md`

Document the resulting actual flow:

```text
FastAPI Presentation
    ↓
transport-neutral Application/service use case
    ↓
Domain + focused query/persistence capabilities
```

Document dependency lifetimes:

**Request-scoped**

- SQLAlchemy `Session` from `get_db`;
- authenticated session/user context resolved from that Session.

**App-scoped**

- `PaymentProviderRegistry` created by `create_app()` and read through the HTTP dependency accessor.

**Ordinary code, not DI-managed services**

- stateless application/service functions are called directly and are not put behind `Depends()` only for testability.

Document transaction ownership:

- `get_db` owns lifetime only;
- session `last_seen_at` bookkeeping owns its established dedicated commit;
- register/login/logout/password-reset/legal/checkout application operations own the commit/rollback points established by ANY-489 and preserved here;
- request lifetime never implies one business transaction.

Update physical owner/module names in the transaction map where code moved, without changing semantic ownership.

### H. Update coding conventions

Add only durable rules proven by this implementation:

- routers parse/validate transport input, invoke inward use cases, and map output/errors;
- active domain Presentation does not compose infrastructure queries/persistence mechanics;
- FastAPI DI is for explicit resource/context composition, not every service function;
- response presenters do not query persistence;
- inward service/application code stays transport-neutral;
- public Pydantic HTTP DTOs are Presentation-owned; inward use cases use their own concrete typed contracts only where needed.

### I. Update testing strategy

Document:

- use `app.dependency_overrides` for explicit FastAPI dependency substitution;
- always restore/clear overrides after tests;
- prefer dependency overrides to monkeypatching globals when an explicit FastAPI dependency already exists;
- direct service/application tests call the inward function directly and do not require FastAPI DI;
- add shared API client fixtures only when multiple test modules actually need the same lifecycle, consistent with the existing fixture policy.

### J. No new ADR

Do not add an ADR unless implementation uncovered a genuinely new architectural decision that contradicts this plan and was separately approved.

## Invariants

- No production behavior change in this step.
- No API/OpenAPI change.
- No transaction change.
- No database change.
- No web change.
- No CloudPayments runtime change.
- Architecture rules protect responsibility semantics rather than incidental filenames.
- Final documentation matches implemented code, not aspirational future Step 8/9 architecture.

## Out of scope

- fixing ANY-489 review-required checker defects that should already be present on the inherited reviewed baseline;
- reopening explicitly accepted ANY-489 checker limitations, including broader attribute/chained-expression Session-flow analysis;
- eliminating every historical monkeypatch;
- physical package reorganization for style;
- generic DI/service container;
- Step 8/9 business-transition implementation;
- future external billing/vendor design;
- retained CloudPayments cleanup.

## AI prompt

Implement only Step 5 of ANY-490: protect and document the Presentation/FastAPI DI boundary established by Steps 1-4.

Steps 1-4 are already complete and verified. The current ANY-490 branch inherits from the pinned reviewed/accepted ANY-489 head, whose architecture checker is the predecessor baseline. ANY-489 does not need to be merged into `main` to execute this step.

Before editing, inspect only the inherited ANY-489 architecture-check functions, their focused tests, the new Presentation/service modules created by ANY-490, and the authoritative architecture/testing documents listed by this step. Do not perform broad repository research.

Important predecessor rule:
- Do not repair or broaden transaction-ownership checker behavior that belongs to ANY-489. If a review-required ANY-489 fix is missing from the pinned inherited baseline, stop and report the predecessor mismatch. Do not stop for an explicitly accepted ANY-489 limitation, and do not pull that limitation into ANY-490.

Required implementation:

1. Extend the existing architecture checker rather than creating a second checker.
2. Detect active domain FastAPI Presentation semantically, preferably from actual APIRouter ownership under `apps/api/app/domains/**`, so the rule covers router.py as well as active Presentation modules such as password-reset/catalog without maintaining a brittle filename list.
3. Exclude retained provider-specific integration routers such as historical CloudPayments code from this active-domain Presentation classification. Keep operational health/readiness and metrics endpoints outside the active-domain business Presentation rule; their intentional infrastructure probes are not business query orchestration.
4. Treat `app.http_dependencies` separately as a known HTTP Presentation/composition module and protect it with the same persistence-orchestration prohibition even though it does not own an APIRouter.
5. For active domain Presentation and `app.http_dependencies`, reject direct `app.infrastructure.queries` and `app.infrastructure.persistence` imports and reject detectable direct Session query mechanics. Allow `sqlalchemy.orm.Session` as a DI type, `Depends(get_db)`, passing Session to inward services, FastAPI/Starlette imports, and canonical enum/schema types required by Presentation.
6. Preserve the existing service/application rules that reject FastAPI/Starlette inward. Make sure all new inward modules from ANY-490 are naturally covered; do not add exceptions.
7. Protect `app.payment_providers.registry` from regaining FastAPI/Starlette request access.
8. Finalize focused dependency-override tests for get_db, current-session context, and provider-registry dependency substitution. Keep overrides isolated. Do not mass-migrate unrelated old tests or create a universal service-container fixture.
9. Update ARCHITECTURE.md with the actual Presentation -> Application/service -> Domain/Infrastructure flow, request/app-scoped dependency lifetimes, and the unchanged ANY-489 transaction ownership mapped to the new physical functions/modules.
10. Update CODING_CONVENTIONS.md with only the durable rules proven by this implementation: thin routers, no persistence-query composition in active Presentation, DI for resources/context rather than every service, presenters do not query persistence, transport-neutral inward services, and Presentation ownership of HTTP DTOs.
11. Update TESTING.md with the dependency-overrides policy and direct-service testing guidance. Update apps/api/AGENTS.md only if required to keep its concise rules consistent.
12. Do not create a new ADR unless a separately approved new architectural decision actually emerged.
13. Do not change production behavior in this step.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only directly relevant current files if needed to verify assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, generators, documentation checks, or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation, report:
- every changed file;
- each architecture rule added/changed;
- how active Presentation is detected;
- dependency lifetimes documented;
- confirmation that transaction semantics remain unchanged from ANY-489;
- the exact manual verification commands I should run.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

Run focused checks first:

```bash
pytest apps/api/tests/test_presentation_di.py apps/api/tests/test_architecture.py -q
npm run architecture:check
npm run docs:check
npm run generate:check
```

Then run the fast repository quality gate:

```bash
npm run check:fast
```

Then keep the repository-managed PostgreSQL test server running through all database-dependent final checks:

```bash
make test_db_up
npm run test:api
npm run check
make test_db_stop
```

`npm run check` is the authoritative complete repository quality gate and includes the repository's PostgreSQL-backed API test stage, so PostgreSQL must not be stopped before it finishes. The preceding `npm run test:api` is intentionally retained as an explicit backend-suite verification even though some coverage is repeated by the final gate.

If a PostgreSQL/browser/check stage is intentionally unavailable in the environment, record the exact skipped/blocked command and reason in the handoff instead of claiming it passed. If a command fails before `make test_db_stop` can run, stop the test database during cleanup after recording the failure.

## Expected completion

- Active FastAPI domain Presentation is thin and test-protected.
- FastAPI DI exposes explicit request/app-scoped composition points.
- Inward Application/service modules are transport-neutral.
- Active Presentation does not own persistence-query composition.
- HTTP DTOs are Presentation-owned.
- Transaction semantics remain exactly aligned with final ANY-489.
- Documentation describes the actual implemented lifetimes and boundaries.
- Focused and complete applicable verification passes.

## Proposed commit

`chore(architecture): enforce presentation boundary`

---

# Explicitly Deferred Work

## ANY-407 Step 8 — Order / Payment / Refund Application Transitions

ANY-490 must not redesign:

- Order transition ownership;
- Payment transition ownership;
- Refund transition ownership;
- state-machine rules;
- transition idempotency semantics.

Existing orchestration may be moved inward only to establish the Presentation boundary.

## ANY-407 Step 9 — Subscription / Entitlement Application Transitions

ANY-490 must not redesign:

- subscription activation/cancellation/renewal semantics;
- entitlement creation/revocation/continuity semantics;
- subscription/entitlement transition ownership.

Read-side loading may move inward; lifecycle behavior may not change.

## External billing

Do not design:

- LBX;
- Dodo;
- a generic external billing SDK/adapter;
- webhook/reconciliation contracts;
- external billing customer mapping;
- future vendor DI.

## CloudPayments

Do not:

- reactivate runtime wiring;
- register its adapter in `create_app()`;
- refactor retained integration routers merely to match active domain Presentation style;
- delete retained source in ANY-490.

## Payment-status public identity contract

The current endpoint still uses its current public email/invoice inputs.

ANY-490 may move that logic inward but must not redesign the API/correlation contract. If that contract should change to better align with long-term internal UUID identity rules, it requires a separate explicit API/business ticket.

---

# Final Plan Validation

This plan was deliberately reduced to **5 implementation steps** to avoid tiny commits and unstable intermediate states.

The grouping is intentional:

1. **DI + authentication mutations** are one boundary because current-session resolution, auth request composition, app-state dependencies, and register/login/logout are tightly coupled.
2. **All active read orchestration** is one step because it is transaction-free and follows the same typed-read-result pattern across identity, billing account, and catalog.
3. **Password reset** remains separate because its intentionally multi-phase transactions and anti-enumeration/background-task behavior make it independently high-risk and review-worthy.
4. **Legal acceptance + checkout** are grouped because checkout directly depends on legal-consent semantics and they form the active commercial write request path; legal extraction is performed first inside the step.
5. **Guards + documentation + final verification** are one final ratchet after the code shape is stable.

The plan does not leave the execution model responsible for deciding:

- where FastAPI dependencies belong;
- whether `get_db` commits;
- whether request lifetime equals transaction lifetime;
- whether Application may receive SQLAlchemy Session;
- how current-session bookkeeping is committed;
- where PaymentProviderRegistry is scoped;
- whether services should be FastAPI dependencies;
- whether API DTOs may leak inward;
- how read results cross the boundary;
- whether password-reset phases may be collapsed;
- whether legal acceptance is mutable;
- whether checkout may redesign billing transitions;
- whether CloudPayments should be reactivated;
- whether Step 8/9 work should be pulled forward;
- whether current ANY-489 checker review defects belong to ANY-490.

The execution model still retains normal local implementation freedom for incidental details such as exact private helper names, provided those choices do not change a contract, invariant, transaction boundary, resource lifetime, dependency direction, or public behavior fixed by this plan.

## Acceptance-criteria coverage

- Current active Presentation/DI responsibility inventory: covered by research summary and step scopes.
- Thin active routers: Steps 1-4.
- Standard FastAPI DI for request/app-scoped composition: Step 1.
- Explicit Session/resource lifetimes: Steps 1 and 5.
- ANY-489 transaction preservation: all write steps plus final documentation.
- Transport-neutral Application/Domain: Steps 1, 3, 4, 5.
- No persistence/query orchestration in active Presentation: Steps 2, 4, 5.
- Response/ORM leakage correction without mapper framework: Step 2.
- Supported FastAPI dependency overrides: Steps 1 and 5.
- Observability/privacy preservation: Steps 3 and 4.
- CloudPayments stays deactivated: Steps 1 and 4.
- Step 8/9 transition redesign deferred: explicit throughout.
- Architecture guard: Step 5, including active domain Presentation plus the canonical `app.http_dependencies` boundary while excluding intentional operational health/metrics probes.
- Authoritative documentation: Step 5.
- Focused + complete verification: every step plus Step 5 final suite.

## Required execution order

```text
Pin reviewed ANY-489 head
    ↓
create ANY-490 from ANY-489
    ↓
Step 1 — DI + identity authentication boundary
    ↓
manual verification + review + commit
    ↓
Step 2 — active read orchestration
    ↓
manual verification + review + commit
    ↓
Step 3 — password reset
    ↓
manual verification + review + commit
    ↓
Step 4 — legal acceptance + checkout
    ↓
manual verification + review + commit
    ↓
Step 5 — guards + docs + full verification
    ↓
final ANY-490 review + commit
    ↓
ANY-489 merges into main
    ↓
rebase/retarget ANY-490-only commits onto final main
    ↓
verify clean ANY-490-only diff
    ↓
rerun Step 5 focused checks + final repository quality gate
    ↓
ANY-490 final merge
```

Do not execute multiple implementation steps in parallel. ANY-489 merge blocks only the final ANY-490 integration/merge, not execution of Steps 1-5.
