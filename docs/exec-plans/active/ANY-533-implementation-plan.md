# ANY-533 — Locale-Aware User Communications & Multi-Locale Hardening

## Plan Overview

| Field | Value |
| --- | --- |
| Parent feature | `ANY-525 — 4B. Establish Portal Internationalization (EFIGS + RU + PT)` |
| Ticket | `ANY-533 — 4B.3 Locale-Aware User Communications & Multi-Locale Hardening` |
| Overall status | `todo` |
| Execution order | Sequential only: Step 1 → manual verification → commit → Step 2 → manual verification → commit → Step 3 → manual verification → commit → Step 4 → final verification |
| Steps / proposed commits | 4 |
| Blocking predecessor | `ANY-529 — 4B.2 Localize Existing Portal UI & Client-Facing Application Copy` |
| Current predecessor PR | `gushinets/payments-portal#124` — open and mergeable at plan validation |
| Current inherited research baseline | `ANY-529` head `dc9e70d8be970383e0714b7a4925412cf2c00132` |
| Merged predecessor chain | `ANY-408` merge `746ebffac9901a611597c0b618f080d60666ca55` → `ANY-526` merge `9ddebdd610463dc2049b53b860278408abfb4087` → current `ANY-529` PR head |
| Expected database work | None |
| Expected generated-locale contract change | None; consume the existing generated contract and keep `npm run generate:check` green |
| Expected provider / LBX work | None |
| Successor boundary | Completed 4B becomes the provider-independent Portal presentation baseline consumed by `ANY-504` Step 5; it is not LBX evidence |

The concrete SHA above is a planning snapshot, not durable architecture authority. `ANY-529` is still open. Implementation may start from this reviewed head, but **ANY-533 must contain the final merged/reviewed ANY-529 result before 4B.3 is considered complete**. If PR #124 changes, synchronize those changes before final Step 4 verification and re-check only the directly affected 4B.3 surfaces.

At planning time no GitHub `ANY-533` branch exists yet.

---

## How to Use This File

1. Create the `ANY-533` working branch from the latest reviewed `ANY-529` branch while PR #124 is open, or from the final merged `ANY-529` result once it lands. Do not branch from an older `main` baseline and replay 4B.1/4B.2 manually.
2. Keep this file at `docs/exec-plans/active/ANY-533-implementation-plan.md` while the ticket is active.
3. Use a fresh execution chat for each implementation step.
4. Give the execution model this plan and the repository. Do not ask it to repeat broad Linear/ADR/repository research.
5. For every step:
   - implement only that step;
   - review the diff yourself;
   - run the listed manual verification commands yourself;
   - commit only after the focused checks pass;
   - update the step status in this plan yourself if desired.
6. Before Step 4 final verification, ensure the branch contains the final/current `ANY-529` predecessor result. If the predecessor changed one of the files/contracts named below, reconcile that change first; do not redo the full i18n investigation.
7. The execution model must not run tests, linters, formatters, builds, generators, verification commands, `git add`, or `git commit`.
8. Treat each step's **Primary files** list as a closed investigation set. The execution model may open those files and the explicitly named generated/read-only contract files. If a named symbol has moved after predecessor synchronization, allow one exact-symbol/path lookup to locate that symbol; do not inventory neighboring modules, reread tickets/docs, inspect git history, or broaden into repository research. If the moved code changes an architectural assumption rather than only its location, stop and report the contradiction.
9. Do not research framework/RFC/library alternatives during execution. Concrete parsing, transport, locale-flow, email-template, and AST-guard choices are locked below; local implementation details not affecting contracts should follow the surrounding code style.

---

## Research Snapshot and Source-of-Truth Resolution

### Authority chain

The current source-of-truth order for this ticket is:

1. `ANY-525` and `ANY-533` for the Step 4B locale/communication contract.
2. The final completed predecessor implementation (`ANY-526` + `ANY-529`) for the concrete current runtime and established i18n patterns.
3. `ARCHITECTURE.md`, `docs/engineering/CODING_CONVENTIONS.md`, and accepted architecture authority where they do not conflict with the selected 4B.3 contract.
4. Existing tests/guards for current security, routing, API, and localization behavior.

ADR `0005 — External billing boundary` remains accepted and confirms that `ANY-504` controls provider-dependent execution order and that provider-specific production semantics remain gated by LBX Phase 0. Nothing in ANY-533 changes billing authority or provider semantics.

### Proven predecessor baseline

The researched ancestry is concrete:

```text
ANY-408 / PR #120
  merge 746ebffac9901a611597c0b618f080d60666ca55
        ↓
ANY-526 / PR #121
  base = that ANY-408 merge
  merge 9ddebdd610463dc2049b53b860278408abfb4087
        ↓
ANY-529 / PR #124
  base = that ANY-526 merge
  current head = dc9e70d8be970383e0714b7a4925412cf2c00132
```

PR #124 has no unresolved inline review threads at the planning snapshot. Its PR description explicitly leaves frontend-to-backend locale propagation, localized reset URLs/email, and the broader ordinary-UI-copy hardening guard to 4B.3.

### Established locale runtime that ANY-533 must consume

The current predecessor already provides:

- `config/locales.json` as the single checked-in machine-readable locale authority;
- generated web and API locale artifacts;
- exactly these public route locales: `en`, `fr`, `it`, `de`, `es`, `ru`, `pt`;
- `ru` as the default/routing fallback;
- distinct `routeLocale`, `languageTag`, and `intlLocale` identities;
- public `pt` mapped to `languageTag = pt-BR` and `intlLocale = pt-BR`;
- `next-intl` locale routing under `app/[locale]`;
- explicit locale-prefixed URLs as authoritative;
- root-only `Accept-Language` negotiation;
- `localeDetection: false` and `localeCookie: false`;
- server-first translation ownership;
- root `NextIntlClientProvider` with `messages={null}`;
- bounded current-locale namespace delivery to true Client Components;
- seven complete UI catalogs with exact key/ICU signature checks;
- canonical RU-only legal routing/content/evidence;
- locale-neutral auth/session state;
- reset-confirmation locale switching disabled;
- reset tokens kept fragment/client-only.

Do not create another locale registry, message loader, routing layer, formatting mapping, persistence field, or locale preference mechanism.

### Current frontend password-reset boundary

At `dc9e70d...`:

- `apps/web/src/app/[locale]/forgot-password/page.tsx` already has access to the validated explicit route locale through `getCurrentRouteLocale()`;
- `apps/web/src/features/password-reset/PasswordResetRequestClient.tsx` submits the localized form;
- it currently calls `requestPasswordReset({ email })`;
- `apps/web/src/shared/api/auth.ts` sends only `{ email }` and has no language metadata;
- shared API transport is intentionally language-neutral and is protected from owning human-readable localized presentation.

The clean 4B.3 boundary is therefore:

```text
validated explicit routeLocale (server page)
  → generated LANGUAGE_TAG_BY_ROUTE_LOCALE
  → PasswordResetRequestClient prop
  → requestPasswordReset request metadata
  → Accept-Language header on this request only
```

The route-to-language-tag mapping must stay outside generic shared API transport. `shared/api/auth.ts` may carry an already-canonical header value but must not import locale catalogs, `next-intl`, or duplicate route-to-language rules.

### Current API/password-reset boundary

Current code:

- `apps/api/app/domains/identity/password_reset.py` owns FastAPI Presentation for reset request/confirmation;
- `apps/api/app/domains/identity/services/password_reset.py` owns token/rate-limit/account lookup and delivery preparation;
- `apps/api/app/core/password_reset_email.py` owns reset URL/email presentation;
- `apps/api/app/core/email.py` is a generic SMTP text-delivery primitive;
- `apps/api/app/generated/locales.py` already contains the generated route locale type, default locale, supported route locales, and route-locale → language-tag mapping.

Current gap:

- Presentation does not read `Accept-Language`;
- `prepare_password_reset()` has no locale input;
- `build_password_reset_url()` hardcodes `/ru/reset-password`;
- reset subject/body are hardcoded Russian.

### Password-reset invariants already proven by current tests

Existing behavior that must remain unchanged:

- tenant and region come from server settings;
- client JSON cannot choose tenant or region;
- account lookup and anti-enumeration behavior are locale-neutral;
- rate-limit keys remain based on tenant/region/account/IP and never locale;
- token identity, hashing, TTL, claim, and replay behavior remain locale-neutral;
- token storage remains hashed;
- reset confirmation still revokes active sessions and invalidates outstanding reset tokens;
- reset token transport remains URL fragment only;
- delivery-disabled and delivery-failure observability remains secret-safe;
- public request response remains `{"status":"accepted"}`;
- language-neutral error codes/statuses remain unchanged.

### Active backend-originated communication inventory

The current API application tree contains the generic SMTP primitive and the password-reset email surface. No second active backend-originated end-user communication was identified. Therefore this plan does **not** introduce a generic notification framework, CMS, template engine, or provider communication abstraction.

### Current hardening coverage

The predecessor already protects:

- seven-catalog exact key/ICU/argument/tag parity;
- all seven locale roots and `html lang` values;
- root locale negotiation and RU fallback;
- explicit locale URL authority and direct/deep-link behavior;
- locale switch pathname/query preservation;
- auth/session continuity across locale changes;
- canonical RU legal routes and no fake alternates;
- reset-confirmation switch restriction and fragment-token safety;
- routing-owned literal `/ru` regressions;
- language-neutral shared API presentation ownership.

The missing concrete hardening item is the broader **ordinary hardcoded UI copy** guard promised by 4B.3. Current source inspection found no remaining ordinary direct JSX copy requiring migration on the researched head beyond intentional source-owned/non-translatable literals such as the `AnytoolAI` brand and the `user@example.com` example placeholder. The new guard should protect that state instead of triggering another UI rewrite.

### Bounded documentation contradiction to fix

`docs/engineering/CODING_CONVENTIONS.md` currently ends the 4B.2 handoff with a blanket instruction not to infer 4B.3 behavior from route locale. That wording is too broad for the authoritative ANY-525/ANY-533 contract.

For password-reset communication only, 4B.3 **must** derive the canonical `languageTag` from the explicit validated `routeLocale`. The corrected rule must continue to forbid inferring tenant, region, identity, provider, currency, timezone, or persistence state from locale.

---

## Locked Implementation Decisions

These decisions are resolved by the ticket, current code, predecessor architecture, and this planning pass. Execution agents must not reopen them unless the current branch materially contradicts an assumption.

1. **Frontend derivation happens from the validated explicit URL locale.**
   - `forgot-password/page.tsx` obtains the canonical `RouteLocale` through `getCurrentRouteLocale()`.
   - It derives `languageTag` through generated `LANGUAGE_TAG_BY_ROUTE_LOCALE`.
   - The Client Component receives only that canonical language tag as a prop.
   - Do not derive tenant/region/provider/currency/timezone from it.

2. **`Accept-Language` is added only to the password-reset request.**
   - Keep the JSON body exactly `{ email }`.
   - Do not globally add locale to all auth/API calls.
   - Do not store locale in localStorage, cookies, session state, user rows, tokens, or database tables.

3. **Generic web transport stays locale-policy-neutral.**
   - Extend `postJson()` only with an optional `extraHeaders?: Readonly<Record<string, string>>` argument **after** the existing `token?: string` argument. Do not use a broad `HeadersInit` here; the implementation intentionally relies on plain-record spreading and fixed-header override order.
   - Preserve its existing token parameter and all current decoders.
   - Build headers as `extraHeaders` first, then fixed `Content-Type`, then optional fixed `Authorization`, so feature code cannot override transport/security-owned headers.
   - Add a small `PasswordResetRequestOptions` shape containing `languageTag: string`; keep `PasswordResetRequestValues` as `{ email: string }`.
   - `requestPasswordReset()` owns the single `Accept-Language` use.

4. **API normalization stays in FastAPI Presentation.**
   - `apps/api/app/domains/identity/password_reset.py` reads the header and converts it to canonical `RouteLocale` before invoking the service.
   - Application/service code never receives arbitrary header text.

5. **Use the existing generated locale contract; do not change the generator for this ticket.**
   - Derive a case-insensitive reverse lookup mechanically from `LANGUAGE_TAG_BY_ROUTE_LOCALE` in `apps/api/app/generated/locales.py`.
   - Do not add a handwritten Python supported-locale list or second config file.
   - `scripts/repo.py`, `config/locales.json`, and generated locale artifacts should remain unchanged unless the final inherited predecessor unexpectedly changes the contract.

6. **Use one strict local weighted `Accept-Language` parser; do not research or implement a broader RFC negotiation framework.**
   - Read the raw value with the already-present FastAPI `Request`: `request.headers.get("accept-language")`. Do not add a second header dependency parameter only for this endpoint.
   - Build one private module-level reverse map by case-folding the generated `LANGUAGE_TAG_BY_ROUTE_LOCALE` values. If the case-folded key count differs from the generated mapping count, raise a configuration/runtime error immediately because reverse selection is ambiguous.
   - Implement one private normalizer (for example `_normalize_password_reset_route_locale(value: str | None) -> RouteLocale`).
   - For each comma-separated item, strip surrounding OWS. Empty items are ignored.
   - Split the item by `;`. Accept **only** either `<tag>` or `<tag>;q=<qvalue>`; an item with extra/duplicate parameters is malformed and is ignored as a whole. Strip OWS around the two segments.
   - Do not implement a generic BCP-47 parser. A tag is supported only when its case-folded text exactly matches a generated canonical `languageTag`; `*` and all other tags are unsupported.
   - Default weight is `1.0`. For an explicit weight, use the equivalent of `(?i)^q=(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)$`: accept `0`, `0.`, `0.xxx` (up to 3 digits), `1`, `1.`, or `1.000` (up to 3 zeroes). Treat `q` case-insensitively; do not accept other parameter names, signs, exponent notation, `.5`, values above `1`, or more than 3 fractional digits.
   - Ignore candidates with `q=0`. Keep the supported candidate with the numerically highest positive weight; update only on `>` so the first input item wins ties.
   - If no valid supported canonical candidate remains, return generated `DEFAULT_ROUTE_LOCALE` (`ru`).
   - Do not add regional best-fit policy beyond the canonical generated language tags. The web already sends canonical values (`de`, `pt-BR`, etc.). Arbitrary noncanonical variants are unsupported request metadata and fall back to RU unless the header also contains a supported canonical entry.
   - Raw header text must never be used as a path/template selector.

