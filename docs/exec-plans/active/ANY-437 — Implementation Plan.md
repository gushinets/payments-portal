# ANY-437 — Establish Observability & Correlation

## Status

**Plan status:** ready for implementation; revalidated against merged ANY-415, current OpenTelemetry HTTP attribute behavior, and the actual subscription-expiry transaction boundary.

**Research baseline:**
- Linear: `ANY-437`
- Parent: `ANY-407`
- Previous architecture step: `ANY-411`
- Error Architecture source of truth: `ANY-415`
- Repository baseline used for research: `main` after merge of `ANY-415` PR #82 on 2026-09-08
- Repository: `gushinets/payments-portal`

ANY-437 is not a greenfield observability implementation. The repository already has JSON logging, request/trace correlation, Prometheus metrics, optional OTLP export, FastAPI/SQLAlchemy instrumentation, provider-operation telemetry and the bounded unexpected HTTP failure diagnostic introduced by ANY-415. The ticket requires filling only confirmed gaps in current critical payment flows.

---

# 1. Research conclusions

## 1.1 Source-of-truth order

For this ticket:

1. Final accepted ANY-415 behavior is authoritative for Error Architecture.
2. ANY-411 / ADRs define architecture and billing boundaries.
3. Current repository code and tests define actual implemented behavior.
4. ANY-437 narrows the scope of ANY-407 Step 3.
5. ANY-86 owns production monitoring/alerting/runbook work and must not be pulled into this ticket.

### Completed ANY-415 revalidation

ANY-415 PR #82 was merged into `main` on 2026-09-08. The plan has been narrowly revalidated against the resulting current state of the files/contracts ANY-437 depends on:

- `apps/api/app/core/observability.py`;
- `apps/api/app/http_errors.py`;
- `apps/api/app/main.py`;
- directly related observability/error tests.

The revalidation confirmed that:

- the single bounded unexpected HTTP failure diagnostic still exists;
- application/domain error ownership established by ANY-415 has not changed;
- request correlation and observability composition have not materially changed;
- the confirmed ANY-437 gaps and implementation decisions below remain valid.

No additional ANY-415 gate remains before Step 1. If the directly relevant current code later materially contradicts a locked decision in this approved plan, stop and report that contradiction rather than redesigning the step during implementation.

---

# 2. Critical-surface inventory

| Critical surface | Current state | Classification | Action |
|---|---|---|---|
| HTTP request correlation | Validated/generated `request_id`, trace/span IDs, request duration metric and structured completion log already exist | **Mostly sufficient; two concrete gaps** | Fix unmatched-route cardinality and automatic trace query exposure in Step 1 |
| Checkout creation | Existing `billing.checkout_intent.create` trace and checkout outcome metric; durable `Order` created | **Gap** | Add one post-commit diagnostic linking request/trace to local `order_id` |
| Provider API calls | `payment_provider.api.operation` span plus provider/operation/outcome metrics and duration; static safe failure logging | **Already sufficient** | Do not duplicate |
| Provider timeout / ambiguous outcome | Provider client already emits `TIMEOUT`; ADR preserves UNKNOWN/ambiguous semantics | **Already sufficient** | No retry/state behavior changes |
| Billing REST mutation commands | Current billing router is read-only | **Not currently applicable** | Do not invent endpoints or instrumentation |
| Verified CloudPayments webhook receipt | Request trace and webhook metric exist; `PaymentWebhookEvent` is persisted before processing | **Partial gap** | Correlate durable local webhook/business IDs |
| Webhook manual warnings | Raw values are inserted into formatted messages | **Confirmed privacy/consistency gap** | Replace with static safe structured diagnostics |
| Duplicate/stale/conflicting webhook | Existing processing persists status/error information and follows current lifecycle rules | **Semantically sufficient; diagnostic link incomplete** | Covered by the same webhook event diagnostic |
| Payment success/failure | Existing webhook → lifecycle transition path | **Semantics sufficient** | Covered by webhook correlation |
| Refund processing | Existing provider/webhook/lifecycle paths and local audit references | **Semantics sufficient** | No separate observability subsystem |
| Recurring operations | Existing CloudPayments/provider operations use provider client instrumentation | **Already sufficient for current consumers** | No speculative recurring workflow telemetry |
| Subscription transitions | Existing durable `SubscriptionEvent` audit trail contains local correlation references | **Already sufficient as durable business trail** | Do not log inside lifecycle service before caller commit |
| Entitlement activation/revocation | Occurs in the lifecycle transaction with subscription transition | **Already sufficient** | No duplicate entitlement telemetry |
| Reconciliation/transaction lookup | Provider-side operation exists; no independent scheduled reconciliation worker requiring new execution correlation | **Current provider layer sufficient / standalone workflow not applicable** | Do not create scheduler/job telemetry |
| Concurrency conflicts | Existing lifecycle/concurrency behavior and tests | **Already covered semantically** | Preserve behavior; no generic error logging |
| Unexpected HTTP invariant failure | ANY-415 bounded unexpected-failure boundary | **Already sufficient** | Do not add duplicate inner exception reports |
| Scheduled subscription expiry | CLI has no request/trace context and only prints result | **Confirmed gap** | Add per-run `run_id` and safe post-commit diagnostics |

Provider call instrumentation already records `provider`, `operation`, `outcome` and duration around the current provider operation span, including timeout/error classification.  

The current billing HTTP router is read-only, so creating instrumentation for nonexistent cancellation/refund/recurring REST commands would be speculative future work. 

ADR 0004 already defines webhook/reconciliation convergence and explicitly treats a lost/timeout provider response as ambiguous rather than confirmed success/failure. Observability must expose that behavior, not redesign it. 

---

# 3. Correlation model

No new global correlation object or context propagation framework is required.

## Ambient context

Use the existing mechanisms:

- `request_id` — validated HTTP request correlation;
- OpenTelemetry `trace_id`;
- OpenTelemetry `span_id`.

Do not put business entity IDs into the request `ContextVar`.

## Event-/operation-local identifiers

The approved steps introduce or preserve the following local identifiers in telemetry where they solve a concrete incident-reconstruction problem:

- `order_id`
- `payment_id`
- `subscription_id`
- `webhook_event_id`
- `run_id`

The names above mean **local Payment Portal identifiers only**. They must never become metric labels.

