# External billing boundary and Payments Portal redesign

Status: review requested after fourth external-review amendments
Date: 2026-09-15

## Goal

Redesign Payments Portal around a strict bounded-context split:

- External Billing owns the commercial billing domain;
- Payments Portal owns AnyToolAI identity plus the anti-corruption, projection,
  reconciliation, recovery, entitlement, and billing-integration boundary;
- Platform Kernel owns technical product/metric vocabulary, actual usage,
  runtime quota enforcement, and execution;
- Platform Kernel never communicates directly with LBX, Dodo, or any future
  billing provider.

The repository has not been deployed to production. The current Portal-owned
commerce/direct-payment schema is disposable. After the mandatory LBX Phase 0
feasibility gate succeeds, this design uses a clean pre-production reset rather
than a backward-compatible data migration.

MVP intentionally supports independent purchase of one existing Platform product
at a time. Bundles, overlapping paid subscriptions for the same product,
allowance stacking, paid overage, upgrade/downgrade, in-place commercial
re-consent, and provisional quota rollover are deferred.

## Canonical documentation precedence

This design supersedes conflicting semantics in ADR 0002, ADR 0004, and related
canonical documentation, including:

- Portal-owned `Product`, `Plan`, `PlanLimit`, and commercial `Order` as purchase
  authority;
- `Plan.id` as exact commercial purchase identity;
- recurring/commercial consent bound to `Plan.id`;
- direct payment-provider orchestration by Payments Portal;
- Portal-owned payment-method, autopay, invoice, payment-history, or billing
  cabinet UI where the external billing provider supplies those capabilities.

Replacement semantics are:

- Platform Kernel owns `product_id` and `metric_key` vocabulary;
- External Billing owns offers, prices, periods, subscriptions, balances,
  payments, refunds, payment methods, autopay, invoices, and billing lifecycle;
- Payments Portal projects external offers as `billing_offer` and identifies the
  material commercial version by `offer_id + commercial_fingerprint`;
- `PurchaseIntent` is orchestration state, not a commercial Order;
- AnyToolAI commercial/legal acceptance is bound to the current material offer
  fingerprint and exact required legal-document versions;
- payment and billing self-service UX are provider-owned.

Before implementation is considered complete, ADRs, billing-authority docs,
data-model docs, reliability docs, Platform Kernel quota/access docs, legal-flow
docs, and README guidance must describe one coherent model. A superseding ADR
may record this decision.

The clean Alembic reset is an explicit pre-production exception to any older
"baseline frozen / forward-only" migration convention. It MUST NOT happen until
the Phase 0 LBX feasibility gate defined below passes.

## Architectural invariants

### Ownership

External Billing owns commercial billing truth. For RU this is LBX. EU/US may
use Dodo or another provider behind the same Portal boundary. External Billing
owns, as applicable:

- commercial products/services, tariffs, periods, package composition, prices,
  discounts, sellability, and commercial allowance rules;
- subscription lifecycle, agreements or equivalent provider contracts;
- balances, charges, billing calculations, and financial blocking;
- payment initiation/UX, acquiring, payment methods, and autopay;
- refunds and dispute/chargeback consequences as represented by the provider;
- invoices, billing documents, money/payment history, billing customer profile,
  billing notifications, and billing self-service UI.

Payments Portal owns:

- canonical AnyToolAI user identity, registration, authentication/session, and
  AnyToolAI legal acceptance;
- verified mapping between Portal users and external billing customers;
- read-only local projections of external catalog and subscription facts;
- immutable/versioned mapping between external billing components and Platform
  technical capabilities;
- `PurchaseIntent` and provider-owned customer-interaction orchestration;
- durable external-operation recovery, customer discovery, reconciliation,
  webhook ingestion, work queues, and manual review;
- normalized product grants and authoritative purchased-allowance projections;
- vendor-neutral `AccessSnapshot` and access invalidation toward Platform Kernel;
- conditional usage-delivery integration only when an external tariff actually
  requires metering.

Platform Kernel owns:

- technical `product_id` registry;
- technical `metric_key` registry, with each metric owned by exactly one
  `product_id`;
- actual runtime usage and remaining-quota calculation;
- runtime quota policy/enforcement;
- scenario/workflow/action execution;
- an optional durable usage outbox only when an enabled offer requires external
  metering.

Payments Portal never becomes the source of truth for actual runtime usage or
remaining runtime quota.

### One-way billing dependency

Platform Kernel never receives provider credentials or provider-specific IDs and
never calls External Billing directly.

```text
External Billing
      |
      | catalog/customer/subscription APIs
      | webhooks + provider-owned billing UI
      v
Payments Portal
      |
      | AccessSnapshot / AccessInvalidation
      v
Platform Kernel
```

If and only if an enabled offer requires external metering, an additional path
may exist:

```text
Platform Kernel -> durable UsageEvent -> Payments Portal -> provider adapter
```

### Strict payment boundary

Payments Portal does not call payment-specific REST APIs. It does not create a
payment, submit/calculate a payment amount as payment authority, choose an
acquirer, save a card/payment method, enable or retry autopay, issue a refund,
or use payment status as an access-granting fact.

Portal may call non-payment External Billing APIs needed to establish or
reconcile commercial structure: customer ensure/recovery, catalog reads,
provider-specific agreement/subscription preparation, authoritative
subscription reads/discovery, and conditional safe usage reporting.

For RU, the selected billing/payment surface is **LBX Widget**. There is no
fallback to Portal-orchestrated `/eps_payments` or another payment REST flow.
Failure of the LBX feasibility gate blocks the rewrite/launch rather than
weakening this boundary.

### Commercial facts versus derived paid access

External commercial/subscription facts change only after a complete,
successfully normalized authoritative provider read. Portal never invents
provider lifecycle, financial state, subscription composition, terminal dates,
commercial quantities, or billing-cycle boundaries.

Derived paid access may change only because of:

1. a complete successfully normalized authoritative provider snapshot;
2. deterministic passage of time across a boundary already contained in trusted
   facts, which may only reduce/expire access;
3. an explicit audited operator resolution/rebind that selects/rebinds
   already-authoritative facts and then returns through normal derivation.

No Portal-local mechanism may create or increase paid quota without a new
authoritative provider fact. In particular, MVP has **no provisional allowance
rollover** at a billing-period boundary.

A local catalog row, webhook, Widget/browser callback, successful outbound POST,
payment fact, agreement creation, or `PurchaseIntent` state is never by itself
access authority.

## MVP commercial scope

MVP supports one existing Platform product per offer:

```text
Product A -> Offer A -> Subscription A
Product B -> Offer B -> Subscription B
```

For one `(user_id, product_id)` there may be at most one selected
access-producing billable subscription. A user may own different products
independently.

MVP does not support:

- bundles/all-access or one offer granting multiple products;
- multiple access-producing subscriptions for one user/product;
- allowance stacking;
- one metric shared by multiple products;
- multiple source components for one metric in one concrete subscription;
- paid overage;
- upgrade/downgrade flows;
- in-place re-consent for material changes to a live customer-funded
  subscription;
- provisional renewal quota while the next provider billing cycle is
  unconfirmed.

## Phase 0: LBX feasibility gate before destructive implementation

The LBX assumptions below are architectural prerequisites, not end-of-project
QA. Before deleting the old commerce model, resetting Alembic, implementing the
new production adapter, or building Kernel paid-access integration, run a
throwaway/integration spike against a real LBX test environment.

Each probe result is recorded with evidence status:

```text
DOCUMENTED        = supported by public/provider documentation only
VENDOR_CONFIRMED  = explicitly confirmed by LBX/vendor for our deployment
CONFIRMED_ON_TEST = reproduced on the real test stand
```

