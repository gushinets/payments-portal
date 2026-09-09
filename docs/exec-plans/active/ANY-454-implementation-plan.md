# ANY-454 — Establish Sync / Async Architecture

## Plan Overview

| Field | Value |
| --- | --- |
| Parent | `ANY-407` |
| Ticket | `ANY-454` |
| ANY-407 step | Step 4 — Sync / Async Architecture |
| Plan status | `reviewed / conditionally approved; execution blocked by ANY-437 merge + narrow post-merge revalidation` |
| Execution model | `Domain / Application / Persistence → sync-first`; `async → only unavoidable framework / genuinely awaitable I/O boundaries` |
| Migration intent | **Not an async migration. The application remains synchronous.** |
| Implementation order | predecessor gate → Step 1 → manual verification → commit → Step 2 → manual verification → commit → Step 3 → manual verification → commit → final verification |
| Steps / commits | 3 |
| Schema changes | none |
| Public API changes | none |
| Persisted semantics changes | none |
| New libraries/frameworks | none |

---

## Architectural intent

ANY-454 does **not** convert Payment Portal to an asynchronous application architecture.

The target remains:

```text
FastAPI / ASGI framework shell
    -> async only where required by the framework or real awaitable I/O

Presentation request handlers for current DB/application flows
    -> synchronous `def`

Application
    -> synchronous

Domain
    -> synchronous

Persistence / SQLAlchemy
    -> synchronous

Current synchronous integrations
    -> synchronous
```

The purpose of this ticket is only to remove blocking synchronous work from FastAPI event-loop paths and to establish one reusable framework-boundary pattern where unavoidable ASGI work is asynchronous.

Do not interpret the presence of an async lifespan, middleware, or raw request-body dependency as permission to propagate async into Application, Domain, Persistence, or current synchronous integrations.

---

## Pre-implementation gate — ANY-437

`ANY-437` / PR #84 is the immediate predecessor and must be merged/accepted before implementation of ANY-454 starts.

The research for this plan was performed against the current ANY-437 PR state. After it is merged, do **not** repeat broad repository research. Before Step 1, narrowly revalidate only the assumptions that can affect this plan:

- `apps/api/app/integrations/cloudpayments/router.py`
- `apps/api/app/integrations/cloudpayments/adapter.py`
- `apps/api/app/integrations/cloudpayments/processing.py`
- `apps/api/app/main.py`
- `apps/api/app/core/database.py`
- `apps/api/app/core/observability.py`
- `apps/api/app/http_errors.py`
- `apps/api/app/http_dependencies.py` if it exists after predecessor merge
- `apps/api/tests/test_api.py`
- `apps/api/tests/test_cloudpayments_webhook_postgres.py`
- `apps/api/tests/test_observability.py`
- `ARCHITECTURE.md`
- `docs/RELIABILITY.md`
- `docs/engineering/CODING_CONVENTIONS.md`

The following assumptions must still be true:

1. SQLAlchemy remains synchronous and `get_db()` owns a synchronous request-scoped `Session`.
2. CloudPayments webhook remains the DB-heavy HTTP path currently declared as `async def`.
3. CloudPayments normalization still has no genuine async I/O after raw request-body acquisition.
4. Provider server API remains based on synchronous `httpx.Client`.
5. ANY-437 request/trace/log correlation and safe webhook diagnostics remain materially as researched.
6. No predecessor change has already established another reviewed sync/async execution mechanism.
7. No shared Presentation/HTTP raw-body dependency already exists under another authoritative module name.

If final ANY-437 materially contradicts any of these assumptions, stop and update this plan rather than adapting the architecture during execution.

---

# Research Result

## Verified execution inventory

| Runtime surface | Current execution | Classification | ANY-454 action |
| --- | --- | --- | --- |
| Identity/account DB-heavy FastAPI routes | normal `def` + sync `Session` | framework-managed sync/threadpool | keep |
| Billing DB-heavy FastAPI routes | normal `def` + sync `Session` | framework-managed sync/threadpool | keep |
| Legal DB-heavy FastAPI routes | normal `def` + sync `Session` | framework-managed sync/threadpool | keep |
| Metrics/ordinary simple sync routes | normal `def` | framework-managed sync/threadpool | keep |
| `request_context_middleware` | `async def`, awaits `call_next` | genuine framework async boundary | keep |
| `unexpected_failure_middleware` | `async def`, awaits `call_next` | genuine framework async boundary | keep |
| CloudPayments webhook route | `async def`; reads body asynchronously and then performs sync SQLAlchemy processing | **confirmed event-loop blocking boundary** | fix |
| CloudPayments raw request-body acquisition | `await request.body()` | unavoidable ASGI/framework I/O | isolate in shared HTTP dependency |
| `CloudPaymentsAdapter.normalize_webhook_request()` | `async def`, but only awaits parser with no async I/O | incidental async | make sync |
| `_parse_payload()` | `async def`, no real await/I/O | incidental async | make sync |
| CloudPayments webhook processing | synchronous SQLAlchemy/domain calls | sync application/integration processing | keep sync |
| Provider server API client | sync `httpx.Client`, bounded timeout/retries/backoff | blocking integration I/O | keep sync and keep off event loop |
| FastAPI lifespan | async framework lifecycle | unavoidable framework async boundary | keep async |
| Legal seed inside lifespan | synchronous SQLAlchemy inside async lifespan | **confirmed lifecycle event-loop blocking** | offload complete resource-owning unit |
| CloudPayments client shutdown | synchronous client cleanup inside async lifespan | transitional sync resource cleanup | execute through framework worker mechanism while integration exists |
| Password-reset email `BackgroundTask` | synchronous callback | framework-managed worker-thread work | keep |
| Scheduled subscription expiry | synchronous CLI | non-HTTP sync execution | keep |
| `@traced` | explicitly supports both sync and async functions | boundary-neutral wrapper | keep |
| PostgreSQL webhook concurrency/idempotency tests | concurrent requests with real locking | current semantic regression baseline | preserve and rerun |