`refund_id` remains a safe local **durable business lookup reference** already present in lifecycle/audit data, including `SubscriptionEvent`. ANY-437 does not add a new refund-specific telemetry emission merely for uniformity. If a later current flow has a concrete incident-reconstruction need for `refund_id` in telemetry, that must be justified at that emission site rather than inferred from this plan.

## Explicitly excluded correlation values

Do not use as general telemetry correlation keys:

- email;
- user-provided account identifiers;
- authorization/token/cookie data;
- card/payment credentials;
- raw provider payloads;
- raw request bodies;
- arbitrary headers;
- arbitrary query values;
- provider transaction IDs;
- provider invoice IDs;
- amounts;
- exception text from unknown failures.

`docs/SECURITY.md` already classifies email/IP as personal data and request/external identifiers as untrusted input, and prohibits raw payment/provider/security data from telemetry. 

---

# 4. Signal ownership

### Logs

Use for incident-local detail and high-cardinality but safe local identifiers.

New business/failure diagnostics introduced by this plan must:

- use static message/event names;
- put only explicitly selected diagnostic values into `structured`;
- never use `exc_info` for the new failure events;
- never interpolate untrusted/provider/error values into the message.

The existing HTTP request-completion log is an explicit compatibility exception: preserve `http_request_complete request_id=%s` so the current request-ID text lookup continues to work. Its `request_id` is already validated/bounded; no other dynamic request value may be added to that message.

### Traces

Use existing request/application/provider spans.

Add no generic tracing abstraction.

The only shared trace change required is preventing arbitrary query values from remaining in automatically generated server-span attributes.

### Metrics

Keep current low-cardinality metrics.

No new metric family is justified by the current repository:

- checkout outcomes already exist;
- webhook outcomes already exist;
- provider operation outcomes/duration already exist;
- HTTP method/route/status already exists;
- a short-lived CLI process is not a reliable Prometheus scrape target without introducing separate job metrics infrastructure.

Business IDs must not appear in metric labels.

### Durable business trail

`PaymentWebhookEvent` and `SubscriptionEvent` remain durable business/audit references.

Telemetry helps locate the relevant durable record; telemetry does not become billing authority.

The billing lifecycle already writes `SubscriptionEvent` alongside state transitions and local order/payment/refund/webhook references. The existing `_transactional` wrapper can either own a transaction or join an already-open one, so a generic “committed” log inside the lifecycle service would be incorrect: the service cannot always know whether its return is the outer durability boundary. The scheduled-expiry CLI is a narrower confirmed case: it creates a fresh `SessionLocal`, performs no DB work before calling `expire_due_subscriptions()`, and therefore lets `_transactional` own and commit the business transaction before the function returns.

---

# 5. Telemetry emission-path audit

Research identified the following concrete rules:

1. `JsonFormatter.redact()` protects `structured` JSON output, but dynamic values embedded in the log message bypass that field-level mechanism.
2. OpenTelemetry's Python logging bridge exports the `LogRecord` body/attributes/exception information independently of the JSON formatter, so a value must not be considered safe merely because `JsonFormatter` would redact another output path.
3. New/changed critical events therefore must be safe **at the logging call site**.
4. Current provider logs already follow this model: static messages plus sanitized `details_safe`.
5. Current unexpected HTTP failure logging from ANY-415 is bounded and must stay the single generic HTTP failure report.
6. Automatic HTTP tracing must not retain arbitrary query values.
7. Unmatched paths must not be used verbatim as HTTP metric `route` labels.

This ticket will not introduce a repository-wide custom OpenTelemetry log processor. Such a framework-level sanitizer would be broader than the confirmed payment-flow gaps.

---

# 6. Representative incident reconstruction

## Journey A — Checkout was created, but payment did not progress

Expected investigation path after implementation:

`request_id / trace_id`
→ `billing_checkout_committed`
→ local `order_id`
→ persisted order/payment/webhook records
→ provider-operation spans/metrics if a server API operation happened.

No email or provider transaction ID is needed as the telemetry correlation key.

## Journey B — Provider sent a webhook and processing failed

`request_id / trace_id`
→ `cloudpayments_webhook_processed`
→ local `webhook_event_id`
→ local `order_id` / `payment_id`
→ persisted `PaymentWebhookEvent.status/error_code`
→ existing lifecycle/audit records
→ provider-call spans if reconciliation/provider API access occurred.

The raw webhook payload, provider invoice ID and transaction ID are unnecessary in telemetry.

## Journey C — Provider call timed out

Provider operation span/metric:
`provider + operation + outcome=timeout`
→ current request trace
→ local business ID obtained from the surrounding checkout/webhook diagnostic/persisted state.

Timeout remains ambiguous. Investigation must inspect local/provider state rather than treating timeout as failure and blindly retrying.

## Journey D — Scheduled expiry changed subscriptions

`subscription_expiry_run_started`
→ `run_id`
→ one or more `subscription_expiry_transition_committed`
→ local `subscription_id`
→ durable `SubscriptionEvent`
→ `subscription_expiry_run_succeeded`.

If the run fails:

`subscription_expiry_run_failed`
→ same `run_id`
→ safe `error_type`

with no false “committed” events for rolled-back transitions.

---

# Plan Overview

| Step | Result | Primary files |
|---|---|---|
| 1 | Shared privacy/cardinality boundaries hardened | `core/observability.py`, observability tests |
| 2 | Checkout trace/request can lead to durable local order | identity checkout router/tests |
| 3 | Webhooks emit one safe durable correlation diagnostic | CloudPayments router/Postgres tests |
| 4 | Scheduled expiry has explicit non-HTTP run correlation | expiry CLI/tests |
| 5 | Operational conventions and incident journeys documented; full verification | reliability/security docs |

Steps are sequential.

Do not start a later step until the previous step has been reviewed and its focused checks pass.

---

# Step 1 — Harden shared observability privacy and cardinality boundaries

**Status:** `todo`

**Goal**  
Close the shared observability gaps that affect all later instrumentation: preserve the local `payment_id` that is currently over-redacted by the broad payment-key rule without weakening provider/payment-data protection, prevent raw unmatched paths from becoming metric labels/log route values, and prevent arbitrary query data from remaining in automatic HTTP server spans.

**Scope / affected code**

Primary:

- `apps/api/app/core/observability.py`
- new focused `apps/api/tests/test_observability.py`

Regression-only inspection if necessary:

- `apps/api/app/http_errors.py`
- `apps/api/tests/test_error_handling.py`
- `apps/api/app/main.py`

**Implementation decisions**

