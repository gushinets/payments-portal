# ANY-529 — Localize Existing Portal UI & Client-Facing Application Copy

## Plan Overview

| Field | Value |
| --- | --- |
| Parent feature | `ANY-525 — 4B. Establish Portal Internationalization (EFIGS + RU + PT)` |
| Ticket | `ANY-529 — 4B.2 Localize Existing Portal UI & Client-Facing Application Copy` |
| Overall status | `done` |
| Execution order | Sequential only: Step 1 → manual verification → commit → Step 2 → manual verification → commit → Step 3 → manual verification → commit → Step 4 |
| Steps / proposed commits | 4 |
| Blocking predecessor | `ANY-526 — 4B.1 Establish Locale Runtime, Routing & Navigation Foundation` |
| Working predecessor baseline at latest validation | PR `#121`, branch `ANY-526`, head `5f7e4bbd89dd848877933ff59028d1c78617dfe8` |
| Predecessor base at latest validation | PR `#120`, branch `ANY-408`, head `8adbf15cf670908527902b33e9d2dc8dc1237660` |
| Expected backend / DB work | None |
| Deferred successor work | 4B.3 backend locale propagation, locale-aware password-reset URL generation, and localized backend-originated communications |

The concrete SHAs above are a research snapshot only. They are **not** durable architecture authority. `ANY-529` must be created from the latest reviewed `ANY-526` branch and must contain the final 4B.1 review fixes before `ANY-529` is completed.

At the latest validation, no `ANY-529` branch exists in GitHub yet. PR `#121` is open and is based directly on the current `ANY-408` head. Its current head `5f7e4bb` contains fixes for the three latest 4B.1 review findings (root-query preservation, RU language metadata on canonical legal footer links, and JSX-expression coverage in the `/ru` guard), although those review threads are still shown as unresolved in GitHub. Treat `ANY-526` as still under review and synchronize the final resolved predecessor head before 4B.2 closeout.

Important PR-composition rule: GitHub shows PR `#121` as a diff **against** `ANY-408`, so the PR diff itself contains only the additional 4B.1 changes. The actual `ANY-526` branch working tree already contains the full `ANY-408` head plus those 4B.1 commits. Therefore `ANY-529` must branch from `ANY-526`; execution must not separately replay PR `#120` or implement 408 cleanup again.

---

## How to Use This File

1. Create or update the `ANY-529` working branch **directly from the latest reviewed `ANY-526` branch**, not from `main` or `ANY-408` alone.
2. Put this plan at `docs/exec-plans/active/ANY-529-implementation-plan.md` while the ticket is active.
3. Use a fresh execution chat for each step.
4. Give the execution model only this plan and the repository. Do not ask it to repeat broad ticket/architecture research.
5. For each step:
   - ask the model to implement only that step;
   - review its diff;
   - run the listed manual verification commands yourself;
   - if the checks pass, create the proposed commit yourself;
   - change that step's status from `todo` to `done`.
6. Before the final Step 4 verification/closeout, synchronize the **final/current `ANY-526` predecessor output** into the `ANY-529` branch. That `ANY-526` state must itself include any final `ANY-408` review fixes that were incorporated into its base. Do not replay `ANY-408` separately in `ANY-529`. Re-check only the 4B.2 surfaces affected by predecessor changes. Do not redo the whole i18n architecture investigation unless the predecessor has materially changed one of the locked contracts below.
7. The execution model must never run test/lint/format/build/generation/check commands, stage files, or create commits.

---

## Research Snapshot and Locked Baseline

### Current 4B.1 runtime that 4B.2 must consume

The current reviewed `ANY-526` implementation already establishes:

- Next.js `16.3.1`, React `19.2.8`, and `next-intl` `4.14.7`;
- `config/locales.json` as the single machine-readable locale contract;
- generated TypeScript and Python locale artifacts;
- exactly these public route locales:
  - `en`
  - `fr`
  - `it`
  - `de`
  - `es`
  - `ru`
  - `pt`
- `pt` public route identity mapped to `pt-BR` for both `languageTag` and `intlLocale`;
- ordinary application routes under `apps/web/src/app/[locale]`;
- `/` as the only `Accept-Language` negotiation entry;
- root locale negotiation changes only the pathname and preserves the incoming query string;
- explicit locale-prefixed URLs as authoritative;
- locale-aware navigation in `apps/web/src/i18n/navigation.ts`;
- `apps/web/src/i18n/request.ts` loading exactly one current-locale catalog;
- `apps/web/src/i18n/formatting-locale.ts`, `formatting-locale.server.ts`, and `use-formatting-locale.ts` as the canonical route-locale → Intl-locale mapping;
- all seven `apps/web/src/messages/*.json` files, currently empty;
- a root `NextIntlClientProvider` with `messages={null}` so the whole current-locale catalog is **not** automatically serialized to every Client Component;
- canonical generated RU legal routes and locale-switch restrictions;
- generated canonical RU legal labels in the shared footer retain `lang="ru"` on non-RU pages;
- the bounded `/ru` ordinary-route lint guard covers direct literals and JSX expression-valued href literals while allowing generated canonical legal paths;
- locale switching disabled for password-reset confirmation;
- password-reset tokens remaining fragment/client-only;
- repository generation/drift conventions through `scripts/repo.py`, `npm run generate`, and `npm run generate:check`.

4B.2 must **consume** this foundation. It must not create another locale registry, routing layer, navigation abstraction, message loader, formatting-locale mapping, or root all-messages provider.

### Current ordinary copy that still requires localization

The current reviewed 4B.1 branch still contains Russian-only ordinary Portal copy in:

- `apps/web/src/app/[locale]/layout.tsx`;
- `apps/web/src/app/[locale]/page.tsx`;
- `apps/web/src/app/[locale]/products/page.tsx`;
- the reset-password Suspense fallback;
- `apps/web/src/shared/ui/SiteShell.tsx`;
- `apps/web/src/shared/ui/LocaleSwitcher.tsx` presentation/accessibility labels only;
- `apps/web/src/shared/ui/Footer.tsx`;
- `apps/web/src/shared/ui/CookieBanner.tsx`;
- `apps/web/src/shared/ui/HeaderAccount.tsx`;
- `apps/web/src/shared/ui/AuthForm.tsx`;
- `apps/web/src/features/catalog/catalog.ts`;
- `apps/web/src/features/catalog/ProductOverview.tsx`;
- `apps/web/src/features/account/AccountClient.tsx`;
- `apps/web/src/features/checkout/CheckoutClient.tsx`;
- `apps/web/src/features/password-reset/PasswordResetRequestClient.tsx`;
- `apps/web/src/features/password-reset/PasswordResetConfirmClient.tsx`;
- `apps/web/src/features/payment-result/PaymentResultClient.tsx`;
- presentation chrome in `apps/web/src/features/legal/LegalPageView.tsx`;
- ordinary metadata in `apps/web/src/i18n/metadata.ts`;
- Russian user-facing auth/password-reset error mapping in `apps/web/src/shared/api/auth.ts`.

### Current server/client component boundaries

The current component tree already gives a clean implementation path:

- server-compatible / server-rendered surfaces:
  - locale layout;
  - home page;
  - products page;
  - `ProductOverview`;
  - `Footer`;
  - `LegalPageView`;
  - `PaymentResultClient` despite its historical name;
- genuine Client Components:
  - `LocaleSwitcher`;
  - `CookieBanner`;
  - `HeaderAccount`;
  - `AuthForm`;
  - `CheckoutClient`;
  - `AccountClient`;
  - `PasswordResetRequestClient`;
  - `PasswordResetConfirmClient`.

