# ANY-541 — Establish Generated Backend-Frontend API Contract Boundary

## Plan Overview

**Linear issue:** `ANY-541`  
**Parent:** `ANY-504 — External Billing & Paid Access`  
**Direct predecessor:** `ANY-538 — Establish Email Verification & New-Password Baseline`  
**Development baseline:** `ANY-538` is implementation-complete and ready to inherit. ANY-541 may be developed from its current final code before the formal PR merge; GitHub merge status alone is not a blocker.  
**Relevant predecessor:** `ANY-510 — Identity / Session / Legal baseline`  
**Future consumer:** `ANY-539 / Step 4F — Portal frontend evolution`

**Status:** `done`

### Objective

Establish one durable backend-to-frontend API contract authority chain:

```text
FastAPI / Pydantic
  → canonical OpenAPI
  → repository-owned generated Zod schemas + inferred TypeScript wire types
  → existing shared API transport
  → frontend consumers
```

After ANY-541:

- backend Pydantic models remain the source of truth for web-consumed wire contracts;
- frontend production code does not independently re-declare migrated backend request/response DTOs;
- successful JSON remains `unknown` until runtime validation succeeds;
- generated contract artifacts participate in normal repository generation and stale checks;
- existing auth/session/password-reset/email-verification behavior remains unchanged;
- frontend form/UI/view-state models remain frontend-owned;
- Step 4F can add new Portal-owned APIs without reopening the contract-authority decision.

### Execution order

```text
Step 1 — Establish deterministic OpenAPI → Zod generation                    [DONE / Sol]
Step 2 — Establish frontend Sentry error-reporting boundary                  [Sol]
Step 3 — Migrate current production auth consumers                           [Sol]
Step 4 — Enforce the boundary and publish the durable 4F handoff             [Luna]
```

Each step is intended for a separate implementation chat with fresh context.

Use one commit per step.

---

# Locked Implementation Decisions

These decisions are already resolved. Do not reopen them during implementation unless the inherited ANY-538 baseline or current repository state materially contradicts them.

## Contract authority

Canonical authority:

```text
FastAPI/Pydantic
  → app.openapi()
  → docs/generated/openapi.json
  → generated frontend runtime schemas/types
```

Backend Pydantic request/response models remain authoritative for the **API wire shape**.

OpenAPI is not the authority for every backend business rule. In the final ANY-538 baseline, `RegisterRequest.password` and `PasswordResetConfirmRequest.password` intentionally expose only `string` in Pydantic/OpenAPI. The actual new-password policy (`12–128` Unicode code points plus required character classes) remains backend business validation in the identity password-policy code.

Therefore ANY-541 must **not** reconstruct password-policy constraints in generated Zod schemas, must not copy backend password constants into the frontend contract layer, and must not restore `min_length` / `max_length` to those Pydantic request fields merely to make OpenAPI stricter.

Do not introduce manually maintained frontend wire schemas.

## Generation mechanism

Use:

- `@hey-api/openapi-ts`
- Zod plugin only
- Zod v4
- generated reusable component definitions
- TypeScript types inferred from generated Zod schemas

Do **not** generate:

- SDK functions;
- HTTP clients;
- fetch wrappers;
- Axios clients;
- React Query/TanStack Query integrations;
- operation-specific request wrappers unless they become unavoidable for generation correctness.

The existing repository transport in `apps/web/src/shared/api/auth.ts` remains the transport boundary.

## Dependencies

Install with npm so `package.json` and `package-lock.json` are updated normally:

```bash
npm install --save-dev --save-exact @hey-api/openapi-ts
npm install --workspace @anytoolai/web --save-exact zod@4
```

Do not manually edit the lockfile.

## Generator configuration

The repository-owned generator must use the equivalent of:

```text
plugin: zod

compatibilityVersion: 4

definitions:
  enabled: true
  name: "z{{name}}"
  types:
    infer:
      enabled: true
      name: "{{name}}"

requests: false
responses: false
webhooks: false
```

Generated runtime schema names must therefore remain:

```text
zRegisterRequest
zRegisterResponse
zLoginRequest
zLoginResponse
zSessionResponse
...
```

Generated inferred TypeScript names must retain the Pydantic/OpenAPI component names:

```text
RegisterRequest
RegisterResponse
LoginRequest
LoginResponse
SessionResponse
SessionUserResponse
...
```

Explicitly point the generator at:

```text
apps/web/tsconfig.json
```

Do not allow a script located under `scripts/` to guess the frontend TypeScript configuration.

## Generated artifact location

Use:

```text
apps/web/src/generated/api-contracts/
```

This directory is repository-generated code.

Normal generation must replace stale generated output rather than leaving obsolete files behind.

## Generation pipeline

Extend the existing repository generation flow in:

```text
scripts/repo.py
```

Do not create a parallel generation command that bypasses:

```bash
npm run generate
npm run generate:check
```

The API-contract generator must consume the same freshly rendered OpenAPI representation used by repository generation.

`generate --check` must:

1. render current backend OpenAPI;
2. generate frontend contracts into a temporary directory;
3. compare expected generated files with committed files;
4. fail on missing, changed, or obsolete generated files;
5. not mutate committed generated artifacts.

Normal `generate` must synchronize the generated directory with expected output and remove obsolete generated files.

## Backend scope

Do not change backend Pydantic models merely to make frontend generation easier. In particular, do not restore `min_length` / `max_length` on registration or password-reset new-password fields: their password policy is intentionally business validation, not an OpenAPI transport constraint.

Do not redesign:

- auth semantics;
- bearer session transport;
- authentication headers;
- OpenAPI security schemes;
- persistence;
- transactions;
- email verification;
- password behavior;
- legal ownership.

## Current migrated API surface

The current web-consumed backend wire contracts are:

```text
RegisterRequest
RegisterResponse

LoginRequest
LoginResponse

SessionResponse
SessionUserResponse

LogoutResponse

PasswordResetRequest
PasswordResetRequestResponse
PasswordResetConfirmRequest
PasswordResetConfirmResponse

EmailVerificationRequest
EmailVerificationRequestResponse
EmailVerificationConfirmRequest
EmailVerificationConfirmResponse
```

`email_verified` remains part of `SessionUserResponse`.

## Legal / account disposition

There is no separate current Account API contract to migrate.

Current account UI consumes:

```text
/api/auth/session
/api/auth/logout
```

and therefore belongs to the auth migration.

Current legal frontend code consumes generated legal manifest/content rather than maintaining duplicate TypeScript DTOs for the backend legal endpoints.

Therefore:

- do not add a speculative legal API consumer;
- do not migrate unused legal endpoint contracts merely for completeness.

## Frontend-local types

Frontend-owned form/UI state stays local.

In particular:

```text
AuthFormSubmitValues
AuthMode
SubmitAuthValues
```

may remain frontend adapter/form concepts.

Do not force UI form state into generated API contracts.

## Auth adapter type

If `submitAuth()` needs one result type, define only the derived union:

```ts
type AuthResponse = RegisterResponse | LoginResponse;
```

This is allowed because it composes generated backend types instead of re-declaring their wire fields.

## Runtime validation

Every successful JSON payload must follow:

```text
response.json()
  → unknown
  → generatedSchema.safeParse(payload)
  → success: result.data
  → failure: ApiContractError
```

Do not use:

```text
as SomeResponse
```

Do not expose `ZodError` directly to features/UI.

Malformed successful responses must continue to surface as the existing `ApiContractError`.

## Error handling

Do not build a generated universal error platform.

Keep:

```text
ApiError.detail: unknown
```

and retain the existing narrow `apiErrorCode()` behavior required by current UI flows.

Unknown or malformed error JSON must not become a trusted typed domain error.

## Frontend error observability

Runtime contract validation is useful only if production contract failures are visible to the team. ANY-541 therefore also establishes a **minimal web Sentry reporting boundary** before production consumers are migrated.

Use the existing Sentry organization, but keep the web application in its own Sentry project/DSN from the FastAPI project:

```text
payment-portal-api  → existing Python sentry-sdk project
payment-portal-web  → @sentry/nextjs project
```

This does **not** create a backend relay endpoint and does not replace the existing backend Sentry integration. The web application reports directly through the official Next.js SDK.

Keep one error-reporting vocabulary across backend and web where it is useful:

```text
service
failure_category
operation
```

The web service tag is:

```text
payment-portal-web
```

Initial web reporting scope is intentionally small:

- standard uncaught browser exceptions and Next.js server/Edge/request errors are captured through the configured SDK/runtime hooks; this step does not claim complete React render-error coverage without a custom application error boundary;
- handled API contract-validation failures call the shared reporter as `consistency_invariant_violation` / `api_contract_validation` before the existing `ApiContractError` is propagated; the reporter is a no-op while DSN is absent and sends to Sentry only when later enabled;
- expected `ApiError` responses, normal authentication failures, form validation, known business outcomes, payment declines, and other expected domain states are **not** reported as exceptions merely because the user flow did not succeed;
- handled `5xx` API responses are not duplicated into web Sentry merely because they are non-2xx; the FastAPI/backend Sentry boundary remains authoritative for backend failures;
- handled network/abort/transient failures are not reported by default unless they become an otherwise-unhandled web exception.

