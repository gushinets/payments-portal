# ANY-377 — Fix full refund after subscription expiration

## Plan Overview

| Field | Value |
| --- | --- |
| Feature | `ANY-71` |
| Parent | `ANY-78` |
| Ticket | `ANY-377` |
| Overall status | `done` |
| Execution order | Sequential only: Step 1 → manual verification → commit |
| Steps / commits | 1 |
| Blocks | `ANY-168` |
| Recommended branch | `ANY-377` from up-to-date `main` |

## How to Use This File

1. Open the repository on the up-to-date `ANY-377` branch created from `main` and give the AI this file together with access to the codebase.
2. Instruct the AI:

   > Read `docs/exec-plans/active/ANY-377-implementation-plan.md` and implement only Step 1. Follow the prompt exactly.

3. After the step is implemented, review the changes and manually run the checks listed at the end of the step.
4. If the checks pass, create the specified commit and change the step status from `todo` to `done`.
5. This ticket intentionally has one implementation step. Do not split the state-machine fix and its regression test into separate commits because they form one coherent behavior change.

## Context and Locked Decisions

`ANY-377` fixes a post-merge defect in the provider-neutral subscription lifecycle implemented by `ANY-78`.

The failing lifecycle is:

```text
verified paid order
-> paid subscription becomes active
-> paid entitlement becomes active
-> expire_due_subscriptions()
-> subscription becomes expired
-> entitlement becomes expired
-> verified full refund webhook
-> apply_refund()
-> full refund must finalize the subscription as refunded
```

`apply_refund()` already contains the required full-refund orchestration. For a full refund it:

- resolves and validates the persisted order, refund, payment, and subscription context;
- applies refund effects only to entitlements funded by the refunded order;
- checks whether any active or future grants remain;
- keeps the subscription non-terminal if another grant remains;
- transitions the subscription to `REFUNDED` when no active or future grant remains;
- writes the `REFUND_APPLIED` subscription event.

The defect is the subscription state machine.

`SUBSCRIPTION_STATUS_TRANSITIONS` currently has no outgoing transition from `SubscriptionStatus.EXPIRED`. Therefore, after `expire_due_subscriptions()` has already finalized the subscription as expired, a later verified full refund reaches the correct business decision in `apply_refund()` but fails while validating:

```text
EXPIRED -> REFUNDED
```

with:

```text
SubscriptionLifecycleError("invalid_subscription_status_transition")
```

The required and locked lifecycle decision for `ANY-377` is:

```text
EXPIRED -> REFUNDED
```

This transition represents a later financial reversal of a paid period that had already ended naturally.

It must not restore access.

Both `EXPIRED` and `REFUNDED` remain non-live subscription states. `REFUNDED` remains terminal.

The already-expired entitlement does not need to be rewritten to `REVOKED` merely because the refund arrived later. The acceptance requirement is that it remains non-active and access is not resurrected.

No new tables, columns, API contracts, provider abstractions, or database migrations are required for `ANY-377`.

### Branching Decision

Create `ANY-377` from up-to-date `main`, not from `ANY-379`.

`ANY-377` and `ANY-379` are independent post-merge fixes for `ANY-78`. `ANY-379` changes recurring-consent and automatic-renewal validation; `ANY-377` changes the refund-after-expiration lifecycle edge and its regression coverage.

If `ANY-379` or another accepted change is merged into `main` before the `ANY-377` pull request is opened, update/rebase `ANY-377` onto the latest `main`.

### Out of Scope for ANY-377

- recurring-consent hardening from `ANY-379`;
- paid-activation tenant/region validation from `ANY-378`;
- lifecycle operation-key concurrency/idempotency changes from `ANY-380`;
- CloudPayments recurring orchestration from `ANY-168`;
- provider-specific subscription lifecycle semantics inside the billing domain;
- new database schema or migrations;
- new API endpoints or request/response contracts;
- general subscription lifecycle refactoring unrelated to the defect.

---

# Step 1 — Allow full refund after expiration and cover the real webhook lifecycle

**Status:** `done`  
**Commit:** `fix(billing): allow refund after subscription expiration`

## Prompt

Implement step 1 of ANY-377: allow a verified full refund to finalize an already-expired paid subscription as refunded, and add a PostgreSQL regression covering the real webhook lifecycle.

## Goal

Fix only the state-machine defect that currently rejects:

```text
SubscriptionStatus.EXPIRED -> SubscriptionStatus.REFUNDED
```

and prove through the existing PostgreSQL CloudPayments webhook integration test that this full production sequence succeeds:

```text
successful pay webhook
-> paid subscription and entitlement
-> expire_due_subscriptions()
-> expired subscription and non-active entitlement
-> verified full refund webhook
-> refunded subscription
```

The refund must remain atomic, provider-neutral, idempotent for duplicate webhook delivery, and must never restore access.

## Relevant existing code

Work primarily in:

- `apps/api/app/domains/billing/service/state_machine.py`
- `apps/api/tests/test_cloudpayments_webhook_postgres.py`

Read and preserve the existing behavior in:

- `apps/api/app/domains/billing/service/lifecycle_operations.py`
- `apps/api/app/domains/billing/service/support.py`
- `apps/api/app/infrastructure/queries/subscriptions.py`
- `apps/api/app/integrations/cloudpayments/processing.py`

Relevant existing lifecycle operations:

- `apply_refund(...)`
- `expire_due_subscriptions(...)`

Relevant commands:

- `ApplyRefundCommand`
- `ExpireDueSubscriptionsCommand`

Relevant existing test helpers/fixtures:

- `webhook_database`
- `seed_order(...)`
- `paid_payload(...)`
- `refund_payload(...)`

There is already PostgreSQL webhook coverage for a full refund after a provider-canceled subscription. Follow that test style instead of building a parallel test framework.

## Implementation

### 1. Add the exact state-machine transition required by the ticket

Update:

- `apps/api/app/domains/billing/service/state_machine.py`

In `SUBSCRIPTION_STATUS_TRANSITIONS`, add `SubscriptionStatus.EXPIRED` as a source state with exactly one allowed outgoing transition:

```text
SubscriptionStatus.EXPIRED -> SubscriptionStatus.REFUNDED
```

Do not add any other outgoing transition from `EXPIRED`.

In particular, do not allow:

```text
EXPIRED -> ACTIVE
EXPIRED -> PAST_DUE
EXPIRED -> PAUSED
EXPIRED -> CANCELED
EXPIRED -> TRIALING
```

Keep `REFUNDED` terminal. Do not add a `REFUNDED` transition set that enables further lifecycle movement.

Use the existing structure and formatting style of `state_machine.py`.

### 2. Do not redesign `apply_refund()`

Do not add a special-case branch such as:

```text
if subscription.status == EXPIRED:
    ...
```

unless the regression exposes a concrete incompatibility that cannot be solved by the required state-machine edge.

The existing refund lifecycle already makes the correct business decision:

- a full refund with no remaining active/future grant finalizes the subscription as `REFUNDED`;
- a full refund must not revoke unrelated future paid grants;
- entitlement access remains controlled by entitlement state and validity.

Transition validity belongs in the state machine. Do not duplicate state-transition rules inside `apply_refund()`.

Do not introduce provider-specific behavior into the billing lifecycle.

### 3. Preserve atomic refund processing

Do not change the existing transaction boundary.

The verified refund webhook, refund persistence, payment/order refund state, subscription lifecycle transition, entitlement effects, and `REFUND_APPLIED` event must continue to participate in the existing transaction.

Do not add intermediate commits inside `apply_refund()` or the CloudPayments processing flow.

Do not move lifecycle mutation into the HTTP route or provider adapter.

### 4. Add a focused PostgreSQL webhook regression

Update:

- `apps/api/tests/test_cloudpayments_webhook_postgres.py`

Add a focused regression test for the ticket.

Use the existing `webhook_database` fixture and existing seed/payload helpers.

The regression must exercise the real production lifecycle rather than constructing the final state manually.

Use this sequence:

1. Seed an order with the existing `seed_order(...)` helper.
2. Send the normal successful:

   ```text
   POST /api/cloudpayments/pay
   ```

   webhook using the existing `paid_payload(...)` helper.

3. Assert the pay webhook succeeds before continuing.
4. Load the subscription created by the paid lifecycle.
5. Load its paid entitlement.
6. Derive an expiration timestamp strictly after `subscription.current_period_end`.
7. Call the real provider-neutral:

   ```python
   expire_due_subscriptions(...)
   ```

   with `ExpireDueSubscriptionsCommand` at that logical timestamp.

8. Persist the expiration transaction according to the existing test/session pattern.
9. Before sending the refund webhook, reload state and prove that:

   - `subscription.status == SubscriptionStatus.EXPIRED.value`;
   - the entitlement is no longer active;
   - the existing expiration behavior has marked the entitlement expired;
   - exactly one `SUBSCRIPTION_EXPIRED` event exists for the subscription.