Launch-critical properties require `CONFIRMED_ON_TEST`.

### Phase 0 A: Widget and agreement isolation

Prove:

- authenticated Widget rendering with the supported script and real signing
  secret/configuration;
- Portal-like non-payment preparation of customer -> dedicated agreement ->
  subscription;
- `disableCreateSubscription=true` and `disableEditSubscription=true` actually
  prevent bypass of Portal fixed-offer scope;
- two agreements under one customer are accounting-isolated: funding Agreement
  A cannot make Agreement B commercially/access eligible;
- autopay/payment-method behavior is isolated to the intended agreement;
- cancellation/stop of Agreement/Subscription A cannot mutate B;
- a freshly prepared but unpaid subscription is distinguishable as
  access-ineligible via ordinary authoritative subscription/billing facts;
- underpayment remains access-ineligible;
- sufficient funding through Widget makes only the intended subscription
  access-eligible without Portal querying payment-specific endpoints.

### Phase 0 B: prepared commercial terms and later mutation

Prove that Portal can authoritative-read back the prepared commercial state
before opening Widget and compare material terms/components with the accepted
offer.

Run at least these mutation probes:

```text
1. prepare subscription S from tariff T
2. authoritative-read S
3. change source tariff T
4. authoritative-read S again
```

and, where LBX permits operator editing:

```text
1. prepare S
2. mutate S/operator-side material terms
3. authoritative-read S again
```

The architecture passes only if material changes either do not affect the
already-prepared subscription or are unambiguously visible through the
non-payment authoritative APIs Portal is allowed to use. A provider-side change
that can alter customer obligation/access while remaining invisible to those
reads is a blocker.

### Phase 0 C: authoritative allowance semantics

For every metered MVP offer, prove the authoritative sources for:

```text
quantity
period_start
period_end
cycle_identity
component/source identity
```

Prefer a native stable provider cycle/period identifier. If LBX has no native
cycle ID, a derived identity is acceptable only when test evidence proves that
the chosen fields are authoritative and stable across rereads and financial
block/unblock, and change only on an actual new billing cycle.

The mandatory end-to-end probe is:

```text
1. prepare subscription
2. make it commercially eligible through Widget
3. authoritative-read cycle C1, quantity Q, interval [T1, T2)
4. materialize Portal allowance A1 for C1
5. consume N units in Kernel from A1
6. cause financial/access blocking in LBX
7. authoritative-read and prove the cycle is still C1
8. remove blocking
9. authoritative-read and prove cycle/quantity/interval are still C1/Q/[T1,T2)
10. prove Portal still resolves C1 -> A1 and Kernel still has used=N
11. trigger/wait for real renewal
12. authoritative-read a distinct cycle C2 with its authoritative quantity and
    interval
13. prove C2 -> new allowance A2 and A2 starts with zero Kernel usage
14. reread C2 repeatedly and prove every reread resolves to the same A2
```

PASS requires `CONFIRMED_ON_TEST` that:

- quantity is authoritative;
- period boundaries are authoritative and stable for an already-published cycle;
- same-cycle reread is distinguishable from renewal;
- financial block/unblock does not look like renewal;
- the same cycle keeps the same `allowance_id`;
- only a confirmed new cycle creates a new `allowance_id`.

For each fact, Phase 0 records the exact LBX endpoint/field(s) used as evidence.
The design intentionally does not guess those field names in advance.

If a metered offer lacks provable cycle/quantity semantics, that offer is
`NOT_SELLABLE`. An unmetered paid offer may still be sellable if the other gates
pass.

### Phase 0 D: discovery consistency semantics

Determine and record the actual consistency model of customer-scoped
subscription enumeration:

```text
SNAPSHOT_CONSISTENT
EVENTUALLY_CONSISTENT
```

Probe at least:

- sort-order stability;
- offset versus cursor/keyset pagination;
- insert/delete behavior between pages;
- availability of snapshot/version/as-of token;
- stable `created_at`/`updated_at` or equivalent monotonic markers;
- visibility delay after successful create/read;
- whether webhook may precede listing visibility;
- whether the expected MVP customer cardinality can be returned safely in one
  request/page.

Reaching the last page is not by itself evidence of an atomic external snapshot.
The Portal algorithm below adapts to the proven provider mode.

### Phase 0 failure policy

Failure of a launch-critical gate means:

```text
STOP external-billing rewrite implementation
NO fallback to /eps_payments
NO Portal-owned payment orchestration
escalate provider capability gap
```

A second pre-production gate repeats the critical probes against the actual
deployed configuration as regression/launch evidence.

## LBX Widget as RU billing cabinet

Public LBX Widget documentation describes an embedded authenticated customer
window able to show subscriptions, create/edit/stop subscriptions, top up a
selected agreement balance, accept a customer-entered payment amount, manage
autopay/payment method, generate/view invoices, and show money movement.
Configuration includes flags such as `disableCreateSubscription`,
`disableEditSubscription`, `disableStopSubscription`, `disableAutopayments`,
`disablePayments`, `disableInvoiceGeneration`, `hideInvoicesList`, and
`hideSubscriptionsList`.

Documentation basis:

- https://docs.lbxbilling.ru/integration_lbx/widget/
- https://docs.lbxbilling.ru/integration_lbx/widget/widget_connection/

Target MVP configuration:

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

Portal does not treat hidden controls as a security boundary; Phase 0 and the
pre-production gate must prove effective restrictions.

Widget owns customer-facing billing self-service for payment/top-up,
payment-method/card entry and storage, autopay, subscription/balance display,
invoices, payment/money history, and customer-initiated cancellation.

Portal keeps AnyToolAI identity/legal acceptance, fixed-offer selection,
purchase uniqueness, lazy external-customer ensure, dedicated
agreement/subscription preparation via non-payment APIs, discovery,
reconciliation, mappings, entitlements, allowances, AccessSnapshot, and Kernel
invalidation.

Portal-owned payment form, card UI, autopay UI, invoice/payment-history UI, and
"payment success" page semantics are removed. Post-Widget UX reports access
activation/reconciliation state.

### Native agreement-balance model

MVP accepts the provider-native balance top-up model. The user may enter an
amount and LBX may recommend one. Portal does not require or submit an exact
payment amount.

Safety depends on dedicated-agreement accounting isolation:

- underpayment must not grant access;
- sufficient funding may enable only the intended subscription;
- overpayment may remain on that dedicated agreement for future billing;
- Portal does not model agreement balance.

For LBX MVP:

```text
1 Portal User = 1 LBX Customer per billing account
1 paid AnyToolAI subscription = 1 dedicated LBX Agreement
renewal of same subscription reuses that Agreement
new subscription = new dedicated Agreement
```

This cardinality is adapter-specific, not a provider-neutral domain concept.

## Platform capability manifest

Platform Kernel is the source of truth for technical product and metric
vocabulary and publishes a versioned read-only internal manifest, conceptually:

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

`manifest_version` changes deterministically on semantic changes. Kernel
validation enforces `metric_key -> exactly one product_id`.

Portal imports the manifest into a local read-only projection. MVP defaults:

```text
refresh ~= every 5 minutes + startup
capability_manifest_max_age_for_new_sales = 24h
```

On import failure Portal keeps the last-known-good manifest. Older than 24h
blocks new purchases but does not revoke existing pinned subscriptions.
`enabled=false` blocks new sales/mappings that depend on that capability but
does not silently revoke historical paid access.

Every published mapping revision records the manifest version against which it
was validated.

