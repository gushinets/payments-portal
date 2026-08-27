# ANY-378 — Validate paid Order Plan scope

## Plan Overview

| Field | Value |
| --- | --- |
| Feature | `ANY-71` |
| Parent | `ANY-78` |
| Ticket | `ANY-378` |
| Overall status | `done` |
| Execution order | Sequential only: Step 1 → manual verification → commit |
| Steps / commits | 1 |
| Follow-up context | `ANY-168` consumes the provider-neutral paid lifecycle; no `ANY-168` work belongs in this ticket |
| Recommended branch | `ANY-378` from up-to-date `main` |

## How to Use This File

1. Open the repository on branch `ANY-378`, created from the latest `main`, and give the AI this file together with access to the codebase.
2. Instruct the AI:

   > Read `docs/exec-plans/active/ANY-378-implementation-plan.md` and implement only Step 1. Follow the prompt exactly.

3. After the step is implemented, review the diff and manually run the checks listed at the end of the step.
4. If the checks pass, create the specified commit and change the step status from `todo` to `done`.
5. This ticket intentionally has one implementation step. Do not split the production guard and its focused lifecycle regressions into separate commits because they define and verify one coherent invariant.

## Context and Locked Decisions

`ANY-378` closes a provider-neutral paid-activation invariant left by `ANY-78`.

The current paid lifecycle resolves the `Plan` for an `Order` through `_find_plan_for_order()`:

```text
order.plan_id
-> if absent, OrderItem.plan_id
-> get_plan_by_id(plan_id)
-> return Plan
```

The helper currently rejects only a missing Plan. It does not verify that the resolved Plan belongs to the same tenant and contour as the Order.

The missing invariant is:

```text
plan.tenant_id == order.tenant_id
AND
plan.region == order.region
```

This matters even though the public checkout currently creates same-scope Orders. `activate_paid_period()` is also an internal trust boundary used by provider integrations. A persisted Plan ID must not be sufficient to grant access across a tenant or contour boundary.

The production database schema does not enforce this relationship as a composite foreign key. `Order.plan_id` references `Plan.id`, while both records independently carry their own `tenant_id` and `region`. The lifecycle must therefore validate the scope before using the Plan to create or mutate access state.

### Existing paid-activation sequence

`activate_paid_period()` already performs the relevant work in a safe order:

```text
initial operation-idempotency lookup
-> verify and lock persisted Order / Payment / processed webhook context
-> resolve Plan through _find_plan_for_order()
-> lock and validate User
-> inspect subscription state
-> mutate or create Subscription
-> create Entitlement
-> write lifecycle events
```

`ANY-378` must preserve this sequence.

The scope check belongs in `_find_plan_for_order()` immediately after Plan resolution. This guarantees that a foreign-tenant or foreign-region Plan is rejected before the User lock, Subscription mutation, Entitlement creation, or lifecycle event creation.

Do not duplicate the check in `activate_paid_period()`.

### Error contract

Do not introduce a new lifecycle error code for this defect.

Keep the existing:

```text
order_plan_missing
```

and treat a Plan outside the Order scope as unavailable to that Order.

The canonical guard is:

```python
if (
    plan is None
    or plan.tenant_id != order.tenant_id
    or plan.region != order.region
):
    raise SubscriptionLifecycleError("order_plan_missing")
```

This preserves the existing plan-not-found behavior and avoids expanding the externally observable lifecycle error vocabulary without a requirement from the ticket.

### Resolution contract

Preserve both existing Plan resolution paths:

1. prefer `order.plan_id` when present;
2. otherwise use the existing `OrderItem` fallback and its `plan_id`;
3. load the resolved ID through the existing Plan query;
4. apply the same tenant/region validation regardless of which path produced the Plan ID.

Do not remove or bypass the `OrderItem` fallback.

Do not change `get_plan_by_id()` into a tenant/region-scoped query for this ticket. That query is reused by other lifecycle operations with their own scope-validation contracts. Broadening its signature would create unrelated churn and move a domain invariant into a lower-level query without necessity.

### No schema or public contract change

No new table, column, constraint, index, Alembic migration, Pydantic model, Enum, setting, API route, request field, response field, or generated artifact is required for `ANY-378`.

The fix is an application-level lifecycle invariant over already-persisted fields.

