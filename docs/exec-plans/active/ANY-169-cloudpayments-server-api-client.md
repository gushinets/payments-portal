# ANY-169 — CloudPayments Server API Client

Status: active

## Objective

Implement the smallest CloudPayments server API surface required by the RU
CloudPayments MVP and the recurring-payment lifecycle, behind the provider
boundary.

The implementation must provide safe authentication, bounded transport
behavior, idempotency, response validation, redacted observability,
transaction reconciliation, refunds, and recurring subscription primitives.
Domain services must receive normalized provider results rather than raw
CloudPayments payloads.

## Scope

- CloudPayments-specific server API client and configuration.
- HTTP Basic Auth using the configured Public ID and API Secret.
- Bounded connect/read/write/pool timeouts.
- Safe retry classification and stable `X-Request-ID` idempotency keys.
- Response decoding and validation into CloudPayments-specific DTOs.
- Transaction lookup by `TransactionId` and reconciliation fallback by
  `InvoiceId`.
- Refund operations required by the current payment/refund model.
- Create, update, and cancel recurring subscriptions.
- Provider-neutral normalized results at the adapter boundary.
- Mocked contract tests and an opt-in sandbox verification path.
- Provider-operation metrics, tracing, and sanitized failure logging.

## Non-goals

- A universal provider API client with shared provider request/response models.
- Subscription or entitlement business logic.
- Automatic entitlement activation inside the client or adapter.
- Webhook orchestration or broad webhook characterization work.
- Card-data collection, storage, or logging.
- Support for additional production contours or providers.
- CloudPayments API methods not required by this MVP.

## Authority and constraints

- CloudPayments API documentation at `developers.cloudpayments.ru` is the
  source of truth for endpoint and field names.
- The production product surface remains the `ru` contour.
- Provider-specific code belongs under
  `apps/api/app/integrations/cloudpayments/`.
- Provider-neutral contracts belong under
  `apps/api/app/payment_providers/`.
- Secrets and authorization data must never appear in logs, traces, database
  rows, or test output.
- Paid access must not be activated by this client or by a browser return URL.
- `lookup_transaction` remains an adapter orchestration method. It may stay
  relatively thick because it owns account checks, provider lookup,
  reconciliation, and safe result mapping.

## Decisions

1. The generic payment client layer is transport-only. CloudPayments endpoint
   paths, DTOs, and success semantics remain in the CloudPayments client.
2. `payments/get` is used for exact lookup by `TransactionId`.
   `v2/payments/find` is used when only an `InvoiceId` is available.
3. Reconciliation never treats caller-provided identifiers or amounts as
   provider-confirmed values. Missing or mismatching provider facts produce a
   safe non-success result.
4. Mutating operations may be retried only when a stable idempotency key is
   present. The key must represent the logical operation, not an HTTP attempt.
5. `PaymentProviderAccount` must not store provider secrets. If credentials
   remain instance-level, the adapter must explicitly enforce that the
   selected account and terminal match the configured server credential.
6. CloudPayments subscription update exposes only documented fields. Email is
   not part of the update contract.
7. Cancel returns an optimistic normalized `CANCELED` result after a successful
   provider response; no read-after-write is required by this task.

## Current progress

### Step 1 — Define the provider-neutral server API contract

Status: completed

Implemented in the current branch:

- Transaction lookup request/result types.
- Refund request/result types.
- Recurring create/update/cancel request/result types.
- Normalized statuses, outcome, retry disposition, and safe failure details.
- Provider adapter protocol methods.

Completion condition:

- Raw CloudPayments payloads do not cross the adapter boundary.

### Step 2 — Define the CloudPayments client boundary and configuration

Status: completed

Implemented in the current branch:

- CloudPayments-specific client module and DTOs.
- Settings for base URL, credentials, timeout components, retry count, and
  backoff.
- Provider-specific authentication and endpoint methods.

Completion condition:

- The client is responsible for transport/authentication/decoding only; it
  does not persist domain state or activate access.

### Step 3 — Implement transport, authentication, retry, and idempotency

