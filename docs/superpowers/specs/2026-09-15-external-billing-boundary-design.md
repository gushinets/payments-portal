# External billing boundary and Payments Portal redesign

Status: review requested after sixth external-review amendments  
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
re-consent, dynamic/prorated quota, and provisional quota rollover are deferred.

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
- vendor-neutral `AccessSnapshot` and access invalidation toward Platform Kernel.

Platform Kernel owns:

- technical `product_id` registry;
- technical `metric_key` registry, with each metric owned by exactly one
  `product_id`;
- actual runtime usage and remaining-quota calculation;
- runtime quota policy/enforcement;
- scenario/workflow/action execution.

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

### Strict payment boundary

Payments Portal does not call payment-specific REST APIs. It does not create a
payment, submit/calculate a payment amount as payment authority, choose an
acquirer, save a card/payment method, enable or retry autopay, issue a refund,
or use payment status as an access-granting fact.

Portal may call non-payment External Billing APIs needed to establish or
reconcile commercial structure: customer ensure/recovery, catalog reads,
provider-specific agreement/subscription preparation, and authoritative
subscription reads/discovery.

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

No Portal-local mechanism may create or increase paid quota without the accepted
provider-owned commercial terms plus authoritative provider cycle facts. MVP has
**no provisional allowance rollover** at a billing-period boundary.

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
- postpaid/debt access semantics;
- dynamic, prorated, charge-derived, or usage-dependent allowance quantity;
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

Existing stand-043 evidence is input to Phase 0 rather than something to
rediscover from scratch. In particular, current evidence already identifies
provider facts/constraints around `users.outer_id`, `agreement_number`,
non-unique `subscriptions.outer_id`, `state`, `current_blocking`, and
`last_tariffication_period_*`. Phase 0 must validate the launch-critical
semantics built on those facts, not reopen the REST model merely to rename
fields.

### Phase 0 A: Widget and agreement isolation

Prove:

- authenticated Widget rendering with the supported script and real signing
  secret/configuration;
- Portal-like non-payment preparation of customer -> dedicated agreement ->
  subscription;
- two agreements under one customer are accounting-isolated: funding Agreement
  A cannot make Agreement B commercially/access eligible;
- autopay/payment-method behavior is isolated to the intended agreement;
- cancellation/stop of Agreement/Subscription A cannot mutate B;
- a freshly prepared but unpaid subscription is distinguishable as
  access-ineligible through the approved authoritative subscription facts;
- underpayment remains access-ineligible;
- sufficient funding through Widget makes only the intended subscription
  access-eligible without Portal querying payment-specific endpoints.

Client-side Widget flags are not accepted as the security proof; server-side
scope/authorization is tested explicitly in Phase 0 E.

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

### Phase 0 C: fixed allowance quantity and authoritative cycle semantics

For every metered MVP offer, prove the authoritative sources for:

```text
fixed quantity per metric in the provider offer/tariff
period_start
period_end
cycle_identity
component/source identity
metric/source binding
```

MVP allowance quantity is captured from the provider-owned offer/tariff before
commercial acceptance and then pinned in the immutable accepted offer snapshot.
It is **not** read from live charges, agreement balance, payment amount/status,
or another mutable funding artifact.

Prefer a native stable provider cycle/period identifier. If LBX has no native
cycle ID, a derived identity is acceptable only when test evidence proves that
the chosen provider period fields are authoritative and stable across rereads
and financial block/unblock, and change only on an actual new billing cycle.

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
1. project fixed offer terms before acceptance, for example:
     generations quantity=1000 per cycle
     exports     quantity=100  per cycle
2. create PurchaseIntent and pin those accepted quantities
3. prepare subscription S and make it commercially eligible through Widget
4. authoritative-read provider cycle C1 and interval [T1,T2)
5. allocate stable probe IDs:
     (S, source X, generations, C1) -> G1, quantity=1000
     (S, source X-or-Y, exports, C1) -> E1, quantity=100
6. record independent probe usage:
     G1 used=300
     E1 used=20
7. cause financial/access blocking in LBX
8. authoritative-read and prove C1/source identities remain the same
9. remove blocking and prove G1/E1 and their probe usage remain unchanged
10. mutate/fund the account so a live charge changes while the accepted offer and
    provider cycle remain the same
11. prove that charge mutation does not change allowance quantity, identity,
    commercial fingerprint, or Kernel usage bucket
12. trigger/wait for real renewal
13. authoritative-read distinct cycle C2
14. prove new metric-specific IDs:
     generations -> G2, quantity=1000, G2 != G1, used=0
     exports     -> E2, quantity=100,  E2 != E1, used=0
