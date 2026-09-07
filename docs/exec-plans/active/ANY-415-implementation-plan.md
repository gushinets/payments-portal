# ANY-415 — Establish transport-neutral Error Architecture

## Plan Overview

| Field | Value |
| --- | --- |
| Feature | `ANY-407` |
| Ticket | `ANY-415` |
| Overall status | `todo` |
| Execution order | Sequential only: Step 1 → verification → commit → Step 2 → … → Step 5 |
| Steps / commits | 5 |
| Prerequisite | **Hard execution gate:** final accepted/merged result of `ANY-411` / PR #78. This plan may be reviewed/approved before merge, but Step 1 must not start before that gate is satisfied. |
| Database migration | Not required |
| Public API policy | Preserve existing HTTP statuses and machine-readable codes; migrate only the explicitly touched response shapes to structured `detail.code` |
| Provider policy | Preserve retry/idempotency/UNKNOWN/ambiguous outcome/redaction semantics from ANY-165/169 |

## How to Use This Plan

Execute exactly one step at a time.

After every step:

1. review the diff;
2. run only the listed manual verification;
3. fix problems before continuing;
4. create the proposed commit yourself;
5. only then start the next step.

Execution-model must not repeat the repository-wide research captured by this plan.

If the final merged ANY-411 materially changes the locked layer responsibilities below, stop before Step 1 and reconcile this plan with the accepted architecture instead of silently adapting it.

Before executing Step 1, verify only that PR #78 is final/accepted and that its merged architecture authority does not materially contradict the locked decisions in this plan. Do **not** repeat the repository-wide ANY-415 research merely because the prerequisite was merged after this plan was approved.

---

## Context and Locked Decisions

### Current state

The repository already has:

- neutral `AppError` carrying:
  - `code`;
  - `message_safe`;
  - `details_safe`;
- payment/provider errors with established retry disposition and safe diagnostics;
- exception chaining around provider transport/decoding failures;
- redaction and provider-operation telemetry;
- provider-neutral `UNKNOWN`/ambiguous-outcome semantics;
- domain-owned `SubscriptionLifecycleError`;
- domain-owned `LegalAcceptanceError`;
- mixed legacy HTTP error bodies:
  - `detail: "code"`;
  - `detail: {"code": "code"}`;
- frontend `ApiError` with typed `status` and `detail`, but auth/password-reset UX still parses `Error.message`.

### Target ownership

```text
Core
  AppError only
       |
       v
Application / Domain
  feature-owned transport-neutral errors
       |
       v
Integrations / Provider boundary
  normalized integration/provider errors
       |
       v
Presentation
  HTTP status + response body mapping
       |
       v
Frontend
  ApiError.status + structured detail.code
```

The arrows above describe propagation, not dependency direction.

### Locked decisions

1. `AppError` remains the small shared neutral base.
2. Feature-specific payment errors do not belong in `Core`.
3. Payment errors move to the current provider boundary without changing their runtime semantics.
4. HTTP status codes are not stored on Application/Domain exceptions.
5. FastAPI types must not appear in the service/application modules migrated by this ticket.
6. Presentation owns mapping from an internal error to:
   - HTTP status;
   - `detail.code`;
   - explicitly allowlisted public detail fields.
7. `details_safe` means safe diagnostic metadata; it must **not** automatically be serialized to clients.
8. No global error-code registry is introduced.
9. No class-per-error-code hierarchy is introduced.
10. Existing `SubscriptionLifecycleError` and `LegalAcceptanceError` remain unchanged because they are already transport-neutral and have no current need for forced migration to `AppError`.
11. Existing provider retryability, idempotency, redaction, exception chaining and unresolved/ambiguous-result semantics remain mechanically unchanged.
12. Existing HTTP statuses and machine-readable codes remain the same in the reviewed API slice.
13. The reviewed API slice migrates from legacy string detail to:
   ```json
   {
     "detail": {
       "code": "stable_error_code"
     }
   }
   ```
14. `missing_required_documents` retains its current additional `documents` payload.
15. Standard FastAPI/Pydantic validation errors such as HTTP 422 are not replaced by a custom framework.
16. Provider-specific CloudPayments checkout-configuration error compatibility is not redesigned in this ticket merely to achieve aesthetic uniformity.
17. An unexpected server failure is exposed only as a generic structured 500 response and is logged at the HTTP system boundary without request bodies, headers, query values, exception messages, provider payloads, secrets or card/token values.
18. Sentry/new monitoring/alerting belongs to later observability work, not ANY-415.

## Explicitly Out of Scope

- Persistence extraction or repository-pattern work.
- SQLAlchemy transaction redesign.
- Database schema/migrations.
- External billing implementation.
- LBX/Dodo design.
- Removal of CloudPayments.
- Reworking payment retry rules.
- Reworking idempotency.
- Reworking reconciliation or `UNKNOWN`/ambiguous outcomes.
- Global conversion of every `HTTPException` in the repository.
- Physical reorganization of all routers/services/packages.
- Converting every existing domain exception into `AppError`.
- Global error-code catalog.
- Error localization framework.
- Sentry or new telemetry infrastructure.
- ANY-408 cleanup items.
- Opportunistic auth, checkout, billing or password-reset refactoring.

---

# Step 1 — Move payment error ownership out of Core

**Status:** `done`

## Goal

Remove the current inward dependency from shared `Core` to the payment-provider boundary while preserving the existing payment failure contract exactly.

After this step:

- `app.core.errors` owns only the neutral `AppError`;
- payment/provider failure types are owned by `app.payment_providers`;
- all existing payment error codes, retry dispositions and diagnostics behave exactly as before;
- architecture checks prevent payment-specific errors from drifting back into Core.

