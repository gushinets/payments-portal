# ANY-636 — Evolve Payments Portal into the RU AnyToolAI Portal

## Plan Overview

| Field | Value |
| --- | --- |
| Parent program | `ANY-504 — External Billing & Paid Access` |
| Ticket | `ANY-636 — 4F. Evolve Payments Portal into the RU AnyToolAI Portal` |
| Direct predecessor / required code baseline | `ANY-541`, PR `#129`, branch `ANY-541` |
| Original planning baseline | `3e53f1cc7756cc6825b05b4fcbd580479a196a64` — historical ANY-541 baseline used by initial ANY-636 Steps 1–5 |
| Required predecessor baseline for continuation | final/current `ANY-541` / PR `#129`; planning observation: `bc80eaaee3b0c6051548ff446960791636216436` |
| Observed ANY-636 head before correction | `af0ea815cf12d2440bdad6a36d8dbf396e5d9950`; branch was `behind 2 / ahead 6` versus `ANY-541` |
| Overall status | `in progress` — current repository includes completed Steps 1–12; Step 13 documentation/handoff prepared, complete final verification and human screenshot/intent acceptance pending |
| Initial Steps 1–5 completed | `2026-10-06`; historical initial handoff, superseded by the corrected product-centric surface; final Step 13 acceptance pending |
| Execution order | Preserve the current repository baseline and completed Steps 1–12 → Step 13 final verification and human acceptance → close ANY-636; do not re-execute predecessor synchronization or earlier steps |
| Steps / commits | 5 completed baseline steps + 1 predecessor-synchronization step + 7 product/visual completion steps |
| Blocks | `ANY-634 — Step 5. LBX Phase 0 provider research` |
| Backend/API/schema work expected | No new backend API or schema. Step 6 does update inherited frontend generated-contract/transport mechanics to match final ANY-541; later API/schema work remains out of 4F unless a material contradiction forces replanning |

## Initial Completion Evidence — superseded as final 4F completion

> **Correction:** Steps 1–5 established the provider-independent route/auth/product foundation, but two later facts prevent them from being the final 4F baseline: (1) the RU mockup was unavailable and product/visual DoD was therefore incomplete; (2) ANY-541 / PR #129 subsequently replaced the generated-Zod/browser-runtime-validation design with generated TypeScript wire contracts plus one shared transport trust boundary. ANY-636 was still based on the older `3e53f1c` predecessor state. The ticket therefore remains open until Step 6 synchronizes the final ANY-541 architecture and Steps 7–13 complete the RU product/visual DoD. The corrective sequence now includes an explicit Bundle 3 visual-authority recalibration before applying the approved mockup styling, because the earlier mandatory indigo glass/bento rules materially conflicted with the target RU visual language.

All five initial implementation steps are complete on branch `ANY-636`, based on
`3e53f1cc7756cc6825b05b4fcbd580479a196a64`. The implementation history contains
one commit per step:

- Step 1: `3cfddc1` — public product discovery and product-detail routes.
- Step 2: `d6f7e46` — direct authentication on `/account`; retired `/auth-checkout`.
- Step 3: `46a30c5` — honest account cabinet states; retired `/payment-result`.
- Step 4: `a8fbe72` — focused route, state, boundary, mobile, and accessibility coverage.
- Step 5: `7c1fded` — current-authority docs and durable future-step handoff,
  including the reviewed Kernel capability / External Billing commercial /
  Portal projection-mapping distinction.

The completion review inspected the current route inventory, account/product
implementation, focused test coverage, current handoff, and baseline-to-HEAD
file inventory. Changes are confined to web presentation, web tests, and
documentation; backend, API contracts, generated artifacts, and schema are
unchanged.

Existing local browser evidence was inspected without rerunning checks:

- `.harness/playwright-report/results.json`, updated on 2026-10-06 at 14:53
  (UTC+08:00), records 116 passing tests across the seven focused non-runtime
  suites, with no failures, skipped tests, flaky tests, or global errors.
- `.harness/playwright-react-runtime-report/results.json`, updated at 14:01
  that day, records two passing runtime tests with no failures. This report
  predates the Step 4 commit and is not evidence of a fresh run of its final
  runtime coverage.

No formatting or automated verification was run during this completion review.
Saved results for documentation, architecture, generation, web boundaries,
components, typecheck, lint, build, and the fast repository gate were not
available in the inspected artifacts; their outcomes are not asserted here.
The original manual-verification commands remain below for use as required.

## Architecture Correction After Final ANY-541 / PR #129

The initial ANY-636 implementation was created from `ANY-541` commit
`3e53f1cc7756cc6825b05b4fcbd580479a196a64`. PR #129 later changed the inherited
frontend HTTP contract architecture in two follow-up commits, including
`b081cd3be03db48730385cbb2031afa05c398473` and
`bc80eaaee3b0c6051548ff446960791636216436`.

The final inherited contract is now:

```text
FastAPI / Pydantic
  → app.openapi()
  → OpenAPI
  → generated TypeScript wire contracts
  → shared API transport trust boundary
  → endpoint adapters
  → frontend consumers / view state
```

Locked semantics:

- Pydantic/FastAPI is the only runtime request/response validation authority.
- Successful same-service JSON is read as `unknown` and trusted exactly once in
  `apps/web/src/shared/api/transport.ts`.
- The private transport assertion is a deliberate trust decision, **not**
  browser structural runtime validation.
- Endpoint adapters consume generated TypeScript response/request contracts and
  reuse shared `getJson<T>` / `postJson<T>` transport helpers.
- Syntactically invalid successful JSON still becomes `ApiContractError`.
- Structurally unexpected but syntactically valid successful JSON is not passed
  through a second browser schema validator.
- Handwritten backend wire DTOs, handwritten structural response decoders,
  generated Zod response schemas, or any second runtime schema authority are
  forbidden for this boundary.
- `npm run generate:check` remains the generated-contract freshness authority.
- Frontend forms, product presentation models, UI/view state and the per-product
  composition introduced later in this plan remain frontend-owned.

Any historical Steps 1–5 wording below that refers to generated Zod runtime
validation or frontend structural response validation is superseded by this
section and by Step 6. Do not use that historical 4D mechanism for new work.

## How to Use This File

### Current use — Step 6 architecture sync, then corrective Steps 7–13

1. Continue from the existing `ANY-636` branch containing completed initial Steps 1–5; do not reset or discard those commits. Step 6 must first merge the current/final `ANY-541` predecessor into this branch and reconcile the changed HTTP contract boundary.
2. Keep `portal-ru-anytools.html` readable for Steps 7–13. Step 6 does not use the mockup. Recommended: place the HTML beside this plan and treat it as an input-only untracked reference.
3. Keep this plan under `docs/exec-plans/active/ANY-636-implementation-plan.md` while Steps 6–13 are pending. Do not leave a second authoritative `completed` copy in parallel.
4. Give the execution model this file and instruct it to implement **one pending step only**.
5. After each pending step:
   - review the diff against the exact step and the RU mockup where visual composition is involved;
   - run the step's manual verification commands yourself;
   - fix only failures caused by that step;
   - create the proposed commit yourself;
   - only then continue to the next step.
6. Do not ask the execution model to repeat broad billing/provider/architecture research already captured here.
7. Do not let existing tests or the incidental current layout preserve a UI composition that conflicts with the corrective RU product/visual contract. Tests may be updated when they encode the old transitional presentation, while settled auth/security/provider boundaries remain authoritative.

### Historical note for initial Steps 1–5

The original execution began from `ANY-541` / PR #129 at planning baseline commit `3e53f1cc7756cc6825b05b4fcbd580479a196a64`. Those branch-creation instructions are historical only and must not be followed again except for the explicit predecessor merge required by Step 6.

### Continuation instructions for Steps 6–13

1. **Do not recreate or reset the `ANY-636` branch.** Step 6 merges the current/final `ANY-541` branch into the existing 636 history and resolves only the predecessor drift.
2. Step 6 must finish with the final ANY-541 generated-TypeScript/shared-transport trust boundary actually present in `ANY-636`; no Zod response-validation path may remain.
3. Before each visual corrective step (Steps 7–13), open the local `portal-ru-anytools.html` reference and compare the exact affected surface against the current implementation.
4. Preserve the working auth/session/legal/i18n/provider-independent product behavior from Steps 1–5 while replacing only the obsolete inherited 4D mechanics in Step 6. Later steps correct presentation and product composition; they do not reopen settled architecture.
5. The RU mockup wins over the **incidental current layout** for both product composition and target visual language. Bundle 3 remains the single implementation design-system authority, but Step 10 must evolve its canonical tokens/components/rules where the previous glass/bento identity conflicts with that approved target; accessibility/responsive discipline remains authoritative.
6. When the mockup contains demo or unverified business facts, keep the layout role but replace the value/control with current authoritative content or an honest unavailable/not-ready state. If neither is useful, omit the block rather than manufacture a placeholder.
7. Do not continue to parent ANY-504 Step 6 implementation until ANY-636 Step 13 final acceptance is complete. The numbering below is internal to the ANY-636 plan and must not be confused with parent ANY-504 Steps 6–10.

---

## Research Basis and Source-of-Truth Order

This plan was prepared against the current `ANY-541` PR #129 code, not against `main`.

When sources conflict during Steps 6–13, use the following precedence for this ticket:

1. `ANY-636` and the `ANY-504` execution sequence for the current 4F scope and future-step boundaries.
2. ADR 0005 and the accepted External Billing / Portal-Kernel designs for ownership and authority.
3. The final/current `ANY-541` / PR #129 architecture for HTTP wire-contract generation, single shared transport trust, and no second browser runtime schema authority.
4. The current `ANY-636` code for settled route/auth/session/legal/i18n/provider-independent product behavior from Steps 1–5, except where Step 6 explicitly replaces obsolete inherited 4D mechanics.
5. The ANY-539 `portal-ru-anytools.html` plus its development handoff for the **target RU Portal product and visual language**: hierarchy, density, palette direction, typography, surfaces, spacing, navigation/card/dashboard treatment and customer journey. They are not authority for tariffs, prices, providers, subscription/access truth, usage/quota, legal/privacy claims or runtime product identity.
6. Bundle 3 remains the single implementation design system, but Step 10 deliberately evolves its canonical rules/tokens so they encode the approved RU mockup direction instead of preserving the older indigo glass/bento appearance. Accessibility/responsive discipline remains authoritative.
7. Current repository tests for behavior that remains authoritative. Tests that merely encode the old transitional visual composition may be updated by Steps 7–12; tests for auth/security/contracts/provider boundaries remain authoritative.

### Sources reviewed

- Linear:
  - `ANY-636`
  - parent `ANY-504`
  - source direction ticket `ANY-539`
  - predecessor `ANY-541`
  - future provider gate `ANY-634`
  - relevant prior baseline represented by the current code from `ANY-505`, `ANY-509`, `ANY-510`, `ANY-522`, `ANY-408`, `ANY-525`, and `ANY-538`
- PR #129 final/current planning observation at `bc80eaaee3b0c6051548ff446960791636216436`, plus historical baseline `3e53f1cc7756cc6825b05b4fcbd580479a196a64` used by initial Steps 1–5.
- `docs/exec-plans/completed/ANY-541-implementation-plan.md`, including the durable 4F handoff.
- `ARCHITECTURE.md`.
- `docs/PRODUCT.md`.
- `docs/product/ru-mvp.md`.
- `docs/DESIGN.md` and Bundle 3 web guidance.
- `docs/architecture/contours.md`.
- `docs/architecture/deployment.md`.
- `docs/architecture/region-resolver-contract.md`.
- `docs/architecture/decisions/0005-external-billing-boundary.md`.
- accepted External Billing and Portal-Kernel design baselines.
- current web route tree, shell, catalog, account/auth, reset, verification, legal and payment-unavailable surfaces.
- current API composition and identity/legal routers.
- current web component, boundary and Playwright coverage.

### Mockup access note — resolved for corrective completion

The raw `portal-ru-anytools.html` is now available and is a **required input** for product/visual Steps 7–13. The original planning limitation is resolved.

For Steps 7–13 the execution model must inspect the RU HTML before editing the affected visual surface. The HTML is a **visual/product reference**, not business or runtime authority. It may define layout hierarchy, grouping, density, palette direction, typography, navigation feel, surface/card treatment, product-detail composition and cabinet composition, but it must not supply unverified facts. Step 10 translates that visual direction into the single Bundle 3 design-system authority rather than copying the stylesheet as a second theme.

The following RU mockup content remains explicitly non-authoritative and must not be copied as production truth unless a current authoritative source independently proves it: prices/tariffs, CloudPayments/provider references, payment-method claims, active-subscription values, renewal dates, usage/quota numbers, product availability labels, user/product counts, release cadence, storage/location/privacy claims, unimplemented products, and install/web-app targets that do not have an authoritative current destination.

For local Codex execution, keep `portal-ru-anytools.html` accessible beside this plan (recommended) or provide its exact readable filesystem path in the execution prompt. Treat it as input-only: do not edit, stage or commit the reference unless explicitly requested.

---

## Historical Planning Baseline Before Initial Steps 1–5

> This section records the repository state that the original plan started from. It is retained for history and must **not** be treated as the current branch state during Steps 6–13. The corrective starting baseline is defined below.


### Web routes currently present

```text
/[locale]
/[locale]/products
/[locale]/account
/[locale]/auth-checkout
/[locale]/forgot-password
/[locale]/reset-password
/[locale]/verify-email
/[locale]/payment-result
/[locale]/privacy
/[locale]/consent-personal-data
/[locale]/offer
/[locale]/cancellation
/[locale]/cookies
/[locale]/security
```

The exact route locales remain:

```text
en / fr / it / de / es / ru / pt
```

Locale is presentation only and must not be used as tenant, contour, provider, currency, timezone, billing or product authority.

### Existing frontend authority

- `apps/web/src/messages/*.json` owns ordinary Portal UI copy.
- `config/locales.json` owns the locale contract.
- canonical RU legal content remains source-owned/generated and RU-only.
- `apps/web/src/features/catalog/catalog.ts` currently contains two **presentation-only** product identifiers:
  - `document-summary`
  - `prompt-optimizer`
- those identifiers are not a commercial catalog and are not assumed to be Platform Kernel `product_id` values.
- seller/support/legal facts remain source-owned and must not be relabeled or invented.
- `paymentMethods` is currently empty; the UI must not invent provider/payment-method marks.

### Existing API authority

The current FastAPI composition exposes only the provider-independent surface needed here:

```text
auth / registration / login / session / logout
email verification
password reset
legal required documents / acceptances
health / metrics
```

Removed contracts remain removed:

```text
/api/catalog/products
/api/auth/checkout-intent
/api/account/subscriptions
/api/auth/payment-status
```

There is no current billing/catalog/subscription/access/usage runtime that 4F may use.

### Historical ANY-541 contract assumption at original planning time — superseded

The initial plan was written against predecessor commit `3e53f1c`, where the
frontend 4D boundary still used generated Zod runtime schemas. That mechanism is
**not current authority** and must not be preserved by later work. Step 6
reconciles the already-implemented ANY-636 branch with the final PR #129
generated-TypeScript/shared-transport design defined above.

4F still must not create handwritten backend wire DTOs; the changed point is
that browser structural runtime validation is no longer part of the authority
chain.

### Research conclusion: no new 4F backend API is justified

No new Portal-owned HTTP API is required for the implementation allowed by ANY-636:

- account/session/email-verification facts already exist through generated auth contracts;
- legal/reset/verification contracts already exist;
- product descriptions and route slugs are frontend-owned presentation metadata;
- tariffs/prices/subscriptions/payment methods/autopay/invoices/refunds belong to External Billing and are deferred;
- confirmed paid-access state belongs to later Portal projection work and is deferred;
- technical product identity, actual usage and quota belong to Platform Kernel and are deferred.

Therefore this plan deliberately contains **no new FastAPI/Pydantic/OpenAPI contract or database-design step**. Step 6 synchronizes already-defined ANY-541 frontend generated TypeScript artifacts/transport mechanics; it does not invent a new API contract.

If implementation discovers a genuinely required Portal-owned persisted/API fact that is not represented by the current backend, stop and report the exact missing fact and ownership reason. Do not add an API opportunistically.

---

## Mockup Block → Authority → 4F Decision Matrix

| UI / mockup concern | Authority | Current source | 4F behavior | Deferred owner / step |
| --- | --- | --- | --- | --- |
| Portal shell, brand, navigation, responsive layout | Portal Presentation | `SiteShell`, Bundle 3, locale catalogs | Implement/refine now | — |
| User email / authenticated identity | Portal | generated `SessionUserResponse` from `/api/auth/session` | Render now | — |
| Sign in / registration / logout | Portal | existing generated auth contracts + `AuthForm` | Reuse and consolidate around `/account` | — |
| Email verification | Portal | `email_verified`, verification routes/contracts | Preserve now | — |
| Password recovery | Portal | current reset routes/contracts | Preserve now | — |
| Legal links / legal acceptance UX | Portal / canonical RU legal source | generated legal assets + existing auth/legal behavior | Preserve now | — |
| Product list and product descriptions | Portal presentation only | current static `productPresentation` + locale copy | Implement now as clearly presentational content | Future technical identity still comes from Kernel |
| Product detail page / discovery route | Portal presentation only | new local route based on presentation slug | Implement now | — |
| Actual product execution target | Not currently authoritative in this repo | none | Show no fabricated launch URL; route only to Portal product/account surfaces | Future owning product/Kernel integration decision |
| Tariffs, prices, periods, sellability | External Billing | none | Explicit `not ready` / unavailable presentation; no values | ANY-504 Step 6 |
| Purchase / checkout / Widget entry | External Billing + Portal orchestration | none | Do not implement; no buy/checkout CTA | ANY-504 Step 7 |
| Subscription/billing state | External Billing | none | Explicitly unavailable/unknown; never render “no subscription” as a fact | ANY-504 Steps 6–8 |
| Provider recovery/reconciliation | Portal boundary over External Billing facts | none | No runtime/UI assumption | ANY-504 Step 8 |
| Paid access / entitlement result | Portal paid-access projection | none | Explicitly unknown/not ready; never infer from identity or browser state | ANY-504 Step 9 |
| Actual usage / remaining quota | Platform Kernel | none | Explicitly unavailable; never render `0` or a guessed quota | ANY-504 Step 10 |
| Payment methods / autopay / invoice / refund self-service | External Billing | none | No Portal-owned fake controls | Provider-backed later steps |
| Profile/account shell and logout | Portal | session/logout contracts | Implement now | — |
| Error/loading/empty/retry presentation | Portal Presentation | existing patterns in header/verification/reset + Bundle 3 | Implement where 4F touches a surface | — |
| Mobile layout/accessibility | Portal Presentation | Bundle 3 + current responsive CSS + Axe E2E | Implement and verify now | — |

