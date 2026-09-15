# External billing boundary and Payments Portal redesign

Status: review requested after second external-review and LBX Widget refinement
Date: 2026-09-15

## Goal

Redesign Payments Portal around a strict bounded-context split:

- External Billing owns the commercial billing domain;
- Payments Portal owns AnyToolAI identity plus the anti-corruption,
  projection, reconciliation, recovery, entitlement, and integration boundary;
- Platform Kernel owns technical product/metric vocabulary, actual usage,
  runtime quota enforcement, and execution;
- Platform Kernel never communicates directly with LBX, Dodo, or any future
  billing provider.

The repository has not been deployed to production. The current direct-payment
and Portal-owned commerce schema is disposable. This design therefore uses a
clean pre-production reset rather than a backward-compatible migration path.

MVP intentionally supports independent purchase of one existing Platform product
at a time. Commercial bundles, overlapping paid subscriptions for the same
product, allowance stacking, paid overage, and upgrade/downgrade are deferred.

## Canonical documentation precedence and required supersession

This design changes accepted semantics that still exist in Payments Portal ADRs
and architecture documents. Those older passages must not remain simultaneously
authoritative.

This design supersedes, where present in ADR 0002, ADR 0004, or related canonical
documentation:

- Portal-owned `Product`, `Plan`, `PlanLimit`, and commercial `Order` as the
  purchase authority;
- `Plan.id` as exact commercial purchase identity;
- recurring/commercial consent bound to `Plan.id`;
- a mandatory Portal commercial Order for Portal-initiated purchase;
- direct-payment-provider orchestration by Payments Portal;
- the assumption that payment UX, invoices, payment methods, or autopay must be
  implemented as Portal-owned UI.

Replacement semantics are:

- Platform Kernel owns `product_id` and `metric_key` vocabulary;
- External Billing owns commercial offers, prices, periods, subscriptions,
  balances, payments, refunds, payment methods, autopay, invoices, and billing
  lifecycle;
- Payments Portal projects provider offers as `billing_offer` and identifies the
  commercial version by `offer_id + commercial_fingerprint`;
- `PurchaseIntent` is orchestration state only, not a commercial Order;
- AnyToolAI commercial/legal acceptance is bound to current offer fingerprint
  and exact required legal-document versions;
- payment and billing self-service UX are provider-owned.

Before implementation is complete, the canonical set must be made consistent in
one documentation stream: ADR 0002, ADR 0004, billing authority, Portal data
model, reliability docs, Platform Kernel contract/quota docs, legal-flow docs,
and README/implementation guidance that still describes superseded semantics. A
new superseding ADR may record this target. Until that update lands, this spec is
the target design and conflicting older passages are migration inputs, not
concurrent requirements.

The clean Alembic reset is an explicit pre-production exception to any older
"baseline frozen / forward-only" convention. There is no production-data
compatibility requirement for this rewrite.

## Architectural invariants

### Ownership

External Billing owns commercial billing truth. For RU this is LBX. EU/US may
use Dodo or another provider behind the same Portal boundary. External Billing
owns, as applicable:

- commercial services/products, tariffs, periods, package composition, prices,
  discounts, sellability, and commercial allowances;
- subscription lifecycle, agreements or equivalent provider-native contracts;
- balances, charges, billing calculations, financial blocking;
- payment initiation and payment UX, acquiring, payment methods, autopay;
- refunds and dispute/chargeback consequences as represented by the provider;
- invoices, billing documents, payment history, billing customer profile, and
  billing notifications;
- provider-owned billing self-service UI.

Payments Portal owns:

- canonical AnyToolAI user identity, registration, authentication/session, and
  AnyToolAI legal acceptance;
- verified mapping between AnyToolAI users and external billing customers;
- read-only local projections of external catalog and subscription state;
- explicit immutable/versioned mapping between external billing components and
  Platform technical capabilities;
- `PurchaseIntent` and customer-interaction orchestration state;
- durable command recovery, customer discovery, reconciliation, webhook
  ingestion, work queues, and manual-review workflow;
- normalized entitlements and purchased-allowance projections;
- vendor-neutral `AccessSnapshot` and access invalidation toward Platform Kernel;
- durable ingestion/delivery state for usage forwarding when required.

Platform Kernel owns:

- technical `product_id` registry;
- technical `metric_key` registry, with every metric owned by exactly one
  `product_id`;
- actual runtime usage;
- runtime quota state, policy, and enforcement;
- scenario/workflow/action execution;
- durable paid-usage outbox.

Payments Portal never becomes the source of truth for actual runtime usage or
remaining runtime quota.

### One-way billing dependency

Platform Kernel must never receive LBX/Dodo credentials or provider-specific
identifiers and must never call a billing provider directly.

```text
External Billing
      |
      | catalog/customer/subscription APIs
      | webhooks + provider-owned billing UI
      v
Payments Portal
      |
      | AccessSnapshot / invalidation / UsageEvent
      v
Platform Kernel
```

When provider metering is required:

```text
Platform Kernel -> durable UsageEvent -> Payments Portal -> provider adapter
```

### Strict payment boundary

Payments Portal does not call payment-specific REST APIs. It does not create a
payment, submit or calculate a payment amount as payment authority, choose an
acquirer, save a payment method, enable autopay, retry a payment, issue a refund,
or use payment status as an access-granting fact.

Portal may call non-payment External Billing APIs required to establish or
reconcile commercial structure: customer provisioning/recovery, catalog reads,
provider-specific agreement/subscription provisioning, subscription state
reads/discovery, and safe usage reporting when a tariff requires it.

For RU, the selected customer-facing billing/payment surface is **LBX Widget**.
There is no fallback to Portal-orchestrated `/eps_payments` or another LBX
payment REST flow. Failure of the Widget production gate is an LBX capability
blocker, not a reason to weaken this boundary.

### Commercial facts versus derived paid access

External commercial/subscription facts change only after a complete,
successfully normalized authoritative provider read. Portal never invents
provider lifecycle, financial state, subscription composition, terminal dates,
or commercial quantities.

Derived paid access may change only from this closed list of causes:

1. a complete successfully normalized authoritative provider snapshot;
2. deterministic passage of time across a boundary already present in trusted
   facts; this may only reduce/expire access;
3. the explicitly bounded provisional recurring-allowance rollover defined in
   this spec;
4. an explicit audited operator resolution/rebind that selects or rebinds
   already-authoritative facts and then returns through normal derivation.

No other Portal-local event may create or increase paid access. Among
Portal-local mechanisms, provisional rollover is the **only** mechanism allowed
to increase usable paid allowance without a new authoritative provider read.

