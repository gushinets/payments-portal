# ANY-489 — Establish Transaction Boundaries & Idempotency — Implementation Plan

## Summary

ANY-489 is Step 6 of the ANY-407 architecture sequence. Its purpose is to make transaction ownership, commit/rollback responsibility, idempotency, retry, and concurrency semantics explicit and reusable without pulling Step 7–11 work forward.

The current `main` branch already contains the completed ANY-455 persistence boundary and the predecessor architecture work from ANY-411, ANY-415, ANY-437, ANY-454, ANY-457, and ANY-458. Those results are the baseline and must not be reimplemented.

Research against the current repository identified three concrete Step 6 implementation gaps:

1. `POST /register` currently commits `User` before creating and committing the initial `AuthSession`, leaving a partial-registration failure window.
2. Provider-neutral billing lifecycle code uses `_transactional` and `Session.in_transaction()` to decide whether it owns the outer transaction. With SQLAlchemy autobegin, transaction presence is not a reliable business-ownership signal.
3. Some billing lifecycle operations perform an idempotency lookup before acquiring their serialization lock but do not re-read the same idempotency key after the lock is acquired. Under concurrent same-key execution, correctness falls back to a uniqueness failure instead of normal idempotent replay.

A large part of the existing transaction/idempotency model is already correct and must be preserved: persisted operation idempotency keys, `SubscriptionEvent`, database uniqueness, focused row locking, targeted savepoints through `begin_nested()`, atomic PostgreSQL persistence helpers, and the existing PostgreSQL concurrency test suite.

No schema migration is required for the demonstrated current Step 6 gaps. Future durable operation/intent storage for external billing commands belongs to the later External Billing Command step once real provider-neutral persistence requirements exist.

---

## Current-State Assessment

### Already correct and to be preserved

| Area | Current semantics | ANY-489 decision |
|---|---|---|
| `get_db()` / Session lifecycle | Request dependency creates and closes `Session`; it does not provide global auto-commit | Preserve. Do not introduce request-wide auto-commit |
| Billing lifecycle row locks | Storage-specific `FOR UPDATE` mechanics live in focused persistence/query code | Preserve |
| Billing idempotency | Persisted `operation_idempotency_key`, durable events, and database uniqueness already exist | Preserve and harden concurrent replay |
| Billing savepoints | `begin_nested()` is used for narrowly scoped recoverable uniqueness conflicts | Preserve |
| `start_trial` / `activate_paid_period` / `enable_automatic_renewal` | Same-key replay already re-checks the event after the serialization lock | Preserve pattern |
| Password reset request | Intentional multi-phase commits protect rate-limit/token semantics, with email after durable DB state | Preserve |
| Password reset confirmation | Password change + token consumption + session revocation form one local transaction | Preserve |
| Legal acceptance | Local mutation is finalized by one commit | Preserve |
| Provider account creation | Nested savepoint handles uniqueness races without owning the business commit | Preserve |
| Scheduled subscription expiry | Lifecycle currently finalizes the batch transaction before returning; committed diagnostics are emitted afterward | Preserve atomic batch semantics, but move explicit transaction ownership to the CLI |
| CloudPayments webhook code | Legacy outer orchestration owns commit/rollback and lifecycle participates in it | Preserve as legacy evidence only |
| Checkout ordering | Local checkout state is staged, `prepare_checkout_action()` performs local/non-network preparation, and the final local commit occurs afterward; CloudPayments normal runtime is disabled | Preserve current local semantics; do not treat action preparation as an external command or implement Step 10 |

### Concrete gaps to fix

#### 1. Registration is not atomic

Registration currently persists the `User` before creating the initial `AuthSession`.

Current shape:

`User -> commit -> refresh -> AuthSession -> commit`

If the second phase fails, a durable user remains although registration did not complete successfully. A retry with the same email may then fail with `email_already_registered`.

There is no current business requirement for two committed registration phases. Creating the new user and the initial auth session is one local business operation and must commit atomically.

#### 2. Billing transaction ownership is inferred from Session state

Current billing lifecycle code uses `_transactional` with logic equivalent to:

- if `session.in_transaction()` is true, join the existing transaction;
- otherwise open/own the transaction and commit it on successful exit.

That supports both standalone lifecycle calls and composition inside retained legacy webhook processing, but the ownership signal is implicit.

With SQLAlchemy autobegin, a normal preceding read/query can make `Session.in_transaction()` return `True`. Therefore transaction existence does not mean the caller deliberately owns the business transaction.

ANY-489 must not replace this with another Session-state heuristic. Transaction ownership must be explicit in the application flow.

#### 3. Same-key concurrency coverage is incomplete

Some lifecycle operations already use the correct pattern:

`initial idempotency lookup -> serialization lock -> idempotency re-check -> transition`

This is already present for operations such as `enable_automatic_renewal`, `start_trial`, and `activate_paid_period`, with PostgreSQL concurrency coverage.

The following current operations still need equivalent post-lock replay protection:

- `apply_renewal_payment`
- `apply_provider_subscription_state`
- `request_cancellation`
- `apply_refund`

The database uniqueness constraint remains the final correctness backstop, but normal same-key concurrent replay must not rely on leaking an `IntegrityError`.

---

## Target Transaction Ownership

### Application business transaction

Application/entrypoint orchestration owns the beginning and end of an atomic business operation.

The physical placement of some orchestration inside FastAPI routers may remain temporarily unchanged. Moving orchestration into a dedicated application layer belongs to Step 7 and later architecture work.

ANY-489 changes transaction semantics, not broad package placement.

### Provider-neutral billing lifecycle

