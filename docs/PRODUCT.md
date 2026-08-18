# Product Scope

Status: authoritative
Last verified: 2026-08-18

Payment Portal is the identity, legal-consent, checkout, and access-entry
service for AnytoolAI products, deployed as one **contour** (compliance zone)
per production instance. Planned contours are `ru`, `eu`, and `us`.

The current release is the `ru` contour for Document Summary and Prompt
Optimizer, with CloudPayments as the `ru` adapter.

Contour architecture is defined in [contours](architecture/contours.md).
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
  provider adapters. Those markets are not implemented product surface.
- Catalog, plans, subscriptions, entitlements, and the Payment Portal access API
  are tracked by Linear ANY-71 and its subtickets.
- Workflow execution, scenario runtime, artifacts, and usage accounting belong to
  the separate Platform Kernel repository.

## Product invariants

- A production instance serves one contour and does not know other contours'
  customers or base URLs.
- A browser return URL never confirms payment or activates access.
- Only verified provider webhooks may advance payment state.
- This service never collects or stores card data. Card data is handled by the
  contour's payment provider.
- Legal drafts are not represented as counsel-approved documents.
- Product and plan identifiers must remain stable across web, payment metadata,
  and future Platform Kernel integration.