A local catalog row, webhook, browser/Widget callback, successful outbound POST,
payment fact, agreement creation, or `PurchaseIntent` state is never by itself
access authority.

## MVP commercial scope

MVP supports independent purchase of one existing Platform product at a time:

```text
Product A -> Offer A -> Subscription A
Product B -> Offer B -> Subscription B
```

For one `(user_id, product_id)` there may be at most one access-producing
billable subscription. A user may own different products independently.

MVP does not support:

- commercial bundles or all-access packages;
- one offer granting multiple products;
- multiple active billable subscriptions for the same product;
- allowance stacking;
- one metric shared by several products;
- paid overage;
- upgrade/downgrade flows.

Every sellable offer resolves to exactly one `product_id` and may contain zero or
more allowances whose `metric_key` values all belong to that product.

## System shape

```text
                    Sales / Finance
                          |
                          v
                  External Billing
                 LBX (RU) / future
                commercial authority
                          |
             non-payment REST + webhooks
                          |
             + provider-owned billing UI
                          |
                          v
                +-------------------+
                | Payments Portal   |
                |                   |
                | User identity     |
                | Legal acceptance  |
                | Catalog projection|
                | Mapping revisions |
                | Purchase intent   |
                | Reconciliation    |
                | Entitlements      |
                | Allowances        |
                +---------+---------+
                          |
             AccessSnapshot / invalidation
                          |
                          v
                +-------------------+
                | Platform Kernel   |
                | product_id        |
                | metric_key        |
                | actual usage      |
                | quota enforcement |
                | runtime execution |
                | usage outbox      |
                +-------------------+
```

## LBX Widget as the RU billing cabinet

### Vendor-documented capabilities

The public LBX Widget documentation describes an embeddable authenticated
customer window that can:

- show all customer subscriptions;
- create, edit, and stop subscriptions;
- top up a selected agreement balance;
- let the customer enter a payment amount, with LBX offering a recommended
  amount;
- manage autopay/payment method for a selected agreement;
- create, view, and download invoices;
- show history of money movement across agreements.

The Widget connection documentation also exposes configuration flags including
`disableCreateSubscription`, `disableEditSubscription`,
`disableStopSubscription`, `disableAutopayments`, `disablePayments`,
`disableInvoiceGeneration`, `hideInvoicesList`, and `hideSubscriptionsList`.
JWT authentication supports several customer lookup modes, including lookup by
agreement number (`ident_type=5`). The documentation does **not** by itself prove
that lookup by agreement number server-side restricts the Widget to only that
agreement; isolation remains a runtime/vendor proof obligation.

Vendor documentation basis:

- https://docs.lbxbilling.ru/integration_lbx/widget/
- https://docs.lbxbilling.ru/integration_lbx/widget/widget_connection/

### Target Widget configuration

MVP delegates billing self-service to LBX Widget while preserving Portal control
of commercial preparation:

```text
disableCreateSubscription = true
disableEditSubscription   = true

disableStopSubscription   = false
disablePayments           = false
disableAutopayments       = false

disableInvoiceGeneration  = false
hideInvoicesList          = false
hideSubscriptionsList     = false
```

Portal does not rely on `activeSubscriptionsLimit` or hidden controls as a
security boundary. Production validation must prove the relevant restrictions
are effective server-side/in the actual LBX deployment.

The following customer-facing billing UX moves to Widget:

- agreement balance/payment top-up;
- card/payment-method entry and storage handled by provider/payment
  infrastructure;
- autopay enable/change/disable;
- billing subscription/balance display;
- invoice generation/view/download where enabled;
- payment/money-movement history;
- customer-initiated subscription cancellation.

Portal keeps:

- AnyToolAI login/registration and legal acceptance;
- product catalog and fixed offer selection;
- purchase uniqueness and `PurchaseIntent`;
- lazy customer ensure;
- dedicated agreement/subscription preparation through non-payment LBX APIs;
- discovery/reconciliation;
- mapping, entitlements, allowances, `AccessSnapshot`, Kernel invalidation, and
  usage delivery.

Portal-owned payment form, card UI, autopay UI, invoice/payment-history UI, and
payment-result semantics are removed from the target. Post-Widget UX should
report **access activation/reconciliation state**, not claim payment success as
Portal authority.

### Native LBX balance model is accepted

LBX documentation describes an agreement-balance top-up where the user selects
an agreement and enters a payment amount; LBX may suggest a recommended amount.
MVP intentionally accepts that provider-native balance model rather than
requiring an exact Portal-defined checkout amount.

The safety boundary is therefore **dedicated-agreement accounting isolation**,
not "exact amount". Underpayment must not grant access; sufficient funding may
make only the intended subscription access-eligible; overpayment may remain on
the dedicated agreement for future provider billing. Portal does not model or
interpret the agreement balance.

## Platform capability manifest

Platform Kernel is the source of truth for technical product and metric
vocabulary. It publishes a versioned, vendor-neutral, read-only internal
capability manifest derived from the canonical Platform registry.

Conceptual shape:

```json
{
  "schema_version": 1,
  "manifest_version": "sha256:...",
  "generated_at": "...",
  "products": [
    {"product_id": "document-summary", "enabled": true}
  ],
  "usage_metrics": [
    {
      "metric_key": "document-summary.generations",
      "product_id": "document-summary",
      "unit": "generation",
      "enabled": true
    }
  ]
}
```

`manifest_version` changes deterministically on semantic changes. Platform
validation enforces `metric_key -> exactly one product_id`.

Portal imports the manifest into a local read-only projection. It is not fetched
synchronously on each purchase or runtime access request.

MVP defaults:

- import on startup plus refresh approximately every 5 minutes;
- `capability_manifest_max_age = 24h` for **new sales**.

If import fails, Portal retains the last-known-good manifest. Once it is older
than 24h, new purchases fail closed. Existing pinned subscriptions and
entitlements are not revoked because the capability manifest became stale.

`enabled=false` blocks new offers/mappings that depend on that capability but
does not automatically revoke historical paid access. Product sunset is a
separate controlled migration.

Every published mapping revision records the manifest version against which it
was validated.

```text
Capability Manifest = what technical capabilities exist
AccessSnapshot       = what this user may use now
```

## External catalog and mapping model

### Fixed one-product offers

Every MVP sellable external tariff/period is projected as a fixed
`billing_offer`. Portal purchase flow does not allow a customer to modify tariff,
service composition, or component quantity.

An offer may contain several external components, but after mapping:

- it resolves to exactly one unique `product_id`;
- every mapped `metric_key` belongs to that product;
- commercial-only components are allowed;
- any `UNCLASSIFIED` component makes the offer `NOT_SELLABLE`;
- more than one source component for the same `metric_key` makes the offer
  `NOT_SELLABLE` with `duplicate_metric_source`.

There is no Portal-owned Product/Bundle/Plan/PlanLimit commercial model.

### Component classification

Each imported external component is explicitly:

```text
UNCLASSIFIED
CAPABILITY_BEARING
COMMERCIAL_ONLY
```

`CAPABILITY_BEARING` requires one or more technical bindings.
`COMMERCIAL_ONLY` intentionally has no technical bindings. Missing mapping is
never silently interpreted as commercial-only.

### Immutable versioned mappings

Conceptually:

```text
billing_component_mapping_revisions
  id
  billing_component_id
  revision
  classification
  status                  # active / retired
  validated_manifest_version
  created_at
  published_by

billing_component_mapping_bindings
  mapping_revision_id
  capability_type         # product / usage_metric
  technical_key
```

One external component may bind to both a product and one or more product-owned
metrics. Mapping revisions are immutable after publication; future changes
create revision N+1.

Mapping publication is a controlled Product/Engineering operation, not Sales
free-form editing and not automatic inference from `outer_id`. MVP may use a
controlled admin command/API rather than a dedicated UI. Publication validates
against the current capability manifest and records actor, timestamp, and
manifest version.

Sales/Finance owns the commercial catalog in LBX. A new LBX service/tariff may
therefore exist while its Portal component remains `UNCLASSIFIED`; the related
offer is not sellable until Product/Engineering publishes a valid mapping.

### Subscription-component pinning

When Portal first resolves a real external subscription component, it pins that
component instance to the then-active mapping revision.

```text
External subscription component
        -> pinned mapping revision
        -> technical capabilities
        -> entitlements / allowance buckets
```

Future catalog mapping changes do not silently rewrite existing access. If the
provider later removes the component from the subscription, the derived
capability is removed through normal reconciliation.

A previously unresolved subscription component may be resolved once from
`NULL` to its first valid mapping revision. Changing an already-pinned revision
requires an explicit audited rebind; ordinary catalog sync and reconciliation
never rebind automatically.

Several components may map to the same `product_id`; product grants use set/union
semantics and materialize one product grant. A concrete subscription may not
have more than one source component for one `metric_key`. If it does, that
metric receives no allowance, `allowance_conflict` is opened for manual review,
and unrelated unambiguous capabilities may continue.

## Target Payments Portal data model

Exact SQL names/types may follow repository conventions. The semantic entities
and constraints below are required.

### Identity and legal

Retain Portal-owned:

- `users`;
- authentication/session state;
- versioned legal documents and append-only acceptances.

`users.id` is canonical AnyToolAI identity. Email is an attribute, never a
cross-system identity key.

### External billing configuration and customer correlation

`external_billing_accounts` identifies provider/system, contour/region,
environment/account key, and enabled state. It contains no secrets.

`external_billing_customers` is also the **durable customer slot** for a Portal
user and billing account. It exists before the first external customer-create
call and contains at least:

```text
id
external_billing_account_id
user_id
recovery_key              # stable opaque, NOT NULL
provider_customer_id      # NULL until proven
provisioning_status       # provisioning/ready/unknown/manual_review/failed
```

Required uniqueness:

```text
(external_billing_account_id, user_id) UNIQUE
(external_billing_account_id, provider_customer_id) UNIQUE when provider id exists
```

The stable recovery key is generated before any provider create and never
changes, including after email change.

External customer provisioning is lazy. Normal Portal registration creates no
LBX customer. Customer creation starts only after a commercial action passes its
legal barrier. Only minimum provider-required PII is transmitted.

Concurrent purchases of different products share the same customer slot. Only
the single unresolved `ensure_customer` operation may execute external create.
Parallel callers wait/reuse that operation and never issue a second LBX customer
create. `unknown` customer-create outcome blocks new create attempts until
recovery/manual resolution.

### Catalog projections

Portal stores read-only projections for:

- capability-manifest import metadata;
- technical products and metrics;
- external catalog components;
- immutable mapping revisions/bindings;
- fixed `billing_offers` with `product_id`, display facts,
  `commercial_fingerprint`, provider references, sellability, and sync metadata;
- offer component composition/allowance facts.

### Purchase intent: orchestration and interaction are separate

There is no Portal commercial `Order`.

`purchase_intents` includes at least:

- `user_id`, billing account, `product_id`, `billing_offer_id`;
- immutable commercial fingerprint/snapshot;
- client idempotency identity;
- orchestration state;
- interaction state/timestamps;
- optional linked external subscription once proven.

`PurchaseIntent` is not an invoice, payment, subscription, or access authority.

Orchestration states conceptually include:

```text
created
preparing
awaiting_external_result
linked
resolved_no_external_effect
manual_review
failed_before_external_effect
```

Customer-interaction state is separate:

```text
not_ready
available
expired
```

`interaction=expired` means the normal Widget UX is no longer considered active;
it does **not** mean the commercial outcome is resolved and does not by itself
release the `(user_id, product_id)` purchase scope.

PurchaseIntent stops owning the scope only after one of these outcomes:

- `linked` — a real external subscription was proven and scope ownership moves
  to that `billing_subscription`;
- `resolved_no_external_effect` — provider-specific recovery proves the old flow
  can no longer create an external effect;
- `failed_before_external_effect` — failure happened before any external
  mutation was possible;
- explicit audited manual resolution.

A linked non-terminal subscription continues to hold product-purchase scope even
when it is prepared-but-unpaid or otherwise not yet access-eligible. New purchase
for that product remains blocked until authoritative provider state proves that
the linked subscription is terminal/cannot later become access-producing, or an
explicit audited resolution clears it. If outcome cannot be proven, the subject
remains unresolved/manual-review. A late external subscription after UX expiry
is still discovered/reconciled and may link the intent.

### Subscription projection

`billing_subscriptions` exists only after a real external subscription is
confirmed. Pre-subscription uncertainty belongs to `PurchaseIntent` and
`billing_operations`.

Normalized subscription facts are deliberately small:

```text
lifecycle_status: active | inactive | ended
financial_access_status: allowed | blocked
commercial_access_status: eligible | ineligible
```

`commercial_access_status` is adapter-derived from provider-authoritative facts
and represents the provider-validated criterion that the prepared subscription
is commercially eligible for access, including any required initial-activation
semantics. Unknown access-relevant provider semantics are not stored as normal
business states.

