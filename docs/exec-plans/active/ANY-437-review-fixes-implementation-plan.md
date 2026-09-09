# ANY-437 — Review Fixes Implementation Plan v4

## Статус

- PR: `gushinets/payments-portal#84`
- Branch: `ANY-437`
- Reviewed head: `630c6e6f68de9dc5a5ded2031a7b8b966bce750f`
- Linear: `ANY-437 — Establish Observability & Correlation`
- Parent: `ANY-407`
- Architecture authority: `ANY-411`
- Error Architecture authority: `ANY-415`
- Next ANY-407 step: `ANY-454 — Establish Sync/Async Architecture`

Этот план предназначен только для устранения validated review findings уже реализованного ANY-437.

Использовать **один непрерывный Codex chat** с human review gate между шагами.

---

# 1. Итог после повторной валидации

Основной approved `docs/exec-plans/active/ANY-437 — Implementation Plan.md` остаётся execution authority.

Его не нужно перерабатывать целиком и нельзя переписывать задним числом под уже написанный код.

Однако review выявил **одну новую material tracing/privacy проблему**, которой не было в locked decisions исходного плана и которая теперь подтверждается реальным repository evidence.

Поэтому перед production fix требуется **узкая revision только affected tracing decision**.

Причинная последовательность:

```text
approved ANY-437 plan
-> implementation
-> review evidence reveals a real missed tracing/privacy risk
-> bounded plan revision for that one decision
-> human review
-> implementation
```

Не:

```text
implementation happened
-> rewrite the whole plan to justify it
```

Все остальные review findings являются implementation defects уже утверждённых решений и **не требуют изменения исходного плана**.

---

# 2. Почему tracing revision действительно требуется

Approved ANY-437 plan зафиксировал:

```text
The only shared trace change required is preventing arbitrary query values
from remaining in automatically generated server-span attributes.
```

Но текущий PR глобально изменил shared `@traced`:

```python
record_exception=False
set_status_on_exception=False
```

и добавил manual ERROR status.

Само по себе наличие такого кода не было бы причиной менять plan.

После повторной проверки найдено concrete current evidence:

1. OpenTelemetry `start_as_current_span()` по умолчанию:
   - `record_exception=True`;
   - `set_status_on_exception=True`;
   - exception event может содержать exception message и stacktrace.

2. Реальные production `@traced` consumers выполняют DB/provider-sensitive work.
   В частности CloudPayments webhook path внутри `@traced("cloudpayments.webhook.process")`:
   - принимает provider/account data;
   - создаёт `PaymentWebhookEvent`;
   - выполняет `db.flush()` / `db.commit()`;
   - persisted fields включают provider transaction/invoice/account/amount-related data.

3. SQLAlchemy engine создаётся без `hide_parameters=True`.

4. SQLAlchemy документирует, что без `hide_parameters=True` bound statement parameters могут попадать в string representation `StatementError`.

Следовательно существует реальный current path:

```text
real @traced HTTP operation
-> DB write/flush/commit failure
-> SQLAlchemy StatementError / wrapped DB error
-> exception text can include bound parameters
-> default OTel exception event / status description
-> prohibited provider/account/request data can enter trace telemetry
```

Это уже не synthetic test-only possibility.

Значит просто вернуть pre-PR `@traced` semantics без принятого решения нельзя.

При этом текущий global suppression тоже нельзя автоматически считать правильным:
- он меняет shared primitive repo-wide;
- нужно проверить всех current consumers;
- нужно проверить, не теряется ли единственный useful diagnostic;
- текущий `except BaseException` меняет control-flow/cancellation semantics относительно OpenTelemetry default behavior.

Поэтому требуется bounded plan-decision step.

---

# 3. Validated review findings

| Finding | Severity | Final handling |
|---|---:|---|
| HTTP query sanitizer может упасть на `//[` и прервать sanitization | P1 | implementation fix |
| deployment command test вызывает real environment/runtime setup | P2 | hermetic test fix |
| shared `@traced` получил material repo-wide exception semantics вне approved plan | P1 | bounded plan revision first, then implementation |
| expiry run может остаться без terminal diagnostic и выпустить partial transition chain | P2 | implementation fix |

---

# 4. Session-wide engineering rules