## Scope / affected code

Primary files:

- `apps/api/app/core/errors/base.py`
- `apps/api/app/core/errors/__init__.py`
- `apps/api/app/core/errors/payments.py`
- new `apps/api/app/payment_providers/errors.py`
- `apps/api/app/payment_providers/api_client.py`
- directly affected `apps/api/app/integrations/cloudpayments/**` imports
- directly affected identity/router imports
- directly affected payment/provider tests
- `scripts/repo.py`
- `apps/api/tests/test_architecture.py`

Known consumers include at least:

- payment API client;
- CloudPayments API client;
- CloudPayments adapter;
- CloudPayments operation metadata;
- transaction lookup/reconciliation;
- checkout route handling of `PaymentProviderConfigurationError`.

## Implementation decisions

Move the existing payment-specific exception hierarchy from:

```text
app.core.errors.payments
```

to:

```text
app.payment_providers.errors
```

The moved classes retain their current names and public Python behavior, including:

- `PaymentsError`;
- `PaymentProviderConfigurationError`;
- `PaymentsTransportError`;
- `PaymentsTimeoutError`;
- `PaymentsIdempotencyKeyRequiredError`;
- `PaymentsAuthenticationError`;
- `PaymentsRateLimitError`;
- `PaymentsUpstreamError`;
- `PaymentsHttpError`;
- `PaymentsResponseDecodeError`;
- `PaymentsResponseValidationError`;
- `PaymentsOperationDeclinedError`.

`RetryDisposition` remains owned by `app.payment_providers.contracts`.

`app.payment_providers.errors` may depend on that sibling contract.

`app.core.errors` must export only `AppError` after the migration.

Do not keep a compatibility re-export of payment errors from `app.core.errors`: this would preserve the feature-specific Core ownership that this step is explicitly removing.

Delete `apps/api/app/core/errors/payments.py` after all internal references have been migrated.

Update imports mechanically. Do not change:

- constructors;
- class inheritance except for module ownership;
- `.code`;
- `.message_safe`;
- `.details_safe`;
- `.retry_disposition`;
- `.status_code`;
- error code strings;
- retry classification;
- exception chaining;
- logging/redaction behavior.

Extend the existing Core dependency architecture rule so modules under `app.core` may not import:

- `app.domains`;
- `app.integrations`;
- `app.payment_providers`.

Keep the guard directional. Do not add a general-purpose dependency framework.

Add a focused `test_architecture.py` case proving that a Core → `app.payment_providers` import is rejected.

## Invariants

The following must remain unchanged:

- retryable vs non-retryable decisions;
- mutation idempotency-key requirements;
- retry attempt behavior;
- timeout classification;
- transport-error classification;
- HTTP/provider failure classification;
- operation-declined semantics;
- exception `raise ... from ...` chaining;
- telemetry-safe metadata;
- secret/card/token redaction;
- transaction lookup returning normalized `UNKNOWN` where it does today;
- no CloudPayments-specific vocabulary enters billing Domain/Application.

## Out of scope

Do not:

- rename error codes;
- redesign `RetryDisposition`;
- redesign `ProviderFailure`;
- introduce new payment error types;
- alter CloudPayments calls;
- change retries/timeouts;
- change reconciliation;
- change API responses;
- create an integration-wide generic error framework;
- move other payment-provider modules.

## AI prompt

```text
Implement only Step 1 of ANY-415: move payment-specific error ownership out of shared Core and into the existing payment-provider boundary.

The architecture and implementation decisions for this step are already defined. Follow them exactly.

Required result:

1. Keep `app.core.errors.base.AppError` unchanged as the neutral shared base.
2. Move the existing payment-specific exception hierarchy from `app.core.errors.payments` to a new `app.payment_providers.errors` module.
3. Preserve the existing class names, inheritance from AppError, constructors, attributes, error codes, retry disposition behavior, safe diagnostic metadata, status-code metadata on PaymentsHttpError, and exception semantics exactly.
4. `RetryDisposition` remains owned by `app.payment_providers.contracts`; the new sibling error module may import it.
5. Update every directly affected internal import to use `app.payment_providers.errors`.
6. After migration, `app.core.errors.__init__` must expose only AppError and must not re-export payment-specific exceptions.
7. Remove the obsolete `app/core/errors/payments.py` once there are no internal references to it.
8. Extend the existing `check_python_boundaries()` Core dependency rule in `scripts/repo.py` so Core cannot import `app.payment_providers` in addition to the already-forbidden domain/integration directions.
9. Add a focused architecture test proving that Core -> payment_providers imports are rejected.

Preserve without modification:
- payment retryability;
- mutation idempotency requirements;
- timeout/transport classification;
- retry attempt behavior;
- provider failure normalization;
- UNKNOWN/reconciliation behavior;
- exception chaining;
- telemetry/redaction behavior;
- every existing machine-readable error code.

Do not change HTTP response contracts in this step.

Do not introduce compatibility re-exports from app.core.errors. They would preserve the incorrect ownership this step removes.

Implement only this step.
Do not perform broad repository research.
Inspect only the directly relevant current files and import consumers needed to verify that the plan assumptions still match the code after previous work.
Do not redesign the architecture.
Do not introduce a new error framework or abstraction.
Do not perform unrelated refactoring.
Do not work on future ANY-415 steps.
Do not run tests, linters, formatters, type checkers, generators, architecture commands, or any other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed/deleted/created file;
- briefly summarize the ownership move and guard change;
- explicitly confirm that payment error semantics were not changed;
- report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, especially because the accepted ANY-411 result changed the dependency model, stop and describe the contradiction instead of inventing a new solution.
```

## Manual verification

Run from repository root:

```bash
pytest apps/api/tests/test_payments_api_client.py apps/api/tests/test_cloudpayments_adapter_api.py apps/api/tests/test_architecture.py
pytest apps/api/tests/test_api.py -k "checkout"
npm run architecture:check
rg "app\.core\.errors\.payments|from app\.core\.errors import .*Payments|from app\.core\.errors import .*PaymentProvider" apps/api
```

The final `rg` command must produce no matches.

## Expected completion

Step 1 is complete when:

- no payment-specific exception lives in `app.core.errors`;
- payment clients/integrations use `app.payment_providers.errors`;
- no legacy `app.core.errors.payments` or payment-error re-export imports remain under `apps/api`;
- Core cannot import `payment_providers` without failing architecture checks;
- payment behavior tests pass unchanged except for import-location adjustments.

## Proposed commit

`refactor(errors): move payment errors to provider boundary`

---

# Step 2 — Establish central AppError HTTP mapping for checkout

**Status:** `done`

## Goal

Create the first real transport-neutral Application → Presentation error path:

```text
checkout application/service
    -> CheckoutError
    -> central FastAPI AppError handler
    -> HTTP status + structured detail.code
```

The checkout service must no longer depend on FastAPI.

## Scope / affected code

Primary files:

- new `apps/api/app/domains/identity/errors.py`
- `apps/api/app/domains/identity/services/checkout.py`
- `apps/api/app/domains/identity/router.py`
- new `apps/api/app/http_errors.py`
- `apps/api/app/main.py`
- `scripts/repo.py`
- `apps/api/tests/test_architecture.py`
- `apps/api/tests/test_api.py`
- new focused `apps/api/tests/test_error_handling.py`

## Implementation decisions

Add a feature-owned transport-neutral exception:

```python
class CheckoutError(AppError):
    ...
```

Do not create one class per checkout code.

`CheckoutError` carries existing stable codes through normal `AppError` fields.

Migrate application/business checkout errors to `CheckoutError`.

The reviewed checkout codes are:

| Code | HTTP status |
| --- | ---: |
| `unknown_product_plan` | 400 |
| `automatic_renewal_not_permitted` | 409 |
| `missing_required_documents` | 409 |
| `recurring_consent_required` | 409 |
| `provider_currency_mismatch` | 409 |

`identity/services/checkout.py` must remove its FastAPI dependency.

Specifically:

- `get_sellable_plan()` raises `CheckoutError("unknown_product_plan")`;
- `raise_missing_recurring_consent()` raises transport-neutral checkout errors;
- `missing_required_documents` preserves the existing public `documents` data via safe internal details.

For the checkout route, replace the listed business `HTTPException` branches with `CheckoutError`.

Do not move route/request mechanics out of the router.

Create a small Presentation-layer module:

```text
apps/api/app/http_errors.py
```

It owns FastAPI/Starlette response mapping.

Register a central handler for `AppError` from the application composition root in `create_app()`.

The handler must:

- explicitly map current `CheckoutError` codes to their existing HTTP statuses;
- return structured:
  ```json
  {"detail": {"code": "..."}}
  ```
- for `missing_required_documents`, preserve:
  ```json
  {
    "detail": {
      "code": "missing_required_documents",
      "documents": [...]
    }
  }
  ```
- never blindly serialize arbitrary `AppError.details_safe`;
- return a generic structured 500 for an unmapped `AppError`.

Do not include `message_safe` in public responses unless an existing contract explicitly requires it. None of the checkout errors in this slice currently require it.

Keep the existing `PaymentProviderConfigurationError` route handling unchanged apart from its new import path from Step 1. Its provider-specific compatibility behavior is not part of this API-shape slice.

Enhance the AST architecture checker with a narrowly scoped rule covering domain service trees:

```text
domains/*/service/**
domains/*/services/**
domains/*/service.py
```

Those service/application modules must not import:

- `fastapi`;
- `starlette`.

Do not apply the rule blindly to routers or mixed presentation modules such as session dependencies.

## Invariants

Preserve:

- all checkout HTTP statuses;
- all checkout machine-readable codes;
- missing-document payload contents;
- checkout metric outcomes;
- DB commit/rollback behavior;
- provider account selection;
- order/session creation flow;
- recurring-consent behavior established by previous tickets;
- public success response;
- no new database changes.

`details_safe` must not become an automatic public serialization mechanism.

## Out of scope

Do not:

- migrate every identity `HTTPException`;
- split `identity/router.py`;
- split the checkout orchestration into new layers;
- change payment-provider configuration errors;
- change auth/login/register errors yet;
- change password reset yet;
- add exception monitoring;
- modify billing lifecycle errors;
- add HTTP status fields to `CheckoutError`.

## AI prompt