Sentry reporting is an observability side effect only. A missing DSN, unavailable Sentry service, SDK failure, or rejected event must never change auth/session/UI behavior and must never prevent `ApiContractError` or other application errors from following their existing control flow.

Privacy is strict. Do not send:

```text
request body
response body
raw Zod payload/error data
bearer or verification/reset tokens
cookies
localStorage
email or user identity
query strings or URL fragments
headers
```

Allow only the minimum safe diagnostic context needed for a contract failure, such as:

```text
service = payment-portal-web
failure_category = consistency_invariant_violation
operation = api_contract_validation
route = /api/auth/session        # pathname only
contract = SessionResponse
release / environment
stack trace
```

The frontend Sentry configuration must use the Sentry JavaScript v11 privacy controls explicitly rather than legacy `sendDefaultPii`. Configure restrictive `dataCollection` so user info, cookies, request/response headers, HTTP bodies, URL query parameters and other unnecessary request/application data are not collected; keep Sentry Logs unused by not calling `Sentry.logger.*` and not adding logging integrations such as `consoleLoggingIntegration()` or Pino; keep tracing disabled for this error-only baseline. Sanitize events before delivery so SDK defaults cannot reintroduce sensitive browser/request context. Do not attach raw API payloads or raw validation errors.

This step is **error reporting only**. Do not add Session Replay, performance tracing, profiling, Sentry Logs, user/session identity tracking, a custom error ingestion API, or a generic frontend error framework. Source-map upload is not required by ANY-541 and must not introduce insecure build-secret handling; it may be enabled later through a secure build pipeline.

## Direct production consumers confirmed by research

`apps/web/src/shared/api/auth.ts` is directly consumed by:

```text
apps/web/src/features/account/AccountClient.tsx
apps/web/src/features/checkout/CheckoutClient.tsx
apps/web/src/features/email-verification/EmailVerificationClient.tsx
apps/web/src/shared/ui/HeaderAccount.tsx
apps/web/src/shared/ui/EmailVerificationPending.tsx
```

Password-reset pages also consume the exported auth API wrappers.

These consumers are already known. Do not perform a broad repository-wide dependency investigation before implementation.

## Final ANY-538 frontend behavior that 4D must preserve

The latest ANY-538 commits add behavior that is **not part of the wire schema**, but must survive the Step 3 migration to generated contracts:

- `HeaderAccount` treats the local bearer as trusted until the matching `/session` request proves it invalid with `401`; malformed-success responses, `5xx` responses, and network failures must not clear the bearer.
- `HeaderAccount` must ignore both stale successful `/session` responses and stale `401` responses when `localStorage` already contains a different bearer than the one used to start that request. A response for token A must never overwrite or clear token B.
- `EmailVerificationClient` keeps a fragment verification token memory-only after removing it from the URL. If a fragment token is pending, `email_verified=true` on the current session must not silently discard that token; the pending token remains available for explicit confirmation.
- Account switching from `EmailVerificationClient` still attempts backend logout, but backend logout failure must not block local sign-out or destroy the pending in-memory verification token.

These are frontend state/concurrency invariants, not backend API DTOs. Generated contracts must replace only wire-shape duplication and must not simplify these behaviors.

## Repository frontend instructions

The final ANY-538 baseline also updates `apps/web/AGENTS.md` with mandatory Next.js agent guidance. Any step that edits web production code must read and follow the current `apps/web/AGENTS.md` and the specific local documentation it explicitly requires. Do not expand that into unrelated repository research. If a Next.js API/convention is touched, use the relevant local guide under `node_modules/next/dist/docs/` rather than relying on model memory.

## Predecessor rule

ANY-541 inherits directly from the current final ANY-538 implementation baseline. ANY-538 is considered implementation-complete for development sequencing, so ANY-541 may start from and build on that code before PR #127 is formally merged. Do not block implementation solely on GitHub merge status.

Use the current ANY-538 head as the inherited baseline when it contains commits not yet present on `main`. After ANY-538 is merged, rebase/update ANY-541 onto the merged result in the normal workflow.

If ANY-538 receives a later substantive commit that materially changes any of these surfaces:

```text
backend auth Pydantic contracts
apps/web/src/shared/api/auth.ts
repository generation harness
```

re-check only the affected ANY-541 assumptions. If they materially contradict the approved plan, stop and report the contradiction before redesigning the solution.

Changes elsewhere in ANY-538 that do not affect these contract/generation surfaces do not block ANY-541 and do not require broad re-research. Minor file movement or naming drift may be handled locally without reopening research.

---

# Step 1 — Establish Deterministic OpenAPI-to-Zod Generation

**Status:** `done` — implemented before this plan revision; do not reopen or redo this step.  
**Recommended model:** `Sol` — highest-risk step; establishes the generation/stale-check infrastructure used by all later work.

## Goal

Add deterministic repository-owned generation of frontend runtime schemas and inferred wire types from current FastAPI/Pydantic OpenAPI.

At the end of this step:

```text
FastAPI/Pydantic
→ current OpenAPI
→ generated Zod definitions/types
```

exists and participates in normal `generate` / `generate:check`.

No production frontend consumer is migrated yet.

## Scope / affected code

Expected implementation surfaces:

```text
package.json
package-lock.json
apps/web/package.json
scripts/repo.py
scripts/generate-api-contracts.mjs            # new
apps/web/src/generated/api-contracts/**       # generated
```

Inspect only directly relevant generation helpers if the actual current filenames differ.

## Implementation decisions

### 1. Install exact dependencies

Use:

```bash
npm install --save-dev --save-exact @hey-api/openapi-ts
npm install --workspace @anytoolai/web --save-exact zod@4
```

`@hey-api/openapi-ts` is repository tooling.

`zod` is a runtime dependency of the web application because generated schemas execute in production frontend code.

### 2. Add one repository-owned generator adapter

Create:

```text
scripts/generate-api-contracts.mjs
```

Its responsibility is only:

```text
OpenAPI input
→ @hey-api/openapi-ts
→ Zod component schemas + inferred TS types
→ requested output directory
```

Do not put repository stale-check logic inside the Node adapter.

That remains owned by `scripts/repo.py`.

### 3. Use the locked Zod configuration

Configure only the Zod plugin:

```text
compatibilityVersion: 4

definitions:
  enabled: true
  name: "z{{name}}"
  types:
    infer:
      enabled: true
      name: "{{name}}"

requests: false
responses: false
webhooks: false
```

Do not enable SDK/client/plugins that are not required.

Explicitly use:

```text
apps/web/tsconfig.json
```

for TypeScript configuration.

### 4. Generate from fresh OpenAPI

Do not treat the currently committed `docs/generated/openapi.json` as an independently authoritative input.

Within repository generation:

```text
render current FastAPI app OpenAPI
→ use that exact fresh result for docs/generated/openapi.json
→ use the same current result as input to frontend contract generation
```

A temporary OpenAPI file may be used as an implementation detail if required by the generator API.

Do not add a second OpenAPI-rendering authority.

### 5. Preserve `generate` semantics

Normal:

```bash
npm run generate
```

must update:

```text
docs/generated/openapi.json
apps/web/src/generated/api-contracts/**
```

and remove obsolete generated frontend files.

### 6. Preserve `generate:check` semantics

Check mode must generate expected contracts in a temporary directory and compare recursively.

Failure conditions include:

```text
committed generated file differs
expected generated file is missing
obsolete committed generated file exists
OpenAPI artifact is stale
```

Do not mutate committed files during check mode.

Use the existing Python generation/check pattern rather than inventing another CI system.

### 7. Do not touch API semantics

No backend Pydantic model change belongs to this step unless a concrete generator defect proves the existing OpenAPI invalid.

If that occurs, stop and report instead of silently redesigning the API.

## Invariants

- FastAPI/Pydantic stays authoritative.
- OpenAPI stays repository-generated.
- Generated frontend files are reproducible.
- Generated output is committed.
- Zod performs runtime validation.
- No SDK/client generation is introduced.
- Existing transport is untouched.
- No API behavior changes.

## Out of scope

Do not:

- migrate `auth.ts`;
- change feature/components;
- change auth behavior;
- modify OpenAPI auth/security representation;
- create Portal APIs;
- generate all possible frontend clients;
- redesign repository CI;
- introduce a second contract source.

## AI prompt

