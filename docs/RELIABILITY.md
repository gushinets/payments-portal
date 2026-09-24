# Reliability Requirements

Status: authoritative operational requirements; target external-billing semantics delegated
Last verified: 2026-09-24

## Target external-billing authority

Target external-billing ownership and behavior are defined, in precedence
order, by
[ADR 0005](architecture/decisions/0005-external-billing-boundary.md), the
accepted [External Billing Boundary Design](superpowers/specs/2026-09-15-external-billing-boundary-design.md),
and the accepted
[Portal <-> Kernel Access Contract Design](superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md).
`ANY-504` controls their implementation sequence. This document records
cross-cutting operational constraints; it does not redefine target commercial
ownership, persistence, or paid-access derivation.

The direct-provider/CloudPayments runtime and Portal-owned commercial/access
lifecycle have been physically removed. The target persistence graph exists,
starts empty, and has no current producer runtime.

## Cross-cutting critical paths

- API liveness must not depend on PostgreSQL; readiness must.
- Billing must use retry-safe orchestration. Persist or find the durable local
  operation or purchase intent and commit it before issuing an external
  command. Issue the command outside a database transaction, then persist the
  reliable result/mapping and apply a verified fact or reconcile through the
  shared local transition path. Use provider idempotency when available, but
  do not assume every external command is idempotent.
- A timeout or lost response is neither confirmed success nor confirmed
  failure. Reconcile before deciding whether another command is safe; never
  blindly duplicate a create after an uncertain outcome.
- Recovery may auto-bind only when correlation finds exactly one unambiguous
  external object. No match remains unknown. Multiple matches are ambiguous
  and fail closed for manual review.
- A valid webhook notification must be authenticated and minimally validated,
  reduced to whitelisted/redacted evidence, and durably persisted before it is
  acknowledged according to integration policy. Processing, retry, and
  reconciliation then belong to Payment Portal. Once receipt is durable,
  correctness must not depend on the external system retrying an
  application-level HTTP failure. Concrete acknowledgement codes/retry policy
  remain integration-specific; durability does not require storing a raw
  request.
- Duplicate, stale, reordered, or conflicting authoritative facts must not
  duplicate or blindly overwrite local projections.
- Valid later lifecycle facts such as refunds, disputes, cancellations and
  expirations must remain able to reduce access when the authoritative-fact and
  derivation rules require it.
- Every integration must recover or reconcile externally authoritative state
  changes whose notifications are completely missed. Correctness must not
  depend solely on webhook delivery.
- Browser return state is informational and never billing authority.
- Webhook receipt, Widget callback, outbound command success, payment state, or
  manual operator input alone never grants paid access.

These are target constraints. Provider integration, webhook processing,
reconciliation workers, paid-access derivation, and invalidation delivery are
not current runtime behavior.

## Transaction, idempotency, and retry contract

Application orchestration owns outer transaction commit and rollback. Focused
query/persistence code owns database mechanics below that boundary: queries,
row locks, atomic DML, flushes, storage-specific exception handling, and
targeted nested savepoints. A SQLAlchemy `Session` autobegin does not make the
first helper the logical owner, and helpers do not finalize the outer
transaction.