15. reread C2 repeatedly and prove each metric resolves to its same ID
```

The stand-043 observation that a charge on the same `charge_id` and period can
mutate after funding is an explicit negative test: mutable charge state is a
funding/billing-calculation signal, not allowance quantity or cycle identity.

PASS requires `CONFIRMED_ON_TEST` that:

- each sellable metered offer exposes fixed per-cycle quantity before acceptance;
- the accepted quantity can be pinned independently of live charges;
- provider period boundaries/identity are authoritative and stable for an
  already-published cycle;
- same-cycle reread is distinguishable from renewal;
- financial block/unblock does not look like renewal;
- repeated reads preserve the same `allowance_id` **per metric/source/cycle**;
- different metrics in one cycle retain independent usage buckets;
- only a confirmed new provider cycle creates new allowance IDs for those
  metrics.

If fixed quantity or cycle/source semantics cannot be proved, the offer is
`NOT_SELLABLE`. Dynamic/prorated/charge-derived quantity is outside this MVP.

### Phase 0 D: LBX customer-list completeness for first-primary selection

Phase 0 D answers one practical RU question: can the LBX customer subscription
list, using the actual supported pagination/page size, provide a sufficiently
complete candidate set for the first-primary decision before Portal selects the
PurchaseIntent-linked subscription?

Probe at least:

- sort-order stability;
- actual pagination behavior and maximum supported/useful page size;
- insert/delete behavior while reading the customer list;
- visibility delay after successful create/read;
- whether webhook may precede list visibility;
- expected MVP customer cardinality and whether all relevant rows can be returned
  in one complete list operation;
- a concurrent/second-subscription scenario proving whether an already-existing
  competing row can be hidden from the decision-making read.

Current stand evidence does not provide cursor/as-of snapshot semantics, so the
RU MVP does not build a generic snapshot/eventual-consistency strategy framework.
If the probe proves one complete customer-list read is sufficient, implement only
that path. If the probe demonstrates that a competing row can be hidden from one
complete list read, add only the minimal bounded stabilization required by that
evidence; do not introduce a generic `primary_decision_attempt` subsystem merely
for hypothetical future providers.

### Phase 0 E: Widget identity/security and prepaid eligibility

#### Server-generated Widget identity

Widget JWT is created only by Payments Portal backend from the authenticated
Portal session and the verified Portal-user <-> LBX-customer mapping. Browser
input never authoritatively chooses `ident`, `ident_type`, customer, agreement,
or Widget permissions.

The Widget principal must be a stable unique non-PII login/identifier mapped to
one LBX customer. Email, phone, and name are never Widget identity authority.
Phase 0 records the exact LBX-supported `ident_type` used and proves that changing
the principal without re-signing the JWT fails.

Phase 0 must also prove bounded credential lifetime by one provider-supported
mechanism: verified `exp`, enforced maximum age based on `iat`, revocable
short-lived session, or an equivalent supported control. Adding an ignored JWT
claim is not evidence. An effectively unbounded replayable Widget bearer token
blocks launch.

#### Server-side Widget operation scope

`disableCreateSubscription` / `disableEditSubscription` and related JavaScript
flags are presentation controls, not trusted ACLs. Phase 0 must prove either:

1. server-side agreement-scoped Widget authorization; or
2. customer-scoped Widget identity plus server-side authorization that forbids
   unsafe commercial mutations independently of client flags.

The hostile-client probe uses a real signed token and deliberately initializes or
invokes Widget functionality with create/edit protections disabled. It attempts
arbitrary subscription creation, tariff/service modification, unintended
agreement operation/top-up/autopay, cross-customer use, principal tampering, and
token replay after the supported validity window. PASS is based on server
behavior, not on hidden buttons.

Any LBX lookup mode such as an agreement-number/`ident_type` variant is treated
as **UNKNOWN AS AUTHORIZATION SCOPE** until the probe proves that it restricts
server-side operations rather than merely locating a customer.

#### Prepaid eligibility contract

RU MVP sells only tariff configurations classified:

```text
PREPAID_BLOCKING_CONFIRMED
```

For every sellable tariff, Phase 0 must prove this transition model on the real
configuration:

```text
prepared unpaid       -> financially blocked
underpaid             -> remains financially blocked
sufficiently funded   -> financially unblocked
next unfunded renewal -> financially blocked again
```

The LBX paid-access predicate is therefore based on a **complete authoritative
subscription GET** and requires all of:

```text
non-terminal lifecycle
billing_mode == PREPAID_BLOCKING_CONFIRMED
current_blocking == 0
observed commercial fingerprint == accepted fingerprint
no access/subscription conflict
```

`state=2` plus `current_blocking=0` alone never means "paid". The stand-043 case
where those values coexist with no payment and negative balance is an explicit
negative test. Any tariff/configuration that permits postpaid/debt access or
cannot prove the prepaid blocking transitions is `NOT_SELLABLE`.

Portal still does not read payment status, charge amount, or balance as access
authority.

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

Target MVP presentation configuration:

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

These flags are not the authorization boundary. Widget is launchable only after
Phase 0 E proves the server-side identity/scope and bounded-token guarantees.

Widget JWT is minted server-side from the authenticated Portal user and verified
LBX-customer mapping. The principal is stable, unique, and non-PII. Email, phone,
and name are not principals and are not accepted from the browser as authority.
Widget signing secrets never reach the browser.

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

Safety depends on dedicated-agreement accounting isolation and the prepaid
eligibility contract:

- underpayment must remain financially blocked;
- sufficient funding may unblock only the intended subscription;
- overpayment may remain on that dedicated agreement for future billing;
- Portal does not model agreement balance;
- balance/charge/payment data never defines allowance quantity.

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
- each metered quantity is `fixed_per_cycle` and readable before acceptance;
- the LBX tariff is `PREPAID_BLOCKING_CONFIRMED` for customer-funded RU access;
- external usage-reporting requirement is explicitly classified as `none`.

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

External usage-reporting classification is:

```text
external_usage_reporting = none | required | unknown
```

Only `none` is sellable in this MVP. `required` and `unknown` are
`NOT_SELLABLE` until a separate metering design is approved and implemented.

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

### Purchase-time mapping and accepted-quantity snapshot

For Portal-initiated purchases, mapping and fixed metric quantities are pinned
**when `PurchaseIntent` is created**, not when the subscription is first
reconciled.

The same local transaction stores an immutable purchase-time component/metric
snapshot, conceptually:

```text
purchase_intent_components
  purchase_intent_id
  external_component_ref
  mapping_revision_id
  resolved_product_id

