# Technical Debt Tracker

| Item | Owner | Status | Notes |
|---|---|---|---|
| Target catalog/subscription/entitlement model | ANY-71 | Planned | Out of scope for ANY-108 |
| Checkout and payment transitions belong in billing | Follow-up after provider boundary | Observed | Two vertical slices in [the DDD-lite audit](../architecture/ddd-lite-audit.md); do not block ANY-165/166/167; not a repository/DTO programme |
| Region Resolver browser client | Planned | Observed | Login/registration contour list; instance knows only the resolver origin; see [the contract](../architecture/region-resolver-contract.md) |
| Contour-aware runtime and generation | Planned | Observed | Enforce server-side instance contour; reject foreign auth regions; remove foreign production seed data; parameterize legal generation/rendering, routes/locales, and provider registration before enabling another contour |
| `eu` / `us` MoR and providers | Product decision | Observed | Seed `paddle` for DE/ES is not an accepted provider choice |
| Platform Kernel runtime and usage integration | External repository | Planned | No implementation in this repository |
| Production email verification | Product backlog | Planned | Current authentication remains demo-oriented |
| Clean-context autonomy trial | ANY-116 | Completed | [PR #9](https://github.com/gushinets/payments-portal/pull/9); final autonomy and overall grade B |
| Worktree and dependency cleanup safety | ANY-123 | Planned | Prevent cleanup from traversing shared dependency junctions |
| Agent heartbeats, timeouts, and resumable checkpoints | ANY-124 | Planned | Remove manual resume needs for long or interrupted commands |
| Trace discovery and browser artifact hygiene | ANY-125 | Planned | Add recent-trace lookup and contain or ignore expected browser diagnostics |
| Deterministic Python dependency locking | ANY-100 | Planned | Owns the unpinned indirect dependency and generated-OpenAPI drift gap |
| PostgreSQL and Alembic test stability | ANY-99 | Completed | [PR #28](https://github.com/gushinets/payments-portal/pull/28); shared fixtures and the canonical migration gate cover the PostgreSQL follow-up |
| npm moderate advisories | Maintenance ticket required | Observed | Review without applying breaking `npm audit fix --force` automatically |