### Provider-neutral boundary and ANY-168

`ANY-378` remains entirely inside the provider-neutral billing lifecycle.

`ANY-168` will later consume this lifecycle from CloudPayments recurring/payment orchestration. That provider integration must be able to rely on `activate_paid_period()` refusing a Plan outside the persisted Order scope.

Do not move this validation into CloudPayments or any provider adapter. Provider-specific callers must not be responsible for enforcing the billing-domain tenant/contour invariant.

### Branching Decision

Create `ANY-378` from up-to-date `main`.

Do not create it from `ANY-377`, `ANY-379`, or `ANY-380`.

These tickets are independent post-merge fixes around the `ANY-78` lifecycle:

- `ANY-377` changes refund-after-expiration behavior;
- `ANY-378` validates resolved paid Order Plan scope;
- `ANY-379` hardens recurring-consent validation and automatic-renewal attachment;
- `ANY-380` fixes lifecycle operation-key concurrency semantics.

If `ANY-377`, `ANY-379`, or `ANY-380` is merged before branch creation, create `ANY-378` from the resulting latest `main`.

If work on `ANY-378` starts before those PRs merge, do not cherry-pick their branches into `ANY-378`. Update/rebase `ANY-378` onto the latest `main` before the final pull request and preserve their accepted changes when resolving conflicts.

`ANY-379` may change helpers in `apps/api/tests/test_billing_lifecycle.py`. If it is already merged, use the final helper shape from `main`; do not restore or duplicate an older fixture implementation.

`ANY-380` may change `activate_paid_period()` idempotency behavior. If it is already merged, preserve its post-lock idempotency recheck exactly as baseline behavior. `ANY-378` does not need to edit that logic.

The pull request target remains:

```text
main
```

### Out of Scope for ANY-378

- `ANY-377` refund-after-expiration state transitions or webhook behavior;
- `ANY-379` recurring-consent matching, `EnableAutomaticRenewalCommand`, legal validation, or provider-reference attachment;
- `ANY-380` lifecycle concurrency/idempotency changes or PostgreSQL race regressions;
- `ANY-168` CloudPayments recurrent API calls, card tokens, provider subscriptions, retries, or notification orchestration;
- adding Plan status, price, currency, product, bundle, or provider validation to paid activation;
- changing transaction isolation, row-lock strategy, `_transactional`, or payment/webhook verification;
- changing the Plan query API globally;
- database schema changes;
- public HTTP contract changes;
- general billing lifecycle refactoring.

---

# Step 1 — Reject resolved Plans outside the paid Order scope

**Status:** `done`  
**Commit:** `fix(billing): validate paid order plan scope`

## Prompt

Implement Step 1 of ANY-378: validate the resolved paid Order Plan tenant and region before any subscription or entitlement mutation.

Work only on the provider-neutral lifecycle defect described below. All required architectural and implementation decisions are already defined in this prompt. Do not perform broad codebase research, redesign the lifecycle, or implement adjacent tickets.

## Goal

`activate_paid_period()` must reject a verified paid Order when the Plan resolved for that Order belongs to a different `tenant_id` or `region`.

The rejection must happen before any `Subscription` or `Entitlement` is created or mutated and before a `PAID_PERIOD_ACTIVATED` event is written.

Preserve:

- successful same-tenant / same-region paid activation;
- existing verified Order / Payment / webhook validation;
- the existing `order.plan_id` resolution path;
- the existing `OrderItem.plan_id` fallback;
- the existing `order_plan_missing` error behavior;
- existing lifecycle idempotency and locking behavior;
- provider-neutral domain boundaries.

## Branch Context

Work on:

```text
ANY-378
```

created from the latest:

```text
main
```

Do not cherry-pick or depend on `ANY-377`, `ANY-379`, or `ANY-380`.

If those tickets are already present in `main`, preserve their changes and adapt only where required by merge/rebase conflicts.

The pull request target remains:

```text
main
```

## Relevant Existing Code

Work primarily in:

- `apps/api/app/domains/billing/service/support.py`
- `apps/api/tests/test_billing_lifecycle.py`

Read and preserve the surrounding behavior in:

- `apps/api/app/domains/billing/service/lifecycle.py`
- `apps/api/app/infrastructure/queries/plans.py`
- `apps/api/app/infrastructure/queries/orders.py`
- the current billing lifecycle test helpers in `apps/api/tests/test_billing_lifecycle.py`

