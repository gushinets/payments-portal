# ANY-458 — Integrate Sentry Error Reporting

## Plan Overview

| Field | Value |
|---|---|
| Feature | `ANY-407` |
| Ticket | `ANY-458` |
| Overall status | `done` |
| Execution order | Sequential only: Step 1 → verification → commit → Step 2 → … → Step 4 |
| Steps / commits | 4 |
| Prerequisite | `ANY-437` merged into `main` — **satisfied** |
| Database migration | Not required |
| Public API | No changes |
| Persisted semantics | No changes |
| Business behavior | No changes |
| Sentry role | Backend application error reporting only |
| Existing observability | Preserve JSON logs + OpenTelemetry + Prometheus |
| Frontend Sentry | Out of scope |
| SDK baseline | `sentry-sdk==2.69.1` |
| Reporting ownership | Explicit outer-boundary capture |
| Automatic Sentry capture | Disabled except safe process shutdown/flush |
| Sentry tracing/logging/metrics | Explicitly disabled / out of scope |

## How to Use This Plan

Execute exactly one step at a time.

After every step:

1. review the diff;
2. let the implementation agent run only the focused formatting/tests/static checks assigned to that step;
3. fix any focused-check failure before continuing;
4. run any larger developer-owned repository gate explicitly assigned to the step;
5. create the proposed commit yourself;
6. only then start the next step.

The agent must not run repository-wide, Docker-heavy, or PostgreSQL-heavy verification unless the step explicitly requires it.

The implementation model must **not** repeat the repository-wide research captured by this plan.

Before each step it may inspect only the directly affected current files needed to verify that the previous steps did not invalidate an assumption.

If current code materially contradicts a locked decision in this plan, stop and report the contradiction instead of silently redesigning the solution.

---

# 1. Research Conclusions

## 1.1 Source-of-truth order

For ANY-458:

1. `ANY-407` defines the architectural direction and Sentry reporting policy.
2. `ANY-415` is authoritative for Error Architecture.
3. merged `ANY-437` is authoritative for observability, correlation, privacy, and current failure boundaries.
4. current `main` code/tests define actual implemented behavior.
5. `ANY-454` and later ANY-407 steps define work that must not be pulled into this ticket.
6. the pinned Sentry SDK behavior defines the integration mechanics.

## 1.2 Current repository baseline

The repository is not missing general observability.

It already has:

- structured JSON logs;
- validated `request_id`;
- OpenTelemetry `trace_id` / `span_id`;
- HTTP metrics;
- application/provider spans;
- Prometheus metrics;
- safe bounded HTTP failure diagnostics;
- a centralized `AppError` HTTP mapping;
- a single unexpected HTTP failure middleware;
- scheduled subscription-expiry correlation through `run_id`;
- safe local diagnostic IDs;
- strict telemetry privacy rules.

The existing HTTP boundary already owns:

```text
mapped AppError
    -> expected HTTP response

unmapped AppError
    -> bounded http_internal_failure
    -> generic 500

unexpected Exception
    -> bounded http_internal_failure
    -> generic 500
```

The current scheduled-expiry command already owns:

```text
run_started
    -> lifecycle
        -> run_failed
        OR
        -> transition_committed...
        -> run_succeeded

post-commit diagnostic invariant
    -> diagnostic_invariant_violated
```

ANY-458 must attach Sentry to these established outer boundaries rather than inventing new inner failure reporting.

## 1.3 Confirmed remaining gaps

The current repository has no:

- Sentry SDK dependency;
- Sentry runtime configuration;
- safe Sentry event contract;
- explicit exception aggregation;
- Sentry event grouping policy;
- HTTP Sentry capture;
- non-HTTP Sentry capture;
- Sentry-first incident-investigation documentation;
- production `SENTRY_DSN` / `SENTRY_RELEASE` wiring;
- architecture guard preventing SDK leakage into inner layers.

Those are the actual implementation gaps owned by ANY-458.

## 1.4 Work already solved and not to be repeated

ANY-458 must **not** redesign:

- `AppError`;
- HTTP error mapping;
- generic 500 responses;
- logging;
- OpenTelemetry tracing;
- Prometheus metrics;
- provider retry semantics;
- ambiguous/unknown provider outcome semantics;
- request-ID generation;
- trace correlation;
- subscription-expiry transaction behavior;
- persistence boundaries;
- sync/async boundaries;
- CloudPayments lifecycle behavior.

---

# 2. Locked Sentry Integration Model

## 2.1 Ownership

Target:

```text
Domain / Application / Payment Provider contracts
                    |
                    | semantic failures
                    v
        Presentation / Process boundary
                    |
          +---------+---------+
          |         |         |
        logs       OTEL     Sentry
                    |
               correlation
```

Sentry is an **outer infrastructure adapter**.

The only module allowed to import `sentry_sdk` in application code should be:

```text
app/infrastructure/sentry.py
```

Callers such as:

```text
app/http_errors.py
app/main.py
app/commands/expire_subscriptions.py
```

must depend on that adapter, not on `sentry_sdk`.

No:

```text
send_to_sentry=True
```

No Sentry dependency in Domain/Application errors.

No generic `ErrorReporter` / `MonitoringPort` framework is justified by the current repository.

## 2.2 Explicit capture instead of framework magic

Do **not** enable Sentry's automatic FastAPI/Starlette capture.

Do **not** enable its default logging or uncaught-exception capture.

Initialize the SDK with:

- `default_integrations=False`;
- `auto_enabling_integrations=False`.

This prevents automatic activation of:

- `LoggingIntegration`;
- `ExcepthookIntegration`;
- FastAPI/Starlette;
- SQLAlchemy;
- HTTPX;
- other auto integrations.

Enable only `AtexitIntegration` for transport shutdown/flush, using a silent callback so short-lived CLI processes can deliver queued events without changing their stdout/stderr contract.

This means the application owns exactly where an exception becomes a Sentry event.

## 2.3 Error-reporting policy

Use one small closed infrastructure-owned category vocabulary:

```text
internal_application_failure
integration_failure
unknown_external_outcome
unexpected_exception
consistency_invariant_violation
```

Classification policy:

| Failure | Sentry |
|---|---|
| mapped expected business `AppError` | no |
| normal `PaymentsOperationDeclinedError` | no |
| `PaymentsTimeoutError` reaching a reportable outer boundary | yes → `unknown_external_outcome` |
| `PaymentsIdempotencyKeyRequiredError` | yes → `internal_application_failure` |
| `PaymentProviderConfigurationError` | yes → `internal_application_failure` |
| another `PaymentsError` reaching a reportable outer boundary | yes → `integration_failure` |
| unmapped non-provider `AppError` | yes → `internal_application_failure` |
| unexpected exception | yes → `unexpected_exception` |
| diagnostic/consistency invariant violation | yes → `consistency_invariant_violation` |
| successful operation | no |

Do not inspect or parse exception messages to classify failures.

Do not add reporting flags to error classes.

## 2.4 Event contract

Every reportable event should answer:

```text
What failed?
Where?
In which release/environment?
Which safe operation was running?
Which existing trace/log correlation should I follow next?
```

### Stable tags

Only low-cardinality values:

```text
service
failure_category
operation
```

Examples:

```text
service=payment-portal-api
failure_category=unexpected_exception
operation=http_request
```

or:

```text
operation=expire_subscriptions
```

Do not use `request_id`, `trace_id`, `run_id`, entity IDs, URLs, provider IDs, or arbitrary codes as tags/fingerprint components.

### Safe `payment_portal` event context

May contain, when actually available:

```text
request_id
trace_id
span_id
run_id
method
route
error_code
invariant
batch_size
failure_location:
    module
    function
    line
```

Rules:

- `route` means matched FastAPI route template, never raw path input.
- `request_id` comes from the existing validated request context.
- trace IDs come from the existing OpenTelemetry context.
- `run_id` comes from the existing CLI invocation.
- `error_code` is included only as bounded machine-readable diagnostic metadata.
- no DB query is performed to enrich a Sentry event.
- no provider/customer/entity lookup is performed merely for Sentry.

If later a current boundary already has an approved local `order_id`, `payment_id`, `subscription_id` or `webhook_event_id`, the safe context allowlist may be extended deliberately in a future reviewed change. ANY-458 must not query for these IDs merely for uniformity.

Allowlisting a field name is not sufficient by itself. Every string-like context value owned by the Sentry adapter must also be bounded and structurally validated. Values that violate the reviewed bound/shape must be dropped rather than truncated from arbitrary input. In particular, `error_code`, `invariant`, `operation`, `method`, `route`, and `failure_location` components must never become an unbounded pass-through channel for request/provider/exception data.