---

## Locked Route and CTA Decisions

These decisions are resolved for this plan. The execution model must not reopen them without a material code contradiction.

| Surface | Final 4F route / behavior |
| --- | --- |
| Home | `/{locale}` |
| Product catalog | `/{locale}/products` |
| Pricing placeholder | `/{locale}/pricing`; presentation-only unavailable/not-ready state and safe home/products navigation; no commercial facts or purchase controls |
| Product details | `/{locale}/products/document-summary` and `/{locale}/products/prompt-optimizer` |
| Account + direct sign-in/registration entry | `/{locale}/account` |
| Header sign-in | Keep the existing HeaderAccount modal; do not redesign it into another route |
| Password-reset request | `/{locale}/forgot-password` |
| Password-reset confirmation | `/{locale}/reset-password` |
| Email verification | `/{locale}/verify-email` |
| Canonical legal routes | Keep current RU legal paths/semantics unchanged |
| Transitional `/{locale}/auth-checkout` | Remove; no redirect or compatibility route |
| Transitional `/{locale}/payment-result` | Remove; no redirect or compatibility route |
| Home primary CTA | Account/sign-in entry, not checkout |
| Catalog card CTA | Product detail page |
| Product detail account CTA | `/account`; must not be labelled as purchase/checkout |
| Buy / pay / choose tariff CTA | Not present in 4F |
| Product execution CTA | Do not invent an external/runtime target; show the honest not-ready state instead |

There is no production compatibility obligation for the two retired transitional UI routes.

### Approved Step 11 pricing placeholder decision

The user-approved Step 11 topology change supersedes the original blanket prohibition on a pricing page or Pricing navigation entry in 4F. It permits only the localized `/[locale]/pricing` **presentation-only placeholder** and its localized public navigation entry.

- The page has localized metadata, honestly states that pricing/terms are not available yet, and offers safe navigation to home/products.
- It does not own or expose actual commercial catalog data. It contains no prices, tariff names, billing periods, sellability, subscription state, provider data, purchase controls or fake offers. The pricing feature makes no network/API calls and introduces no backend changes.
- The route exists only to establish the final Portal navigation/topology and a stable future presentation surface; it does not reproduce the HTML mockup's tariff cards.
- Authoritative offers, prices and sellability may populate this surface only through parent **ANY-504 Step 6**, with commercial truth remaining owned by External Billing.
- Purchase and provider Widget behavior remain parent **ANY-504 Step 7**. This exception does not move commercial authority into ANY-636 or authorize purchase/provider runtime.
- Earlier Step 7 pricing prohibitions are retained below as historical restrictions explicitly superseded by this narrow Step 11 decision. Existing product/auth/legal semantics and all other ownership boundaries remain locked.

---

## Locked Invariants for the Whole Ticket

- 4F is provider-independent.
- No provider network I/O.
- No LBX adapter/client/Widget.
- No CloudPayments restoration.
- No Portal-owned `Product`, `Plan`, `Order`, `Payment`, `Subscription`, `Entitlement`, trial, or payment-method runtime.
- No database schema or persistence semantics changes.
- No new billing idempotency/concurrency design.
- No fake commercial values.
- No fake access result.
- No fake usage/quota values.
- “Unavailable”, “unknown” and “not ready” remain distinct from negative business facts such as “no subscription”, “no access”, or “0 usage”.
- Canonical legal content and deep links remain unchanged.
- Reset/verification token handling remains unchanged and tokens remain absent from persistent UI/logging surfaces.
- Bearer/session API contracts remain generated from backend OpenAPI.
- Ordinary UI copy keeps exact seven-locale key/ICU-signature parity.
- Bundle 3 remains the single design system. Step 10 may evolve its canonical tokens/rules to match the approved RU mockup visual language, but no parallel token system or page-local replacement theme is allowed.
- No opportunistic repository cleanup.

---

# Step 1 — Build the Public Portal and Product Discovery Surface

**Status:** `done`  
**Recommended model:** `Luna`

**Goal**  
Evolve the public shell, home and catalog into the provider-independent AnyToolAI Portal presentation and add stable localized detail routes for the two current presentation products, without creating commercial, access, usage or runtime-product authority.

**Scope / affected code**  
Work primarily in:

```text
apps/web/src/app/[locale]/page.tsx
apps/web/src/app/[locale]/products/page.tsx
apps/web/src/app/[locale]/products/[product]/page.tsx        # new
apps/web/src/shared/ui/SiteShell.tsx
apps/web/src/features/catalog/catalog.ts
apps/web/src/features/catalog/ProductOverview.tsx
apps/web/src/features/catalog/                              # one small detail view/helper only if justified
apps/web/src/messages/en.json
apps/web/src/messages/fr.json
apps/web/src/messages/it.json
apps/web/src/messages/de.json
apps/web/src/messages/es.json
apps/web/src/messages/ru.json
apps/web/src/messages/pt.json
apps/web/src/app/globals.css
apps/web/src/app/catalog.css
apps/web/src/app/responsive.css
```

Touch only directly affected tests if the changed source makes them stale. Use the existing metadata/i18n helpers; do not create a second routing or metadata system.

**Implementation decisions**  

1. Keep the existing Bundle 3 shell, typography, glass/bento visual language, locale switcher, footer, cookie banner and `HeaderAccount` behavior.
2. Keep exactly two current frontend presentation products:
   - `document-summary`;
   - `prompt-optimizer`.
3. Treat those values only as frontend presentation/route slugs. Prefer a `slug` field in `ProductPresentation`; do not treat them as Platform Kernel `product_id`, External Billing IDs or commercial catalog identity.
4. Add one localized dynamic route:

```text
/[locale]/products/[product]
```

with exactly the two supported presentation slugs. Use `generateStaticParams()` if required by the current Next.js route/build convention. Unknown slugs must call `notFound()`.
5. Update public navigation/CTAs coherently:
   - home primary account/auth action -> localized `/account`;
   - home/catalog discovery -> `/products` or the existing product section;
   - catalog product cards -> their localized product detail routes.
6. Product detail pages may show only Portal-owned descriptive presentation facts, catalog navigation and an account/profile CTA. They may show a concise explicit not-ready state only where the approved RU mockup has a slot that depends on future-owned data. Do **not** force separate billing/access/usage panels onto every product page if the mockup/current UX does not require them; those broader cabinet states belong in Step 3.
7. Do not expose an actual product execution target unless an authoritative current route already exists. Current research found none. Do not invent an external application URL or Kernel execution URL.
8. Do not add prices, tariff names, periods, sellability, subscription state, payment methods, provider names, paid-access state, actual usage, remaining quota, external billing IDs, Kernel IDs, commercial plan IDs or buy/subscribe/trial CTAs.
9. Do not convert existing static marketing/presentation statements into fake runtime authority. At the same time, do not delete harmless presentation content merely because it is static. Change `accountCount`, `catalogRegion`, pricing/readiness facts or similar fields only when the final public presentation would otherwise misleadingly look like a dynamically verified business/runtime fact. Prefer semantic copy over invented metrics; avoid opportunistic cleanup.
10. Keep source-owned seller/support/legal facts unchanged and keep `paymentMethods` empty.
11. Make the public copy truthfully communicate that account/auth/legal functionality exists, the two products can be discovered, and commercial purchase is not ready, without implying that subscription/access/quota state was checked.
12. All new/changed ordinary UI copy must exist in all seven locale catalogs with exact key and ICU-signature parity. RU is the primary product/visual direction, but the established locale contract remains intact.
13. Keep localized ordinary navigation through `@/i18n/navigation`; do not hardcode `/ru` application paths.
14. Reuse the existing `createLocalizedMetadata()` flow for product pages; do not infer contour from locale.
15. Use only existing Bundle 3 tokens/CSS patterns and add only CSS needed for the changed public/product surfaces.
16. Do not change account authentication, reset, verification, canonical legal, `/auth-checkout` retirement or `/payment-result` behavior in this step; those belong to later steps.
17. Do not add or change FastAPI endpoints, Pydantic models, OpenAPI, generated API contracts, database models or migrations.
18. If the RU HTML mockup is directly available during execution, inspect it only as the visual/layout reference for these public/product surfaces. It must not reopen the route/data-ownership decisions above or contribute demo commercial/provider/usage facts. If the attachment remains unavailable, follow Bundle 3 plus the locked route/ownership decisions and do not invent mockup-specific structures.

**Invariants**  

- Existing locale routing and metadata authority remain unchanged.
- Header authentication behavior remains unchanged.
- Footer legal/operator/source-owned values remain unchanged.
- Product slugs remain frontend presentation identity only.
- Unknown product slugs fail closed through `notFound()`.
- No backend request is added for public/product presentation.
- No External Billing/Kernel/runtime-product value is synthesized.
- No tariff/price/subscription/access/usage/quota truth is invented.
- No product execution endpoint is invented.
- Seven-locale message parity remains valid.

**Out of scope**  

- account/cabinet redesign;
- removing `/auth-checkout`;
- removing `/payment-result`;
- purchase/checkout/Widget;
- External Billing catalog projection;
- Kernel capability manifest or product execution integration;
- paid-access projection;
- usage/quota reads;
- backend/API/OpenAPI/generated-contract changes;
- documentation rewrite;
- broad CSS/catalog cleanup unrelated to the changed surfaces.

**AI prompt**  

```text
Implement only Step 1 of ANY-636: build the provider-independent public AnyToolAI Portal and product-discovery surface.

Follow the decisions defined in this prompt. Do not perform broad repository research. Inspect only the directly relevant current public shell, catalog, routing, metadata, locale-message, CSS and directly affected test files, plus the local web agent/design instructions they explicitly require to verify assumptions.

If portal-ru-anytools.html is directly available, inspect it only for visual/layout direction for these public/product surfaces. Do not derive contracts, commercial values, provider facts, access state, usage or quota from the mockup.

Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.

Implement these settled decisions:

1. Keep Bundle 3, the existing locale switcher, footer, cookie banner and HeaderAccount behavior.
2. Keep exactly two frontend presentation products: document-summary and prompt-optimizer.
3. Treat those values only as presentation/route slugs; prefer ProductPresentation.slug. Do not treat them as Platform Kernel product_id or External Billing identity.
4. Add /[locale]/products/[product] for exactly those two slugs. Use generateStaticParams if required by the current Next.js route/build conventions. Unknown slugs must use notFound().
5. Change the home primary account/auth CTA to localized /account. Keep product discovery through /products. Make product cards navigate to their localized product detail routes.
6. Product detail pages may contain only Portal-owned descriptive presentation facts, catalog navigation and account/profile navigation. Add a concise not-ready state only where the approved RU mockup/current UX actually has a future-owned data slot. Do not invent mandatory billing/access/usage panels that are not required by the visual direction.
7. Do not add prices, tariffs, periods, sellability, subscription state, payment methods, provider names, paid-access state, usage, quota, billing IDs, Kernel IDs, plan IDs, buy/subscribe/trial controls or product execution URLs.
8. Current research found no authoritative product execution target. Do not invent one.
9. Do not remove harmless static presentation content merely because it is static. Change accountCount, catalogRegion, pricing/readiness presentation or similar fields only if the final UI would otherwise misrepresent them as dynamically verified runtime/business facts. Avoid opportunistic cleanup.
10. Preserve source-owned seller/support/legal facts and keep paymentMethods empty.
11. Make the home/catalog/product copy truthful: account/auth/legal functionality exists; the two products are discoverable; commercial purchase is not ready; no wording implies that plan/subscription/access/quota was checked.
12. Put all new/changed ordinary UI copy into en/fr/it/de/es/ru/pt catalogs with exact key and ICU-signature parity.
13. Keep ordinary navigation through @/i18n/navigation. Do not hardcode /ru routes and do not derive contour from locale.
14. Reuse createLocalizedMetadata() and the existing Bundle 3 CSS/token system.
15. Do not change account auth semantics, reset, verification, legal flows, /auth-checkout retirement or /payment-result in this step.
16. Do not add or change FastAPI endpoints, Pydantic models, OpenAPI, generated API contracts, database models or migrations.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

Do not run tests, linters, formatters, type checks, builds, generators or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed/new file;
- list the final public/product routes and CTAs;
- summarize the final ProductPresentation responsibility;
- identify any removed or rewritten pseudo-runtime presentation and why it was misleading;
- confirm that no commercial/access/usage/provider/runtime-product data or execution URL was invented;
- report the exact verification commands I should run manually.
```

**Manual verification**  

Run:

```bash
node --test \
  apps/web/tests/i18n-contract.test.mjs \
  apps/web/tests/app-metadata.test.mjs
npm run typecheck:web
```

Then manually inspect at least:

```text
/ru
/ru/products
/ru/products/document-summary
/ru/products/prompt-optimizer
/en/products/document-summary
/pt/products/prompt-optimizer
```

and verify an unknown product slug is not-found. Confirm the public/product surfaces contain no invented price, subscription/access/quota result, purchase CTA or product execution target.

**Expected completion**  

- Home/catalog read as the AnyToolAI Portal rather than a payment placeholder.
- Both current products have localized provider-independent detail routes.
- Product slugs remain presentation-only.
- Public CTAs point to account/product discovery, not checkout.
- No new API/data authority is introduced.
- Seven-locale copy stays structurally valid.

**Proposed commit**  

```text
ANY-636 build portal public product discovery
```

---

# Step 2 — Make `/account` the Direct Auth Entry and Retire `/auth-checkout`

**Status:** `done`  
**Recommended model:** `Sol`

**Goal**  
Consolidate direct sign-in/registration and account entry on the existing `/account` surface, preserve the established auth/legal/reset/verification contracts, and remove the misleading transitional `/auth-checkout` route without compatibility behavior.

**Scope / affected code**  

Primary production code:

```text
apps/web/src/app/[locale]/account/page.tsx
apps/web/src/features/account/AccountClient.tsx
apps/web/src/app/[locale]/auth-checkout/page.tsx          # remove
apps/web/src/features/checkout/CheckoutClient.tsx         # remove
apps/web/src/features/checkout/index.ts                   # remove if empty
apps/web/src/features/password-reset/PasswordResetRequestClient.tsx
apps/web/src/features/password-reset/PasswordResetConfirmClient.tsx
apps/web/src/features/email-verification/EmailVerificationClient.tsx
apps/web/src/features/payment-result/PaymentResultView.tsx # navigation links only
apps/web/src/messages/{en,fr,it,de,es,ru,pt}.json
apps/web/src/app/account.css
```

Directly affected tests/guards:

```text
apps/web/tests/components/AccountClient.test.tsx
apps/web/tests/components/CheckoutClient.test.tsx         # remove
apps/web/e2e/auth-legal-links.spec.ts
apps/web/e2e/email-verification.spec.ts
apps/web/e2e/password-reset.spec.ts
apps/web/e2e/account-logout.spec.ts
apps/web/e2e/checkout-unavailable.spec.ts                 # remove; replacement boundary coverage is Step 5
apps/web/tests/app-metadata.test.mjs
```

**Implementation decisions**  

1. `/[locale]/account` becomes the direct page for both:
   - signed-out login/registration;
   - authenticated account/cabinet presentation.
2. Reuse the existing `AuthForm`. Do not create a second auth form.
3. Reuse existing shared generated-contract API wrappers:
   - `submitAuth()`;
   - `getSession()`;
   - `logoutSession()`;
   - `SessionUserResponse`.
4. `AccountPage` must provide the `Auth`, `Account`, and `EmailVerification` message namespaces needed by the client boundary. Do not send the full locale catalog.
5. For signed-out account state, render the login/registration form directly instead of linking to `/auth-checkout`.
6. Registration must preserve the current explicit personal-data and offer confirmations and current password-policy ownership. Do not duplicate backend password policy into a new frontend wire contract.
7. After successful login/registration:
   - store the returned bearer exactly through the current local-storage/session-event convention;
   - update the account state from the generated response;
   - preserve email-verification pending behavior for an unverified user.
8. Preserve `HeaderAccount` as a modal-based header sign-in entry. Do not convert it to `/account` merely for uniformity.
9. Strengthen only the account-page **presentation recovery** that becomes necessary once `/account` is the direct auth entry:
   - only a `401` for the same current bearer may clear that bearer and resolve to signed-out;
   - a stale success/401 for an older bearer must not overwrite or clear a newer bearer;
   - `5xx`, network, timeout/abort, and `ApiContractError` failures must preserve the current bearer and render a retryable account-session error instead of falsely claiming signed-out;
   - retry re-runs only the session read.
   This follows the already established `HeaderAccount` / email-verification trust behavior and does not change backend auth semantics.
10. Logout behavior remains: attempt backend logout, but local bearer removal still wins in the fallback/finally path so the browser becomes signed out.
11. Update every active `/auth-checkout` reference encountered within the Step 2 dependency surface to the locale-aware `/account` route, including reset/verification links and navigation in `PaymentResultView`, without otherwise modifying the payment-result feature.
12. Preserve reset/verification fragment-token behavior exactly. Do not put tokens into query strings, localStorage, logs or new UI state.
13. Delete the `/[locale]/auth-checkout` page and checkout feature. Do not add a redirect, alias, compatibility route, rewrite, or deprecated banner.
14. Remove the obsolete `Checkout` locale namespace when no active surface consumes it.
15. Adapt existing auth/legal/email-verification/password-reset/account tests to `/account`. Delete tests whose only purpose was the retired checkout shell.
16. `app-metadata.test.mjs` currently reads checkout files directly for the provider-script guard. After those files are removed, keep the **repository-wide source scan** for forbidden provider code and removed billing contracts, but remove the dead dependency on specific checkout files. Do not weaken the actual guard.
17. Do not add any commerce API call to `/account`.

**Invariants**  

- Generated ANY-541 auth contracts remain the only frontend HTTP wire authority.
- Registration legal confirmations remain explicit and unchanged.
- Verification/reset token lifecycle remains unchanged.
- Header auth modal remains available.
- Logout still revokes backend session where possible and always clears the local browser session.
- Transient account session-load failure does not become a false signed-out claim.
- No commerce/provider request is introduced.
- `/auth-checkout` is gone with no compatibility layer.

**Out of scope**  

- the richer authenticated cabinet/product readiness blocks from Step 3;
- removal of `/payment-result`;
- product-access integration;
- billing/access/usage APIs;
- backend auth redesign;
- session-storage mechanism redesign;
- Sentry redesign;
- general auth code deduplication beyond what is required to retire `CheckoutClient`.