```text
Implement only Step 1 of ANY-541: deterministic OpenAPI-to-Zod frontend contract generation.

Do not perform broad repository or architecture research. The design decisions are already settled.

Inspect only:
- root package.json and package-lock.json,
- apps/web/package.json,
- apps/web/tsconfig.json,
- scripts/repo.py,
- the current OpenAPI generation helper it directly uses,
- existing generated-directory conventions if needed.

Implementation requirements:

1. Install exact dependencies using npm:
   npm install --save-dev --save-exact @hey-api/openapi-ts
   npm install --workspace @anytoolai/web --save-exact zod@4

   Do not manually edit package-lock.json.

2. Add scripts/generate-api-contracts.mjs as a thin programmatic @hey-api/openapi-ts adapter.

3. Generate only reusable Zod OpenAPI component definitions and inferred TypeScript types.

Use these settled Zod plugin decisions:
- compatibilityVersion: 4
- definitions.enabled: true
- definitions.name: "z{{name}}"
- definitions.types.infer.enabled: true
- definitions.types.infer.name: "{{name}}"
- requests: false
- responses: false
- webhooks: false

Do not enable SDK, client, fetch, axios, React Query/TanStack Query, or other generated transport plugins.

4. Explicitly point generation at apps/web/tsconfig.json.

5. Generated output belongs under:
   apps/web/src/generated/api-contracts/

6. Integrate API-contract generation into the existing scripts/repo.py generate_all() authority.

Use the freshly rendered FastAPI OpenAPI for both:
- docs/generated/openapi.json
- frontend API-contract generation

Do not make the previously committed OpenAPI file a second authority.

7. In normal generation, synchronize the generated directory and remove obsolete generated files.

8. In --check mode, generate expected frontend contracts into a temporary directory and recursively compare expected files against committed generated files.

Check mode must detect:
- modified generated files,
- missing generated files,
- obsolete generated files.

It must not modify committed generated files.

9. Preserve all existing repository generation behavior.

10. Do not modify backend API models or auth behavior to simplify generation.

The final ANY-538 baseline intentionally leaves RegisterRequest.password and PasswordResetConfirmRequest.password as plain strings in Pydantic/OpenAPI. Do not restore min_length/max_length or otherwise encode the backend password business policy into OpenAPI/Zod as part of ANY-541.

If the inherited ANY-538/current repository code materially contradicts the plan's assumed OpenAPI/generation structure, stop and report the contradiction instead of redesigning the solution.

Do not run tests, linters, formatters, type checks, builds, generate:check, or other automated verification commands.

Running npm install and the generator itself is allowed because those are necessary implementation actions, not verification.

Do not stage, commit, or push.

After implementation report:
- files changed,
- dependency changes,
- generated artifact location,
- how normal generation works,
- how stale checking works,
- any material contradiction,
- exact manual verification commands listed below.
```

## Manual verification

Run manually after the implementation step:

```bash
npm run generate
npm run generate:check
npm run typecheck:web
```

Then run generation once more:

```bash
npm run generate
git diff --exit-code
```

Expected result: a second generation produces no changes.

## Expected completion

- Hey API and Zod are exact-pinned.
- Generated Zod schemas exist under the agreed generated directory.
- Generated TS wire types are inferred from those schemas.
- `npm run generate` owns regeneration.
- `npm run generate:check` detects stale/missing/obsolete generated files.
- No API or frontend behavior has changed.

## Proposed commit

```text
ANY-541 generate frontend API contracts from OpenAPI
```

---

# Step 2 — Establish Minimal Frontend Sentry Error Reporting

**Status:** `done`  
**Recommended model:** `Sol` — small implementation, but production observability/privacy and current Next.js runtime hooks must be correct.

## Goal

Add the smallest Sentry integration foundation for the Next.js application so Step 3 can report `ApiContractError` through one safe shared helper when Sentry is enabled later. The application must remain fully functional with no Sentry project, DSN or other external configuration.

This step is intentionally narrow. It does **not** change generated contracts, auth behavior, UI flows or Step 1. Sentry is disabled by default until a DSN is explicitly configured.

## Scope / affected code

Expected surfaces only:

```text
package-lock.json
apps/web/package.json
apps/web/src/instrumentation-client.ts            # browser init
apps/web/src/instrumentation.ts                   # Node/Edge registration + request error hook
apps/web/sentry.server.config.ts                  # Node init
apps/web/sentry.edge.config.ts                    # Edge init
apps/web/src/shared/observability/sentry.ts       # narrow safe reporter for handled contract failures
apps/web/tests/components/SentryReporting.test.ts # or equivalent focused test
.env.example
.env.production.example
docker-compose.prod.yml                           # optional build/runtime propagation only
apps/web/Dockerfile                               # optional build/runtime propagation only
apps/web/next.config.mjs                          # only if required by the installed SDK for runtime integration
```

Do not add a new application error page/boundary solely for Sentry in this step. Existing UI error handling remains unchanged.

Read `apps/web/AGENTS.md` and only the local Next.js documentation it directly requires for the instrumentation files above. Do not run the Sentry wizard or repeat broad frontend research.

## Implementation decisions

### 1. Install only the official Next.js SDK

```bash
npm install --workspace @anytoolai/web --save-exact @sentry/nextjs@11.4.0
```

Do not manually edit `package-lock.json`. Do not add Replay, analytics, logging or another error SDK.

### 2. Prepare for a separate web Sentry project/DSN, but do not require it now

When Sentry is enabled later, use the existing organization with separate projects:

```text
payment-portal-api  → existing FastAPI project
payment-portal-web  → web project
```

Do **not** require the `payment-portal-web` project or a DSN to exist for this step to be complete. The code must work normally with Sentry unconfigured.

When enabled, the web app reports directly to Sentry. Do not add `/client-errors` or another backend relay.

### 3. Disabled-by-default configuration

Use a single optional activation variable:

```text
NEXT_PUBLIC_SENTRY_DSN
```

If the variable is missing, blank or whitespace-only:

- do not initialize Sentry;
- do not attempt event delivery;
- `reportApiContractError(...)` is a safe no-op;
- browser, Node and Edge application behavior is identical to the current non-Sentry baseline.

Document the variable as optional with an empty default in both development and production env examples. Because `NEXT_PUBLIC_*` browser values are captured during the Next.js image build, propagate `NEXT_PUBLIC_SENTRY_DSN` through the existing web Docker build/production Compose path as an optional `${NEXT_PUBLIC_SENTRY_DSN:-}` value, never as a required `${...:?}` value. Keep it optional at runtime as well for the server/Edge side. Do not require `SENTRY_AUTH_TOKEN`, Sentry project creation, release/environment configuration or source-map upload in this step. Release/environment metadata can be added later when deployment observability needs it.

### 4. Initialize only the standard Next.js runtimes

Use the current supported Next.js 16 / `@sentry/nextjs` instrumentation pattern for:

```text
browser
Node.js server runtime
Edge runtime
Next.js request errors
```

Every initialization/capture entry point must respect the optional DSN and remain inactive when it is absent.

Preserve existing `next-intl`, standalone build and `next.config.mjs` behavior. Change `next.config.mjs` only if the installed SDK requires it for this runtime error-reporting setup.

Do **not** add a new `global-error.tsx` merely for observability in this step. React/UI error-boundary hardening can be added later if production needs it.

### 5. Add one narrow handled-error reporter

Create a small shared helper for the only handled technical failure currently required by ANY-541: contract validation.

Its public responsibility should be equivalent to:

```text
reportApiContractError(error, { route, contract })
```

It reports safe metadata using the same small diagnostic vocabulary as backend where useful:

```text
service = payment-portal-web
failure_category = consistency_invariant_violation
operation = api_contract_validation
route = pathname only
contract = generated contract name
```

Do not build a generic frontend error registry/classification framework. Future error categories can be added when a concrete need appears.

Step 2 only establishes the reporter; Step 3 wires generated-validation failures to it.

### 6. Keep event data safe

Use the Sentry JavaScript v11 privacy controls, not the removed legacy `sendDefaultPii` option. Configure restrictive `dataCollection` for this error-only baseline so user info, cookies, request/response headers, HTTP bodies, URL query parameters and other unnecessary request/application data are not collected. Do not call `Sentry.logger.*` and do not add logging integrations such as `consoleLoggingIntegration()` or Pino; in Sentry JavaScript v11 this keeps Logs unused without an `enableLogs` option. Explicitly set `tracesSampleRate: 0`. For explicit contract events, send only the metadata above plus normal sanitized exception/stack information.

Do not attach:

```text
request/response bodies
headers/cookies
email or user identity
localStorage/sessionStorage
bearer/session/verification/reset tokens
query strings or URL fragments
raw API payloads
raw Zod issues/payload values
arbitrary extra objects
```

Use a small `beforeSend`/sanitization boundary only as needed to remove SDK-created user/request/breadcrumb data that would violate these rules. Do not build a large custom Sentry event schema.

