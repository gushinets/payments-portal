# Web Agent Guide

Read the root `AGENTS.md`, [the `ru` journey](../../docs/product/ru-mvp.md),
[contours](../../docs/architecture/contours.md),
[design](../../docs/DESIGN.md), and the
[web section of coding conventions](../../docs/engineering/CODING_CONVENTIONS.md#web--typescript)
before frontend work.

## Conventions

- Treat `response.json()`, `JSON.parse`, storage, and query params as
  `unknown`. `as T` is not validation.
- HTTP helpers take a decoder or return `unknown`; a generic `T` without a
  decoder is forbidden. A decoder must fail on mismatch and have a test that
  rejects an invalid value.
- Keep API types in `shared/api` or the feature API module; do not copy
  response types in components.
- Inspect errors with `ApiError.status` and `detail.code`, never
  `message.includes(...)`.

## Boundaries

- App routes compose feature entrypoints.
- Feature modules own product behavior.
- Shared modules own reusable API contracts, configuration, and UI primitives.
- Features must not deep-import another feature's internals.

## UI rules

- Preserve the current contour's customer-facing locale. The implemented `ru`
  contour uses Russian.
- Use Bundle 3 tokens and glass/bento patterns; do not invent replacement tokens.
- Prefer semantic roles and labels. Add `data-testid` only when a stable semantic
  selector is unavailable.
- UI changes require desktop and mobile evidence and accessibility checks.

## Checks

```bash
npm run lint:web
npm run build:web
npm run test:e2e
```