1. Use the merged ANY-415 state already revalidated above as the Error Architecture source of truth.
   - Do not repeat repository-wide or ANY-415 research during implementation.
   - Inspect directly relevant current files only as needed to apply this step.
   - If the current code materially contradicts a locked decision below, stop and report the contradiction instead of inventing a new design.

2. Add one narrow exact-key redaction exception only for local `payment_id`.
   - The current broad `"payment"` marker would otherwise redact this local Payment Portal identifier.
   - Check this exact key before the broad payment-value marker.

3. Do not create a special redaction allowlist for `order_id`, `subscription_id`, `refund_id`, `webhook_event_id`, or `run_id` merely for uniformity.
   - The current broad redaction rules do not require exceptions for those keys.
   - They may still be used as local diagnostic fields where a later approved step has a concrete incident-reconstruction consumer.
   - `provider_payment_id`, `transaction_id`, `invoice_id` and other provider/external/payment values remain excluded/redacted.
   - Do not weaken secret/token/card redaction.

4. Replace raw unmatched-path fallback in request telemetry with the stable sentinel:
   - `route="unmatched"`

   The raw `request.url.path` must not become the Prometheus route label or structured route value when FastAPI did not resolve a route template.

5. Keep matched routes represented by their route template.

6. Preserve the existing HTTP completion message format:
   - `http_request_complete request_id=%s`

   Do not remove the validated/bounded `request_id` from the message body in this step. The current repository log-query interface relies on request-ID text lookup in exported logs. Do not add any other dynamic request, path, header, query, or business value to this free-form message.

7. Use FastAPI/OpenTelemetry's existing `server_request_hook` integration to sanitize query-bearing server-span attributes.
   - Do not create custom tracing middleware.
   - Do not add a new tracing library.
   - An injected unique query value must be absent from every query-bearing HTTP server-span attribute actually emitted by the active semantic-convention mode, including `http.target`, `http.url`, `url.full`, and `url.query` when present.
   - Preserve useful path/route identification after sanitization.
   - Do not enable arbitrary request-header capture.

8. Add focused tests proving:
   - local `payment_id` survives `redact()` despite the broad payment marker;
   - other local IDs that do not require a special exception retain their existing safe behavior;
   - provider/external/payment/security values remain redacted;
   - unmatched request paths do not appear as route label values;
   - matched route templates still work;
   - the existing HTTP completion message remains searchable by a validated/bounded `request_id`;
   - an injected unique query secret does not occur in any query-bearing HTTP server-span attribute actually emitted by the active semantic-convention mode (`http.target`, `http.url`, `url.full`, `url.query`, as applicable);
   - the same unique marker is absent from the complete exported HTTP server-span attribute set, so a semantic-convention change cannot silently reintroduce query leakage through another HTTP attribute;
   - path/route identification remains available after query sanitization;
   - an arbitrary header marker is not introduced into spans;
   - no business identifier is added to metric labels.

9. Preserve the ANY-415 unexpected HTTP failure boundary without adding another reporting layer.

**Invariants**

- Existing HTTP response contracts remain unchanged.
- Existing `X-Request-ID` behavior remains unchanged.
- `request_id` remains bounded/validated.
- Existing provider/checkouts/webhook metrics keep their current names and label sets.
- High-cardinality local IDs never become Prometheus/OTel metric labels.
- No raw query/header/payload values are intentionally exported.
- No new generic observability framework is introduced.
- Unexpected HTTP exceptions still produce one bounded diagnostic only.

**Out of scope**

- Sentry.
- Production monitoring backend.
- Global repository-wide OTel log sanitizer.
- SQLAlchemy redesign.
- Disabling existing SQLAlchemy instrumentation.
- Business-flow instrumentation from Steps 2–4.
- Changes to error ownership or HTTP error mapping.

**AI prompt**

Implement only Step 1 of ANY-437: harden the existing shared observability privacy and cardinality boundaries.

ANY-415 PR #82 is already merged, and this plan has already been revalidated against its resulting `main` state. Do not repeat broad ANY-415 or repository research. Inspect the directly relevant current versions of the following files only as needed to implement the locked decisions below:
- `apps/api/app/core/observability.py`
- `apps/api/app/http_errors.py`
- `apps/api/app/main.py`
- `apps/api/tests/test_error_handling.py`

If the directly relevant current code materially contradicts a locked assumption below, stop and describe the contradiction instead of inventing a new solution.

Follow these implementation decisions:

1. Keep the existing observability architecture. Do not introduce a new logging/tracing framework.
2. In `app/core/observability.py`, add one narrow exact-key redaction exception only for local `payment_id`, before the broad payment-related marker such as `payment` is applied.
   Do not create special-case allowlist entries for `order_id`, `subscription_id`, `refund_id`, `webhook_event_id`, or `run_id`; the current broad rules do not require exceptions for those keys.
   Do not allow provider/external identifiers such as `provider_payment_id`, `transaction_id`, or `invoice_id`.
   Do not weaken token, authorization, cookie, card, payload, or other sensitive-data redaction.

3. For HTTP requests that do not resolve to a FastAPI route template, use the exact stable route value `unmatched`. Do not use `request.url.path` as the fallback route value for metrics or structured request-completion diagnostics.
4. Keep resolved route-template behavior unchanged.
5. Preserve the existing HTTP completion log format `http_request_complete request_id=%s`. Do not remove the validated/bounded request ID from the message body because the current repository log-query interface relies on request-ID text lookup. Do not interpolate any additional dynamic request values into that message.
6. Register a small FastAPI/OpenTelemetry `server_request_hook` through the existing `FastAPIInstrumentor.instrument_app(...)` configuration. Use it only to ensure arbitrary query values are removed/redacted from every query-bearing HTTP server-span attribute actually emitted by the active OpenTelemetry semantic conventions. An injected query marker must be absent from `http.target`, `http.url`, `url.full`, and `url.query` whenever those attributes are present. Also assert that the marker is absent from the complete exported HTTP server-span attribute set so the privacy invariant does not depend only on a hard-coded attribute list. Preserve useful path/route identification. Do not add custom tracing middleware and do not enable arbitrary request-header capture.
7. Add a focused `apps/api/tests/test_observability.py` covering:
   - preservation of local `payment_id` despite the broad payment marker;
   - unchanged safe handling of other local IDs without special-case allowlist entries;
   - continued redaction of provider/external/payment/security values;
   - stable `unmatched` handling without leaking a raw unmatched path;
   - preservation of matched route templates;
   - preservation of request-ID text lookup in the existing HTTP completion message;
   - absence of an injected query secret from every query-bearing server-span attribute actually emitted (`http.target`, `http.url`, `url.full`, `url.query`, as applicable);
   - absence of the same injected marker from the complete exported HTTP server-span attribute set;
   - preservation of useful path/route identification after query sanitization;
   - absence of arbitrary request-header values from those attributes;
   - continued low-cardinality HTTP metric labels.
