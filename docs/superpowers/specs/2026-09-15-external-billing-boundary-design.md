# External billing boundary and Payments Portal redesign

Status: review requested after external-review amendments
Date: 2026-09-15

## Goal

Redesign Payments Portal around a strict bounded-context split:

- the external billing system owns the commercial billing domain;
- Payments Portal owns AnyToolAI user identity plus the anti-corruption,
  projection, reconciliation, recovery, and entitlement boundary;
- Platform Kernel owns technical product identity, usage metrics, actual usage,
  quota enforcement, and runtime execution;
- Platform Kernel never communicates directly with LBX, Dodo, or any future
  billing provider.

The repository has not been deployed to production. The current direct-payment
and Portal-owned commerce schema is disposable. This design therefore uses a
clean pre-production reset rather than a backward-compatible migration path.

This revision incorporates the external architecture review and the decisions
accepted after that review. It intentionally narrows MVP commercial scope to
buying one existing Platform product at a time.

## Canonical documentation precedence and required supersession

This design changes accepted semantics that are still present in existing
Payments Portal ADRs and architecture documents. Those older semantics must not
be treated as simultaneously authoritative.

In particular, this design supersedes the following concepts where they appear
in ADR 0002, ADR 0004, or related canonical documentation:

- Portal-owned `Product`, `Plan`, `PlanLimit`, and commercial `Order` as the
  purchase authority;
- `Plan.id` as the exact commercial purchase identity;
- recurring/commercial consent bound to `Plan.id`;
- a mandatory Portal commercial Order for Portal-initiated purchase;
- direct-payment-provider orchestration by Payments Portal.

The replacement semantics are:

- Platform Kernel owns technical `product_id` and `metric_key` vocabulary;
- External Billing owns commercial offers, prices, periods, subscriptions,
  payments, refunds, payment methods, autopay, and billing lifecycle;
- Payments Portal projects a provider offer as `billing_offer` and identifies
  the exact commercial version by `offer_id + commercial_fingerprint`;
- `PurchaseIntent` is orchestration state only, not a commercial Order;
- AnyToolAI commercial/legal acceptance is bound to the current offer
  fingerprint and exact required legal-document versions;
- payment initiation and payment UX are provider-owned.

Before implementation is considered complete, the canonical set must be made
consistent in one documentation change: ADR 0002, ADR 0004, billing authority,
data model, reliability, Platform Kernel contract, legal-flow documentation,
and any README/implementation guidance that still describes the superseded
model. A new ADR may record this design as the superseding decision. Until that
canonical update lands, this document is the intended target design for the
external-billing rewrite and the conflicting older passages are migration
inputs, not concurrent requirements.

The clean Alembic reset is also an explicit pre-production exception to any
older "baseline frozen / forward-only" migration convention. There is no
production data compatibility requirement for this rewrite.

## Architectural invariants

### Ownership

External Billing owns commercial billing truth. For RU this is LBX. EU/US may
use Dodo or another provider behind the same Portal boundary. External Billing
owns, as applicable:

- commercial services/products and tariff/package composition;
- prices, currency, billing periods, discounts, and sellability;
- commercial allowances and billing rules;
- commercial subscription lifecycle;
- agreements or equivalent provider-native commercial contracts;
- balances, charges, billing calculations, and financial blocking;
- payment initiation, payment UX, acquiring, payment methods, autopay;
- refunds, disputes/chargebacks as represented by the provider;
- invoices and billing documents;
- billing customer profile and billing notifications.

Payments Portal owns:

- canonical AnyToolAI user identity, registration, authentication/session, and
  AnyToolAI legal acceptance;
- verified mapping between AnyToolAI users and external billing customers;
- read-only local projections of external catalog and subscription state;
- explicit, versioned mapping between external billing components and Platform
  technical capabilities;
- `PurchaseIntent` and provider-owned customer-interaction orchestration state;
- durable command recovery, discovery, reconciliation, work queues, webhook
  ingestion, and manual-review workflow;
- normalized entitlements and purchased-allowance projections;
- the vendor-neutral `AccessSnapshot` consumed by Platform Kernel;
- delivery state for usage forwarding when a provider requires it.

Platform Kernel owns:

- technical `product_id` vocabulary and product registry;
- technical usage metric vocabulary (`metric_key`) and ownership of each metric
  by exactly one `product_id`;
- actual runtime usage;
- runtime quota state, policy, and enforcement;
- scenario/workflow/action execution;
- a durable usage outbox for paid usage events.

Payments Portal never becomes the source of truth for actual runtime usage or
remaining runtime quota.

### One-way billing dependency

Platform Kernel must never receive LBX/Dodo credentials or provider-specific
identifiers and must never call a billing provider directly.

```text
External Billing
      |
      | provider-specific catalog/subscription/customer APIs
      | provider-owned payment UI + webhooks
      v
Payments Portal
      |
      | AccessSnapshot / invalidation / UsageEvent
      v
Platform Kernel
```

When provider metering is required, the usage path is:

```text
Platform Kernel -> durable UsageEvent -> Payments Portal -> provider adapter
```

### Strict payment boundary

Payments Portal does not call payment-specific REST APIs. It does not create a
payment, calculate or submit a payment amount as payment authority, choose an
acquirer, save a payment method, enable autopay, retry a payment, issue a
refund, or use payment status as an access-granting fact.

