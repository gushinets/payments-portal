# ANY-167 - Complete CloudPayments notification adapter

Status: active
Owner: Codex
Parent: ANY-163

## Goal

Complete CloudPayments notification handling while keeping provider-specific
verification, payload parsing, response codes, and redaction inside the adapter
or integration layer.

## Scope

- Validate Check notifications against existing orders before acknowledging.
- Keep Pay, Fail, Refund normalized into provider-neutral payment events.
- Persist and normalize Recurrent notifications for downstream subscription
  handling without implementing subscription business state.
- Support Confirm and Cancel notifications for two-stage payment schemas.
- Preserve durable inbox, idempotency, redaction, and monotonic terminal
  payment/order transitions.
- Add signed webhook and PostgreSQL idempotency coverage.

## Evidence

- Baseline:
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py -k 'cloudpayments or webhook or refund or late_fail or duplicate_success'`:
  18 passed, 32 deselected.
- `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py -k 'cloudpayments or webhook or refund or late_fail or duplicate_success or confirm_and_cancel or recurrent or signed_check or signed_pay'`:
  23 passed, 32 deselected.
- Review fixes:
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py -k 'cloudpayments or webhook or refund or late_fail or duplicate_success or confirm_and_cancel or late_pay_or_confirm or recurrent or signed_check or signed_pay'`:
  24 passed, 32 deselected.
- `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_cloudpayments_webhook_postgres.py`:
  3 skipped because `TEST_POSTGRES_DATABASE_URL` is not set locally.
- `python3 -m compileall -q apps/api/app`: passed.
- `python3 scripts/repo.py architecture check`: passed.
- `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_architecture.py`:
  6 passed.
- `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py`:
  55 passed.
- `npm run check:fast`: failed before checks because this shell has no `python`
  executable.
- `PATH=.venv/bin:$PATH npm run check:fast`: passed; 74 passed, 3
  PostgreSQL webhook tests skipped because `TEST_POSTGRES_DATABASE_URL` is not
  set locally.
- Review fixes:
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py`:
  56 passed.
- Review fixes:
  `python3 -m compileall -q apps/api/app`: passed.
- Review fixes:
  `python3 scripts/repo.py architecture check`: passed.
- Review fixes:
  `PATH=.venv/bin:$PATH npm run check:fast`: passed; 75 passed, 3
  PostgreSQL webhook tests skipped because `TEST_POSTGRES_DATABASE_URL` is not
  set locally.
- Blocking review fixes evidence:
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py -k 'cloudpayments or webhook or refund or late_fail or duplicate_success or confirm_and_cancel or late_pay_or_confirm or recurrent or signed_check or signed_pay or authorized_pay or provider_cancel or expired_pay or second_successful_charge or refund_bound'`:
  31 passed, 33 deselected.
  `TEST_POSTGRES_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/payments_portal_test .venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_cloudpayments_webhook_postgres.py`:
  3 passed against a disposable local PostgreSQL 18.4 container.
  `npm --workspace @anytoolai/web run test:components -- PaymentResultClient.test.tsx`:
  9 passed.
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py`:
  64 passed.
  `python3 -m compileall -q apps/api/app`: passed.
  `python3 scripts/repo.py architecture check`: passed.
  `PATH=.venv/bin:$PATH npm run check:fast`: passed; 83 passed, 3
  PostgreSQL webhook tests skipped inside the broad harness because
  `TEST_POSTGRES_DATABASE_URL` is not set for that command.
- Follow-up review fixes evidence:
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py -k 'late_pay_and_confirm_after_checkout_expiry or cloudpayments or refund or cancel or recurrent or second_successful_charge'`:
  24 passed, 40 deselected.
  `npm --workspace @anytoolai/web run test:components -- PaymentResultClient.test.tsx`:
  10 passed.
  `PATH=.venv/bin:$PATH npm run docs:check`: passed.
  `TEST_POSTGRES_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/payments_portal_test .venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_cloudpayments_webhook_postgres.py`:
  7 passed against a disposable local PostgreSQL 18.4 container.
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py`:
  64 passed.
  `python3 -m compileall -q apps/api/app`: passed.
  `python3 scripts/repo.py architecture check`: passed.
  `PATH=.venv/bin:$PATH npm run check:fast`: passed; 83 passed, 7
  PostgreSQL webhook tests skipped inside the broad harness because
  `TEST_POSTGRES_DATABASE_URL` is not set for that command.
- Remaining review fixes evidence:
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py -k 'authorized_pay or late_distinct_pay or recurrent or idempotency_key'`:
  6 passed, 58 deselected.
  `TEST_POSTGRES_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/payments_portal_test .venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_cloudpayments_webhook_postgres.py`:
  8 passed against a disposable local PostgreSQL 18.4 container.
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py`:
  64 passed.
  `python3 -m compileall -q apps/api/app`: passed.
  `python3 scripts/repo.py architecture check`: passed.
  `PATH=.venv/bin:$PATH npm run docs:check`: passed.
  `PATH=.venv/bin:$PATH npm run check:fast`: passed; 83 passed, 8
  PostgreSQL webhook tests skipped inside the broad harness because
  `TEST_POSTGRES_DATABASE_URL` is not set for that command.
- Review comment fixes evidence:
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py -k 'cloudpayments or webhook or refund or late_fail or late_distinct_pay or multiple_successful or recurrent or signed_check or signed_pay or confirm_and_cancel or authorized_pay'`:
  32 passed, 34 deselected.
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_cloudpayments_webhook_postgres.py`:
  9 skipped because `TEST_POSTGRES_DATABASE_URL` is not set locally.
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py`:
  66 passed.
  `python3 -m compileall -q apps/api/app`: passed.
  `python3 scripts/repo.py architecture check`: passed.
  `git diff --check`: passed.
  `PATH=.venv/bin:$PATH npm run check:fast`: passed; 85 passed, 9
  PostgreSQL webhook tests skipped inside the broad harness because
  `TEST_POSTGRES_DATABASE_URL` is not set for that command.
- Final defect fixes:
  enabled the configured CloudPayments `auth` checkout mode, gated DMS-only
  notifications by payment schema, preserved late-charge refund accounting and
  customer-visible provider truth, rejected unscoped Recurrent events, and
  normalized terminal Recurrent statuses and schedule fields.
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py`:
  70 passed.
  `npm --workspace @anytoolai/web run test:components -- CheckoutClient.test.tsx PaymentResultClient.test.tsx`:
  22 passed.
  `TEST_POSTGRES_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/payments_portal_test .venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_cloudpayments_webhook_postgres.py`:
  10 passed against a disposable local PostgreSQL 18.4 container.
  `python3 -m compileall -q apps/api/app`: passed.
  `python3 scripts/repo.py architecture check`: passed.
  `git diff --check`: passed.
  `PATH=.venv/bin:$PATH npm run check:fast`: passed; 89 passed, 10
  PostgreSQL webhook tests skipped inside the broad harness because
  `TEST_POSTGRES_DATABASE_URL` is not set for that command.