8. Preserve the ANY-415 bounded unexpected-failure behavior; do not add any new generic exception logging.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report the changed files;
- briefly summarize what changed;
- report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

**Manual verification**

```bash
cd apps/api
uv run pytest tests/test_observability.py tests/test_error_handling.py -q
```

**Expected completion**

- unmatched routes cannot create unbounded route-label cardinality;
- matched routes keep canonical templates;
- local `payment_id` is no longer swallowed by the broad payment-key redaction rule, without adding unnecessary exceptions for unrelated local IDs;
- provider/external/sensitive identifiers remain protected;
- existing request-ID text lookup remains compatible;
- arbitrary query/header markers are absent from all applicable HTTP span attributes while useful path/route identification remains available;
- ANY-415 unexpected-error behavior remains unchanged.

**Proposed commit**

`fix(api): harden observability privacy boundaries`

---

# Step 2 — Correlate committed checkout with the local order

**Status:** `todo`

**Goal**  
Allow an engineer starting from an HTTP request/trace to identify the durable local order created by a successful checkout without adding PII, provider identifiers, new metrics, or a global business correlation context.

**Scope / affected code**

Primary:

- `apps/api/app/domains/identity/router.py`
- checkout-related tests in `apps/api/tests/test_api.py`

**Implementation decisions**

1. Reuse the existing checkout trace:
   - `billing.checkout_intent.create`

2. Reuse the existing checkout outcome metric.

3. Do not create a new checkout span or metric.

4. After the transaction creating the checkout/order has successfully committed, emit exactly one structured info diagnostic:
   - message/event: `billing_checkout_committed`
   - structured field:
     - `order_id`: local `Order.id` serialized to string

5. Do not emit this success event before `db.commit()` succeeds.

6. Rely on existing ambient request/trace context:
   - do not manually copy `request_id`;
   - do not manually copy `trace_id`;
   - do not create an `order_id` ContextVar.

7. Do not include:
   - email;
   - user ID;
   - plan/product data unless later proven necessary;
   - amount;
   - currency;
   - provider;
   - provider transaction/invoice IDs;
   - token/checkout payload.

8. Add focused tests proving:
   - a successful committed checkout emits the event with the local `order_id`;
   - sensitive checkout/user values are absent;
   - no committed event is emitted if commit fails.

**Invariants**

- Checkout API request/response contract is unchanged.
- Order creation semantics are unchanged.
- Existing checkout metric semantics remain unchanged.
- Commit remains the durability boundary.
- No provider-specific dependency is introduced.
- No additional exception reporting is introduced.

**Out of scope**

- Checkout business logic changes.
- Checkout schema changes.
- New checkout metric families.
- New Pydantic contracts.
- Provider checkout integration redesign.
- Frontend changes.
- Webhook instrumentation.

**AI prompt**

Implement only Step 2 of ANY-437: correlate a successfully committed checkout with its local Payment Portal order.

The shared observability/privacy changes from Step 1 are already implemented and are the source of truth.

Work only in the directly relevant checkout endpoint and its existing tests.

Follow these decisions:

1. Reuse the existing `billing.checkout_intent.create` trace and existing checkout outcome metric. Do not add another checkout span or metric.
2. In the current checkout creation flow in `apps/api/app/domains/identity/router.py`, emit exactly one info-level structured diagnostic only after the database commit that makes the checkout/order durable has succeeded.
3. Use the exact static log message/event name:
   `billing_checkout_committed`
4. Include only:
   - `order_id`: the local Payment Portal `Order.id`, serialized safely as a string.
5. Do not manually add `request_id` or `trace_id`; rely on the existing ambient request/trace logging context.
6. Do not create a global/order-specific ContextVar.
7. Do not include email, user IDs, amount, currency, plan/product data, provider transaction/invoice IDs, tokens, request payloads, or other customer/provider data.
8. Add focused checkout tests in the existing checkout test area of `apps/api/tests/test_api.py` proving:
   - the event is emitted after a successful checkout commit with the local order ID;
   - sensitive values are absent;
   - a failed commit does not emit `billing_checkout_committed`.
9. Preserve all existing checkout HTTP, persistence, idempotency, and error behavior.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report the changed files;
- briefly summarize what changed;
- report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

**Manual verification**

```bash
cd apps/api
uv run pytest tests/test_api.py -q -k "checkout"
```

**Expected completion**

Given a checkout incident, the request/trace diagnostic chain can lead to the durable local `order_id`, and no false committed event is emitted when the transaction fails.

**Proposed commit**

`feat(api): correlate committed checkouts`

---

# Step 3 — Normalize CloudPayments webhook diagnostics around durable local identifiers

**Status:** `todo`

**Goal**  
Replace unsafe/inconsistent manually formatted CloudPayments webhook warnings with one bounded structured diagnostic that links a request/trace to the durable local webhook/business records.

**Scope / affected code**

Primary:

- `apps/api/app/integrations/cloudpayments/router.py`
- `apps/api/tests/test_cloudpayments_webhook_postgres.py`

Direct inspection only if necessary:

- `apps/api/app/integrations/cloudpayments/processing.py`
- `apps/api/app/integrations/cloudpayments/processing_support.py`
- `PaymentWebhookEvent` model

**Implementation decisions**

1. Preserve the current webhook transaction flow:
   - normalized/authenticated input;
   - durable `PaymentWebhookEvent`;
   - existing processing;
   - existing success/failure commits;
   - existing HTTP response behavior.

2. Preserve the current:
   - `cloudpayments.webhook.process` trace;
   - `record_webhook(...)` metrics;
   - duplicate/stale/conflict semantics;
   - payment/refund/recurring/lifecycle semantics.

3. Remove the existing warnings that interpolate:
   - `transaction_id`;
   - `invoice_id`;
   - error text;
   - other provider values into the free-form log message.

4. Add one small webhook-local logging helper in `router.py`.
   - Do not make it a generic cross-application logging abstraction.

5. Use one static event name:
   - `cloudpayments_webhook_processed`