Relevant production functions:

- `_find_plan_for_order(db: Session, order: Order) -> Plan`;
- `activate_paid_period(db: Session, command: ActivatePaidPeriodCommand) -> Subscription`;
- `get_plan_by_id(...)`;
- `get_order_item_with_plan(...)`;
- `_verify_successful_payment_context(...)`.

Relevant persisted fields:

`Order`:

- `id`;
- `tenant_id`;
- `region`;
- `user_id`;
- `plan_id`;
- `status`;
- `provider_account_id`;
- `provider`;
- `paid_at`.

`OrderItem`:

- `order_id`;
- `plan_id`.

`Plan`:

- `id`;
- `tenant_id`;
- `region`;
- `scope_type`;
- `product_id`;
- `bundle_id`;
- `price_amount_minor`;
- `currency`;
- `billing_period`.

## Implementation

### 1. Harden `_find_plan_for_order()`

Update:

```text
apps/api/app/domains/billing/service/support.py
```

Keep the current Plan ID resolution unchanged:

```python
plan_id = order.plan_id
if plan_id is None:
    item = get_order_item_with_plan(db, order.id)
    plan_id = item.plan_id if item else None
```

Keep loading the Plan through the existing query:

```python
plan = get_plan_by_id(db, plan_id) if plan_id else None
```

After resolving the Plan, fail closed unless all of the following are true:

```text
plan exists
plan.tenant_id == order.tenant_id
plan.region == order.region
```

Use the existing lifecycle error:

```python
SubscriptionLifecycleError("order_plan_missing")
```

for all three invalid cases.

The intended guard is:

```python
if (
    plan is None
    or plan.tenant_id != order.tenant_id
    or plan.region != order.region
):
    raise SubscriptionLifecycleError("order_plan_missing")
```

Then return the validated Plan as before.

Do not introduce a new `order_plan_scope_mismatch` or similar error code.

Do not move the validation into `activate_paid_period()`.

Do not perform separate validation only for `order.plan_id`; the `OrderItem` fallback must pass through the same final Plan validation.

### 2. Preserve the Plan query boundary

Do not change:

```text
apps/api/app/infrastructure/queries/plans.py
```

unless a merge conflict requires a mechanical adaptation unrelated to the behavior of this ticket.

Specifically, do not change `get_plan_by_id()` to accept `tenant_id` or `region` for this ticket.

The lifecycle helper owns the relationship between the resolved Plan and the Order that selected it.

Do not add a second query helper solely for the two scope comparisons.

### 3. Preserve paid-activation sequencing

Do not reorder `activate_paid_period()`.

The relevant behavior must remain:

```text
_verify_successful_payment_context(...)
-> _find_plan_for_order(...)
-> lock and validate User
-> inspect/mutate Subscription state
-> create Entitlement
-> write lifecycle events
```

Because `_find_plan_for_order()` runs before the User lock and all access-state mutations, rejecting the Plan in that helper satisfies the acceptance criterion that the failure occurs before subscription/entitlement mutation.

Do not add another Plan check later in the function.

Do not alter:

- the initial operation-idempotency fast path;
- any post-lock idempotency recheck already merged from `ANY-380`;
- `_verify_successful_payment_context()`;
- User locking;
- live subscription lookup/locking;
- replacement-subscription handling;
- carry-forward entitlement handling;
- entitlement creation for valid activations;
- lifecycle event writing for valid activations.

### 4. Add focused cross-scope lifecycle regressions

Update:

```text
apps/api/tests/test_billing_lifecycle.py
```

Add a focused parameterized test named approximately:

```text
test_activate_paid_period_rejects_order_plan_scope_mismatch_without_mutation
```

Cover exactly these two cases:

1. the resolved Plan has a different `tenant_id` from the Order;
2. the resolved Plan has a different `region` from the Order.

Create otherwise-valid persisted paid activation context using the existing final test helpers where possible:

```text
User
PaymentProviderAccount
paid Order
successful Payment
processed PaymentWebhookEvent
```

Keep the Order, User, Payment, webhook, and provider context valid and in the normal scope:

```text
tenant_id = "anytoolai"
region = "ru"
```

