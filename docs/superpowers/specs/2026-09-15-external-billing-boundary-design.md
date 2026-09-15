# External billing boundary and Payments Portal redesign

Status: review requested after fifth external-review amendments  
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

Every sellable offer resolves to exactly one `product_id`. It may carry zero or
more usage metrics, but every `metric_key` belongs to that one product.

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
quantity per metric
period_start
period_end
cycle_identity
component/source identity
metric/source binding
```

Prefer a native stable provider cycle/period identifier. If LBX has no native
cycle ID, a derived identity is acceptable only when test evidence proves that
the chosen fields are authoritative and stable across rereads and financial
block/unblock, and change only on an actual new billing cycle.

This is a provider-semantics spike, not production Kernel implementation. It may
use a throwaway probe ledger/harness to represent stable metric-specific
`allowance_id` values and already-consumed quantities while testing LBX
transitions.

At least one probe must use a subscription/cycle with two independent metric
allowances whenever the selected LBX tariff model can represent such a case. If
LBX represents the metrics through different components, the test uses those
actual provider components; the Portal invariant remains metric-specific.

Mandatory probe shape:

```text
1. prepare subscription S
2. make S commercially eligible through Widget
3. authoritative-read cycle C1 and its metric allowances, for example:
     generations quantity=1000 interval=[T1,T2)
     exports     quantity=100  interval=[T1,T2)
4. allocate stable probe IDs:
     (S, source X, generations, C1) -> G1
     (S, source X-or-Y, exports, C1) -> E1
5. record independent probe usage:
     G1 used=300
     E1 used=20
6. cause financial/access blocking in LBX
7. authoritative-read and prove C1/source/metric identities remain the same
8. remove blocking
9. authoritative-read again and prove:
     G1 is still G1 and used=300
     E1 is still E1 and used=20
10. trigger/wait for real renewal
11. authoritative-read distinct cycle C2
12. prove metric-specific new IDs:
     generations -> G2, G2 != G1, used=0
     exports     -> E2, E2 != E1, used=0
13. reread C2 repeatedly and prove each metric resolves to its same ID
```

PASS requires `CONFIRMED_ON_TEST` that:

- quantity is authoritative for every metric source;
- period boundaries are authoritative and stable for an already-published cycle;
- same-cycle reread is distinguishable from renewal;
- financial block/unblock does not look like renewal;
- repeated reads preserve the same `allowance_id` **per metric/source/cycle**;
- different metrics in one cycle retain independent usage buckets;
- only a confirmed new cycle creates new allowance IDs for those metrics.

For each fact, Phase 0 records the exact LBX endpoint/field(s) used as evidence.
The design intentionally does not guess those field names in advance.

If a metered offer lacks provable cycle/quantity/source semantics, that offer is
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
The provider-neutral design supports both modes, but after Phase 0 the RU LBX
implementation MUST implement only the mode actually confirmed for LBX. The
alternative mode remains a future-adapter requirement and must not be built only
for hypothetical reuse.

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
- the provider's external-metering requirement is explicitly classified;
- any provider-required metering capability is actually implemented and proven
  safe.

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
  id
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

Creation of a subscription does **not** imply `eligible`.

Unknown access-relevant provider semantics are not stored as ordinary business
statuses. They are normalization errors; the last-known-good projection may be
preserved only inside its finite trust lease. No prior good state means no
access. A known blocked state stays blocked.

`billing_subscription_components` projects actual component composition and
stores pinned mapping revision IDs.

Multiple external subscription rows may coexist for audit/conflict handling,
but at most one may be selected as access-producing for `(user_id, product_id)`.

### Entitlements and authoritative purchased allowances

`entitlements` materializes vendor-neutral product grants.

`purchased_allowances` materializes **authoritatively confirmed metric quota
buckets**. One provider billing cycle may yield zero, one, or many allowances.
Every allowance belongs to exactly one `metric_key`.

Conceptual fields:

```text
allowance_id                         # stable opaque Portal UUID
billing_subscription_component_id    # exact concrete provider source
mapping_revision_id                  # exact pinned interpretation
mapping_binding_id                   # exact metric binding where applicable
product_id
metric_key
provider_cycle_key                   # internal/provider-specific, never Kernel-facing
quantity
period_start
period_end
```

Logical identity is:

```text
(
  external billing account,
  external subscription,
  concrete subscription component/source,
  metric_key,
  provider_cycle_key
)
  <-> exactly one allowance_id