## 2.5 Exception data retained

Sentry remains useful because the event retains:

- exception type;
- exception module where available;
- stack frame filenames/modules;
- function names;
- line numbers;
- safe cause/chaining structure.

It must not retain:

- exception value/message;
- source-code context lines;
- local variables;
- function arguments;
- raw traceback text as a string;
- request body;
- raw path values;
- query values;
- headers;
- cookies;
- user/email data;
- provider payload;
- provider transaction/invoice IDs;
- authorization/tokens;
- card/payment values.

`include_local_variables=False` and `include_source_context=False` are mandatory, but are defense in depth rather than the complete privacy boundary.

The `before_send` hook must enforce the final event allowlist as the last application-side gate. Treat this as a positive allowlist, not an ever-growing denylist: after SDK serialization, retain only the reviewed top-level structures and reviewed subfields required by the event contract, then sanitize those structures recursively.

## 2.6 Request-data policy

Set:

```text
send_default_pii=False
max_request_body_size="never"
```

In addition, `before_send` must remove request/user/breadcrumb/extra/log payloads regardless of SDK defaults.

Do not rely only on Sentry server-side scrubbing.

## 2.7 Grouping policy

Do not set a custom Sentry `fingerprint`.

Use Sentry's exception type + sanitized stack grouping.

Correlation values such as:

```text
request_id
trace_id
run_id
```

must remain context only and must never influence grouping.

This prevents one logical production problem from becoming thousands of issues.

## 2.8 Existing OTEL ownership

Sentry does not become a tracing backend.

Do not enable:

- Sentry Performance;
- Sentry tracing;
- Sentry profiling;
- Sentry Logs;
- Sentry Metrics.

The SDK configuration must make that ownership explicit rather than relying on defaults. Use the current non-deprecated sampling controls for Sentry SDK 2.69.1:

```text
traces_sample_rate=0.0
profiles_sample_rate=0.0
enable_logs=False
before_send_metric=_drop_metric
propagate_traces=False
auto_session_tracking=False
```

For the pinned Sentry SDK `2.69.1`, `_drop_metric` is an application-owned
callback that returns `None`, so metric telemetry is dropped before delivery.
The final configuration intentionally does not pass `enable_metrics=False`:
that option is ineffective in this SDK version and emits an SDK warning. This
SDK-specific correction does not change ownership; Prometheus/OpenTelemetry
remain the metrics owners and Sentry Metrics remain disabled/out of scope.

Do not use deprecated `enable_tracing=False`.

Existing ownership remains:

```text
Sentry        -> application error issues
OpenTelemetry -> traces
Prometheus    -> metrics
JSON logs     -> bounded diagnostics
PostgreSQL    -> authoritative business state
```

## 2.9 Release/environment/service

Use:

```text
environment = APP_ENV
release     = SENTRY_RELEASE
service     = existing OTEL_SERVICE_NAME value
```

Do not introduce:

```text
SENTRY_ENVIRONMENT
SENTRY_SERVICE_NAME
```

as duplicate sources of truth.

When `SENTRY_DSN` is empty:

- Sentry is disabled;
- no SDK initialization is performed;
- existing local/test behavior is unchanged.

When `SENTRY_DSN` is configured:

- `SENTRY_RELEASE` is required;
- deployment/CI owns the release value;
- runtime git revision discovery must not be used.

Configuration and runtime reporting failures have different semantics:

```text
invalid application configuration
(DSN configured, release absent)
    -> fail fast during Settings validation

valid configuration, but SDK init/capture/transport failure
    -> fail safe with bounded diagnostics
    -> never mask or replace application behavior
```

The existing `OTEL_SERVICE_NAME` source remains the shared service identity.

### Settings ownership

All deployment-varying Sentry-owned configuration is resolved by the existing Pydantic `Settings` model in `apps/api/app/core/settings.py`:

```text
SENTRY_DSN     -> settings.sentry_dsn
SENTRY_RELEASE -> settings.sentry_release
APP_ENV        -> settings.app_env
```

`app/infrastructure/sentry.py` must not call `os.getenv()` / read `os.environ` for Sentry-owned configuration and must not instantiate a second settings object. Composition roots pass the existing application `settings` into `configure_sentry(...)`.

The existing `OTEL_SERVICE_NAME` remains the shared observability service identity; it is not duplicated as a Sentry-specific setting. Do not add `SENTRY_SERVICE_NAME`.

The following are locked adapter policy, not deployment settings, and therefore must not become new environment variables or `Settings` fields in this ticket:

```text
traces_sample_rate=0.0
profiles_sample_rate=0.0
enable_logs=False
before_send_metric=_drop_metric
propagate_traces=False
auto_session_tracking=False
```

## 2.10 Trace/log navigation

The repository currently has no stable production trace/log UI base URL owned by the application.

Therefore ANY-458 must **not** invent:

```text
GRAFANA_URL
TEMPO_URL
LOKI_URL
OBSERVABILITY_UI_URL
```

only to manufacture Sentry links.

The documented investigation path is:

```text
Sentry issue
    ↓
request_id / trace_id / run_id
    ↓
existing trace/log backend
    ↓
existing local diagnostic IDs
    ↓
persisted Payment Portal state
```

Direct links can be added later if deployment provides a stable supported query URL contract.

---

# Explicitly Out of Scope

- Sentry frontend/Next.js SDK.
- Source maps.
- Session Replay.
- Sentry Performance.
- Sentry tracing.
- Sentry profiling.
- Sentry Logs.
- Sentry Metrics.
- Replacing OpenTelemetry.
- Replacing Prometheus.
- Replacing structured logging.
- Generic error-reporting interfaces.
- Generic monitoring framework.
- Production dashboard infrastructure.
- General alerting infrastructure owned by `ANY-86`.
- Persistence/schema changes.
- Sync/async architecture.
- Worker/job architecture.
- Retry/idempotency redesign.
- Reconciliation redesign.
- CloudPayments redesign or removal.
- Unrelated cleanup/refactoring.

---

# Step 1 — Establish the privacy-safe Sentry infrastructure and event contract

**Status:** `done`

## Goal

Introduce the Sentry SDK, disabled-by-default runtime configuration, one infrastructure-owned reporting adapter, safe semantic classification, and a privacy-enforced event contract without wiring Sentry into HTTP or CLI callers yet.

After this step the repository has one tested Sentry reporting primitive but current runtime failure boundaries are not changed.

## Scope / affected code

Primary:

- `apps/api/pyproject.toml`
- `apps/api/uv.lock`
- `apps/api/app/core/settings.py`
- new `apps/api/app/infrastructure/sentry.py`
- new focused `apps/api/tests/test_sentry_reporting.py`

Test-only support under `apps/api/tests/support/` may be added only if a minimal SDK transport helper is needed to inspect the final captured event.

## Implementation decisions

1. Add the exact pinned runtime dependency:

   ```text
   sentry-sdk==2.69.1
   ```

   Do not add the `fastapi` extra because Sentry FastAPI auto-integration is intentionally not enabled.

2. Regenerate the API lockfile through the repository-owned dependency workflow.

3. Add the Sentry-owned deployment configuration to the existing `apps/api/app/core/settings.py` Pydantic `Settings` model:

   ```text
   sentry_dsn: str = ""
   sentry_release: str = ""
   ```

   Use the repository's existing whitespace-stripping settings conventions. `SENTRY_DSN` and `SENTRY_RELEASE` must be resolved only through this `Settings` model. The Sentry adapter must not read those environment variables directly and must not create/instantiate a second settings object. Existing `settings.app_env` is the Sentry environment source.

4. Do not add `SENTRY_ENABLED`.

   ```text
   empty SENTRY_DSN -> disabled
   non-empty SENTRY_DSN -> enabled
   ```

5. Add `Settings` validation requiring a non-empty `sentry_release` whenever `sentry_dsn` is non-empty.

   This is application configuration validation and must fail fast while constructing the existing `Settings`. It prevents Sentry's fallback release autodetection and makes release correlation explicit.

6. Create:

   ```text
   app/infrastructure/sentry.py
   ```

   Do not create a generic reporting interface.

