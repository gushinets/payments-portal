# ANY-526 — Establish Locale Runtime, Routing & Navigation Foundation

## Plan Overview

| Field | Value |
| --- | --- |
| Parent | `ANY-525 — 4B. Establish Portal Internationalization (EFIGS + RU + PT)` |
| Ticket | `ANY-526 — 4B.1 Establish Locale Runtime, Routing & Navigation Foundation` |
| Baseline | Final `ANY-408` baseline; at plan validation time represented by PR #120 head |
| Overall status | `todo` |
| Execution order | Sequential only: Step 1 → manual verification → commit → Step 2 → manual verification → commit → Step 3 → manual verification → commit → Step 4 |
| Steps / commits | 4 |
| Successor | `4B.2 — Localize Existing Portal UI & Client-Facing Application Copy` |

## How to Use This File

1. Start from the final merged `ANY-408` baseline. If `ANY-408` is not merged yet, use its reviewed PR head rather than the older default-branch structure.
2. Execute exactly one step at a time.
3. After each step:
   - review the diff;
   - run only the listed manual verification commands;
   - fix any discovered issue before continuing;
   - create the proposed commit manually.
4. The execution model must not repeat broad repository/architecture research. The research and architecture decisions are captured in this plan.
5. If a directly referenced file/symbol moved after the previous step, inspect only the replacement location needed to apply the same decision.
6. If repository reality materially contradicts a locked contract below, stop and report the contradiction instead of silently redesigning the solution.

## Fresh-chat Codex execution model

Each implementation step is intended to run in a **new Codex chat**. Minimize context reconstruction on every step:

- give the new chat only the current step's **AI prompt**; the complete plan remains the human reference and does not need to be re-read by the execution model;
- treat the current step prompt and already-implemented branch state as authoritative execution context;
- assume all previous steps were manually verified and committed before the next chat starts;
- do **not** reopen/research Linear tickets, parent/successor tickets, ADRs, PR discussions, git history or external framework documentation unless the current step explicitly reports a material contradiction that cannot be resolved from the named files;
- do **not** revalidate locked architecture decisions or redesign the decomposition;
- inspect only the named files/areas for the current step plus the minimum replacement location when a named file moved;
- use narrow repository searches only to enumerate direct consumers of a known symbol/path; do not use broad exploratory searches;
- package-manager commands required solely to add a declared dependency and update the lockfile are allowed; automated verification/generation commands remain user-owned unless a step explicitly says otherwise;
- after implementation, report changed files, unresolved contradictions if any, and the exact user-run verification commands; do not spend tokens restating the full plan.

This is deliberate: the plan carries the research/architecture context so each fresh chat can spend its budget on implementation rather than rediscovery.

---

# Validated Current Baseline

The `ANY-408` baseline establishes the post-reset structure that `ANY-526` must extend.

Relevant current facts:

- web uses Next.js `16.3.1` and React `19.2.8`;
- `next-intl` is not currently installed;
- `apps/web/src/app/page.tsx` redirects `/` directly to `/ru`;
- `apps/web/src/app/layout.tsx` owns `<html>`, `<body>`, `SiteShell`, RU-only metadata and `lang="ru"`;
- ordinary Portal routes live under `apps/web/src/app/ru/*`;
- shared UI/features still contain normal application links with literal `/ru/...`;
- legal paths are generated and authoritative through `apps/web/src/generated/legal-manifest.json`;
- generated legal URLs include canonical RU paths such as `/ru/privacy`, `/ru/offer`, `/ru/cookies`;
- password-reset confirmation reads `token` from `window.location.hash`, stores it only in a client ref, then removes the fragment with `history.replaceState`;
- auth/session state is stored independently of locale;
- repository generation/drift checking is owned by `scripts/repo.py` and exposed by `npm run generate` / `npm run generate:check`;
- full UI translation, frontend error localization and complete message catalogs belong to 4B.2;
- backend locale propagation, password-reset URL/email localization and `Accept-Language` API handling belong to 4B.3.

No database migration or business/API persistence change is required by `ANY-526`.

---

# Locked Architecture Decisions

## Canonical locale contract

One checked-in machine-readable source is the authority for supported locales.

Public `routeLocale` values are exactly:

```text
en
fr
it
de
es
ru
pt
```

The contract must expose:

```text
routeLocale
languageTag
intlLocale
displayName
default
```

Canonical values:

| routeLocale | languageTag | intlLocale | displayName | default |
| --- | --- | --- | --- | --- |
| `en` | `en` | `en` | `English` | no |
| `fr` | `fr` | `fr` | `Français` | no |
| `it` | `it` | `it` | `Italiano` | no |
| `de` | `de` | `de` | `Deutsch` | no |
| `es` | `es` | `es` | `Español` | no |
| `ru` | `ru` | `ru` | `Русский` | yes |
| `pt` | `pt-BR` | `pt-BR` | `Português` | no |

`ru` is the routing/negotiation fallback only. It must not become the normal missing-message fallback policy for later complete catalogs.

Generated TypeScript and Python artifacts must come from this same source. No second handwritten locale list is allowed.

## next-intl runtime

Use `next-intl` with the current Next.js App Router.

Use its normal routing/request/navigation primitives rather than implementing a custom i18n framework.

Routing configuration must use:

- the generated public `routeLocale` set;
- default locale `ru`;
- always-prefixed locale URLs;
- `localeDetection: false` because `/` is the only negotiation entrypoint;
- `localeCookie: false` so `next-intl` never persists locale in `NEXT_LOCALE` or another locale cookie;
- `alternateLinks: false` because this application owns canonical/alternate metadata explicitly and legal documents are intentionally available only in RU.

Do not introduce legacy middleware-era architecture when the current Next.js 16 routing/proxy model provides the required boundary.

### Locale identity vs formatting locale

The three locale identifiers have distinct roles and must not be collapsed:

- `routeLocale` is the public URL identity and the locale identity used by `next-intl` routing/message selection (`pt` stays `pt` in the route and routing configuration);
- `languageTag` owns document-language semantics such as `<html lang>`, so `/pt/*` uses `lang="pt-BR"`;
- `intlLocale` owns exact Intl/ICU formatting semantics, so Portuguese formatting resolves through `pt-BR`.

`next-intl` routing must therefore use the seven public `routeLocale` values directly. Do not introduce a hidden `/pt` -> internal `pt-BR` rewrite or custom locale-prefix scheme in 4B.1; the proxy is intentionally root-only. When formatting requires an exact locale, resolve it through the generated `routeLocale -> intlLocale` mapping instead of assuming that the route string is the formatting locale.

## Public routing model

Ordinary application routes are always prefixed:

```text
/en/...
/fr/...
/it/...
/de/...
/es/...
/ru/...
/pt/...
```

Application pathnames are stable across locales. Do not localize slugs.

Only `/` negotiates locale from `Accept-Language`.

Required examples:

```text
de-AT -> /de
pt-BR -> /pt
supported language not present -> /ru
missing usable language -> /ru
```

Explicit locale-prefixed URLs are authoritative and must not be re-negotiated.

The following must not gain implicit fallback:

```text
/products
/account
/reset-password
/privacy
...
```

Unsupported locale prefixes produce normal not-found behavior.

## Root-layout structure

A global `app/layout.tsx` above `[locale]` cannot correctly derive the locale segment for `<html lang>`.

Therefore the route move must intentionally establish the localized root layout at:

```text
app/[locale]/layout.tsx
```

and that layout owns:

- `<html lang=...>`;
- `<body>`;
- `SiteShell`;
- locale-scoped request/message context;
- locale-aware metadata structure.

The root `/` entrypoint remains separate and minimal. After removing the global `app/layout.tsx`, define it explicitly as a second minimal root-layout tree:

```text
app/(entry)/layout.tsx
app/(entry)/page.tsx
app/[locale]/layout.tsx
app/[locale]/...
```

`app/(entry)/layout.tsx` exists only so `/` has a valid root layout and defensive fallback page. It must not contain `SiteShell` or become a second application routing architecture.

The expected request path is:

```text
/ -> proxy negotiation -> /<supported-locale>
```

The fallback root page may redirect to `/ru` only as a defensive render fallback when proxy negotiation was not applied; it must not replace negotiation logic.

## Metadata public origin

Canonical and alternate metadata URLs must be based on one explicit public Portal origin. Reuse the existing server-side `APP_PUBLIC_BASE_URL` contract rather than inventing a client-visible origin variable.

Step 2 must make `APP_PUBLIC_BASE_URL` available to the web build/runtime path that produces metadata (including the current web Docker build/production compose wiring where required), normalize it once, and use it as Next.js `metadataBase` or an equivalent single metadata-origin helper. Relative canonical/alternate URLs must never rely on an implicit host.

Because localized pages are statically generated where possible, the production web build must receive this value at build time. Do not expose it as `NEXT_PUBLIC_*` unless client code genuinely needs it; 4B.1 metadata generation is server/build-side.

## Accept-Language negotiation

Use a standards-compliant language-priority parser plus best-fit matching.

Use the established small libraries for this purpose rather than handwritten parsing:

- `negotiator` for parsing/prioritizing `Accept-Language`;
- `@formatjs/intl-localematcher` for best-fit matching.

Add direct web dependencies on `negotiator` and `@formatjs/intl-localematcher` for this boundary. If TypeScript declarations for `negotiator` are required, add `@types/negotiator` as a web dev dependency. Do not research or substitute alternative negotiation libraries and do not import undocumented/private package internals.

The result must be normalized back to the canonical public `routeLocale`.

## Locale ownership

Locale is presentation state only.

It must not select or mutate:

- user identity;
- auth/session state;
- tenant;
- deployment region;
- billing contour;
- provider;
- currency;
- timezone;
- persisted business records.

Do not add:

- locale DB columns;
- i18n migrations;
- locale cookies;
- locale localStorage;
- locale profile fields.

## Legal routing boundary

The generated legal manifest remains authoritative.

Canonical RU legal paths such as:

```text
/ru/privacy
/ru/consent-personal-data
/ru/offer
/ru/cancellation
/ru/cookies
/ru/security
```

remain valid.

Fake variants such as:

```text
/en/privacy
/de/offer
/pt/cookies
```

must return normal not-found behavior.

Do not:

- translate canonical legal documents;
- change legal versions/hashes/source paths;
- synthesize localized legal URLs;
- emit fake legal `hreflang` alternatives;
- detach legal acceptance/evidence from the generated canonical RU source.

Canonical RU legal/acceptance fragments embedded inside non-RU application UI must carry `lang="ru"` at the authoritative fragment boundary.

This includes generated registration/legal acceptance text when it appears inside locale-aware auth UI, not only full legal-document pages.

## Password-reset boundary

For the entire:

```text
/[locale]/reset-password
```

route, locale switching is unavailable.

The reset token contract remains:

```text
URL fragment
    -> client-only read
    -> tokenRef/client memory
    -> fragment removed from browser history
```

The token must not move into:

- query parameters;
- pathname;
- cookies;
- server-visible route params;
- shared/global shell state.

The shell may determine switcher availability from the current route identity/pathname. It must not inspect or coordinate token state.

Locale-aware reset URL/email generation remains 4B.3.

## Translation boundary

4B.1 establishes runtime/routing/navigation only.

It may add only bounded copy needed for:

- locale switcher;
- routing shell;
- metadata scaffolding;
- RU-authority presentation around legal content.

Do not migrate the complete current RU UI to catalogs.

Complete UI translation, localized API/error presentation and catalog parity belong to 4B.2.

---

# Step 1 — Establish the canonical locale contract and next-intl routing primitives

**Status:** `todo`

**Goal**  
Create the single locale authority, derive web/API locale artifacts through the existing generator, install `next-intl`, and establish reusable routing/navigation primitives. The request/plugin runtime is intentionally wired in Step 2 together with the actual `[locale]` tree.

**Scope / affected code**

Primary areas:

- new machine-readable locale contract, preferably `config/locales.json`;
- `scripts/repo.py`;
- `apps/web/package.json`;
- repository lockfile;
- new `apps/web/src/generated/locales.ts`;
- new `apps/api/app/generated/locales.py`;
- generated package exports if the existing generated packages require them;
- new `apps/web/src/i18n/routing.ts`;
- new `apps/web/src/i18n/navigation.ts`;
- no broad message-catalog work; only the smallest mechanically uniform 4B.1 message placeholder/files if the installed next-intl request API requires messages in Step 2.

Do not move `app/ru/*` yet.

**Implementation decisions**

1. Add `next-intl` to the web workspace on major version 4 and update the lockfile through the repository package manager. Do not research alternative i18n libraries, upgrade unrelated dependencies or hand-edit the lockfile.

2. Add one checked-in machine-readable locale source with exactly the canonical table defined above.

3. Extend `scripts/repo.py` and the existing `generate` / `generate:check` workflow.

4. Generate:

```text
apps/web/src/generated/locales.ts
apps/api/app/generated/locales.py
```

5. Generated TypeScript must provide:

- the supported route-locale tuple/list;
- `RouteLocale` finite type;
- default route locale;
- route-locale guard;
- `routeLocale -> languageTag`;
- `routeLocale -> intlLocale`;
- `routeLocale -> displayName`.

