# ANY-166 - CloudPayments browser checkout adapter

Status: active
Parent: ANY-166

## Goal

Move the one-time CloudPayments browser checkout behind the provider boundary
while preserving the existing RU checkout journey and keeping browser success
informational until verified provider state arrives.

## Scope

- Keep CloudPayments widget calls isolated to the browser checkout adapter.
- Make backend checkout intent return the public terminal identifier required by
  the adapter.
- Reject missing CloudPayments public terminal configuration and non-charge
  widget modes before persisting checkout state.
- Validate SDK readiness and safe checkout descriptor fields before opening the
  widget.
- Remove the synthetic pending redirect fallback when a provider widget cannot
  be opened.
- Extend unit and provider-UI stub coverage for safe one-stage charge payloads.

## Evidence

- `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py -k 'checkout or cloudpayments'`:
  20 passed, 30 deselected.
- `npm --workspace @anytoolai/web run test:components -- CheckoutClient.test.tsx`:
  10 passed.
- `node apps/web/tests/app-metadata.test.mjs`: 3 passed.
- `PATH=.venv/bin:$PATH npm run check:fast`: passed; 65 API tests passed, 2
  PostgreSQL webhook tests skipped, web boundaries/components/lint passed.
- `npm run build:web`: passed.
- `python3 -m compileall -q apps/api/app`: passed.
- `npm run lint:web`: passed after provider-UI stub smoke assertions.
- `PATH=.venv/bin:$PATH npm run docs:check`: passed.
- `python3 scripts/repo.py harness-smoke`: passed after CI browser runtime fix.
- API checkout smoke against the local harness stack returned
  `public_identifier=test-provider-public-id` and `mode=charge`.
- GitHub Actions `browser` job on PR #24 passed after the CI browser runtime fix.
- `PLAYWRIGHT_PROVIDER_UI_STUB=true npm exec playwright test -- --config playwright.config.ts apps/web/e2e/checkout-webhook.spec.ts --project desktop-chromium --workers=1 -g "provider UI stub success"`:
  not completed locally. Chromium exits with `SIGTRAP` in the macOS sandbox
  before the test body runs.

## Notes

- Browser e2e remains opt-in because it requires `RUN_E2E=true` or a focused
  Playwright invocation plus a running harness stack. The provider UI stub path
  is extended to assert the one-stage CloudPayments charge payload without card
  data.
