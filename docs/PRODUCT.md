# Product Scope

Status: authoritative
Last verified: 2026-09-24

Payment Portal is the identity, legal-consent, checkout, and access-entry
service for AnytoolAI products, deployed as one contour per production
instance. The target contour set is `ru`, `eu`, and `us`; only `ru` is an
implemented product surface.

The current `ru` surface presents Document Summary and Prompt Optimizer,
supports account/session/password-recovery and legal-acceptance flows, and
shows checkout, subscriptions, and payment as unavailable. Payment Portal is
under development and is not running as a production billing service. There
are no production direct-provider subscribers or subscriptions to migrate.

The former CloudPayments/direct-provider implementation and Portal-owned
catalog/order/payment/subscription/entitlement runtime have been physically
removed. The clean database contains provider-neutral target persistence but
no application behavior currently populates it. The sole long-term production
target is external-billing-managed.

Contour architecture is defined in [contours](architecture/contours.md).
Target billing ownership and authoritative facts follow, in precedence order,
[ADR 0005](architecture/decisions/0005-external-billing-boundary.md), the
accepted [External Billing Boundary Design](superpowers/specs/2026-09-15-external-billing-boundary-design.md),
and the accepted
[Portal <-> Kernel Access Contract Design](superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md).
The [Billing Authority and Consistency](architecture/billing-authority.md)
document is historical/superseded only; it is neither current-state nor target
authority. Implemented `ru` screens are defined in the
[RU MVP journey](product/ru-mvp.md).

## Implemented

- `ru` landing, presentational product snapshot, account/authentication,
  unavailable checkout/payment-result, and legal pages.
- Password-based demo registration, sessions, logout, and email password reset.
  Region Resolver confirmation is not implemented.
- Versioned `ru` legal-document metadata and append-only acceptance evidence.
- One clean PostgreSQL first-install schema with configured-contour and legal
  bootstrap.
- Ten retained identity/session/legal tables and fifteen empty,
  provider-neutral target external-billing persistence tables.
- Static guards preventing restoration of the deleted direct-provider runtime,
  legacy Portal commercial/access schema, and `external_billing_accounts`.

## Planned

- Login/registration contour confirmation through Region Resolver.
- Isolated `eu` and `us` deployments, legal trees, operators, and selected
  external-billing integrations. Those are not implemented product surfaces.
- Capability/catalog import, mapping publication, purchase/customer/create
  orchestration, Widget integration, webhook/reconciliation/recovery workers,
  paid-access derivation, and invalidation delivery in their owning
  `ANY-504` steps.
- Portal <-> Kernel paid-access and quota integration under the accepted wire
  contract. Workflow execution, artifacts, usage and quota enforcement remain
  in the separate Platform Kernel repository.

## Product invariants

- A production instance serves one contour and does not know another contour's
  customers, users, legal records, or base URLs.
- Checkout stays unavailable until the approved external-billing runtime and
  its Phase 0 gates are complete.
- A browser return, Widget callback, webhook receipt, outbound request success,
  payment state, or operator input alone never activates paid access.
- Paid access may advance only from verified authoritative facts and the
  accepted provider-neutral derivation rules.
- This service never collects or stores card data. The responsible external
  payment boundary handles it.
- Legal drafts are not represented as counsel-approved documents.
- The web's two product identifiers are presentational current UI identifiers,
  not a Portal-owned commercial catalog. Target technical product/metric
  identity comes from Platform Kernel; commercial offers come from External
  Billing.
