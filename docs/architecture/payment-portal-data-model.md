# Payment Portal Data Model and Backend Invariants

Status: normative source of truth
Version: 0.6
Last verified against code: 2026-09-04
Implementation expansion owner: Linear ANY-71

This document is the primary source of truth for Payment Portal data ownership,
state transitions, persistence rules, and the boundary with Platform Kernel.
The generated schema documents what exists in code; this document explains what
that schema means and distinguishes current implementation from planned work.
Contour isolation is defined in [contours](contours.md). Provider adapters are
defined for the Portal-managed direct-provider flow in
[payment providers](payment-providers.md). Billing ownership and external
lifecycle authority are defined in
[Billing Authority and Consistency](billing-authority.md). Browser routing to
another contour is defined in [Region Resolver](region-resolver-contract.md).

## 1. Locked decisions

- PostgreSQL is the production database.
- Production-facing and cross-service domain IDs use UUIDs.
- Mutable tables carry `created_at` and `updated_at`; append-only event/audit
  tables carry an immutable creation or occurrence timestamp.
- Use text plus validated application values or check constraints for evolving
  statuses rather than PostgreSQL enums.
- `app.models` owns SQLAlchemy models and confirmed closed persisted
  vocabularies. Persisted Python enums are `StrEnum` values validated at the
  model boundary; database representation remains `TEXT` or `VARCHAR`.
- Provider contract enums remain distinct from local persisted enums. Open
  provider, configuration, and identifier namespaces remain strings.
- Money uses integer minor units and an ISO 4217 currency code.
- Provider identifiers are opaque text.
- Raw provider payloads use JSONB and are redacted before persistence.
- Contour identity is `regions.code`. Planned contours are `ru`, `eu`, and
  `us`. A production instance stores and serves exactly one contour.
- Identity is `tenant_id + region + user_id` and is independent across
  contours. The same email on two contours is two accounts on two data planes.
- Payment Portal owns identity, legal and catalog semantics, entitlement rules,
  and local entitlements. In the current Portal-managed direct-provider flow it
  also owns the billing lifecycle. Under external billing, the external system
  owns its external customer, invoice, payment, and subscription lifecycle,
  while Portal `Order`, `Payment`, and `Subscription` records are normalized
  local projections. Platform Kernel owns runtime sessions, jobs, actions,
  provider calls, artifacts, events, and usage consumption.
- Paid access is activated only from a verified authoritative billing fact,
  never from a browser return URL or outbound command result.
- Payment Portal stores purchased limits; Platform Kernel stores usage.
- A free trial is modeled as subscription plus entitlement without order/payment.
- Bundle and all-access offerings are independent sellable plans whose final
  price is snapshotted into order items.
- Card data is never stored by this service.

## 2. Implementation status

| Table | Status | Purpose |
|---|---|---|
| `regions` | Implemented | Regional configuration vocabulary |
| `country_region_rules` | Implemented | Country-to-region policy data |
| `legal_entities` | Implemented | Seller/operator identity per region |
| `document_versions` | Implemented | Versioned legal document metadata |
| `document_acceptances` | Implemented | Append-only acceptance evidence |
| `users` | Implemented | Regional user identity |
| `auth_sessions` | Implemented | Hashed login sessions |
| `magic_link_tokens` | Implemented | Hash-only password-reset token storage |
| `password_reset_rate_limits` | Implemented | Shared password-reset throttling counters |
| `payment_provider_accounts` | Implemented | Non-secret regional direct-provider configuration for the Portal-managed flow |
| `entrypoint_sessions` | Implemented schema | Product/paywall entry context |
| `checkout_sessions` | Implemented | Checkout preparation state |
| `orders` | Implemented | Internal commercial order |
| `order_items` | Implemented | Immutable commercial snapshot |
| `payments` | Implemented | Payment attempts and outcomes |
| `refunds` | Implemented | Full and partial refund records |
| `payment_webhook_events` | Implemented | Redacted webhook inbox and processing audit |
| `product_access_states` | Removed by ANY-78 | Temporary access projection replaced by subscriptions and entitlements |
| `products` | Implemented | Billing-visible product catalog |
| `bundles` | Implemented | Sellable product groups |
| `bundle_products` | Implemented | Version-aware bundle membership |
| `plans` | Implemented | Versioned sellable prices and periods |
| `plan_price_components` | Implemented | Bundle/all-access price calculation snapshot |
| `plan_limits` | Implemented | Purchased usage limits |
| `subscriptions` | Implemented | Trial/manual/automatic access lifecycle |
| `entitlements` | Implemented | Explicit runtime-readable access grants |
| `subscription_events` | Implemented | Append-only subscription audit |
| Fiscal receipt tables | Deferred | Add only with a contour's fiscal-provider requirement |
| Coupons, wallet, ledger | Deferred | Not required for the implemented `ru` contour |
| Provider reconciliation runs | Deferred | Add when operational volume requires it |