7. Introduce one closed `StrEnum` or equivalently strict finite vocabulary owned by this adapter for failure categories:

   ```text
   INTERNAL_APPLICATION_FAILURE
   INTEGRATION_FAILURE
   UNKNOWN_EXTERNAL_OUTCOME
   UNEXPECTED_EXCEPTION
   CONSISTENCY_INVARIANT_VIOLATION
   ```

   serialized using the exact lowercase values defined in the locked reporting policy above.

   Also make `operation` a closed low-cardinality vocabulary for this ticket:

   ```text
   HTTP_REQUEST          -> "http_request"
   EXPIRE_SUBSCRIPTIONS  -> "expire_subscriptions"
   ```

   `report_exception(...)` must not accept arbitrary free-form operation strings.

8. Implement a small classifier for normalized semantic exception types:

   - `PaymentsOperationDeclinedError` → no report;
   - `PaymentsTimeoutError` → `unknown_external_outcome`;
   - `PaymentsIdempotencyKeyRequiredError` → `internal_application_failure`;
   - `PaymentProviderConfigurationError` → `internal_application_failure`;
   - other `PaymentsError` → `integration_failure`;
   - other `AppError` → `internal_application_failure`;
   - ordinary unexpected `Exception` → `unexpected_exception`.

   Invariant violations are explicitly classified by the caller as `consistency_invariant_violation`.

9. Implement `configure_sentry(...)` using the already-constructed existing application `Settings`. The adapter must not read Sentry configuration directly from environment variables.

10. If `settings.sentry_dsn` is empty, do not call `sentry_sdk.init()`.

11. When enabled, initialize with:

    ```text
    default_integrations=False
    auto_enabling_integrations=False
    send_default_pii=False
    include_local_variables=False
    include_source_context=False
    max_request_body_size="never"
    traces_sample_rate=0.0
    profiles_sample_rate=0.0
    enable_logs=False
    before_send_metric=_drop_metric
    propagate_traces=False
    auto_session_tracking=False
    sample_rate=1.0
    ```

    `_drop_metric` must return `None`, hard-dropping Sentry metric telemetry
    before delivery. Intentionally do not pass `enable_metrics=False`; it is
    ineffective and produces a warning with the pinned SDK `2.69.1`.

12. Explicitly install only `AtexitIntegration`.

    Use a silent shutdown callback so transport flush/close cannot add Sentry status text to CLI stdout/stderr.

13. Use:

    ```text
    environment = settings.app_env.value
    release     = settings.sentry_release
    ```

14. Reuse the current `OTEL_SERVICE_NAME` value and existing fallback as the Sentry `service` tag.

    Do not create a separate service-name setting.

15. Implement `report_exception(...)` as the only application Sentry capture entrypoint.

16. `report_exception(...)` must use a temporary/per-call Sentry scope so context from one error cannot leak into another.

17. Obtain ambient:

    ```text
    request_id
    trace_id
    span_id
    ```

    from the existing observability mechanisms.

18. The caller may additionally pass only the explicitly approved fields:

    ```text
    run_id
    method
    route
    error_code
    invariant
    batch_size
    failure_location
    ```

    Enforce these reviewed shapes before they enter the Sentry event:

    - `request_id`: existing `REQUEST_ID_PATTERN`, therefore 1..128 characters from `[A-Za-z0-9._-]`;
    - `trace_id`: exactly 32 lowercase hexadecimal characters;
    - `span_id`: exactly 16 lowercase hexadecimal characters;
    - `run_id`: canonical UUID string;
    - `method`: uppercase HTTP method token, maximum 16 characters;
    - `route`: matched FastAPI route template only, starts with `/`, contains no query/fragment, maximum 256 characters;
    - `error_code`: stable identifier matching `[a-z0-9][a-z0-9_.:-]{0,127}`;
    - `invariant`: static identifier matching `[a-z0-9][a-z0-9_.:-]{0,63}`;
    - `batch_size`: integer in the existing CLI range `1..1000`;
    - `failure_location.module`: repository-relative module string, maximum 256 characters;
    - `failure_location.function`: function name, maximum 128 characters;
    - `failure_location.line`: positive integer.

    Invalid values are dropped. Do not coerce/truncate arbitrary external text into a valid-looking allowed value.

19. Add stable low-cardinality tags only:

    ```text
    service
    failure_category
    operation
    ```

20. Do not set a custom fingerprint.

21. Implement `before_send` as a strict positive allowlist over the final serialized SDK event. Keep only these reviewed top-level keys when present:

    ```text
    event_id
    timestamp
    platform
    level
    exception
    tags
    contexts
    release
    environment
    sdk
    ```

    `event_id` must be preserved because the SDK transport requires it after `before_send`. Everything else at the top level is dropped unless explicitly listed above.

    Subfield policy:

    - `tags`: keep only `service`, `failure_category`, `operation`;
    - `contexts`: keep only the application-owned `payment_portal` context and only its approved fields from this plan; drop ambient SDK/device/runtime/OS/trace/request/user contexts;
    - `exception.values[*]`: keep exception `type`, safe module identity, sanitized `stacktrace`, and only SDK-generated structural chaining/mechanism identifiers/booleans required to preserve cause/chaining; drop exception `value`/message and arbitrary mechanism data;
    - `stacktrace.frames[*]`: keep only repository-safe `filename`/module/function/line identity and `in_app`; drop `abs_path`, `vars`, locals, arguments, `pre_context`, `context_line`, `post_context`, and other source snippets;
    - `sdk`: keep SDK name/version/package identity only;
    - `release`, `environment`, `platform`, `level`, `timestamp`, `event_id`: keep only SDK/application-generated scalar values, never caller/provider-derived replacements.

    Explicitly drop `request`, `user`, breadcrumbs, arbitrary `extra`, log/message payload fields, transaction data, modules, threads, server/host information, any existing fingerprint, arbitrary tags/contexts and every unknown future top-level key.

22. Validate/bound every approved context value according to the exact shapes above before serialization. Drop values that do not satisfy the reviewed type/length/shape; do not truncate arbitrary request/provider/exception-derived text into an allowed field.

23. Do not inspect:

    - exception `str(...)`;
    - arbitrary exception attributes;
    - `details_safe` automatically;
    - request objects;
    - database entities;
    - provider payloads

    to enrich events.

24. `report_exception(...)` must be fail-safe.

    A Sentry SDK failure must never replace or mask the original application failure.

    If reporting itself raises unexpectedly, emit at most one static bounded application log such as:

    ```text
    sentry_reporting_failed
    ```

    containing only the Sentry reporting exception type, then return without raising it.

25. Sentry initialization failure must similarly not expose the DSN or SDK exception message. Missing `SENTRY_RELEASE` while `SENTRY_DSN` is configured is not a runtime reporting failure: it is invalid application configuration and must fail fast during `Settings` validation.

26. Add tests proving:

    - empty DSN is a real no-op;
    - Sentry DSN/release are resolved by the existing `Settings` model and the adapter does not perform direct Sentry env lookup;
    - Sentry DSN requires explicit release;
    - enabled configuration has no default/auto integrations;
    - Sentry logs, trace propagation, tracing sampling, profiling sampling and auto session tracking are explicitly disabled;
    - `enable_metrics` is not configured, `before_send_metric` uses the application-owned drop callback, the callback returns `None`, and metric telemetry cannot produce a Sentry envelope item;
    - `LoggingIntegration`, `ExcepthookIntegration`, FastAPI/Starlette, SQLAlchemy and HTTPX are not enabled;
    - safe `AtexitIntegration` is enabled;
    - error tracing/performance is disabled;
    - a captured exception becomes exactly one error event;
    - no log/transaction event is generated;
    - exception type and stack location survive;
    - chained exceptions remain structurally understandable;
    - secret values in exception messages and locals are absent from the final event;
    - hostile request/user/header/query/cookie/extra-shaped data is absent from the fully serialized final event;
    - unbounded or malformed values for approved context keys are dropped rather than passed through;
    - safe request/trace/run correlation survives;
    - high-cardinality correlation does not create a custom fingerprint;
    - different request/run IDs do not alter the grouping inputs;
    - reporting failure cannot escape to the caller.

Use an SDK-level test transport or equivalent test-only capture mechanism so the final post-`before_send` event can be inspected without network access.

Do not introduce a production transport abstraction only to support tests.

## Invariants

- Domain/Application remains unaware of Sentry.
- Existing observability behavior is untouched.
- No HTTP behavior changes.
- No CLI behavior changes.
- No persistence changes.
- No SDK auto-capture.
- Sentry is disabled by default.
- Sentry-owned deployment configuration is centralized in the existing `Settings`; the adapter has no direct Sentry env lookup.
- No runtime git release discovery when Sentry is enabled.
- Raw exception messages never become Sentry data.
- Sentry failure cannot break application execution.

## Out of scope