External subscription uniqueness includes:

```text
(external_billing_account_id, external_subscription_id) UNIQUE
```

The domain/DB also prevents more than one selected access-producing subscription
per `(user_id, product_id)`. Multiple external subscription rows may exist for
audit/conflict handling, but only one may be selected as the access source.
Separately, a linked non-terminal subscription may hold purchase scope even
while it is not selected as access-producing.

`billing_subscription_components` projects actual subscription composition and
stores its pinned mapping revision.

### Entitlements and purchased allowances

`entitlements` materializes product grants. `purchased_allowances` materializes
paid metric limits. Kernel-facing representations contain no provider IDs.

Every allowance has stable opaque `allowance_id` and an internal link to the
exact normalized subscription + pinned external component needed for historical
routing. Historical/expired allowance rows are retained and remain resolvable by
`allowance_id`; they are not physically deleted merely because the period ended.

For MVP, one user may have at most one active paid allowance source for a given
`metric_key`. No stacking or automatic sum/max semantics exist.

Portal does not persist authoritative runtime `remaining` usage. Platform Kernel
owns actual usage and remaining-quota calculation.

### Reliability and operational state

`billing_operations` is the durable journal for Portal-initiated non-payment
external mutations. An operation exists before any non-idempotent side effect.
Timeout/lost response becomes `unknown`; no blind retry occurs before
provider-specific recovery.

`billing_webhook_inbox` stores every authenticated delivery with a
Portal-generated `delivery_id`, safe correlation hints, event type, non-unique
`payload_hash`, processing state, and timestamps.

`billing_work_items` is the durable PostgreSQL queue for catalog/capability sync,
operation recovery, discovery, reconciliation, invalidation delivery, and
related work.

`manual_review_cases` records subject, reason code, owner category, status,
timestamps, explicit resolution, and audit actor/details. It is separate from
access state.

Usage ingestion/delivery persistence records integration state only, not a
second runtime usage ledger.

Provider-specific typed support tables are allowed. LBX agreement
bindings/recovery data may live in LBX-specific tables without forcing Agreement
into provider-neutral domain contracts.

## Legal barrier, origin classification, and customer creation

### User-initiated purchase

Before creating a user-initiated `PurchaseIntent`, Portal verifies all currently
required AnyToolAI legal documents for the exact commercial version.

Acceptance is bound to:

```text
user_id
region
billing_offer_id
commercial_fingerprint
required legal document versions
acceptance kind
timestamp/audit metadata
```

Commercial fingerprint covers material terms used to decide what the user buys:
price/currency, billing period/recurrence, product, component/allowance
composition, and material renewal/cancellation terms presented or relied on.
Cosmetic copy changes alone do not change the fingerprint.

Changed material terms return `offer_changed` and require review/new acceptance
before a new intent.

Portal owns AnyToolAI legal acceptance. LBX/payment infrastructure owns
provider-specific payment-method/autopay consent inside Widget. Portal never
infers permission to charge from its own checkbox.

### Discovered/manual subscriptions

Automatic access-producing origins are limited to:

```text
purchase
operator_comp
external_unknown
```

A normal customer-funded/recurring subscription discovered without the matching
Portal purchase/legal acceptance does **not** automatically grant access; it is
`external_unknown` and requires manual review.

`operator_comp` is an explicit audited classification for a non-customer-funded,
non-autopay comp/gift grant. It may omit `PurchaseIntent`/recurring-payment
consent, but the Portal user must still hold current baseline AnyToolAI terms /
privacy acceptances required to use the service. If baseline acceptance is
missing, the comp entitlement is held until acceptance.

MVP supports comp/gift only for an **already mapped** external customer. Creating
or auto-binding a new LBX customer solely for a Sales/Finance gift is out of
scope. Unknown provider customers are never auto-bound by PII.

### Data lifecycle

Erasure/retention, merchant-of-record, fiscal/54-FZ responsibility, and exact
legal retention periods require explicit Legal/Finance policy. The technical
design must support delete/anonymize/disconnect/retain decisions without
pretending Portal user deletion automatically erases provider records with
independent retention obligations.

## Purchase and LBX preparation lifecycle

### Offer and scope validation

Browser submits only Portal opaque identifiers:

```text
offer_id
commercial_fingerprint / offer_version
client idempotency key
```

It never submits authoritative price, provider tariff/service ID, payment
amount, or billing period.

Portal verifies capability-manifest freshness, external catalog freshness,
offer sellability, current fingerprint, legal acceptance, and business
uniqueness for `(user_id, product_id)`. Changed terms return `offer_changed`.
When current terms cannot be confirmed where required, new purchase fails
closed.

### Business uniqueness beyond HTTP idempotency

`Idempotency-Key` protects retransmission of one public request. Business
uniqueness is `(user_id, product_id)`.

In a short local transaction Portal checks for:

```text
scope-holding billing_subscription -> already_owned if access-eligible,
                                      otherwise existing_subscription_pending
scope-holding PurchaseIntent       -> purchase_in_progress
none                               -> create PurchaseIntent
```

DB uniqueness/partial uniqueness is the final race protection. `unknown`,
`ambiguous`, interaction expiry, or unresolved provider outcome continues to
hold purchase scope until proven resolved. A linked prepared-but-unpaid
subscription therefore cannot be bypassed by starting a second purchase.

### Durable external-customer ensure

The customer slot + stable recovery key and a durable `ensure_customer`
operation are committed **before** LBX customer create.

```text
BEGIN
create/find customer slot
create/find single unresolved ensure operation
COMMIT

only then -> LBX customer create/recovery
```

Two parallel purchases for Product A and Product B may have independent
PurchaseIntents, but they share the same customer ensure. A timeout keeps the
slot `unknown`; lookup/recovery by stable key happens before any controlled
retry. Multiple matches become manual review.

### Provider-neutral preparation

```text
validate offer + legal + purchase scope
 -> create PurchaseIntent
 -> ensure external customer
 -> provider-specific non-payment commercial preparation
 -> CustomerInteraction
 -> Widget interaction / external changes
 -> discovery + authoritative reconciliation
 -> link PurchaseIntent when subscription identity is proven
```

Application ports do not require Agreement. LBX adapter may create/recover a
dedicated agreement and subscription.

LBX MVP cardinality:

```text
1 Portal User = 1 LBX Customer
1 paid AnyToolAI product subscription = 1 dedicated LBX Agreement
renewal of same subscription reuses Agreement
new subscription = new dedicated Agreement
```

### Prepared-but-unpaid safety

