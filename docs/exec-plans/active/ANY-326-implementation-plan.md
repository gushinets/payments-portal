# ANY-326 — Canonical persisted enums and model-layer contract — revised after review

## Plan Overview

| Field | Value |
| --- | --- |
| Feature | `ANY-407` |
| Ticket | `ANY-326` |
| Overall status | `todo` |
| Execution order | Sequential only: Step 1 → manual verification → commit → Step 2 → manual verification → commit → Step 3 → manual verification → commit → Step 4 → manual verification → commit → Step 5 |
| Steps / commits | 5 |
| Architecture role | Stage 0 / prerequisite for the following ANY-407 domain/application refactoring |
| Database migration | None expected; unknown persisted values block the refactor rather than triggering an automatic migration |
| Business behavior changes | None |
| Public API / OpenAPI changes | None; existing schema component identity must remain stable |
| Existing-data gate | Required before accepting Step 1 when an existing database is available |

## Review Changes Incorporated

This revision incorporates the plan-review findings against the current ANY-326 / ANY-407 contract and repository state:

1. Preserve the existing public enum class names `SubscriptionScopeType` and `SubscriptionRenewalMode` instead of renaming them to neutral internal names and accidentally changing OpenAPI schema components.
2. Add a read-only compatibility gate for already persisted database values before accepting the fail-closed enum adapter.
3. Keep `EntrypointSession.region_mismatch_status` and `Order.region_mismatch_status` as strings because only `none` is currently confirmed and a complete closed vocabulary is not yet defined.
4. Add a narrow static architecture guard plus ADR `0003-canonical-persisted-model-layer.md` so the new ownership rule is durable rather than only documented in this implementation plan.
5. Make raw-string binding explicitly transitional: Steps 1–4 may accept validated raw strings, but the final Step-5 `PersistedEnumType` contract must accept canonical enum members only and reject plain strings.
6. Add an explicit single-value-enum rule: a single observed/default value is not enough by itself; a one-member enum is allowed only for a confirmed application-owned closed vocabulary whose expansion is an explicit model-contract change.
7. Keep model-layer internal imports direct: ORM modules and temporary compatibility modules import canonical definitions from `app.models.enums`; `app.models.__init__` remains the public external façade and must not become an internal circular dependency.
8. Strengthen per-step verification: add account-subscription API coverage after Step 3, `architecture:check` after Step 4, and `docs:check` plus focused architecture-guard tests after Step 5.
9. Make the architecture guard exact and narrow: protect the known canonical persisted enum class names and obsolete import/facade paths without banning unrelated `StrEnum` classes such as provider or non-persisted domain enums.

## How to Use This File

1. Work from an up-to-date branch based on the current `main`.
2. Give the AI this file and instruct it to implement exactly one step at a time.
3. For Step 1:

   > Read the ANY-326 implementation plan and implement only Step 1. Do not work on later steps. Do not run automated checks and do not create a commit.

4. Review the resulting diff yourself.
5. Run the manual checks listed for that step.
6. If they pass, create the commit yourself using the specified commit name and change the step status from `todo` to `done`.
7. Only then give the AI the next step.
8. The AI must not independently investigate or redesign the architecture. Architectural and vocabulary decisions required for this ticket are locked below.
9. For Step 1, do not accept the commit until the read-only existing-data compatibility gate has been run against every available existing database that will be upgraded.
10. For every step that can affect API typing/generation, run `npm run generate:check` manually; any incidental OpenAPI diff is a regression for this ticket.

---

# Context and Locked Decisions

ANY-326 is the model-layer prerequisite for the following architecture work in ANY-407.

The ticket does **not** create a separate domain entity layer and does **not** move business logic out of existing services.

The target dependency is:

```text
app.models
├── SQLAlchemy models
└── canonical persisted enums

domains / integrations / infrastructure
        ↓
     app.models
```

The current reverse dependency:

```text
app.models
        ↓
app.domains.billing.enums
```

must disappear for persisted model vocabularies.

## Persistence contract

Persisted enums are Python `StrEnum` values but database storage remains the existing `TEXT` / `VARCHAR` representation.

Do not:

- introduce PostgreSQL native ENUMs;
- alter persisted string values;
- modify historical Alembic migrations;
- create a migration merely because Python ORM typing changes;
- create parallel ORM and domain enums containing the same persisted vocabulary.

Use one shared SQLAlchemy adapter for enum-backed model fields so that:

```python
payment.status
```

loads as:

```python
PaymentStatus
```

while PostgreSQL still stores:

```text
succeeded
```

During Steps 1–4, the adapter must also allow a valid raw string, convert/validate it through the target enum and persist the enum `.value`. This is a **temporary staged-migration compatibility rule only** so the first four commits can be accepted sequentially without breaking runtime code that has not yet been migrated.

The final Step-5 contract is stricter:

```text
enum member -> accepted and persisted as .value
plain raw str -> rejected at the ORM bind boundary
unknown database value -> rejected on load
```

Step 5 must remove the temporary raw-string bind compatibility after all runtime consumers have been migrated to canonical enum members. External/provider strings remain strings at their owning boundary and must be explicitly mapped/validated into the canonical enum before assignment to an enum-backed ORM attribute.

### Internal model import contract

Inside `app.models`, canonical enum definitions are imported directly from:

```python
from app.models.enums import ...
```

or the equivalent relative import.

`app.models.__init__` is the public export façade for callers outside the model package; model modules themselves must not import canonical enum classes back through `app.models`, because that obscures ownership and can create circular imports.

Temporary compatibility modules in `app.domains.billing.enums` and `app.domains.legal.enums` must also reference the exact class objects from `app.models.enums`, not define duplicate classes and not route the alias through `app.models.__init__`.

`app.models._shared` may contain the shared SQLAlchemy adapter/helpers, but it must not become a permanent re-export façade for canonical enum classes.

## Existing persisted-data compatibility gate

Changing a SQLAlchemy attribute from unrestricted `str` to a fail-closed enum adapter can make an existing row unreadable even when the physical PostgreSQL column remains `TEXT`.

Before accepting the Step 1 commit, perform a read-only inventory of the **actual existing database data that will be upgraded**, where such a database is available. For every field converted to `PersistedEnumType`, compare all distinct non-null stored values with the locked enum inventory in this plan.

Required rule:

```text
stored value is in canonical enum -> compatible
stored value is not in canonical enum -> STOP
```

On an unknown value, do **not**:

- silently pass it through the adapter;
- add it to the enum just to make the check pass;
- rewrite the row automatically;
- add an unplanned migration.

Instead, determine whether it is a legitimate historical lifecycle value, bad/test data, or evidence that the locked inventory is incomplete. Resolve that explicitly before committing Step 1.

A fresh migration test database is still required, but it is not a substitute for this gate because it only proves compatibility with migration seeds/current fixtures, not with already persisted environments.

`EntrypointSession.region_mismatch_status` and `Order.region_mismatch_status` are excluded from this enum-data gate because they remain strings in ANY-326.

## Single-value enum policy

A one-member enum is **not** justified merely because the current default, seed or test data contains only one value.

A single-value enum is allowed in ANY-326 only when all of the following are true:

1. the field is owned by Payment Portal's persisted model contract rather than by an external provider, resolver, configuration source or open identifier namespace;
2. runtime/model semantics treat it as a closed category, even if only one state is implemented today;
3. adding another value later is expected to be an explicit model-contract change, not arbitrary new configuration data;
4. the enum does not invent a future lifecycle transition or behavior.

Under that rule, this plan keeps the following currently single-value model vocabularies as closed enums:

```text
BundleProductStatus.ACTIVE
PlanPriceComponentType.PRODUCT_PLAN
PlanLimitResetPolicy.BILLING_PERIOD
PlanLimitOveragePolicy.DENY
RegionStatus.ACTIVE
UserStatus.ACTIVE
LegalEntityStatus.ACTIVE
MagicLinkPurpose.PASSWORD_RESET
```

Their one-member shape means "this is the complete model vocabulary implemented and accepted by ANY-326 today", **not** "other states can never exist". A later real state must expand the canonical enum and its tests explicitly.

By contrast, `EntrypointSession.region_mismatch_status` and `Order.region_mismatch_status` stay strings because their meaning belongs to an incompletely defined routing/mismatch contract; observing only `none` is not enough to declare that external-facing diagnostic vocabulary closed.

Do not generalize this policy into "every string with a default becomes an enum".

## Canonical naming and public-schema compatibility

Keep the existing enum class names:

```text
SubscriptionScopeType
SubscriptionRenewalMode
```

as the canonical persisted model types in ANY-326, even though they are shared by more than `Subscription`:

```text
SubscriptionScopeType:
Plan
Subscription
Entitlement

SubscriptionRenewalMode:
Plan
Subscription
```

The historical `Subscription*` prefix is not ideal for the model vocabulary, but both names are already exposed as OpenAPI schema components. Renaming them to neutral Python class names in this ticket would create an unnecessary public-contract diff or require a second transport enum solely to preserve schema identity.

Therefore the locked decision for ANY-326 is:

- move these enum definitions into `app.models` and make them canonical there;
- reuse the same canonical classes for Plan / Subscription / Entitlement ORM fields;
- preserve the public OpenAPI component names `SubscriptionScopeType` and `SubscriptionRenewalMode`;
- do not introduce `AccessScopeType` or a second generic renewal enum in this ticket;
- defer any cosmetic neutral rename to a separate explicitly API-compatible change if it is still desired later.

`all_access` remains a member of `SubscriptionScopeType`.

It is internal persisted access-scope vocabulary.

It is **not**:

- a checkout purchase ID;
- a substitute for `Plan.id`;
- the removed synthetic checkout selector `all-access`.

The ANY-327 checkout decision remains unchanged:

```text
frontend selects catalog product
-> frontend submits exact Plan.id
-> backend resolves Plan
-> Plan determines product / bundle / all_access scope
```

## Public API and OpenAPI compatibility

ANY-326 is a model/persistence-source refactor, not an API-contract change.

The following are acceptance constraints, not best-effort goals:

- serialized JSON values and field names remain unchanged;
- existing OpenAPI component names remain unchanged unless a separate already-approved contract change requires otherwise;
- in particular, `SubscriptionScopeType` and `SubscriptionRenewalMode` must remain the generated schema names;
- moving an enum from `app.domains.billing.enums` to `app.models` must not by itself change `$ref` targets in `docs/generated/openapi.json`;
- `npm run generate:check` is a required manual gate for every step that can affect Pydantic/OpenAPI generation.

If a proposed internal type cleanup changes generated OpenAPI while wire values stay the same, treat that as a regression for ANY-326 and keep the existing public type identity instead of updating the generated contract.

## Canonical persisted enum inventory

The implementation must use the following model-layer ownership.

### Catalog

```text
Product.status
    -> ProductStatus
       active
       inactive

Bundle.status
    -> BundleStatus
       active
       inactive

BundleProduct.status
    -> BundleProductStatus
       active

Plan.status
    -> PlanStatus
       active
       inactive

Plan.scope_type
    -> SubscriptionScopeType
       product
       bundle
       all_access

Plan.billing_period
    -> BillingPeriod
       day
       days
       week
       weeks
       month
       months
       year
       years
       annual
       yearly

Plan.renewal_mode
    -> SubscriptionRenewalMode
       manual
       automatic

PlanPriceComponent.component_type
    -> PlanPriceComponentType
       product_plan

PlanLimit.period
    -> BillingPeriod

PlanLimit.reset_policy
    -> PlanLimitResetPolicy
       billing_period

PlanLimit.overage_policy
    -> PlanLimitOveragePolicy
       deny
```

Do not invent additional Bundle, BundleProduct, component, reset or overage states. The enum can be expanded later when a real persisted value is introduced.

### Commerce

```text
EntrypointSession.region_mismatch_status
Order.region_mismatch_status
    -> keep as string in ANY-326
       current default/value observed: none

CheckoutSession.status
    -> CheckoutSessionStatus
       created
       order_created

Order.status
    -> OrderStatus
       created
       requires_consents
       pending_payment
       paid
       payment_failed
       canceled
       expired
       refunded
       partially_refunded
       region_mismatch

OrderItem.item_type
    -> OrderItemType
       product_plan
       bundle_plan
       all_access_plan

Payment.status
    -> PaymentStatus
       created
       requires_action
       authorized
       captured
       succeeded
       failed
       canceled
       refunded
       partially_refunded
       disputed

Refund.status
    -> RefundStatus
       requested
       succeeded
```

`region_mismatch_status` is **not** converted to an enum in ANY-326. The current schema/runtime only confirms the default/value `none`, while the Region Resolver contract is not yet mature enough to establish a complete closed local vocabulary. A one-member enum would encode an assumption rather than an invariant. Keep both fields as `Mapped[str]` until a later ticket introduces and documents a real closed state set.

Do not confuse these fields with `OrderStatus.REGION_MISMATCH`: order lifecycle status and region-mismatch diagnostic/routing state are different concepts.

`CheckoutSession` currently behaves as a write-once checkout record and checkout creates it with `order_created`. Do not introduce a new lifecycle.

`OrderStatus` and `PaymentStatus` intentionally contain documented local model states that the current RU CloudPayments path does not yet emit. Do not add transitions for those states in this ticket.

### Payment method

Keep:

```python
Payment.payment_method_type: Mapped[str | None]
```

It is currently populated directly from a payment-provider payload and there is no canonical provider-neutral Payment Portal vocabulary for it.

Do **not** create `PaymentMethodType` as part of ANY-326.

### Webhook inbox

```text
PaymentWebhookEvent.status
    -> PaymentWebhookEventStatus
       received
       processing
       processed
       ignored
       duplicate
       failed
```

Do not reuse provider webhook/event values for this enum.

### Subscription and entitlement

```text
Subscription.status
    -> SubscriptionStatus
       trialing
       active
       past_due
       canceled
       expired
       refunded
       paused

Subscription.scope_type
    -> SubscriptionScopeType

Subscription.renewal_mode
    -> SubscriptionRenewalMode

Entitlement.status
    -> EntitlementStatus
       active
       expired
       revoked
       superseded

Entitlement.source
    -> EntitlementSource
       trial
       order

Entitlement.scope_type
    -> SubscriptionScopeType

SubscriptionEvent.event_type
    -> SubscriptionEventType
       trial_started
       paid_period_activated
       subscription_replaced
       automatic_renewal_enabled
       renewal_succeeded
       renewal_failed
       provider_subscription_state_applied
       cancellation_requested
       refund_applied
       partial_refund_applied
       subscription_expired

SubscriptionEvent.previous_status
SubscriptionEvent.next_status
    -> SubscriptionStatus | None
```

### Identity and legal

```text
Region.status
    -> RegionStatus
       active

User.status
    -> UserStatus
       active

MagicLinkToken.purpose
    -> MagicLinkPurpose
       password_reset

LegalEntity.status
    -> LegalEntityStatus
       active

LegalEntity.entity_type
    -> LegalEntityType
       individual_entrepreneur
       merchant_of_record
       company

DocumentAcceptance.acceptance_kind
    -> AcceptanceKind
       privacy_consent
       terms_acceptance
       recurring_consent
       cookies
```

Do not invent additional inactive/disabled identity or legal states in this ticket.

### Intentionally remaining strings

