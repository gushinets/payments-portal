# Web Agent Guide

Read the root `AGENTS.md`, [the `ru` journey](../../docs/product/ru-mvp.md),
[contours](../../docs/architecture/contours.md),
[design](../../docs/DESIGN.md), and the
[web section of coding conventions](../../docs/engineering/CODING_CONVENTIONS.md#web--typescript)
before frontend work.

## Conventions

- Treat `response.json()`, `JSON.parse`, storage, and query params as
  `unknown`. `as T` is not validation; production-source lint rejects direct
  assertions on `response.json()` and `JSON.parse(...)` results.
- HTTP helpers take a decoder or return `unknown`; a generic `T` without a
  decoder is forbidden. A decoder must fail on mismatch and have a test that
  rejects an invalid value.
- Keep API types in `shared/api` or the feature API module; do not copy
  response types in components.
- Inspect errors with `ApiError.status` and `detail.code`, never
  `message.includes(...)`.

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
  confirmation. Complete copy localization is 4B.2; backend locale propagation
  is 4B.3.

## Boundaries

- App routes compose feature entrypoints.
- Feature modules own product behavior.
- Shared modules own reusable API contracts, configuration, and UI primitives.
- Features must not deep-import another feature's internals.

## UI rules

- Preserve the current contour's customer-facing copy. The implemented `ru`
  contour still uses Russian copy across every route locale until 4B.2.
- Use Bundle 3 tokens and glass/bento patterns; do not invent replacement tokens.
- Prefer semantic roles and labels. Add `data-testid` only when a stable semantic
  selector is unavailable.
- UI changes require desktop and mobile evidence and accessibility checks.

## Checks

```bash
npm run lint:web
npm run build:web
npm run test:e2e
```