purchase_intent_metric_terms
  purchase_intent_id
  external_component_ref
  mapping_revision_id
  mapping_binding_id
  metric_key
  accepted_quantity
  quantity_semantics = fixed_per_cycle
```

A later mapping revision N+1 cannot change the technical meaning of an existing
PurchaseIntent. A subscription linked to that intent inherits these pinned
mapping revisions and fixed accepted metric quantities.

`mapping_revision_id` itself is not part of the user's legal/commercial
fingerprint. The fingerprint represents material semantics: target product,
price/currency, billing period/recurrence, component/allowance composition,
fixed allowance quantities/policies, and material renewal/cancellation terms. A
purely internal revision change that preserves those semantics does not require
renewed user consent.

Live charges, balances, payment amounts/statuses, and charge-calculation
mutations are not accepted-quantity sources and do not alter the commercial
fingerprint merely by changing.

### Subscription-component pinning outside purchase flow

For an admissible externally-created subscription without PurchaseIntent, each
previously unresolved component may be resolved once using the then-active
mapping and is then permanently pinned. A current/sellable Portal offer is not
required for such an already-existing subscription; access derives from the
actual authoritative component composition plus pinned mappings and legal/origin
rules in this spec.

For an audited operator comp that is allowed to produce quota, fixed metric
quantity is likewise captured once from the authoritative commercial
configuration into the operator's immutable commercial snapshot. It is never
inferred from charge/balance/payment state.

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
commercial fingerprint, fixed metric quantities, source versions, sellability,
prepaid eligibility classification, metering classification, and sync timestamps.

### PurchaseIntent and interaction state

There is no Portal-owned commercial `Order`.

`PurchaseIntent` records that a user began buying an exact accepted offer
version. It contains at least:

- `user_id`, billing account, `product_id`, `billing_offer_id`;
- accepted `commercial_fingerprint` and relevant material commercial snapshot;
- immutable purchase-time component/mapping and fixed metric-quantity snapshot;
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

Automatic scope release is allowed only when:

- failure happened before any external mutation/effect was possible; or
- a linked subscription becomes authoritatively terminal and no unresolved
  competing flow remains; or
- a provider-specific absence predicate has been separately proven strong enough
  to establish `resolved_no_external_effect`.

For LBX subscription creation, the current MVP has **no proven automatic absence
predicate**. Timeout, lost response, HTTP 500, Widget abandonment, and a recovery
lookup returning zero rows do not prove that no subscription was created.
`subscriptions.outer_id` is not assumed unique. Therefore an uncertain LBX
subscription-create outcome:

```text
subscription_create_outcome_unknown
 -> keep (user, product) scope held
 -> continue bounded recovery/discovery
 -> DO NOT blindly create another subscription
 -> DO NOT auto-release scope on 0 matches
 -> eventually open manual_review if unresolved
```

Support/Billing Ops may release the scope only through an audited resolution
based on provider/human evidence that release is safe, or may bind a recovered
existing subscription. The audit records actor, reason, evidence/reference,
timestamp, and affected PurchaseIntent.

If an old external object appears after such a manual release and a later
purchase already succeeded, the late object gets no automatic access; it enters
conflict/manual review.

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

For customer-funded RU LBX subscriptions, `financial_access_status=allowed` may
be produced only when all of the following are true:

- the tariff configuration is already `PREPAID_BLOCKING_CONFIRMED`;
- a complete authoritative subscription GET succeeded;
- lifecycle is non-terminal;
- `current_blocking == 0`.

This is not a generic statement that `state/current_blocking` means payment.
Without the proven prepaid tariff classification, the subscription cannot become
access-producing and the dependent offer/configuration is not sellable in MVP.
Postpaid/debt semantics are unsupported.

`commercial_access_status=eligible` additionally requires accepted/observed
commercial fingerprint match, valid pinned mapping/origin/legal rules, and no
access/subscription conflict.

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

`purchased_allowances` materializes metric quota buckets derived from two
separate authoritative inputs:

```text
quantity              <- immutable accepted fixed offer/operator-comp snapshot
cycle identity/bounds <- authoritative provider cycle facts
```

Live charge quantity/value, charge mutation, agreement balance, and payment
amount/status never create or resize a quota bucket.

One provider billing cycle may yield zero, one, or many allowances. Every
allowance belongs to exactly one `metric_key`.

Conceptual fields:

```text
allowance_id                         # stable opaque Portal UUID
billing_subscription_component_id    # exact concrete provider source
mapping_revision_id                  # exact pinned interpretation
mapping_binding_id                   # exact metric binding where applicable
product_id
metric_key
provider_cycle_key                   # internal/provider-specific, never Kernel-facing
quantity                             # pinned fixed_per_cycle accepted quantity
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
those IDs, fixed quantities, and Kernel usage. Mutable charge recalculation does
not change them.