Creation of agreement/subscription never implies paid access.

Access-producing eligibility requires all of:

```text
lifecycle_status = active
financial_access_status = allowed
commercial_access_status = eligible
current time is inside applicable trusted boundaries
```

For LBX, production enablement requires runtime proof that an unpaid prepared
subscription remains commercially/access ineligible and becomes eligible only
after provider-owned billing processing changes authoritative subscription
facts. Portal does not query payment-specific APIs and does not use Widget
callback/payment event as the criterion.

If LBX can expose a newly prepared unpaid subscription as access-eligible under
the chosen configuration, RU launch is blocked. Portal must not compensate by
creating a shadow payment state.

## LBX Widget production gate

RU production requires authenticated stand/vendor proof of all of the following:

- supported Widget script URL and signing-secret provisioning;
- intended configuration flags actually prevent subscription create/edit;
- one customer with Agreement A and Agreement B cannot use Widget context A to
  fund/mutate/activate B;
- balance top-up is accounted to the selected dedicated agreement;
- autopay/payment-method behavior is isolated to the intended agreement context;
- funding Agreement A cannot activate Subscription B;
- prepared-but-unpaid subscription gives no access;
- underpayment gives no access;
- sufficient funding can make only the target subscription access-eligible;
- Widget cancellation produces an authoritative subscription change that Portal
  can reconcile correctly;
- browser/JS success callbacks remain hints only;
- Portal can derive access from ordinary authoritative subscription reads
  without payment-specific REST calls.

Editable payment amount is **not** itself a blocker: it is documented LBX native
behavior and is accepted if dedicated-agreement isolation above is proven.
Likewise, `ident_type=5` or UI-hidden controls are not accepted as proof of
server-side isolation by themselves.

## Reconciliation and discovery

### Webhook is only an accelerator

Webhook handling:

```text
authenticate
 -> minimal validate / extract safe hints
 -> generate delivery_id
 -> persist inbox row
 -> enqueue/coalesce work
 -> commit
 -> return 2xx
```

No provider REST read occurs in webhook request. Every valid HTTP delivery is
stored separately. `payload_hash` is diagnostic, not unique. Dedup/coalescing is
on reconciliation work by subject. Provider webhook order is not authoritative.

Scheduled reconciliation/discovery are correctness backstops even when webhooks
are missed.

### Known-subscription reconciliation

Known subscriptions reconcile by exact external reference and a full
authoritative read. A complete consistent snapshot atomically updates normalized
state, components, entitlements, allowances, audit state, access revision, and
reconciliation timestamps as appropriate.

Partial/inconsistent reads preserve previous good projection.

### Customer-scoped inbound discovery

`PurchaseIntent` is not required for `billing_subscription`. Every mapped
external customer undergoes periodic subscription discovery independent of
checkout.

Discovery never grants from list output alone. A discovered reference always
receives a full authoritative read first.

Automatic identity binding is allowed only through the already-verified Portal
User <-> external customer mapping. Account-wide scans may detect orphans for
manual review but never auto-bind by email/phone/name.

A retired/missing current catalog offer does not invalidate an existing
subscription; access derives from actual composition + pinned mapping + trusted
authoritative state.

### Discovery cadence

MVP defaults, all configurable:

```text
stable mapped customer            every 6 hours
recent/changed customer           every 5 minutes
open PurchaseIntent               adaptive 1-5 minutes
valid webhook hint                immediate/high priority
manual-review/ambiguous recovery  dedicated recovery policy
```

Workers persist `last_discovery_at`, `next_discovery_at`, priority/result
metadata so restarts do not lose cadence. Webhooks improve latency only.

### Fenced per-subject reconciliation lease

Only one provider snapshot may apply for a subscription at a time. MVP uses a
PostgreSQL fenced lease:

1. short transaction claims `lease_owner`, `lease_until`, monotonically
   increasing fencing generation;
2. commit;
3. provider HTTP read with no open DB transaction;
4. new short transaction applies only if owner+generation are still current;
5. release/expire lease.

If another worker acquires a higher generation, a stale worker cannot commit its
older read.

## Conflict and primary-source semantics

MVP never stacks eligible subscriptions for one `(user, product)`.

If an already-known trusted access-producing subscription exists and discovery
finds a second eligible subscription for the same product:

```text
existing trusted primary continues within normal trust rules
new conflicting subscription produces no access
open subscription_conflict manual review
```

If Portal first observes two or more eligible subscriptions and no trusted
primary was previously established:

```text
no paid grant for that product
open subscription_conflict manual review
```

`PurchaseIntent` by itself does not make a subscription primary. Resolution
`accept_subscription_as_primary` selects the authoritative source and then
normal reconciliation derives access. Portal never auto-selects by age, amount,
agreement order, or another heuristic.

## Normalization uncertainty

Unknown access-relevant provider semantics are integration failure, not a normal
business state.

```text
provider response received
 -> normalization_error
 -> preserve last-known-good normalized projection
 -> alert + retry/manual review
```

Rules:

- previous allowed access may survive only to its existing finite trust deadline;
- previous blocked state remains blocked;
- no prior valid state means no access;
- uncertainty never increases access;
- semantic unknown does not qualify for provisional rollover;
- irrelevant unknown optional provider fields are tolerated.

## Freshness, renewal, and provisional rollover

Business state and operational freshness are separate:

```text
fresh -> stale_usable -> expired
```

An authoritative `blocked`, `ended`, or other known negative fact revokes Portal
access immediately; outage grace does not override known negative state.

### Subscription lifetime is not allowance period

```text
subscription terminal boundary != allowance period_end
```

An open-ended recurring subscription does not lose product grant because the
current monthly allowance period ended.

### Provisional rollover

Portal increases reconciliation urgency before expected allowance boundary. If
the next period cannot be confirmed **only because of provider transport/
unavailability**, Portal may create a provisional next allowance when the last
authoritative state proves all of:

- already-confirmed recurring subscription;
- lifecycle active, financial allowed, commercial access eligible;
- no known cancellation/terminal end;
- same product and metric;
- same or smaller confirmed quantity/policy;
- previous period completed normally;
- failure is provider transport/unavailability, not unknown access semantics.

MVP default:

```text
renewal_grace_window = 6 hours
```

Provisional rollover cannot create a new product grant, first paid access,
upgrade, larger allowance, different metric/product/tariff, or revive a known
blocked/ended subscription.

Portal may materialize a **future-dated** provisional bucket before the boundary
when the qualifying provider outage is already established:

```text
period_start = previous period_end
renewal_grace_until = period_start + 6h
```