7. **Carry only canonical ephemeral locale metadata through delivery preparation.**
   - Add `route_locale: RouteLocale` to `prepare_password_reset()`.
   - Include the same canonical locale in `PasswordResetDeliveryResult` so URL and email delivery cannot accidentally diverge.
   - Do not persist it on `MagicLinkToken`, `User`, auth session, rate-limit rows, or any billing model.

8. **Reset URL construction accepts only canonical `RouteLocale`.**
   - `build_password_reset_url(token, route_locale)` constructs `/{route_locale}/reset-password#token=...`.
   - The token remains exclusively after `#`.
   - Do not put token or locale in query parameters for convenience.

9. **Password-reset email presentation remains a small backend-owned structure.**
   - Keep it in `apps/api/app/core/password_reset_email.py`.
   - Add one explicit template record per generated `RouteLocale` in one module, validated for exact completeness against `SUPPORTED_ROUTE_LOCALES`.
   - Do not introduce Jinja, Babel, a generic notification framework, CMS/TMS, or per-locale files for this single current email surface.

10. **Email copy preserves current semantics only.**
    Every locale template must communicate the same facts as the current RU email:
    - AnytoolAI password reset subject;
    - greeting;
    - instruction to open the reset link;
    - the reset URL;
    - instruction to ignore the email if the user did not request the reset;
    - the current reset-link validity duration.

    `pt` copy must use Brazilian Portuguese semantics. Do not add legal, security, commercial, or marketing claims that are not present in the current email.

11. **The TTL remains service-owned.**
    - `PASSWORD_RESET_TTL_MINUTES = 30` remains the authority for token expiry.
    - Pass that value into the email renderer/sender so the “30 minutes” statement cannot drift into a separate hardcoded policy constant.

12. **The final ordinary-copy guard is bounded, AST-based, and focused on direct active JSX presentation.**
    - Extend the existing web i18n contract/boundary tests using the already-installed TypeScript compiler API; add no new dependency.
    - Scan active `.tsx` files under `src/app/[locale]`, `src/features`, and `src/shared/ui`.
    - Detect direct human-readable JSX literals containing any Unicode letter (`/\p{L}/u`) in: trimmed non-empty `JsxText`; child-content `JsxExpression` values whose direct expression is a `StringLiteral` / `NoSubstitutionTemplateLiteral` (exclude attribute-owned `JsxExpression` nodes so attributes are classified once by the attribute rule); and literal values in user-facing attributes such as `aria-label`, `title`, `placeholder`, and `alt`. Expression calls such as `{t("...")}` are not direct copy.
    - Keep a tiny explicit allowlist for intentional direct source-owned/non-translatable values verified on the final predecessor tree (currently the `AnytoolAI` brand/fragments and `user@example.com` example placeholder). Key every allowlist entry by repository-relative POSIX path + surface kind/attribute + exact literal value; never by value globally.
    - Do not scan generated legal content or source-owned `.ts` data as if they were translatable Portal copy.
    - If final predecessor synchronization adds a new direct literal, classify it: ordinary copy must move to the catalog; only genuinely source-owned/non-translatable content may receive a narrowly documented allowlist entry.

13. **Existing 4B guards remain the authority for their own concerns.**
    - Do not duplicate the `/ru` routing guard.
    - Do not replace catalog parity tests.
    - Do not multiply the deep E2E suite by seven.

14. **No persistence, schema, provider, legal-evidence, or billing redesign belongs here.**

---

# Step 1 — Propagate the canonical password-reset request language from the explicit route

**Status:** `todo`

**Goal**  
Make the localized forgot-password UI send the canonical generated language tag through `Accept-Language` on the password-reset request only, while keeping generic API transport and the JSON business payload language-neutral.

**Scope / affected code**

Primary files:

- `apps/web/src/app/[locale]/forgot-password/page.tsx`
- `apps/web/src/features/password-reset/PasswordResetRequestClient.tsx`
- `apps/web/src/shared/api/auth.ts`
- `apps/web/e2e/password-reset.spec.ts`
- `apps/web/tests/eslint-boundaries.test.mjs`

Existing contracts consumed, not redesigned:

- `apps/web/src/i18n/current-locale.ts`
- `apps/web/src/generated/locales.ts`
- `apps/web/src/i18n/request.ts`

**Implementation decisions**

1. In `forgot-password/page.tsx`, resolve the explicit validated `routeLocale` with `getCurrentRouteLocale()` and map it through generated `LANGUAGE_TAG_BY_ROUTE_LOCALE`.
2. Pass only the resulting canonical `languageTag` into `PasswordResetRequestClient`.
3. Update `PasswordResetRequestClient` to call `requestPasswordReset()` with `{ email }` plus the injected canonical language metadata; do not call `useLocale()` and independently reinterpret route values inside the Client Component.
4. In `shared/api/auth.ts`:
   - keep `PasswordResetRequestValues` as `{ email: string }`;
   - add `PasswordResetRequestOptions = { languageTag: string }` (or the equivalent local type);
   - extend `postJson()` with `extraHeaders?: Readonly<Record<string, string>>` **after** the existing `token?: string` argument, so existing callers remain source-compatible;
   - do not use `HeadersInit` for this optional argument; use the existing plain object header construction;
   - merge `extraHeaders` first, then fixed `Content-Type`, then optional fixed `Authorization`;
   - make only `requestPasswordReset(values, options)` send `Accept-Language: options.languageTag`.
5. Keep response decoding and `ApiError` behavior unchanged.
6. Update the shared-API boundary test allowlist for the machine header literal `Accept-Language`; do not weaken the rule against localized human-readable strings in `shared/api`.
7. Extend password-reset browser coverage so:
   - a representative `de` reset request sends `Accept-Language: de`;
   - `/pt/forgot-password` sends `Accept-Language: pt-BR`;
   - the POST body remains exactly `{ email }` with no locale/region/tenant fields;
   - existing normal success/error decoding behavior remains unchanged.

**Invariants**

- `routeLocale`, `languageTag`, and `intlLocale` remain distinct;
- JSON request body remains password-reset business data only;
- generic auth/session transport is not implicitly locale-coupled;
- no locale persistence is introduced;
- no API response/error contract changes;
- `pt` public route still maps to `pt-BR` via generated authority only.

**Out of scope**

- backend `Accept-Language` parsing;
- reset URL changes;
- email localization;
- API/business/security changes;
- CORS middleware/settings changes (`Accept-Language` needs no project CORS redesign and current API CORS already allows request headers);
- hardcoded UI copy guard;
- docs closeout;
- database/schema/provider work.

**AI prompt**

