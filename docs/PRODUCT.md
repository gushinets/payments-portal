# Product Scope

Status: authoritative
Last updated: 2026-10-22

AnyToolAI Portal combines public product discovery, direct account entry, and
identity/legal-consent flows for AnyToolAI products, deployed as one contour
per production instance. The target contour set is `ru`, `eu`, and `us`; only
`ru` is an implemented product surface. Ordinary UI supports `en`, `fr`, `it`,
`de`, `es`, `ru`, and `pt` route locales on that same data plane. Locale never
selects deployment or contour.

The current `ru` surface is product-centric: product-first home and discovery,
detail pages keyed by Kernel `product_id`, presentation-only pricing
navigation, direct auth entry, and an authenticated cabinet led by published
products. Identity/verification/logout context supports the per-product
commercial/access/usage/action slots. Account/session/email-verification,
password-recovery and legal-acceptance flows remain implemented. Published
immutable commercial terms are displayed; paid access remains unknown and
actual usage/quota unavailable. The repository remains pre-production and
provider-independent on the surface established by ANY-636 4F. ANY-664 adds
historical read-only source clients and controlled immutable offer publication.
ANY-709 Step 1 adds direct versioned links and source-backed catalog/current
offers; genuine
Kernel conformance and sales remain gated. There are no production direct-
provider subscribers or subscriptions to migrate.

The former CloudPayments/direct-provider implementation and Portal-owned
catalog/order/payment/subscription/entitlement runtime have been physically
removed. The clean database contains provider-neutral target persistence;
ANY-664 can append immutable mapping revisions. Purchase orchestration,
reconciliation and paid-access producers remain later work. The sole long-term
production target is external-billing-managed.

Contour architecture is defined in [contours](architecture/contours.md).
Target billing ownership and authoritative facts follow, in precedence order,
[ADR 0005](architecture/decisions/0005-external-billing-boundary.md), the
accepted [External Billing Boundary Design](superpowers/specs/2026-09-15-external-billing-boundary-design.md),
and the accepted
[Portal <-> Kernel Access Contract Design](superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md).
The [accepted live-source admission amendment](superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md)
narrowly supersedes source-catalog mirroring/new-sale TTL: publication and each
genuinely new purchase require current Kernel/LBX reads; approved immutable
history stays in PostgreSQL. ANY-709 Step 1 supersedes file approval and
DB-only public browsing with enabled-product discovery and current selected
offers; customer purchase consent remains immutable and is implemented later. Paid-access,
subscription trust/reconciliation and AccessSnapshot remain unchanged.
The [Billing Authority and Consistency](architecture/billing-authority.md)
document is historical/superseded only; it is neither current-state nor target
authority. Implemented `ru` screens are defined in the
[as-built RU Portal 4F handoff](product/ru-mvp.md), including the durable
UI/data-ownership matrix and deferred ANY-504 Steps 6–10.

External Billing owns commercial billing truth and lifecycle. The Portal owns
current identity/legal and the later anti-corruption, projection,
reconciliation, recovery, and paid-access delivery boundary. Platform Kernel
owns technical product/metric identity, actual usage, and quota enforcement.
The historically named “Payments Portal” component in the accepted ADR/design
records maps to this Portal backend boundary; the accepted amendment changes
only their source-read/admission strategy.

## Implemented

- Locale-prefixed product-first home, public catalog and detail pages at
  `/[locale]/products/[product_id]`, using Kernel identity and stored approved
  immutable offer mappings through the Portal catalog API. Browsing makes no
  live Kernel/LBX calls and does not promise current sellability.
- `/[locale]/pricing` and localized public Pricing navigation as presentation
  only: a not-ready state, localized metadata and safe home/products links,
  without commercial facts, purchase controls or API calls.
- `/[locale]/account` as the direct sign-in/registration entry and authenticated
  product-centric cabinet, with compact identity context and one card per
  published product, showing commercial terms and independent unknown-access
  and unavailable-usage states; the header retains its sign-in modal. These
  account-only states are absent from public catalog/detail pages and home.
