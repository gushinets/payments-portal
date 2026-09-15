# External billing boundary and Payments Portal redesign

Status: approved design
Date: 2026-09-15

## Goal

Redesign Payments Portal around a strict bounded-context split:

- the external billing system owns the commercial billing domain;
- Payments Portal owns AnyToolAI user identity plus the anti-corruption,
  projection, reconciliation, and entitlement boundary;
- Platform Core owns technical product identity, usage metrics, actual usage,
  quota enforcement, and runtime execution;
- Platform Core never communicates directly with LBX, Dodo, or any future
  billing provider.

The repository has not been deployed to production. The current direct-payment
and Portal-owned commerce schema is therefore disposable. This design uses a
clean pre-production reset rather than a backward-compatible migration path.

## Architectural invariants

### Ownership

External billing owns commercial billing truth. For RU this is LBX; EU/US will
use Dodo behind the same Portal boundary. The external billing system owns, as
applicable:

- commercial services/products;
- tariff/package composition;
- prices, currency, billing periods, discounts, commercial availability;
- commercial allowances and overage terms;
- commercial subscription lifecycle;
- agreements or equivalent provider-native commercial contracts;
- balances, charges, billing calculations, financial blocking;
- payments, refunds, payment methods, autopay;
- invoices and billing documents;
- billing customer profile and billing notifications.

Payments Portal owns:

- canonical AnyToolAI user identity, registration, authentication/session, and
  legal acceptance;
- mapping between AnyToolAI users and external billing customers;
- read-only projections of the external billing catalog and subscription state;
- explicit mapping between external billing components and technical Platform
  capabilities;
- purchase intent and customer-interaction orchestration state;
- reconciliation, command recovery, durable work, and webhook ingestion;
- normalized entitlements and purchased-allowance projections;
- the vendor-neutral access contract consumed by Platform Core.

Platform Core / the Platform side owns:

- technical `product_id` vocabulary and product registry mechanics;
- technical usage metric vocabulary (`metric_key`);
- actual runtime usage;
- runtime quota policy and enforcement;
- scenario/workflow/action execution.

The Portal may transport or normalize usage for an external billing provider,
but it does not become the source of truth for actual runtime usage.

### One-way billing dependency

Platform Core must never receive LBX/Dodo credentials or provider-specific
identifiers and must never call a billing provider directly.

```text
External Billing
      |
      | provider-specific REST/webhook/checkout
      v
Payments Portal
      |
      | vendor-neutral access + usage contracts
      v
Platform Core
```

The reverse usage path, when required by a provider, is also mediated by the
Portal:

```text
Platform Core -> UsageEvent -> Payments Portal -> provider adapter -> LBX/Dodo
```

### Projection, not duplicated authority

A local `billing_subscription`, catalog offer, or payment-related projection
never becomes commercial authority. If local state conflicts with an
external-billing authoritative read, successful reconciliation updates the
local projection to the provider state.

A webhook, browser callback, redirect return, successful outbound POST, payment
fact, agreement creation, or `PurchaseIntent` completion is never by itself an
access-granting fact.

## System shape

```text
                    Sales / Finance
                          |
                          v
                  External Billing
                 LBX (RU) / Dodo
                commercial authority
                          |
                   REST + webhooks
                          |
                          v
                +-------------------+
                | Payments Portal   |
                |                   |
                | User identity     |
                | Catalog projection|
                | Capability mapping|
                | Purchase intent   |
                | Reconciliation    |
                | Entitlements      |
                | Allowances        |
                +---------+---------+
                          |
                    AccessSnapshot
                          |
                          v
                +-------------------+
                | Platform Core     |
                |                   |
                | product_id        |
                | metric_key        |
                | actual usage      |
                | quota enforcement |
                | runtime execution |
                +-------------------+
```

## Commercial catalog model

### Fixed offers for MVP

For MVP, every sellable external tariff/period is a fixed commercial offer.
The customer does not add/remove individual services or choose arbitrary
quantities inside that offer. If sales needs a different service composition or
allowance, it creates a separate tariff/offer variant in the external billing
system.

For LBX, one normalized Portal offer is conceptually derived from a tariff,
period, and the tariff's service composition. The Portal does not author a
second Plan/Bundle model.

### No Portal-owned Product, Bundle, Plan, or PlanLimit