Exact implemented columns and indexes are generated in
[`docs/generated/db-schema.md`](../generated/db-schema.md). Any implemented ORM
table missing from the table above is a documentation-check failure.

## 3. Current implemented model

### Contour configuration

`regions.code` is the contour key. Identity, legal, billing, and access records
carry that contour. `country_region_rules` lists countries that belong to the
**local** contour: market enablement, override policy, document set, and default
provider. The default-provider fields configure the current Portal-managed
direct-provider flow; they do not define a universal external-billing model.

The implemented product is the `ru` contour. The first-install seed also inserts
an `eu` region and DE/ES country rules into the same database. That seed is not
permission for a `ru` instance to serve Europe. `us` is not in the schema.
See [contours](contours.md).

Region Resolver, not this database, owns the map of deployed contours and their
base URLs, plus the public ISO country-to-contour map. `region_mismatch` means
this instance cannot serve the request: send the browser through the resolver.
Do not write another contour's user or order into this data plane.

Current registration and login accept a client-supplied `region`, and the
first-install migration seeds both `ru` and `eu`. These are known gaps against
the target one-contour-per-instance invariant. A future instance-contour setting
must reject foreign regions before another contour is enabled.

### Identity

`users` uses UUID primary keys and requires:

```text
unique(tenant_id, region, email_normalized)
```

Raw session tokens are returned to the client once and stored only as SHA-256
hashes in `auth_sessions`. Sessions have expiry and revocation timestamps.
Password-reset tokens are emailed once and stored only as SHA-256 hashes in
`magic_link_tokens`. Reset confirmation consumes outstanding reset tokens for
that user and revokes active sessions. For the implemented `ru` contour,
password-reset request scope is derived server-side rather than accepted from
unauthenticated clients.
Password-reset request throttling is stored in `password_reset_rate_limits` so
limits are shared across API workers. Counters are keyed by account or IP scope
and expire after their current window. Expired password-reset token rows are
pruned before new reset-token persistence.

### Legal

`document_versions` identifies a legal document by:

```text
tenant_id + region + doc_type + version
```

Only one version per `tenant_id + region + doc_type` may be active. Its
`content_hash` is the SHA-256 hash of the canonical normalized Markdown body.

The current schema therefore supports one active legal pack per contour.
`country_region_rules.default_document_set` is configuration vocabulary, not a
key or foreign key into `document_versions`. If countries in one contour need
different active documents, ANY-71 must define a document-set dimension and its
relationship to country rules, document versions, acceptances, generation, and
rendering before that contour is enabled.

`document_acceptances` is append-only. It snapshots type, version, acceptance
kind, acceptance text hash, time, source, and relevant entrypoint context. A new
document version requires a new acceptance. Revocation, when implemented, must
be a separate append-only record rather than mutation of acceptance history.

### Checkout and orders

The accepted checkout identity decision is recorded in [ADR 0002](decisions/0002-plan-based-checkout-identity.md).
The catalog returns Product data with the exact currently sellable Plan:

```text
backend catalog returns Product + exact current Plan
-> frontend selects Product for UI
-> frontend submits Plan.id for checkout
-> backend resolves exact current Plan
-> backend validates Plan scope/reference shape
-> backend derives scope and commercial snapshots
-> order/order_item persist resolved facts
```

`Plan.id` is the only commercial purchase identity submitted by checkout.
`Product.code`, `Bundle.code`, and `Plan.code` are readable catalog or
snapshot data, not generic checkout selectors. The target checkout request
therefore removes `product` and `plan_code` without compatibility aliases.

An `entrypoint_session` records product/bundle/catalog/paywall context and future
regional-resolution evidence. It is provenance, not the purchased object:
`entrypoint_session != purchased object`. For current product navigation,
`?product=<Product.code>` may remain as UI selection, but it does not authorize
the purchase. Entrypoint fields never participate in Plan resolution.

A `checkout_session` binds an authenticated user, the exact Plan reference,
amount/currency snapshot, consent readiness, and expiry. Product, Bundle, and
scope facts are derived from the resolved Plan. A product-scoped Plan requires
an active referenced Product and no Bundle reference; a bundle-scoped Plan
requires an active referenced Bundle and no Product reference; an
`all_access`-scoped Plan has neither reference. No Product or Bundle is
synthesized for `all_access` scope, and no `all-access` identity is generated.

The persisted access scope `all_access` is distinct from the removed synthetic
checkout sentinel `all-access`. `all_access` remains access/scope semantics;
`all-access` is not checkout vocabulary or a purchase identifier.

Recurring consent is bound to the exact Plan ID plus the existing user, contour,
current legal document/version/hash, acceptance kind/time, and entrypoint
dimensions:

```text
same Plan.id + same user/contour/legal/entrypoint context -> consent may validate
new Plan.id -> previous recurring consent does not authorize the new Plan
-> checkout provides a fresh append-only consent path
```

Provider merchant and invoice IDs are opaque and do not encode catalog, scope,
or entrypoint strings. Checkout responses are purchase/Plan-oriented while
preserving the provider-neutral `checkout.amount`, `checkout.currency`, and
`checkout.action` envelope.

In the current Portal-managed flow, an `order` is the authoritative internal
commercial request. It contains the user, region, checkout and entrypoint links,
amount/currency, provider account, merchant/provider identifiers, timestamps,
and region-mismatch state. In an external-billing-managed flow, the local
`Order` is instead a normalized projection of the externally owned lifecycle;
this documentation change introduces no new columns or mapping tables.

`order_items` preserves the commercial facts shown at checkout: item type,
product/bundle/plan identifiers, names and codes, quantities, prices, discounts,
currency, trial days, and pricing calculation. Historical order items are not
recalculated when catalog prices change.

### Payments, refunds, and webhook inbox

One order may have multiple payment attempts. `payments` stores provider IDs,
status, amounts, currency, method category, lifecycle times, refund total, safe
failure details, and a normalized safe summary.

`refunds` records each full or partial refund independently and is idempotent on
provider account plus provider refund ID when supplied.

`payment_webhook_events` is the provider inbox. It stores provider/endpoint,
payload hash, normalized idempotency key, safe identifiers, amount/currency,
redacted payload and headers, processing state, and links to normalized order and
payment records. Raw card fields and secrets are forbidden.

### Subscriptions, entitlements, and access audit

`subscriptions` represents the contour-local, access-facing lifecycle for
trials, paid periods, manual renewal, automatic renewal, cancellation,
provider-reference attachment, refund outcomes, and expiration. In the current
Portal-managed flow, Payment Portal owns that billing lifecycle. In an
external-billing-managed flow, the external system owns its external
subscription lifecycle and the local `Subscription` is a normalized projection
used by Portal entitlement rules. Subscription identity is internal UUID
identity; provider account and provider subscription IDs are optional opaque
references, not Payment Portal domain identities.

