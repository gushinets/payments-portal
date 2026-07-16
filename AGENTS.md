# Agents Guide

This file is the repository map, not the full manual. Load only the linked
document that applies to the current task.

## Instruction priority

1. Current user request.
2. This file and any narrower `AGENTS.md` in the affected subtree.
3. The authoritative document listed below.
4. Other repository documentation and examples.

## Sources of truth

- [README.md](README.md) — setup and canonical commands.
- [ARCHITECTURE.md](ARCHITECTURE.md) — current boundaries and dependency rules.
- [docs/PRODUCT.md](docs/PRODUCT.md) — current product scope.
- [docs/architecture/payment-portal-data-model.md](docs/architecture/payment-portal-data-model.md)
  — normative Payment Portal data and backend invariants.
- [docs/product/ru-mvp.md](docs/product/ru-mvp.md) — verified RU journey and pages.
- [docs/DESIGN.md](docs/DESIGN.md) — Bundle 3 UI rules.
- [docs/SECURITY.md](docs/SECURITY.md) and
  [docs/RELIABILITY.md](docs/RELIABILITY.md) — operational constraints.
- [docs/engineering/AGENT_WORKFLOW.md](docs/engineering/AGENT_WORKFLOW.md) —
  required delivery and evidence loop.
- [docs/exec-plans](docs/exec-plans/) — active plans, completed plans, and debt.

## Repository map

- `apps/web` — Next.js RU portal. Read `apps/web/AGENTS.md` before UI work.
- `apps/api` — FastAPI service. Read `apps/api/AGENTS.md` before backend work.
- `docs/legal/ru` — versioned Russian legal source. Do not edit without explicit
  legal-content authorization.
- `docs/design-system/bundle3` — canonical web design reference and tokens.
- `scripts/repo.py` — setup, isolation, checks, generation, and observability.

## Log papercuts

When the current task permits repository edits and you encounter actionable,
repository-related workflow friction—a failing tool or command, confusing setup,
flaky check, stale cache, misleading error, missing helper, or non-obvious
gotcha—append one concise entry to [PAPERCUTS.md](PAPERCUTS.md). Create the file
if it does not exist.

Use UTC and this format:

```text
## YYYY-MM-DD HH:MMZ - <model or agent, if known> - <operating system>

<What you were doing> → <what got in the way>. Add a likely cause, workaround,
or proposed fix when useful.
```

Record the entry after recovering or at task handoff so the main task continues.
Before appending, search for a materially equivalent entry and do not add a
duplicate. Never include secrets, tokens, authorization headers, personal data,
or unredacted payment data.

Do not log simple command typos, canceled actions, or one-off external failures
unless they reveal a reusable repository improvement. Use this file only for
minor workflow friction; use Linear or the documented debt process for product
bugs and tracked work.

## Non-negotiable rules

- Keep v1 scoped to the RU CloudPayments MVP.
- Platform Kernel changes belong to `gushinets/anytoolai-platform`.
- ANY-71 owns planned catalog, subscription, entitlement, and access-API work.
- Activate paid access only from a verified webhook, never from a return URL.
- Never collect card data or log secrets, authorization headers, raw tokens, or
  unredacted payment fields.
- Legal pages are drafts; do not present them as legally approved.
- Preserve Bundle 3 for frontend changes.
- Add tests when behavior changes and use PostgreSQL tests for migration logic.
- Engineering artifacts are English. Russian is allowed only in RU legal source
  and customer-facing localization.
- Do not hand-edit generated files; run `npm run generate`.

## Canonical verification

```bash
npm run check:fast
npm run check
```

Use the smallest relevant check during iteration. Before handoff, run the
broadest check supported by the local environment and record any skipped check.

## Pull requests

Every PR title must match `ANY-<number> - <summary>`, for example:

```text
ANY-71 - Implement Payment Portal data model
```

Agents must use an existing Linear ticket, include its URL in the PR body, and
prepare evidence for human merge approval.