The current Portal-owned `Product`, `Bundle`, `Plan`, and `PlanLimit` commerce
concepts are removed from the target domain. Commercial packaging is external.
Technical product and metric identities are Platform-owned.

The Portal stores only read-only projections required for catalog display,
purchase validation, mapping, and reconciliation.

### External component mapping

Sales must not be required to type a technical identifier such as
`product.writer` or `writer.generations` correctly into an external billing
field for every tariff. Human entry of LBX `outer_id` is not the sole source of
truth.

The Portal owns an explicit mapping:

```text
external billing component -> Platform technical capability
```

A mapping target is one of:

- `product` with a valid Platform `product_id`;
- `usage_metric` with a valid Platform `metric_key`.

Example:

```text
LBX service #731 "Writer"      -> product_id = writer
LBX service #845 "Generations" -> metric_key = writer.generations
```

LBX `outer_id` may be stored and checked as an optional diagnostic/validation
hint, but it is not the authority for the mapping.

An offer containing an unmapped or invalid component is `NOT_SELLABLE` in the
Portal. Existing subscriptions are not revoked merely because current catalog
validation fails; subscription reconciliation is separate from new-offer
sellability.

### Platform capability manifest

The Platform side publishes a versioned technical capability manifest. The
Portal imports it as a read-only `technical_capabilities` projection instead of
calling Platform Core synchronously every time a mapping is validated.

The manifest includes at least:

- enabled technical products and their `product_id`;
- enabled usage metrics and their `metric_key` and unit;
- a source/version identifier.

The Platform repository remains the source of truth for this vocabulary. A
real usage-metric registry is added on the Platform side; it defines what can
be measured, not how many units a customer bought.

The distinction is:

```text
Platform: what can be measured
External billing: how much the customer bought
Platform Core runtime: how much was actually used
```

## Target Payments Portal data model

The exact SQL types, indexes, and names may follow repository conventions, but
the following semantic boundaries are required.

### Identity

Retain Portal-owned identity and legal concepts:

- `users`;
- authentication/session state;
- legal/document acceptances.

`users.id` is the canonical AnyToolAI user identifier. Email is an attribute,
not a cross-system identity key.

### External billing configuration and customer correlation

`external_billing_accounts` identifies the configured billing integration for a
contour. It includes provider/system, region, environment/account key, and
enabled state. It contains no credentials or secrets.

`external_billing_customers` maps `user_id` to an opaque provider customer
identifier and optional stable recovery key for one billing account.

External customer provisioning is eager-asynchronous after successful Portal
registration. Registration succeeds independently of provider availability. A
durable operation/work item provisions the external customer. Checkout always
executes an `ensure customer` barrier so it can recover or complete provisioning
if the background path has not finished.

### Catalog projections

`technical_capabilities` is the read-only projection of the Platform capability
manifest.

`billing_catalog_components` represents provider catalog components/services
needed by Portal mapping and offer composition.

`billing_component_mappings` maps each external component to exactly one valid
technical capability where applicable.

`billing_offers` is a read-only normalized projection of a concrete sellable
commercial offer. It includes commercial display facts, provider references,
status, source fingerprint/version, and synchronization timestamps.

`billing_offer_components` records the fixed external component composition and
commercial quantities/allowances of an offer.

### Purchase intent

There is no Portal-owned commercial `Order` in the target model.

`purchase_intents` records only that an AnyToolAI user started a purchase flow
for a confirmed offer version. It stores the local offer reference, immutable
commercial snapshot/fingerprint, orchestration status, idempotency identity,
interaction metadata, and lifecycle timestamps.

A `PurchaseIntent` is not an invoice, payment, order, or subscription.

Its state machine is Portal orchestration state, for example:

```text
created -> preparing -> interaction_ready -> awaiting_external_result -> linked
```

with terminal `expired` and `failed` states. `linked` means only that the
intent has been unambiguously linked to a real external subscription. It does
not mean that access is active.

### Subscription projection

`billing_subscriptions` exists only after an external subscription is confirmed
by authoritative provider read. The Portal does not create a fake
`provisioning` subscription before an external subscription exists.

Pre-subscription uncertainty belongs to `PurchaseIntent` and
`billing_operations`.

A normalized subscription keeps independent business dimensions:

```text
lifecycle_status: active | inactive | ended | unknown
financial_access_status: allowed | blocked | unknown
```

