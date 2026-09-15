# External billing boundary and Payments Portal redesign

Status: review requested after tenth external-review amendments  
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
commerce/direct-payment schema is disposable, but the clean Alembic reset is
allowed only after every launch-critical LBX Phase 0 gate in this document passes
on the real test configuration.

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

## Phase 0: LBX feasibility gate before destructive implementation

Phase 0 is an architecture gate, not end-of-project QA. Before deleting the old
commerce model, resetting Alembic, implementing the production LBX adapter, or
building paid Kernel integration, run the required probes against the real LBX
test environment.

Evidence labels:

```text
DOCUMENTED        = public/provider documentation only
VENDOR_CONFIRMED  = vendor confirmed for our deployment
CONFIRMED_ON_TEST = reproduced on the real test stand
```

Launch-critical properties require `CONFIRMED_ON_TEST`.

Existing stand-043 evidence is input, not something to rediscover from scratch.
Known facts already include `users.outer_id`, `agreement_number`, non-unique
`subscriptions.outer_id`, `state`, `current_blocking`, and
`last_tariffication_period_*`. Phase 0 proves the semantics we depend on.

As of the current review, authenticated Widget operation has not yet been proven
on stand 043. That remains a launch gate, not an assumption.

### Phase 0 A: Widget and agreement isolation

Prove:

- authenticated Widget rendering with real signing/configuration;
- Portal-like non-payment preparation of customer -> dedicated agreement ->
  subscription;
- the concrete provider agreement identifier for a subscription can be read
  authoritatively and remains stable for that subscription/renewal;
- funding Agreement A cannot make Agreement B commercially/access eligible;
- autopay/payment-method behavior is isolated to the intended agreement;
- cancellation/stop of A cannot mutate B;
- prepared unpaid and underpaid subscriptions remain access-ineligible;
- sufficient Widget funding changes only the intended subscription to the
  financially allowed state without Portal payment API calls.

Client-side Widget flags are presentation only; security proof is Phase 0 E.

### Phase 0 B: complete material-term re-verification

Every material field in the accepted commercial fingerprint must have a proven
authoritative re-verification source for the concrete subscription.

The authoritative read set may contain more than one provider read, for example a
subscription read plus an exact immutable/revision-bound tariff read, but Phase 0
must prove that every source unambiguously applies to that concrete subscription.

Required material fields include, where applicable:

```text
price
currency
billing cadence/recurrence
customer payment obligation
product/component composition
metric set
fixed allowance quantities/policies
material renewal/cancellation semantics
```

Observed verification has exactly three outcomes:

```text
COMPLETE_MATCH
COMPLETE_MISMATCH
INCOMPLETE
```

Rules:

- `COMPLETE_MATCH` may extend provider-fact trust;
- `COMPLETE_MISMATCH` creates `commercial_terms_conflict`, blocks paid access,
  increments `access_revision`, and enters manual review;
- `INCOMPLETE` is normalization/integration failure, never an implicit match, and
  does not extend trust.

If a material field cannot be re-read/reconstructed reliably by design, the offer
is `NOT_SELLABLE`.

Mandatory mutation probes include changing the source tariff and, where allowed,
operator-side material subscription terms after preparation. A customer
obligation/access change that remains invisible to the approved authoritative
read set is a launch blocker.

### Phase 0 C: fixed allowance quantity and authoritative cycle semantics

For every metered sellable offer prove:

```text
fixed quantity per metric from provider-owned offer/tariff
period_start
period_end
cycle_identity
component/source identity
metric/source binding
```

Allowance quantity is captured before acceptance from provider-owned commercial
configuration and pinned in the accepted snapshot. Live charges, agreement
balance, payment amount/status, and other mutable funding artifacts never define
or resize quota.

Prefer a native stable provider cycle ID. If none exists, derived identity is
allowed only when test evidence proves its fields remain stable across rereads
and financial block/unblock and change only for a real new billing cycle.

The probe must prove, including with multiple metrics when the tariff model can
represent them, that:

- same-cycle reread preserves each metric/source/cycle `allowance_id`;
- financial block/unblock preserves IDs, pinned quantities, and already-used
  Kernel amounts;
- mutable charge recalculation does not change quantity, cycle identity,
  commercial fingerprint, or runtime bucket identity;
- a confirmed new provider cycle creates new metric-specific IDs with fresh
  Kernel usage counters.

The stand-043 same-charge/same-period mutation after funding is an explicit
negative test: charge state is not quota authority.

### Phase 0 D: customer-list completeness for first-primary selection

Determine whether the actual LBX customer subscription list, using supported
pagination/page size, gives a sufficiently complete candidate set before Portal
selects the linked purchase subscription.

