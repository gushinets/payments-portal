# ANY-458 — PR #92 Review Remediation Plan

## 0. Назначение

Этот remediation закрывает подтверждённые замечания review для PR #92 после завершения исходных Step 1–4 ANY-458.

Исходная реализация ANY-458 остаётся архитектурной базой.

Review выявил четыре конкретных gap:

1. configured production Sentry DSN может использовать cleartext HTTP;
2. safe Windows-relative stack filenames отбрасываются sanitizer-ом;
3. CloudPayments webhook перехватывает unexpected processing exception и превращает его в `HTTPException(500)` до общего HTTP Sentry boundary;
4. password-reset background callback поглощает SMTP/email-delivery exception и поэтому failure остаётся вне Sentry.

Это не новый design phase и не переосмысление ANY-458.

---

# 1. Правило изменения исходного implementation plan

`docs/exec-plans/active/ANY-458-implementation-plan.md` остаётся authoritative artifact.

Но original Steps 1–4 являются **исторической записью реально утверждённой и выполненной реализации**.

Поэтому post-review remediation:

- не переписывает историю выполнения Step 1–4;
- не делает вид, что новые review decisions существовали изначально;
- добавляет отдельный authoritative addendum;
- изменяет верхнеуровневый final contract там, где review действительно расширил или уточнил его.

Добавить в remediation section явное правило:

```text
This post-review remediation supersedes earlier locked decisions only where
explicitly stated below. Original Steps 1–4 remain the historical record of
the approved initial implementation.
```

---

# 2. Source of truth

При remediation использовать:

1. ANY-407 — architecture direction;
2. ANY-415 — Error Architecture;
3. ANY-437 — observability/privacy/correlation;
4. ANY-458 — Sentry ownership;
5. original ANY-458 implementation plan;
6. текущую реализацию PR #92;
7. validated PR review findings;
8. post-review remediation section — только для явно superseded решений.

Не проводить новый широкий Linear/repository research.

---

# 3. Неподвижные архитектурные решения

Остаётся:

```text
Sentry             -> backend application failure issues
OpenTelemetry      -> traces
Prometheus / OTEL  -> metrics
JSON logs          -> bounded diagnostics
PostgreSQL         -> authoritative business state
```

Sentry:

- optional;
- disabled with empty `SENTRY_DSN`;
- explicit capture only;
- no FastAPI/Starlette automatic capture;
- no logging auto-capture;
- no Sentry tracing;
- no Sentry metrics;
- no profiling;
- no Sentry dependency in semantic Domain/Application errors;
- direct `sentry_sdk` imports only in `app/infrastructure/sentry.py`;
- reporting remains fail-safe.

Privacy contract remains unchanged.

Never emit:

```text
email
reset URL
reset token
request/query values
headers
provider payload
provider IDs
customer identifiers
payment values
raw exception message
locals
source context
credentials
```

---

# 4. Locked post-review decisions

## 4.1 Production Sentry transport

Final rule:

```text
empty production SENTRY_DSN
    -> Sentry disabled

configured production SENTRY_DSN
    -> HTTPS required

development/test
    -> HTTP DSN remains permitted for controlled local/test use
```

Reuse:

```python
validate_production_public_url(...)
```

Do not use `validate_https_origin_url(...)`.

The existing rule remains:

```text
configured SENTRY_DSN -> SENTRY_RELEASE required
```

---

## 4.2 Platform-neutral repository-relative paths

Safe Windows SDK filenames:

```text
app\payment_providers\registry.py
```

normalize to:

```text
app/payment_providers/registry.py
```

before component validation.

Still reject:

```text
/absolute/path.py
\rooted\path.py
C:\absolute\path.py
C:relative-looking-but-drive-qualified.py
\\server\share\path.py
../path.py
app/../path.py
app//path.py
```

Do not use filesystem resolution or host-dependent `Path.resolve()`.

---

## 4.3 Catch-and-convert / catch-and-absorb rule

The centralized HTTP error boundary remains the default reporting owner.

New clarification:

```text
If an already-existing outer boundary catches a reportable exception and
converts or absorbs it before the normal reporting boundary can observe it,
that boundary owns exactly one explicit Sentry report.
```

This does **not** authorize arbitrary Sentry calls from business logic.

---

## 4.4 CloudPayments webhook

The current webhook does:

```text
processing failure
    ->
catch Exception
    ->
persist existing failed webhook state
    ->
HTTPException(500)
```

Therefore the common middleware never receives the original exception.

Final remediation:

```text
processing failure
    ->
existing rollback/failure-state handling
    ->
existing bounded diagnostic
    ->
report original exception exactly once
    ->
existing HTTPException(500)
```

Use:

```python
operation=Operation.HTTP_REQUEST
method=request.method
route="/api/cloudpayments/{endpoint}"
error_code="normalization_unexpected_error"
```

Do not override `failure_category`.

Do not emit runtime endpoint value or webhook/provider/customer/payment data.

CloudPayments architecture is not redesigned in ANY-458.

Its later disable/decommission remains separate work.

---

## 4.5 Password-reset background delivery

`send_password_reset_email_safely(...)` intentionally catches delivery failures and returns.

Therefore it is an existing background outer boundary for operational failure reporting.

Extend the **final** closed Operation vocabulary with:

```python
PASSWORD_RESET_EMAIL = "password_reset_email"
```

Final vocabulary becomes:

```text
HTTP_REQUEST          -> "http_request"
EXPIRE_SUBSCRIPTIONS  -> "expire_subscriptions"
PASSWORD_RESET_EMAIL  -> "password_reset_email"
```

Important historical rule:

The original Step 1 text should continue to show only the operations that existed when Step 1 was implemented.

`PASSWORD_RESET_EMAIL` is introduced by the post-review remediation and must not be retroactively inserted into the historical Step 1 execution instructions.

Delivery exception:

```python
report_exception(
    error,
    operation=Operation.PASSWORD_RESET_EMAIL,
    failure_category=FailureCategory.INTEGRATION_FAILURE,
)
```

Pass no email-specific context.

Preserve:

- failed metric;
- warning diagnostic;
- callback return behavior;
- HTTP `accepted` semantics;
- current background execution model.

---

# 5. Execution model

Execute strictly sequentially:

```text
R1
↓ review
↓ user commit

R2
↓ review
↓ user commit

R3
↓ review
↓ user commit

R4
↓ review
↓ user commit

R5
↓ review
↓ user commit

R6
↓ final developer gates
```

Codex does not commit.

For each step:

1. read the relevant remediation section;
2. inspect only directly affected files/tests;
3. implement only that step;
4. run targeted formatting/static checks;
5. run smallest focused pytest selection;
6. inspect diff once;
7. stop.

If a focused test hangs or produces a non-obvious failure:

```text
STOP after the first useful failure.
```

Do not:

- repeatedly rerun tests;
- start Docker automatically;
- start PostgreSQL/debug environments automatically;
- investigate framework/SDK internals autonomously;
- run the whole suite.

---

# R1 — Finalize authoritative remediation amendment

## Status

`in progress` until this step is committed.

## Goal

Make the existing ANY-458 plan accurately represent:

```text
original implementation completed
+
post-review remediation currently in progress
```

without rewriting implementation history.

## File

```text
docs/exec-plans/active/ANY-458-implementation-plan.md
```

## Keep from the current R1 diff

Keep:

- production HTTPS Sentry rule in the current/final contract;
- Windows path normalization contract;
- centralized boundary clarification;
- final three-operation vocabulary in the current/final contract;
- `Post-review remediation — PR #92`;
- R1–R6 table;
- detailed webhook correction;
- detailed password-reset correction.

## Correct before commit

### Metadata

Do not use:

```text
Overall status | todo
```

Use the repository's appropriate in-progress form, conceptually:

```text
Overall status | in progress — post-review remediation
```

Make it clear separately that:

```text
Original implementation | Steps 1–4 completed
Review remediation       | R1 → R6 in progress
```

Do not pretend the original implementation is undone.