- Follow `ARCHITECTURE.md`, `apps/api/AGENTS.md`, `docs/engineering/CODING_CONVENTIONS.md`.
- Implement the **smallest coherent change**, not merely the fewest lines.
- Listed files are starting points, not a whitelist.
- Follow directly relevant callers/callees/consumers/tests/wiring only as far as evidence requires.
- Do not repeat broad ANY-407/ANY-411/ANY-415 research.
- Keep Core/observability free from feature business logic.
- Keep CLI as Presentation/Delivery; do not move lifecycle/business ownership into it.
- Do not introduce speculative repositories, services, interfaces, factories, job frameworks, generic telemetry frameworks, or dependencies without a current consumer.
- Preserve public APIs, billing semantics, transaction ownership, retry/idempotency, error propagation/chaining, and architecture boundaries.
- Do not pull ANY-454 sync/async/job-system redesign into ANY-437.
- Do not weaken tests that protect approved behavior.
- Tests introduced solely to lock an **unapproved implementation deviation** are not authority; they must be removed/reworked if the reviewed decision rejects that deviation.
- New/materially changed Python functions must be typed.
- Prefer explicit/readable code over clever/generalized code.
- No unrelated cleanup, rename, or formatting churn.

## Tooling rule

Use the repository's **canonical root Python environment**.

Do not create or use `apps/api/.venv`.

For focused Python tests/lint:
- use the already-existing repository-root `.venv` interpreter or the then-current repository-supported equivalent;
- do not run `uv run` in a way that creates a nested API virtualenv;
- run Ruff only for the changed Python scope during implementation steps;
- leave broad repository gates for the final gate.

---

# Step 0 — Resolve and revise the shared trace exception policy

## Goal

Resolve the one material review-evidence contradiction before changing production code.

This step is **research + approved-plan revision only**.

Do not modify production code or tests.

## Starting points

- `docs/exec-plans/active/ANY-437 — Implementation Plan.md`
- `apps/api/app/core/observability.py`
- `apps/api/app/http_errors.py`
- `apps/api/app/core/database.py`
- current direct production consumers of `@traced`
- directly relevant tests
- `ARCHITECTURE.md`
- `apps/api/AGENTS.md`
- `docs/engineering/CODING_CONVENTIONS.md`
- `docs/SECURITY.md`
- `docs/RELIABILITY.md`

Required local search:

```bash
rg "@traced|traced\(" apps/api/app apps/api/tests
```

## Evidence to revalidate

Confirm from the actual current environment/code:

1. installed OpenTelemetry defaults and exported failure data;
2. all current production `@traced` consumers;
3. which consumers can propagate DB/provider/untrusted exceptions;
4. whether SQLAlchemy error text can expose bound parameters in current engine configuration;
5. which enclosing diagnostics already exist for each consumer;
6. whether suppressing automatic exception events removes a duplicate unsafe signal or the only useful signal;
7. whether a global policy is justified or a narrower scoped policy is better;
8. normal `Exception` vs `BaseException` / cancellation/control-flow semantics.

## Required decision

Select the **smallest coherent safe semantics**.

The revision must define:

- which spans suppress automatic exception event recording;
- whether automatic status description is suppressed;
- how failure visibility is preserved safely;
- whether safe error type is needed;
- what happens for ordinary `Exception`;
- what happens for cancellation/control-flow `BaseException`;
- why the policy is global or scoped;
- representative current consumers proving the decision;
- focused tests required.

Do not pre-design future ANY-454/job behavior.

Do not change provider API tracing that is already classified as sufficient unless direct evidence proves it is part of this contradiction.

## Allowed file change

Only:

```text
docs/exec-plans/active/ANY-437 — Implementation Plan.md
```

Make the revision explicit as caused by implementation/review evidence.

Do not rewrite old research as if this decision had already existed.

Prefer a narrow revision of:
- Signal ownership / Traces;
- Step 1 affected decisions/invariants/tests;
- Step 5 docs expectations only if needed.

## Stop gate

After Step 0:
- STOP;
- show consumers inspected;
- show evidence;
- state selected semantics/tradeoff;
- show exact plan sections changed;
- do not implement production code;
- wait for human review.

Suggested plan-only commit after approval:

```text
docs(plan): revise ANY-437 trace exception policy
```