- HTTP integration.
- CLI integration.
- Production Compose.
- Architecture guards.
- Operational documentation.
- Frontend.
- Any change to OpenTelemetry.

## AI prompt

Implement only Step 1 of ANY-458: establish the privacy-safe backend Sentry infrastructure and event contract.

The repository research and architecture decisions are already complete. Do not perform broad repository research and do not redesign the solution.

Inspect only the directly relevant current files if needed to verify these assumptions:

- `apps/api/pyproject.toml`
- `apps/api/app/core/settings.py`
- `apps/api/app/core/observability.py`
- `apps/api/app/core/errors/**`
- `apps/api/app/payment_providers/errors.py`
- existing test conventions under `apps/api/tests/`
- existing test support only if needed for a test-only Sentry transport helper

Follow these decisions exactly:

1. Add the exact runtime dependency `sentry-sdk==2.69.1`.
2. Regenerate `apps/api/uv.lock` with the repository-owned command `npm run lock:api`. Lockfile generation is part of implementation, not verification.
3. Add optional `sentry_dsn` and `sentry_release` fields to the existing Pydantic `Settings` model, following existing whitespace normalization. `SENTRY_DSN` and `SENTRY_RELEASE` must be resolved only by this `Settings` model. The Sentry adapter must not call `os.getenv()` / read `os.environ` for them and must not instantiate another settings object. Existing `settings.app_env` is the environment source.
4. Do not add a separate Sentry enabled flag. Empty `settings.sentry_dsn` means disabled.
5. Add `Settings` validation: if `sentry_dsn` is configured, `sentry_release` must be non-empty. This invalid configuration fails fast during `Settings` construction. Do not allow the SDK to fall back to runtime git release discovery.
6. Create exactly one vendor-specific application adapter at `apps/api/app/infrastructure/sentry.py`. Do not create a generic monitoring port, ErrorReporter interface, or reporting framework.
7. Only that adapter may import `sentry_sdk`; architecture enforcement is a later plan step.
8. Define the closed reporting categories:
   - `internal_application_failure`
   - `integration_failure`
   - `unknown_external_outcome`
   - `unexpected_exception`
   - `consistency_invariant_violation`
   Also define the closed operation vocabulary for this ticket: `http_request` and `expire_subscriptions`. Do not accept arbitrary free-form operation tags.
9. Implement semantic classification without parsing messages:
   - `PaymentsOperationDeclinedError` => not reportable
   - `PaymentsTimeoutError` => `unknown_external_outcome`
   - `PaymentsIdempotencyKeyRequiredError` => `internal_application_failure`
   - `PaymentProviderConfigurationError` => `internal_application_failure`
   - another `PaymentsError` => `integration_failure`
   - another `AppError` => `internal_application_failure`
   - ordinary unexpected `Exception` => `unexpected_exception`
   Invariant violations are explicitly overridden by the boundary caller later.
10. Implement `configure_sentry(...)` so it receives the existing application `Settings` from the composition root. Do not read Sentry-owned environment variables inside the adapter. If `settings.sentry_dsn` is empty, do not call `sentry_sdk.init`.
11. When enabled, initialize Sentry with:
   - `default_integrations=False`
   - `auto_enabling_integrations=False`
   - `send_default_pii=False`
   - `include_local_variables=False`
   - `include_source_context=False`
   - `max_request_body_size="never"`
   - `traces_sample_rate=0.0`
   - `profiles_sample_rate=0.0`
   - `enable_logs=False`
   - `before_send_metric=_drop_metric`, with the callback returning `None`
   - `propagate_traces=False`
   - `auto_session_tracking=False`
   - error `sample_rate=1.0`
12. Explicitly enable only `AtexitIntegration`, with a silent shutdown callback so it can flush queued events without changing CLI stdout/stderr.
13. Use `settings.app_env` as Sentry environment and `settings.sentry_release` as release; do not read `APP_ENV` / `SENTRY_RELEASE` directly inside the adapter.
14. Reuse the existing `OTEL_SERVICE_NAME` source and fallback as the stable Sentry `service` tag. Do not add `SENTRY_SERVICE_NAME`.
15. Implement one `report_exception(...)` application entrypoint using a temporary per-call Sentry scope.
16. Add only `service`, `failure_category`, and `operation` as stable tags.
17. Reuse existing ambient request ID and OpenTelemetry trace/span IDs. Allow only the approved safe context fields: `request_id`, `trace_id`, `span_id`, `run_id`, `method`, matched `route`, bounded `error_code`, `invariant`, `batch_size`, and safe `failure_location`.
18. Do not query the DB or inspect provider/customer objects to enrich an event.
19. Do not set a custom fingerprint. Correlation identifiers must not affect grouping.
20. Add a strict `before_send` positive allowlist over the final SDK event. Top-level allowed keys are only `event_id`, `timestamp`, `platform`, `level`, `exception`, `tags`, `contexts`, `release`, `environment`, and `sdk`; preserve `event_id` because the SDK transport requires it after `before_send`. Keep only `service`/`failure_category`/`operation` tags; only the `payment_portal` custom context; sanitized exception type/module/stack/chaining structure; repository-safe frame filename/module/function/line/`in_app`; and SDK name/version/package identity. Drop all unknown top-level keys plus request/user/breadcrumb/extra/log/message/transaction/modules/threads/server/fingerprint data, arbitrary tags/contexts, exception values/messages, locals, source-code context and absolute paths.
21. Validate approved context values exactly: existing request-id contract (max 128), trace ID = 32 lowercase hex, span ID = 16 lowercase hex, run ID = canonical UUID, method = uppercase token max 16, matched route template max 256 with no query/fragment, error code = `[a-z0-9][a-z0-9_.:-]{0,127}`, invariant = `[a-z0-9][a-z0-9_.:-]{0,63}`, batch size = integer `1..1000`, failure-location module max 256/function max 128/line positive integer. Drop malformed/unbounded values; never truncate arbitrary external text into an approved field.
22. Do not use raw `str(error)`, exception messages, arbitrary exception attributes, provider payloads, request input, user/email data, card/payment data, tokens, headers, cookies or query values.
23. Treat configuration and reporting failures differently: `SENTRY_DSN` without `SENTRY_RELEASE` must fail fast during `Settings` validation; SDK init/capture/transport failures after valid configuration must fail safe.
24. Make Sentry reporting fail-safe. An SDK/reporting failure must never replace the original application failure. If a bounded diagnostic is emitted for a reporting failure, log only a static event and reporting exception type.
25. Add focused `apps/api/tests/test_sentry_reporting.py` tests. Use a test-only SDK transport or equivalent mechanism to inspect the final sanitized captured event without any network request. Do not add a production transport abstraction solely for tests.
26. Tests must verify Settings-owned DSN/release behavior, disabled configuration, explicit release validation, no adapter-side direct Sentry env lookup, disabled default/auto integrations, explicitly disabled logs/tracing sampling/profiling sampling/trace propagation/session tracking, `enable_metrics` absent from the configured options, metric telemetry hard-dropped by the `before_send_metric` callback, only safe shutdown integration, exactly one error event, the exact top-level/subfield allowlist (including preserved `event_id`), absence of transaction/log events, privacy scrubbing, preserved safe stack/cause, exact context-value validation, safe correlation context, stable grouping inputs, and fail-safe reporting.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Before finishing, run targeted `ruff format` on the Python files changed in this step, then run the focused pytest and `ruff check` verification for this step. Do not run repository-wide, Docker-heavy, or PostgreSQL-heavy gates; leave those larger checks for the developer unless a focused test in this step inherently requires the repository PostgreSQL workflow.
Do not stage files.
Do not create commits.

After implementation:
- report the changed files;
- briefly summarize what changed;
- report the focused verification results;
- report the larger/manual verification commands that remain for me, if any.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Focused verification

Agent runs the targeted formatting/checks during implementation; the developer may repeat the following focused checks from repository root:

```bash
npm run lock:check:api

cd apps/api
uv run ruff format app/core/settings.py app/infrastructure/sentry.py tests/test_sentry_reporting.py
uv run pytest tests/test_sentry_reporting.py -q
uv run ruff check app/core/settings.py app/infrastructure/sentry.py tests/test_sentry_reporting.py
uv run ruff format --check app/core/settings.py app/infrastructure/sentry.py tests/test_sentry_reporting.py
```

## Expected completion

- Sentry dependency and configuration exist.
- Empty DSN causes no SDK initialization.
- Enabled Sentry requires an explicit release.
- No framework/logging/excepthook auto-capture exists.
- Exactly one explicit sanitized error event can be captured.
- Stack/cause remain useful without exception text or locals.
- Reporting is fail-safe.
- No runtime caller has been changed yet.