```

Because the component row already links to subscription and billing account, the
practical relational guard may be:

```text
UNIQUE (
  billing_subscription_component_id,
  metric_key,
  provider_cycle_key
)
```

The invariant is therefore:

```text
one authoritative provider billing cycle
  -> 0..N metric allowance buckets

one metric/source/cycle tuple
  <-> one stable Portal allowance_id
  <-> one independent Kernel usage bucket
```

Repeated reads of the same provider cycle preserve each metric-specific
`allowance_id`. Financial block/unblock within that same cycle also preserves
those IDs and Kernel usage. Only an authoritatively confirmed new provider cycle
creates new metric-specific allowance IDs.

Once an allowance has been published to Kernel, its `period_start` and
`period_end` are immutable in MVP. A later authoritative read claiming different
boundaries for the same provider cycle is `allowance_cycle_conflict`; Portal does
not silently rewrite the bucket.

Historical allowance rows are retained/addressable; they are not physically
deleted merely because a period ended.

Portal does not persist authoritative runtime `remaining`. Platform Kernel owns
actual usage and computes remaining quota independently for every
`allowance_id`.

### Product access scope and decision generation

For every `(user_id, product_id)`, Portal owns a durable product access scope,
conceptually:

```text
billing_product_access_scope
  user_id
  product_id
  primary_subscription_id nullable
  decision_generation bigint
```

with:

```text
UNIQUE(user_id, product_id)
```

`decision_generation` is a monotonic **invalidation epoch for the evidence used
to select the primary subscription**. It is not merely a count of completed
decisions.

It increments in the same local transaction whenever a fact changes that can
change primary-selection validity, including:

- candidate subscription appears/disappears for the scope;
- candidate resolves to or away from this product;
- candidate eligibility/lifecycle/financial/commercial classification changes;
- mapping rebind changes candidate product/capability interpretation;
- primary is selected or cleared;
- an operator resolves/rejects a conflict or otherwise changes source selection.

A trusted provider-change hint also invalidates pending first-primary decisions.
If a valid webhook is correlated to one product scope, increment that scope. If
it is correlated only to the mapped customer, conservatively increment all
first-primary-pending/unresolved product scopes for that customer and enqueue
fresh discovery.

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

The fingerprint covers material user-facing/commercial semantics including:

- price and currency;
- billing cadence/recurrence;
- customer payment obligation;
- target Platform product;
- subscription component composition;
- included metric set and allowance quantities/policies;
- material renewal/cancellation terms.

Provider internal IDs, invoice/order numbers, current cycle timestamps, generated
document references, reconciliation timestamps, cosmetic names/descriptions, and
other operational metadata do not by themselves change the fingerprint.

### Commercial terms remain invariant for a live customer-funded subscription

The accepted fingerprint is not checked only before Widget. Portal reconstructs
an `observed_commercial_fingerprint` from every complete access-relevant
authoritative provider read and requires:

```text
observed_commercial_fingerprint == accepted_commercial_fingerprint
```

This check applies:

- during prepared-state read-back before Widget;
- on the first authoritative read that would make the subscription access
  producing;
- on every later access-relevant read, including renewal/new-cycle reads.

A normal next billing cycle with unchanged commercial semantics does not change
the fingerprint merely because `period_start`/`period_end` advanced.

Any material mismatch creates `commercial_terms_conflict`, blocks paid access
from that subscription, increments `access_revision`, and enters manual review.
MVP does not attempt to determine whether the new terms are financially better
or worse for the customer.

MVP does **not** support in-place re-consent for a live customer-funded
subscription. A planned material commercial change requires ending/canceling the
old subscription and a normal new offer/purchase/acceptance flow. Sales/Finance
must not material-edit a live customer-funded subscription and expect automatic
continuation.

Portal owns AnyToolAI legal acceptance. Provider/payment infrastructure owns
payment-method/acquiring/autopay consent. Portal never infers permission to
charge from its own checkbox.

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

In the same transaction that creates `PurchaseIntent`, Portal pins the exact
mapping revisions and accepted component snapshot.

### Provider-neutral preparation

```text
validate offer + legal + purchase scope
 -> create PurchaseIntent + mapping snapshot
 -> ensure/recover external customer
 -> prepare/recover dedicated agreement/subscription via non-payment provider API
 -> authoritative read-back of prepared commercial state
 -> compare prepared state with accepted snapshot/fingerprint
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
permit it, target technical product through the pinned mapping, and allowance
semantics used by the accepted fingerprint.

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