```text
Implement only Step 1 of ANY-533: propagate the canonical password-reset request language from the explicit locale route to the password-reset API request metadata.

The implementation plan has already completed the broad research. Follow the decisions in this prompt exactly. Do not perform broad repository research, do not read unrelated Linear tickets/PR history, and do not redesign the established i18n architecture. Inspect only the directly relevant current files named below if needed to verify that the plan assumptions still hold after predecessor synchronization.

Primary files:
- apps/web/src/app/[locale]/forgot-password/page.tsx
- apps/web/src/features/password-reset/PasswordResetRequestClient.tsx
- apps/web/src/shared/api/auth.ts
- apps/web/e2e/password-reset.spec.ts
- apps/web/tests/eslint-boundaries.test.mjs

Established contracts to consume:
- getCurrentRouteLocale() returns the validated explicit routeLocale.
- apps/web/src/generated/locales.ts is generated authority and exposes LANGUAGE_TAG_BY_ROUTE_LOCALE.
- public route `pt` maps to canonical languageTag `pt-BR`.
- shared/api must remain language-neutral presentation-wise.

Implement these exact decisions:

1. In forgot-password/page.tsx, obtain routeLocale with getCurrentRouteLocale(), derive the canonical languageTag from LANGUAGE_TAG_BY_ROUTE_LOCALE, and pass only that languageTag to PasswordResetRequestClient.

2. Update PasswordResetRequestClient to accept the canonical languageTag prop and pass it to requestPasswordReset when the form is submitted.

3. Keep PasswordResetRequestValues as business data only: `{ email: string }`.

4. In shared/api/auth.ts:
- keep `PasswordResetRequestValues = { email: string }`;
- add `PasswordResetRequestOptions = { languageTag: string }` (or an equivalent local type);
- change postJson() to accept `extraHeaders?: Readonly<Record<string, string>>` after the existing `token?: string`; do not use a broad `HeadersInit` because this helper uses plain object header spreading;
- build headers in this order: extraHeaders, fixed Content-Type, fixed Authorization when token exists, so feature code cannot override transport/security-owned headers;
- only requestPasswordReset(values, options) should add `Accept-Language: options.languageTag`;
- do not import next-intl, message catalogs, RouteLocale, or route-to-language mapping into shared/api.

5. Do not add locale to the JSON body, localStorage, cookies, auth session state, user state, or any other request. Do not modify CORS middleware/settings for this step; the existing API CORS configuration already permits request headers.

6. Update the shared API boundary test only as needed to classify `Accept-Language` as a machine/transport literal. Do not weaken the existing prohibition on human-readable localized presentation in shared/api.

7. Extend the focused password-reset E2E coverage to prove:
- a `/de/forgot-password` submission sends `Accept-Language: de`;
- a `/pt/forgot-password` submission sends `Accept-Language: pt-BR`;
- request JSON remains exactly `{ email }`.
Use locale-independent selectors where useful instead of duplicating translation assertions.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not implement backend language parsing, localized reset URLs, or localized emails yet.
Do not run tests, linters, formatters, generators, builds, type checkers or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report the changed files;
- briefly summarize what changed and confirm that the JSON body remains `{ email }`;
- report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

```bash
npm run test:boundaries:web
npm run lint:web
npm run typecheck:web
npm run test:e2e -- apps/web/e2e/password-reset.spec.ts
```

**Expected completion**  
Forgot-password requests now carry canonical request-language metadata derived from the explicit route; `pt` sends `pt-BR`; the business JSON body, auth/session behavior, and generic transport semantics remain unchanged.

**Proposed commit**

```text
feat(i18n): propagate password reset request locale
```

---

# Step 2 — Normalize request language at API Presentation and make reset URLs locale-aware

**Status:** `todo`

**Goal**  
Convert untrusted `Accept-Language` request metadata into one canonical generated `RouteLocale` at the FastAPI Presentation boundary and use it only to build the reset delivery route, without changing password-reset security/business behavior.

**Scope / affected code**

Primary files:

- `apps/api/app/domains/identity/password_reset.py`
- `apps/api/app/domains/identity/services/password_reset.py`
- `apps/api/app/core/password_reset_email.py`
- `apps/api/tests/test_api_password_reset.py`
- `apps/api/tests/test_email.py`

Generated contract consumed, not edited:

- `apps/api/app/generated/locales.py`

**Implementation decisions**

1. Add one small private request-language normalization helper in `app.domains.identity.password_reset`; read the raw value from the existing `Request` with `request.headers.get("accept-language")`.
2. Derive one private case-folded languageTag → routeLocale reverse map from generated `LANGUAGE_TAG_BY_ROUTE_LOCALE`; do not maintain a second supported-locale list. Fail fast if case-folding causes a key collision.
3. Implement the strict parser already locked above; do not research another negotiation policy:
   - comma-separated items, surrounding whitespace stripped;
   - item shape is only `<tag>` or `<tag>;q=<qvalue>`; extra/duplicate parameters make that item invalid;
   - supported tag means exact case-insensitive match to a generated canonical `languageTag`; no generic BCP-47/best-fit parsing;
   - default q is `1.0`; explicit q accepts only `0`, `0.`, `0.xxx` up to 3 digits, `1`, `1.`, or `1.000` up to 3 zeroes; `q` itself is case-insensitive;
   - ignore invalid/unsupported/wildcard items and q=0;
   - highest positive q wins and the first item wins ties;
   - if no supported candidate survives, return generated `DEFAULT_ROUTE_LOCALE` (`ru`).
4. Do not add regional best-fit matching at this API boundary. The web already maps its validated explicit route locale to a canonical language tag. Noncanonical external metadata is unsupported and falls back unless it also supplies a canonical supported candidate.
5. In the request endpoint, resolve `route_locale` before calling the service and pass only canonical `RouteLocale` inward.
6. Add `route_locale: RouteLocale` to `prepare_password_reset()` and to the ephemeral `PasswordResetDeliveryResult`.
7. Do **not** include locale in:
   - rate-limit keys;
   - tenant/region resolution;
   - account lookup;
   - `MagicLinkToken` fields;
   - token hash/claims;
   - confirmation behavior;
   - response DTOs/errors.
8. Change `build_password_reset_url()` to accept canonical `route_locale` and produce:

```text
{APP_PUBLIC_BASE_URL}/{route_locale}/reset-password#token=...
```

9. Keep the fragment encoding behavior; token must never move to path/query.
10. Extend focused API tests for:
    - all seven canonical language tags;
    - `pt-BR -> pt`;
    - case-insensitive canonical tag matching;
    - weighted supported candidates;
    - `q=0` candidates are ignored, including a mixed case where another supported positive candidate wins and an all-zero case falls back to `ru`;
    - missing header -> `ru`;
    - unsupported/malformed/wildcard/injection-style values -> safe `ru` fallback when no supported candidate remains;
    - unchanged accepted response/error semantics.
11. Parameterize URL tests across all generated supported route locales and assert token is never present in query/path.

**Invariants**

- Presentation is the only layer that sees raw header text;
- service receives canonical locale only;
- locale does not alter tenant/region/security/rate-limit/account behavior;
- request anti-enumeration remains unchanged;
- token remains hashed at rest and fragment-only in the URL;
- no schema migration or persistence field;
- response remains `{"status":"accepted"}`.

**Out of scope**

- localized email subject/body;
- generic localization framework;
- frontend changes from Step 1;
- hardcoded UI guard/docs closeout;
- regional best-fit API matching beyond canonical supported tags;
- provider/billing work.

**AI prompt**

```text
Implement only Step 2 of ANY-533: normalize password-reset Accept-Language at FastAPI Presentation and make the generated reset URL use the normalized route locale.

The implementation plan already researched the architecture. Follow the decisions below exactly. Do not perform broad repository research. Inspect only the directly relevant current files if needed to verify that Step 1 and the inherited ANY-529 baseline still match these assumptions.

Primary files:
- apps/api/app/domains/identity/password_reset.py
- apps/api/app/domains/identity/services/password_reset.py
- apps/api/app/core/password_reset_email.py
- apps/api/app/generated/locales.py (read-only generated authority)
- apps/api/tests/test_api_password_reset.py
- apps/api/tests/test_email.py

Implement these decisions:

1. Keep raw Accept-Language handling in apps/api/app/domains/identity/password_reset.py, the FastAPI Presentation boundary.

2. Read the header from the existing FastAPI Request with `request.headers.get("accept-language")`. Derive a private case-folded reverse lookup from generated LANGUAGE_TAG_BY_ROUTE_LOCALE. Do not write a second manual supported-locale list and do not edit the generated locale artifact. Fail fast if two generated language tags collide after case-folding instead of silently picking one route locale.

3. Implement exactly this local parser/normalizer; do not research or introduce another Accept-Language library/policy:
- input `None` or empty -> DEFAULT_ROUTE_LOCALE;
- split on commas and strip surrounding whitespace per item; ignore empty items;
- split each non-empty item on `;`; accept only one segment (`tag`) or exactly two segments (`tag`, `q=...`); extra/duplicate parameters invalidate that item;
- tag matching is only exact case-insensitive lookup against generated canonical languageTag values; `*` and noncanonical tags are unsupported;
- omitted q means 1.0; explicit q accepts only `0`, `0.`, `0.xxx` with at most 3 digits, `1`, `1.`, or `1.000` with at most 3 zeroes; match the `q` name case-insensitively; reject `.5`, signs, exponent forms, q>1, non-zero fractional digits after 1, and more than 3 fractional digits;
- ignore malformed/unsupported/q=0 items;
- keep the candidate with highest positive q and replace the current best only when q is strictly greater, preserving first-item tie order;
- if no valid supported candidate remains, return DEFAULT_ROUTE_LOCALE (`ru`);
- do not add regional best-fit behavior for noncanonical tags;
- never use raw header text as a path or template selector.

Examples that must hold:
- `de` -> `de`
- `PT-br` -> `pt`
- `en;q=0.4,de;q=0.9` -> `de`
- `de;q=0.8,en;q=0.8` -> `de` (first wins tie)
- `de;q=0,en;q=0.5` -> `en`
- `de;q=0` -> `ru`
- `ja-JP,de;q=0.7` -> `de`
- `de;foo=bar,en;q=0.6` -> `en` (malformed item is ignored, valid item remains)
- `de;q=.5` -> `ru`
- `de;q=1.1` -> `ru`
- missing/empty -> `ru`
- unsupported `ja-JP` -> `ru`
- wildcard `*` with no supported candidate -> `ru`
- malformed/injection-shaped input with no valid supported candidate -> `ru`

4. Resolve the normalized route_locale in the password-reset request endpoint and pass only that canonical value to prepare_password_reset().

5. Add route_locale: RouteLocale to prepare_password_reset() and PasswordResetDeliveryResult. This is ephemeral delivery metadata only.

6. Use route_locale only for reset delivery presentation. Do not put it in rate-limit keys, tenant/region selection, account lookup, MagicLinkToken, token claims, auth/session state, or response DTOs.

7. Change build_password_reset_url(token, route_locale) so it generates:
`{app_public_base_url}/{route_locale}/reset-password#token=...`
Keep the token exclusively in the fragment and preserve existing safe fragment encoding.

8. Extend the existing API tests instead of replacing them. Preserve all current security/anti-enumeration/rate-limit/session-revocation assertions.

Add focused coverage for:
- all seven canonical language tags normalizing to the correct route locale;
- pt-BR -> pt;
- case-insensitive canonical matching;
- q-weight choice, including explicit `q=0` exclusion (`de;q=0,en;q=0.5 -> en`) and all-zero fallback (`de;q=0 -> ru`);
- RU fallback for missing/unsupported/malformed/wildcard/injection-shaped input;
- unchanged `{"status":"accepted"}` response;
- locale not changing existing tenant/region/rate-limit/token behavior.

9. Parameterize reset URL tests across generated SUPPORTED_ROUTE_LOCALES and prove the token remains after `#` and never enters path/query.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not localize email subject/body yet.
Do not add a library, generic i18n framework, persistence field, or database migration.
Do not run tests, linters, formatters, generators, builds, type checkers or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report the changed files;
- briefly summarize the normalization rule and delivery-only data flow;
- report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

```bash
python -m pytest -p no:cacheprovider apps/api/tests/test_api_password_reset.py apps/api/tests/test_email.py -q
```

**Expected completion**  
Untrusted request language is reduced to a canonical generated `RouteLocale` before Application/service logic; all seven canonical tags work; unsafe/unsupported input falls back to RU; reset URLs return to the matching locale route while security and response semantics stay unchanged.

**Proposed commit**

```text
feat(i18n): normalize password reset delivery locale
```

---

# Step 3 — Localize backend-owned password-reset email presentation for all seven locales

**Status:** `todo`

**Goal**  
Use the same canonical route locale from Step 2 to select a complete backend-owned password-reset email template for all seven locales, while preserving generic SMTP delivery, observability, token security, and the 30-minute reset policy.

**Scope / affected code**

Primary files:

- `apps/api/app/domains/identity/password_reset.py`
- `apps/api/app/domains/identity/services/password_reset.py`
- `apps/api/app/core/password_reset_email.py`
- `apps/api/tests/test_api_password_reset.py`
- `apps/api/tests/test_email.py`

Explicitly not expected to change:

- `apps/api/app/core/email.py`
- database models/migrations
- generated locale files

**Implementation decisions**

1. In `password_reset_email.py`, add a small immutable template representation (prefer a frozen dataclass, matching current Python style) for:
   - `subject`;
   - `body` template containing only `{reset_url}` and `{ttl_minutes}` dynamic values.
2. Define exactly one template entry for each generated `RouteLocale` (`en/fr/it/de/es/ru/pt`) in the same module.
3. Treat those entries as presentation content, not a second locale registry. Add a test that template keys equal `SUPPORTED_ROUTE_LOCALES` exactly, so adding/removing a supported locale cannot silently leave email coverage incomplete.
4. Preserve the current email semantics exactly across translations:
   - password reset for AnytoolAI;
   - greeting;
   - instruction to open the link;
   - reset link;
   - ignore-if-not-requested statement;
   - link validity statement.
5. `pt` must be Brazilian Portuguese. Keep the `AnytoolAI` brand unchanged. Treat dialect quality as a manual content-review requirement: automated tests can prove template selection/completeness/rendering, but they must not be described as proving Brazilian-vs-European Portuguese semantics.
6. Add a pure renderer with the concrete shape `render_password_reset_email(*, route_locale: RouteLocale, reset_url: str, ttl_minutes: int) -> PasswordResetEmailContent` (the return type may be the same frozen template/content dataclass if that keeps the module smaller). It must perform only canonical template selection and `.format(reset_url=..., ttl_minutes=...)`-style rendering; no SMTP side effects.
7. Change the sender contract to `send_password_reset_email(email: str, reset_url: str, route_locale: RouteLocale, ttl_minutes: int) -> bool`: render, then delegate unchanged text delivery to `send_text_email()`.
8. Keep `PASSWORD_RESET_TTL_MINUTES` in the service as the reset-lifetime authority. `send_password_reset_email_safely(email: str, reset_url: str, route_locale: RouteLocale) -> None` passes that exact constant to `send_password_reset_email(...)`.
9. Thread `PasswordResetDeliveryResult.route_locale` into the existing FastAPI background task as the third positional argument. Update `skip_password_reset_email(email: str, reset_url: str, route_locale: RouteLocale) -> None` to the same three-argument background-task shape. Do not put TTL into `PasswordResetDeliveryResult`; it remains service policy.
10. Preserve secret-safe observability:
    - no recipient/reset URL/token/template body in warning logs;
    - same `sent` / `disabled` / `failed` metrics/outcomes;
    - same Sentry ownership and failure category.