### 7. Do not turn expected outcomes into exceptions

Do not explicitly report normal handled outcomes such as:

```text
ApiError / expected 4xx
login rejection / invalid password
form validation
signed-out or expired-session state
payment decline or commercial refusal
handled network/abort/transient failures
```

Backend `5xx` remains primarily a backend Sentry concern; do not duplicate every handled API failure from the browser.

### 8. Reporting is best-effort only

Missing DSN is the normal default state for now. In that state no SDK initialization or event delivery should occur. Later, when a DSN is configured, Sentry outage or capture failure must still never change application behavior or throw into user flows. Application code must not await Sentry delivery.

### 9. Add only focused tests

Test our boundary, not Sentry internals. At minimum prove:

```text
missing DSN keeps Sentry uninitialized and the reporter is a no-op
capture failure is non-throwing when Sentry is enabled
contract reporter attaches only the approved tags/context
route is pathname-only
payload/token/user/arbitrary-extra data is not sent
```

Mock Sentry; automated tests must never send real events.

## Invariants

- Step 1 implementation is untouched.
- Existing FastAPI Sentry code is untouched.
- No auth/session/business/UI behavior changes.
- No backend relay endpoint.
- No generic frontend error framework.
- Reporting remains optional observability, never application control flow.
- The application requires no Sentry configuration to start, build or run.
- Step completion does not require creating/configuring the web project in Sentry.

## Out of scope

Do not add in this step:

- source-map upload/auth token handling;
- Session Replay;
- performance tracing/profiling;
- Sentry Logs;
- user/session tracking;
- feedback UI;
- custom Sentry tunnel/relay;
- billing-specific reporting;
- new application error pages/boundaries;
- generated-contract migration or changes to generated output.

## AI prompt

```text
Implement only Step 2 of ANY-541: the minimal frontend Sentry error-reporting foundation.

Step 1 is already complete. Do not reopen, regenerate or rewrite Step 1. Package-lock changes caused by installing @sentry/nextjs are expected.

Do not perform broad architecture/frontend research. Read only apps/web/AGENTS.md, the directly required local Next.js instrumentation documentation, current web package/config/Docker/env files, and focused test setup.

Requirements:

1. Install exactly:
   npm install --workspace @anytoolai/web --save-exact @sentry/nextjs@11.4.0
   Do not manually edit package-lock.json.

2. Add only one optional activation variable:
   - NEXT_PUBLIC_SENTRY_DSN

   Do not require a Sentry project or DSN to exist now. Missing/blank DSN is the expected default: do not initialize Sentry, do not attempt delivery, and keep the application fully functional. When Sentry is enabled later, use a dedicated `payment-portal-web` project/DSN in the existing organization.

   Add an empty optional entry to `.env.example` and `.env.production.example`. Propagate it through the existing web Dockerfile and `docker-compose.prod.yml` build/runtime path with an empty default (`${NEXT_PUBLIC_SENTRY_DSN:-}`), never as a required production variable. Remember that the browser-visible value is captured during the Next.js image build.

3. Use the current supported Next.js 16 / @sentry/nextjs pattern for browser, Node, Edge and Next.js request-error capture. Preserve next-intl and standalone build behavior. Change next.config.mjs only if required by this runtime integration. Do not add a new global-error page solely for Sentry.

4. Do not modify the FastAPI/Python Sentry integration and do not create a backend client-error endpoint.

5. Add one small shared helper for future generated-contract failures, equivalent to reportApiContractError(error, { route, contract }). It may send only:
   - service=payment-portal-web
   - failure_category=consistency_invariant_violation
   - operation=api_contract_validation
   - safe route pathname
   - contract name
   - sanitized exception/stack information

   Do not wire it into auth.ts yet; Step 3 owns that migration. Do not create a generic frontend error registry.

6. Privacy: this plan uses @sentry/nextjs v11, where legacy sendDefaultPii is removed. Use restrictive `dataCollection` settings supported by the pinned SDK instead. Disable collection of user info, cookies, request/response headers, HTTP bodies, URL query parameters and other unnecessary request/application data. Do not call `Sentry.logger.*` and do not add logging integrations such as `consoleLoggingIntegration()` or Pino; Sentry JavaScript v11 has no `enableLogs` option and Logs stay unused unless logging APIs/integrations are used. Explicitly set `tracesSampleRate: 0` for this error-only baseline. Do not send storage contents, tokens, fragments, raw API payloads, raw Zod issues/payload values or arbitrary extra objects. Add only the minimum event sanitization needed to enforce this.

7. Do not explicitly report expected ApiError/4xx, authentication/form/business outcomes, payment declines, signed-out/session-expired states or handled network/transient failures. Do not duplicate every backend 5xx into web Sentry.

8. Sentry is disabled by default. Application start/build/runtime must require no Sentry configuration. Reporting is best-effort and non-throwing when later enabled. Application control flow must be identical when Sentry is disabled or unavailable. Do not await event delivery.

9. Do not add source-map upload, SENTRY_AUTH_TOKEN, Replay, tracing, profiling, Logs, user tracking, feedback UI, tunnels or billing-specific telemetry.

10. Add focused mocked tests only for our reporter/sanitization boundary. Prove the default missing-DSN mode performs no initialization/capture. Do not send real Sentry events from tests.

Do not run tests, linters, typechecks, builds, Playwright, checks, formatters or other verification commands. Running npm install is allowed because it is an implementation-required write command.

Do not stage, commit or push.

After implementation report the changed files, dependency/env/config changes, runtime initialization added, reporter metadata/privacy behavior, tests added, and the exact manual verification commands below.
```

## Manual verification

Run:

```bash
npm --workspace @anytoolai/web run test:components -- tests/components/SentryReporting.test.ts
npm run typecheck:web
npm run lint:web
npm run build:web
```

If the focused test has another final filename, substitute only that filename.

No live Sentry configuration is required to complete this step. The required verification is that the app builds/runs with `NEXT_PUBLIC_SENTRY_DSN` absent or empty and mocked tests prove no initialization/capture occurs. A later deployment task may set a non-production DSN and perform a controlled delivery check before enabling production reporting.

## Expected completion

- `@sentry/nextjs` is exact-pinned.
- Web browser/Node/Edge instrumentation is present and remains inactive until `NEXT_PUBLIC_SENTRY_DSN` is configured.
- A narrow non-throwing `ApiContractError` reporter exists for Step 3 and is a no-op while Sentry is disabled.
- Events contain only approved diagnostic metadata and stack information.
- No expected business/API outcomes are blanket-reported.
- No Sentry account/project setup is required for this implementation step.
- Production Docker/Compose can accept the optional DSN later without making it a required deployment variable; the browser value is supplied at image build time.
- Backend Sentry and Step 1 remain untouched.

## Proposed commit

```text
ANY-541 add minimal frontend Sentry reporting
```

---

# Step 3 — Migrate Current Auth Consumers to Generated Wire Contracts

**Status:** `done`  
**Recommended model:** `Sol` — production auth/session consumers and runtime validation are changed here, so preserve behavior carefully.

## Goal

Replace the current handwritten backend wire DTO/decoder authority in the production auth frontend with the generated contracts from Step 1.

Preserve existing application behavior and existing HTTP transport semantics.

## Scope / affected code

Primary production boundary:

```text
apps/web/src/shared/api/auth.ts
```

Direct production consumers that must be considered:

```text
apps/web/src/features/account/AccountClient.tsx
apps/web/src/features/checkout/CheckoutClient.tsx
apps/web/src/features/email-verification/EmailVerificationClient.tsx
apps/web/src/shared/ui/HeaderAccount.tsx
apps/web/src/shared/ui/EmailVerificationPending.tsx
```

Existing password-reset page clients using auth wrappers, where directly affected:

```text
password reset request client
password reset confirmation client
```

Also inspect and follow:

```text
apps/web/AGENTS.md
```

Read only the additional local documentation that this AGENTS file explicitly requires for frontend work. Do not perform unrelated architecture research.

Focused tests:

```text
apps/web/tests/components/AuthDecoders.test.ts
apps/web/tests/components/AuthApiError.test.ts
apps/web/tests/components/AccountClient.test.tsx
apps/web/tests/components/CheckoutClient.test.tsx
apps/web/tests/components/EmailVerificationClient.test.tsx
apps/web/tests/components/HeaderAccount.test.tsx
```

Use actual current filenames if the inherited ANY-538 baseline renamed them.

## Implementation decisions

### 1. Import backend wire contracts from generated output

Use generated runtime schemas and generated inferred types.

Expected schemas include:

```text
zRegisterResponse
zLoginResponse
zSessionResponse
zLogoutResponse
zPasswordResetRequestResponse
zPasswordResetConfirmResponse
zEmailVerificationRequestResponse
zEmailVerificationConfirmResponse
```

and generated request schemas/types as needed.