---

# Prompt — Step 0

```text
We are fixing review findings in `gushinets/payments-portal` PR #84 / ANY-437.

Use this same Codex chat for all review-fix steps, but STOP after this step for human review.

This is a bounded plan-decision step only.
Do not modify production code or tests.

The original approved `docs/exec-plans/active/ANY-437 — Implementation Plan.md` remains execution authority, but review evidence has now exposed one concrete material tracing/privacy gap that was not covered by its locked shared-trace decision.

Do not rewrite the plan broadly or retroactively justify already-written code.

Read:
- `docs/exec-plans/active/ANY-437 — Implementation Plan.md`
- `apps/api/app/core/observability.py`
- `apps/api/app/http_errors.py`
- `apps/api/app/core/database.py`
- all current direct production consumers of `@traced`
- directly relevant observability/error tests
- `ARCHITECTURE.md`
- `apps/api/AGENTS.md`
- `docs/engineering/CODING_CONVENTIONS.md`
- `docs/SECURITY.md`
- `docs/RELIABILITY.md`

Find all consumers with:

    rg "@traced|traced\(" apps/api/app apps/api/tests

These are starting points, not a whitelist. Follow only directly relevant exception/error/provider/DB paths required to decide the policy. Do not repeat broad ANY-407/ANY-411/ANY-415 research and do not investigate future ANY-454 execution architecture.

Revalidate the concrete review evidence:

- the installed OpenTelemetry `start_as_current_span()` behavior records uncaught exceptions by default and can export exception message/stacktrace and an error status description;
- real current `@traced` consumers perform DB/provider-sensitive work;
- CloudPayments webhook processing is one concrete consumer that persists provider/account/business data while inside `@traced`;
- the current SQLAlchemy engine does not enable `hide_parameters=True`;
- SQLAlchemy StatementError-style failures may render bound parameters when they are not hidden.

Determine from current code and a minimal local/in-memory reproduction where needed:

1. Which current production `@traced` consumers can propagate exception text containing prohibited provider/account/request/PII/payment data.
2. What default OpenTelemetry exports for representative real failure shapes.
3. Which existing bounded diagnostics/span status/metrics remain if automatic exception events are suppressed.
4. Whether suppression should apply to the shared decorator globally or only to a narrower current subset.
5. Whether a safe low-cardinality error type is needed to preserve useful trace diagnostics.
6. How normal `Exception` should be handled.
7. How cancellation/control-flow failures that inherit directly from `BaseException` should be handled. Do not silently preserve the current PR's `except BaseException` if it changes default OpenTelemetry semantics without justification.
8. Whether any non-HTTP consumer would lose its only meaningful diagnostic.
9. Which focused regression tests are required.

Select the smallest coherent policy that satisfies:
- ANY-437 privacy/security invariants;
- ANY-415 single bounded unexpected-error ownership;
- useful trace failure visibility;
- no duplicate unexpected-error reporting;
- no future/job architecture work.

Do not assume the current global suppression implementation is correct merely because it exists.
Do not assume restoring `main` semantics is safe now that a real current privacy path has been found.

Update only:

    docs/exec-plans/active/ANY-437 — Implementation Plan.md

Clearly mark the affected decision as a revision caused by implementation/review evidence. Do not rewrite unrelated plan sections or history.

At the end:
1. list the real production consumers inspected;
2. show the concrete privacy/diagnostic evidence;
3. state the selected trace exception semantics and tradeoff;
4. show the exact plan sections changed;
5. identify any remaining human decision;
6. STOP.

Do not modify production code or tests.
Do not stage or commit.
```

---

# Step 1 — Implement shared observability/privacy review fixes

## Prerequisite

Step 0 plan revision has been human-reviewed and approved.

## Goal

Resolve in one coherent change:

1. `@traced` semantics exactly as approved by revised Step 0 decision;
2. non-throwing HTTP query sanitization;
3. Uvicorn access-log privacy boundary;
4. hermetic deployment command test.

## Starting points

- revised ANY-437 plan
- `apps/api/app/core/observability.py`
- `apps/api/app/http_errors.py`
- `apps/api/app/main.py`
- `apps/api/Dockerfile`
- `docker-compose.yml`
- `docker-compose.agent.yml`
- `docker-compose.prod.yml`
- `scripts/repo.py`
- `apps/api/tests/test_observability.py`
- `apps/api/tests/test_deployment_contract.py`
- directly affected error tests