Phase 0 must prove LBX exposes sufficient authoritative facts for this read-back
and for detecting later material mutation.

### Prepared-but-unpaid invariant

Creation/preparation of customer, agreement, or subscription never grants
access. Widget callback, payment event, or balance change does not directly
grant access either.

Access appears only after an ordinary authoritative provider read satisfies the
provider-validated normalized commercial-access criterion **and** the observed
commercial fingerprint still matches the accepted fingerprint.

If LBX cannot expose the unpaid/ineligible versus sufficiently-funded/eligible
distinction without payment APIs, RU launch is blocked; Portal does not
compensate by tracking payment status itself.

## Webhooks

Webhook handling is intentionally short:

```text
authenticate
 -> minimally validate/extract safe correlation hints
 -> generate delivery_id
 -> persist inbox row
 -> invalidate any affected first-primary decision generation
 -> enqueue/coalesce reconciliation/discovery work
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
subscription. Actual authoritative component composition plus pinned
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

At `projection_valid_until`, paid access derived from that stale provider
projection fails closed until a new complete successfully normalized
authoritative read succeeds.

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

### Provider consistency mode

Phase 0 classifies the provider enumeration mode.

#### SNAPSHOT_CONSISTENT

If the provider supplies a proven snapshot/version/as-of mechanism, first-primary
evidence is built from one completed provider snapshot plus the authoritative
candidate reads tied to that observation.

#### EVENTUALLY_CONSISTENT

If no snapshot-consistency guarantee exists, Portal requires two agreeing
completed enumeration observations before a first-primary decision. MVP default:

```text
first_primary_stability_delay = 30s
```

The two observations must agree on the decision-relevant candidate set and
state. Any known provider-change hint between them invalidates the attempt and
forces a new observation sequence.

Two-pass stabilization does not claim mathematical snapshot consistency. It is a
bounded eventual-consistency safety check. A later-visible conflicting
subscription is handled as a newcomer conflict and never stacks/replaces access
automatically.

For RU LBX, production implementation builds only the mode proven in Phase 0.
Future providers may add a different strategy behind the same provider-neutral
contract.

### Decision attempts, generations, and candidate digest

Each first-primary decision attempt stores immutable evidence metadata,
conceptually:

```text
primary_decision_attempt
  user_id
  product_id
  evidence_reference          # snapshot/pass ids as applicable
  expected_generation
  candidate_set_digest
  state = ready | superseded | finalized | failed