Payments Portal may call non-payment External Billing APIs needed to establish
or reconcile commercial structure: customer provisioning/recovery, catalog
reads, provider-specific agreement/subscription provisioning, subscription
state reads/discovery, and safe usage reporting when a tariff requires it.

For RU, the selected customer-facing payment mechanism is **LBX Widget**. The
Portal embeds provider-owned payment UI scoped to the prepared billing context.
There is no fallback to Portal-orchestrated LBX payment REST calls. If LBX
cannot satisfy the required Widget isolation, that is a provider capability gap
and blocks RU production enablement rather than weakening this boundary.

### Projection, not duplicated authority

A local catalog row, subscription projection, entitlement, allowance, webhook,
browser callback, successful outbound POST, payment fact, agreement creation,
or `PurchaseIntent` state never becomes commercial authority by itself.

Only a complete, successfully normalized authoritative subscription read may
change access-producing subscription facts. Webhooks and browser interaction
only accelerate such reads.

## MVP commercial scope

MVP intentionally supports only independent purchase of one existing Platform
product at a time.

```text
Product A -> Offer A -> Subscription A
Product B -> Offer B -> Subscription B
```

A user may own different products independently, but for one `(user_id,
product_id)` there may be at most one access-producing billable subscription.
MVP does not support commercial bundles, all-access packages, overlapping paid
subscriptions for the same product, allowance stacking, shared metrics across
products, paid overage, or upgrade/downgrade flows.

Every sellable offer resolves to exactly one unique Platform `product_id` and
may include zero or more usage allowances whose `metric_key` values all belong
to that same product. A `metric_key` belongs to exactly one `product_id` in the
Platform capability registry.

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
                 + provider-owned UI
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
                |                   |
                | product_id        |
                | metric_key        |
                | actual usage      |
                | quota enforcement |
                | runtime execution |
                | usage outbox      |
                +-------------------+
```

## Platform capability manifest

Platform Kernel is the single source of truth for technical product and metric
vocabulary. It publishes a versioned, vendor-neutral, read-only internal
capability manifest derived from the canonical Platform registry rather than a
second billing-specific source file.

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

`manifest_version` changes deterministically on semantic content changes.
Platform validation enforces that each metric belongs to exactly one product.

Payments Portal periodically imports the manifest into a local read-only
projection. The manifest is not fetched synchronously on every purchase or
runtime access request.

MVP operational defaults:

- import on startup plus scheduled refresh approximately every 5 minutes;
- `capability_manifest_max_age = 24h` for **new sales**.

If refresh fails, Portal retains the last-known-good manifest. Once that
manifest is older than the maximum sales age, new purchase creation fails
closed. Existing pinned subscriptions and entitlements are not revoked merely
because capability import is stale.

`enabled=false` for a product or metric blocks new offers/mappings that depend
on it but does not automatically revoke historical paid access. Product sunset
for already-sold subscriptions is a separate controlled migration.

Every mapping revision records the `manifest_version` against which it was
validated.

Capability Manifest and AccessSnapshot are separate contracts:

```text
Capability Manifest = what technical capabilities exist
AccessSnapshot       = what this user may use now
```

## External catalog and mapping model

### Fixed one-product offers

For MVP every sellable external tariff/period is projected as a fixed
`billing_offer`. The customer cannot add/remove services or choose arbitrary
component quantities inside that Portal purchase flow.

The offer may contain multiple external billing components, but after mapping:

- it must resolve to exactly one unique `product_id`;
- every mapped `metric_key` must belong to that product;
- commercial-only components are allowed;
- an unclassified component makes the offer `NOT_SELLABLE`.

There is no Portal-owned Product/Bundle/Plan/PlanLimit commercial model.

### Component classification

Every imported external billing component has an explicit classification:

```text
UNCLASSIFIED
CAPABILITY_BEARING
COMMERCIAL_ONLY
```

Semantics:

- `UNCLASSIFIED`: new offers containing the component are `NOT_SELLABLE`;
- `CAPABILITY_BEARING`: at least one valid technical capability binding is
  required;
- `COMMERCIAL_ONLY`: zero technical bindings are intentional and produce no
  entitlement/allowance.

Missing mapping is never silently interpreted as commercial-only.

### Immutable versioned mappings

A component mapping is versioned and immutable after publication. A component
revision has zero or more bindings, not exactly one.

Conceptually:

```text
billing_component_mapping_revisions
  id
  billing_component_id
  revision
  classification
  status            # active / retired
  validated_manifest_version
  created_at
  created_by/source

billing_component_mapping_bindings
  mapping_revision_id
  capability_type   # product / usage_metric
  technical_key
```

A single external component may therefore imply both product access and one or
more product-owned usage metrics.

A new revision may become active for future resolution; an old revision is
retained for history. Editing an already-used revision in place is forbidden.

### Subscription-component pinning

When Portal first resolves an actual external subscription component, it pins
that component instance to the then-active mapping revision. Future catalog
mapping changes do not silently change existing access.

```text
External subscription component
        -> pinned mapping revision
        -> technical capabilities
        -> entitlements / allowance buckets