Provider-neutral lifecycle transition functions become transaction-participating operations:

- they do not perform top-level `commit()` or `rollback()`;
- they do not infer transaction ownership from `Session.in_transaction()`;
- they execute inside a transaction owned by the calling application operation;
- they may use `flush()` when storage materialization or constraint checking is required;
- focused `begin_nested()` savepoints remain valid for recoverable storage conflicts.

For scheduled expiry, the CLI invocation is the explicit transaction owner:

`Session -> begin transaction -> expire_due_subscriptions -> commit -> committed diagnostics`

For retained CloudPayments webhook processing, the existing legacy outer processing transaction remains the owner. CloudPayments must not be redesigned or promoted as the target architecture.

### Persistence layer

`app.infrastructure.queries` and `app.infrastructure.persistence` may own:

- SQL queries;
- `FOR UPDATE`;
- atomic DML;
- storage-specific uniqueness handling;
- `flush()` when required;
- targeted nested savepoints.

They must not:

- open an independent top-level business transaction;
- commit an application operation;
- rollback an application operation's outer transaction.

### Multi-phase operations

Multiple commits are valid only when each committed phase has independent recovery meaning.

After every durable phase, the system must be in a state that:

- can be identified after restart;
- does not require guessing whether the previous phase happened;
- permits a safe retry or explicitly requires state inspection;
- does not misclassify partial progress as complete failure.

The password-reset request flow is an existing intentional multi-phase example and must not be mechanically collapsed into a single transaction.

---

## Idempotency and Retry Contract

### Local same-operation replay

`operation_idempotency_key` identifies one logical operation.

Sequential replay:

1. Read the persisted event using the operation key.
2. If it exists, return the corresponding already-persisted local result.
3. Otherwise execute the transition and persist exactly one operation event.

Concurrent replay:

1. Optionally perform the current fast initial idempotency lookup.
2. Acquire the existing row lock that serializes the relevant business transition.
3. Re-read the persisted operation event using the same idempotency key.
4. If another transaction already completed it, return the existing persisted result.
5. Otherwise execute the transition and persist the event.

Database uniqueness remains the final correctness invariant, not the normal same-key control-flow mechanism.

### Different-operation concurrency

Different operation keys are not automatically duplicates.

Correctness continues to rely on the appropriate combination of:

- application state-machine validation;
- row locks;
- uniqueness constraints;
- atomic DML;
- existing transition invariants.

ANY-489 must not introduce global billing serialization.

### Database failure and retry

If a transaction definitely fails before commit, the whole logical application operation may be retried using the same operation identity where the operation supports retry.

A failed flush/commit must leave the `Session` rolled back before reuse.

If commit completion itself is uncertain to the caller, the caller must inspect authoritative persisted state/idempotency state before replaying instead of assuming failure.

No generic automatic database retry middleware is introduced by this ticket.

---

## External-Command Contract for Later Steps

ADR-0004 remains authoritative.

A future Portal-initiated external financial/billing command must follow the provider-neutral conceptual ordering:

`persist/find durable local operation or intent`
→ **commit**
→ `perform external command with no database transaction held`
→ `persist authoritative result/mapping`
→ **commit**
→ `consume later verified facts/reconciliation through the same local transition semantics`

ANY-489 documents this semantic contract but does not implement future external-command storage or provider integration.

### Outcome vocabulary

**Confirmed success**

Authoritative evidence proves the external operation succeeded.

**Confirmed failure**

Authoritative evidence proves the requested external operation did not succeed and can safely be classified as failed/rejected.

**Unknown outcome**

The command may have reached the external system, but authoritative completion evidence was not received. Examples include timeout, lost response, or process/network failure after dispatch.

**Ambiguous outcome**

Available observations are incomplete or conflicting, so neither success nor failure can safely be selected.

`unknown` and `ambiguous` are unresolved for retry purposes:

- do not blindly repeat charge/create/refund operations;
- inspect authoritative provider/local state or reconcile later;
- only an explicitly proven safe recovery rule may issue another external command.

No new persisted enum/table is introduced solely to encode these future states.

---

## Schema Decision

**No Alembic migration is planned for ANY-489.**

The existing provider-neutral subscription lifecycle already has persisted operation events, operation idempotency keys, locking, and database uniqueness sufficient to address the demonstrated current races.

`PaymentWebhookEvent` remains retained CloudPayments-era infrastructure and must not be promoted into a generic provider-neutral inbox architecture.

If implementation discovers that a required ANY-489 acceptance criterion cannot be met without changing persisted semantics, execution must stop and report the contradiction rather than invent future external-billing storage inside Step 6.

---

# Implementation Steps

## Step 1 — Make Registration Atomic

**Status:** `done`

### Goal

Make new `User` creation and the initial `AuthSession` one atomic local business operation: either both become durable or neither does.

### Scope / affected code

Primary areas:

- `apps/api/app/domains/identity/router.py`
- focused registration tests in `apps/api/tests/test_api.py`, or the current dedicated identity test module if the tests have moved before execution.

Do not move registration out of the router in this step.

### Implementation decisions

- Preserve the existing HTTP request/response and error contract.
- Remove the intermediate commit between `User` creation and `AuthSession` creation.
- If the generated user primary key is required before building `AuthSession`, use `flush()` to materialize it without committing the business operation.
- Stage the initial session in the same transaction.
- Perform one final commit only after all registration state required for a successful response is ready.
- Do not introduce a Unit of Work, transaction service, repository, or new transaction abstraction for this operation.
- Add a focused regression test that injects a failure at the previous partial-commit window, after the user has been staged/materialized but before the initial auth session completes.
- The current session-token generation seam is suitable if it remains directly relevant.
- The test must prove:
  - no durable `User` remains;
  - no durable `AuthSession` remains;
  - retrying the same registration succeeds after the injected failure is removed.