plus effective dates and authoritative/reconciliation timestamps. Provider
adapters translate provider-specific values into these normalized dimensions.
LBX fields such as `state` and `current_blocking` do not escape the LBX
integration layer.

`billing_subscription_components` is the authoritative read-only projection of
the actual component composition of that specific external subscription,
including effective quantities/allowances and dates.

Entitlements for existing customers are derived from the actual external
subscription composition, not from the current mutable catalog offer. Changing
a catalog tariff later must not silently rewrite the access of already-existing
subscriptions unless the external subscription itself has changed.

### Entitlements and purchased allowances

`entitlements` materializes normalized technical access grants. It references
`user_id`, the normalized billing subscription, `product_id`, validity, status,
and authoritative timestamps. It contains no tariff, bundle, LBX, or Dodo
identifiers.

`purchased_allowances` materializes purchased limits using Platform
`metric_key`, quantity, effective period, status, and the normalized billing
subscription.

The Portal does not persist runtime `remaining` usage as authority. Platform
Core computes remaining usage from purchased allowance and its own actual usage.

`billing_subscription_events` is an append-only Portal audit of normalized
projection/access transitions. It is not a copy of the provider event stream or
raw webhook payload.

### Reliability

`billing_operations` is the durable journal for Portal-initiated external
commands. It records operation type/key/request hash, subject links, attempts,
provider object references when known, and states such as:

```text
pending | in_progress | succeeded | unknown | ambiguous | failed | manual_review
```

The operation row exists durably before a non-idempotent external mutation is
attempted.

`billing_webhook_inbox` stores each authenticated webhook delivery separately,
with safe allowlisted correlation identifiers, event type, payload hash,
processing state, and timestamps. Payload hash is not a unique event identity.
Unrestricted raw provider payload is not stored by default.

`billing_work_items` is the durable PostgreSQL work queue for catalog sync,
webhook processing, operation recovery, discovery, and reconciliation. Claiming
uses short transactions/leases and is safe for multiple processors even though
MVP initially runs one API replica.

### Provider-specific support tables

Provider-neutral architecture does not require every persistence table to be
artificially generic. Typed integration-support tables are allowed when a
provider has a real concept that is not universal.

For LBX, dedicated agreement correlation/recovery data may live in tables such
as `lbx_agreement_bindings` and other typed LBX recovery tables. `Agreement` is
not a required application/domain concept and is not a mandatory relationship
on generic `billing_subscriptions`.

Do not replace typed provider support with a generic JSONB object graph.

## Purchase and customer-interaction lifecycle

### Offer validation

The browser submits only the Portal `offer_id`, the opaque `offer_version`
/fingerprint it was shown, and a client idempotency key. It never submits an
authoritative price, provider tariff ID, service ID, or billing period.

Before a new purchase, the Portal validates catalog freshness. If the projection
is fresh enough, it may proceed. If stale, the Portal performs a targeted
provider refresh. If commercial terms changed, the purchase returns
`offer_changed` and requires the user to review/confirm the new terms. If stale
terms cannot be confirmed because the billing provider is unavailable, a new
purchase fails closed.

Only after current terms are confirmed does the Portal create the durable
`PurchaseIntent` and immutable commercial snapshot.

### Provider-neutral purchase preparation

The application flow is:

```text
PurchaseIntent
 -> ensure external customer
 -> provider-specific purchase preparation
 -> CustomerInteraction
 -> external result/discovery
 -> authoritative subscription reconciliation
 -> PurchaseIntent linked
```

The application layer does not issue provider-shaped commands such as
`create_agreement()` or assume every provider has an Agreement. The LBX adapter
may internally create/recover a dedicated agreement and subscription; Dodo may
use a hosted checkout or other provider-native sequence.

### CustomerInteraction

A provider adapter may return a vendor-neutral interaction of type:

- `embedded`;
- `redirect`;
- `portal_managed`.

A browser return, JS callback, redirect success flag, or embedded-widget event
is only a UX/reconciliation hint. It may enqueue a high-priority reconciliation
but never activates an entitlement directly.

### Synchronous happy path with durable recovery

A normal request may execute provider calls synchronously after the local
durable operation has committed, so a healthy provider does not force an
artificial worker delay. No external network call occurs inside an open database
transaction.

If the result is uncertain, the operation becomes `unknown`, the API may return
a processing response, and the durable worker continues recovery. Non-idempotent
create calls are never blindly retried after timeout.