It is unusable before `period_start`.

Provider confirmation turns it authoritative. Provider confirmation of blocked,
cancelled, or not-renewed state revokes it immediately. Usage legitimately
consumed during grace is not retroactively undone. Without confirmation, it
expires at grace end.

## AccessSnapshot contract and Kernel cache

All timestamps are UTC. All validity intervals use half-open `[start, end)`
semantics.

Conceptual AccessSnapshot:

```json
{
  "schema_version": 1,
  "tenant_id": "anytoolai",
  "region": "ru",
  "user_id": "uuid",
  "access_revision": 184,
  "authoritative_as_of": "...",
  "refresh_after": "...",
  "expires_at": "...",
  "grants": [
    {
      "product_id": "document-summary",
      "valid_from": "...",
      "valid_until": null
    }
  ],
  "allowances": [
    {
      "allowance_id": "opaque-uuid",
      "product_id": "document-summary",
      "metric_key": "document-summary.generations",
      "quantity": 1000,
      "period_start": "...",
      "period_end": "..."
    }
  ]
}
```

`grant.valid_until` is only a known **terminal product-access lifecycle
boundary**. For open-ended recurring subscriptions it is `null`. It must never
be copied from `allowance.period_end`. `null` does not mean infinite trust;
`AccessSnapshot.expires_at` remains mandatory.

Known scheduled cancellation/end may set a finite `grant.valid_until`.

MVP cache defaults:

```text
refresh_after = generated_at + 1 minute
expires_at    = generated_at + 5 minutes
```

These are Kernel cache bounds, not LBX billing grace. Snapshot `expires_at` must
never exceed the Portal freshness/trust deadline for the paid facts represented
by that snapshot and must not extend a provisional bucket beyond
`renewal_grace_until`. Earlier per-grant/per-allowance semantic boundaries remain
independent refresh triggers.

Kernel behavior:

- before `refresh_after`, cached snapshot may be used if no semantic boundary
  has been crossed;
- between `refresh_after` and `expires_at`, Kernel attempts refresh but may use
  cache if Portal is temporarily unavailable and the relevant grant/allowance
  interval is still valid;
- at/after `expires_at`, cached paid access fails closed;
- crossing `grant.valid_until`, `allowance.period_start`, `allowance.period_end`,
  or another access-relevant temporal boundary requires synchronous
  AccessSnapshot refresh before treating absence of a new period as final deny;
- Kernel never creates provisional paid access itself;
- if an allowance ended and Portal is unavailable, paid consumption fails closed
  until refresh succeeds;
- guest/free Kernel-owned functionality is independent of paid billing outage.

Portal may continue to serve a last-known-good snapshot within its own longer
`projection_valid_until` even while LBX is unavailable. The 5-minute Kernel
expiry means only "Kernel may not remain autonomous from Portal longer than
this". It does not redefine Portal's LBX trust lease.

## Access revision and invalidation

Any material access projection change, positive or negative, increments the
user's monotonically increasing `access_revision` and enqueues durable Kernel
invalidation in the same local transaction.

Examples include:

- new paid grant after authoritative activation;
- blocked -> allowed or allowed -> blocked;
- new authoritative allowance;
- future/provisional rollover materialization;
- allowance reduction/removal;
- subscription end;
- audited rebind/manual resolution affecting access.

Invalidation carries only a vendor-neutral hint:

```json
{
  "schema_version": 1,
  "user_id": "uuid",
  "region": "ru",
  "access_revision": 184
}
```

It never carries entitlement deltas. Kernel discards older cached revisions and
uses the normal AccessSnapshot pull path. Delayed invalidations with older
revision are ignored. Multiple pending revisions may coalesce to the newest.

Lost invalidation is tolerated because `refresh_after`, semantic-boundary
refresh, and `expires_at` remain correctness backstops.

## Runtime usage and durable delivery

Platform Kernel remains the single authority for actual usage and runtime quota.
Paid quota consumption and UsageEvent-outbox insertion occur in the same Kernel
transaction:

```text
update actual usage/quota
insert UsageEvent outbox row
COMMIT
```

Portal is not in the synchronous hot path of each runtime action.

Conceptual event:

```json
{
  "schema_version": 1,
  "usage_event_id": "uuid",
  "tenant_id": "anytoolai",
  "region": "ru",
  "user_id": "uuid",
  "allowance_id": "opaque-uuid",
  "product_id": "document-summary",
  "metric_key": "document-summary.generations",
  "quantity": 1,
  "occurred_at": "..."
}
```

Kernel -> Portal delivery is at-least-once. Portal ingestion is idempotent by
`usage_event_id` and acknowledges only after durable persistence.

Portal outcomes are logically:

```text
accepted
duplicate
rejected_permanent
```

Permanent semantic rejection (for example unknown allowance, wrong user,
tenant/region mismatch, product/metric mismatch, invalid quantity, or occurrence
outside the historical allowance interval) is itself durably recorded and
returned as a terminal `2xx` result. Kernel stops retrying and retains a
terminal/dead-letter audit state. Runtime usage is **not** refunded.

Only failures where Portal could not durably process the event because of a
retryable infrastructure problem return `5xx` and remain retryable.

Late delivery after subscription/period end remains valid when `occurred_at` was
inside the historical `[period_start, period_end)` and `allowance_id` still
resolves.

Portal delivery state may include:

```text
received
not_required
pending_external
external_delivered
external_unknown
rejected_permanent
manual_review
```

Portal never calculates authoritative remaining runtime quota.

If external metering is required, unsafe non-idempotent provider reporting is
never blindly retried. An offer requiring provider metering is `NOT_SELLABLE`
unless native idempotency or an unambiguous recovery strategy is proven.

Paid overage is absent. Kernel hard-stops at the known allowance limit.

## Commercial lifecycle scope

MVP Portal command orchestration supports only **buy one product**.

- **Cancellation** is customer-initiated in LBX Widget where enabled, or
  Support/Finance in LBX. Portal only reconciles the resulting authoritative
  state.
- **Upgrade/downgrade** is out of scope. A second offer for the same product
  cannot be bought while current subscription owns the product.
- **Refund/dispute/chargeback** are provider/payment concerns. Portal does not
  initiate or interpret payment status; it reacts to authoritative subscription
  consequences.
- **Commercial trial** has no Portal-owned paid state. Free/guest usage remains
  Kernel policy. A future provider-managed free-period/recurring-charge trial
  requires separate design.
- **Comp/gift** is allowed only for an already mapped customer and only as
  explicit audited `operator_comp` with no customer-funded/autopay obligation.

