# Reliability Requirements

Status: authoritative
Last verified: 2026-09-14

## Critical paths

- API liveness must not depend on PostgreSQL; readiness must.
- Billing must use retry-safe orchestration. The provider-neutral future
  external-command sequence is: persist or find the durable local operation or
  purchase intent, commit it, issue the external command outside any database
  transaction, persist the reliable result and mapping in a subsequent commit,
  then apply a verified fact or reconcile through the shared local transition
  path. Use provider idempotency features when available, but
  do not assume every external command is idempotent.
- A Portal-initiated commercial purchase or change must validate the exact
  `Plan.id`, user, legal, entrypoint, and commercial context and persist its
  Portal-owned purchase intent / commercial `Order` before the external
  commercial command. A commercial `Order` is not required for unrelated
  external billing operations: customer provisioning may correlate through the
  existing Portal `User`, durable operation, and external mapping, while an
  externally initiated or scheduled renewal is projected or reconciled from
  authoritative external facts.
- A timeout or lost response is neither confirmed success nor confirmed failure:
  the external outcome is unknown. Reconcile before deciding whether another
  command is safe; never automatically issue a duplicate create after an
  uncertain outcome.
- Recovery succeeds only when correlation finds exactly one unambiguous external
  object. No unambiguous match remains unknown for later reconciliation or
  another approved safe recovery policy. Multiple plausible matches are
  ambiguous and must fail closed for manual review or repair, without another
  automatic create.
- A valid webhook notification must be authenticated and minimally validated,
  reduced to a whitelisted or redacted inbox record, and durably persisted
  before the external request is acknowledged according to integration policy.
  Processing, retry, and reconciliation then belong to Payment Portal. Once
  receipt is durable, correctness must not depend on the external billing system
  retrying an application-level HTTP failure. Concrete acknowledgement codes and
  external retry policies remain integration-specific. Durability does not
  require persisting the complete raw HTTP request.
- Duplicate authoritative billing facts must not duplicate payment, refund,
  subscription, order, or entitlement changes.
- Stale, duplicate, reordered, or conflicting authoritative billing facts must
  not blindly overwrite newer confirmed state. Explicit transition and
  idempotency rules must reject or ignore them, or trigger reconciliation.
- Valid later lifecycle facts, including refunds, disputes, cancellations, and
  expirations, must remain able to perform their legitimate transitions.
- Verified webhook and future reconciliation facts must feed the same local
  transition path; reconciliation must not become a competing state machine.
- Every external-billing integration must define recovery or reconciliation for
  externally authoritative state changes whose notifications are completely
  missed. Correctness must not depend solely on webhook delivery. The concrete
  mechanism, cadence, cursor, pagination, scheduler, and storage remain outside
  ANY-411.
- Browser return-page state is informational and never billing authority.
- No CloudPayments flow is active in normal runtime. Any future active billing
  integration must obtain authoritative facts through authenticated,
  validated integration facts and reconciliation as required.

## Transaction, idempotency, and retry contract

Application orchestration owns outer business transaction commit and rollback.
Focused persistence/query code owns database mechanics below that boundary:
queries, row locks, atomic DML, flushes, storage-specific exception handling,
and explicitly targeted nested savepoints. A `Session` autobegin does not make
the first persistence helper the logical transaction owner, and those helpers
must not finalize the outer transaction.

The current provider-neutral billing lifecycle participates in a caller-owned
transaction. Same-key operations first inspect the persisted operation event,
serialize on the established row lock, and inspect the operation event again
after acquiring that lock. Once one transaction commits, a concurrent replay
returns the persisted result rather than repeating the transition. Database
uniqueness remains the final invariant; logs and exceptions are not a substitute
for it. Retained CloudPayments webhook transaction and idempotency mechanics are
legacy evidence only, are not active in normal runtime, and are not the target
model.

Database retry decisions use these semantics:

- a transaction known to have rolled back before commit may be retried as the
  whole logical operation, using the same operation identity where supported;
- an operation known to have committed is replayed or read from its persisted
  idempotent result;
- an uncertain local commit requires inspection of authoritative persisted
  state before any retry;
- there is no generic automatic database retry loop.

External-command outcomes have four distinct meanings:

- **confirmed success** — authoritative evidence establishes that the intended
  external command effect occurred; any billing or entitlement transition still
  requires the applicable verified fact and local policy;
- **confirmed failure** — authoritative evidence establishes that the command
  did not produce its intended effect and supplies enough information for the
  integration's explicit failure policy;