### Remediation status

Use:

```text
Status: in progress
```

not `todo`, because R1 itself is already being executed.

### Preserve historical Step 1

Revert modifications that inserted:

```text
PASSWORD_RESET_EMAIL
```

into:

- original Step 1 implementation decisions;
- original Step 1 Codex execution prompt;
- original Step 1 test requirements.

Those sections must remain an accurate historical record.

The **current final contract sections above them** may show all three operations.

### Add supersession rule

Add:

```text
This post-review remediation supersedes earlier locked decisions only where
explicitly stated below. Original Steps 1–4 remain the historical record of
the approved initial implementation.
```

### Do not preserve rejected review nit

Remove the permanent plan section about rejecting the CodeRabbit composition-root callable suggestion.

That is a review-resolution decision, not part of the long-term ANY-458 architecture contract.

Do not implement the CodeRabbit suggestion in runtime code either.

### Definition of Done clarification

Add:

```text
ANY-458 is not complete for merge until both the original Definition of Done
and the post-review remediation R1–R6 are satisfied.
```

### Final execution sentence

While remediation is active, use wording equivalent to:

```text
The original Steps 1–4 were completed sequentially. Post-review remediation
proceeds through R1–R6 without reopening the broader research/design phase.
```

R6 will replace this with the final completed wording.

## Verification

Run once:

```bash
npm run docs:check
```

## Codex prompt

```text
Continue ANY-458 in the same implementation chat.

Implement remediation R1 only.

The current working tree already contains an initial R1 amendment to:
docs/exec-plans/active/ANY-458-implementation-plan.md

Keep the valid review-remediation additions, but correct the plan so it preserves
the historical record of the already completed original Steps 1-4.

Required corrections:

1. Do not mark the overall ticket as "todo". Use the repository's appropriate
   in-progress wording and make it explicit that original Steps 1-4 are
   completed while post-review R1-R6 remediation is in progress.

2. Mark the post-review remediation section as in progress, not todo.

3. Preserve the new final/current contract:
   - production configured SENTRY_DSN requires HTTPS;
   - safe Windows-relative filenames normalize "\" to "/";
   - catch-and-convert/absorb outer boundaries own one explicit report;
   - the final closed operation vocabulary includes PASSWORD_RESET_EMAIL.

4. Revert the edits that retroactively inserted PASSWORD_RESET_EMAIL into the
   historical original Step 1 implementation decisions, Step 1 execution prompt,
   and Step 1 test requirements. Those historical sections must continue to
   describe what was actually approved and implemented at that time.

5. In the post-review remediation section, explicitly state that R5 extends the
   original operation vocabulary with PASSWORD_RESET_EMAIL.

6. Add this supersession rule:
   "This post-review remediation supersedes earlier locked decisions only where
   explicitly stated below. Original Steps 1-4 remain the historical record of
   the approved initial implementation."

7. Remove the permanent "Rejected non-blocking review nit" section about the
   CodeRabbit composition-root callable. We are still not implementing that
   suggestion, but it does not belong in the authoritative architecture plan.

8. Clarify that ANY-458 is not complete for merge until both the original
   Definition of Done and R1-R6 remediation are satisfied.

9. Replace the final completion sentence with wording that says original Steps
   1-4 are complete while R1-R6 remediation is still proceeding without a new
   broad design/research phase.

Do not change runtime code.

Run exactly once:
npm run docs:check

If it fails non-obviously, stop and report the failure.

Show the resulting diff and stop. Do not commit.
```

## Commit

```text
docs(api): record ANY-458 review remediation
```

---

# R2 — Enforce HTTPS for production Sentry DSN

## Files

```text
apps/api/app/core/settings.py
apps/api/tests/test_sentry_reporting.py
```

## Runtime change

When `sentry_dsn` is configured and:

```text
APP_ENV=production
```

validate it with:

```python
validate_production_public_url(...)
```

Preserve:

```text
empty DSN -> valid / disabled
non-production HTTP DSN -> valid
configured DSN without release -> invalid
```

## Focused tests

Cover:

```text
production + HTTP DSN      -> reject
production + HTTPS DSN     -> accept
test/development + HTTP    -> accept
production + empty DSN     -> accept
DSN + empty release        -> reject
```

Production test fixtures must use production-valid application public URL and CORS origins.

## Codex prompt

```text
Implement ANY-458 remediation R2 only.

Read the R2 remediation contract in the current implementation plan, then inspect
only app/core/settings.py, app/core/url_validation.py, and the directly relevant
Sentry Settings tests.

Require configured production SENTRY_DSN values to pass
validate_production_public_url(...).

Do not use validate_https_origin_url(...).

Preserve:
- empty SENTRY_DSN disables Sentry;
- HTTP DSNs remain allowed in development/test;
- SENTRY_RELEASE is still required whenever a DSN is configured;
- configure_sentry() is unchanged.

Add focused regression coverage for:
- production HTTP DSN rejected;
- production HTTPS DSN accepted;
- non-production HTTP DSN accepted;
- empty production DSN accepted;
- existing release requirement preserved.

Use production-valid APP_PUBLIC_BASE_URL and CORS_ALLOW_ORIGINS in production
test cases.

Run only targeted ruff format/check for changed files and the exact focused
Settings pytest nodes.

Do not run the full Sentry test module.

On a non-obvious focused-test failure, stop after the first useful failure and
report it.

Show diff/results and stop. Do not commit.
```

## Commit

```text
fix(api): require HTTPS Sentry DSN in production
```

---

# R3 — Normalize safe Windows stack filenames

## Files

```text
apps/api/app/infrastructure/sentry.py
apps/api/tests/test_sentry_reporting.py
```

## Implementation

Update existing `_repository_relative_path()`.

Conceptual sequence:

```text
validate raw type/length
↓
reject rooted / absolute / drive-qualified raw forms
↓
normalize "\" -> "/"
↓
validate normalized components
↓
return normalized relative path
```

Do not simply permit arbitrary `\`.

Do not access filesystem.

## Cases

Accept:

```text
app\payment_providers\registry.py
tests\test_sentry_reporting.py
```

Normalize to `/`.

Reject:

```text
C:\secret\file.py
C:secret\file.py
\\server\share\file.py
\rooted\file.py
/absolute/file.py
../secret.py
app\..\secret.py
app\\file.py
```

## Codex prompt

```text
Implement ANY-458 remediation R3 only.

Read the R3 remediation contract, then inspect only
app/infrastructure/sentry.py around repository-relative path sanitization and
the directly related Sentry tests.

Fix _repository_relative_path so legitimate relative Windows SDK filenames are
normalized from "\" to "/" while preserving the strict positive allowlist.

Requirements:
- reject POSIX absolute paths;
- reject Windows rooted paths;
- reject drive-qualified C:\... and C:... paths;
- reject UNC paths;
- normalize safe relative backslashes to "/";
- reject ".", "..", duplicate/empty components;
- preserve whitespace/control-character validation;
- no Path.resolve(), filesystem access, or host-dependent behavior.

Add deterministic literal Windows-path tests that run on Linux CI as well.

Keep the existing captured-event privacy/stack regression passing.

Run targeted ruff format/check only and exact new path tests plus the existing
captured-event stack test.

Do not run the whole module.

Stop on the first non-obvious failure.

Show diff/results and stop. Do not commit.
```

## Commit

```text
fix(api): normalize safe Sentry stack paths
```

---

# R4 — Report webhook processing failures before HTTP conversion

## Files

```text
apps/api/app/integrations/cloudpayments/router.py
```

plus nearest existing webhook processing regression test.

## Runtime behavior

Preserve existing sequence and semantics.

Add exactly one reporting call for the original processing exception before conversion to `HTTPException(500)`.

Use:

```python
operation=Operation.HTTP_REQUEST
method=request.method
route="/api/cloudpayments/{endpoint}"
error_code="normalization_unexpected_error"
```

No manual category override.

No unsafe identifiers.

## Important

Do not:

- redesign CloudPayments;
- change durable inbox behavior;
- change rollback behavior;
- change response;
- introduce webhook reporting abstraction;
- introduce new webhook Operation.

## Codex prompt

```text
Implement ANY-458 remediation R4 only.