Status: completed

Files:

- `apps/api/app/payment_providers/api_client.py`
- `apps/api/app/core/errors/`
- `apps/api/app/core/observability.py`
- `apps/api/app/integrations/cloudpayments/api_client.py`

Required work:

- Keep Basic Auth, bounded timeout components, and response validation.
- Distinguish timeout, transport, authentication, rate-limit, upstream,
  HTTP, decode, validation, and provider-declined failures.
- Require a non-empty stable `idempotency_key` before retrying refund or
  subscription mutations. A mutation without a key must not be retried.
- Keep `X-Request-ID` stable across retries of one logical operation.
- Redact request/response fields before logging or telemetry.
- Do not expose raw provider `Message` as a domain-safe error message; map it
  to a stable internal code and safe message.

Implemented in the current branch:

- Mutation requests now declare their mutating nature, and transport retries
  require a non-empty idempotency key for those requests.
- Idempotency keys are normalized once and the same `X-Request-ID` is reused
  across all attempts of one logical operation.
- Transport and client configuration validate positive bounded timeout and
  retry values; per-request timeout overrides retain component bounds.
- CloudPayments declines use a stable internal code and fixed safe message;
  provider `Message` is not propagated.
- Shared telemetry redaction covers CloudPayments credential, token,
  cryptogram, PAN, CVV/CVC, expiry, and masked-card field variants.
- Focused tests cover retry gating, stable request IDs, timeout bounds,
  decline-message safety, and structured-log redaction.

Completion condition:

- A provider mutation cannot be repeated by the transport layer unless the
  provider can deduplicate it with the same stable request key.

### Step 4 — Implement transaction lookup/reconciliation and refunds

Status: partially implemented; review follow-up required

Files:

- `apps/api/app/integrations/cloudpayments/api_client.py`
- `apps/api/app/integrations/cloudpayments/adapter.py`
- `apps/api/app/integrations/cloudpayments/refunds.py`
- `apps/api/app/payment_providers/contracts.py`

Required work:

- Add a raw client method for documented `v2/payments/find` by `InvoiceId`.
- Keep `payments/get` for exact lookup by `TransactionId`.
- Use this policy in the adapter:
  - `provider_payment_id` present: call `payments/get`;
  - otherwise use `provider_invoice_id`, or a documented
    `merchant_order_id` to invoice mapping;
  - not found: return a safe failed/unknown result without raw payload.
- Extend the lookup input with expected amount and currency, or perform the
  equivalent check before returning a successful reconciliation result.
- Verify returned `TransactionId`, `InvoiceId`, amount, currency, and terminal
  identity where available. Never fill missing provider values from the
  unverified request.
- Account for the fact that `v2/payments/find` can return the latest operation
  for an invoice, including a refund or payout. Reject non-payment or
  ambiguous results rather than treating them as the original payment.
- Require `Model.TransactionId` in a successful refund response. Missing model
  data is a response-validation failure, not a successful pending refund.
- Keep persistence and payment/refund state transitions outside the client and
  adapter.

Completion condition:

- An order can only be reconciled from provider-confirmed identifiers and
  matching commercial facts.

### Step 5 — Implement recurring subscription primitives

Status: partially implemented; review follow-up required

Files:

- `apps/api/app/integrations/cloudpayments/api_client.py`
- `apps/api/app/integrations/cloudpayments/adapter.py`
- `apps/api/app/payment_providers/contracts.py`

Required work:

- Implement these methods on `CloudPaymentsAdapter`:
  - `create_recurring_subscription`;
  - `update_recurring_subscription`;
  - `cancel_recurring_subscription`.
- Keep the raw client methods for:
  - `/subscriptions/create`;
  - `/subscriptions/update`;
  - `/subscriptions/cancel`.
- Map statuses exactly:
  - `Active` → `ACTIVE`;
  - `PastDue` → `PAST_DUE`;
  - `Cancelled` → `CANCELED`;
  - `Rejected` → `FAILED`;
  - `Expired` → `ENDED`;
  - any other value → `UNKNOWN`.