Probe:

- sort stability and pagination behavior;
- insert/delete while reading;
- visibility delay after successful create/read;
- webhook-before-listing visibility;
- expected MVP customer cardinality;
- concurrent/second-subscription scenarios that might hide a competing row.

If one complete list operation is proven sufficient, implement only that path.
If a real competing row can be hidden, add only the minimal bounded stabilization
proved necessary. Do not build a generic consistency subsystem for hypothetical
providers.

### Phase 0 E: Widget identity/security and prepaid eligibility

#### One opaque customer key

Portal creates one immutable opaque non-PII `billing_customer_key` for the unique
`(external_billing_account_id, user_id)` customer slot before external customer
creation.

For RU the intended mapping is:

```text
Portal billing_customer_key
  = LBX users.outer_id
  = Widget ident with ident_type=0
```

Phase 0 E must prove that `ident_type=0` safely authenticates the mapped customer
in the real Widget configuration. If it does not, this gate fails and the design
is revisited; MVP does not silently add a second identity key.

Email, phone, and name are never Widget identity authority.

The Portal-owned key is immutable even though stand-043 has demonstrated that LBX
can mutate `users.outer_id`. Portal must never PATCH `outer_id` as normal
application behavior. Phase 0 E must explicitly probe drift:

```text
1. create/bind customer with Portal key K1
2. prove lookup and Widget identity through K1
3. mutate LBX users.outer_id externally to K2
4. prove authoritative reread detects K2 != K1
5. prove old-K1 lookup behavior and whether LBX permits K1 reuse elsewhere
6. prove Portal never reuses K1 regardless of provider behavior
7. restore K1 through controlled provider-side resolution
8. reread and prove identity is restored
```

Any authoritative mismatch becomes `identity_conflict`; it is never solved by
adopting K2 locally or silently creating a second key. While the conflict exists,
all paid grants/allowances derived from that external customer slot fail closed.
Stable provider IDs remain usable only for read-only diagnosis/reconciliation,
not to preserve paid access. Normal MVP resolution restores the original K1 on
the provider side and then proves it by authoritative reread.

#### Server-generated bounded Widget credential

Widget JWT is minted only by Portal backend after authenticated Portal-user ->
verified LBX-customer resolution. Browser input never authoritatively chooses
`ident`, `ident_type`, customer, agreement, or permissions.

Phase 0 must prove a provider-enforced bounded lifetime using supported `exp`, an
`iat` maximum age, a revocable short-lived session, or equivalent. An ignored
claim or effectively unbounded replayable token blocks launch.

Repeated mint must also have bounded overlap. Phase 0 E must prove one of:

1. the provider supports one live/revocable Widget session for the linked
   subscription/customer and a new mint invalidates/revokes the prior live
   session; or
2. provider-enforced short `exp`/maximum-age semantics bound concurrent old-token
   survival tightly enough that remint cannot accumulate effectively long-lived
   credentials.

If neither property is `CONFIRMED_ON_TEST`, launch fails rather than adding an
unproven client-side assumption. Portal-side request rate limiting may be abuse
control but is not a substitute for provider-enforced credential lifetime.

#### Server-side operation scope

JavaScript flags such as `disableCreateSubscription` and
`disableEditSubscription` are not ACLs. Phase 0 must prove either:

1. agreement-scoped server authorization; or
2. customer-scoped identity plus server-side authorization that blocks unsafe
   commercial mutation independently of client flags.

The hostile-client probe deliberately enables create/edit controls and attempts
arbitrary subscription creation, tariff/service modification, unintended
agreement/top-up/autopay operation, cross-customer use, principal tampering, and
expired-token replay. PASS depends on server behavior, not hidden buttons.

While `identity_conflict` is active, Phase 0 must also prove that Portal issues no
Widget JWT, starts no new customer/agreement/subscription creation, and derives no
paid access from that external customer slot.

#### Prepaid eligibility

RU customer-funded MVP supports only tariff configurations classified:

```text
PREPAID_BLOCKING_CONFIRMED
```

For every sellable tariff prove:

```text
prepared unpaid       -> financially blocked
underpaid             -> financially blocked
sufficiently funded   -> financially unblocked
next unfunded renewal -> financially blocked again
```

Paid access requires a complete authoritative subscription read satisfying:

```text
non-terminal lifecycle
billing_mode == PREPAID_BLOCKING_CONFIRMED
current_blocking == 0
complete material terms == accepted fingerprint
no access/subscription conflict
```

`state=2 + current_blocking=0` alone never means payment. Postpaid/debt semantics
are unsupported and therefore `NOT_SELLABLE`.

### Phase 0 failure policy

Any launch-critical failure means:

```text
STOP external-billing rewrite
NO /eps_payments fallback
NO Portal-owned payment orchestration
escalate provider capability gap
```

Critical probes are repeated against the deployed RU configuration before
launch.

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
a separate fail-closed authorization decision. A fresh short-lived Widget JWT may
be minted only when all of these hold:

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
 -> mint fresh short-lived Widget JWT
 -> return Widget bootstrap data
```

If the cabinet cannot be opened, Portal returns a derived `billing_not_ready` or
review-required result without exposing provider internals. Closing the browser
creates no billing state. A later authenticated open reevaluates the predicate
and, if still allowed, mints a new token subject to the Phase-0-proven overlap
rule above.

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
billing_account_id
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
subscription therefore blocks a second purchase.

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
unknown_recovery_deadline_at = unknown_since + 2h   # MVP default, configurable
```

The affected scope is the external-customer slot for customer create and the
purchase/product flow for agreement or subscription create. Widget mint and any
dependent create that would duplicate the unresolved object remain blocked.

When UNKNOWN is first created, Portal durably schedules one escalation work item
for the deadline. Before the deadline, safe read-only recovery runs with urgent
cadence. A unique proven match binds immediately; more than one plausible match
enters manual review immediately.

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

For customer-funded LBX subscriptions, the dedicated-agreement invariant is also
materialized. One non-terminal paid subscription has exactly one
`provider_agreement_id`, and that agreement cannot back two non-terminal Portal
subscriptions in the same billing account. A practical DB guard is a partial
unique constraint/index equivalent to:

```text
UNIQUE(external_billing_account_id, provider_agreement_id)
WHERE lifecycle_status != 'ended'
```

Renewal of the same subscription keeps the same agreement. A new subscription
uses a new dedicated agreement. If an authoritative reread claims a different
agreement for an already-linked non-terminal subscription, Portal creates
`agreement_binding_conflict`, fails affected paid access closed, and enters
manual review rather than silently rebinding.

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
`PREPAID_BLOCKING_CONFIRMED` tariff, complete authoritative subscription read,
non-terminal lifecycle, and `current_blocking == 0`.

`commercial_access_status=eligible` additionally requires complete material-term
match, valid pinned mapping/legal/origin rules, and no access conflict.

Unknown provider semantics are normalization errors, not ordinary lifecycle
states. Last-known-good facts may survive only inside their existing finite trust
lease; no prior good state means no access; a previously blocked state remains
blocked.

## Allowances and quota identity

`purchased_allowances` combines two authorities:

```text
quantity              <- immutable accepted fixed offer/operator-comp snapshot
cycle identity/bounds <- authoritative provider cycle facts
```

Live charges, balance, or payment state never create or resize a quota bucket.

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

For a given `allowance_id`, product, metric, quantity, and period boundaries are
immutable. A later read claiming different boundaries or other tuple fields for
the same allowance creates a conflict rather than silently rewriting the bucket.
Kernel independently freezes and verifies the same tuple according to the
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

No provider REST call occurs inside the webhook request. Payload content does not
directly mutate entitlement. Duplicate/out-of-order deliveries are safe.

Webhook is a priority hint only. Authoritative reads remain access authority.
Scheduled reconciliation/discovery is the correctness backstop.

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

The existing durable Portal worker selects indexed due facts, including effective
conservative deadlines derived from:

```text
projection_valid_until
a finite allowance.period_end
a finite grant.valid_until
```

and sends them through the same effective-access commit path used by other
material changes:

```text
SELECT due facts
 -> derive omission of only the due paid facts
 -> short DB transaction
 -> if semantic effective set changed:
      access_revision = N + 1
      upsert durable invalidation N + 1
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
haircut defined by the companion Portal<->Kernel contract.

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

`null` does not mean infinite provider trust.

Raw provider intervals are UTC half-open `[start, end)`. Portal retains those raw
bounds for provider/cycle evidence and publishes conservative effective
authorization bounds to Kernel using the configured clock-skew budget defined in
the companion contract.

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

The exact HTTP schemas, host/caller ownership, freshness fields, clock-skew
rules, status/error semantics, request-driven refresh, revision-floor behavior,
invalidation outbox/ack rules, immutable allowance tuple, usage-ledger lifetime,
and contract fixtures are defined exclusively by:

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
under the product scope lock. Operators never directly set entitlement active
and never rebind an existing purchase to a different mapping revision.

MVP requires durable records, alerting, runbook, and controlled admin command/API;
a dedicated manual-review UI is not required.

## Worker topology and transactions

MVP runs a durable billing worker embedded in the Payments Portal API process
with one API replica initially. Correctness-critical work lives in PostgreSQL,
not FastAPI `BackgroundTasks` or an in-memory queue.

Queue claims, unified outbound-create UNKNOWN escalation, deterministic due-time
boundary processing, product-scope decisions, reconciliation leases, and
invalidation delivery must be safe for multiple consumers even though initial
deployment has one replica.

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

Widget JWT is signed only by Portal backend after verified user/customer mapping;
client flags are not ACLs; launch requires server-side operation scope, bounded
credential lifetime, and bounded remint overlap proven by Phase 0 E. Active
`identity_conflict`, unresolved external-create uncertainty, or
incomplete/mismatching commercial verification prevents mint.

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
- oldest `external_create_outcome_unknown` and pending 2h escalation by operation
  kind;
- manual-review count/age by reason;
- normalization and commercial-verification failures;
- discovery/reconciliation success, latency, trust-deadline proximity;
- deterministic due-boundary backlog/lag;
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

Destructive rewrite begins only after all Phase 0 launch-critical gates pass.

Order:

0. Run Phase 0 A-E and record PASS evidence. Reuse existing stand-043 REST facts;
   prove missing semantics, especially authenticated Widget behavior, bounded
   Widget remint overlap, `users.outer_id` drift/recovery, and stable subscription
   -> agreement binding.
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
   dedicated `provider_agreement_id`, non-payment preparation, and one unified
   customer/agreement/subscription outbound-create UNKNOWN recovery path.
6. Implement PurchaseIntent scope, complete prepared-state commercial verification,
   fail-closed Widget mint-on-open, common UNKNOWN 2h escalation, and
   manual-review controls.
7. Implement the actual LBX customer-list/point-read behavior proven in Phase 0 D,
   persist target-product observation before the product decision lock,
   first-primary selection, fenced reconciliation, unified urgent scheduling,
   prepaid normalization, terminal-revival conflict, and 6h provider trust lease.
8. Implement metric-specific allowance identity/cycles from Phase 0 evidence with
   immutable allowance tuple, metric-local duplicate conflict, quantity pinned
   from accepted fixed terms, and no provisional rollover.
9. Implement deterministic local time-boundary commits plus implicit
   revision-zero/committed immutable-revision AccessSnapshot, durable invalidation,
   and Kernel revision-floor consumer according to the companion contract.
10. Integrate allowances into Kernel durable quota consumption, including metered
    action `metric_key` requirements, clock-safe effective bounds, request-driven
    snapshot refresh, and usage lifetime independent from snapshot/cache presence.
11. Run cross-repo contract/integration proofs with producer-owned fixtures,
    invalidation in-flight ack races, and exact HTTP semantics.
12. Repeat critical LBX probes against deployed RU configuration before launch.

No dual-write old/new billing compatibility layer is required.

## Implementation-plan proof areas

The later implementation plan must contain concrete automated/provider proofs for
these areas rather than duplicating a large test matrix here:

- Phase 0 A-E launch evidence, including Widget remint overlap,
  `outer_id` drift/recovery, and stable subscription -> agreement identity;
- complete commercial re-verification and `NOT_SELLABLE` fallback;
- fail-closed Widget mint and paid access under identity/commercial conflict;
- unified customer/agreement/subscription uncertain-create recovery, 2h
  escalation, and no unsafe scope release;
- canonical LBX `subscription_id` binding with non-unique `outer_id` only as a
  recovery hint;
- `ended -> non-terminal` same-ID revival fails closed as conflict;
- first-primary persists target-product observations before acquiring the product
  decision lock and includes every observed candidate;
- fresh manifest + fresh catalog mapping publication and immutable historical pin;
- unified urgent scheduling and provider trust expiry;
- deterministic local due-boundary omission without provider HTTP preserves
  independent products and increments revision;
- fixed quantity/cycle identity, immutable allowance tuple, metric-local duplicate
  conflict, and multi-metric bucket isolation;
- implicit revision `0`, immutable semantic revisions, and independent fact
  omission;
- AccessInvalidation outbox/retry plus revision-floor and in-flight `204` races;
- same-cycle allowance omission/reappearance preserves durable Kernel usage;
- paid metered action requires its exact metric allowance; no allowance stacking;
- clock-skew-safe effective bounds and `refresh_after <= expires_at`;
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
- support bundles, overlapping access-producing subscriptions, allowance stacking,
  duplicate metric sources, shared metrics, or paid overage;
- support postpaid/debt access or dynamic/prorated/charge-derived quota;
- support Portal-initiated upgrade/downgrade/refund/dispute/commercial trial;
- issue Portal-owned unpaid/free/trial grants in this billing rewrite;
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
  deterministic local time-boundary access reductions
  product-scope primary selection
  paid entitlements + metric-specific allowances
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