```

If the authoritative external subscription later removes the component, the
corresponding derived grant/allowance is removed. If a previously unknown
component later receives its first valid mapping, an unresolved subscription
component may be resolved once from `NULL` to that mapping revision.

Changing an already-pinned revision requires an explicit audited rebind
operation. Catalog sync and ordinary reconciliation never perform such a
rebind automatically.

If a live subscription contains both known and unknown components, known pinned
components may continue to produce their known access while the unknown
component produces no invented capability and opens mapping review.

## Target Payments Portal data model

Exact SQL names/types may follow repository conventions, but these semantic
entities and constraints are required.

### Identity and legal

Retain Portal-owned:

- `users`;
- authentication/session state;
- versioned legal documents and acceptances.

`users.id` is canonical AnyToolAI identity. Email is an attribute, not a
cross-system identity key.

### External billing configuration and customer correlation

`external_billing_accounts` identifies provider/system, contour/region,
environment/account key, and enabled state. It contains no credentials or
secrets.

`external_billing_customers` maps one Portal user to one provider customer for a
billing account and includes a **mandatory stable opaque recovery key** generated
by Portal. The recovery key is independent of email and must support provider
recovery after uncertain customer creation. The database enforces at most one
active mapping per `(external_billing_account_id, user_id)`.

External customer provisioning is **lazy**, not registration-time eager. Normal
Portal registration creates no LBX customer. Customer creation starts only
after the user begins a commercial action and passes the required legal barrier.
Only the minimum provider-required PII is transmitted.

Changing Portal email updates the existing external customer where required; it
must not create a second external customer merely because contact data changed.

### Catalog projections

The Portal stores read-only projections such as:

- capability-manifest import metadata;
- `technical_products` and `technical_usage_metrics`;
- `billing_catalog_components`;
- immutable component mapping revisions and bindings;
- `billing_offers` with commercial display facts, provider references,
  `product_id`, `commercial_fingerprint`, source version, sellability, and sync
  timestamps;
- `billing_offer_components` with fixed provider component composition and
  commercial quantities/allowance facts.

### Purchase intent

There is no Portal-owned commercial `Order`.

`purchase_intents` records that a user started buying one current offer version.
It includes at least:

- `user_id`, `billing_account_id`, `product_id`, `billing_offer_id`;
- immutable `commercial_fingerprint` and relevant displayed commercial snapshot;
- client idempotency identity;
- orchestration status and timestamps;
- optional linked external subscription once proven.

`PurchaseIntent` is not an invoice, payment, subscription, or access authority.

Conceptual states include:

```text
created -> preparing -> interaction_ready -> awaiting_external_result -> linked
```

plus `expired` and `failed`. `linked` only means an external subscription was
unambiguously linked; it does not mean entitlement is active.

An expired intent may still be a reconciliation subject when an external result
can arrive late. Expiry of the UX flow never authorizes Portal to ignore a
later real external subscription/payment outcome.

### Subscription projection

`billing_subscriptions` exists only after a real external subscription is
confirmed. Pre-subscription uncertainty belongs to `PurchaseIntent` and
`billing_operations`.

Normalized business states are deliberately small:

```text
lifecycle_status: active | inactive | ended
financial_access_status: allowed | blocked
```

Unknown provider semantics are **not** persisted as a normal business status.
Normalization health is tracked separately. On an access-relevant normalization
error, the last successfully normalized business projection is preserved until
its finite trust boundary; a subject with no prior good state grants no access.

`billing_subscription_components` projects the actual component composition of
that specific subscription and stores its pinned mapping revision.

External subscription uniqueness includes at least:

```text
(external_billing_account_id, external_subscription_id) UNIQUE
```

The application/DB also prevents more than one access-producing billable
subscription for the same `(user_id, product_id)`. A second externally-created
active subscription for the same product is a conflict, not something to stack.

### Entitlements and purchased allowances

`entitlements` materializes normalized product grants. It contains Portal and
Platform identifiers only, never provider tariff/agreement/subscription IDs in
the Kernel-facing representation.

`purchased_allowances` materializes paid metric limits. Every active allowance
has a stable opaque `allowance_id` and is linked internally to one normalized
subscription and the exact pinned subscription component/source needed for
historical routing.

For MVP a user has at most one active paid allowance bucket for a given
`metric_key`. Paid allowance stacking is not supported.

Portal does not persist authoritative runtime `remaining` usage. Platform Kernel
owns actual usage and remaining-quota calculation.

### Reliability and operational state

`billing_operations` is the durable journal for Portal-initiated external
non-payment mutations. States include:

```text
pending | in_progress | succeeded | unknown | ambiguous | failed
```

An operation row exists before a non-idempotent external side effect. Network
calls never execute inside its database transaction. Timeout/lost response is
`unknown` and triggers provider-specific recovery before any retry.

`billing_webhook_inbox` stores every authenticated webhook delivery with a
Portal-generated `delivery_id`, safe correlation hints, event type, non-unique
`payload_hash`, processing state, and timestamps.

`billing_work_items` is the durable PostgreSQL work queue for catalog/capability
sync, webhook-triggered work, operation recovery, customer discovery,
subscription reconciliation, access invalidation, and related jobs.

`manual_review_cases` records operational cases separately from billing/access
state. It contains subject, reason code, owner category, status, timestamps, and
explicit resolution/audit information.

Usage ingestion/delivery state is stored as integration state, not a second
runtime usage ledger.

Provider-specific typed support tables are allowed. For LBX, agreement
bindings/recovery data may live in typed LBX tables. Provider-specific concepts
must not force themselves into generic domain contracts.

## Legal barrier and customer creation

Before a `PurchaseIntent` is created, Portal must verify that the user has
accepted every currently-required AnyToolAI legal document for the exact
commercial version being purchased.

Commercial/legal acceptance is bound to:

```text
user_id
region
billing_offer_id
commercial_fingerprint
required legal document versions
acceptance kind
authorized timestamp/audit metadata
```

The commercial fingerprint covers material terms used to decide what the user
is buying, including price/currency, billing period/recurrence, target product,
component/allowance composition, and material renewal/cancellation terms that
Portal presents or relies on. Cosmetic description/copy changes alone must not
change the fingerprint.

If the commercial fingerprint changes after display/acceptance, the purchase
returns `offer_changed`; the user must review the new commercial version and
complete any newly-required acceptance before a new PurchaseIntent is created.

Portal owns AnyToolAI legal acceptance. LBX/its payment infrastructure owns
payment-method, acquiring, and provider-specific autopay consent inside the
provider-owned payment UX. Portal must not infer "permission to charge" from
its own legal checkbox.

After the legal barrier, the purchase flow may lazily ensure the external
billing customer using the mandatory stable recovery key.

Erasure/retention, merchant-of-record, fiscal/54-FZ responsibility, and exact
legal retention periods require explicit Legal/Finance policy. The technical
design must support delete/anonymize/disconnect/retain decisions without
pretending Portal identity deletion automatically erases provider records that
may have independent retention obligations.

## Purchase and LBX Widget lifecycle

### Offer validation

The browser submits only Portal-owned opaque identifiers:

```text
offer_id
commercial_fingerprint / offer_version shown to the user
client idempotency key
```

It never supplies authoritative price, provider tariff/service IDs, payment
amount, or billing period.

Before purchase, Portal verifies capability-manifest freshness, catalog
freshness, offer sellability, current commercial fingerprint, legal acceptance,
and business uniqueness for `(user_id, product_id)`.

If commercial terms are stale, Portal performs the required targeted provider
refresh. Changed terms return `offer_changed`. If current terms cannot be
confirmed when required, a new purchase fails closed.

### Business uniqueness beyond HTTP idempotency

`Idempotency-Key` protects retransmission of the same public request. It is not
the business uniqueness mechanism.

Before creating a new intent Portal serializes the purchase scope
`(user_id, product_id)` in a short local transaction and checks:

- whether an access-producing billable subscription already exists;
- whether a non-terminal/unresolved PurchaseIntent already owns that scope.

Results are conceptually:

```text
active subscription -> already_owned
unresolved purchase  -> purchase_in_progress
none                 -> create PurchaseIntent
```

The database provides the final race protection with appropriate uniqueness or
partial uniqueness constraints for the one active subscription and one
non-terminal/unresolved purchase scope.

A purchase whose external operation is `unknown` or `ambiguous` continues to
hold the purchase scope until recovery proves the outcome or an explicit manual
resolution occurs. A second browser tab with a different idempotency key cannot
start a duplicate external purchase.

### Provider-neutral commercial preparation

The application flow is:

```text
validate offer + legal + business scope
 -> create PurchaseIntent
 -> ensure external customer
 -> provider-specific non-payment commercial preparation
 -> CustomerInteraction
 -> external result/discovery
 -> authoritative subscription reconciliation
 -> PurchaseIntent linked