6. Generated Python must expose equivalent finite values/mappings for later API Presentation validation. Do not wire locale into API business behavior in this ticket.

7. Add the `next-intl` dependency now, but defer the Next.js plugin/request configuration to Step 2 when the `[locale]` root segment exists. Do not introduce a temporary default-locale request shim.

8. `src/i18n/routing.ts` must define the normal locale-routing contract from generated data with:

   - the seven public `routeLocale` values;
   - default locale `ru`;
   - always-prefixed routing;
   - `localeDetection: false`;
   - `localeCookie: false`;
   - `alternateLinks: false` so metadata remains application-owned.

9. `src/i18n/navigation.ts` must export the standard next-intl locale-aware navigation primitives application code will consume later.

10. Keep `routeLocale` as the next-intl routing/message identity. Use the generated `intlLocale` mapping whenever exact Intl/ICU formatting semantics are needed; in particular `pt -> pt-BR`.

11. Do not create `src/i18n/request.ts` or wire the next-intl plugin yet. The stable `next/root-params` configuration belongs to Step 2 together with the actual `[locale]` route tree, avoiding a temporary invalid root-param dependency.

12. Do not add broad UI translations.

**Invariants**

- exactly seven public route locales;
- `pt` remains the URL/next-intl route identity while `languageTag` and `intlLocale` resolve to `pt-BR`;
- `ru` is the only default;
- no locale cookie is written;
- web/API vocabulary is generated from one source;
- no business/API/persistence semantics change;
- legal manifest remains untouched;
- route behavior is not changed yet.

**Out of scope**

- moving routes;
- root negotiation;
- locale switcher;
- normal-link migration;
- full translations;
- backend `Accept-Language`;
- reset email localization;
- DB changes.

**AI prompt**

```text
Implement only Step 1 of ANY-526: establish the canonical locale contract and minimal next-intl routing/navigation primitives.

Fresh-chat rule: treat this prompt as the authoritative execution context. Do not read Linear tickets, ADRs, PR discussions, git history, other plan steps or external framework docs. Do not revalidate the architecture. Inspect only the files named below and the smallest existing generator/package pattern needed to implement them.

Read first / expected inputs:
- scripts/repo.py (only the existing generation/write-or-check pattern);
- apps/web/package.json and the repository lockfile;
- the existing generated web/API package layout only where needed to match conventions.

Baseline:
- work from the final ANY-408 structure;
- web uses Next.js 16.3.1 / React 19.2.8;
- next-intl is not installed;
- scripts/repo.py owns `generate` / `generate:check`;
- legal generated artifacts are already authoritative and must remain unchanged.

Implement:

1. Add one checked-in machine-readable locale contract, preferably `config/locales.json`.

It must define exactly:

en, fr, it, de, es, ru, pt

with these canonical values:

en -> languageTag=en, intlLocale=en, displayName=English
fr -> languageTag=fr, intlLocale=fr, displayName=Français
it -> languageTag=it, intlLocale=it, displayName=Italiano
de -> languageTag=de, intlLocale=de, displayName=Deutsch
es -> languageTag=es, intlLocale=es, displayName=Español
ru -> languageTag=ru, intlLocale=ru, displayName=Русский, default=true
pt -> languageTag=pt-BR, intlLocale=pt-BR, displayName=Português

No other locale is default.

2. Extend the existing scripts/repo.py generator rather than introducing a second generation system.

Generate:
- apps/web/src/generated/locales.ts
- apps/api/app/generated/locales.py

The TypeScript artifact must expose:
- finite supported route locales;
- RouteLocale type;
- default route locale;
- safe route-locale guard;
- languageTag / intlLocale / displayName mappings.

The Python artifact must expose equivalent generated finite locale validation/mapping data for later API Presentation use.

Both artifacts must participate in the existing generate/generate:check drift workflow.

3. Add `next-intl` on major version 4 to the web workspace and update the lockfile using the repository's npm workspace install mechanism. Do not research other i18n packages, upgrade unrelated dependencies or hand-edit the lockfile. The dependency-install command needed for this lockfile update is allowed; it is not a verification command. Do not wire the Next.js plugin/request module yet; Step 2 does that together with the `[locale]` root segment so there is no temporary root-param shim.

Use public supported next-intl APIs only.

4. Add:
- apps/web/src/i18n/routing.ts
- apps/web/src/i18n/navigation.ts

Build all locale configuration from the generated TypeScript artifact. Do not maintain another handwritten locale list.

Routing configuration must use:
- the generated routeLocale list directly as next-intl locales;
- always-present locale prefix;
- stable non-localized application pathnames;
- default locale ru;
- localeDetection=false because `/` negotiation is owned separately by Step 2;
- localeCookie=false so no NEXT_LOCALE or equivalent locale cookie is created;
- alternateLinks=false because canonical/hreflang metadata is application-owned.

Do not use a custom next-intl prefix that rewrites public `/pt` to an internal `/pt-BR` route. Keep routeLocale=pt as the route/message identity and use the generated intlLocale=pt-BR mapping for exact Intl/ICU formatting semantics.

Do not create apps/web/src/i18n/request.ts in this step. Step 2 will add it with stable `next/root-params` once `[locale]` actually exists.

5. Do not design or migrate the Portal message catalog in this step. If the installed next-intl API will require message objects once Step 2 wires request runtime, add only the smallest mechanically uniform per-route-locale 4B.1 placeholder structure needed for that API. Do not spend time deciding translation architecture and do not add ordinary Portal translations.

Do not extract or translate the complete existing Portal UI. That belongs to 4B.2. Do not create an all-locales normal client bundle.

Do not:
- move app/ru routes;
- implement Accept-Language negotiation;
- add locale persistence;
- change User/session/auth behavior;
- add DB migrations;
- modify legal documents/manifests;
- implement backend locale handling;
- redesign architecture;
- perform unrelated refactoring;
- work on future steps.

Do not run tests, linters, formatters, generators, builds, type checkers or other automated verification commands.
Do not stage files.
Do not create commits.

Do not hand-edit generated locale artifacts. Update only the canonical locale source and scripts/repo.py generator logic. I will run `npm run generate` manually so the checked-in generated outputs are produced by the repository generator, then verify their diff and drift status.

After implementation:
- report changed files;
- summarize the canonical locale contract/runtime modules;
- report the exact verification commands I should run manually.

If current code materially contradicts a required assumption, stop and describe the contradiction instead of inventing a different solution.
```

**Manual verification**

```bash
npm run generate
git diff -- apps/web/src/generated/locales.ts apps/api/app/generated/locales.py
npm run generate:check
npm run typecheck:web
npm run test:boundaries:web
```

**Expected completion**