Create a separate Plan for the mismatch instead of corrupting the Order, User, Payment, or webhook scope.

Use an existing normal paid Plan as the source for implementation-relevant values and create a new Plan with a unique code.

Copy only the fields needed to produce an otherwise-valid Plan, including the source Plan's:

- `scope_type`;
- `product_id`;
- `bundle_id`;
- `price_amount_minor`;
- `currency`;
- `billing_period`.

Preserve any additional required constructor fields from the actual current model/fixture baseline.

For the tenant mismatch case:

```text
Order.tenant_id = "anytoolai"
Order.region = "ru"
Plan.tenant_id = a different tenant value
Plan.region = "ru"
```

For the region mismatch case:

```text
Order.tenant_id = "anytoolai"
Order.region = "ru"
Plan.tenant_id = "anytoolai"
Plan.region = "eu"
```

Use only an existing contour value accepted by the current test database. Do not add seed data or migrations for the test.

Point the otherwise-valid paid Order to the mismatched Plan through:

```text
order.plan_id
```

Use a unique `operation_idempotency_key` per parameterized case.

Call the real:

```python
activate_paid_period(...)
```

with the real persisted:

- `order_id`;
- `payment_id`;
- `webhook_event_id`;
- `occurred_at`.

For both mismatch cases, assert:

```text
SubscriptionLifecycleError("order_plan_missing")
```

Do not weaken the regression to assert only that some lifecycle error was raised.

### 5. Prove rejection occurs before access-state mutation

For every cross-scope mismatch case, assert after the failed call that the operation produced no access-state mutation.

At minimum prove:

1. no new `Subscription` exists for the target User / mismatched paid operation;
2. no `Entitlement` exists with `order_id` equal to the rejected Order ID;
3. no `SubscriptionEvent` exists with the attempted `operation_idempotency_key`;
4. no `PAID_PERIOD_ACTIVATED` event exists for the rejected Order.

Use the narrowest reliable queries supported by the current test model.

Do not rely only on transaction rollback as implicit proof. Query the persisted state and assert the absence explicitly.

Do not create a synthetic unit test that calls `_find_plan_for_order()` without the lifecycle. The acceptance criterion is about paid activation, so the focused regression must exercise `activate_paid_period()` and prove the lifecycle does not mutate access state.

### 6. Preserve existing missing-Plan behavior

Add a focused regression named approximately:

```text
test_activate_paid_period_preserves_missing_order_plan_without_mutation
```

Create an otherwise-valid verified paid activation context and make the Order resolve no Plan:

```text
order.plan_id is None
```

and ensure there is no `OrderItem` for that Order with a non-null `plan_id`.

Call `activate_paid_period()` and assert the existing:

```text
SubscriptionLifecycleError("order_plan_missing")
```

Also assert that the rejected operation created no:

- `Subscription`;
- order-backed `Entitlement`;
- `PAID_PERIOD_ACTIVATED` event;
- `SubscriptionEvent` for the attempted operation key.

Do not change the `OrderItem` fallback itself.

This regression exists to prove that extending the guard from:

```text
plan is None
```

to:

```text
plan is missing OR outside Order tenant/region scope
```

preserves the old missing-plan contract.

### 7. Preserve valid same-scope activation

Do not rewrite or duplicate the existing successful paid-activation coverage unless a small assertion is necessary to adapt to the final test helper shape.

Existing lifecycle tests already exercise valid paid activation and multiple paid periods for the same scope.

The production guard must continue to accept a Plan when:

```text
plan.tenant_id == order.tenant_id
AND
plan.region == order.region
```

Do not add extra validation for:

- Plan status;
- Plan validity window;
- Plan price versus Order amount;
- Plan currency versus Order currency;
- product or bundle ownership beyond existing model invariants;
- provider account;
- provider name.

Those are separate invariants and are not part of `ANY-378`.

### 8. Preserve adjacent-ticket boundaries

Do not implement any part of `ANY-377`.

Specifically, do not change:

- `SubscriptionStatus.EXPIRED -> SubscriptionStatus.REFUNDED`;
- refund lifecycle behavior;
- refund webhook handling.

Do not implement any part of `ANY-379`.

Specifically, do not modify:

- recurring-consent matching;
- `EnableAutomaticRenewalCommand`;
- legal acceptance validation;
- automatic-renewal order/entrypoint validation;
- provider-reference attachment semantics.