```text
Capability Manifest = what technical capabilities exist
AccessSnapshot       = what this user may use now
```

## External catalog and mapping model

### Fixed one-product offers

Every sellable MVP tariff/period is projected as a fixed `billing_offer`.
Customers cannot alter tariff, service composition, or component quantity in
Portal's purchase flow.

An offer is sellable only if:

- it resolves to exactly one unique `product_id`;
- every mapped `metric_key` belongs to that product;
- every external component is explicitly classified;
- no two source components resolve to the same `metric_key`;
- the provider's metering requirement is explicitly classified;
- every metered allowance has Phase-0-proven quantity/cycle semantics;
- any provider-required external usage-reporting capability is implemented and
  proven safe.

Component classification is:

```text
UNCLASSIFIED
CAPABILITY_BEARING
COMMERCIAL_ONLY
```

`UNCLASSIFIED` makes dependent offers `NOT_SELLABLE`.
`CAPABILITY_BEARING` requires one or more technical bindings.
`COMMERCIAL_ONLY` intentionally has no technical bindings. Missing mapping is
never interpreted as commercial-only.

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

One external component may bind to a product and one or more metrics owned by
that product. Published revisions are immutable; later changes create revision
N+1.

Publication is a privileged Product/Engineering operation, not Sales free-form
editing and not inference from `outer_id`. MVP may use a controlled admin
command/API rather than a UI. Publication validates against the current
capability manifest and records actor, timestamp, reason, and manifest version.

Sales/Finance may create commercial services/tariffs in LBX, but until a valid
mapping is published the component remains `UNCLASSIFIED` and dependent offers
are not sellable.

### Purchase-time mapping snapshot

For Portal-initiated purchases, mapping is pinned **when `PurchaseIntent` is
created**, not when the subscription is first reconciled.

The same local transaction stores an immutable purchase-time component snapshot,
conceptually:

```text
purchase_intent_components
  purchase_intent_id
  external_component_ref
  commercial_quantity
  mapping_revision_id
  resolved_product_id
  resolved_metric_keys / allowance semantics
```

A later mapping revision N+1 cannot change the technical meaning of an existing
PurchaseIntent. A subscription linked to that intent inherits these pinned
mapping revisions.

`mapping_revision_id` itself is not part of the user's legal/commercial
fingerprint. The fingerprint represents material semantics: target product,
price/currency, billing period/recurrence, component/allowance composition, and
material renewal/cancellation terms. A purely internal revision change that
preserves those semantics does not require renewed user consent.

### Subscription-component pinning outside purchase flow

For an admissible externally-created subscription without PurchaseIntent, each
previously unresolved component may be resolved once using the then-active
mapping and is then permanently pinned. A current/sellable Portal offer is not
required for such an already-existing subscription; access derives from the
actual authoritative component composition plus pinned mappings and legal/origin
rules in this spec.

Future mapping publication, retirement, manifest staleness, or `enabled=false`
does not silently rewrite/revoke an already-pinned historical interpretation.
Changing an already-pinned revision requires an explicit audited rebind.

If an authoritative subscription later removes a pinned component, the
corresponding derived grant/allowance is removed through normal reconciliation.

Several components may map to the same `product_id`; product grants use set/union
semantics. A concrete subscription may not have more than one source component
for one `metric_key`. If it does, that metric gets no allowance,
`allowance_conflict` enters manual review, and unrelated unambiguous
capabilities may continue.

## Target Payments Portal data model

Exact SQL names/types may follow repository conventions, but the semantic
entities and constraints are required.

### Identity and legal

Retain Portal-owned `users`, authentication/session state, versioned legal
documents, and append-only legal acceptances. `users.id` is canonical AnyToolAI
identity. Email is an attribute, never a cross-system identity key.

### External billing accounts and customer slot

`external_billing_accounts` identifies provider/system, contour/region,
environment/account key, and enabled state. Secrets are not persisted there.

`external_billing_customers` is a durable customer slot with uniqueness:

```text
(external_billing_account_id, user_id) UNIQUE
```

The slot is committed **before** any external customer create call and contains
an immutable stable opaque `recovery_key`. Only the owner of the unique
unresolved ensure-customer operation may create externally. Concurrent Product
A/Product B purchases reuse/wait on the same slot.

Conceptual states:

```text
provisioning | ready | unknown | manual_review | failed
```

A timeout/lost response becomes `unknown` and blocks another create until
recovery/manual resolution. Failed rows are retained/reopened, not deleted and
recreated. After binding:

```text
(external_billing_account_id, provider_customer_id) UNIQUE
```

External customer provisioning is lazy: Portal registration alone creates no
LBX customer. Normal customer creation occurs only after a commercial action has
passed the required legal barrier. Email changes update the same mapped customer
where needed; they never create a new identity.

### Catalog projections

Portal stores read-only projections of technical manifest facts, external
components, immutable mappings, billing offers, offer components, material
commercial fingerprint, source versions, sellability, metering classification,
and sync timestamps.

### PurchaseIntent and interaction state

There is no Portal-owned commercial `Order`.

`PurchaseIntent` records that a user began buying an exact accepted offer
version. It contains at least:

- `user_id`, billing account, `product_id`, `billing_offer_id`;
- accepted `commercial_fingerprint` and relevant material commercial snapshot;
- immutable purchase-time component/mapping snapshot;
- client idempotency identity;
- orchestration state and timestamps;
- optional linked external subscription once proven.

Separate orchestration from customer-interaction lifetime.

Conceptual orchestration states:

```text
created
preparing
awaiting_external_result
linked
resolved_no_external_effect
failed_before_external_effect
manual_review
```

Conceptual interaction states:

```text
not_ready | available | expired
```

Widget/UX expiry does not resolve external uncertainty and does not release the
business purchase scope.

### Purchase scope and business uniqueness

`Idempotency-Key` handles retransmission of one public request. Business
uniqueness is `(user_id, product_id)`.

At most one scope-holding PurchaseIntent exists for a user/product. The scope is
held across `unknown`, `ambiguous`, expired interaction, and any state from
which an external commercial effect may still appear.

When a real non-terminal subscription is linked, scope ownership transfers from
the PurchaseIntent to that subscription. A prepared-but-unpaid linked
subscription therefore still blocks a second purchase.

Purchase scope can become available only when:

- provider-specific recovery proves `resolved_no_external_effect`;
- failure happened before any external mutation/effect was possible;
- the linked subscription becomes terminal and no unresolved competing flow
  remains;
- an explicit audited resolution proves release is safe.

Browser timeout or missing callback is never proof that no external effect
exists.

### Subscription projection

`billing_subscriptions` exists only for a proven external subscription. External
uniqueness includes:

```text
(external_billing_account_id, external_subscription_id) UNIQUE
```

Normalized access-relevant facts are deliberately small, conceptually:

```text
lifecycle_status:          active | inactive | ended
financial_access_status:   allowed | blocked
commercial_access_status:  eligible | ineligible
```

The provider adapter may derive the normalized tuple from provider-specific
fields, but access requires a successfully normalized favorable state. Creation
of a subscription does **not** imply `eligible`.

Unknown access-relevant provider semantics are not stored as normal business
statuses. They are normalization errors; the last known-good projection may be
preserved only inside its finite trust lease. No prior good state means no
access. A known blocked state stays blocked.

`billing_subscription_components` projects actual component composition and
stores pinned mapping revision IDs.

Multiple external subscription rows may coexist for audit/conflict handling,
but at most one may be selected as access-producing for `(user_id, product_id)`.

### Entitlements and authoritative purchased allowances

`entitlements` materializes vendor-neutral product grants.