"Out of scope for command orchestration" is not "out of scope for
observation". Portal must reconcile access-relevant consequences created
externally.

## Manual review

`manual_review` is operational workflow, never access state or direct entitlement
authority.

Minimum reasons/owners:

- duplicate/overlapping subscription -> Finance/Billing Ops;
- ambiguous create/recovery -> Billing Ops;
- unknown external customer -> Support/Billing Ops;
- unmapped/unclassified component -> Product/Engineering;
- duplicate metric source -> Product/Engineering;
- unknown access-relevant provider semantics -> Engineering/on-call;
- invalid capability mapping -> Product/Engineering.

Safety behavior follows trusted facts, not the existence of the case. A newly
found conflicting subscription cannot add access; an already-known primary may
continue within its trust rules.

Explicit resolutions may include:

```text
bind_existing_external_object
mark_duplicate_external_object
rebind_mapping_revision
accept_subscription_as_primary
reject_subscription_as_conflict
mark_external_customer_unmatched
```

MVP does **not** include `bind_external_customer_to_user` for unknown provider
customers. Operators never directly set `entitlement=active`; resolution always
returns through normal reconciliation/derivation.

A dedicated admin UI is not required. Durable records, metrics/alerts, runbook,
and controlled operational command/API are sufficient.

## Provider abstraction

Application/domain code depends on small capability-oriented ports:

- external catalog reads;
- external customer ensure/recovery;
- non-payment commercial preparation;
- provider-owned customer-interaction description;
- authoritative subscription read and customer-scoped discovery;
- optional usage reporting;
- webhook authentication/parsing.

There is no generic payment-command capability in Payments Portal.
Provider-specific branches live only in integration/composition packages.
LBX Agreement logic, tariff/service API, `state`, `current_blocking`, Widget
mechanics, balance behavior, and recovery lookups stay inside LBX integration.

## Portal <-> Platform Kernel implementation contract

This is a cross-repository implementation stream, not a final Portal-only step.
Implementation is incomplete until both repos implement and test their sides.

Wire contracts and ownership:

| Contract | Producer/source | Consumer |
| --- | --- | --- |
| Capability Manifest | Platform Kernel | Payments Portal |
| AccessSnapshot | Payments Portal | Platform Kernel |
| AccessInvalidation | Payments Portal | Platform Kernel |
| UsageEvent | Platform Kernel | Payments Portal |

Each wire payload has `schema_version`. Consumers fail clearly on unsupported
major schema versions. Do not introduce a shared runtime Python package that
couples repo release cycles; use versioned HTTP/JSON contracts and contract tests
on both sides.

Platform Kernel implementation work must include:

- canonical usage-metric registry and Capability Manifest endpoint;
- AccessSnapshot client/cache and semantic-boundary refresh;
- AccessInvalidation receiver keyed by `access_revision`;
- integration of paid allowances into the existing backend-owned quota engine;
- atomic paid-usage + UsageEvent-outbox persistence;
- outbox retry/terminal-rejection handling.

Payments Portal implementation work must include:

- Capability Manifest importer;
- AccessSnapshot producer;
- monotonic access revision + durable invalidation sender;
- durable UsageEvent ingestion, permanent rejection, and historical allowance
  routing.

Required cross-repo proof includes at minimum:

```text
subscription becomes eligible
 -> Portal AccessSnapshot revision N
 -> Kernel authorizes product
 -> Kernel atomically consumes quota + writes UsageEvent
 -> Portal durably ingests event
 -> Portal access changes to revision N+1
 -> invalidation reaches Kernel
 -> Kernel refetches N+1 and uses it for next decision
```

Failure proof must cover Portal outage beyond snapshot expiry, LBX outage with
Portal still serving last-known-good state, allowance boundary refresh, and
permanent UsageEvent rejection without infinite retry.

## Worker topology and transaction rules

MVP runs the durable billing worker embedded in the Payments Portal API process,
with one API replica initially. Correctness-critical work is PostgreSQL-backed,
not FastAPI `BackgroundTasks` or an in-memory queue.

Worker/use-case code is independent of FastAPI composition so it can later move
to a dedicated process. Queue claiming, customer ensure, purchase uniqueness,
and reconciliation leases remain multi-consumer safe even if replicas increase.

External network requests never execute inside an open DB transaction.
Transactions are short and cover durable intent/customer slot creation,
operation/queue/lease claims, and atomic local projection updates.

No RabbitMQ/Kafka is required for MVP.

## Security and PII

External billing credentials, webhook secrets, Widget signing secrets, and
payment credentials live only in runtime secret configuration. They are not
stored in billing-account/domain rows, logs, or ordinary browser-visible API
responses.

Kernel-facing capability/access/usage/invalidation APIs are service-to-service
over TLS with explicit service authentication and contour scope. User auth alone
must not authorize them.

Only minimum provider-required customer PII is transmitted/stored. Email, phone,
name, and INN are never automatic cross-system identity-binding authority.

Reverse-proxy/access logging must not leak webhook query secrets, Widget signing
material, or auth data. Raw provider payload retention requires an explicit
purpose plus redaction/retention policy.

## Observability and audit

At minimum monitor:

- capability-manifest age/import failure;
- catalog sync age and not-sellable reasons;
- customer ensure/recovery failures and unresolved `unknown`;
- open manual-review count and oldest age by reason;
- normalization errors and affected subjects;
- discovery/reconciliation age, success/failure, and duration;
- webhook auth failures and processing lag;
- work-queue depth/oldest age;
- Portal invalidation queue lag;
- Kernel UsageEvent outbox depth/oldest age;
- permanent usage rejection rate by reason;
- fresh/stale-usable/expired projection counts;
- provisional rollover count/age/grace expiry;
- provider latency/timeouts/errors.

Normalization errors and sustained permanent UsageEvent rejects are high-priority
alerts because they indicate contract/provider inconsistency.

Audit must answer why access changed and which authoritative reconciliation,
mapping revision/rebind, manual resolution, or provisional rollover caused it,
without creating a shadow provider financial ledger.

## Clean pre-production reset and implementation ordering

There is no production deployment or compatibility contract. Do not implement a
dual schema or semantic data migration from old Portal commerce.

Implementation ordering must be dependency-aware and cross-repo:

1. supersede/update contradictory canonical ADR/docs in Portal and Kernel;
2. remove obsolete Portal Product/Bundle/Plan/PlanLimit/Order and direct-payment
   orchestration semantics;
3. replace the disposable Portal Alembic baseline with clean target schema and
   recreate development/test DBs;