One canonical locale source generates consistent TypeScript/Python contracts, next-intl is installed, and reusable routing/navigation primitives compile without changing public routing or introducing a premature root-param request runtime.

**Proposed commit**

```text
feat(i18n): establish canonical locale contract
```

---

# Step 2 — Establish the locale route tree, localized root layout and root-only negotiation

**Status:** `todo`

**Goal**  
Replace the static RU application route tree with a single finite `[locale]` route tree, make locale available at the root document-layout boundary, and make `/` the only deterministic `Accept-Language` negotiation entrypoint.

**Scope / affected code**

Primary areas:

- current `apps/web/src/app/layout.tsx`;
- current `apps/web/src/app/page.tsx`;
- current `apps/web/src/app/ru/**`;
- new `apps/web/src/app/[locale]/layout.tsx`;
- new `apps/web/src/app/[locale]/**`;
- required minimal `apps/web/src/app/(entry)/layout.tsx` and `apps/web/src/app/(entry)/page.tsx`;
- new `apps/web/src/proxy.ts`;
- new `apps/web/src/i18n/request.ts`;
- `apps/web/src/i18n/routing.ts` / `navigation.ts`;
- `apps/web/next.config.mjs` for next-intl plugin wiring;
- current web Dockerfile / production compose / env wiring needed to provide `APP_PUBLIC_BASE_URL` to the web metadata build/runtime;
- `apps/web/package.json` / lockfile if negotiation parser/matcher dependencies are needed;
- legal-route rendering boundary needed to keep generated documents RU-only during the route move;
- new focused `apps/web/e2e/locale-routing.spec.ts` plus directly relevant routing/metadata tests.

**Implementation decisions**

1. Remove the global root-layout architecture that hardcodes RU above the locale segment.

2. Make `app/[locale]/layout.tsx` the root layout for the normal Portal route tree.

   It owns:

   - `<html lang={canonical languageTag}>`;
   - `<body>`;
   - `SiteShell`;
   - current-locale next-intl server provider/context as required;
   - locale-aware metadata structure.

3. Create the separate minimal root-entry tree unconditionally after removing the global root layout:

```text
app/(entry)/layout.tsx
app/(entry)/page.tsx
```

It exists only to give `/` a valid root layout and defensive fallback page. It must not duplicate `SiteShell` or the localized application shell.

4. Move current `app/ru/*` routes under one `app/[locale]/*` tree.

5. Validate locale against the generated finite contract. Unsupported values call `notFound()` rather than becoming `ru`.

6. Configure the supported next-intl plugin in `apps/web/next.config.mjs` and add `src/i18n/request.ts` using the stable Next.js 16.3 `next/root-params` API. Validate `[locale]` against the generated route-locale set, call `notFound()` for invalid values, and load only the current locale's bounded 4B.1 messages. Do not use legacy `requestLocale`/`setRequestLocale`.

7. Use `generateStaticParams` for the seven generated route locales so otherwise-static pages remain static/server-rendered where current behavior allows.

8. Keep `routeLocale` as the `[locale]`/next-intl route identity and resolve `languageTag` / `intlLocale` separately from the generated mapping (`/pt` remains `pt`, while document/formatting semantics use `pt-BR`).

9. Add root-only `proxy.ts`.

   Its matcher/logic must affect `/` only.

10. Parse `Accept-Language` with a standards-compliant parser and best-fit matcher.

   Prefer:

   - `negotiator`;
   - `@formatjs/intl-localematcher`.

   Add them as direct web dependencies when they are not already direct dependencies. If TypeScript requires it, add `@types/negotiator` as a dev dependency. Do not research substitute libraries.

11. Match against the generated canonical `languageTag` values, then map the matched language tag back to the public `routeLocale`. This keeps `/pt` public while matching Portuguese with `pt-BR` semantics.

12. Required routing behavior:

```text
/ + de-AT -> /de
/ + pt-BR -> /pt
/ + unsupported languages only -> /ru
/ + no usable language -> /ru
/de -> remains /de
/pt/products -> remains /pt/products
/products -> no implicit redirect
/unknown/products -> normal not-found
```

13. Root page fallback may redirect to `/ru` only as a defensive fallback when it renders without proxy negotiation. It must not parse headers itself or create a second negotiation implementation.

14. Establish locale-aware metadata structure for ordinary routes:

- reuse the existing server-side `APP_PUBLIC_BASE_URL` as the canonical public Portal origin;
- wire it into the web production build/runtime path required for statically generated metadata;
- define `metadataBase` or one equivalent normalized metadata-origin helper;
- emit canonical URL for the current locale route;
- emit alternate-language URLs for equivalent ordinary localized routes;
- use canonical language values from the generated contract.

Do not rely on an implicit request host for canonical/hreflang generation. Do not fully translate metadata copy yet; 4B.2 owns complete localized metadata content.

15. Enforce the legal routing exception in the same commit as the route move. For every generated legal slug, only `locale == ru` may render canonical legal content; every non-RU variant must call `notFound()`. Legal metadata must expose the generated RU canonical URL only and must not emit locale alternates/hreflang. This cannot be deferred to Step 3 because the dynamic route tree would otherwise temporarily create fake legal routes.

16. Add focused routing coverage, including a dedicated locale-routing E2E test for root negotiation/prefixed-route behavior, unsupported/non-prefixed routes, document language, metadata origin/canonical behavior, RU-only legal routing and absence of a locale cookie.

**Invariants**

- one route tree, not seven copies;
- one localized application root layout;
- `/` is the only negotiation boundary;
- explicit locale URLs win;
- unsupported locale does not fall back;
- arbitrary unprefixed app routes do not acquire locale;
- `pt` remains the public route locale while rendering `lang="pt-BR"`;
- non-RU legal variants never become temporarily renderable;
- canonical/alternate metadata is based on explicit `APP_PUBLIC_BASE_URL`;
- no locale cookie is written;
- static/server rendering is preserved where possible;
- no auth/business/persistence semantics change.

**Out of scope**

- broad normal-link migration;
- locale switcher;
- full UI localization;
- backend locale propagation;
- legal translation;
- reset email locale handling;
- DB work.

**AI prompt**

