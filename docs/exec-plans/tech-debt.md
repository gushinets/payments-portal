# Technical Debt Tracker

Rows describe repository gaps and retained evidence, not freshly synchronized
Linear issue states. Current billing ownership follows
[ADR 0005](../architecture/decisions/0005-external-billing-boundary.md).

| Item | Owner | Status | Notes |
|---|---|---|---|
| Region Resolver browser client | Planned | Observed | Login/registration contour list; instance knows only the resolver origin; see [the contract](../architecture/region-resolver-contract.md) |
| Contour enablement beyond `ru` | Dedicated enablement ticket | Deferred | Current auth/seed scope is enforced; another contour needs its own legal source/generation, country membership and external-billing/deployment acceptance; see [contours](../architecture/contours.md) |
| Platform Kernel paid HTTP and usage integration | ANY-766 / separate Kernel repository | Local scope complete; PR review pending | Delegation V2, snapshot V3, coherent paid admission, recipient delivery, browser launch and usage/exhaustion/cabinet reads are implemented. Steps 16/17 supply focused local acceptance and build/install preparation; full and remote/live acceptance belong to ANY-767. See [the integration map](../integrations/platform-kernel.md) |
| Production email delivery acceptance | Deployment operators | Gate | Email-verification and password-reset flows are implemented; production SMTP must be configured and smoke-tested |
| Clean-context autonomy trial | ANY-116 | Completed | [PR #9](https://github.com/gushinets/payments-portal/pull/9); final autonomy and overall grade B |
| Worktree and dependency cleanup safety | ANY-123 | Planned | Prevent cleanup from traversing shared dependency junctions |
| Agent heartbeats, timeouts, and resumable checkpoints | ANY-124 | Planned | Remove manual resume needs for long or interrupted commands |
| Trace discovery and browser artifact hygiene | ANY-125 | Planned | Add recent-trace lookup and contain or ignore expected browser diagnostics |
| PostgreSQL and Alembic test stability | ANY-99 | Completed | [PR #28](https://github.com/gushinets/payments-portal/pull/28); shared fixtures and the canonical migration gate cover the PostgreSQL follow-up |
| npm dependency advisories | Maintenance ticket required | Recheck before remediation | Use a fresh audit to establish the current set; do not apply breaking `npm audit fix --force` automatically |