Do not create handwritten equivalents.

### 2. Preserve local frontend adapter/form types

Keep local frontend concepts where they are not backend DTOs.

`AuthFormSubmitValues` stays in the UI layer.

`SubmitAuthValues` may remain in `shared/api/auth.ts` as an adapter input.

It may contain:

```text
mode
email
password
personalConsent
offerConsent
```

because this is not a backend request DTO; it is a frontend orchestration input that maps to either login or registration.

Map it explicitly into:

```text
LoginRequest
```

or:

```text
RegisterRequest
```

before sending the request.

Do not make `shared/api` import from `shared/ui`.

### 3. Use a generated-type union for submitAuth

If the public wrapper needs a shared result:

```ts
type AuthResponse = RegisterResponse | LoginResponse;
```

Do not manually reproduce fields of these responses.

### 4. Preserve transport helpers

Keep the existing responsibilities of:

```text
resolveApiBase
getJson
postJson
ApiError
ApiContractError
timeout handling
Authorization header
Content-Type
Accept-Language
error-body handling
```

Do not replace fetch transport with generated client code.

### 5. Change successful JSON validation

Transport must continue to treat successful JSON as unknown.

Use the equivalent of:

```ts
const result = schema.safeParse(payload);

if (!result.success) {
  throw new ApiContractError();
}

return result.data;
```

Do not leak `ZodError`.

Do not cast unknown JSON.

When generated validation fails, report the handled contract violation through the Step 2 web reporting boundary **before** propagating the existing `ApiContractError`. Supply only safe metadata:

```text
failure_category = consistency_invariant_violation
operation = api_contract_validation
route = API pathname
contract = generated schema/component name
```

Do not attach the response payload or raw `ZodError`. Sentry reporting failure must not replace, suppress or alter the `ApiContractError`.

### 6. Remove replaced handwritten response validation

After generated validation is in place, remove obsolete local wire authorities such as:

```text
AuthUser
handwritten Register/Login/Session/Logout response DTOs
handwritten password-reset response DTOs
handwritten email-verification response DTOs

isAuthUser
decodeAuthResponse
decodeStatusResponse
decodeRegisterResponse
decodeLoginResponse
decodeAuthSessionResponse
decodeLogoutResponse
manual password-reset response decoders
manual email-verification response decoders
```

Remove only helpers actually replaced by generated runtime validation.

### 7. Add transport-level endpoint wrappers

Keep existing wrappers where they already exist.

Add:

```text
getSession(sessionToken)
logoutSession(sessionToken)
```

so production feature/UI code no longer imports generic transport plus auth-specific response decoders.

The shared auth module should own:

```text
endpoint
request mapping
runtime schema selection
transport invocation
```

Features should consume the domain-specific wrapper.

### 8. Migrate direct consumers explicitly

#### `AccountClient.tsx`

Replace direct:

```text
getJson + decodeAuthSessionResponse
postJson + decodeLogoutResponse
AuthUser
```

with:

```text
getSession()
logoutSession()
SessionUserResponse
```

Preserve existing account behavior and error handling.

#### `CheckoutClient.tsx`

Replace direct:

```text
getJson + decodeAuthSessionResponse
postJson + decodeLogoutResponse
AuthUser
```

with:

```text
getSession()
logoutSession()
SessionUserResponse
```

Preserve current session-loading, authentication, logout, storage and event behavior.

Do not redesign checkout.

#### `HeaderAccount.tsx`

Replace:

```text
getJson + decodeAuthSessionResponse
AuthUser
```

with:

```text
getSession()
SessionUserResponse
```

Preserve:

```text
ApiError
submitAuth()
session-storage behavior
sessionChangedEvent behavior
```

Preserve the final ANY-538 session-race/error semantics exactly:

- only a `401` for the **same bearer token that started the request** may clear the local bearer and dispatch `sessionChangedEvent`;
- if the bearer changed while the request was in flight, ignore both a stale successful response and a stale `401`;
- malformed successful JSON must still become `ApiContractError`, but that contract failure must not clear a previously trusted local bearer;
- `5xx`, network, aborted/transient, and contract-validation failures must not turn the UI into a signed-out state or remove the bearer;
- do not let a stale response populate `sessionUser` for a newer bearer.

Do not redesign header authentication UI.

#### `EmailVerificationClient.tsx`

Replace direct session transport:

```text
getJson + decodeAuthSessionResponse
AuthUser
```

with:

```text
getSession()
SessionUserResponse
```

The final ANY-538 baseline also adds account switching inside this client. Replace its direct:

```text
postJson("/api/auth/logout", ...) + decodeLogoutResponse
```

with:

```text
logoutSession(sessionToken)
```

Preserve the current account-switch behavior exactly:

- logout is attempted against the backend when a bearer token exists;
- backend logout failure must **not** prevent local sign-out;
- the local bearer is still removed in the fallback/finally path;
- `sessionChangedEvent` is still dispatched;
- the verification token remains memory-only and available so the user can sign in with the correct account and continue verification;
- auth/verification error state and loading transitions keep their current behavior.

Preserve the latest pending-token behavior exactly:

- read the fragment token once, keep it memory-only, and remove it from the URL as today;
- do **not** clear the pending fragment token merely because `/session` or `submitAuth()` returns `user.email_verified=true`;
- when a fragment token is still pending, keep the explicit confirmation flow available even for an already-verified session;
- clear the in-memory token only through the existing successful-confirmation lifecycle or other behavior already present in the final ANY-538 code.

Also preserve:

```text
submitAuth()
confirmEmailVerification()
fragment-token lifecycle
current error handling
```

#### `EmailVerificationPending.tsx`

No migration is required if it continues to consume:

```text
requestEmailVerification()
ApiError
apiErrorCode()
```

through the existing public shared API wrapper.

Do not modify it merely because it imports `shared/api/auth`.

#### Password-reset clients

Modify only where necessary because existing wrapper argument/result types now come from generated backend contracts.

Do not redesign their UI/state.

### 9. Preserve stable errors

Do not try to derive a universal generated error type from FastAPI.

Keep:

```text
ApiError.detail: unknown
```

Keep `apiErrorCode()` as a narrow extractor for existing machine-readable codes.

No generic error decoder framework.

### 10. Account for UUID runtime strictness

Generated `SessionUserResponse.user_id` validation is allowed to enforce the backend OpenAPI UUID contract.

Backend already returns valid UUIDs.

Successful frontend test fixtures using placeholders such as:

```text
"user-id"
"registered-user-id"
```

must be changed to valid UUID strings where those payloads are supposed to represent valid backend responses.

Do not weaken generated UUID validation to preserve invalid test fixtures.

### 11. Replace decoder characterization tests

The old `AuthDecoders.test.ts` should no longer validate handwritten decoders after those decoders are removed.

Replace/rename it with focused generated contract-boundary coverage that proves at least:

```text
valid register response succeeds
valid login response succeeds
valid session response succeeds
email_verified is preserved
valid verification/reset status responses succeed
malformed successful JSON becomes ApiContractError
invalid user_id UUID is rejected
missing required response fields are rejected
```

Do not duplicate Hey API/Zod's internal test suite.

Test our transport boundary and current application contract expectations.

## Invariants

- Registration behavior unchanged.
- Login behavior unchanged.
- Session behavior unchanged, including trusted-bearer retention on transient/contract failures and stale-response protection after bearer changes.
- Logout behavior unchanged.
- Password reset unchanged.
- Email verification unchanged, including preservation of a pending memory-only fragment token until its explicit confirmation lifecycle completes.
- `email_verified` remains available everywhere it was available before.
- Bearer/session storage semantics unchanged.
- Locale/Accept-Language behavior unchanged.
- Unknown successful JSON remains untrusted.
- Contract-validation failures are best-effort reported through the Step 2 Sentry boundary without payload/PII.
- Sentry failure never changes auth/session/UI behavior.
- UI state remains local.
- No generated HTTP client is introduced.

## Out of scope

Do not:

- redesign auth UI;
- redesign Checkout;
- redesign HeaderAccount;
- change session storage;
- change bearer authentication;
- migrate legal manifest code;
- add new APIs;
- change password policy;
- modify email verification semantics;
- clean unrelated frontend duplication;
- redesign Sentry/observability established in Step 2;
- report expected ApiError/business outcomes as Sentry exceptions;
- move UI models into generated contracts;
- implement future Portal contracts.

## AI prompt

