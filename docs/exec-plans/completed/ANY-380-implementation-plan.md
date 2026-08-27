# ANY-380 — Make lifecycle operation keys concurrency-idempotent

## Plan Overview

| Field | Value |
| --- | --- |
| Feature | `ANY-71` |
| Parent | `ANY-78` |
| Ticket | `ANY-380` |
| Overall status | `done` |
| Execution order | Sequential only: Step 1 → manual verification → commit |
| Steps / commits | 1 |
| Blocks | `ANY-168` |
| Recommended branch | `ANY-380` from up-to-date `main` |

## How to Use This File

1. Open the repository on branch `ANY-380`, created from the latest `main`, and give the AI this file together with access to the codebase.
2. Instruct the AI:

   > Read `docs/exec-plans/active/ANY-380-implementation-plan.md` and implement only Step 1. Follow the prompt exactly.

3. After the step is implemented, review the diff and manually run the checks listed at the end of the step.
4. If the checks pass, create the specified commit and change the step status from `todo` to `done`.
5. This ticket intentionally has one implementation step. Do not split the lifecycle fix and its PostgreSQL concurrency regressions into separate commits because they define and verify one coherent behavior change.

## Context and Locked Decisions

`ANY-380` completes the operation-idempotency contract for two provider-neutral lifecycle commands introduced by `ANY-78`:

- `start_trial()`;
- `activate_paid_period()`.

Both commands currently perform an optimistic idempotency lookup before reaching their serialization point:

```text
check subscription_events.operation_idempotency_key
-> acquire existing lifecycle row locks
-> perform lifecycle mutation
-> write SubscriptionEvent
```

This is insufficient under concurrency.

Two concurrent calls with the same `operation_idempotency_key` can both observe that no matching `SubscriptionEvent` exists before either call acquires the serialization lock. The first call then performs the mutation and writes the event. The second call waits for the lock, resumes after the first transaction completes, but does not recheck the operation key. It can therefore continue into business logic and eventually attempt a duplicate event insert.

The database already protects:

```text
subscription_events.operation_idempotency_key
```

with the unique constraint:

```text
uq_subscription_events_operation_key
```

That constraint remains required as a final persistence invariant, but an `IntegrityError` from the unique constraint must not be the normal result of two identical lifecycle commands racing each other.

The lifecycle command contract is:

```text
same operation_idempotency_key
-> same logical operation
-> return the already-created subscription outcome
```

The required implementation pattern already exists in `enable_automatic_renewal()`:

```text
fast pre-lock idempotency check
-> acquire the command's serialization lock
-> post-lock idempotency recheck
-> return the existing subscription when another worker completed the operation
```

`ANY-380` applies this existing pattern only to the two lifecycle commands named in the ticket.

No new idempotency mechanism is required.

Do not introduce:

- advisory locks;
- an idempotency table;
- retry loops;
- generic lifecycle wrappers;
- a replacement for the existing unique constraint;
- provider-specific duplicate handling.

### Serialization point for `start_trial()`

The existing implementation already serializes lifecycle work through locked persisted state:

```text
get and lock Plan
-> lock User
-> trial-per-scope lookup / locking
-> live-subscription lookup / locking
```

For identical operation keys, the definitive idempotency recheck must happen immediately after the User row has been successfully locked and validated.

The required order is:

```text
initial operation-key check
-> lock and validate Plan
-> lock and validate User
-> recheck operation key
-> validate trial availability
-> enforce trial-per-scope
-> enforce live-subscription conflict rules
-> create Subscription + Entitlement + TRIAL_STARTED event
```

This preserves the current distinct-key behavior.

Two concurrent calls for the same trial scope with different operation keys must still be independent commands. The existing concurrency behavior remains:

```text
one command succeeds
other command -> trial_already_used_for_scope
```

The second command must not be converted into an idempotent success merely because it targets the same scope.

### Serialization point for `activate_paid_period()`

The existing paid-activation path already validates and locks the verified persisted payment context and then serializes subscription changes by User / subscription rows.

The required order is:

```text
initial operation-key check
-> verify and lock persisted Order / Payment context
-> resolve Plan
-> lock and validate User
-> recheck operation key
-> inspect locked live subscriptions
-> perform paid-period mutation
-> create Entitlement + PAID_PERIOD_ACTIVATED event
```

The post-lock recheck must occur before subscription or entitlement mutation.