```

`candidate_set_digest` covers at least the decision-relevant normalized facts:

```text
external_subscription_id
resolved product_id
eligibility classification
normalization/resolution status relevant to primary choice
```

After the provider evidence is complete, Portal opens a short local transaction,
locks the `(user_id, product_id)` access scope, verifies that the current local
candidate set still matches that evidence, records the current
`decision_generation` as immutable `expected_generation`, records the candidate
digest, marks the attempt ready, and commits.

Capturing generation at the start of a long network discovery is insufficient;
it is captured only after the decision evidence is ready and locally verified.

### Atomic finalization by `(user, product)`

The finalizer acquires the same product-access scope lock and must prove both:

```text
current decision_generation == attempt.expected_generation
AND
current candidate_set_digest == attempt.candidate_set_digest
```

If either check fails:

```text
attempt = superseded/stale
DO NOT choose primary
DO NOT replace expected_generation with the new generation
schedule/reuse fresh discovery evidence
```

If both checks pass, no primary exists, and all relevant candidates are resolved,
the finalizer evaluates atomically:

```text
0 eligible candidates   -> keep primary NULL
1 eligible candidate    -> select it as first primary
>=2 eligible candidates -> keep primary NULL; subscription_conflict/manual_review
```

Selection is not biased by worker completion order, subscription age, amount,
agreement ordering, or PurchaseIntent correlation.

When primary is selected, cleared, or explicitly changed by audited operator
resolution, `decision_generation` increments in the same transaction. Thus a
second pending finalizer built on the older generation automatically becomes
stale.

`primary_subscription_id` may first transition `NULL -> subscription_id` only
through:

- successful finalization satisfying the generation+digest checks and the
  provider-consistency strategy proven for that adapter; or
- explicit audited `accept_subscription_as_primary` resolution under the same
  product-scope lock/generation rules.

If a trusted primary already exists and later discovery finds another eligible
subscription, the trusted primary continues within its normal trust rules; the
newcomer produces no additional access and opens conflict review.

If the selected primary becomes blocked/ineligible, Portal does not automatically
promote another candidate. Access follows the selected primary's authoritative
state. If the primary becomes terminal and the selection is cleared,
`decision_generation` increments and any future automatic selection requires new
provider evidence/finalization.

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
  operator classification `subscription_origin=operator_comp` establishes that
  it creates no customer payment obligation and no customer-authorized
  recurring/autopay obligation;
- comp/gift still requires current baseline AnyToolAI legal documents needed to
  use the service; absent acceptance holds access until completed.

Conceptual origins:

```text
purchase | operator_comp | external_unknown
```

Origin is explicit trusted/audited local state; it is never inferred from price,
balance, or other financial heuristics.

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

## Subscription lifetime and allowance periods

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

Before an expected allowance boundary Portal raises reconciliation priority so
that the next provider cycle is ideally confirmed before the current
`allowance.period_end`.

If the current allowance expires and the provider has not authoritatively
confirmed the next cycle:

```text
product grant may remain valid if subscription trust/lifecycle still allow it
BUT
no new metric allowance exists
therefore metered paid usage fails closed at the old period_end
```

Portal never invents a future bucket from the previous cycle. When a later
complete authoritative read confirms a new provider cycle, Portal creates new
metric-specific allowance IDs, increments `access_revision`, invalidates Kernel,
and metered usage resumes after refresh.

Same-cycle financial unblock is not renewal and must reuse the same
metric-specific allowance IDs and Kernel counters.

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
      "valid_until": null
    }
  ],
  "allowances": [
    {
      "allowance_id": "opaque-uuid-generations",
      "product_id": "document-summary",
      "metric_key": "document-summary.generations",
      "quantity": 1000,
      "period_start": "...",
      "period_end": "..."
    },
    {
      "allowance_id": "opaque-uuid-exports",
      "product_id": "document-summary",
      "metric_key": "document-summary.exports",
      "quantity": 100,
      "period_start": "...",
      "period_end": "..."
    }
  ]
}
```

No provider IDs, LBX statuses, balances, payment states, or provider cycle keys
appear in this contract.

MVP defaults:

```text
refresh_after = now + 1m
expires_at = min(
  now + 5m,
  earliest relevant subscription projection_valid_until,
  known grant terminal boundary where present,
  relevant allowance temporal boundary where needed
)
```

For a multi-product user, one user snapshot expires no later than the earliest
relevant trust deadline among the paid facts included in the snapshot.

Portal cannot issue a new snapshot containing a paid fact after that fact's
`projection_valid_until` has expired.

Kernel treats an allowance as usable only while `now` belongs to its UTC
half-open period `[period_start, period_end)` and while the parent snapshot is
valid.

Kernel performs synchronous refresh when crossing an access-relevant temporal
boundary such as `grant.valid_until` or `allowance.period_end` before treating
absence of future access as final. If Portal is unavailable or cannot confirm a
new cycle, Kernel does not invent one and fails closed for the expired metric.

### Monotonic access revision and durable invalidation

Every material positive or negative access change increments a per-user
monotonic `access_revision` and atomically writes durable Kernel invalidation
work.

Material changes include at least:

- new paid grant after authoritative activation;
- blocked -> allowed or allowed -> blocked;
- new authoritative metric allowance cycle;
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

It never carries entitlement deltas. Multiple pending invalidations may coalesce
to the newest revision.

### Kernel revision floor prevents stale-response resurrection

Kernel keeps a monotonic `highest_seen_access_revision` **independently of the
cached snapshot** for each:

```text
(tenant_id, region, user_id)
```

This revision floor can only increase:

```text
floor = max(floor, invalidation.access_revision)
floor = max(floor, accepted_snapshot.access_revision)
```

Receiving invalidation revision `R` atomically:

```text
raise floor to at least R
if cached_snapshot.revision < floor:
    evict cached snapshot
```

Evicting the snapshot never erases the floor.

When an AccessSnapshot HTTP response arrives, Kernel must compare and install it
inside the same per-user coherence boundary used by invalidation:

```text
if response.access_revision < floor:
    reject response
    DO NOT cache it
    DO NOT authorize from it
else:
    floor = max(floor, response.access_revision)
    install response only if it cannot regress cached revision
```

The revision check, floor update, and cache installation must be atomic relative
to invalidation for that user. The implementation may use a lock, CAS, or shared
cache primitive; the contract requires the atomic semantics, not one library.

Therefore this race is forbidden:

```text
start fetch for revision N
 -> Portal commits access change N+1
 -> Kernel receives invalidation N+1 and evicts N
 -> delayed HTTP response N arrives
 -> N MUST be rejected and cannot resurrect old access
```

If Kernel already accepted a newer snapshot N+1, a later concurrent response N
is rejected by the same floor rule even when no invalidation was involved.

If Portal repeatedly returns a revision lower than Kernel's floor, Kernel never
downgrades. It retries according to bounded internal policy; if it cannot obtain
a snapshot `>= floor`, paid access fails closed.

An authorization/runtime action fully committed before an invalidation is not
retroactively canceled. The revision floor governs new authorization decisions
after the newer revision becomes known.

The revision floor and the snapshot cache must share one coherence domain. If a
future Kernel deployment has several cache-owning replicas, either invalidation
must reach every such replica or both cache and floor must be shared. A design in
which only one of several independent cache replicas receives invalidation is
invalid.

Lost invalidation is still tolerated because `refresh_after`, temporal-boundary
refresh, and `expires_at` remain correctness backstops.

## Platform Kernel paid quota semantics

A paid allowance from AccessSnapshot supplies one purchased metric limit. Kernel
owns durable actual usage and performs atomic runtime consumption. Portal is not
called synchronously on every action/scenario execution.

For each allowance independently:

```text
remaining = max(0, allowance.quantity - durable Kernel usage[allowance_id])
```

Kernel hard-stops when remaining is zero. There is no paid overage.