Automatic renewal can be enabled only after provider setup succeeds. Until then,
a requested automatic renewal remains a manual subscription with paid access
governed by the verified paid period. The subscription stores the exact
`document_acceptances` row used as recurring-consent evidence.

`entitlements` are the explicit access grants for a subscription. They snapshot
the same exact scope as the subscription: direct product, bundle, or all-access.
Each paid period is a separate grant with immutable source provenance:
`source='order'` plus the source `order_id`. Payment and webhook evidence stays
on the append-only `subscription_events` row for the operation. Ordinary
renewal creates a new grant and does not rewrite the previous grant's source.
Replacing access for the same exact scope supersedes the previous active or
future entitlements for that scope; other scopes may coexist.

Access checks must evaluate the entitlement time range, not only its lifecycle
status:

```text
status = active
AND valid_from <= now
AND valid_until > now
```

A future paid entitlement is stored as `active` so refund and audit logic can
see it, but it does not grant runtime access before `valid_from`. If a refund
removes the current grant while a future paid grant remains, the subscription
stays in a non-terminal lifecycle state such as `active`; access remains denied
until the future grant enters its validity window.

`subscription_events` is append-only audit. It records the event type, previous
and next subscription status, occurrence time, local operation idempotency key,
optional order/payment/refund/webhook links, and redacted metadata. It does not
carry `updated_at`.

## 4. State models

### Order

```text
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
```

Only a verified authoritative fact from the billing owner may set `paid`. For
the current Portal-managed flow, that is verified provider state.
`region_mismatch` blocks future entitlement creation on this instance and is a
Region Resolver redirect signal, not a local rewrite onto another contour.

### Payment

```text
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
```

For the implemented `ru` CloudPayments charge mode, the expected terminal
transition is `created -> succeeded` or `created -> failed`. Authorization mode
may persist `created -> authorized`; a later `confirm`, `fail`, or `cancel`
webhook moves it to `succeeded`, `failed`, or `canceled`. A late failure must not
downgrade an already successful payment or paid order. Future billing
integrations may project authoritative facts into the same local payment
states; a contour is not required to register a direct-provider adapter.

### Webhook event

```text
received
processing
processed
ignored
duplicate
failed
```

Duplicate delivery is a normal provider behavior and must produce an idempotent
result rather than duplicate domain mutations.

### Subscription and entitlement states

```text
subscription: trialing | active | past_due | canceled | expired | refunded | paused
entitlement: active | expired | revoked | superseded
```

## 5. CURRENT: Portal-managed payment lifecycle

```text
authenticated user
-> required active legal versions checked
-> missing acceptances recorded by the user
-> checkout session and order created
-> contour payment-provider checkout opened
-> webhook received, authenticity checked, payload redacted and persisted
-> payment/order updated idempotently
-> verified initial payment activates the paid subscription period and entitlement
-> browser payment-result page polls informational state
```

The implemented `ru` adapter opens the CloudPayments widget and verifies
CloudPayments signatures. That is adapter behavior, not the domain lifecycle.
The domain lifecycle receives only internal order, payment, webhook, refund, and
normalized provider-state identifiers. Browser callbacks never activate access.

Contour confirmation through Region Resolver at login and registration is
planned and is not part of the current implemented flow.

Refunds and expiration also change access only through the subscription
lifecycle. A full refund revokes only the entitlement rows funded by the
refunded order/payment; it must not revoke later paid periods funded by another
order. A partial refund records an audit event without changing access.
Expiration is a one-shot, idempotent maintenance command for an external
scheduler, and access evaluation must still enforce `valid_until` if that
command is delayed.

### TARGET: external-billing-managed lifecycle

An external billing system may own its external customer, invoice, payment, and
subscription lifecycle. For that flow, verified webhooks are the primary
asynchronous authoritative facts and verified reconciliation is the recovery
path. Both must converge through the same normalized local transition rules;
an outbound command result is not payment, subscription, or entitlement
authority.

