# ANY-112 — Enforce Minimal Domain Boundaries

Status: completed
Owner: repository maintainers
Completed: 2026-07-13
Linear: https://linear.app/paveldik/issue/ANY-112/reorganize-code-into-enforced-domain-boundaries

## Objective

Strengthen the critical Python and web dependency boundaries for the current RU
MVP without changing public routes, response schemas, or compatibility modules.

## Non-goals

- Complexity metrics.
- Repository/service decomposition or aggregate-model migration owned by ANY-71.
- A general feature dependency graph or comprehensive contract snapshot system.

## Decisions

- Python dependencies are analyzed with the standard-library AST.
- Existing `app.models` imports remain allowed during the ANY-71 transition.
- Shared footer content is composed by the app layer and injected into shared UI.
- Boundary failures identify the source, dependency, rule, and remediation.

## Completed work

- [x] Extracted the shared identity session dependency from the identity router.
- [x] Replaced regex Python import scanning with AST boundary analysis.
- [x] Enforced minimal web dependency directions with ESLint.
- [x] Removed the shared-to-feature footer dependency through composition.
- [x] Added focused negative and compatibility tests.
- [x] Recorded validation and compatibility evidence.

## Discoveries

- The first local browser-stack start reused a stale PostgreSQL volume whose
  duplicate legal seed prevented API startup; resetting the worktree-scoped
  runtime restored a clean environment.
- One checkout test failed once during the first parallel browser run, then
  passed in isolation and in the complete 22-test rerun.

## Completion evidence

- `python -m pytest apps/api/tests/test_architecture.py`: 5 passed.
- `npm run test:boundaries:web`: 4 passed.
- `npm run check:fast`: documentation, generation, architecture, ESLint, 4 web
  boundary tests, and 30 Python/API tests passed.
- `npm run typecheck:web`: passed.
- `npm run check`: passed; its environment-gated PostgreSQL and browser steps
  were run separately below.
- PostgreSQL Alembic upgrade/downgrade integration: 1 passed.
- `npm run test:e2e`: 22 passed on desktop and mobile Chromium.
- Production web and Docker image builds completed successfully.
- `docs/generated/openapi.json` has no diff from `origin/main`.
