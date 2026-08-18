# Payment Portal Data Model and Backend Invariants

Status: normative source of truth
Version: 0.4
Last verified against code: 2026-08-18
Implementation expansion owner: Linear ANY-71

This document is the primary source of truth for Payment Portal data ownership,
state transitions, persistence rules, and the boundary with Platform Kernel.
The generated schema documents what exists in code; this document explains what
that schema means and distinguishes current implementation from planned work.
Contour isolation is defined in [contours](contours.md). Provider adapters are
defined in [payment providers](payment-providers.md). Browser routing to another
contour is defined in [Region Resolver](region-resolver-contract.md).

## 1. Locked decisions

- PostgreSQL is the production database.
- Production-facing and cross-service domain IDs use UUIDs.
- Mutable tables carry `created_at` and `updated_at`; append-only event/audit
  tables carry an immutable creation or occurrence timestamp.
- Use text plus validated application values or check constraints for evolving
  statuses rather than PostgreSQL enums.
- Money uses integer minor units and an ISO 4217 currency code.
- Provider identifiers are opaque text.
- Raw provider payloads use JSONB and are redacted before persistence.
- Contour identity is `regions.code`. Planned contours are `ru`, `eu`, and
  `us`. A production instance stores and serves exactly one contour.
- Identity is `tenant_id + region + user_id` and is independent across
  contours. The same email on two contours is two accounts on two data planes.
- Payment Portal owns identity, legal, catalog, orders, payments, subscriptions,
  and entitlements. Platform Kernel owns runtime sessions, jobs, actions,
  provider calls, artifacts, events, and usage consumption.
- Paid access is activated only from a verified webhook or verified server-side
  provider state, never from a browser return URL.
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
| `payment_provider_accounts` | Implemented | Non-secret regional provider configuration |
| `entrypoint_sessions` | Implemented schema | Product/paywall entry context |
| `checkout_sessions` | Implemented | Checkout preparation state |
| `orders` | Implemented | Internal commercial order |
| `order_items` | Implemented | Immutable commercial snapshot |
| `payments` | Implemented | Payment attempts and outcomes |
| `refunds` | Implemented | Full and partial refund records |
| `payment_webhook_events` | Implemented | Redacted webhook inbox and processing audit |
| `product_access_states` | Legacy temporary | Current simplified product payment/access view |
| `products` | Implemented | Billing-visible product catalog |
| `bundles` | Implemented | Sellable product groups |
| `bundle_products` | Implemented | Version-aware bundle membership |
| `plans` | Implemented | Versioned sellable prices and periods |
| `plan_price_components` | Implemented | Bundle/all-access price calculation snapshot |
| `plan_limits` | Implemented | Purchased usage limits |
| `subscriptions` | Planned under ANY-71 | Trial/manual/automatic access lifecycle |
| `entitlements` | Planned under ANY-71 | Explicit runtime-readable access grants |
| `subscription_events` | Planned under ANY-71 | Append-only subscription audit |
| Fiscal receipt tables | Deferred | Add only with a contour's fiscal-provider requirement |
| Coupons, wallet, ledger | Deferred | Not required for the implemented `ru` contour |
| Provider reconciliation runs | Deferred | Add when operational volume requires it |

Exact implemented columns and indexes are generated in
[`docs/generated/db-schema.md`](../generated/db-schema.md). Any implemented ORM
table missing from the table above is a documentation-check failure.

## 3. Current implemented model

### Contour configuration

`regions.code` is the contour key. Identity, legal, payment, and access records
carry that contour. `country_region_rules` lists countries that belong to the
**local** contour: market enablement, override policy, document set, and default
provider.

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

An `entrypoint_session` records product/bundle/catalog/paywall context and future
regional-resolution evidence. A `checkout_session` binds an authenticated user,
plan reference, amount/currency snapshot, consent readiness, and expiry.

An `order` is the authoritative internal commercial request. It contains the
user, region, checkout and entrypoint links, amount/currency, provider account,
merchant/provider identifiers, timestamps, and region-mismatch state.

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