11. Update existing monkeypatches/fakes for the new sender signature rather than weakening current behavior tests.
12. Add tests proving:
    - exact seven-locale template completeness;
    - every rendered body contains the provided reset URL and the passed TTL;
    - subject/body are non-empty;
    - `pt` selects the explicitly authored `pt` template and preserves its exact authored subject/body through rendering;
    - router/service delivery passes the same normalized route locale to URL and email;
    - missing/unsupported request language reaches the RU template through Step 2 fallback;
    - disabled/failure observability remains secret-safe.

**Invariants**

- generic SMTP transport remains locale-agnostic;
- email locale equals reset URL locale from the same canonical delivery result;
- TTL policy has one authority;
- no locale stored on token/user/session/database;
- no generic notification framework;
- no translated legal content;
- anti-enumeration and delivery-failure behavior unchanged.

**Out of scope**

- HTML email redesign;
- templates for future LBX/provider notifications;
- CMS/TMS/runtime translation;
- legal document translation;
- web UI copy guard/docs closeout;
- persistence/schema work.

**AI prompt**

```text
Implement only Step 3 of ANY-533: localize the backend-owned password-reset email presentation for all seven supported locales using the canonical route locale established by Step 2.

Broad research and architecture decisions are already complete. Follow this prompt exactly. Inspect only the directly relevant current files if needed to verify the Step 2 signatures before editing. Do not redesign the email/integration architecture.

Primary files:
- apps/api/app/domains/identity/password_reset.py
- apps/api/app/domains/identity/services/password_reset.py
- apps/api/app/core/password_reset_email.py
- apps/api/tests/test_api_password_reset.py
- apps/api/tests/test_email.py

Generated authority to consume:
- apps/api/app/generated/locales.py

Implement these decisions:

1. Keep password-reset email presentation in app/core/password_reset_email.py. Do not create a generic notification framework, template engine, CMS/TMS abstraction, per-locale files, or new dependency.

2. Add one small immutable password-reset template representation with:
- subject
- body template
The body template may interpolate only `reset_url` and `ttl_minutes`.

3. Define one explicit template for every generated RouteLocale: en, fr, it, de, es, ru, pt.
These are content variants, not a second supported-locale registry. Add completeness tests against generated SUPPORTED_ROUTE_LOCALES.

4. Translate only the existing email meaning in every locale:
- AnytoolAI password-reset subject;
- greeting;
- instruction to open the reset link;
- reset URL;
- ignore the email if the user did not request the reset;
- reset-link validity duration.
Do not add legal, marketing, provider, commercial, or security claims that do not exist in the current RU email.
Keep the AnytoolAI brand unchanged.
Use Brazilian Portuguese wording for the public `pt` locale.

5. Use these concrete function contracts unless a local naming collision requires an equivalent spelling:
- `render_password_reset_email(*, route_locale: RouteLocale, reset_url: str, ttl_minutes: int) -> PasswordResetEmailContent`;
- `send_password_reset_email(email: str, reset_url: str, route_locale: RouteLocale, ttl_minutes: int) -> bool`;
- `send_password_reset_email_safely(email: str, reset_url: str, route_locale: RouteLocale) -> None`;
- `skip_password_reset_email(email: str, reset_url: str, route_locale: RouteLocale) -> None`.
The pure renderer selects the canonical template and renders only reset_url/ttl_minutes. The sender delegates to the unchanged generic send_text_email(). Do not add locale logic to app/core/email.py.

6. Keep PASSWORD_RESET_TTL_MINUTES in the identity password-reset service as the sole token-lifetime authority. send_password_reset_email_safely() passes that exact value into send_password_reset_email(). Do not add TTL to PasswordResetDeliveryResult.

7. Use the route_locale already carried by PasswordResetDeliveryResult. In the existing request router background task, pass delivery.route_locale as the third positional task argument. The send/skip background task call shapes remain identical.

8. Preserve existing observability and secret-redaction behavior. Never add recipient email, reset URL, token, or email body to logs/Sentry metadata.

9. Extend existing tests rather than replacing them. Cover:
- exact template key completeness against generated SUPPORTED_ROUTE_LOCALES;
- non-empty subject/body for every locale;
- rendered body contains the supplied reset URL and TTL;
- explicit `pt` template selection and exact preservation of its authored subject/body through rendering;
- normalized locale is shared by reset URL and email presentation;
- missing/unsupported header still produces RU presentation via the Step 2 fallback;
- delivery-disabled/failure observability stays secret-safe.
Update existing sender monkeypatches/fakes for the new signature while preserving their original assertions.
Before completing the step, manually review the authored `pt` subject/body for Brazilian Portuguese wording and semantic equivalence to the RU source. Do not claim automated tests establish dialect quality.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not modify database schema or persistence semantics.
Do not implement future provider/LBX communications.
Do not run tests, linters, formatters, generators, builds, type checkers or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report the changed files;
- briefly summarize the template structure, locale flow, and preserved security/observability invariants;
- report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

```bash
python -m pytest -p no:cacheprovider apps/api/tests/test_api_password_reset.py apps/api/tests/test_email.py -q
```

Manual content review:

- inspect the authored `pt` password-reset subject/body and confirm Brazilian Portuguese wording with the same meaning as the current RU source; automated tests verify template selection/completeness/rendering, not dialect quality.

**Expected completion**  
Every supported locale produces a locale-matched reset URL and localized backend-owned text email; RU fallback is deterministic; the 30-minute policy, token security, anti-enumeration, SMTP transport, and secret-safe observability are unchanged.

**Proposed commit**

```text
feat(i18n): localize password reset emails
```

---

# Step 4 — Add the final ordinary-copy guard, update durable 4B guidance, and close the multi-locale contract

**Status:** `todo`

**Goal**  
Protect the completed 4B baseline against concrete locale regressions, correct stale predecessor documentation, and run the final bounded multi-locale contract matrix without expanding scope into a new localization framework or future billing work.

**Scope / affected code**

Primary expected files:

- `apps/web/tests/i18n-contract.test.mjs`
- `ARCHITECTURE.md`
- `docs/engineering/CODING_CONVENTIONS.md`
- `apps/web/AGENTS.md`

Only if the final predecessor synchronization exposes a real uncovered regression in an existing contract:

- `apps/web/e2e/password-reset.spec.ts`
- `apps/web/e2e/locale-routing.spec.ts`
- directly relevant current presentation file containing a newly detected ordinary hardcoded literal

Existing guards/tests to consume rather than duplicate:

- `apps/web/tests/eslint-boundaries.test.mjs`
- `apps/web/e2e/locale-routing.spec.ts`
- `apps/web/e2e/password-reset.spec.ts`
- `apps/api/tests/test_api_password_reset.py`
- `apps/api/tests/test_email.py`

**Implementation decisions**

1. Before editing this step, the human owner must ensure the branch contains the final/current `ANY-529` result. If predecessor changes touched these surfaces, inspect only those changed files and reconcile them before continuing.
2. Extend `apps/web/tests/i18n-contract.test.mjs` with a bounded direct-copy guard using the already-installed `typescript` package/compiler API. Do not investigate alternative parsers.
3. Recursively scan active `.tsx` presentation source under:

```text
apps/web/src/app/[locale]
apps/web/src/features
apps/web/src/shared/ui
```

4. Use the concrete AST walk below; do not design a different static-analysis system:
   - `import ts from "typescript"` (or equivalent namespace import if required by the module loader);
   - parse each file with `ts.createSourceFile(filePath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)`;
   - recursively walk children with `ts.forEachChild`;
   - for `ts.isJsxText(node)`, trim the text and inspect it when non-empty;
   - for `ts.isJsxExpression(node)`, inspect it only when it is JSX child content rather than an attribute initializer (for example, `!ts.isJsxAttribute(node.parent)`) and its direct expression is a `StringLiteral` or `NoSubstitutionTemplateLiteral`; this catches forms such as `<p>{"Reset your password"}</p>` / direct no-substitution template literals while leaving calls such as `{t("...")}` alone and avoids double-classifying literal attributes;
   - for `ts.isJsxAttribute(node)` where the attribute name is exactly `aria-label`, `title`, `placeholder`, or `alt`, inspect only a direct `StringLiteral` initializer or a `JsxExpression` containing a `StringLiteral` / `NoSubstitutionTemplateLiteral`; expression calls such as `{t("...")}` are not direct copy;
   - treat a candidate as human-readable when it contains any Unicode letter (`/\p{L}/u`), rather than maintaining language-specific character ranges.
5. Store intentional exceptions as exact, reviewable `(repository-relative POSIX file path, surface kind/attribute, literal value)` entries rather than a global value-only allowlist. The researched head has exactly these expected exceptions:
   - `apps/web/src/shared/ui/SiteShell.tsx`: `JsxText` values `Anytool` and `AI`; `aria-label="AnytoolAI"`;
   - `apps/web/src/shared/ui/AuthForm.tsx`: `placeholder="user@example.com"`;
   - `apps/web/src/features/password-reset/PasswordResetRequestClient.tsx`: `placeholder="user@example.com"`.
6. Include small synthetic assertions for the detector helper itself: ordinary `JsxText` such as `Reset your password` must be reported; the direct JSX-expression form `<p>{"Reset your password"}</p>` (and equivalent no-substitution template literal form) must also be reported; whitespace, an empty `alt`, and the explicitly modeled brand/example exceptions must not be reported.
7. Do not expand this guard into source-owned `.ts` business/legal/config data. Seller facts, generated legal content, identifiers, support addresses, and user content remain outside ordinary translation ownership.
8. Do not duplicate the existing `/ru` route-literal guard or catalog parity/ICU checks.
9. Update `ARCHITECTURE.md` to describe the completed end-to-end communication contract:

```text
explicit validated routeLocale
  → generated languageTag
  → password-reset Accept-Language request metadata
  → API Presentation normalization to canonical RouteLocale
  → localized reset URL + backend-owned email