Read the R4 remediation contract and inspect only the current CloudPayments
router catch-and-convert path and its nearest focused regression tests.

The current processing exception is caught and converted to HTTPException(500)
before the centralized HTTP Sentry boundary can observe it.

At that existing outer boundary, report the original exception exactly once
through app.infrastructure.sentry before raising the existing HTTPException.

Use:
- Operation.HTTP_REQUEST
- method=request.method
- route="/api/cloudpayments/{endpoint}"
- error_code="normalization_unexpected_error"

Do not override failure_category.

Do not pass runtime endpoint values, payload, headers, provider identifiers,
invoice/transaction/account identifiers, payment values, webhook entity IDs,
order IDs, or customer data.

Preserve existing:
- rollback;
- durable failed webhook state;
- metric;
- bounded log;
- HTTP 500 response/body;
- CloudPayments contracts.

Patch report_exception in the focused test. Do not use a real Sentry transport.

Assert:
- same original exception reported exactly once;
- reporting arguments are safe and exact;
- response behavior is unchanged;
- durable failure behavior remains unchanged.

Run targeted ruff format/check and the single smallest relevant pytest node.

If PostgreSQL/environment is unavailable or a non-obvious failure occurs, stop
and report it. Do not start container/debug loops.

Show diff/results and stop. Do not commit.
```

## Commit

```text
fix(api): report webhook processing failures to Sentry
```

---

# R5 — Report password-reset background email failures

## Files

```text
apps/api/app/infrastructure/sentry.py
apps/api/app/domains/identity/password_reset.py
```

plus focused tests.

## Adapter

Add:

```python
Operation.PASSWORD_RESET_EMAIL = "password_reset_email"
```

## Boundary

Inside caught email-delivery exception:

```python
report_exception(
    error,
    operation=Operation.PASSWORD_RESET_EMAIL,
    failure_category=FailureCategory.INTEGRATION_FAILURE,
)
```

No additional context.

Preserve existing metric/log/return behavior.

## Architecture constraint

This is an existing background outer boundary despite its current module placement.

Do not relocate the entire password-reset feature merely to make the package name look cleaner.

If an actual architecture guard rejects this dependency:

```text
STOP
```

and report the contradiction.

Do not weaken/bypass the guard.

## Codex prompt

```text
Implement ANY-458 remediation R5 only.

Read the R5 remediation contract and inspect only:
- app/infrastructure/sentry.py around Operation/report_exception;
- send_password_reset_email_safely in the password-reset module;
- the directly relevant tests.

Extend the final closed Operation vocabulary with:
PASSWORD_RESET_EMAIL = "password_reset_email"

At the existing background email-delivery catch boundary, report the same
original exception exactly once using:

operation=Operation.PASSWORD_RESET_EMAIL
failure_category=FailureCategory.INTEGRATION_FAILURE

Pass no email/reset-specific context.

Never pass:
- email;
- reset URL;
- token;
- SMTP credentials;
- message body;
- user/customer identifiers.

Preserve:
- existing failed metric;
- existing bounded warning;
- callback return behavior;
- HTTP accepted behavior;
- current background execution model.

Do not import sentry_sdk outside app/infrastructure/sentry.py.
Do not introduce a generic reporter abstraction.
Do not move the whole password-reset implementation.

If an actual repository architecture guard rejects importing the application
Sentry adapter from this existing background boundary, stop and report the
contradiction instead of bypassing the guard.

Add focused mock-based tests proving:
- the new operation is accepted as "password_reset_email";
- the original delivery exception is reported once;
- category is integration_failure;
- no email/reset URL/token is supplied;
- callback still returns normally and existing diagnostic behavior remains.

Run targeted ruff format/check and exact focused pytest nodes only.

Stop on the first non-obvious failure.