6. Emit it only when the corresponding `PaymentWebhookEvent` state has been durably persisted.

7. Structured fields may contain only:
   - `endpoint`;
   - `status`;
   - `error_code`, when present;
   - `webhook_event_id`;
   - `order_id`, when present;
   - `payment_id`, when present.

8. Serialize local IDs as strings.

9. Log level:
   - `warning` for persisted `FAILED`;
   - `info` for other persisted outcomes.

10. Never emit:
    - `transaction_id`;
    - provider invoice ID;
    - `error_message`;
    - raw exception text;
    - raw body/payload;
    - webhook signature/header values;
    - account/email;
    - amount/currency.

11. For unexpected processing exceptions:
    - keep existing rollback/failure-persistence behavior;
    - call the diagnostic only after `fail_webhook_event(...)` has durably stored the failed event;
    - do not use `logger.exception`;
    - do not use `exc_info`;
    - do not log `str(exc)`;
    - preserve the existing HTTP 500 behavior.

12. Do not introduce separate telemetry families for duplicate/stale/conflicting webhooks.
    - Existing persisted `status` / `error_code`, together with this diagnostic and existing metrics, provide the required distinction.

13. Add focused PostgreSQL tests for at least:
    - successfully processed webhook;
    - normalization/validation failure that is persisted;
    - unexpected processing failure;
    - existing duplicate/stale/conflict case if one of the current fixtures already exposes it cleanly.

14. Tests must verify that provider/error secret markers do not appear in the emitted diagnostic.

The current router persists/refetches the webhook event before downstream processing, and the failure helper persists the final `FAILED` state. This gives a real durable correlation anchor without changing persistence design.  

**Invariants**

- Webhook signature/authenticity behavior unchanged.
- Current provider ACK/error HTTP semantics unchanged.
- Existing webhook metric semantics unchanged.
- Idempotency, duplicate/stale/conflict handling unchanged.
- Payment/refund/subscription semantics unchanged.
- Failed events remain durably recorded according to current behavior.
- No duplicate generic unexpected HTTP report is introduced.
- Provider-specific logic remains inside the CloudPayments integration.

**Out of scope**

- Provider-neutral webhook redesign.
- Persistence extraction.
- Webhook schema changes.
- Reconciliation redesign.
- New metrics.
- Retry changes.
- CloudPayments business-rule changes.
- LBX/Dodo telemetry.

**AI prompt**

Implement only Step 3 of ANY-437: normalize CloudPayments webhook diagnostics around durable local Payment Portal identifiers.

Steps 1 and 2 are already implemented. Follow their observability/privacy conventions.

Work primarily in:
- `apps/api/app/integrations/cloudpayments/router.py`
- `apps/api/tests/test_cloudpayments_webhook_postgres.py`

Inspect `processing.py`, `processing_support.py`, and the existing webhook model only as needed to verify transaction/durability assumptions. Do not redesign those components.

Follow these decisions:

1. Preserve the current webhook authentication, normalization, persistence, processing, duplicate/stale/conflict, payment/refund/recurring, commit/rollback, metric, tracing, and HTTP response behavior.
2. Keep the existing `cloudpayments.webhook.process` trace and `record_webhook(...)` metrics.
3. Remove the current free-form warning messages that interpolate provider transaction IDs, invoice IDs, error text, or other dynamic provider values.
4. Add one small private webhook-local logging helper in `router.py`; do not introduce a generic logging abstraction.
5. Use exactly one static diagnostic event name:
   `cloudpayments_webhook_processed`
6. Emit the diagnostic only after the relevant `PaymentWebhookEvent` state has been durably persisted.
7. The structured fields are limited to:
   - `endpoint`
   - `status`
   - `error_code` when present
   - `webhook_event_id`
   - `order_id` when present
   - `payment_id` when present
   Local IDs must be serialized as strings.
8. Use warning level when the persisted webhook status is FAILED and info level otherwise.
9. Never emit provider `transaction_id`, provider invoice IDs, persisted `error_message`, raw exception text, raw body/payload, signatures, arbitrary headers, account/email, amount, or currency.
10. In the unexpected-processing-exception path, preserve the existing rollback and `fail_webhook_event(...)` semantics. Emit the diagnostic only after that helper has durably persisted/refreshed the FAILED event. Do not use `logger.exception`, `exc_info`, or `str(exc)`.
11. Do not add separate metrics/log families for duplicate, stale, or conflicting webhook outcomes. Reuse the persisted status/error code plus the existing webhook metric.
12. Extend the existing PostgreSQL webhook tests to cover safe diagnostics for success, persisted normalization failure, and unexpected processing failure. Reuse an existing duplicate/stale/conflict fixture only if it is already directly available; do not refactor test infrastructure merely for uniformity.
13. Tests must prove that injected provider IDs, invoice IDs, payload markers, and raw exception text do not appear in the diagnostic output.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report the changed files;
- briefly summarize what changed;
- report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

**Manual verification**

From repository root:

```bash
make test_db_up
(cd apps/api && uv run pytest tests/test_cloudpayments_webhook_postgres.py -q)
make test_db_stop
```

**Expected completion**

Every current durable webhook outcome has a bounded searchable diagnostic tied to local IDs, while provider payload/transaction/error details no longer leak through manually formatted log messages.

**Proposed commit**

`feat(api): add safe webhook correlation diagnostics`

---

# Step 4 — Add explicit correlation for scheduled subscription expiry

**Status:** `todo`

**Goal**  
Give the current non-HTTP subscription-expiry command its own bounded execution correlation without pretending it has an HTTP request, introducing a job framework, changing lifecycle transaction ownership, or emitting a committed transition diagnostic before the real durability boundary has completed.

**Scope / affected code**

Primary:

- `apps/api/app/commands/expire_subscriptions.py`
- `apps/api/tests/test_expire_subscriptions_cli.py`

Direct lifecycle inspection only if needed to preserve the locked durability assumption:

- `apps/api/app/domains/billing/service/lifecycle_operations.py`
- `apps/api/app/domains/billing/service/support.py`
- existing expiry return contract and focused lifecycle tests

**Confirmed current transaction model**

`expire_due_subscriptions()` is wrapped by the existing `_transactional` helper. `_transactional` owns and commits a transaction when the supplied `Session` has no transaction already open, and otherwise joins the caller's existing transaction.

The current CLI creates a fresh `SessionLocal`, performs no DB operation before calling `expire_due_subscriptions()`, and therefore enters the lifecycle call without an already-open transaction. For this exact CLI path:

```text
fresh SessionLocal
    -> expire_due_subscriptions()
    -> _transactional opens transaction
    -> expiry state + SubscriptionEvent writes
    -> _transactional commits
    -> expire_due_subscriptions() returns
```

Therefore, **successful return from `expire_due_subscriptions()` is the confirmed business durability boundary for the current CLI path**. The existing explicit `db.commit()` after that return is redundant and must not be treated as the commit proving expiry durability.

If implementation discovers that the CLI now performs DB work before the lifecycle call, explicitly opens a transaction, or otherwise enters `expire_due_subscriptions()` with `db.in_transaction() == True`, stop and report the contradiction instead of applying this step unchanged.

**Implementation decisions**

1. Keep the current CLI and lifecycle transaction architecture.
   - Do not introduce a scheduler/job abstraction.
   - Do not move transaction ownership out of `_transactional`.
   - Do not wrap the lifecycle call in a new outer `db.begin()`/`db.commit()` boundary.
   - Do not create a task table or persistence record.
   - Do not reuse `request_id_context`.

2. Remove the current redundant explicit `db.commit()` that runs after `expire_due_subscriptions()` returns.
   - Its removal does not move the business transaction boundary: the current fresh-session path is already committed by `_transactional` before return.
   - Do not otherwise refactor lifecycle transaction handling.

3. Configure the existing JSON logging for this CLI using the existing `configure_logging()` entry point.

4. Generate one `run_id` per command invocation using a locally generated random UUID value.
   - Keep it as an ordinary local variable.
   - It is diagnostic metadata, not persisted billing authority.

5. Emit before the lifecycle call:
   - `subscription_expiry_run_started`
   - fields: `run_id`, `batch_size`

6. After `expire_due_subscriptions()` returns successfully, emit one static info event for each returned expired subscription:
   - `subscription_expiry_transition_committed`
   - fields: `run_id`, `subscription_id`

   For this locked fresh-session CLI path, successful lifecycle return means the expiry state and corresponding durable `SubscriptionEvent` writes have already committed.

7. After the committed transition events, emit:
   - `subscription_expiry_run_succeeded`
   - fields: `run_id`, `batch_size`, `expired_count`

8. If `expire_due_subscriptions()` raises:
   - emit exactly one `subscription_expiry_run_failed`;
   - fields: `run_id`, `batch_size`, `error_type`;
   - then preserve the current exception behavior.

9. Failure diagnostic must:
   - use a static message;
   - not use `logger.exception`;
   - not use `exc_info`;
   - not include raw exception text.

10. Never emit `subscription_expiry_transition_committed` or `subscription_expiry_run_succeeded` before `expire_due_subscriptions()` has returned successfully.

11. Preserve exact existing successful CLI stdout:
   - `expired_subscriptions=<N>`

12. Preserve existing return-code and exception behavior.

13. Do not add Prometheus metrics for this short-lived CLI.
   - Proper scrape/push semantics would require additional job-monitoring infrastructure outside ANY-437.

14. Do not add standalone OTLP tracing bootstrap to the command.
   - For the currently synchronous CLI, `run_id` + structured logs + durable `SubscriptionEvent` is the intended correlation strategy.
   - General job tracing belongs to later execution architecture if/when such a runner exists.

15. Focused tests must prove:
   - one stable `run_id` is shared across a successful run's events;
   - committed transition events contain local subscription IDs;
   - no explicit outer `db.commit()` is required or treated as the durability boundary after the lifecycle function returns;
   - transition/success diagnostics are emitted only after `expire_due_subscriptions()` returns successfully;
   - if the lifecycle function raises, exactly one bounded failure event is emitted and no committed/succeeded event is emitted;
   - injected exception text is absent;
   - successful stdout remains unchanged.

Do not redesign `_transactional` or add an artificial commit hook solely to make the CLI test observe the internal transaction. Existing lifecycle tests remain responsible for the lifecycle transaction/durable `SubscriptionEvent` behavior; the CLI tests should verify the CLI-specific ordering and correlation contract around the successful/failed lifecycle call.

**Invariants**

- Expiry selection/business rules unchanged.
- Existing lifecycle `_transactional` ownership semantics unchanged.
- For the current fresh-session CLI path, successful `expire_due_subscriptions()` return remains the durability boundary.
- No DB work is added before the lifecycle call that would implicitly open a transaction.
- `SubscriptionEvent` behavior unchanged.
- CLI successful stdout unchanged.
- CLI return/exception behavior unchanged.
- No new persistence.
- No request-context misuse.
- No false committed diagnostic is emitted for work that did not durably complete.

**Out of scope**

- Cron/scheduler redesign.
- Queue/worker architecture.
- ANY-407 Step 4 sync/async work.
- Pushgateway/job metrics.
- Persistent job execution model.
- New lifecycle repository/service abstractions.
- Per-transition tracing infrastructure.
- General transaction-boundary redesign.

**AI prompt**

Implement only Step 4 of ANY-437: add explicit non-HTTP correlation to the existing subscription-expiry CLI.

Steps 1 through 3 are already implemented.

Work primarily in:
- `apps/api/app/commands/expire_subscriptions.py`
- `apps/api/tests/test_expire_subscriptions_cli.py`

Inspect only these lifecycle files if needed to verify the locked transaction/return assumptions:
- `apps/api/app/domains/billing/service/lifecycle_operations.py`
- `apps/api/app/domains/billing/service/support.py`

The approved transaction model for this step is already established: with the current fresh `SessionLocal` and no preceding DB work, `expire_due_subscriptions()` enters with no open transaction; its existing `_transactional` wrapper owns and commits the business transaction before the function returns. The current explicit `db.commit()` after the call is redundant and is not the expiry durability boundary.

If the current CLI has changed so that a transaction is already open before `expire_due_subscriptions()` is called, stop and report that contradiction instead of changing the transaction design.

Follow these decisions:

1. Keep the existing lifecycle transaction architecture. Do not move transaction ownership out of `_transactional`, do not add a new outer transaction, and do not redesign the lifecycle service.
2. Remove the redundant explicit `db.commit()` that currently runs after `expire_due_subscriptions()` returns. Do not otherwise change transaction semantics.
3. Use the existing `configure_logging()` function for CLI logging. Do not initialize a new observability framework.
4. Generate one random UUID-based `run_id` per CLI invocation and keep it as a local variable. Do not put it into `request_id_context` and do not add a new global ContextVar.
5. Emit the static info event `subscription_expiry_run_started` before the lifecycle call with:
   - `run_id`
   - `batch_size`