`purchased_allowances` materializes **authoritatively confirmed provider billing
cycles only**. Every allowance has:

```text
allowance_id              # stable opaque Portal UUID
product_id
metric_key
quantity
period_start
period_end
provider_cycle_key        # internal/provider-specific, never Kernel-facing
source subscription/component linkage
```

The invariant is:

```text
one authoritative provider billing cycle
  <-> one stable provider_cycle_key
  <-> one Portal allowance_id
  <-> one Kernel usage bucket
```

Repeated reads of the same cycle preserve the same `allowance_id`. Financial
block/unblock within the same cycle also preserves the same allowance and Kernel
usage. Only an authoritatively confirmed new provider cycle creates a new
allowance ID.

Once an allowance has been published to Kernel, its `period_start` and
`period_end` are immutable in MVP. A later authoritative read claiming different
boundaries for the same provider cycle is `allowance_cycle_conflict`; Portal does
not silently rewrite the bucket.

Historical allowance rows are retained/addressable; they are not physically
deleted merely because a period ended.

Portal does not persist authoritative runtime `remaining`. Platform Kernel owns
actual usage and computes remaining quota from the allowance quantity and its
own durable usage state.

### Durable reliability state

`billing_operations` is the journal for non-idempotent external mutations and
uses states such as:

```text
pending | in_progress | succeeded | unknown | ambiguous | failed | manual_review
```

The operation exists before network side effects. Timeout/lost response becomes
`unknown`; recovery lookup occurs before any retry. No external network request
runs inside an open database transaction.

For the LBX adapter, recovery identity is stable and operation-specific:

```text
customer     -> Portal-generated stable recovery/outer key
agreement    -> mapped customer + stable agreement number/key
subscription -> agreement_id + stable Portal external key
```

Recovery result semantics are:

```text
0 matches  -> controlled retry only when the adapter can prove retry is safe
1 match    -> bind the existing provider object
>1 matches -> ambiguous/manual_review; never guess
```

`billing_webhook_inbox` stores every authenticated HTTP delivery separately with
Portal-generated `delivery_id`. `payload_hash` is diagnostic, not a uniqueness
key.

`billing_work_items` is the durable PostgreSQL work queue.
`manual_review_cases` is separate operational state with subject, reason, owner,
status, timestamps, resolution, and actor/audit details.

## Legal barrier and commercial fingerprint

Before a normal user-funded `PurchaseIntent` is created, Portal verifies all
currently-required AnyToolAI legal acceptance for the exact material offer
version.

Acceptance is bound to:

```text
user_id
region
billing_offer_id
commercial_fingerprint
required legal-document versions
acceptance kind
timestamp/audit metadata
```

The fingerprint covers material user-facing semantics including:

- price and currency;
- billing cadence/recurrence;
- customer payment obligation;
- material renewal/cancellation semantics;
- target product;
- capability-bearing component composition;
- included metric set;
- allowance quantity/policy;
- tariff/service semantics used to derive access.

Operational fields such as provider internal IDs, invoice/order numbers,
reconciliation timestamps, current cycle timestamps, generated document
references, cosmetic names/descriptions, and internal technical metadata are not
material by themselves.

Changed material terms produce `offer_changed` before purchase or
`commercial_terms_conflict` after a subscription has been prepared/linked.
Cosmetic-only changes do not change the fingerprint.

Portal owns AnyToolAI legal acceptance. Provider/payment infrastructure owns
payment-method/acquiring/autopay consent. Portal never infers permission to
charge from its own checkbox.

MVP does not support in-place re-consent for a materially changed live
customer-funded subscription. The normal business path is to end/cancel the old
subscription, publish/sync the new offer, and complete a new ordinary purchase
with new acceptance after safe scope release.

Erasure/retention, merchant-of-record, fiscal/54-FZ responsibility, and exact
legal retention periods remain Legal/Finance decisions; this technical design
does not invent them.

## Purchase and commercial preparation flow

### Offer validation and mapping pin

Browser submits only Portal opaque identifiers, such as:

```text
offer_id
commercial_fingerprint shown to the user
Idempotency-Key
```

It never submits authoritative provider IDs, price, payment amount, or period.

Portal validates capability-manifest freshness, catalog freshness, sellability,
current fingerprint, legal acceptance, and `(user, product)` uniqueness.

In the same transaction that creates PurchaseIntent, Portal pins the exact
mapping revisions and accepted component snapshot.

### Provider-neutral preparation

```text
validate offer + legal + purchase scope
 -> create PurchaseIntent + mapping snapshot
 -> ensure/recover external customer
 -> prepare/recover dedicated agreement/subscription via non-payment provider API
 -> authoritative read-back of prepared commercial state
 -> compare prepared state with accepted snapshot
 -> only if exact material match: expose CustomerInteraction / LBX Widget
 -> discover/reconcile authoritative subscription state
 -> derive access only from authoritative eligible facts
```

`CustomerInteraction` types are:

```text
embedded_external | redirect_external | none
```

There is no `portal_managed` payment interaction.

### Prepared-state read-back before Widget

Successful create response is insufficient. Before Widget is exposed, Portal
must authoritative-read the prepared external commercial object(s) and compare
material terms with the PurchaseIntent snapshot.

Comparison covers all material facts that the provider exposes/derives,
including tariff/offer identity, billing period/recurrence, component set,
component quantities, currency/price basis where authoritative provider facts
permit it, and allowance semantics used by the accepted fingerprint.

If facts differ after an external object may already have been created:

```text
DO NOT open Widget
DO NOT grant access
DO NOT blindly recreate
keep (user, product) scope held
prepared_commercial_mismatch -> recovery/manual_review
```

An unexpected component in initial Portal-initiated preparation is also a
commercial snapshot mismatch; it is not automatically interpreted using the
latest mapping.

Phase 0 must prove LBX exposes sufficient authoritative facts for this read-back.

### Commercial fingerprint remains an access invariant after Widget

The prepared-state read-back is not the last fingerprint check. For a normal
customer-funded Portal subscription, every access-relevant authoritative read
that can activate or continue paid access reconstructs the observed material
commercial fingerprint and compares it with the accepted PurchaseIntent
fingerprint.

This includes:

- first post-payment/eligible reconciliation;
- later authoritative reads inside the current cycle;
- every confirmed renewal/new-cycle reconciliation.

Access requires both:

```text
authoritative subscription is commercially eligible
AND
observed_commercial_fingerprint == accepted_commercial_fingerprint
```

A material mismatch at any later point becomes `commercial_terms_conflict`:

```text
DO NOT automatically accept the changed terms
DO NOT grant/continue paid access from the changed commercial state
increment access_revision if previously usable access changes
open manual review
```

The Portal does not try to determine whether a changed price/allowance is
"better" or "worse" for the user. Customer-funded live subscriptions must not
be materially edited in place by Sales/Finance in LBX for MVP.

Normal passage from one billing cycle to the next does not itself change the
fingerprint because cycle timestamps are operational facts, not accepted
commercial semantics.

### Prepared-but-unpaid invariant

Creation/preparation of customer, agreement, or subscription never grants
access. Widget callback, payment event, or balance change does not directly
grant access either.

Access appears only after an ordinary authoritative provider read satisfies the
provider-validated normalized commercial-access criterion and the commercial
fingerprint invariant above. Phase 0 must prove that prepared/unpaid and
underpaid cases remain ineligible and that sufficient funding becomes eligible
without Portal payment API calls.

If LBX cannot expose such a distinction, RU launch is blocked; Portal does not
compensate by tracking payment status itself.

## Webhooks

Webhook handling is intentionally short:

```text
authenticate
 -> minimally validate/extract safe correlation hints
 -> generate delivery_id
 -> persist inbox row
 -> enqueue/coalesce reconciliation work
 -> commit
 -> return 2xx
```

No provider REST call occurs inside the webhook request. Payload contents never
directly mutate entitlement. Duplicate/out-of-order deliveries are safe.
Coalescing occurs at reconciliation-work level, not by deleting delivery rows.
Authentication failure creates no trusted inbox work and emits security
telemetry.

Scheduled discovery/reconciliation remains the correctness backstop.

## Discovery, reconciliation, and freshness

### Customer-scoped discovery

`PurchaseIntent` is not a prerequisite for `billing_subscription`. Every mapped
external customer is periodically enumerated for subscriptions. Unknown external
customers are never auto-bound by email, phone, or name.

Default discovery cadence:

```text
stable mapped customer             every 6h
recent/changed mapped customer      every 5m
open PurchaseIntent                 adaptive 1-5m
valid webhook hint                  immediate/high priority
manual-review/ambiguous recovery    dedicated recovery policy
```

Workers persist `last_discovery_at`, `next_discovery_at`, priority, and result so
restarts preserve cadence.

A current catalog offer is not required for an already-existing discovered
subscription. The actual authoritative component composition plus pinned
mapping/legal/origin rules decide access.

An optional account-wide scan may detect orphan provider customers/subscriptions,
but it is audit/manual-review input only and never grants access or PII-binds an
unknown external customer.

Sales/Finance manual creation for an already-mapped LBX customer must follow the
same dedicated-Agreement isolation rule; it must not create a second LBX customer
for the Portal user.

### Known-subscription authoritative reconciliation

Known access-relevant subscriptions are authoritative-read independently of
customer discovery.

MVP defaults:

```text
normal authoritative reconciliation = every 15m
provider outage retry                = 1m -> 2m -> 5m -> 15m -> 15m ... + jitter
remaining trust <= 30m               = max 5m between retries
after trust expiry                   = continue retry <= 5m until recovery
```

Only a complete successfully normalized authoritative read updates commercial
facts and **extends trust**.

For each subscription projection:

```text
last_authoritative_read_at
projection_valid_until = last_authoritative_read_at + 6h
```

`subscription_projection_trust_ttl = 6h` is the MVP default and is configurable.

The following do NOT extend `projection_valid_until`:

- reading Portal's local database/projection;
- issuing another AccessSnapshot;
- webhook or Widget callback;
- PurchaseIntent activity;
- failed/partial provider requests;
- normalization errors/unknown semantics;
- manual-review activity.

At `projection_valid_until`, access derived from that stale provider projection
fails closed until a new complete successfully normalized authoritative read
succeeds.

### Fenced per-subscription reconciliation lease

A PostgreSQL fenced lease prevents stale workers from applying old provider
reads:

1. short transaction claims owner, expiry, and monotonically increasing fencing
   token;
2. commit;
3. provider HTTP read with no DB transaction open;
4. new short transaction applies only if the same fencing token is current;
5. release/expire lease.

A worker whose lease was superseded cannot commit its older snapshot.

## First-primary selection and conflict semantics

Subscription reconciliation workers may classify/update candidate subscriptions,
but **may never establish the first primary** for `(user_id, product_id)`.

### Enumeration cycle semantics

Customer discovery uses explicit durable enumeration-cycle state, conceptually:

```text
discovery_cycle
  customer_id
  started_at
  completed_at
  provider_consistency_mode
  status = collecting | resolving | complete | failed
```

A cycle is `complete` only when the listing operation itself reached its normal
end and every relevant observed candidate obtained enough authoritative data to
classify it. `complete` does **not** claim the external provider supplied an
atomic snapshot unless Phase 0 proved `SNAPSHOT_CONSISTENT` semantics.

A partial list, failed candidate read, or normalization uncertainty means the
first-primary decision is deferred.

### First-primary under SNAPSHOT_CONSISTENT enumeration

If Phase 0 proves a provider snapshot/version/as-of mechanism, one completed
provider snapshot is enough. With no prior trusted primary, the finalizer
atomically evaluates the candidate set for `(user, product)`:

```text
0 eligible candidates   -> no primary
1 eligible candidate    -> select it as first primary
>=2 eligible candidates -> select none; subscription_conflict/manual_review
```

### First-primary under EVENTUALLY_CONSISTENT enumeration

If LBX does not guarantee snapshot-consistent listing, Portal explicitly does
not pretend that reaching the final page is a historical snapshot.

For MVP, first-primary selection requires **two agreeing completed enumeration
passes** separated by a configurable stability interval:

```text
first_primary_stability_delay = 30 seconds   # MVP default
```

The two passes must agree on the relevant candidate identity and access
classification for the product scope. Examples:

```text
pass A: {S1 eligible}
pass B: {S1 eligible}
=> stable observation; S1 may be selected atomically
```

```text
pass A: {S1 eligible}
pass B: {S1 eligible, S2 eligible}
=> not stable; restart confirmation; no primary
```

```text
pass A: {S1 blocked}
pass B: {S1 eligible}
=> not stable; restart confirmation; no primary
```

A trusted webhook hint or known completed external create/recovery for that
customer between the two passes invalidates the stability attempt and schedules
a fresh enumeration.

This is a bounded stabilization rule, not a claim of mathematically complete
knowledge of concurrent external mutations. If a provider object was invisible
to both passes and appears later, it is handled as a later conflict under the
rules below.

### Atomic finalization by `(user, product)`

A product-access scope row/lock serializes finalization:

```text
(user_id, product_id) UNIQUE
primary_subscription_id nullable
decision_generation
```

`primary_subscription_id` may first transition `NULL -> subscription_id` only
through:

- successful atomic finalization under the proven snapshot-consistent mode; or
- successful atomic finalization after the required stable two-pass observation
  under eventually-consistent mode; or
- explicit audited `accept_subscription_as_primary` resolution.

`PurchaseIntent` correlation does not allow bypassing a real conflicting
subscription.

If a trusted primary already existed and a later discovery finds another
eligible subscription, the trusted primary continues within its normal trust
rules; the newcomer produces no additional access and opens conflict review.

If the selected primary later becomes blocked/ineligible, Portal does not
automatically promote another candidate. Access follows the selected primary's
authoritative state. If the selected primary becomes terminal and the selection
is cleared, any future first selection again follows the applicable discovery
consistency rule or explicit audited resolution.

No heuristic selection by age, amount, agreement order, worker completion order,
or another convenience rule is allowed.

## Inbound/manual/comp subscriptions and legal semantics

Automatic identity correlation for externally-created subscriptions is allowed
only through an existing verified Portal user <-> external-customer mapping.
Unknown provider customers are orphan/manual-review subjects and are never bound
by PII.

MVP does not create or auto-bind a new provider customer solely to deliver a
Sales/Finance gift.

For an already-mapped user:

- ordinary customer-funded discovered subscription without corresponding valid
  Portal purchase/legal acceptance does not automatically create paid access;
  it is `external_unknown`/manual review;
- an operator comp/gift may bypass PurchaseIntent only when a trusted audited
  operator classification establishes that it creates no customer payment
  obligation and no customer-authorized recurring/autopay obligation;
- comp/gift still requires current baseline AnyToolAI legal documents needed to
  use the service; absent acceptance holds access until completed.

Manual review never directly sets `entitlement=active`; it selects/resolves
authoritative facts and returns through normal derivation.

## Normalization uncertainty

Unknown access-relevant provider semantics are integration failure, not business
lifecycle status.

