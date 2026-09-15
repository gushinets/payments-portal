# External billing boundary and Payments Portal redesign

Status: review requested after eighth external-review amendments  
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
3. an explicit audited operator resolution/rebind that selects already-proven
   facts and returns through normal derivation.

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
adopting K2 locally or silently creating a second key.

#### Server-generated bounded Widget credential

Widget JWT is minted only by Portal backend after authenticated Portal-user ->
verified LBX-customer resolution. Browser input never authoritatively chooses
`ident`, `ident_type`, customer, agreement, or permissions.

Phase 0 must prove a provider-enforced bounded lifetime using supported `exp`, an
`iat` maximum age, a revocable short-lived session, or equivalent. An ignored
claim or effectively unbounded replayable token blocks launch.

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
Widget JWT and starts no new customer/agreement/subscription creation for that
slot.

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
and, if still allowed, mints a new token.

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

Portal imports the manifest into a local read-only projection atomically. A
manifest sync updates `capability_manifest_last_complete_sync_at` only after a
complete `200`, supported schema, full reference validation, and successful
local projection commit. Timeout, `5xx`, partial/malformed payload, unsupported
schema, broken references, or local transaction failure retain the previous LKG
projection and do not advance freshness.

Use one freshness constant for all projections required to begin a new sale:

```text
new_sales_projection_max_age = 24h
refresh target ~= every 5m + startup
```

A new `PurchaseIntent` is allowed only when both:

```text
capability_manifest_last_complete_sync_at age <= 24h
billing_catalog_last_complete_sync_at age <= 24h
```

Only a complete successful catalog sync likewise refreshes the catalog timestamp.
Failed/partial sync does not.

Staleness blocks new sales. Manifest staleness also blocks publishing a new
mapping revision. Staleness does not revoke existing pinned mappings,
subscriptions, grants, or allowances.

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
Each revision records the Platform manifest version used for validation. Later
changes create a new revision; already-pinned subscriptions are not silently
rewritten.

### Purchase-time snapshot

When `PurchaseIntent` is created, the same local transaction pins:

- external component references;
- exact mapping revision IDs;
- resolved `product_id` and `metric_key` bindings;
- fixed accepted quantity for each metric;
- exact material commercial fingerprint and legal-document versions.

A later mapping revision does not change an existing purchase/subscription
meaning.

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
or wait on the same slot. Timeout/lost response becomes `unknown` and blocks
another create until recovery/manual resolution.

For RU, `billing_customer_key` is the Portal-owned expected value of LBX
`users.outer_id`. Portal never PATCHes that field during normal operation. An
authoritative reread with a different `outer_id` creates `identity_conflict`;
Portal never mutates its key to follow the provider drift. Once a key has ever
been allocated to a Portal customer slot it remains permanently reserved locally
and is never reused for another user/customer even if LBX no longer resolves the
old value.

`identity_conflict` blocks Widget mint, new sales, new customer/agreement/
subscription mutation, and identity-based recovery until audited resolution.
Existing linked paid access may continue only when stable provider customer and
subscription IDs independently and authoritatively prove the original ownership
and ordinary access predicates still hold; otherwise affected access fails closed
through the normal revisioned access transition.

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

### Purchase scope and uncertain subscription creation

`Idempotency-Key` handles retransmission of one public request. Business
uniqueness is `(user_id, product_id)`.

At most one scope-holding purchase flow exists for one user/product. Once a
non-terminal subscription is linked, it owns that scope; a prepared unpaid
subscription therefore blocks a second purchase.

Automatic scope release is allowed only when:

- failure happened before any external mutation was possible;
- a linked subscription is authoritatively terminal and no unresolved competing
  flow exists;
- a provider-specific absence predicate has separately been proven safe.

For LBX subscription creation, timeout, lost response, HTTP 500, zero recovery
matches, or Widget abandonment do **not** prove absence. `subscriptions.outer_id`
is not assumed unique.

`subscription_create_outcome_unknown` therefore:

```text
keeps (user, product) scope held
allows read-only recovery/discovery only
never blind-retries subscription create
never auto-releases on zero matches
```

The operation stores:

```text
unknown_since
unknown_recovery_deadline_at = unknown_since + 2h   # MVP default, configurable
```