For providers such as LBX that lack create idempotency, recovery follows the
provider-specific stable lookup contract. Zero matches may permit a controlled
retry according to operation policy; one match binds the object; multiple
matches become `ambiguous`/`manual_review`.

## Entitlement derivation

An active entitlement requires all of the following:

- normalized subscription lifecycle is `active`;
- normalized financial access is `allowed`;
- current time is inside the authoritative effective period;
- the actual external subscription component has a valid Portal mapping to an
  enabled technical capability;
- the Portal still considers the last authoritative state usable under the
  freshness policy.

`unknown` never creates a new active grant. Payment success alone never grants
access. An authoritative negative state such as blocked or ended removes access
through normal reconciliation without waiting for a grace period.

Purchased allowances are derived by the same reconciliation transaction from
the actual subscription components, not from a mutable current catalog offer.

## Reconciliation model

### Webhook plus scheduled authoritative reads

Webhook is a notification/acceleration mechanism, not billing authority.
Scheduled reconciliation is mandatory and correctness must not depend on
webhook delivery or provider retry behavior.

Webhook request processing is deliberately short:

```text
authenticate provider webhook
 -> minimal validation / safe correlation extraction
 -> persist inbox delivery
 -> enqueue or coalesce work
 -> commit
 -> return 2xx
```

No provider REST call occurs in the webhook request.

Webhook deliveries remain individually auditable, while work items may coalesce
multiple notifications into one logical reconciliation subject.

Scheduled reconciliation selects subjects based on `next_reconcile_at` or
equivalent policy and executes the same authoritative read/apply path as a
webhook-triggered reconcile. Reconciliation cadence is configurable and may be
more aggressive for recent purchases or blocked subscriptions.

### Per-subject serialization

Only one authoritative reconciliation for a given external subscription may be
active at a time. MVP should use a process-independent PostgreSQL mechanism such
as a session-level advisory lock or an equivalent per-subject lock. The network
read occurs without an open database transaction.

After a complete provider snapshot is available, a short local transaction
atomically updates:

- normalized subscription state;
- subscription components;
- entitlements;
- purchased allowances;
- normalized audit events;
- reconciliation timestamps.

A partial/inconsistent provider read does not replace a known-good projection
with empty or guessed state. The reconciliation fails, preserves the prior
projection, records safe operational diagnostics, and retries later.

### Discovery versus known-object reconciliation

Known subscriptions reconcile by exact external reference. Discovery of a new
subscription for a `PurchaseIntent` is a separate work kind. This distinction is
required for provider flows, such as a future LBX Widget flow, in which the
provider interaction might create the subscription before the Portal knows its
external ID.

The exact Widget discovery strategy is not part of the core domain contract and
must be proven against LBX agreement/subscription scoping before production use.

## Freshness and failure policy

Use bounded last-known-good access for existing confirmed subscriptions, while
failing closed for new commercial actions.

New purchases, upgrades/downgrades, or other new commercial mutations fail
closed when required provider state/terms cannot be confirmed.

A single failed reconciliation does not immediately revoke previously confirmed
access. Business state and operational freshness are separate. The Portal keeps
`last_authoritative_at`, reconciliation-attempt metadata, and a finite
`projection_valid_until`/equivalent trust boundary.

Conceptually:

```text
fresh -> stale_usable -> expired
```

This is derived freshness, not a provider subscription status.

Rules:

- stale data may temporarily continue an already-confirmed grant;
- stale data cannot create a new grant, increase an allowance, or extend a
  subscription period;
- the trust deadline never exceeds the authoritative subscription
  `effective_until`;
- once the finite trust deadline expires, paid access fails closed;
- an authoritative blocked/ended state applies immediately and is not delayed by
  the outage grace policy.

TTL/grace durations are configurable operational policy rather than hard-coded
domain constants.

## Payments Portal <-> Platform contract

### AccessSnapshot

Platform Core pulls a vendor-neutral AccessSnapshot from the Portal and caches
it with bounded freshness. The snapshot identifies the canonical tenant/region
/user and contains explicit technical grants and purchased allowances.

Conceptual shape:

```json
{
  "tenant_id": "anytoolai",
  "region": "ru",
  "user_id": "uuid",
  "snapshot_version": "opaque",
  "authoritative_as_of": "timestamp",
  "refresh_after": "timestamp",
  "expires_at": "timestamp",
  "grants": [
    {"product_id": "writer", "valid_from": "...", "valid_until": "..."}
  ],
  "allowances": [
    {
      "metric_key": "writer.generations",
      "quantity": 1000,
      "period_start": "...",
      "period_end": "..."
    }
  ]
}
```

