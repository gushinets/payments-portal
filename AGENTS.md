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
- [docs/architecture/contours.md](docs/architecture/contours.md) — contour
  isolation and country membership.
- [docs/architecture/region-resolver-contract.md](docs/architecture/region-resolver-contract.md)
  — planned Region Resolver consumer rules.
- [docs/architecture/payment-providers.md](docs/architecture/payment-providers.md)
  — provider-neutral billing and adapters.
- [docs/architecture/payment-portal-data-model.md](docs/architecture/payment-portal-data-model.md)
  — normative Payment Portal data and backend invariants.
- [docs/product/ru-mvp.md](docs/product/ru-mvp.md) — implemented `ru` journey
  and pages.
- [docs/DESIGN.md](docs/DESIGN.md) — Bundle 3 UI rules.
- [docs/SECURITY.md](docs/SECURITY.md) and
  [docs/RELIABILITY.md](docs/RELIABILITY.md) — operational constraints.
- [docs/engineering/AGENT_WORKFLOW.md](docs/engineering/AGENT_WORKFLOW.md) —
  required delivery and evidence loop.
- [docs/exec-plans](docs/exec-plans/) — active plans, completed plans, and debt.

## Repository map

- `apps/web` — Next.js Payment Portal UI. Current routes are the `ru` contour.
  Read `apps/web/AGENTS.md` before UI work.
- `apps/api` — FastAPI service. Read `apps/api/AGENTS.md` before backend work.
- `docs/legal/<contour>` — versioned customer-facing legal source. The only
  existing tree is `docs/legal/ru`. Do not edit without explicit legal-content
  authorization.
- `docs/design-system/bundle3` — canonical web design reference and tokens.
- `scripts/repo.py` — setup, isolation, checks, generation, and observability.

## Non-negotiable rules

- The implemented product surface remains the `ru` contour until a ticket
  enables another contour. Do not ship `eu` or `us` product surface without
  that ticket.
- Domain architecture is multi-contour. Do not document or encode CloudPayments
  or `ru` as the only possible provider or contour in billing design.
- A production instance serves one contour. It must not persist other contours'
  base URLs, users, or legal records, and must not call another contour's API.
- Region Resolver is a separate repository. This portal may know only that
  resolver origin, as a planned client. Do not implement the resolver here.
- Platform Kernel changes belong to `gushinets/anytoolai-platform`.
- ANY-71 owns planned catalog, subscription, entitlement, and access-API work.
- Activate paid access only from a verified webhook, never from a return URL.
- Never collect card data or log secrets, authorization headers, raw tokens, or
  unredacted payment fields.
- Legal pages are drafts; do not present them as legally approved.
- Preserve Bundle 3 for frontend changes.
- Add tests when behavior changes and use PostgreSQL tests for migration logic.
- Engineering artifacts are English. Customer legal source lives under
  `docs/legal/<contour>/`. Customer-facing UI uses that contour's locale.
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
