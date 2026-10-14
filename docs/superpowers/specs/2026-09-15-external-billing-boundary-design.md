# External billing boundary and Payments Portal redesign

Status: accepted implementation baseline  
Date: 2026-09-15

## Goal

Redesign Payments Portal around a strict bounded-context split:

- External Billing owns commercial billing truth;
- Payments Portal owns AnyToolAI identity plus the billing anti-corruption,
  projection, reconciliation, recovery, entitlement, and access boundary;
- Platform Kernel owns technical product/metric vocabulary, actual runtime usage,
  quota enforcement, and execution;
- Platform Kernel never communicates directly with LBX, Dodo, or another billing
  provider.

The repository has not been deployed to production. The current Portal-owned
commerce/direct-payment schema is disposable. Under `ANY-504`, provider-
independent pre-production cleanup and reset may occur before Phase 0. Phase 0
remains the hard gate for provider-dependent production semantics, Widget/LBX
production behavior, and launch.

MVP supports buying one existing Platform product at a time. Bundles, overlapping
access-producing subscriptions for one product, allowance stacking, paid
overage, upgrade/downgrade, postpaid/debt access, dynamic/prorated quota,
in-place commercial re-consent, and provisional quota rollover are deferred.

## Canonical documentation precedence

This design supersedes conflicting semantics in ADR 0002, ADR 0004, and related
canonical documentation, including:

- Portal-owned `Product`, `Plan`, `PlanLimit`, and commercial `Order` as purchase
  authority;
- `Plan.id` as exact commercial purchase identity;
- direct payment-provider orchestration by Payments Portal;
- Portal-owned payment-method, autopay, invoice, payment-history, or billing
  cabinet UI where the external billing provider supplies those capabilities.

Replacement semantics are:

- Platform Kernel owns `product_id` and `metric_key`;
- External Billing owns commercial offers, prices, periods, subscriptions,
  balances, payments, refunds, payment methods, autopay, invoices, and billing
  lifecycle;
- Payments Portal projects external offers as `billing_offer` and identifies the
  material accepted version by `offer_id + commercial_fingerprint`;
- `PurchaseIntent` is orchestration state, not a commercial Order;
- AnyToolAI legal/commercial acceptance is bound to the exact material offer
  fingerprint and required legal-document versions;
- billing/payment self-service is provider-owned.

Before implementation is complete, contradictory ADRs and architecture/docs in
Payments Portal and Platform Kernel must be superseded so only this ownership
model remains canonical.

## Architectural invariants

### Ownership

External Billing owns, as applicable:

- commercial products/services, tariffs, periods, package composition, prices,
  discounts, sellability, and commercial allowance rules;
- subscription lifecycle and provider agreements/contracts;
- balances, charges, billing calculation, and financial blocking;
- payment UX/initiation, acquiring, payment methods, autopay;
- refunds, dispute/chargeback consequences, invoices, billing documents, money
  history, billing profile/notifications, and provider self-service UI.

Payments Portal owns:

- canonical AnyToolAI user identity, auth/session, and AnyToolAI legal acceptance;
- verified Portal-user <-> external-customer mapping;
- read-only external catalog/subscription projections;
- immutable/versioned external-component -> Platform-capability mappings;
- `PurchaseIntent` and fixed-offer purchase orchestration;
- durable external-operation recovery, discovery, reconciliation, webhook inbox,
  work queue, and manual review;
- normalized product grants and purchased allowance projections;
- vendor-neutral `AccessSnapshot`, monotonic `access_revision`, and durable
  invalidation toward Platform Kernel.

Platform Kernel owns:

- technical `product_id` registry;
- technical `metric_key` registry, with each metric belonging to exactly one
  product;
- durable actual usage and remaining-quota calculation;
- runtime quota policy/enforcement;
- scenario/workflow/action execution.

Payments Portal never becomes the runtime usage ledger.

### One-way billing dependency

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

Kernel receives no provider credentials or provider-specific IDs and never calls
External Billing directly.

### Strict payment boundary

Payments Portal does not call payment-specific REST APIs. It does not create a
payment, submit/calculate payment amount as payment authority, choose an
acquirer, save a card, enable/retry autopay, issue refunds, or use payment status
as access authority.

Portal may call non-payment provider APIs needed for customer recovery, catalog
reads, agreement/subscription preparation, authoritative subscription reads, and
customer-scoped subscription discovery.

RU payment/billing interaction is **LBX Widget**. There is no fallback to
Portal-orchestrated `/eps_payments`. Failure of the LBX feasibility gate blocks
the rewrite/launch rather than weakening this boundary.

### Paid access authority

Provider commercial/subscription facts change locally only after a complete,
successfully normalized authoritative provider read.

Paid access may change only because of:

1. complete authoritative provider facts plus the accepted provider-owned
   commercial terms;
2. deterministic passage of time across an already-known boundary, which may
   only reduce/expire access;
3. an explicit audited operator resolution that selects already-proven facts,
   never mutates pinned commercial/mapping meaning, and returns through normal
   derivation.

A local catalog row, webhook, Widget/browser callback, successful outbound POST,
charge/payment/balance change, agreement creation, or `PurchaseIntent` state is
never by itself access authority.

## MVP commercial scope and sellability

MVP shape:

```text
Product A -> Offer A -> Subscription A
Product B -> Offer B -> Subscription B
```

For `(user_id, product_id)`, at most one billable subscription is selected as
access-producing. Different products are independent.

Every sellable offer must:

- resolve to exactly one `product_id`;
- map every metric to that same product;
- classify every external component explicitly;
- have no duplicate source component for one `metric_key`;
- use only `fixed_per_cycle` allowance quantity;
- have fully re-verifiable material commercial terms;
- be `PREPAID_BLOCKING_CONFIRMED` for customer-funded RU access;
- have `external_usage_reporting=none` in this MVP.

Anything violating those rules is `NOT_SELLABLE`.

## Phase 0: LBX architecture gate and provider-contract evidence

Phase 0 is an architecture gate, not end-of-project QA. Before implementing
provider-dependent production semantics, Widget/LBX production behavior, or
launching, run the required probes against the real LBX test environment.

Evidence labels:

```text
DOCUMENTED        = public/provider documentation only
VENDOR_CONFIRMED  = vendor confirmed for our deployment
CONFIRMED_ON_TEST = reproduced on the real test stand
```


Evidence acceptance is **risk-based**, as approved in ANY-504 on 2026-10-14.
`DOCUMENTED` is sufficient for a standard, unambiguous LBX API capability;
`CONFIRMED_ON_TEST` is required when a specific unresolved stand-dependent
assumption would change identity, security, paid-access correctness, or the
integration architecture and no documented contract plus fail-closed fallback is
sufficient. `VENDOR_CONFIRMED` and `LOCAL_POLICY_CHECK` retain their distinct
meanings. A research/probe marked DONE does not retroactively turn UNKNOWN or
an observed provider FAIL into a live PASS.

The reviewed [ANY-634 Phase 0 evidence and deferred-gates matrix](../phase0/2026-10-14-any-634-lbx-evidence-handoff.md)
records each B1-B15 result, accepted decisions, owners and pre-enable tests.
In particular: B8 pricing is consolidated into the service-price contract in Phase 0 B below; B11 natural unpaid renewal was **not** observed cleanly because S22 was
manually blocked; B14 received **zero real LBX webhook events**; B15 is
POLICY_REVIEWED, not a provider fault-injection test. These findings do not make
the whole Step 5 PASS.

Historical stand-043 facts, Widget type-7 evidence and sanitized reports are
inputs to the next steps, not reasons to re-run completed probes or invent test
results. The initial provider-independent cleanup was deliberately performed
before Phase 0 under ANY-504's approved execution order.


### Phase 0 A: Widget and agreement isolation

B1/B2/B6 already establish on stand 043: server auth and required non-payment
reads/creates work; a real authenticated Widget resolves the target customer
with `ident_type=7`; a subscription can be prepared with its own dedicated
agreement; funding the intended agreement changes that subscription's financial
state without unlocking a separately controlled agreement. For the supported
integration scope B6 is **PASS / CONFIRMED_ON_TEST**.