Two different verified paid orders with different operation keys for the same scope remain different lifecycle operations. They must continue to use the existing serialization logic and may append separate paid periods to the same subscription.

### Database Contract

`subscription_events` remains append-only audit.

The existing `operation_idempotency_key` column and its unique constraint remain unchanged.

No table, column, index, migration, API contract, Pydantic model, enum, configuration value, or generated artifact is required for this ticket.

### Provider-Neutral Boundary

`ANY-380` remains entirely inside the provider-neutral billing lifecycle.

The fix must not add CloudPayments-specific code.

This is important for `ANY-168`, which will later translate retryable CloudPayments operations and notifications into these lifecycle commands. The provider adapter must be able to safely repeat the same internal operation key without duplicating domain mutations.

### Branching Decision

Create `ANY-380` from up-to-date `main`.

Do not create it from `ANY-377` or `ANY-379`.

`ANY-377`, `ANY-379`, and `ANY-380` are independent post-merge fixes for `ANY-78`:

- `ANY-377` changes refund-after-expiration lifecycle behavior;
- `ANY-379` hardens recurring-consent validation and automatic-renewal attachment;
- `ANY-380` fixes lifecycle operation-key concurrency semantics.

At the time this plan was prepared, `ANY-377` and `ANY-379` were still separate pull requests based on `main` after `ANY-78`.

If either ticket is merged before branch creation, create `ANY-380` from the new latest `main`.

If either ticket is merged after work on `ANY-380` has started, update/rebase `ANY-380` onto the latest `main` before the final pull request. Do not cherry-pick those branches into `ANY-380` merely to establish a dependency.

`ANY-379` also updates `apps/api/tests/test_billing_lifecycle_concurrency_postgres.py`, so a later rebase may require resolving a test-file conflict. Preserve accepted `ANY-379` coverage and add the `ANY-380` regressions without removing either behavior.

### Out of Scope for ANY-380

- `ANY-377` refund-after-expiration state transition changes;
- `ANY-378` validation of resolved Order Plan tenant/region during paid activation;
- `ANY-379` recurring-consent matching or `EnableAutomaticRenewalCommand` changes;
- `ANY-168` CloudPayments recurrent API calls, provider subscriptions, token handling, or notification orchestration;
- changes to `_find_plan_for_order()` tenant/region validation;
- general lifecycle refactoring;
- generic idempotency infrastructure;
- provider-specific idempotency behavior;
- new API endpoints or request/response contracts;
- database schema or Alembic migrations;
- changes to the `subscription_events` unique constraint;
- catching duplicate `SubscriptionEvent` insertion as the primary same-key concurrency strategy.

---

# Step 1 — Make trial and paid activation operation keys concurrency-idempotent

**Status:** `done`  
**Commit:** `fix(billing): make lifecycle operation keys concurrency-idempotent`

## Prompt

Implement Step 1 of ANY-380: make `start_trial()` and `activate_paid_period()` concurrency-idempotent for identical `operation_idempotency_key` values.

Work only on the provider-neutral lifecycle defect described below. Do not perform additional research or redesign the idempotency architecture; the required technical decisions are already defined in this prompt.

## Goal

Two concurrent invocations of the same lifecycle command with the same `operation_idempotency_key` must converge on the already-created subscription result.

The first invocation should perform the lifecycle mutation and create the `SubscriptionEvent`.

The second invocation, after waiting for the existing serialization lock, must re-read the operation key and return the subscription referenced by the existing event instead of attempting the mutation again.

The existing database unique constraint on `subscription_events.operation_idempotency_key` remains a persistence invariant and must not become the normal concurrency-control mechanism.

## Branch Context

Work on:

```text
ANY-380
```

created from the latest:

```text
main
```

Do not cherry-pick or depend on `ANY-377` or `ANY-379`.

If those tickets are already present in `main`, preserve their changes and adapt only where required by merge/rebase conflicts.

The pull request target remains:

```text
main
```

## Relevant Existing Code

Work primarily in:

- `apps/api/app/domains/billing/service/lifecycle.py`
- `apps/api/tests/test_billing_lifecycle_concurrency_postgres.py`

Read and preserve existing behavior in:

- `apps/api/app/domains/billing/service/support.py`
- `apps/api/app/domains/billing/service/lifecycle_operations.py`
- `apps/api/app/infrastructure/queries/subscriptions.py`
- `apps/api/app/infrastructure/queries/identity.py`

