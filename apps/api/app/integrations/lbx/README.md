# ANY-664 Step 3 handoff

Implementation source only; tests, checks and live LBX requests have **not**
been run for this step. This boundary grants no commercial or paid-access
approval. Step 4 owns complete selected-offer normalization and classification.

## Source inventory

The public [LBX Swagger JSON](https://demo.lbxbilling.ru/swagger/swagger.json)
was inspected as version **1.0.11** on 2026-10-16. Its server path is
`/api/rest/v1`. Authentication and envelope conventions also follow the
[API quick start](https://docs.lbxbilling.ru/api/api_start/). Only public
documentation was fetched; no Server API endpoint was called.

- `GET /auth`: `Auth` envelope, Basic credentials, session `token` and returned
  `expires_in`; subsequent reads use Bearer. No fixed 600-second guarantee.
- `list_tariffs(tariff_id=..., budget=...)`: `GET /tariffs`, documented
  `GetTariffsFilter` JSON **request body** containing only `tariff_id`;
  `TariffsList` / `TariffInfo` response. Selection is mandatory; an empty list
  remains empty, extra or mismatched tariff identities are refused. No account
  query parameter or pagination protocol is documented for this read.
- `get_tariff(tariff_id=..., budget=...)`: `GET /tariffs/{tar_id}`,
  `RetTariffInfo` / `TariffInfo` and optional `AddonsInfo`.
- `list_tariff_periods(tariff_id=..., budget=...)`:
  `GET /tariffs/{tar_id}/periods`, `TarPeriodsList` / `TarPeriodInfo`.
  This already carries `period_id`, `period_type`, `period_length` and `hidden`,
  so this foundation needs no additional `GET /periods`.
- `list_tariff_services(tariff_id=..., budget=...)`:
  `GET /tariffs/{tar_id}/services`, `TarServicesList` / `TariffServiceInfo`,
  nested `NewPriceInfo`, `PeriodDiscountInfo` and `DiscountInfo`.
- `list_service_prices(tariff_id=..., tariff_service_id=..., budget=...)`:
  `GET /tariffs/{tar_id}/services/{service_id}/prices`,
  `TarServPricesList` / `PriceInfo` / `CreatePriceInfo`.
  Here `service_id` is the tariff service identity. Standalone price lookup,
  subscription reads and provider writes are not part of this inventory.

## Inputs, outputs and ownership

`Settings` adds optional, all-or-none `LBX_BASE_URL` (origin only),
`LBX_EXTERNAL_BILLING_ACCOUNT_ID`, `LBX_SERVER_USERNAME` and
`LBX_SERVER_PASSWORD`. Credentials belong to that explicitly configured RU
account. These GETs do not attest the account in a response field, so deployment
credential/account binding still requires independent evidence. No currency
mapping, scale, selected product, tariff or price is a runtime default.
Production configuration requires HTTPS; HTTPX verifies TLS, ignores ambient
proxy/auth configuration, and refuses redirects. No credential goes in a URL.

The optional application-policy settings are `LBX_CONNECT_TIMEOUT_SECONDS`,
`LBX_READ_TIMEOUT_SECONDS`, `LBX_MAX_RESPONSE_BYTES`, `LBX_MAX_GET_ATTEMPTS`,
`LBX_RETRY_DELAY_SECONDS` and `LBX_MAX_RETRY_DELAY_SECONDS`. Defaults are Portal
resource limits, not LBX SLAs. Attempt limits count **all** HTTP exchanges for
one logical read: initial auth, selected GET, transient retries and at most one
GET reauth. Another selected read starts its own attempt counter but receives
the same nonrenewable caller deadline. Only 429/500/502/503/504, network failures
and HTTP timeouts are retried. Retry-After seconds/dates and exponential backoff
are capped by policy and by the remaining caller budget. Auth 401/403 and
malformed responses are not transient. Authenticated GET 401 allows one reauth;
another caller's replacement token is retained when an older request fails.
Expiry between transient GET attempts also consumes that single replacement;
it cannot open another refresh loop.

`LbxServerClient(configuration, transport=...)` owns one HTTP pool and an
in-memory session/refresh lock, with no constructor request or catalog cache.
Instantiate it explicitly in source-work composition; do not add it as a
required dependency of startup, DB-only query or public catalog browsing.
Only tests inject an HTTP transport. Callers obtain `budget` from the existing
`PreflightAdmission.operation()` and pass it unchanged through Kernel reads,
these selected reads and Step 4 normalization. No SQLAlchemy resource belongs
in that scope, and a budget permits one counted source task at a time.

Every read returns Integration-only `LbxRead[T]` from `client.py`: configured
account, requested tariff/service identity, local UTC observation time and a
validated DTO from `dto.py`. Observation time is not a provider snapshot or a
price-applicability decision. DTOs preserve source IDs, exact `Decimal` values,
separate recurring/connection prices, calendar dates and optional fields.
Inline prices use documented `price_start_date`; the dedicated prices GET uses
`start_date` and optional `next_change_date`. No date becomes a guessed UTC
cycle boundary. Missing/null fields stay `None`; empty arrays stay empty.
Step 4 must decide completeness and normalize before Application. Neither
`currency_id` nor commercial service multiplier bounds establish ISO money,
money scale or integer Kernel allowance. Unsupported extra wire fields fail
validation rather than silently losing potential evidence.

The existing `PreflightBudget.run()` owns full read/lock/retry/body/cleanup
accounting. A canceled read retains its admission slot until its actual stream
close finishes, including HTTPX's automatic close at EOF. Stop and drain the
owning admission before `client.aclose()`; if `PreflightCleanupPending` is
raised, retain the client until counted work has stopped. There are no detached
refresh tasks. Per-HTTP sublimits never extend the absolute work deadline.

## Failures and future boundary

All Server API methods use the same bounded decoder for success and failure.
An LBX error envelope (`code`, `response.error`) is a provider refusal even at
HTTP 500 or inside HTTP 200. Unknown nonempty error text becomes the safe
`provider_rejected` category; it is never retained. Authentication/permission,
rate limit, malformed response, no-response network failure and timeout remain
distinct. Missing error text alone is not success: the success DTO must validate.

Classification and retries are independent: unknown transient HTTP/LBX codes
retain bounded GET retries and the provider error class/codes; known permanent
rejections do not retry. A 5xx without a readable LBX refusal retains bounded
unavailability retries; malformed error fields remain invalid responses with
bounded GET retries at transient codes. POST never automatically retries. An error envelope does
not prove that CREATE had no effect; customer send fencing and GET recovery
remain authoritative for handling an uncertain outcome.

`LbxResponseFacts` and the existing `lbx_http` event carry HTTP/LBX codes,
error-field presence, safe reason/failure category, GET retry eligibility,
method/allowlisted endpoint template and request/create-operation correlation.
No response is represented by null codes. Arbitrary body text, provider IDs,
URLs, credentials and request values never enter these diagnostics.

`errors.py` contains safe `AppError` subclasses. `LbxNotConfigured` and
`LbxClosed` indicate resource misuse/absence; `LbxAuthenticationFailed` is
unauthorized auth or persistent GET 401; `LbxScopeForbidden` is 403;
`LbxScopeMismatch` rejects invalid requested or mismatched returned identities;
`LbxResponseInvalid` rejects malformed/enlarged/unsupported envelopes and
payloads; `LbxRateLimited`, `LbxUnavailable`, `LbxTimeout` classify exhausted
transient reads; `LbxAttemptsExhausted` refuses further exchanges when the total
limit is spent between successful auth and the next GET. Shared
`PreflightDeadlineExceeded`, saturation/closure and cancellation keep their
Step 2 meanings. Presentation later maps concrete exceptions to `detail.code`.
Errors contain no provider response body, URL, credentials or raw exception.
`privacy.py` suppresses automatic HTTPX/httpcore diagnostics in the counted LBX
I/O/close context, including debug response headers and raw transport errors.
Other tasks keep their logger settings and diagnostics. No raw body or header
is emitted by this Integration.

Existing `ExternalCreateOperationKind` already defines customer, agreement and
subscription operation identities in `app.models`; no speculative parallel
operation vocabulary/response DTO or callable mutation is needed by this read
consumer. Future program Steps 7/8 must persist the operation before CREATE;
an uncertain result stays UNKNOWN and is discovered read-only, never blindly
retried. That was the original read-consumer boundary. ANY-709 Step 2 now adds
only fenced customer CREATE, users discovery/point reads and Client user
readiness on this same real client. No agreement/subscription/payment mutation
is supplied in this step. `LbxCreateNotSent` proves a before-dispatch failure;
every dispatched failure remains uncertain. Customer responses accept the
operation-specific 200/201 envelope and must be point-verified before binding.
Technical login/password are generated only for one POST; JWT signing uses
type 7, the proven canonical ID and fresh `iat`. Account traffic has separate
bounded admission/pool capacity from offer reads. See the
[normal account runbook](../../../../../docs/engineering/lbx-product-links.md#human-account-widget-checkpoint-step-2).

Selected-account currency/scale, historically applicable policy, rollback
guarantees and actual account/credential deployment remain unverified. B1 and
B8/B9 evidence and B15 reviewed policy retain their existing evidence levels;
these fixtures cannot certify them. Tests use only visibly simulated HTTP
responses in `apps/api/tests/fixtures/lbx/`, through the real parser/client.

## Manual verification

Run from `/home/wstanley/www/work_unirec/payments-portal`, using the existing
repository-root environment. No generation or migration is needed; dependency
manifests, Portal HTTP contracts and persistence are unchanged.

```bash
export PATH="/home/wstanley/www/work_unirec/payments-portal/.venv/bin:$PATH"
./.venv/bin/python -m pytest -q apps/api/tests/test_lbx_client.py apps/api/tests/test_lbx_client_errors.py
npm run lock:check:api
npm run architecture:check
npm run check:fast
```

These commands are a human handoff, not recorded PASS evidence. No live provider
probe is required or authorized by this implementation. The PATH prefix supplies
the `python` executable expected by the repository npm aliases without creating
another environment.