Only verified provider state may set `paid`. `region_mismatch` blocks future
entitlement creation on this instance and is a Region Resolver redirect signal,
not a local rewrite onto another contour.

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

For the implemented `ru` one-stage CloudPayments charge, the expected terminal
transition is `created -> succeeded` or `created -> failed`. A late failure must
not downgrade an already successful payment or paid order. Other contours will
use the same payment states through their own adapters.

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

### Planned subscription and entitlement states

These values are normative for ANY-71 but are not implemented by ANY-108:

```text
subscription: trialing | active | past_due | canceled | expired | refunded | paused
entitlement: active | expired | revoked | superseded
```

## 5. Current payment lifecycle

```text
authenticated user
-> required active legal versions checked
-> missing acceptances recorded by the user
-> checkout session and order created
-> contour payment-provider checkout opened
-> webhook received, authenticity checked, payload redacted and persisted
-> payment/order updated idempotently
-> browser payment-result page polls informational state
```

The implemented `ru` adapter opens the CloudPayments widget and verifies
CloudPayments signatures. That is adapter behavior, not the domain lifecycle.

Contour confirmation through Region Resolver at login and registration is
planned and is not part of the current implemented flow.

The current legacy `product_access_states` record is not the target entitlement
model. ANY-108 must not expand it. ANY-71 will replace it with subscriptions and
entitlements without requiring Platform Kernel to understand payment lifecycle.

## 6. Planned ANY-71 model

### Catalog and pricing

- `products` owns stable tenant product codes and Platform Kernel product IDs.
- `bundles` plus `bundle_products` own explicit bundle membership.
- `plans` owns versioned scope, region, price, currency, period, renewal mode,
  trial days, validity interval, and status.
- `plan_price_components` records source plan prices and discount calculation for
  bundle/all-access plans.
- `plan_limits` records metric, limit, period, reset, and overage policy.

Initial product codes remain `document-summary` and `prompt-optimizer`. The
implemented `ru` catalog stores prices in minor RUB units and snapshots them at
order creation. Money in the model is always integer minor units plus an ISO
4217 code; it is not RUB-only.

### Subscriptions and entitlements

`subscriptions` will own trial and paid periods, renewal mode, cancellation, and
provider subscription identifiers. `entitlements` will be explicit grants with
scope, validity, source, order, and subscription links. Platform Kernel will read
entitlements through the future Payment Portal access API and will continue to
own actual usage counters.

Direct product, containing bundle, and all-access grants are the three allowed
ways for a product access check to succeed.

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

The interface is planned context only in this repository. Implementation belongs
to ANY-71 on the Payment Portal side and the separate Platform Kernel repository
on the consumer side.

## 8. Migration and seed rules

- The corrected initial migration defines the schema baseline.
- After it is frozen, use forward Alembic revisions.
- Do not use PostgreSQL enums for evolving provider/domain statuses.
- Use JSONB for redacted provider payloads and INET for IP data.
- Do not add `updated_at` to append-only acceptance, subscription-event, or
  webhook-inbox records.
- Never place secrets in migrations, seed data, or database configuration rows.
- Versioned legal source and its generated manifest must match the first-install
  seed exactly.

## 9. Unresolved product decisions owned by ANY-71

- Retention for raw webhook payloads, IP, user agent, and acceptance evidence.
- Whether billing address or payer profile is required.
- Merchant of Record, assigned countries, and payment provider for `eu` and for
  `us`, plus whether either contour needs country-specific legal document sets.
  The seed `paddle` and `default_document_set` values for DE/ES are not those
  decisions.
- How the required customer country is declared, verified, and updated inside a
  multi-country contour. Resolver geo is only a routing suggestion; contour
  enablement must define the country used to select legal and provider rules.
- Initial bundle/all-access offering and numeric plan limits.
- Administrative price regeneration and provider reconciliation behavior.

These are not implementation decisions for ANY-108.
