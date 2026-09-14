# ANY-455 — Establish Persistence Boundary — Implementation Plan

## Plan overview

**Overall status:** `done`

| Step | Result | Status |
|---|---|---|
| 1 | Legal SQLAlchemy query/load mechanics moved behind existing Infrastructure query boundary | `done` |
| 2 | Active Identity read/query mechanics moved behind focused query helpers | `done` |
| 3 | Password Reset raw SQL and atomic/bulk DML moved into focused Persistence capability | `done` |
| 4 | Persistence Boundary documented, guarded, and fully verified | `done` |

Execution order:

`Step 1 → Step 2 → Step 3 → Step 4`

No steps should be executed in parallel.

---

# 1. Research outcome

## 1.1. Source of truth and execution gate

Research for this revision was performed against the reviewed ANY-457 / PR #93 state and revalidated against the current PR head `02974fad3db51d94ac3f8deaf4cbb1695f0476f2` on 2026-09-13.

ANY-455 may begin **before ANY-457 is merged** as stacked work, provided it inherits the reviewed ANY-457 head. It must not be implemented from `main` without ANY-457, and ANY-455 must not be merged before ANY-457.

### Execution gate

The current stacked baseline is acceptable for implementation because:

- PR #93 is open, mergeable, and no longer has unresolved substantive review findings;
- the last full implementation review reported no findings against commit `9628abb66d0a66c2a4d9562cffcfa722f938bd6e`;
- the current head differs from that reviewed commit only by housekeeping: removal of `diff.txt`, `.gitignore` protection for the local `.diff.txt` artifact, and moving the ANY-458 execution plan from active to completed;
- CI, security scans, and PR metadata checks pass on the current head;
- ANY-457 does not modify the Legal, Identity, Password Reset, or `app.infrastructure.queries` runtime files selected by ANY-455 Steps 1-3.

Before Step 1, use one of the following baselines:

**A. Stacked execution before ANY-457 merge — approved for the current state**

1. Create/rebase the ANY-455 branch directly from the current reviewed ANY-457 head.
2. If an ANY-455 PR is opened before PR #93 merges, target the ANY-457 branch so the review diff contains only ANY-455 work.
3. Keep ANY-457 as a merge prerequisite: do not merge ANY-455 while PR #93 is still unmerged.
4. If ANY-457 receives new commits after ANY-455 starts, rebase/update ANY-455 onto the new ANY-457 head and inspect only that predecessor delta. If it materially changes an ANY-455 persistence path, architecture guard, or source-of-truth document, stop and revalidate the affected step.
5. After ANY-457 merges, rebase or retarget ANY-455 onto the resulting `main`, verify that the PR contains only ANY-455 changes, and continue the normal review/merge flow.

**B. Execution after ANY-457 merge**

1. Create/rebase ANY-455 from the resulting `main`.
2. Confirm that the accepted ANY-457 outcome still matches the assumptions below.
3. Continue with Step 1.

In both modes, the execution model may inspect the directly affected current files to confirm that the assumptions below still hold, but it must not redesign the architecture ad hoc.

Authoritative architectural baseline:

- ANY-407;
- ANY-326 canonical persisted-model decision;
- ANY-411 architecture direction and billing authority;
- ANY-415 Error Architecture;
- ANY-437 observability/privacy/correlation;
- ANY-454 sync-first execution architecture;
- reviewed ANY-457 CloudPayments deactivation state for stacked execution, which must become the accepted/merged predecessor before ANY-455 itself is merged;
- `ARCHITECTURE.md`;
- ADR 0003;
- ADR 0004;
- `docs/architecture/billing-authority.md`;
- current tests and architecture guards.

### ANY-457 outcomes inherited by ANY-455

Treat the following as fixed predecessor behavior rather than work to revisit in ANY-455:

- normal FastAPI composition does not initialize/register CloudPayments runtime components and does not mount `/api/cloudpayments/{endpoint}`;
- the generic payment-provider registry remains present but is empty in normal runtime, so checkout fails closed when no provider is registered;
- failed normal-runtime checkout must not create provider-backed checkout/order state;
- supported runtime, Compose, repository harness, CI, and environment examples no longer require or advertise CloudPayments activation/credentials;
- the frontend checkout is deliberately unavailable and does not call `/api/auth/checkout-intent` or load the CloudPayments widget in the disabled path;
- retained CloudPayments tests may compose the provider explicitly in test-only setup without reactivating it in normal `create_app()`;
- CloudPayments implementation, migrations, historical/support persistence, and retained provider-specific tests remain temporarily present for evidence-based later decommissioning;
- `ARCHITECTURE.md`, `scripts/repo.py`, and `apps/api/tests/test_architecture.py` already contain ANY-457 deactivation-era changes. Step 4 must extend those inherited versions without reverting or weakening the CloudPayments deactivation contract.

`app.models` remains the canonical persisted SQLAlchemy model contract.

Do not introduce a parallel pure-domain entity model.

CloudPayments is no longer part of the normal runtime after ANY-457 and is expected to be physically decommissioned later once its retained historical/support dependencies are evaluated. ANY-455 must therefore avoid creating new abstractions, dependencies, tests, or persistence contracts whose purpose is to improve or preserve CloudPayments-only code. The retained direct-provider implementation is evidence for classification and later removal, not a target architecture to normalize.

---

## 1.2. Selected Persistence Boundary

The boundary is **semantic**, not repository-pattern-driven.

### Application / business code owns

- deciding what a use case needs;
- business validation and decisions;
- domain/application errors;
- canonical ORM entity state transitions when those mutations represent business meaning;
- selection of semantic filters such as which payment states are meaningful to a use case;
- orchestration around persistence capabilities.

### Persistence / Infrastructure owns

- SQLAlchemy query construction;
- joins;
- filtering implementation;
- ordering;
- loading strategy;
- implementation of requested row locking and PostgreSQL locking mechanics;
- raw SQL;
- PostgreSQL-specific operations;
- bulk DML;
- atomic database operations;
- physical constraint interpretation where an active use case actually needs it.

