# RU AnyToolAI Portal — As-Built 4F Handoff

Status: authoritative implemented-product specification and deferred-step handoff
Last updated: 2026-10-27

The surface established by ANY-636 4F is a product-centric AnyToolAI Portal:
public product-first home, catalog/discovery, per-product pages,
presentation-only pricing navigation, direct account/auth entry, and an
authenticated cabinet whose primary content is one card per current product.
Identity facts are compact supporting content. The repository remains
pre-production. ANY-709 Step 2 adds optional FIO and explicit verified-email
account-only Widget viewing with one durable customer, pending human validation.
No offer/subscription is needed to view that account. ANY-709 Steps 3–4 implement
accepted purchases, request-driven preparation/recovery and localized
Buy/Continue/Manage/payment Widget in the existing detail/cabinet slots. Step 4
targeted component/boundary/desktop/mobile synthetic tests PASS. Final real purchase/
payment QA remains pending; billing workers, paid access and usage/quota are deferred.
ANY-664 Step 6 now supplies published products and approved immutable commercial
terms through the Portal catalog API. Home, catalog, product detail and the
cabinet use Kernel `product_id`. ANY-709 listing discovers enabled Kernel products;
selected details/review read current LBX offers. PostgreSQL retains immutable
links and accepted history. Genuine conformance and production
enablement remain gated. Each published account product retains independent
unknown-access and unavailable-usage states for Steps 9–10; public pages omit
these account-only statuses. Published terms do not grant access or promise
current sellability.

This handoff preserves the completed ANY-636 implementation through Step 13,
with current catalog routes and Step 6 sources updated below. The former static
`document-summary` and `prompt-optimizer` presentation is historical 4F context,
not the current catalog identity or product source.
All thirteen steps are marked `done`, and the plan was moved to `completed` on
2026-10-08 at the user's explicit instruction. The completion record preserves
the historical verification evidence and the scope of the archival checks.
**Implementation completed; final acceptance pending.** Plan archival does not
confirm the final CI gate or human product/visual acceptance. Linear ANY-636
remains In Review, and merge requires both gates to be recorded explicitly.

Only the `ru` contour is implemented. Ordinary UI routes support `en`, `fr`,
`it`, `de`, `es`, `ru`, and `pt`, with `ru` as the default locale. All use the
same contour and data plane; `/en` is a locale, not another contour. Canonical
legal content remains Russian and RU-only. Multi-contour architecture is
defined in [contours](../architecture/contours.md). Login/registration contour
confirmation through the separate Region Resolver remains planned.

## Current routes

| Route | Implemented purpose |
| --- | --- |
| `/[locale]` | Product-first home with account entry, collection and current-product discovery |
| `/[locale]/products` | Enabled Kernel products through the Portal catalog API |
| `/[locale]/products/[product_id]` | Current LBX offer plus independent authenticated review/Buy/Continue/Manage |
| `/[locale]/pricing` | Localized presentation-only not-ready state and home/products navigation |
| `/[locale]/account` | Direct sign-in/registration entry and product-centric authenticated cabinet |
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

## Historical 4F composition and visual authority

The two-product presentation below records the ANY-636 handoff. ANY-664 replaces
its static catalog/detail content with published products and immutable terms
from the Portal API; the Bundle 3 visual authority and cabinet slots remain.

The approved ANY-539 RU Portal mockup was supplied and directly inspected as a
local input-only product/visual reference for the corrected 4F surface and its
final human comparison. It defines product hierarchy,
composition, density, palette direction, typography, surface treatment and
dashboard/card feel. It is not repository, commercial, runtime or legal
authority.

The evolved [Bundle 3](../design-system/bundle3/README.md) is the single
canonical implementation encoding of that target. ANY-636 Step 10 superseded
the previous mandatory purple/indigo glass+bento appearance with deep navy,
opaque flat dark-blue panels, thin blue borders, amber actions, compact radii
and spacing, and Plus Jakarta Sans. Step 11 applied that language across the
active Portal, including font loading through `next/font/google`. The subsequent
ANY-636 Cyrillic coverage correction uses Manrope for headlines and body text
across all seven locales because Plus Jakarta Sans lacks basic Cyrillic
U+0400–U+045F. Canonical tokens remain in
`docs/design-system/bundle3/tokens.json`; generated CSS and
shared rules remain the implementation authority, without a parallel theme or
the mockup's remote CSS import.

- Home leads with customer product value, account entry and discovery of the
  two current tools. The collection and product cards replace the earlier
  readiness/system-fact composition.
- Catalog cards show product name, type, tagline and description, with a
  neutral detail action. Product type is presentation metadata, not proof of
  runtime availability.
- Each detail screen has a two-column hero and labeled schematic illustration,
  three product-specific supporting blocks, account/catalog navigation, and
  commercial/access/usage readiness slots. The illustration is explicitly not
  a working extension interface. No install, web-app or execution destination
  is fabricated.