```

   Also document RU fallback and reiterate that locale never becomes tenant/region/identity/provider/currency/timezone/persistence state.
10. Fix `docs/engineering/CODING_CONVENTIONS.md`:
    - replace the stale blanket “do not infer any of them from route locale” 4B.3 handoff wording;
    - document that **only** the bounded password-reset communication flow derives canonical `languageTag` from an explicit validated route locale;
    - preserve the prohibition on inferring tenant/region/identity/provider/currency/timezone or persistence semantics from locale;
    - document the implemented ordinary-copy guard instead of saying it is deferred.
11. Update `apps/web/AGENTS.md` so it no longer says backend `Accept-Language`, reset URL/email localization, and ordinary-copy hardening are future 4B.3 work. Record the completed request-metadata rule without moving locale mapping into shared API transport.
12. Do not populate the currently empty `apps/api/AGENTS.md` merely for symmetry; the durable cross-cutting rule is sufficiently owned by architecture/coding guidance unless the final implementation introduces an API-specific convention not captured there.
13. Use existing tests for the final matrix rather than adding seven copies of every behavior test.
14. No database migration, locale persistence, legal translation, provider work, billing work, visual redesign, or route architecture redesign.

**Invariants**

- exact locale set still derives from `config/locales.json`;
- generated artifacts remain in sync;
- all seven message catalogs retain key/ICU signature parity;
- direct/deep links and explicit route authority stay intact;
- switcher still preserves pathname/query and auth/session state;
- reset-confirmation still hides locale switching;
- reset token remains fragment-only;
- canonical legal routes/text/evidence remain RU-only;
- locale stays independent from region/provider/currency/timezone;
- no all-locale client bundle or message-loading regression;
- no persistence/schema changes.

**Out of scope**

- new localization library/framework;
- broad natural-language static analysis;
- translation of source-owned seller/provider/legal facts;
- visual redesign;
- future LBX/provider communication;
- generalized notifications;
- database work.

**AI prompt**

```text
Implement only Step 4 of ANY-533: add the final bounded ordinary-UI-copy regression guard and update durable documentation to describe the completed 4B locale communication contract.

Prerequisite: the human owner has synchronized the final/current ANY-529 predecessor result into this branch. Do not perform git synchronization yourself. If the directly relevant predecessor files materially differ from the assumptions below, stop and describe the contradiction.

Broad research is already complete. Do not re-read Linear tickets, PR history, unrelated ADRs, or the repository broadly. Inspect only the directly relevant files named here plus an exact presentation file if the new guard identifies a concrete current offender.

Primary files:
- apps/web/tests/i18n-contract.test.mjs
- ARCHITECTURE.md
- docs/engineering/CODING_CONVENTIONS.md
- apps/web/AGENTS.md

Existing contract tests to preserve, not duplicate:
- apps/web/tests/eslint-boundaries.test.mjs
- apps/web/e2e/locale-routing.spec.ts
- apps/web/e2e/password-reset.spec.ts

1. Extend apps/web/tests/i18n-contract.test.mjs with a bounded direct ordinary-copy guard using the already-installed `typescript` compiler API. Do not add a dependency and do not inspect alternative parser libraries.

Use `ts.createSourceFile(filePath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)` and recursively walk nodes with `ts.forEachChild`.

Scan `.tsx` files recursively only under:
- apps/web/src/app/[locale]
- apps/web/src/features
- apps/web/src/shared/ui

Detect exactly:
- trimmed non-empty `JsxText` containing a Unicode letter (`/\p{L}/u`);
- child-content `JsxExpression` values (exclude expressions owned by `JsxAttribute`, e.g. via `!ts.isJsxAttribute(node.parent)`) whose direct expression is a `StringLiteral` / `NoSubstitutionTemplateLiteral`, again only when the literal contains a Unicode letter; this must catch forms such as `<p>{"Reset your password"}</p>` while ignoring expression calls such as `{t("...")}` and avoiding duplicate attribute findings;
- direct `StringLiteral` attribute initializers, or `JsxExpression` attribute values containing a `StringLiteral` / `NoSubstitutionTemplateLiteral`, for attributes named exactly `aria-label`, `title`, `placeholder`, or `alt`, again only when the value contains a Unicode letter.
Do not flag expression calls such as `{t("...")}` or other non-literal expressions.