```

The application layer exposes capability-oriented ports and does not require an
Agreement concept. The LBX adapter may internally create/recover a dedicated
agreement and subscription.

For LBX MVP the cardinality rule is:

```text
1 Portal User = 1 LBX Customer
1 externally billed AnyToolAI product subscription = 1 dedicated LBX Agreement
renewal of that same subscription reuses the same Agreement
new subscription = new dedicated Agreement
```

This is an LBX adapter isolation rule, not a provider-neutral domain concept.

### CustomerInteraction

The provider-neutral interaction types are:

```text
embedded_external
redirect_external
none
```

There is no `portal_managed` payment interaction.

For RU:

```text
provider  = lbx
mechanism = widget
interaction = embedded_external
```

The Widget is provider-owned payment UI. Portal may embed/launch it but does not
submit a payment command or treat its JS/browser success callback as access
authority.

### LBX Widget production gate

RU production launch is blocked until vendor/runtime validation proves all of
the following:

- authenticated Widget rendering with the actual supported script/signing
  configuration;
- unambiguous scoping to the intended LBX customer and, critically, the exact
  dedicated Agreement/subscription context;
- with two Agreements for one customer, Widget A cannot pay or mutate Agreement
  B;
- the user cannot use the Widget to create a different subscription, change
  tariff/services, or otherwise bypass Portal's fixed-offer purchase scope;
- payment amount/payment method/acquiring are determined inside provider-owned
  billing/payment infrastructure, not by Portal payment REST calls;
- initial payment works through the Widget/provider UX;
- required recurring/autopay setup is provider-owned;
- browser callback is only a reconciliation hint;
- after provider-side payment, Portal can derive access from ordinary
  authoritative subscription state without querying payment-specific APIs.

Failure of this validation is a provider capability gap. The fallback is not
`/eps_payments` or another Portal payment API orchestration path.

## Reconciliation and discovery

### Webhook is only an accelerator

Webhook handling is deliberately short:

```text
authenticate
 -> minimal validate / extract safe correlation hints
 -> generate Portal delivery_id
 -> persist inbox delivery
 -> enqueue/coalesce reconciliation work
 -> commit
 -> return 2xx