## Confirmed problems

There are two production execution boundaries requiring code changes.

### 1. CloudPayments webhook

Current call flow is effectively:

```text
FastAPI event loop
    -> async receive_cloudpayments_webhook()
        -> await request.body()
        -> await normalize_webhook_request()
            -> await _parse_payload()
                -> synchronous parsing only
        -> synchronous Session queries
        -> flush / commit / refresh
        -> synchronous process_webhook_event()
        -> lifecycle and SQLAlchemy work
        -> commit / rollback
```

Only raw request-body acquisition is genuinely asynchronous because it consumes the ASGI request stream.

The remainder of the chain is synchronous and must not continue on the event loop.

The raw-body concern is not CloudPayments-specific. Exact request bytes may also be needed by another webhook/signature boundary later. The ASGI read should therefore exist once as a shared HTTP transport dependency rather than being reimplemented in integration routers.

### 2. FastAPI lifespan

Current startup/shutdown shape is:

```text
async lifespan()
    -> create sync CloudPayments client
    -> SessionLocal()
    -> seed_legal_documents(...)
    -> yield
    -> cloudpayments_adapter.close()
```

Creating the current CloudPayments client object itself does not establish a network operation and does not require async initialization or thread offloading without concrete evidence of blocking work.

The synchronous legal-seed unit performs persistence work directly from the async lifespan and therefore should execute outside the event loop.

While the transitional CloudPayments integration remains wired into the application, its synchronous cleanup must also not block the event loop. This cleanup handling is temporary runtime safety for the current integration, **not** a permanent provider lifecycle abstraction.

---

# Locked Architecture Decisions

## 1. Sync-first application remains unchanged

Keep:

```text
Domain
Application
Persistence
provider-neutral business operations
current synchronous integrations
    -> synchronous by default
```

Do not introduce:

- `AsyncSession`;
- async SQLAlchemy engine;
- duplicate sync/async service trees;
- generic async/sync gateway abstractions;
- custom executors;
- a repository redesign;
- a generic job/worker framework.

## 2. FastAPI owns normal request worker dispatch

For HTTP use cases implemented with synchronous SQLAlchemy or other blocking libraries, use ordinary synchronous FastAPI path operations.

Do not wrap the whole current webhook handler manually in a thread call while passing its already-resolved `Session` into another execution context.

Instead:

```text
shared async HTTP dependency
    -> read exact raw request bytes

sync FastAPI endpoint
    -> normalize already-buffered bytes
    -> use request-scoped sync Session
    -> process application/domain logic synchronously
```

FastAPI/Starlette owns the framework worker dispatch for the synchronous endpoint.

Do not depend on a particular OS-thread identity between dependency resolution and endpoint execution. The invariant is that application code does not manually create a cross-thread `Session` handoff or concurrent `Session` use.

## 3. Raw request-body acquisition is a shared HTTP transport concern

Create or reuse one shared Presentation/HTTP dependency for exact raw request bytes.

Current baseline has no dedicated shared HTTP dependency module, so the expected location is:

```text
apps/api/app/http_dependencies.py
```

If final merged ANY-437 introduces an authoritative equivalent location, reuse it instead of creating a duplicate module.

The dependency should remain minimal and explicitly typed:

```python
async def get_raw_request_body(request: Request) -> bytes:
    return await request.body()
```

Its responsibility ends after returning the bytes.

It must not own:

- parsing;
- Pydantic validation;
- signature verification;
- SQLAlchemy;
- application/domain calls;
- logging policy;
- provider-specific behavior.

Usage policy:

- routes that require the **exact raw request bytes** for a concrete transport concern such as webhook signature verification should reuse this dependency;
- ordinary JSON API routes should continue to use normal FastAPI/Pydantic request models;
- do not read `Request.body()` directly in individual routers when the shared dependency satisfies the requirement;
- do not use raw-body handling merely to avoid defining proper request schemas.

This shared dependency is an HTTP transport utility, not an async application abstraction.

## 4. CloudPayments normalization becomes synchronous

Once raw request bytes already exist:

- content-type inspection;
- JSON/form parsing;
- signature verification;
- hash calculation;
- redaction;
- Pydantic normalization

are synchronous operations.

`normalize_webhook_request()` and its internal payload parser must therefore become ordinary synchronous functions.

Do not convert them to a new async parser or introduce async solely for symmetry.

## 5. Lifespan remains async only as a framework boundary

`lifespan()` remains `async` because FastAPI lifespan is an ASGI/framework lifecycle boundary.

This does **not** make startup persistence or the application architecture asynchronous.

For blocking startup work, use the existing Starlette/AnyIO worker mechanism rather than creating a custom executor.

The synchronous worker unit that seeds legal documents must itself own the complete resource lifecycle:

```text
create Session
-> perform seed
-> close Session
```

The `Session` must not be created on the event-loop side and handed into worker code.

## 6. Current provider client remains synchronous

The current provider API client intentionally owns:

- bounded timeout budgets;
- safe retries;
- retry backoff;
- idempotency handling;
- ambiguous/unknown-outcome semantics;
- safe error mapping and redaction.

ANY-454 must not rewrite it to `httpx.AsyncClient`.

Its blocking nature is acceptable as long as it is reached only from a synchronous execution context.

CloudPayments is transitional under ANY-407. Its current construction/cleanup wiring must not be generalized into permanent provider lifecycle architecture. When CloudPayments is decommissioned, its initialization and cleanup wiring should disappear with it.

## 7. Threadpool capacity is not tuned here

FastAPI/Starlette worker threads are shared capacity.

ANY-454 must not:

- change global AnyIO thread limits;
- create a dedicated thread pool;
- add unbounded blocking work;
- add new sleeps/retries.

The existing bounded provider timeout/retry policy remains important because cancellation of an HTTP task does not imply forcible interruption of arbitrary synchronous worker code.

## 8. Observability context must survive framework worker boundaries

ANY-437 establishes request ID, trace and business-diagnostic correlation.

The resulting synchronous webhook execution must preserve that context.

Do not:

- introduce a fresh request ID;
- manually reconstruct trace context;
- create a second logging context;
- change existing safe diagnostic fields;
- serialize raw webhook/request data.

Add focused regression coverage proving the existing request ID and trace/span correlation remain available from inside the synchronous webhook execution boundary.

Do not add manual `ContextVar` copying unless authoritative evidence shows the framework path does not propagate the required context.

## 9. Future integrations do not change this ticket

A future genuinely asynchronous external-billing integration does not justify making current Application/Persistence async.

Future integration execution modality must follow its **actual I/O client** and remain at the outer boundary.

A future integration may be sync or async without forcing that modality into Domain/Application/Persistence.

Do not pre-build:

- an async gateway protocol;
- sync and async copies of use cases;
- `asyncio.run()` bridges inside the core;
- a speculative LBX/Dodo execution model.

## 10. No broad async AST rule

A repository-wide rule such as "domain may never contain `async def`" or "all routes using DB must be syntactically sync" would be broader than the confirmed problem and could reject legitimate framework/I/O boundaries.

Use focused regression coverage for the current boundaries plus explicit coding conventions.

The shared raw-body dependency should be the documented standard, but ANY-454 does not introduce a repository-wide scanner banning every direct `Request.body()` call.

---

# Explicitly deferred work

The following findings are intentionally **not** part of ANY-454:

- SQLAlchemy/query/write mechanics currently mixed into use cases → `ANY-455`, Persistence Boundary.
- webhook commit/rollback ownership, transaction scope, lock ordering, idempotency architecture → ANY-407 Step 6.
- broad FastAPI DI/composition/resource lifecycle redesign → later ANY-407 step.
- broad provider lifecycle abstraction → later step only if concretely required.
- durable email jobs / generic worker infrastructure → separate requirement, not ANY-454.
- future external-billing client modality/design → its concrete integration ticket.
- CloudPayments business/state-machine cleanup → later business/domain work.
- CloudPayments decommission implementation → separate cutover/decommission work when its criteria are met.
- new persistence schema or migrations.

---

# Step 1 — Establish the shared raw-body boundary and make CloudPayments webhook processing synchronous

**Status:** `todo`

## Goal

Keep only unavoidable ASGI raw-request-body acquisition asynchronous, centralize that acquisition in one reusable HTTP dependency, and execute DB-heavy CloudPayments webhook processing through FastAPI's normal synchronous endpoint model.

At the same time, remove incidental async from CloudPayments normalization and prove that ANY-437 correlation survives framework worker dispatch.

## Scope / affected code

Primary production code:

- `apps/api/app/http_dependencies.py` — new shared HTTP dependency module unless an equivalent exists after ANY-437 merge;
- `apps/api/app/integrations/cloudpayments/router.py`;
- `apps/api/app/integrations/cloudpayments/adapter.py`.

Focused tests:

- `apps/api/tests/test_api.py`;
- `apps/api/tests/test_cloudpayments_webhook_postgres.py`;
- `apps/api/tests/test_architecture.py` only if the focused shared-boundary guard fits the existing architecture-test organization.

Do not change `processing.py` business/persistence responsibilities except if a mechanical call-site adjustment is strictly necessary.

## Implementation decisions

### 1. Add/reuse one shared raw-body HTTP dependency

If the final repository still has no shared equivalent, add:

```text
apps/api/app/http_dependencies.py
```

with a minimal typed dependency equivalent to:

```python
async def get_raw_request_body(request: Request) -> bytes:
    return await request.body()
```

Keep FastAPI/Starlette imports and ASGI request-body mechanics in this Presentation/HTTP utility.

Do not move this helper into Domain, Application, Persistence, or a provider integration module.

Do not add provider-specific logic to it.

### 2. Reuse the shared dependency from CloudPayments

The CloudPayments webhook must depend on already-buffered raw bytes supplied by the shared dependency.

Do not keep a local CloudPayments-specific `read_raw_body()` implementation if the shared dependency exists.

Do not add a second body reader for form vs JSON payloads; content parsing happens synchronously after the exact bytes are available.

### 3. Make the webhook route synchronous

Change `receive_cloudpayments_webhook()` to an ordinary synchronous `def`.

Keep the current request-scoped synchronous `Session` through the existing `get_db` dependency.

Do not manually invoke `run_in_threadpool()` around the route body and do not pass `Session` objects through a manually created thread boundary.

### 4. Make normalization synchronous

Change:

- `_parse_payload(...)`;
- `CloudPaymentsAdapter.normalize_webhook_request(...)`

to synchronous functions.

Remove obsolete `await` calls.

Do not alter:

- signature verification;
- JSON/form parsing behavior;
- safe payload redaction;
- header redaction;
- payload hash;
- event ID/idempotency calculation;
- Pydantic normalization;
- validation errors;
- webhook response-code mapping.

### 5. Preserve public HTTP/OpenAPI contract

The execution-model change must not alter the public endpoint contract.

Add explicit typing required by current coding conventions, but do not accidentally introduce a new inferred FastAPI response model or change generated OpenAPI.

If a return annotation would cause schema inference that differs from the current API contract, keep the public contract explicit using the existing project/FastAPI mechanism rather than accepting schema drift.

### 6. Preserve current persistence and lifecycle semantics exactly

Do not change the existing sequence of:

- initial safe webhook receipt;
- flush/commit/refresh;
- subsequent processing;
- rollback/failure persistence;
- final event status;
- webhook acknowledgement.