### Invariants

- Successful registration still creates exactly one `User` and one initial `AuthSession`.
- The public registration API contract does not change.
- A failed registration cannot leave a partially registered durable user.
- Duplicate-email behavior for an already successfully registered user remains unchanged.
- No database schema change is introduced.

### Out of scope

- Moving registration orchestration into a new application service.
- FastAPI DI redesign.
- Login/logout/session architecture redesign.
- Authentication model changes.
- General identity refactoring.

### AI prompt

```text
Implement only Step 1 of ANY-489: make user registration atomic.

Current verified behavior:
- apps/api/app/domains/identity/router.py currently persists the new User with a commit before creating the initial AuthSession.
- That creates a partial-success window: a failure after the User commit but before the AuthSession commit leaves a durable user and a retry may fail with email_already_registered.
- Registration orchestration physically remains in the router for now; moving it to an application layer belongs to the later Presentation/FastAPI DI step.

Implement the following decisions:
1. Treat creation of the User and its initial AuthSession as one local business transaction.
2. Remove the intermediate business commit between those writes.
3. If the User primary key must be materialized before the AuthSession can be built, use Session.flush() rather than commit.
4. Perform one final commit only after all registration state required for a successful response is staged.
5. Preserve the current public API, consent checks, token behavior and error semantics.
6. Do not introduce a generic transaction manager, Unit of Work, repository, or new abstraction for this operation.
7. Add a focused regression test for failure at the previous partial-commit boundary. Prefer the existing registration test infrastructure. Inject a deterministic failure after the User has been staged/materialized but before the initial AuthSession is completed (the current session-token-generation seam is suitable if it remains directly relevant). Verify that no User/AuthSession is durable after the failed attempt and that retrying the same registration succeeds once the failure is removed.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Run only focused verification for this step when practical: `ruff check` / `ruff format --check` on changed Python files and the smallest registration-focused test(s). Do not run the full repository quality gate or broad test suites.
Do not stage files.
Do not create commits.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

After implementation:
- report the changed files;
- briefly summarize the changes;
- report the exact verification commands I should run manually.
```

### Manual verification

```bash
./.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py -k "register"
```

If registration tests have moved into a dedicated identity test module, run that focused module instead and report the updated command before review.

### Expected completion

A registration attempt cannot durably create only the user half of the operation. An injected failure leaves the database retryable, and a subsequent registration with the same input succeeds.

### Proposed commit

`ANY-489 - Make registration atomic`

---

## Step 2 — Make Billing Transaction Ownership Explicit

**Status:** `todo`

### Goal

Remove implicit top-level transaction ownership from provider-neutral billing lifecycle functions and make the calling application operation explicitly own the transaction boundary.

### Scope / affected code

Relevant areas:

- `apps/api/app/domains/billing/service/lifecycle.py`
- `apps/api/app/domains/billing/service/lifecycle_operations.py`
- `apps/api/app/domains/billing/service/support.py`
- `apps/api/app/commands/expire_subscriptions.py`
- `apps/api/tests/test_billing_lifecycle.py`
- `apps/api/tests/test_billing_lifecycle_concurrency_postgres.py`
- `apps/api/tests/test_expire_subscriptions_cli.py`

Retained CloudPayments code may require compatibility verification only. Do not broadly refactor it.

### Implementation decisions

- Remove transaction ownership based on `_transactional` / `Session.in_transaction()` from lifecycle transition functions.
- Do not replace it with another hidden ownership heuristic based on `SessionTransaction.origin`, Session state, call-stack inspection, flags, or a universal transaction abstraction.
- Provider-neutral lifecycle transition functions must participate in the caller's transaction.
- They may query, lock, mutate, and `flush()`, but they must not commit or rollback the outer business operation.
- The scheduled expiry command must explicitly own one transaction around `expire_due_subscriptions`.
- While that transaction is still open, the CLI must validate and capture the returned persisted subscription identities. An identity-invariant failure must therefore roll back the lifecycle changes instead of occurring after commit.
- `subscription_expiry_transition_committed` and `subscription_expiry_run_succeeded` diagnostics must remain truly post-commit. Emit them only after the caller-owned transaction exits successfully; if lifecycle execution, identity validation, or commit fails, no committed/success diagnostic may be emitted.
- Existing retained CloudPayments processing already owns its larger legacy processing transaction; preserve that behavior.
- Tests and PostgreSQL worker helpers that intentionally execute one lifecycle operation as a standalone application operation must explicitly frame and commit the transaction instead of relying on lifecycle auto-commit.
- Add focused transaction-participation regression coverage proving that lifecycle code cannot finalize the caller transaction. Cover:
  - a clean `Session` with no caller-owned transaction, proving the lifecycle does not self-commit and caller rollback/close leaves neither the transition nor its `SubscriptionEvent` durable;
  - an explicit caller-owned transaction, proving lifecycle code does not finalize it;
  - the SQLAlchemy autobegin case triggered by a harmless preceding read, proving incidental Session state cannot change transaction ownership.
  In all rollback cases, verify from a fresh `Session` that neither the business transition nor its `SubscriptionEvent` became durable.
- Rewrite the scheduled-expiry CLI tests that currently assert the CLI must not commit. After ANY-489, the CLI is the transaction owner: tests must prove returned subscription identities are validated/captured before the caller-owned transaction exits, commit/transaction exit succeeds before committed diagnostics are emitted, and lifecycle failure, identity-invariant failure, or commit failure emits neither `subscription_expiry_transition_committed` nor `subscription_expiry_run_succeeded`.
- Do not change lifecycle business rules in this step.

