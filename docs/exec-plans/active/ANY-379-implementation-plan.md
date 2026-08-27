# ANY-379 — Fail-closed recurring consent boundary

## Plan Overview

| Field | Value |
| --- | --- |
| Feature | `ANY-71` |
| Ticket | `ANY-379` |
| Overall status | `todo` |
| Execution order | Sequential only: Step 1 → manual verification → commit → Step 2 |
| Steps / commits | 2 |
| Blocks | `ANY-168` |

## How to Use This File

1. Open the repository on the up-to-date branch for `ANY-379` and give the AI this file together with access to the codebase.
2. For the first commit, instruct the AI:

   > Read `docs/exec-plans/active/ANY-379-implementation-plan.md` and implement only Step 1. Follow the prompt exactly. Do not work on Step 2.

3. After the step is implemented, review the changes and manually run the checks listed at the end of the step.
4. If the checks pass, create a commit with the specified message and change the step status from `todo` to `done`.
5. Only then instruct the AI to implement the second step:

   > Read `docs/exec-plans/active/ANY-379-implementation-plan.md` and implement only Step 2. Step 1 is already complete. Follow the prompt exactly.

6. Do not ask the AI to implement both steps at once. Each step is designed as a separate change, review, and commit.

## Context and Locked Decisions

`ANY-379` closes two fail-open gaps in the recurring-consent boundary:

1. Checkout currently treats recurring consent with a missing `entrypoint_type`, missing `entrypoint_value`, or invalid `metadata.plan_code` as a wildcard.
2. `enable_automatic_renewal()` does not revalidate the current legal document/hash and exact checkout context before writing provider references and switching the subscription to automatic renewal.

The required checkout context is already persisted:

- `EntrypointSession` stores the exact `entrypoint_type` and `entrypoint_value`;
- `Order` stores `plan_id`, `entrypoint_session_id`, and metadata containing `auto_renew` and `recurring_consent_acceptance_id`;
- subscription-event provenance can prove that a paid order belongs to a specific subscription.

No new tables, columns, or database migrations are required for `ANY-379`.

Step 2 adds `order_id` to `EnableAutomaticRenewalCommand` to establish the stable provider-neutral boundary required later by `ANY-168`. The originating checkout must not be inferred as the first or latest order for a subscription because one subscription can have multiple `PAID_PERIOD_ACTIVATED` events.

### Out of Scope for ANY-379

- the refund fix from `ANY-377`;
- paid-activation tenant/region validation from `ANY-378`;
- lifecycle concurrency/idempotency changes from `ANY-380`;
- CloudPayments recurring orchestration from `ANY-168`;
- provider-specific DTOs or card tokens inside the billing domain.

---

# Step 1 — Make recurring consent matching fail closed

**Status:** `done`  
**Commit:** `fix(legal): fail closed recurring consent scope`

## Prompt

Implement step 1 of ANY-379: make recurring-payment consent validation fail closed at the checkout boundary.

## Goal

Harden the existing provider-neutral recurring-consent matcher so that a recurring consent is valid only when it is explicitly and exactly bound to the current user, contour, active legal document, checkout entrypoint, and plan.

This step must only change recurring-consent validation. Do not change non-recurring legal acceptance behavior.

## Relevant existing code

Work primarily in:

- `apps/api/app/domains/legal/service.py`
- `apps/api/tests/test_api.py`

The canonical function is:

- `is_current_recurring_consent_acceptance(...)`

It is used by:

- `get_current_recurring_consent_acceptance(...)`
- the authenticated `/api/auth/checkout-intent` flow

The existing bug is that:

- `acceptance.entrypoint_type is None` currently acts as a wildcard;
- `acceptance.entrypoint_value is None` currently acts as a wildcard;
- missing `metadata.plan_code` acts as a wildcard;
- non-string `metadata.plan_code` acts as a wildcard.

## Implementation

### 1. Make `is_current_recurring_consent_acceptance()` the complete canonical predicate

Keep all existing current-document requirements and make the predicate independently safe enough to be reused by the billing lifecycle in the next step.

For the supplied `DocumentAcceptance`, require all of the following:

- `acceptance.tenant_id == user.tenant_id`;
- `acceptance.region == user.region`;
- `acceptance.user_id == user.id`;
- `acceptance.doc_type == "recurring_consent"`;
- `acceptance.acceptance_kind == AcceptanceKind.RECURRING_CONSENT.value`;
- `acceptance.accepted_at <= effective_at`.

For the referenced `DocumentVersion`, require:

- the document exists;
- document tenant matches the user;
- document region matches the user;
- `document.doc_type == "recurring_consent"`;
- `document.is_active is True`;
- `document.requires_acceptance is True`;
- `document.effective_from <= effective_at`.

Keep the existing acceptance text integrity check:

- `acceptance.acceptance_text_hash == expected_acceptance_text_hash(document)`.

Make checkout scope matching strictly fail closed:

- `acceptance.entrypoint_type` must exactly equal the supplied `entrypoint_type`;
- `acceptance.entrypoint_value` must exactly equal the supplied `entrypoint_value`;
- `acceptance.metadata_` must contain `plan_code`;
- `metadata.plan_code` must be a `str`;
- `metadata.plan_code` must exactly equal the supplied `plan_code`.

Do not treat `None`, a missing key, a non-dict metadata value, or a non-string `plan_code` as a wildcard.

Do not introduce fallback values.

Keep the existing UTC/timezone normalization approach instead of introducing a second datetime comparison convention.

### 2. Keep `get_current_recurring_consent_acceptance()` as the checkout-facing resolver

Do not remove its existing database filters. Let it continue to narrow the candidate row and then delegate the definitive validation to `is_current_recurring_consent_acceptance()`.

Do not introduce another parallel recurring-consent validation implementation.

### 3. Do not change the generic legal-acceptance API contract in this step

Do not change:

- `AcceptDocumentRequest`;
- `POST /api/legal/acceptances`;
- `create_document_acceptance(...)`;
- database columns or migrations.

The legal acceptance endpoint is shared by recurring and non-recurring documents. ANY-379 requires ambiguous recurring evidence to stop satisfying recurring checkout validation; it does not require changing generic persistence semantics.

An ambiguous recurring acceptance may still exist as append-only evidence, but it must never authorize automatic renewal.

### 4. Update focused API coverage

Update `apps/api/tests/test_api.py`.

The existing successful automatic-checkout test must use a fully scoped recurring consent. Do not keep a happy path that creates the acceptance without `entrypoint_type`, `entrypoint_value`, or `metadata.plan_code`.

Cover these recurring checkout cases:

1. exact user + contour + active document + hash + entrypoint type + entrypoint value + string plan code succeeds;
2. `entrypoint_type=None` is rejected with the existing `recurring_consent_invalid` checkout result;
3. `entrypoint_value=None` is rejected;
4. missing `metadata.plan_code` is rejected;
5. non-string `metadata.plan_code` is rejected;
6. wrong string `metadata.plan_code` is rejected;
7. existing wrong-entrypoint behavior remains rejected;
8. existing stale-document, foreign-user, foreign-contour, wrong-kind and future-acceptance coverage continues to work.

Prefer parameterizing the new null/missing/wrong-type scope cases rather than duplicating complete checkout setup.

Where practical, create malformed/ambiguous acceptance evidence through the existing public `/api/legal/acceptances` route so the regression test proves that persistence of an ambiguous row cannot make it valid for checkout.

Do not change the behavior of `auto_renew=false` checkout.

## Scope constraints

Do not:

- modify subscription lifecycle code yet;
- add new tables or migrations;
- add CloudPayments-specific logic;
- modify provider adapters;
- implement ANY-168 recurring subscription orchestration;
- touch refund handling;
- touch paid-plan tenant/region validation;
- touch lifecycle operation-key concurrency handling;
- refactor unrelated legal code.

## Automated checks

Do NOT run tests, pytest, linters, formatters, type checkers, generators, `npm run check`, `npm run check:fast`, or any other automated verification command.

Do not automatically reformat unrelated files.

## After implementation

Report:

1. the files changed;
2. the exact recurring-consent invariant now enforced;
3. any existing tests that had to be corrected because they encoded the wildcard behavior;
4. the exact checks I should run manually.

Tell me to run these checks manually, but do not run them yourself:

```bash
pytest apps/api/tests/test_api.py -k "automatic_checkout or recurring_acceptance or recurring_consent"
npm run check:fast
```

## Commit

Final commit name:

```text
fix(legal): fail closed recurring consent scope
```

Status:

```text
todo
```

---

# Step 2 — Revalidate recurring consent before automatic-renewal attachment

**Status:** `done`  
**Commit:** `fix(billing): revalidate recurring consent on renewal attach`  
**Depends on:** Step 1 completed, manually verified, and committed.

## Prompt

Implement step 2 of ANY-379: enforce the same fail-closed recurring-consent boundary inside `enable_automatic_renewal()` before any provider reference is attached to a subscription.

Step 1 is assumed to be complete: `is_current_recurring_consent_acceptance()` is now the canonical strict validator for current document/hash/user/contour/plan/entrypoint context.

## Goal

`enable_automatic_renewal()` must not trust only the supplied acceptance ID and subscription IDs.

Before changing the subscription from manual to automatic, it must prove that:

- the supplied internal order is the paid checkout that belongs to this subscription;
- that checkout requested automatic renewal;
- the supplied acceptance is exactly the acceptance persisted for that checkout;
- the checkout entrypoint is available and belongs to the same user/contour;
- the acceptance is still valid for the subscription plan and exact checkout entrypoint;
- the recurring legal document is still current and the acceptance hash is still correct.

