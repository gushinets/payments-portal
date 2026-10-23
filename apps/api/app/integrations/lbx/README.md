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
retried. No CREATE transport is supplied here.

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

## ANY-709 Step 3 — private preparation and point proof

The earlier inventory above describes the selected-catalog foundation.
`preparation_dto.py`, `preparation_profile.py` and `preparation.py` now extend
the same Server client with strict private non-payment CREATE, identity/material
point GET and bounded scoped discovery. They add no public API, persistence,
recovery loop, Widget authorization, payment or access grant.

The implementation follows the named [Swagger 1.0.11 schemas](https://demo.lbxbilling.ru/swagger/swagger.json)
and reuses [ANY-634's recorded conclusions](../../../../../docs/superpowers/phase0/2026-10-14-any-634-lbx-evidence-handoff.md).
Customer/agreement POST accepts the documented HTTP 201. Subscription POST
accepts HTTP 200 or 201 (ANY-634 B1). The strict ID envelope is only a receipt;
`LbxPreparation.prove_*` must obtain authoritative point GETs before returning
`complete_match`. Other outcomes are `incomplete`, `mismatch`,
`identity_conflict`, `owner_conflict` and `unresolved`. All are private.

Server auth is acquired before send. A mutating POST has exactly one exchange;
there is no automatic refresh/replay for 401, 429, 5xx, timeout or disconnect.
Any post-send response/parsing/cleanup/deadline/cancellation failure raises
`LbxCreateUncertain(possible_send=True)`. Pre-send profile/auth failures remain
separate. Callers must commit their durable fence before invoking CREATE and
retain it on ambiguity; this Integration does not own that transaction. A
successful receipt is not a binding or permission to repeat CREATE.

The SIMULATED profile in `tools/purchase_mock/preparation.json` explicitly
selects the same account, seller, currency, calendar, service quantity and
commercial policy as Step 2's `profile.json`. Its lawful-field set authorizes
only the test customer type and simulated email; no name/passport/company is
synthesized. It explicitly selects one supplied service (or a separately
selected default-only rule), no demo/manual activation, zero debt and balance
activation. Potential balance activation/debit remains part of the stated
create evidence. All added HTTP recordings are visibly test-only and use the
same selected tariff/service/period as the catalog recordings.

`RecordedPreparationTransport` never opens a socket. CREATE also refuses
production or a client without an injected `httpx.MockTransport`, independently
of settings. The optional `LBX_SELLER_ORGANIZATION_ID` has no default organization
and is checked against the explicit fixture seller when supplied.
`LBX_DISCOVERY_MAX_ITEMS` bounds candidate lists (default 50); reaching the cap,
duplicate IDs, invalid rows, extra envelope fields or unverifiable ownership
fails closed. Discovery sends only documented JSON GET filters: customer
`outer_id` plus `show_passwords=false`, or exact owner `user_id`. Subscription
lists have no owner field, so their agreement owners are point-checked. Results
remain hints, including zero/one matches; they never clear an earlier possible
send or authorize a new POST. There is no invented pagination or visibility SLA.

Customer proof pairs the canonical user ID and original immutable key.
Agreement proof checks the canonical agreement, owner, configured seller,
dedicated immutable reference/date/offer and no-credit fields. Local exclusive
ownership of that dedicated reference remains the caller's persisted hold
invariant. Credential origin/account binding is explicit SIMULATED account
evidence, not a fictional GET field. Subscription proof rereads that ownership
chain and checks exact selected tariff/period/start, one service, integer
quantity inside service bounds, effective `services[].price`, `total_price`,
supported status/calendar fields and absence of a scheduled material change.
`tariff_price` is comparison-only. Currency symbol is matched against explicit
account currency/unit/scale evidence, never converted blindly to ISO. Exact
minor-unit conversion does not depend on Decimal context precision.

Connection charges and renewal/cancellation/historical policy have no invented
subscription GET fields: their immutable selected-catalog digest and matching
account policy evidence are retained with the normalized proof. The normalized
connection amount is the accepted catalog implication, not evidence of an
actual provider debit. No proof here establishes paid access.

Real CREATE remains disabled. The remaining G2 real-account gate is the lawful
minimum customer/agreement field set, seller/legal/no-credit binding, verified
money units/ISO scale, evidenced billing calendar, one-default-service request
rule and exact activation/debit semantics. Missing real facts do not prevent
unrelated startup. These recordings do not upgrade any real-account UNKNOWN.

Formatting only was performed for this step. Tests, linters, typechecks, builds,
migrations, generation and broad checks were not run. No public contract changed.
Run manually from the repository root:

```bash
export PATH="$PWD/.venv/bin:$PATH"
./.venv/bin/python -m pytest -q apps/api/tests/test_lbx_prepare_readback.py apps/api/tests/test_lbx_client.py apps/api/tests/test_lbx_client_errors.py
./.venv/bin/python scripts/repo.py lint api
npm run test:api:fast
```