```text
provider response
 -> normalization_error
 -> preserve last-known-good projection only inside existing trust lease
 -> alert + retry/manual review
```

Rules:

- previously allowed state may survive only until existing
  `projection_valid_until`;
- previously blocked state remains blocked;
- no previous valid state means no access;
- uncertainty never increases access;
- irrelevant unknown optional provider fields may be ignored.

## Subscription lifetime and authoritative allowance periods

Subscription lifetime and quota period are distinct:

```text
subscription terminal boundary != allowance.period_end
```

An open-ended recurring subscription does not lose its product grant merely
because one allowance period ended.

### Product-grant time semantics

`grant.valid_until` means known terminal lifecycle boundary only.

For open-ended recurring subscriptions:

```text
grant.valid_until = null
```

`null` never means infinite trust; snapshot expiry and Portal provider-fact trust
still apply. `allowance.period_end` must never be copied into
`grant.valid_until`.

All intervals are UTC half-open `[start, end)`.

### No provisional quota rollover in MVP

Before an expected allowance boundary, Portal raises reconciliation priority so
that the next provider cycle is ideally confirmed before the current
`allowance.period_end`.

However, pre-boundary reconciliation is only a latency optimization. If the next
provider cycle has not been authoritatively confirmed when the current allowance
ends:

```text
current allowance expires
NO new allowance is invented
NO renewal grace quota is created
Kernel performs mandatory boundary refresh
if no authoritative next allowance exists -> new metered paid usage fails closed
```

An open-ended product grant may still remain valid inside the subscription's
normal provider-fact trust lease, but absence of an authoritative next allowance
means the metered capability has no new quota bucket yet.

When LBX later recovers and confirms a genuinely new provider cycle, Portal
creates its new authoritative allowance, increments `access_revision`, sends the
normal invalidation hint, and Kernel resumes consumption after refresh.

### Stable cycle identity and immutable published bucket

For a metered allowance, Portal resolves an internal provider cycle key from the
Phase-0-proven provider facts. Preferred identity is a native provider cycle ID.
A derived key is allowed only if Phase 0 proved its stability.

Same provider cycle means same `allowance_id`, including across financial
block/unblock and repeated authoritative reads. A confirmed new cycle means a
new `allowance_id` and a fresh Kernel usage bucket.

Once published to Kernel, the following are immutable for that allowance in MVP:

```text
allowance_id
product_id
metric_key
period_start
period_end
provider cycle identity linkage
```

If the provider later reports different period boundaries for the same cycle,
Portal records `allowance_cycle_conflict`, does not rewrite the existing bucket,
and does not create a replacement full bucket automatically. Further
consumption that depends on ambiguous cycle semantics fails closed pending
recovery/manual resolution.

A quantity or other material allowance-policy change within the same live cycle
is a `commercial_terms_conflict`, not a silent quota correction.

## AccessSnapshot contract and Kernel cache

Conceptual vendor-neutral snapshot:

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

No provider tariff/service/agreement/subscription/payment IDs or provider
statuses cross this boundary.

MVP cache defaults:

```text
refresh_after = now + 1 minute
expires_at    = min(now + 5 minutes, relevant Portal projection trust deadline)
```

Known grant and allowance temporal boundaries remain independent semantic
constraints; an allowance is usable only inside `[period_start, period_end)`.

Kernel behavior:

- before `refresh_after`, cached snapshot may be used if no semantic boundary
  has been crossed;
- between `refresh_after` and `expires_at`, Kernel attempts refresh but may use
  cache if Portal is temporarily unavailable and relevant intervals remain
  valid;
- at/after `expires_at`, cached paid access fails closed;
- crossing `grant.valid_until`, `allowance.period_start`, `allowance.period_end`,
  or another access-relevant temporal boundary requires synchronous snapshot
  refresh before the next paid decision;
- Kernel never creates paid allowance periods itself;
- if an allowance ended and Portal cannot provide an authoritative next bucket,
  metered paid usage fails closed;
- guest/free Kernel-owned functionality is independent of paid billing outage.

Portal may continue to serve last-known-good subscription facts while they are
inside `projection_valid_until`. The 5-minute Kernel expiry is only the maximum
Kernel autonomy from Portal; it is not LBX billing grace and does not extend the
Portal provider-fact lease.

## Access revision and invalidation

Any material access projection change, positive or negative, increments the
user's monotonically increasing `access_revision` and enqueues durable Kernel
invalidation in the same local transaction.

Examples include:

- new paid grant after authoritative activation;
- blocked -> allowed or allowed -> blocked;
- new authoritative allowance cycle;
- allowance/grant removal;
- subscription end;
- `commercial_terms_conflict` or `allowance_cycle_conflict` affecting access;
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

## Platform Kernel paid quota semantics

A paid allowance from AccessSnapshot supplies the purchased limit. Kernel owns
durable actual usage and performs atomic runtime consumption. Portal is not
called synchronously on every action/scenario execution.

For an allowance:

```text
remaining = max(0, current allowance quantity - durable Kernel usage for allowance_id)
```

Kernel hard-stops when remaining is zero. There is no paid overage.

`allowance_id` is required even when no external usage reporting exists because
it is the stable identity of one authoritative billing-cycle quota bucket.

Production-safe quota concurrency must be proven on PostgreSQL: concurrent
requests cannot consume beyond the allowance; restart preserves consumption;
replayed/idempotent execution must not double-consume according to Kernel's
runtime idempotency model.

## Conditional external metering / UsageEvent

The baseline paid MVP does **not** require a Kernel -> Portal UsageEvent pipeline
unless a selected external tariff actually requires reporting runtime usage back
to the provider.

Each normalized offer has provider-derived metering classification:

```text
external_usage_reporting = none | required | unknown
```

`unknown` is fail-closed for new sales; Portal never silently interprets an
unclassified tariff as `none`.

For `none`:

```text
Kernel persists actual usage and enforces hard quota locally
NO UsageEvent outbox required
NO Portal usage-ingestion endpoint required
```

For `required`, the offer is `NOT_SELLABLE` until the complete metering path is
implemented and proven safe. Browser/client input never controls this flag.

When that conditional capability is implemented, the previously agreed safety
rules are normative:

- paid quota consumption and durable Kernel UsageEvent outbox insertion are one
  transaction;
- Portal ingests idempotently by globally unique `usage_event_id`;
- processed result is `accepted`, `duplicate`, or `rejected_permanent`;
- permanent semantic rejection is durably recorded and terminal, not retried
  forever;
- retryable infrastructure failures leave the Kernel event pending;
- rejected usage never refunds actual Kernel usage/quota;
- historical allowances remain addressable long enough for late delivery;
- a provider metering call with non-idempotent uncertain outcome is never blind
  retried; if idempotency/recovery cannot be proven, dependent offers stay
  `NOT_SELLABLE`.

Do not build this distributed subsystem in the baseline MVP merely for future
possibility.

## Commercial lifecycle scope

Portal command orchestration supports only **buy one product**.

Other operations are observed but not Portal-commanded:

- cancellation: via LBX Widget/cabinet where supported or Support/Finance in
  LBX; Portal reconciles authoritative result;
- upgrade/downgrade: unsupported; end current subscription, then buy another
  offer after safe scope release;
- refunds/disputes/chargebacks: provider/payment concern; Portal reacts only to
  authoritative subscription consequences;
- commercial paid trial: unsupported in Portal; free/guest policy belongs to
  Kernel; any future recurring trial must be provider-modeled separately.

Material in-place modification of a live customer-funded LBX subscription is
also unsupported in MVP. If it occurs externally, Portal detects the resulting
fingerprint mismatch and fails closed rather than silently accepting new terms.

