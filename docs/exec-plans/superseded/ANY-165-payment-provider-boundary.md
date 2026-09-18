# ANY-165 - Minimal payment provider boundary

> **Classification: superseded — retained implementation history.** Do not
> continue this plan as the target billing direction. Already implemented source
> may remain temporarily for characterization and later gated cleanup. New
> billing work follows [ADR 0005], the [External Billing Boundary Design], and
> the [Portal ↔ Kernel Access Contract Design].

[ADR 0005]: ../../architecture/decisions/0005-external-billing-boundary.md
[External Billing Boundary Design]: ../../superpowers/specs/2026-09-15-external-billing-boundary-design.md
[Portal ↔ Kernel Access Contract Design]: ../../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md

Status: superseded
Owner: Codex
Parent: https://linear.app/paveldik/issue/ANY-163/podklyuchenie-cloudpayments-vidzhet-api-uvedomleniya-podpiski

## Goal

Introduce the smallest backend and frontend payment-provider boundary needed to
keep billing and checkout domain code provider-neutral while CloudPayments
remains the only production adapter.

## Scope

- Define provider-neutral backend contracts for checkout actions and normalized
  webhook events.
- Register CloudPayments at the API composition root by provider code.
- Keep CloudPayments verification, payload parsing, response formatting,
  redaction, and external identifiers inside the adapter.
- Select checkout provider accounts from `payment_provider_accounts`.
- Define a small web checkout-adapter contract and register CloudPayments only.
- Add architecture tests that fail when provider-neutral modules import provider
  integrations or branch on the `cloudpayments` literal.

## Evidence

- `python3 -m compileall -q apps/api/app`: passed.
- `python3 scripts/repo.py architecture check`: passed.
- `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_architecture.py`:
  6 passed.
- `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py -k 'checkout or cloudpayments or webhook or refund'`:
  21 passed, 22 deselected.
- `npm --workspace @anytoolai/web run test:components -- CheckoutClient.test.tsx`:
  5 passed.
- `npm run build:web`: passed.
- `PATH=.venv/bin:$PATH npm run check`: passed; 58 API tests passed, 2
  PostgreSQL webhook tests skipped, web boundaries/components/lint/build passed.
  PostgreSQL integration was skipped because `TEST_POSTGRES_DATABASE_URL` was
  not set; browser e2e was skipped because `RUN_E2E=true` and a running harness
  stack were not set.
- Review fixes:
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py -k 'cloudpayments or webhook or checkout'`:
  24 passed, 24 deselected.
- Review fixes:
  `npm --workspace @anytoolai/web run test:components -- CheckoutClient.test.tsx`:
  7 passed.
- Review fixes:
  `PATH=.venv/bin:$PATH npm run check:fast`: passed; 63 API tests passed, 2
  PostgreSQL webhook tests skipped, web boundaries/components/lint passed.
- Review fixes:
  `npm run build:web`: passed.