**AI prompt**  

```text
Implement only Step 2 of ANY-636: make the localized /account page the direct login/registration + account entry surface and remove the transitional /auth-checkout route.

Step 1 is assumed complete and manually verified.

Follow the decisions defined in this prompt. Do not perform broad repository research. Inspect only the directly relevant account, checkout, AuthForm/shared-auth, password-reset, email-verification, locale-message and affected test/guard files needed to verify these assumptions.

Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.

Implement these settled decisions:

1. /[locale]/account becomes both:
   - the signed-out login/registration page;
   - the authenticated account/cabinet page.
2. Reuse the existing AuthForm. Do not create another auth form.
3. Reuse submitAuth(), getSession(), logoutSession() and generated SessionUserResponse from the ANY-541 boundary. Do not introduce handwritten backend response DTOs or decoders.
4. Update the account page provider so the client receives only the needed Auth, Account and EmailVerification message namespaces.
5. Signed-out AccountClient must render login/registration directly rather than link to /auth-checkout.
6. Preserve current registration legal confirmations, password-policy ownership, Accept-Language behavior and generated-contract/shared-transport API boundary.
7. After successful login/registration, store the bearer and dispatch the existing sessionChangedEvent using the current conventions, then present the returned generated user state. Keep EmailVerificationPending for an unverified user.
8. Keep HeaderAccount as the current modal sign-in entry. Do not redesign it.
9. Make account session loading truthful and retryable using the already established trust rule from HeaderAccount/email verification:
   - only a 401 for the same still-current bearer may clear the bearer and resolve signed-out;
   - stale success/401 responses for an older bearer must not mutate a newer bearer/session state;
   - 5xx, network, timeout/abort and ApiContractError failures must preserve the bearer and render a retryable session-error state instead of claiming signed-out;
   - retry only reloads the session.
   Do not change backend auth/session semantics.
10. Preserve logout behavior: attempt backend logout when a bearer exists, but always clear the matching local bearer in the fallback/finally path and dispatch the session change.
11. Update every active /auth-checkout reference encountered within the Step 2 dependency surface to locale-aware /account, including reset/verification “back to sign in” links and navigation in PaymentResultView, without otherwise modifying the payment-result feature.
12. Preserve password-reset and email-verification fragment-token lifecycle exactly. Do not persist those tokens or move them into query strings.
13. Delete apps/web/src/app/[locale]/auth-checkout/page.tsx and the checkout feature files once no active code imports them.
14. Do not add a redirect, rewrite, compatibility alias or deprecated /auth-checkout page. There is no production compatibility obligation.
15. Remove the obsolete Checkout locale namespace if it has no remaining active consumer, updating all seven catalogs together.
16. Update directly affected component/E2E tests from auth-checkout to account. Remove CheckoutClient tests and checkout-unavailable E2E coverage that exist only for the retired surface; Step 4 will add final Portal boundary coverage.
17. Update app-metadata.test.mjs so its provider-script guard no longer reads deleted checkout files directly. Keep or strengthen the repository-wide source scan for provider scripts and removed billing contracts.
18. Do not remove, redesign, or otherwise evolve /payment-result in this step; its removal remains Step 3. Updating its navigation links only as required to remove references to the deleted /auth-checkout route is explicitly allowed.
19. Do not add FastAPI endpoints, Pydantic models, OpenAPI changes, generated API contracts, database models, migrations, commerce APIs, provider code, billing state, paid access or usage/quota data.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

Do not run tests, linters, formatters, type checks, builds, generators or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed/deleted file;
- summarize the new signed-out/account auth flow;
- describe session failure/retry semantics;
- list every /auth-checkout reference removed or intentionally retained (there should be no active production route/reference);
- confirm reset/verification token semantics were not changed;
- report the exact verification commands I should run manually.
```

**Manual verification**  

Run focused component coverage:

```bash
npm --workspace @anytoolai/web run test:components -- \
  tests/components/AccountClient.test.tsx \
  tests/components/HeaderAccount.test.tsx \
  tests/components/EmailVerificationClient.test.tsx \
  tests/components/AuthForm.test.tsx \
  tests/components/AuthContractValidation.test.ts \
  tests/components/AuthApiError.test.ts
```

Before browser coverage, rebuild and recreate the worktree harness from the current source. `test:e2e` uses the existing running server; it does not start or rebuild the frontend. For an already running harness:

```bash
npm run repo:up -- --reuse
```

Preserve any custom `--port-offset` used to start that harness.

Run focused browser flows:

```bash
npm run test:e2e -- \
  apps/web/e2e/auth-legal-links.spec.ts \
  apps/web/e2e/email-verification.spec.ts \
  apps/web/e2e/password-reset.spec.ts \
  apps/web/e2e/account-logout.spec.ts
```

Then:

```bash
node --test \
  apps/web/tests/app-metadata.test.mjs \
  apps/web/tests/i18n-contract.test.mjs
npm run typecheck:web
```

**Expected completion**  

- Direct navigation to `/ru/account` provides login/registration when signed out and the account surface when signed in.
- Header modal auth still works.
- Reset/verification routes return users to `/account` rather than `/auth-checkout`.
- Transient session failures are retryable and do not falsely delete the trusted bearer.
- `/auth-checkout` no longer exists or has an active production reference.
- No commerce/provider behavior was introduced.

**Proposed commit**  

```text
ANY-636 consolidate authentication on account route
```

---

# Step 3 — Build the Honest RU Account Cabinet and Retire `/payment-result`

**Status:** `done`  
**Recommended model:** `Luna`

**Goal**  
Turn the authenticated account surface into the RU AnyToolAI Portal cabinet described by the mockup direction, while clearly separating current identity facts from future commercial/access/usage facts, and remove the remaining obsolete payment-result surface.

**Scope / affected code**  

Primary production code:

```text
apps/web/src/features/account/AccountClient.tsx
apps/web/src/features/catalog/catalog.ts
apps/web/src/app/[locale]/account/page.tsx              # only if composition/messages require it
apps/web/src/app/[locale]/payment-result/page.tsx       # remove
apps/web/src/features/payment-result/PaymentResultView.tsx  # remove
apps/web/src/features/payment-result/index.ts           # remove if empty
apps/web/src/messages/{en,fr,it,de,es,ru,pt}.json
apps/web/src/app/account.css
apps/web/src/app/catalog.css
apps/web/src/app/responsive.css
apps/web/src/app/globals.css                            # only directly related selectors if necessary
```

Directly affected tests:

```text
apps/web/tests/components/AccountClient.test.tsx
apps/web/e2e/account-logout.spec.ts
```

Delete or adapt any test/source that exists only for the removed payment-result page.

**Implementation decisions**  

1. Keep the canonical authenticated identity facts limited to what the existing session contract actually provides:
   - email;
   - `email_verified`;
   - existing session/logout behavior.
2. Do not invent profile fields such as name, avatar, country, company, tariff, customer number or billing ID.
3. Keep `EmailVerificationPending` visible for an authenticated unverified user. Email verification status must remain sourced from the generated session contract.
4. Build the cabinet from the current mockup categories, but use honest current-data states:
   - **Products**: show the two static Portal presentation products and link to their detail pages;
   - **Access**: show that authoritative access status is not available yet; never state “no access”;
   - **Billing/subscription**: show that plan/subscription/billing data is not ready; never state “no subscription”, a default plan, a price, renewal state or payment method;
   - **Usage/quota**: show that usage/quota data is not available yet; never render `0`, a guessed limit, progress bar, percentage or remaining count.
5. Do not add a “buy”, “subscribe”, “manage payment method”, “cancel subscription”, “invoice”, “refund”, “autopay” or provider self-service control.
6. Product cards inside the cabinet may navigate only to the current Portal product-detail routes. They must not launch an invented external application URL.
7. Do not fetch External Billing, target persistence tables, Platform Kernel, or removed commerce APIs.
8. The authenticated cabinet should remain useful with identity/product discovery even while future-owned data is unavailable. Do not hide the whole account behind a generic billing-unavailable panel.
9. Use frontend-local presentation structures only where needed. Do not define a backend-like `Subscription`, `Access`, `Usage`, `Plan` or `Quota` model in TypeScript.
10. Remove `/[locale]/payment-result` and its feature because there is no active payment flow and no compatibility requirement.
11. Remove the `PaymentResult` locale namespace if it has no remaining consumer.
12. Remove only CSS selectors that become dead specifically because the payment-result feature is removed; do not do a general stylesheet cleanup.
13. Do not replace `/payment-result` with a redirect, success/failure compatibility page, query-driven state or browser-return interpretation.
14. Keep all new account/cabinet copy in seven-locale parity even though RU is the primary implementation direction.

**Invariants**  

- Session identity remains authoritative only through generated auth contracts.
- Unverified state remains visible and recoverable.
- Missing access/billing/usage source is represented as unknown/not-ready, not a negative or zero fact.
- Product presentation remains static/frontend-owned.
- No network request is added beyond existing identity/verification/logout behavior.
- Browser URL/state never becomes payment/access authority.
- `/payment-result` is gone with no compatibility layer.

**Out of scope**  

- External Billing catalog/prices/subscriptions/self-service;
- purchase/Widget;
- reconciliation/recovery;
- paid-access projection;
- Platform Kernel capability/usage/quota integration;
- product execution integration;
- new backend APIs;
- profile schema expansion;
- general UI framework refactor.

**AI prompt**  

```text
Implement only Step 3 of ANY-636: build the authenticated AnyToolAI Portal account cabinet using only authoritative current identity facts plus explicit future-owned not-ready states, and remove the obsolete /payment-result surface.

Steps 1–2 are assumed complete and manually verified.

Follow the decisions defined in this prompt. Do not perform broad repository research. Inspect only the directly relevant account/catalog/payment-result/message/CSS files and directly affected tests needed to verify the plan assumptions.

Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.

Implement these settled decisions:

1. Authenticated account identity may display only facts available from the current generated session contract, primarily email and email_verified, plus the existing logout action.
2. Keep EmailVerificationPending for authenticated unverified users.
3. Do not invent profile name/avatar/country/company/customer ID/billing ID fields.
4. Evolve the authenticated account layout into the Portal cabinet direction with these blocks:
   - current products: the two existing frontend presentation products with links to their product-detail pages;
   - access: explicit authoritative status not available yet;
   - billing/subscription: explicit data not ready yet;
   - usage/quota: explicit data not available yet.
5. Missing-source wording must not claim:
   - no subscription,
   - no access,
   - 0 usage,
   - 0 remaining quota,
   - a free/default/trial plan,
   - a price,
   - renewal/payment state.
6. Do not add buy/subscribe/payment-method/autopay/invoice/refund/cancel-subscription/provider-self-service controls.
7. Cabinet product cards may only navigate to the current localized Portal product-detail routes. Do not invent product execution URLs.
8. Do not add External Billing, Platform Kernel, target-persistence, legacy commerce or provider network calls.
9. Do not create frontend models that imitate future backend Subscription/Plan/Entitlement/Usage/Quota wire contracts. Keep readiness/presentation state local and minimal.
10. Remove apps/web/src/app/[locale]/payment-result/page.tsx and the payment-result feature once unused.
11. Do not add a redirect, alias or compatibility payment-result route. Browser return state must not become purchase/access authority.
12. Remove the PaymentResult locale namespace if it is no longer consumed, updating all seven message catalogs together.
13. Remove only CSS that becomes dead specifically because payment-result is removed; do not perform a general CSS cleanup.
14. Update AccountClient component tests for verified, unverified and honest not-ready cabinet states.
15. Preserve all Step 2 account authentication/session/retry/logout behavior.
16. Do not add or change FastAPI endpoints, Pydantic models, OpenAPI, generated API contracts, database models or migrations.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

Do not run tests, linters, formatters, type checks, builds, generators or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed/deleted file;
- list the exact account cabinet blocks and what each is allowed to claim;
- confirm there are no new billing/access/usage/provider network calls;
- confirm /payment-result was removed without compatibility behavior;
- report the exact verification commands I should run manually.
```

**Manual verification**  

Run:

```bash
npm --workspace @anytoolai/web run test:components -- \
  tests/components/AccountClient.test.tsx \
  tests/components/HeaderAccount.test.tsx \
  tests/components/EmailVerificationClient.test.tsx
node --test apps/web/tests/i18n-contract.test.mjs
npm run typecheck:web
```

Manually verify `/ru/account` in at least these states:

```text
signed out
authenticated + email verified
authenticated + email unverified
```

Confirm that the authenticated page does not show a fake subscription/access/quota result and that `/ru/payment-result` is no longer an application route.

**Expected completion**  

- `/account` looks and behaves as an AnyToolAI Portal cabinet rather than a payment placeholder.
- Identity facts are real; all future-owned account blocks are explicitly not-ready/unknown.
- Product discovery is useful without pretending to know paid access.
- `/payment-result` is removed without replacement compatibility behavior.

**Proposed commit**  

```text
ANY-636 build honest portal cabinet states
```

---

# Step 4 — Add Focused Portal Route, Boundary, Mobile and Accessibility Coverage

**Status:** `done`  
**Recommended model:** `Luna`

**Goal**  
Replace retired checkout/payment placeholder tests with focused regression coverage for the actual 4F Portal journey, including route topology, honest unavailable states, no legacy commerce/provider traffic, mobile behavior and accessibility.

**Scope / affected code**  

Primary tests/guards:

```text
apps/web/e2e/public-routes.spec.ts
apps/web/e2e/portal-ru.spec.ts                    # new preferred focused 4F suite
apps/web/e2e/auth-legal-links.spec.ts             # only if Step 3 left follow-up naming/assertions
apps/web/e2e/email-verification.spec.ts           # only if directly required
apps/web/e2e/password-reset.spec.ts               # only if directly required
apps/web/e2e/account-logout.spec.ts               # only if directly required
apps/web/tests/components/AccountClient.test.tsx  # only missing focused assertions
apps/web/tests/app-metadata.test.mjs
apps/web/tests/i18n-contract.test.mjs             # normally unchanged; use existing guard
```

Do not create a parallel general-purpose test framework.

**Implementation decisions**  

1. Extend public route smoke/accessibility coverage to include the new active Portal routes:

```text
/ru
/ru/products
/ru/products/document-summary
/ru/products/prompt-optimizer
/ru/account
/ru/forgot-password
/ru/reset-password
canonical RU legal routes
```

`/ru/verify-email` remains covered by its dedicated flow where token/session state matters.
2. Add a focused `portal-ru.spec.ts` (or equivalently narrow existing suite) covering the 4F business presentation, not pixel-perfect CSS.
3. Prove that home/catalog/product-detail/account surfaces do not request removed commerce contracts:

```text
/api/catalog/products
/api/auth/checkout-intent
/api/account/subscriptions
/api/auth/payment-status
```

and do not load CloudPayments/provider browser scripts.
4. Prove route retirement explicitly:
   - `/ru/auth-checkout` → not found;
   - `/ru/payment-result` → not found;
   - neither route redirects to another compatibility page.
5. Prove product route behavior:
   - both supported product slugs render;
   - an unknown product slug is not found;
   - product cards navigate to the correct localized detail routes.
6. Prove account honesty with mocked session responses where appropriate:
   - verified user shows identity + product presentation + not-ready access/billing/usage states;
   - unverified user still shows email-verification guidance;
   - no assertion interprets absent billing/access data as “none” or `0`.
7. Preserve existing auth/reset/verification E2E behavior after route consolidation; do not duplicate every auth test into `portal-ru.spec.ts`.
8. Add one focused mobile viewport check using a normal phone-sized viewport (for example 390×844) for the key RU journey. Verify:
   - shell/navigation remains usable;
   - product cards/detail content remain visible;
   - account/auth form remains usable;
   - no horizontal page overflow.
9. Keep accessibility on semantic roles and existing Axe coverage. The key active public pages must have no serious/critical Axe violations.
10. Continue attaching screenshots/runtime evidence through the existing public-route test conventions where practical. Do not add visual snapshot/pixel-diff infrastructure.
11. Keep `app-metadata.test.mjs` source guards for provider scripts and removed billing contracts. Add a focused production-source guard for retired route literals only if it is simple and does not flag test/docs files; E2E 404 remains the behavior proof.
12. Do not test future Step 6–10 data or invent mock billing/provider contracts solely to make the UI look populated.

**Invariants**  

- Existing auth/legal/reset/verification regression coverage remains meaningful.
- New tests validate current 4F behavior, not future billing behavior.
- No fake provider/billing API is introduced for tests.
- Mobile/accessibility checks use current Bundle 3 behavior rather than a new testing subsystem.
- Retired routes are proven absent.

**Out of scope**  

- full provider/LBX E2E;
- billing catalog fixtures;
- paid-access fixtures;
- Kernel usage fixtures;
- visual regression tooling;
- backend/PostgreSQL test expansion;
- broad test refactoring.

**AI prompt**  

```text
Implement only Step 4 of ANY-636: add focused regression coverage for the final provider-independent RU AnyToolAI Portal journey.

Steps 1–3 are assumed complete and manually verified.

Follow the decisions defined in this prompt. Do not perform broad repository research. Inspect only the current public-route, account/auth/reset/verification E2E/component tests, app-metadata/i18n boundary tests, Playwright conventions and the directly relevant final Portal UI needed to write precise assertions.

Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.

Implement these settled decisions:

1. Extend active public route smoke/accessibility coverage to the final route set, including:
   - /ru
   - /ru/products
   - /ru/products/document-summary
   - /ru/products/prompt-optimizer
   - /ru/account
   - existing reset/legal routes that remain public.
2. Add one focused RU Portal E2E suite, preferably apps/web/e2e/portal-ru.spec.ts, for 4F-specific behavior.
3. Prove that Portal home/catalog/product/account pages do not call these removed contracts:
   - /api/catalog/products
   - /api/auth/checkout-intent
   - /api/account/subscriptions
   - /api/auth/payment-status
   and do not load CloudPayments/provider browser scripts.
4. Prove retired route behavior:
   - /ru/auth-checkout is not found;
   - /ru/payment-result is not found;
   - neither is redirected to a compatibility surface.
5. Prove both supported product detail routes render, unknown product slug fails closed/not-found, and catalog cards navigate to the correct localized product route.
6. With mocked /api/auth/session only where needed, prove the authenticated account surface:
   - displays the real user email;
   - preserves unverified-email guidance when email_verified=false;
   - shows explicit not-ready/unknown access, billing/subscription and usage/quota presentation;
   - does not display fake “no subscription”, “no access”, zero usage/quota or invented prices.
7. Do not duplicate existing complete auth/reset/verification tests into the new Portal suite. Keep those existing suites and adjust only directly stale route assertions.
8. Add a focused mobile viewport check for the RU journey using a normal phone viewport such as 390x844. Verify shell/navigation, product discovery/detail and account/auth remain usable and the document does not horizontally overflow.
9. Keep existing Axe accessibility behavior and require no serious/critical violations on active public Portal pages.
10. Keep existing screenshot/runtime-evidence conventions where practical. Do not add pixel-diff/visual-regression infrastructure.
11. Keep the app-metadata source guard against provider scripts and removed billing contracts. Add a simple production-source retired-route literal guard only if it fits the existing test cleanly; do not create a generic route-analysis framework.
12. Do not add fake billing/provider/access/usage APIs or fixtures merely for presentation tests.
13. Do not change production behavior unless a tiny accessibility/testability correction is directly necessary for the intended 4F behavior; if such a correction would be material, stop and report it instead.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

Do not run tests, linters, formatters, type checks, builds, generators or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed/new/deleted test file;
- list the route cases covered;
- list the no-commerce/no-provider assertions;
- describe the mobile and accessibility coverage;
- confirm retired routes are asserted not-found without redirects;
- report the exact verification commands I should run manually.
```

