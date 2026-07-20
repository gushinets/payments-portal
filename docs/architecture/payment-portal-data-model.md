# Payment Portal Data Model and Backend Invariants

Status: normative source of truth
Version: 0.3
Last verified against code: 2026-07-11
Implementation expansion owner: Linear ANY-71

This document is the primary source of truth for Payment Portal data ownership,
state transitions, persistence rules, and the boundary with Platform Kernel.
The generated schema documents what exists in code; this document explains what
that schema means and distinguishes current implementation from planned work.

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
- RU and future EU accounts are regionally independent; identity is
  `tenant_id + region + user_id`.
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
| `magic_link_tokens` | Implemented schema | Future passwordless token storage |
| `payment_provider_accounts` | Implemented | Non-secret regional provider configuration |
| `entrypoint_sessions` | Implemented schema | Product/paywall entry context |
| `checkout_sessions` | Implemented | Checkout preparation state |
| `orders` | Implemented | Internal commercial order |
| `order_items` | Implemented | Immutable commercial snapshot |
| `payments` | Implemented | Payment attempts and outcomes |
| `refunds` | Implemented | Full and partial refund records |
| `payment_webhook_events` | Implemented | Redacted webhook inbox and processing audit |
| `product_access_states` | Legacy temporary | Current simplified product payment/access view |
| `products` | Planned under ANY-71 | Billing-visible product catalog |
| `bundles` | Planned under ANY-71 | Sellable product groups |
| `bundle_products` | Planned under ANY-71 | Version-aware bundle membership |
| `plans` | Planned under ANY-71 | Versioned sellable prices and periods |
| `plan_price_components` | Planned under ANY-71 | Bundle/all-access price calculation snapshot |
| `plan_limits` | Planned under ANY-71 | Purchased usage limits |
| `subscriptions` | Planned under ANY-71 | Trial/manual/automatic access lifecycle |
| `entitlements` | Planned under ANY-71 | Explicit runtime-readable access grants |
| `subscription_events` | Planned under ANY-71 | Append-only subscription audit |
| Fiscal receipt tables | Deferred | Add only with fiscal provider requirements |
| Coupons, wallet, ledger | Deferred | Not required for RU MVP |
| Provider reconciliation runs | Deferred | Add when operational volume requires it |

Exact implemented columns and indexes are generated in
[`docs/generated/db-schema.md`](../generated/db-schema.md). Any implemented ORM
table missing from the table above is a documentation-check failure.

## 3. Current implemented model

### Regional configuration

`regions.code` is the regional key. Region-aware identity, legal, payment, and
access records carry a region. `country_region_rules` controls market enablement,
override policy, document set, and default provider. The current product remains
RU-only even though the schema has future-region vocabulary.

### Identity

`users` uses UUID primary keys and requires:

```text
unique(tenant_id, region, email_normalized)
```

Raw session tokens are returned to the client once and stored only as SHA-256
hashes in `auth_sessions`. Sessions have expiry and revocation timestamps.
`magic_link_tokens` follows the same hash-only rule when passwordless login is
implemented.

### Legal

`document_versions` identifies a legal document by:

```text
tenant_id + region + doc_type + version
```

Only one version per `tenant_id + region + doc_type` may be active. Its
`content_hash` is the SHA-256 hash of the canonical normalized Markdown body.

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
entitlement creation.

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

For a one-stage CloudPayments charge, the expected terminal transition is
`created -> succeeded` or `created -> failed`. A late failure must not downgrade
an already successful payment or paid order.

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
-> CloudPayments widget opened
-> webhook received, signature checked, payload redacted and persisted
-> payment/order updated idempotently
-> browser payment-result page polls informational state
```

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

Initial product codes remain `document-summary` and `prompt-optimizer`. Prices
are stored in minor RUB units and snapshotted at order creation.

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
- Future EU Merchant of Record choice and market enablement.
- Initial bundle/all-access offering and numeric plan limits.
- Administrative price regeneration and provider reconciliation behavior.

These are not implementation decisions for ANY-108.