6. Only after `expire_due_subscriptions()` returns successfully, emit one static info event `subscription_expiry_transition_committed` per returned expired subscription with:
   - `run_id`
   - `subscription_id`
   Successful return is the confirmed durability boundary for this exact fresh-session CLI path.
7. After those committed transition events, emit `subscription_expiry_run_succeeded` with:
   - `run_id`
   - `batch_size`
   - `expired_count`
8. If `expire_due_subscriptions()` raises, emit exactly one bounded `subscription_expiry_run_failed` diagnostic with:
   - `run_id`
   - `batch_size`
   - `error_type`
   Do not use `logger.exception`, `exc_info`, or the raw exception message. Preserve the existing exception behavior after logging.
9. Do not emit any committed/succeeded event before the lifecycle call returns successfully.
10. Preserve the exact successful stdout contract `expired_subscriptions=<N>` and existing return/exception behavior.
11. Do not add Prometheus metrics, persistent job records, a scheduler abstraction, a queue, standalone OTLP tracing bootstrap, or a new transaction abstraction.
12. Extend the focused CLI tests to prove stable run correlation, post-lifecycle-return event ordering, bounded failure output, absence of raw exception text, no committed/succeeded event on lifecycle failure, removal of the redundant outer commit, and unchanged successful stdout.

Do not redesign `_transactional` or create an artificial internal commit hook just for testing. Existing lifecycle tests remain the source of truth for the lifecycle transaction and durable `SubscriptionEvent` behavior.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report the changed files;
- briefly summarize what changed;
- report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

**Manual verification**

```bash
cd apps/api
uv run pytest tests/test_expire_subscriptions_cli.py -q
uv run pytest tests/test_billing_lifecycle.py -q
```

If PostgreSQL cases in the then-current focused tests require the test database:

```bash
make test_db_up
(cd apps/api && uv run pytest tests/test_expire_subscriptions_cli.py tests/test_billing_lifecycle.py -q)
make test_db_stop
```

**Expected completion**

A non-HTTP expiry incident can be followed from one `run_id` to the exact local subscriptions and durable `SubscriptionEvent` records. The CLI emits committed transition diagnostics only after the existing lifecycle-owned transaction has durably completed, without adding job infrastructure or changing transaction architecture.

**Proposed commit**

`feat(api): correlate subscription expiry runs`

---

# Step 5 — Document the operational contract and complete acceptance verification

**Status:** `todo`

**Goal**  
Document the resulting observability/correlation model as an operationally usable contract and verify the completed ANY-437 implementation as one coherent change set.

**Scope / affected code**

Primary documentation:

- `docs/RELIABILITY.md`
- `docs/SECURITY.md`

Existing documentation tests only if the established repository pattern requires an assertion:

- `apps/api/tests/test_repository_docs.py`

No runtime behavior should be introduced in this step.

**Implementation decisions**

Update `docs/RELIABILITY.md` with:

### Signal responsibilities

- metrics = low-cardinality rates/outcomes/durations;
- traces = operation chain;
- structured logs = bounded incident details and local diagnostic IDs;
- database events/state = durable billing truth.

### Correlation strategy

HTTP:

`request_id / trace_id`
→ local business diagnostic
→ `order_id/payment_id/webhook_event_id/...`
→ persisted records.

Non-HTTP expiry:

`run_id`
→ committed `subscription_id`
→ persisted `SubscriptionEvent`.

### Current useful local IDs

Document the implemented distinction explicitly:

- telemetry-emitted/preserved local IDs in ANY-437: `order_id`, `payment_id`, `subscription_id`, `webhook_event_id`, `run_id`;
- durable local lookup reference not newly emitted by ANY-437: `refund_id` through existing lifecycle/audit data such as `SubscriptionEvent`.

None of these local business/entity IDs may become metric labels.

### Incident journeys

Document at least:

1. checkout → order;
2. webhook → local webhook/payment/order;
3. provider timeout / UNKNOWN investigation;
4. scheduled expiry → subscription event.

### OTLP/backend boundary

Document the real repository state:

- application can export OTLP when configured;
- the local/agent compose environment provides the existing local observability stack;
- the production observability backend is deployment/environment-owned;
- building production alerting, dashboards, HetrixTools checks and production runbooks is outside ANY-437 and belongs to ANY-86;
- Sentry remains separate follow-up scope.

### Metrics cardinality

Document that current metric labels remain bounded and business/entity IDs are forbidden.

Update `docs/SECURITY.md` with:

- exact distinction between local IDs emitted in telemetry, durable local lookup references such as `refund_id`, and provider/external/user values;
- source-level telemetry rule:
  redaction is defense-in-depth and is not permission to put secrets/PII/provider payload/error text into message bodies or arbitrary logging extras;
- static messages for critical failure diagnostics;
- no raw exception text/`exc_info` for the new bounded business diagnostics.

Do not document speculative future job/provider designs.

The repository already exposes canonical root verification commands including `check:fast`, `test:api:fast`, `test:api:postgres`, `test:api` and `check`. 

**Invariants**

- Documentation matches implemented behavior.
- No new architecture commitment for future billing systems.
- No production monitoring implementation is added.
- No Sentry-specific design is added.
- Durable billing state remains authoritative.
- Timeout ambiguity remains documented correctly.

**Out of scope**

- Deployment of Grafana/Loki/Tempo/Prometheus in production.
- Alert definitions.
- SLO/SLI design beyond current metrics.
- HetrixTools.
- Incident on-call processes.
- Sentry.
- New infrastructure/config solely to make the docs true.
- Future LBX/Dodo monitoring.

**AI prompt**

Implement only Step 5 of ANY-437: document the final observability/correlation contract after Steps 1 through 4.

Do not make new runtime architecture decisions in this step.

Update primarily:
- `docs/RELIABILITY.md`
- `docs/SECURITY.md`

Modify `apps/api/tests/test_repository_docs.py` only if the repository's existing documentation-test pattern requires a focused assertion for the new normative contract.

Document the following implemented facts:

1. Metrics are for low-cardinality outcomes/rates/durations; traces are for operation flow; structured logs provide bounded incident-local diagnostic fields; persisted billing records/events remain authoritative.
2. HTTP incident correlation is:
   request/trace context -> safe local diagnostic ID -> durable Payment Portal record.
