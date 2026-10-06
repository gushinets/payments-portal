# RU AnyToolAI Portal — As-Built 4F Handoff

Status: authoritative implemented-product specification and deferred-step handoff
Last updated: 2026-10-06

ANY-636 4F brings public product discovery, direct account/auth entry, and the
account cabinet into this AnyToolAI Portal. The repository remains
pre-production and provider-independent. External Billing/provider runtime,
commercial catalog, purchase/Widget, confirmed paid-access projection, and
actual usage/quota integration are not implemented.

Only the `ru` contour is implemented. Ordinary UI routes support `en`, `fr`,
`it`, `de`, `es`, `ru`, and `pt`, with `ru` as the default locale. All use the
same contour and data plane; `/en` is a locale, not another contour. Canonical
legal content remains Russian and RU-only. Multi-contour architecture is
defined in [contours](../architecture/contours.md). Login/registration contour
confirmation through the separate Region Resolver remains planned.

## Current routes

| Route | Implemented purpose |
| --- | --- |
| `/[locale]` | Public landing and product discovery |
| `/[locale]/products` | Static product catalog presentation |
| `/[locale]/products/document-summary` | Document Summary presentation detail |
| `/[locale]/products/prompt-optimizer` | Prompt Optimizer presentation detail |
| `/[locale]/account` | Direct sign-in/registration entry and authenticated cabinet |
| `/[locale]/forgot-password` | Password-reset email request |
| `/[locale]/reset-password` | Password replacement from emailed reset link |
| `/[locale]/verify-email` | Authenticated email-verification flow |
| `/ru/privacy` | Personal-data policy |
| `/ru/consent-personal-data` | Personal-data consent |
| `/ru/offer` | Public offer |
| `/ru/cancellation` | Cancellation and refund terms |
| `/ru/cookies` | Cookie policy |
| `/ru/security` | Information security policy |

`/` is the existing Accept-Language negotiation entry; explicit locale-prefixed
URLs remain authoritative. Other unprefixed application paths are not
implicitly localized. Legal paths have no invented locale alternates.

The transitional pre-production `/{locale}/auth-checkout` and
`/{locale}/payment-result` surfaces were removed without redirects or
compatibility routes because there is no production compatibility obligation
for them. This is not a permanent rule for future production route changes.

## Primary journey and account states

1. The user opens the landing or catalog. Product cards open a local product
   detail page; home and product account CTAs open `/[locale]/account`.
2. A signed-out user signs in or registers directly on `/account` through the
   existing `AuthForm`. The header sign-in modal remains available.
3. Registration requires explicit, initially unchecked personal-data and offer
   confirmations using generated canonical RU acceptance text and legal links.
4. The authenticated cabinet renders the returned email and `email_verified`
   fact, offers verification/resend when needed, links to the two local product
   detail pages, and provides logout.
5. A user can request a password-reset email, replace the password through the
   existing reset flow, and complete authenticated email verification.
6. Billing, paid-access, and usage/quota panels show explicit unavailable or
   unknown states. No purchase/checkout CTA or product-execution URL is invented.

Account state is frontend component state: loading, signed out, session error
with retry, or authenticated. Missing or expired sessions lead to the direct
auth form; transient session failures offer retry. Authentication and email
verification facts do not establish paid access.

UI “not ready/unknown” is not evidence of no subscription, no access, or zero
usage/quota. The Portal cannot render guessed commercial values, access results,
usage, or remaining allowances. A browser return, Widget callback, webhook,
outbound success, or payment state alone never grants paid access.

## UI/data ownership and ANY-504 handoff

The target authority chain remains
[ADR 0005](../architecture/decisions/0005-external-billing-boundary.md), the
accepted [External Billing Boundary Design](../superpowers/specs/2026-09-15-external-billing-boundary-design.md),
and the accepted
[Portal ↔ Kernel Access Contract Design](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md),
in that order. Their historically named “Payments Portal” component corresponds
to this Portal backend boundary. Those accepted records retain their original
names and ownership decisions.

