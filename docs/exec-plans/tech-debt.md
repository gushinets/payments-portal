# Technical Debt Tracker

| Item | Owner | Status | Notes |
|---|---|---|---|
| Target catalog/subscription/entitlement model | ANY-71 | Planned | Out of scope for ANY-108 |
| Platform Kernel runtime and usage integration | External repository | Planned | No implementation in this repository |
| Production email verification | Product backlog | Planned | Current authentication remains demo-oriented |
| Clean-context autonomy trial | ANY-116 | Completed | [PR #9](https://github.com/gushinets/payments-portal/pull/9); final autonomy and overall grade B |
| Worktree and dependency cleanup safety | ANY-123 | Planned | Prevent cleanup from traversing shared dependency junctions |
| Agent heartbeats, timeouts, and resumable checkpoints | ANY-124 | Planned | Remove manual resume needs for long or interrupted commands |
| Trace discovery and browser artifact hygiene | ANY-125 | Planned | Add recent-trace lookup and contain or ignore expected browser diagnostics |
| Deterministic Python dependency locking | ANY-100 | Planned | Owns the unpinned indirect dependency and generated-OpenAPI drift gap |
| PostgreSQL and Alembic test stability | ANY-99 | Planned | Owns integration timing and hung migration-test follow-up |
| npm moderate advisories | Maintenance ticket required | Observed | Review without applying breaking `npm audit fix --force` automatically |