10. Send a verified full refund through:

    ```text
    POST /api/cloudpayments/refund
    ```

    using the existing `refund_payload(...)` helper and the full payment amount.

11. If the webhook processing timestamp must be controlled so that the refund logically occurs after the simulated expiration, patch the existing `cloudpayments_processing.datetime_now` clock in the test rather than changing production time semantics.

    Keep the lifecycle timestamps chronologically consistent:

    ```text
    paid_at < current_period_end < expiration_at < refund_at
    ```

12. Assert the refund webhook returns the normal CloudPayments acknowledgement:

    ```text
    HTTP 200
    {"code": 0}
    ```

### 5. Verify the persisted result after the first refund

After the refund transaction commits, reload the persisted entities and verify:

- the order is `REFUNDED`;
- the payment is `REFUNDED`;
- `payment.refunded_amount_minor` equals the full payment amount;
- exactly one `Refund` row exists for this provider refund;
- the subscription is `SubscriptionStatus.REFUNDED`;
- the entitlement is not `EntitlementStatus.ACTIVE`;
- the expired entitlement has not been reactivated;
- the previous `SUBSCRIPTION_EXPIRED` event is still persisted;
- exactly one `REFUND_APPLIED` subscription event exists;
- `REFUND_APPLIED.previous_status == SubscriptionStatus.EXPIRED.value`;
- `REFUND_APPLIED.next_status == SubscriptionStatus.REFUNDED.value`.

Do not require an already-expired entitlement to become `REVOKED` unless existing lifecycle code already does so naturally.

The acceptance criterion is that it remains non-active and no access is restored.

### 6. Prove that access is not resurrected

The regression must prove that the refund does not make the user eligible for access again.

At minimum, verify that there is no active entitlement after the refund.

If an existing access-query helper is already available and natural to reuse from this test, use it. Do not introduce a new access service or abstraction only for this regression.

Do not create a replacement entitlement.

### 7. Cover repeated refund webhook delivery

In the same regression scenario, send the exact same refund webhook notification again.

Use the same provider refund identity/idempotency data as the first delivery.

Verify:

- the duplicate delivery is acknowledged successfully according to the existing webhook behavior;
- there is still exactly one `Refund` domain row for the provider refund;
- there is still exactly one `REFUND_APPLIED` subscription event;
- the subscription remains `REFUNDED`;
- the entitlement remains non-active;
- no access is restored.

Do not implement new lifecycle-operation concurrency semantics here.

`ANY-380` owns concurrency-idempotency changes. This step only verifies the existing webhook duplicate-delivery contract for the `ANY-377` scenario.

### 8. Keep the production diff minimal

The expected production/test files are:

```text
apps/api/app/domains/billing/service/state_machine.py
apps/api/tests/test_cloudpayments_webhook_postgres.py
```

A change to `lifecycle_operations.py` is not expected.

If a concrete incompatibility discovered while implementing the regression requires another production-file change, keep it minimal and explain exactly why the state-machine change alone was insufficient.

Do not make opportunistic cleanup or refactoring changes.

## Scope constraints

Do not:

- implement `ANY-378`;
- implement `ANY-379`;
- implement `ANY-380`;
- implement `ANY-168`;
- change recurring-consent validation;
- change automatic-renewal behavior;
- change paid plan tenant/region validation;
- redesign lifecycle idempotency;
- add migrations;
- add tables or columns;
- add API endpoints;
- add request/response models;
- add CloudPayments-specific status semantics to the billing domain;
- refactor unrelated lifecycle code;
- change expired-entitlement semantics beyond what is required to keep access denied.

## Automated checks

During implementation, run the focused regression:

pytest apps/api/tests/test_cloudpayments_webhook_postgres.py -k "full_refund_after_subscription_expiration"

Before handoff, run the broadest supported canonical check:

npm run check:fast

If a required check cannot be executed in the current environment, record the skipped check and the reason.

## After implementation

Report:

1. the files changed;
2. the exact state-machine transition added;
3. whether `apply_refund()` required any production change and, if so, why;
4. the exact paid → expired → refunded lifecycle covered by the new regression;
5. how the regression proves that access is not restored;
6. how duplicate refund delivery is verified;
7. the exact checks I should run manually.

report the checks executed and their results

```bash
pytest apps/api/tests/test_cloudpayments_webhook_postgres.py -k "full_refund_after_subscription_expiration"
npm run check:fast
```

If the test is named differently, give me the exact pytest node ID or an equivalent focused selector for the new regression.

## Commit

Final commit name:

```text
fix(billing): allow refund after subscription expiration
```

Status:

```text
done
```