```text
Implement only Step 2 of ANY-526: establish the dynamic locale route tree, localized root document layout and root-only Accept-Language negotiation.

Fresh-chat rule: Step 1 is already manually verified and committed. Treat this prompt plus the current branch as authoritative. Do not read Linear tickets, ADRs, PR discussions, git history, other plan steps or external framework docs, and do not revalidate the architecture.

Read first / expected inputs only:
- config/locales.json;
- apps/web/src/generated/locales.ts;
- apps/web/src/i18n/routing.ts and apps/web/src/i18n/navigation.ts;
- apps/web/src/app/layout.tsx, apps/web/src/app/page.tsx and apps/web/src/app/ru/**;
- apps/web/next.config.mjs;
- the web Dockerfile, docker-compose.prod.yml, .env.example and .env.production.example only for APP_PUBLIC_BASE_URL wiring;
- generated legal manifest plus the current legal page/rendering boundary;
- directly relevant existing route/legal tests.

Do not inspect backend business/domain code. Use the Step 1 generated locale contract and i18n modules as authoritative inputs.

1. Replace the current global RU root-layout structure.

The current app/layout.tsx sits above the locale route and therefore cannot be the long-term owner of locale-derived `<html lang>`.

Make `app/[locale]/layout.tsx` the root layout for normal Portal routes. It must own:
- html/body;
- canonical `<html lang>` from the generated languageTag mapping;
- SiteShell;
- the current-locale next-intl server/provider boundary required by the installed supported APIs;
- locale-aware metadata structure.

Create a separate minimal root-entry tree for `/` after removing the global app/layout.tsx:
- app/(entry)/layout.tsx
- app/(entry)/page.tsx

This is required so `/` retains a valid root layout. It must not contain SiteShell or create a second application routing architecture.

2. Move the current app/ru route structure into one dynamic app/[locale] route tree.

Do not create seven physical copies.

Keep stable application pathnames under the prefix.

Validate locale against the generated canonical contract. Unsupported locale values must produce ordinary not-found behavior, never silent RU fallback.

Configure the supported next-intl plugin in apps/web/next.config.mjs and add apps/web/src/i18n/request.ts now that `[locale]` exists. Use the stable Next.js 16.3 `next/root-params` API, validate against generated routeLocale values, call notFound() for invalid values and load only the current locale's bounded 4B.1 messages. Do not use legacy setRequestLocale/requestLocale architecture.

Use generateStaticParams for the seven route locales so otherwise-static pages remain static/server-rendered where possible.

Keep the `[locale]` and next-intl routing/message identity as the public routeLocale. Resolve document language and exact Intl formatting through the generated languageTag/intlLocale mappings.

Required document language examples:
- /en/* -> lang=en
- /de/* -> lang=de
- /pt/* -> lang=pt-BR

3. Implement `/` as the only Accept-Language negotiation entrypoint using Next.js 16 proxy.ts.

The proxy matcher/logic must be root-only. It must not broadly rewrite non-prefixed application paths.

Use a standards-compliant language-priority parser plus best-fit locale matcher.

Use exactly these public packages:
- `negotiator`;
- `@formatjs/intl-localematcher`.

Add them as direct web dependencies if they are not already direct dependencies, and add `@types/negotiator` as a dev dependency if TypeScript declarations are required. The package-install command needed only to update these dependencies/lockfile is allowed. Do not research substitute libraries and do not import package-private internals.

Use the generated languageTag values as the best-fit matcher candidates, then normalize the matched languageTag back to the canonical public routeLocale. Do not match Portuguese by treating public routeLocale `pt` as the formatting contract; `pt-BR` is the canonical language/Intl candidate and maps back to public `/pt`.

Required behavior:
- de-AT -> /de
- pt-BR -> /pt
- other Portuguese regional variants that best-fit Portuguese -> /pt
- no supported match -> /ru
- missing/empty usable preference -> /ru
- explicit /en, /de, /pt/... routes are never re-negotiated
- /products, /account, /privacy and other arbitrary non-prefixed paths do not receive locale fallback

The root page may contain only a defensive `/ru` fallback redirect if it is rendered without proxy negotiation. Do not duplicate Accept-Language parsing in the page.

4. Establish reusable locale-aware metadata for ordinary localized pages.

Reuse the existing server-side APP_PUBLIC_BASE_URL as the canonical public Portal origin. Wire it into the web production build/runtime path needed by metadata generation, including the current Docker/compose wiring where necessary. Define metadataBase or one equivalent normalized origin helper so canonical and alternate URLs are absolute and deterministic.

For ordinary localized routes provide:
- canonical current-locale URL;
- equivalent alternate-language routes for supported locales;
- language values from the canonical contract.

Do not perform complete metadata-copy translation; that belongs to 4B.2.

5. Enforce the generated legal routing exception now, in the same step as the dynamic route move.

For every generated legal slug:
- only locale=ru renders the canonical document;
- all non-RU locale variants return ordinary not-found;
- metadata exposes only the generated RU canonical URL;
- no fake locale alternates/hreflang are emitted;
- generated URL/version/hash/source/evidence semantics remain unchanged.

Do not translate legal documents. Step 3 will only add navigation/switcher suppression and `lang=ru` presentation markers around this already-enforced route boundary.

6. Add/update focused tests, including apps/web/e2e/locale-routing.spec.ts, for:
- seven locale roots;
- unsupported locale not-found;
- representative root negotiation;
- non-prefixed-path behavior;
- explicit locale authority;
- pt -> html lang=pt-BR;
- no NEXT_LOCALE/equivalent locale cookie;
- metadataBase/canonical behavior from APP_PUBLIC_BASE_URL;
- canonical RU legal routes and non-RU legal 404;
- no fake legal alternates;
- representative static/server rendering expectations.

Do not implement the locale switcher yet.
Do not perform full UI translation.
Do not change backend/API behavior.
Do not change auth/session persistence.
Do not change password-reset token handling.
Do not redesign architecture.
Do not perform unrelated refactoring.
Do not work on future steps.

Do not run tests, linters, formatters, generators, builds, type checkers or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report changed/moved files;
- summarize route/layout/negotiation behavior;
- report exact verification commands I should run manually.

If current code materially contradicts a required assumption, stop and describe the contradiction instead of inventing a new architecture.
```

**Manual verification**

```bash
npm run typecheck:web
npm run test:boundaries:web
npm --workspace @anytoolai/web run test:components
npm run build:web
npm run test:e2e -- apps/web/e2e/locale-routing.spec.ts
```

**Expected completion**

The normal Portal has one `[locale]` route tree with a true locale-aware root document layout; `/` alone negotiates language; direct locale URLs are authoritative; unsupported/non-prefixed routes do not silently fall back; legal documents remain RU-only throughout the route move; canonical metadata uses an explicit public origin.

**Proposed commit**

```text
feat(i18n): establish locale-prefixed routing
```

---

# Step 3 — Make navigation locale-aware and preserve legal/reset-token boundaries

**Status:** `todo`

**Goal**  
Migrate routing-owned navigation away from literal `/ru`, add the locale switcher, preserve the RU-only legal routing boundary already established in Step 2, and enforce reset-confirmation/switcher presentation rules without touching authentication state or legal evidence.