## Proposed commit

`feat(api): establish safe Sentry error reporting`

---

# Step 2 — Integrate Sentry with the single HTTP failure boundary

**Status:** `done`

## Goal

Make current reportable HTTP application failures produce exactly one safe Sentry event at the existing Presentation failure boundary while preserving all ANY-415/ANY-437 HTTP, logging, privacy and correlation contracts.

## Scope / affected code

Primary:

- `apps/api/app/main.py`
- `apps/api/app/http_errors.py`
- `apps/api/tests/test_error_handling.py`

Existing infrastructure from Step 1:

- `apps/api/app/infrastructure/sentry.py`
- `apps/api/tests/test_sentry_reporting.py`

No router/domain/provider implementation should require modification merely to report errors.

## Implementation decisions

1. Configure Sentry once at the API composition root in `app/main.py`.

2. Preserve the existing:

   ```text
   app = create_app()
   configure_observability(...)
   ```

   composition.

   Configure Sentry after existing observability/logging initialization so bounded Sentry initialization diagnostics use the established application logging format.

3. Do not pass the FastAPI app to Sentry.

4. Do not enable Sentry FastAPI/Starlette middleware/integration.

5. Preserve:

   - `unexpected_failure_middleware`;
   - `request_context_middleware`;
   - their existing ordering;
   - `AppError` handler registration.

6. Evolve the existing private `_log_internal_failure(...)` responsibility into one HTTP-boundary report operation, e.g. `_report_internal_failure(...)`.

   It should:

   - compute the existing safe structured diagnostic once;
   - emit exactly the existing `http_internal_failure` log;
   - classify whether Sentry should receive the exception;
   - explicitly capture at most one Sentry event.

7. Preserve the current log fields and privacy behavior.

8. Mapped `HTTP_ERROR_RESPONSES` must return before Sentry reporting.

9. Normal provider decline remains no-Sentry even if it unexpectedly reaches this generic internal boundary.

   Do not change its current HTTP behavior as part of this ticket.

10. For reportable errors:

    ```text
    PaymentsTimeoutError
        -> unknown_external_outcome

    PaymentsIdempotencyKeyRequiredError
        -> internal_application_failure

    PaymentProviderConfigurationError
        -> internal_application_failure

    other PaymentsError
        -> integration_failure

    unmapped AppError
        -> internal_application_failure

    unexpected Exception
        -> unexpected_exception
    ```

11. Send:

    ```text
    operation=http_request
    method
    matched route template
    error_code when existing bounded AppError code is available
    safe failure_location
    ```

12. Let the Sentry adapter attach existing ambient:

    ```text
    request_id
    trace_id
    span_id
    ```

13. Do not add:

    - raw URL;
    - path parameter values;
    - query data;
    - request headers;
    - body;
    - cookies;
    - email/user;
    - provider details;
    - `details_safe`;
    - exception message.

14. Keep the existing Sentry-independent structured log even when Sentry reporting succeeds.

15. If Sentry fails, HTTP failure behavior stays:

    ```json
    {
      "detail": {
        "code": "internal_server_error"
      }
    }
    ```

16. Add regression tests proving:

    - mapped expected business error → 0 Sentry reports;
    - normal `PaymentsOperationDeclinedError` → 0 Sentry reports;
    - unmapped AppError → exactly 1;
    - provider integration failure → exactly 1;
    - provider timeout/unknown outcome → exactly 1;
    - unexpected exception → exactly 1;
    - each reportable failure still produces exactly one existing `http_internal_failure` log;
    - no ERROR-log-generated duplicate Sentry event exists;
    - HTTP status/body remain unchanged;
    - response `X-Request-ID` remains unchanged;
    - Sentry context contains the same safe request ID;
    - trace/span values are carried when existing OTEL context provides them;
    - matched route template is included;
    - raw path parameter value is absent;
    - query/header/local/exception secrets from the existing adversarial test are absent from the final Sentry event;
    - safe application `failure_location` remains present where available.

Reuse the privacy scenario already established by `test_unexpected_failures_are_converted_and_logged_safely` instead of inventing an unrelated synthetic flow.

## Invariants

- Existing error taxonomy remains unchanged.
- Existing HTTP mapping remains unchanged.
- Existing status codes remain unchanged.
- Generic 500 body remains unchanged.
- `X-Request-ID` remains unchanged.
- One unexpected failure still emits one bounded log diagnostic.
- One reportable application failure emits at most one Sentry event.
- Expected business failures do not create Sentry issues.
- No SDK import enters `http_errors.py`.
- No Domain/Application changes.
- No automatic FastAPI capture.
- No PII/raw request data in Sentry.

## Out of scope

- New HTTP exception classes.
- New status mappings.
- Router refactoring.
- Provider retry changes.
- New Sentry middleware.
- Performance tracing.
- CLI reporting.
- Production environment wiring.
- Sync/async changes.

## AI prompt

Implement only Step 2 of ANY-458: integrate the Step 1 Sentry adapter with the existing single HTTP failure boundary.

Step 1 is already implemented and is the source of truth. Do not redesign the Sentry adapter or repeat broad repository research.

Inspect only these directly relevant files if needed:

- `apps/api/app/main.py`
- `apps/api/app/http_errors.py`
- `apps/api/app/infrastructure/sentry.py`
- `apps/api/app/core/observability.py`
- `apps/api/tests/test_error_handling.py`
- the focused Step 1 Sentry tests only as needed to reuse their test approach

Follow these decisions:

1. Preserve the current ANY-415/ANY-437 middleware ordering, AppError handler registration, generic 500 contract, request-ID behavior, bounded HTTP failure logging and privacy rules.
2. Initialize the existing Step 1 Sentry adapter at the API composition root. Keep Sentry framework integrations disabled; do not add Sentry middleware or pass FastAPI/Starlette objects into Sentry.
3. Keep the existing application structured log as an independent diagnostic signal.
4. Refactor the existing private HTTP internal-failure helper only as needed so the same outer boundary owns both:
   - the existing single `http_internal_failure` structured log;
   - at most one explicit Sentry report.
5. Mapped `HTTP_ERROR_RESPONSES` must return without Sentry capture.
6. Use the Step 1 semantic classifier:
   - normal `PaymentsOperationDeclinedError` => no Sentry
   - `PaymentsTimeoutError` => `unknown_external_outcome`
   - `PaymentsIdempotencyKeyRequiredError` => `internal_application_failure`
   - `PaymentProviderConfigurationError` => `internal_application_failure`
   - other reportable `PaymentsError` => `integration_failure`
   - unmapped non-provider `AppError` => `internal_application_failure`
   - unexpected exception => `unexpected_exception`
7. Do not change the existing HTTP behavior of any of those exception types merely to improve Sentry classification.
8. For a reportable HTTP failure send only:
   - operation `http_request`
   - HTTP method
   - matched route template
   - existing bounded AppError code when applicable
   - the existing safe application failure location
   The Step 1 adapter must add request/trace/span correlation from the current ambient observability context.
9. Never pass raw request URL/path values, query values, headers, cookies, bodies, email/user data, provider payloads, `details_safe`, exception messages or locals.
10. Sentry reporting failure must not change the existing generic HTTP response or propagate a new error.
11. Extend `apps/api/tests/test_error_handling.py` with focused Sentry reporting assertions:
   - expected mapped business error => zero reports
   - normal provider decline => zero reports
   - unmapped AppError => exactly one
   - provider integration failure => exactly one
   - provider timeout => exactly one with unknown-outcome category
   - unexpected exception => exactly one
   - exactly one existing `http_internal_failure` log remains
   - no logging-generated duplicate event
   - response status/body/X-Request-ID remain unchanged
   - request ID and deterministic trace/span correlation are present when available
   - matched route template and safe failure location are present
   - the existing adversarial exception/path/query/header/local secret markers do not occur anywhere in the final captured Sentry event.
12. Reuse the Step 1 test-only capture strategy. Do not create a production transport abstraction for testing.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Before finishing, run targeted `ruff format` on the Python files changed in this step, then run the focused pytest and `ruff check` verification for this step. Do not run repository-wide, Docker-heavy, or PostgreSQL-heavy gates; leave those larger checks for the developer unless a focused test in this step inherently requires the repository PostgreSQL workflow.
Do not stage files.
Do not create commits.

After implementation:
- report the changed files;
- briefly summarize what changed;
- report the focused verification results;
- report the larger/manual verification commands that remain for me, if any.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Focused verification