- **unknown** — available evidence cannot establish whether the command took
  effect, for example after a timeout or lost response;
- **ambiguous** — observations conflict or correlate to multiple plausible
  external objects, so no single outcome can be selected safely.

Unknown and ambiguous outcomes remain unresolved. They require authoritative
inspection, reconciliation, or another explicitly safe recovery policy before
another external command; they must never trigger a blind duplicate command.
Confirmed external command success is not by itself paid-access authority.

Logs, traces, metrics, and Sentry are diagnostics and correlation aids only.
They never serve as the correctness, transaction, idempotency, or replay store;
persisted local state and events remain authoritative. Existing request/trace
correlation, redaction, and privacy constraints continue to apply during retry
and recovery.

ANY-489 required no schema migration because it changed transaction ownership,
rollback behavior, post-lock rechecks, and architecture enforcement while using
existing persisted operation identities and uniqueness constraints. A future
external-command operation-intent representation remains deferred until the
external-billing work has concrete persistence and recovery requirements; this
document does not invent a table, entity, API, or vendor status for it.

## Framework worker execution

FastAPI/Starlette framework worker capacity is finite and shared. Synchronous
database and application flows run through normal `def` endpoints, and an
async framework boundary delegates a complete resource-owning synchronous unit
through the framework worker mechanism when blocking work is unavoidable. Do
not add unbounded blocking work, unbounded retries, or blocking retry sleeps.

Retained synchronous provider integrations have bounded timeout and retry
budgets in their source code. They are not active normal-runtime paths.
Cancellation of the request or async waiter does not imply that work already
running in a synchronous worker can be forcibly stopped. Resource ownership
must therefore remain inside the delegated synchronous unit, and request ID
plus trace/span/log context must remain correlated across the framework worker
boundary.

Scheduled subscription expiry remains a synchronous CLI. Password-reset email
delivery remains its existing synchronous framework background task. Neither
surface establishes a generic durable job or worker system. Retained
CloudPayments cleanup source is not normal-runtime work and is not permanent
provider lifecycle architecture.

## Agent-verifiable signals

- Every request receives an `X-Request-ID` response header.
- API logs are structured JSON and include request and trace identifiers.
- Metrics expose request latency/errors and billing/legal outcome counters.
- Traces cover HTTP, checkout, legal acceptance, database, and webhook work.
- Critical browser journeys fail on unexpected console errors, failed application
  requests, or error spans.

## Observability and correlation contract

Signals have distinct responsibilities:

- Sentry is the primary error-issue entry point for reportable backend
  application failures. It provides the failure category, sanitized stack, and
  release needed to begin investigation.
- Metrics report bounded rates, outcomes, and durations. They are not a
  business-record lookup index; Prometheus and OpenTelemetry remain the metrics
  owners.
- OpenTelemetry traces show the operation chain across the HTTP request,
  application work, database instrumentation, and provider calls.
- Structured logs provide bounded incident-local detail, including selected
  local diagnostic IDs.
- Persisted billing state and events remain the authoritative business record.

For a reportable HTTP incident, start in Sentry and use its bounded correlation
context to move into the existing telemetry and durable-state trail:

```text
Sentry
    -> request_id / trace_id
    -> trace and structured-log backend
    -> approved local Payment Portal diagnostic IDs
    -> persisted Payment Portal records and events
```

The trace/span IDs and validated `request_id` correlate the issue with the
operation trace and bounded JSON diagnostics. Those diagnostics, not the Sentry
event, provide approved local entity IDs for locating durable records.

The current local identifiers emitted or preserved by the ANY-437 telemetry
paths are `order_id`, `payment_id`, `subscription_id`, `webhook_event_id`, and
`run_id`. They are local Payment Portal identifiers and must never be metric
labels. `refund_id` remains a local durable business and audit lookup reference
available through existing lifecycle data such as `SubscriptionEvent`; ANY-437
does not add a separate refund diagnostic merely for uniformity.

The representative incident journeys are:

1. Checkout to order: find the request/trace, then the post-commit
   `billing_checkout_committed` diagnostic and its local `order_id`. Follow the
   order to its payment, webhook, and provider-operation records as applicable.
2. Retained provider webhook source to local billing state: when analyzing
   retained legacy records or source, use the durable
   `cloudpayments_webhook_processed` diagnostic, if present. Its
   `webhook_event_id`, and any available `order_id` or `payment_id`, lead to the
   persisted `PaymentWebhookEvent` and existing lifecycle/audit records.
   Persisted status and error code distinguish duplicate, stale, or conflicting
   outcomes without creating separate diagnostic families. The retained route
   is not reachable in normal runtime.