The snapshot contains no LBX tariff/service/agreement/subscription IDs, Dodo
IDs, balances, billing statuses, or provider-specific blocking fields.

Portal materializes commercial bundles/all-access packages into explicit
`product_id` grants before returning the snapshot. Platform Core does not know
billing Bundle/Plan concepts.

Core cache behavior:

- before `refresh_after`, use the cached snapshot;
- between `refresh_after` and `expires_at`, attempt refresh but the existing
  snapshot remains usable if Portal is temporarily unavailable;
- at/after `expires_at`, the paid snapshot is unusable and paid access fails
  closed;
- Core snapshot expiry never exceeds the Portal's own projection/entitlement
  trust boundary.

Guest/free functionality remains governed by Platform Core policy and is not
implicitly disabled by a billing outage.

### Runtime usage

Platform Core remains authoritative for actual usage and quota consumption. It
combines purchased allowance from AccessSnapshot with its own atomic usage
state. The Portal does not sit in the hot path of every scenario/action.

If a provider requires consumption reporting, Core sends vendor-neutral,
idempotent `UsageEvent` records to the Portal, including a unique
`usage_event_id`, canonical identity, `metric_key`, quantity, and occurrence
time. The Portal maps the metric to the relevant external component and invokes
the provider usage capability. Provider retries must not double-report the same
usage event.

## Provider abstraction

Application/domain code depends on small capability-oriented ports rather than
one LBX-shaped interface or a lowest-common-denominator object model.

Required conceptual capabilities include:

- external catalog reads;
- external customer ensure/recovery;
- purchase preparation/customer interaction;
- authoritative subscription state read/discovery;
- optional usage reporting;
- webhook authentication/parsing.

Provider adapters translate provider protocol into normalized billing facts.
The Portal mapping layer separately translates normalized external components
into AnyToolAI technical capabilities.

Provider-specific branching (`LBX` versus `Dodo`) is allowed in composition and
integration packages, not in domain/application use cases or Platform Core.

LBX-specific Agreement logic, `state`, `current_blocking`, tariff/service API,
Widget mechanics, create-recovery details, and `/bulk` usage protocol remain
inside the LBX integration boundary.

## Worker topology and transaction rules

MVP runs the durable billing worker embedded in the API process with one API
replica initially. Work is persisted in PostgreSQL before asynchronous
execution. Correctness must not depend on in-memory background tasks.

Worker/use-case code is independent of FastAPI composition so it can later move
to a dedicated process without changing domain behavior.

Queue claiming and reconciliation serialization must be safe for multiple
processors even though deployment initially uses one replica.

External network requests never execute inside an open database transaction.
Transactions are short and cover durable intent creation, queue claiming, or
atomic local projection updates only.

No RabbitMQ/Kafka is required for MVP.

## Security

External billing credentials, webhook secrets, Widget signing secrets, and
payment credentials exist only in runtime secret configuration for the
integration layer. They are not stored in `external_billing_accounts`, domain
objects, logs, or browser-visible responses.

Core-facing access and usage endpoints are internal service-to-service APIs.
User authentication alone must not authorize them. The deployment must provide
a service-authentication mechanism over TLS and both sides must enforce the
expected tenant/region/user scope. A contour may never read or write another
contour's billing/access data.

Webhook authentication is provider-specific and occurs before durable
processing. Reverse proxy/access logging must not leak query-string secrets or
authentication data.

Store only the billing data the Portal needs for identity correlation,
projection, access, support, or recovery. Do not build a shadow financial
ledger or copy card details, provider secrets, full billing documents, or other
sensitive provider data without a concrete Portal use case.

## LBX Widget status

LBX Widget remains an optional customer-interaction adapter, not a dependency of
the architecture. Current evidence is insufficient to approve it for
production checkout because authenticated rendering and strict agreement-level
commercial isolation have not yet been proven.

Production enablement requires runtime/vendor confirmation of the supported
script URL and signing-key provisioning, agreement/subscription scoping, and
server-side mutation restrictions. UI-hidden controls are not treated as a
security boundary.

Until those requirements are proven, REST-managed/provider-hosted interaction
remains the planning baseline. The domain/data model does not change if Widget
is later approved.