Do **not** convert server-compatible components to Client Components merely to use translations.

### Current API error contract

`apps/web/src/shared/api/auth.ts` correctly owns:

- `ApiError`;
- `ApiContractError`;
- runtime response decoders;
- `apiErrorCode`;
- `getJson` / `postJson`;
- session storage/event constants;
- auth/password-reset transport requests.

It incorrectly still owns Russian presentation functions:

- `authErrorMessage`;
- `passwordResetErrorMessage`.

The API already exposes language-neutral codes including:

- `email_already_registered` → HTTP 409;
- `invalid_credentials` → HTTP 401;
- `missing_personal_consent` → HTTP 400;
- `missing_offer_consent` → HTTP 400;
- `password_reset_rate_limited` → HTTP 429;
- `invalid_or_expired_reset_token` → HTTP 400;
- `internal_server_error` → HTTP 500.

4B.2 must move the mapping from those facts to human-readable copy into the web Presentation/UI boundary. It must not change backend error codes or parse backend prose.

---

## Locked Architectural Decisions

The following decisions are already made by `ANY-525`, `ANY-408`, and `ANY-526` and must not be reopened during implementation:

1. `routeLocale`, `languageTag`, and `intlLocale` remain distinct.
2. Public route `pt` means Brazilian Portuguese copy/language/formatting semantics (`pt-BR`).
3. `ru` is the routing/negotiation fallback only. It is **not** the runtime missing-message fallback.
4. All seven catalogs must be complete. Missing messages are a repository-check failure.
5. `/` remains the only locale negotiation entry. It preserves the incoming query string while changing only the negotiated pathname. Explicit locale-prefixed routes remain authoritative.
6. Application slugs remain stable and non-localized.
7. Locale is Presentation state only:
   - no locale field in User/session/tenant/billing persistence;
   - no i18n database migration;
   - no locale cookie/localStorage preference;
   - no locale-driven tenant/region/provider selection.
8. Auth/session identity remains locale-neutral.
9. The localized root provider remains `messages={null}`.
10. Server Components use server-side `next-intl` APIs.
11. A Client Component receives only the current-locale namespaces it needs, from the nearest appropriate server boundary.
12. Do not serialize all seven catalogs or the full current-locale catalog to ordinary client boundaries.
13. `DISPLAY_NAME_BY_ROUTE_LOCALE` remains the authority for locale-switcher language names. Do not duplicate language names in message catalogs.
14. Canonical RU legal document path/title/body/version/hash/evidence remains generated/source-owned authority.
15. Generated registration acceptance statements remain canonical RU text and retain `lang="ru"`. Canonical RU legal link labels rendered in the shared footer also retain `lang="ru"` on non-RU pages.
16. Password-reset confirmation remains without locale switching and its token remains URL-fragment/client-only.
17. UI locale must not change RU commercial/payment semantics.
18. Locale must not infer currency or timezone.
19. No provider/LBX work belongs in this ticket.
20. No frontend-to-backend locale propagation belongs in this ticket. In particular, do not add `Accept-Language` to API requests in 4B.2.
21. Password-reset URL generation and email subject/body localization remain 4B.3 work.
22. The existing bounded `/ru` ordinary-route regression guard remains authoritative, including JSX expression-valued href coverage; generated canonical legal paths remain the intentional exception.

---

## Content Ownership Rules

| Content category | 4B.2 ownership |
| --- | --- |
| Portal-owned UI/navigation/help/product presentation copy | Move to `apps/web/src/messages/*.json` |
| Ordinary localized metadata | Move to the message catalogs |
| Generated legal document title/body/version/path | Keep generated/source-owned RU |
| Generated registration acceptance statements | Keep generated/source-owned RU and `lang="ru"` |
| Seller legal name, INN, OGRNIP, legal address | Keep source-owned values; localize only surrounding labels |
| Support email | Keep source-owned value |
| Provider/payment-method labels and provider facts | Keep source-owned unless an explicit localization rule exists |
| User-entered email/content | Never translate |
| Backend error code/status | Keep language-neutral transport fact |
| Human-readable frontend error message | Localize in owning web Presentation/UI |
| Backend email/reset URL copy | Defer to 4B.3 |

Do not translate canonical legal authority merely because it appears inside a non-RU UI.

---

## Message Catalog Design

Use the seven existing files:

```text
apps/web/src/messages/en.json
apps/web/src/messages/fr.json
apps/web/src/messages/it.json
apps/web/src/messages/de.json
apps/web/src/messages/es.json
apps/web/src/messages/ru.json
apps/web/src/messages/pt.json
```

Use semantic nested namespaces. The planned final namespace ownership is:

| Namespace | Owns |
| --- | --- |
| `Navigation` | main-nav labels and locale-switcher accessibility/presentation copy |
| `Home` | landing hero, facts, highlights, and product-section intro |
| `Catalog` | products-page copy, product-card copy, product presentation content |
| `Auth` | shared login/register form, validation, auth notices, auth error messages, header account/auth presentation |
| `Checkout` | auth-checkout page/session/unavailable-payment presentation |
| `Account` | account loading/signed-out/signed-in/unavailable-billing presentation |
| `PasswordReset` | request/confirmation UI, local validation, notices, password-reset error messages |
| `PaymentResult` | unavailable payment-result presentation |
| `CookieBanner` | cookie banner copy/actions/accessibility labels |
| `Footer` | seller/support/legal/payment surrounding labels and accessibility text |
| `Metadata` | ordinary Portal metadata title/description |
| `LegalPresentation` | non-authoritative chrome around canonical legal content |

Do not create a `Common` namespace only to deduplicate words such as “Account”, “Sign in”, or “Information” when their semantics differ by surface. Add shared keys only for genuine semantic reuse.

Catalog rules:

- use stable semantic keys, never a source-language sentence as a key;
- store complete user-facing thoughts;
- do not assemble translated sentences from fragments;
- use ICU interpolation for dynamic values;
- use ICU/rich-text messages where styling occurs inside one grammatical sentence;
- specifically, the styled home hero heading must remain one grammatical message (for example through `t.rich`) rather than separate sentence fragments;
- preserve semantic placeholder names across all locales;
- preserve rich-text tag names across all locales;
- all seven catalogs must have exact leaf-key parity;
- all leaf values must be strings;
- every message must parse as valid ICU;
- `pt.json` must use Brazilian Portuguese wording;
- `ru.json` is a complete real catalog, not a missing-message fallback.

---

## Client Message Delivery Design

Keep the root provider unchanged:

```tsx
<NextIntlClientProvider locale={locale} messages={null}>
```

For server-compatible components, use `getTranslations` directly.

For genuine Client Components:

1. the nearest server page/shell obtains the current messages on the server;
2. it passes only the required namespace object(s) to a nested `NextIntlClientProvider`;
3. the Client Component uses `useTranslations`.

Intended bounded delivery:

- shell header:
  - `Navigation`
  - `Auth`
- cookie banner:
  - `CookieBanner`
- auth-checkout:
  - `Auth`
  - `Checkout`
- account:
  - `Account`
- forgot/reset password:
  - `PasswordReset`

Do not pass `messages` into the root provider and do not pass unrelated namespaces to a client boundary.

`getMessages()` may read the complete current-locale catalog **on the server** to select the required namespaces. Only the selected namespace object(s) may be passed through the client-provider boundary.

---

## Catalog Validation Design

Use the existing web boundary-test workflow rather than creating another repository validation command.

Create:

```text
apps/web/tests/i18n-contract.test.mjs
```

This file is automatically included by the existing:

```text
npm run test:boundaries:web
```

and therefore by the repository `check` workflow.

For proper ICU validation, declare `@formatjs/icu-messageformat-parser` as an explicit `@anytoolai/web` dev dependency. The current lock already contains version `3.5.20` transitively through the installed i18n stack; making it direct is preferable to implementing a custom ICU parser or relying on an undeclared transitive import.

The catalog contract test must:

1. read supported route locales from `config/locales.json`;
2. require exactly one message file for each supported route locale and no unexpected locale catalog;
3. recursively flatten each catalog to semantic leaf keys;
4. require every leaf to be a string;
5. compute exact symmetric key parity across all seven catalogs;
6. parse every message using the ICU parser;
7. extract the semantic argument names and rich-text tag names from the parsed AST;
8. require the argument/tag signature for a given key to be identical in every locale;
9. report the locale and semantic key clearly when validation fails.

Do not create a runtime fallback or a second locale registry for validation.

---

# Step 1 — Establish the catalog contract and localize server-rendered Portal copy

**Status:** `done`

**Goal**  
Establish mechanically validated seven-locale message catalogs and move the server-rendered/currently server-compatible Portal presentation into them without changing routing, legal authority, commercial meaning, or client bundle boundaries.

**Scope / affected code**

Primary files:

- `apps/web/package.json`
- `package-lock.json`
- `apps/web/src/messages/{en,fr,it,de,es,ru,pt}.json`
- `apps/web/tests/i18n-contract.test.mjs` (new)
- `apps/web/src/i18n/metadata.ts`
- `apps/web/src/app/[locale]/layout.tsx`
- `apps/web/src/app/[locale]/page.tsx`
- `apps/web/src/app/[locale]/products/page.tsx`
- `apps/web/src/shared/ui/SiteShell.tsx` — server-owned nav labels only in this step
- `apps/web/src/shared/ui/Footer.tsx`
- `apps/web/src/features/catalog/catalog.ts`
- `apps/web/src/features/catalog/ProductOverview.tsx`
- `apps/web/src/features/payment-result/PaymentResultClient.tsx`
- `apps/web/src/features/legal/LegalPageView.tsx`
- `apps/web/tests/app-metadata.test.mjs`

Relevant existing contracts to preserve:

- `apps/web/src/i18n/request.ts`
- `apps/web/src/generated/locales.ts`
- `apps/web/src/generated/legal-manifest.json`
- `apps/web/src/features/legal/legal.ts`
- `apps/web/src/features/legal/routing.ts`

**Implementation decisions**

1. Add the catalog validation test described in **Catalog Validation Design**.
2. Add `@formatjs/icu-messageformat-parser` as an explicit web dev dependency using the already-resolved current major/version family. Do not add a custom parser.
3. Populate all seven catalogs for the namespaces introduced in this step:
   - `Navigation` server-owned shell labels;
   - `Home`;
   - `Catalog`;
   - `PaymentResult`;
   - `Footer`;
   - `Metadata`;
   - `LegalPresentation`.
4. Translate every key in all seven locales in the same change. `pt` means Brazilian Portuguese.
5. Keep server-compatible components server-compatible:
   - use `getTranslations` from `next-intl/server`;
   - make a component `async` only where required to call server translation APIs;
   - do not add `"use client"`.
6. Home hero heading:
   - keep it as one grammatical translation message;
   - use rich-text/ICU markup for the existing emphasized fragment;
   - do not concatenate two translated heading fragments.
7. Refactor `features/catalog/catalog.ts` so Portal-owned product/fact/highlight presentation text no longer lives as Russian literals in TypeScript:
   - retain source-owned facts (`seller`, `supportEmail`, payment-method source data);
   - retain locale-neutral structural identity such as product code, semantic message identity, and icon;
   - keep numeric/product/commercial facts as source-owned structured values rather than duplicating them as seven translated literals; where such values appear inside localized prose, interpolate the source-owned value through ICU/semantic message placeholders;
   - move only the translatable product type/tagline/description and surrounding product/fact/highlight presentation wording into `Catalog.*` messages;
   - do not change product codes, numeric/commercial facts, seller facts, payment availability, or expose new product functionality;
   - distinguish RU contour/legal facts from obsolete language-state copy: keep genuine RU contour/commercial/legal facts unchanged, but update Portal-owned claims that currently say or imply the **interface itself is RU-only** so they become truthful after 4B.2 (seven UI locales while canonical legal authority remains RU). In particular, the current presentation meaning `Localization = RU / interface and legal documents` must not survive unchanged as a claim about the localized UI. Do not use this copy cleanup to change region, tenant, currency, provider, or legal authority.
8. `ProductOverview` and the landing/products pages must resolve localized presentation through the catalogs.
9. `PaymentResultClient` currently has no client-only behavior. Keep its public export/name for compatibility, but localize it server-side; do not rename it merely because the historical name contains `Client`.
10. Localize only the **surrounding** legal presentation in `LegalPageView`:
    - eyebrow/help/accessibility/revision chrome → `LegalPresentation`;
    - `page.title`, `page.version`, and document blocks remain generated/source-owned RU content;
    - do not create non-RU legal routes;
    - do not alter legal parsing, manifest paths, versions, hashes, or evidence.
11. Footer:
    - localize labels such as legal address/support/payment section/accessibility text;
    - keep seller name/INN/OGRNIP/address values unchanged;
    - keep generated legal link labels/paths source-owned;
    - preserve the existing 4B.1 `lang="ru"` metadata on generated RU legal link text when rendered inside otherwise non-RU pages;
    - do not translate provider/payment-method source labels.
12. Metadata:
    - remove the Russian-only layout fallback title/description;
    - keep `APP_METADATA_BASE`;
    - minimally evolve `createLocalizedMetadata(routeLocale, pathname)` so it resolves `Metadata` title/description for the requested locale on the server;
    - preserve its existing canonical and alternate URL construction exactly;
    - keep `createCanonicalOnlyMetadata` and canonical RU legal metadata source-owned.
13. Do not change `i18n/request.ts`: it already loads exactly one locale catalog and has no missing-message fallback.
14. Update `app-metadata.test.mjs` so it protects:
    - no Russian-only default title/description remains in the locale layout;
    - root provider still has `messages={null}`;
    - existing routing/static/canonical architecture assertions remain intact.

**Invariants**

- `config/locales.json` remains the only locale registry.
- Supported route locales remain exactly `en/fr/it/de/es/ru/pt`.
- `pt -> pt-BR` remains unchanged.
- The root provider remains `messages={null}`.
- No Client Component is introduced merely for translation.
- Canonical/alternate URL behavior remains 4B.1 behavior.
- Canonical legal routes/title/body/version remain RU source-owned.
- Seller legal facts remain source-owned and unchanged.
- Checkout/payment availability remains unchanged.
- No currency/timezone is inferred from locale.
- No backend/API/database behavior changes.

**Out of scope**

- Client Component translation providers and client interaction copy except the server-owned part of `SiteShell`;
- auth/account/password-reset interactive localization;
- moving frontend error mapping out of `shared/api`;
- locale propagation to the backend;
- password-reset URL/email changes;
- locale switcher routing behavior;
- any 4B.3 work;
- visual redesign;
- broad SEO changes.

**AI prompt**