```

No provider REST read occurs in the webhook request.

Each valid HTTP delivery is persisted separately. `payload_hash` is diagnostic
and is not a uniqueness/deduplication key. Duplicate or out-of-order deliveries
are safe because payload contents never directly mutate entitlement.

Coalescing happens at the reconciliation-work level by subject, not by deleting
webhook deliveries. Provider event ordering is not treated as an authoritative
sequence.

Authentication failure creates no trusted billing inbox delivery and triggers
security telemetry instead.

Scheduled reconciliation and discovery remain correctness backstops even if
webhooks are missed or the provider does not retry them.

### Known-subscription reconciliation

Known subscriptions reconcile by exact external reference and a full
authoritative read. Only a complete, internally consistent provider snapshot may
atomically update normalized subscription state, components, entitlements,
allowances, audit state, and reconciliation timestamps.

A partial/inconsistent read preserves the previous good projection and retries
later.

### Customer-scoped inbound discovery

`PurchaseIntent` is not a prerequisite for `billing_subscription`.

Every mapped external billing customer periodically undergoes subscription
discovery independent of checkout:

```text
known Portal user
  -> verified external_billing_customer mapping
  -> list/discover provider subscriptions for that customer
  -> find unknown subscription reference
  -> perform full authoritative subscription read
  -> resolve/pin components
  -> create normalized subscription/access projection
```

This supports Sales/Finance-created, comp/gift, repaired, or otherwise externally
created subscriptions.

Automatic identity binding is allowed only through the already-verified Portal
User <-> external customer mapping. Portal must never auto-bind an unknown
external customer to a user by email, phone, or name.

An account-wide scan may be added as an audit/orphan detector, but unknown
external customers discovered that way produce no entitlement and require
manual review.

Operational rule for Sales/Finance: when manually granting a product to an
existing user, create it under the already-mapped external customer and obey the
LBX dedicated-Agreement isolation rule. Do not create a second customer for the
same Portal user.

A current catalog offer is not required for an already-existing discovered
subscription. Runtime access derives from actual subscription composition,
pinned mappings, and normalized authoritative state, even if the corresponding
commercial offer is retired or no longer sellable.

### Per-subject serialization by fenced lease

Only one reconciliation for an external subscription may be allowed to apply at
a time. MVP uses a process-independent PostgreSQL **fenced lease**, not a
long-lived database transaction across the provider HTTP call.

Conceptually:

1. in a short transaction, atomically claim the subject with `lease_owner`,
   `lease_until`, and a monotonically increasing `lease_generation`/fencing
   token;
2. commit;
3. perform the provider HTTP read with no open database transaction;
4. in a new short transaction, apply the snapshot only if the same lease owner
   and fencing generation are still current;
5. release/expire the lease.

If a lease expires and another worker acquires a higher generation, the stale
worker cannot commit its older read. Long-running calls may renew the lease in a
short transaction before expiry. This removes the connection/transaction
ambiguity of holding a session advisory lock across network I/O.

## Normalization uncertainty

Unknown access-relevant provider semantics are an integration failure, not a
normal business state.

If the adapter receives an unrecognized access-relevant subscription state,
blocking meaning, effective-date semantic, or component semantic:

```text
provider response received
 -> normalization_error
 -> do not overwrite last-known-good business projection
 -> alert + retry / manual review as appropriate