### Invariants

- Lifecycle functions do not silently finalize a caller transaction.
- A prior unrelated DB read/autobegin cannot change who owns the business commit.
- Scheduled expiry preserves its atomic batch/operation boundary.
- Nested savepoint behavior remains unchanged.
- Row locks remain in the persistence/query boundary.
- Existing lifecycle business transitions and public errors remain unchanged.
- Retained CloudPayments behavior is not promoted into target architecture.
- Post-commit diagnostics remain truthful.

### Out of scope

- Subscription/Entitlement transition redesign from Step 9.
- Broad package movement into new application/domain modules.
- A new transaction framework.
- Request-wide FastAPI transactions.
- CloudPayments cleanup or redesign.
- Same-key idempotency hardening planned for Step 3.

### AI prompt

```text
Implement only Step 2 of ANY-489: make provider-neutral billing transaction ownership explicit.

Verified current state:
- Provider-neutral billing lifecycle functions in apps/api/app/domains/billing/service currently use the _transactional helper/decorator.
- That helper decides whether to own the transaction by checking Session.in_transaction().
- With SQLAlchemy autobegin, Session.in_transaction() may be true simply because earlier DB work occurred; it is therefore not an explicit business-transaction ownership signal.
- Lifecycle functions are also called as part of a larger retained CloudPayments transaction, while the scheduled expire_subscriptions CLI currently relies on lifecycle self-commit behavior.
- The retained CloudPayments integration is deactivated from normal runtime and must not be redesigned here.

Implement these decisions:
1. Remove implicit top-level transaction finalization from the provider-neutral billing lifecycle functions. They must become transaction-participating operations: they may query, lock, mutate and flush, but must not commit or rollback the caller's outer transaction.
2. Remove the _transactional ownership heuristic if it has no remaining valid use. Do not replace it with Session.in_transaction(), SessionTransaction.origin, a transaction flag, a generic Unit of Work, or another hidden ownership mechanism.
3. Make the currently active scheduled subscription-expiry command explicitly own the transaction around expire_due_subscriptions.
4. Ensure subscription_expiry_transition_committed and success diagnostics remain post-commit: they must execute only after the explicit transaction has exited successfully.
5. Update directly affected lifecycle/concurrency test helpers that currently depend on standalone lifecycle auto-commit so that the test/application caller explicitly frames the intended transaction.
6. Preserve nested savepoints, flushes, row locks, state-machine behavior, error contracts and all business transition semantics.
7. Retained CloudPayments processing should continue to own its existing outer commit/rollback boundary. Do not broadly modify or modernize it; make only a strictly necessary compatibility adjustment if removal of lifecycle auto-commit requires one.
8. Add focused regression coverage for transaction participation. At minimum:
   - prove a lifecycle operation invoked on a clean Session with no pre-existing caller transaction does not self-commit; explicitly roll back/close the caller Session afterward and verify from a fresh Session that neither the business transition nor its SubscriptionEvent became durable;
   - prove a lifecycle operation invoked inside an explicit caller-owned transaction does not commit it and is fully removed by caller rollback;
   - prove a harmless preceding read/autobegin does not cause lifecycle code to infer ownership or finalize the transaction; after rollback, a fresh Session must observe neither the business transition nor its SubscriptionEvent.
9. Update apps/api/tests/test_expire_subscriptions_cli.py to the new ownership model. Existing assertions that the CLI must not commit are obsolete. The CLI must validate and capture the returned persisted subscription identities while still inside its caller-owned transaction. Only after successful transaction exit may it emit `subscription_expiry_transition_committed` and `subscription_expiry_run_succeeded`. Prove that lifecycle failure, missing-persisted-identity failure, or commit/transaction-exit failure cannot emit committed/success diagnostics.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not implement the same-key idempotency hardening from the next step.
Run only focused verification for this step when practical: `ruff check` / `ruff format --check` on changed Python files and the smallest directly relevant non-PostgreSQL tests. Do not start the PostgreSQL test stack and do not run the full repository quality gate; leave those for the manual verification below.
Do not stage files.
Do not create commits.

If the current code materially contradicts an assumption required by this step, especially if an active caller actually requires lifecycle-owned commit semantics that cannot be moved to the application caller without changing a business/public contract, stop and describe the contradiction instead of inventing a new solution.

After implementation:
- report the changed files;
- briefly summarize how transaction ownership now works;
- report the exact verification commands I should run manually.
```

### Manual verification

```bash
./.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_billing_lifecycle.py
./.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_expire_subscriptions_cli.py
```

Then verify the PostgreSQL-backed composition/concurrency behavior:

```bash
make test_db_up
./.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_billing_lifecycle_concurrency_postgres.py
make test_db_stop
```

### Expected completion

No lifecycle decorator/helper decides whether to commit based on incidental `Session` state. A clean Session cannot cause lifecycle code to self-commit, current application entrypoints explicitly own complete transactions, caller rollback fully removes lifecycle changes, autobegin cannot change ownership, scheduled-expiry identity validation happens before commit, and committed/success diagnostics are emitted only after a successful caller-owned transaction exit.

### Proposed commit

`ANY-489 - Make billing transaction ownership explicit`

---

## Step 3 — Harden Same-Key Billing Concurrency

**Status:** `todo`

### Goal

Ensure concurrent execution of the same logical provider-neutral lifecycle operation converges to the same persisted result instead of relying on a uniqueness exception as ordinary control flow.

### Scope / affected code

Primary areas:

- `apps/api/app/domains/billing/service/lifecycle_operations.py`
- existing helpers in `apps/api/app/domains/billing/service/support.py` only if needed without changing responsibilities;
- existing lock/query functions in `apps/api/app/infrastructure/queries/subscriptions.py`;
- `apps/api/tests/test_billing_lifecycle_concurrency_postgres.py`;
- focused lifecycle tests where required.

Operations identified by current research:

- `apply_renewal_payment`
- `apply_provider_subscription_state`
- `request_cancellation`
- `apply_refund`

Do not modify already-correct `start_trial`, `activate_paid_period`, or `enable_automatic_renewal` except for harmless shared helper reuse.

### Implementation decisions

Use the existing project pattern:

`initial event lookup -> existing serialization lock -> event lookup again -> transition`

The second lookup must happen after the existing row lock has serialized competing executions of the same operation/target.

If the second lookup finds the event, return the existing persisted subscription/result through the existing sequential replay helper/semantics.

Keep the database uniqueness constraint as the final correctness invariant.

Do not catch a generic `IntegrityError` around the whole operation and reinterpret it as success. Preserve only existing targeted constraint/savepoint handling for specific recoverable uniqueness races.

Add PostgreSQL concurrency tests for every affected operation. Follow the established same-key concurrency test pattern:

- synchronize two workers so both miss the initial idempotency lookup;
- hold/release the current serialization lock so one worker commits first;
- ensure the second worker performs the post-lock re-check;
- both invocations return the same logical result;
- exactly one durable `SubscriptionEvent` for the tested `operation_idempotency_key` is persisted, with no duplicate business effect from the second execution;
- no raw storage exception leaks.

Tests must use explicit caller-owned transactions established by Step 2.

### Invariants

- Sequential same-key replay remains unchanged.
- Concurrent same-key replay is observably equivalent to sequential replay.
- Different operation keys are not incorrectly deduplicated.
- Existing state-machine rejection behavior remains unchanged.
- One logical operation creates at most one corresponding durable event.
- Storage uniqueness remains the final backstop.
- No schema change is introduced.
- Lock mechanics remain in persistence/query code.

### Out of scope

- Generic idempotency middleware.
- HTTP-level idempotency headers.
- New payload-fingerprint semantics.
- New event tables.
- Order/Payment/Refund redesign from Step 8.
- Subscription/Entitlement redesign from Step 9.
- External-command idempotency from Step 10.

### AI prompt

```text
Implement only Step 3 of ANY-489: harden concurrent same-operation idempotency in the existing provider-neutral billing lifecycle.

Verified current state:
- Subscription lifecycle operations use persisted operation_idempotency_key events and database uniqueness.
- start_trial, activate_paid_period and enable_automatic_renewal already use the correct concurrency pattern: initial idempotency lookup, acquire the relevant serialization lock, then re-read the operation event before mutating.
- PostgreSQL concurrency tests already protect that behavior for those operations.
- apply_renewal_payment, apply_provider_subscription_state, request_cancellation and apply_refund currently perform the initial operation-event lookup and then acquire their existing row lock, but do not consistently perform the same post-lock idempotency recheck.
- The existing database uniqueness constraint remains the final correctness invariant, but same-key concurrent replay should normally return the already persisted result rather than leak an IntegrityError.

Implement these decisions:
1. For each affected operation, preserve its existing initial fast idempotency lookup.
2. After the existing row lock that serializes the corresponding business transition has been acquired, re-read the same operation_idempotency_key before performing any new transition/event write.
3. If the event now exists, return the existing persisted subscription/result using the existing replay semantics.
4. Preserve the existing lock ordering, state-machine checks, flush/savepoint mechanics and error contracts.
5. Do not introduce a new table, migration, generic idempotency service, retry middleware or broad exception-to-success conversion.
6. Extend apps/api/tests/test_billing_lifecycle_concurrency_postgres.py with focused same-key concurrent tests for:
   - apply_renewal_payment;
   - apply_provider_subscription_state;
   - request_cancellation;
   - apply_refund.
   Reuse the existing barrier/held-lock patterns rather than building a new concurrency framework.
7. Each test must prove that both same-key invocations converge successfully, exactly one durable `SubscriptionEvent` for that `operation_idempotency_key` is produced with no duplicate business effect from the second execution, and no raw `IntegrityError` is exposed.
8. Use explicit caller-owned transaction scopes established by the previous ANY-489 step.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Run `ruff check` / `ruff format --check` on changed Python files and, if useful, the smallest fast non-PostgreSQL lifecycle tests. Do not start the PostgreSQL test stack or run the full repository quality gate; the PostgreSQL concurrency suite remains part of manual verification below.
Do not stage files.
Do not create commits.

If a listed operation already has an equivalent post-lock replay check in the current code after previous-step changes, do not duplicate it; report that fact. If the operation lacks a stable serialization lock and satisfying the requirement would require a new locking/business design, stop and describe the contradiction rather than inventing one.

After implementation:
- report the changed files;
- briefly summarize the idempotency/concurrency changes;
- report the exact verification commands I should run manually.
```

### Manual verification

```bash
./.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_billing_lifecycle.py
```

Then run the real PostgreSQL concurrency suite:

```bash
make test_db_up
./.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_billing_lifecycle_concurrency_postgres.py
make test_db_stop
```

### Expected completion

All identified same-key lifecycle races converge to one logical result and one durable event while existing different-key concurrency and state-machine semantics continue to pass.

### Proposed commit

`ANY-489 - Harden billing idempotency concurrency`

---

## Step 4 — Guard Transaction Ownership at the Persistence Boundary

**Status:** `todo`

### Goal