3. Scheduled subscription expiry uses its own local `run_id`; it does not reuse HTTP request context.
4. The local identifiers actually emitted/preserved by the approved ANY-437 telemetry paths are:
   - order_id
   - payment_id
   - subscription_id
   - webhook_event_id
   - run_id
   These are local Payment Portal identifiers and must never become metric labels.
   `refund_id` remains a local durable business/audit lookup reference already available through lifecycle data such as `SubscriptionEvent`; ANY-437 does not add a refund-specific telemetry emission merely for uniformity.
5. Provider transaction IDs, invoice IDs, email, auth/token/card data, arbitrary headers/query values, raw payloads, amounts, and raw unexpected exception text are not telemetry correlation keys.
6. Redaction is defense in depth; critical telemetry must be safe at the emission site and must not rely on a downstream formatter to make an unsafe free-form message safe.
7. Document representative operational journeys for:
   - checkout -> local order;
   - webhook -> local webhook/order/payment;
   - provider timeout/ambiguous outcome;
   - scheduled expiry -> subscription -> durable SubscriptionEvent.
8. Preserve the established rule that provider timeout/lost response is ambiguous and must not be treated as confirmed failure or blindly retried.
9. Document the existing OTLP boundary accurately:
   - the application supports configured OTLP export;
   - the repository's local/agent environment provides the existing development observability stack where applicable;
   - production monitoring/backend/alerting/runbook work is separate and owned by ANY-86;
   - Sentry is outside ANY-437.
10. Do not invent future LBX/Dodo/job-system telemetry or deployment architecture.

Implement only this step.
Follow the decisions defined in this prompt.
Do not perform broad repository research.
Inspect only the directly relevant current files if needed to verify the plan assumptions.
Do not redesign the architecture.
Do not perform unrelated refactoring.
Do not work on future steps.
Do not run tests, linters, formatters, or other automated verification commands.
Do not stage files.
Do not create commits.

After implementation:
- report the changed files;
- briefly summarize what changed;
- report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

**Manual verification**

Focused documentation check:

```bash
cd apps/api
uv run pytest tests/test_repository_docs.py -q
```

Final ANY-437 verification from repository root:

```bash
npm run check:fast
npm run test:api:fast
make test_db_up
npm run test:api:postgres
npm run test:api
npm run check
make test_db_stop
```

`test_db_up` / `test_db_stop` are the repository's existing wrappers around the test PostgreSQL environment. 

**Expected completion**

- authoritative docs describe the actual observability/correlation contract;
- incident reconstruction is possible using the identifiers that the system actually emits;
- production monitoring and future architectural work remain explicitly outside ANY-437;
- focused and repository-level quality gates pass.

**Proposed commit**

`docs: define payment observability correlation contract`

---

# 7. Explicitly not implemented by this plan

The following are intentionally excluded despite being observability-related:

- new Prometheus metric families;
- `order_id`, `payment_id`, etc. as metric labels;
- a universal business-correlation `ContextVar`;
- generic logging facade;
- repository-wide OpenTelemetry log processor;
- Sentry;
- production dashboards/alerts;
- HetrixTools;
- new reconciliation scheduler;
- async job architecture;
- persistent job execution records;
- payment persistence redesign;
- repository/service extraction;
- transaction-boundary redesign;
- new LBX/Dodo-specific signals;
- additional payment/refund/recurring HTTP endpoints.

---

# 8. Potential follow-up outside ANY-437

## Repository-wide OTLP log sanitation

OpenTelemetry's logging handler can consume the Python `LogRecord` message, extra attributes and exception information independently of the JSON formatter. ANY-437 makes the identified **critical payment flow emissions** safe at their source instead of adding another generic framework.

If the project later needs a framework-level guarantee covering every application and third-party logger, that should be evaluated separately as a repository-wide telemetry-hardening concern rather than silently added to this ticket.

This is not required for ANY-437 completion once all approved critical-flow emission paths are source-safe and protected by tests.

---

# 9. Acceptance-criteria coverage

| ANY-437 requirement | Covered by |
|---|---|
| Research current observability substrate | Research section |
| Classify all critical Step-3 surfaces | Critical-surface inventory |
| Distinguish ambient vs event-local correlation | Correlation model |
| Audit structured/free-form/exception/auto instrumentation/metrics | Emission-path audit + Step 1 |
| Preserve one unexpected HTTP error boundary | Step 1 invariant |
| Safe HTTP request correlation | Existing substrate + Step 1 |
| Checkout incident reconstruction | Step 2 |
| Provider timeout/outcome observability | Existing provider instrumentation |
| Verified webhook correlation | Step 3 |
| Duplicate/stale/conflict diagnostics | Existing persisted status + Step 3 |
| Payment/refund/recurring flow correlation | Existing lifecycle/provider instrumentation + Step 3 |
| Subscription/entitlement transition visibility | Existing durable `SubscriptionEvent` |
| Non-HTTP scheduled correlation | Step 4 |
| No high-cardinality metric labels | Steps 1–5 |
| Privacy/redaction tests | Steps 1–4 |
| OTLP/backend boundary documented | Step 5 |
| Representative incident journeys | Research + Step 5 |
| No speculative future work | Explicit out-of-scope sections |
| Full repository verification | Step 5 |

---

# 10. Final plan validation

The plan closes the confirmed gaps without changing:

- billing authority;
- public API;
- persisted schema;
- retry/idempotency semantics;
- provider timeout/UNKNOWN semantics;
- subscription state-machine rules;
- webhook transaction semantics;
- entitlement rules;
- Error Architecture established by ANY-415.

It also deliberately avoids moving later ANY-407 work into ANY-437.

The most important implementation boundary is **durability**:

> A diagnostic claiming that a checkout, webhook state, or subscription expiry transition was committed must be emitted only after the transaction responsible for that state has successfully committed. For the current subscription-expiry CLI specifically, the locked fresh-session path means the existing lifecycle `_transactional` wrapper commits before `expire_due_subscriptions()` returns, so successful lifecycle return — not the redundant outer `db.commit()` — is the durability boundary.

This prevents observability from reporting a business state that was later rolled back while preserving the existing transaction architecture.

No unresolved business, API, persistence, security, ownership, transaction-boundary, or architectural decision remains in the plan. The ANY-415 dependency has been satisfied by merge of PR #82; the OpenTelemetry query-attribute privacy boundary and scheduled-expiry durability semantics have been revalidated against the current repository; the plan is ready for sequential implementation.