### Transitional rule

Application decides **whether** a use case requires a locked read or other concurrency-sensitive access. Persistence owns **how** that lock is expressed through SQLAlchemy/PostgreSQL (`FOR UPDATE`, `SKIP LOCKED`, loading/order details). Global lock ordering and broader concurrency policy remain Step 6 concerns.

A SQLAlchemy `Session` is **not prohibited** in Application or Presentation by ANY-455.

ANY-455 must not create abstractions whose only purpose is converting:

```python
db.add(entity)
```

into:

```python
repository.save(entity)
```

Simple canonical ORM enlistment/mutation may remain where there is no meaningful storage mechanic to hide.

Transaction ownership, general `flush()` policy, `commit`/`rollback`, idempotency, retry/recovery, global lock ordering and Unit-of-Work-like concerns belong to ANY-407 Step 6.

---

## 1.3. Existing persistence code that is already appropriate

Keep the concern-oriented function model under:

```text
app.infrastructure.queries
```

including the existing modules for:

- subscriptions;
- orders;
- payments;
- plans;
- products;
- identity;
- legal;
- webhooks.

These are already the right general shape.

Do not convert them into repository classes.

Functions returning canonical ORM objects are acceptable.

---

## 1.4. Post-ANY-457 persistence classification

### Active generic persistence — relevant to ANY-455

Confirmed areas:

- Legal document/acceptance reads;
- Identity user/session reads;
- Product/Bundle validation reads used during checkout validation;
- historical/current payment-status reads;
- Password Reset persistence;
- subscription-expiration persistence.

### Active generic persistence already sufficiently separated

The subscription-expiration flow already delegates its meaningful loading and locking operations to `app.infrastructure.queries.subscriptions`.

Its remaining subscription/entitlement state mutation belongs to business/Application behavior.

Its outer transactional wrapper and general `flush()` behavior belong to Step 6.

The process command `app/commands/expire_subscriptions.py` still uses `sqlalchemy.inspect(subscription).identity` only to derive a persisted ORM identity for bounded post-use-case diagnostics. This is SQLAlchemy-aware process-boundary diagnostic code, not query/load/write/locking composition and not a business decision. Record it in the persistence inventory, but do not refactor it in ANY-455 merely for purity; changing that diagnostic ownership belongs with a concrete observability/process-boundary need.

Therefore **no billing persistence refactor is required by ANY-455 for the active expiration path**.

### Retained transitional persistence — do not refactor in ANY-455

Do not refactor merely for architectural cleanliness:

- retained CloudPayments integration persistence;
- provider webhook persistence used only by the deactivated direct-provider flow;
- provider subscription-reference conflict handling;
- direct-provider paid activation / renewal / refund persistence;
- live-subscription uniqueness/savepoint handling used only by the retained provider-managed lifecycle;
- `PaymentProviderAccount` creation/savepoint mechanics belonging to the retained direct-provider checkout architecture.

These remain evidence for later cleanup/decommissioning, not a model for future external billing.

CloudPayments/direct-provider decommission direction for ANY-455:

- do not move CloudPayments-only persistence into new generic `app.infrastructure.persistence` capabilities;
- do not create repositories/ports/interfaces solely to make retained provider code look cleaner;
- do not make new active Legal/Identity/Password Reset persistence helpers depend on `app.integrations.cloudpayments`, provider-specific literals, or provider-specific persisted vocabulary;
- if an existing generic helper is shared by active code and retained provider code, change it only as required by the active consumer and keep its contract provider-neutral;
- do not add architecture guards or tests whose effect is to require retained CloudPayments source to remain present;
- leave physical source/schema/history removal to a later controlled decommission step.

This removes the previous ANY-455 plan's proposed `infrastructure/persistence/billing.py` step and intentionally avoids investing in persistence architecture that is expected to be deleted with CloudPayments.

---

## 1.5. Confirmed violations selected for implementation

### Legal

`domains/legal/service.py` currently owns SQLAlchemy query construction for legal documents and acceptances.

`domains/legal/router.py` also directly constructs the persisted lookup for the document being accepted.

Persistence should own those reads.

Legal/Application continues to own:

- acceptance text construction;
- hash validation;
- missing-document decisions;
- recurring-consent semantics;
- plan/entrypoint matching;
- `LegalAcceptanceError`;
- creation of `DocumentAcceptance`.

### Identity

The following active paths still construct persistence queries directly:

- `domains/identity/services/checkout.py` — Product/Bundle scope validation;
- `domains/identity/session.py` — AuthSession/User loading;
- register/login in `domains/identity/router.py` — User lookup;
- `/payment-status` — User, Order and special Payment lookup.

Move only these query mechanics.

Do not broadly decompose `identity/router.py`.

Simple `db.add()`, `db.delete()`, model mutations, commits and refreshes remain unchanged.

### Password Reset

`domains/identity/password_reset.py` contains genuine storage-specific write behavior:

- PostgreSQL `INSERT ... ON CONFLICT ... RETURNING`;
- raw DELETE;
- bulk UPDATE/DELETE;
- atomic reset-token claim;
- bulk outstanding-token invalidation;
- bulk session revocation.

This justifies a focused write-oriented persistence capability.

It does **not** justify a `PasswordResetRepository`.

---

## 1.6. Explicitly deferred

ANY-455 must not implement:

- transaction/UoW redesign;
- general `commit`/`rollback` policy;
- general `flush()` policy;
- billing idempotency redesign;
- lock-order redesign;
- retry/reconciliation/outbox/inbox architecture;
- FastAPI DI or `get_db` redesign;
- broad router-to-Application decomposition;
- billing state-machine redesign;
- CloudPayments physical cleanup/decommission;
- architectural improvement, abstraction, or migration of CloudPayments-only persistence before that decommission;
- retained direct-provider persistence cleanup;
- future external-billing persistence/schema;
- migrations;
- public API changes;
- frontend changes.

---

### Step 1 — Move Legal query/load mechanics into Infrastructure