Agent runs targeted formatting plus the focused checks below; the developer may repeat them before committing:

```bash
cd apps/api
uv run ruff format app/main.py app/http_errors.py tests/test_error_handling.py
uv run pytest tests/test_sentry_reporting.py tests/test_error_handling.py -q
uv run ruff check app/main.py app/http_errors.py tests/test_error_handling.py
uv run ruff format --check app/main.py app/http_errors.py tests/test_error_handling.py
```

## Expected completion

- API initializes Sentry only when configured.
- Mapped business errors generate no Sentry issue.
- Normal provider decline generates no Sentry issue.
- Every reportable HTTP failure generates exactly one explicit Sentry event.
- Existing bounded HTTP logging still occurs exactly once.
- Response semantics and request correlation are unchanged.
- Sentry event is actionable but contains no raw request/error/PII data.

## Proposed commit

`feat(api): report HTTP failures to Sentry`

---

# Step 3 — Add Sentry reporting to the scheduled subscription-expiry boundary

**Status:** `done`

## Goal

Cover the current non-HTTP scheduled execution boundary so real lifecycle failures and the existing post-commit diagnostic invariant become Sentry issues correlated by `run_id`, without introducing a worker/job framework or changing lifecycle transaction semantics.

## Scope / affected code

Primary:

- `apps/api/app/commands/expire_subscriptions.py`
- `apps/api/tests/test_expire_subscriptions_cli.py`

Existing adapter:

- `apps/api/app/infrastructure/sentry.py`

Do not modify billing lifecycle implementation unless the current command materially contradicts the already-established ANY-437 transaction contract.

## Implementation decisions

1. Preserve the current command's existing:

   ```text
   configure_logging()
   run_id
   start/failure/invariant/transition/success diagnostics
   lifecycle transaction ownership
   stdout
   exception propagation
   ```

2. Configure Sentry at this process composition boundary after logging initialization.

3. Do not import `app.main`.

4. Do not initialize FastAPI.

5. Do not create a new job/runtime abstraction.

6. For exception from `expire_due_subscriptions(...)`:

   - first preserve the existing `subscription_expiry_run_failed` bounded log;
   - classify the original exception through the Step 1 reporting policy;
   - if reportable, send exactly one Sentry event;
   - pass:

     ```text
     operation=expire_subscriptions
     run_id
     batch_size
     ```

   - re-raise the original exception unchanged.

7. No raw lifecycle exception message enters Sentry.

8. For the existing missing-persisted-identity invariant:

   - preserve the exact existing `subscription_expiry_diagnostic_invariant_violated` log semantics;
   - preserve the same `RuntimeError` type/message used by the existing CLI behavior;
   - ensure the exception acquires a real Python traceback before reporting it; do **not** call `report_exception(...)` on a never-raised exception object;
   - raise/catch that same `RuntimeError` locally at this boundary, report the caught exception, then re-raise that same exception unchanged;
   - report it explicitly with:

     ```text
     failure_category=consistency_invariant_violation
     operation=expire_subscriptions
     run_id
     batch_size
     invariant=missing_persisted_identity
     ```

   - raise the same error afterward.

9. Do **not** emit:

   ```text
   subscription_expiry_run_failed
   ```

   for the post-commit identity invariant.

   ANY-437 deliberately distinguishes this from lifecycle failure because committed lifecycle changes already exist.

10. Successful expiry run generates zero Sentry events.

11. `subscription_expiry_transition_committed` remains a log/durable-state correlation signal, not a Sentry event.

12. Do not report every successfully expired subscription.

13. Do not add:

    - cron monitoring;
    - Sentry Cron Monitor;
    - job metrics;
    - worker;
    - task table;
    - OTLP bootstrap;
    - additional tracing.

14. Rely on the explicitly enabled safe `AtexitIntegration` from Step 1 for final Sentry transport shutdown/flush.

15. Add focused tests proving:

    - success → zero Sentry events;
    - lifecycle exception → one event;
    - lifecycle exception is still re-raised;
    - lifecycle failure keeps the existing log timeline;
    - invariant → one event;
    - invariant category is `consistency_invariant_violation`;
    - invariant still has no `run_failed` log;
    - failure/invariant event carries the same run ID as logs;
    - raw lifecycle/invariant exception message is absent from final event;
    - the invariant event still contains the real application stack location from the raised/caught `RuntimeError`;
    - existing successful stdout is unchanged;
    - existing transaction/durability behavior is untouched.

## Invariants

- Billing lifecycle behavior unchanged.
- No DB transaction changes.
- `SubscriptionEvent` behavior unchanged.
- Existing log timeline unchanged.
- Existing `run_id` remains the non-HTTP correlation key.
- Successful stdout unchanged.
- Failure exceptions still propagate.
- Post-commit invariant is not relabeled as lifecycle failure.
- No worker/job redesign.
- Sentry remains outside Domain/Application.

## Out of scope

- Sentry Cron Monitoring.
- Scheduler redesign.
- Worker queues.
- Async jobs.
- Persistent job records.
- Changes to `expire_due_subscriptions`.
- New metrics.
- Persistence work from later ANY-407 steps.

## AI prompt

Implement only Step 3 of ANY-458: add explicit Sentry error reporting to the existing scheduled subscription-expiry CLI boundary.

Steps 1 and 2 are already implemented. Use the existing `app/infrastructure/sentry.py` adapter and reporting policy; do not redesign it.

Work primarily in:

- `apps/api/app/commands/expire_subscriptions.py`
- `apps/api/tests/test_expire_subscriptions_cli.py`

Inspect the directly related lifecycle implementation only if necessary to verify that the ANY-437 transaction assumptions are still true. Do not change lifecycle architecture.

Follow these decisions:

1. Preserve all current ANY-437 subscription-expiry logging, `run_id`, transaction, stdout and exception semantics.
2. Keep `configure_logging()` and configure the existing Sentry adapter at this CLI/process composition boundary after logging initialization.
3. Do not import `app.main`, FastAPI, or create any new job/runtime abstraction.
4. When `expire_due_subscriptions(...)` raises:
   - preserve the existing `subscription_expiry_run_failed` structured log exactly in semantic meaning;
   - classify the original exception using the Step 1 Sentry policy;
   - if reportable, explicitly report it exactly once;
   - use operation `expire_subscriptions`;
   - include only existing safe `run_id` and `batch_size`;
   - re-raise the original exception unchanged.
5. Never pass the raw exception message, traceback string, entity data or database state into Sentry.
6. For the existing missing persisted identity diagnostic invariant:
   - preserve the existing `subscription_expiry_diagnostic_invariant_violated` log;
   - preserve the same `RuntimeError` type/message currently raised by the CLI;
   - do not report a newly constructed never-raised exception object; ensure that same `RuntimeError` first acquires a real traceback (raise/catch it locally at the boundary), report the caught exception exactly once with category `consistency_invariant_violation`, then re-raise that same exception unchanged;
   - operation is `expire_subscriptions`;
   - include only `run_id`, `batch_size`, and the static invariant value `missing_persisted_identity`.
7. Do not emit or introduce `subscription_expiry_run_failed` for that post-commit diagnostic invariant. The lifecycle work has already committed and ANY-437 intentionally distinguishes this condition.
8. Successful runs must generate zero Sentry events.
9. Do not create Sentry events for each successful `subscription_expiry_transition_committed` diagnostic.
10. Do not add Sentry Cron Monitoring, Prometheus job metrics, a scheduler, worker, task table, new tracing bootstrap or any sync/async redesign.
11. Extend the focused CLI tests to prove:
   - successful run => zero Sentry reports and unchanged stdout;
   - lifecycle failure => exactly one Sentry report and unchanged existing log timeline;
   - the original failure still propagates;
   - invariant => exactly one consistency-invariant Sentry report;
   - invariant still emits no `subscription_expiry_run_failed`;
   - Sentry and logs share the existing `run_id`;
   - raw exception/invariant text is absent from the final captured event;
   - the invariant event retains a real application stack location after exception-message removal;
   - existing durability/transaction semantics remain unchanged.
12. Reuse the test-only Sentry capture strategy from Step 1. Do not add a production testing abstraction.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Before finishing, run targeted `ruff format` on the Python files changed in this step, then run the focused pytest and `ruff check` verification for this step. Do not run repository-wide, Docker-heavy, or PostgreSQL-heavy gates; leave those larger checks for the developer unless a focused test in this step inherently requires the repository PostgreSQL workflow.
Do not stage files.
Do not create commits.