Only an authoritatively confirmed new provider cycle creates new metric-specific
allowance IDs. For a normal customer-funded renewal, each new bucket uses the
same pinned accepted fixed quantity only while the observed commercial
fingerprint still matches the accepted fingerprint. A material provider-side
commercial quantity change is `commercial_terms_conflict`, not an automatic quota
resize.

Once an allowance has been published to Kernel, its `period_start` and
`period_end` are immutable in MVP. A later authoritative read claiming different
boundaries for the same provider cycle is `allowance_cycle_conflict`; Portal does
not silently rewrite the bucket.

Historical allowance rows are retained/addressable; they are not physically
deleted merely because a period ended.

Portal does not persist authoritative runtime `remaining`. Platform Kernel owns
actual usage and computes remaining quota independently for every
`allowance_id`.

### Product access scope

For every `(user_id, product_id)`, Portal owns a durable product access scope,
conceptually:

```text
billing_product_access_scope
  user_id
  product_id
  primary_subscription_id nullable
```

with:

```text
UNIQUE(user_id, product_id)
```

The row is the PostgreSQL serialization point for first-primary selection,
clearing primary, and audited operator resolution. MVP deliberately does not
create a generic `primary_decision_attempt`, generation, or candidate-digest
state machine.

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
subscription -> agreement/customer context + all proven correlation facts
```

A recovery lookup result is not interpreted uniformly across object types. For
customer/agreement creation, retry after zero matches is allowed only if that
specific operation has a proven safe absence/retry contract. For uncertain LBX
subscription creation:

```text
0 matches  -> remains unknown; no blind retry and no automatic scope release
1 proven unique correlation -> bind the existing provider object
>1 plausible matches -> ambiguous/manual_review; never guess
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
- included metric set and fixed allowance quantities/policies;
- material renewal/cancellation terms.

Provider internal IDs, invoice/order numbers, current cycle timestamps, generated
document references, reconciliation timestamps, mutable charges/balance/payment
artifacts, cosmetic names/descriptions, and other operational metadata do not by
themselves change the fingerprint.

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
the fingerprint merely because `period_start`/`period_end` advanced or because a
mutable funding/charge artifact changed.

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

It never submits authoritative provider IDs, price, payment amount, period, or
allowance quantity.

Portal validates capability-manifest freshness, catalog freshness, sellability,
prepaid-blocking classification, fixed-per-cycle quantity semantics, current
fingerprint, legal acceptance, and `(user, product)` uniqueness.

In the same transaction that creates `PurchaseIntent`, Portal pins the exact
mapping revisions, accepted component snapshot, and fixed metric quantities.

### Provider-neutral preparation

```text
validate offer + legal + purchase scope
 -> create PurchaseIntent + mapping/quantity snapshot
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
fixed allowance semantics/quantities from the accepted offer configuration,
currency/price basis where authoritative provider facts permit it, and target
technical product through the pinned mapping.

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
access. Widget callback, payment event, charge mutation, or balance change does
not directly grant access either.

For RU LBX, customer-funded access appears only after an ordinary **complete
authoritative subscription GET** satisfies the tariff-specific
`PREPAID_BLOCKING_CONFIRMED` predicate and the observed commercial fingerprint
still matches the accepted fingerprint.

If LBX cannot prove the prepared-unpaid/underpaid versus sufficiently-funded
transition through the approved prepaid financial-blocking semantics, the tariff
is `NOT_SELLABLE`; Portal does not compensate by tracking payment status itself.

## Webhooks

Webhook handling is intentionally short:

```text
authenticate
 -> minimally validate/extract safe correlation hints
 -> generate delivery_id
 -> persist inbox row
 -> enqueue/coalesce reconciliation/discovery work
 -> commit
 -> return 2xx
```

No provider REST call occurs inside the webhook request. Payload contents never
directly mutate entitlement. Duplicate/out-of-order deliveries are safe.
Coalescing occurs at reconciliation-work level, not by deleting delivery rows.
Authentication failure creates no trusted inbox work and emits security
telemetry.

A valid webhook is only a high-priority hint. Stand evidence already shows that
a create-related webhook may be stale relative to later REST financial blocking,
so authoritative reads remain the access authority.

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
linked-but-never-eligible purchase  activation_watch, max 5m
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
activation_watch reconciliation      = <= 5m
provider outage retry                = 1m -> 2m -> 5m -> 15m -> 15m ... + jitter
remaining trust <= 30m               = max 5m between retries
after trust expiry                   = continue retry <= 5m until recovery
```