Do not turn these into persisted enums in ANY-326:

```text
provider code
region code
currency
provider/external IDs
Product.code
Bundle.code
Plan.code
DocumentVersion.doc_type
DocumentAcceptance.doc_type
entrypoint_type
entrypoint_value
EntrypointSession.region_mismatch_status
Order.region_mismatch_status
metadata keys/values
Payment.payment_method_type
```

These are open/configuration/provider vocabularies or identifiers rather than a confirmed closed model lifecycle.

## Provider boundary remains separate

Do not merge local persisted statuses with provider contract statuses.

In particular:

```text
app.models.RefundStatus
```

describes the persisted local `Refund` row.

The payment-provider contract's current `RefundStatus` describes an operation result and includes provider-boundary states such as:

```text
pending
failed
unknown
```

Rename that provider-contract enum to:

```text
ProviderRefundStatus
```

when migrating its usages in Step 4.

Do not add provider `pending` or `unknown` to local `app.models.RefundStatus`.

Existing provider `TransactionStatus` and `RecurringSubscriptionStatus` do not need unrelated renaming in this ticket.

## Non-persisted billing enums

The following existing enums are not persisted model vocabularies and must **not** be moved into `app.models` merely because they currently share `app.domains.billing.enums`:

```text
ProviderSubscriptionState
SensitiveMetadataKey
ProductAccessStatus
```

Keep them in their current owning layer unless a tiny import adjustment is required by the enum split.

Do not redesign these concepts in ANY-326.

## Migration strategy

The ticket is implemented in five commits:

```text
1. canonical persisted enum definitions + ORM typing
2. catalog / checkout / identity / legal consumers
3. subscription / entitlement consumers
4. payment / refund / webhook consumers
5. remove compatibility façades and document final contract
```

Step 1 may temporarily leave compatibility aliases in the old enum modules so later steps can be committed independently.

These aliases must reference the canonical classes directly from `app.models.enums`; they must not duplicate enum definitions. Runtime consumers outside the model/compatibility modules migrate to the public `app.models` exports in Steps 2–4.

All compatibility aliases must be removed in Step 5.

## Out of Scope for ANY-326

Do not:

- create domain entity classes;
- introduce repositories or units of work;
- move checkout logic out of the identity router;
- move payment/refund transitions out of CloudPayments integration;
- redesign payment, refund, subscription or entitlement state machines;
- change webhook routes, signatures, response bodies or idempotency behavior;
- change checkout request/response contracts;
- change purchase identity from `Plan.id`;
- remove `all_access` access scope;
- implement a synthetic `all-access` purchase selector;
- introduce payment-method normalization;
- implement another contour;
- implement future Platform Kernel access APIs;
- edit historical Alembic revisions;
- introduce PostgreSQL ENUM;
- remove unrelated compatibility modules;
- refactor files merely because they are large.

---

# Step 1 — Create the canonical persisted enum layer and type the ORM

**Status:** `done`  
**Commit:** `refactor(models): centralize persisted enum contracts`

## Prompt

Implement Step 1 of ANY-326: establish `app.models` as the canonical owner of persisted enum vocabularies and make enum-backed SQLAlchemy fields return typed `StrEnum` values while preserving the current TEXT/VARCHAR database schema.

Implement only this foundation step. Do not migrate all runtime consumers yet.

## Goal

After this step:

```text
app/models/enums.py
```

is the only source of truth for persisted enum definitions.

SQLAlchemy model attributes representing confirmed closed persisted vocabularies are typed as enum members rather than plain strings.

Database storage remains exactly string-based.

Existing runtime modules that still import the old billing/legal enum locations must continue to work temporarily through aliases to the same canonical classes.

## Relevant Existing Code

Work primarily in:

```text
apps/api/app/models/enums.py                 # new
apps/api/app/models/_shared.py
apps/api/app/models/__init__.py
apps/api/app/models/catalog.py
apps/api/app/models/commerce.py
apps/api/app/models/identity.py
apps/api/app/models/legal.py
apps/api/app/models/subscriptions.py
apps/api/app/models/webhooks.py
apps/api/app/domains/billing/enums.py
apps/api/app/domains/legal/enums.py
apps/api/tests/test_model_enums.py           # new focused test module
docs/generated/openapi.json                      # verification baseline only; do not edit manually
```

Do not edit historical Alembic revisions.

## Implementation

### 1. Create `app/models/enums.py`

Define the canonical enums from the locked inventory in this plan.

Use `enum.StrEnum`.

Move the existing persisted enum behavior as well, including:

```python
SubscriptionStatus.is_live
SubscriptionStatus.live_values()
```

Do not change the meaning of live subscription states.

Use the canonical names:

```python
SubscriptionScopeType
SubscriptionRenewalMode
PaymentWebhookEventStatus
```

`SubscriptionScopeType` and `SubscriptionRenewalMode` deliberately keep their existing public class names for OpenAPI compatibility. They are still moved into `app.models` and become the single persisted source of truth there.

Do not keep an independent canonical model definition named:

```python
WebhookEventStatus
```

Use `PaymentWebhookEventStatus` for the persisted webhook-inbox model state.

Do not introduce `AccessScopeType` or a second generic renewal enum in ANY-326.

### 2. Introduce one shared SQLAlchemy text-enum adapter

Implement one reusable adapter in the model infrastructure, preferably in:

```text
app/models/_shared.py
```

Use a name such as:

```python
PersistedEnumType
```

The implementation must:

- use SQLAlchemy `Text` as its physical implementation;
- accept one concrete `StrEnum` class when instantiated;
- return `None` unchanged for nullable columns;
- accept an enum member on bind and store its `.value`;
- temporarily accept a raw `str` on bind in Steps 1–4, validate it by constructing the configured enum, and persist the resulting `.value`;
- make that raw-string acceptance easy to remove in Step 5 without changing physical storage or read semantics;
- reconstruct and return the configured enum member when a value is read from the database;
- fail rather than silently pass through an unknown persisted value;
- be SQLAlchemy-cache-safe if implemented as `TypeDecorator`;
- not introduce native `sqlalchemy.Enum`;
- not produce a PostgreSQL native ENUM.

Do not introduce one adapter per enum.

This compatibility is intentionally asymmetric across the plan lifecycle: Step 1 tests must prove valid raw strings still bind so the staged migration is safe; Step 5 tests must replace that assertion and prove plain strings are rejected by the final contract.

### 3. Type all confirmed enum-backed model fields

Use the locked inventory from this plan.

Representative target shape:

```python
status: Mapped[PaymentStatus] = mapped_column(
    PersistedEnumType(PaymentStatus),
    nullable=False,
    default=PaymentStatus.CREATED,
)
```

Nullable example:

```python
previous_status: Mapped[SubscriptionStatus | None]
```

Model defaults should become enum members rather than `.value` strings where the field is enum-backed.

For example:

```python
default=PaymentStatus.CREATED
```

not:

```python
default="created"
```

and not:

```python
default=PaymentStatus.CREATED.value
```

The SQL adapter owns conversion to the stored string.

### 4. Preserve SQL constraints and partial-index behavior

Existing `CheckConstraint` and partial-index SQL must continue to use the same persisted string values.

Where a Python-generated SQL predicate already uses enum values, derive it from canonical enums.

For example, continue generating live-subscription predicates from:

```python
SubscriptionStatus.live_values()
```

Do not alter names or semantics of existing constraints/indexes.

Do not add new database constraints merely to mirror every Python enum in this ticket.

### 5. Export models and enums through `app.models`

Update:

```text
app/models/__init__.py
```

so callers outside the model package can write:

```python
from app.models import Order, OrderStatus, Payment, PaymentStatus
```

and similarly for all canonical persisted enums.