Do not move commits or locks.

Step 6 of ANY-407 owns those concerns.

### 7. Preserve tracing and diagnostics

Keep the existing `@traced("cloudpayments.webhook.process")`.

The tracing helper already supports synchronous callables, so no alternate tracing wrapper is required.

Preserve:

- current span name;
- `record_webhook`;
- `cloudpayments_webhook_processed`;
- safe structured fields;
- current privacy rules.

### 8. Add focused correlation regression

Add focused webhook coverage that proves code executing inside the synchronous webhook worker still sees the ANY-437 context established before dispatch.

At minimum verify:

- a fixed valid `X-Request-ID` remains correlated;
- valid trace/span identifiers remain present on the relevant worker-side diagnostic when tracing is active;
- the regression does not require production code to expose thread IDs or unsafe data.

Prefer observing existing logs/tracing behavior rather than adding production-only test hooks.

### 9. Preserve PostgreSQL concurrency coverage

Do not rewrite the existing concurrent duplicate-webhook tests.

They exercise important PostgreSQL locking/idempotency semantics and must continue to pass after the route becomes synchronous.

## Invariants

After this step:

- the application remains sync-first;
- only exact raw ASGI body acquisition remains asynchronous for this webhook path;
- raw-body acquisition has one reusable shared HTTP implementation;
- CloudPayments does not own its own body-reading helper;
- synchronous SQLAlchemy webhook work is not executed directly on the event loop;
- the request-scoped DB session is not manually passed across execution contexts;
- webhook HTTP routes, payload formats and response codes are unchanged;
- generated OpenAPI is unchanged;
- signature validation is unchanged;
- safe webhook persistence occurs in the same semantic order;
- duplicate deliveries remain idempotent;
- payment/subscription/entitlement transitions remain unchanged;
- provider API behavior is unchanged;
- ANY-415 failure semantics remain unchanged;
- ANY-437 privacy, tracing and request correlation remain intact.

## Out of scope

Do not:

- create a general-purpose request wrapper;
- replace normal Pydantic request models with raw-body parsing;
- build a new DI framework;
- move webhook persistence behind repositories;
- change `process_webhook_event()` architecture;
- change transaction boundaries;
- change locking;
- change idempotency keys;
- add queues/workers;
- change provider API clients;
- change billing state transitions;
- convert SQLAlchemy to async;
- introduce an async service layer;
- refactor unrelated CloudPayments modules.

## AI prompt

Implement only Step 1 of ANY-454: establish the shared raw-request-body HTTP boundary and make the existing CloudPayments webhook execution conform to the approved sync-first architecture.

Precondition: ANY-437 / PR #84 has already been merged and accepted.

Before editing, inspect only the current directly relevant files needed to verify these assumptions:

- `apps/api/app/integrations/cloudpayments/router.py`
- `apps/api/app/integrations/cloudpayments/adapter.py`
- any existing shared FastAPI/HTTP dependency module, if present
- the directly relevant CloudPayments webhook tests
- `apps/api/app/core/observability.py` only as needed to verify the existing tracing/request-context contract
- `apps/api/tests/test_architecture.py` only if needed for a focused shared-boundary regression

Do not perform broad repository research.

The locked design for this step is:

1. This is **not an async migration**. Domain, Application, Persistence, synchronous SQLAlchemy, and current synchronous integrations remain synchronous.
2. Exact raw ASGI request-body acquisition is the only async operation required by the current CloudPayments webhook path.
3. Reuse an existing authoritative shared raw-body dependency if one exists. Otherwise create a small Presentation/HTTP module, expected at `apps/api/app/http_dependencies.py`, with a typed `async def get_raw_request_body(request: Request) -> bytes` whose only responsibility is awaiting `request.body()` and returning the bytes.
4. The shared raw-body dependency must stay provider-neutral and must not parse payloads, verify signatures, access SQLAlchemy, call application/domain code, or own logging policy.
5. CloudPayments must consume the shared dependency rather than defining its own local body-reading helper.
6. Convert `receive_cloudpayments_webhook()` itself to a normal synchronous `def` so FastAPI/Starlette owns worker execution for the DB-heavy handler.
7. Keep the existing `get_db` dependency and request-scoped synchronous SQLAlchemy `Session`. Do not manually send that Session through `run_in_threadpool`, `asyncio.to_thread`, a custom executor, or another thread bridge.
8. Convert `_parse_payload()` and `CloudPaymentsAdapter.normalize_webhook_request()` to synchronous functions because after raw bytes are available they perform only synchronous parsing, validation, hashing, redaction, and Pydantic normalization.
9. Preserve the existing `@traced("cloudpayments.webhook.process")`; the tracing helper already supports sync functions.
10. Preserve webhook persistence, commits, rollbacks, locking, idempotency, acknowledgement codes, signature verification, redaction, safe diagnostics, billing transitions, error semantics, and generated OpenAPI exactly.
11. Add focused regression coverage proving ANY-437 request ID and trace/span correlation remain available from inside the synchronous webhook execution boundary.
12. Keep the existing PostgreSQL duplicate/concurrency tests semantically unchanged except for minimal adaptation required by the execution-boundary change.
13. Do not introduce a global AST ban on `Request.body()`. The reusable dependency plus documented convention is the architectural rule; any focused architecture test should guard only the current concrete boundary.

Do not redesign the architecture.

Do not introduce AsyncSession, AsyncEngine, AsyncClient, a generic sync/async adapter, a custom executor, a queue, a worker system, or a new repository abstraction.

Do not perform unrelated refactoring.

Do not work on the lifespan changes from the next step.

Do not work on future ANY-407 persistence, transaction/idempotency, DI/composition, or business-logic steps.

Do not run tests, linters, formatters, type checkers, generators, or other automated verification commands.