The existing `orders`, `payments`, and `subscriptions` remain the Portal's
normalized local projections for entitlement processing. Payment Portal remains
authoritative for catalog semantics, entitlement rules, and `entitlements`, and
Platform Kernel continues to consume only those local entitlements. This target
description adds no external-customer table, external-subscription table,
billing-owner field or enum, adapter, mapping schema, or other implemented
persistence.

## 6. Implemented catalog and access model

### Catalog and pricing

- `products` owns stable tenant product codes and Platform Kernel product IDs.
- `bundles` plus `bundle_products` own explicit bundle membership.
- `plans` owns versioned scope, region, price, currency, period, renewal mode,
  trial days, validity interval, and status.
- The backend catalog returns each product with its exact currently sellable
  Plan ID. Product selection is UI/catalog selection; checkout purchase
  authority is that Plan ID.
- `plan_price_components` records source plan prices and discount calculation for
  bundle/all-access plans.
- `plan_limits` records metric, limit, period, reset, and overage policy.

Initial product codes remain `document-summary` and `prompt-optimizer`. The
implemented `ru` catalog stores prices in minor RUB units and snapshots them at
order creation. Money in the model is always integer minor units plus an ISO
4217 code; it is not RUB-only.

### Subscriptions and entitlements

`subscriptions` own trial and paid periods, renewal mode, cancellation, and
optional provider subscription references. `entitlements` are explicit grants
with scope, validity, source, order, and subscription links. Platform Kernel will
read entitlements through the future Payment Portal access API and will continue
to own actual usage counters.

Direct product, containing bundle, and all-access grants are the three allowed
ways for a product access check to succeed. Final ANY-370 ownership checks may
therefore block purchase of a selected Product through a direct Product,
containing Bundle, or `all_access` entitlement. That access decision is
independent from checkout selection: none of these scopes is a checkout
purchase identifier, and the client submits only the exact Plan ID.

## 7. External Platform Kernel boundary

The future verified identity key is:

```text
tenant_id + region + user_id
```

`region` is the local contour. Platform Kernel in another contour is a different
deployment. This portal does not answer access checks for a foreign contour.

The proposed access request includes the identity key, product code, and optional
scenario/session context. The response includes allowed state, entitlement and
subscription identifiers, plan code, validity, scope, and purchased limits.

The private Platform Kernel access API is planned context only in this
repository and is owned by ANY-79. The implemented authenticated account
subscription APIs are for Payment Portal users and do not expose provider
references, payment IDs, webhook IDs, or raw audit payloads.

## 8. Migration and seed rules

- The corrected initial migration defines the schema baseline.
- After it is frozen, use forward Alembic revisions.
- Do not use PostgreSQL enums for evolving provider/domain statuses.
- Use JSONB for redacted provider payloads and INET for IP data.
- Do not add `updated_at` to append-only acceptance, subscription-event, or
  webhook-inbox records.
- Do not recreate or expand `product_access_states`; ANY-78 is a clean-baseline
  implementation with no legacy data backfill because deployment has not
  occurred.
- Never place secrets in migrations, seed data, or database configuration rows.
- Versioned legal source and its generated manifest must match the first-install
  seed exactly.

## 9. Unresolved product decisions owned by ANY-71

- Retention for raw webhook payloads, IP, user agent, and acceptance evidence.
- Whether billing address or payer profile is required.
- Merchant of Record, billing owner and integration, assigned countries, and
  any direct payment provider for `eu` and `us`, plus whether either contour
  needs country-specific legal document sets. The seed `paddle` and
  `default_document_set` values for DE/ES are not those decisions.
- How the required customer country is declared, verified, and updated inside a
  multi-country contour. Resolver geo is only a routing suggestion; contour
  enablement must define the country used to select legal and provider rules.
- Initial bundle/all-access offering and numeric plan limits.
- Administrative price regeneration and provider reconciliation behavior.

These are not implementation decisions for ANY-78.