Relevant lifecycle operations:

- `start_trial(...)`;
- `activate_paid_period(...)`;
- `enable_automatic_renewal(...)` as the existing post-lock idempotency pattern.

Relevant helpers:

- `_event_for_key(db, operation_idempotency_key)`;
- `_subscription_for_event(db, existing_event)`;
- `_transactional`;
- `_write_event`;
- `lock_user_by_id`;
- `get_trial_for_scope`;
- `get_live_subscription_for_scope`;
- `list_active_subscriptions_for_user`;
- `_verify_successful_payment_context`.

The existing PostgreSQL concurrency test module already provides the correct test style:

- migrated PostgreSQL database;
- independent SQLAlchemy sessions per worker;
- `ThreadPoolExecutor`;
- `Barrier`;
- real PostgreSQL row locks;
- deterministic synchronization for the initial event lookup.

Follow that test harness rather than introducing a second concurrency framework.

## Implementation

### 1. Add the post-lock operation-key recheck to `start_trial()`

Keep the current fast idempotency check at the beginning of `start_trial()`:

```python
existing_event = _event_for_key(db, command.operation_idempotency_key)
if existing_event:
    return _subscription_for_event(db, existing_event)
```

Preserve the existing Plan resolution and lock:

```text
get_plan_by_id(..., for_update=True)
```

Preserve its existing validation:

```text
plan exists
plan.tenant_id == command.tenant_id
plan.region == command.region
```

Preserve the existing User serialization lock:

```text
lock_user_by_id(db, command.user_id)
```

and the current validation:

```text
user exists
user.tenant_id == command.tenant_id
user.region == command.region
```

Immediately after the User has been successfully locked and validated, perform a second lookup using:

```python
_event_for_key(db, command.operation_idempotency_key)
```

If another transaction has already completed the same operation, return:

```python
_subscription_for_event(db, existing_event)
```

The post-lock check must happen before:

- validating `plan.trial_days`;
- calling `get_trial_for_scope(...)`;
- calling `get_live_subscription_for_scope(...)`;
- creating a `Subscription`;
- creating an `Entitlement`;
- writing `SubscriptionEventType.TRIAL_STARTED`.

Do not move the recheck before the User lock. That would preserve the original race.

Do not move it after trial/live conflict checks. A duplicate same-key request must return the first operation's result instead of being converted into `trial_already_used_for_scope` or `live_subscription_conflict` after waiting for the first operation.

Do not remove or weaken:

- the Plan lock;
- the User lock;
- `get_trial_for_scope()` locking;
- the trial-per-scope invariant;
- the live-subscription lookup and locking;
- the existing live-subscription unique-conflict handling.

Distinct operation keys must remain distinct commands.

For the same trial scope with different keys, preserve the current behavior:

```text
one result: success
other result: SubscriptionLifecycleError("trial_already_used_for_scope")
```

Do not treat same scope as idempotency. Idempotency is keyed only by the exact `operation_idempotency_key`.

### 2. Add the post-lock operation-key recheck to `activate_paid_period()`

Keep the current initial `_event_for_key()` fast path at the beginning of `activate_paid_period()`.

Preserve:

```text
_verify_successful_payment_context(...)
```

and all of its existing persisted-context checks and row-locking behavior for:

- `Order`;
- `Payment`;
- processed `PaymentWebhookEvent` linkage.

Preserve:

```text
_find_plan_for_order(db, order)
```

without adding new tenant/region validation in this ticket.

Preserve:

```text
lock_user_by_id(db, order.user_id)
```

and the existing validation that the User belongs to the same tenant and region as the Order.

Immediately after the User has been successfully locked and validated, perform the second:

```python
_event_for_key(db, command.operation_idempotency_key)
```

lookup.

If the event now exists, return the existing subscription using:

```python
_subscription_for_event(db, existing_event)
```

The post-lock check must happen before:

- calculating paid-period mutation state;
- `list_active_subscriptions_for_user(...)`;
- replacement subscription handling;
- carry-forward entitlement handling;
- creating or mutating a Subscription;
- creating an Entitlement;
- writing `SubscriptionEventType.SUBSCRIPTION_REPLACED` for this operation path;
- writing `SubscriptionEventType.PAID_PERIOD_ACTIVATED`.

Do not change the behavior of different operation keys.