**Manual verification**  

Run focused boundary/component checks:

```bash
npm run test:boundaries:web
npm --workspace @anytoolai/web run test:components -- \
  tests/components/AccountClient.test.tsx \
  tests/components/HeaderAccount.test.tsx \
  tests/components/EmailVerificationClient.test.tsx \
  tests/components/AuthForm.test.tsx
```

Run focused browser coverage:

```bash
npm run test:e2e -- \
  apps/web/e2e/public-routes.spec.ts \
  apps/web/e2e/portal-ru.spec.ts \
  apps/web/e2e/auth-legal-links.spec.ts \
  apps/web/e2e/email-verification.spec.ts \
  apps/web/e2e/password-reset.spec.ts \
  apps/web/e2e/account-logout.spec.ts
```

Then:

```bash
npm run typecheck:web
```

**Expected completion**  

- The actual 4F route topology is regression-tested.
- Retired checkout/payment-result routes are proven absent.
- Product/account pages are proven provider-independent and honest about missing future data.
- Core RU desktop/mobile/accessibility behavior has focused evidence.
- Existing auth/reset/verification regressions remain covered without duplicated test architecture.

**Proposed commit**  

```text
ANY-636 cover portal routes states and boundaries
```

---

# Step 5 — Align Current Authority Docs and Publish the 4F Handoff

**Status:** `done`  
**Recommended model:** `Sol`

**Goal**  
Update current-authority documentation to describe this repository as the AnyToolAI Portal, remove the obsolete separate Application Portal assumption, record the final route/data-ownership topology, and leave a durable handoff for provider-backed ANY-504 Steps 6–10 without rewriting accepted historical ADR/design records.

**Scope / affected code**  

Update only current-authority/index/instruction documents whose statements are stale after Steps 1–5. Expected files:

```text
README.md
ARCHITECTURE.md
docs/PRODUCT.md
docs/product/ru-mvp.md
docs/DESIGN.md
docs/design-system/bundle3/README.md
docs/architecture/contours.md
docs/architecture/region-resolver-contract.md
docs/architecture/deployment.md            # only stale naming/topology passages
docs/README.md                              # only if index labels need alignment
apps/web/AGENTS.md                          # only if route/journey wording is stale
```

Do **not** rewrite accepted ADR 0005 or the accepted 2026-09-15 design specs merely to replace the historical “Payments Portal” component name. They remain normative decision records; current docs should explain how their Portal boundary maps to the current AnyToolAI Portal.

**Implementation decisions**  

1. Rename current product/system wording from “Payment(s) Portal” to **AnyToolAI Portal** where the document describes the current repository/product surface.
2. Keep billing-boundary terminology semantically exact:
   - External Billing still owns commercial billing truth;
   - the Portal still owns identity/legal and later projection/reconciliation/recovery/paid-access delivery responsibilities from ADR 0005;
   - Kernel still owns technical product/metric identity, actual usage and quota enforcement.
3. Update the current route inventory to the final 4F topology:

```text
/[locale]
/[locale]/products
/[locale]/products/document-summary
/[locale]/products/prompt-optimizer
/[locale]/account
/[locale]/forgot-password
/[locale]/reset-password
/[locale]/verify-email
canonical RU legal routes
```

Explicitly record that `/auth-checkout` and `/payment-result` were transitional pre-production surfaces and are removed without compatibility routes.
4. Update `docs/product/ru-mvp.md` into the durable as-built 4F product handoff. It must contain a compact version of the ownership/deferred matrix from this plan:
   - Portal current identity/auth/legal;
   - static product presentation;
   - External Billing commercial truth deferred to ANY-504 Step 6+;
   - purchase/Widget deferred to ANY-504 Step 7;
   - provider reconciliation/recovery deferred to ANY-504 Step 8;
   - confirmed paid-access projection deferred to ANY-504 Step 9;
   - actual usage/quota deferred to ANY-504 Step 10.
5. Document explicitly that “not ready/unknown” UI is not evidence of no subscription, no access, or zero usage.
6. Document that the current product slugs are presentation/route identifiers only and are not claimed as authoritative Platform Kernel `product_id` or External Billing IDs.
7. Document that ANY-636 required no new Portal HTTP API because all data it may authoritatively render is either already available through existing generated auth/legal flows or is frontend presentation metadata; future web APIs must still follow the ANY-541 generated-contract boundary.
8. Update Region Resolver topology to remove the obsolete **separate Application Portal** peer assumption. The target user-facing entry is this AnyToolAI Portal plus the Platform Kernel API boundary as appropriate.
9. Because the Region Resolver API schema is still explicitly undefined, update only conceptual ownership/topology wording. Do not invent endpoint fields, environment variable names, URL schema, CORS, cache or redirect behavior.
10. Keep contour isolation and locale orthogonality unchanged. Do not make `/en` a contour or let locale select deployment/data plane.
11. Keep accepted ADR/design documents unchanged unless there is a factual broken link. Current docs may note that the component historically named “Payments Portal” in those accepted records corresponds to the Portal backend boundary implemented here.
12. Update root/current docs to state that the repository is still pre-production and that External Billing/provider-dependent runtime is not implemented yet.
13. Record no-production-compatibility as the reason retired UI routes did not receive redirects; do not generalize this into a permanent rule for future production changes.
14. Do not alter generated docs manually.
15. This is the final step; run the complete 4F verification surface manually after the documentation diff is reviewed.

**Invariants**  

- ADR 0005 and accepted design ownership remain unchanged.
- Current docs, routes and code agree.
- Region Resolver remains a separate service and its API contract remains undefined.
- No separate Application Portal is described as a required peer frontend after 4F.
- Locale remains orthogonal to contour.
- Future billing/access/usage ownership remains deferred to the correct steps.
- No historical accepted architecture is silently rewritten.

**Out of scope**  

- provider/LBX documentation discovered by ANY-634;
- Step 6–10 implementation details not already settled by current authority;
- new Region Resolver API schema;
- repo/package/repository renaming;
- migrations or API changes;
- rewriting historical/superseded docs just for terminology consistency;
- broad documentation cleanup unrelated to the 4F topology.

**AI prompt**  

```text
Implement only Step 5 of ANY-636: align current-authority documentation with the completed AnyToolAI Portal 4F implementation and publish the durable handoff for later ANY-504 steps.

Steps 1–4 are assumed complete and manually verified.

Follow the decisions defined in this prompt. Do not perform broad repository research. Inspect only the final 4F route/code state and these current-authority/index documents where their statements are now stale:

- README.md
- ARCHITECTURE.md
- docs/PRODUCT.md
- docs/product/ru-mvp.md
- docs/DESIGN.md
- docs/design-system/bundle3/README.md
- docs/architecture/contours.md
- docs/architecture/region-resolver-contract.md
- docs/architecture/deployment.md only where naming/topology is stale
- docs/README.md only where index labels are stale
- apps/web/AGENTS.md only where its route/journey wording is stale

Do not redesign the architecture.
Do not perform unrelated documentation cleanup.
Do not work on future steps.

Implement these settled decisions:

1. Current repository/product documentation must describe this system as the AnyToolAI Portal where it describes the current product surface, rather than as a standalone Payments Portal UI.
2. Preserve the ADR 0005 ownership boundary exactly:
   - External Billing owns commercial billing truth/lifecycle;
   - Portal owns identity/legal and the later anti-corruption/projection/reconciliation/recovery/paid-access delivery boundary;
   - Platform Kernel owns technical product/metric identity, actual usage and quota enforcement.
3. Update the as-built route inventory to:
   - /[locale]
   - /[locale]/products
   - /[locale]/products/document-summary
   - /[locale]/products/prompt-optimizer
   - /[locale]/account
   - /[locale]/forgot-password
   - /[locale]/reset-password
   - /[locale]/verify-email
   - canonical RU legal routes.
4. Record that /auth-checkout and /payment-result were transitional pre-production routes and were removed in 4F without redirects because there is no production compatibility obligation.
5. Make docs/product/ru-mvp.md the durable as-built 4F handoff. Include a concise UI/data ownership matrix documenting:
   - current Portal identity/auth/legal sources;
   - frontend-only product presentation;
   - External Billing commercial catalog/pricing/sellability deferred to parent ANY-504 Step 6;
   - purchase/Widget deferred to ANY-504 Step 7;
   - recovery/reconciliation deferred to ANY-504 Step 8;
   - confirmed paid-access state deferred to ANY-504 Step 9;
   - Platform Kernel actual usage/quota deferred to ANY-504 Step 10.
6. State explicitly that UI “not ready/unknown” is not evidence of no subscription, no access or zero usage/quota.
7. State explicitly that document-summary and prompt-optimizer are current presentation/route slugs only, not claimed Platform Kernel product_id or External Billing IDs.
8. Record the ANY-541 rule: any future Portal-owned web-consumed API must start with backend Pydantic, named OpenAPI, repository generation, generated TypeScript wire contracts, and the shared API transport trust boundary. Record that ANY-636 itself required no new API because no additional Portal-owned server fact was needed.
9. Remove the obsolete target assumption that Region Resolver publishes separate “Payment Portal” and “Application Portal” frontend destinations. The user-facing target is this AnyToolAI Portal; Platform Kernel remains a separate API/service boundary.
10. Region Resolver still has no defined API schema. Do not invent fields, environment variables, CORS/cache/redirect details or implementation behavior.
11. Preserve contour isolation and locale orthogonality exactly. Do not describe /en or another locale as a contour.
12. Do not rewrite ADR 0005 or the accepted 2026-09-15 design specs solely to rename the historical component. They are accepted decision records. Current docs may explain that their historically named Payments Portal boundary corresponds to this current Portal backend boundary.
13. Keep the repository explicitly pre-production and provider-independent at the end of 4F. Do not document LBX/provider runtime, commercial catalog, purchase, paid access or usage as implemented.
14. Do not manually edit generated documentation/artifacts.

If the final current code materially contradicts an assumption required by this documentation step, stop and describe the contradiction instead of documenting a false state.

Do not run tests, linters, formatters, type checks, builds, generators, documentation checks or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every documentation file changed;
- summarize the final AnyToolAI Portal topology;
- summarize the final 4F→Steps 6–10 handoff;
- identify every separate-Application-Portal assumption removed;
- confirm accepted ADR/design records were not rewritten merely for naming;
- report the exact final verification commands I should run manually.
```

**Manual verification**  

Run documentation/architecture and generated-contract checks first:

```bash
npm run docs:check
npm run architecture:check
npm run generate:check
```

Run the complete web boundary/component surface:

```bash
npm run test:boundaries:web
npm --workspace @anytoolai/web run test:components
npm run typecheck:web
npm run lint:web
```

Run the focused final browser suite:

```bash
npm run test:e2e -- \
  apps/web/e2e/public-routes.spec.ts \
  apps/web/e2e/portal-ru.spec.ts \
  apps/web/e2e/auth-legal-links.spec.ts \
  apps/web/e2e/email-verification.spec.ts \
  apps/web/e2e/password-reset.spec.ts \
  apps/web/e2e/account-logout.spec.ts \
  apps/web/e2e/locale-routing.spec.ts \
  apps/web/e2e/react-runtime.spec.ts
```

Build and run the normal fast repository gate:

```bash
npm run build:web
npm run check:fast
```

A PostgreSQL-heavy API test pass is not required solely by ANY-636 because this plan changes no backend behavior, persistence, migrations or API contracts. Run the full repository `npm run check` only if normal PR/CI policy requires it beyond the focused 4F verification above.

**Expected completion**  

- Current docs consistently describe the repository as the AnyToolAI Portal.
- The final route topology matches the implementation.
- The separate Application Portal assumption is removed from current target topology without inventing a Resolver API schema.
- The 4F data-ownership/deferred-step handoff is durable and explicit.
- All focused frontend, contract, locale, accessibility, lint, type and build checks pass.
- No backend/persistence/provider behavior was accidentally pulled into 4F.

**Proposed commit**  

```text
ANY-636 align portal docs and future-step handoff
```

---

## Corrective Starting Baseline After Initial Steps 1–5

Steps 1–5 already implemented the following product/auth route baseline and must
not be reimplemented:

```text
/[locale]
/[locale]/products
/[locale]/products/document-summary
/[locale]/products/prompt-optimizer
/[locale]/account
/[locale]/forgot-password
/[locale]/reset-password
/[locale]/verify-email
canonical RU legal routes
```

Settled ANY-636 behavior to preserve:

- `/[locale]/auth-checkout` is removed with no compatibility redirect.
- `/[locale]/payment-result` is removed with no compatibility redirect.
- `/[locale]/account` is the direct signed-out auth entry and authenticated
  cabinet route.
- Header auth modal remains.
- The two frontend presentation products remain `document-summary` and
  `prompt-optimizer`; both already have localized detail routes.
- Current authenticated account behavior already preserves real identity facts,
  email verification, stale-bearer/session race protection, retryable transient
  failure behavior and logout semantics.
- No commerce/provider API, CloudPayments runtime, real commercial catalog,
  paid-access projection or usage/quota runtime exists.
- Existing route/boundary/mobile/accessibility tests are useful evidence, but
  they do not prove the final RU product/visual outcome.

### Required predecessor correction before product/visual work

At planning time for this continuation:

```text
ANY-541 head: bc80eaaee3b0c6051548ff446960791636216436
ANY-636 head: af0ea815cf12d2440bdad6a36d8dbf396e5d9950
relationship: ANY-636 ahead 6 / behind 2
merge base: 3e53f1cc7756cc6825b05b4fcbd580479a196a64
```

The current `ANY-636` tree still carries the **obsolete** pre-final-541 HTTP
contract mechanics in several places, including generated `zod.gen.ts`, Zod
response `safeParse()`, custom email/IDN generator logic, the `zod` frontend
dependency, structural-response rejection tests and documentation that calls
Zod/browser validation part of the authority chain.

Step 6 must merge the current/final `ANY-541` branch into `ANY-636` and resolve
conflicts using these ownership rules:

- **ANY-541 wins** for generated HTTP contract mechanics, shared transport trust
  semantics, boundary guards, generator configuration and 4D architecture
  wording.
- **ANY-636 wins** for its already-completed 4F route retirement, `/account`
  direct auth flow, product routes, product presentation, honest not-ready
  states and Portal topology, except where those files import/use the obsolete
  4D mechanism.
- For files changed by both branches, preserve the 636 product/auth behavior and
  apply the final 541 contract boundary surgically; do not choose an entire side
  blindly.
- A modify/delete conflict for retired checkout/payment-result code resolves to
  the ANY-636 deletion.

Only after Step 6 is complete do Steps 7–13 change the **customer-facing
composition and product UX**.

---

# Corrective Completion — Synchronize Architecture, Then Finish the Actual RU AnyToolAI Portal

## Why Steps 6–13 exist

The initial five steps correctly established route cleanup, direct account auth,
provider-independent boundaries, honest unknown states, regression coverage and
documentation. Two gaps remain:

1. ANY-541 finalized its HTTP trust boundary after the original ANY-636 baseline,
   so the branch must first inherit the final generated-TypeScript/shared-transport
   architecture.
2. The original implementation did not complete the product/visual objective of
   4F because the primary RU mockup was unavailable and the Portal remained too
   account/readiness-centric.

Step 6 closes the predecessor drift. Steps 7–13 finish the product/visual DoD.
The existing 4F product work is reused, not discarded.

### Locked corrective product/visual contract

The following interpretation is fixed for Steps 7–13:

- **RU mockup is the primary product and visual target.** Reproduce its hierarchy, density, palette direction, typography, surface treatment, interaction intent and dashboard/product-card feel where applicable, without importing demo facts or blindly pasting literal inline HTML/CSS.
- **Bundle 3 remains the single implementation design system, but its previous indigo glass/bento visual identity is not immutable.** Step 10 must evolve Bundle 3 so the design system itself encodes the approved RU mockup direction; later UI work consumes those canonical rules/tokens rather than creating local overrides or a second theme.
- **Public Portal is product-first.** Home should lead with the AnyToolAI product value proposition and discovery, not engineering/readiness facts such as region, locale count, canonical legal language or billing migration status.
- **Only current real presentation products are shown.** At the current baseline these are `document-summary` and `prompt-optimizer`. Do not surface Proposal Checker, Scope Guard, “next product”, waitlists or roadmap products merely because they appear in the mockup.
- **Presentation-only pricing navigation is allowed in 4F.** The localized `/[locale]/pricing` placeholder follows the [approved Step 11 decision](#approved-step-11-pricing-placeholder-decision). Actual commercial offers/prices/sellability remain parent ANY-504 Step 6; purchase/provider Widget behavior remains Step 7. The mockup's real tariff composition and purchase CTAs remain deferred.
- **Product cards must not claim runtime availability.** Labels such as “Available”, “Under review”, “Coming soon” are not authoritative unless a current source proves them. Prefer product type/presentation metadata and a neutral detail CTA.
- **Product detail pages are substantial customer-facing screens.** They should use the RU mockup's two-column hero / preview / supporting-content composition where useful, but only with current truthful presentation facts and current safe actions.
- **No install/web-app target is invented.** If there is no authoritative current destination, the page may navigate to account/catalog and show the relevant not-ready state instead.
- **Authenticated cabinet is product-centric.** Identity/account facts are compact supporting content; the primary cabinet content is one card/surface per current product.
- **Future commercial/access/usage integration must fill stable per-product slots rather than require another cabinet redesign.** These slots are frontend-local view composition only, not new wire DTOs or domain models.
- **Per-product missing data stays honest.** Current state may say commercial data not ready, access unknown, usage unavailable. It must never say “no subscription”, “no access”, `0/N`, a plan name or a price without authority.
- **Do not add backend/API/schema work unless a material contradiction proves a genuinely Portal-owned server fact is required.** If that happens, stop and report it for replanning.

---


# Step 6 — Synchronize ANY-636 with the Final ANY-541 API Trust Boundary

> **ANY-636 internal Step 6 — predecessor reconciliation, not parent ANY-504 Step 6.**

**Status:** `pending`  
**Recommended model:** `Sol`

**Goal**  
Bring the already-implemented ANY-636 branch onto the final/current ANY-541 / PR
#129 architecture **without discarding or reimplementing Steps 1–5**. Preserve
all 636 product/auth behavior while replacing the obsolete generated-Zod / second
browser runtime-validation mechanism with the final generated-TypeScript / single
shared-transport trust boundary.

**Why this is a separate step**  

At planning time the branches are genuinely divergent:

```text
ANY-541: bc80eaaee3b0c6051548ff446960791636216436
ANY-636: af0ea815cf12d2440bdad6a36d8dbf396e5d9950
merge base: 3e53f1cc7756cc6825b05b4fcbd580479a196a64
ANY-636 relative to ANY-541: ahead 6 / behind 2
```

The two missing ANY-541 commits intentionally changed 4D semantics. This cannot
be deferred to the documentation/final-review step because product/account code
in later steps consumes the inherited API boundary.

If `ANY-541` has advanced by execution time, use its **current reviewed head**
provided the target semantics above are unchanged; do not pin implementation to
an obsolete SHA merely to match this planning observation.

**Branch integration strategy**  

Use a **merge of current `ANY-541` into existing `ANY-636`**, rather than
recreating or rebasing away the completed 636 history. The goal is to preserve
the existing Step 1–5 commits and make the branch graph inherit the final
predecessor.

The merge/index mechanics are the only exception in this plan to the normal
"do not stage" rule. Do not create the merge commit or push it from the execution
model; leave the resolved merge for manual review/commit.

Suggested preparation:

```bash
git fetch origin
git switch ANY-636
git status --short
git merge --no-commit --no-ff origin/ANY-541
```

Start only from a clean working tree. If Git reports conflicts, resolve them
using the ownership rules below. Staging conflict resolutions is allowed only as
required to complete the pending merge. Do not stage unrelated files.

**Expected conflict/ownership rules**  

1. **Final ANY-541 wins completely for the HTTP contract mechanism:**
   - `apps/web/src/shared/api/transport.ts` exists and owns the only successful
     HTTP JSON read/trust assertion;
   - generated contracts are TypeScript wire contracts (`types.gen.ts` / generated
     exports), not generated Zod response schemas;
   - `apps/web/src/shared/api/auth.ts` consumes generated TypeScript types and
     delegates HTTP JSON handling to shared `getJson<T>` / `postJson<T>`;
   - generator configuration emits TypeScript wire contracts and contains no
     custom email/IDN Zod semantics;
   - frontend `zod` dependency is removed when no other valid consumer exists;
   - `zod.gen.ts` is removed;
   - boundary guards enforce exactly one HTTP JSON trust point.
2. **ANY-636 wins for completed 4F behavior:**
   - `/auth-checkout` and `/payment-result` stay deleted;
   - `/account` remains the direct signed-out auth + authenticated account route;
   - current session race/401/transient-error/retry/logout behavior remains;
   - product routes and `document-summary` / `prompt-optimizer` presentation stay;
   - provider-independent not-ready/unknown semantics stay.
3. For `AccountClient.tsx`, preserve the richer ANY-636 behavior/layout state but
   import `SessionUserResponse` from the final generated TypeScript contract,
   not `zod.gen.ts`.
4. A modify/delete conflict for retired checkout/payment-result files resolves to
   **deletion**. Do not resurrect them merely because ANY-541 changed them before
   636 removed them.
5. For `ARCHITECTURE.md`, `apps/web/AGENTS.md`,
   `docs/engineering/CODING_CONVENTIONS.md`, `docs/PRODUCT.md` and
   `docs/product/ru-mvp.md`, preserve the 636 Portal topology/product handoff but
   replace every active 4D statement with the final ANY-541 authority chain.
6. Do not manually edit generated output to resolve semantics. Resolve generator
   configuration/source first, then refresh generated artifacts through the
   repository generation command if the merge result is stale.

**Final contract that must exist after the step**  

```text
FastAPI / Pydantic
  → app.openapi()
  → OpenAPI
  → generated TypeScript wire contracts
  → shared API transport trust boundary
  → endpoint adapters
  → frontend consumers / view state
```

Runtime semantics:

```text
successful response
→ response.json()
→ unknown
→ one audited payload-as-T trust assertion in shared/api/transport.ts
→ generated TypeScript response type
→ endpoint adapter / frontend consumer
```

- invalid successful JSON **syntax** → `ApiContractError`;
- syntactically valid but structurally unexpected successful JSON is **not**
  revalidated by a second browser schema authority;
- backend Pydantic/FastAPI remains runtime validation authority.

**Scope / affected code**  

The merge determines the exact file set. Inspect at minimum:

```text
apps/web/package.json
package-lock.json
scripts/generate-api-contracts.mjs
apps/web/src/generated/api-contracts/
apps/web/src/shared/api/transport.ts
apps/web/src/shared/api/auth.ts
apps/web/src/features/account/AccountClient.tsx
apps/web/src/features/email-verification/EmailVerificationClient.tsx
apps/web/src/shared/ui/HeaderAccount.tsx
apps/web/eslint.config.mjs
apps/web/tests/components/AuthContractValidation.test.ts
apps/web/tests/eslint-boundaries.test.mjs
ARCHITECTURE.md
apps/web/AGENTS.md
docs/engineering/CODING_CONVENTIONS.md
docs/PRODUCT.md
docs/product/ru-mvp.md
this active ANY-636 implementation plan if repository-local wording is stale
```

Also inspect every merge conflict and every remaining production/test/doc
reference to `zod.gen`, generated Zod HTTP response validation, response
`safeParse`, or "runtime-validate successful JSON".

**Implementation decisions**  

1. Do not change FastAPI/Pydantic endpoints, schemas or business behavior in this
   step; the predecessor correction is frontend contract generation/transport
   semantics and their guards/docs.
2. Keep request construction typed from generated TypeScript request contracts.
3. Keep `ApiError.detail` as `unknown` and preserve stable `apiErrorCode()`
   extraction semantics.
4. Preserve current Sentry privacy behavior and sanitized `ApiContractError`
   reporting. Do not restore raw payload/validation-data reporting.
5. Replace structural-invalid-response tests that existed only to prove browser
   Zod validation. In particular, tests that expect invalid email/UUID/missing
   response fields to become `ApiContractError` are obsolete under the final
   trust decision.
6. Retain focused coverage that proves:
   - valid adapters map requests/responses as expected;
   - malformed successful JSON syntax becomes `ApiContractError`;
   - stable API errors remain stable/private;
   - one shared HTTP JSON trust point exists;
   - features/UI/adapters cannot create a second Fetch/Response JSON trust point;
   - generated contract freshness is owned by `generate:check`.
7. Remove `zod` only if the final merged repository has no unrelated legitimate
   consumer. Current ANY-541 indicates it should be absent from the web runtime.
8. Do not touch product composition/mockup work in this step except where a file
   needs a narrow conflict resolution to preserve current 636 behavior.
9. Do not add new backend APIs, billing/provider behavior, product identity,
   access or usage data.

**Invariants**  

- Initial ANY-636 Steps 1–5 remain functionally intact.
- Final ANY-541 HTTP authority is inherited exactly once.
- No generated Zod HTTP response authority remains.
- No handwritten backend wire DTO/structural response decoder is introduced.
- No second `response.json()`/Fetch JSON trust path appears in production
  adapters/features/UI.
- `generate:check` owns generated-artifact freshness.
- No product/billing/access/usage scope is added.

**Out of scope**  

- RU mockup/public-shell redesign (Step 7);
- substantial product pages (Step 8);
- product-centric cabinet redesign (Step 9);
- Bundle 3 RU visual-language recalibration (Step 10);
- Portal-wide application of the recalibrated visual system (Step 11);
- product/visual acceptance screenshots (Step 12);
- final 4F handoff/closure (Step 13);
- parent ANY-504 Step 5+ implementation.

**AI prompt**  

```text
Implement only ANY-636 Step 6: synchronize the existing ANY-636 branch with the final/current ANY-541 / PR #129 API contract architecture.

Do not recreate or reset ANY-636. Steps 1–5 are completed and must be preserved.

This step is the one exception to the normal no-staging rule because it must integrate the predecessor branch. Start from a clean ANY-636 worktree, fetch origin, then merge current origin/ANY-541 into ANY-636 with --no-commit --no-ff. Do not create the merge commit and do not push.

Resolve conflicts using these authorities:
- ANY-541 wins for generated HTTP wire-contract generation, shared/api/transport.ts, one successful-JSON trust point, boundary guards, and contract-architecture wording.
- ANY-636 wins for retired /auth-checkout and /payment-result routes/features, direct /account auth behavior, existing session/race/retry/logout behavior, current product routes/presentation, and provider-independent not-ready states.
- For files changed by both, preserve 636 behavior while applying the final 541 contract mechanism surgically. Do not take an entire side blindly.

Required final HTTP chain:
FastAPI/Pydantic -> OpenAPI -> generated TypeScript wire contracts -> shared API transport trust boundary -> endpoint adapters -> frontend consumers.

Pydantic/FastAPI is the only runtime structural validation authority. Successful same-service JSON is read as unknown and trusted once in shared/api/transport.ts. Invalid JSON syntax remains ApiContractError. Do not preserve generated Zod response schemas, safeParse response validation, custom email/IDN generator semantics, handwritten backend wire DTOs, or another runtime schema authority.

Preserve all completed ANY-636 route/auth/product behavior. A modify/delete conflict on checkout/payment-result resolves to deletion.

After resolving the merge, search active production/tests/current docs for stale zod.gen, safeParse response validation, "generated Zod runtime validation", or instructions to structurally runtime-validate successful API JSON. Remove/correct active stale references. Historical explanation may mention that the old mechanism was superseded.

Do not work on the RU mockup/UI redesign in this step.
Do not add backend/API/schema/provider/billing/access/usage behavior.
Do not create commits or push. Merge-related staging required to resolve conflicts is allowed; do not stage unrelated files.

After implementation:
- report the predecessor and ANY-636 heads used;
- report all merge conflicts and how each was resolved;
- report every changed/added/deleted contract-related file;
- confirm zod.gen and browser structural response validation are gone;
- confirm /auth-checkout and /payment-result remain gone;
- confirm /account auth/session behavior and product routes remain;
- list exact manual verification commands I should run;
- report whether the merge is ready for my review/commit.
```

**Manual verification**  

First inspect the merge result:

```bash
git status
git diff --check
git diff --cached --check
git grep -n -E 'zod\.gen|generated Zod runtime validation|runtime-validate successful JSON|safeParse\(' -- \
  ':!docs/exec-plans/completed/**' \
  ':!docs/exec-plans/active/ANY-636-implementation-plan.md'
```

The grep may return unrelated legitimate `safeParse` uses only if they are not
HTTP successful-response structural validation; review any hit rather than
blanket-removing it.

Run generation/contract/boundary checks:

```bash
npm run generate:check
npm run test:boundaries:web
npm --workspace @anytoolai/web run test:components -- \
  tests/components/AuthContractValidation.test.ts \
  tests/components/AccountClient.test.tsx \
  tests/components/HeaderAccount.test.tsx \
  tests/components/EmailVerificationClient.test.tsx \
  tests/components/AuthApiError.test.ts
npm run typecheck:web
npm run lint:web
npm run build:web
```

Then run the focused browser regressions most exposed to the merge:

```bash
npm run test:e2e -- \
  apps/web/e2e/auth-legal-links.spec.ts \
  apps/web/e2e/email-verification.spec.ts \
  apps/web/e2e/password-reset.spec.ts \
  apps/web/e2e/account-logout.spec.ts \
  apps/web/e2e/portal-ru.spec.ts \
  apps/web/e2e/react-runtime.spec.ts
```

Before the manual merge commit, confirm `git rev-parse MERGE_HEAD` is the ANY-541 head used for this step. After you create the reviewed merge commit, confirm that head is an ancestor of ANY-636, for example with `git merge-base --is-ancestor <ANY-541-head> HEAD`, and that the branch no longer reports itself behind that predecessor head.

**Expected completion**  

- Existing ANY-636 product/auth work is preserved.
- The branch now inherits the final reviewed ANY-541 predecessor instead of
  remaining two commits behind it.
- `shared/api/transport.ts` is the single successful same-service HTTP JSON
  trust boundary.
- Generated TypeScript owns compile-time wire contracts; Pydantic/FastAPI owns
  runtime structural validation.
- `zod.gen.ts`, the web Zod response-validation dependency/path and custom
  email/IDN generator workaround are gone.
- Structural-invalid-success-response tests no longer encode the rejected second
  runtime authority.
- Current docs/agent rules describe the same final architecture.
- No route/product/provider/business behavior changed unintentionally.

**Proposed commit**  

Because this step is a predecessor merge, preserve the merge relationship. A
suitable manually-created merge commit message is:

```text
ANY-636 sync final ANY-541 API trust boundary
```

---

# Step 7 — Rebuild the RU Public Shell, Home and Catalog from the Actual Mockup Direction

> **ANY-636 internal Step 7 — not parent ANY-504 Step 7.**

**Status:** `pending`  
**Recommended model:** `Sol`

**Goal**  
Replace the technically-correct but transitional public composition with the real RU AnyToolAI Portal product experience: mockup-grounded navigation, hero, product discovery and catalog presentation, while preserving all provider-independent boundaries from Steps 1–5.

**Required reference**  

Before editing, inspect:

```text
portal-ru-anytools.html
```

The execution model must specifically compare the current `/ru` and `/ru/products` surfaces with the RU mockup's:

```text
sticky/top navigation
centered hero hierarchy
product-group/discovery composition
product-card density/hierarchy
mobile collapse behavior
footer rhythm
```

Do not copy demo stats, pricing or provider/legal claims from the HTML.

**Scope / affected code**  

Expected primary surfaces:

```text
apps/web/src/shared/ui/SiteShell.tsx
apps/web/src/app/[locale]/page.tsx
apps/web/src/app/[locale]/products/page.tsx
apps/web/src/features/catalog/ProductOverview.tsx
apps/web/src/features/catalog/catalog.ts              # presentation metadata only if required
apps/web/src/messages/{en,fr,it,de,es,ru,pt}.json
apps/web/src/app/globals.css
apps/web/src/app/catalog.css
apps/web/src/app/responsive.css
apps/web/src/app/account.css                          # only shared shell selectors if genuinely needed
```

Touch direct tests only when current assertions become stale; focused corrective E2E expansion is Step 12.

**Implementation decisions**  

1. Preserve current route topology from Steps 1–5 and do not resurrect checkout/payment-result routes. The original Step 7 instruction "Do not add a `/pricing` route" is historical and superseded only by the [approved Step 11 presentation-only placeholder](#approved-step-11-pricing-placeholder-decision).
2. Rework `SiteShell` visual/navigation composition to match the RU mockup direction using Bundle 3 primitives/tokens:
   - clear AnyToolAI brand;
   - product discovery as the primary public navigation concern;
   - existing locale switcher retained;
   - existing `HeaderAccount` auth behavior retained;
   - historical Step 7 restriction: do not add “Pricing” until authoritative commercial catalog/purchase work exists; superseded only for the [approved Step 11 placeholder navigation entry](#approved-step-11-pricing-placeholder-decision).
3. Rebuild `/[locale]` so the hero reads as a customer product entry, not a platform/readiness dashboard.
4. Remove or demote home content whose primary purpose is exposing engineering/system facts rather than helping a customer choose/use a product, including region/locale/legal-language style statistics when they dominate the hero.
5. Do not replace removed statistics with mockup numbers such as `200k+`, `10`, or `2 / month`.
6. Use the mockup's product-discovery rhythm (group/collection framing + cards) but only with products that are actually present in current Portal presentation metadata.
7. `AI utilities` may be used as UI taxonomy for the current two products if it fits the RU composition. Do not show `For freelancers` as if it contained released/current products when the current presentation catalog has none. A taxonomy label must not invent a roadmap/product fact.
8. Product cards must expose current truthful presentation facts only:
   - product name;
   - current product type such as Chrome Extension where already established;
   - current approved description;
   - neutral “Learn more”/detail navigation.
9. Remove misleading card/status affordances that look like authoritative runtime/commercial availability when no source exists. Do not copy “Available”, “Under review”, “Coming soon”, install targets, web-app targets or waitlist actions from the mockup without an authoritative current destination/state.
10. Keep public purchase unavailable semantics honest, but do not make “billing not ready” a primary marketing fact repeated across the whole page. Show it only where a user would otherwise expect a purchase/commercial action.
11. Keep current footer legal/operator facts sourced from existing authoritative data/components. Do not copy `CloudPayments`, placeholder INN, hosting/location, or FZ-152 claims from the mockup.
12. Keep all ordinary copy in exact seven-locale key/ICU-signature parity; RU remains the visual acceptance target.
13. Preserve keyboard navigation, focus styles, semantic heading order and responsive behavior.
14. Do not change auth/session/reset/verification semantics, the final ANY-541 generated-TypeScript/shared-transport contract boundary, backend APIs or database state.

**Invariants**  

- Bundle 3 remains the design implementation authority.
- RU mockup defines composition/product hierarchy, not business facts.
- Existing locale routing and HeaderAccount behavior remain intact.
- Only current presentation products appear as current products.
- No pricing, purchase, provider, access or usage truth is invented.
- No new backend request is introduced for the public surface.

**Out of scope**  

- product-detail redesign (Step 8);
- authenticated cabinet redesign (Step 9);
- design-system visual recalibration (Step 10);
- Portal-wide visual application (Step 11);
- visual acceptance E2E/screenshots (Step 12);
- documentation correction/final handoff (Step 13);
- parent ANY-504 commercial Step 6 or purchase Step 7.

**AI prompt**  

```text
Implement only ANY-636 Step 7: rebuild the RU public shell, home and catalog from the actual portal-ru-anytools.html visual/product direction while preserving the existing provider-independent foundation.

Required input before editing:
- this updated ANY-636 implementation plan;
- portal-ru-anytools.html located beside the plan (or at the exact path supplied by me).

Step 6 architecture synchronization is assumed complete and manually verified. Steps 1–5 remain preserved.

First inspect the current SiteShell, /[locale] home, /[locale]/products catalog, current product presentation metadata/messages/CSS, and the RU mockup. Compare composition only: navigation, hero, grouping, card hierarchy, spacing/density, mobile behavior and footer rhythm.

Implement the locked decisions from Step 7. In particular:
- keep the current routes and current auth/locale behavior;
- make the public Portal product-first rather than readiness/system-fact-first;
- use the RU mockup composition through Bundle 3, not by pasting its CSS;
- show only the current real presentation products document-summary and prompt-optimizer;
- do not copy pricing, 200k+, 10 products, 2/month, CloudPayments, product availability labels, fake roadmap products, install/web-app targets, quota/usage or other demo facts;
- historical Step 7 restriction: no /pricing route or pricing CTA; superseded only by the approved Step 11 presentation-only placeholder/navigation decision above, with actual commercial/purchase behavior still deferred;
- no new backend/API/OpenAPI/generated-contract/schema work.

The mockup reference is input-only. Do not modify, stage or commit it.

Do not run tests, linters, formatters, type checks, builds or generators.
Do not stage files.
Do not create commits.

After implementation:
- report every changed file;
- summarize the final home/navigation/catalog composition;
- list every mockup element intentionally NOT copied because it lacks authority;
- confirm no future-step data/API/provider behavior was introduced;
- report exact manual verification commands I should run.
```

**Manual verification**  

Run:

```bash
node --test \
  apps/web/tests/i18n-contract.test.mjs \
  apps/web/tests/app-metadata.test.mjs
npm run typecheck:web
npm run lint:web
```

Then manually inspect at desktop and phone widths:

```text
/ru
/ru/products
/en
/pt/products
```

Compare `/ru` and `/ru/products` side-by-side with `portal-ru-anytools.html` for hierarchy/composition, while confirming no demo stats/prices/provider claims leaked into production.

**Expected completion**  

- Public Portal visually/product-wise reads as the RU AnyToolAI product entry rather than the old transitional readiness page.
- Home and catalog clearly lead the user toward the two actual products.
- The composition visibly follows the RU mockup direction without copying unverified facts.
- Existing auth/i18n/provider boundaries remain intact.

**Proposed commit**  

```text
ANY-636 align public portal with RU product direction
```

---

# Step 8 — Build Substantial RU Product Screens on the Mockup Composition

> **ANY-636 internal Step 8 — not parent ANY-504 Step 8.**

**Status:** `pending`  
**Recommended model:** `Sol`

**Goal**  
Turn the current thin detail cards into real customer-facing product screens that follow the RU mockup's product-page composition while using only current truthful presentation facts and safe current actions.

**Required reference**  

Inspect the RU mockup's `PRODUCT RU` section before editing. Use its two-column hero, preview/supporting-content rhythm and product-specific focus as the composition reference.

**Scope / affected code**  

Expected primary surfaces:

```text
apps/web/src/app/[locale]/products/[product]/page.tsx
apps/web/src/features/catalog/catalog.ts
apps/web/src/features/catalog/                     # product presentation/view components as needed
apps/web/src/messages/{en,fr,it,de,es,ru,pt}.json
apps/web/src/app/catalog.css
apps/web/src/app/responsive.css
apps/web/src/app/globals.css                        # only shared selectors if required
```

**Implementation decisions**  

1. Keep the two current localized routes and unknown-slug `notFound()` behavior.
2. Replace the single generic detail card with a substantial product page inspired by the RU mockup:
   - back navigation / product taxonomy context;
   - product type/category eyebrow;
   - product name/title;
   - current truthful description/value proposition;
   - safe primary/secondary action area;
   - a visual preview/illustration region that is clearly presentation, not runtime state;
   - supporting product information sections only where current facts support them.
3. Do not copy unverified mockup claims such as:
   - “free” unless a current authoritative product policy says so;
   - “data does not leave the browser”;
   - “nothing is stored on servers”;
   - “52 languages”;
   - “a ChatGPT account is not required”;
   - installation/web-app availability without an authoritative destination.
4. Do not invent Chrome Web Store URLs, web execution URLs, Kernel URLs or provider/purchase destinations.
5. Keep the current product type (`Chrome Extension`) only because it already exists in current presentation metadata. If another type is not current authority, omit it.
6. Safe current actions are limited to Portal-owned navigation such as account/sign-in and back-to-catalog/detail navigation. Do not label account navigation as purchase, install or launch.
7. Add a compact per-product readiness/presentation area only when it improves the product journey. It may expose frontend-local states such as `commercial information not ready`, `access status unavailable`, or `usage unavailable`, but must not imitate future backend wire models.
8. Prefer one reusable product-presentation component/data structure for the two pages where it naturally reduces duplication. Do not introduce speculative generic product frameworks or domain abstractions.
9. Ensure responsive behavior follows the mockup intent: two-column desktop composition becomes a clear single-column mobile flow without horizontal overflow.
10. Keep metadata/i18n behavior and seven-locale parity unchanged.
11. No backend/API/schema/provider work.

**Invariants**  

- Product slugs remain presentation-only.
- Product pages do not claim commercial/access/usage authority.
- No product execution target is invented.
- Product preview content is presentation, not simulated application output.
- Existing account/auth/legal behavior is unchanged.

**Out of scope**  

- actual Chrome Web Store integration;
- actual web-product execution/onboarding/result flows;
- pricing/purchase;
- paid-access reads;
- usage/quota reads;
- cabinet redesign;
- parent ANY-504 Steps 6–10.

**AI prompt**  

```text
Implement only ANY-636 Step 8: replace the thin product-detail cards with substantial RU AnyToolAI product screens grounded in the PRODUCT RU composition of portal-ru-anytools.html.

Steps 6–7 are assumed complete and manually verified. Continue from the current ANY-636 branch.

Before editing, inspect:
- portal-ru-anytools.html PRODUCT RU section;
- current /[locale]/products/[product] page;
- current catalog presentation metadata/messages/CSS.

Use the mockup for composition only: two-column hero, product focus, preview/supporting content and responsive collapse. Do not copy demo business/privacy/product claims.

Keep exactly the current two presentation products and routes. Preserve unknown-product notFound behavior.

Do not invent install URLs, web-app execution URLs, prices, free-plan claims, access, subscription, usage/quota, provider facts, 52-language/privacy claims or other unsupported mockup content.

Use only current truthful presentation facts and safe Portal navigation actions. Keep seven-locale parity and Bundle 3.

The mockup reference is input-only. Do not modify, stage or commit it.

Do not run tests, linters, formatters, type checks, builds or generators.
Do not stage files.
Do not create commits.

After implementation:
- report every changed/new file;
- describe the final product page composition;
- list every mockup claim/control intentionally omitted or replaced and why;
- confirm no runtime product target or future-step authority was invented;
- report exact verification commands.
```

**Manual verification**  

Run:

```bash
node --test apps/web/tests/i18n-contract.test.mjs
npm run typecheck:web
npm run lint:web
```

Manually inspect desktop/mobile:

```text
/ru/products/document-summary
/ru/products/prompt-optimizer
/en/products/document-summary
```

Confirm unknown product slugs remain 404 and each product page is meaningfully more than a repeated catalog card.

**Expected completion**  

- Each current product has a real customer-facing page aligned with the RU mockup composition.
- Product pages remain truthful despite absent commercial/access/usage sources.
- Later product execution/purchase integration can attach to a stable screen rather than replace it.

**Proposed commit**  

```text
ANY-636 build RU product detail experience
```

---

# Step 9 — Rebuild the Authenticated Cabinet Around Per-Product State

> **ANY-636 internal Step 9 — not parent ANY-504 Step 9.**

**Status:** `pending`  
**Recommended model:** `Sol`

**Goal**  
Correct the account-centric cabinet from initial Step 3 into a product-centric Portal cabinet: compact identity/account context plus one stable state surface per current product, ready for later authoritative commercial/access/usage data without another structural redesign.

**Required reference**  

Inspect the RU mockup's `LK RU` section before editing. Reuse its dashboard/product-card hierarchy and responsive cabinet feel, but do not copy its subscription banner, prices, payment method/provider, usage bars, renewal date or unsupported navigation destinations.

**Scope / affected code**  

Expected primary surfaces:

```text
apps/web/src/features/account/AccountClient.tsx
apps/web/src/app/[locale]/account/page.tsx              # only composition/provider messages if needed
apps/web/src/features/catalog/catalog.ts                # presentation metadata only if needed
apps/web/src/features/account/                          # small local presentation components/view state if justified
apps/web/src/messages/{en,fr,it,de,es,ru,pt}.json
apps/web/src/app/account.css
apps/web/src/app/catalog.css
apps/web/src/app/responsive.css
```

Direct component tests may be updated where current assumptions become stale; complete corrective E2E coverage belongs to Step 12.

**Implementation decisions**  

1. Preserve all Step 2 session/auth/retry/logout behavior exactly.
2. Signed-out `/account` remains the direct login/registration surface. Do not turn it into a mock dashboard.
3. For authenticated users, make identity/account data compact supporting context rather than the main dashboard content.
4. The primary authenticated section becomes **per-product cards/surfaces** for the two current presentation products.
5. Each product surface should reserve explicit presentation slots for the concepts later steps will authoritatively fill:

```text
product presentation
commercial state / offer readiness
paid-access state
usage / quota state
action state
```

These are frontend-local view composition states only. Do not create backend-like `Subscription`, `Plan`, `Entitlement`, `Allowance`, `Usage`, `Quota` or provider DTOs.
6. Current default rendering before parent Steps 6/9/10 must be honest and per-product, for example:
   - commercial: information/offer not ready;
   - access: authoritative status unavailable/unknown;
   - usage: data unavailable;
   - action: safe detail/account navigation only.
7. Remove the current global three-card `Access / Billing / Usage` readiness grid if the same information becomes clearer and more future-proof inside each product card. Do not keep both representations just for compatibility.
8. Do not show mockup values or controls such as `Pro`, `490 ₽/month`, renewal date, `320/500`, `3/10`, usage bars, “Manage subscription”, CloudPayments, payment method or active-subscription banners.
9. Do not claim a product is free, paid, active, inactive, available or unavailable unless current authority proves that exact state.
10. Product cards may navigate to their current product-detail routes. Do not invent execution/purchase/self-service destinations.
11. Keep `email_verified` and `EmailVerificationPending` behavior authoritative and visible where appropriate without letting it dominate product state.
12. A session/API error remains distinct from product-state unknown. Never map a session/read error to “no access” or “no subscription”.
13. Keep responsive/mobile cabinet behavior usable. The mockup's left sidebar is a composition reference; do not create meaningless routes/tabs solely to imitate it. If an aside/navigation is used, it must point to real current sections/routes.
14. Keep seven-locale parity and Bundle 3.
15. No new network calls beyond existing auth/session/verification/logout behavior.

**Invariants**  

- Session identity remains generated-contract authority only.
- Missing product data remains unknown/not-ready, never negative/zero.
- Product-centric composition is stable for future parent ANY-504 integrations.
- No provider/commercial/access/usage backend authority is introduced.
- No fake navigation destination is introduced.

**Out of scope**  

- real commercial offers/prices;
- purchase/Widget;
- provider subscription recovery;
- paid-access projection;
- actual usage/quota;
- billing self-service;
- profile schema expansion;
- new backend APIs.

**AI prompt**  

```text
Implement only ANY-636 Step 9: rebuild the authenticated /account cabinet around each current product while preserving all existing auth/session/security behavior.

Steps 6–8 are assumed complete and manually verified.

Before editing, inspect:
- portal-ru-anytools.html LK RU section;
- current AccountClient/auth/session behavior and tests;
- current product presentation metadata.

Use the mockup for cabinet composition only. Do not copy its active subscription, Pro plan, 490 RUB, renewal date, usage bars, 320/500, 3/10, CloudPayments, payment method, manage-subscription control or unsupported sidebar destinations.

Keep signed-out /account as the current direct auth page.

For authenticated users:
- make identity compact supporting context;
- make the main cabinet product-centric;
- render one surface per current product;
- expose local presentation slots for commercial readiness, access, usage/quota and action;
- keep current missing data honest per product;
- remove the old global Access/Billing/Usage readiness grid if replaced by the per-product composition;
- do not create future backend DTOs or new network calls.

Preserve email verification, session race/error/retry, logout and generated-contract behavior exactly.

The mockup reference is input-only. Do not modify, stage or commit it.

Do not run tests, linters, formatters, type checks, builds or generators.
Do not stage files.
Do not create commits.

After implementation:
- report every changed/new/deleted file;
- describe the final authenticated cabinet hierarchy;
- list the per-product slots and what each may claim today;
- confirm the old global readiness layout was retained or removed and why;
- confirm no new billing/access/usage/provider request/model was introduced;
- report exact verification commands.
```

**Manual verification**  

Run:

```bash
npm --workspace @anytoolai/web run test:components -- \
  tests/components/AccountClient.test.tsx \
  tests/components/HeaderAccount.test.tsx \
  tests/components/EmailVerificationClient.test.tsx
node --test apps/web/tests/i18n-contract.test.mjs
npm run typecheck:web
npm run lint:web
```

Manually verify `/ru/account` at desktop/mobile for:

```text
signed out
authenticated + verified email
authenticated + unverified email
session read failure + retry
```

**Expected completion**  

- Cabinet is visibly organized around products, not around three global technical readiness categories.
- Each product has stable slots later parent Steps 6/9/10 can populate without structural redesign.
- Current missing data remains honest.
- Existing auth/security behavior is unchanged.

**Proposed commit**  

```text
ANY-636 make portal cabinet product centric
```

---

# Step 10 — Recalibrate Bundle 3 to the Approved RU Portal Visual Language

> **ANY-636 internal Step 10 — design-system authority correction, not parent ANY-504 Step 10.**

**Status:** `pending`  
**Recommended model:** `Sol`

**Goal**  
Resolve the visual-authority conflict exposed after Step 9. Keep Bundle 3 as the **single** AnyToolAI Portal design system, but deliberately evolve its canonical visual rules/tokens from the older indigo glass/bento treatment to the approved RU mockup language so later UI work can follow the mockup without fighting repository instructions.

This step defines and encodes the design-system target. It does **not** redesign product/auth/business semantics and does not copy demo facts from the mockup.

**Required reference**  

Inspect side-by-side before editing:

```text
portal-ru-anytools.html
current docs/DESIGN.md
current docs/design-system/bundle3/*
current apps/web/AGENTS.md
```

Use the mockup's CSS and rendered surfaces as design evidence, especially its shared root palette/typography plus public navigation/cards and `LK RU` dashboard treatment. The relevant visual direction includes:

```text
deep navy page background
flat/opaque dark-blue surfaces
thin blue borders
amber primary accent
restrained indigo as a secondary accent only
compact 8–16px radii
compact typography/spacing
minimal shadow/glow
little/no glass blur except where the mockup actually uses it
Plus Jakarta Sans visual direction
220px-class dashboard rail + flat workspace on desktop
```

The mockup's tariffs, provider names, usage values, subscription facts, roadmap products and legal/privacy claims remain non-authoritative.

**Scope / affected code/docs**  

Expected design-system authority files:

```text
docs/DESIGN.md
docs/design-system/bundle3/README.md
docs/design-system/bundle3/SKILL.md
docs/design-system/bundle3/web.md
docs/design-system/bundle3/PROMPT_SNIPPET.md
docs/design-system/bundle3/tokens.json
apps/web/AGENTS.md
apps/web/src/app/tokens.generated.css          # generated only through the existing generator when tokens change
this active ANY-636 implementation plan        # status/evidence only if needed
```

Do **not** perform page-specific CSS/TSX redesign in this step. That is Step 11.

**Implementation decisions**  

1. **Preserve Bundle 3 as the only design-system authority.** Do not create `Bundle 4`, a page-local theme, a second token file or cabinet-only replacement system.
2. Replace the obsolete mandatory visual identity that currently requires indigo radial glows, translucent glass cards, blur-heavy bento surfaces, large radii and gradient primary actions. Those rules conflict with the approved RU visual target and must no longer be mandatory Portal styling.
3. Translate the mockup's shared visual palette into canonical Bundle 3 semantics. The target values/direction should be based on the mockup's actual shared variables, including:

```text
page background        #07101f
surface level 1        #0d1929
surface level 2        #122035
surface level 3        #1a2d45
border                 #1e3250
primary amber          #f59e0b
amber text/highlight   #fcd34d
success                #10b981
primary text           #f0f4ff
secondary text         #8ba3c0
tertiary text          #4a6480
secondary indigo       #6366f1 / #818cf8 only where justified
```

Map these values onto stable semantic Bundle 3 token names rather than exposing mockup variable names (`--s1`, `--amber`, etc.) to application code.
4. Recalibrate radii/component treatment toward the mockup: compact buttons/controls, roughly `8–12px` common radii and `12–16px` cards/panels unless a specific component needs otherwise. Remove the old rule that all major Portal cards must read as large glass/bento tiles.
5. Recalibrate surfaces: flat/opaque dark surfaces with thin borders are normal and approved. Blur/glass is optional and restrained; navigation may use the mockup-like subtle backdrop treatment, but the design system must not require blur for every elevated surface.
6. Recalibrate primary actions: amber can be the flat primary accent where the mockup uses it. Remove the old prohibition against flat primary accents and the requirement for an indigo gradient/glow on every primary action.
7. Recalibrate page background: a flat deep-navy Portal background is valid. Remove the old requirement that every page must contain layered radial glows.
8. Recalibrate typography to the mockup direction, including Plus Jakarta Sans as the target Portal family unless current repository/font-loading constraints reveal a concrete blocker. Do not add a remote CSS `@import` merely because the HTML mockup uses one; Step 11 must use the repository's approved font-loading mechanism.
9. Capture both public and application/dashboard layout guidance in Bundle 3:
   - public Portal: compact sticky nav, centered hero, flat product cards, restrained section rhythm;
   - authenticated application: narrow supporting rail + wide workspace, compact section labels and product surfaces;
   - both share one palette/typography/component language.
10. Keep accessibility rules strong: visible focus, semantic controls, sufficient contrast, keyboard usability, responsive single-column collapse, and no color-only state meaning.
11. Update `docs/DESIGN.md` so it no longer claims the current Portal is defined by the old indigo glass/bento appearance. State that the approved RU mockup is the product/visual target and Bundle 3 is the canonical implementation encoding of that target.
12. Update `apps/web/AGENTS.md` so UI work is no longer instructed to preserve legacy glass/bento patterns. Agents must use the current Bundle 3 tokens/rules and the approved mockup for affected visual surfaces.
13. If `tokens.json` changes, refresh `tokens.generated.css` only through the existing repository generator. Do not hand-edit generated token output.
14. Do not change route topology, React composition, auth/session behavior, product state semantics, locale behavior, backend APIs, database state or future billing/access/usage ownership.
15. Do not copy mockup business/runtime facts into the design system. Design tokens/components must contain no provider/tariff/subscription/product-state assumptions.

**Invariants**  

- Bundle 3 remains the only Portal design system.
- The RU mockup defines the target visual language; Bundle 3 encodes it instead of opposing it.
- No second theme/token authority is introduced.
- No Step 7–9 product/auth/data semantics change.
- No business/provider/runtime fact is promoted from the mockup.
- Accessibility/responsive rules remain first-class.

**Out of scope**  

- restyling the actual Portal pages/components (Step 11);
- product/business copy changes unrelated to visual-system terminology;
- pricing/purchase/provider runtime;
- paid-access/usage implementation;
- backend/API/schema changes;
- redesigning auth/session/legal semantics;
- pixel-perfect duplication of the HTML file.

**AI prompt**  

```text
Implement only ANY-636 Step 10: recalibrate the canonical Bundle 3 design system so it encodes the approved RU Portal visual language from portal-ru-anytools.html.

This is a design-system authority step, not a page redesign step. The Step 9 application structure is the baseline and must not be changed here.

Before editing, inspect:
- portal-ru-anytools.html shared CSS variables and representative HOME/TOOLS/PRODUCT/LK RU styles;
- docs/DESIGN.md;
- docs/design-system/bundle3/README.md, SKILL.md, web.md, PROMPT_SNIPPET.md, tokens.json;
- apps/web/AGENTS.md;
- the existing token generation path/output.

The current problem is that the old Bundle 3 authority mandates indigo gradients, radial glows, translucent glass/bento cards, blur-heavy surfaces and large radii, while the approved RU mockup uses a much flatter deep-navy/amber/compact system. Resolve that conflict inside Bundle 3 itself.

Keep Bundle 3 as the single design system. Do not create a second theme or cabinet-only token system.

Translate the mockup's visual language into semantic Bundle 3 rules/tokens, including its deep navy background, dark flat surfaces, thin blue borders, amber primary accent, compact radii/spacing and Plus Jakarta Sans direction. Preserve accessibility/responsive requirements. Do not paste raw mockup CSS wholesale into application styles.

Update docs/DESIGN.md and apps/web/AGENTS.md so future UI work no longer receives instructions to preserve the obsolete glass/bento appearance when it conflicts with the approved mockup.

If tokens.json changes, refresh generated token CSS through the repository generator only. Do not manually edit generated artifacts.

Do not edit page/component-specific layout/CSS/TSX in this step. Do not change routes, auth/session behavior, product-state semantics, APIs, backend, schema or provider/billing/access/usage behavior.

Do not copy demo values or business facts from the mockup.

Do not run tests, linters, formatters, type checks, builds or generators except the specific repository generation command required to refresh token output after changing canonical tokens.
Do not stage files.
Do not create commits.

After implementation:
- report every design-system/doc/generated-token file changed;
- summarize the old Bundle 3 rules removed or superseded;
- list the new canonical palette/typography/surface/radius/action rules;
- confirm there is still exactly one design-system/token authority;
- confirm no page composition/business/auth/API behavior changed;
- report exact manual verification commands.
```

**Manual verification**  

Review the design-system diff against the mockup, then run:

```bash
npm run docs:check
npm run generate:check
```

If token generation changes production CSS, also run:

```bash
npm run typecheck:web
npm run lint:web
```

Before accepting the step, confirm that no current instruction still requires all Portal surfaces to use the old purple/indigo glass+bento treatment or forbids the approved flat navy/amber language.

**Expected completion**  

- Bundle 3 itself now describes/encodes the RU mockup's visual language instead of blocking it.
- `docs/DESIGN.md`, Bundle 3 docs/tokens and `apps/web/AGENTS.md` agree on one visual authority.
- No parallel theme/token system exists.
- Application structure/semantics remain unchanged and ready for Step 11 restyling.

**Proposed commit**  

```text
ANY-636 align Bundle 3 with RU portal visual language
```

---

# Step 11 — Apply the Recalibrated Bundle 3 Style Across the RU Portal

> **ANY-636 internal Step 11 — visual implementation, not parent ANY-504 Step 11.**

**Status:** `pending`  
**Recommended model:** `Sol`

**Goal**  
Apply the Step 10 Bundle 3 visual system to the actual RU Portal so the public shell, home, catalog, product detail pages and authenticated cabinet materially look like one coherent implementation of the approved mockup. Preserve the structural/product/auth semantics already established by Steps 7–9.

The sole approved topology addition is the localized presentation-only `/[locale]/pricing` placeholder and Pricing navigation entry defined by the [approved Step 11 decision](#approved-step-11-pricing-placeholder-decision).

This is the step that should make the running Portal look **obviously different** from the old purple glass/bento implementation.

**Required reference**  

Compare the current rendered Portal after Step 9 with these mockup sections:

```text
HOME RU
TOOLS RU
PRODUCT RU
LK RU
```

Use Step 10's canonical Bundle 3 rules/tokens as the implementation authority. The mockup remains the visual target and business-fact filter described above.

**Scope / affected code**  

Expected primary production surfaces:

```text
apps/web/src/shared/ui/SiteShell.tsx
apps/web/src/shared/ui/HeaderNavigation.tsx           # Products/Pricing navigation and current-section semantics
apps/web/src/shared/ui/HeaderAccount.tsx               # styling/markup compatibility only if needed
apps/web/src/app/[locale]/page.tsx                    # markup/classes only if needed for styling
apps/web/src/app/[locale]/products/page.tsx           # markup/classes only if needed
apps/web/src/features/catalog/ProductOverview.tsx
apps/web/src/features/catalog/ProductDetail.tsx
apps/web/src/app/[locale]/pricing/page.tsx            # localized presentation-only placeholder route/metadata
apps/web/src/features/pricing/**                     # honest not-ready state and safe home/products links only
apps/web/src/features/account/AccountClient.tsx
apps/web/src/features/account/AccountProductCard.tsx
apps/web/src/app/globals.css
apps/web/src/app/catalog.css
apps/web/src/app/account.css
apps/web/src/app/responsive.css
font-loading/root layout files only if required by the canonical typography change
```

Shared auth/reset/verification/legal surfaces may receive only narrow compatibility styling needed because common tokens/primitives changed. Do not redesign their flows or information architecture.

**Implementation decisions**  

1. Preserve the Step 7–9 route/content/state structure unless a small markup/class adjustment is required to express the new visual system. Do not redo product discovery, product data or account-state modeling.
2. Replace the old Portal-wide purple/indigo glass/bento appearance on the affected surfaces with the canonical Step 10 language:
   - deep navy base background;
   - flat/opaque dark-blue surfaces;
   - thin blue borders;
   - amber primary highlight/actions;
   - compact radii and controls;
   - restrained shadows/glows;
   - compact spacing/typography;
   - Plus Jakarta Sans through the approved repository font-loading mechanism.
3. Public navigation should materially follow the mockup feel: compact sticky bar, clear brand/accent, restrained links/actions and no oversized translucent glass shell.
4. Home should preserve Step 7's truthful product-first content while adopting the mockup's visual styling and centered product-entry rhythm. Do not restore demo stats/pricing/free/freelancer content that Step 7 intentionally omitted.
5. Catalog/product cards should use the flatter mockup-like surface treatment, compact icon/type/name/description hierarchy and amber/secondary action treatment without fake availability badges or execution targets.
6. Product detail pages should keep Step 8's truthful two-column/product-preview composition while restyling hero, preview, supporting cards, actions and footer rhythm to the new Bundle 3 language. Do not add unsupported mockup claims.
7. Authenticated `/account` should materially follow `LK RU` styling:
   - narrow supporting rail/context + wide workspace at desktop widths;
   - compact heading/section labels;
   - flat product cards with thin borders and smaller radii;
   - product state rows visually secondary;
   - account/email-verification/logout context compact;
   - no fake sidebar destinations.
8. Do not resurrect the old Step 10 attempt merely by making its purple glass panels smaller. The final rendered account page must no longer read as the Step 9 purple account page.
9. Signed-out `/account`, HeaderAccount modal, reset, verification and legal behavior remain semantically unchanged. Shared styling may adapt to the new canonical palette/components so these surfaces remain coherent and accessible.
10. Preserve the exact seven-locale copy contract. Visual implementation should not require gratuitous copy changes.
11. Preserve focus/keyboard/ARIA/live-region behavior and sufficient contrast. Do not hide live regions with `display:none` merely for spacing.
12. Responsive behavior must follow the mockup intent: public navigation/cards collapse cleanly; product detail becomes one column; cabinet rail becomes a compact top/section treatment; no horizontal overflow.
13. Keep the approved `/[locale]/pricing` placeholder and localized navigation entry presentation-only: pricing/terms unavailable, safe home/products links, no commercial catalog data or purchase controls. Do not add prices, tariff names, billing periods, sellability, Pro/Free state, CloudPayments/provider data, active subscription, renewal dates, usage values/bars, install/web-app URLs, fake products or fake navigation destinations.
14. Do not change APIs, generated contracts, backend code, database/schema, auth/session semantics or future commercial/access/usage ownership.

**Invariants**  

- Step 7–9 product/auth semantics remain intact.
- Bundle 3 from Step 10 is the only style/token authority.
- The running Portal materially follows the approved RU visual language without copying demo facts.
- No provider/commercial/access/usage authority is introduced.
- The pricing placeholder establishes presentation/navigation topology only; authoritative offers/prices/sellability remain parent ANY-504 Step 6 and purchase/provider Widget behavior remains Step 7.
- Accessibility and responsive behavior remain intact.

**Out of scope**  

- new business/product features;
- authoritative commercial pricing/purchase/Widget behavior; only the approved presentation-only pricing placeholder is in scope;
- provider runtime;
- paid-access/usage integration;
- new APIs/schema;
- semantic redesign of auth/reset/verification/legal flows;
- automated visual-regression/pixel-diff infrastructure (Step 12 uses human-review screenshots instead).

**AI prompt**  

```text
Implement only ANY-636 Step 11: apply the recalibrated Bundle 3 visual language from Step 10 across the actual RU Portal surfaces.

Steps 7–9 define the structure/semantics and must be preserved. Step 10 defines the canonical design tokens/rules and is assumed complete.

Before editing, compare the running/current code against portal-ru-anytools.html HOME RU, TOOLS RU, PRODUCT RU and LK RU sections.

Restyle the affected Portal so it materially adopts the mockup's deep-navy, flat dark-surface, thin-border, amber-accent, compact-radius/spacing and typography language. Use the canonical Bundle 3 tokens/rules from Step 10 rather than page-local raw colors or a second theme.

Apply the style coherently to:
- global SiteShell/navigation;
- home;
- products catalog/cards;
- both product detail pages;
- authenticated account cabinet;
- only narrow shared auth/legal compatibility surfaces where token/component changes require it.

Preserve Step 7–9 content and data truth. Do not restore demo stats, pricing, freelancer products, Pro/Free, CloudPayments, subscription/renewal/usage values, fake availability labels, install/web-app URLs or fake sidebar destinations.

Retain the approved localized /[locale]/pricing placeholder and Pricing navigation entry as the sole topology exception to the historical Step 7 restriction. It must honestly show pricing/terms unavailable, contain no commercial facts or purchase controls, and make no pricing network/API calls. Authoritative offers/prices/sellability remain parent ANY-504 Step 6; purchase/provider Widget behavior remains Step 7.

The authenticated cabinet must stop looking like the old purple glass/bento account page. Follow LK RU's dashboard feel while keeping the real current account/product semantics and existing auth/session/email-verification behavior.

Do not change backend/API/schema/generated-contract/data ownership. Do not add network calls.

Do not run tests, linters, formatters, type checks, builds or generators.
Do not stage files.
Do not create commits.

After implementation:
- report every changed file;
- summarize visual changes by home/catalog/product/account surface;
- identify any old glass/bento selectors/primitives no longer used on active Portal surfaces;
- list every mockup fact/control intentionally omitted;
- confirm Step 7–9 semantics/auth/API boundaries are unchanged;
- report exact manual verification commands.
```

**Manual verification**  

Run:

```bash
node --test \
  apps/web/tests/i18n-contract.test.mjs \
  apps/web/tests/app-metadata.test.mjs
npm --workspace @anytoolai/web run test:components -- \
  tests/components/AccountClient.test.tsx \
  tests/components/HeaderAccount.test.tsx \
  tests/components/EmailVerificationClient.test.tsx
npm run typecheck:web
npm run lint:web
```

Then inspect desktop and normal phone widths for:

```text
/ru
/ru/products
/ru/pricing                             # presentation-only placeholder, no tariff cards or commercial actions
/ru/products/document-summary
/ru/products/prompt-optimizer
/ru/account signed out
/ru/account authenticated + verified email
/ru/account authenticated + unverified email
```

Compare the RU surfaces side-by-side with the mockup. The test is not pixel equality; the pages must be materially recognizable as the same visual family in palette, typography, surface treatment, density, control treatment and hierarchy while retaining only authoritative content.

**Expected completion**  

- The running Portal is visibly no longer the old purple glass/bento presentation.
- Public, product and account surfaces share the new Bundle 3 navy/amber/compact language.
- Step 7–9 product/auth/data semantics remain unchanged.
- The localized pricing placeholder and Products/Pricing navigation reflect the approved topology without introducing commercial facts or purchase behavior.
- Desktop/mobile remain usable and accessible.
- Step 12 can now validate the actual intended final UI rather than perform redesign work.

**Proposed commit**  

```text
ANY-636 apply RU portal visual system
```

---

# Step 12 — Add Mockup-Grounded Product UX Acceptance, Screenshots and Regression Coverage

> **ANY-636 internal Step 12 — final 4F visual/product acceptance evidence.**

**Status:** `pending`  
**Recommended model:** `Sol`

**Goal**  
Close the validation gap that allowed the initial implementation to pass without proving the actual product outcome. Add focused semantic regression coverage and reviewable desktop/mobile screenshot evidence for the RU home, catalog, product pages and authenticated cabinet.

**Scope / affected code**  

Expected test surfaces:

```text
apps/web/e2e/portal-ru.spec.ts
apps/web/e2e/public-routes.spec.ts
apps/web/e2e/account-logout.spec.ts                 # only if directly stale
apps/web/tests/components/AccountClient.test.tsx    # only if missing local state assertions
apps/web/tests/app-metadata.test.mjs
apps/web/tests/i18n-contract.test.mjs
```

Do not create a visual-regression framework or pixel-diff system.

**Implementation decisions**  

1. Keep all initial Step 4 boundary proofs:
   - no removed commerce APIs;
   - no CloudPayments/provider scripts;
   - retired routes stay 404;
   - unknown product slug stays 404;
   - auth/reset/verification behavior remains covered;
   - no serious/critical Axe findings.
2. Update 4F product acceptance so tests prove **composition semantics**, not just route existence:
   - home has clear product-first hero/discovery CTA hierarchy;
   - catalog exposes the two current product cards with correct localized detail links;
   - product detail pages contain meaningful product-specific sections beyond duplicated card text;
   - authenticated cabinet exposes both current products as primary surfaces;
   - each product surface shows honest current commercial/access/usage state without fake negatives or zeroes.
   - the localized pricing route renders an honest presentation-only not-ready state, safe home/products links and correct Products/Pricing current-section semantics, without commercial facts or purchase controls.
3. Add or retain desktop screenshots for at least:

```text
/ru
/ru/products
/ru/products/document-summary
/ru/products/prompt-optimizer
/ru/account authenticated
```

4. Add/retain mobile screenshots for the same key journey at approximately `390x844` (or the repository's existing standard phone viewport).
5. Screenshot evidence is for human review against `portal-ru-anytools.html`; it is not a pixel-perfect automated baseline.
6. Human screenshot review must evaluate the **visual language as well as composition**: deep-navy background, flat dark surfaces, thin borders, amber accent, compact radii/spacing, typography and dashboard/card treatment should materially follow the approved mockup. The old purple/indigo glass+bento appearance must not remain the dominant Portal identity.
7. Keep assertions resilient to incidental text/layout changes. Assert semantic sections, actions, headings, product identities and absence of prohibited facts rather than exact CSS coordinates.
8. Add negative assertions for the main mockup demo values that must never accidentally leak into the current 4F UI where practical, such as:

```text
490 ₽
990 ₽
200k+
320 / 500
3 / 10
CloudPayments
```

Do not build a generic forbidden-string framework.
9. Continue proving that absent future data is not rendered as “no subscription”, “no access”, zero usage/quota, default/free/pro plan or price.
10. Verify mobile shell/product/account composition has no horizontal overflow and remains keyboard/focus usable.
11. Do not add fake APIs/fixtures for commercial/access/usage state. Mock only the existing auth/session endpoint where already appropriate.
12. Do not change production behavior except a tiny accessibility/testability fix directly required by the intended current UI. Material corrections belong back in Steps 7–11.

**Invariants**  

- Tests prove current 4F product experience, not future billing behavior.
- Screenshot review remains human/review evidence, not pixel-locking.
- Provider/boundary tests remain intact.
- No fake data source is introduced for tests.

**Out of scope**  

- LBX/provider E2E;
- commercial catalog fixtures;
- paid-access fixtures;
- Kernel usage fixtures;
- visual snapshot infrastructure;
- broad test refactoring.

**AI prompt**  

```text
Implement only ANY-636 Step 12: strengthen product/visual acceptance coverage for the fully restyled RU AnyToolAI Portal and produce reviewable desktop/mobile screenshot evidence.

Steps 6–11 are assumed complete and manually verified.

Inspect the final corrected Portal surfaces, existing portal-ru/public-route/account E2E tests, Playwright screenshot conventions and portal-ru-anytools.html.

Preserve all existing architecture/provider/auth/accessibility boundary proofs.

Add focused semantic assertions proving:
- product-first home/discovery hierarchy;
- both current catalog products and links;
- substantial product pages, not just repeated card text;
- product-centric authenticated cabinet;
- per-product honest commercial/access/usage states;
- no fake negative/zero/plan/price state.

Capture human-review screenshots for the main RU desktop and mobile surfaces. Do not add pixel-diff infrastructure. Human review must cover the new canonical visual language (navy/flat/amber/compact treatment), not only block ordering.

Where practical, assert that obvious demo values/providers from the mockup such as 490 ₽, 990 ₽, 200k+, 320/500, 3/10 and CloudPayments do not leak into the current Portal.

Do not add fake billing/access/usage APIs or fixtures.
Do not redesign production code unless a tiny accessibility/testability correction is directly necessary.

Do not run tests, linters, formatters, type checks, builds or generators.
Do not stage files.
Do not create commits.

After implementation:
- report all test files changed;
- list the semantic product acceptance assertions;
- list screenshot evidence produced by the suite;
- list prohibited demo-value/provider assertions;
- confirm boundary/auth/accessibility proofs remain;
- report exact manual verification commands.
```

**Manual verification**  

Rebuild/reuse the harness according to current repository convention, then run:

```bash
npm run test:boundaries:web
npm --workspace @anytoolai/web run test:components
npm run test:e2e -- \
  apps/web/e2e/public-routes.spec.ts \
  apps/web/e2e/portal-ru.spec.ts \
  apps/web/e2e/auth-legal-links.spec.ts \
  apps/web/e2e/email-verification.spec.ts \
  apps/web/e2e/password-reset.spec.ts \
  apps/web/e2e/account-logout.spec.ts \
  apps/web/e2e/locale-routing.spec.ts \
  apps/web/e2e/react-runtime.spec.ts
npm run typecheck:web
npm run lint:web
```

Then inspect the produced RU desktop/mobile screenshots side-by-side with `portal-ru-anytools.html`.

**Expected completion**  

- The final product and visual experience has objective semantic regression coverage.
- The approved pricing placeholder/navigation topology is covered while commercial authority and purchase/provider Widget behavior remain deferred to parent ANY-504 Steps 6/7.
- Reviewers have desktop/mobile evidence for actual mockup-direction comparison.
- The old failure mode (“routes pass, Portal still not actually rebuilt”) is no longer sufficient to satisfy the tests/review.

**Proposed commit**  

```text
ANY-636 prove RU portal visual and product experience
```

---

# Step 13 — Correct the 4F Handoff, Re-run Final Review and Close ANY-636

> **ANY-636 internal Step 13 — final handoff/closure, not a parent ANY-504 step.**

**Status:** `in progress` — documentation/handoff prepared on 2026-10-08; final verification and human screenshot/intent acceptance pending  
**Recommended model:** `Sol`

**Goal**  
Bring current-authority documentation and the 4F handoff in line with the corrected product-centric Portal, remove documentation that describes the initial transitional layout as final, run the complete final gate, and make ANY-636 genuinely ready to close before parent ANY-504 Step 6 implementation.

**Scope / affected code**  

Update only documents that became stale because Steps 7–12 changed the as-built Portal composition, especially:

```text
README.md                                  # only if current product surface description is stale
ARCHITECTURE.md                            # only if topology wording is stale
docs/PRODUCT.md                            # current Portal product behavior
docs/product/ru-mvp.md                     # primary 4F handoff
docs/DESIGN.md                             # only if current Portal layout guidance is stale
docs/design-system/bundle3/README.md       # only if needed
apps/web/AGENTS.md                         # only if current route/UI guidance is stale
this ANY-636 implementation plan           # status/evidence/final acceptance only
```

Do not rewrite accepted historical ADR/design records merely for visual naming.

**Implementation decisions**  

1. Update `docs/product/ru-mvp.md` from the initial account-centric handoff to the final product-centric as-built state.
2. Document the final current visual/product topology:

```text
public product-first home
catalog / product discovery
substantial per-product pages
presentation-only localized pricing placeholder / public navigation
direct account/auth entry
product-centric authenticated cabinet
per-product commercial/access/usage/action slots
```
3. Document the final visual-authority correction: the approved RU mockup is the product/visual target, while the evolved Bundle 3 is the single canonical implementation design system. Record that the previous mandatory purple/indigo glass+bento appearance was superseded for the Portal by the navy/amber/flat/compact language encoded in Step 10.

4. Preserve all ownership boundaries already documented:
   - External Billing commercial truth → parent Step 6+;
   - purchase/Widget → parent Step 7;
   - reconciliation/recovery → parent Step 8;
   - provider-neutral paid access → parent Step 9;
   - actual usage/quota → parent Step 10.
5. Explicitly document that later parent steps **populate the existing per-product Portal slots** rather than redesign the main cabinet/product surface.
6. Keep the current product slugs presentation-only until technical identity mapping is introduced by its owning step.
7. Keep no-price/no-fake-access/no-fake-usage semantics until authoritative sources exist.
8. Record the RU mockup as the visual/product reference used to close 4F, while explicitly noting that demo prices/providers/metrics/legal/privacy claims were excluded from authority.
9. Update this plan's overview/final evidence to `done` only after complete verification and human screenshot review pass.
10. Run the complete 4F verification surface after the documentation diff is reviewed.
11. Perform a final intent/DoD review whose first question is: **does the system now look and behave like the RU AnyToolAI Portal expected by ANY-539/ANY-504 4F, not merely pass technical route/boundary checks?**
12. Do not begin parent ANY-504 Step 6 implementation inside this step.

**Invariants**  

- Current docs match current code.
- ADR 0005 and accepted design ownership remain unchanged.
- No parent ANY-504 Step 6–10 business truth is documented as implemented.
- Product-centric Portal structure is the durable integration surface for later steps.

**Out of scope**  

- LBX/provider implementation;
- commercial catalog/purchase;
- paid access;
- usage/quota runtime;
- new backend API/schema;
- unrelated doc cleanup.

**AI prompt**  

```text
Implement only ANY-636 Step 13: align current-authority documentation and the 4F handoff with the corrected product-centric RU Portal, then prepare the final verification/DoD evidence.

Steps 6–12 are assumed complete and manually verified.

Inspect only the final corrected Portal code/routes/tests/screenshots and the current-authority docs that describe the Portal product surface.

Update docs/product/ru-mvp.md so it records the final product-centric Portal and the evolved Bundle 3 visual authority, and so later parent ANY-504 Steps 6/7/8/9/10 integrate through the already-existing product-centric Portal surfaces: Step 6 commercial facts, Step 7 purchase action, Step 8 recovery/reconciliation behavior, Step 9 paid access, and Step 10 usage/quota — without redesigning the main cabinet.

Record portal-ru-anytools.html as the visual/product reference used for 4F and the evolved Bundle 3 as its canonical implementation encoding, while explicitly rejecting its demo prices, provider names, metrics, subscription/usage values, unsupported product states and other non-authoritative facts.

Preserve all accepted architecture ownership and the final ANY-541 generated-TypeScript/shared-transport trust rule.
Do not rewrite historical ADR/design records merely for naming.
Do not implement parent ANY-504 Step 6–10 work.

Do not run tests, linters, formatters, type checks, builds, generators or docs checks during editing.
Do not stage files.
Do not create commits.

After implementation:
- report every documentation/plan file changed;
- summarize the final product-centric Portal topology;
- summarize exactly how parent Steps 6/7/8/9/10 plug into it;
- list the final verification commands;
- identify any remaining reason ANY-636 cannot be closed. If any material product/visual DoD gap remains, report it instead of marking the plan done.
```

**Manual verification**  

Run the final complete surface:

```bash
npm run docs:check
npm run architecture:check
npm run generate:check
npm run test:boundaries:web
npm --workspace @anytoolai/web run test:components
npm run typecheck:web
npm run lint:web
npm run test:e2e -- \
  apps/web/e2e/public-routes.spec.ts \
  apps/web/e2e/portal-ru.spec.ts \
  apps/web/e2e/auth-legal-links.spec.ts \
  apps/web/e2e/email-verification.spec.ts \
  apps/web/e2e/password-reset.spec.ts \
  apps/web/e2e/account-logout.spec.ts \
  apps/web/e2e/locale-routing.spec.ts \
  apps/web/e2e/react-runtime.spec.ts
npm run build:web
npm run check:fast
```

Then perform the human acceptance review:

```text
1. Open portal-ru-anytools.html.
2. Open /ru desktop beside it.
3. Open /ru/products and both RU product pages.
4. Open authenticated /ru/account.
5. Repeat the key journey at mobile width.
6. Confirm the production UI follows the mockup's composition/product hierarchy **and the evolved navy/amber/flat/compact visual language**.
7. Confirm all demo/unverified facts from the mockup were either omitted or replaced with authoritative/honest states.
8. Confirm later parent Steps 6–10 can attach data/actions without another major shell/catalog/product/cabinet redesign.
```

**Expected completion**  

- ANY-636 finally satisfies the actual ANY-539 / ANY-504 4F product intent.
- The RU mockup has been materially applied to the current Portal surface.
- The Portal is product-centric and remains provider-independent.
- The handoff records `/[locale]/pricing` as presentation/navigation only, with authoritative offers/prices/sellability deferred to parent ANY-504 Step 6 and purchase/provider Widget behavior to Step 7.
- Steps 6–10 of the parent program can integrate into stable existing UI slots.
- Documentation, tests, screenshots and human review all describe/prove the same as-built Portal.

**Prepared implementation evidence — 2026-10-08**

- Execution baseline: the current repository and completed Steps 1–12, as
  directed for this selected step. Earlier implementation and the final
  ANY-541 generated-TypeScript/shared-transport trust boundary are preserved;
  no historical merge or earlier step was repeated.
- Updated `docs/product/ru-mvp.md` as the primary as-built 4F handoff, plus
  `README.md`, `ARCHITECTURE.md`, `docs/PRODUCT.md`, `docs/DESIGN.md` and
  `docs/design-system/bundle3/README.md` where route/composition or applied
  design-system wording was stale. This plan records preparation and pending
  acceptance only. `apps/web/AGENTS.md` already describes the evolved visual
  authority and needed no change.
- Final topology recorded: product-first public home and catalog, substantial
  screens for the two current presentation products, localized pricing
  placeholder/navigation, direct account/auth entry, product-centric
  authenticated cabinet and per-product commercial/access/usage/action slots.
  Identity/verification/logout context is compact supporting content.
- Parent ANY-504 handoff: Step 6 fills authoritative commercial/pricing slots
  and technical identity mapping; Step 7 fills purchase/Widget action areas;
  Step 8 fills reconciled commercial state and recovery feedback; Step 9 fills
  confirmed provider-neutral paid-access slots; Step 10 fills actual Kernel
  usage/quota slots. These are deferred integrations into existing surfaces,
  without a main cabinet redesign or guessed business facts.
- Directly read the adjacent `portal-ru-anytools.html` as input-only
  product/visual reference. Evolved Bundle 3 is its canonical navy/amber,
  flat/compact implementation encoding; the old mandatory purple/indigo
  glass+bento identity is superseded. Demo prices/providers/metrics,
  subscription/access/usage values, unsupported products/availability and
  legal/privacy claims are excluded from authority. The HTML was not modified
  or staged; accepted ADR/design records and legal source were not changed.
- Reviewed current routes/components/transport, focused acceptance test source,
  and existing representative desktop home/catalog/product/account and mobile
  home/product/account screenshots under `.harness/playwright-results`.
  Existing test source captures full-page desktop/mobile route evidence,
  verified/unverified authenticated account fixtures and the 390×844 journey,
  with review context pointing to the mockup. Screenshot inspection is not
  human acceptance and does not establish a new test pass or business facts.
- No tests, linters, typechecks, builds, Playwright runs, checks, generators or
  formatting were run during Step 13 editing. No files were staged and no
  commits or pushes were created.

**Final verification / intent-review gate — pending**

The first review question remains: **does the system now look and behave like
the RU AnyToolAI Portal expected by ANY-539/ANY-504 4F, not merely pass technical
route/boundary checks?** The prepared documentation and existing inspected
screenshots describe the corrected product hierarchy and evolved visual
language; final acceptance still requires the complete command results and
human desktop/mobile comparison specified above.

The listed focused E2E command is retained. Current `playwright.config.ts`
explicitly excludes `react-runtime.spec.ts`; naming that file in the ordinary
route command does not run it. Also run the existing canonical command below,
which uses `playwright.react-runtime.config.ts`, to complete the required
runtime surface:

```bash
npm run test:e2e:react-runtime
```

Closure is pending: review the documentation diff, run the entire manual
verification surface plus the dedicated React runtime command, and record
command outcomes, current screenshot/report locations and human intent/DoD
acceptance. Do not treat existing artifacts or previous-step verification as
the final Step 13 gate. If the human comparison finds a material product/visual
gap, record it here instead of marking completion. Only after all gates pass
may Step 13 and the overview become `done`; parent ANY-504 Step 6 remains
outside this implementation.

**Proposed commit**  

```text
ANY-636 finalize RU portal visual product handoff
```

---

## Final Acceptance Validation for ANY-636

After **all thirteen** ANY-636 implementation steps are complete and manually verified, the implementation must satisfy this matrix.

| Requirement | Expected final result |
| --- | --- |
| Required baseline | Current completed Steps 1–12 preserved, including the final ANY-541 generated-TypeScript/shared-transport boundary; Step 13 uses the current repository without repeating historical merges or earlier implementation |
| RU visual authority | `portal-ru-anytools.html` was directly inspected and used for product hierarchy **and visual language** (palette, typography, surfaces, density, spacing and dashboard/card treatment) |
| Design system | Bundle 3 remains the single implementation token/component authority and is deliberately evolved to encode the approved RU mockup direction; no parallel theme/token system is introduced |
| Home/shell | Product-first AnyToolAI Portal composition materially aligned with the RU mockup, not a readiness/system-fact dashboard |
| Visual language | Active Portal surfaces use the evolved deep-navy / flat dark-surface / thin-border / amber-accent / compact-radius language rather than the superseded purple glass/bento identity |
| Catalog | Current products are discoverable in a mockup-grounded product/catalog composition; no fake roadmap/current products |
| Product pages | Both current products have substantial localized product screens, not just repeated catalog cards |
| Product identity | `document-summary` and `prompt-optimizer` remain frontend presentation/route slugs only |
| Product actions | No install/web-app/execution/purchase target is invented; only authoritative current navigation/actions are exposed |
| Direct auth route | `/[locale]/account` |
| Header auth | Existing modal preserved |
| Signed-out account | Direct login/registration remains functional |
| Authenticated cabinet | Product-centric primary composition with compact identity context |
| Per-product future slots | Each current product has stable local presentation slots for commercial readiness, paid access, usage/quota and action |
| Per-product current truth | Missing future data renders unknown/not-ready/unavailable, never fake negative/zero/default-plan state |
| Unverified email | Existing verification guidance preserved |
| Password reset | Existing request/fragment-token semantics preserved |
| Email verification | Existing memory-only fragment-token semantics preserved |
| Canonical legal | Existing RU canonical paths/source preserved |
| `/auth-checkout` | Removed, no redirect/compatibility route |
| `/payment-result` | Removed, no redirect/compatibility route |
| Pricing placeholder/navigation | Localized `/[locale]/pricing` and Pricing navigation exist only as an honest presentation-only not-ready surface; no commercial catalog data, prices, tariff names, billing periods, sellability, subscription state, provider data, purchase controls or fake offers; authoritative offers/prices/sellability remain parent ANY-504 Step 6 and purchase/provider Widget behavior remains Step 7 |
| Commercial offers/prices | Not implemented; no mock `0/490/990 ₽` or plan authority |
| Purchase / Widget | Not implemented; no purchase CTA |
| Subscription/payment state | Not implemented; no fake “none” result, renewal date or manage-billing control |
| Paid access | Not implemented; no fake deny/allow result |
| Usage/quota | Not implemented; no fake zero/progress/`320/500`/`3/10` values |
| Mockup demo provider | `CloudPayments` or other demo provider value does not leak into the current provider-independent UI |
| Mockup demo metrics | `200k+`, `10 products`, `2/month`, unsupported privacy/language claims and roadmap products are not treated as production facts |
| Provider network | None |
| CloudPayments runtime | Not restored |
| FastAPI/Pydantic | No new/changed 4F API contract unless separately replanned after a material ownership contradiction |
| HTTP successful JSON trust | Read as `unknown` and trusted exactly once in `shared/api/transport.ts`; malformed JSON syntax → `ApiContractError` |
| Browser structural validation | None for same-service successful API JSON; Pydantic/FastAPI remains the runtime authority |
| Generated Zod response schemas | Absent from the HTTP contract boundary; `zod.gen.ts` / response `safeParse()` path removed |
| OpenAPI/generated TypeScript | Final ANY-541 boundary preserved: generated TS wire contracts, one shared transport trust point, no second browser structural runtime validation |
| Database schema | Unchanged |
| Target billing persistence | Not used as UI/runtime authority |
| Locale parity | `en/fr/it/de/es/ru/pt` exact key/ICU-signature parity |
| Mobile | Home/catalog/product/account journey follows intended hierarchy without horizontal overflow |
| Accessibility | Focused active routes have no serious/critical Axe failures and keyboard/focus behavior remains usable |
| Product acceptance evidence | Desktop/mobile screenshots exist for human comparison with the RU mockup |
| Removed commerce contracts | No frontend call to removed catalog/checkout/subscription/payment-status APIs |
| Current docs | Describe the corrected product-centric AnyToolAI Portal and final route/data ownership topology |
| Region Resolver docs | No obsolete separate Application Portal frontend assumption; no invented API schema |
| Future handoff | Parent ANY-504 Steps 6/7/8/9/10 integrate through stable existing Portal/product/cabinet surfaces without another main Portal redesign |
| Final intent review | Reviewer confirms the result is the expected RU customer Portal by product semantics, not merely technically valid routes/boundaries |

---

## Explicit Follow-ups Not Included in ANY-636

These remain intentionally **outside** this ticket even after corrective completion:

- `ANY-634` / parent Step 5 real LBX Phase 0 evidence.
- Parent ANY-504 Step 6 External Billing capability/catalog/pricing/sellability projection and mapping.
- Parent ANY-504 Step 7 purchase intent / provider Widget entry.
- Parent ANY-504 Step 8 provider webhook/reconciliation/recovery.
- Parent ANY-504 Step 9 confirmed provider-neutral paid-access projection.
- Parent ANY-504 Step 10 Portal↔Kernel access/usage/quota integration.
- Parent ANY-504 Step 11 final provider-backed end-to-end flow.
- Region Resolver concrete API/schema implementation.
- EU/US launch/enablement.
- Actual web-product execution/onboarding/result flows unless separately owned by their product/backend implementation work.
- An authoritative product execution destination if/when a later product/Kernel integration defines it.

Do not pre-build future wire DTOs, persistence, provider abstractions or backend domain models inside ANY-636. Frontend-local composition required to render today's product-centric Portal is allowed; future service/domain authority is not.