Maintain one dedicated agreement per Portal subscription for its entire history
and authoritative customer/agreement/subscription binding. A new subscription
uses a new agreement; renewal of the *same* subscription is modeled against the
same agreement. Incomplete reads or changed ownership fail closed.

This acceptance does **not** claim live proof for every provider-owned
autopay/payment-method/cancellation operation or every historical revival.
An unverified provider-owned capability is never silently promoted to an access
guarantee. Step 7 configures only the supported Widget/prepared-subscription
flow; Step 8 reconciles conflicts; required full E2E and launched billing
configuration checks remain explicit pre-enable/launch gates.

### Phase 0 B: LBX service-price and accepted-term verification contract

**Phase 0 B8 research outcome (stand 043, 2026-10-13): DONE for the supported integration algorithm, not a certification that production implementation or any specific offer is launch-ready.** The original mandatory live *source-tariff price mutation* probe has been retired by explicit product/architecture decision: it tested catalog repricing propagation already described by LBX, whereas the safety-critical observable mutation of a concrete subscription was tested on stand 043 (B8.3). The attempt to add a service to synthetic tariff 29 did not persist and proves neither a provider defect nor an incompatibility of this integration algorithm; no source-price live propagation was tested. Do not require that redundant experiment again to mark B8 research DONE. Re-open only for contradicting provider facts or a newly discovered mandatory field with no safe source.

LBX commercial model used by Steps 6–9:

- Tariff is a set of commercial rules, billing periods and tariff services. **It has no independently charged single tariff price.** Price rows (recurring price, connection price and effective date) belong to an individual tariff service for the applicable period. The amount of a prepared subscription derives from its actual selected service composition, quantities and applicable effective prices, not from a fictitious `tariff.base_price`.
- A catalog service price change with an effective date defines the price for **new subscription preparations** according to LBX's published rules. Recalculation of previous charges is a separate provider operation. A subscription can also have its own operator-adjusted **effective service price**. Do not infer that all old subscriptions' effective terms change whenever the current catalog price row changes, or that documentation alone proves future renewal behavior for every policy.
- An already prepared subscription's authoritative effective service prices, composition, quantities and aggregate `total_price` are read from that concrete subscription, alongside applicable period, owner/agreement, currency and lifecycle. Current catalog tariff/service price (`tariff_price`) is reference context, **not authority replacing an older accepted price**. B8.3 on stand 043 demonstrated effective service price 10→15→10 using subscription-specific PUT, visible via authoritative point GET despite unchanged subscription instance ID.
- The Portal's immutable independently accepted snapshot pins component/period identities and effective unit prices, quantities, connection/discount terms where applicable, total, account-scoped ISO currency/money units, recurring/customer-obligation terms, technical metric mapping with fixed quantity, and accepted legal/policy revisions. `multiplicator=1` denotes one LBX service unit, not 1,000 Kernel operations. Kernel exclusively records runtime usage and remaining.
- A *new catalog price row* that leaves historically accepted subscription effective terms untouched is **not a commercial mismatch by itself**. A material change to the concrete subscription effective terms conflicts with the pinned snapshot even if `subscription_instance_id` stays unchanged. Missing, unprovable or non-historically-applicable mandatory source facts yield `INCOMPLETE`, never a guessed match. Provider payments, balances, charges, Widget callbacks, instance IDs and mutable history are not substitutes for the accepted terms.

#### Implementation admission and mandatory decision table