## Observability and audit

Structured logs and traces use safe correlation identifiers such as request ID,
user ID, purchase intent ID, billing operation ID, work-item ID, normalized
subscription ID, and safe opaque external references. Do not use email or other
PII as the primary correlation key.

At minimum monitor:

- catalog projection age and sync failures;
- unmapped components and invalid/not-sellable offers;
- external customer provisioning failures;
- `unknown`, `ambiguous`, and `manual_review` operation counts;
- reconciliation success/failure, duration, and age since last authoritative
  state;
- work-queue depth, oldest-item age, and retry counts;
- webhook authentication failures and processing lag;
- fresh/stale-usable/expired access projection counts;
- provider latency, timeout, and error rate.

Alert on growing unknown/manual-review work, stale catalog or reconciliation,
unmapped components in externally sellable offers, a non-draining queue, and a
material increase in expired paid-access projections.

The normalized subscription audit must make it possible to answer why Portal
access changed, for example which authoritative reconciliation caused a
financially-allowed subscription to become blocked and which entitlements were
then deactivated. This audit does not require storing raw provider payloads.

## Clean pre-production reset

There is no production deployment and no compatibility contract to preserve.
Do not implement a staged dual-schema or semantic data migration from the old
Portal-owned commerce model.

The implementation should:

1. remove obsolete Portal-owned commercial concepts and their code paths,
   including Product/Bundle/Plan/PlanLimit/Order semantics from Payments Portal;
2. remove the old direct-payment-provider architecture, DTOs, adapters,
   checkout/webhook paths, and provider-shaped subscription/payment fields that
   are no longer part of the target design;
3. replace the development database/Alembic baseline with the clean target
   schema rather than preserving disposable legacy commerce data;
4. recreate development/test databases from empty state;
5. implement the new path in dependency order: capability import -> external
   catalog projection -> component mappings -> customer provisioning -> purchase
   flow -> reconciliation -> entitlements/allowances -> AccessSnapshot -> Core
   integration;
6. use no dual-write compatibility layer and no old/new billing traffic split.

If a developer or staging database contains useful manual data, export it
separately before reset. That data does not constrain the target architecture.

## Required correctness tests

The implementation plan must include tests proving at least these behaviors:

- duplicate public purchase submission with one idempotency key creates one
  PurchaseIntent;
- provider create timeout enters `unknown`, performs lookup/recovery, and does
  not blindly duplicate a non-idempotent create;
- duplicate or out-of-order webhooks converge to the same current authoritative
  projection;
- a completely missed webhook is repaired by scheduled reconciliation;
- temporary provider outage preserves an existing last-known-good entitlement
  only inside its finite trust lease;
- outage beyond the trust lease fails closed for paid access;
- an authoritative blocked/ended state revokes access without grace delay;
- an unmapped external service makes a new offer not sellable;
- commercial terms changing after display produce `offer_changed` and no
  purchase on the stale version;
- two workers cannot apply stale concurrent reconciliation for the same
  subscription;
- an incomplete provider read preserves the previous good projection;
- catalog mutation does not silently rewrite existing subscription grants;
- Core receives no provider-specific identifiers or billing state;
- Core actual-usage consumption remains atomic and independent of provider
  availability;
- usage reporting is idempotent by `usage_event_id` when enabled;
- no external network request occurs inside an open database transaction;
- architecture checks prevent LBX/Dodo concepts/imports from leaking into
  domain/application and Platform Core code outside explicit integration and
  composition boundaries.

## Explicit non-goals

This design does not:

- make Platform Core a billing client;
- make Payments Portal a second commercial catalog or financial ledger;
- define Dodo-specific API behavior before its adapter is designed;
- require LBX Widget for MVP;
- define exact production TTLs, polling intervals, alert thresholds, or
  service-authentication technology; these are configurable operational choices
  constrained by the semantics above;
- preserve legacy direct-payment-provider data or schema compatibility.

## Resulting bounded contexts

The final boundary is intentionally strict:

```text
External Billing
  owns commercial billing domain

Payments Portal
  owns AnyToolAI user identity
  + external-billing anti-corruption layer
  + local projections
  + reconciliation/recovery
  + entitlements and purchased allowances

Platform Core
  owns technical product/metric vocabulary
  + actual usage
  + runtime quota enforcement
  + execution

Platform Core never calls an external billing system directly.
```