Search:

```bash
rg "@traced|traced\(" apps/api/app apps/api/tests
rg "uvicorn|--access-log|--no-access-log" .
```

## 1.1 `@traced`

Implement exactly the reviewed policy from Step 0.

Do not invent a third design while coding.

Preserve:
- sync/async wrapping;
- resolved function signatures;
- exception propagation/chaining;
- ANY-415 bounded HTTP failure ownership;
- control-flow/cancellation semantics approved in Step 0.

If the approved policy suppresses automatic exception events:
- do not emit raw exception text/traceback as replacement;
- preserve safe failure visibility exactly as the revised plan defines.

Tests introduced in the current PR solely to lock the previous unapproved global suppression must be aligned with the reviewed policy:
- keep/rework them where they protect the approved contract;
- remove/revert assertions that exist only to enforce a rejected deviation.

Do not weaken tests protecting approved query/privacy/error-boundary behavior.

## 1.2 Query sanitizer

Must be:

- non-throwing by construction for arbitrary untrusted string values;
- independent of URL authority validity when the task is only query/fragment removal;
- resilient so one problematic attribute cannot abort sanitization attempts for remaining applicable attributes;
- safe for `http.target`, `http.url`, `url.full`, `url.query` as present;
- path/route preserving;
- non-masking of application response/error.

Add a real exported SERVER-span regression for:

```text
//[?custom=review-query-marker-437
```

Verify the unique marker is absent from all relevant exported SERVER span content, including attributes/events/status descriptions where applicable.

## 1.3 Uvicorn access logs

Revalidate all repository-owned API startup paths.

Current evidence shows:
- Docker development CMD uses `--no-access-log`;
- Docker production CMD uses `--no-access-log`;
- root/agent/prod Compose use the corresponding image CMD rather than replacing the API command;
- `scripts/repo.py::cmd_dev_api()` uses `--no-access-log`.

If search confirms no other supported Uvicorn path, do not make additional runtime changes.

Keep application-owned:

```text
payment_portal.http / http_request_complete
```

## 1.4 Hermetic deployment test

`test_dev_api_command_disables_access_logging` must isolate the command-construction boundary.

Stub:

```text
direct_api_environment()
```

or the actual owning equivalent if code has changed.

The test must not:
- call `read_runtime_env()` for this assertion;
- create/modify `.harness`;
- write runtime config;
- change ACLs;
- depend on machine permissions;
- depend on real `.env`.

Do not deep-mock harness internals when one boundary stub is sufficient.

## Focused verification

Use the existing repository-root Python environment.

Do not create `apps/api/.venv`.

Run:
- focused pytest for changed observability/error/deployment tests;
- Ruff check/fix and format only for actually changed Python files;
- report the exact commands used.

Do not run full repository gates in this step.

## Stop gate

After Step 1:
- STOP;
- show changed files;
- finding → resolution mapping;
- confirm implementation matches revised trace decision exactly;
- show startup paths revalidated;
- show focused test/Ruff results;
- suggested commit.

Suggested commit:

```text
fix(api): address observability privacy review findings
```

---

# Prompt — Step 1