When UNKNOWN is first created, Portal durably schedules an escalation work item
for that deadline. Before the deadline, safe read-only recovery runs with urgent
cadence. A unique proven match binds immediately; ambiguity enters manual review
immediately.

At the deadline, if still UNKNOWN:

```text
operation -> manual_review
reason = subscription_create_outcome_unknown
scope remains held
```

Read-only discovery may continue after escalation, for example every 30 minutes
plus webhook-triggered acceleration. Support/Billing Ops may release scope only
through audited provider/human evidence that release is safe, or bind a recovered
object. A late object discovered after manual release never receives automatic
access and enters conflict review if a later purchase already succeeded.

## Subscription projection and paid eligibility

A local subscription row exists only for a proven external subscription.
Uniqueness includes:

```text
UNIQUE(external_billing_account_id, external_subscription_id)
```

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

Published allowance boundaries are immutable for that cycle in MVP. A later read
claiming different boundaries for the same cycle creates
`allowance_cycle_conflict` rather than silently rewriting the bucket.

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

Only after the complete provider observation is assembled does Portal open a
short DB transaction and lock the product scope. Under that lock it:

```text
1. persists/upserts ALL point-read results from this provider observation
2. rereads the union of:
   - candidates from this observation, and
   - already-known local non-terminal candidates for (user, product)
3. evaluates first-primary
```

A candidate seen by the current provider list can therefore never disappear from
the decision merely because its projection had not yet been written before the
lock.

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

All intervals are UTC half-open `[start, end)`.

If an allowance expires before the next provider cycle is authoritatively
confirmed, the product grant may remain but no future metric bucket is invented;
metered paid usage fails closed at the old `period_end`. A later confirmed cycle
creates new metric-specific IDs using the pinned fixed quantities.

## AccessSnapshot and Platform Kernel boundary

`AccessSnapshot` is vendor-neutral and is the complete current effective set for
one `(tenant_id, region, user_id)`. It contains product grants and metric
allowances but no provider IDs/statuses, balances, payments, charges, or provider
cycle keys.

One `access_revision` identifies one immutable semantic effective access state.
For the same revision, authorization-relevant contents of `grants[]` and
`allowances[]` may not change. Any grant/allowance add, omission, or material
change is first committed as a new effective state with `access_revision N+1` and
durable invalidation. GET materialization serializes the committed state; it does
not change rights on the fly while retaining revision N.

`authoritative_as_of`, `refresh_after`, and `expires_at` may be recalculated at
the same revision if the semantic access state is unchanged.

Portal evaluates facts independently when committing a new effective state. If
Product A source loses trust while independent Product B remains trusted:

```text
revision N:   A + B
revision N+1: B only
```

A's omission is a material negative access change and increments
`access_revision`; B remains valid. An expired metric allowance may be omitted
while its open-ended product grant remains present, but that omission likewise
requires the new revision before a GET can return it.

MVP defaults:

```text
refresh_after = now + 1m
expires_at = min(
  now + 5m,
  deadlines of paid facts actually included,
  included grant terminal boundaries,
  included allowance boundaries where relevant
)
```

After a fact is omitted, its old deadline no longer shortens the new snapshot.

Known Portal users always receive `200` with a complete snapshot, including
`grants=[]` and `allowances=[]` after a committed empty-access revision. `404`
means only an unknown canonical user in the requested tenant/region; `401`/`403`
mean service-auth/scope failures; `5xx` means Portal could not produce a complete
valid snapshot. Kernel may use a prior snapshot after transport/`5xx` only until
its existing `expires_at`, never extending it locally, then paid access fails
closed. An unexpected `404` for a previously known scoped user is an integration
anomaly, not a normal empty-entitlement transition.

### Monotonic access revision and durable invalidation

Every material positive or negative access change increments per-user
`access_revision` and atomically upserts durable invalidation work.

Payments Portal calls the region-local endpoint hosted by Platform Kernel:

```text
POST /internal/v1/access-invalidations
```

with:

```text
(tenant_id, region, user_id, access_revision)
```

Platform Kernel, conversely, calls the region-local AccessSnapshot endpoint hosted
by Payments Portal. The exact host/caller matrix and HTTP contract are defined in
the companion design.

Invalidation delivery is at-least-once, idempotent, durable, and coalesced to the
maximum pending revision for that user. Transport/429/5xx failures retry durably;
contract/auth/region errors remain unresolved and alert rather than hot-looping.