All validation must happen before provider fields or renewal mode are mutated.

## Relevant existing code

Work primarily in:

- `apps/api/app/domains/billing/service/commands.py`
- `apps/api/app/domains/billing/service/lifecycle_operations.py`
- `apps/api/app/infrastructure/queries/orders.py`
- `apps/api/tests/test_billing_lifecycle.py`

Reuse existing functionality from:

- `apps/api/app/domains/legal/service.py`
- `apps/api/app/infrastructure/queries/subscriptions.py`
- `apps/api/app/infrastructure/queries/identity.py`

Do not create provider-specific dependencies in the billing domain.

## Implementation

### 1. Extend `EnableAutomaticRenewalCommand`

Add:

```python
order_id: uuid.UUID
```

to `EnableAutomaticRenewalCommand`.

Do not add entrypoint type, entrypoint value, plan code, CloudPayments token, CloudPayments subscription state, or other duplicated checkout fields to this command.

`order_id` is the canonical internal reference to the checkout/payment context. The remaining values must be reloaded from persisted domain state rather than trusted from the caller.

This command change is intentionally preparing the stable provider-neutral boundary used by ANY-168.

### 2. Resolve and validate the exact paid checkout context

Inside `enable_automatic_renewal()` preserve the existing operation-idempotency behavior and row locking.

Before mutating the subscription:

- load and lock the subscription;
- load and lock the supplied `Order`;
- load and lock the provider account;
- load and lock the supplied `DocumentAcceptance`;
- load the subscription plan;
- resolve the authenticated `User` represented by `subscription.user_id`;
- resolve the `EntrypointSession` referenced by `order.entrypoint_session_id`.

Add a small infrastructure query such as `get_entrypoint_session_by_id(...)` in `apps/api/app/infrastructure/queries/orders.py` rather than adding checkout SQL directly to the lifecycle service.

Use the existing subscription-event provenance to prove the supplied order belongs to this subscription. Reuse `get_subscription_for_order(...)` and require the resolved subscription ID to equal `command.subscription_id`.

Do not infer the checkout by taking the first or latest order for a subscription. A subscription can have multiple paid-period activation events, so the caller must identify the exact internal order through `command.order_id`.

### 3. Validate order/subscription context

Require the order to match the subscription on the fields that define this lifecycle operation:

- same `tenant_id`;
- same `region`;
- same `user_id`;
- `order.plan_id == subscription.plan_id`;
- the order is linked through a `PAID_PERIOD_ACTIVATED` event to this exact subscription.

Require checkout metadata to represent an automatic-renewal checkout:

- `order.metadata_` must be a dict;
- `order.metadata_["auto_renew"] is True`;
- `order.metadata_["recurring_consent_acceptance_id"]` must equal `str(command.recurring_consent_acceptance_id)`.

Do not silently accept missing metadata.

This preserves the ANY-78 invariant that the exact recurring-consent evidence selected during checkout is what is attached after successful provider setup.

### 4. Validate persisted entrypoint context

Require `order.entrypoint_session_id` to be present and resolve to an existing `EntrypointSession`.

Require that entrypoint session to match the checkout/subscription contour:

- `entrypoint_session.tenant_id == subscription.tenant_id`;
- `entrypoint_session.resolved_region == subscription.region`;
- `entrypoint_session.user_id == subscription.user_id`.

Use the persisted:

- `entrypoint_session.entrypoint_type`;
- `entrypoint_session.entrypoint_value`;

as the expected consent entrypoint context.

Do not derive these values from the provider request and do not trust new command parameters for them.

### 5. Revalidate the recurring consent using the canonical legal matcher

After the existing direct scope checks, call the strict `is_current_recurring_consent_acceptance(...)` from the legal domain with:

- the loaded `DocumentAcceptance`;
- the loaded subscription `User`;
- `entrypoint_type=entrypoint_session.entrypoint_type`;
- `entrypoint_value=entrypoint_session.entrypoint_value`;
- `plan_code=plan.code`;
- `now=command.occurred_at`.

This must revalidate:

- user;
- tenant;
- region;
- recurring acceptance kind/type;
- acceptance timestamp;
- current active required recurring document;
- document effective time;
- exact acceptance text hash;
- exact entrypoint type;
- exact entrypoint value;
- exact string `plan_code`.

Do not duplicate these legal-document rules inside `lifecycle_operations.py`.

### 6. Preserve existing lifecycle failure semantics

Do not introduce a new family of externally visible lifecycle error codes unless required by existing conventions.

Keep the current errors where they already apply:

- `automatic_renewal_context_missing` for missing required persisted lifecycle/checkout objects;
- `provider_account_scope_mismatch` for provider-account contour mismatch;
- `consent_scope_mismatch` for the existing direct acceptance contour mismatch;
- `recurring_consent_invalid` when recurring consent fails its semantic/current-context validation;
- `automatic_renewal_not_permitted` when the subscription plan does not permit automatic renewal;
- `provider_subscription_reference_conflict` for the existing unique provider-reference conflict.

Most importantly, every validation failure must happen before assigning:

- `subscription.provider_account_id`;
- `subscription.provider_subscription_id`;
- `subscription.recurring_consent_acceptance_id`;
- `subscription.renewal_mode`.

A failed validation must leave the subscription in `renewal_mode="manual"` with provider references unchanged and must not create an `AUTOMATIC_RENEWAL_ENABLED` event.

Preserve the existing idempotent early return for an already-recorded operation key.

### 7. Update focused lifecycle tests

Update `apps/api/tests/test_billing_lifecycle.py`.

Adjust existing automatic-renewal fixtures so they create a real valid context instead of the current minimal acceptance with no plan/entrypoint/current-document proof.

A valid fixture must contain the necessary persisted chain:

```text
User
-> current recurring DocumentVersion
-> scoped DocumentAcceptance
-> EntrypointSession
-> paid Order
-> Subscription
-> PAID_PERIOD_ACTIVATED SubscriptionEvent
```

The order must contain:

- `auto_renew=True`;
- the exact recurring acceptance ID;
- the same plan as the subscription;
- the `entrypoint_session_id`.

The acceptance must contain:

- the expected acceptance text hash;
- exact entrypoint type/value;
- string `metadata.plan_code`.

Cover at least:

1. valid same-user/same-contour/same-plan/same-entrypoint/current-document consent succeeds;
2. stale document is rejected;
3. wrong acceptance text hash is rejected;
4. missing entrypoint context is rejected;
5. wrong `metadata.plan_code` is rejected;
6. wrong entrypoint type/value is rejected;
7. foreign user consent is rejected;
8. foreign contour consent is rejected;
9. an order not linked to the target subscription is rejected;
10. an acceptance ID different from the one stored on the automatic-renewal order is rejected.

For every failure case assert that:

- `renewal_mode` remains `manual`;
- `provider_account_id` is unchanged;
- `provider_subscription_id` is unchanged;
- `recurring_consent_acceptance_id` is unchanged;
- no `AUTOMATIC_RENEWAL_ENABLED` event was written.

Update the existing provider-subscription-reference conflict test to construct valid consent/order/entrypoint context and pass `order_id`, so the test continues exercising the provider-reference uniqueness behavior rather than failing earlier at the new consent boundary.

## Scope constraints

Do not:

- modify CloudPayments adapter or recurrent API code;
- create or cancel a provider subscription;
- consume or persist a CloudPayments card token;
- implement ANY-168 webhook orchestration;
- change subscription database schema;
- add recurring checkout columns;
- implement ANY-377 refund changes;
- implement ANY-378 paid-activation tenant/region changes;
- implement ANY-380 concurrency-idempotency changes;
- refactor unrelated billing lifecycle operations.

No database migration should be necessary.

## Automated checks

Do NOT run tests, pytest, linters, formatters, type checkers, generators, `npm run check`, `npm run check:fast`, or any other automated verification command.

Do not automatically reformat unrelated files.

## After implementation

Report:

1. every file changed;
2. the exact persisted chain used to bind consent to the subscription checkout;
3. the new `EnableAutomaticRenewalCommand` contract;
4. confirmation that no provider field is mutated before validation;
5. the exact checks I should run manually.

Tell me to run these checks manually, but do not run them yourself:

```bash
pytest apps/api/tests/test_billing_lifecycle.py -k "automatic_renewal"
npm run test:api
npm run check:fast
```

## Commit

Final commit name:

```text
fix(billing): revalidate recurring consent on renewal attach
```

Status:

```text
todo
```

---

## Definition of Done for ANY-379

- Step 1 has status `done`, has passed manual verification, and is stored in a separate commit.
- Step 2 has status `done`, has passed manual verification, and is stored in a separate commit.
- Recurring consent with `NULL`, missing, or wrong-type checkout context cannot authorize automatic checkout.
- The billing lifecycle revalidates the current legal document, hash, user/contour, plan, and exact entrypoint before any provider-field mutation.
- Failed validation leaves the subscription in manual renewal with no new provider references and no `AUTOMATIC_RENEWAL_ENABLED` event.
- The changes do not include work from `ANY-377`, `ANY-378`, `ANY-380`, or `ANY-168`.
- No database migrations are added.

After these two commits, `ANY-379` is complete and `ANY-168` has a clean provider-neutral integration point through `EnableAutomaticRenewalCommand` with the initial `order_id`.