4. implement Kernel capability/metric manifest and Portal importer;
5. implement external catalog projection + mapping publication/pinning;
6. implement durable customer slot/ensure and LBX non-payment preparation;
7. implement PurchaseIntent scope rules and embedded Widget integration;
8. implement customer discovery, fenced reconciliation, normalized access and
   allowances;
9. implement Portal AccessSnapshot/revision/invalidation and Kernel consumer;
10. integrate paid allowance into existing Kernel quota engine;
11. implement Kernel UsageEvent outbox + Portal durable ingestion/routing;
12. run cross-repo contract/integration proofs;
13. separately satisfy LBX Widget production gate before RU production launch.

No old/new billing traffic split or dual-write compatibility layer is required.

## Required correctness tests and launch evidence

Implementation plan must include automated tests plus provider-validation spikes
proving at least:

- same idempotency key creates one PurchaseIntent;
- different keys/tabs cannot create two simultaneous purchase scopes for one
  `(user, product)`;
- UX interaction expiry does not release unresolved purchase scope;
- linking a prepared-but-unpaid subscription transfers purchase scope from the
  PurchaseIntent to that subscription and still blocks a second purchase;
- late external subscription after Widget expiry still links/reconciles;
- customer slot is created before LBX create and parallel Product A/B purchases
  cannot create two LBX customers;
- customer-create timeout keeps same recovery key and forbids blind duplicate
  create;
- provider create timeout for agreement/subscription uses safe recovery;
- duplicate/out-of-order webhooks converge and each HTTP delivery keeps unique
  Portal `delivery_id`;
- missed webhook is repaired by scheduled reconciliation/discovery;
- mapped-customer manual subscription is found without PurchaseIntent;
- unknown external customer never auto-binds by PII;
- comp/gift to an unmapped user is unsupported in MVP;
- external_unknown customer-funded subscription without proper Portal purchase
  acceptance does not automatically grant access;
- baseline legal acceptance is required before operator-comp access activates;
- full authoritative read is required before discovered access;
- mapping publication is controlled/audited and revisions are immutable;
- existing subscription component remains pinned through mapping changes;
- unclassified component makes offer not sellable;
- duplicate metric source makes new offer not sellable and creates no summed
  allowance for a live subscription;
- multiple product bindings deduplicate to one product grant;
- when two eligible subscriptions first appear with no trusted primary, no grant
  is created until manual primary selection;
- when a trusted primary already exists, later conflicting subscription adds no
  access and does not revoke the trusted primary merely by appearing;
- prepared-but-unpaid LBX subscription is access-ineligible;
- underfunding the dedicated agreement does not grant access;
- sufficient Widget funding can make only target subscription eligible;
- funding/autopay for Agreement A cannot activate/mutate Agreement B;
- Widget create/edit subscription restrictions are effective in actual runtime;
- Widget cancellation reconciles through authoritative subscription state;
- Widget/browser callback never grants access directly;
- allowance-period end does not end an open-ended product grant;
- open-ended grant serializes with `valid_until=null`;
- `allowance.period_end` is never copied into `grant.valid_until`;
- all temporal semantics are UTC half-open intervals;
- qualifying provider outage may create only same-terms provisional rollover;
- provisional allowance expires in <=6h unless confirmed;
- semantic unknown cannot create provisional rollover or overwrite good state;
- any positive or negative material access change increments `access_revision`
  and durably queues invalidation;
- crossing an allowance/grant semantic boundary forces Kernel refresh before
  final deny;
- `AccessSnapshot.expires_at` never exceeds Portal trust/grace bounds;
- lost invalidation still converges via refresh/expiry;
- Kernel cache defaults are 1m refresh / 5m expiry and are not confused with
  Portal LBX trust lease;
- stale capability manifest blocks new sales after 24h but not historical access;
- Kernel paid quota consumption and UsageEvent insertion are atomic;
- Portal ingest is idempotent by `usage_event_id`;
- permanent invalid UsageEvent is durably rejected, acknowledged terminally,
  does not retry forever, and never refunds Kernel usage;
- late UsageEvent routes through historical `allowance_id`;
- unsafe external metering semantics make dependent offer not sellable;
- no provider network request occurs inside an open Portal DB transaction;
- fenced lease prevents stale reconciliation commit;
- manual review never directly sets entitlement active;
- cross-repo integration proves Capability Manifest, AccessSnapshot,
  invalidation, paid quota, and UsageEvent paths together;
- architecture checks prevent LBX/future-provider concepts from leaking into
  Platform Kernel or generic Portal domain/application packages.

## Explicit non-goals

MVP does not:

- make Platform Kernel a billing client;
- make Payments Portal a second commercial catalog, payment orchestrator, or
  financial ledger;
- call payment-specific LBX REST APIs;
- implement Portal-owned card/payment-method, autopay, invoice, payment-history,
  or billing-cabinet UI where LBX Widget provides it;
- allow Widget subscription create/edit in the AnyToolAI MVP flow;
- require a fixed exact Widget top-up amount;
- support bundles/all-access/multiple products per offer;
- support multiple access-producing subscriptions per user/product;
- support allowance stacking, duplicate metric sources, or shared metric across
  products;
- support paid overage;
- support Portal-initiated upgrade/downgrade/refund/dispute/commercial trial;
- create or auto-bind an external customer solely to deliver a gift to an
  unmapped user;
- auto-bind unknown external customers using PII;
- define Dodo-specific behavior before its adapter is designed;
- require a dedicated manual-review admin UI;
- decide MoR, 54-FZ, or retention policy without Legal/Finance confirmation;
- preserve old direct-payment-provider data/schema compatibility.

## Resulting bounded contexts

```text
External Billing / LBX Widget
  owns commercial catalog and billing lifecycle
  + balances/payment UX/payment methods/autopay
  + invoices/payment history/customer billing self-service
  + customer-initiated cancellation

Payments Portal
  owns AnyToolAI identity and legal acceptance
  + external-billing anti-corruption layer
  + catalog/subscription projections
  + immutable versioned capability mappings
  + PurchaseIntent/customer correlation
  + reconciliation/discovery/recovery/manual review
  + entitlements and purchased allowances
  + AccessSnapshot/access revision/invalidation
  + usage delivery mediation when required

Platform Kernel
  owns technical product/metric vocabulary
  + actual usage and durable UsageEvent outbox
  + runtime quota enforcement
  + execution

Platform Kernel never calls External Billing directly.
Payments Portal never calls payment-specific provider APIs.
RU billing/payment self-service is LBX Widget with create/edit disabled and is
subject to the dedicated-agreement production validation gate.
```