This research closure does **not** waive the per-offer Step 6 sellability gate. Before a real RU offer is published, Step 6 must validate a fresh complete LBX tariff→service→period/price projection, its exact normalized account currency (for stand 043 UI/API evidence maps the configured ruble choice to numeric currency 1; confirm and enforce the chosen account's ISO RUB / monetary units, without treating numeric 1 as a universal currency code), and a supported prepaid fixed-period profile. Step 6 must pin provider component/price provenance, published immutable mapping and a controlled historical policy/change-management contract; cannot silently rely on mutable current tariff-only policies as a historical record. Step 7 must obtain explicit versioned product/legal acceptance for renewal/autopay/cancellation when applicable. Unapproved terms and absent provenance make the **specific offer** `NOT_SELLABLE`, not B8 research `NOT DONE`. Future EU currency requires independent account evidence, not EUR testing on RU stand.

The authoritative implementation verifier must classify exactly:

```text
COMPLETE_MATCH     all material independent accepted fields reconstructed
                   from proven sources and equal effective subscription terms
COMPLETE_MISMATCH  full material reconstruction proves a changed effective
                   subscription obligation/composition/term
INCOMPLETE         missing/uncertain source, currency/units, policy applicability
                   or provenance; may additionally flag a known material difference
```

`COMPLETE_MISMATCH` blocks affected access, increments `access_revision`, and enters manual review; `INCOMPLETE` never extends trust. Tests in Steps 6–9 must explicitly cover: (1) catalog service price 10→20 without old subscription effective-price change (no false conflict); (2) new subscription at the currently applicable offer price; (3) subscription-specific effective price 10→15 with unchanged instance (conflict once complete); (4) extra/missing service, quantity, period or total change; (5) missing historical tariff-policy provenance / currency / required field (fail closed); (6) existing Kernel allowance/usage not reset by catalog price change. Application tests may use mocks/fixtures; B8 research did not run these unwritten production tests.

**Evidence labels:** `DOCUMENTED` for LBX tariff-service price/effective-date/new-subscription and operator price rules (https://docs.lbxbilling.ru/tariffs/change_price/ ; https://docs.lbxbilling.ru/subscriptions/subscribe_client/); `CONFIRMED_ON_TEST` for stand-043 subscription-specific 10→15→10 visibility and ruble UI/stand account-linked price display; `NOT_TESTED` for catalog-price mutation propagation (tariff 29 setup was `BLOCKED_SETUP`). These levels must never be presented as a live PASS for an experiment that did not run.

### Phase 0 C: fixed allowance quantity and authoritative cycle semantics

**B9 (research DONE / provider partially confirmed).** LBX
`subscriptions.services[].tariff_service_id` identifies the concrete
commercial service and `multiplicator` is its number of **LBX service
units**. For the observed periodic fixed-price, non-bulk service, outbound
actual-usage reporting to LBX is not needed. The observed `1.0` is one
service unit: neither one Kernel operation nor automatically 1,000 operations.
Step 6 admits a sellable offer only with independently approved, published
and immutable commercial component-to-`product_id`/`metric_key`/fixed-quantity
mapping, tied to the exact provider tariff/service/period/price provenance.
No mapping or historical policy proof means `NOT_SELLABLE`. Normalize
integral-looking provider quantity values losslessly; fractional or invalid
values must not enter the integer Portal-to-Kernel allowance contract.
Only Kernel records actual usage and remaining quantity.

**B10 (research DONE / documented calendar-cycle model accepted).** LBX
`last_tariffication_period_start/end` are calendar-date provider evidence;
do **not** invent account timezone or convert them into exact UTC instants.
A native cycle-instance identifier was not proven. Portal may derive an
immutable provider-cycle key only from a complete, stable, authoritative
subscription/agreement/period/commercial/financial reconstruction and a
genuine next expected cycle. A `period_id` configuration value, charge row,
in-place edit, recalculation, payment, block/unblock or version change is not
proof of a new usage bucket. Overlapping, re-anchored, inconsistent or
incomplete cycles fail closed without refilling quota. Preserve the same
metric/source/`allowance_id`, frozen quantity and Kernel usage on reread and
same-cycle block/unblock; only a proven subsequent cycle creates new IDs.

Stand evidence proves repeated same-cycle reads and adjacent historic charges;
it does **not** independently prove the observed historical charge was produced
by natural renewal. Extra independent B10 renewal tests and a provider
timezone lookup are no longer standalone Phase 0 gates. Steps 8-9 must
implement and test authoritative classification, re-anchor protection,
idempotent allowance identity and paid eligibility before enabling quotas.

**Contract handoff, NOT a wire-format change in this PR:** the older
Portal-to-Kernel AccessSnapshot spec and `purchased_allowances` persistence
use immutable UTC `period_start/period_end`. Their reconciliation with
LBX date-only cycle identity and finite UTC trust/snapshot/grant deadlines
is explicitly assigned to Steps 9-10 in ANY-504. The existing 6h provider
trust lease, up-to-5m snapshot TTL, fail-closed expiry and durable Kernel
usage are retained. Do not ship production quota/reset logic using guessed
LBX-local-midnight UTC bounds or delete UTC wire fields without the coupled
contract/schema/client/fixture review. An unobserved rollover can be resolved
only by bounded reconciliation and the accepted finite trust policy.


### Phase 0 D: customer-list completeness for first-primary selection

**B12 PASS / CONFIRMED_ON_TEST.** The deployed customer-scoped subscription
list and point GET were sufficient to discover multiple candidates, including
a newly created subscription, without assuming pagination, sorting or a
first-row selection rule. Before choosing a target product's primary
subscription, Portal must persist a sufficiently complete customer inventory
observation, point-read potentially relevant candidates, prove
customer/agreement/terms, and combine the observed set with locally linked
non-terminal scopes under the `(user_id, product_id)` lock. Zero proven
eligible candidates, exactly one matching known purchase, and conflicting
or multiple eligible candidates lead respectively to no primary, the proven
primary, or hold/manual review. Incomplete visibility cannot authorize a
fresh create or grant.

Do not introduce a speculative pagination/stabilization subsystem. Exact
provider visibility SLA, races, list cardinality extremes and
webhook-before-read timing were **not** confirmed by B12; Step 8 must test
the application-side concurrency, held scopes and bounded discovery/retry
behavior. B13 independently confirmed read-only discover-first recovery from
a simulated lost CREATE response without a second POST.


### Phase 0 E: Widget identity/security and prepaid eligibility

#### Opaque customer key versus verified Widget identity (B2/B3/B5)

Portal allocates a unique, immutable, non-reusable opaque
`billing_customer_key` and sets it as LBX `users.outer_id` solely for
customer creation, correlation, discover-first recovery and drift detection.
The authoritative LBX-assigned `users.user_id` is retained as the bound
`provider_customer_id`. These identifiers are **not interchangeable**.

**Production Widget target, CONFIRMED_ON_TEST on real stand 043:**
`ident_type=7`, `ident=string(provider_customer_id)`. A type-7 Widget
loaded the expected `users.user_id` through authenticated Client GET.
The historical type-6 Widget lookup also passed as a lookup test, but B3
showed that remapping `users.outer_id` could cause an old type-6 JWT
to resolve a different customer. B3's original provider FAIL remains
recorded; **do not mint type 6** as a production fallback.

Before every Widget mint, Portal independently verifies its session and
legal/purchase/security gates and performs an authoritative Server GET
establishing both `users.user_id == provider_customer_id` **and**
`users.outer_id == billing_customer_key` for the intended customer.
The browser chooses none of these identifiers or claims. Email, phone,
login, name or type 6 are never fallback identity. Any mismatch becomes
`identity_conflict`: no new Widget mint/create and no new paid eligibility
derived from that external slot; restore the **original** `outer_id`
provider-side and reread before releasing the conflict. A **type-6**
Client API JWT was able to modify its own `outer_id`. Type 7 eliminates
the type-6 mutable-key customer-selection failure, but a type-7
`PATCH /client/user` was **not** tested: neither its denial nor its
permission is established. Treat the write risk as unresolved.

#### JWT lifetime and residual replay risk (B4)

**B4 research DONE, initial 900-second acceptance criterion FAIL.**
A real type-7 Widget continued to accept a token after `exp` and rejected
an unchanged backdated-`iat` token when its age exceeded 72 hours in the
observed run. **Old-token survival after remint was directly tested with
type-6 Client API JWTs, not independently reenacted with type 7.** LBX
confirmed via the operator that Client JWT acceptance is bounded by
**72 hours from JWT `iat`**, including backdating; the exact cutoff was
not measured. For the selected type-7 production flow, treat earlier
issued JWTs as potentially usable for this entire window unless actual
provider revocation is independently established. For RU MVP, Portal signs a *fresh*
JWT with `iat=now` at each permitted Widget open after all checks; do
not persist/reuse it, backdate `iat`, add auto-remint/revocation storage,
or present `exp` as a short provider-enforced lifetime.

A previously copied JWT may remain usable for up to 72 hours after its
own `iat`, including after remint/logout. **Fresh mint is not revocation.**
This residual browser-credential exposure requires an explicit security
decision before production Widget enablement. B4 DONE is not security PASS.

#### Server-side Client API permissions (B5)

Widget flags (`disableCreateSubscription`, `disableEditSubscription`)
and LBX tariff/service manage settings restrict presentation or the intended
offer configuration; **they are not demonstrated server-side ACLs**.
B5 confirmed that a **type-6** Client JWT could modify its own
`users.outer_id` (Provider FAIL). Cross-customer subscription GET was
denied with both type-6 and type-7 JWTs in separate read-only probes.
An equivalent `PATCH /client/user` with the selected production type-7
JWT was **not** performed; do not assert either server-side denial or
permission for that untested mode. Direct Client API
service/quantity/payment-method/top-up/autopay mutation authorization
also remains **UNKNOWN**: no safe test fixture established a denial or
a general server-side restriction.

Step 6 publishes only verified fixed prepaid offers with client
service/quantity management OFF and a controlled immutable mapping.
Step 7 prepares subscriptions using Server API, rereads complete accepted
effective service terms, and only then mints the verified type-7 Widget JWT.
Step 8 detects owner, service, quantity, price and period drift even
without a new instance ID. Step 9 grants nothing on conflicting or
incomplete terms. **These checks cannot prevent LBX-side financial
effects of a direct Client API write.** An explicit security/provider
decision on the remaining dangerous mutation paths is still required
before enabling the affected Widget/payment flow; do not declare this
a server-ACL PASS.

#### Prepaid eligibility (B6/B11)

RU MVP supports only approved fixed-price prepaid blocking offers:
`balance_blocks=1`, activation after sufficient funding,
no unsupported trial/demo/credit/promised-payment/postpaid/manual-activation
products. Verify these exact rules for each offer at Step 6 publication;
they are product admission constraints, **not** proof administrators
cannot override LBX state.

Stand evidence proves a waiting, unpaid subscription may have
`state=-2/current_blocking=0` and must be **denied**. One funded
daily subscription became `state=2/current_blocking=0` after
15 RUB funding and 10 RUB charge, leaving 5 RUB. Therefore
`current_blocking=0` on its own, and even `state=2` with an apparent
balance, are **not sufficient paid-access proof**. Require normalized
**ACTIVE** lifecycle, complete owner/agreement/material terms,
verified supported prepaid configuration and authoritative financial
eligibility for the confirmed current cycle; financial or administrative
blocking, missing facts and conflicts deny a new grant/allowance.

**B11 research DONE / automatic unpaid renewal NOT TEST-CONFIRMED.**
The operator manually blocked S22 on 2026-10-13; its next-day state
cannot establish that LBX automatically blocked unpaid renewal.
The official prepaid/blocking contract is DOCUMENTED and accepted as
sufficient to design Steps 6-8, not as a simulated renewal live PASS.
Step 8/9 and Step 11 must validate a *new untouched* prepaid subscription
through naturally processed funded -> underfunded renewal and record
authoritative subscription/agreement/charges/financial block history.
Do not grant a fresh quota when a new cycle is financially ambiguous,
and do not infer the precise LBX midnight/block-job time. Preserve
same-cycle Kernel usage through block/unblock.


### Phase 0 failure and closeout policy

An unresolved provider property that changes a **required architecture
or identity/security choice before implementation** keeps Step 5 gated.
For a documented standard behavior with safe fail-closed design, an
explicitly deferred integration/E2E check may instead be owned by the
appropriate later Step and checked before enablement. Neither route
turns UNKNOWN/FAIL into `CONFIRMED_ON_TEST`.

Any unresolved launch-critical failure means: no affected production
Widget/paid access, no `/eps_payments` fallback, no Portal-owned
payment orchestration; escalate the precise provider/design gap.
B14 real delivery/header/retry/visibility stays UNKNOWN until Step 8
pre-enable verification, or an explicit tested polling-only decision.
B15 retry/recovery policy is reviewed, but no native LBX CREATE
idempotency or forced-500/429 guarantee is assumed.

**Step 5 sign-off is separate from probe research DONE.** Before admitting
Step 6, review the linked evidence/deferral matrix, obtain explicit
decisions on the remaining architectural/security risks, align the
external-billing design and GitHub issue #112, and record the final
Phase 0 architecture-gate verdict in ANY-634. The B8 service-price contract and the other B-probe conclusions are reviewed
together in this single consolidated documentation change. The provider-neutral
Kernel wire redesign for B10 belongs to Steps 9-10 and must not be
prematurely shipped as an unreviewed change to this docs-only PR.

## LBX Widget as RU billing cabinet

Target presentation flags may hide create/edit while keeping stop, payment,
autopay, invoices, and subscription history available, but flags are not the
security boundary.

Widget owns customer-facing billing self-service: top-up/payment UX,
payment-method/card handling, autopay, subscription/balance display, invoices,
money history, and customer-initiated stop/cancellation where supported.

Portal keeps identity/legal acceptance, fixed-offer selection, purchase
uniqueness, non-payment customer/agreement/subscription preparation, discovery,
reconciliation, mappings, entitlements, allowances, and Kernel access delivery.

There is no persistent checkout/session abstraction around Widget. Widget mint is
a separate fail-closed authorization decision. A fresh LBX Client JWT (whose provider-enforced replay window may be
72 hours) may be minted only when all of these hold:

```text
authenticated Portal session
verified Portal <-> LBX customer mapping
billing_customer_key has no identity_conflict
exact target subscription is proven and linked
no unresolved external-create UNKNOWN/AMBIGUOUS state
latest required material verification == COMPLETE_MATCH
no prepared-commercial mismatch or commercial_terms_conflict
Phase 0 E server-side Widget security contract is satisfied
```

`COMPLETE_MISMATCH`, `INCOMPLETE`, `commercial_terms_conflict`,
prepared-commercial mismatch, unresolved create uncertainty, ambiguous
correlation, or `identity_conflict` therefore forbid mint. Existing paid access
may still survive a transient `INCOMPLETE` only inside the ordinary prior LKG
trust lease, but that does not authorize a new Widget credential.

When mint is allowed:

```text
authenticated Portal request
 -> reload current Portal state
 -> verify current customer/subscription/commercial predicates
 -> mint fresh type-7 LBX Widget JWT with iat=now
 -> return Widget bootstrap data
```

If the cabinet cannot be opened, Portal returns a derived `billing_not_ready` or
review-required result without exposing provider internals. Closing the browser
creates no billing state and does **not** revoke an earlier LBX JWT. A later
authenticated open reevaluates the predicate and, if permitted, mints a fresh
type-7 JWT; any older token may remain usable for up to 72 hours from its `iat`
and its residual risk remains a separate pre-enable security decision.

JWT issuance is never evidence of paid access, and existing paid access never by
itself proves that Widget mint is currently safe.

For LBX MVP:

```text
1 Portal User = 1 LBX Customer per billing account
1 paid AnyToolAI subscription = 1 dedicated LBX Agreement
renewal reuses that Agreement
new subscription = new dedicated Agreement
```

Portal does not model agreement balance. Underpayment must remain blocked;
sufficient funding may unblock only the intended subscription; overpayment may
remain provider-owned on that agreement.

## Platform capability manifest and catalog freshness

Platform Kernel hosts the versioned read-only technical manifest and Payments
Portal consumes it through the region-local internal contract:

```http
GET /internal/v1/capability-manifest?tenant_id=anytoolai&region=ru
```

The response is all-or-nothing and includes `schema_version`, tenant/region,
deterministic `manifest_version`, products, and `metric_key -> product_id`
bindings. Kernel validates unique products/metrics and exactly one existing
product for every metric before serving `200`.

`enabled` is admission control for new technical-commercial bindings only. A new
mapping or purchase may reference only enabled products and enabled metrics that
belong to that product. A later `enabled=false` does not rewrite or revoke an
already-pinned purchase/subscription/grant/allowance; runtime emergency disable,
if required, is a separate Kernel policy.

Portal imports the manifest into a local read-only projection atomically. A
manifest sync updates `capability_manifest_last_complete_sync_at` only after a
complete `200`, supported schema, full reference validation, and successful
local projection commit. Timeout, `5xx`, partial/malformed payload, unsupported
schema, broken references, or local transaction failure retain the previous LKG
projection and do not advance freshness.

Use one freshness constant for all projections required to begin a new sale or
publish a new mapping:

```text
new_sales_projection_max_age = 24h
refresh target ~= every 5m + startup
```

A new `PurchaseIntent` is allowed only when both:

```text
capability_manifest_last_complete_sync_at age <= 24h
billing_catalog_last_complete_sync_at age <= 24h
```

A new mapping revision is also allowed only when both projections satisfy that
same freshness bound. Only a complete successful catalog sync refreshes the
catalog timestamp. Failed/partial sync does not.

Staleness blocks new sales and new mapping publication. It does not revoke
existing pinned mappings, subscriptions, grants, or allowances.

The detailed manifest wire contract and contract-fixture rules live in
`docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md`.

## External catalog and mapping model

Component classification:

```text
UNCLASSIFIED
CAPABILITY_BEARING
COMMERCIAL_ONLY
```

`UNCLASSIFIED` makes dependent offers `NOT_SELLABLE`. Missing mapping is never
interpreted as commercial-only.

External usage reporting:

```text
external_usage_reporting = none | required | unknown
```

Only `none` is sellable in this MVP. `required` and `unknown` stay
`NOT_SELLABLE` until a separate external-metering design is approved and
implemented.

Published mapping revisions are immutable, privileged Product/Engineering state.
A new revision may be published only against a fresh complete capability manifest
and fresh complete external billing catalog. Each revision records both the
Platform manifest version and the normalized billing-catalog version/digest used
for validation. Later changes create a new revision; existing pins never rebind.
Historical mapping revisions remain queryable while any purchase/subscription
references them.

Publication validates that every referenced external offer/component still
exists in the current catalog projection, every target product/metric exists and
is enabled in the current manifest, and each metric belongs to the mapped product.

### Purchase-time snapshot

When `PurchaseIntent` is created, Portal first revalidates the exact current offer
against the fresh current catalog and the pinned mapping against the fresh current
manifest, including `enabled` flags and current component structure. The same
local transaction then pins:

- external component references;
- exact mapping revision IDs;
- resolved `product_id` and `metric_key` bindings;
- fixed accepted quantity for each metric;
- exact material commercial fingerprint and legal-document versions.

A later mapping revision does not change an existing purchase/subscription
meaning. If a historical pin is later found invalid/inconsistent, affected paid
access fails closed and enters manual review; MVP does not mutate that pin to a
new mapping revision. Corrective choices are restoring the original semantics,
ending/replacing the commercial relationship through a new normal purchase, or a
separately designed migration mechanism.

Provider internal IDs may be stored as verification evidence without becoming
part of the user-facing commercial fingerprint.

### Commercial fingerprint invariant

The accepted fingerprint is reconstructed from the approved authoritative read
set during:

- prepared-state verification before Widget can open;
- first read that would produce paid access;
- every later access-relevant/renewal read.

Partial reconstruction is forbidden. `INCOMPLETE` does not mean match and does
not extend trust.

A planned material change to a live customer-funded subscription requires ending
that subscription and a new normal purchase/acceptance flow. MVP has no in-place
re-consent.

## Target Payments Portal data model

Exact SQL names/types may follow repository conventions; semantics and
constraints are required.

MVP has exactly one configured external billing account per regional contour.
`external_billing_account_id` is therefore a stable deployment/configuration
scope value used in keys and audit, not a Portal-managed billing-account catalog
or runtime account-routing subsystem. Multi-account-per-contour routing is
deferred.

### Identity and billing customer slot

Retain `users`, auth/session, versioned legal documents, and append-only legal
acceptance. Email is an attribute, not a cross-system key.

`external_billing_customers` has:

```text
UNIQUE(external_billing_account_id, user_id)
billing_customer_key  # immutable opaque non-PII
provider_customer_id  # nullable until proven/bound
```

The row is committed before external customer create. Concurrent purchases reuse
or wait on the same slot. Any uncertain customer create is handled by the single
outbound-create UNKNOWN mechanism below rather than by a separate customer state
machine.

For RU, `billing_customer_key` is the Portal-owned expected value of LBX
`users.outer_id`. Portal never PATCHes that field during normal operation. An
authoritative reread with a different `outer_id` creates `identity_conflict`;
Portal never mutates its key to follow the provider drift. Once a key has ever
been allocated to a Portal customer slot it remains permanently reserved locally
and is never reused for another user/customer even if LBX no longer resolves the
old value.

`identity_conflict` blocks Widget mint, new sales, new customer/agreement/
subscription mutation, identity-based recovery, and all paid access derived from
that customer slot. The Portal commits the resulting paid-fact omissions through
the ordinary revisioned access path. Stable provider IDs may still be used for
read-only diagnosis/reconciliation but never preserve paid access while the
identity invariant is broken. Normal MVP resolution is provider-side restoration
of the original `billing_customer_key` value followed by authoritative reread;
Portal does not adopt a replacement provider `outer_id`.

### PurchaseIntent

There is no Portal-owned commercial Order.

`PurchaseIntent` contains at least:

```text
user_id
external_billing_account_id
product_id
billing_offer_id
accepted commercial_fingerprint
pinned component/mapping/metric-quantity snapshot
client idempotency identity
orchestration state/timestamps
linked external subscription when proven
```

Conceptual states:

```text
created
preparing
awaiting_external_result
linked
resolved_no_external_effect
failed_before_external_effect
manual_review
```

Browser/Widget close does not resolve external uncertainty.

### Purchase scope and unified uncertain outbound-create recovery

`Idempotency-Key` handles retransmission of one public request. Business
uniqueness is `(user_id, product_id)`.

At most one scope-holding purchase flow exists for one user/product. Once a
non-terminal subscription is linked, it owns that scope; a prepared unpaid
subscription therefore blocks a second purchase. A linked prepared/unpaid
subscription has no checkout/session TTL: it keeps `(user_id, product_id)` until
it is authoritatively terminal or the scope is released through audited evidence
that release is safe. Public purchase attempts against such an occupied scope use
a stable provider-neutral error code such as `purchase_scope_occupied`; callers
must not infer provider billing state from internal reason strings.

Customer, agreement, and subscription creation all use one conceptual durable
outbound-create operation model rather than three independent UNKNOWN state
machines. A record carries enough type/scope/correlation to recover the attempted
object, conceptually:

```text
operation_kind = customer | agreement | subscription
scope_ref
request/idempotency correlation
state
unknown_since
unknown_recovery_deadline_at
provider recovery hints
bound provider object id when proven
```

For any of these create operations, timeout, lost response, HTTP 500/ambiguous
provider error after mutation may have happened, or zero recovery matches do not
prove absence. The common UNKNOWN behavior is:

```text
hold the affected scope
allow safe read-only recovery/discovery only
never blind-retry the create
never auto-release on zero matches
unknown_recovery_deadline_at = unknown_since + 2h   # fixed MVP constant
```

The affected scope is the external-customer slot for customer create and the
purchase/product flow for agreement or subscription create. Widget mint and any
independent create that would duplicate the unresolved object remain blocked.

When UNKNOWN is first created, Portal durably schedules one escalation work item
for the fixed two-hour deadline. Before the deadline, safe read-only recovery runs
with urgent cadence. A unique proven match binds immediately; more than one
plausible match enters manual review immediately.

At the deadline, if still UNKNOWN:

```text
operation -> manual_review
reason = external_create_outcome_unknown:<operation_kind>
scope remains held
```

Read-only discovery may continue after escalation, for example every 30 minutes
plus webhook-triggered acceleration. Support/Billing Ops may release a held scope
only through audited provider/human evidence that release is safe, or bind a
recovered object. A late object discovered after manual release never receives
automatic access and enters conflict review if a later purchase already
succeeded.

Automatic scope release is otherwise allowed only when:

- failure happened before any external mutation was possible;
- a linked subscription is authoritatively terminal and no unresolved competing
  flow exists;
- a provider-specific absence predicate has separately been proven safe.

Widget/browser abandonment of an already linked/prepared object is not an UNKNOWN
create outcome and creates no separate checkout/session state.

## Subscription projection and paid eligibility

A local subscription row exists only for a proven external subscription.

For LBX, Portal naming is explicit:

```text
external_subscription_id = LBX subscriptions.subscription_id
subscriptions.outer_id   = non-unique correlation/recovery hint only
```

`subscriptions.outer_id` never proves identity. Recovery candidates found through
that hint must still be point-read and proven by canonical `subscription_id` plus
expected customer/agreement/commercial facts. Multiple plausible matches are
ambiguous and never auto-bind. Once bound, authoritative rereads and local joins
use canonical `subscription_id`, not `outer_id`.

Subscription storage includes at least:

```text
external_billing_account_id
provider_customer_id
provider_agreement_id
external_subscription_id
lifecycle_status
```

Uniqueness includes:

```text
UNIQUE(external_billing_account_id, external_subscription_id)
```

For customer-funded LBX subscriptions, the dedicated-agreement invariant is
permanent, including historical subscriptions. One paid subscription has exactly
one `provider_agreement_id`, and one agreement may never back a different Portal
subscription in the same billing account, even after the first subscription has
ended. The DB guard is therefore unconditional:

```text
UNIQUE(external_billing_account_id, provider_agreement_id)
```

Renewal of the same subscription stays on the same subscription row and keeps the
same agreement. A new subscription uses a new dedicated agreement. If Phase 0 A
demonstrates that LBX requires a new subscription ID to reuse an ended agreement,
that violates the isolation invariant and is a launch blocker rather than a reason
to weaken this uniqueness rule. If an authoritative reread claims a different
agreement for an already-linked subscription, Portal creates
`agreement_binding_conflict`, fails affected paid access closed, and enters manual
review rather than silently rebinding.

`ended` is terminal for a canonical `external_subscription_id` in this MVP. Once
Portal has authoritatively committed `ended`, a later non-terminal provider state
for the same canonical subscription ID is `subscription_terminal_revival_conflict`.
Portal does not reactivate paid access, does not treat the old agreement slot as a
normal live subscription again, and enters manual review. Supporting provider
revival semantics would require a separate explicitly proven design.

Normalized access-relevant fields remain deliberately small:

```text
lifecycle_status:          active | inactive | ended
financial_access_status:   allowed | blocked
commercial_access_status:  eligible | ineligible
```

For customer-funded RU access, `financial_access_status=allowed` requires a
verified supported prepaid-blocking profile, **ACTIVE** lifecycle (not merely
non-terminal), `current_blocking == 0`, complete authoritative owner/agreement,
current-cycle and material-term reads, and independently supportable paid
eligibility. A pending `state=-2/current_blocking=0` subscription is denied;
`state=2/current_blocking=0` alone does not prove a paid period. When an
underfunded renewal or financial block is ambiguous, deny the new allowance
rather than infer access from a balance or payment status.

`commercial_access_status=eligible` additionally requires complete material-term
match, valid pinned mapping/legal/origin rules, and no access conflict.

Unknown provider semantics are normalization errors, not ordinary lifecycle
states. Last-known-good facts may survive only inside their existing finite trust
lease; no prior good state means no access; a previously blocked state remains
blocked.

## Allowances and quota identity

`purchased_allowances` combines two authorities:

```text
quantity              <- immutable accepted fixed offer snapshot
cycle identity/bounds <- authoritative provider cycle facts
```

There is no operator-supplied allowance quantity path. Quantity is a non-negative
integer in Portal storage, AccessSnapshot, and Kernel quota state. Live charges,
balance, payment state, or manual operator input never create or resize a quota
bucket.

Logical allowance identity is:

```text
(
  external billing account,
  external subscription,
  concrete source component,
  metric_key,
  provider_cycle_key
)
<-> exactly one allowance_id
```

A practical relational guard is:

```text
UNIQUE(billing_subscription_component_id, metric_key, provider_cycle_key)
```

Repeated same-cycle reads and financial block/unblock preserve each metric's
`allowance_id`, fixed quantity, and Kernel usage. Only a confirmed new provider
cycle creates new metric-specific IDs.

For a given `allowance_id`, product, metric, integer quantity, and effective wire
period boundaries are immutable. The effective `period_start`/`period_end` are
frozen when that allowance ID is first committed; a later deployment change to
`clock_skew_budget` applies only to future allowance IDs and must not rewrite an
existing tuple. A later read claiming different boundaries or other tuple fields
for the same allowance creates a conflict rather than silently rewriting the
bucket. Kernel independently freezes and verifies the same tuple according to the
companion access contract.

MVP does not stack multiple effective allowances for one `(product_id,
metric_key)`. If conflicting duplicate effective allowances are observed, Portal
fails closed only that metric by omitting the conflicting metric allowance(s)
from the committed effective access set; unrelated product grants and metrics
remain independently eligible. Kernel applies the same metric-local blast radius
as defense in depth.

Portal does not store authoritative runtime `remaining`.

## Product access scope and first-primary selection

For each `(user_id, product_id)` Portal owns one serialization row:

```text
billing_product_access_scope
  user_id
  product_id
  primary_subscription_id nullable

UNIQUE(user_id, product_id)
```

Linking a purchase subscription does not make it primary.

After linked subscription `S` is known, Portal first runs the Phase-0-D-proven
customer-list operation and authoritative point-reads every observed candidate
that is not already authoritatively proven irrelevant to the target product.
Every potentially relevant observed candidate must normalize completely; a failed
or incomplete read prevents first-primary selection and schedules retry/discovery.

The complete normalized observation is persisted before taking the product-scope
lock. This persistence uses short transactions and writes only candidates
classified to the target product for this decision; it does not hold the
product-scope lock while writing customer-wide point-read results. Candidates for
other products may be handled by their own discovery/reconciliation paths.

Only after those target-product candidates are persisted does Portal open the
short decision transaction and lock the product scope. Under that lock it:

```text
1. rereads the union of:
   - target-product candidates from this observation, and
   - already-known local non-terminal candidates for (user, product)
2. evaluates first-primary
```

A candidate seen by the current provider list can therefore never disappear from
the decision merely because its projection had not yet been written before the
lock, while the product lock itself is held only for the serialized decision.

The decision is:

```text
0 eligible
  -> primary stays NULL; S may remain waiting for first activation

exactly 1 eligible and it is linked S
  -> primary = S

exactly 1 eligible but it is not linked S
  -> no automatic primary; manual/conflict path

>=2 eligible
  -> primary stays NULL; subscription_conflict/manual_review
```

Worker completion order, subscription age, amount, or agreement ordering never
selects primary. No durable `primary_decision_attempt`/generation/digest subsystem
is introduced; a worker crash before finalization simply causes a new discovery
observation on retry.

If a trusted primary already exists and a later eligible competitor appears, the
trusted primary continues within normal trust rules; newcomer adds no access and
opens conflict review. If primary becomes blocked, another candidate is not
auto-promoted. If primary becomes terminal and is cleared under the scope lock,
an old candidate is not automatically promoted; a new purchase or audited
operator resolution is required.


## Webhooks

Webhook request handling is intentionally short:

```text
authenticate
 -> minimally validate/extract safe correlation hints
 -> persist one inbox delivery with Portal delivery_id
 -> enqueue/coalesce discovery/reconciliation work
 -> commit
 -> return 2xx
```

No provider REST call occurs inside the webhook request. Payload content does
not directly mutate entitlement. Duplicate/out-of-order deliveries are safe.
Webhook is a priority hint only: an optional acceleration signal.
Authoritative REST reread establishes current provider facts. Scheduled
reconciliation/discovery is the correctness backstop.

**B14 is Phase 0 research DONE / DOCUMENTED, not delivery PASS.**
The official LBX event/payload/configuration contract and ordinary Server REST
reads suffice for the architecture; **zero actual provider webhooks** were
received in the B14 probe. Actual transport/header/shared-secret verification,
delivery/correlation, receipt-before-2xx and webhook-to-REST visibility
remain UNKNOWN. Step 8 must prove them against its deployed endpoint
*before enablement* and test duplicate/order/loss/crash/recovery behavior.
If authenticity cannot be proven, leave the webhook endpoint disabled
and approve a tested polling-only path; never accept anonymous events or
derive a paid grant from webhook body. Provider 500->retry is not a
correctness dependency unless separately proven.

## Reconciliation, discovery, and freshness

### Unified urgent scheduling

Known access-relevant subscription reconciliation uses only two cadence classes:

```text
normal reconciliation = every 15m
urgent reconciliation = no more than 5m between attempts
```

A scope/subscription is urgent when any of these holds:

```text
open or unresolved PurchaseIntent
linked subscription has never yet become eligible
projection_valid_until - now <= 30m
allowance.period_end - now <= 30m
```

A valid webhook may enqueue immediate work but does not create a third cadence
class. When no urgent condition remains, cadence returns to normal 15m.

Stable customer-wide inventory discovery may remain slower (MVP default 6h)
because it searches for unknown provider subscriptions rather than refreshing
already-known access-critical facts.

Provider outage retry may use bounded backoff/jitter but urgent conditions retain
the <=5m maximum attempt spacing. After provider projection trust expires,
read-only retries continue while affected paid facts fail closed.

### Provider trust lease

For each subscription projection:

```text
projection_valid_until = last_authoritative_read_at + 6h
```

Only a complete normalized authoritative read with complete commercial
verification extends this trust.

Local DB reads, snapshot issuance, webhook/Widget callback, PurchaseIntent
activity, failed/partial provider reads, `INCOMPLETE` commercial verification,
normalization errors, or manual-review activity do not extend trust.

At expiry, only paid facts derived from the stale source fail closed; independent
products/sources may continue.

### Deterministic time-boundary commits

Every deterministic access-reducing boundary has a local writer independent of
AccessSnapshot GET and independent of provider availability.

Whenever Portal commits or legitimately refreshes a paid fact, it also schedules
the existing durable worker for the earliest effective access-reducing deadline
for that affected access scope. Conceptually:

```text
next_attempt_at = min(
  effective projection_valid_until,
  finite effective allowance.period_end,
  finite effective grant.valid_until
)
```

This deadline-driven work is separate from the 5m/15m provider HTTP
reconciliation cadence. The same worker infrastructure wakes at the scheduled
`next_attempt_at`; it does not wait for the next reconciliation tick. After a due
commit it schedules the next remaining effective deadline, if any.

At the deadline the worker selects indexed due facts and sends them through the
same effective-access commit path used by other material changes:

```text
SELECT due facts
 -> derive omission of only the due paid facts
 -> short DB transaction
 -> if semantic effective set changed:
      access_revision = N + 1
      upsert durable invalidation N + 1
 -> schedule next remaining effective deadline
 -> COMMIT
```

This path performs **no provider HTTP**. It may only reduce/omit previously known
access; it cannot add a grant, create a renewal allowance, unblock a subscription,
or extend provider trust. Positive changes still require their ordinary
authoritative source.

AccessSnapshot GET remains strictly read-only and never creates a revision to
handle expiry. A due Product B fact therefore becomes `N+1: A only` rather than
causing an overdue B deadline to keep a new snapshot for independent Product A
expired. No separate expiry service and no fleet-wide user snapshot poller are
introduced.

The effective time bounds used for authorization include the clock-skew safety
haircut defined by the companion Portal<->Kernel contract. A finite raw deadline
is therefore scheduled using its conservative effective deadline; a null
`grant.valid_until` remains null and contributes no grant-terminal deadline, while
provider/source trust still contributes its own finite effective deadline.

### Fenced reconciliation lease

Per-subscription authoritative reads use a PostgreSQL fenced lease:

1. short transaction claims owner/expiry and increments fencing token;
2. commit;
3. provider HTTP call with no DB transaction open;
4. short transaction applies only if the same fencing token is current.

Superseded workers cannot commit stale provider reads.

## Subscription lifetime and allowance periods

Subscription lifetime and allowance period are separate:

```text
subscription terminal boundary != allowance.period_end
```

For open-ended recurring subscriptions:

```text
grant.valid_until = null
```

`null` stays `null` in the wire contract and does not mean infinite provider
trust.

**B10 contract review pending Steps 9-10:** LBX returned calendar-date
`last_tariffication_period_start/end`, **not** verified UTC instants. The
pre-existing provider-UTC/source-period and immutable Kernel UTC allowance
wire rules in this document and its companion are not yet reconciled with
that evidence. Do not project a guessed LBX timezone or midnight cutoff.
Until the coupled producer/consumer redesign is reviewed, the legacy contract
below is not proof that LBX supplies those instants; actual date-only provider
cycle identity stays Portal-internal.

The existing Portal/Kernel baseline retains UTC half-open `[start, end)`
authorization bounds for independently supported finite facts, with the
configured clock-skew budget in the companion contract. This does **not**
assert that LBX period date fields can be used directly as those UTC bounds.

If an allowance expires before the next provider cycle is authoritatively
confirmed, the product grant may remain but no future metric bucket is invented;
metered paid usage fails closed at the effective old `period_end`. A later
confirmed cycle creates new metric-specific IDs using the pinned fixed quantities.

## Access boundary with Platform Kernel

Payments Portal is the authority for the derived **paid** access projection.
Platform Kernel never consumes provider-specific billing facts.

For each known `(tenant_id, region, user_id)`, Portal exposes a complete
vendor-neutral paid effective-access state consisting of product grants and
metric allowances. The initial state is the implicit immutable empty state:

```text
access_revision = 0
grants = []
allowances = []
```

Revision zero requires no persisted access-state row, and AccessSnapshot GET is
read-only. The first material paid-access transition atomically creates revision
`1` and durable invalidation `1`; after that, revisions never return to zero.

One `access_revision` identifies one immutable semantic effective-access set. Any
material add, omission, or change of a grant/allowance commits revision `N+1` and
durable invalidation before it can be returned. Deterministic due-boundary
processing uses the same commit path and may only reduce the affected paid facts.
Independent products/facts remain independent.

Portal supplies allowance identity and purchased quantity. Platform Kernel owns
durable actual usage, remaining-quota calculation, and runtime enforcement. A
product grant alone does not authorize a paid metered action: each paid metered
action has exactly one Kernel-owned `metric_key` and requires the corresponding
current allowance. MVP does not stack multiple effective allowances for one
metric.

Free, guest, and trial entitlement/quota remain Kernel-owned policies. Until a
paid grant exists, Portal's paid AccessSnapshot is empty; this rewrite does not
carry forward Portal-issued unpaid/free/trial grants.

The exact HTTP schemas, canonical Portal `user_id`, host/caller ownership,
freshness fields, clock-skew rules, status/error semantics, request-driven
refresh, revision-floor behavior, invalidation outbox/ack rules, immutable
allowance tuple, usage-ledger lifetime, and contract fixtures are defined
exclusively by:

`docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md`.

## Manual review

`manual_review` is operational workflow, never access authority.

Typical reasons include:

- duplicate/conflicting subscription;
- `external_create_outcome_unknown:<operation_kind>`;
- ambiguous external create/recovery;
- unknown external customer or `identity_conflict`;
- `agreement_binding_conflict`, subscription identity conflict, or
  `subscription_terminal_revival_conflict`;
- unmapped/unclassified component or duplicate metric source;
- invalid historical mapping pin;
- normalization/integration uncertainty;
- prepared-commercial mismatch or `commercial_terms_conflict`;
- `allowance_cycle_conflict`/allowance tuple conflict.

Controlled resolutions may bind a proven external object, release a scope after
audited evidence of safe absence, restore/prove the original customer identity,
mark duplicate/conflict, or accept an already-proven subscription as primary
under the product scope lock. Operators never directly set entitlement active,
never supply allowance quantity, and never rebind an existing purchase to a
different mapping revision.

MVP requires durable records, alerting, runbook, and controlled admin command/API;
a dedicated manual-review UI is not required.

## Worker topology and transactions

MVP runs a durable billing worker embedded in the Payments Portal API process
with one API replica initially. Correctness-critical work lives in PostgreSQL,
not FastAPI `BackgroundTasks` or an in-memory queue.

Queue claims, unified outbound-create UNKNOWN escalation, deadline-driven
deterministic due-time processing, product-scope decisions, reconciliation
leases, and invalidation delivery must be safe for multiple consumers even though
initial deployment has one replica.

No external network request runs inside an open DB transaction. Transactions are
short and cover local state creation, claims/leases, access decisions, outbox
updates, and atomic projection/access changes. Deterministic time-boundary commits
perform no provider HTTP at all.

RabbitMQ/Kafka is not required for MVP.

## Security and PII

Provider credentials, webhook secrets, Widget signing secrets, and payment
credentials live only in runtime secret configuration.

`billing_customer_key` is opaque, immutable, and non-PII. Email, phone, and name
are not cross-system or Widget identity authority. Portal never changes its key
to follow provider-side `outer_id` drift and never reuses an allocated key.

Widget JWT is signed only by Portal backend after verified user/customer mapping
with `ident_type=7`, `ident=string(provider_customer_id)`, fresh `iat=now`, and
an authoritative paired `users.user_id`/`users.outer_id` check. UI flags are
not provider-side ACLs. B4 proved `exp` non-enforcement on a real type-7
Widget; old-token survival after remint was tested with type-6 Client API
JWTs, not independently with type 7. The vendor-confirmed 72h-`iat`
window is treated conservatively as a potential exposure, **not** as
automatically safe for launch. B5 proved an identity write with type 6;
production type-7 identity writes and other mutation ACLs remain UNKNOWN. Explicit security resolution is
required before affected Widget/payments enablement. Active `identity_conflict`,
unresolved external-create uncertainty, or incomplete/mismatching commercial
verification prevents mint.

Portal<->Kernel internal APIs require TLS, trusted-service authentication, and
tenant/region scope. A regional contour never reads/writes another contour's
billing/access data.

Logs must not expose webhook secrets, Widget JWT/signing material, auth data, or
unnecessary billing PII.

## Observability and audit

Monitor at minimum:

- manifest/catalog age and sync failures;
- not-sellable reasons and invalid/unclassified mappings;
- customer/recovery UNKNOWN, ambiguous states, and `identity_conflict`;
- oldest `external_create_outcome_unknown` and pending fixed 2h escalation by
  operation kind;
- manual-review count/age by reason;
- normalization and commercial-verification failures;
- discovery/reconciliation success, latency, trust-deadline proximity;
- deterministic due-boundary scheduling lag, overdue work, and execution lag;
- urgent vs normal reconciliation backlog;
- work-queue depth/oldest item;
- webhook auth failures/delivery lag;
- commercial/agreement/subscription/allowance conflicts;
- access fact omissions and revision changes;
- AccessInvalidation delivery lag/errors and Kernel stale-snapshot rejection;
- provider latency/timeouts/error rate.

Audit must explain why access changed and identify the authoritative read,
pinned mapping/commercial snapshot, provider cycle/source, deterministic temporal
boundary, primary decision, or manual resolution without creating a shadow
financial ledger.

## Clean pre-production reset and implementation ordering

`ANY-504` is the current implementation-sequence authority. It supersedes older
ordering statements in this document, including the order below, wherever they
delay provider-independent pre-production cleanup until Phase 0 PASS. This
design remains authoritative for target architecture and provider-contract
requirements. Phase 0 remains the hard gate for provider-dependent production
semantics, Widget/LBX production behavior, and launch. The order below is
retained as historical design context.

Historical ordering statement, superseded for current execution sequencing by
`ANY-504`: destructive rewrite begins only after all Phase 0 launch-critical
gates pass.

Order:

0. Run Phase 0 A-E and record PASS evidence. Reuse existing stand-043 REST facts;
   prove missing semantics, especially authenticated Widget behavior, bounded
   Widget remint overlap, `users.outer_id` drift/recovery, and stable subscription
   -> agreement binding/isolation with no cross-subscription agreement reuse.
1. Supersede contradictory canonical ADR/docs in Portal and Kernel.
2. Remove obsolete Portal Product/Bundle/Plan/PlanLimit/Order and direct-payment
   semantics; replace the disposable Alembic baseline and recreate dev/test DBs.
3. Implement the Kernel-hosted capability/metric manifest contract and Portal
   atomic LKG manifest/catalog freshness projections, including `enabled`
   admission semantics.
4. Implement controlled mapping publication against fresh manifest + fresh
   billing catalog, immutable historical revisions, and purchase-time
   mapping/fingerprint/fixed-quantity snapshot.
5. Implement one configured billing account per contour, durable external-customer
   slot using one `billing_customer_key`, canonical provider subscription identity,
   permanently unique dedicated `provider_agreement_id`, non-payment preparation,
   and one unified customer/agreement/subscription outbound-create UNKNOWN recovery
   path with the fixed 2h escalation.
6. Implement PurchaseIntent scope, no checkout TTL for linked prepared/unpaid
   subscription ownership, stable provider-neutral occupied-scope errors, complete
   prepared-state commercial verification, fail-closed Widget mint-on-open, and
   manual-review controls.
7. Implement the actual LBX customer-list/point-read behavior proven in Phase 0 D,
   persist target-product observation before the product decision lock,
   first-primary selection, fenced reconciliation, unified urgent scheduling,
   prepaid normalization, terminal-revival conflict, and 6h provider trust lease.
8. Implement metric-specific allowance identity/cycles from Phase 0 evidence with
   immutable integer quantity and effective allowance tuple, metric-local duplicate
   conflict, quantity pinned only from accepted fixed terms, and no provisional
   rollover.
9. Implement deadline-scheduled deterministic local time-boundary commits plus
   implicit revision-zero/committed immutable-revision AccessSnapshot, durable
   invalidation, and Kernel revision-floor consumer according to the companion
   contract.
10. Integrate allowances into Kernel durable quota consumption, including metered
    action `metric_key` requirements, immutable existing allowance bounds across
    clock-skew-config changes, clock-safe effective bounds, request-driven snapshot
    refresh, and usage lifetime independent from snapshot/cache presence.
11. Run cross-repo contract/integration proofs with producer-owned fixtures,
    canonical Portal UUID identity, integer quantity, invalidation in-flight ack
    races, and exact HTTP semantics.
12. Repeat critical LBX probes against deployed RU configuration before launch.

No dual-write old/new billing compatibility layer is required.

## Implementation-plan proof areas

The later implementation plan must contain concrete automated/provider proofs for
these areas rather than duplicating a large test matrix here:

- Phase 0 A-E launch evidence, including Widget remint overlap,
  `outer_id` drift/recovery, stable subscription -> agreement identity, and no
  agreement reuse across different subscription IDs;
- complete commercial re-verification and `NOT_SELLABLE` fallback;
- fail-closed Widget mint and paid access under identity/commercial conflict;
- unified customer/agreement/subscription uncertain-create recovery, fixed 2h
  escalation, and no unsafe scope release;
- linked prepared/unpaid scope remains held with no checkout TTL until terminal or
  audited safe release, with a stable provider-neutral public error;
- canonical LBX `subscription_id` binding with non-unique `outer_id` only as a
  recovery hint;
- `ended -> non-terminal` same-ID revival fails closed as conflict;
- full uniqueness of `(external_billing_account_id, provider_agreement_id)` also
  prevents a new subscription from reusing a historical ended agreement;
- first-primary persists target-product observations before acquiring the product
  decision lock and includes every observed candidate;
- fresh manifest + fresh catalog mapping publication and immutable historical pin;
- unified urgent scheduling and provider trust expiry;
- every committed paid fact schedules the existing durable worker for its nearest
  effective access-reducing deadline; due omission occurs without provider HTTP,
  preserves independent products, and increments revision;
- fixed quantity/cycle identity, non-negative integer quantity, immutable allowance
  tuple across clock-skew-config changes, metric-local duplicate conflict, and
  multi-metric bucket isolation;
- implicit revision `0`, immutable semantic revisions, and independent fact
  omission;
- AccessInvalidation outbox/retry plus revision-floor and in-flight `204` races;
- same-cycle allowance omission/reappearance preserves durable Kernel usage;
- paid metered action requires its exact metric allowance; no allowance stacking;
- `null grant.valid_until` stays null, clock-skew-safe effective trust/period/grant
  bounds are conservative, and `refresh_after <= expires_at`;
- canonical AccessSnapshot/Invalidation `user_id` is the Portal identity UUID;
- request-driven snapshot refresh with no fleet-wide user poller;
- concurrent durable Kernel quota consumption;
- capability `enabled` admission semantics, manifest LKG/freshness, and
  producer-owned/hash-checked cross-repo contract fixtures;
- architecture checks preventing provider concepts from leaking into Kernel.

## Explicit non-goals

MVP does not:

- make Platform Kernel a billing client;
- make Payments Portal a second commercial catalog, financial ledger, or payment
  orchestrator;
- call payment-specific LBX REST APIs;
- build Portal-owned card/payment/autopay/invoice/payment-history UI where Widget
  provides it;
- treat Widget JS flags as ACLs or PII as identity authority;
- preserve paid access while `billing_customer_key` identity is in conflict;
- rebind an existing purchase/subscription to a newer mapping revision;
- support provider revival of an `ended` subscription ID without a separate
  approved design;
- reuse a dedicated provider agreement for a different subscription, including
  after the original subscription ended;
- support bundles, overlapping access-producing subscriptions, allowance stacking,
  duplicate metric sources, shared metrics, or paid overage;
- support postpaid/debt access or dynamic/prorated/charge-derived quota;
- support Portal-initiated upgrade/downgrade/refund/dispute/commercial trial;
- issue Portal-owned unpaid/free/trial grants in this billing rewrite;
- support operator-supplied paid allowance quantity;
- release a linked prepared/unpaid purchase scope because a checkout/session TTL
  or browser-close timer elapsed;
- support in-place re-consent/material mutation of live customer-funded
  subscriptions;
- create provisional renewal allowances;
- auto-bind unknown customers using PII;
- auto-release uncertain external create scope because recovery found zero rows;
- implement external usage delivery in the baseline MVP;
- introduce a separate expiry service or fleet-wide AccessSnapshot poller;
- introduce a Portal billing-account registry/multi-account routing subsystem;
- introduce a shared Portal/Kernel runtime package for contracts;
- decide merchant-of-record, 54-FZ, or legal retention policy without
  Legal/Finance confirmation;
- preserve legacy direct-payment schema compatibility after Phase 0 passes.

## Resulting bounded contexts

```text
External Billing
  commercial catalog and billing lifecycle
  provider-owned payment/autopay/refund/invoice/self-service UX

Payments Portal
  AnyToolAI identity and legal acceptance
  external-billing anti-corruption layer
  one configured billing account per contour
  one immutable opaque external-customer key + fail-closed drift detection
  catalog/subscription projections + freshness gates
  immutable mappings + accepted commercial/quantity snapshot
  unified durable outbound-create recovery and manual review
  LBX discovery/reconciliation proven by Phase 0
  deadline-scheduled deterministic local time-boundary access reductions
  product-scope primary selection
  paid entitlements + metric-specific integer allowances
  complete paid AccessSnapshot + durable AccessInvalidation

Platform Kernel
  technical product/metric vocabulary + Capability Manifest
  free/guest/trial policy outside paid billing projection
  monotonic AccessSnapshot revision floor
  durable actual usage by allowance_id independent of snapshot presence
  runtime quota enforcement and execution
```

Platform Kernel never calls External Billing directly.  
Payments Portal never calls payment-specific provider APIs.  
RU billing interaction is LBX Widget, subject first to Phase 0 feasibility and
again to the final deployed-configuration gate.
