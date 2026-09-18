# Product Scope

Status: authoritative
Last verified: 2026-09-18

Payment Portal is the identity, legal-consent, checkout, and access-entry
service for AnytoolAI products, deployed as one **contour** (compliance zone)
per production instance. The target contour set is `ru`, `eu`, and `us`; `ru`
is implemented, while `eu` and `us` remain planned.

The implemented product surface is the `ru` contour for Document Summary and
Prompt Optimizer. Payment Portal is still under development and is not running
as a production billing service. CloudPayments implementation and persistence
source is retained under ANY-407 for later evidence-based cleanup, but normal
backend and frontend runtime no longer initializes, registers, loads, or invokes
it. Checkout is temporarily unavailable until a separately selected and
implemented billing integration exists. There are no production CloudPayments
subscribers or subscriptions to migrate. The sole long-term production target
is an external-billing-managed flow.

Contour architecture is defined in [contours](architecture/contours.md).
Target billing ownership and authoritative facts follow, in precedence order,
[ADR 0005](architecture/decisions/0005-external-billing-boundary.md), the
accepted [External Billing Boundary Design](superpowers/specs/2026-09-15-external-billing-boundary-design.md),
and the accepted [Portal ↔ Kernel Access Contract Design](superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md).
The retained [Billing Authority and Consistency](architecture/billing-authority.md)
document is current-state and historical context, not target authority.
Implemented `ru` screens are defined in [RU MVP journey](product/ru-mvp.md).

## Implemented

- `ru` landing, product catalog, account, checkout, payment-result, and legal
  pages.
- Password-based demo registration, sessions, and email password reset. The
  form does not yet confirm contour with Region Resolver.
- Versioned `ru` legal-document metadata and append-only acceptance records.
- Checkout sessions, orders, order items, payment attempts, refunds, and the
  retained provider-oriented persistence schema.
- Catalog products, plans, bundles, and limits implemented under ANY-77.
- Local subscriptions, entitlement rules, entitlements, and subscription audit
  implemented under ANY-78.
- PostgreSQL first-install schema and legal metadata seed.

## Planned

- Login and registration confirm the contour using the Region Resolver list of
  deployed contours, then stay on this instance or leave through the resolver.
- Isolated `eu` and `us` deployments, legal trees, operators, catalogs, and
  external-billing integrations selected for each contour. Those markets are
  not implemented product surface; the concrete external-billing integration
  for those deployed products is not selected here.
- The old private entitlement contract planned under ANY-79 is superseded for
  target development. Future paid-access and quota integration follows the
  accepted Portal ↔ Kernel Access Contract Design and the `ANY-504` sequence.
- Workflow execution, scenario runtime, artifacts, and usage accounting belong to
  the separate Platform Kernel repository.

## Product invariants

- A production instance serves one contour and does not know other contours'
  customers or base URLs.
- A browser return URL never confirms payment or activates access.
- Paid access advances only from verified authoritative billing facts. Normal
  runtime has no active CloudPayments fact path. For any future external
  billing integration, authentication alone is not semantic authority:
  integration policy decides whether the external fact is sufficient or must
  trigger point reconciliation, and both fact sources feed the same local
  transition path.
- This service never collects or stores card data. Card data is handled by the
  responsible external payment boundary.
- Checkout remains deliberately unavailable until a billing integration is
  selected and implemented for normal runtime.
- Legal drafts are not represented as counsel-approved documents.
- Retained Portal product and plan identifiers remain stable where the current
  web, persistence, and provider metadata use them. They are not future
  commercial or paid-access authority: target technical product and metric
  identity comes from Platform Kernel through the accepted designs.