`activation_watch=true` when a subscription is linked to a PurchaseIntent,
non-terminal, free of conflict/manual-review blockers, has matching commercial
terms, and has **never yet produced paid access** because the current
authoritative financial state is blocked/ineligible.

Linking the PurchaseIntent does not drop this subscription to the normal 15m
cadence. While `activation_watch` is true, authoritative reconciliation runs at
most 5 minutes apart. Widget completion/closure and valid webhook hints may
enqueue an immediate read, but they do not themselves activate access or end the
watch.

The watch ends only after the first authoritative eligible state, terminal state,
commercial/access conflict, or explicit audited resolution. A subscription that
was previously eligible and later becomes blocked uses normal reconciliation,
webhook acceleration, and trust-expiry urgency rather than the first-activation
watch.

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

## Linked-intent first-primary selection and conflict semantics

MVP uses the already-known PurchaseIntent-linked subscription as the candidate
for the normal purchase fast path, but **linking alone never makes it primary**.

After subscription `S` is linked, Portal performs the customer subscription-list
operation proven by Phase 0 D, authoritative point-reads the relevant candidate
subscriptions, and updates local candidate projections. Only after that network
work completes does Portal open a short transaction and lock the
`billing_product_access_scope` row for `(user_id, product_id)`.

Under that lock, Portal rereads the **current local candidate set** rather than
applying a saved worker list and evaluates:

```text
0 eligible candidates
  -> keep primary NULL
  -> linked S may remain activation_watch

exactly 1 eligible candidate, and it is linked S
  -> primary = S

exactly 1 eligible candidate, but it is not linked S
  -> no automatic primary; external_unknown/conflict -> manual_review

>=2 eligible candidates
  -> keep primary NULL
  -> subscription_conflict/manual_review
```

Selection is not biased by worker completion order, subscription age, amount, or
agreement ordering. PurchaseIntent correlation is useful only for the normal
linked fast path; it never suppresses a real competing eligible subscription.

Phase 0 D decides whether one complete LBX customer-list operation is sufficient.
Only if the real provider probe demonstrates hidden competing rows does MVP add a
small bounded stabilization step. It does not pre-build a provider-neutral
two-pass/generation/digest framework.

If a trusted primary already exists and later discovery finds another eligible
subscription, the trusted primary continues within its normal trust rules; the
newcomer produces no additional access and opens conflict review.

If the selected primary becomes blocked/ineligible, Portal does not automatically
promote another candidate. Access follows the selected primary's authoritative
state. If the primary becomes terminal and the selection is cleared under the
same product-scope lock, another previously existing candidate is not
automatically promoted; a new valid purchase flow or explicit audited operator
resolution is required.

An audited operator may accept an already-proven subscription as primary only
under the same product-scope lock and after re-evaluating current conflicts. The
operator never sets entitlement directly.

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
balance, charge, or other financial heuristics.

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
metric-specific allowance IDs using the pinned fixed quantities, increments
`access_revision`, invalidates Kernel, and metered usage resumes after refresh.

Same-cycle financial unblock is not renewal and must reuse the same
metric-specific allowance IDs, fixed quantities, and Kernel counters.

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

No provider IDs, LBX statuses, balances, payment states, charges, or provider
cycle keys appear in this contract.

`AccessSnapshot` is the **complete current effective access set**, not a partial
delta. Absence of Product A while Product B is present means A is denied and B
remains allowed; it does not mean the snapshot is incomplete.

Portal evaluates grants/allowances independently at snapshot materialization.
When one source/fact loses trust, expires, or enters conflict, only the affected
derived facts are omitted unless other facts genuinely share the same invalid
source. Independent products continue to be published from their own trusted
sources.

For example:

```text
revision N:   Product A facts + Product B facts
A trust expires while B remains trusted
revision N+1: Product A facts omitted; Product B facts remain
```

That omission is a material negative access change: Portal increments
`access_revision` and writes durable invalidation. A metric allowance may expire
and be omitted while its open-ended product grant remains present.

MVP defaults:

```text
refresh_after = now + 1m
expires_at = min(
  now + 5m,
  deadlines of subscription/source facts actually included,
  known grant terminal boundaries actually included,
  allowance temporal boundaries actually included where needed
)
```

After an expired fact is omitted, its old deadline is no longer used to shorten
the new snapshot. A multi-product user's fresh snapshot therefore is not made
unusable merely because an independent product/source has already expired and
been omitted.

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
- allowance/grant omission because trust/period/conflict no longer permits it;
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

`allowance_id` is required because it is the stable identity of one
**metric/source/provider-cycle** runtime quota bucket.

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

## External metering is outside this MVP