`allowance_id` is required even when no external usage reporting exists because
it is the stable identity of one **metric/source/provider-cycle** runtime quota
bucket.

Two metric allowances from the same provider billing cycle never share a runtime
counter. For example:

```text
generations allowance G1: quantity=1000, used=300, remaining=700
exports allowance E1:     quantity=100,  used=20,  remaining=80
```

Production-safe quota concurrency must be proven on PostgreSQL: concurrent
requests cannot consume beyond the relevant allowance; restart preserves
consumption; replayed/idempotent execution must not double-consume according to
Kernel's runtime idempotency model.

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

When that conditional capability is implemented, the safety rules are:

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

## Manual review

`manual_review` is operational workflow, never access authority.

Each case records subject, reason code, status, owner kind, timestamps, explicit
resolution, actor, and audit details.

Typical owners/reasons include:

- duplicate/conflicting subscription -> Finance/Billing Ops;
- ambiguous external create/recovery -> Billing Ops;
- unknown external customer -> Support/Billing Ops;
- unmapped/unclassified component or duplicate metric source ->
  Product/Engineering;
- unknown provider semantics -> Engineering/on-call;
- invalid capability mapping -> Product/Engineering;
- prepared-commercial mismatch -> Billing Ops + Product/Engineering;
- commercial-terms conflict -> Billing Ops + Product/Legal as appropriate;
- allowance-cycle conflict -> Billing Ops + Engineering.

Allowed controlled resolutions include binding an already-proven external object
to an existing operation, marking duplicate/conflict, audited mapping rebind,
`accept_subscription_as_primary`, reject conflict, or mark unknown customer
unmatched.

MVP does not include PII-based `bind_external_customer_to_user`. Operators never
directly set entitlement active. Dedicated admin UI is not required; durable
records, alerts, runbook, and controlled admin command/API are sufficient.

Operator actions that affect product-source selection run under the same
`billing_product_access_scope` lock and increment `decision_generation`, so a
pending automated finalizer cannot overwrite a more recent operator decision.

## Provider abstraction

Application/domain code depends on small capability-oriented ports for:

- external catalog reads;
- external customer ensure/recovery;
- non-payment commercial preparation;
- provider-owned customer interaction;
- authoritative subscription read;
- customer-scoped enumeration/discovery;
- webhook authentication/parsing;
- optional usage reporting.

There is no generic payment-command capability in Payments Portal.
Provider-specific concepts such as LBX Agreement, tariff/service APIs, `state`,
`current_blocking`, Widget mechanics, balances, provider cycle fields, and
recovery lookup remain in provider integration packages and never leak into
Platform Kernel.

The provider-neutral discovery port may support multiple consistency strategies,
but the RU LBX production adapter implements only the Phase-0-confirmed strategy.

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
- AccessSnapshot client/cache with monotonic per-user revision floor;
- AccessInvalidation receiver using the same cache/floor coherence boundary;
- temporal-boundary refresh;
- paid allowance integration into the existing quota engine;
- durable actual usage independently by metric-specific `allowance_id`.

Required Portal work:

- Capability Manifest importer;
- AccessSnapshot producer;
- monotonic revision + durable invalidation delivery;
- provider projection/reconciliation semantics defined in this spec.

UsageEvent outbox/ingestion/dead-letter work is added only when an enabled offer
requires external metering.

Baseline cross-repo proof:

```text
subscription becomes eligible
 -> Portal AccessSnapshot revision N
 -> Kernel authorizes product
 -> Kernel consumes metric allowance durably
 -> Portal access changes to revision N+1
 -> invalidation N+1 reaches Kernel and raises revision floor
 -> delayed N response cannot be cached or used
 -> Kernel refetches >= N+1
 -> next runtime decision uses >= N+1
```

Failure proof includes Portal outage beyond snapshot expiry, LBX outage with
Portal still inside provider-fact trust lease, trust-lease expiry, allowance
boundary refresh with no provisional quota, and multi-metric counter isolation.