Current identity/legal transaction boundaries are documented in
[ARCHITECTURE.md](../ARCHITECTURE.md#current-transaction-map). No current
runtime transaction populates the fifteen target billing tables.

Future database retry decisions use these semantics:

- a transaction known to have rolled back before commit may retry the whole
  logical operation with the same operation identity where supported;
- an operation known to have committed is replayed/read from its persisted
  idempotent result;
- an uncertain local commit requires inspection of authoritative persisted
  state before retry;
- there is no generic automatic database retry loop.

External-command outcomes are distinct:

- **confirmed success** — authoritative evidence proves the intended external
  effect; this alone is not paid-access authority;
- **confirmed failure** — authoritative evidence proves no intended effect and
  supports the explicit failure policy;
- **unknown** — available evidence cannot prove success or failure;
- **ambiguous** — evidence conflicts or identifies multiple plausible objects.

Unknown/ambiguous outcomes require authoritative inspection, reconciliation,
or another explicitly safe policy before another external command.

Logs, traces, metrics and Sentry are diagnostics only. They never serve as the
correctness, idempotency, reconciliation, or replay store.

## Durable target storage semantics

- Complete capability/catalog projection replacement preserves the previous
  last-known-good row on partial or failed sync.
- Mapping revisions, accepted purchase evidence and purchased allowances are
  immutable where the clean migration installs PostgreSQL protections.
  Observation core fields are immutable, while
  `resulting_access_revision` has only a one-time `NULL`-to-value storage
  transition; ANY-504 Step 9 owns positivity and semantic/causal validation.
- Webhook delivery rows contain bounded/redacted correlation and evidence,
  never raw payload, authorization, secret, or card/payment fields.
- Durable work/lease rows are scheduling state, not commercial/access truth.
- Paid-access state storage holds a complete provider-neutral document and a
  non-null revision slot. The clean baseline does not enforce positive or
  monotonic paid-access transitions; ANY-504 Step 9 owns those runtime
  semantics. Invalidation storage physically requires a positive pending
  revision and forbids an acknowledged revision beyond it; later runtime owns
  coalescing and delivery behavior.
- Durable observations and manual-review evidence explain uncertainty/conflict;
  they cannot independently grant access.

The persistence shape does not authorize later runtime behavior. Open work,
processing, classification, and review vocabularies remain open until their
owning `ANY-504` step closes them.

## Framework worker execution

FastAPI/Starlette worker capacity is finite and shared. Synchronous database
and application flows use normal synchronous endpoints. An async boundary may
delegate a complete resource-owning synchronous unit when unavoidable; it must
not move a request-created SQLAlchemy `Session` through a manual thread
bridge. The delegated unit creates, owns, and closes all of its synchronous
resources inside the worker. Cancellation of an async waiter does not imply
that the synchronous worker was forcibly stopped; resource lifetime, retries,
and side effects must account for work that may still finish. Request ID,
trace/span, and structured-log context remain correlated across the framework
worker boundary. Do not add unbounded blocking work, retry loops, or retry
sleeps.

Password-reset email delivery remains its bounded synchronous framework
background task. Billing work tables do not establish a worker runtime; the
durable worker implementation belongs to a later step.

## Agent-verifiable signals

- Every request receives an `X-Request-ID` response header.
- API logs are structured JSON and include request/trace identifiers.
- Metrics expose bounded request and legal/auth outcomes.
- Traces cover HTTP, identity/legal operations and database work.
- Critical browser journeys fail on unexpected console errors, failed
  application requests, or error spans.

## Observability and correlation contract

Sentry is the primary optional entry point for reportable backend application
errors. Metrics provide bounded rates/outcomes/durations. OpenTelemetry traces
show the operation chain. Structured logs provide bounded incident-local
detail. Persisted records remain authoritative business/evidence state.

```text
Sentry
    -> request_id / trace_id
    -> trace and structured-log backend
    -> approved local Payment Portal diagnostic IDs
    -> persisted Payment Portal records
```

Current identity/legal diagnostics may correlate only approved local IDs. Future
billing runtime may add bounded identifiers such as `purchase_intent_id`,
`create_operation_id`, `delivery_id`, `work_item_id`, `subscription_id`,
`observation_id`, or `review_case_id`; they must never be metric labels and
must not expose external/provider identifiers.

Password-reset email delivery intentionally absorbs delivery exceptions so the
accepted HTTP response remains unchanged. It retains the failed metric and
bounded warning and reports the exception once without email address, reset
URL/token, SMTP data, or message content.

## Telemetry backend boundary

The application supports OTLP export when configured. Production trace/log
backends, retention, dashboards, alerts, and operational runbooks are
deployment-owned. Production monitoring and alerting work belongs to
`ANY-86`.

Sentry is a separate optional outbound backend application-error destination.
It does not replace the OTLP backend, JSON logs, Prometheus/OpenTelemetry
metrics, or persisted state. Project-side scrubbing, IP policy and
notifications remain operator-managed.

Local/entity IDs, external transaction/invoice IDs, email, and request/payload
values are forbidden as metric labels.

## HTTP failure boundary

Mapped application errors retain their public status and structured contract.
Unmapped `AppError` values and unexpected failures return only
`{"detail":{"code":"internal_server_error"}}` with HTTP 500.

The outer failure boundary for an operation owns application error reporting.
For HTTP requests, this is the Presentation failure boundary that maps the
failure to its response. A bounded background operation that intentionally
catches and absorbs a failure reports it at that catch boundary. Lower layers
do not report a failure that continues propagating, which prevents duplicate
application logging and Sentry capture. Domain and Application logic do not
import or call `sentry_sdk`; SDK access remains behind the application-owned
`app.infrastructure.sentry` adapter.

The Presentation boundary may record request ID, method, matched route,
exception type, and a repository-owned failure location/fingerprint. It never
records source text, locals, arguments, exception messages, raw traceback,
request/response bodies, URLs/query values, headers, cookies, authorization,
provider payloads, secrets, or card/token/payment values.

## Recovery

Development environments are worktree-isolated and disposable. The Step-4
baseline is a destructive compatibility boundary:

- pre-Step-4 binaries never run against the clean database;
- databases stamped with discarded history are recreated, never upgraded,
  downgraded, stamped, or bridged;
- image-only rollback across the reset is forbidden;
- recovery restores/recreates a matching application and database pair;
- reset, bootstrap, schema-verification, or smoke failure blocks rollout.

The executable local and shared-environment prerequisite sequence is in the
[one-time recreate/bootstrap runbook](architecture/deployment.md#one-time-step-4-recreate-and-bootstrap).
Recovery never treats a browser return as a billing fact or substitutes it for
authoritative reads/reconciliation.