If `external_usage_reporting` is `required` or `unknown`, the offer is
`NOT_SELLABLE`. A future UsageEvent/external-metering subsystem requires a
separate approved design before such an offer can be enabled.

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
- `subscription_create_outcome_unknown` -> Billing Ops/Support;
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
to an existing operation, `bind_recovered_subscription`,
`release_scope_after_proven_absence`, marking duplicate/conflict, audited mapping
rebind, accepting a proven subscription as primary under the product-scope lock,
rejecting conflict, or marking unknown customer unmatched.

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
- customer-scoped enumeration/discovery;
- webhook authentication/parsing.

There is no generic payment-command capability in Payments Portal.
Provider-specific concepts such as LBX Agreement, tariff/service APIs, `state`,
`current_blocking`, Widget mechanics, balances, provider cycle fields, and
recovery lookup remain in provider integration packages and never leak into
Platform Kernel.

The RU LBX adapter implements only the customer-list/point-read behavior and any
minimal stabilization actually proven necessary by Phase 0 D. Future providers
may define their own discovery behavior in their own adapter design without
forcing a generic MVP strategy framework here.

## Portal <-> Platform Kernel implementation contract

This is a cross-repository implementation stream. Baseline MVP completion
requires both repositories to implement and contract-test:

| Contract | Producer/source | Consumer | MVP |
| --- | --- | --- | --- |
| Capability Manifest | Platform Kernel | Payments Portal | required |
| AccessSnapshot | Payments Portal | Platform Kernel | required |
| AccessInvalidation | Payments Portal | Platform Kernel | required |

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
- AccessSnapshot producer with independent fact omission/failure isolation;
- monotonic revision + durable invalidation delivery;
- provider projection/reconciliation semantics defined in this spec.

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
Portal still inside provider-fact trust lease, trust-lease expiry isolated to an
affected source/product, allowance boundary refresh with no provisional quota,
and multi-metric counter isolation.

## Worker topology and transactions

MVP runs a durable billing worker embedded in the Payments Portal API process
with one API replica initially. Correctness-critical work lives in PostgreSQL,
not in-memory queues or FastAPI `BackgroundTasks`.

Worker/use-case logic is independent of FastAPI composition so it can later move
to a separate process. Queue claims, product-scope first-primary decisions, and
reconciliation leases must be multi-consumer safe even though the initial
deployment has one replica.

External network requests never run inside open DB transactions. Transactions
are short and cover local intent/state creation, claims/leases, durable operation
state, current-candidate evaluation under the product-scope lock, and atomic
projection/access updates.

RabbitMQ/Kafka is not required for MVP.

## Security and PII

Provider credentials, webhook secrets, Widget signing secrets, and payment
credentials live only in runtime secret configuration. They are not stored in
billing-account rows, domain objects, logs, or browser-visible responses.

Widget JWT is signed only by Portal backend after resolving the authenticated
Portal user to the verified LBX customer. Its principal is stable, unique, and
non-PII; email, phone, and name are never cross-system or Widget identity
authority. Browser-provided `ident`, `ident_type`, customer, agreement, and
permission values are not trusted.

Widget client flags are not ACLs. Launch requires Phase 0 proof of server-side
commercial-operation scope and bounded token lifetime/replay semantics.

Capability/access/invalidation internal APIs use TLS, explicit service
authentication, and tenant/region scope. User authentication alone is not enough.
One regional contour never reads/writes another contour's billing/access data.

Only minimum provider-required billing PII is transmitted/stored. Reverse-proxy
and access logs must not leak webhook query secrets, Widget signing material,
JWTs, or auth data. Raw provider-payload retention requires explicit
redaction/retention policy.

## Observability and audit

Use non-PII correlation identifiers such as request ID, user ID,
PurchaseIntent ID, billing operation ID, webhook `delivery_id`, work item ID,
subscription ID, metric-specific `allowance_id`, and safe opaque provider
references.

At minimum monitor:

- capability-manifest/catalog age and sync failures;
- unclassified/invalid mappings and not-sellable reasons;
- customer ensure/recovery unknown/ambiguous state;
- `subscription_create_outcome_unknown` count and oldest scope-held age;
- manual-review count and oldest age by reason;
- normalization errors;
- discovery/reconciliation success/failure/duration;
- `activation_watch` count, oldest age, and time-to-first-eligibility;
- age since last authoritative subscription read and time to
  `projection_valid_until`;
- work-queue depth/oldest item;
- webhook auth failures/delivery lag;
- fresh/stale-usable/expired projections;
- commercial-terms and allowance-cycle conflicts;
- access fact omissions caused by trust/period/conflict boundaries;
- access-invalidation lag and stale-snapshot rejection count;
- provider latency/timeouts/error rate.

Audit must explain why access changed and identify the authoritative read,
mapping revision/snapshot/rebind, accepted fixed quantity, provider cycle/source,
current-candidate first-primary decision, or manual resolution involved without
creating a shadow provider financial ledger.

## Clean pre-production reset and implementation ordering

There is no production compatibility contract, but destructive rewrite begins
only after **all Phase 0 launch-critical gates pass**.

Implementation order:

0. **Run Phase 0 A-E against LBX and record PASS evidence. Reuse stand-043 REST
   facts where already known; prove the remaining semantics. If a launch-critical
   gate fails, stop the rewrite.**
1. Supersede/update contradictory canonical ADR/docs in Portal and Kernel.
2. Remove obsolete Portal Product/Bundle/Plan/PlanLimit/Order and direct-payment
   orchestration semantics; replace the disposable Alembic baseline and recreate
   development/test DBs.
3. Implement Kernel capability/metric manifest and Portal importer.
4. Implement external catalog projection, controlled mapping publication, fixed
   accepted-quantity projection, and purchase-time mapping/quantity snapshot.
5. Implement durable external-customer slot/recovery and LBX non-payment
   preparation, including the no-auto-release rule for uncertain subscription
   creation.
6. Implement PurchaseIntent scope rules, prepared-state authoritative read-back,
   recurring commercial-fingerprint checks, server-generated Widget identity,
   and embedded Widget interaction using the Phase 0 E security contract.
7. Implement the **actual LBX customer-list + authoritative point-read behavior
   proven in Phase 0 D**, linked-intent first-primary fast path under the
   product-scope lock, fenced reconciliation, activation watch, normalized
   prepaid access, conflict handling, and the 6h provider-fact trust lease.
8. Implement metric-specific allowance-cycle identity/projection from the exact
   Phase 0 evidence, with quantity pinned from accepted fixed offer terms; do not
   use live charges and do not implement provisional rollover.
9. Implement Portal complete-effective-set AccessSnapshot with per-fact omission,
   revision/invalidation, and Kernel consumer with monotonic revision-floor race
   protection.
10. Integrate paid allowances into the existing Kernel quota engine with one
    independent usage bucket per metric-specific `allowance_id`.
11. Run cross-repo contract/integration proofs.
12. Repeat the LBX production gate against the deployed RU configuration before
    launch.

No dual-write old/new billing traffic split or compatibility layer is required.

## Required correctness tests and launch evidence

Implementation planning must include automated tests plus provider-validation
spikes proving at least:

- Phase 0 A-E passes before destructive rewrite;
- stand-043 known REST facts are reused rather than needlessly rediscovered, while
  their launch-critical semantics are explicitly tested;
- Widget authenticated rendering works with a real signing secret;
- Widget JWT is server-generated from the verified customer mapping and uses a
  stable unique non-PII principal;
- principal tampering without re-signing fails;
- Widget bearer credential has a provider-enforced bounded lifetime/replay window;
- hostile Widget/client attempts with create/edit protections disabled cannot
  bypass the proven server-side commercial-operation scope;
- Widget session intended for one customer/agreement cannot operate an unrelated
  customer/agreement according to the exact Phase 0 E authorization model;
- Agreement A funding/autopay/cancellation cannot affect Agreement B;
- every sellable RU tariff is `PREPAID_BLOCKING_CONFIRMED`;
- prepared unpaid and underpaid subscriptions remain financially blocked;
- sufficient Widget funding unblocks only the intended subscription;
- an unfunded renewal blocks again according to the proven prepaid model;
- `state=2` + `current_blocking=0` without the proven prepaid tariff
  classification cannot produce access;
- postpaid/debt configurations are `NOT_SELLABLE`;
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
- mapping revision N and fixed metric quantities are pinned with PurchaseIntent
  and later mapping N+1 does not change that intent/subscription meaning;
- live charge mutation (including the stand-observed same-charge same-period
  mutation after funding) does not resize an allowance, create a new bucket, or
  change the accepted commercial fingerprint;
- only `fixed_per_cycle` quantity is sellable; dynamic/prorated/charge-derived
  quantity is `NOT_SELLABLE`;
- same HTTP idempotency key creates one PurchaseIntent;
- different tabs/keys cannot create two purchase scopes for one `(user,product)`;
- Widget expiry does not release unresolved scope;
- linking a prepared-but-unpaid subscription transfers scope to that
  non-terminal subscription;
- uncertain LBX subscription create timeout/500/lost response retains the scope;
- zero recovery matches for uncertain subscription create does **not** prove
  absence, trigger blind retry, or auto-release the scope;
- audited Support/Billing Ops resolution is required before releasing such scope
  unless a future provider-specific absence predicate is separately proven;
- a subscription discovered after a manual release does not gain automatic access
  and enters conflict/manual review if a later purchase already succeeded;
- customer slot exists before LBX create and parallel purchases cannot create
  two external customers;
- create timeout uses stable recovery evidence and never blind-retries;
- duplicate/out-of-order webhooks converge and retain distinct `delivery_id`s;
- stale create/payment-related webhook never overrides later authoritative REST
  financial blocking;
- missed webhook is repaired by scheduled discovery/reconciliation;
- linked-but-never-eligible subscription remains in `activation_watch` with
  authoritative reconciliation no more than 5m apart even after intent linking;
- Widget close without funding does not end activation watch or release scope;
- first confirmed eligibility ends activation watch and allows normal cadence;
- Phase 0 D proves the exact LBX customer-list completeness behavior used by the
  first-primary path;