Protect the stable ANY-455/ANY-489 invariant that focused persistence/query helpers may own database mechanics but may not silently own an outer business transaction.

### Scope / affected code

Primary areas:

- `scripts/repo.py`
- `apps/api/tests/test_architecture.py`

Guard the established focused persistence/query boundary, currently under:

- `apps/api/app/infrastructure/queries`
- `apps/api/app/infrastructure/persistence`

The repository-owned `npm run architecture:check` entrypoint is authoritative. The transaction-ownership rule must therefore be implemented in the architecture checker invoked from `scripts/repo.py`, while `test_architecture.py` provides focused fixture coverage for the checker.

Only modify production code if the new stable guard exposes a genuine current ANY-489 violation.

### Implementation decisions

Extend the current repository architecture-check approach instead of adding runtime machinery.

Implement the semantic check in `scripts/repo.py` and wire it into `cmd_architecture()` so `npm run architecture:check` fails on violations. Add focused tests in `apps/api/tests/test_architecture.py` using temporary fixture modules to prove the checker behavior.

The guard must reject SQLAlchemy `Session` outer transaction ownership/finalization in focused persistence/query modules, specifically operations equivalent to:

- `Session.commit()`;
- `Session.rollback()`;
- top-level `Session.begin()` ownership of a business transaction.

The checker must not reject arbitrary methods named `begin`, `commit`, or `rollback` on unrelated objects; enforcement should target SQLAlchemy `Session` transaction ownership with the minimum reliable static analysis appropriate for this repository.

The guard must not reject:

- `flush()`;
- `begin_nested()` / savepoints;
- row locks;
- atomic DML;
- storage-specific exception handling.

Keep the test semantic and based on stable layer responsibility.

Do not freeze helper names, exact lifecycle structure, import ordering, or incidental file details.

Do not add a repository-wide ban on `commit()` in routers/application code. Step 7 will change physical orchestration placement, and ANY-489 must not freeze transitional package structure.

### Invariants

- Persistence may still implement PostgreSQL mechanics it owns.
- Business commit/rollback ownership remains above focused persistence/query helpers.
- Savepoints and flushes remain legal.
- Existing ANY-455 architecture guards remain intact.
- Future Step 7/8/9 package movement remains possible.

### Out of scope

- Full static transaction-flow analysis.
- AST heuristics for detecting all external I/O in transactions.
- Freezing exact lifecycle locations.
- Repository-wide commit bans.
- Runtime monkeypatching of `Session`.

### AI prompt

```text
Implement only Step 4 of ANY-489: add a stable architecture regression guard for transaction ownership at the existing persistence boundary.

Current architectural contract:
- Application/business orchestration owns outer business transaction boundaries.
- apps/api/app/infrastructure/queries and apps/api/app/infrastructure/persistence own justified SQLAlchemy/PostgreSQL mechanics.
- Those persistence helpers may query, lock rows, perform atomic DML, flush and use targeted nested savepoints.
- They must not silently own/finalize the outer business transaction with commit, rollback, or a top-level begin scope.
- Existing ANY-455 architecture guards already protect selective persistence composition and should remain intact.

Implement these decisions:
1. Add the transaction-ownership rule to the repository architecture checker in scripts/repo.py and invoke it from cmd_architecture(), so `npm run architecture:check` is the actual enforcement gate. Do not rely on pytest alone for enforcement.
2. Add focused fixture-based tests in apps/api/tests/test_architecture.py for the new checker, following the existing architecture-test style.
3. The checker must reject SQLAlchemy Session outer transaction ownership/finalization in apps/api/app/infrastructure/queries and apps/api/app/infrastructure/persistence, including Session commit(), rollback(), and top-level begin() ownership.
4. Do not reject arbitrary methods named begin(), commit(), or rollback() on unrelated objects. Target SQLAlchemy Session transaction ownership using the minimum reliable static analysis appropriate for the repository.
5. Explicitly allow flush(), begin_nested()/savepoint mechanics, row-locking and atomic DML.
6. Keep the checker semantic and narrowly scoped to the focused persistence/query boundary. Do not freeze helper names, lifecycle file layout, import ordering, or unrelated implementation details.
7. Do not create a repository-wide ban on commits: current router/application orchestration is transitional and later ANY-407 steps will change its physical placement.
8. Do not modify unrelated architecture checks.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Run the focused architecture checker tests and `npm run architecture:check` after implementation. Run `ruff check` / `ruff format --check` for changed Python files if needed. Do not run the full repository quality gate.
Do not stage files.
Do not create commits.

If current focused infrastructure code contains a top-level transaction operation that is materially required for an already-established behavior, stop and report that concrete contradiction instead of weakening the guard or moving architecture on your own.

After implementation:
- report the changed files;
- briefly summarize the protected invariant;
- report the exact verification commands I should run manually.
```

### Manual verification

```bash
./.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_architecture.py
npm run architecture:check
```

### Expected completion

A future persistence helper cannot accidentally acquire business commit/rollback ownership without failing the repository-owned `npm run architecture:check` gate, while savepoints, flushes, locking, and atomic DML remain legal.

### Proposed commit

`ANY-489 - Guard transaction ownership boundaries`

---

## Step 5 — Document Transaction, Retry, and Idempotency Contracts

**Status:** `todo`

### Goal

Make the resulting ANY-489 semantics authoritative and reusable by later ANY-407 steps without requiring another repository-wide rediscovery of the transaction model.

### Scope / affected code

Review and update only the authoritative documents where each rule belongs, primarily:

- `ARCHITECTURE.md`
- `docs/RELIABILITY.md`
- `docs/engineering/CODING_CONVENTIONS.md`
- `docs/architecture/billing-authority.md`