## Worker topology and transactions

MVP runs a durable billing worker embedded in the Payments Portal API process
with one API replica initially. Correctness-critical work lives in PostgreSQL,
not in-memory queues or FastAPI `BackgroundTasks`.

Worker/use-case logic is independent of FastAPI composition so it can later move
to a separate process. Queue claims, discovery finalization, product-scope
decisions, and reconciliation leases must be multi-consumer safe even though the
initial deployment has one replica.

External network requests never run inside open DB transactions. Transactions
are short and cover local intent/state creation, claims/leases, durable operation
state, generation/digest decisions, and atomic projection/access updates.

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
subscription ID, metric-specific `allowance_id`, discovery evidence/attempt ID,
product access-scope generation, and safe opaque provider references.

At minimum monitor:

- capability-manifest/catalog age and sync failures;
- unclassified/invalid mappings and not-sellable reasons;
- customer ensure/recovery unknown/ambiguous state;
- manual-review count and oldest age by reason;
- normalization errors;
- discovery/reconciliation success/failure/duration;
- age since last authoritative subscription read and time to
  `projection_valid_until`;
- work-queue depth/oldest item;
- webhook auth failures/delivery lag;
- fresh/stale-usable/expired projections;
- commercial-terms and allowance-cycle conflicts;
- discovery attempts invalidated by generation/digest mismatch;
- access-invalidation lag and stale-snapshot rejection count;
- provider latency/timeouts/error rate.

If conditional metering is enabled, also monitor usage-outbox lag and permanent
rejection rate.

Audit must explain why access changed and identify the authoritative read,
mapping revision/snapshot/rebind, provider cycle/source, discovery decision,
generation, candidate digest, or manual resolution involved without creating a
shadow provider financial ledger.

## Clean pre-production reset and implementation ordering

There is no production compatibility contract, but destructive rewrite begins
only after Phase 0 passes.

Implementation order:

0. **Run Phase 0 LBX feasibility spike and record PASS evidence. If it fails,
   stop the rewrite.**
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
7. Implement the **single LBX discovery consistency strategy proven in Phase 0**,
   plus first-primary generation/digest finalization, fenced reconciliation,
   normalized access, conflict handling, and the 6h provider-fact trust lease.
8. Implement authoritative metric-specific allowance-cycle identity/projection
   from the exact Phase 0 evidence; do not implement provisional rollover.
9. Implement Portal AccessSnapshot/revision/invalidation and Kernel consumer with
   monotonic revision-floor race protection.
10. Integrate paid allowances into the existing Kernel quota engine with one
    independent usage bucket per metric-specific `allowance_id`.
11. If and only if an enabled offer requires external metering, implement the
    conditional UsageEvent pipeline before that offer becomes sellable.
12. Run cross-repo contract/integration proofs.
13. Repeat the LBX production gate against the deployed RU configuration before
    launch.

No dual-write old/new billing traffic split or compatibility layer is required.

## Required correctness tests and launch evidence

Implementation planning must include automated tests plus provider-validation
spikes proving at least:

- Phase 0 feasibility gate passes before destructive rewrite;
- Widget authenticated rendering and create/edit restrictions work;
- Agreement A funding/autopay/cancellation cannot affect Agreement B;
- prepared unpaid and underpaid subscriptions remain access-ineligible;
- sufficient Widget funding changes only the intended subscription to an
  authoritative access-eligible state without Portal payment API calls;
- source-tariff/operator material mutation is either isolated from the prepared
  subscription or visible in allowed authoritative reads;
- prepared commercial read-back matches the accepted PurchaseIntent snapshot
  before Widget exposure;
- prepared mismatch after external mutation does not open Widget, grant access,
  or blindly recreate, and keeps purchase scope held;
- accepted and observed commercial fingerprints are compared again on first
  activation and every later access-relevant/renewal read;