**Scope / affected code**

Primary current surfaces:

- `apps/web/src/shared/ui/SiteShell.tsx`;
- `apps/web/src/shared/ui/HeaderAccount.tsx`;
- `apps/web/src/shared/ui/Footer.tsx`;
- `apps/web/src/shared/ui/CookieBanner.tsx`;
- `apps/web/src/shared/ui/AuthForm.tsx`;
- `apps/web/src/features/account/AccountClient.tsx`;
- `apps/web/src/features/checkout/CheckoutClient.tsx`;
- `apps/web/src/features/password-reset/PasswordResetConfirmClient.tsx`;
- `apps/web/src/features/password-reset/PasswordResetRequestClient.tsx`;
- `apps/web/src/features/payment-result/PaymentResultClient.tsx`;
- current route pages with ordinary application links;
- `apps/web/src/features/legal/legal.ts`;
- `apps/web/src/features/legal/LegalPageView.tsx`;
- `apps/web/src/generated/registration-acceptance.ts` consumers;
- generated legal-manifest consumers;
- new locale-switcher component;
- focused component/E2E coverage.

**Implementation decisions**

1. Use the next-intl navigation primitives from Step 1 for ordinary application links/navigation.

2. Remove routing-owned hardcoded `/ru` from normal destinations such as:

- home;
- products;
- account;
- auth checkout;
- forgot password;
- post-reset login navigation;
- other current non-legal application links.

3. Do not rewrite canonical legal links through locale-aware navigation. Legal links continue to use generated manifest `urlPath`.

4. Add one accessible locale switcher in the shared shell.

5. The switcher:

- offers exactly seven canonical route locales;
- displays canonical `displayName`;
- replaces only locale prefix;
- preserves stable pathname;
- preserves query parameters;
- does not persist locale outside the URL;
- does not change session/auth state.

6. Route-based switch suppression:

- hide/disable it for `/<locale>/reset-password`;
- hide/disable it for canonical legal-document pages.

The switcher may use current pathname/search params to determine route policy. Do not create global token state.

7. Preserve `PasswordResetConfirmClient` fragment handling exactly in security semantics.

8. Preserve the RU-only legal route guard established in Step 2. Do not move, relax or duplicate it into a second routing mechanism. A shared predicate may be reused where Step 3 needs to identify legal pages for switcher policy.

9. For canonical legal pages:

- locale switching is unavailable;
- no fake alternate-language destination is exposed by navigation UI;
- Step 2's RU-only route/metadata guard remains intact;
- generated manifest URL remains canonical;
- document path/version/hash/evidence semantics remain untouched.

10. Mark canonical RU content with `lang="ru"` where it may appear within otherwise locale-aware UI.

   This applies to:

- full legal-document content;
- generated registration/legal acceptance text or equivalent authoritative RU fragments rendered by auth/registration UI.

Do not translate these authoritative fragments.

11. Minimal surrounding copy may use the bounded 4B.1 message namespace. Do not localize the full application.

12. Locale changes must not clear or rewrite auth/session localStorage.

**Invariants**

- no normal application navigation depends on literal `/ru`;
- legal manifest paths remain exact canonical RU links;
- non-RU legal variants 404;
- no fake legal alternates;
- reset-confirmation route has no switcher;
- token remains fragment/client-only;
- auth/session state survives locale navigation;
- locale is not persisted.

**Out of scope**

- complete UI translation;
- canonical legal translation;
- backend locale handling;
- localized reset email/link generation;
- DB changes;
- auth redesign;
- future billing/provider work.

**AI prompt**