**Status:** `done`

**Goal**  
Remove SQLAlchemy query/load composition from the active Legal service and acceptance route while preserving all legal/business behavior and transaction semantics.

**Scope / affected code**

Primary:

- `apps/api/app/domains/legal/service.py`
- `apps/api/app/domains/legal/router.py`
- `apps/api/app/infrastructure/queries/legal.py`
- existing Legal/API tests;
- existing billing tests that exercise recurring-consent validation.

**Implementation decisions**

Extend the existing `app.infrastructure.queries.legal` module.

Move persistence mechanics for:

- selecting active required `DocumentVersion` rows by tenant, region and effective time;
- selecting already accepted document-version/hash/kind records;
- loading a `DocumentVersion` used by recurring-consent validation;
- selecting the recurring-consent acceptance candidate;
- selecting the document accepted by `POST /api/legal/acceptances` using its existing ID/tenant/region/active/requires-acceptance/effective-time constraints.

Preserve the current query ordering and temporal semantics exactly.

Persistence helpers may return canonical ORM objects or the small tuple/projection already required by the use case.

Do not introduce duplicate domain entities or repository classes.

Keep in Legal/Application:

- document/acceptance hash construction;
- acceptance-text validation;
- missing-required-document decisions;
- mapping between document types and acceptance kinds;
- recurring-consent metadata rules;
- entrypoint and plan matching;
- tenant/region/user business validation;
- legacy recurring-consent semantics;
- `LegalAcceptanceError`;
- creation of `DocumentAcceptance`.

Keep in Presentation:

- current HTTP error mapping;
- request metadata extraction;
- current `commit()` / `refresh()` behavior.

A simple `db.add(acceptance)` does not need a persistence wrapper.

Some Legal helpers are also referenced by retained direct-provider lifecycle code. Keep the extracted Legal query helpers provider-neutral, but do not use this step to refactor or preserve the retained provider callers. The result must remain independently usable after CloudPayments/direct-provider code is later removed.

**Invariants**

Preserve:

- public Legal API;
- response shapes;
- required-document ordering;
- effective-time behavior;
- tenant/region/user isolation;
- acceptance hash behavior;
- recurring-consent semantics;
- legacy recurring-consent compatibility;
- persisted acceptance metadata;
- current transaction boundaries;
- Error Architecture.

**Out of scope**

Do not change:

- Legal API models;
- document-type vocabulary;
- acceptance schema;
- database schema;
- transaction ownership;
- router decomposition;
- recurring-consent business rules;
- retained provider billing behavior;
- unrelated Legal cleanup.

**AI prompt**

```text
Implement only Step 1 of ANY-455: move active Legal query/load persistence mechanics behind the existing Infrastructure query boundary.

The architectural decisions for this step are already defined. Follow them; do not redesign them.

Relevant current files:
- apps/api/app/domains/legal/service.py
- apps/api/app/domains/legal/router.py
- apps/api/app/infrastructure/queries/legal.py
- directly related Legal/API tests

Required outcome:

1. Extend app.infrastructure.queries.legal with focused query functions for the SQLAlchemy read/load mechanics currently performed by Legal service and router code.
2. Move the current active-required-document query behind that module, preserving tenant, region, active/required, effective-time, and ordering semantics exactly.
3. Move the query/projection used to determine already accepted document versions/fingerprints behind the query module.
4. Move direct DocumentVersion loading used by recurring-consent validation behind a focused query helper.
5. Move recurring-consent candidate query composition behind the query module.
6. Move the persisted DocumentVersion selection currently performed by POST /api/legal/acceptances behind a focused query helper. Preserve all existing ID, tenant, region, active, requires-acceptance, and effective-time conditions.
7. Keep business semantics in Legal/Application:
   - acceptance text and hash construction;
   - expected hash validation;
   - missing-document decisions;
   - document-type / acceptance-kind semantics;
   - recurring-consent metadata, plan, entrypoint, tenant, region, and user validation;
   - legacy recurring-consent compatibility;
   - LegalAcceptanceError.
8. Keep HTTP mapping and the existing commit/refresh behavior in the router.
9. Continue using canonical ORM models from app.models. Do not introduce parallel domain entities.
10. Do not create LegalRepository, BaseRepository, generic CRUD, Unit of Work, or generic persistence interfaces.
11. Do not add a wrapper merely to replace the simple db.add(acceptance) operation.
12. Preserve all public API, persisted-data, error, and transaction semantics.
13. Keep all new Legal persistence helpers provider-neutral. Do not add CloudPayments/direct-provider dependencies or abstractions to support retained provider callers; those callers are transitional and expected to be decommissioned later.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Run only formatting/linting after implementation: apply the repository's configured Ruff formatting and linting to changed Python files. Do not run tests or any other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed file;
- briefly summarize what changed;
- report every formatting/lint/test command you ran and its result;
- report the remaining manual verification commands.

Before reporting completion, from `apps/api` run the repository-configured Ruff formatting and linting for the changed Python files.
Do not run tests; leave the focused test commands for manual verification below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

From `apps/api`:

```bash
uv run pytest tests/test_api.py -k "legal or acceptance or recurring_consent"
uv run pytest tests/test_billing_lifecycle.py -k "consent or automatic_renewal"
```

**Expected completion**

- active Legal code no longer constructs the selected SQLAlchemy queries;
- persistence filtering/loading is centralized in `queries/legal.py`;
- Legal rules and public behavior remain unchanged.

**Proposed commit**

`refactor(api): move legal reads behind persistence queries`

---

### Step 2 — Isolate active Identity read/query mechanics

**Status:** `done`

**Goal**  
Remove confirmed SQLAlchemy read-query construction from active Identity/session/checkout/status paths without turning Identity into a repository architecture or redesigning its Presentation/Application structure.

**Scope / affected code**

Primary:

- `apps/api/app/domains/identity/services/checkout.py`
- `apps/api/app/domains/identity/session.py`
- `apps/api/app/domains/identity/router.py`
- `apps/api/app/infrastructure/queries/identity.py`
- `apps/api/app/infrastructure/queries/products.py`
- `apps/api/app/infrastructure/queries/orders.py`
- `apps/api/app/infrastructure/queries/payments.py`
- corresponding API tests.

**Implementation decisions**

### Checkout validation

Add focused Product/Bundle lookups that express the persisted conditions currently required by `get_sellable_plan()`:

- internal UUID;
- tenant;
- active persisted status.

`get_sellable_plan()` continues to own:

- PRODUCT/BUNDLE/ALL_ACCESS consistency decisions;
- `UnknownProductPlanError`;
- resolved checkout contract construction.

Do not change provider resolution or post-provider checkout persistence.

### Session

Move behind `queries/identity.py`:

- AuthSession lookup by token hash;
- User lookup scoped to the resolved session.

Keep:

- bearer parsing;
- token hashing;
- expiration/revocation validation;
- HTTP 401 mapping;
- `last_seen_at`;
- current commit/refresh behavior

where they are.

### Register/login

Move the repeated persisted User lookup by:

- tenant;
- region;
- normalized email

into a focused identity query helper.

Do not move:

- duplicate-registration decision;
- credential verification;
- User/AuthSession construction;
- `last_login_at`;
- HTTP error mapping.

### Payment status

Move:

- Order lookup by **internal user ID + opaque provider invoice ID** into `queries/orders.py`;
- the special filtered/ordered Payment lookup into `queries/payments.py`.

The provider invoice ID remains correlation data, not identity.

Application/Presentation continues to decide when an order being canceled requires the financially meaningful payment-status set.

The query helper may accept that caller-selected status set; Infrastructure owns SQL filtering and ordering, not the business reason for choosing the statuses.

Reuse the existing normal `get_latest_payment_for_order()` where its current behavior is sufficient.

### Explicitly retained

Do not refactor the checkout writes that happen after successful provider resolution. After ANY-457 that is retained direct-provider architecture, not an active normal-runtime persistence target and is expected to be removed during later direct-provider/CloudPayments decommission.

Do not refactor `payment_providers/accounts.py` for Persistence Boundary cleanliness. Do not create new persistence abstractions to preserve or normalize those retained provider paths.

**Invariants**

Preserve:

- register/login behavior;
- email normalization;
- authentication semantics;
- token format/hash;
- session expiry/revocation behavior;
- `last_seen_at`;
- checkout plan resolution;
- PRODUCT/BUNDLE/ALL_ACCESS validation;
- inactive/wrong-tenant catalog behavior;
- `/payment-status` behavior and payment selection;
- correlation through internal `user.id`;
- HTTP error/status behavior;
- all existing transaction boundaries.

**Out of scope**

Do not change:

- Identity public API;
- response/request models;
- authentication architecture;
- FastAPI DI;
- token format;
- checkout provider architecture;
- checkout writes after provider resolution;
- CloudPayments;
- `PaymentProviderAccount` persistence;
- simple `db.add()` / `db.delete()` operations;
- commits/refreshes;
- broad `identity.router` decomposition.

**AI prompt**

```text
Implement only Step 2 of ANY-455: isolate the confirmed active Identity read/query persistence mechanics.