Inside `app.models` itself, ORM modules must import enum definitions directly from `app.models.enums` (or `.enums`), not from `app.models.__init__`. Keep enum definitions independent from ORM model imports so the public export layer does not create circular dependencies.

`app.models._shared` may expose the common `PersistedEnumType` and SQL helpers, but canonical enum ownership remains physically in `app.models.enums`; do not use `_shared.py` as the long-term enum import source.

### 6. Add temporary compatibility aliases

Until Steps 2–4 migrate runtime imports, existing imports must continue to work.

In:

```text
app/domains/billing/enums.py
```

keep only the actual definitions of non-persisted billing enums:

```text
ProviderSubscriptionState
SensitiveMetadataKey
ProductAccessStatus
```

For persisted enums still imported by runtime code, temporarily alias/import the canonical model-layer class rather than redefining it.

Examples:

```text
WebhookEventStatus -> PaymentWebhookEventStatus
```

Unchanged-name persisted enums such as:

```text
SubscriptionScopeType
SubscriptionRenewalMode
PaymentStatus
SubscriptionStatus
```

should be imported/re-exported directly from `app.models.enums` rather than redefined as second enum classes. Keeping the same Python class names also preserves the existing OpenAPI schema identity for the subscription scope/renewal types. Runtime consumers outside these compatibility modules should still migrate to the public `app.models` exports in later steps.

Apply the same transitional rule to:

```text
app/domains/legal/enums.py
```

for `AcceptanceKind`.

These compatibility imports are temporary and are removed in Step 5.

### 7. Preserve public OpenAPI schema identity

Do not use the enum move as a reason to rename Pydantic/OpenAPI schema components.

The generated OpenAPI must continue to expose:

```text
SubscriptionScopeType
SubscriptionRenewalMode
```

with the same enum values as before.

Because the canonical model classes keep those names, public Pydantic response models may use the canonical classes directly where they already used the same logical type. Do not introduce a second transport enum merely for style.

If any other annotation/import change unexpectedly changes `docs/generated/openapi.json`, revert the public type-identity change rather than accepting an unrelated contract diff.

### 8. Add focused model enum tests

Create a focused test module for the model-layer contract.

Cover at least:

1. critical canonical value sets:
   - `OrderStatus`;
   - `PaymentStatus`;
   - `PaymentWebhookEventStatus`;
   - `CheckoutSessionStatus`;
   - `RefundStatus`;
   - `SubscriptionScopeType`;
   - `SubscriptionRenewalMode`;

2. representative ORM enum round trips:
   - assigning an enum member persists successfully;
   - loading the row returns the expected enum member;
   - valid raw strings still bind during the staged migration;
   - an invalid raw string is rejected;

3. representative nullable enum round trip for `SubscriptionEvent.previous_status` / `next_status`;

4. enum-backed columns continue to use text storage rather than SQLAlchemy/PostgreSQL native enum types;

5. old compatibility imports, while they still exist in Step 1, reference the **same class object** as the canonical `app.models` enum rather than a duplicate enum definition;
6. `EntrypointSession.region_mismatch_status` and `Order.region_mismatch_status` remain plain string-backed ORM attributes;
7. public enum class names used by OpenAPI remain `SubscriptionScopeType` and `SubscriptionRenewalMode`.

Do not write tests that depend on a new state transition.

## Scope Constraints

Do not:

- migrate services/integrations/routers wholesale yet;
- change checkout behavior;
- change subscription behavior;
- change payment/refund behavior;
- change provider contracts;
- change API response values;
- add migrations;
- edit Alembic history;
- introduce new state values beyond the locked inventory;
- remove `app/domains/billing/models.py` yet;
- remove compatibility aliases required by later steps.

## Automated Checks

Do NOT run:

```text
pytest
tests
linters
formatters
type checkers
generators
npm run check
npm run check:fast
npm run test:api:fast
npm run architecture:check
or any other automated verification command
```

Do not automatically reformat unrelated files.

Do not create a git commit.

## After Implementation

Report:

1. every file changed;
2. every canonical enum created;
3. which fields are now ORM enum-backed;
4. the SQLAlchemy adapter behavior;
5. confirmation that physical database storage is still `TEXT` / `VARCHAR`;
6. confirmation that no Alembic migration was added;
7. confirmation that both `region_mismatch_status` fields intentionally remain strings;
8. a table of every enum-backed `table.column` and its allowed values for the read-only existing-data compatibility gate;
9. confirmation that public OpenAPI enum names were not intentionally changed;
10. the exact checks I should run manually.

Before accepting the Step 1 commit, run the read-only existing-data compatibility gate against every existing environment/database that will be upgraded and is available to you. For every Step-1 enum-backed column, inspect all distinct non-null stored values and compare them with the locked inventory. Any unknown value blocks the commit until investigated.

Then run these checks manually, but do not run them yourself:

```bash
pytest apps/api/tests/test_model_enums.py
npm run generate:check
npm run test:api:fast
npm run architecture:check
```

For PostgreSQL verification before accepting this foundation commit:

```bash
make test_db_up
pytest apps/api/tests/test_alembic_postgres.py
make test_db_stop
```

## Commit

Final commit name:

```text
refactor(models): centralize persisted enum contracts
```

Status:

```text
todo
```

---

# Step 2 — Migrate catalog, checkout, identity and legal consumers

**Status:** `done`  
**Commit:** `refactor(models): migrate catalog identity and legal vocabularies`  
**Depends on:** Step 1 completed, manually verified, and committed.

## Prompt

Implement Step 2 of ANY-326: migrate catalog, checkout, identity and legal runtime code to the canonical persisted enums exported by `app.models`.

Step 1 is already complete. Do not modify subscription lifecycle or CloudPayments payment/refund processing in this step.

## Goal

Remove raw persisted model literals and old persisted-enum imports from the catalog, checkout, identity and legal slices without changing any API or business behavior.

## Relevant Existing Code

Work primarily in:

```text
apps/api/app/domains/billing/catalog.py
apps/api/app/domains/identity/router.py
apps/api/app/domains/identity/services/checkout.py
apps/api/app/domains/identity/password_reset.py
apps/api/app/domains/legal/service.py
apps/api/app/domains/legal/router.py
apps/api/app/infrastructure/queries/products.py
apps/api/app/infrastructure/queries/plans.py
apps/api/tests/test_api.py
```

Also update directly related factories/helpers if they currently construct these ORM fields with raw closed values.

Do not perform broad architectural investigation.

## Implementation

### 1. Use canonical model imports

Persisted model enums in this slice must be imported from:

```python
from app.models import ...
```

Do not import persisted enum classes from:

```text
app.domains.billing.enums
app.domains.legal.enums
```

Non-persisted billing enums may continue to come from their current domain module if required.

### 2. Migrate catalog queries and responses

Update catalog-related code to use:

```text
ProductStatus
BundleStatus
BundleProductStatus
PlanStatus
SubscriptionScopeType
BillingPeriod
SubscriptionRenewalMode
```

Queries such as:

```python
Product.status == ProductStatus.ACTIVE.value
```

should become:

```python
Product.status == ProductStatus.ACTIVE
```

because the column is now enum-backed.

Do the same for Plan and Bundle/BundleProduct filters.

Pydantic response models may directly use the canonical `StrEnum` types where the response already emits the same string value **and the generated OpenAPI schema identity remains unchanged**.

For subscription scope/renewal types, the canonical classes deliberately retain the public names `SubscriptionScopeType` and `SubscriptionRenewalMode`.

Do not alter serialized JSON, `$ref` targets, schema component names, or response fields as an incidental result of the model-layer move.

### 3. Migrate checkout plan resolution

In:

```text
app/domains/identity/services/checkout.py
```

use:

```text
SubscriptionScopeType
ProductStatus
BundleStatus
BillingPeriod
SubscriptionRenewalMode
```

from `app.models`.

`ResolvedCheckoutPlan` should carry canonical types for closed values where practical.

Do not wrap an ORM enum in its own enum constructor without need.

For example, if:

```python
plan.scope_type
```

is already `SubscriptionScopeType`, use it directly.

Preserve all existing validation:

```text
product scope -> product_id required, bundle_id absent
bundle scope -> bundle_id required, product_id absent
all_access -> both absent
```

Do not create or infer a Product/Bundle for `all_access`.

### 4. Migrate checkout persistence in the identity router

Replace model-state raw values with canonical enum members.

Use:

```text
CheckoutSessionStatus.ORDER_CREATED
OrderStatus.PENDING_PAYMENT
```

for checkout creation.

Use the closed `OrderItemType` vocabulary rather than:

```python
f"{scope_type.value}_plan"
```

Build an explicit mapping:

```text
SubscriptionScopeType.PRODUCT    -> OrderItemType.PRODUCT_PLAN
SubscriptionScopeType.BUNDLE     -> OrderItemType.BUNDLE_PLAN
SubscriptionScopeType.ALL_ACCESS -> OrderItemType.ALL_ACCESS_PLAN
```

Do not make arbitrary strings from enum values.

For payment-status presentation, compare with `OrderItemType.ALL_ACCESS_PLAN` rather than a raw item type.

Preserve the existing payment-result compatibility behavior, including any existing `all-access` presentation value. ANY-326 is not the ticket that redesigns that API.

### 5. Preserve Plan.id checkout authority

Do not modify:

```text
CheckoutIntentRequest.plan_id
Plan resolution
recurring consent Plan.id binding
Order.plan_id
OrderItem.plan_id
checkout purchase response
```

`SubscriptionScopeType.ALL_ACCESS` describes resolved access scope only.

### 6. Migrate identity values

Use:

```text
UserStatus.ACTIVE
MagicLinkPurpose.PASSWORD_RESET
```

instead of raw persisted strings in identity/password-reset code.

Do not alter password reset HTTP behavior, throttling, token TTLs, email behavior, or session invalidation.

### 7. Migrate legal acceptance values

Use canonical:

```text
AcceptanceKind
LegalEntityStatus
LegalEntityType
```

where the ORM persisted values are created, compared or queried.

`ACCEPTANCE_KIND_BY_DOC_TYPE` should map to `AcceptanceKind` members rather than `.value` strings where those values flow directly into the enum-backed ORM field.

Preserve:

```text
privacy -> privacy_consent
pd_consent -> privacy_consent
offer -> terms_acceptance
recurring_consent -> recurring_consent
cookies -> cookies
```

Do not redesign document-type handling.

`DocumentVersion.doc_type` and `DocumentAcceptance.doc_type` remain strings.

Do not change the ANY-379 recurring-consent validation semantics.

### 8. Update tests and factories in this slice

Replace raw model vocabulary in affected setup code and assertions with canonical enum members where the value represents an ORM closed vocabulary.

Do not replace ordinary HTTP/JSON string assertions just for style.

For example, the public response:

```json
{"status": "active"}
```

must remain `"active"`.

Tests should confirm that API serialization is unchanged even though ORM attributes are now typed enum members.

## Scope Constraints

Do not:

- touch subscription state transitions;
- touch entitlement lifecycle behavior;
- touch CloudPayments processing/refunds;
- rename provider contract enums yet;
- change payment webhook handling;
- refactor checkout into another layer;
- change legal-document lifecycle;
- change public JSON;
- add migrations;
- delete the compatibility aliases from Step 1 yet.

## Automated Checks

Do NOT run tests, linters, formatters, type checkers, generators or other automated verification.

Do not create a git commit.

## After Implementation

Report:

1. files changed;
2. old persisted-enum imports removed from this slice;
3. raw model literals replaced;
4. confirmation that checkout still purchases by exact `Plan.id`;
5. confirmation that `all_access` remains internal scope;
6. confirmation that HTTP/Pydantic serialization did not change;
7. exact manual checks.

Tell me to run:

```bash
pytest apps/api/tests/test_api.py -k "catalog or checkout or password_reset or legal or payment_status"
npm run generate:check
npm run architecture:check
```

## Commit

Final commit name:

```text
refactor(models): migrate catalog identity and legal vocabularies
```

Status:

```text
todo
```

---

# Step 3 — Migrate subscription and entitlement lifecycle consumers

**Status:** `done`  
**Commit:** `refactor(billing): use canonical subscription model enums`  
**Depends on:** Steps 1–2 completed, manually verified, and committed.

## Prompt

Implement Step 3 of ANY-326: migrate subscription, entitlement and subscription-event runtime code to the canonical persisted enum types exported by `app.models`.

Do not change lifecycle semantics.

## Goal

The billing lifecycle and subscription query layer should operate on typed model values rather than strings or persisted enums owned by `app.domains.billing.enums`.

Provider state and persisted subscription state must remain separate concepts.

## Relevant Existing Code

Work primarily in:

```text
apps/api/app/domains/billing/router.py
apps/api/app/domains/billing/service/state_machine.py
apps/api/app/domains/billing/service/lifecycle.py
apps/api/app/domains/billing/service/lifecycle_operations.py
apps/api/app/domains/billing/service/commands.py
apps/api/app/infrastructure/queries/subscriptions.py
apps/api/tests/test_billing_lifecycle.py
apps/api/tests/test_billing_lifecycle_concurrency_postgres.py
```

Update another billing service/query file only when it directly consumes one of the persisted subscription/entitlement enum values defined in this plan.

## Implementation

### 1. Import persisted values through `app.models`

Use:

```text
SubscriptionScopeType
SubscriptionRenewalMode
SubscriptionStatus
EntitlementStatus
EntitlementSource
SubscriptionEventType
```

from `app.models`.

Do not import these persisted types from `app.domains.billing.enums`.

### 2. Keep provider state separate

`ProviderSubscriptionState` is not a persisted model enum.

It may remain in:

```text
app.domains.billing.enums
```

The state machine remains an explicit translation:

```text
ProviderSubscriptionState
        ↓ mapping
SubscriptionStatus
```

Do not collapse the two enum types.

Do not add provider-only values to `SubscriptionStatus`.

### 3. Type the local state machine

Where the code is processing local subscription state, prefer:

```python
SubscriptionStatus
```

rather than `str`.

For example, update transition helpers so the current and next local state are canonical model types whenever they originate from a `Subscription`.

Do not alter the allowed transition graph.

The existing transitions must remain identical.

### 4. Remove `.value` at ORM boundaries

When assigning or comparing enum-backed ORM fields, use enum members.

Replace shapes like:

```python
subscription.status = SubscriptionStatus.ACTIVE.value
subscription.status == SubscriptionStatus.ACTIVE.value
```

with:

```python
subscription.status = SubscriptionStatus.ACTIVE
subscription.status == SubscriptionStatus.ACTIVE
```

Apply the same rule to:

```text
renewal_mode
scope_type
entitlement.status
entitlement.source
subscription event type
previous_status
next_status
```

Do not mechanically remove `.value` where a real external string is required, such as:

- provider DTO;
- metadata snapshot;
- explicit SQL string;
- external API payload.

### 5. Type subscription and entitlement query contracts

Where an infrastructure query parameter represents a local closed persisted scope/status, type it with the appropriate canonical enum instead of an unconstrained `str`.

Examples include scope-aware subscription/entitlement lookup helpers.

Do not change:

```text
tenant_id
region
provider IDs
operation idempotency keys
```

to enums.

### 6. Preserve SQLAlchemy query behavior

Use enum members directly in filters:

```python
Entitlement.status == EntitlementStatus.ACTIVE
```