Kernel atomically raises its monotonic revision floor and evicts older cached
snapshots. Once floor `R` is known, a delayed snapshot `< R` cannot be cached or
used for authorization.

Invalidation push accelerates convergence and fences stale responses; it is not
the sole correctness mechanism. `refresh_after`, `expires_at`, temporal-boundary
refresh, and complete snapshot replacement remain fail-closed backstops.

The detailed cross-repository wire contract is:

`docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md`.

## Platform Kernel paid quota semantics

For each allowance independently:

```text
remaining = max(0, allowance.quantity - durable Kernel usage[allowance_id])
```

Kernel hard-stops at zero; there is no paid overage. Usage consumption is atomic
and restart-safe. Two metrics from one provider cycle have independent counters.

The durable usage ledger lifetime is independent of an allowance's current
presence in `AccessSnapshot`. Omission because of financial block, trust/conflict,
snapshot expiry, or cache eviction stops current authorization but does not
delete/reset `usage[allowance_id]`.

If the same allowance reappears after same-cycle unblock, Kernel resumes the same
counter and remaining amount. Only a new `allowance_id`, produced by a confirmed
new provider cycle, creates a new zero-usage bucket. Historical usage rows remain
at least longer than any possible reappearance; MVP may retain them without
automatic deletion.

External usage reporting is outside this MVP. If a billing offer requires it or
its requirement is unknown, the offer remains `NOT_SELLABLE` until a separate
design is approved.

## Manual review

`manual_review` is operational workflow, never access authority.

Typical reasons include:

- duplicate/conflicting subscription;
- `subscription_create_outcome_unknown`;
- ambiguous external create/recovery;
- unknown external customer or `identity_conflict`;
- unmapped/unclassified component or duplicate metric source;
- normalization/integration uncertainty;
- prepared-commercial mismatch or `commercial_terms_conflict`;
- `allowance_cycle_conflict`.

Controlled resolutions may bind a proven external object, release a scope after
audited evidence of safe absence, restore/prove the original customer identity,
mark duplicate/conflict, perform audited mapping rebind, or accept a proven
subscription as primary under the product scope lock. Operators never directly
set entitlement active.

MVP requires durable records, alerting, runbook, and controlled admin command/API;
a dedicated manual-review UI is not required.

## Worker topology and transactions

MVP runs a durable billing worker embedded in the Payments Portal API process
with one API replica initially. Correctness-critical work lives in PostgreSQL,
not FastAPI `BackgroundTasks` or an in-memory queue.

Queue claims, scheduled UNKNOWN escalation, product-scope decisions,
reconciliation leases, and invalidation delivery must be safe for multiple
consumers even though initial deployment has one replica.

No external network request runs inside an open DB transaction. Transactions are
short and cover local state creation, claims/leases, access decisions, outbox
updates, and atomic projection/access changes.

RabbitMQ/Kafka is not required for MVP.

## Security and PII

Provider credentials, webhook secrets, Widget signing secrets, and payment
credentials live only in runtime secret configuration.

`billing_customer_key` is opaque, immutable, and non-PII. Email, phone, and name
are not cross-system or Widget identity authority. Portal never changes its key
to follow provider-side `outer_id` drift and never reuses an allocated key.

Widget JWT is signed only by Portal backend after verified user/customer mapping;
client flags are not ACLs; launch requires server-side operation scope and bounded
credential lifetime proven by Phase 0 E. Active `identity_conflict`, unresolved
external-create uncertainty, or incomplete/mismatching commercial verification
prevents mint.

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
- oldest `subscription_create_outcome_unknown` and pending 2h escalation;
- manual-review count/age by reason;
- normalization and commercial-verification failures;
- discovery/reconciliation success, latency, trust-deadline proximity;
- urgent vs normal reconciliation backlog;
- work-queue depth/oldest item;
- webhook auth failures/delivery lag;
- commercial/allowance conflicts;
- access fact omissions and revision changes;
- AccessInvalidation delivery lag/errors and Kernel stale-snapshot rejection;
- provider latency/timeouts/error rate.

Audit must explain why access changed and identify the authoritative read,
pinned mapping/commercial snapshot, provider cycle/source, primary decision, or
manual resolution without creating a shadow financial ledger.

## Clean pre-production reset and implementation ordering

Destructive rewrite begins only after all Phase 0 launch-critical gates pass.

