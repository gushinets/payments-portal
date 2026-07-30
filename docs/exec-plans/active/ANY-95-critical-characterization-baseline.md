# ANY-95 — Critical Characterization Baseline

Status: active
Owner: repository maintainers
Started: 2026-07-30

## Objective

Complete the minimal frontend component and browser characterization baseline
needed before ANY-165 changes the internal multi-provider payment boundary.

## Non-goals

- Implementing new CloudPayments widget, notification, API, or recurring
  behavior.
- Enforcing the future multi-provider architecture boundary owned by ANY-165.
- Adding broad coverage thresholds or cross-browser CI matrices.

## Progress

- [x] Read root, web, API, product, design, data-model, and workflow guidance.
- [x] Inspect current Playwright, backend, PostgreSQL, and CI baseline.
- [x] Add frontend component test infrastructure with Vitest, RTL, MSW,
  jest-dom, user-event, and V8 coverage reporting.
- [x] Add provider-neutral checkout UI helper and critical component
  characterization tests.
- [x] Wire component tests and coverage into local harness and ANY-92 CI.
- [x] Run focused and canonical checks.
- [x] Record completion evidence.

## Decisions

- Component tests should assert provider-neutral outcomes: browser success may
  store and navigate to pending result state, but only backend polling can render
  paid, failed, or active states.
- The provider UI test helper may use the current CloudPayments browser shape as
  a compatibility adapter, while exposing only generic success/fail controls to
  tests.
- Coverage is produced as a report and CI artifact, without a high global
  blocking threshold.

## Completion Evidence

- `npm --workspace @anytoolai/web run test:components`: 8 passed.
- `npm --workspace @anytoolai/web run test:components:coverage`: 8 passed;
  V8 HTML/JSON coverage written under `.harness/coverage/web-components`.
- `npm run typecheck:web`: passed.
- `npm run lint:web`: passed.
- `./.venv/bin/python scripts/repo.py check --fast`: documentation, generated
  artifacts, architecture, web boundary tests, component tests, lint, and API
  tests passed; API PostgreSQL-only tests were skipped by test configuration.
- `./.venv/bin/python scripts/repo.py check`: passed; PostgreSQL integration
  and full browser suite skipped because `TEST_POSTGRES_DATABASE_URL` and
  `RUN_E2E=true` were not set.
- `PLAYWRIGHT_PROVIDER_UI_STUB=true npm exec playwright test -- --config playwright.config.ts apps/web/e2e/checkout-webhook.spec.ts --project desktop-chromium --workers=1`:
  2 passed against the local harness stack with real Next.js, FastAPI, and
  PostgreSQL through Caddy.