- material commercial mutation produces `commercial_terms_conflict` and no
  automatic in-place re-consent;
- mapping revision N is pinned with PurchaseIntent and later N+1 does not change
  that intent/subscription meaning;
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
- LBX discovery tests exactly the Phase-0-confirmed consistency mode rather than
  both hypothetical modes;
- worker completion order cannot directly establish first primary;
- stale first-primary attempt with old `expected_generation` cannot finalize
  after a newer discovery changes the candidate set;
- candidate digest mismatch blocks finalization even if a programming error were
  to leave generation unchanged;
- two concurrent finalizers with the same expected generation cannot both win:
  the first decision increments generation and the second becomes stale;
- a relevant webhook invalidates a waiting first-primary attempt before later
  reconciliation finishes;
- audited operator resolution increments generation and cannot be overwritten by
  an older automated finalizer;
- exactly one eligible candidate under valid current evidence may become primary;
- two eligible first-seen candidates produce no primary and manual review;
- an existing trusted primary continues when a later conflicting eligible
  subscription appears, while newcomer adds no access;
- an ineligible/blocked selected primary does not auto-promote a competing
  subscription;
- clearing a terminal primary increments generation and requires fresh evidence
  before any automatic replacement;
- `PurchaseIntent` never shortcuts a real subscription conflict;
- unknown provider customer never auto-binds by PII;
- comp/gift to unmapped user is unsupported;
- ordinary discovered customer-funded subscription without valid purchase/legal
  evidence does not auto-grant access;
- operator comp requires audited non-customer-funded classification and baseline
  legal acceptance;
- unclassified component, unknown metering classification, or duplicate metric
  source blocks new offer sale;
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
- no provisional allowance is created when provider confirmation of the next
  cycle is unavailable;
- at allowance period end, Kernel refreshes and fails closed for that metric if
  no authoritative new cycle exists;
- same-cycle reread preserves each metric-specific `allowance_id`;
- same-cycle block/unblock preserves each metric-specific ID and already-used
  Kernel amount;
- one provider cycle with at least two metrics produces two independent Kernel
  counters and no cross-metric consumption;
- a new provider cycle creates new IDs independently for each metric and starts
  each new Kernel usage bucket at zero;
- changed interval for an already-published same-cycle bucket produces
  `allowance_cycle_conflict` rather than silent rewrite;
- every material positive or negative access change increments
  `access_revision` and durably invalidates Kernel cache;
- delayed snapshot N arriving after invalidation N+1 is rejected, not cached,
  and not used for authorization;
- concurrent snapshot response N+1 followed by delayed N leaves floor/cache at
  N+1;
- Portal returning snapshots below Kernel's known floor cannot cause downgrade;
  paid access fails closed until a snapshot at or above the floor is obtained;
- revision-floor update, stale check, and cache installation are atomic relative
  to invalidation;
- lost invalidation still fails closed by snapshot expiry/boundary rules;
- PostgreSQL concurrent paid usage cannot exceed an allowance and restart
  preserves used quantity;
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
- implement both hypothetical discovery consistency strategies for LBX after
  Phase 0 has proven which one is actually required;
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
  durable external-operation recovery
  provider-mode-specific customer discovery
  generation/digest-protected access-source finalization
  bounded provider-fact trust lease
  entitlements and metric-specific authoritative allowances
  AccessSnapshot + AccessInvalidation
  optional usage-delivery mediation only when a tariff requires it

Platform Kernel
  technical product/metric vocabulary
  monotonic AccessSnapshot revision floor
  durable actual usage independently by allowance_id
  runtime quota enforcement
  execution
  optional UsageEvent outbox only for externally-metered offers
```

Platform Kernel never calls External Billing directly.  
Payments Portal never calls payment-specific provider APIs.  
RU billing interaction is LBX Widget, subject first to Phase 0 feasibility and
again to the final deployed-configuration production gate.
