# Web Agent Guide

Read the root `AGENTS.md`, [the `ru` journey](../../docs/product/ru-mvp.md),
[contours](../../docs/architecture/contours.md),
[design](../../docs/DESIGN.md), and the
[web section of coding conventions](../../docs/engineering/CODING_CONVENTIONS.md#web--typescript)
before frontend work.

## Conventions

- Read `response.json()` and `JSON.parse` results as `unknown`; production
  lint rejects direct assertions on these calls. Storage/query values still
  require boundary validation.
- Successful JSON from our own FastAPI service is trusted once in
  `shared/api/transport.ts` using generated TypeScript contracts. Endpoint
  adapters reuse its exported `getJson<T>` / `postJson<T>` helpers with
  generated response types. The private decoding helper's documented assertion
  is not runtime validation. Do not cast API JSON in features/components or
  introduce another runtime schema authority.
- Import backend wire DTOs from generated contracts; keep form/UI/view models
  local and do not copy response fields in components.
- Inspect errors with `ApiError.status` and `detail.code`, never
  `message.includes(...)`.

## HTTP API contract authority

Web API boundaries consume generated contracts from
`src/generated/api-contracts/`; they do not independently redeclare backend
wire DTO fields. The authority chain is:

```text
FastAPI/Pydantic
  → app.openapi()
  → docs/generated/openapi.json
  → generated TypeScript wire contracts in apps/web/src/generated/api-contracts/
  → shared API transport trust boundary
  → endpoint adapters
  → features/UI and view state
```

Use `npm run generate` to update generated contracts and
`npm run generate:check` to check freshness. For a future Portal-owned,
web-consumed API, define backend Pydantic models, expose durable named OpenAPI
components, generate, consume the generated TypeScript contract, use the shared
API transport trust boundary, and keep form/UI/view state local. Backend owns
runtime validation; frontend contracts provide compile-time ownership. Invalid
successful JSON syntax remains `ApiContractError`; no structural response
re-validation runs in the browser.
Stop for the owning architecture/API decision if the backend API or suitable
named schema is missing, generation cannot faithfully generate the required
TypeScript shape, the frontend would redefine wire meaning, the data belongs to External Billing
or Platform Kernel, or transport/auth redesign is required. Shared values that
do not cross HTTP, such as locale mappings or legal source text, retain their
own canonical source and generation path.

## Locale routing

- `config/locales.json` is the canonical locale contract; generated web and API
  locale artifacts must stay in sync through `npm run generate` and
  `npm run generate:check`.
- The exact route locales are `en`, `fr`, `it`, `de`, `es`, `ru`, and `pt`.
  `routeLocale` is the URL/next-intl identity, while `languageTag` and
  `intlLocale` own document language and formatting. The `pt` route uses
  `pt-BR` for both.
- Ordinary routes live under `app/[locale]`, whose layout derives the document
  language. `/` alone negotiates Accept-Language; explicit locale prefixes are
  authoritative, and other unprefixed app paths stay not-found.
- Keep `localeDetection` and `localeCookie` disabled. Do not persist locale in
  cookies, localStorage, or user records, and do not derive contour/region,
  provider, currency, or timezone from it.
- Use `@/i18n/navigation` for ordinary links, redirects, and route
  construction. Do not hardcode `/ru` ordinary routes. Generated canonical RU
  legal paths remain the intentional RU-only exception.
- Canonical and alternate metadata uses the required `APP_PUBLIC_BASE_URL`
  server/build origin and is owned by the application.
- Do not offer locale switching on generated legal pages or reset-password
  confirmation.
- Password-reset communication derives the canonical `languageTag` from the
  explicit validated `routeLocale` at the forgot-password route boundary and
  sends it as `Accept-Language` metadata on that request only. API Presentation
  ignores malformed and unsupported candidates individually, then passes only
  the winning canonical `RouteLocale` inward. If no valid supported canonical
  candidate remains, including for a missing header or one containing only
  malformed or unsupported candidates, it falls back to the generated default
  `ru` route locale. Do not derive or persist tenant, region, identity,
  provider, currency, timezone, or other application state from locale.

## Localization ownership

- `src/messages/*.json` is the canonical home of Portal-owned UI and ordinary
  metadata copy. The `en`, `fr`, `it`, `de`, `es`, `ru`, and `pt` catalogs must
  have exact leaf-key parity, valid ICU syntax, and matching argument and tag
  signatures. `pt` copy is Brazilian Portuguese.
- Translate in Server Components first. The root `NextIntlClientProvider`
  remains `messages={null}`; a true Client Component receives only the
  current-locale namespace or subset it needs from the nearest server boundary.
- `shared/api` stays language-neutral. It exposes machine status/error facts;
  the owning Presentation/UI maps those facts to localized messages. It may
  carry an already-canonical password-reset language tag as request metadata,
  but it does not own route-to-language mapping or localized presentation.
- Canonical RU legal documents and generated registration acceptance text stay
  source-owned and retain `lang="ru"`. Seller/provider facts, support addresses,
  identifiers, and user-entered content also remain source-owned; localize only
  the surrounding Portal presentation.
- Formatting resolves `routeLocale` through the generated `intlLocale` mapping.
  Locale never selects contour/region, provider, currency, or timezone.

## Boundaries

- App routes compose feature entrypoints.
- Feature modules own product behavior.
- Shared modules own reusable API contracts, configuration, and UI primitives.
- Features must not deep-import another feature's internals.

## UI rules

- Ordinary Portal-owned customer-facing copy follows the active route catalog.
  Do not translate or relabel canonical RU legal/source-owned content as if it
  were ordinary UI copy.
- The i18n contract test rejects direct human-readable JSX copy in active
  localized app, feature, and shared UI presentation. New ordinary copy belongs
  in the locale catalogs; intentional source-owned exceptions must be exact,
  reviewable path/surface/value entries.
- Use the current [Bundle 3 tokens and rules](../../docs/design-system/bundle3/README.md)
  as the single design-system authority. The approved ANY-539 RU Portal mockup
  supplied as the local visual reference during implementation defines the
  target visual language for affected surfaces: deep navy, opaque dark-blue
  panels, thin blue borders, amber actions, compact radii/spacing and Manrope
  (the ANY-636 basic Cyrillic coverage correction). Legacy glass/bento, indigo
  gradient and radial-glow patterns are no longer
  mandatory. Do not create replacement tokens or copy demo business facts.
- Refresh token CSS through `npm run generate`; never hand-edit generated output.
  Apply fonts through the repository-approved loading mechanism, without adding
  the mockup's remote CSS `@import`. Preserve contrast, visible focus, keyboard
  controls and responsive single-column collapse.
- Prefer semantic roles and labels. Add `data-testid` only when a stable semantic
  selector is unavailable.
- UI changes require desktop and mobile evidence and accessibility checks.

## Checks

```bash
npm run lint:web
npm run build:web
npm run test:e2e
```

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