```text
Continue in the same Codex chat with Step 1 of the ANY-437 PR #84 review fixes.

Prerequisite:
the Step 0 revision of `docs/exec-plans/active/ANY-437 — Implementation Plan.md` has been human-reviewed and is now execution authority.

Re-read the final revised trace exception decision before editing.

Start from:
- revised ANY-437 plan
- `apps/api/app/core/observability.py`
- `apps/api/app/http_errors.py`
- `apps/api/app/main.py`
- `apps/api/Dockerfile`
- `docker-compose.yml`
- `docker-compose.agent.yml`
- `docker-compose.prod.yml`
- `scripts/repo.py`
- `apps/api/tests/test_observability.py`
- `apps/api/tests/test_deployment_contract.py`
- directly affected error tests

Validate impact with:

    rg "@traced|traced\(" apps/api/app apps/api/tests
    rg "uvicorn|--access-log|--no-access-log" .

These are starting points, not a whitelist. Follow only directly relevant consumers/wiring/tests needed for a correct implementation.

1. Implement exactly the reviewed `@traced` exception semantics from the revised plan.

Do not invent a different policy during coding.

Preserve:
- sync/async wrapping;
- function signatures;
- exception propagation/chaining;
- ANY-415 single bounded unexpected HTTP failure ownership;
- the approved Exception versus BaseException/cancellation behavior.

Do not add duplicate exception logging or raw exception telemetry.

The current PR contains tests created specifically for its earlier unapproved global suppression behavior. Align them with the reviewed decision:
- preserve/rework tests that protect the approved policy;
- remove/revert assertions that exist only to lock a rejected implementation deviation.
This is not permission to weaken tests that protect approved query/privacy/error-boundary behavior.

2. Make HTTP server span query sanitization non-throwing.

A request target equivalent to:

    //[?custom=review-query-marker-437

must not make the server_request_hook raise or abort sanitization.

Requirements:
- non-throwing by construction for arbitrary untrusted string values;
- do not use authority-aware URL parsing when only query/fragment removal is required;
- one problematic attribute must not prevent sanitization attempts for remaining applicable attributes;
- clear query values from `http.target`, `http.url`, `url.full`, and `url.query` when present;
- preserve useful path/route identification;
- do not capture arbitrary headers;
- never mask the application result/error.

Add a real exported HTTP SERVER-span regression for the malformed double-slash/bracket request.
Verify the marker is absent from all relevant exported SERVER span data, not only one hard-coded attribute.

3. Revalidate repository-owned Uvicorn startup paths.

Standard `uvicorn.access` must remain disabled.

Current evidence indicates Docker development/production CMDs and `scripts/repo.py::cmd_dev_api()` already use `--no-access-log`, while Compose does not override the API command. Confirm by repository search.

If all supported paths are covered, do not make unnecessary runtime changes.

Keep `payment_portal.http` / `http_request_complete`.

4. Make `test_dev_api_command_disables_access_logging` hermetic.

Stub `direct_api_environment()` or the actual owning environment boundary with controlled data.

The test must not create/modify `.harness`, call real runtime setup, write files, change ACLs, depend on real `.env`, or depend on machine filesystem permissions.

Engineering constraints:
- smallest coherent change;
- no business logic in Core;
- no speculative abstractions/frameworks/dependencies;
- no unrelated refactoring;
- typed materially changed functions;
- preserve public API/billing/transaction/retry/idempotency semantics.

Tooling:
- use the repository-root canonical Python environment;
- do not create/use `apps/api/.venv`;
- run focused pytest for the changed observability/error/deployment scope;
- run Ruff check/fix and format only for changed Python files;
- do not run broad/full repository gates.

At the end:
1. show changed files;
2. map every review finding in this step to the exact fix;
3. confirm the trace implementation matches the revised plan;
4. list the Uvicorn startup paths checked;
5. report exact focused test/Ruff commands and results;
6. report remaining risks;
7. suggest commit message;
8. STOP.

Do not stage or commit.
```

---

# Step 2 — Close scheduled-expiry terminal diagnostic boundary

## Goal

Fix the expiry CLI review defect without changing lifecycle or transaction ownership.

After:

```text
subscription_expiry_run_started
```

a lifecycle or post-return validation/preparation failure must produce exactly one:

```text
subscription_expiry_run_failed
```

A successful committed and fully validated result must produce:

```text
transition_committed*
-> run_succeeded
```

## Starting points

- `apps/api/app/commands/expire_subscriptions.py`
- `apps/api/tests/test_expire_subscriptions_cli.py`
- `apps/api/app/domains/billing/service/support.py`
- `apps/api/app/domains/billing/service/lifecycle_operations.py`
- `Subscription` model only as required

## Revalidate before edit

Confirm:
1. fresh `SessionLocal`;
2. no pre-lifecycle DB work opening an outer transaction;
3. `_transactional` owns the transaction in this CLI path;
4. successful `expire_due_subscriptions()` return follows lifecycle-owned commit;
5. no outer `db.commit()` is needed.

If any assumption is false:
- STOP;
- do not redesign transaction ownership.

## Required structure

Conceptually:

```text
run_started

try:
    expired = expire_due_subscriptions(...)
    subscription_ids = validate_and_collect_all_ids(expired)
except Exception:
    run_failed
    raise

for subscription_id in subscription_ids:
    transition_committed

run_succeeded
```

Critical invariant:

```text
validate the COMPLETE returned result before emitting ANY per-transition diagnostic
```

## Identity / SQL constraint

The current implementation uses SQLAlchemy inspection to obtain persisted identity without triggering post-commit SQL.

Do not introduce a re-query/refresh merely for telemetry.

Preserve the existing property that transition diagnostic preparation does not issue additional SQL after the lifecycle function returns.

Use the smallest correct identity extraction consistent with this contract.

## Failure event

Exactly one:

```text
subscription_expiry_run_failed
```

Allowed:
- `run_id`
- `batch_size`
- `error_type`

Forbidden:
- `logger.exception`
- `exc_info`
- raw exception message
- traceback
- sensitive/untrusted values

Preserve original exception propagation.

## Required regression

Do not test only a single invalid object.

Use a result where an earlier element is valid and a later element is invalid, for example:

```text
[
  persisted/detached Subscription with valid identity,
  Subscription without persisted identity,
]
```

This specifically proves the reviewer’s late-failure case.

Assert:
- one `run_started`;
- exactly one `run_failed`;
- **zero** `transition_committed` even though the first result was valid;
- zero `run_succeeded`;
- raw exception text absent;
- original exception propagates.

Also preserve successful tests proving:
- stable `run_id`;
- local IDs;
- transitions after lifecycle return;
- no post-return SQL;
- stdout exactly `expired_subscriptions=<N>`;
- no outer commit.

## Focused verification

Use repository-root canonical Python environment.

Do not create `apps/api/.venv`.

Run focused expiry tests and Ruff only for changed files.

## Stop gate

After Step 2:
- STOP;
- show changed files;
- show terminal-outcome behavior;
- prove no partial transition chain;
- prove transaction ownership unchanged;
- confirm no post-return SQL was introduced;
- show tests/Ruff;
- suggested commit.

Suggested commit:

```text
fix(api): close expiry diagnostic failure boundary
```

---

# Prompt — Step 2

```text
Continue in the same Codex chat with Step 2 of the ANY-437 PR #84 review fixes.

Use the current reviewed branch state and approved ANY-437 plan.

Start from:
- `apps/api/app/commands/expire_subscriptions.py`
- `apps/api/tests/test_expire_subscriptions_cli.py`
- `apps/api/app/domains/billing/service/support.py`
- `apps/api/app/domains/billing/service/lifecycle_operations.py`
- the Subscription model only if required to validate identity behavior

These are starting points, not a whitelist. Follow only directly relevant transaction/session/model/test code.

Before editing confirm from current code:
1. CLI creates a fresh SessionLocal;
2. no DB work before `expire_due_subscriptions()` opens an outer transaction;
3. `_transactional` owns the transaction in this path;
4. successful lifecycle return follows its commit;
5. no explicit outer `db.commit()` is needed.

If any assumption is false, STOP and report. Do not redesign transaction ownership.

Validated defect:
post-return identity validation can fail after `subscription_expiry_run_started`, outside the current failure boundary, and can occur after earlier per-transition logs.

Required behavior:

    run_started

    try:
        expired = expire_due_subscriptions(...)
        subscription_ids = validate_and_collect_all_ids(expired)
    except Exception:
        run_failed
        raise

    for subscription_id in subscription_ids:
        transition_committed

    run_succeeded

Validate the complete returned result before emitting any `subscription_expiry_transition_committed`.

Keep application/validation failure handling bounded:
- exactly one `subscription_expiry_run_failed`;
- safe fields only: run_id, batch_size, error_type;
- no logger.exception;
- no exc_info;
- no raw exception text/traceback;
- preserve original exception propagation.

Do not treat a telemetry backend/logging infrastructure failure after a successful business commit as a business rollback.

Preserve transaction ownership:
- no outer commit;
- no `_transactional` redesign;
- no job/scheduler framework;
- no request ContextVar;
- no persistent run model.

Preserve the existing no-post-return-SQL property used by the CLI tests.
Do not re-query or refresh subscriptions merely to produce diagnostic IDs.

Regression requirement:
return at least two items where:
- an earlier item has a valid persisted/detached identity;
- a later item has no persisted identity (or the closest real invalid state).

Assert:
- one run_started;
- exactly one run_failed;
- zero transition_committed, including for the earlier valid item;
- zero run_succeeded;
- raw exception text absent;
- original exception propagates.

Preserve successful behavior:
- stable run_id;
- local subscription IDs;
- transition diagnostics after lifecycle return;
- no post-return SQL;
- stdout exactly `expired_subscriptions=<N>`;
- no explicit outer commit.

Engineering/tooling:
- smallest coherent change;
- keep lifecycle/business responsibility outside CLI;
- no speculative abstractions;
- use repository-root canonical Python environment;
- do not create/use `apps/api/.venv`;
- run focused expiry tests;
- run Ruff check/fix and format only for changed Python files;
- do not run broad/full repository gates.

At the end:
1. show changed files;
2. explain exact success/failure terminal behavior;
3. show how the regression proves no partial transition chain;
4. confirm transaction ownership unchanged;
5. confirm no post-return SQL was introduced;
6. report exact focused test/Ruff commands and results;
7. report risks;
8. suggest commit message;
9. STOP.

Do not stage or commit.
```