```text
Implement only Step 3 of ANY-526: migrate application navigation to the locale-aware routing foundation and enforce the canonical legal/reset-password route restrictions.

Fresh-chat rule: Steps 1 and 2 are already manually verified and committed. Treat this prompt plus the current branch as authoritative. Do not read Linear tickets, ADRs, PR discussions, git history, other plan steps or external framework docs, and do not revalidate routing architecture.

Read first / primary targets:
- apps/web/src/i18n/navigation.ts and apps/web/src/generated/locales.ts;
- apps/web/src/shared/ui/SiteShell.tsx;
- apps/web/src/shared/ui/HeaderAccount.tsx;
- apps/web/src/shared/ui/Footer.tsx;
- apps/web/src/shared/ui/CookieBanner.tsx;
- apps/web/src/shared/ui/AuthForm.tsx;
- apps/web/src/features/account/AccountClient.tsx;
- apps/web/src/features/checkout/CheckoutClient.tsx;
- apps/web/src/features/password-reset/PasswordResetConfirmClient.tsx;
- apps/web/src/features/password-reset/PasswordResetRequestClient.tsx;
- apps/web/src/features/payment-result/PaymentResultClient.tsx;
- apps/web/src/features/legal/legal.ts and LegalPageView.tsx;
- generated legal-manifest and registration-acceptance consumers.

Use one narrow search for literal `/ru` under `apps/web/src` to enumerate remaining direct navigation consumers. Classify each hit as ordinary routing vs intentional generated/canonical legal usage; do not broaden that search into backend/docs/history.

1. Replace routing-owned hardcoded `/ru` ordinary application navigation with the locale-aware next-intl primitives from Step 1.

Update directly relevant shared UI/features/pages so normal links preserve the active locale instead of concatenating `/ru`.

Do not convert generated legal manifest URLs into current-locale URLs.

2. Add an accessible locale switcher to the shared Portal shell.

It must:
- expose exactly en/fr/it/de/es/ru/pt;
- use generated canonical displayName values;
- replace only the locale prefix;
- preserve the same stable pathname where that route is locale-switchable;
- preserve query parameters;
- not use locale cookies;
- not use locale localStorage;
- not persist locale on User/session data;
- not alter authentication/session state.

It may use current pathname/search params for route policy and destination construction. Do not introduce global token state.

3. Hide/disable locale switching for the entire:

`/[locale]/reset-password`

route.

Do not inspect whether a token is currently present.

Preserve the existing reset token contract:
- read only from window.location.hash;
- capture client-side;
- remove fragment using history.replaceState;
- never move token into query, pathname, server params, cookies or shared shell state.

4. Preserve the generated RU legal authority that Step 2 already enforces.

Generated legal paths remain canonical, including:
- /ru/privacy
- /ru/consent-personal-data
- /ru/offer
- /ru/cancellation
- /ru/cookies
- /ru/security

Do not reimplement the route guard. Confirm the existing Step 2 guard remains the single routing boundary, then add only Step 3 concerns:
- locale switching is unavailable on canonical legal pages;
- no fake alternate-language destination is exposed by the switcher/navigation UI;
- generated URL/version/hash/source/evidence semantics remain unchanged.

Reuse the existing small legal-route predicate if needed for route-policy detection. Do not create a new generic routing framework.

5. Preserve language semantics for authoritative RU content.

Mark canonical RU legal text with `lang="ru"` where appropriate.

Also inspect the current generated registration/legal acceptance text consumer. If canonical RU acceptance text is rendered inside a non-RU UI route, mark the authoritative fragment `lang="ru"` rather than translating it.

Do not translate authoritative legal/acceptance content.

6. Update focused tests for:
- active-locale ordinary navigation;
- pathname/query preservation when switching locale;
- exactly seven switcher destinations;
- auth/session-neutral locale navigation;
- no switcher on reset-password;
- canonical RU legal routes;
- non-RU legal 404;
- no fake legal alternates;
- RU language metadata on authoritative legal/acceptance content.

Do not perform complete UI localization.
Do not implement backend Accept-Language.
Do not localize reset emails/generated reset URLs.
Do not change auth/session storage.
Do not change database schema.
Do not redesign architecture.
Do not perform unrelated refactoring.
Do not work on future steps.

Do not run tests, linters, formatters, generators, builds, type checkers or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report changed files;
- summarize navigation/legal/reset-token invariants;
- report exact verification commands I should run manually.

If current code materially contradicts a required assumption, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

```bash
npm --workspace @anytoolai/web run test:components
npm run test:boundaries:web
npm run typecheck:web
npm run test:e2e -- apps/web/e2e/password-reset.spec.ts apps/web/e2e/public-routes.spec.ts
```

**Expected completion**

Ordinary navigation follows the active locale without literal `/ru`; switcher preserves logical destination/query; legal routes remain generated RU-only; reset-confirmation cannot lose its fragment token through locale switching.

**Proposed commit**

```text
feat(i18n): add locale-aware navigation
```

---

# Step 4 — Add durable routing guards, complete verification coverage and document the 4B.1 baseline

**Status:** `todo`

**Goal**  
Protect the completed 4B.1 architecture with bounded tests/static guards and update durable project guidance so 4B.2 can consume the result without reopening routing design.

**Scope / affected code**

Primary areas:

- `apps/web/tests/*.test.mjs`;
- `apps/web/tests/components/*` where focused;
- `apps/web/e2e/locale-routing.spec.ts`;
- `apps/web/e2e/public-routes.spec.ts`;
- `apps/web/e2e/password-reset.spec.ts`;
- existing auth/account E2E tests whose route expectations changed;
- existing web static/boundary guard tests;
- `docs/engineering/CODING_CONVENTIONS.md`;
- `ARCHITECTURE.md`;
- `apps/web/AGENTS.md` where routing guidance becomes stale;
- generation/drift documentation if directly required.

**Implementation decisions**

1. Use a lightweight seven-locale smoke/contract matrix, not seven copies of the deep behavioral suite.

2. Ensure durable coverage for:

- all seven supported public locales;
- unsupported locale not-found;
- root negotiation;
- regional matching;
- `pt-BR -> pt`;
- RU fallback;
- explicit locale URL authority;
- no implicit localization of arbitrary non-prefixed paths;
- representative static/server-rendering characteristics;
- `html lang`, including `pt-BR`;
- locale switch pathname/query preservation;
- canonical RU legal routes;
- rejected non-RU legal variants;
- absence of fake legal alternates;
- reset-confirmation without switcher;
- token remains fragment/client-only;
- locale-neutral auth/session behavior;
- locale generated-artifact drift;
- no locale cookie (`NEXT_LOCALE` or equivalent) is created;
- canonical/alternate metadata uses the explicit `APP_PUBLIC_BASE_URL` origin.

3. Add a bounded static guard against routing-owned literal `/ru`.

   Reject examples such as:

```text
href="/ru/products"
redirect("/ru/account")
hand-built `/ru/${...}` ordinary route navigation
```

   Allow intentional canonical legal values coming from generated legal artifacts/manifests.

   Do not globally ban `/ru`.

4. Do not add a "Russian UI literal" guard yet. That belongs to 4B.2 after UI copy has actually been localized.

5. Update durable docs with:

- one canonical machine-readable locale contract;
- generated TS/Python locale artifacts;
- exact supported locales;
- `routeLocale` as URL/next-intl routing identity and `languageTag`/`intlLocale` as document/formatting identities, including `pt -> pt-BR`;
- `[locale]` ordinary route architecture;
- localized root document layout;
- `/` as the only negotiation entry;
- explicit locale-prefixed URL authority;
- `localeDetection=false`, `localeCookie=false`, and application-owned alternate metadata;
- `APP_PUBLIC_BASE_URL` as the server/build-side metadata origin;
- normal-link use of locale-aware navigation helpers;
- no locale persistence;
- locale independence from region/provider/currency/timezone;
- RU-only generated legal routing;
- reset-confirmation switching restriction;
- 4B.2/4B.3 ownership boundaries.

6. Remove/update tests/docs that assert the obsolete hardcoded RU routing implementation while retaining their actual security/business assertions.

**Invariants**

- regression guards distinguish normal routing from intentional generated legal RU paths;
- deep tests are not multiplied by seven;
- 4B.2 copy-localization work is not pulled forward;
- 4B.3 backend propagation is not pulled forward;
- provider/billing behavior remains untouched.

**Out of scope**

- complete message-catalog parity;
- all-Russian-literal sweep;
- localized frontend API errors;
- backend locale propagation;
- password-reset email localization;
- provider/billing work.

**AI prompt**

```text
Implement only Step 4 of ANY-526: finish durable tests, guards and documentation for the established locale runtime/routing/navigation foundation.

Fresh-chat rule: Steps 1-3 are already manually verified and committed. Protect that implementation; do not redesign it. Treat this prompt plus the current branch as authoritative. Do not read Linear tickets, ADRs, PR discussions, git history, other plan steps or external framework docs.

Read first / expected inputs only:
- existing apps/web/tests/*.test.mjs and directly relevant component guards;
- apps/web/e2e/locale-routing.spec.ts;
- apps/web/e2e/public-routes.spec.ts;
- apps/web/e2e/password-reset.spec.ts;
- existing auth/account E2E files only when their route expectations are stale;
- docs/engineering/CODING_CONVENTIONS.md;
- ARCHITECTURE.md;
- apps/web/AGENTS.md.

First inventory coverage already added by Steps 2-3 and only fill missing durable gaps. Do not rewrite equivalent tests merely to match this prompt. Do not inspect application source broadly; open an exact implementation file only when a guard/test needs the current symbol/path.

1. Add/adjust the smallest durable verification coverage for the completed 4B.1 contract.

Cover:
- exactly en/fr/it/de/es/ru/pt;
- unsupported locale -> normal not-found;
- `/` Accept-Language negotiation;
- de-AT -> de;
- pt-BR -> pt;
- RU fallback when no supported language matches;
- explicit locale-prefixed URLs remain authoritative;
- `/products` and other ordinary non-prefixed app paths do not receive implicit localization;
- representative static/server-rendering characteristics;
- `<html lang>` mapping, especially `/pt/* -> pt-BR`;
- locale switching preserves pathname/query;
- generated canonical RU legal paths resolve;
- non-RU legal variants do not resolve;
- legal pages have no fake locale-switch/alternate destination;
- `/[locale]/reset-password` has no locale switcher;
- reset token remains fragment/client-only;
- auth/session storage remains valid across locale navigation;
- generated locale contract drift is detected by the existing generation workflow;
- no locale cookie is written;
- canonical/alternate metadata is anchored to APP_PUBLIC_BASE_URL.

Use deep behavior primarily in one representative locale plus a lightweight seven-locale smoke/contract matrix. Do not multiply the entire suite by seven. Reuse the Step 2/3 tests when they already prove an item; add only the missing assertion/guard instead of creating parallel coverage.

2. Add a bounded static/boundary guard against reintroducing routing-owned literal `/ru` ordinary application navigation.

The guard should catch direct normal app href/redirect/path construction using `/ru`, while allowing intentional generated/canonical legal manifest paths.

Do not globally reject the string `/ru`.

Do not add a broad Russian UI-literal guard in this ticket. Full UI localization belongs to 4B.2.

3. Update durable architecture/coding/web-agent guidance where it is now stale.

Document:
- the canonical machine-readable locale contract;
- generated web/API locale artifacts;
- exactly supported route locales and the distinct routeLocale/languageTag/intlLocale roles, including pt -> pt-BR;
- `[locale]` as the ordinary route tree;
- locale-derived root document lang;
- `/` as the only Accept-Language negotiation entry;
- explicit locale-prefixed URL authority;
- localeDetection=false and localeCookie=false;
- APP_PUBLIC_BASE_URL as the deterministic metadata origin;
- locale-aware navigation helper requirement;
- no locale cookie/localStorage/User persistence;
- locale != region/provider/currency/timezone;
- generated RU legal routes remain canonical and RU-only;
- reset-confirmation has no locale switching;
- complete UI localization belongs to 4B.2;
- backend communication locale propagation belongs to 4B.3.

Update/remove obsolete RU-only routing assertions instead of keeping conflicting guidance.

Do not modify application architecture beyond Steps 1-3.
Do not translate the complete UI.
Do not add backend locale propagation.
Do not change database schema.
Do not implement future billing/provider work.
Do not perform unrelated refactoring.
Do not work on future steps.

Do not run tests, linters, formatters, generators, builds, type checkers or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report changed files;
- summarize new regression tests/guards/docs;
- report exact verification commands I should run manually.

If current code materially contradicts a required assumption, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

Focused/final web checks:

```bash
npm run generate:check
npm --workspace @anytoolai/web run test:components
npm run test:boundaries:web
npm run lint:web
npm run typecheck:web
npm run build:web
npm run test:e2e
```

Repository-level final checks:

```bash
npm run docs:check
npm run architecture:check
npm run generate:check
npm run check:fast
```

**Expected completion**

The routing/runtime/navigation foundation is fully protected by focused tests, seven-locale contract smoke coverage, drift checks, static guards and durable documentation. 4B.2 can now localize current UI without changing the routing architecture.

**Proposed commit**

```text
test(i18n): protect locale routing foundation
```

---

# Final Validation

This plan closes the complete `ANY-526` scope:

```text
canonical locale source
        ↓
generated TS/Python locale contracts
        ↓
next-intl runtime
        ↓
localized [locale] root document layout
        ↓
one dynamic locale route tree
        ↓
root-only Accept-Language negotiation
        ↓
explicit APP_PUBLIC_BASE_URL metadata origin
        ↓
locale-aware ordinary metadata + RU-only legal routing guard
        ↓
locale-aware navigation + switcher
        ↓
RU-only generated legal authority
        ↓
reset-token-safe route restriction
        ↓
tests + guards + durable docs
```

It intentionally does not implement:

```text
complete seven-locale Portal UI translation      -> 4B.2
complete message catalog parity                  -> 4B.2
localized frontend API/error presentation        -> 4B.2
backend Accept-Language propagation              -> 4B.3
localized password-reset emails                  -> 4B.3
locale-aware reset-email URL generation          -> 4B.3
locale persistence                               -> explicitly not part of design
translated canonical RU legal documents          -> explicitly not part of 4B
LBX/provider runtime                              -> later ANY-504 stages
billing/catalog implementation                   -> later ANY-504 stages
```

## Plan Validation Result

The implementation sequence is intentionally four steps and is sized for fresh-chat Codex execution. No step is a token-wasting micro-step.

- Step 1 establishes locale authority, generated contracts and routing/navigation dependencies without changing routes.
- Step 2 performs the structural route/root-layout change, root negotiation, metadata-origin wiring and RU-only legal route guard as one coherent routing change so no intermediate commit exposes fake legal routes.
- Step 3 migrates navigation and applies switcher/language-marking restrictions on top of the already-safe locale tree without creating a second legal routing mechanism.
- Step 4 hardens the resulting architecture without mixing new runtime behavior into the earlier changes.

No execution step requires a new product/business/architecture decision.

The important hidden decisions have been resolved in the plan:

1. `<html lang>` is owned by a root layout below `[locale]`, while `/` has its own minimal `(entry)` root layout.
2. `/` negotiation is isolated in root-only `proxy.ts`.
3. `Accept-Language` parsing/matching is standards-based rather than handwritten.
4. `routeLocale` is the public/next-intl routing identity; `languageTag` and `intlLocale` carry document/formatting semantics, including `pt -> pt-BR`.
5. next-intl locale persistence is explicitly disabled with `localeCookie=false`; URL is the only locale persistence mechanism.
6. canonical/alternate metadata uses explicit server/build-side `APP_PUBLIC_BASE_URL`, never an implicit host.
7. RU-only legal routing is enforced in Step 2 together with the dynamic route move so fake non-RU legal routes never exist between commits.
8. ordinary locale navigation and generated RU legal URLs intentionally use different routing rules.
9. reset-password switch suppression is route-based and never depends on token state.
10. canonical RU acceptance fragments embedded in non-RU UI are explicitly language-marked, not translated.
11. generated artifacts are produced only by `npm run generate`; execution agents do not hand-edit them.
12. full UI localization and backend communication localization remain with 4B.2/4B.3.

The plan is implementation-ready for `ANY-526`.