Do not stage files and do not create commits.

After implementation:

1. report every changed file;
2. briefly summarize the shared raw-body boundary and synchronous webhook change;
3. state how DB Session ownership remains safe;
4. state how request/trace/log correlation is preserved;
5. confirm that webhook business/persistence semantics and OpenAPI were not intentionally changed;
6. report the exact verification commands I should run manually.

If the final merged ANY-437 code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

Run from the repository root:

```bash
.venv/bin/python -m pytest apps/api/tests/test_api.py -k "cloudpayments"
```

Run the focused architecture test if Step 1 changed it:

```bash
.venv/bin/python -m pytest apps/api/tests/test_architecture.py
```

Then run the PostgreSQL webhook regression suite:

```bash
python scripts/repo.py test-db up
.venv/bin/python -m pytest -m postgres apps/api/tests/test_cloudpayments_webhook_postgres.py
python scripts/repo.py test-db stop
```

## Expected completion

Step 1 is complete when:

- there is one shared HTTP dependency for exact raw request bytes;
- CloudPayments uses that dependency instead of local body-reading logic;
- the DB-heavy webhook endpoint itself is synchronous;
- normalization after body acquisition is synchronous;
- no request-scoped `Session` is manually moved across a thread boundary;
- public HTTP/OpenAPI behavior remains unchanged;
- existing webhook behavior and PostgreSQL concurrency semantics pass unchanged;
- request/trace/log correlation is proven to survive synchronous worker execution.

## Proposed commit

`refactor(webhooks): enforce shared sync-first request boundary`

---

# Step 2 — Remove blocking synchronous work from FastAPI lifespan

**Status:** `todo`

## Goal

Keep FastAPI lifespan asynchronous only as the framework lifecycle boundary while ensuring synchronous startup persistence and transitional synchronous integration cleanup do not execute directly on its event loop.

Resource ownership must stay explicit: a SQLAlchemy `Session` used by startup worker code must be created, used, and closed inside the same synchronous unit.

## Scope / affected code

Primary code:

- `apps/api/app/main.py`.

Focused lifecycle tests:

- preferably the existing lifecycle/API test location under `apps/api/tests/`;
- do not introduce a new test module unless the existing test organization makes that materially clearer.

## Implementation decisions

### 1. Keep `lifespan()` async

Do not replace FastAPI's async lifespan architecture.

It remains an async **framework shell**, not an async application service.

Use an explicit return annotation consistent with project typing conventions, e.g. `AsyncIterator[None]` where appropriate for the current context-manager shape.

### 2. Extract one synchronous resource-owning seed unit

Create a small private synchronous helper for startup legal seeding with an explicit `-> None` return type.

The helper itself must own:

```text
SessionLocal()
-> seed_legal_documents(...)
-> session close
```

Do not instantiate the Session in `lifespan()` and then pass it to worker code.

### 3. Execute startup persistence through the framework worker mechanism

When legal seeding is enabled, await the complete synchronous helper through the existing Starlette/AnyIO framework threadpool primitive.

Use the framework mechanism already available through the current stack.

Do not create:

- `ThreadPoolExecutor`;
- dedicated thread pools;
- custom concurrency wrappers.

### 4. Keep CloudPayments client construction simple

`build_cloudpayments_api_client()` currently creates the configured synchronous client object.

Do not redesign construction, make it async, or offload it merely for architectural symmetry.

Only revisit construction if the final current code provides concrete evidence that construction itself performs blocking I/O that is material to lifespan safety.

### 5. Move current synchronous CloudPayments cleanup off the event loop

During lifespan shutdown, execute the existing synchronous `cloudpayments_adapter.close()` through the framework-managed worker mechanism while this transitional integration remains present.

Preserve exactly one cleanup call and current ownership by the application lifespan.

This is **temporary runtime safety for the current CloudPayments integration**, not a target provider lifecycle abstraction.

Do not create a reusable provider lifecycle manager because of this cleanup. When CloudPayments is decommissioned, this initialization/cleanup wiring should be removable with the integration.

### 6. Add focused lifecycle regression

Add focused coverage proving the synchronous legal-seed unit executes without a running event loop.

Where practical, also prove synchronous adapter cleanup executes outside the active event loop.

A behavioral test may monkeypatch the relevant synchronous operation to assert that `asyncio.get_running_loop()` is unavailable when that operation executes.

Do not assert exact OS-thread identity and do not add production thread IDs, runtime flags, or diagnostics solely to support the test.

## Invariants

After this step:

- the application architecture remains synchronous;
- FastAPI lifespan remains async only as a framework boundary;
- startup legal seed preserves current behavior;
- the seed's `Session` is created, used, and destroyed inside one synchronous worker unit;
- no SQLAlchemy Session crosses a manually introduced lifespan worker boundary;
- CloudPayments client setup remains semantically unchanged;
- current adapter/client cleanup still occurs exactly once during shutdown;
- CloudPayments cleanup handling does not create permanent provider lifecycle architecture;
- no new executor or threadpool configuration is introduced;
- API startup/shutdown contracts remain unchanged;
- ANY-437 observability setup remains unchanged.

## Out of scope

Do not:

- redesign application composition;
- move `PaymentProviderRegistry`;
- introduce resource-container abstractions;
- redesign provider client ownership;
- change legal seed semantics;
- move legal seed to migrations;
- create startup jobs;
- add health/readiness behavior;
- change SQLAlchemy configuration;
- change provider retry/timeout settings;
- alter global AnyIO threadpool capacity;
- generalize transitional CloudPayments lifecycle wiring.

## AI prompt

Implement only Step 2 of ANY-454: keep blocking synchronous startup and shutdown work off the FastAPI lifespan event loop while preserving the sync-first application architecture.

Step 1 is assumed to be completed, manually verified, and committed.

Before editing, inspect only:

- `apps/api/app/main.py`
- the current directly relevant API/lifespan tests
- `apps/api/app/core/database.py` only if needed to confirm `SessionLocal` ownership

Do not perform broad repository research.

Follow these locked decisions:

1. This is **not an async migration**. `lifespan()` stays asynchronous only because it is a real FastAPI/ASGI framework lifecycle boundary.
2. Extract a small private synchronous startup helper that creates its own `SessionLocal`, calls `seed_legal_documents()`, and closes the Session inside that same synchronous unit.
3. Give new/materially changed helpers explicit parameter/return annotations according to repository conventions.
4. Await that complete synchronous helper through the existing Starlette/AnyIO framework worker mechanism.
5. Never create a SQLAlchemy Session on the event-loop side and pass it into worker code.
6. Keep CloudPayments API client construction unchanged unless the final current code proves construction itself performs material blocking I/O.
7. Execute the existing synchronous `cloudpayments_adapter.close()` through the framework-managed worker mechanism during lifespan shutdown.
8. Treat CloudPayments cleanup offloading as transitional runtime safety only. Do not introduce a generic provider lifecycle abstraction, DI container, or resource manager because CloudPayments is expected to be removable under ANY-407.
9. Preserve startup legal-seed behavior, provider configuration, cleanup behavior, public API behavior, and observability semantics.
10. Add focused lifecycle regression coverage that proves the synchronous seed operation executes without an active event loop. Where practical, verify the same invariant for synchronous adapter cleanup without adding production-only test hooks or asserting exact thread identity.

Do not redesign the architecture.

Do not perform unrelated refactoring.

Do not modify the CloudPayments webhook execution boundary from Step 1 except for a strictly necessary compatibility fix.

Do not work on future Persistence Boundary, transaction/idempotency, DI/composition, job-system, or business-logic steps.

Do not run tests, linters, formatters, type checkers, generators, or other automated verification commands.

Do not stage files and do not create commits.

After implementation:

1. report every changed file;
2. summarize how startup and shutdown blocking work is isolated;
3. explain where SQLAlchemy Session creation and cleanup now occur;
4. confirm that provider-client behavior remains unchanged and no permanent provider lifecycle abstraction was introduced;
5. report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new architecture.

## Manual verification

Run:

```bash
.venv/bin/python -m pytest apps/api/tests/test_api.py -k "lifespan or liveness_readiness_metrics_and_request_id"
```

Then run the complete fast API suite because lifespan affects application startup shared by API tests:

```bash
npm run test:api:fast
```

## Expected completion

Step 2 is complete when:

- lifespan remains an async framework boundary only;
- legal-seed persistence is executed outside the event loop;
- its SQLAlchemy Session is entirely owned by the synchronous worker unit;
- current synchronous CloudPayments cleanup is executed outside the event loop;
- no generic provider lifecycle architecture was introduced;
- startup and shutdown behavior remain unchanged;
- focused lifecycle coverage proves the intended boundary.

## Proposed commit

`refactor(api): isolate sync lifespan work`

---

# Step 3 — Codify and narrowly guard the sync-first execution policy

**Status:** `todo`

## Goal

Make the resulting execution architecture authoritative and discoverable, including the shared raw-body dependency pattern, and add only narrow regression protection for the confirmed boundaries.

Do not create a generic static-analysis framework.

## Scope / affected code

Documentation:

- `ARCHITECTURE.md`;
- `docs/RELIABILITY.md`;
- `docs/engineering/CODING_CONVENTIONS.md`.

Focused architecture regression:

- `apps/api/tests/test_architecture.py`.

No production runtime code should normally change in this step.

## Implementation decisions

### 1. Document the authoritative runtime model in `ARCHITECTURE.md`

Add a concise runtime execution-model section establishing:

```text
Payment Portal application
    -> synchronous by default

Domain / Application / Persistence
    -> synchronous

current sync integrations
    -> synchronous

async
    -> only unavoidable ASGI/FastAPI framework boundaries
       or concrete genuinely awaitable outer I/O
```

State explicitly:

> ANY-454 is not an async migration. The application remains synchronous. Async exists only at unavoidable framework or genuinely asynchronous outer I/O boundaries.

Clarify that:

- ordinary synchronous FastAPI endpoints are the expected execution surface for current synchronous DB/application work;
- genuine async framework boundaries may use async dependencies or middleware;
- blocking work must not execute directly on the event loop;
- an async framework boundary may hand a **complete synchronous resource-owning unit** to the framework worker mechanism where necessary;
- a SQLAlchemy Session must not be casually moved across a manually introduced thread boundary;
- execution modality does not justify duplicate application/domain services.

### 2. Document the shared raw-body rule

Document the reusable HTTP transport convention:

- exact raw request bytes are an HTTP/ASGI transport concern;
- `get_raw_request_body()` is the shared dependency for routes that genuinely require exact bytes;
- integration routers should not each implement their own `await request.body()` helper when the shared dependency satisfies the requirement;
- signature-verification webhooks are a valid example;
- normal JSON API routes should use FastAPI/Pydantic request models rather than raw-body parsing;
- the shared raw-body dependency contains no parsing, provider logic, persistence, or application/domain work.

Do not describe this helper as a general async service or core abstraction.

### 3. Record operational consequences in `docs/RELIABILITY.md`

Document only consequences that matter to reliability:

- framework worker capacity is finite/shared;
- do not add unbounded blocking work or retry sleeps;
- provider timeout/retry budgets remain necessary for current synchronous integrations;
- synchronous worker work is not assumed to be forcibly canceled merely because its waiting request is canceled;
- request/trace/log context must remain correlated across selected framework worker boundaries;
- current scheduled expiry remains a synchronous CLI;
- current password-reset background delivery remains the existing framework background task and is not a general durable job system;
- transitional CloudPayments cleanup handling is not a permanent integration lifecycle architecture.