Do not rewrite accepted ADR-0004 unless a genuine contradiction is discovered. Prefer clarifying the accepted decision in living documentation.

### Implementation decisions

Document the final current transaction map and distinguish logical ownership from temporary physical placement.

Document at least:

- registration — one atomic transaction;
- login and legal acceptance — existing local transaction semantics preserved;
- authenticated-request `last_seen_at` bookkeeping — the current `get_current_session()` dependency performs a separate bookkeeping commit before the endpoint continues; preserve this current semantic for Step 6 and explicitly defer physical responsibility/DI separation to Step 7;
- logout — the endpoint deletion commit is separate from the preceding auth-session `last_seen_at` bookkeeping commit; do not document logout as one transaction across the whole request;
- password-reset request — deliberate multiple committed phases;
- password-reset confirmation — atomic local transaction;
- provider-neutral billing lifecycle — transaction participant; calling application operation owns the outer transaction;
- scheduled expiry — CLI explicitly owns one transaction and emits committed diagnostics only afterward;
- provider-account uniqueness recovery — nested savepoint, not a business commit;
- checkout — local checkout state and action preparation remain in the current local flow; `prepare_checkout_action()` is local/non-network preparation and occurs before the final local commit, so it must not be presented as an external-command ordering guarantee;
- CloudPayments webhook transaction/idempotency model — retained legacy behavior only.

Document persistence responsibility:

- query/lock/atomic-DML/savepoint/flush mechanics below application;
- outer commit/rollback above persistence.

Document retry semantics:

- definite pre-commit rollback → retry the whole logical operation where supported, using the same operation identity;
- already committed operation → replay/read the persisted idempotent result;
- uncertain local commit → inspect persisted state before retry;
- no generic automatic retry loop.

Document the provider-neutral future external-command ordering from ADR-0004:

`durable intent -> commit -> external call -> result/mapping -> commit -> verified fact/reconciliation`

Define:

- confirmed success;
- confirmed failure;
- unknown;
- ambiguous.

Make it explicit that unknown/ambiguous outcomes prohibit blind duplicate external commands.

Document that logs, traces, and Sentry are diagnostics only and never the correctness/idempotency store.

Document why no schema migration was required for ANY-489 and explicitly defer future external-command operation-intent persistence until later work has concrete persistence requirements.

Preserve existing privacy and correlation contracts from ANY-437/ANY-458.

### Invariants

- Documentation matches the actual code after Steps 1–4.
- ADR-0004 remains authoritative.
- No vendor-specific target contract is invented.
- No future table/entity/API is presented as already designed.
- CloudPayments legacy behavior is clearly separated from target architecture.
- Later steps may rely on the documented semantics without treating temporary helper names/files as architecture contracts.

### Out of scope

- A new ADR unless a real architecture decision is discovered that ADR-0004 does not already cover.
- Step 10 persistence schema.
- Reconciliation implementation/design.
- Provider-specific retry/status vocabulary.
- Router/application package redesign.
- General documentation cleanup.

### AI prompt

```text
Implement only Step 5 of ANY-489: document the resulting transaction, idempotency, retry and concurrency contract after the previous code steps.

Use the current post-Step-4 repository state as the implementation truth. Do not perform broad repository research; inspect only the directly relevant authoritative documentation and changed transaction/idempotency files needed to ensure the documentation matches the implementation.

Update the appropriate living authoritative documents, primarily:
- ARCHITECTURE.md
- docs/RELIABILITY.md
- docs/engineering/CODING_CONVENTIONS.md
- docs/architecture/billing-authority.md

Preserve ADR-0004 as the accepted architecture decision; do not rewrite the ADR unless you find a concrete contradiction that prevents accurate documentation.

Document these material rules:
1. Application orchestration owns outer business transaction commit/rollback; focused persistence/query code owns SQLAlchemy/PostgreSQL mechanics such as queries, row locks, atomic DML, flush and targeted nested savepoints.
2. SQLAlchemy Session autobegin is a DB/session mechanism and must not be treated as an application transaction-ownership signal.
3. Provider-neutral billing lifecycle transitions participate in a caller-owned transaction rather than silently committing themselves.
4. Registration User + initial AuthSession is one atomic local operation.
5. Current authenticated-request `last_seen_at` bookkeeping is a separate commit performed by `get_current_session()` before endpoint execution. Preserve and document that current transaction semantic in Step 6; moving/splitting the FastAPI dependency responsibility belongs to Step 7. In particular, do not describe logout as one transaction across authentication bookkeeping plus session deletion.
6. Password-reset request intentionally uses multiple durable phases; preserve and explain their recovery meaning instead of suggesting they should be collapsed.
7. Scheduled subscription expiry has an explicit transaction owner and committed diagnostics remain post-commit.
8. Same-key billing replay uses persisted operation identity plus serialization and post-lock recheck; database uniqueness remains the final invariant.
9. Current checkout `prepare_checkout_action()` is local/non-network preparation performed before the final local commit; do not misstate it as an already-implemented external-command boundary.
10. Definite database rollback may be retried as the whole logical operation with the same operation identity; uncertain commit/result requires authoritative persisted-state inspection before retry.
11. The provider-neutral future external-command contract remains:
   durable local operation/intent -> commit -> external command outside any DB transaction -> persist result/mapping -> commit -> verified fact/reconciliation.
12. Define confirmed success, confirmed failure, unknown and ambiguous outcomes. Unknown/ambiguous outcomes are unresolved and must not cause blind duplicate external commands.
13. Logs, traces and Sentry are diagnostics, never the idempotency/correctness store.
14. No schema migration was required by ANY-489. Future external-command operation-intent persistence remains explicitly deferred until the later external-billing step has concrete requirements.
15. Retained CloudPayments transaction/webhook mechanics are legacy evidence only and are not the target architecture.

Also document the current transaction map concisely enough that later ANY-407 work does not need to rediscover these semantics.

Implement only this step.
Follow the decisions defined in this prompt.
Do not redesign the architecture.
Do not invent future provider contracts, tables, enums, entities or business statuses.
Do not perform unrelated documentation cleanup.
Do not work on future steps.
Run the directly relevant lightweight documentation/architecture checks (`npm run docs:check` and `npm run architecture:check`) after the edits. Do not run the full repository quality gate; leave `npm run check` and PostgreSQL verification for the manual final gate below.
Do not stage files.
Do not create commits.

If the actual post-Step-4 code materially contradicts any required contract above, stop and report the contradiction instead of documenting behavior that is not true.

After implementation:
- report the changed files;
- briefly summarize the documentation updates;
- report the exact verification commands I should run manually.
```