3. Provider timeout or ambiguous outcome: use the provider operation span and
   bounded provider/operation/outcome metrics, then inspect the surrounding
   request trace and local durable state. A timeout or lost response is
   ambiguous, not confirmed failure; reconcile before deciding whether another
   command is safe and never blindly retry a possibly completed command.
4. Scheduled expiry to subscription event: start with the Sentry issue for a
   reportable failure and follow:

   ```text
   Sentry
       -> run_id
       -> subscription-expiry diagnostics
       -> subscription_id
       -> SubscriptionEvent and persisted state
   ```

   Follow `subscription_expiry_run_started` through its `run_id` to each
   `subscription_expiry_transition_committed` and the durable
   `SubscriptionEvent`, then to `subscription_expiry_run_succeeded`. A failed
   run starts with `subscription_expiry_run_started` and ends with
   `subscription_expiry_run_failed` with the run ID, batch size, and exception
   type; it must not emit `subscription_expiry_transition_committed` or
   `subscription_expiry_run_succeeded`. A missing persisted identity is checked
   inside the CLI-owned transaction and reported as
   `subscription_expiry_diagnostic_invariant_violated`; the transaction rolls
   back, no committed/success diagnostic is emitted, and the CLI propagates the
   invariant exception.

5. Password-reset email delivery: the existing background callback intentionally
   absorbs delivery exceptions so the accepted HTTP response remains unchanged.
   It preserves the failed metric and bounded warning, and reports the same
   exception exactly once as the `password_reset_email` operation with the
   `integration_failure` category. The report carries no email address, reset
   URL, token, SMTP data, message content, or other email-specific context.

Scheduled expiry is not an HTTP request and does not reuse request context. Its
`run_id` is generated for that command invocation only. The committed
transition diagnostics are emitted only after the explicit CLI-owned
transaction commits successfully. The lifecycle operation itself is a
transaction participant and does not commit.

## Telemetry backend boundary

The application supports OTLP export when the deployment configures an OTLP
endpoint. The repository's local and agent Compose environments provide the
existing development observability stack where configured. The production
trace/log backend, retention, dashboards, alerts, and operational runbooks are
deployment/environment-owned. The repository has no stable production
trace/log query base-URL contract, so Sentry events intentionally do not invent
direct Grafana, Tempo, or Loki links. Production monitoring and alerting work,
including broad availability and
HetrixTools checks, belongs to ANY-86 and remains outside this contract.

Sentry is a separate optional outbound backend application-error destination.
It does not receive application logs, metrics, tracing, or profiling and does
not replace the OTLP backend, JSON logs, Prometheus/OpenTelemetry metrics, or
persisted state. Operators must enable project-side data scrubbing, disable or
scrub IP collection according to policy, and configure useful notifications
for new or regressed production issues. Those project settings are operator
actions, not runtime automation or general alerting infrastructure in this
repository.

Current HTTP, billing, webhook, and provider metrics retain bounded label sets.
Local business/entity IDs, provider transaction or invoice IDs, email, and
other request or payload values are forbidden as metric labels.

## HTTP failure boundary

Mapped application errors retain their existing public status and structured
error contract. Unmapped `AppError` values and unexpected application failures
return only the generic structured response
`{"detail":{"code":"internal_server_error"}}` with HTTP 500; internal
codes, diagnostics, and provider details are not serialized.

Unexpected application failures are converted by the Presentation middleware
while request-ID context is active. The boundary emits exactly one bounded
application-level failure diagnostic. It may record the request ID through the
existing logging context, HTTP method, matched route template, exception type,
and one application-owned failure location/fingerprint containing only a
repository-relative module/file identifier, function name, and line number.
It never records source text, locals, arguments, exception messages, raw
traceback text, request bodies, response bodies, URLs/query values, headers,
cookies, authorization data, provider payloads, secrets, or
card/token/payment values. The existing request-completion log remains a
separate request lifecycle record. The same outer failure boundary may also
make at most one explicit report through the application-owned Sentry adapter;
framework auto-capture and logging-to-Sentry are disabled so they cannot create
a second issue.

## Recovery

Development environments must be isolated by worktree and safely disposable.
Production migrations are forward-only after the corrected initial baseline is
frozen. Recovery instructions must never suggest treating the return URL as an
authoritative billing fact or as a substitute for verified webhook processing
or reconciliation.