and enum collections in `.in_(...)`.

Do not convert members to values unless constructing unavoidable textual SQL.

### 7. Keep account API JSON stable

Billing account Pydantic responses may use the canonical enum classes directly.

They must preserve both wire values **and existing generated schema identity**. In particular, scope and renewal fields must continue to reference the public OpenAPI components `SubscriptionScopeType` and `SubscriptionRenewalMode`.

They must still serialize as the existing strings:

```text
active
manual
product
...
```

Do not rename JSON fields or alter nesting.

### 8. Preserve lifecycle invariants

Do not modify:

- trial creation rules;
- paid-period activation;
- entitlement superseding;
- recurring consent;
- automatic-renewal enablement;
- cancellation;
- provider-state application;
- refund lifecycle;
- expiration;
- operation idempotency;
- row locking;
- concurrency behavior.

This step is a type/source-of-truth migration only.

### 9. Update focused tests

Update model construction and ORM assertions to use canonical enum members.

Keep HTTP/serialized payload assertions as strings where they are testing the external contract.

Do not weaken state-transition tests merely to make the enum migration pass.

## Scope Constraints

Do not:

- redesign the state machine;
- change any accepted transition;
- change idempotency keys;
- change row locking;
- modify CloudPayments provider mapping beyond import/type adjustments strictly required here;
- implement ANY-168 or another provider subscription flow;
- touch refund implementation;
- add migrations;
- introduce a domain entity layer.

## Automated Checks

Do NOT run automated tests or checks.

Do not create a git commit.

## After Implementation

Report:

1. files changed;
2. persisted enum imports migrated;
3. lifecycle assignments/comparisons converted;
4. query signatures converted from `str` where appropriate;
5. confirmation that the provider/local status mapping remains explicit;
6. confirmation that the transition graph did not change;
7. exact checks I should run manually.

Tell me to run:

```bash
pytest apps/api/tests/test_billing_lifecycle.py
pytest apps/api/tests/test_api.py -k "account_subscription"
npm run generate:check
npm run architecture:check
```

For the PostgreSQL concurrency-sensitive path:

```bash
make test_db_up
pytest apps/api/tests/test_billing_lifecycle_concurrency_postgres.py
make test_db_stop
```

## Commit

Final commit name:

```text
refactor(billing): use canonical subscription model enums
```

Status:

```text
todo
```

---

# Step 4 — Migrate payment, refund and webhook processing

**Status:** `done`  
**Commit:** `refactor(payments): use canonical commerce model enums`  
**Depends on:** Steps 1–3 completed, manually verified, and committed.

## Prompt

Implement Step 4 of ANY-326: migrate payment/order/refund/webhook processing to the canonical persisted model enums without changing CloudPayments or payment-provider behavior.

Keep local persisted model statuses strictly separate from provider operation statuses.

## Goal

All runtime code that mutates or compares:

```text
Order.status
Payment.status
Refund.status
PaymentWebhookEvent.status
```

must use canonical `app.models` enum members.

CloudPayments-specific/provider-specific strings remain at the external adapter boundary.

## Relevant Existing Code

Work primarily in:

```text
apps/api/app/integrations/cloudpayments/processing.py
apps/api/app/integrations/cloudpayments/refunds.py
apps/api/app/payment_providers/contracts.py
apps/api/tests/test_api.py
apps/api/tests/test_cloudpayments_adapter_api.py
apps/api/tests/test_cloudpayments_webhook_postgres.py
```

Update other CloudPayments/provider modules only if they directly import the provider `RefundStatus` being renamed or compare/assign one of the local model states above.

Do not redesign the integration.

## Implementation

### 1. Use canonical local model enums

Import from `app.models`:

```text
OrderStatus
PaymentStatus
RefundStatus
PaymentWebhookEventStatus
```

Replace local persisted strings such as:

```text
created
authorized
succeeded
failed
canceled
paid
payment_failed
partially_refunded
refunded
received
processing
processed
ignored
duplicate
```

with the matching model enum member whenever the value is assigned to or compared with an enum-backed ORM field.

### 2. Type terminal-state collections

Replace string collections such as:

```python
TERMINAL_ORDER_STATUSES = {...}
TERMINAL_PAYMENT_STATUSES = {...}
CAPTURED_PAYMENT_STATUSES = {...}
```

with collections of canonical local enum members.

Keep exactly the same membership.

Do not add newly documented-but-currently-unused states to these runtime sets unless they were already part of the current business rule.

The canonical enum being broader than a particular runtime terminal set does **not** mean every enum value belongs in that set.

### 3. Preserve CloudPayments provider input as provider data

Values obtained from provider payload fields such as:

```text
Status
PaymentMethod
ReasonCode
endpoint
```

remain provider-boundary values until explicitly mapped.

The existing provider-status normalization logic may continue to normalize a provider string before choosing a local enum state.

Do not make the CloudPayments payload deserialize directly into local ORM enums.

### 4. Keep `Payment.payment_method_type` as string

The current code assigns the provider payload's:

```text
PaymentMethod
```

directly to:

```python
Payment.payment_method_type
```

Keep the model field and runtime value as:

```python
str | None
```

Do not introduce a local `PaymentMethodType`.

Do not change the provider payload or normalization contract.

### 5. Separate provider refund result from local Refund row

Rename the payment-provider contract enum:

```text
RefundStatus
```

to:

```text
ProviderRefundStatus
```

Update all direct imports/usages of that provider-contract type.

The provider refund operation continues to use values such as:

```text
PENDING
FAILED
UNKNOWN
...
```

The local ORM:

```text
app.models.RefundStatus
```

contains only the currently persisted local values:

```text
REQUESTED
SUCCEEDED
```

When a verified refund webhook creates a local `Refund` row, use:

```python
RefundStatus.SUCCEEDED
```

Do not map provider `PENDING` into the local persisted row unless existing behavior already persists such a row. Current behavior must remain unchanged.

### 6. Preserve payment/order transition semantics exactly

The RU CloudPayments implementation must continue to behave exactly as before:

```text
pay + authorized
    -> PaymentStatus.AUTHORIZED

pay / confirm success
    -> PaymentStatus.SUCCEEDED
    -> OrderStatus.PAID

fail
    -> PaymentStatus.FAILED
    -> OrderStatus.PAYMENT_FAILED where current rules permit it

cancel
    -> PaymentStatus.CANCELED
    -> OrderStatus.CANCELED where current rules permit it

refund
    -> RefundStatus.SUCCEEDED
    -> PaymentStatus.REFUNDED or PARTIALLY_REFUNDED
    -> OrderStatus.REFUNDED or PARTIALLY_REFUNDED
```

Do not start using currently documented but inactive states such as:

```text
PaymentStatus.REQUIRES_ACTION
PaymentStatus.CAPTURED
PaymentStatus.DISPUTED
OrderStatus.REQUIRES_CONSENTS
OrderStatus.EXPIRED
OrderStatus.REGION_MISMATCH
```

unless existing runtime already does so.

### 7. Preserve webhook inbox semantics

Use:

```text
PaymentWebhookEventStatus.RECEIVED
PaymentWebhookEventStatus.PROCESSING
PaymentWebhookEventStatus.PROCESSED
PaymentWebhookEventStatus.IGNORED
PaymentWebhookEventStatus.DUPLICATE
PaymentWebhookEventStatus.FAILED
```

for ORM state.

Do not change:

- webhook idempotency key calculation;
- duplicate detection;
- signature verification;
- redaction;
- endpoint routing;
- CloudPayments HTTP response codes;
- rollback/recovery behavior.

### 8. Update payment/provider tests

Update test setup and direct ORM assertions to canonical model/provider enums.

Keep HTTP and provider DTO serialization assertions unchanged.

