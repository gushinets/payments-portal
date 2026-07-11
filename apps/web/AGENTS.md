# Web Agent Guide

Read the root `AGENTS.md`, `docs/product/ru-mvp.md`, and `docs/DESIGN.md` before
frontend work.

## Boundaries

- App routes compose feature entrypoints.
- Feature modules own product behavior.
- Shared modules own reusable API contracts, configuration, and UI primitives.
- Features must not deep-import another feature's internals.

## UI rules

- Preserve Russian customer-facing localization.
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
