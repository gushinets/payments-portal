# ANY-709 Step 2 - Customer and account Widget

Status: DONE - condensed historical implementation/evidence report
Date: 2026-10-27
Scope: Step 2 and shared LBX error corrections; actual payment remains unverified.

Historical checkpoint: the one-POST-per-opening behavior recorded below was
superseded by the owner-approved 2026-10-28 bounded customer recovery amendment.
Current behavior and verification are in the completed plan and billing runbook.

## Delivered result

- First name, surname and patronymic are independently optional. Empty/whitespace
  values become null; populated values trim and retain length/type validation.
- Login, registration and ordinary GETs create no LBX objects. A verified explicit
  billing opening ensures one customer and opens the official account Widget,
  even without a subscription, current catalog offer or product link.
- Shared `ensure_customer` discovers by stored identity/key/email, performs
  paired point verification, then sends at most one CREATE in that opening.
  Existing proven binding or durable success receipt prevents another CREATE;
  an email-only match never proves ownership.
- After failure, the same opening performs GET recovery only. A later separate
  opening may search/retry once its finite send lease clears. Stable customer
  key, permanent operation, receipts and history survive; leases/fences prevent
  concurrent sends and stale completion. The old indefinite customer hold is
  superseded; financial agreement/subscription retry rules remain stricter.
- Account Widget uses fresh JWT and a session-safe SDK lifecycle. Account
  presentation disables payment; verified purchase payment is delivered by
  Steps 3-4. Customer-wide JWT and presentation flags are not a product ACL,
  and logout does not revoke a copied token.

## Important corrections

- Correct nullable-name validation and generated enum/wire contracts; reuse the
  backend-owned schema and shared web transport rather than parallel DTOs.
- Preserve durable CREATE receipts and bounded recovery. An error or empty
  discovery does not prove that a possibly sent CREATE had no effect.
- One Server API decoder handles HTTP status, JSON code and `response.error`.
  HTTP 500 must not erase a provider refusal. GET retries remain bounded;
  known permanent refusals do not retry, and POST never enters a retry loop.
- Localized safe failure/request-ID presentation and read-only customer diagnosis
  retain allowlisted response facts without raw provider text, secrets or PII.
  Repair/force-binding commands were removed.
- Unresolved integration errors are reported once through the sanitized Sentry
  boundary when configured. Successful GET recovery and active parallel attempts
  are not reported as unresolved failures.

## Recorded verification

- Customer-ensure canonical checkpoint passed: 1,298 fast API tests, 210
  PostgreSQL tests, 300 component tests, 38 boundary tests and standard checks.
  Coverage includes send leases, concurrent opens, receipts and Sentry behavior.
- The later shared-error canonical checkpoint passed: 1,422 fast API tests,
  218 PostgreSQL tests, 301 component tests, 38 boundary tests, TypeScript,
  production build, lint/format, architecture, docs and generation freshness.
  Final retry refinements passed `check:fast` and 142 focused error/client tests.
- Synthetic desktop/mobile error-state checks covered safe reason/request-ID
  display, no Widget on failure, keyboard/overflow and accessibility checks.
- The owner observed a real customer Widget. A new live owner-account/browser
  smoke after the customer-ensure correction was not performed. The complete
  browser suite and actual product-bound payment were not acceptance evidence.

These are separate historical checkpoints, not additive totals or a full
final-SHA PASS. Earlier temporary failures/NOT_RUN entries are superseded only
by their specifically recorded successful rechecks.

## Persistence and retained limits

Optional names, customer origin, identity uniqueness, send fence and recovery
indexes are now included in `20261027_0003_normal_billing`. No provider objects
are created by migration and no history is promoted or deleted.

LBX error text does not establish native CREATE idempotency or no-side-effect
proof. Actual acquiring, intended-agreement Widget payment and paid access are
not proven by account-Widget rendering or these synthetic checks.

- [Completed plan](ANY-709-implementation-plan.md)
- [Billing runbook](../../engineering/ANY-709-billing-runbook.md)

Full pre-compaction chronology, original commands and intermediate failures are
retained in Git at `2961577`.