The architectural decisions for this step are already defined. Follow them; do not redesign them.

Relevant current files:
- apps/api/app/domains/identity/services/checkout.py
- apps/api/app/domains/identity/session.py
- apps/api/app/domains/identity/router.py
- apps/api/app/infrastructure/queries/identity.py
- apps/api/app/infrastructure/queries/products.py
- apps/api/app/infrastructure/queries/orders.py
- apps/api/app/infrastructure/queries/payments.py
- directly related API tests

Required outcome:

1. Add focused Product and Bundle query helpers for the current checkout validation lookup by internal UUID, tenant, and ACTIVE persisted status.
2. Refactor get_sellable_plan() to use those helpers instead of constructing Product/Bundle SQLAlchemy queries directly.
3. Keep PRODUCT/BUNDLE/ALL_ACCESS validation, UnknownProductPlanError decisions, and ResolvedCheckoutPlan construction in the checkout application code.
4. Add focused identity query helpers for:
   - AuthSession lookup by token hash;
   - User lookup scoped to the AuthSession;
   - User lookup by tenant, region, and normalized email where currently used by register/login/payment-status flows.
5. Refactor get_current_session() to use those helpers while keeping bearer parsing, token hashing, expiry/revocation checks, HTTP mapping, last_seen_at mutation, commit, and refresh behavior unchanged.
6. Refactor register/login read lookups to use the identity query boundary. Keep duplicate-registration, credential verification, model construction, state changes, and HTTP decisions where they are.
7. Move the payment-status Order lookup into app.infrastructure.queries.orders. The lookup must remain constrained by the internal user ID plus the opaque provider invoice identifier; the provider identifier must not become an identity source.
8. Move the special payment-status SQL filtering/ordering into app.infrastructure.queries.payments. Application/Presentation must continue to choose the semantic payment-status set used for a canceled order. Reuse the existing get_latest_payment_for_order helper for the normal unfiltered case.
9. Return canonical app.models ORM objects from these helpers. Do not create DTO/entity duplicates solely to hide SQLAlchemy.
10. Do not broadly refactor identity/router.py.
11. Do not move or redesign simple db.add(), db.delete(), commit(), rollback(), refresh(), or ORM state mutation.
12. Do not refactor checkout persistence that occurs after provider resolution, and do not refactor payment_providers/accounts.py. Those belong to retained direct-provider code after ANY-457 and are expected to be removed in later controlled decommissioning.
13. Do not move retained provider-only writes into new generic persistence modules or create abstractions whose only current consumer is the deactivated direct-provider flow.
14. Do not introduce repositories, generic interfaces, CRUD abstractions, or Unit of Work.
15. Preserve public API, authentication, checkout, payment-status, transaction, and persisted-data behavior exactly.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Run only formatting/linting after implementation: apply the repository's configured Ruff formatting and linting to changed Python files. Do not run tests or any other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed file;
- briefly summarize what changed;
- report every formatting/lint/test command you ran and its result;
- report the remaining manual verification commands.