Order:

0. Run Phase 0 A-E and record PASS evidence. Reuse existing stand-043 REST facts;
   prove missing semantics, especially authenticated Widget behavior and
   `users.outer_id` drift/recovery semantics.
1. Supersede contradictory canonical ADR/docs in Portal and Kernel.
2. Remove obsolete Portal Product/Bundle/Plan/PlanLimit/Order and direct-payment
   semantics; replace the disposable Alembic baseline and recreate dev/test DBs.
3. Implement the Kernel-hosted capability/metric manifest contract and Portal
   atomic LKG manifest/catalog freshness projections.
4. Implement controlled mapping publication plus purchase-time
   mapping/fingerprint/fixed-quantity snapshot.
5. Implement durable external-customer slot using one `billing_customer_key`,
   immutable identity/drift detection, non-payment customer/agreement/subscription
   preparation, and safe recovery.
6. Implement PurchaseIntent scope, complete prepared-state commercial verification,
   fail-closed Widget mint-on-open, UNKNOWN 2h escalation, and manual-review
   controls.
7. Implement the actual LBX customer-list/point-read behavior proven in Phase 0 D,
   persist-all-observed-candidates first-primary selection under product lock,
   fenced reconciliation, unified urgent scheduling, prepaid normalization, and
   6h provider trust lease.
8. Implement metric-specific allowance identity/cycles from Phase 0 evidence with
   quantity pinned from accepted fixed terms and no provisional rollover.
9. Implement committed immutable-revision AccessSnapshot plus durable invalidation
   and Kernel revision-floor consumer according to the companion contract.
10. Integrate allowances into Kernel durable quota consumption with usage ledger
    lifetime independent from snapshot/cache presence.
11. Run cross-repo contract/integration proofs, including manifest fixtures and
    exact HTTP semantics.
12. Repeat critical LBX probes against deployed RU configuration before launch.

No dual-write old/new billing compatibility layer is required.

## Implementation-plan proof areas

The later implementation plan must contain concrete automated/provider proofs for
these areas rather than duplicating a large test matrix here:

- Phase 0 A-E launch evidence, including `outer_id` drift/recovery;
- complete commercial re-verification and `NOT_SELLABLE` fallback;
- fail-closed Widget mint under mismatch/INCOMPLETE/conflict/UNKNOWN;
- uncertain-create recovery, 2h escalation, and no unsafe scope release;
- first-primary includes every observed candidate before decision under lock;
- unified urgent scheduling and provider trust expiry;
- fixed quantity/cycle identity and multi-metric bucket isolation;
- same `access_revision` always means the same semantic effective access set;
- independent AccessSnapshot fact omission and exact 200/404/401/403/5xx behavior;
- AccessInvalidation outbox/retry plus Kernel revision-floor races;
- same-cycle allowance omission/reappearance preserves durable Kernel usage;
- concurrent durable Kernel quota consumption;
- capability-manifest LKG/freshness and hash-checked cross-repo contract fixtures;
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
- support bundles, overlapping access-producing subscriptions, allowance stacking,
  duplicate metric sources, shared metrics, or paid overage;
- support postpaid/debt access or dynamic/prorated/charge-derived quota;
- support Portal-initiated upgrade/downgrade/refund/dispute/commercial trial;
- support in-place re-consent/material mutation of live customer-funded
  subscriptions;
- create provisional renewal allowances;
- auto-bind unknown customers using PII;
- auto-release uncertain LBX create scope because recovery found zero rows;
- implement external usage delivery in the baseline MVP;
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
  one immutable opaque external-customer key + drift detection
  catalog/subscription projections + freshness gates
  immutable mappings + accepted commercial/quantity snapshot
  durable recovery and manual review
  LBX discovery/reconciliation proven by Phase 0
  product-scope primary selection
  entitlements + metric-specific allowances
  complete AccessSnapshot + durable AccessInvalidation

Platform Kernel
  technical product/metric vocabulary + Capability Manifest
  monotonic AccessSnapshot revision floor
  durable actual usage by allowance_id independent of snapshot presence
  runtime quota enforcement and execution
```

Platform Kernel never calls External Billing directly.  
Payments Portal never calls payment-specific provider APIs.  
RU billing interaction is LBX Widget, subject first to Phase 0 feasibility and
again to the final deployed-configuration gate.
