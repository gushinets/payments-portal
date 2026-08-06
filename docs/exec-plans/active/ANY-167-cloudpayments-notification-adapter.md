# ANY-167 - Complete CloudPayments notification adapter

Status: active
Owner: Codex
Parent: https://linear.app/paveldik/issue/ANY-163/podklyuchenie-cloudpayments-vidzhet-api-uvedomleniya-podpiski

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