```text
Implement only Step 2 of ANY-415: establish a transport-neutral checkout error path with central FastAPI AppError mapping.

Step 1 is assumed complete: AppError remains in `app.core.errors`, and payment-specific errors are owned by `app.payment_providers.errors`.

Follow these decisions exactly.

1. Add `app.domains.identity.errors.CheckoutError` as a small AppError subclass. Do not create one exception class per code and do not put HTTP status information on the exception.
2. Remove FastAPI/HTTPException usage from `app.domains.identity.services.checkout`.
3. Replace the service-level checkout HTTP failures with CheckoutError while preserving the existing codes and behavior:
   - unknown_product_plan -> HTTP 400 at the presentation boundary;
   - missing_required_documents -> HTTP 409 and preserve the current documents payload;
   - recurring_consent_required -> HTTP 409.
4. In the checkout route, migrate these business conditions to CheckoutError as well:
   - automatic_renewal_not_permitted -> 409;
   - missing_required_documents -> 409;
   - provider_currency_mismatch -> 409.
5. Do not alter the existing PaymentProviderConfigurationError compatibility mapping in the router apart from using its Step-1 import location.
6. Add a small presentation-boundary module `apps/api/app/http_errors.py`.
7. Register a central FastAPI handler for AppError from `create_app()`.
8. The handler must explicitly map the current CheckoutError codes to their existing HTTP statuses and return `{"detail":{"code":"..."}}`.
9. Preserve `missing_required_documents` as `{"detail":{"code":"missing_required_documents","documents":[...]}}`.
10. Never blindly expose AppError.details_safe or message_safe. Only the currently public `documents` field may be copied from CheckoutError safe details.
11. An AppError not explicitly mapped by the current presentation rules must fail closed as HTTP 500 with a generic structured internal error code. Do not expose its internal/provider code by default.
12. Update current API characterization tests so only the response shape changes where this step deliberately migrates a legacy string detail. Preserve status and code.
13. Extend the existing AST architecture guard so domain service/application files under `service.py`, `service/**`, or `services/**` cannot import FastAPI or Starlette transport types. Keep routers/session presentation dependencies outside this rule.
14. Add a focused architecture test for that rule and focused central-handler tests.

Do not change transaction boundaries, checkout persistence, provider selection, recurring-consent semantics, metrics, or successful response contracts.

Implement only this step.
Follow the decisions defined above.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify these assumptions.
Do not redesign the architecture or physically reorganize packages.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, type checkers, generators, architecture checks, or any other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report changed files;
- summarize the new checkout error flow;
- identify exactly which legacy checkout response bodies became structured while retaining their status/code;
- report the exact manual verification commands.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

## Manual verification

```bash
pytest apps/api/tests/test_error_handling.py -k "app_error or checkout"
pytest apps/api/tests/test_api.py -k "checkout"
npm run architecture:check
```

## Expected completion

Step 2 is complete when:

- checkout service code contains no FastAPI/Starlette dependency;
- checkout business failures propagate as `CheckoutError`;
- Presentation owns their HTTP statuses;
- touched checkout errors use structured `detail.code`;
- existing status/code/business behavior remains unchanged;
- architecture checks prevent FastAPI from returning to domain service trees.

## Proposed commit

`refactor(errors): centralize checkout error mapping`

---

# Step 3 — Normalize auth and password-reset error contracts

**Status:** `done`

## Goal

Finish the backend API slice required by the frontend migration:

- login/register errors have structured codes;
- password-reset business errors are transport-neutral;
- all existing statuses and machine-readable codes remain unchanged.

## Scope / affected code

Primary files:

- `apps/api/app/domains/identity/errors.py`
- `apps/api/app/domains/identity/router.py`
- `apps/api/app/domains/identity/password_reset.py`
- `apps/api/app/http_errors.py`
- `apps/api/tests/test_api.py`
- `apps/api/tests/test_error_handling.py`

## Implementation decisions

### Register/login

These errors are raised directly by route/presentation logic and do **not** need artificial Application exception classes.

Keep them as `HTTPException`, but migrate their public body from string detail to structured detail:

| Route condition | Status | Code |
| --- | ---: | --- |
| personal consent absent | 400 | `missing_personal_consent` |
| offer consent absent | 400 | `missing_offer_consent` |
| existing email | 409 | `email_already_registered` |
| invalid login | 401 | `invalid_credentials` |

Example:

```python
raise HTTPException(
    status_code=401,
    detail={"code": "invalid_credentials"},
)
```

Do not replace native FastAPI validation 422 responses.

### Password reset

Add one feature-level transport-neutral type:

```python
class PasswordResetError(AppError):
    ...
```

Use it for current business failures:

| Code | Status |
| --- | ---: |
| `password_reset_rate_limited` | 429 |
| `invalid_or_expired_reset_token` | 400 |

`enforce_password_reset_rate_limit()` must no longer construct `HTTPException`.

The request route must preserve its rollback-before-propagation behavior when the rate limit is hit. Because that path currently catches `HTTPException` to perform the rollback, migrate the narrow catch together with the raised type: catch `PasswordResetError`, call `db.rollback()`, and re-raise. Do not replace it with a broad `except Exception`.

All invalid/expired-token branches must continue to be deliberately indistinguishable from one another.

Extend the existing central `AppError` presentation mapper with only these two current PasswordResetError mappings.

Do not expose internal token/user existence information.

## Invariants

Preserve:

- registration/login statuses;
- registration/login codes;
- credential behavior;
- password-reset anti-enumeration behavior;
- password-reset rate limits;
- reset-token one-time consumption;
- reset-token expiry behavior;
- session revocation;
- DB rollback behavior;
- Pydantic 422 validation behavior;
- no information disclosure about account existence.

## Out of scope

Do not:

- move register/login into new services;
- split `password_reset.py`;
- redesign password reset persistence;
- change password policy;
- change rate-limit thresholds;
- change token lifetime;
- change status codes;
- introduce localization into the backend;
- migrate unrelated session/payment-status HTTP errors.

## AI prompt

```text
Implement only Step 3 of ANY-415: normalize the selected auth/password-reset error contracts while preserving behavior.

Step 2 is assumed complete: AppError has a central FastAPI mapping boundary, CheckoutError exists, and `app/http_errors.py` owns transport mapping.

Follow these decisions exactly.

Register/login:
1. Keep direct route-owned validation/auth failures as HTTPException; do not create unnecessary application exception classes for them.
2. Change only the response detail shape for these existing failures:
   - missing_personal_consent: status 400, detail {"code":"missing_personal_consent"}
   - missing_offer_consent: status 400, detail {"code":"missing_offer_consent"}
   - email_already_registered: status 409, detail {"code":"email_already_registered"}
   - invalid_credentials: status 401, detail {"code":"invalid_credentials"}
3. Preserve the existing HTTP statuses and code strings.
4. Do not modify FastAPI/Pydantic 422 validation responses.

Password reset:
5. Add a small `PasswordResetError` AppError subclass in the existing identity error module. Do not create one class per code.
6. `enforce_password_reset_rate_limit()` must raise PasswordResetError with code `password_reset_rate_limited` instead of HTTPException.
7. Preserve the request route's rollback behavior before the rate-limit error propagates. Replace the current narrow `except HTTPException` rollback catch for this path with `except PasswordResetError`; call `db.rollback()` and re-raise. Do not broaden the catch to `Exception`.
8. All current invalid/expired reset-token branches must raise PasswordResetError with code `invalid_or_expired_reset_token`.
9. Extend the central presentation mapper with:
   - password_reset_rate_limited -> HTTP 429
   - invalid_or_expired_reset_token -> HTTP 400
10. Responses from those mappings must use structured detail.code.
11. Preserve password-reset anti-enumeration, token usage, session revocation, password policy, timing semantics, and persistence behavior exactly.

Update focused API and handler tests to assert the structured response contracts and unchanged statuses.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant identity/password-reset/error-handler files if needed to verify plan assumptions.
Do not redesign the architecture.
Do not split modules or move unrelated business logic.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, type checkers, generators, or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed file;
- summarize which backend errors now use structured detail.code;
- confirm all existing statuses and machine-readable code strings are preserved;
- report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

## Manual verification

```bash
pytest apps/api/tests/test_error_handling.py -k "password_reset"
pytest apps/api/tests/test_api.py -k "register or login or password_reset"
```

## Expected completion

Step 3 is complete when:

- selected register/login errors return structured codes;
- password-reset business errors no longer depend on `HTTPException`;
- rate limiting and invalid-token semantics are unchanged;
- frontend has a stable `status + detail.code` contract for the paths it is about to consume.

## Proposed commit

`refactor(errors): normalize auth error contracts`

---

# Step 4 — Stop frontend error-message parsing

**Status:** `todo`

## Goal

Make frontend decisions from the actual API contract rather than serialized `Error.message`.

After this step:

```text
ApiError.status
+
ApiError.detail.code
```

are the only inputs used by auth/password-reset UX error classification.

## Scope / affected code

Primary files:

- `apps/web/src/shared/api/auth.ts`
- `apps/web/src/features/checkout/CheckoutClient.tsx` only for reuse of the structured-code helper if applicable
- new focused test such as:
  - `apps/web/tests/components/AuthApiError.test.ts`

Existing checkout characterization tests are used to protect compatibility if `CheckoutClient` imports the shared helper.

## Implementation decisions

Add/export a small helper in the existing shared API module:

```ts
apiErrorCode(error: unknown): string | null
```

It must:

- require `error instanceof ApiError`;
- require `detail` to be an object;
- require a string `detail.code`;
- return `null` otherwise.

It must **not**:

- inspect `Error.message`;
- parse `rawBody`;
- infer codes from arbitrary strings;
- treat legacy string `detail` as a structured code.

Rewrite `authErrorMessage()` to branch on explicit status/code pairs:

- `409 + email_already_registered`;
- `401 + invalid_credentials`;
- `400 + missing_personal_consent`;
- `400 + missing_offer_consent`.

Preserve the existing Russian UX messages.

Rewrite `passwordResetErrorMessage()`:

- `400 + invalid_or_expired_reset_token` → existing invalid-link message;
- status `422` → existing validation message;
- otherwise → existing generic fallback.

Do not invent new UX for 429 in this ticket.

If `CheckoutClient` still contains its own equivalent structured-object `apiErrorCode` parser, replace that duplication with the shared helper.

However, retain **narrow, explicit compatibility branches** for untouched legacy string-detail contracts that `CheckoutClient` still consumes. At the reviewed PR #78 baseline this includes:

- provider configuration compatibility: `cloudpayments_public_terminal_id_missing` and `cloudpayments_widget_mode_invalid`;
- legal acceptance compatibility: `invalid_acceptance_text_hash` from the existing legal acceptance endpoint.

Do not silently broaden the new shared helper to support arbitrary legacy strings merely to eliminate those compatibility branches. The shared helper remains structured-only; legacy handling stays local to the exact call site/status/code combinations that still require it.

Add focused tests proving:

1. correct structured auth codes produce the current messages;
2. correct password-reset structured code produces the current message;
3. 422 still uses the current validation message;
4. a misleading generic `Error.message` containing `401`, `409` or a known code does **not** trigger API-specific UX;
5. an `ApiError` with the wrong status/code combination does not get misclassified;
6. fallback behavior remains unchanged;
7. the intentionally retained legacy provider/legal string-detail branches still work, while an arbitrary string `detail` is **not** treated as a structured code.

## Invariants

Preserve:

- all current user-facing Russian strings;
- fetch/request timeout behavior;
- `ApiError.status`;
- `ApiError.detail`;
- auth submission behavior;
- session storage behavior;
- checkout missing-document behavior;
- existing explicitly allowlisted provider/legal legacy compatibility that was not migrated by backend steps.

## Out of scope

Do not:

- redesign `ApiError`;
- make a global frontend networking library;
- change localization architecture;
- change auth UI;
- change checkout UI;
- parse arbitrary backend errors;
- migrate unrelated API clients.

## AI prompt

```text
Implement only Step 4 of ANY-415: stop frontend auth/password-reset error classification from parsing Error.message.

The backend contract from Step 3 is assumed complete:
- selected auth/password-reset failures now expose structured `detail.code`;
- their HTTP statuses and code strings are unchanged.

Follow these decisions exactly.

1. In `apps/web/src/shared/api/auth.ts`, add/export a small `apiErrorCode(error: unknown): string | null` helper.
2. It must return a code only when:
   - error is an ApiError;
   - error.detail is a non-array object;
   - error.detail.code is a string.
3. It must not inspect Error.message, rawBody, or arbitrary strings.
4. It must not treat legacy string detail as a structured code.

Rewrite `authErrorMessage()` so it uses explicit ApiError status + structured code:
- 409 + email_already_registered -> keep the existing duplicate-account Russian message;
- 401 + invalid_credentials -> keep the existing invalid-credentials message;
- 400 + missing_personal_consent -> keep the existing personal-consent message;
- 400 + missing_offer_consent -> keep the existing offer-consent message;
- otherwise preserve the current fallback.

Rewrite `passwordResetErrorMessage()`:
- 400 + invalid_or_expired_reset_token -> keep the existing invalid/expired-link message;
- HTTP 422 -> keep the existing validation message;
- otherwise keep the existing generic fallback.

Do not invent new UX for password-reset rate limiting.

If CheckoutClient contains its own duplicate helper for structured `detail.code`, reuse the new shared helper for the structured paths and remove only that duplicated parser. Preserve only the narrow legacy string-detail compatibility still required by untouched backend contracts:
- status 409 + `cloudpayments_public_terminal_id_missing`;
- status 409 + `cloudpayments_widget_mode_invalid`;
- status 400 + `invalid_acceptance_text_hash` from the legal acceptance flow.
Do not make the shared helper accept legacy strings, and do not treat arbitrary string `detail` values as structured codes.

Add a focused Vitest test file under the existing component-test discovery path. Tests must prove:
- the expected structured status/code pairs map correctly;
- wrong status/code combinations do not;
- plain Error.message text containing "401", "409", or known backend codes does not influence classification;
- current fallbacks remain intact;
- the three intentionally retained legacy provider/legal string-detail cases still map as before;
- an arbitrary string detail does not become a structured code.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant shared API module, CheckoutClient if needed for helper reuse, and the directly relevant existing tests.
Do not redesign frontend API architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, type checkers, builds, or any other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report changed files;
- summarize which Error.message parsing was removed;
- note the intentionally retained legacy provider/legal string-detail compatibility;
- report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.
```

## Manual verification

```bash
npm --workspace @anytoolai/web run test:components -- tests/components/AuthApiError.test.ts tests/components/CheckoutClient.test.tsx
npm run typecheck:web
```

## Expected completion

Step 4 is complete when:

- auth/password-reset classification contains no `Error.message` parsing;
- behavior is driven by `ApiError.status` and structured `detail.code`;
- current Russian messages and fallback behavior remain unchanged;
- checkout compatibility is preserved.

## Proposed commit

`refactor(web): consume structured API error codes`

---

# Step 5 — Add the safe unexpected-failure boundary and document the contract

**Status:** `todo`

## Goal

Complete ANY-415 by making unexpected HTTP failures operationally visible without leaking untrusted/sensitive data, and document the resulting error ownership rules as architecture authority.

## Scope / affected code

Primary runtime/test files:

- `apps/api/app/http_errors.py`
- `apps/api/app/main.py` for explicit exception-handler/middleware registration order
- `apps/api/tests/test_error_handling.py`

Documentation:

- `ARCHITECTURE.md`
- `docs/architecture/billing-authority.md`
- `docs/RELIABILITY.md`

Only update repository documentation tests if the existing documentation guard requires it.

## Implementation decisions

Keep two distinct Presentation mechanisms:

1. the existing central `AppError` exception handler for mapped and unmapped `AppError` values;
2. one Presentation-level catch-all middleware for truly unexpected exceptions escaping FastAPI/Starlette endpoint handling.

Do **not** register unexpected-failure handling as a generic `app.exception_handler(Exception)` / `add_exception_handler(Exception, ...)` fallback. The catch-all must be user middleware so the application deliberately converts the failure to the public 500 response instead of relying on Starlette's outer server-error boundary, which may re-raise the original exception for server-level handling.

Implement the catch-all in the Presentation error-boundary module (`app/http_errors.py`) and register it so the existing request-context middleware wraps it. The effective runtime order must preserve this relationship:

```text
outer server/CORS middleware
    -> request_context_middleware
        -> unexpected_failure_middleware
            -> FastAPI ExceptionMiddleware / routes
```

This ordering is a correctness requirement:

- `request_id_context` is still active when the unexpected-failure diagnostic is emitted;
- the catch-all returns a response to `request_context_middleware`;
- `request_context_middleware` still attaches `X-Request-ID` and records the request-completion event.

Do not move HTTP response construction into `app.core.observability`; Core remains infrastructure, while Presentation owns the public error mapping.

Both an unexpected exception and an unmapped `AppError` must return:

```json
{
  "detail": {
    "code": "internal_server_error"
  }
}
```

with HTTP 500.

Use one small shared internal helper in the Presentation error-boundary module for the bounded internal-failure diagnostic so unmapped `AppError` and unexpected exceptions follow the same logging policy without duplicate logging.

Log exactly one application-level failure diagnostic for each such internal failure.

The failure log may contain only bounded metadata such as:

- request ID through the existing logging context;
- HTTP method;
- matched route template;
- exception class/type;
- for an unmapped `AppError`, its machine-readable `code` if useful;
- one bounded application-owned failure location/fingerprint derived from traceback metadata, containing only:
  - repository-relative module/file identifier;
  - function name;
  - line number.

When a traceback contains application-owned frames, select one deterministic frame that best identifies where the application failure originated (prefer the innermost frame under the application code). If no application-owned frame exists, omit the location rather than logging external-library internals.

The location/fingerprint must not include source text, local variables, arguments, object values, exception text, or raw traceback text.

Do **not** log:

- exception message;
- `repr(exc)`;
- raw traceback text;
- source-code line text;
- traceback locals, arguments or object values;
- request body;
- response body;
- raw URL/query string;
- request headers;
- cookies;
- authorization;
- raw provider payload;
- `AppError.details_safe` wholesale;
- card/token/payment values.

Do not call `logger.exception()` or pass raw `exc_info` from this boundary if doing so would serialize the original exception message/traceback into the application diagnostic.

The existing request-completion log remains. It is a request lifecycle record, not a second exception diagnostic.

An `AppError` reaching the central handler without an explicit Presentation mapping must:

- return generic `internal_server_error`;
- be treated as an unmapped/internal failure;
- not leak its internal/provider code or details to the HTTP client;
- produce the same bounded boundary diagnostic exactly once.

Tests must verify:

1. ordinary mapped AppError responses are unchanged;
2. an unmapped AppError gives structured HTTP 500 and exactly one bounded failure diagnostic;
3. an unexpected exception gives structured HTTP 500;
4. `X-Request-ID` still exists on the unexpected-failure response;
5. one bounded failure diagnostic is emitted for the unexpected exception;
6. a deliberately secret-looking exception message is absent from the emitted application log;
7. an unexpected application exception includes one bounded application-owned failure location/fingerprint (module/file, function and line number) without source text, locals or arguments;
8. no raw request inputs are logged by this boundary;
9. the ordinary test client path receives the structured 500 response rather than re-raising the deliberately raised application exception to the caller.

### Documentation

Update the accepted ANY-411 architecture text, not an alternative architecture.

Document:

#### Core

- owns neutral `AppError`;
- does not own feature-specific error vocabularies.

#### Domain/Application

- own business/application failure meaning;
- exceptions carry stable internal codes and safe diagnostics where justified;
- no FastAPI/HTTP status/vendor response dependency.

#### Integrations/provider boundary

- normalize vendor failures;
- preserve retryability/idempotency/unknown/ambiguous semantics;
- raw vendor responses are not Domain/Application error contracts.

#### Presentation

- maps internal errors to HTTP;
- owns statuses and public error DTO/body shape;
- only allowlisted safe fields become public;
- touched errors use structured `detail.code`.

#### Frontend

- branches on `ApiError.status` and structured `detail.code`;
- does not parse serialized exception text.

#### Unexpected failures

- generic public 500;
- bounded safe log once at the application HTTP boundary;
- diagnostics may include one bounded application-owned failure location/fingerprint (module/file, function and line number), never source text, locals, arguments or raw traceback text;
- Sentry/new monitoring deferred.

Do not add a new ADR: ANY-411 already establishes the layer direction. This ticket is implementing and documenting that existing decision.

## Invariants

Preserve:

- request ID behavior;
- current JSON logging setup;
- existing redaction;
- current metrics/tracing;
- no raw request/provider payload logging;
- no Sentry/new telemetry dependency;
- all mapped business error contracts from Steps 2–4;
- payment/provider retry semantics.

## Out of scope

Do not:

- add Sentry;
- add another log framework;
- capture local variables/stack locals;
- add request/response-body logging;
- modify OTEL architecture;
- change metrics;
- introduce a generic monitoring abstraction;
- rewrite ANY-411 ADRs;
- redesign the package tree.

## AI prompt

```text
Implement only Step 5 of ANY-415: complete the safe unexpected-failure HTTP boundary and document the final error architecture.

Steps 1-4 are assumed complete.

Follow these decisions exactly.

Runtime behavior:
1. Keep the central AppError exception handler in `app/http_errors.py` for mapped and unmapped AppError values.
2. Add a Presentation-level `unexpected_failure_middleware` (name may vary) in `app/http_errors.py` for exceptions that escape FastAPI/Starlette endpoint handling.
3. Do NOT register the unexpected-failure fallback as `app.exception_handler(Exception)` or `add_exception_handler(Exception, ...)`. The middleware must deliberately convert the exception into the public response instead of relying on Starlette's outer server-error boundary.
4. Register middleware so `request_context_middleware` wraps the unexpected-failure middleware. Preserve the effective relationship:
   request_context_middleware -> unexpected_failure_middleware -> ExceptionMiddleware/routes.
   This must keep request-id context active while the failure is logged and must allow request_context_middleware to add X-Request-ID to the returned 500 response.
5. Do not move HTTP response construction into `app.core.observability`; Presentation owns the public error mapping.
6. For both an unexpected exception and an unmapped AppError, return HTTP 500 with exactly:
   {"detail":{"code":"internal_server_error"}}
7. Use one small internal helper in the Presentation error-boundary module for the bounded internal-failure diagnostic so both paths follow the same policy without duplicate logging.
8. Emit exactly one application-level failure diagnostic for each unmapped/internal failure.
9. Use only bounded metadata:
   - existing request-id context;
   - HTTP method;
   - matched route template;
   - exception class/type;
   - optionally the stable code for an unmapped AppError;
   - one bounded application-owned failure location/fingerprint derived from traceback metadata, containing only repository-relative module/file identifier, function name and line number.
10. If a traceback contains application-owned frames, select one deterministic frame that best identifies where the application failure originated (prefer the innermost frame under application code). If no application-owned frame exists, omit the location rather than logging external-library internals.
11. The failure location must not include source-code text, local variables, arguments, object values, exception text, or raw traceback text.
12. Do NOT log:
   - exception message or repr;
   - raw traceback text or source-code line text;
   - traceback locals, arguments or object values;
   - request body;
   - response body;
   - raw URL/query string;
   - headers/cookies/auth;
   - provider payload;
   - AppError.details_safe wholesale;
   - card/token/payment data.
13. Do not use logger.exception or raw exc_info if that would serialize the original exception message/traceback into the boundary diagnostic.
14. An unmapped AppError must not leak its internal/provider code or details to the client.
15. Keep the existing request-completion log. It is not an additional exception diagnostic.

Tests:
16. Extend `apps/api/tests/test_error_handling.py` with focused boundary tests.
17. Verify mapped AppError behavior still works.
18. Verify an unmapped AppError produces structured 500 and exactly one bounded failure diagnostic.
19. Verify a deliberately raised unexpected exception produces structured 500 with X-Request-ID.
20. Verify exactly one application failure diagnostic from the unexpected-failure boundary.
21. Use a secret-looking exception message in the test and assert that message is absent from the boundary log.
22. Verify the unexpected-exception diagnostic includes exactly one bounded application-owned failure location/fingerprint with module/file, function and line number.
23. Verify source text, locals, arguments and raw traceback text are absent from that diagnostic.
24. Verify no raw request values are present in the boundary diagnostic.
25. Exercise the normal test-client path with exception re-raising enabled/default and verify the deliberately raised application exception is converted to the structured 500 response instead of escaping to the test caller.

Documentation:
26. Update the accepted ANY-411 architecture documentation, primarily `ARCHITECTURE.md` and `docs/architecture/billing-authority.md`, to record:
    - Core owns only neutral shared error primitives;
    - feature errors stay with their Application/Domain/provider boundary;
    - Application/Domain errors contain no FastAPI/HTTP/vendor response semantics;
    - Integrations normalize provider failures and preserve retry/unknown/ambiguous semantics;
    - Presentation owns HTTP status/body mapping;
    - only explicitly allowlisted safe data is serialized publicly;
    - changed public errors use structured detail.code;
    - frontend branches on ApiError.status and structured detail.code.
27. Update `docs/RELIABILITY.md` with the bounded unexpected-failure logging rule and generic public 500 behavior, including that unexpected application failures are converted at the Presentation middleware boundary while request-id context is active. Document that the boundary may record one bounded application-owned failure location/fingerprint (module/file, function and line number) but never source text, locals, arguments, exception message or raw traceback text.
28. Do not create a new ADR. ANY-411 already defines the architecture direction.
29. Do not add Sentry, a new telemetry library, request-body logging, or another monitoring abstraction.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant error-boundary, test, and authoritative documentation files if needed.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future ANY-407 steps.
Do not run tests, linters, formatters, type checkers, generators, documentation checks, architecture checks, or any other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report every changed file;
- summarize the final unexpected-failure behavior;
- state exactly what is and is not logged;
- summarize the documented layer ownership;
- report the exact verification commands I should run manually.

If the current code or the final accepted ANY-411 documentation materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new architecture.
```

## Manual verification

First run the focused checks:

```bash
pytest apps/api/tests/test_error_handling.py
npm run docs:check
npm run architecture:check
```

Then run final ticket verification:

```bash
npm run check:fast
npm run test:api
npm --workspace @anytoolai/web run test:components
```

## Expected completion

ANY-415 is complete when:

- shared Core no longer owns payment-specific errors;
- provider failures retain all established retry/idempotency/redaction semantics;
- service/application checkout failures do not depend on FastAPI;
- current password-reset business failures have transport-neutral representation;
- FastAPI has one central `AppError` mapping boundary;
- reviewed API errors use structured `detail.code`;
- frontend auth/password reset does not parse `Error.message`;
- unmapped/unexpected failures return safe structured 500 responses;
- unexpected failures are converted by the Presentation middleware while request-id context is active and produce one bounded application-level diagnostic without raw sensitive input, including a bounded application-owned failure location/fingerprint when available;
- architecture guards prevent the concrete dependency regressions fixed by this ticket;
- architecture/reliability documentation describes the resulting ownership;
- no persistence/schema or future ANY-407 work has been pulled in.

## Proposed commit

`refactor(errors): complete safe HTTP error boundary`

---

# Final Plan Validation

The plan covers the current ANY-415 acceptance surface without taking neighboring work.

It deliberately preserves already completed work from ANY-165/169:

- retry disposition;
- idempotency;
- provider error normalization;
- exception chaining;
- redaction;
- unknown/reconciliation behavior.

It follows ANY-411 rather than reopening its architecture:

- Presentation maps HTTP;
- Application/Domain remain transport-neutral;
- Integrations own provider translation;
- Core stays shared infrastructure.

It does not pre-empt later ANY-407 work:

- no persistence extraction;
- no sync/async redesign;
- no new billing-system abstraction;
- no observability platform/Sentry work;
- no general layering refactor.

No database migration or persisted-data change is required.

## Potential follow-ups found during research, not part of ANY-415

The repository still contains broader legacy transport debt, including string `HTTPException.detail` responses outside the reviewed auth/checkout/password-reset slice. Those should not be mass-migrated here.

`password_reset.py` remains a physically mixed router/business module even after its business error semantics become transport-neutral. Physical package separation belongs to later layering work.

`SubscriptionLifecycleError` and `LegalAcceptanceError` remain separate transport-neutral domain exceptions intentionally. Converting them merely to make every exception inherit the same base would add churn without a current consumer.

The transitional checkout frontend still contains provider-specific compatibility around current CloudPayments configuration failures. That should be reconsidered together with the corresponding provider/public API contract rather than silently renamed in ANY-415.