If `ANY-379` is already present in `main`, preserve its final test helpers and use them as baseline rather than duplicating old fixture code.

Do not implement any part of `ANY-380`.

Specifically, do not modify:

- post-lock operation-key rechecks;
- lifecycle concurrency behavior;
- trial concurrency handling;
- PostgreSQL concurrency tests;
- the `subscription_events.operation_idempotency_key` unique constraint.

If `ANY-380` is already present in `main`, preserve its `activate_paid_period()` idempotency behavior unchanged.

Do not implement any part of `ANY-168`.

Specifically, do not add:

- CloudPayments recurrent API calls;
- CloudPayments card tokens;
- provider subscription create/update/cancel orchestration;
- provider-specific retries;
- provider-specific state values inside the billing domain;
- notification orchestration.

### 9. Do not introduce unrelated abstractions or generated changes

Do not add:

- a new service class;
- a repository abstraction;
- a validator framework;
- a Pydantic contract;
- an Enum;
- a configuration setting;
- a database constraint;
- an Alembic migration.

Do not update generated DB schema or OpenAPI artifacts because no persisted or HTTP contract changes in this ticket.

Do not refactor unrelated billing code while touching the helper.

## Scope Constraints

Only the following production behavior should change:

```text
verified paid Order
+ resolved Plan from another tenant
-> order_plan_missing
-> no subscription or entitlement mutation
```

and:

```text
verified paid Order
+ resolved Plan from another region
-> order_plan_missing
-> no subscription or entitlement mutation
```

The following behavior must remain unchanged:

```text
verified paid Order
+ resolved same-tenant, same-region Plan
-> existing paid activation behavior
```

```text
Order with no resolvable Plan
-> order_plan_missing
```

```text
order.plan_id absent
+ OrderItem.plan_id present
-> existing fallback resolution
-> same tenant/region validation after Plan load
```

```text
same operation key retry/concurrency
-> preserve existing baseline behavior
```

No public API response shape changes are required.

No schema or migration changes are required.


## After Implementation

Report:

1. every file changed;
2. the exact final condition enforced by `_find_plan_for_order()`;
3. confirmation that `order.plan_id` resolution was preserved;
4. confirmation that the `OrderItem.plan_id` fallback was preserved;
5. confirmation that tenant mismatch and region mismatch both fail with `order_plan_missing`;
6. confirmation that validation happens before User/subscription/entitlement mutation;
7. how the regressions prove no `Subscription`, `Entitlement`, or `PAID_PERIOD_ACTIVATED` event is written on rejection;
8. how the missing-Plan regression proves the existing behavior was preserved;
9. confirmation that valid same-scope paid activation was not changed;
10. confirmation that no `ANY-377`, `ANY-379`, `ANY-380`, or `ANY-168` scope was implemented;
11. confirmation that no database schema, API, Pydantic, Enum, configuration, or generated contract changed;
12. the exact checks I should run manually.

## Commit

Final commit name:

```text
fix(billing): validate paid order plan scope
```

Status after implementation and successful manual verification:

```text
done
```

---

## Definition of Done for ANY-378

- Step 1 has been implemented and manually verified.
- Step 1 status is changed from `todo` to `done` only after the required manual checks pass.
- The resolved Plan must match the paid Order on both `tenant_id` and `region`.
- A cross-tenant resolved Plan is rejected with `order_plan_missing`.
- A cross-region resolved Plan is rejected with `order_plan_missing`.
- Rejection occurs before Subscription or Entitlement mutation and before paid-activation lifecycle event creation.
- Existing missing-Plan behavior remains `order_plan_missing`.
- Existing `order.plan_id` and `OrderItem.plan_id` resolution paths remain supported.
- Valid same-scope paid activation remains unchanged.
- No `ANY-377`, `ANY-379`, `ANY-380`, or `ANY-168` behavior is implemented by this ticket.
- No database migration, schema change, public API change, Pydantic contract, Enum, configuration value, or generated artifact is added.
- The final change is stored in one commit:

```text
fix(billing): validate paid order plan scope
```

After merge, the provider-neutral paid lifecycle is safe to reuse from later provider integration work without trusting callers to prevalidate Order-to-Plan tenant/contour scope.
