# ANY-76 Follow-up — Refund Result Status

Status: active
Owner: repository maintainers
Started: 2026-07-11

## Objective

Show verified full and partial refund outcomes on `/ru/payment-result` from
backend payment/order state instead of leaving refunded payments in pending UI.

## Non-goals

- Activating access from browser return URLs.
- Changing CloudPayments refund normalization or legal content.
- Expanding catalog, subscriptions, entitlements, or ANY-71 scope.

## Progress

- [x] Read root, web, API, product, design, workflow, and data-model guidance.
- [x] Locate payment-result status derivation and refund webhook normalization.
- [x] Add frontend refund display based on normalized backend status.
- [x] Add frontend and backend refund-status tests.
- [x] Run focused checks and browser evidence.
- [x] Record completion evidence.

## Decisions

- Payment-result derives refund UI from `order.status`, `payment.status`, and
  `payment.refunded_amount_minor`, never from `status` query parameters.
- Partial refund is shown when backend reports `partially_refunded` or a positive
  refunded amount lower than the captured/payment amount.

## Completion evidence

- `npm run lint:web`: passed.
- `npm run build:web`: passed.
- `./.venv/bin/python -m pytest apps/api/tests/test_api.py -k refund`: 2 passed.
- `./.venv/bin/python -m pytest apps/api/tests`: 21 passed, 1 skipped
  (`test_alembic_postgres.py` skipped by test configuration).
- `./.venv/bin/python scripts/repo.py check --fast`: documentation, generated
  checks, architecture, web lint, and API tests passed.
- `npm exec playwright test -- --config playwright.config.ts apps/web/e2e/payment-result-refund.spec.ts --headed --workers=1`:
  4 passed across desktop and mobile Chromium.
- Harness PostgreSQL E2E data:
  - `document-summary-205600e4b53415cb`: order/payment `refunded`,
    `refunded_amount_minor=99000`, one refund row.
  - `document-summary-6dcc1b790ba9de00`: order/payment
    `partially_refunded`, `refunded_amount_minor=40000`, one refund row.
- Live browser verification against harness web/API:
  - Full refund URL with spoofed `status=success` rendered
    `Платёж возвращён` / `Возврат выполнен` and no `Ожидаем подтверждение`.
  - Partial refund URL with spoofed `status=success` rendered
    `Платёж частично возвращён` / `Частичный возврат` and no
    `Ожидаем подтверждение`.
  - Screenshots: `.harness/playwright-results/live-refund-full.png` and
    `.harness/playwright-results/live-refund-partial.png`.