---

# Step 3 — Final merge gate

After Step 0 plan revision is reviewed/committed and Step 1 + Step 2 implementation diffs are reviewed/committed:

## Combined focused regression

Run the affected focused tests using the repository-root canonical Python environment:

```text
test_observability.py
test_error_handling.py
test_deployment_contract.py
test_expire_subscriptions_cli.py
```

Use the then-current repository-supported invocation.

Do not create `apps/api/.venv`.

## Repository gates

`npm run check:fast` already includes API fast tests through repository tooling, so do **not** immediately repeat `npm run test:api:fast`.

Run:

```bash
npm run check:fast

make test_db_up
npm run test:api:postgres
make test_db_stop
```

Then rely on / require the full applicable PR CI gate before merge.

If running the complete local gate instead of CI, follow the then-current repository-supported `npm run check` flow with the required PostgreSQL test server available.

---

# Final checklist

## Plan authority

- [ ] only the affected tracing decision was revised;
- [ ] revision explicitly records that it came from implementation/review evidence;
- [ ] no unrelated original plan history was rewritten;
- [ ] revision was human-reviewed before trace production code changed.

## `@traced`

- [ ] every real current production consumer was enumerated;
- [ ] exception privacy risk was tested using representative real failure shapes;
- [ ] selected policy is global/scoped for a documented reason;
- [ ] useful failure visibility remains;
- [ ] no raw exception message/stacktrace is reintroduced by replacement telemetry;
- [ ] `Exception` vs `BaseException`/cancellation behavior is intentional;
- [ ] ANY-415 single bounded unexpected-error ownership remains intact.

## Query privacy

- [ ] malformed `//[` regression covered;
- [ ] sanitizer non-throwing;
- [ ] one attribute cannot abort remaining sanitization attempts;
- [ ] unique marker absent from all relevant exported SERVER span data;
- [ ] useful path/route identification remains.

## Uvicorn / deployment

- [ ] Docker development/production startup paths checked;
- [ ] Compose overrides checked;
- [ ] direct repo dev command checked;
- [ ] `uvicorn.access` remains disabled;
- [ ] safe application-owned request diagnostic remains;
- [ ] deployment command test is hermetic;
- [ ] no `.harness`/ACL/real env side effects.

## Expiry

- [ ] lifecycle/validation failure -> exactly one `run_failed`;
- [ ] valid-then-invalid regression -> zero partial transition diagnostics;
- [ ] complete result validation before any transition log;
- [ ] successful path -> transitions then `run_succeeded`;
- [ ] no post-return SQL introduced for telemetry;
- [ ] no outer commit;
- [ ] transaction ownership unchanged;
- [ ] raw error text absent.

## Scope

- [ ] no persistence redesign;
- [ ] no DI redesign;
- [ ] no sync/async/job-system redesign from ANY-454;
- [ ] no speculative observability framework;
- [ ] no unrelated refactoring.

---

# Expected commits

```text
docs(plan): revise ANY-437 trace exception policy
fix(api): address observability privacy review findings
fix(api): close expiry diagnostic failure boundary
```