Before reporting completion, from `apps/api` run the repository-configured Ruff formatting and linting for the changed Python files.
Do not run tests; leave the focused test command for manual verification below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

From `apps/api`:

```bash
uv run pytest tests/test_api.py -k "register or login or session or payment_status or checkout"
```

**Expected completion**

- selected active Identity paths no longer construct their SQLAlchemy read queries directly;
- Infrastructure owns persistence filtering/ordering;
- Identity/Presentation still owns validation, authentication and HTTP decisions;
- no provider or transaction redesign occurs.

**Proposed commit**

`refactor(api): isolate identity query mechanics`

---

### Step 3 — Extract Password Reset atomic persistence operations

**Status:** `done`

**Goal**  
Remove PostgreSQL/raw SQL and SQLAlchemy bulk-DML mechanics from Password Reset while preserving its security policy, anti-enumeration behavior and exact transaction sequence.

**Scope / affected code**

Primary:

- `apps/api/app/domains/identity/password_reset.py`
- `apps/api/app/infrastructure/queries/identity.py`
- new focused write boundary:
  - `apps/api/app/infrastructure/persistence/__init__.py`
  - `apps/api/app/infrastructure/persistence/password_reset.py`
- focused Password Reset tests;
- new PostgreSQL-backed persistence regression test.

**Implementation decisions**

Create a **focused persistence module**, not a repository.

Move storage-specific write operations for:

- rate-limit UPSERT using `INSERT ... ON CONFLICT ... RETURNING`;
- pruning expired rate-limit rows;
- pruning expired Password Reset tokens;
- atomic claim of one valid unused reset token;
- bulk invalidation of remaining outstanding reset tokens;
- bulk revocation of active AuthSessions.

The rate-limit persistence operation returns the persisted attempt count.

It must not know:

- IP/account business limits;
- Password Reset policy;
- `PasswordResetRateLimitedError`.

`enforce_password_reset_rate_limit()` remains the business/security policy:

1. derive current window expiration;
2. call persistence;
3. compare attempt count with the supplied limit;
4. raise existing `PasswordResetRateLimitedError`.

Ordinary reads should use `queries/identity.py`.

Reuse helpers introduced in Step 2 when their semantics match.

Add only additional focused reads needed for:

- reset token lookup by hash/purpose after claim;
- active/scoped User lookup required by Password Reset.

Keep simple ORM `db.add(reset_token)` and `db.add(user)` if no storage-specific behavior is hidden by wrapping them.

The new Infrastructure module must not import Password Reset policy/constants from `app.domains.identity.password_reset`. It may use canonical persisted model vocabulary from `app.models` (for example `MagicLinkPurpose.PASSWORD_RESET`) or accept an explicit semantic value from the caller where that produces the clearer boundary. This keeps the new persistence capability compatible with the Step 4 dependency guard.

### Transaction sequence is locked

Preserve the existing sequence:

```text
prune expired rows
    -> commit

IP rate-limit increment
    -> commit

account rate-limit increment
    -> commit

reset-token persistence
    -> commit

confirm:
atomic token claim
    -> load token/user
    -> password mutation
    -> invalidate remaining tokens
    -> revoke sessions
    -> final commit
```

Do not combine these transactions.

If atomic token claim fails, preserve the existing rollback/error behavior.

**Invariants**

Preserve:

- anti-enumeration response;
- decoy token/email behavior;
- IP and account rate limits;
- configured limits and TTL;
- server-derived tenant/region;
- committed IP attempt even if account limit subsequently fails;
- pruning behavior;
- reset-token single-use;
- password hashing;
- invalidation of other reset tokens;
- revocation of authentication sessions;
- email/background-task behavior;
- Sentry/reporting behavior;
- HTTP contracts and errors;
- database schema.

**Out of scope**

Do not change:

- rate-limit values;
- TTL;
- anti-enumeration design;
- password policy;
- email behavior;
- Sentry behavior;
- HTTP API;
- background-task architecture;
- transaction ownership;
- schema/migrations;
- authentication redesign.

**AI prompt**