Add/retain a focused assertion proving the two refund concepts are different enum classes:

```text
app.models.RefundStatus
ProviderRefundStatus
```

Do not weaken payment lifecycle tests.

## Scope Constraints

Do not:

- redesign payment lifecycle;
- move processing into another domain/service;
- change webhook contracts;
- change provider adapter signatures except the internal enum type rename;
- normalize payment method types;
- change refund timing;
- add provider retry behavior;
- change subscription activation behavior;
- alter CloudPayments security checks;
- add migrations.

## Automated Checks

Do NOT run tests, linters, formatters, generators or any automated validation command.

Do not create a git commit.

## After Implementation

Report:

1. files changed;
2. local model raw literals replaced;
3. terminal collections migrated;
4. every provider `RefundStatus` usage renamed;
5. confirmation that local and provider refund enums remain separate;
6. confirmation that `Payment.payment_method_type` remains string;
7. confirmation that payment/webhook semantics did not change;
8. exact manual checks.

Tell me to run:

```bash
pytest apps/api/tests/test_api.py -k "cloudpayments or payment_status or refund or webhook"
pytest apps/api/tests/test_cloudpayments_adapter_api.py
npm run generate:check
npm run architecture:check
```

Then the PostgreSQL webhook coverage:

```bash
make test_db_up
pytest apps/api/tests/test_cloudpayments_webhook_postgres.py
make test_db_stop
```

## Commit

Final commit name:

```text
refactor(payments): use canonical commerce model enums
```

Status:

```text
todo
```

---

# Step 5 — Remove legacy persisted-enum/model façades and lock the final contract

**Status:** `todo`  
**Commit:** `refactor(models): finalize canonical model layer`  
**Depends on:** Steps 1–4 completed, manually verified, and committed.

## Prompt

Implement Step 5 of ANY-326: remove the temporary compatibility layer, make the shared persisted-enum adapter strict, delete the false billing model façade, update the minimal architecture documentation and leave `app.models` as the single canonical persisted model contract.

All runtime consumers are assumed to have been migrated by Steps 2–4.

## Goal

Finish ANY-326 so there is no second persisted enum source, no billing ORM façade, and no temporary raw-string write path into enum-backed ORM fields.

Final runtime code should follow:

```python
from app.models import Order, OrderStatus, Payment, PaymentStatus
```

## Relevant Existing Code

Work primarily in:

```text
apps/api/app/models/__init__.py
apps/api/app/models/_shared.py
apps/api/app/domains/billing/enums.py
apps/api/app/domains/billing/models.py
apps/api/app/domains/legal/enums.py
apps/api/tests/test_model_enums.py
scripts/repo.py                              # narrow architecture guard if this is where current architecture checks live
apps/api/tests/test_repository_docs.py       # use only if it is the existing guard/test home instead
ARCHITECTURE.md
docs/architecture/payment-portal-data-model.md
docs/architecture/decisions/0003-canonical-persisted-model-layer.md   # new ADR
docs/architecture/decisions/README.md
```

Only touch another file if it still has a direct import from one of the compatibility locations being removed.

Do not reopen architectural design.

## Implementation

### 1. Finalize `PersistedEnumType` as a strict enum-only write contract

The raw-string bind support from Step 1 was temporary and must be removed now that Steps 2–4 have migrated runtime consumers.

Final bind behavior must be:

```text
configured enum member -> persist member.value
None for nullable column -> keep None
plain str, even when its text equals a valid member value -> reject
other incompatible Python value -> reject
```

Final read behavior remains fail-closed:

```text
known stored string -> reconstruct canonical enum member
unknown stored string -> reject rather than silently returning raw data
```

Because `StrEnum` is also a subclass of `str`, implement the type check deliberately: recognize the configured enum class before rejecting plain strings. Do not accidentally reject real enum members by checking `isinstance(value, str)` first.

Do not alter the underlying `Text` implementation, add a migration or change stored values.

If an external/provider boundary starts from a string and needs to write a local persisted enum, that boundary must map or validate it explicitly into the canonical enum before assigning the ORM field. Do not reintroduce implicit raw-string acceptance in the adapter.

Update the Step-1 adapter tests accordingly: remove the final-contract expectation that a valid raw string binds successfully and replace it with an assertion that plain raw strings are rejected.

### 2. Remove persisted compatibility exports from billing enums

`app/domains/billing/enums.py` must no longer expose canonical persisted model enums.

Keep only non-persisted concepts that genuinely belong there, currently:

```text
ProviderSubscriptionState
SensitiveMetadataKey
ProductAccessStatus
```

Do not move them into `app.models`.

After this step, persisted enums such as:

```text
PaymentStatus
OrderStatus
SubscriptionStatus
SubscriptionScopeType
SubscriptionRenewalMode
...
```

must come from:

```text
app.models
```

### 3. Remove the legal enum compatibility façade

If `app/domains/legal/enums.py` now contains only the temporary alias to canonical `AcceptanceKind`, delete that module.

All model acceptance-kind usage must already import:

```python
from app.models import AcceptanceKind
```

Do not introduce a replacement façade.

### 4. Delete the false billing model façade

Delete:

```text
apps/api/app/domains/billing/models.py
```

It is only a re-export of the ORM model layer and does not represent a distinct domain abstraction.

Do not replace it with Pydantic copies, dataclasses, protocols or domain entities.

Do not delete `domains/identity/models.py` or `domains/legal/models.py` as unrelated cleanup in this ticket unless they were necessarily touched by an actual import dependency already modified by ANY-326. The explicit ANY-326 acceptance criterion concerns the billing façade; broader façade cleanup should not expand this PR.

### 5. Ensure final imports use the canonical contract

There must be no runtime/test import of persisted model enums through:

```text
app.domains.billing.enums
app.domains.legal.enums
```

and no import of ORM models through:

```text
app.domains.billing.models
```

A single targeted text search for these exact obsolete import forms is acceptable as a final edit check.

Do not perform broad research or unrelated cleanup.

Imports of the still-valid non-persisted billing enums are allowed.

### 6. Add a narrow static architecture guard

ANY-407 requires durable architecture rules to be protected where practical. Add the smallest guard to the repository's existing architecture/static-check infrastructure; do not create a new framework.

The guard must fail when any of these regressions appears in application/runtime code:

```text
apps/api/app/domains/billing/models.py exists again
ORM models are imported through app.domains.billing.models
one of the canonical persisted enum class names is defined again outside app/models/enums.py
persisted model enums are imported through app.domains.billing.enums or app.domains.legal.enums after the compatibility layer is removed
```

For duplicate-definition detection, guard the **exact canonical persisted enum class names from this plan**. Do not implement a blanket rule that rejects `StrEnum` outside `app.models`; provider contracts and non-persisted domain vocabularies legitimately use their own enum types. The static checker may keep those protected class names as strings, but it must not duplicate enum member/value sets and must not become a second persisted-vocabulary source of truth.

The guard must explicitly continue to allow, among other non-persisted/provider concepts:

```text
ProviderSubscriptionState
SensitiveMetadataKey
ProductAccessStatus
TransactionStatus
ProviderRefundStatus
RecurringSubscriptionStatus
OperationOutcome
RetryDisposition
```

Implement this in the existing `architecture:check` path (`scripts/repo.py`) using the repository's current AST/static-check style. Keep the rule scoped to `apps/api/app` rather than inventing a repository-wide enum framework.

Add focused positive/negative tests in the existing repository-check test home:

```text
apps/api/tests/test_repository_docs.py
```

Name the new tests with a common `canonical_persisted_model` substring so they can be run as a focused gate.

Cover at least:

1. recreating `domains/billing/models.py` is rejected;
2. importing ORM models through `app.domains.billing.models` is rejected;
3. defining a protected canonical persisted enum name such as `PaymentStatus` outside `app/models/enums.py` is rejected;
4. importing a canonical persisted enum through the removed billing/legal enum façade is rejected;
5. the canonical definition inside `app/models/enums.py` is allowed;
6. an unrelated/non-persisted `StrEnum` such as `ProviderSubscriptionState` is allowed.

Do not add generalized dependency machinery unrelated to these exact ANY-326 invariants.

### 7. Keep `app.models` public exports explicit

Make sure `app.models.__init__` explicitly exports:

- all ORM models;
- all canonical persisted enum types.

Do not use wildcard imports to hide ownership.

### 8. Update model-layer tests

Remove Step-1 assertions for temporary compatibility aliases and temporary raw-string binding.

Replace them with final-contract assertions:

```text
canonical enums import from app.models
no duplicate enum definitions are required
enum-backed ORM fields round-trip as canonical members
plain raw strings are rejected at the enum-backed ORM bind boundary
unknown persisted strings remain fail-closed on load
underlying SQL storage is text
```

Keep critical enum-value tests and the assertions that `region_mismatch_status` stays string-backed.

### 9. Update architecture documentation minimally

Update the current architecture documentation to reflect the completed transition:

```text
app.models is the canonical persisted model layer.
```

Document these rules succinctly:

```text
SQLAlchemy models -> app.models
persisted closed vocabulary -> app.models enum
database storage -> TEXT/VARCHAR
provider contract enum != local persisted enum
open/provider/configuration identifiers remain strings
```

Remove/update outdated wording that describes `app.models` or domain model re-exports as a temporary transition still awaiting the model-layer work now completed by ANY-326.

In the canonical data-model document, keep the existing rule that statuses are stored as text and validated in application code.

Do not rewrite the architecture documents or describe future ANY-407 layers as already implemented.

### 10. Add ADR 0003 for the durable model/persistence ownership decision

Create:

```text
docs/architecture/decisions/0003-canonical-persisted-model-layer.md
```

and add it to:

```text
docs/architecture/decisions/README.md
```

The repository ADR convention requires an ADR when a durable decision changes domain ownership, dependency direction, persistence, public interfaces, security posture or deployment. ANY-326 changes durable model ownership/dependency direction and the Python persistence contract, so this ADR is required.

The ADR should contain the repository-standard sections (`context`, `decision`, `consequences`, `status`, and superseded links when applicable) and record at least:

```text
app.models owns canonical SQLAlchemy models and persisted closed vocabularies
persisted Python enums are StrEnum
PostgreSQL representation remains TEXT/VARCHAR
no PostgreSQL native ENUM is introduced
provider contract enums remain distinct from local persisted enums
SubscriptionScopeType / SubscriptionRenewalMode keep their public names to avoid incidental OpenAPI changes
region_mismatch_status remains string until a complete closed vocabulary is actually defined
single-value enums are allowed only for confirmed application-owned closed model vocabularies, not merely because one default value is currently observed
raw-string binding is a staged migration compatibility only; final enum-backed ORM writes require canonical enum members
Plan.id remains checkout purchase identity; all_access remains internal scope
```

Reference the existing Plan-based checkout ADR rather than restating or superseding its purchase-identity decision. Do not rewrite prior ADR history.

### 11. Do not add an architecture framework in this final step

Do not add:

- repositories;
- domain entities;
- generic interfaces;
- dependency injection abstractions;
- new architecture checker rules unrelated to this exact model ownership (the narrow ANY-326 guard above is required);
- a second enum registry.

ANY-326 prepares the model boundary for the next ANY-407 stage; it does not implement that stage.

## Scope Constraints

Do not:

- change any state values;
- change runtime transitions;
- change API contracts;
- change database schema;
- add migrations;
- modify provider semantics;
- change checkout identity;
- clean up unrelated legacy modules;
- implement the next ANY-407 ticket.

## Automated Checks

Do NOT run any automated checks.

Do not create a git commit.

## After Implementation

Report:

1. files changed/deleted;
2. compatibility aliases removed;
3. confirmation that final `PersistedEnumType` rejects plain raw strings and still reads canonical stored strings as enum members;
4. confirmation that `app/domains/billing/models.py` is deleted;
5. confirmation that persisted enums are exported publicly through `app.models` and internally owned/imported through `app.models.enums`;
6. which enums remain intentionally in `app.domains.billing.enums` and why;
7. confirmation that the static ANY-326 architecture guard was added, is limited to the exact protected model contracts, and what regressions it catches;
8. confirmation that the focused positive/negative architecture-guard tests were added;
9. confirmation that ADR `0003-canonical-persisted-model-layer.md` and the ADR index were updated;
10. confirmation that generated OpenAPI remains contract-compatible;
11. documentation updated;
12. exact checks I should run manually.

Tell me to run the focused checks first:

```bash
pytest apps/api/tests/test_model_enums.py
pytest apps/api/tests/test_repository_docs.py -k canonical_persisted_model
npm run generate:check
npm run architecture:check
npm run docs:check
npm run test:api:fast
```

Then run the complete backend verification for the finished ticket:

```bash
make test_db_up
npm run test:api
npm run test:api:postgres
make test_db_stop
```

Finally verify migrations still apply without a new ANY-326 schema revision:

```bash
npm run migrate:api
```

## Commit

Final commit name:

```text
refactor(models): finalize canonical model layer
```

Status:

```text
todo
```

---

# Final Definition of Done

ANY-326 is complete only when all of the following are true:

- `app.models` owns every confirmed persisted enum from this plan;
- there is no duplicated persisted enum source;
- ORM enum-backed attributes are Python `StrEnum` members;
- the final enum adapter accepts canonical enum members on write and rejects plain raw strings; the Step-1 raw-string compatibility path is gone;
- PostgreSQL storage remains `TEXT` / `VARCHAR`;
- no PostgreSQL native ENUM was introduced;
- no ANY-326 Alembic migration was required;
- `SubscriptionScopeType` is shared by Plan / Subscription / Entitlement without changing its public OpenAPI schema name;
- `SubscriptionRenewalMode` is shared by Plan / Subscription without changing its public OpenAPI schema name;
- Order, Payment and Webhook canonical enums contain the full documented local state vocabulary;
- current runtime transition sets were not broadened merely because canonical enums are broader;
- `Payment.payment_method_type` remains provider-originated string data;
- `EntrypointSession.region_mismatch_status` and `Order.region_mismatch_status` remain strings because a complete closed vocabulary is not yet established;
- single-value enums in this plan are treated as explicit application-owned closed model contracts, not inferred solely from one observed/default value;
- the read-only existing-data compatibility gate was completed for every available existing database before the enum adapter was accepted; unavailable environments, if any, are explicitly recorded;
- provider refund result status remains a different type from local persisted `RefundStatus`;
- raw closed model-state literals are removed from runtime code except unavoidable SQL/external-boundary cases;
- `app/domains/billing/models.py` is gone;
- `app.models` models/enums are imported directly by consumers;
- a narrow static architecture guard prevents reintroducing the billing model facade, obsolete enum import paths or duplicate definitions of the exact canonical persisted enum names without banning unrelated `StrEnum` types;
- focused positive/negative repository-check tests cover that architecture guard;
- ADR 0003 records the canonical persisted model-layer decision;
- `npm run generate:check` confirms no incidental OpenAPI/schema artifact drift;
- `npm run docs:check` confirms the normative documentation/ADR updates remain valid;
- checkout still purchases by exact `Plan.id`;
- `all_access` remains only an internal access scope;
- public API JSON remains behavior-compatible;
- payment/refund/subscription lifecycle semantics remain unchanged;
- the next ANY-407 architecture stage can depend on a stable canonical persisted model layer.