Keep a tiny explicit allowlist keyed by repository-relative POSIX file path + surface kind/attribute + exact literal value, not by value globally. Use exactly these baseline entries unless the final predecessor changes them:
- apps/web/src/shared/ui/SiteShell.tsx: JsxText `Anytool`;
- apps/web/src/shared/ui/SiteShell.tsx: JsxText `AI`;
- apps/web/src/shared/ui/SiteShell.tsx: aria-label `AnytoolAI`;
- apps/web/src/shared/ui/AuthForm.tsx: placeholder `user@example.com`;
- apps/web/src/features/password-reset/PasswordResetRequestClient.tsx: placeholder `user@example.com`.

If the final inherited tree contains another direct literal:
- if it is ordinary Portal-owned customer-facing copy, move it into the existing locale catalog pattern;
- if it is genuinely source-owned/non-translatable, add only a narrowly documented allowlist entry;
- if classification is materially ambiguous, stop and report it instead of weakening the guard.

Add small synthetic assertions in the test module proving the detector reports both ordinary `JsxText` `Reset your password` and the direct JSX-expression form `<p>{"Reset your password"}</p>` (plus the equivalent no-substitution template literal form), ignores whitespace/empty alt text, and accepts only the explicitly modeled brand/example exceptions.

Do not scan generated legal documents or generic `.ts` source-owned business/config data as ordinary translatable copy.
Do not duplicate the existing `/ru` routing guard or catalog key/ICU parity checks.

2. Update ARCHITECTURE.md to describe the completed flow:
explicit validated routeLocale -> generated languageTag -> password-reset Accept-Language metadata -> API Presentation normalization to canonical RouteLocale -> localized reset URL/email.
Document deterministic RU fallback for missing/unsupported request language and reiterate that locale does not select or persist tenant, region, identity, provider, currency, or timezone.

3. Update docs/engineering/CODING_CONVENTIONS.md:
- remove the stale blanket 4B.2 handoff wording that says 4B.3 behavior must not be inferred from route locale;
- state the narrow allowed rule: password-reset communication derives canonical languageTag from the explicit validated routeLocale and sends it as request metadata;
- continue to forbid deriving tenant/region/identity/provider/currency/timezone/persistence semantics from locale;
- document the now-implemented ordinary hardcoded UI copy guard instead of saying it is deferred.

4. Update apps/web/AGENTS.md so it no longer lists Accept-Language propagation, reset URL/email localization, and the broader ordinary-copy guard as future 4B.3 work. Keep the rule that shared/api does not own route-to-language mapping or localized presentation.

5. Do not populate apps/api/AGENTS.md just for symmetry unless the current implementation created an API-specific convention that is not already accurately captured by the architecture/coding docs.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not introduce a new i18n framework, generalized notification system, database change, provider work, legal translation, or visual redesign.
Do not run tests, linters, formatters, generators, builds, type checkers or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report changed files;
- summarize the new guard and documentation changes;
- explicitly call out any intentional allowlist entries;
- report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

**Manual verification**

Focused final contract checks:

```bash
npm run generate:check
python -m pytest -p no:cacheprovider apps/api/tests/test_api_password_reset.py apps/api/tests/test_email.py -q
npm run test:boundaries:web
npm run lint:web
npm run typecheck:web
npm run test:e2e -- apps/web/e2e/password-reset.spec.ts apps/web/e2e/locale-routing.spec.ts
APP_PUBLIC_BASE_URL=https://payments.example.test npm run build:web
```

Repository/durable-guidance checks:

```bash
npm run docs:check
npm run architecture:check
npm run check:fast
```

A PostgreSQL-specific suite is not required for this ticket because no persisted schema, query, transaction, or database semantics are intentionally changed.

**Expected completion**  
The complete 4B contract is protected from direct ordinary-copy regression; durable docs describe the actual URL → request metadata → API normalization → localized communication flow; existing seven-locale routing/UI/security contracts remain green; no new locale registry, persistence, provider behavior, or legal semantics were introduced.

**Proposed commit**

```text
test(i18n): harden multi-locale communication contract
```

---

# Final Validation

The completed implementation should have this single coherent flow:

```text
explicit URL routeLocale
        ↓
validated by the existing 4B route runtime
        ↓
generated LANGUAGE_TAG_BY_ROUTE_LOCALE
        ↓
Accept-Language on password-reset request only
        ↓
FastAPI Presentation parses untrusted metadata
        ↓
canonical generated RouteLocale or RU fallback
        ↓
prepare_password_reset delivery metadata
        ↓
locale-prefixed reset URL + localized email template
        ↓
unchanged generic SMTP delivery
```

The following remain deliberately separate:

```text
locale                     = presentation preference
instance tenant / region   = server-owned contour
identity / auth session    = locale-neutral
currency / timezone        = independent/source-owned facts
legal canonical content    = RU source/evidence authority
LBX/provider semantics     = future ANY-504 Step 5+ evidence/work
```

## Acceptance-Criteria Coverage

| ANY-533 requirement | Plan coverage |
| --- | --- |
| Password-reset UI sends canonical `Accept-Language` | Step 1 |
| `pt` route sends `pt-BR` | Step 1 |
| JSON payload remains `{ email }` | Step 1 |
| API validates/normalizes request language | Step 2 |
| Missing/unsupported/malformed input falls back to RU | Step 2 |
| Locale cannot become arbitrary path/template input | Step 2 |
| All seven locales normalize through generated authority | Step 2 |
| Reset URL returns to locale-prefixed confirmation route | Step 2 |
| Token remains fragment-only | Step 2 + existing E2E |
| Email subject/body localized for all seven locales | Step 3 |
| `pt` uses Brazilian Portuguese semantics | Step 3 |
| 30-minute statement stays tied to actual TTL | Step 3 |
| Delivery failures remain secret-safe | Step 3 + existing tests |
| No locale persistence/schema migration | Locked invariant across all steps |
| Frontend/backend locale contract has one source | Existing generated artifacts + Steps 1/2 |
| No second active communication abstraction invented | Research result + Step 3 scope |
| Hardcoded ordinary UI copy regression guard | Step 4 |
| Existing routing/deep-link/switch/session/html-lang contracts remain intact | Existing E2E + Step 4 final matrix |
| Catalog parity and current-locale-only loading remain intact | Existing boundary contract + Step 4 final matrix |
| Docs reflect completed 4B architecture | Step 4 |
| 4B remains provider-independent and ready for ANY-504 Step 5 baseline consumption | All steps / final validation |

## Plan Validation Result

This plan is intentionally four substantial steps:

1. **Frontend request propagation** establishes only the bounded metadata path and leaves backend behavior untouched.
2. **API normalization + URL localization** establishes the untrusted-to-canonical boundary and delivery routing without mixing in email-copy work.
3. **Email localization** completes backend-originated presentation using the canonical locale and existing SMTP/observability behavior.
4. **Hardening/docs** protects the completed 4B baseline and performs final verification without opportunistic redesign.

No step requires the execution model to make a new business, persistence, public API, security, ownership, or architecture decision.

The plan intentionally does **not** implement:

```text
locale persistence in DB/session/cookie/localStorage
new database migrations
new public API fields
regional/tenant/provider selection from locale
currency/timezone inference from locale
canonical legal document translation
legal evidence/hash/version changes
generic notification framework
CMS/TMS/runtime machine translation
LBX/provider communication
billing/catalog/payment behavior
visual redesign
routing/message architecture redesign
```

`ANY-533` is implementation-ready against the researched `ANY-529` head, subject only to the mandatory final predecessor synchronization rule described above.
