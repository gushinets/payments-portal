# ANY-108 — AI-Agent-First Repository Transition

Status: active
Owner: repository maintainers
Started: 2026-07-11

## Objective

Make Payment Portal independently legible, runnable, observable, verifiable, and
maintainable by coding agents while retaining human merge approval.

## Non-goals

- Platform Kernel implementation.
- ANY-71 catalog, subscription, entitlement, or access-API delivery.
- Translation of RU legal documents or customer-facing copy.

## Progress

- [x] Audit the current repository, tests, docs, schema, and runtime configuration.
- [x] Establish the English knowledge hierarchy.
- [x] Make legal metadata and generated references deterministic.
- [x] Add the isolated worktree harness.
- [x] Enforce architecture boundaries.
- [x] Add logs, metrics, traces, and browser journeys.
- [x] Add CI, PR title validation, ownership, and gardening.
- [ ] Complete a clean-context agent trial and record evidence.

## Decisions

- PR titles use `ANY-<number> - <summary>`.
- The corrected initial migration is allowed because production has not launched.
- Agents prepare PRs; humans approve merges.
- Russian legal and RU UI content are language-policy exceptions.

## Completion evidence

- `npm run check:fast`: documentation, generated artifacts, architecture, web
  lint, and API tests.
- PostgreSQL integration: clean upgrade, exact six-document legal seed, hashes,
  clean downgrade, and schema cleanup.
- `npm run test:e2e`: 18 desktop/mobile journeys with accessibility, console,
  network, screenshot, trace, video-on-failure, and JSON evidence.
- `python scripts/repo.py harness-smoke`: deterministic disjoint current and
  second-worktree project, database, and port assignments on Windows/Linux CI.
- Concurrent-runtime proof: `payments-e602f807` and `payments-9be94187` ran at
  the same time with distinct PostgreSQL databases, networks, volumes, and all
  nine published ports; both web roots returned HTTP 200 and both APIs reported
  `ready`.
- Observability: request-ID lookup in Loki, business metric lookup in
  Prometheus, and correlated checkout trace lookup in Tempo.

The final clean-context autonomy trial is tracked by ANY-116 and remains the
last closure gate for ANY-108; this implementation run cannot represent a
fresh context.

## Ordered Linear workstreams

1. [ANY-109](https://linear.app/paveldik/issue/ANY-109/establish-english-repository-knowledge-hierarchy)
2. [ANY-110](https://linear.app/paveldik/issue/ANY-110/make-legal-baseline-and-generated-contracts-deterministic)
3. [ANY-111](https://linear.app/paveldik/issue/ANY-111/add-cross-platform-isolated-worktree-harness)
4. [ANY-112](https://linear.app/paveldik/issue/ANY-112/reorganize-code-into-enforced-domain-boundaries)
5. [ANY-113](https://linear.app/paveldik/issue/ANY-113/add-structured-observability-and-agent-query-interface)
6. [ANY-114](https://linear.app/paveldik/issue/ANY-114/add-playwright-critical-journeys-and-evidence-capture)
7. [ANY-115](https://linear.app/paveldik/issue/ANY-115/enforce-github-ci-linear-pr-titles-ownership-and-review-evidence)
8. [ANY-116](https://linear.app/paveldik/issue/ANY-116/add-quality-gardening-and-run-clean-context-autonomy-trial)