- Pricing is localized public navigation and an honest not-ready page with
  localized metadata and safe home/products links. Its feature makes no API
  calls and displays no offers, prices, tariff names, billing periods,
  sellability, subscription/provider state or purchase controls.
- The authenticated cabinet places compact email/verification/logout context
  in a supporting rail and both product cards in the primary workspace. Each
  card has commercial, access and usage/quota slots plus an action area whose
  current action opens the local product detail page. Responsive layouts stack
  the supporting context, cards and product-detail content on narrow screens.

Mockup demo prices (`0/490/990 ₽`), providers such as CloudPayments, plan and
subscription values, renewal/payment controls, usage (`320/500`, `3/10`),
metrics (`200k+`, ten products, two releases/month), availability labels and
roadmap products are excluded from authority. Proposal Checker, Scope Guard,
waitlists and a fictional next product are not current Portal products.
Unsupported privacy, data-residency, legal-approval, performance and language
claims (including the demo's 52-language claim) are not imported. Canonical RU
legal source and existing operator details retain their own authority; legal
documents remain drafts.

## Primary journey and account states

1. The user opens the product-first home or catalog. Product cards open a local
   product detail page. The home account CTA and signed-out product purchase
   entry open `/[locale]/account`; authenticated product pages show purchase and
   account-billing controls, with account navigation retained in the header.
   Public Pricing navigation opens only the presentation placeholder.
2. A signed-out user signs in or registers directly on `/[locale]/account`
   through the existing `AuthForm`. The header sign-in modal remains available.
3. Registration requires explicit, initially unchecked personal-data and offer
   confirmations using generated canonical RU acceptance text and legal links.
4. The authenticated cabinet leads with published product cards and their
   per-product state/action slots. Supporting account context renders the
   returned email and `email_verified` fact, offers verification/resend when
   needed, and provides logout.
5. A user can request a password-reset email, replace the password through the
   existing reset flow, and complete authenticated email verification.
6. Each enabled, linked product shows current source-backed commercial terms.
   ANY-709 adds explicit review/consent, Buy/Continue/Manage and verified payment
   Widget opening; accepted terms and purchase history remain immutable in
   PostgreSQL. Account access is unverified and usage/quota data is unavailable.
   No product-execution URL, plan badge or usage progress is invented.

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
| Product discovery and detail content | Portal catalog API and generated contracts over approved immutable mappings; Kernel owns `product_id` | ANY-664 replaces historical static 4F discovery; locale catalogs own surrounding UI copy |
| Technical capability manifest and commercial catalog, tariffs, prices, periods, sellability | Kernel owns technical identity/capabilities; External Billing owns commercial truth; Portal stores immutable approved bindings/terms | ANY-664 delivered historical v1 source reads/publication. ANY-709 Step 1 adds direct links, enabled-product discovery and live selected offers; genuine Kernel enablement remains gated; ANY-709 now supplies purchase admission |
| Purchase/payment Widget entry | External Billing with Portal orchestration and generated Step 3 contracts | ANY-709 Step 4 implements Buy/Continue/Manage, review/consent and verified payment presentation; targeted synthetic tests PASS; final real acceptance NOT_RUN |
| Subscription/billing state | Step 3 prepared-subscription proof, held intent and original accepted history | Preparation is not payment verification; local GETs show saved state only; operating observations remain Step 8 |
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
Historical 4F changed no backend behavior, persistence, migrations, or
contracts. ANY-664 adds the Step 6 producer for immutable mapping revisions;
ANY-709 adds purchase UI/preparation. Operating reconciliation, access and usage
remain later-step work. See the [single billing runbook](../engineering/ANY-709-billing-runbook.md).

### Stable integration surfaces for parent ANY-504 Steps 6–10

Later parent steps populate the existing Portal/product/cabinet slots rather
than redesign the main shell, catalog, product pages or cabinet. The slots are
frontend-local view composition, not new wire DTOs, domain entities or stored
business facts. Their owning steps must supply authoritative data/actions:

1. **Step 6 — commercial facts:** ANY-664 implements live source validation,
   restricted immutable mapping publication and DB-only catalog browsing.
   Current routes use mapped Kernel `product_id`; commercial terms include
   duration and anchor. Genuine conformance/enablement remain gated. Pricing
   remains a placeholder; commercial truth stays with External Billing.
2. **Step 7 — purchase/Widget:** populate the existing per-product action areas
   and relevant offer presentation with approved purchase entry and Widget
   orchestration. ANY-709 implements these controls with original-intent
   recovery and customer-wide payment presentation. Step 6 facts alone do not
   implement purchase or confer paid access; real payment acceptance is pending.
3. **Step 8 — reconciliation/recovery:** populate relevant commercial/status
   slots and action feedback with authoritative reconciled state and recovery
   behavior. UI returns, callbacks, webhooks and outbound success are signals,
   not commercial or paid-access authority.
4. **Step 9 — paid access:** populate each product's access slot from the
   provider-neutral confirmed projection and its accepted authoritative-fact
   derivation/delivery rules. Authentication or email verification never
   substitutes for this source.
5. **Step 10 — usage/quota:** populate each product's usage/quota slot from
   actual Platform Kernel usage and remaining-quota facts. Kernel retains
   durable usage and quota enforcement; no guessed zero, allowance or progress
   value may fill a missing source.

Steps 7–10 and genuine Step 6 enablement remain deferred parent-program work.
Provider-dependent semantics and launch retain the Phase 0 gates. No step may
treat an unavailable source as “no subscription”, “no access”, a default/free
plan or `0/N` usage.

## Product presentation and API boundary

The former `document-summary` and `prompt-optimizer` slugs and
`productPresentation` belong to historical 4F, where they were presentation
identifiers only. Current product routes use Kernel `product_id` through the
Portal catalog API and approved immutable mapping. Technical identity comes
from Kernel; commercial offers come from External Billing.
No authoritative product-execution target exists in the current Portal, so
navigation stays on the local product/account surfaces.

ANY-636 required no new Portal HTTP API. Its authoritative server facts
were available through existing generated auth contracts and canonical legal
flows/assets, or frontend presentation metadata. ANY-664 adds generated Portal
catalog contracts; there is no handwritten frontend server-fact contract.

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

The final ANY-541 trust rule remains as built: successful same-service JSON is
read as `unknown` and trusted exactly once in the private
`decodeSuccessfulResponse<T>` in `shared/api/transport.ts`. Endpoint adapters
reuse `getJson<T>` / `postJson<T>` with generated TypeScript response types.
Pydantic/FastAPI owns runtime structural validation; generated TypeScript owns
compile-time wire shape. Malformed successful JSON syntax becomes
`ApiContractError`. There is no browser structural re-validation, Zod response
schema or feature-local JSON cast authority.

## Preserved legal, locale, and UI constraints

- Evolved Bundle 3 remains the design system for the public Portal and cabinet.
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

## Final verification and intent/DoD evidence

The first final-review question is: **does the system now look and behave like
the RU AnyToolAI Portal expected by ANY-539/ANY-504 4F, not merely pass technical
route/boundary checks?**

The manual verification commands and human acceptance checklist are retained
in the completed [ANY-636 Step 13](../exec-plans/completed/ANY-636-implementation-plan.md#step-13--correct-the-4f-handoff-re-run-final-review-and-close-any-636)
for traceability and future regression checks.
The ordinary Playwright configuration excludes `react-runtime.spec.ts`, even
when named in the focused route command. Also run the existing canonical
`npm run test:e2e:react-runtime` command to cover that required surface.

Existing acceptance coverage is owned by
[`public-routes.spec.ts`](../../apps/web/e2e/public-routes.spec.ts),
[`portal-ru.spec.ts`](../../apps/web/e2e/portal-ru.spec.ts) and the account/auth
component and focused auth/legal/locale/runtime suites. It covers product
composition, honest per-product states, retired routes, provider/removed-API
boundaries, keyboard focus, accessibility and mobile overflow. This describes
coverage, not a new passing test result.

The route suite writes full-page desktop/mobile screenshots under
`.harness/playwright-results`, including home, catalog, pricing, both product
pages and signed-out account. The Portal suite adds authenticated account
screenshots for verified/unverified email and the 390×844 discovery/auth
journey, with visual-review context naming the RU HTML reference. Account
screenshots use synthetic auth fixtures; they prove composition, not commercial
or paid-access facts. React runtime evidence uses the separate
`.harness/playwright-react-runtime-results` and report directories.

The original Step 13 documentation pass reviewed current source and existing
representative screenshots and aligned this documentation; that pass ran no
verification or formatting commands. The plan and all steps were subsequently
marked `done` at the user's instruction. See the completion record for checks
performed during archival; it does not assert new browser results or an
undocumented human screenshot comparison. For future visual regression review,
compare `/ru`, `/ru/products`, both product pages and
authenticated `/ru/account` with the input-only mockup; confirm the evolved
navy/amber/flat/compact language, honest facts and durable integration slots.

The subsequent 2026-10-08 final-review fix pass completed fresh local
verification: `npm run check:fast`, `RUN_E2E=true npm run check` (including 57
PostgreSQL and 122 browser tests), the separate React runtime suite (2 tests),
and the workflow evidence validator passed. The dated
[final-review record](../exec-plans/completed/ANY-636-implementation-plan.md#final-review-fixes-and-verification--2026-10-08)
contains exact commands, coverage, environment limitations and the human
checklist. The input-only HTML is removed from the local tracked contents and
preserved unchanged outside the repository; its deletion is not yet published.
**Final acceptance remains pending:** the required remote CI must pass on the
head containing these fixes, and the user must explicitly accept the
desktop/mobile product and visual result. Agent screenshot inspection and a
completed implementation plan do not provide that approval.