- MVP does not create a generic primary-decision generation/digest subsystem;
- linked subscription never becomes primary merely because it is linked;
- after the proven customer-list operation and point reads, current candidates
  are reread under the `(user,product)` scope lock before first-primary decision;
- exactly one eligible current candidate may become primary only when it is the
  linked subscription for the normal purchase flow;
- one eligible unlinked candidate does not silently replace the purchase target;
- two or more eligible candidates produce no primary and manual review;
- an existing trusted primary continues when a later conflicting eligible
  subscription appears, while newcomer adds no access;
- an ineligible/blocked selected primary does not auto-promote a competing
  subscription;
- clearing a terminal primary does not auto-promote another old candidate;
- `PurchaseIntent` never shortcuts a real subscription conflict;
- unknown provider customer never auto-binds by PII;
- comp/gift to unmapped user is unsupported;
- ordinary discovered customer-funded subscription without valid purchase/legal
  evidence does not auto-grant access;
- operator comp requires audited non-customer-funded classification, fixed
  authoritative quantity snapshot where quota exists, and baseline legal
  acceptance;
- unclassified component, required/unknown external metering, duplicate metric
  source, non-prepaid tariff, or unsupported quantity semantics blocks new offer
  sale;
- mapping revisions are immutable and already-pinned subscription mappings do
  not change silently;
- explicit audited rebind is required to change a pinned mapping;
- `projection_valid_until = last_authoritative_read_at + 6h` and only successful
  complete normalized provider read extends it;
- local snapshot issuance/webhook/callback/failed read never extends provider
  trust;
- known active subscription reconciliation normally runs every 15m with defined
  outage backoff/near-expiry urgency, while activation watch stays <=5m;
- access fails closed for an affected source after projection trust expiry even
  if Portal itself is healthy;
- if Product A source expires while independent Product B remains trusted,
  revision increments, A facts are omitted, and B remains in the complete
  AccessSnapshot;
- after omitted A facts are gone, A's old deadline no longer shortens the new
  snapshot expiry;
- open-ended grant uses `valid_until=null`, and allowance period end alone does
  not end product grant;
- expired allowance may be omitted while its valid product grant and unrelated
  product facts remain;
- no provisional allowance is created when provider confirmation of the next
  cycle is unavailable;
- at allowance period end, Kernel refreshes and fails closed for that metric if
  no authoritative new cycle exists;
- same-cycle reread preserves each metric-specific `allowance_id` and its pinned
  fixed quantity;
- same-cycle block/unblock preserves each metric-specific ID and already-used
  Kernel amount;
- one provider cycle with at least two metrics produces two independent Kernel
  counters and no cross-metric consumption;
- a new provider cycle creates new IDs independently for each metric and starts
  each new Kernel usage bucket at zero using the accepted fixed quantities;
- changed interval for an already-published same-cycle bucket produces
  `allowance_cycle_conflict` rather than silent rewrite;
- every material positive or negative access change, including fact omission,
  increments `access_revision` and durably invalidates Kernel cache;
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
- no offer requiring external usage reporting is sellable under this MVP design;
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
- treat Widget JavaScript flags as a security ACL;
- use email/phone/name as Widget or cross-system identity authority;
- require a fixed exact Widget top-up amount;
- support bundles/all-access, multiple products per offer, overlapping
  access-producing subscriptions, allowance stacking, duplicate metric sources,
  shared metrics, or paid overage;
- support postpaid/debt paid-access semantics in RU MVP;
- support dynamic/prorated/charge-derived allowance quantity;
- support Portal-initiated upgrade/downgrade/refund/dispute/commercial trial;
- support in-place re-consent/material modification of a live customer-funded
  subscription;
- create provisional renewal allowances during provider outage;
- auto-bind unknown external customers using PII;
- create a provider customer solely for an unmapped gift recipient;
- auto-release an uncertain LBX subscription-create scope because recovery found
  zero rows;
- require a manual-review admin UI;
- build a generic discovery-consistency strategy framework,
  `primary_decision_attempt`, generation/digest finalization, or unconditional
  two-pass 30s protocol for LBX unless Phase 0 D proves a minimal stabilization
  is actually necessary;
- implement external UsageEvent/metering delivery in this baseline design;
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
  immutable versioned capability mappings + accepted fixed-quantity snapshot
  durable external-operation recovery
  LBX customer-list/point-read discovery proven by Phase 0 D
  linked-intent first-primary decision under product-scope lock
  activation watch + bounded provider-fact trust lease
  entitlements and metric-specific authoritative allowances
  complete-effective-set AccessSnapshot + AccessInvalidation

Platform Kernel
  technical product/metric vocabulary
  monotonic AccessSnapshot revision floor
  durable actual usage independently by allowance_id
  runtime quota enforcement
  execution
```

Platform Kernel never calls External Billing directly.  
Payments Portal never calls payment-specific provider APIs.  
RU billing interaction is LBX Widget, subject first to Phase 0 feasibility and
again to the final deployed-configuration production gate.