| UI/data concern | Authority and current source | 4F state / deferred handoff |
| --- | --- | --- |
| Email and authenticated identity | Portal; generated `SessionUserResponse` from `/api/auth/session` and auth responses | Render the returned facts now |
| Registration, sign-in, logout, verification, recovery | Portal; existing generated auth contracts and shared auth transport/forms | Reuse now; no billing/access inference |
| Legal pages, links, registration acceptance | Portal identity/legal boundary and canonical RU legal source; existing legal runtime and generated legal assets | Preserve now; legal documents remain drafts |
| Product discovery and detail content | Frontend presentation metadata and locale catalogs | Static presentation now; no commercial or technical identity authority |
| Technical capability manifest and commercial catalog, tariffs, prices, periods, sellability | Platform Kernel owns technical `product_id`, `metric_key`, and capability manifest; External Billing owns commercial catalog/offers/tariffs/prices/periods/sellability; no current runtime source | Unavailable; Portal projection and mapping of these authoritative sources deferred to ANY-504 Step 6 |
| Purchase/checkout/Widget entry | External Billing with Portal orchestration; no current runtime source | No purchase CTA or runtime; deferred to ANY-504 Step 7 |
| Subscription/billing state | External Billing; no current authoritative source | Unknown/unavailable; deferred to ANY-504 Steps 6–8 |
| Provider reconciliation/recovery | Portal boundary over authoritative External Billing facts; no current runtime source | Deferred to ANY-504 Step 8 |
| Confirmed paid-access state and delivery | Portal provider-neutral projection from authoritative facts; no current runtime source | Unknown/not ready; deferred to ANY-504 Step 9 |
| Actual usage and remaining quota | Platform Kernel; no current runtime source | Unavailable; integration deferred to ANY-504 Step 10 |

The Portal owns identity/legal now and the later anti-corruption, projection,
reconciliation, recovery, and paid-access delivery boundary. External Billing
owns commercial truth and lifecycle. Platform Kernel owns technical product and
metric identity, durable actual usage, and quota enforcement. Workflow
execution and artifacts also remain outside this repository.

Provider-dependent LBX semantics, Widget behavior, paid-access derivation, and
launch remain gated on Phase 0 PASS under ANY-504, with evidence owned by
ANY-634. This handoff adds no provider semantics or later-step implementation.
The existing target persistence baseline remains empty without producer
runtime; 4F changes no backend behavior, persistence, migrations, or contracts.

## Product presentation and API boundary

The two slugs `document-summary` and `prompt-optimizer` in frontend
`productPresentation` are presentation/route identifiers only. They are not
claimed Platform Kernel `product_id` values or External Billing IDs. Technical
identity comes from Kernel; commercial offers come from External Billing.
No authoritative product-execution target exists in the current Portal, so
navigation stays on the local product/account surfaces.

ANY-636 required no new Portal HTTP API. The facts it may authoritatively render
are available through existing generated auth contracts and canonical legal
flows/assets, or are frontend presentation metadata. There is no new
handwritten frontend server-fact contract.

Every future Portal-owned web-consumed API follows ANY-541:

```text
backend Pydantic request/response models
  → durable named OpenAPI components
  → repository generation
  → generated TypeScript wire contracts
  → shared API transport trust boundary
  → endpoint adapters
  → feature/UI and local view state
```

Generated contracts do not transfer External Billing or Kernel data ownership
to the Portal. Missing authoritative backend facts cannot be replaced with
frontend DTOs, mock billing data, or guessed business states.

## Preserved legal, locale, and UI constraints

- Bundle 3 remains the design system for the public Portal and cabinet.
- Ordinary UI copy retains exact seven-locale key and ICU-signature parity;
  canonical RU legal titles, bodies, versions, paths, and acceptance text stay
  source-owned.
- Legal links and operator details remain in the footer. Required registration
  acceptances are never preselected, and legal pages remain drafts rather than
  counsel-approved documents.
- Reset and verification fragment tokens remain in their current client-only
  flows, are removed from the address bar, and are not persisted or logged.
  Locale navigation does not carry those tokens.
- No provider I/O, card collection, or Portal-owned commercial/access/trial
  runtime is introduced. Payment-method configuration remains empty.
- Manual acceptance covers the focused final route, auth/legal, locale,
  mobile/accessibility, generated-contract, lint/type, and build surfaces listed
  in [ANY-636 Step 5](../exec-plans/active/ANY-636-implementation-plan.md).
