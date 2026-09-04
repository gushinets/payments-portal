# Product Scope

Status: authoritative
Last verified: 2026-09-04

Payment Portal is the identity, legal-consent, checkout, and access-entry
service for AnytoolAI products, deployed as one **contour** (compliance zone)
per production instance. Planned contours are `ru`, `eu`, and `us`.

The implemented product surface is the `ru` contour for Document Summary and
Prompt Optimizer. Payment Portal is still under development and is not running
as a production billing service. CloudPayments exists in the current code as a
transitional Portal-managed direct-provider capability retained under ANY-407;
there are no production CloudPayments subscribers or subscriptions to migrate.
The product will most likely launch with an external billing system.

Contour architecture is defined in [contours](architecture/contours.md).
Billing ownership and authoritative facts are defined in
[billing authority](architecture/billing-authority.md).
Implemented `ru` screens are defined in [RU MVP journey](product/ru-mvp.md).

## Implemented

- `ru` landing, product catalog, account, checkout, payment-result, and legal
  pages.
- Password-based demo registration, sessions, and email password reset. The
  form does not yet confirm contour with Region Resolver.
- Versioned `ru` legal-document metadata and append-only acceptance records.
- Checkout sessions, orders, order items, payment attempts, refunds, and a
  CloudPayments webhook inbox.
- CloudPayments signature checking, payload redaction, and idempotent processing.
- PostgreSQL first-install schema and legal metadata seed.

## Planned

- Login and registration confirm the contour using the Region Resolver list of
  deployed contours, then stay on this instance or leave through the resolver.
- Isolated `eu` and `us` deployments, legal trees, operators, catalogs, and
  billing integrations selected for each contour. Those markets are not
  implemented product surface; the active billing model and integration for
  those deployed products are not selected here.
- Catalog, plans, subscriptions, entitlements, and the Payment Portal access API
  are tracked by Linear ANY-71 and its subtickets.
- Workflow execution, scenario runtime, artifacts, and usage accounting belong to
  the separate Platform Kernel repository.

## Product invariants

- A production instance serves one contour and does not know other contours'
  customers or base URLs.
- A browser return URL never confirms payment or activates access.
- Paid access advances only from verified authoritative billing facts. The
  current transitional CloudPayments implementation accepts those facts
  through verified webhooks.
- This service never collects or stores card data. Card data is handled by the
  responsible external payment boundary; the transitional direct-provider
  implementation delegates it to CloudPayments.
- Legal drafts are not represented as counsel-approved documents.
- Product and plan identifiers must remain stable across web, payment metadata,
  and future Platform Kernel integration.