Do not invent a new SLO, timeout value, thread count, cancellation protocol, or scheduler contract.

### 4. Add coding conventions for new/changed API code

In the API/Python conventions, add a concise ratchet:

- default Application, Domain, Persistence, and current sync integration code to ordinary synchronous functions;
- use `async def` only when that exact boundary truly needs to await framework or asynchronous I/O;
- use normal `def` FastAPI endpoints for flows built on synchronous DB/network libraries;
- never call blocking SQLAlchemy, sync network clients, or blocking sleeps directly from an event-loop path;
- reuse the shared raw-body dependency when exact request bytes are required;
- ordinary JSON routes should use Pydantic request models rather than manual raw-body parsing;
- do not use `asyncio.run()` or duplicate sync/async application services to bridge layers;
- if an explicit thread bridge is required, move the complete synchronous resource-owning unit across it, not an already-created request-scoped resource such as a `Session`;
- new/materially changed functions keep explicit parameter and return annotations without unintentionally changing FastAPI OpenAPI response inference.

Keep this limited to new/materially changed code.

### 5. Add one focused architecture regression

Add narrowly scoped coverage for the concrete result rather than internal line-by-line implementation:

- the registered CloudPayments webhook processing endpoint is synchronous;
- CloudPayments post-body normalization is synchronous;
- CloudPayments uses the shared raw-body dependency rather than owning a local async body reader, if this can be asserted robustly through the existing FastAPI dependency graph/test style.

Do not add a repository-wide AST rule forbidding async functions or every direct `Request.body()` call.

Do not modify `scripts/repo.py` merely to add a new async checker.

The Step 1 behavioral test remains responsible for request/trace correlation across worker dispatch.

### 6. Keep already-correct async framework surfaces explicitly allowed

The documentation should make clear that the following are not architectural debt merely because they are async:

- request/error middleware;
- the shared exact raw request-body dependency;
- FastAPI lifespan coordination;
- future genuinely async outer I/O when introduced by a concrete integration requirement.

Likewise, current synchronous surfaces remain sync:

- ordinary DB-heavy FastAPI routes;
- SQLAlchemy persistence;
- Application/Domain code;
- current provider server API client;
- password-reset sync background callback;
- expiry command;
- current synchronous provider-neutral business operations.

`traced()` may continue supporting both sync and async callables because it is a boundary-neutral observability helper, not an instruction to make application code async.

## Invariants

After this step:

- there is one documented **sync-first** execution policy;
- documentation explicitly states that ANY-454 is not an async migration;
- new code can determine whether it should be sync or async without inventing abstractions;
- exact raw-body access has one documented reusable HTTP dependency pattern;
- normal API routes are not encouraged to bypass Pydantic with raw body parsing;
- legitimate FastAPI/ASGI async boundaries remain allowed;
- the guard covers concrete regressions rather than incidental package layout;
- CloudPayments is documented as a transitional current integration, not a permanent target architecture component;
- no public API or runtime business behavior changes;
- later ANY-407 steps can consume this policy without reopening the sync/async decision.

## Out of scope

Do not:

- document async SQLAlchemy as a target;
- introduce new performance numbers or worker sizing;
- add generic async architecture scanners;
- add a global `Request.body()` scanner;
- modify runtime code unless an inconsistency from Steps 1–2 is discovered;
- prescribe future external-billing client modality;
- document CloudPayments as permanent architecture;
- document a generic job framework;
- redefine transaction ownership;
- redefine Persistence Boundary;
- restructure application packages.

## AI prompt

Implement only Step 3 of ANY-454: codify and narrowly guard the approved **sync-first** execution architecture and the shared raw-request-body HTTP dependency pattern.

Steps 1 and 2 are assumed to be completed, manually verified, and committed.

Before editing, inspect only:

- `ARCHITECTURE.md`
- `docs/RELIABILITY.md`
- `docs/engineering/CODING_CONVENTIONS.md`
- `apps/api/tests/test_architecture.py`
- `apps/api/app/http_dependencies.py` or the final shared equivalent
- the final Step 1 CloudPayments route/normalizer signatures only as needed for the focused guard

Do not perform broad repository research.

Document the following locked policy:

- **ANY-454 is not an async migration. Payment Portal remains sync-first.**
- Domain, Application, Persistence, synchronous SQLAlchemy, and current synchronous integrations remain synchronous.
- Async is used only at unavoidable framework boundaries or concrete genuinely awaitable outer I/O.
- Normal FastAPI `def` endpoints are the standard boundary for current blocking DB/application work.
- Blocking synchronous I/O must not execute directly on event-loop paths.
- Exact raw ASGI request-body acquisition is a Presentation/HTTP concern. Routes that genuinely need exact bytes must reuse the shared `get_raw_request_body` dependency (or its final equivalent) rather than creating integration-local body readers.
- Ordinary JSON routes should continue using Pydantic request models and should not use raw-body parsing without a concrete exact-bytes requirement.
- When an async framework boundary must invoke a synchronous unit, use the existing framework worker mechanism and keep resource ownership inside the synchronous unit; do not move an already-created request-scoped SQLAlchemy Session across a manually introduced thread boundary.
- Do not create duplicate sync/async application services or generic async/sync adapters.
- Framework worker capacity is shared and finite; do not invent new thread counts or performance policy.
- Existing bounded provider timeout/retry behavior remains part of safe current synchronous integration execution.
- Request/trace/log correlation must survive framework worker boundaries.
- Current password-reset BackgroundTask and scheduled expiry CLI keep their existing execution models and do not imply a generic job framework.
- CloudPayments remains a transitional current integration. Its current cleanup handling must not be documented as permanent provider lifecycle architecture.
- Future external-billing integrations choose sync or async according to their real I/O client and keep that modality at the outer boundary rather than propagating it into Domain/Application/Persistence.