```text
Implement only Step 3 of ANY-541: migrate current production auth consumers from handwritten backend wire DTOs/decoders to the generated Zod contracts created in Step 1.

Do not perform broad repository research.

Inspect only:
- apps/web/AGENTS.md and the specific local documentation it explicitly requires for frontend work,
- apps/web/src/shared/api/auth.ts,
- the generated API-contract files from Step 1,
- AccountClient.tsx,
- CheckoutClient.tsx,
- HeaderAccount.tsx,
- EmailVerificationPending.tsx,
- the existing email-verification page client,
- the existing password-reset request/confirm clients if their wrapper types are affected,
- directly relevant existing component/API tests.

Follow these settled decisions exactly.

1. Backend wire request/response DTOs come from generated contracts.

2. Keep frontend-local form/adapter types local.

AuthFormSubmitValues remains UI-owned.

SubmitAuthValues may remain in shared/api/auth.ts as an adapter/orchestration input.

Do not make shared/api depend on shared/ui.

3. Map SubmitAuthValues explicitly to generated:
- RegisterRequest, or
- LoginRequest.

4. If submitAuth() needs a shared result type, use:

type AuthResponse = RegisterResponse | LoginResponse;

Do not manually redeclare those response fields.

5. Preserve existing fetch/get/post transport behavior:
- API base resolution,
- timeout behavior,
- bearer Authorization header,
- Content-Type,
- Accept-Language,
- ApiError,
- ApiContractError.

Do not replace transport with a generated client.

6. Successful JSON remains unknown until generated Zod validation succeeds.

Use the equivalent of:

response.json()
→ unknown
→ schema.safeParse()
→ return result.data on success
→ throw ApiContractError on validation failure

Do not use unchecked `as` casts.

Do not expose ZodError to features/UI.

On generated validation failure, use the Step 2 shared observability boundary to report the handled technical invariant with only:
- failure_category=consistency_invariant_violation
- operation=api_contract_validation
- API route pathname
- contract/schema name

Do not send the response payload or raw ZodError to Sentry. If reporting fails or Sentry is disabled, still throw the same ApiContractError and preserve identical application behavior.

Do not report normal ApiError/business outcomes merely because the response is non-2xx.

7. Add endpoint-level wrappers:

getSession(sessionToken)
logoutSession(sessionToken)

Keep and update existing wrappers:
- submitAuth,
- requestEmailVerification,
- confirmEmailVerification,
- requestPasswordReset,
- confirmPasswordReset.

8. Remove replaced handwritten wire DTO/decoder authority from auth.ts, including obsolete AuthUser/manual response DTOs and manual response decoders after generated validation fully replaces them.

Retain transport/error helpers that still have a real responsibility.

9. Migrate these direct consumers:

AccountClient.tsx:
- use getSession()
- use logoutSession()
- use generated SessionUserResponse
- preserve existing behavior.

CheckoutClient.tsx:
- use getSession()
- use logoutSession()
- use generated SessionUserResponse
- preserve session-load/auth/logout/storage/event behavior.
- do not redesign checkout.

HeaderAccount.tsx:
- use getSession()
- use generated SessionUserResponse
- preserve ApiError, submitAuth, storage, and session event behavior.
- preserve the final ANY-538 request-race semantics: compare the bearer that started the request with the bearer currently in localStorage before applying either success or 401 results.
- a stale success for token A must not populate session state after token B has replaced it.
- a stale 401 for token A must not remove token B or dispatch sessionChangedEvent.
- only a 401 for the still-current bearer may clear it and switch to signed-out state.
- malformed successful JSON must still become ApiContractError, but must retain the trusted bearer just like current contract-validation failure behavior.
- 5xx/network/aborted/transient failures must retain the bearer and must not falsely show the signed-out UI.
- do not redesign header auth UI.

EmailVerificationClient.tsx:
- replace getJson + decodeAuthSessionResponse + AuthUser with getSession() + generated SessionUserResponse.
- replace the new switchAccount() direct postJson(...logout...) + decodeLogoutResponse path with logoutSession(sessionToken).
- preserve the current fallback semantics: backend logout failure must not prevent removal of the local bearer or dispatch of sessionChangedEvent.
- preserve the in-memory verification token across account switching so the user can sign in with the correct account and continue verification.
- preserve the latest ANY-538 pending-token behavior: if a fragment token exists, do not discard it merely because session/user data reports email_verified=true; keep the explicit confirmation flow available until the existing confirmation lifecycle clears the token.
- preserve submitAuth(), confirmEmailVerification(), fragment removal, token lifecycle, loading/error transitions and current UI behavior.

EmailVerificationPending.tsx:
- do not change it if requestEmailVerification(), ApiError and apiErrorCode remain its only API dependencies.

Password-reset clients:
- modify only if generated wrapper request/result types require local typing changes.
- do not redesign UI/state.

10. Preserve current error behavior.

Do not treat generated OpenAPI/Zod request schemas as the authority for the new-password business policy. In the final ANY-538 baseline, RegisterRequest.password and PasswordResetConfirmRequest.password are intentionally plain strings at the transport-contract level; backend business validation remains authoritative for the 12–128/composition policy. Do not restore Pydantic min/max fields or recreate that policy in the generated contract layer.

Keep ApiError.detail as unknown.

Keep apiErrorCode() as the narrow extractor for stable machine codes used by current UI.

Do not design a generic generated error framework.

11. Generated UUID runtime validation is authoritative.

If successful test fixtures use placeholder user IDs like "user-id" or "registered-user-id", replace them with valid UUID strings.

Do not weaken UUID validation.

12. Replace the old handwritten-decoder characterization test with focused generated contract-boundary tests covering valid and malformed auth/session/reset/verification responses and ApiContractError behavior.

13. Preserve and adapt the focused ANY-538 regression coverage in EmailVerificationClient.test.tsx and HeaderAccount.test.tsx. The generated-contract migration must still prove:
- pending fragment token survives when session data says email_verified=true and remains explicitly confirmable;
- backend logout failure during account switching cannot destroy the local sign-out fallback or pending token;
- HeaderAccount clears a bearer only on a matching-current-token 401;
- malformed success, 5xx, and network/transient failures retain the trusted bearer;
- stale success/401 responses for an older bearer cannot overwrite or clear a newer bearer.

Where these successful-response fixtures still use placeholder user IDs, replace them with valid UUID strings because generated SessionUserResponse enforces the OpenAPI UUID format.

Do not modify unrelated tests.

If the inherited ANY-538/current repository code materially contradicts these known consumer relationships or backend contracts, stop and report the contradiction rather than redesigning the architecture.

Do not run tests, linters, formatters, type checks, builds, generation checks, or other automated verification commands.

Do not stage, commit, or push.

After implementation report:
- files changed,
- handwritten wire types/decoders removed,
- generated schemas/types now used,
- endpoint wrappers added/updated,
- production consumers migrated,
- invalid UUID fixtures corrected,
- tests added/updated,
- ApiContractError reporting integration added without payload/PII,
- exact manual verification commands below.
```

## Manual verification

Run:

```bash
npm --workspace @anytoolai/web run test:components -- \
  tests/components/AuthContractValidation.test.ts \
  tests/components/AuthApiError.test.ts \
  tests/components/AccountClient.test.tsx \
  tests/components/CheckoutClient.test.tsx \
  tests/components/EmailVerificationClient.test.tsx \
  tests/components/HeaderAccount.test.tsx
```

If the renamed contract-validation test has a different final filename, substitute that filename only.

Then:

```bash
npm run typecheck:web
npm run lint:web
npm run generate:check
```

## Expected completion

- Current production auth/session/reset/verification responses use generated runtime validation.
- Handwritten duplicate backend wire DTOs are removed.
- Current production consumers no longer combine generic transport with manual auth response decoders.
- Runtime malformed-success handling remains `ApiContractError`.
- Existing auth/session behavior remains unchanged, including stale bearer-response protection and trusted-bearer retention on transient/contract failures.
- Existing email-verification behavior remains unchanged, including preservation of a pending memory-only fragment token until explicit confirmation/account-switch flow completes.
- UI/form state remains frontend-owned.

## Proposed commit

```text
ANY-541 migrate auth API to generated contracts
```

---

# Step 4 — Enforce the Boundary and Publish the Durable 4F Handoff

**Status:** `done`  
**Recommended model:** `Luna` — the architecture is already settled; this step adds a focused guard and documents the completed boundary without changing production behavior.

## Goal

Finish ANY-541 by doing two tightly related tasks in one implementation chat:

1. add the minimum repository guard needed to prevent the migrated auth boundary from returning to handwritten frontend wire contracts;
2. document the final contract authority chain and the rule that Step 4F must follow for future Portal-owned APIs.

This step must not change production API or UI behavior.

## Scope / affected code

Focused boundary test:

```text
apps/web/tests/eslint-boundaries.test.mjs
```

Canonical documentation, only where the current files actually own these rules:

```text
ARCHITECTURE.md
docs/engineering/CODING_CONVENTIONS.md
apps/api/AGENTS.md
apps/web/AGENTS.md
```

Inspect only directly related boundary-test helpers and these canonical documentation files.

Do not create a competing architecture document.

## Implementation decisions

### 1. Keep generated-file freshness enforcement in repository generation

Do not duplicate:

```text
generate:check
```

inside the web boundary suite.

Freshness remains owned by `scripts/repo.py` and the generation flow established in Step 1.

### 2. Add only a focused migrated-surface guard

Protect:

```text
apps/web/src/shared/api/auth.ts
```

The guard must verify that the migrated auth boundary consumes the generated API-contract module produced by Step 1.

### 3. Prevent known migrated backend DTOs from being re-declared locally

Reject local declarations in `auth.ts` of migrated backend wire DTO names such as:

```text
RegisterRequest
RegisterResponse
LoginRequest
LoginResponse
SessionResponse
SessionUserResponse
LogoutResponse
PasswordResetRequest
PasswordResetRequestResponse
PasswordResetConfirmRequest
PasswordResetConfirmResponse
EmailVerificationRequest
EmailVerificationRequestResponse
EmailVerificationConfirmRequest
EmailVerificationConfirmResponse
```

Imports of these names from generated code must remain allowed.

Use the simplest reliable mechanism compatible with the current boundary-test suite.

If syntax-aware inspection is needed, use TypeScript tooling already installed in the repository. Do not add another parser dependency.

### 4. Guard removed handwritten response decoders

Reject reintroduction of known removed helpers such as:

```text
isAuthUser
decodeAuthResponse
decodeStatusResponse
decodeRegisterResponse
decodeLoginResponse
decodeAuthSessionResponse
decodeLogoutResponse
```

plus the removed password-reset and email-verification response decoders.

Do not attempt to ban every function whose name begins with `decode`.

### 5. Preserve legitimate frontend-local adapter types

The guard must continue to allow:

```text
AuthResponse = RegisterResponse | LoginResponse
SubmitAuthValues
ApiError
ApiContractError
other frontend-only form/view/adapter types
```

because these are not parallel backend wire DTO declarations.

### 6. Document the final authority chain

Record the completed architecture as:

```text
FastAPI/Pydantic
→ app.openapi()
→ docs/generated/openapi.json
→ apps/web/src/generated/api-contracts/
→ generated Zod runtime validation + inferred wire types
→ shared API transport
→ feature/UI adapters and view state
```

### 7. Document ownership clearly

Backend owns:

```text
API wire request/response contracts
OpenAPI schema
```

Repository generation owns:

```text
generated frontend runtime contracts/types
freshness checking
```

Frontend owns:

```text
HTTP transport
form state
view models
presentation state
derived UI types
endpoint orchestration adapters
```

Frontend must not independently re-author backend DTO fields.

### 8. Document shared cross-language values separately from HTTP API contracts

Clarify that ANY-541 applies to values that cross the backend/frontend HTTP boundary.

Do not imply that every value used by both Python and TypeScript must move into OpenAPI.

Existing examples that correctly keep their own authority/generation path include:

```text
route locales and locale mappings → config/locales.json → generated Python/TypeScript
legal acceptance text → legal source → generated frontend artifact
other repository-owned shared constants that do not cross the API boundary
```

If a status/enum is part of an API request or response, it belongs to the Pydantic/OpenAPI-generated contract.

If it is shared across backend/frontend but does not cross HTTP, it may retain a separate canonical source and generation mechanism.

If it exists only in frontend UI/view state, it remains frontend-owned.

### 9. Document canonical commands and generated location

Record:

```bash
npm run generate
npm run generate:check
```

and:

```text
apps/web/src/generated/api-contracts/
```

### 10. Document the migrated current API surface

Record that ANY-541 migrated current production:

```text
registration
login
session
logout
password reset
email verification
email_verified session/user fact
```

Account uses auth session/logout contracts.

No currently consumed legal endpoint DTO required migration because the current legal frontend does not maintain a parallel handwritten backend API wire DTO consumer.

### 11. Document the error boundary

Record that:

```text
successful response JSON
→ generated runtime validation
```

while current application errors remain intentionally narrower:

```text
ApiError.detail = unknown
apiErrorCode() extracts only stable machine codes used by current UI
```

ANY-541 does not create a universal generated error model.

Also document the minimal web observability rule established before migration:

```text
when DSN is enabled: standard uncaught web/server/request failures → payment-portal-web Sentry
handled ApiContractError → optional sanitized reporter → same application error flow regardless of Sentry state
expected ApiError/business outcomes → not blanket-reported as exceptions
```

Document that backend and web use separate Sentry projects/DSNs in the same organization and share only a small diagnostic vocabulary (`service`, `failure_category`, `operation`). No payloads, tokens, user identity, query/fragment data or raw validation data are allowed into Sentry.

### 12. Document the future 4F rule

For every future **Portal-owned, web-consumed API**:

```text
1. define request/response with backend Pydantic models;
2. ensure durable named OpenAPI components exist;
3. run repository generation;
4. consume generated Zod schema/type from the frontend shared API boundary;
5. validate successful JSON at runtime before trusting it;
6. keep UI/form/view state local instead of putting it into API DTOs.
```

Do not start with a handwritten TypeScript wire interface and later copy it into Python.

### 13. Preserve ANY-504 domain ownership

Generated contracts solve contract authority, not domain-data ownership.

4F must not create Portal-owned mirrors for:

```text
External Billing commercial catalog/pricing/sellability truth
paid-access authority owned by later ANY-504 steps
Platform Kernel actual usage / remaining quota
```

### 14. Document STOP conditions

Future implementation must stop before inventing a frontend wire contract when:

```text
required backend API does not exist
OpenAPI response is unnamed/unsuitable for durable consumption
generated schema cannot faithfully represent backend wire semantics
frontend would need to redefine backend wire meaning
required data belongs to External Billing or Platform Kernel
a transport/auth redesign would be required rather than a new contract
```

Those cases require the owning architecture/API decision first.

## Invariants

- Stale generated output remains enforced by `generate:check`.
- Migrated backend wire DTO authority remains generated.
- The boundary guard stays local and understandable.
- Existing canonical architecture docs remain canonical.
- Shared non-HTTP constants are not incorrectly forced into OpenAPI.
- 4F does not need to repeat ANY-541 contract-authority research.
- Generated contracts do not change domain-data ownership.
- No production behavior changes in this step.
- The completed handoff records the web Sentry reporting/privacy boundary without turning it into a generic error platform.

## Out of scope

Do not:

- inspect every TypeScript file for DTOs;
- build repository-wide DTO naming heuristics;
- create a new ESLint plugin;
- duplicate OpenAPI/generation freshness checks;
- implement ANY-539 UI;
- design missing Portal APIs;
- create billing APIs;
- create usage/quota APIs;
- modify auth behavior;
- redesign frontend state architecture;
- move locales/legal/shared non-HTTP constants into OpenAPI;
- create a new broad ADR unless current canonical documentation explicitly requires one;
- add implementation code unrelated to the guard/handoff.

## AI prompt