## Manual review

`manual_review` is operational workflow, never access authority.

Each case records subject, reason code, status, owner kind, timestamps, explicit
resolution, actor, and audit details.

Typical owners:

- duplicate/conflicting subscription -> Finance/Billing Ops;
- ambiguous external create/recovery -> Billing Ops;
- unknown external customer -> Support/Billing Ops;
- unmapped/unclassified component or duplicate metric source ->
  Product/Engineering;
- unknown provider semantics -> Engineering/on-call;
- invalid capability mapping -> Product/Engineering;
- prepared-commercial mismatch -> Billing Ops + Engineering;
- commercial-terms or allowance-cycle conflict -> Billing Ops + Engineering.

Allowed controlled resolutions include binding an already-proven external object
to an existing operation, marking duplicate/conflict, audited mapping rebind,
`accept_subscription_as_primary`, reject conflict, or mark unknown customer
unmatched.

MVP does not include PII-based `bind_external_customer_to_user`. Operators never
directly set entitlement active. Dedicated admin UI is not required; durable
records, alerts, runbook, and controlled admin command/API are sufficient.

## Provider abstraction

Application/domain code depends on small capability-oriented ports for:

- external catalog reads;
- external customer ensure/recovery;
- non-payment commercial preparation;
- provider-owned customer interaction;
- authoritative subscription read;
- customer-scoped subscription enumeration with adapter-declared consistency
  semantics;
- webhook authentication/parsing;
- optional usage reporting.

There is no generic payment-command capability in Payments Portal.
Provider-specific concepts such as LBX Agreement, tariff/service APIs, `state`,
`current_blocking`, Widget mechanics, balances, provider cycle identity, and
recovery lookup remain in provider integration packages and never leak into
Platform Kernel.

## Portal <-> Platform Kernel implementation contract

This is a cross-repository implementation stream. Baseline MVP completion
requires both repositories to implement and contract-test:

| Contract | Producer/source | Consumer | MVP |
| --- | --- | --- | --- |
| Capability Manifest | Platform Kernel | Payments Portal | required |
| AccessSnapshot | Payments Portal | Platform Kernel | required |
| AccessInvalidation | Payments Portal | Platform Kernel | required |
| UsageEvent | Platform Kernel | Payments Portal | conditional on metered offer |

Each wire payload has `schema_version`. Consumers fail clearly on unsupported
major versions. Do not introduce a shared runtime Python package coupling the
repos; use versioned HTTP/JSON contracts and contract tests on both sides.

Required Kernel work:

- canonical metric registry and Capability Manifest endpoint;
- AccessSnapshot client/cache and boundary refresh;
- AccessInvalidation receiver keyed by `access_revision`;
- paid allowance integration into existing quota engine;
- durable actual usage by `allowance_id`.

Required Portal work:

- Capability Manifest importer;
- AccessSnapshot producer;
- monotonic revision + durable invalidation delivery;
- provider projection/reconciliation semantics defined in this spec.

UsageEvent outbox/ingestion/dead-letter work is added only when an enabled MVP
offer requires external metering.

Baseline cross-repo proof:

```text
subscription becomes eligible
 -> Portal AccessSnapshot revision N
 -> Kernel authorizes product
 -> Kernel consumes allowance durably
 -> Portal access changes to revision N+1
 -> invalidation reaches Kernel
 -> Kernel refetches N+1
 -> next runtime decision uses N+1
```

Failure proof includes Portal outage beyond snapshot expiry, LBX outage with
Portal still inside provider-fact trust lease, provider-fact trust expiry, and
allowance-boundary refresh with no authoritative next cycle.

## Worker topology and transactions

MVP runs a durable billing worker embedded in the Payments Portal API process
with one API replica initially. Correctness-critical work lives in PostgreSQL,
not in-memory queues or FastAPI `BackgroundTasks`.

Worker/use-case logic is independent of FastAPI composition so it can later move
to a separate process. Queue claims, discovery finalization, product-scope
selection, and reconciliation leases must be multi-consumer safe even though the
initial deployment has one replica.

External network requests never run inside open DB transactions. Transactions
are short and cover local intent/state creation, claims/leases, durable operation
state, and atomic projection/access updates.

RabbitMQ/Kafka is not required for MVP.

## Security and PII

Provider credentials, webhook secrets, Widget signing secrets, and payment
credentials live only in runtime secret configuration. They are not stored in
billing-account rows, domain objects, logs, or browser-visible responses.

Capability/access/invalidation internal APIs use TLS, explicit service
authentication, and tenant/region scope. User authentication alone is not enough.
One regional contour never reads/writes another contour's billing/access data.

Only minimum provider-required billing PII is transmitted/stored. Email, phone,
and name are never automatic cross-system identity authority.

Reverse-proxy/access logs must not leak webhook query secrets, Widget signing
material, or auth data. Raw provider-payload retention requires explicit
redaction/retention policy.

## Observability and audit

Use non-PII correlation identifiers such as request ID, user ID,
PurchaseIntent ID, billing operation ID, webhook `delivery_id`, work item ID,
subscription ID, `allowance_id`, discovery cycle ID, product access-scope
revision, and safe opaque provider references.

At minimum monitor:

- capability-manifest/catalog age and sync failures;
- unclassified/invalid mappings and not-sellable reasons;
- customer ensure/recovery unknown/ambiguous state;
- manual-review count and oldest age by reason;
- normalization errors;
- discovery/reconciliation success/failure/duration;
- discovery stability retries and consistency mode;
- age since last authoritative subscription read and time to
  `projection_valid_until`;
- work-queue depth/oldest item;
- webhook auth failures/delivery lag;
- fresh/stale-usable/expired projections;
- commercial-terms conflicts and allowance-cycle conflicts;
- access-invalidation lag;
- provider latency/timeouts/error rate.

If conditional metering is enabled, also monitor usage-outbox lag and permanent
rejection rate.

Audit must explain why access changed and identify the authoritative read,
mapping revision/snapshot/rebind, discovery decision, manual resolution, or
commercial/cycle conflict involved without creating a shadow provider financial
ledger.

## Clean pre-production reset and implementation ordering

There is no production compatibility contract, but destructive rewrite begins
only after Phase 0 passes.

Implementation order:

0. **Run the complete Phase 0 LBX feasibility spike and record PASS evidence for
   Widget/agreement isolation, prepared-term visibility, authoritative allowance
   semantics for each metered MVP offer, and discovery consistency. If a
   launch-critical assumption fails, stop the rewrite.**
1. Supersede/update contradictory canonical ADR/docs in Portal and Kernel.
2. Remove obsolete Portal Product/Bundle/Plan/PlanLimit/Order and direct-payment
   orchestration semantics; replace the disposable Alembic baseline and recreate
   development/test DBs.
3. Implement Kernel capability/metric manifest and Portal importer.
4. Implement external catalog projection, controlled mapping publication, and
   purchase-time mapping snapshot.
5. Implement durable external-customer slot/recovery and LBX non-payment
   preparation.
6. Implement PurchaseIntent scope rules, prepared-state authoritative read-back,
   recurring commercial-fingerprint checks, and embedded Widget interaction.
7. Implement customer discovery with the Phase-0-proven consistency mode,
   first-primary finalization, fenced reconciliation, normalized access,
   conflict handling, and the 6h provider-fact trust lease.
8. Implement authoritative allowance-cycle identity/projection from the exact
   Phase 0 evidence; do not implement provisional rollover.
9. Implement Portal AccessSnapshot/revision/invalidation and Kernel consumer.
10. Integrate paid allowance into the existing Kernel quota engine with stable
    `allowance_id` per authoritative provider cycle.