Two different verified paid orders with different operation keys for the same scope must continue to be processed as separate operations and use the existing subscription serialization behavior.

The existing regression:

```text
test_parallel_paid_orders_same_scope_share_one_subscription
```

must keep proving that separate paid operations can produce two paid-period events and two order-backed entitlements on one serialized subscription lifecycle.

### 3. Preserve the existing database idempotency invariant

Do not modify:

```text
uq_subscription_events_operation_key
```

Do not change:

- `SubscriptionEvent.operation_idempotency_key`;
- `_write_event()`;
- `_event_for_key()`;
- `_subscription_for_event()`;
- `_transactional`;
- database isolation level.

Do not catch a duplicate `SubscriptionEvent` `IntegrityError` and convert it into the normal same-key result.

The intended path is:

```text
initial miss
-> wait for existing lifecycle serialization lock
-> post-lock hit
-> return existing subscription
```

The unique constraint remains only the final persistence safety net for unexpected bugs or unsupported races.

### 4. Add a deterministic PostgreSQL regression for concurrent same-key `start_trial()`

Update:

```text
apps/api/tests/test_billing_lifecycle_concurrency_postgres.py
```

Add a focused test named approximately:

```text
test_parallel_start_trial_same_key_reuses_event_after_user_lock
```

Use one shared `StartTrialCommand` value for both workers.

The two concurrent calls must use the exact same:

- `tenant_id`;
- `region`;
- `user_id`;
- `plan_id`;
- `operation_idempotency_key`;
- `occurred_at`.

Run the workers through independent SQLAlchemy sessions.

Use the existing real PostgreSQL concurrency style:

- `ThreadPoolExecutor(max_workers=2)`;
- synchronization `Barrier` objects;
- real row locking;
- no mocked transaction layer.

Make the original race deterministic by monkeypatching the symbol used by `start_trial()`:

```text
app.domains.billing.service.lifecycle._event_for_key
```

Follow the synchronization pattern already used by:

```text
test_parallel_enable_automatic_renewal_same_key_reuses_event_after_subscription_lock
```

The monkeypatched lookup must ensure both worker threads execute the initial `_event_for_key()` call and both receive `None` before either is allowed to complete the lifecycle operation.

Track which worker thread has already participated in the forced initial miss, for example using the existing style with:

- `get_ident()`;
- a `set[int]` of synchronized thread IDs;
- a `Lock` protecting that set.

Only synchronize the first missing-event observation from each worker.

Do not block the later post-lock `_event_for_key()` call on the same barrier.

The test must prove the real contract:

```text
worker A: initial event miss
worker B: initial event miss
worker A/B serialize through existing row lock
first worker creates trial + event
second worker performs post-lock lookup
second worker returns existing subscription
```

Both futures must complete normally.

Do not catch `IntegrityError` as an expected outcome.

Do not convert `SubscriptionLifecycleError` into success in this same-key test.

After both workers complete, assert at minimum:

1. both returned subscription IDs are equal;
2. exactly one trial subscription exists for the target scope;
3. exactly one trial entitlement exists for that subscription;
4. exactly one `TRIAL_STARTED` event exists for the operation;
5. exactly one `SubscriptionEvent` row exists with the shared `operation_idempotency_key`.

Keep the existing different-key test:

```text
test_parallel_trials_same_scope_create_one_trial
```

unchanged in semantics.

It must continue to prove:

```text
different operation keys
+ same trial scope
-> one success
-> one trial_already_used_for_scope
```

### 5. Add a deterministic PostgreSQL regression for concurrent same-key `activate_paid_period()`

In the same test module, add a focused test named approximately:

```text
test_parallel_activate_paid_period_same_key_reuses_event_after_user_lock
```

Create one persisted verified initial-payment context using the existing test helpers and patterns:

```text
User
PaymentProviderAccount
Plan
paid Order
successful Payment
processed PaymentWebhookEvent
```

Create one `ActivatePaidPeriodCommand` and invoke that same command concurrently from two independent sessions.

Both workers must use the exact same:

- `order_id`;
- `payment_id`;
- `webhook_event_id`;
- `operation_idempotency_key`;
- `occurred_at`.

Force both workers to observe the initial operation-key miss by monkeypatching:

```text
app.domains.billing.service.lifecycle._event_for_key
```

Use the same first-miss-per-thread synchronization pattern as the new trial regression and the existing automatic-renewal concurrency regression.