Show diff/results and stop. Do not commit.
```

## Commit

```text
fix(api): report password reset email failures to Sentry
```

---

# R6 — Final documentation and contract alignment

## Goal

После runtime remediation снова привести authoritative docs и plan в состояние final/done.

## Inspect

```text
docs/exec-plans/active/ANY-458-implementation-plan.md
ARCHITECTURE.md
docs/RELIABILITY.md
docs/SECURITY.md
docs/architecture/deployment.md
```

Change only where needed.

## Final plan state

Set:

```text
Overall status -> done
Post-review remediation -> done
R1-R6 -> done
```

Final operation vocabulary:

```text
http_request
expire_subscriptions
password_reset_email
```

Keep historical original Steps 1–4 unchanged.

## Architecture

Clarify:

```text
central HTTP boundary -> default owner

existing catch-and-convert/absorb outer boundary
-> owns one explicit report if otherwise invisible upstream
```

No arbitrary Domain/Application reporting.

## Deployment

Document configured production Sentry DSN as HTTPS-only.

## Reliability

Include password-reset email failure as a reportable background/integration failure if needed for operational truth.

Do not invent new dashboards/alerts.

## Security

Existing privacy rules may already be sufficient.

Do not duplicate them unnecessarily.

## Codex prompt

```text
Implement ANY-458 remediation R6 only.

All runtime remediation R2-R5 should now be complete.

Perform only final documentation and plan truth-alignment.

Inspect:
- ANY-458 implementation plan;
- ANY-458-related ARCHITECTURE.md section;
- RELIABILITY.md;
- SECURITY.md;
- architecture/deployment.md.

Do not change runtime code or tests.

Update the implementation plan so:
- Overall status is done;
- post-review remediation status is done;
- R1-R6 are done;
- original Steps 1-4 remain the historical record and are not rewritten;
- the final current contract includes PASSWORD_RESET_EMAIL;
- production configured SENTRY_DSN requires HTTPS;
- Windows relative filenames normalize separators safely;
- catch-and-convert/absorb outer boundaries own one explicit report when the
  centralized boundary cannot see the failure.

Update ARCHITECTURE.md and deployment.md minimally where required.

Update RELIABILITY.md only where needed to reflect the final background
password-reset reporting behavior.

Update SECURITY.md only if the existing privacy contract is insufficient.

Preserve Sentry ownership:
Sentry = application error issues
OTel = traces
Prometheus/OTel = metrics
JSON logs = diagnostics
PostgreSQL = business truth

Run exactly once:
npm run docs:check

Stop on a non-obvious failure.

Show documentation diff/results and stop. Do not commit.
```

## Commit

```text
docs(api): finalize ANY-458 review remediation
```

---

# 6. Developer-owned final gates

После R6 Codex не запускает широкие проверки.

Пользователь запускает:

```bash
npm run architecture:check
npm run docs:check
npm run lock:check:api
npm run check:fast
```

Затем GitHub CI.

---

# 7. Out of scope

Не выполнять:

- CodeRabbit composition-root callable refactor;
- CodeRabbit массовую генерацию docstrings;
- CloudPayments redesign;
- CloudPayments decommission;
- email retry architecture;
- async email conversion;
- frontend Sentry;
- Sentry tracing/logging/metrics;
- generic monitoring abstraction;
- ANY-454;
- ANY-455;
- ANY-86;
- broad Sentry SDK investigation.

---

# 8. Definition of Done

ANY-458 можно отдавать на финальный approve, когда:

- original Steps 1–4 остаются completed;
- R1–R6 completed;
- production HTTP Sentry DSN rejected;
- production HTTPS DSN accepted;
- empty DSN still disables Sentry;
- safe Windows relative filenames preserved;
- unsafe paths rejected;
- webhook unexpected processing failure reported exactly once;
- webhook semantics unchanged;
- password-reset delivery failure reported exactly once;
- password-reset HTTP/background semantics unchanged;
- no email/token/reset URL/provider/payment sensitive data enters reporting;
- final Operation vocabulary remains closed;
- architecture/docs correspond to runtime;
- developer final gates pass;
- GitHub CI passes.