- The approved RU mockup's product/visual direction encoded by evolved Bundle 3
  and applied across the active Portal: navy/amber, flat dark panels, thin
  borders, compact radii/spacing and Manrope (the ANY-636 basic Cyrillic coverage
  correction). Demo business, metrics,
  availability and legal/privacy claims remain excluded from authority.
- Password-based registration, sessions, logout, and the existing
  `/[locale]/forgot-password`, `/[locale]/reset-password`, and
  `/[locale]/verify-email` flows. Region Resolver confirmation is not implemented.
- Canonical RU legal pages and generated registration acceptance copy.
- Versioned `ru` legal-document metadata and append-only acceptance evidence.
- One clean PostgreSQL first-install schema with configured-contour and legal
  bootstrap.
- Ten retained identity/session/legal tables and fifteen provider-neutral target
  external-billing persistence tables, empty after bootstrap. Restricted
  publication appends mapping revisions; source-catalog projection slots are inert.
- Static guards preventing restoration of the deleted direct-provider runtime,
  legacy Portal commercial/access schema, and `external_billing_accounts`.

The transitional pre-production `/auth-checkout` and `/payment-result`
surfaces under each locale were removed without redirects or compatibility
routes because they have no production compatibility obligation. Future
production changes require their own compatibility decision.

ANY-636 required no new Portal HTTP API and used frontend product presentation
metadata. ANY-664 supplies current catalog facts through the Portal API and
generated contracts over approved immutable mappings; auth and legal sources
retain their ownership. Any future Portal-owned web-consumed API
must start with backend Pydantic models, named OpenAPI components, repository
generation, generated TypeScript wire contracts, and the shared API transport
trust boundary under ANY-541.

## Planned

- Login/registration contour confirmation through Region Resolver.
- Isolated `eu` and `us` deployments, legal trees, operators, and selected
  external-billing integrations. Those are not implemented product surfaces.
- Genuine enablement of ANY-504 Step 6's live-source clients and immutable
  approved offer mappings, subject to real Kernel/LBX and approval gates.
  ANY-664 implements the Portal path with simulated local evidence and DB-only
  catalog browsing; there is no periodic source-catalog mirror. Purchase/Widget in Step 7;
  reconciliation/recovery in Step 8; confirmed paid-access projection and
  delivery in Step 9; actual usage/quota integration in Step 10. These are
  deferred ownership boundaries, not implemented runtime. They populate the
  existing pricing/product/cabinet commercial, access, usage and action slots
  without redesigning the main cabinet. All thirteen ANY-636 steps are marked
  `done` in the [completed plan](exec-plans/completed/ANY-636-implementation-plan.md);
  the parent program's provider-dependent Phase 0 gates remain in force.
- Portal <-> Kernel integration under the accepted wire contract. Workflow
  execution, artifacts, actual usage, and quota enforcement remain in the
  separate Platform Kernel repository.

## Product invariants

- A production instance serves one contour and does not know another contour's
  customers, users, legal records, or base URLs.
- Checkout stays unavailable until the approved external-billing runtime and
  its Phase 0 gates are complete.
- UI “not ready/unknown” does not establish no subscription, no access, or zero
  usage/quota. Authentication and email verification do not establish paid access.
- A browser return, Widget callback, webhook receipt, outbound request success,
  payment state, or operator input alone never activates paid access.
- Paid access may advance only from verified authoritative facts and the
  accepted provider-neutral derivation rules.
- This service never collects or stores card data. The responsible external
  payment boundary handles it.
- Legal drafts are not represented as counsel-approved documents.
- `document-summary` and `prompt-optimizer` were frontend presentation/route
  slugs in historical 4F, not authoritative technical IDs. Current catalog
  routes use Kernel `product_id` through the Portal API and immutable mapping.
  Technical product/metric identity comes from Platform Kernel;
  commercial offers come from External Billing.
- Discovery CTAs open product detail or account surfaces. No purchase/checkout
  CTA or fabricated product-execution URL is exposed in 4F.
- Pricing navigation and its unavailable placeholder establish presentation
  topology only. Published offer terms use the ANY-504 Step 6 Portal path;
  current sellability and genuine enablement retain the source/approval gates;
  purchase/provider Widget behavior remains Step 7.