11. If and only if an enabled offer requires external metering, implement the
    conditional UsageEvent pipeline before that offer becomes sellable.
12. Run cross-repo contract/integration proofs.
13. Repeat the LBX production gate against the deployed RU configuration before
    launch.

No dual-write old/new billing traffic split or compatibility layer is required.

## Required correctness tests and launch evidence

Implementation planning must include automated tests plus provider-validation
spikes proving at least:

- Phase 0 passes before destructive rewrite;
- Widget authenticated rendering and create/edit restrictions work;
- Agreement A funding/autopay/cancellation cannot affect Agreement B;
- prepared unpaid and underpaid subscriptions remain access-ineligible;
- sufficient Widget funding changes only the intended subscription to an
  authoritative access-eligible state without Portal payment API calls;
- prepared commercial read-back matches the accepted PurchaseIntent snapshot
  before Widget exposure;
- mutation of source tariff or operator-editable subscription terms is either
  isolated from the prepared subscription or visible in authoritative reads;
- first activation and each later renewal/access-relevant read recheck the
  accepted commercial fingerprint;
- material post-Widget change produces `commercial_terms_conflict` and cannot
  silently continue paid access;
- mapping revision N is pinned with PurchaseIntent and later N+1 does not change
  that intent/subscription meaning;
- material commercial change invalidates old acceptance while cosmetic-only copy
  change does not;
- same HTTP idempotency key creates one PurchaseIntent;
- different tabs/keys cannot create two purchase scopes for one `(user,product)`;
- Widget expiry does not release unresolved scope;
- linking a prepared-but-unpaid subscription transfers scope to that
  non-terminal subscription;
- customer slot exists before LBX create and parallel purchases cannot create
  two external customers;
- create timeout uses stable recovery key and never blind-retries;
- duplicate/out-of-order webhooks converge and retain distinct `delivery_id`s;
- missed webhook is repaired by scheduled discovery/reconciliation;
- Phase 0 classifies discovery as snapshot-consistent or eventually-consistent;
- snapshot mode evaluates one complete provider snapshot atomically for first
  primary;
- eventual-consistency mode requires two agreeing completed passes separated by
  the stability delay;
- webhook/known external mutation between the two passes invalidates the
  stability attempt;
- candidate worker completion order does not establish first primary;
- incomplete enumeration or unresolved candidate cannot establish first primary;
- two eligible first-seen candidates produce no primary and manual review;
- a later-visible conflicting subscription never adds access or replaces an
  established primary automatically;
- an ineligible/blocked selected primary does not auto-promote a competing
  subscription;
- `PurchaseIntent` never shortcuts a real subscription conflict;
- unknown provider customer never auto-binds by PII;
- comp/gift to unmapped user is unsupported;
- ordinary discovered customer-funded subscription without valid purchase/legal
  evidence does not auto-grant access;
- operator comp requires audited non-customer-funded classification and baseline
  legal acceptance;
- unclassified component, unknown external-usage-reporting classification,
  duplicate metric source, or unproven metered allowance semantics blocks new
  offer sale;
- mapping revisions are immutable and already-pinned subscription mappings do
  not change silently;
- explicit audited rebind is required to change a pinned mapping;
- `projection_valid_until = last_authoritative_read_at + 6h` and only successful
  complete normalized provider read extends it;
- local snapshot issuance/webhook/callback/failed read never extends provider
  trust;
- known active subscription reconciliation normally runs every 15m with defined
  outage backoff/near-expiry urgency;
- access fails closed after projection trust expiry even if Portal itself is
  healthy;
- open-ended grant uses `valid_until=null`, and allowance period end alone does
  not end product grant;
- Phase 0 proves authoritative quantity, period boundaries, source identity, and
  cycle identity for every metered offer;
- same provider cycle reread keeps the same `allowance_id`;
- block/unblock in the same cycle keeps the same `allowance_id` and already-used
  Kernel quantity;
- only confirmed new provider cycle creates a new `allowance_id` with fresh
  Kernel usage;
- changed boundaries for an already-published same cycle cause
  `allowance_cycle_conflict` rather than in-place rewrite;
- changed quantity/policy within the same accepted live cycle causes
  `commercial_terms_conflict` rather than silent quota correction;
- if no authoritative next cycle exists at `allowance.period_end`, Kernel
  boundary refresh finds no new bucket and new metered usage fails closed;
- later authoritative confirmation of the next cycle creates one new bucket and
  usage resumes without changing historical usage;
- every material positive or negative access change increments
  `access_revision` and durably invalidates Kernel cache;
- lost invalidation still fails closed by snapshot expiry/boundary rules;
- PostgreSQL concurrent paid usage cannot exceed allowance and restart preserves
  used quantity;
- offers with `external_usage_reporting=required` remain `NOT_SELLABLE` until the
  complete conditional UsageEvent path is implemented and safe;
- if conditional UsageEvent is enabled, quota+outbox are atomic, Portal ingestion
  is idempotent, permanent rejects terminate retry without refunding runtime
  usage, and unsafe provider metering blocks sale;
- no provider network call occurs inside an open DB transaction;
- fenced reconciliation lease prevents stale workers committing old reads;
- manual-review resolution never directly grants entitlement;
- architecture checks prevent provider-specific concepts/imports from leaking
  into Platform Kernel or generic Portal domain/application packages.

## Explicit non-goals

MVP does not:

- make Platform Kernel a billing client;
- make Payments Portal a second commercial catalog, financial ledger, or payment
  orchestrator;
- call payment-specific LBX REST APIs;
- build Portal-owned card/payment/autopay/invoice/payment-history UI where Widget
  provides it;
- allow Widget subscription create/edit in the fixed-offer flow;
- require a fixed exact Widget top-up amount;
- support bundles/all-access, multiple products per offer, overlapping
  access-producing subscriptions, allowance stacking, duplicate metric sources,
  shared metrics, or paid overage;
- support Portal-initiated upgrade/downgrade/refund/dispute/commercial trial;
- support in-place re-consent/material modification of a live customer-funded
  subscription;
- create provisional renewal allowances during provider outage;
- auto-bind unknown external customers using PII;
- create a provider customer solely for an unmapped gift recipient;
- require a manual-review admin UI;
- implement UsageEvent delivery when no enabled MVP offer requires external
  metering;
- decide merchant-of-record, 54-FZ, or legal retention policy without
  Legal/Finance confirmation;
- preserve legacy direct-payment-provider data/schema compatibility after the
  Phase 0 gate has passed.

## Resulting bounded contexts

```text
External Billing
  commercial catalog and billing lifecycle
  provider-owned balance/payment/autopay/refund/invoice/self-service UX

Payments Portal
  AnyToolAI identity and legal acceptance
  external-billing anti-corruption layer
  local catalog/subscription projections
  immutable versioned capability mappings + purchase-time mapping snapshot
  durable operation recovery and customer discovery with proven consistency mode
  access-source conflict finalization and manual review
  bounded provider-fact trust lease
  authoritative allowance-cycle projection
  entitlements and AccessSnapshot + AccessInvalidation
  optional usage-delivery mediation only when a tariff requires it

Platform Kernel
  technical product/metric vocabulary
  durable actual usage by allowance_id
  runtime quota enforcement
  execution
  optional UsageEvent outbox only for externally-metered offers
```

Platform Kernel never calls External Billing directly.
Payments Portal never calls payment-specific provider APIs.
RU billing interaction is LBX Widget, subject first to Phase 0 feasibility and
again to the final deployed-configuration production gate.