```text
Implement only Step 1 of ANY-529: establish the validated message-catalog contract and localize the current server-rendered/server-compatible Portal copy.

The architecture and decisions are already defined. Do not perform broad repository research and do not redesign the solution. Inspect only the directly relevant current files named below if needed to verify that the plan assumptions still hold.

Work from the current ANY-526-derived baseline.

Implement these exact decisions:

1. Add apps/web/tests/i18n-contract.test.mjs under the existing Node boundary-test workflow.
   - Read supported locales from config/locales.json.
   - Require exactly one catalog for each en/fr/it/de/es/ru/pt and no unexpected locale catalog.
   - Recursively flatten catalog leaves and require every leaf to be a string.
   - Enforce exact symmetric leaf-key parity across all seven catalogs.
   - Parse every message as ICU.
   - Compare ICU argument names and rich-text tag names for each semantic key across all locales.
   - Emit clear locale/key failures.
2. Add @formatjs/icu-messageformat-parser as an explicit @anytoolai/web dev dependency. The current lock already resolves the 3.5.x parser through the existing i18n stack; do not implement a custom ICU parser. You may run only the package-manager operation necessary to update the dependency lockfile. This is not a verification command.
3. Populate all seven message files with the Step 1 namespaces:
   Navigation (server-owned shell labels only), Home, Catalog, PaymentResult, Footer, Metadata, LegalPresentation.
   Keep exact key parity in every locale. Use natural en/fr/it/de/es/ru translations and Brazilian Portuguese for pt.
4. Use stable semantic keys, not Russian sentences as keys. Do not concatenate translated sentence fragments. Use ICU/rich text for the styled home hero heading so the heading remains one grammatical message.
5. Localize server-side with next-intl/server getTranslations. Do not convert server-compatible components to Client Components.
6. In features/catalog/catalog.ts keep source-owned seller/support/payment facts, numeric/product/commercial facts, and locale-neutral structural identities/icons, but remove Portal-owned Russian presentation wording from TypeScript. Keep numeric/commercial values as structured source-owned data and interpolate them through ICU/semantic messages where they appear in localized prose; do not duplicate those values independently across seven catalogs. Resolve the translatable product/fact/highlight wording from Catalog/Home messages without changing product codes or current product/payment behavior. Preserve the semantic content currently present except for obsolete claims that the interface itself is RU-only: after 4B.2 the UI has seven locales while canonical legal authority remains RU. Do not use that copy correction to change region, tenant, currency, provider, commercial, or legal semantics.
7. Localize:
   - app/[locale]/page.tsx
   - app/[locale]/products/page.tsx
   - the server-owned navigation labels in SiteShell.tsx
   - Footer.tsx
   - ProductOverview.tsx
   - PaymentResultClient.tsx, keeping its current export/name
   - LegalPageView.tsx presentation chrome only
8. Preserve legal authority:
   - generated legal title/body/version/path remain source-owned RU;
   - non-RU legal routes must not be created;
   - generated legal link labels remain source-owned;
   - preserve the existing 4B.1 lang="ru" metadata on rendered generated RU legal link text when it appears in otherwise non-RU pages.
9. Remove the Russian-only locale-layout default title/description. Keep metadataBase.
10. Minimally evolve createLocalizedMetadata(routeLocale, pathname) to resolve localized ordinary Metadata copy on the server while preserving canonical/alternate URL behavior. Keep createCanonicalOnlyMetadata and legal metadata source-owned.
11. Keep apps/web/src/i18n/request.ts and the 4B.1 locale/routing/navigation foundation unchanged.
12. Update apps/web/tests/app-metadata.test.mjs for the new localized-metadata baseline while preserving the existing messages={null}, static locale, and routing assertions.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, type checkers, builds, generators, or any other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed file;
- summarize the final Step 1 message namespaces and server-side translation boundaries;
- confirm which source-owned RU/legal/seller values intentionally remain outside catalogs;
- report the exact manual verification commands below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

Run manually from the repository root:

```bash
node --test apps/web/tests/i18n-contract.test.mjs
npm run test:boundaries:web
npm run typecheck:web
```

**Expected completion**

- Seven non-empty catalogs exist with exact key/ICU/placeholder parity for Step 1 namespaces.
- Home/products/catalog/payment-result/footer/ordinary metadata and legal presentation chrome render from locale messages.
- Portal-owned catalog presentation text is no longer Russian-only TypeScript data.
- Generated legal authority and seller/source facts are unchanged.
- The root provider still ships no catalog to clients.
- No routing/backend/database behavior changed.

**Proposed commit**

`feat(web): localize server-rendered portal copy`

---

# Step 2 — Localize the shared shell, auth UI, and auth-checkout boundary

**Status:** `done`

**Goal**  
Localize the true Client Components used globally and by auth-checkout, introduce bounded current-locale message delivery for them, and move auth error presentation out of shared transport without changing auth/session semantics.

**Scope / affected code**

Primary files:

- all seven `apps/web/src/messages/*.json`
- `apps/web/src/shared/ui/SiteShell.tsx`
- `apps/web/src/shared/ui/LocaleSwitcher.tsx`
- `apps/web/src/shared/ui/CookieBanner.tsx`
- `apps/web/src/shared/ui/HeaderAccount.tsx`
- `apps/web/src/shared/ui/AuthForm.tsx`
- `apps/web/src/shared/ui/index.ts`
- `apps/web/src/shared/ui/auth-errors.ts` (new)
- `apps/web/src/shared/config/legal-links.ts`
- `apps/web/src/app/[locale]/auth-checkout/page.tsx`
- `apps/web/src/features/checkout/CheckoutClient.tsx`
- `apps/web/src/shared/api/auth.ts`
- `apps/web/tests/setup/render-with-intl.tsx` (new small test helper)
- `apps/web/tests/components/AuthForm.test.tsx`
- `apps/web/tests/components/HeaderAccount.test.tsx`
- `apps/web/tests/components/LocaleSwitcher.test.tsx`
- `apps/web/tests/components/CheckoutClient.test.tsx`
- `apps/web/tests/components/AuthApiError.test.ts`
- `apps/web/tests/components/PresentationErrors.test.ts` (new)

**Implementation decisions**

1. Extend all seven catalogs with exact-parity keys for:
   - remaining `Navigation` client presentation;
   - `Auth`;
   - `Checkout`;
   - `CookieBanner`.
2. Keep language selector display names sourced only from `DISPLAY_NAME_BY_ROUTE_LOCALE`.
3. `SiteShell` remains a Server Component and becomes the bounded provider boundary for global clients:
   - shell/header provider gets only `Navigation` + `Auth`;
   - cookie provider gets only `CookieBanner`;
   - do not wrap `children` in a provider containing unrelated shell messages when a tighter boundary is available;
   - root provider remains `messages={null}`.
4. `LocaleSwitcher`:
   - use `useTranslations` only for accessibility/presentation strings;
   - keep all existing pathname/query preservation, locale list, `hrefLang`, generated display names, and blocked-path behavior unchanged.
5. `CookieBanner`:
   - localize banner/accessibility/action copy;
   - keep the existing storage key/acceptance behavior;
   - keep the canonical generated RU cookies path.
6. `HeaderAccount` and `AuthForm`:
   - localize all ordinary presentation/validation/action copy;
   - preserve localStorage/session event behavior;
   - preserve modal behavior;
   - preserve login/register payload semantics.
7. Registration acceptance:
   - keep `REGISTRATION_PERSONAL_CONSENT_TEXT` and `REGISTRATION_OFFER_CONSENT_TEXT` generated RU authority;
   - keep rendered acceptance statements `lang="ru"`;
   - do not translate them into `Auth` messages;
   - **do not derive link-match anchors from legal-manifest document titles**: the canonical acceptance statements use grammatical forms that do not equal those titles (for example, an instrumental form equivalent to `By consenting...` rather than the nominative title `Consent...`, and a declined form equivalent to `of the Public Offer` rather than the nominative document title `Public Offer for Services`);
   - keep the exact RU grammatical substrings needed to insert links as a small, explicitly source-coupled structural mapping (preferably next to `shared/config/legal-links.ts`, not in the locale catalogs). These substrings are not translatable UI copy; they are anchors into the generated canonical RU statement;
   - add/retain a focused regression assertion that every configured anchor is present in the corresponding generated acceptance statement and resolves to the expected generated canonical legal path, so a future canonical-text change fails loudly instead of silently producing incorrect links.
8. Keep the current `AuthForm` component boundary. Do not redesign authentication.
   - The duplicated `personalConsentError` / `offerConsentError` props may be removed because validation presentation now belongs to `Auth` messages inside the form.
   - Keep genuinely contextual props such as title/prompt/notice/error/initial mode/callbacks.
9. Add a small Presentation helper in `shared/ui/auth-errors.ts` that maps language-neutral error facts to a closed semantic `Auth` error-message key.
   - known mappings:
     - 409 + `email_already_registered`;
     - 401 + `invalid_credentials`;
     - 400 + `missing_personal_consent`;
     - 400 + `missing_offer_consent`;
     - 500 + `internal_server_error`;
     - `ApiContractError`;
     - network/abort failure;
     - generic fallback.
   - inspect `ApiError.status` and `apiErrorCode`;
   - never inspect human prose in `error.message`.
10. Both `HeaderAccount` and `CheckoutClient` must use that Presentation mapping plus `Auth` translations.
11. Because `CheckoutClient` needs `Auth` and `Checkout` messages, `app/[locale]/auth-checkout/page.tsx` becomes the nearest server provider boundary and passes only those two namespaces.
12. Localize all current `CheckoutClient` ordinary copy without changing its auth/session-only business behavior or unavailable-payment semantics.
13. Remove `authErrorMessage` from `shared/api/auth.ts` after all current consumers use the Presentation mapping.
14. Keep `passwordResetErrorMessage` temporarily in `shared/api/auth.ts` until Step 3; do not mix password-reset migration into this step.
15. Add a small test helper that renders a component under a `NextIntlClientProvider` with an explicitly supplied locale + bounded message object. Do not globally mock translations.
16. Update existing AuthForm/HeaderAccount/LocaleSwitcher/CheckoutClient tests to use the RU catalog for deep behavior and add one focused non-RU presentation assertion where useful.
17. Migrate the auth-presentation assertions currently owned by `AuthApiError.test.ts`:
    - keep its language-neutral transport / `apiErrorCode` coverage;
    - remove assertions that depend on `authErrorMessage`;
    - move equivalent auth semantic-key classification coverage into `PresentationErrors.test.ts`.
18. Add focused auth error-key mapping tests in `PresentationErrors.test.ts`.

**Invariants**

- Locale switcher routing behavior is unchanged.
- Auth/session storage survives locale navigation exactly as in 4B.1.
- Generated language display names remain the only selector-name source.
- Registration acceptance evidence/text remains canonical RU.
- No auth API request shape or response decoder changes.
- No backend `Accept-Language` header is added.
- No locale is persisted in auth/session/user data.
- Checkout/payment remains unavailable exactly as before.
- Root `messages={null}` remains unchanged.
- Only current-locale bounded namespaces cross client boundaries.

**Out of scope**

- Account page localization;
- password-reset request/confirmation localization;
- password-reset error mapping;
- backend locale propagation;
- reset-email URL/content changes;
- locale switcher behavior changes;
- legal document translation;
- provider/payment implementation;
- unrelated auth refactoring.

**AI prompt**

```text
Implement only Step 2 of ANY-529: localize the shared shell/auth UI and auth-checkout Client Components using bounded current-locale message delivery, and move auth error presentation out of shared API transport.

Step 1 is assumed complete and manually verified. The seven catalogs and i18n-contract test already exist.

Do not perform broad repository research. Inspect only the named current files as needed to verify the assumptions.

Implement these exact decisions:

1. Extend all seven catalogs with exact-parity keys for:
   - remaining Navigation client presentation;
   - Auth;
   - Checkout;
   - CookieBanner.
   Use natural en/fr/it/de/es/ru copy and Brazilian Portuguese for pt.
2. Keep DISPLAY_NAME_BY_ROUTE_LOCALE as the only language-selector display-name authority. Do not duplicate language names in catalogs.
3. Keep the root NextIntlClientProvider messages={null}.
4. Keep SiteShell a Server Component and make it the nearest bounded provider boundary:
   - header/shell clients receive only Navigation + Auth;
   - CookieBanner receives only CookieBanner;
   - do not pass the full current catalog and do not wrap unrelated children with unnecessary namespaces.
5. Localize LocaleSwitcher presentation/accessibility copy only. Do not change its path/query preservation, hrefLang, supported locales, generated display names, or blocked-route behavior.
6. Localize CookieBanner copy only. Keep its storage behavior and generated canonical RU cookie-policy path.
7. Localize HeaderAccount and AuthForm ordinary copy and validation messages while preserving all session/modal/auth behavior.
8. Preserve generated registration acceptance authority:
   - REGISTRATION_PERSONAL_CONSENT_TEXT and REGISTRATION_OFFER_CONSENT_TEXT stay generated RU text;
   - rendered statements stay lang="ru";
   - do not put those statements in message catalogs.
9. Keep the registration-consent link anchors explicitly coupled to the generated canonical RU statements. Do not use manifest document titles as anchors because their grammatical forms differ from the acceptance text. Put the minimal exact anchor substrings in a clearly named source-owned structural mapping near shared/config/legal-links.ts (or an equally narrow existing config owner), map them to the generated canonical legal paths, and protect the mapping with a focused test that proves each anchor occurs in the generated statement **and resolves to the expected generated canonical legal path**.
10. Keep the existing AuthForm interaction boundary. Remove personalConsentError/offerConsentError props if they are now redundant because the form resolves those validation messages from Auth translations. Do not redesign the form.
11. Add shared/ui/auth-errors.ts as Presentation code that returns a closed semantic Auth error-message key based only on:
   - ApiError.status;
   - apiErrorCode(error);
   - ApiContractError;
   - network/AbortError classification;
   - generic fallback.
   Map:
   - 409 + email_already_registered;
   - 401 + invalid_credentials;
   - 400 + missing_personal_consent;
   - 400 + missing_offer_consent;
   - 500 + internal_server_error;
   - contract failure;
   - network/timeout failure;
   - generic fallback.
   Never parse error.message or backend prose.
12. Update both HeaderAccount and CheckoutClient to translate that semantic key in Presentation.
13. Make app/[locale]/auth-checkout/page.tsx the bounded provider boundary for CheckoutClient and pass only Auth + Checkout.
14. Localize the rest of CheckoutClient ordinary presentation while preserving its current auth/session-only behavior and unavailable-payment semantics.
15. Remove authErrorMessage from shared/api/auth.ts after all auth consumers have migrated. Leave passwordResetErrorMessage untouched for Step 3.
16. Add a small tests/setup/render-with-intl.tsx helper that renders with an explicitly provided locale and bounded messages; do not globally mock translations.
17. Update AuthForm.test.tsx, HeaderAccount.test.tsx, LocaleSwitcher.test.tsx, and CheckoutClient.test.tsx to preserve existing behavioral coverage under the RU catalog. Because CheckoutClient will consume translations, do not leave its existing direct render outside the intl test wrapper. Add a focused non-RU presentation assertion only where it adds signal.
18. Update AuthApiError.test.ts for the new ownership boundary:
    - retain language-neutral ApiError/apiErrorCode transport classification coverage;
    - remove assertions/imports that depend on authErrorMessage;
    - do not delete passwordResetErrorMessage coverage yet because Step 3 still owns that migration.
19. Add PresentationErrors.test.ts with focused auth semantic-key mapping coverage.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, type checkers, builds, generators, or any other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed file;
- summarize the exact nested client message boundaries;
- confirm authErrorMessage is gone from shared API transport and passwordResetErrorMessage intentionally remains for Step 3;
- confirm registration acceptance text is still generated RU authority;
- report the exact manual verification commands below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

Run manually:

```bash
node --test apps/web/tests/i18n-contract.test.mjs
npm --workspace @anytoolai/web run test:components -- tests/components/AuthForm.test.tsx tests/components/HeaderAccount.test.tsx tests/components/LocaleSwitcher.test.tsx tests/components/CheckoutClient.test.tsx tests/components/AuthApiError.test.ts tests/components/PresentationErrors.test.ts
npm run typecheck:web
```

**Expected completion**

- Shell, locale-switcher presentation, cookie banner, header auth, shared auth form, and auth-checkout are localized in all seven catalogs.
- Client Components receive only bounded current-locale namespaces.
- Auth error facts are converted to semantic localized messages in Presentation, not shared transport.
- Canonical registration acceptance remains RU/source-owned.
- Existing auth/session/switching behavior is unchanged.

**Proposed commit**

`feat(web): localize shell and auth surfaces`

---

# Step 3 — Localize account and password recovery and finish the UI error boundary

**Status:** `done`

**Goal**  
Localize the remaining interactive account/password-recovery surfaces, move password-reset presentation mapping out of shared API transport, and leave the entire shared auth transport layer language-neutral.

**Scope / affected code**

Primary files:

- all seven `apps/web/src/messages/*.json`
- `apps/web/src/app/[locale]/account/page.tsx`
- `apps/web/src/features/account/AccountClient.tsx`
- `apps/web/src/app/[locale]/forgot-password/page.tsx`
- `apps/web/src/app/[locale]/reset-password/page.tsx`
- `apps/web/src/features/password-reset/PasswordResetRequestClient.tsx`
- `apps/web/src/features/password-reset/PasswordResetConfirmClient.tsx`
- `apps/web/src/features/password-reset/errors.ts` (new)
- `apps/web/src/features/password-reset/index.ts`
- `apps/web/src/shared/api/auth.ts`
- `apps/web/tests/components/PresentationErrors.test.ts`
- `apps/web/tests/components/AuthApiError.test.ts`
- `apps/web/tests/components/AccountClient.test.tsx`
- focused password-reset component tests only if needed to preserve touched behavior
- `apps/web/e2e/password-reset.spec.ts` only for expectation updates required by the localized RU baseline; do not broaden E2E here

**Implementation decisions**

1. Extend all seven catalogs with exact-parity:
   - `Account`;
   - `PasswordReset`.
2. `app/[locale]/account/page.tsx` is the nearest provider boundary for `AccountClient` and passes only `Account`.
3. Localize all AccountClient presentation states:
   - loading;
   - signed out;
   - authenticated summary;
   - unavailable billing information;
   - actions/labels.
4. Preserve all existing account/session behavior, including the current policy that local session removal still signs the browser out even if logout transport fails.
5. `forgot-password/page.tsx` and `reset-password/page.tsx` are the provider boundaries for their Client Components and pass only `PasswordReset`.
6. Localize the reset-password Suspense fallback server-side.
7. Localize all current password-reset request/confirmation:
   - labels;
   - validation;
   - generic request success;
   - confirmation success;
   - actions;
   - errors.
8. Preserve the anti-enumeration semantics of the request success message: success must remain generic regardless of account existence.
9. Add `features/password-reset/errors.ts` as Presentation code returning a closed semantic PasswordReset error key.
10. Required password-reset mappings:
    - 400 + `invalid_or_expired_reset_token` → invalid/expired link message;
    - 429 + `password_reset_rate_limited` → explicit rate-limit message;
    - HTTP 422 → invalid-input message;
    - 500 + `internal_server_error` → localized server-error message;
    - `ApiContractError` → localized contract-error message;
    - network/AbortError → localized network message;
    - unknown → generic localized fallback.
11. Use `apiErrorCode`; never inspect `error.message` or backend human prose.
12. Remove `passwordResetErrorMessage` from `shared/api/auth.ts` after all consumers migrate.
13. After this step, `shared/api/auth.ts` must contain transport/decoder/error facts only and no language-specific presentation strings.
14. Preserve reset confirmation security/session behavior exactly:
    - token read from fragment only;
    - fragment removed after capture;
    - token never moved to query/path/server state;
    - locale switcher remains unavailable due the existing 4B.1 rule;
    - successful reset still clears the current browser session state.
15. Do not “clean up” the existing local session constants in the reset component unless required by the localization change; that is unrelated refactoring.
16. Do not add `Accept-Language`, route locale, or any locale field to password-reset API requests. Backend locale propagation is 4B.3.
17. Update `AccountClient.test.tsx` to render through the bounded RU intl test helper while preserving all current session/logout assertions.
18. Finish migrating the existing `AuthApiError.test.ts` ownership:
    - retain language-neutral `ApiError` / `apiErrorCode` transport coverage;
    - remove remaining assertions/imports that depend on `passwordResetErrorMessage`;
    - move equivalent password-reset semantic-key classification coverage into `PresentationErrors.test.ts`.
19. Extend `PresentationErrors.test.ts` with the password-reset mapping matrix, especially the explicit 429 rate-limit case.
20. Update the existing RU password-reset E2E text expectations only as necessary; keep the current deep behavioral test in one representative locale rather than multiplying it by seven in this step.

**Invariants**

- Account/auth/session semantics are unchanged.
- Password-reset API payloads are unchanged.
- Password-reset request anti-enumeration semantics are unchanged.
- Reset token remains fragment/client-only.
- Locale switching stays unavailable on reset confirmation.
- No locale is sent to the backend.
- Shared API transport is language-neutral after this step.
- No backend/API/schema/migration changes.
- All seven catalogs remain exact-parity and valid ICU.

**Out of scope**

- backend reset URL generation;
- email subject/body localization;
- adding `Accept-Language`;
- locale persistence;
- auth/session redesign;
- global test matrix / final source guards;
- provider/payment/billing work;
- visual redesign.

**AI prompt**

```text
Implement only Step 3 of ANY-529: localize account and password recovery, and finish moving user-facing error presentation out of shared API transport.

Steps 1 and 2 are assumed complete and manually verified.

Do not perform broad repository research. Inspect only the named current files as needed.

Implement these exact decisions:

1. Extend every locale catalog with exact-parity Account and PasswordReset namespaces. Use Brazilian Portuguese for pt.
2. Make app/[locale]/account/page.tsx the nearest bounded provider for AccountClient and pass only Account messages.
3. Localize AccountClient loading, signed-out, authenticated, action, and unavailable-billing presentation without changing session behavior.
4. Make forgot-password/page.tsx and reset-password/page.tsx the nearest bounded providers for their password-reset clients and pass only PasswordReset.
5. Localize the reset-password Suspense fallback server-side.
6. Localize all PasswordResetRequestClient and PasswordResetConfirmClient ordinary copy, local validation, success notices, actions, and errors.
7. Keep the password-reset request success message enumeration-safe and generic.
8. Add features/password-reset/errors.ts as Presentation code that returns a closed semantic PasswordReset error-message key.
9. Map only language-neutral facts:
   - HTTP 400 + invalid_or_expired_reset_token;
   - HTTP 429 + password_reset_rate_limited;
   - HTTP 422 validation;
   - HTTP 500 + internal_server_error;
   - ApiContractError;
   - network/AbortError;
   - generic fallback.
   Use apiErrorCode. Never parse error.message or backend prose.
10. Update both password-reset clients to translate the returned semantic key.
11. Remove passwordResetErrorMessage from shared/api/auth.ts after all consumers migrate.
12. At the end of this step, shared/api/auth.ts must retain transport, decoders, ApiError, ApiContractError, apiErrorCode, session constants, and request functions, but no localized user-facing messages.
13. Preserve the reset token contract exactly:
   - read token from URL fragment on the client;
   - remove the fragment after capture;
   - never move the token into query/path/server-visible state;
   - keep locale switching unavailable through the existing 4B.1 rule.
14. Preserve successful-reset browser session invalidation.
15. Do not refactor unrelated session constants or auth code.
16. Do not add Accept-Language, route locale, or any locale metadata to API requests. That is 4B.3.
17. Update AccountClient.test.tsx to use the bounded RU intl test wrapper while preserving the current signed-out/session/logout behavioral coverage.
18. Update AuthApiError.test.ts to remove the remaining passwordResetErrorMessage imports/assertions after the production helper is removed. Keep language-neutral ApiError/apiErrorCode transport coverage.
19. Extend PresentationErrors.test.ts with the full password-reset semantic-key mapping matrix including the explicit rate-limit case.
20. Update existing RU password-reset E2E text expectations only if required by the localized RU catalog. Do not create a seven-locale password-reset E2E matrix here.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, type checkers, builds, generators, or any other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed file;
- summarize the Account and PasswordReset client-provider boundaries;
- list the exact password-reset error-code/status mappings;
- confirm shared/api/auth.ts no longer owns any localized presentation strings;
- confirm no locale metadata was added to backend requests and the fragment-token flow is unchanged;
- report the exact manual verification commands below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

Run manually:

```bash
node --test apps/web/tests/i18n-contract.test.mjs
npm --workspace @anytoolai/web run test:components -- tests/components/AccountClient.test.tsx tests/components/AuthApiError.test.ts tests/components/PresentationErrors.test.ts
npm run typecheck:web
```

If Step 3 adds or updates a focused password-reset component test, include that exact file in the Vitest command above before committing.

**Expected completion**

- Account and both password-reset browser surfaces are localized.
- Password-reset rate-limit and other known failures receive localized Presentation messages.
- `shared/api/auth.ts` is fully language-neutral.
- Password-reset security/session behavior is unchanged.
- No 4B.3 locale propagation or email/reset-link work has been pulled forward.

**Proposed commit**

`feat(web): localize account and password recovery`

---

# Step 4 — Add cross-locale guards, smoke coverage, documentation, and final 4B.2 verification

**Status:** `done`

**Goal**  
Protect the completed localization baseline against missing/incompatible catalogs, accidental broad client message delivery, language-specific presentation leaking back into shared API transport, and regressions in locale/legal/formatting behavior; update durable project guidance and prove the 4B.2 acceptance surface without multiplying the whole suite by seven. The broader cross-language sweep/guard for newly hardcoded ordinary UI copy remains 4B.3 work.

**Scope / affected code**

Primary files:

- `apps/web/tests/i18n-contract.test.mjs`
- `apps/web/tests/eslint-boundaries.test.mjs` or the existing boundary-test owner used for the shared/API presentation guard
- `apps/web/e2e/locale-routing.spec.ts`
- `apps/web/e2e/password-reset.spec.ts` only if the completed RU copy changed
- `apps/web/tests/app-metadata.test.mjs`
- `apps/web/tests/components/FormattingLocale.test.ts`
- existing focused component tests touched in Steps 2–3
- `ARCHITECTURE.md`
- `apps/web/AGENTS.md`
- `docs/engineering/CODING_CONVENTIONS.md`

Only touch implementation files again if the final cross-locale/guard verification exposes a real 4B.2 defect.

**Implementation decisions**

1. Before implementing this final step, the working branch must contain the latest/final `ANY-526` predecessor state, including any final `ANY-408` fixes already absorbed by `ANY-526`; do not merge/replay `ANY-408` as a second independent baseline.
2. Do not re-research the repository. Inspect only the 4B.1 files affected by any newly synchronized predecessor changes and stop if they materially contradict a locked contract in this plan.
3. Extend the deterministic 4B.2 localization guardrails without creating another workflow.
4. Keep the catalog parity/ICU/placeholder checks in `i18n-contract.test.mjs`.
5. Add a bounded guard that proves shared API transport cannot silently regain UI localization ownership:
   - `shared/api/auth.ts` must not export `authErrorMessage` or `passwordResetErrorMessage`;
   - `src/shared/api` must not import next-intl/message catalogs or contain locale-specific user-facing presentation copy;
   - language-neutral machine/error identifiers such as decoder failure codes, route strings, protocol/status constants, and API error codes remain allowed.
6. Do **not** introduce the general hardcoded ordinary-UI literal sweep/ESLint rule in 4B.2. The parent 4B.3 stage owns the final bounded sweep and durable guard against hardcoded Russian/English (or other-language) UI copy across active UI source.
7. Preserve the existing 4B.1 `/ru` route-literal guard unchanged, including its coverage for JSX expression-valued href literals such as `href={"/ru/products"}` and its generated-legal-path exception.
8. Update `locale-routing.spec.ts`:
   - keep all existing routing/negotiation/legal/switching assertions, including root-query preservation and canonical RU footer-link `lang="ru"` coverage on a non-RU route;
   - replace assertions that intentionally expected Russian copy on non-RU routes;
   - add a lightweight seven-locale content smoke for a representative ordinary page and shell/catalog presentation;
   - verify at least representative localized metadata (including `pt`) while preserving canonical/hreflang URL assertions;
   - do not run every behavioral scenario seven times.
9. Keep legal-route tests RU-only:
   - `/ru/<legal>` remains 200;
   - non-RU legal variants remain 404;
   - no locale switcher / no fake alternates;
   - canonical source-owned legal content remains RU.
10. Preserve the existing representative-locale deep password-reset tests rather than multiplying them by seven.
11. Strengthen `FormattingLocale.test.ts` only as needed to demonstrate that the `pt` route resolves actual Intl formatting identity `pt-BR`.
12. Do not introduce new date/number/currency formatting code just to satisfy the ticket:
   - current UI has no ordinary locale-sensitive displayed date/number/currency requiring a new formatter;
   - INN/OGRNIP/source IDs are identifiers;
   - legal version is source-owned version identity;
   - no currency or timezone may be inferred from UI locale.
13. Update durable docs with the implemented 4B.2 rules:
   - canonical message ownership under `apps/web/src/messages`;
   - seven-locale completeness and ICU/placeholder parity;
   - server-first translation;
   - bounded nested client providers while root remains `messages={null}`;
   - UI error localization boundary vs language-neutral `shared/api`;
   - `routeLocale -> intlLocale` formatting contract;
   - currency/timezone independent from locale;
   - canonical RU legal/generated registration evidence and other source-owned exclusions;
   - broader hardcoded-UI-copy final sweep/guard and backend locale propagation/reset email+URL localization explicitly handed off to 4B.3.
14. Do not turn the execution plan or docs into a competing locale source of truth. `config/locales.json` + implemented architecture remain authoritative.

**Invariants**

- All 4B.1 routing/navigation/legal/reset-token tests remain valid.
- Seven locales are complete; no routine missing-message fallback.
- Root client provider still has `messages={null}`.
- Client boundaries remain namespace-bounded.
- Legal authority remains RU-only.
- Auth/session state is locale-neutral.
- Locale never chooses region/provider/currency/timezone.
- No backend locale propagation exists yet.
- No database migration/API contract change.
- No provider/LBX work.

**Out of scope**

- 4B.3 email/reset-link/backend locale propagation;
- locale cookies/profile persistence;
- translated canonical legal documents;
- billing/provider implementation;
- E2E multiplication across every locale and every workflow;
- visual redesign;
- broad SEO work;
- unrelated cleanup discovered during final verification.

**AI prompt**

```text
Implement only Step 4 of ANY-529: add the final cross-locale guards/smoke coverage/docs and close the 4B.2 baseline.

Steps 1–3 are assumed complete and manually verified. The user is responsible for synchronizing the branch with the latest/final ANY-526 review fixes before this step.

Do not perform broad repository research. Inspect only directly relevant files and any 4B.1 files that were actually changed by predecessor synchronization. If a synchronized predecessor change materially contradicts a locked assumption in this plan, stop and report it instead of redesigning 4B.2.

Implement these exact decisions:

1. Keep the existing i18n-contract catalog tests and extend them only for final durable 4B.2 ownership checks.
2. Add a bounded guard that shared/api/auth.ts cannot regain authErrorMessage/passwordResetErrorMessage, next-intl/catalog dependencies, or locale-specific user-facing presentation copy. Do not reject language-neutral machine/error identifiers such as decoder failure codes, protocol strings, route strings, or status constants.
3. Do not add the general hardcoded ordinary-UI literal ESLint/boundary rule in this step. The final cross-language hardcoded-copy sweep/guard belongs to 4B.3.
4. Preserve the existing literal-/ru routing guard unchanged, including JSX expression-valued href coverage and the generated canonical legal-path exception.
5. Update locale-routing.spec.ts without reworking routing:
   - keep negotiation/explicit-locale/not-found/html-lang/switch-preservation/legal tests;
   - preserve the existing root-negotiation query-string regression and non-RU footer `lang="ru"` assertions;
   - replace old expectations that deliberately saw Russian UI on non-RU routes;
   - add a lightweight seven-locale representative page/shell/catalog content smoke;
   - verify representative localized metadata including pt/pt-BR while preserving canonical and hreflang URL behavior;
   - do not multiply the full behavioral suite by seven.
6. Keep password-reset deep E2E coverage in the representative RU locale and preserve the fragment-token/no-switch assertions.
7. Strengthen FormattingLocale.test.ts only enough to prove the pt route resolves pt-BR Intl semantics. Do not invent new production formatting abstractions or currency/timezone behavior.
8. Update ARCHITECTURE.md, apps/web/AGENTS.md, and docs/engineering/CODING_CONVENTIONS.md with the implemented 4B.2 baseline:
    - message catalogs are canonical Portal-owned UI copy;
    - exact seven-locale key/ICU/placeholder parity is mandatory;
    - translations are server-first;
    - true Client Components receive bounded current-locale namespaces from the nearest server boundary;
    - root provider remains messages={null};
    - shared API transport is language-neutral and Presentation maps error facts to localized messages;
    - formatting uses the established intlLocale mapping;
    - locale never implies currency/timezone/region/provider;
    - canonical legal/generated acceptance and other source-owned content stay outside ordinary catalogs;
    - the broader hardcoded-UI-copy final sweep/guard and backend Accept-Language/reset URL/email localization are explicitly 4B.3.
9. Do not modify production implementation files unless these final guards/tests reveal a concrete 4B.2 defect. If so, fix only that defect.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, type checkers, builds, generators, or any other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed file;
- summarize the final catalog/API-boundary guards and explicitly note that the general hardcoded-UI-copy sweep/guard remains deferred to 4B.3;
- summarize the seven-locale smoke and metadata coverage;
- confirm 4B.1 legal/routing/reset-token invariants remain intact;
- confirm 4B.3 work was not implemented;
- report the exact manual verification commands below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

First confirm manually that the branch contains the final/current `ANY-526` predecessor output according to your normal branch workflow.

Then run:

```bash
npm run check:fast
APP_PUBLIC_BASE_URL=https://payments.example.test npm run build:web
npm run test:e2e -- apps/web/e2e/locale-routing.spec.ts apps/web/e2e/password-reset.spec.ts
```

The E2E command requires the normal running harness/browser prerequisites already used by this repository.

**Expected completion**

- Every current ordinary Portal-owned UI surface is localized through the seven catalogs.
- All seven catalogs have exact key parity, valid ICU syntax, and argument/tag parity.
- Representative ordinary UI and metadata render correctly across all seven route locales.
- `pt` uses Brazilian Portuguese copy and `pt-BR` language/Intl semantics.
- The root does not serialize the complete catalog to clients; true Client Components receive only bounded namespaces.
- Shared API transport contains no localized presentation ownership.
- 4B.2 guards protect catalog completeness/ICU parity and keep localized presentation out of shared API transport; the broader cross-language hardcoded-UI-copy sweep/guard remains explicitly deferred to 4B.3.
- Canonical RU legal routes/content/acceptance evidence remain unchanged.
- Account/auth/password-reset behavior and fragment-token security are unchanged.
- No currency/timezone/region/provider behavior depends on locale.
- No backend locale propagation, reset URL localization, or email localization has been implemented.
- Durable docs describe the new 4B.2 baseline and explicitly hand backend communications to 4B.3.

**Proposed commit**

`test(web): harden portal localization contracts`

---

## Final Scope Audit

Before closing `ANY-529`, verify the implementation satisfies all of the following:

### Covered by this plan

- complete ordinary Portal UI localization for `en/fr/it/de/es/ru/pt`;
- Brazilian Portuguese semantics for `pt`;
- ordinary localized metadata;
- semantic next-intl catalog ownership;
- server-first translations;
- bounded Client Component messages;
- auth and password-reset localized Presentation error mapping;
- language-neutral shared API transport;
- password-reset rate-limit presentation;
- exact catalog key parity;
- ICU syntax validation;
- placeholder/rich-tag parity;
- representative seven-locale smoke coverage;
- `pt -> pt-BR` formatting coverage;
- canonical/source-owned content boundaries;
- durable catalog/API-boundary guards, with the broader hardcoded-UI-copy sweep/guard deferred to 4B.3;
- durable architecture/coding/web documentation.

### Explicitly not covered

- route-tree or locale negotiation redesign;
- translated route slugs;
- locale persistence;
- auth/session persistence changes;
- database migrations;
- translated canonical RU legal documents;
- translated registration acceptance authority;
- backend `Accept-Language` propagation;
- locale in ordinary API business payloads;
- locale-aware password-reset URL generation;
- password-reset email localization;
- provider/LBX UI or integration;
- future catalog/payment/subscription functionality;
- CMS/TMS/runtime machine translation;
- region/currency/timezone inference from locale.

---

## Follow-up / 4B.3 Handoff

After `ANY-529`, 4B.3 can rely on these completed inputs without reopening browser routing or UI-catalog architecture:

- exact shared locale contract from 4B.1;
- complete current UI message catalogs from 4B.2;
- language-neutral API error transport;
- route locale remaining Presentation state;
- reset confirmation token remaining fragment/client-only;
- backend locale propagation still absent and therefore explicitly owned by 4B.3.

4B.3 should own the later backend request-locale propagation and locale-aware backend-originated communications, including password-reset URL/email generation. It must not move those responsibilities backward into 4B.2.