```text
Implement only Step 3 of ANY-455: extract Password Reset database-specific and bulk-DML persistence mechanics into Infrastructure.

The architectural decisions for this step are already defined. Follow them; do not redesign them.

Relevant current files:
- apps/api/app/domains/identity/password_reset.py
- apps/api/app/infrastructure/queries/identity.py
- apps/api/app/infrastructure/persistence/
- directly related Password Reset tests

Required outcome:

1. Create a focused app.infrastructure.persistence.password_reset module. Add the package __init__.py only if required by the current package structure.
2. Move the current PostgreSQL rate-limit INSERT ... ON CONFLICT ... DO UPDATE ... RETURNING count operation into that persistence module.
3. The persistence operation must return the persisted attempt count. It must not know the configured IP/account limit and must not raise PasswordResetRateLimitedError.
4. Keep enforce_password_reset_rate_limit() as application/security policy: it derives the window expiration, calls the persistence operation, compares the returned count to the supplied limit, and raises the existing error.
5. Move the current persistence mechanics for:
   - pruning expired password_reset_rate_limits rows;
   - pruning expired password-reset MagicLinkToken rows;
   - atomically claiming exactly one valid unused reset token;
   - invalidating the user's other outstanding reset tokens;
   - revoking active AuthSession rows after successful password reset.
6. Keep normal reusable reads in app.infrastructure.queries.identity. Reuse Step 2 helpers where their semantics match, and add only focused reset-token/user reads that are actually required.
7. Keep token generation/hashing, rate-limit constants, TTL, anti-enumeration/decoy logic, password hashing, email/background-task behavior, HTTP contracts, and application errors outside Infrastructure.
8. Preserve the exact current transaction sequence:
   - pruning commit;
   - IP rate-limit commit;
   - account rate-limit commit;
   - reset-token persistence commit;
   - final password-reset commit.
9. Preserve the current rollback/error behavior when token claim does not affect exactly one valid token.
10. Do not introduce an outer transaction or combine existing commits.
11. Simple ORM enlistment such as db.add(reset_token) or db.add(user) may remain where no database-specific semantic needs hiding.
12. Do not create PasswordResetRepository, BaseRepository, generic CRUD, generic Unit of Work, or generic persistence interfaces.
13. The new app.infrastructure.persistence.password_reset module must not import app.domains or Password Reset policy/constants from app.domains.identity.password_reset. Use canonical persisted vocabulary from app.models where appropriate or receive semantic inputs explicitly from the caller.
14. Add a focused PostgreSQL-backed persistence regression test for the extracted rate-limit UPSERT/RETURNING operation against the migrated PostgreSQL schema. At minimum verify:
   - the first attempt returns 1;
   - another attempt within the same window increments the count;
   - an expired window restarts the count.
15. Mark/use the repository's PostgreSQL test fixtures so the regression test participates in the canonical `api-postgres` partition rather than silently behaving like a portable SQLite test.
16. Preserve all existing security, public API, persisted-data, observability, and transaction semantics.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Run only formatting/linting after implementation: apply the repository's configured Ruff formatting and linting to changed Python files. Do not run tests or any other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed file;
- briefly summarize what changed;
- report every formatting/lint/test command you ran and its result;
- report the remaining manual verification commands.

Before reporting completion, from `apps/api` run the repository-configured Ruff formatting and linting for the changed Python files.
Do not run the fast Password Reset tests or the PostgreSQL suite in the implementation-agent step; leave all test execution for manual verification below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

First run the fast Password Reset slice from `apps/api`:

```bash
uv run pytest tests/test_api.py -k "password_reset"
```

Then run PostgreSQL verification through the repository-owned test harness from repository root:

```bash
python scripts/repo.py test-db up
npm run test:api:postgres
```

The new persistence regression test must use the repository PostgreSQL fixtures/marker and execute in this partition. A skipped PostgreSQL test is **not** equivalent to verification. Do not replace this gate with a bare `uv run pytest tests/test_password_reset_persistence_postgres.py` unless `TEST_POSTGRES_DATABASE_URL` is explicitly configured and the test is confirmed to execute rather than skip.

**Expected completion**

- `domains/identity/password_reset.py` contains no raw SQL;
- atomic/bulk storage operations are owned by Infrastructure;
- Password Reset security/business policy remains outside Infrastructure;
- transaction ordering and external behavior are unchanged.

**Proposed commit**

`refactor(api): isolate password reset persistence mechanics`

---

### Step 4 — Document and guard the selective Persistence Boundary

**Status:** `done`

**Goal**  
Record the boundary established by Steps 1–3 as authoritative architecture, add a narrow semantic regression guard, and perform final ticket verification.

**Scope / affected code**

Primary:

- `ARCHITECTURE.md`
- `docs/engineering/CODING_CONVENTIONS.md`
- `scripts/repo.py`
- `apps/api/tests/test_architecture.py`

`ARCHITECTURE.md`, `scripts/repo.py`, and `apps/api/tests/test_architecture.py` already contain ANY-457 changes. Edit the inherited ANY-457 versions in place: preserve the deactivated normal-runtime contract, empty normal provider-registry assumptions, retained-provider transitional classification, and existing deactivation guards while adding the Persistence Boundary rules.

No runtime/business change.

**Implementation decisions**

### Documentation

Document explicitly:

1. `app.models` remains the canonical persisted ORM model.
2. `app.infrastructure.queries` owns concern-oriented SQLAlchemy read mechanics:
   - query construction;
   - filtering;
   - joins;
   - ordering;
   - loading strategy;
   - row locking.
3. Simple functions/query objects are the normal default.
4. Repository classes are not required per entity/table.
5. `app.infrastructure.persistence` is reserved for focused write/storage mechanics that justify a separate boundary, such as:
   - raw SQL;
   - bulk DML;
   - PostgreSQL-specific atomic operations;
   - physical DB conflict interpretation;
   - storage-specific savepoint behavior when an active use case requires it.
6. Application owns business decisions and canonical ORM state transitions.
7. SQLAlchemy `Session` may still be used as application/session context during this architecture stage.
8. Simple ORM `add/delete/mutation` does not require an artificial repository wrapper.
9. Transaction ownership, commit/rollback policy, general flush policy, idempotency, retries, lock ordering, outbox/inbox and reconciliation remain Step 6 responsibilities.
10. Retained CloudPayments/direct-provider persistence is transitional legacy, is expected to be physically decommissioned later, and is not the architectural template for future external billing. New persistence boundaries must not create dependencies that make that removal harder.
11. When generic active persistence and retained provider code share a helper, the helper remains provider-neutral; CloudPayments-only behavior must not be promoted into the generic boundary merely to preserve legacy code.

### Architecture guard

Do **not** implement the previous plan's broad rule forbidding SQLAlchemy mechanics throughout every Domain service tree.

That rule would immediately capture retained direct-provider lifecycle code intentionally excluded from ANY-455 after ANY-457 and would either:

- force unrelated CloudPayments/direct-provider cleanup; or
- require hardcoded exceptions.

Both outcomes violate the ticket.

Add the Infrastructure dependency-direction guard below as the required architecture ratchet.

Additionally, protect the active surfaces refactored by Steps 1–3 with a narrow AST ratchet **only if** it can be expressed robustly using the repository's existing AST machinery without brittle global heuristics, legacy-file exception lists, or a mini static-analysis framework. If that is not practical, use focused architecture regression tests for those changed active modules instead.

#### A. Infrastructure dependency direction

For modules under:

```text
app/infrastructure/queries/**
app/infrastructure/persistence/**
```

reject dependencies on outward/business layers such as:

```text
fastapi
starlette
app.domains
app.integrations
app.payment_providers
```

The exact implementation should use the repository's existing AST import-boundary machinery.

Allow Infrastructure to depend on:

- SQLAlchemy;
- `app.models`;
- suitable neutral `app.core` infrastructure where genuinely required;
- Python standard-library modules.

Add focused guard tests proving at least:

- a persistence/query module importing `sqlalchemy.orm.Session` and `app.models` is accepted;
- a persistence/query module importing a Domain module is rejected;
- a persistence/query module importing FastAPI/Starlette is rejected;
- a persistence/query module importing `app.integrations.cloudpayments` or `app.payment_providers` is rejected.

#### B. Optional narrow ratchet for the active surfaces refactored by Steps 1–3

Where it can be implemented robustly with the existing AST machinery, protect the concrete active paths changed by this ticket from immediately reintroducing the persistence composition that was just extracted.

If implemented, the ratchet should cover the refactored Legal functions, Identity/session/register/login/payment-status/checkout-validation surfaces, and Password Reset module. It should reject direct SQLAlchemy query/load/raw-SQL composition in those selected active surfaces while still allowing the transitional operations intentionally retained there, such as passing a `Session`, `db.add()`, `db.delete()`, `commit()`, `rollback()`, `refresh()`, and canonical ORM state mutation.

Use the existing AST machinery rather than text grep. Keep any such rule deliberately scoped to the exact active surfaces changed by ANY-455; do **not** turn it into a repository-wide ban on `Session` or SQLAlchemy method names, and do not capture retained direct-provider/CloudPayments lifecycle code. If a robust scoped AST ratchet cannot be expressed without brittle file-specific exceptions or new analysis infrastructure, do **not** build it: preserve the required Infrastructure dependency-direction guard and add focused architecture regression tests for the refactored active modules instead.

The guards protect responsibility direction and the concrete boundary established by this ticket rather than enforcing repository naming, repository classes, or physical class patterns.

**Invariants**

Preserve:

- current architecture guards;
- canonical persisted-model decision;
- sync-first architecture;
- Error Architecture;
- observability boundaries;
- retained CloudPayments code until its separate decommission step;
- the ability to remove retained CloudPayments/direct-provider code later without changing the new generic persistence boundaries;
- runtime behavior;
- public API/schema.

**Out of scope**

Do not:

- prohibit `Session` in Application globally;
- prohibit every `.query()`, `.add()`, `.flush()` or `.commit()` using fragile AST name matching;
- require repositories;
- add exceptions whose purpose is to normalize or preserve individual retained CloudPayments/direct-provider files;
- clean up, redesign, or physically remove CloudPayments in this ticket;
- add new generic persistence contracts whose only purpose is to support code already scheduled for later CloudPayments/direct-provider decommission;
- redesign transaction policy;
- add Step 7 DI rules;
- add Step 8 business/domain rules;
- regenerate OpenAPI unnecessarily.

**AI prompt**

```text
Implement only Step 4 of ANY-455: document and guard the selective Persistence Boundary established by the previous steps.

The architectural decisions for this step are already defined. Follow them; do not redesign them.

Relevant files:
- ARCHITECTURE.md
- docs/engineering/CODING_CONVENTIONS.md
- scripts/repo.py
- apps/api/tests/test_architecture.py

Required documentation outcome:

0. Work from the inherited ANY-457 versions of ARCHITECTURE.md, scripts/repo.py, and apps/api/tests/test_architecture.py. Preserve all CloudPayments deactivation-era architecture wording and guards; do not restore CloudPayments runtime registration, supported configuration, webhook exposure, or active-provider assumptions while adding the persistence rules.
1. Record app.models as the canonical persisted ORM model. Do not prescribe parallel pure-domain entities.
2. Record app.infrastructure.queries as the concern-oriented boundary for SQLAlchemy query construction, filtering, joins, ordering, loading strategy, and locking.
3. State that focused functions/query objects are the default when sufficient; repository classes are not required per model/table.
4. Record app.infrastructure.persistence as the boundary for focused storage-specific write mechanics such as raw SQL, bulk DML, PostgreSQL-specific atomic operations, physical constraint interpretation, or storage-specific savepoint mechanics when a current active use case justifies them.
5. State that Application retains business decisions and canonical ORM model transitions.
6. State explicitly that SQLAlchemy Session may still be passed through application/session orchestration at this stage.
7. Do not prescribe wrappers whose only purpose is replacing db.add(entity), db.delete(entity), or a direct canonical model mutation.
8. Explicitly defer transaction ownership, commit/rollback policy, general flush policy, idempotency, retry/recovery, lock ordering, outbox/inbox, and reconciliation to ANY-407 Step 6.
9. Record retained CloudPayments/direct-provider persistence as transitional legacy that is expected to be physically decommissioned later, not as the model for future external billing. New generic persistence boundaries must remain independent of that retained implementation.
10. Record that shared helpers changed for active consumers must remain provider-neutral and must not promote CloudPayments-only semantics into the generic persistence boundary.

Required architecture guard:

11. Extend the existing Python AST boundary checker with a semantic rule for modules under:
    - app/infrastructure/queries/**
    - app/infrastructure/persistence/**
12. Those persistence modules must not depend on FastAPI, Starlette, app.domains, app.integrations, or app.payment_providers. This also prevents new generic persistence code from depending on retained CloudPayments/direct-provider implementation.
13. SQLAlchemy, app.models, standard-library dependencies, and justified neutral Core infrastructure remain allowed.
14. Add focused tests proving:
    - Session/app.models usage in persistence passes;
    - importing app.domains from persistence fails;
    - importing FastAPI or Starlette from persistence fails;
    - importing app.integrations.cloudpayments or app.payment_providers from persistence fails.
15. The Infrastructure dependency-direction guard in items 11-14 is required.
16. Additionally, add a narrow AST ratchet for the active Legal/Identity/Password Reset surfaces changed by Steps 1-3 only if it can be expressed robustly with the repository's existing AST machinery. If implemented, keep it scoped to those refactored active surfaces and continue allowing Session orchestration, db.add/db.delete, commit/rollback/refresh, and ORM state mutation where this plan intentionally permits them.
17. Use AST-based semantic inspection, not text grep. Do not implement a blanket rule forbidding SQLAlchemy imports or persistence method names throughout all Domain/Application code. Retained direct-provider billing lifecycle code remains intentionally outside ANY-455 after ANY-457 and is expected to be removed later; the guard must not force cleanup of that code or add exceptions merely to preserve it.
18. If the optional active-surface ratchet would require brittle global heuristics, legacy-file exception lists, or new mini static-analysis infrastructure, do not implement it. Keep the required Infrastructure direction guard and add focused architecture regression tests for the changed active modules instead. Do not weaken the CloudPayments decommission direction to satisfy the guard.
19. Do not require repository classes, interfaces, or directory-per-entity conventions.
20. Do not modify runtime behavior, public API, schemas, generated OpenAPI, CloudPayments code, or transaction behavior.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Run only formatting/linting after implementation: apply the repository's configured Ruff formatting and linting to changed Python files. Do not run tests or any other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed file;
- briefly summarize what changed;
- report every formatting/lint/test command you ran and its result;
- report the remaining manual verification commands.

Before reporting completion, run the repository-configured Ruff formatting and linting for the changed Python files.
Do not run architecture checks, documentation checks, pytest, repository-wide checks, PostgreSQL tests, or browser E2E in the implementation-agent step; leave them for manual verification below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

First run the focused architecture/document checks from repository root:

```bash
npm run architecture:check
npm run docs:check
```

Then from `apps/api`:

```bash
uv run pytest tests/test_architecture.py
```

Run the complete repository verification from repository root:

```bash
npm run check
```

Finally run the PostgreSQL-specific API suite:

```bash
npm run test:api:postgres
```

No browser E2E suite is required specifically for ANY-455 because this ticket changes no frontend behavior or public HTTP contract.

**Expected completion**

- the selective Persistence Boundary is authoritative and documented;
- active Legal/Identity persistence reads follow the existing query boundary;
- Password Reset database-specific writes follow the focused persistence boundary;
- existing query helpers remain simple functions;
- no repository-per-table/UoW architecture is introduced;
- retained direct-provider/CloudPayments persistence is not opportunistically refactored and no new generic persistence dependency makes its later removal harder;
- the Infrastructure dependency direction and the refactored active surfaces have focused regression protection;
- Step 6 transaction/idempotency ownership remains intact;
- focused architecture and PostgreSQL checks plus canonical repository checks pass.

**Proposed commit**

`chore(api): document and guard persistence boundary`

---

# Final acceptance mapping

| ANY-455 acceptance area | Coverage |
|---|---|
| Current-state persistence inventory | Research section, including active, already-separated, retained provider, and SQLAlchemy-aware process diagnostic classifications |
| ANY-457 active vs retained persistence classification | Research section |
| Existing query helpers evaluated | Preserved as concern-oriented functions |
| No repository-per-table / BaseRepository | Locked across all steps |
| Canonical persisted model | `app.models` preserved |
| Active billing persistence | No refactor required; existing query boundary retained |
| Retained direct-provider / CloudPayments persistence | Explicitly excluded; treated as later decommission target |
| CloudPayments decommission compatibility | New generic persistence remains provider-neutral and independent of retained provider code |
| Legal query/load leakage | Step 1 |
| Identity/session/checkout read leakage | Step 2 |
| Register/login/status read leakage | Step 2 |
| PostgreSQL/raw Password Reset mechanics | Step 3 |
| Focused persistence capability justified by real complexity | Step 3 only |
| External/provider identifiers remain correlation, not identity | Step 2 |
| Transaction/idempotency/concurrency preserved | Deferred unchanged to Step 6 |
| PostgreSQL-specific verification | Step 3 + Step 4 |
| Architecture guard | Step 4 — required Infrastructure direction guard + robust narrow active-surface ratchet when practical, otherwise focused regression tests |
| Authoritative documentation | Step 4 |
| Public API/schema | Unchanged |
| Error Architecture | Unchanged |
| Observability/privacy/correlation | Unchanged |
| Sync-first architecture | Unchanged |

# Follow-ups outside ANY-455

The following findings must remain outside this implementation:

1. ANY-407 Step 6 — transaction boundaries, commit/rollback ownership, idempotency, retry/recovery, general savepoint/flush semantics, lock ordering and reconciliation.
2. ANY-407 Step 7 — FastAPI DI/composition/resource lifecycle.
3. ANY-407 Step 8 — broader Application/Domain decomposition and state-machine cleanup.
4. Later controlled CloudPayments/direct-provider decommissioning — physically remove retained runtime-disabled provider source, provider-only lifecycle conflict handling, provider-account persistence, webhook persistence and other dead/transitional provider-shaped code once dependency/history/support requirements are confirmed. ANY-455 must leave this removal easier by avoiding new generic dependencies on that code.
5. Future external billing — only after a concrete integration establishes its actual persistence/schema requirements. Do not reuse CloudPayments-specific persistence merely because it already exists.

# Final implementation order

Current approved stacked flow:

```text
reviewed ANY-457 head / PR #93
      ↓
branch ANY-455 from ANY-457 head
      ↓
Step 1 — Legal reads
      ↓
Step 2 — Active Identity reads
      ↓
Step 3 — Password Reset persistence
      ↓
Step 4 — Documentation + guard + final verification
      ↓
ANY-457 must be merged before ANY-455 merge
      ↓
rebase/retarget ANY-455 onto resulting main
      ↓
verify clean ANY-455-only diff and merge when approved
```

If ANY-457 is merged before ANY-455 implementation starts, simply branch ANY-455 from the resulting `main` and execute Steps 1-4 in the same order.

Do not restore the removed billing-persistence step merely because retained CloudPayments/direct-provider code still contains persistence complexity. That code is runtime-disabled and intended for later decommission. Restore or add billing persistence work in ANY-455 only if the accepted ANY-457 predecessor state provides concrete evidence of a **generic, non-CloudPayments active normal-runtime use case** that still requires the operation.