```text
Implement only Step 4 of ANY-541: enforce the completed generated API-contract boundary and publish the durable 4F handoff.

This is the final implementation step. Do not perform broad repository or architecture research.

Inspect only:
- apps/web/tests/eslint-boundaries.test.mjs,
- apps/web/src/shared/api/auth.ts,
- directly related existing boundary-test helpers,
- ARCHITECTURE.md,
- docs/engineering/CODING_CONVENTIONS.md,
- apps/api/AGENTS.md,
- apps/web/AGENTS.md.

Update only canonical documentation files whose current statements need the completed ANY-541 boundary.

Part A — focused boundary guard

1. Do not duplicate generate:check or generated-file freshness logic. That remains owned by scripts/repo.py.

2. Add a focused guard for apps/web/src/shared/api/auth.ts.

Confirm that auth.ts consumes the generated API-contract module produced in Step 1.

3. Prevent local re-declaration of these migrated backend wire DTOs in auth.ts:
- RegisterRequest
- RegisterResponse
- LoginRequest
- LoginResponse
- SessionResponse
- SessionUserResponse
- LogoutResponse
- PasswordResetRequest
- PasswordResetRequestResponse
- PasswordResetConfirmRequest
- PasswordResetConfirmResponse
- EmailVerificationRequest
- EmailVerificationRequestResponse
- EmailVerificationConfirmRequest
- EmailVerificationConfirmResponse

Imported generated types with these names must remain allowed.

Use the simplest reliable approach that fits the current boundary-test suite.
If syntax-aware inspection is needed, use the TypeScript tooling already installed in the repository. Do not add a parser dependency.

4. Prevent known replaced manual auth/session/status/password-reset/email-verification response decoders from being reintroduced.

Do not implement a generic "no decode functions" rule.

5. Continue to allow legitimate frontend adapter/local types, including:
- AuthResponse = RegisterResponse | LoginResponse
- SubmitAuthValues
- ApiError
- ApiContractError
- frontend-only form/view/adapter types.

6. Do not add a new ESLint plugin or repository-wide DTO detector.

Part B — durable documentation/handoff

7. Document this completed authority chain:

FastAPI/Pydantic
→ app.openapi()
→ docs/generated/openapi.json
→ apps/web/src/generated/api-contracts/
→ generated Zod runtime validation + inferred wire types
→ shared API transport
→ frontend adapters/forms/view state

8. Document ownership:

Backend:
- owns HTTP API wire request/response contracts and OpenAPI schema.

Repository generation:
- owns generated frontend runtime contracts/types and freshness checking.

Frontend:
- owns HTTP transport, form state, UI/view models, presentation state and derived adapter types.
- must not independently redeclare backend wire DTO fields.

9. Explicitly document that ANY-541 covers HTTP API contracts only.

Do not imply that every value shared by Python and TypeScript must come through OpenAPI.

Examples of valid separate authority paths:
- route locales / locale mappings from config/locales.json into generated Python and TypeScript;
- legal acceptance text from the legal source into its generated frontend artifact;
- other shared non-HTTP constants with their own canonical generation path.

Rule:
- if a status/enum/value crosses the HTTP API boundary, it belongs to the backend Pydantic/OpenAPI-generated contract;
- if it is shared across backend/frontend but does not cross HTTP, it may keep a separate canonical source/generation path;
- if it exists only in frontend UI/view state, it remains frontend-owned.

10. Document canonical commands:
- npm run generate
- npm run generate:check

Document generated location:
- apps/web/src/generated/api-contracts/

11. Document the migrated current production API surface:
- registration,
- login,
- session,
- logout,
- password reset,
- email verification,
- email_verified.

Document that account uses auth session/logout contracts.

Document that no current legal API DTO migration was required because the current legal frontend does not maintain a parallel handwritten backend API wire DTO consumer.

12. Document the error rule:
- successful JSON uses generated runtime validation;
- ApiError.detail remains unknown;
- apiErrorCode() extracts only stable machine codes used by current UI;
- ANY-541 does not create a universal generated error platform.

13. Document the rule for each future Portal-owned web-consumed API:

1. define backend Pydantic request/response models;
2. expose durable named OpenAPI components;
3. run repository generation;
4. consume generated schema/type in the frontend API boundary;
5. runtime-validate successful JSON;
6. keep form/UI/view state local.

14. Document that generated contracts do not change domain ownership.

4F must not mirror/re-author:
- External Billing commercial/pricing/sellability truth,
- future paid-access authority,
- Platform Kernel usage/quota truth.

15. Document STOP conditions for:
- missing backend API,
- unsuitable/unnamed OpenAPI schema,
- generator inability to represent backend semantics faithfully,
- frontend needing to redefine wire meaning,
- data owned by External Billing or Platform Kernel,
- required transport/auth redesign.

Do not create a competing architecture document.
Do not implement future APIs or ANY-539 UI.
Do not change production behavior.

If the current boundary-test or canonical-documentation structure materially contradicts this plan, stop and report the contradiction instead of inventing a new framework or document hierarchy.

Do not run tests, linters, formatters, type checks, builds, generation checks, documentation checks, or other automated verification commands.

Do not stage, commit, or push.

After implementation report:
- files changed,
- exact generated-boundary rules added,
- what re-declarations/decoders are blocked,
- what legitimate frontend-local types remain allowed,
- documentation files changed,
- final authority chain documented,
- HTTP vs non-HTTP shared-value rule documented,
- future 4F rule documented,
- STOP conditions documented,
- exact manual verification commands below.
```

## Manual verification

Run the focused boundary and generation checks first:

```bash
npm run test:boundaries:web
npm run generate:check
npm run lint:web
npm run typecheck:web
```

Then final repository/frontend verification:

```bash
npm run check:fast
npm run build:web
```

Focused E2E verification:

```bash
npm run test:e2e -- \
  apps/web/e2e/email-verification.spec.ts \
  apps/web/e2e/password-reset.spec.ts \
  apps/web/e2e/account-logout.spec.ts
```

Documentation/architecture checks:

```bash
npm run docs:check
npm run architecture:check
```

Run the full repository check if required by normal PR/CI policy:

```bash
npm run check
```

A separate PostgreSQL-heavy verification pass is not required solely by ANY-541 because this ticket changes no persistence or backend transactional behavior.

## Expected completion

- Generated auth contract imports are explicitly protected.
- Known replaced wire DTO declarations and response decoders cannot quietly return.
- No generic DTO analyzer or new ESLint subsystem has been introduced.
- Contract authority is documented once in existing canonical documentation.
- HTTP API contracts are clearly distinguished from shared non-HTTP constants and frontend-only state.
- Generated artifact ownership and commands are documented.
- Current migrated API scope is recorded.
- Error handling boundary is explicit.
- 4F has a deterministic rule for adding Portal-owned APIs.
- External Billing / paid access / Platform Kernel ownership remains intact.
- No production behavior or future API has been added.

## Proposed commit

```text
ANY-541 enforce and document generated API contract boundary
```

---

# Final Acceptance Validation

After all four steps, ANY-541 must satisfy the following.

| Requirement | Expected result |
|---|---|
| Backend contract authority | FastAPI/Pydantic remains authoritative |
| Canonical OpenAPI | Generated from current backend app |
| Frontend wire contracts | Generated from OpenAPI |
| Runtime validation | Generated Zod schemas |
| TypeScript wire types | Inferred from generated schemas |
| Generated SDK | Not introduced |
| HTTP transport | Existing frontend transport retained |
| Registration | Migrated |
| Login | Migrated |
| Session | Migrated |
| Logout | Migrated |
| Password reset | Migrated |
| Email verification | Migrated |
| `email_verified` | Generated contract fact |
| Account | Uses generated auth session/logout boundary |
| Legal API | No speculative migration |
| UI/form/view models | Remain frontend-owned |
| Success JSON | Remains untrusted until runtime validation |
| Malformed success | `ApiContractError` |
| Contract failure observability | `ApiContractError` calls the sanitized optional reporter before propagation; no-op without DSN, Sentry delivery when enabled |
| Standard uncaught web/server/request runtime errors | Captured by configured Next.js Sentry hooks when DSN is enabled; no Sentry initialization without DSN and no custom React global error boundary |
| Sentry privacy | No API payloads, tokens, user identity, query/fragment data, headers/cookies or raw Zod data |
| Expected business/API errors | Not blanket-reported as exceptions |
| Error payloads | No generic redesign; `detail` remains unknown |
| Bearer auth | Behavior unchanged |
| Generated freshness | Enforced through repository generation/check |
| Duplicate handwritten DTO authority | Removed for migrated surface |
| Boundary protection | Focused guard only |
| ANY-539 / 4F UI | Not implemented |
| Billing/LBX/provider APIs | Not implemented |
| Usage/quota contracts | Not implemented |
| Domain data ownership | Unchanged |

---

# Definition of Done

ANY-541 is complete when:

- all four implementation steps are completed sequentially;
- every step has been manually verified before its commit;
- `FastAPI/Pydantic → OpenAPI → generated Zod/types → frontend consumer` is the actual production path;
- migrated production frontend code contains no parallel handwritten backend wire DTO authority;
- successful JSON still requires runtime validation;
- invalid generated-contract payloads call the safe optional web reporter and still fail as `ApiContractError`; without DSN reporting is a no-op, and when enabled it sends the sanitized event to web Sentry;
- Sentry/reporting failure cannot change application control flow;
- expected `ApiError`/business outcomes are not blanket-reported as exceptions;
- generation is deterministic and `generate:check` detects stale, missing and obsolete contract output;
- registration/login/session/logout/password-reset/email-verification behavior remains unchanged;
- direct consumers including Account, Checkout and Header use the new boundary;
- frontend form/UI/view-state types remain local;
- no generated HTTP SDK has been introduced;
- no speculative 4F API or UI work has been added;
- no billing/provider/usage ownership has moved into Portal;
- the durable handoff documents exactly how 4F adds future Portal-owned web APIs.

## Implementation readiness

Recommended execution model by chat:

```text
Step 1 → DONE / Sol
Step 2 → Sol
Step 3 → Sol
Step 4 → Luna
```

Step 1 is already complete and must not be reopened by later implementation chats. No additional broad research is required before Step 2.

Execution models should inspect only the files explicitly listed in each step plus immediately adjacent implementation code required to understand those files.

The material predecessor requirement is that implementation inherits from the current final ANY-538 code baseline. ANY-538 is already implementation-complete for sequencing purposes, so formal PR merge is not required before starting ANY-541. If ANY-538 is not yet on `main`, start from its current head/inherited branch state and later rebase/update onto the merged result.

If that inherited baseline materially contradicts the locked assumptions about:

```text
auth Pydantic request/response contracts
shared/api/auth.ts
repository generation flow
```

the execution model must stop and report the contradiction rather than silently redesigning ANY-541.