Do not implement a timing-only race test.

Use the existing User row lock / worker-start helper style where practical so the test proves serialization through real PostgreSQL locks rather than merely relying on scheduler timing.

The intended sequence is:

```text
worker A: initial event miss
worker B: initial event miss
both enter verified persisted payment context
both serialize through the existing lifecycle lock path
first worker applies paid period and writes PAID_PERIOD_ACTIVATED
second worker reaches the new post-lock event check
second worker returns the existing subscription
```

Both futures must complete normally.

Do not catch `IntegrityError` as acceptable behavior.

After completion, assert at minimum:

1. both calls returned the same subscription ID;
2. exactly one lifecycle outcome was applied for the shared command;
3. exactly one `PAID_PERIOD_ACTIVATED` event exists for the shared operation;
4. exactly one `SubscriptionEvent` exists with the shared `operation_idempotency_key`;
5. exactly one Entitlement exists with the source `order_id` used by the command.

Keep the existing different-key regression:

```text
test_parallel_paid_orders_same_scope_share_one_subscription
```

unchanged in semantics.

It must continue to prove that two different paid orders with two different operation keys are both applied and share the serialized subscription lifecycle rather than being deduplicated.

### 6. Preserve adjacent-ticket boundaries

Do not implement any part of `ANY-377`.

Specifically, do not change:

```text
SubscriptionStatus.EXPIRED -> SubscriptionStatus.REFUNDED
```

or other state-machine transitions.

Do not implement any part of `ANY-378`.

Specifically, do not add Plan tenant/region validation after `_find_plan_for_order()` in `activate_paid_period()`.

Do not implement any part of `ANY-379`.

Specifically, do not modify:

- recurring-consent matching;
- `EnableAutomaticRenewalCommand` fields;
- legal acceptance validation;
- provider-reference attachment semantics.

If `ANY-379` is already present in the branch because it was merged into `main`, preserve it as existing baseline behavior but do not expand it.

Do not implement any part of `ANY-168`.

Specifically, do not add:

- CloudPayments recurrent API calls;
- CloudPayments tokens;
- provider subscription creation/update/cancel orchestration;
- provider-specific retries;
- provider-specific state values inside the billing domain.

### 7. Do not introduce unrelated abstractions or generated changes

Do not extract a generic helper solely because the same:

```text
check -> lock -> recheck
```

pattern now exists in several lifecycle functions.

The explicit pattern is already present in `enable_automatic_renewal()` and remains small enough to keep local and reviewable.

Do not add:

- a new class;
- a decorator;
- a context manager;
- an idempotency service;
- a repository abstraction;
- a Pydantic contract;
- an Enum;
- a configuration setting.

Do not update generated DB schema or OpenAPI artifacts because no persisted or HTTP contract changes in this ticket.

## Scope Constraints

Only the following production behavior should change:

```text
same lifecycle operation key
+ concurrent start_trial()
-> both return the same trial subscription outcome
```

and:

```text
same lifecycle operation key
+ concurrent activate_paid_period()
-> both return the same paid subscription outcome
```

The following behaviors must remain unchanged:

```text
different trial operation keys for same scope
-> existing trial conflict semantics
```

```text
different paid activation keys/orders for same scope
-> existing serialized multi-period behavior
```

```text
webhook deduplication
-> unchanged
```

```text
automatic renewal idempotency
-> unchanged except for preserving already-merged baseline code
```

No public API response shape changes are required.

No schema or migration changes are required.


## After Implementation

Report:

1. every file changed;
2. the exact post-lock recheck position in `start_trial()`;
3. the exact post-lock recheck position in `activate_paid_period()`;
4. how the new trial concurrency test guarantees both workers miss the initial event lookup before proceeding;
5. how the new paid-activation concurrency test guarantees both workers miss the initial event lookup before proceeding;
6. confirmation that both same-key workers complete normally and the tests do not accept `IntegrityError` as a valid result;
7. confirmation that different-key trial behavior was not changed;
8. confirmation that different-key paid-activation behavior was not changed;
9. confirmation that the `subscription_events.operation_idempotency_key` unique constraint was not changed;
10. confirmation that no `ANY-377`, `ANY-378`, `ANY-379`, or `ANY-168` scope was implemented;
11. the exact checks I should run manually.



Then update the step status from:

```text
todo
```

to:

```text
done
```
