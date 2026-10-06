# ANY-636 — Evolve Payments Portal into the RU AnyToolAI Portal

## Plan Overview

| Field | Value |
| --- | --- |
| Parent program | `ANY-504 — External Billing & Paid Access` |
| Ticket | `ANY-636 — 4F. Evolve Payments Portal into the RU AnyToolAI Portal` |
| Direct predecessor / required code baseline | `ANY-541`, PR `#129`, branch `ANY-541` |
| Planning baseline commit | `3e53f1cc7756cc6825b05b4fcbd580479a196a64` (`ANY-541: Fix email contract validation and Sentry sanitization`) |
| Overall status | `done` |
| Completed | `2026-10-06` |
| Execution order | Sequential only: Step 1 → manual verification → commit → Step 2 → ... → Step 5 |
| Steps / commits | 5 |
| Blocks | `ANY-634 — Step 5. LBX Phase 0 provider research` |
| Backend/API/schema work expected | None, unless execution discovers a material contradiction with the researched baseline and stops for replanning |

## Completion Evidence

All five implementation steps are complete on branch `ANY-636`, based on
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

## How to Use This File

1. Create the `ANY-636` implementation branch from the **current HEAD of `ANY-541` / PR #129**, not from `main`.
2. Before Step 1, confirm that PR #129 still contains planning baseline commit `3e53f1cc7756cc6825b05b4fcbd580479a196a64` or a descendant that preserves the ANY-541 contract boundary and its review fixes. If the predecessor changed materially, update the branch and revalidate only the affected assumptions in this plan before implementation.
3. Give the execution model this file and instruct it to implement **one step only**.
4. After each step:
   - review the diff;
   - run the step's manual verification commands yourself;
   - fix only failures caused by that step;
   - create the proposed commit yourself;
   - only then continue to the next step.
5. Do not ask the execution model to repeat the broad repository/architecture research already captured here.
6. Do not combine steps further. Public shell/catalog/product-detail work is intentionally one step because it shares the same presentation context; auth-route work remains separate because of session/security semantics; cabinet presentation, final verification, and documentation remain separate review boundaries.

---

## Research Basis and Source-of-Truth Order

This plan was prepared against the current `ANY-541` PR #129 code, not against `main`.

When sources conflict, use the following precedence for this ticket:

1. `ANY-636` and the `ANY-504` execution sequence for the current 4F scope and future-step boundaries.
2. ADR 0005 and the accepted External Billing / Portal-Kernel designs for ownership and authority.
3. The current `ANY-541` / PR #129 implementation for actual existing behavior and the backend→OpenAPI→generated-TypeScript→shared-transport contract boundary.
4. Current repository tests for behavior that must remain working.
5. Bundle 3 for visual/layout rules.
6. The ANY-539 RU mockup and handoff for product/UI direction only; they are **not** authority for tariffs, prices, subscriptions, provider facts, paid access, usage, quota, or runtime product identity.

### Sources reviewed

- Linear:
  - `ANY-636`
  - parent `ANY-504`
  - source direction ticket `ANY-539`
  - predecessor `ANY-541`
  - future provider gate `ANY-634`
  - relevant prior baseline represented by the current code from `ANY-505`, `ANY-509`, `ANY-510`, `ANY-522`, `ANY-408`, `ANY-525`, and `ANY-538`
- PR #129 at commit `3e53f1cc7756cc6825b05b4fcbd580479a196a64`.
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

### Mockup access note

The embedded `portal-ru-anytools.html` attachment bytes were not retrievable through the available Linear connector during planning/validation. This is the **only material research limitation** remaining. It does not leave an unresolved business/API/persistence/security decision because:

- `ANY-636` already fixes the provider-independent ownership and deferred-step boundaries;
- ANY-539 plus its handoff identify the relevant Portal blocks and explicitly make the HTML a visual/product direction rather than business authority;
- current code, tests, Bundle 3 and current-authority docs were inspected directly;
- no contract or business fact in this plan is taken from an unseen mockup value.

What cannot be claimed without the raw HTML is pixel/layout-level visual completeness against that reference. If the HTML is directly available during Step 1, the execution model may inspect it **only** to align visual composition and block placement inside the locked route/data-ownership decisions. This is a bounded visual reference check, not repeated architecture research and not permission to derive demo tariffs, provider facts, access, usage or quota.

---

## Current As-Built Baseline

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

### ANY-541 contract boundary already established

For every value that actually crosses the backend/frontend HTTP boundary:

```text
FastAPI/Pydantic
  → app.openapi()
  → docs/generated/openapi.json
  → generated TypeScript wire contracts in apps/web/src/generated/api-contracts/
  → shared API transport trust boundary
  → endpoint adapters
  → feature/UI state
```

4F must consume this boundary; it must not create handwritten frontend wire DTOs.

### Research conclusion: no new 4F backend API is justified

No new Portal-owned HTTP API is required for the implementation allowed by ANY-636:

- account/session/email-verification facts already exist through generated auth contracts;
- legal/reset/verification contracts already exist;
- product descriptions and route slugs are frontend-owned presentation metadata;
- tariffs/prices/subscriptions/payment methods/autopay/invoices/refunds belong to External Billing and are deferred;
- confirmed paid-access state belongs to later Portal projection work and is deferred;
- technical product identity, actual usage and quota belong to Platform Kernel and are deferred.

Therefore this plan deliberately contains **no FastAPI/Pydantic/OpenAPI/generated-contract/database step**.

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
- Bundle 3 remains the design system; no replacement token system or parallel visual framework.
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
6. Preserve current registration legal confirmations, password-policy ownership, Accept-Language behavior and the generated-TypeScript/shared-transport contract boundary.
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
   - External Billing commercial catalog/pricing/sellability deferred to Step 6;
   - purchase/Widget deferred to ANY-504 Step 7;
   - recovery/reconciliation deferred to ANY-504 Step 8;
   - confirmed paid-access state deferred to ANY-504 Step 9;
   - Platform Kernel actual usage/quota deferred to ANY-504 Step 10.
6. State explicitly that UI “not ready/unknown” is not evidence of no subscription, no access or zero usage/quota.
7. State explicitly that document-summary and prompt-optimizer are current presentation/route slugs only, not claimed Platform Kernel product_id or External Billing IDs.
8. Record the ANY-541 rule: any future Portal-owned web-consumed API must start with backend Pydantic, named OpenAPI, repository generation, generated TypeScript wire contracts and the shared API transport trust boundary. Record that ANY-636 itself required no new API because no additional Portal-owned server fact was needed.
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

## Final Acceptance Validation for ANY-636

After all five steps are complete and manually verified, the implementation must satisfy this matrix.

| Requirement | Expected final result |
| --- | --- |
| Required baseline | 4F is based on current `ANY-541` / PR #129 code, including its latest review fixes |
| Product identity | `document-summary` and `prompt-optimizer` remain frontend presentation/route slugs only |
| Home/shell | AnyToolAI Portal presentation on Bundle 3 |
| Catalog | Public presentational product discovery, no commercial authority |
| Product pages | Localized product-detail routes for both current products |
| Direct auth route | `/[locale]/account` |
| Header auth | Existing modal preserved |
| Account identity | Existing generated session contract only |
| Unverified email | Existing verification guidance preserved |
| Password reset | Existing request/fragment-token semantics preserved |
| Email verification | Existing memory-only fragment-token semantics preserved |
| Canonical legal | Existing RU canonical paths/source preserved |
| `/auth-checkout` | Removed, no redirect/compatibility route |
| `/payment-result` | Removed, no redirect/compatibility route |
| Commercial offers/prices | Not implemented; explicit not-ready presentation only |
| Purchase / Widget | Not implemented; no purchase CTA |
| Subscription/payment state | Not implemented; no fake “none” result |
| Paid access | Not implemented; no fake deny/allow result |
| Usage/quota | Not implemented; no fake zero/progress value |
| Provider network | None |
| CloudPayments | Not restored |
| FastAPI/Pydantic | No new/changed 4F API contract required |
| OpenAPI/generated TypeScript | No new 4F API contract required; existing ANY-541 boundary preserved |
| Database schema | Unchanged |
| Target billing persistence | Not used as UI/runtime authority |
| Locale parity | `en/fr/it/de/es/ru/pt` exact key/ICU-signature parity |
| Mobile | Key RU journey usable without horizontal overflow |
| Accessibility | Focused active routes have no serious/critical Axe failures |
| Removed commerce contracts | No frontend call to removed catalog/checkout/subscription/payment-status APIs |
| Current docs | Describe AnyToolAI Portal and final route/data ownership topology |
| Region Resolver docs | No obsolete separate Application Portal frontend assumption; no invented API schema |
| Future handoff | ANY-504 Steps 6/7/8/9/10 ownership and not-ready semantics documented |

---

## Explicit Follow-ups Not Included in ANY-636

These are intentionally **not** implementation steps in this ticket:

- `ANY-634` / Step 5 real LBX Phase 0 evidence.
- ANY-504 Step 6 External Billing capability/catalog/pricing/sellability projection and mapping.
- ANY-504 Step 7 purchase intent / provider Widget entry.
- ANY-504 Step 8 provider webhook/reconciliation/recovery.
- ANY-504 Step 9 confirmed provider-neutral paid-access projection.
- ANY-504 Step 10 Portal↔Kernel access/usage/quota integration.
- ANY-504 Step 11 final provider-backed end-to-end flow.
- Region Resolver concrete API/schema implementation.
- EU/US launch/enablement.
- An authoritative product execution destination if/when a later product/Kernel integration defines it.

Do not pre-build placeholders, DTOs, persistence, interfaces or abstractions for these future steps inside ANY-636.