- Keep documented create fields: token, account ID, description, amount,
  currency, confirmation mode, start date, interval, period, and optional
  email/max periods.
- Remove `email` from both update request contracts.
- Reject an empty update patch.
- Return safe normalized results and never return raw subscription payloads.
- Apply the same account binding and idempotency rules as refunds.

Completion condition:

- All three recurring operations are callable through the provider-neutral
  adapter contract and return normalized safe results.

### Step 6 — Add focused mocked contract tests

Status: partially implemented; review follow-up required

Files:

- `apps/api/tests/test_payments_api_client.py`
- `apps/api/tests/test_cloudpayments_adapter_api.py`

Required coverage:

- Basic Auth and `X-Request-ID` behavior.
- Retry and non-retry classification, including mutation without a key.
- Lookup by `TransactionId` and fallback by `InvoiceId`.
- Not-found and mismatching identifier/amount/currency/account results.
- Refund happy path, transport failure, decline, schema mismatch, and missing
  `Model.TransactionId`.
- Recurring client endpoint paths and idempotency headers.
- Recurring adapter create/update/cancel happy paths.
- Recurring transport failure, provider decline, schema mismatch, empty update,
  and missing start date.
- All documented recurring status mappings and unknown status.
- Redaction of authorization, API secret, token, PAN, cryptogram, CVV/CVC,
  expiry, and masked-card fields in logs, traces, and safe error details.
- Provider messages are not exposed as unsanitized domain messages.

Completion condition:

- Acceptance behavior is demonstrated by isolated deterministic tests without
  real credentials or card data.

### Step 7 — Add observability and opt-in sandbox verification

Status: not started

Files:

- `apps/api/app/payment_providers/api_client.py`
- `apps/api/app/core/observability.py`
- `apps/api/tests/` or `scripts/`

Required work:

- Add one span per provider API operation.
- Add per-operation counter and duration histogram labelled only by provider,
  operation, and safe outcome.
- Use only these outcome labels:
  `succeeded`, `timeout`, `transport_error`, `authentication_error`,
  `rate_limited`, `upstream_error`, `http_error`, `response_decode_error`,
  `response_validation_error`, and `operation_declined`.
- Log provider declines once after mapping them to safe internal codes.
- Never put Basic Auth, API secret, token, raw request payload, or raw response
  body into logs, traces, metric labels, or test output.
- Extend shared redaction for CloudPayments fields including
  `CardCryptogramPacket`, `PAN`, `CVV`, `CVC`, card expiry, and token fields.
- Add a live verification path gated only by environment variables and off by
  default. It must cover lookup, refund, and recurring lifecycle where the
  configured sandbox supports them.
- Print only normalized safe results from live verification.

Completion condition:

- Normal test runs remain offline and deterministic, while a maintainer can
  explicitly run the sandbox verification path.

## Definition of Done

- Steps 1–7 are complete and their completion conditions are met.
- Provider API operations are available only through the provider boundary.
- No raw provider response or secret-bearing field reaches domain services,
  persistence, logs, traces, metrics, or test output.
- Mutating retries are safe because stable provider idempotency keys are
  mandatory for retry.
- Transaction reconciliation validates provider identity and commercial facts.
- Refund and recurring lifecycle operations have focused mocked tests.
- Sandbox verification is opt-in and skipped by default.

## Validation

Run the smallest relevant checks during implementation:

```bash
pytest apps/api/tests/test_payments_api_client.py
pytest apps/api/tests/test_cloudpayments_adapter_api.py
```

Before handoff, run:

```bash
npm run test:api
npm run check:fast
npm run check
```

Also run the sandbox verification command only when the required environment
variables are explicitly supplied. Record skipped checks and any environment
limitations in the completion evidence.

## Completion evidence

When the work is complete, add:

- the final changed-file summary;
- focused test results and full API check results;
- redaction/secrecy test results;
- sandbox verification result or explicit skipped status;
- Bugbot/security review result and disposition of findings;
- any remaining non-blocking debt.