### Manual verification

First verify documentation and architecture rules:

```bash
npm run docs:check
npm run architecture:check
```

Then run the final repository quality gate with the PostgreSQL test database available:

```bash
make test_db_up
npm run check
make test_db_stop
```

If `npm run check` does not include the PostgreSQL suite in the then-current repository scripts, additionally run:

```bash
make test_db_up
npm run test:api:postgres
make test_db_stop
```

Do not start a second test database instance if the previous one is still running.

### Expected completion

The repository has one coherent source of truth for transaction ownership, multi-phase operations, database retry, idempotency, concurrency, and unknown external outcomes.

The documentation describes actual Step 6 behavior and clearly hands future external-command and reconciliation work to later ANY-407 steps.

### Proposed commit

`ANY-489 - Document transaction and idempotency contract`

---

# Resulting Transaction Map

| Operation | Transaction owner after ANY-489 | Notes |
|---|---|---|
| User registration | Current registration application flow | `User + AuthSession` atomic |
| Login | Current application flow | Existing login commit semantics preserved |
| Logout | Current auth dependency + logout application flow | `last_seen_at` bookkeeping commits before endpoint execution; session deletion commits separately |
| Auth session last-seen bookkeeping | Current `get_current_session()` dependency | Separate bookkeeping transaction today; physical responsibility/DI separation deferred to Step 7 |
| Legal acceptance | Current application flow | Existing atomic commit preserved |
| Password reset request | Current password-reset orchestration | Intentional multi-phase commits |
| Password reset confirmation | Current password-reset orchestration | Password/token/session revocation atomic |
| Billing lifecycle transition | Calling application operation | Lifecycle does not finalize the outer transaction |
| Scheduled subscription expiry | CLI command | Explicit transaction; diagnostics after commit |
| CloudPayments webhook lifecycle use | Retained legacy webhook orchestration | Legacy only; not target architecture |
| Persistence/query helpers | Never business transaction owner | Lock/flush/savepoint/atomic DML only |
| Future external billing command | Future application orchestration | Durable intent commit -> external I/O -> result commit |

---

# Failure Semantics

| Failure point | Required semantic result |
|---|---|
| Registration before final commit | No `User` or `AuthSession` durable |
| Billing lifecycle before caller commit | Whole local transition can roll back |
| Scheduled-expiry returns an item without persisted identity | Identity invariant fails before transaction exit; lifecycle changes roll back and no committed/success diagnostics are emitted |
| Scheduled-expiry lifecycle succeeds but caller commit fails | Transaction is not reported as committed; no committed/success diagnostics are emitted |
| Same-key operation after another worker committed | Replay existing persisted result |
| Nested savepoint uniqueness conflict | Roll back only the explicitly recoverable nested attempt |
| DB transaction definitely rolled back | Whole logical operation may be retried with the same operation identity |
| Local commit outcome uncertain | Inspect persisted state before replay |
| After durable external intent, before external call | Durable operation exists; later orchestration may determine whether dispatch occurred only if its future persisted contract proves that fact |
| External request may have been sent but response was lost | `unknown`; do not blindly repeat the command |
| External success before local result persistence | Locally unresolved/unknown; authoritative inspection or later reconciliation required |
| Result persisted but client response lost | Replay from durable local operation state |
| Conflicting/incomplete external observations | `ambiguous`; do not guess success/failure |

The external-command recovery mechanics above are semantic requirements for later steps, not new ANY-489 persistence implementation.

---

# Final Scope Check

This plan closes the demonstrated ANY-489 gaps without changing the public API or current persisted schema.

It preserves:

- ANY-411 / ADR-0004 billing authority and external-command ordering;
- ANY-415 transport-neutral error contracts;
- ANY-437 / ANY-458 observability, privacy, and truthful diagnostics;
- ANY-454 sync-first execution;
- ANY-455 selective persistence boundary;
- ANY-457 CloudPayments runtime deactivation;
- existing billing lifecycle/state-machine behavior;
- existing PostgreSQL locks, constraints, and savepoint mechanics.

It intentionally does not implement:

- Presentation Boundary / FastAPI DI restructuring;
- Order / Payment / Refund application redesign;
- Subscription / Entitlement application restructuring;
- a real external billing command;
- reconciliation;
- provider-specific architecture;
- future operation-intent schema;
- generic Unit of Work / repository / transaction framework;
- speculative outbox/inbox infrastructure.

After Step 5 and the final quality gates pass, ANY-489 can be considered implementation-complete. The resulting transaction/idempotency contract becomes the baseline for the next sequential ANY-407 step.