```

Rules:

- a previously `allowed` subscription may preserve its old access only until the
  already-established finite trust deadline;
- a previously `blocked` subscription remains blocked;
- a subject with no prior valid state grants no access;
- uncertainty never creates/increases access;
- semantic unknown does not qualify for provisional renewal rollover;
- unknown irrelevant optional provider fields are tolerated and ignored.

## Freshness, renewal, and failure policy

Business state and operational freshness are separate.

Conceptually:

```text
fresh -> stale_usable -> expired
```

A temporary provider/Portal outage may preserve an already-confirmed grant
inside a finite last-known-good trust lease. New purchases and new grants fail
closed when required current facts cannot be confirmed.

An authoritative negative state such as `blocked` or `ended` revokes access
immediately in the Portal; there is no outage grace after a known negative
fact.

### Subscription lifetime versus allowance period

Do not equate recurring subscription lifetime with the end of the current usage
allowance period.

```text
subscription effective end  !=  allowance period_end
```

An open-ended/recurring active subscription does not lose product entitlement
merely because its current monthly allowance period ended.

### Pre-boundary reconciliation and provisional rollover

Portal increases reconciliation urgency before an expected allowance-period
boundary. If the next period cannot be authoritatively confirmed **only because
of provider transport/unavailability**, Portal may create a bounded provisional
rollover when the last authoritative state proves all of the following:

- this is an already-confirmed recurring subscription;
- lifecycle/access were active + allowed;
- no known cancellation/terminal end blocks renewal;
- the new allowance terms do not improve on the last confirmed recurring terms.

MVP default:

```text
renewal_grace_window = 6 hours
```

The value is configurable. Provisional rollover may reuse at most the same
confirmed allowance quantity/policy for the next period and exists only until
`renewal_grace_until`.

Provisional rollover is forbidden for:

- a new product grant;
- a new purchase;
- an upgrade or larger allowance;
- a different tariff;
- an already ended/blocked subscription;
- access-relevant semantic unknown returned by the provider.

If provider recovery confirms renewal, the allowance becomes authoritative. If
it confirms blocked/cancelled/not renewed, Portal immediately revokes the
provisional allowance and any dependent access. Usage already legitimately
consumed during the bounded grace is not retroactively undone.

If no authoritative confirmation exists when the 6-hour grace expires, the
provisional allowance expires and the affected paid usage fails closed.

## AccessSnapshot contract

Platform Kernel pulls a vendor-neutral AccessSnapshot from Payments Portal.
Conceptual shape:

```json
{
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
      "valid_until": "..."
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

The Kernel-facing snapshot contains no provider tariff/service/agreement/
subscription/payment IDs, balances, provider statuses, or provider-specific
blocking values.

`allowance_id` is an opaque stable Portal identifier that lets Kernel later
report usage against the exact historical allowance source without learning
provider identity.

MVP normal cache defaults:

```text
refresh_after = now + 1 minute
expires_at    = now + 5 minutes
```

These are configurable operational defaults. `expires_at` must never exceed the
Portal's own projection trust deadline, entitlement validity, or provisional
`renewal_grace_until`.

Kernel behavior:

- before `refresh_after`, use the cached snapshot;
- from `refresh_after` until `expires_at`, attempt refresh but may temporarily use
  the cache if Portal is unavailable;
- at/after `expires_at`, cached paid access fails closed;
- guest/free Kernel-owned functionality is independent of paid billing outage.

## Negative-access invalidation

Pull + bounded expiry remains the correctness contract, but Portal sends a
best-effort durable invalidation when paid access is reduced.

Each user's paid-access projection has a monotonically increasing
`access_revision`. In the same local transaction that applies an access-reducing
change, Portal:

```text
updates normalized projection
increments access_revision
enqueues durable Kernel invalidation
COMMIT
```

A worker later sends only a vendor-neutral invalidation hint such as:

```json
{
  "user_id": "uuid",
  "region": "ru",
  "access_revision": 184
}
```

The push never carries an entitlement delta. Kernel compares revisions; if the
incoming revision is newer than its cached revision, it invalidates the paid
snapshot and uses the normal AccessSnapshot pull path. Delayed older
invalidations are ignored.

Access-reducing changes include blocked/ended subscription, product grant
removal, allowance removal/reduction, forced period termination, and an audited
mapping rebind/manual resolution that removes capability.

Positive changes do not require push for correctness in MVP; normal refresh is
sufficient. Invalidation delivery failure does not roll back the authoritative
Portal change. The 5-minute snapshot expiry remains the hard safety bound when
push is lost.

Invalidation jobs are durable PostgreSQL work, not FastAPI `BackgroundTasks`.
Multiple pending revisions for one user may be coalesced to the newest revision.

## Runtime usage and durable delivery

Platform Kernel is the single authority for actual usage and runtime quota.
When paid usage is consumed, Kernel atomically updates its usage/quota state and
writes a `UsageEvent` to a durable outbox in the **same transaction**.

```text
Kernel transaction
  update actual usage / quota
  insert UsageEvent outbox row
COMMIT
```

A separate Kernel worker delivers events to Portal at least once. Portal ingests
them idempotently by globally unique `usage_event_id` and acknowledges only
after durable persistence.

Conceptual event:

```json
{
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

The Portal validates that the allowance/product/metric relationship matches its
historical projection and uses `allowance_id` to route to the exact historical
subscription/component source even if the subscription later ends.

Portal usage state records delivery/integration facts only, for example:

```text
received
not_required
pending_external
external_delivered
external_unknown
failed/manual_review
```

It does **not** calculate authoritative remaining runtime quota.

If the external provider does not require usage reporting, the event becomes
`not_required`. If reporting is required, the adapter performs safe delivery.
Provider calls with uncertain non-idempotent outcomes are never blindly retried.

If a provider's metering API cannot provide native idempotency or a proven
unambiguous recovery strategy after timeout, an offer requiring such metering is
`NOT_SELLABLE` until safe semantics are established.

Portal outage does not synchronously block each runtime call: Kernel continues
to enforce its locally known allowance and its durable usage outbox accumulates
pending delivery. Paid overage is not supported; when the known allowance is
exhausted, Kernel hard-stops further paid consumption.

## Commercial lifecycle scope

MVP supports only Portal-orchestrated **buy one product**.

Other commercial mutations are intentionally not Portal command flows:

- **Cancellation**: initiated through LBX-owned Widget/cabinet where supported or
  by Support/Finance in LBX. Portal observes the resulting authoritative state.
  A scheduled end continues access until its authoritative effective end.
- **Upgrade/downgrade**: not supported in MVP. A second offer for the same
  product cannot be bought while the current billable subscription owns that
  product. The simple fallback is end/cancel current subscription, then buy a
  new offer after it ends.
- **Refund/dispute/chargeback**: provider/payment concern. Portal does not issue
  the financial operation and does not infer its own access rule from payment
  status; it reacts to the resulting authoritative subscription state.
- **Commercial trial**: no Portal-owned paid trial state. Free/guest usage is a
  Platform Kernel policy. A future "free period then recurring charge" trial
  must be modeled by External Billing and designed separately.
- **Manual/comp paid grant**: created in External Billing under the already
  mapped customer and discovered by customer-scoped discovery.

"Out of scope for command orchestration" does not mean "out of scope for
observation". Reconciliation must understand access-relevant consequences such
as active, blocked, scheduled end, ended, component change, and allowance-period
change.

## Manual review

`manual_review` is an operational workflow, never an access state or direct
entitlement authority.

Each case records:

```text
subject_type / subject_id
reason_code
status
owner_kind
created_at / resolved_at
explicit resolution
audit actor + details
```

Minimum MVP reason/owner policy:

- duplicate/overlapping subscription -> Finance/Billing Ops;
- ambiguous external create/recovery -> Billing Ops;
- unknown external customer -> Support/Billing Ops;
- unmapped/unclassified component -> Product/Engineering owner;
- unknown access-relevant provider semantics -> Engineering/on-call;
- invalid capability mapping -> Product/Engineering.

Before resolution, safety behavior follows the last trusted state, not the mere
existence of the manual-review case. For example, a newly discovered second
subscription cannot add access, while an already-known-good primary subscription
may continue within its normal trust rules.

Resolutions are explicit actions such as `bind_existing_external_object`,
`mark_duplicate_external_object`, `rebind_mapping_revision`,
`accept_subscription_as_primary`, `reject_subscription_as_conflict`, or
`mark_external_customer_unmatched`. An operator never directly sets
`entitlement=active`; resolution returns the subject to ordinary
reconciliation/access derivation.

MVP does not require a dedicated backoffice UI. Durable records, alerts,
a documented runbook, and controlled operational command/API are sufficient.

## Provider abstraction

Application/domain code depends on capability-oriented ports rather than one
giant provider interface or an LBX-shaped domain model. Conceptual capabilities
include:

- external catalog reads;
- external customer ensure/recovery;
- non-payment commercial purchase preparation;
- provider-owned customer interaction description;
- authoritative subscription read and customer-scoped discovery;
- optional usage reporting;
- webhook authentication/parsing.

There is deliberately no generic payment-command capability in Payments Portal.

Provider-specific branching (`LBX` versus future providers) belongs in
integration/composition packages, not in domain/application use cases or
Platform Kernel. LBX Agreement logic, tariff/service APIs, `state`,
`current_blocking`, Widget mechanics, and recovery lookups remain inside the
LBX integration boundary.

## Worker topology and transaction rules

MVP runs the durable billing worker embedded in the Payments Portal API process
with one API replica initially. Correctness-critical work is persisted in
PostgreSQL and never relies on in-memory queues or FastAPI `BackgroundTasks`.

Worker/use-case code is independent of FastAPI composition so it can later move
to a dedicated process without changing domain behavior.

Queue claiming and subject leases are multi-consumer safe even though initial
deployment has one replica. External network requests never execute inside an
open database transaction. Transactions are short and cover intent creation,
queue/lease claims, durable command state, or atomic projection updates.

No RabbitMQ/Kafka is required for MVP.

## Security and PII

External billing credentials, webhook secrets, Widget signing secrets, and
payment credentials exist only in runtime secret configuration for integration
code. They are not stored in billing-account rows, domain objects, logs, or
browser-visible responses.

Kernel-facing capability/access/usage/invalidation APIs are internal
service-to-service contracts over TLS with explicit service authentication and
expected tenant/region scope. User authentication alone must not authorize them.
A contour may never read or write another contour's billing/access data.

Only minimum billing/customer PII required for the external provider is
transmitted/stored. Email, phone, or name are never used as automatic identity
binding authority between systems.

Reverse proxy/access logging must not leak webhook query secrets, Widget signing
material, or authentication data. Raw provider payload retention requires an
explicit operational/debugging purpose plus redaction/retention policy.

## Observability and audit

Use non-PII correlation identifiers such as request ID, user ID,
PurchaseIntent ID, billing operation ID, webhook `delivery_id`, work item ID,
subscription ID, `allowance_id`, access revision, and safe opaque external
references.

At minimum monitor:

- capability-manifest age/import failures;
- catalog projection age/sync failures;
- unclassified components and invalid/not-sellable offers;
- external customer provisioning/recovery failures;
- `unknown`/`ambiguous` operation counts;
- manual-review open count and oldest age by reason;
- normalization-error count, affected subjects, and oldest error age;
- reconciliation/discovery success, failure, duration, and age since last
  authoritative state;
- work-queue and Kernel usage-outbox depth/oldest-item age;
- webhook authentication failures, delivery rate, and processing lag;
- fresh/stale-usable/expired access projection counts;
- provisional-renewal count/age and grace expiry;
- access-invalidation queue lag;
- provider latency, timeout, and error rate.

Normalization errors are high-priority alerts because a vendor semantic change
can affect many paid users as their finite trust leases expire.

Audit must answer why access changed and which authoritative reconciliation,
mapping revision/rebind, or manual resolution caused it without requiring a
shadow copy of the provider financial ledger.

## Clean pre-production reset

There is no production deployment and no compatibility contract to preserve.
Do not implement a staged dual-schema or semantic migration from the old
Portal-owned commerce model.

The implementation should:

1. explicitly supersede/update contradictory ADR/canonical billing docs;
2. remove obsolete Portal-owned Product/Bundle/Plan/PlanLimit/Order semantics;
3. remove old direct-payment-provider architecture, DTOs, checkout/payment
   orchestration, and obsolete provider-shaped payment fields;
4. replace the development Alembic baseline with the clean target schema under
   the documented pre-production reset exception;
5. recreate development/test databases from empty state;
6. implement the new flow in dependency order;
7. use no dual-write compatibility layer and no old/new billing traffic split.

If a developer/staging database contains useful manual data, export it
separately before reset. It does not constrain the target architecture.

## Required correctness tests

The implementation plan must include automated tests and provider-validation
spikes proving at least the following:

- two identical submissions with one idempotency key create one PurchaseIntent;
- two tabs with different idempotency keys cannot create two simultaneous
  purchase flows for the same `(user_id, product_id)`;
- `unknown`/`ambiguous` external create holds purchase scope and is recovered
  before any retry;
- an expired PurchaseIntent can still late-link to a real external subscription;
- a provider create timeout performs lookup/recovery and never blindly duplicates
  a non-idempotent create;
- valid duplicate/out-of-order webhooks converge to the same authoritative
  projection and each delivery retains its own Portal `delivery_id`;
- a missed webhook is repaired by scheduled reconciliation/discovery;
- a Sales/Finance-created subscription under a mapped customer is discovered
  without PurchaseIntent;
- an unknown external customer is never auto-bound by email/phone/name;
- a full authoritative read is required before discovered access is granted;
- an offer with an unclassified component is not sellable;
- one component can bind to both product and metric capabilities;
- mapping revisions are immutable and an existing subscription component remains
  pinned when the catalog mapping changes;
- explicit audited rebind is required to change an already-pinned mapping;
- current mapping removal/retirement does not silently revoke historical access;
- a live subscription with one unknown component never invents access for that
  component and preserves independently known components;
- an offer cannot resolve to more than one product in MVP;
- a metric cannot belong to multiple products;
- overlapping active external subscriptions for the same `(user, product)` are
  treated as conflict/manual review and are not allowance-stacked;
- paid overage is rejected by Kernel at the hard allowance limit;
- a UsageEvent routes via `allowance_id` to the historical subscription/component
  even if delivered after the subscription ended;
- Kernel quota update and usage-outbox insertion are atomic;
- Kernel retries Portal delivery without duplicating Portal ingestion by
  `usage_event_id`;
- a Portal outage does not lose usage events;
- provider metering with unsafe/unrecoverable non-idempotent semantics makes the
  dependent offer not sellable;
- temporary provider outage preserves existing last-known-good access only
  inside the finite Portal trust boundary;
- allowance-period end alone does not terminate an open recurring product grant;
- pre-boundary provider outage may create only same-terms provisional rollover;
- provisional rollover expires no later than 6 hours unless authoritatively
  confirmed;
- authoritative blocked/cancelled/not-renewed state revokes provisional access
  immediately;
- semantic unknown never creates provisional renewal and never overwrites the
  last-known-good normalized state;
- unknown irrelevant provider fields do not fail reconciliation;
- authoritative negative access change increments `access_revision`, persists a
  durable invalidation, and Kernel drops an older cached snapshot on receipt;
- lost invalidation still fails closed no later than AccessSnapshot `expires_at`;
- normal AccessSnapshot cache defaults are 1-minute refresh / 5-minute expiry and
  are always capped by Portal trust/grace validity;
- stale capability manifest blocks new sales after 24 hours but does not revoke
  existing pinned subscriptions;
- `enabled=false` technical capability blocks new sales but does not silently
  terminate historical entitlement;
- legal acceptance for old commercial fingerprint cannot authorize changed
  material terms;
- cosmetic-only offer-copy change does not change commercial fingerprint;
- PurchaseIntent cannot be created without current required legal acceptances;
- external customer provisioning does not occur merely on Portal registration;
- external customer recovery key is stable across email change;
- LBX Widget validation proves two-Agreement isolation, intended-subscription
  scoping, no unauthorized tariff/service mutation, initial payment, and
  provider-owned recurring/autopay behavior before RU production enablement;
- Widget/browser callback never grants entitlement without authoritative
  subscription reconciliation;
- cancellation/refund/dispute outcomes affect access only through resulting
  authoritative subscription state;
- no external network request occurs inside an open database transaction;
- fenced reconciliation lease prevents an expired/stale worker from committing
  an older provider read;
- manual-review resolution never directly grants entitlement and returns through
  reconciliation/access derivation;
- architecture checks prevent LBX/future-provider concepts/imports from leaking
  into Platform Kernel and generic domain/application packages.

## Explicit non-goals

MVP does not:

- make Platform Kernel a billing client;
- make Payments Portal a second commercial catalog, payment orchestrator, or
  financial ledger;
- call payment-specific LBX REST APIs;
- support bundles/all-access packages or one offer granting multiple products;
- support multiple active billable subscriptions for one user/product;
- support allowance stacking or a metric shared by multiple products;
- support paid overage;
- support Portal-initiated upgrade/downgrade, refund, dispute, or commercial
  trial;
- define Dodo-specific behavior before that adapter is designed;
- auto-bind unknown external customers to Portal users using PII;
- require a dedicated manual-review admin UI in MVP;
- decide merchant-of-record, 54-FZ, or legal retention policy without
  Legal/Finance confirmation;
- preserve legacy direct-payment-provider data/schema compatibility.

## Resulting bounded contexts

```text
External Billing
  owns commercial catalog and billing lifecycle
  + provider-owned payment UX/payment methods/refunds/invoices

Payments Portal
  owns AnyToolAI user identity and legal acceptance
  + external-billing anti-corruption layer
  + local catalog/subscription projections
  + immutable versioned capability mappings
  + reconciliation/discovery/recovery/manual review
  + entitlements and purchased allowance projections
  + AccessSnapshot and negative-access invalidation
  + usage delivery mediation when required

Platform Kernel
  owns technical product/metric vocabulary
  + actual usage and durable UsageEvent outbox
  + runtime quota enforcement
  + execution

Platform Kernel never calls an external billing system directly.
Payments Portal never calls payment-specific provider APIs.
RU payment interaction is LBX Widget, subject to the production validation gate.
```