Add one narrow architecture regression in `apps/api/tests/test_architecture.py` protecting the current concrete result: the DB-heavy CloudPayments webhook is registered as synchronous, its post-body normalization is synchronous, and — if robustly testable through the existing dependency graph — it consumes the shared raw-body dependency rather than a local reader.

Do not add a broad AST rule that forbids async functions, bans all `Request.body()` use globally, or encodes incidental file layout.

Do not modify `scripts/repo.py` merely to enforce this step.

Do not redesign the architecture.

Do not perform unrelated documentation cleanup.

Do not work on future Persistence Boundary, transaction/idempotency, DI/composition, job-system, or business/domain steps.

Do not run tests, linters, formatters, documentation checks, type checkers, generators, or any other automated verification commands.

Do not stage files and do not create commits.

After implementation:

1. report every changed file;
2. summarize the documented sync-first execution rules;
3. describe the shared raw-body rule and exactly what the focused regression protects;
4. confirm that no generic async architecture framework or permanent CloudPayments lifecycle abstraction was introduced;
5. report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

Run the focused architecture regression:

```bash
.venv/bin/python -m pytest apps/api/tests/test_architecture.py
```

Then:

```bash
npm run architecture:check
npm run docs:check
```

## Expected completion

Step 3 is complete when:

- architecture documentation explicitly states that Payment Portal remains sync-first and ANY-454 is not an async migration;
- the shared raw-body dependency pattern is documented for exact-bytes HTTP boundaries;
- reliability documentation records relevant framework-worker/cancellation/resource implications;
- coding conventions tell future changes how to select `def` vs `async def` and when raw-body access is allowed;
- one focused regression protects the current webhook execution boundary without a broad async scanner;
- CloudPayments is not elevated into permanent target architecture.

## Proposed commit

`chore(architecture): codify sync-first execution model`

---

# Final Manual Verification

After all three steps have been reviewed and committed sequentially, run the final backend verification from the repository root.

Fast backend suite:

```bash
npm run test:api:fast
```

Architecture and documentation:

```bash
npm run architecture:check
npm run docs:check
```

PostgreSQL-backed backend suite:

```bash
python scripts/repo.py test-db up
npm run test:api:postgres
python scripts/repo.py test-db stop
```

Final fast repository quality gate:

```bash
npm run check:fast
```

A repository-wide `npm run check` is not required specifically by ANY-454 because the implementation does not touch the web application or schema. It may still be run separately if required by the PR/merge workflow.

---

# Expected final state

After ANY-454:

```text
FastAPI / ASGI framework shell
├── async request/error middleware
├── async shared exact raw-body dependency (only where required)
├── async lifespan coordination
│
└── framework worker execution
    ├── sync FastAPI DB routes
    ├── sync CloudPayments webhook processing (while transitional integration exists)
    ├── sync SQLAlchemy
    ├── sync Application
    ├── sync Domain
    ├── sync current provider clients
    ├── sync startup persistence unit
    └── sync background callbacks where currently used
```

There is no async propagation into Domain/Application/Persistence.

There is no async SQLAlchemy.

There is no duplicate sync/async service architecture.

There is no custom executor.

There is no generic job framework.

There is one reusable HTTP transport dependency for exact raw request bytes instead of integration-local async body-reading helpers.

Ordinary JSON routes continue using Pydantic request models.

CloudPayments webhook no longer blocks the event loop with synchronous SQLAlchemy work.

Lifespan no longer directly performs blocking startup persistence or current synchronous integration cleanup on the event loop.

CloudPayments remains transitional; ANY-454 does not create permanent lifecycle architecture around it.

Request/trace/log correlation established by ANY-437 survives the selected framework worker boundaries.

Provider timeout/retry/idempotency/unknown-outcome semantics remain unchanged.

Public API contracts, generated OpenAPI, webhook acknowledgement semantics, persisted-data semantics and billing state transitions remain unchanged.

Future external integrations may use sync or async outer I/O according to their concrete client without changing the sync-first Domain/Application/Persistence architecture.

ANY-455 can subsequently establish the Persistence Boundary while treating this execution model as fixed predecessor architecture.

---

# Plan validation against ANY-454 acceptance criteria

The plan covers the ticket acceptance criteria as follows:

- predecessor gate for final ANY-437 state — explicitly required before Step 1;
- execution inventory — completed during planning and recorded above;
- explicit non-goal — ANY-454 is not an async migration;
- confirmed event-loop blockers — webhook and lifespan identified with concrete call chains;
- already-safe sync surfaces — explicitly separated from problems;
- FastAPI worker model — used without custom concurrency infrastructure;
- exact raw-body ASGI requirement — isolated once behind a shared Presentation/HTTP dependency;
- normal JSON request modeling — remains Pydantic-based;
- SQLAlchemy resource ownership — Session remains synchronous and resource-owned where an explicit lifecycle worker bridge exists;
- provider timeout/retry/idempotency behavior — explicitly preserved;
- CloudPayments status — kept transitional, without permanent lifecycle abstraction;
- cancellation/threadpool implications — documented, not redesigned;
- ANY-437 request/trace/log propagation — protected by focused regression;
- blocking I/O removed from covered event-loop paths;
- async SQLAlchemy / duplicate services — explicitly forbidden;
- PostgreSQL webhook behavior — preserved and verified by existing PostgreSQL suite;
- practical regression guard — scoped to the confirmed webhook/shared-boundary invariant;
- authoritative architecture/reliability/coding documentation — updated in Step 3;
- future integrations — may choose their real outer I/O modality without changing sync-first core architecture;
- Persistence Boundary, transaction/idempotency, broad DI/composition and business cleanup — explicitly deferred to later ANY-407 steps.

No unresolved architectural decision is intentionally left for the execution agent to make.