After implementation:
- report the changed files;
- briefly summarize what changed;
- report the focused verification results;
- report the larger/manual verification commands that remain for me, if any.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Focused verification

Agent runs targeted formatting plus these focused checks when they do not require PostgreSQL; the developer may repeat them before committing.

Without PostgreSQL-dependent cases:

```bash
cd apps/api
uv run ruff format app/commands/expire_subscriptions.py tests/test_expire_subscriptions_cli.py
uv run pytest tests/test_sentry_reporting.py tests/test_expire_subscriptions_cli.py -q
uv run ruff check app/commands/expire_subscriptions.py tests/test_expire_subscriptions_cli.py
uv run ruff format --check app/commands/expire_subscriptions.py tests/test_expire_subscriptions_cli.py
```

If the then-current focused CLI test selection requires the repository PostgreSQL test database, use the existing repository DB test workflow and run the same focused test file against it.

## Expected completion

- Successful scheduled runs generate no Sentry noise.
- Failed scheduled runs generate one correlated Sentry issue.
- Diagnostic invariant violations generate one correctly classified Sentry issue.
- Existing `run_id` connects Sentry to logs and durable lifecycle state.
- Transaction, logging and CLI semantics are unchanged.

## Proposed commit

`feat(api): report scheduled failures to Sentry`

---

# Step 4 — Lock deployment, architecture, privacy and investigation contracts

**Status:** `done`

## Goal

Make the completed Sentry integration deployable and durable as an architectural/operational contract, prevent SDK leakage into inner layers, document the Sentry-first incident workflow, and perform the final applicable repository verification.

## Scope / affected code

Runtime/deployment:

- `.env.production.example`
- `docker-compose.prod.yml`

Focused deployment tests:

- `apps/api/tests/test_deployment_contract.py`

Architecture enforcement:

- `scripts/repo.py`
- `apps/api/tests/test_architecture.py`

Authoritative documentation:

- `ARCHITECTURE.md`
- `docs/RELIABILITY.md`
- `docs/SECURITY.md`
- `docs/architecture/deployment.md`

No business/runtime failure handling should be redesigned in this step.

## Implementation decisions

### Production configuration

1. Add to `.env.production.example`:

   ```text
   SENTRY_DSN=
   SENTRY_RELEASE=
   ```

2. Add the same optional environment variables to the shared production API environment in `docker-compose.prod.yml`.

3. Do not add:

   ```text
   SENTRY_ENABLED
   SENTRY_ENVIRONMENT
   SENTRY_SERVICE_NAME
   SENTRY_TRACES_SAMPLE_RATE
   ```

4. `APP_ENV` remains the environment source.

5. `OTEL_SERVICE_NAME` remains the service identity source.

6. Deployment/CI must provide `SENTRY_RELEASE` when enabling Sentry.

7. Do not discover release from git inside the running container.

8. Do not hardcode a production DSN.

### Deployment tests

Add focused assertions that production configuration exposes:

```text
SENTRY_DSN
SENTRY_RELEASE
```

without making Sentry mandatory.

Preserve the current migrate/API environment equality contract.

### Architecture guard

Extend the existing Python AST boundary checker with one narrow rule:

```text
`sentry_sdk` and any `sentry_sdk.*` module may be imported by application code only from
`apps/api/app/infrastructure/sentry.py`
```

All other application modules must use that adapter.

This includes rejecting direct imports from:

- core;
- domain/application;
- provider contracts;
- integrations;
- routers/presentation;
- commands;
- composition root.

The composition root and boundary callers import:

```text
app.infrastructure.sentry
```

not `sentry_sdk`.

Do not create a new architecture-check framework.

Add focused architecture tests proving:

- a domain/application direct Sentry SDK import is rejected;
- a payment-provider/integration direct import is rejected;
- a presentation/command direct SDK import is rejected;
- the intended `app/infrastructure/sentry.py` import is allowed.

### `ARCHITECTURE.md`

Replace the now-stale statement that Sentry is outside the architecture.

Document:

```text
Domain/Application
    -> semantic errors

outer Presentation/process boundary
    -> structured diagnostic
    -> explicit Sentry report according to policy
```

State explicitly:

- `sentry_sdk` is infrastructure-only;
- errors do not carry Sentry flags;
- mapped expected business errors are not Sentry issues;
- existing logs/traces/metrics remain separate signals.

### `docs/RELIABILITY.md`

Update signal ownership:

```text
Sentry
    = primary error-issue entrypoint for reportable application failures

OpenTelemetry
    = operation trace

structured logs
    = bounded incident detail

Prometheus
    = aggregate health/outcomes

persisted state
    = business truth
```

Document the HTTP investigation journey:

```text
Sentry issue
    -> failure category / stack / release
    -> request_id + trace_id
    -> trace + structured logs
    -> local Payment Portal diagnostic IDs
    -> persisted records/events
```

Document the scheduled journey:

```text
Sentry issue
    -> run_id
    -> subscription expiry diagnostics
    -> subscription_id
    -> SubscriptionEvent
```

Document that current production trace/log backend URLs are deployment-owned and no stable repository-configured query URL exists, therefore ANY-458 intentionally does not generate direct trace/log hyperlinks.

Document that broad production monitoring/availability remains owned by `ANY-86`.

### `docs/SECURITY.md`

Add the explicit Sentry data contract.

Allowed:

- release/environment/service;
- failure category;
- stable operation;
- exception type;
- sanitized stack locations;
- safe cause structure;
- request/trace/span/run IDs;
- matched route template;
- approved failure location;
- explicitly allowlisted static/bounded diagnostic fields.

Forbidden:

- raw exception messages;
- locals;
- source-code context;
- request body;
- raw URL/path values;
- query;
- headers;
- cookies;
- email/user data;
- IP data;
- provider payloads;
- provider external IDs;
- authorization/tokens;
- card/payment values.

State:

- client-side allowlisting/scrubbing is primary;
- Sentry server/project data scrubbing and IP scrubbing are defense in depth;
- high-cardinality identifiers must not become tags or fingerprints.

### Deployment architecture

Update the deployment description to represent optional outbound Sentry error reporting separately from the existing optional OTEL backend.

Do not imply Sentry owns tracing, logs or metrics.

### Sentry project-side operational settings

Document, but do not automate in this repository:

- enable Sentry project data scrubbing as defense in depth;
- disable/scrub IP collection;
- configure a useful notification for new/regressed production issues.

Do not add Sentry management API calls, Terraform, dashboards or general alerting infrastructure in this ticket.

## Invariants

- Existing HTTP/business/persistence behavior unchanged.
- Sentry remains optional.
- Sentry SDK remains behind one outer infrastructure adapter.
- Existing ANY-437 telemetry roles remain intact.
- No PII is made acceptable merely because Sentry has server-side scrubbing.
- Production monitoring scope from ANY-86 is not absorbed.
- No speculative trace/log URL configuration is introduced.

## Out of scope

- Sentry project provisioning automation.
- Organization/project creation.
- Terraform.
- Sentry alert-rule IaC.
- Grafana/Tempo/Loki deployment.
- HetrixTools configuration.
- Frontend Sentry.
- Any business code refactor.

## AI prompt

Implement only Step 4 of ANY-458: lock the deployment, architecture, privacy and operational investigation contracts for the already-implemented Sentry integration.

Steps 1 through 3 are already implemented and are the source of truth. Do not redesign their runtime behavior.

Inspect only these directly relevant current files if needed:

- `.env.production.example`
- `docker-compose.prod.yml`
- `apps/api/tests/test_deployment_contract.py`
- `scripts/repo.py`
- `apps/api/tests/test_architecture.py`
- `ARCHITECTURE.md`
- `docs/RELIABILITY.md`
- `docs/SECURITY.md`
- `docs/architecture/deployment.md`
- `apps/api/app/infrastructure/sentry.py` only to verify the contract being documented/enforced

Follow these decisions:

1. Add optional `SENTRY_DSN` and `SENTRY_RELEASE` to the production environment example and production API environment wiring. These variables are consumed through the existing Pydantic `Settings` fields created in Step 1; runtime Sentry code must not read them directly from the environment.
2. Do not add separate enable, environment, service-name, tracing, profiling or sampling environment variables. The error-only sampling/telemetry-disable policy remains hard-coded in the adapter.
3. Preserve `settings.app_env` / `APP_ENV` as Sentry environment and the existing `OTEL_SERVICE_NAME` source as service identity.
4. Deployment/CI supplies `SENTRY_RELEASE` when Sentry is enabled. Do not add runtime git release discovery.
5. Preserve existing production migrate/API environment equality.
6. Add focused deployment-contract coverage for the Sentry variables without making Sentry mandatory.
7. Extend the existing Python AST architecture checker with one narrow Sentry dependency rule: application code may import `sentry_sdk` or any `sentry_sdk.*` module only from `apps/api/app/infrastructure/sentry.py`. Every other application module must depend on that adapter instead.
8. Add focused architecture tests proving forbidden imports from inner/provider/integration/presentation/command code are rejected and the intended infrastructure adapter is allowed.
9. Do not create a new architecture-check framework.
10. Update `ARCHITECTURE.md` so it no longer says Sentry is deferred. Document explicit outer-boundary reporting and the prohibition on Domain/Application Sentry dependencies or reporting flags.
11. Update `docs/RELIABILITY.md` so Sentry is the primary investigation entry point for reportable application failures, while OpenTelemetry remains tracing, structured logs remain bounded diagnostics, Prometheus remains aggregate metrics, and persisted state remains business truth.
12. Document the HTTP investigation path:
    `Sentry -> request_id/trace_id -> trace/logs -> approved local diagnostic IDs -> persisted state`.
13. Document the scheduled expiry path:
    `Sentry -> run_id -> expiry diagnostics -> subscription_id -> SubscriptionEvent`.
14. State explicitly that the current repository has no stable production trace/log query base URL, so this ticket does not invent direct Sentry-to-Grafana/Tempo/Loki links or new URL settings.
15. Update `docs/SECURITY.md` with the explicit Sentry event allowlist and forbidden data categories. Client-side sanitization is primary; Sentry project scrubbing/IP scrubbing is defense in depth.
16. Update `docs/architecture/deployment.md` to show optional outbound Sentry error reporting separately from the existing OTEL backend. Do not present Sentry as a tracing/logging/metrics backend.
17. Document that Sentry project-side data scrubbing, IP scrubbing and a useful new/regressed-issue notification should be configured operationally, but do not automate Sentry project management or general monitoring/alerting in this repository.
18. Preserve ANY-86 ownership of broad production monitoring and alerting.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Before finishing, run targeted formatting/checks only for changed Python files and the focused architecture/deployment pytest selection. Do not run `npm run architecture:check`, `npm run docs:check`, `npm run lock:check:api`, `npm run check:fast`, Docker-heavy checks, or PostgreSQL-heavy checks; those final repository gates remain for the developer.
Do not stage files.
Do not create commits.

After implementation:
- report the changed files;
- briefly summarize what changed;
- report the focused verification results;
- report the larger/manual verification commands that remain for me, if any.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Verification

Agent-focused checks before finishing Step 4:

```bash
cd apps/api
uv run ruff format ../../scripts/repo.py tests/test_architecture.py tests/test_deployment_contract.py
uv run ruff check ../../scripts/repo.py tests/test_architecture.py tests/test_deployment_contract.py
uv run pytest tests/test_architecture.py tests/test_deployment_contract.py -q
cd ../..
```

Developer final repository gates after reviewing the complete Step 4 diff:

```bash
npm run architecture:check
npm run docs:check
npm run lock:check:api
```

Then final applicable ticket verification:

```bash
cd apps/api
uv run pytest \
  tests/test_sentry_reporting.py \
  tests/test_error_handling.py \
  tests/test_expire_subscriptions_cli.py \
  tests/test_architecture.py \
  tests/test_deployment_contract.py \
  -q
cd ../..

npm run check:fast
```

If the then-current expiry test selection requires the repository PostgreSQL test database, run that focused file using the existing repository PostgreSQL test workflow as an additional verification. No schema migration or persistence redesign is introduced by ANY-458.

## Expected completion

ANY-458 is complete when:

- Sentry is optional and explicitly configured;
- Sentry logs, metrics, tracing, trace propagation and auto session tracking are explicitly disabled;
- enabled production Sentry has release/environment/service identity;
- reportable HTTP failures produce one issue;
- reportable scheduled failures produce one issue;
- expected business failures do not produce noise;
- exception grouping is not fragmented by request/trace/run IDs;
- stack/cause remains useful;
- raw messages, locals, request data, PII and payment/provider secrets are absent;
- Sentry failure cannot affect application failure behavior;
- Domain/Application cannot import the SDK;
- Sentry is documented as the error-investigation entry point, not as a replacement for OTEL/logs/Prometheus;
- current incident correlation remains usable from Sentry into the existing observability and durable-state trail;
- applicable architecture, documentation, lock and fast quality gates pass;
- when a non-production DSN is available, one manual synthetic smoke event confirms the actual Sentry UI contract and stable grouping.

## Proposed commit

`chore(api): lock Sentry operational contract`

---

# Operational Smoke Verification

After Step 4 focused/repository checks pass and a non-production Sentry project/DSN is available, perform one manual synthetic capture through the real `app.infrastructure.sentry` adapter. This is a deployment/operation verification, not an automated unit-test requirement.

Verify in the Sentry UI that the representative event has:

- exactly one error event / one resulting issue for the synthetic failure;
- expected `release`, `environment`, and `service`;
- expected `failure_category` and `operation`;
- useful sanitized stack/cause information;
- request/trace/run correlation only when the synthetic boundary provides it;
- no raw exception text, locals, request input, query/header/cookie values, PII, provider payloads, tokens, or payment data;
- stable grouping when the same synthetic failure is repeated with different correlation identifiers.

Also confirm project-side operational defenses documented by Step 4:

- Sentry data scrubbing is enabled as defense in depth;
- IP collection is disabled/scrubbed according to the project policy;
- a useful notification exists for new/regressed production issues.

Do not use a production customer/payment failure merely to test Sentry.

---

# Final Acceptance Mapping

| ANY-458 requirement | Plan coverage |
|---|---|
| Backend Sentry SDK | Step 1 |
| Explicit runtime config | Steps 1, 4 |
| Enable/disable without affecting local/test | Step 1 |
| Release/environment/service tagging | Steps 1, 4 |
| No Domain/Application SDK | Steps 1, 4 |
| Explicit reporting policy | Step 1 |
| Expected business errors excluded | Steps 1, 2 |
| Provider decline excluded | Steps 1, 2 |
| Integration failures represented | Steps 1, 2 |
| Unknown external outcomes represented | Steps 1, 2 |
| Unexpected failures | Step 2 |
| Invariant violations | Step 3 |
| HTTP reporting | Step 2 |
| Non-HTTP reporting | Step 3 |
| Exactly one event per failure | Steps 1–3 |
| No logging duplicate | Steps 1, 2 |
| FastAPI/Starlette duplicate prevention | Steps 1, 2 |
| No Excepthook duplicate | Step 1 |
| Privacy/PII protection | Step 1 + Step 4 docs |
| No exception messages | Step 1 |
| No locals/source context | Step 1 |
| No request body/query/header/cookies | Step 1 + Step 2 |
| Safe stack/cause retained | Step 1 |
| Safe request/trace/run correlation | Steps 1–3 |
| Stable grouping | Step 1 |
| No high-cardinality fingerprint/tags | Step 1 |
| Sentry-first investigation | Step 4 |
| Trace/log continuation | Step 4 |
| Direct links only with real backend URL contract | Step 4 — intentionally deferred |
| Production config | Step 4 |
| Architecture enforcement | Step 4 |
| Reliability documentation | Step 4 |
| Security documentation | Step 4 |
| Frontend excluded | All steps |
| Sentry tracing/logs/metrics excluded | All steps |
| No persistence/schema changes | All steps |
| No Sync/Async work | All steps |
| No unrelated ANY-407 future work | All steps |

# Final Plan Validation

The plan was checked against the current ANY-458 acceptance criteria and current merged ANY-415/ANY-437 baseline.

It does not redo:

- Error Architecture;
- structured logging;
- OpenTelemetry;
- metrics;
- request/trace correlation;
- scheduled run correlation.

It does not pull in:

- ANY-454 Sync/Async work;
- Persistence Boundary;
- transaction redesign;
- generic jobs/workers;
- external billing architecture;
- CloudPayments decommission;
- frontend Sentry;
- ANY-86 monitoring infrastructure.

Every material implementation decision required by the execution model is fixed before implementation:

- SDK/version;
- integration mode;
- reporting ownership;
- error classification;
- event data contract;
- privacy model;
- grouping policy;
- HTTP boundary;
- CLI boundary;
- configuration ownership;
- architecture enforcement;
- operational investigation path.

Execution was completed sequentially without requiring a second broad research/design phase.
