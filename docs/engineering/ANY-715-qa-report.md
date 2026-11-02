# ANY-715 verification

Status: local automated verification complete; real integration acceptance open
Updated: 2026-11-02
Issue: [ANY-715](https://linear.app/paveldik/issue/ANY-715)

This report records coverage, the verified runtime baseline and remaining
integration checks. The [delivery record](../exec-plans/completed/ANY-715-implementation-plan.md)
owns scope and retained decisions; the [operations guide](ANY-715-billing-operations.md)
owns current commands and operating guarantees.

## Verified runtime baseline

Runtime source: `0edd114c9a3ba30c1de38bd84bab4a8016afba01` on ANY-715.
The complete `npm run check` completed successfully on the corresponding
application/test source on 2026-11-02:

- 1,689 fast API tests and 620 PostgreSQL tests.
- 395 frontend component tests and 38 web boundary tests.
- Python/web lint, production build, architecture, documentation and generated
  artifact freshness.

The checks use disposable PostgreSQL and SIMULATED LBX responses. They exercise
real Portal Application and persistence paths, but do not establish live provider
conformance. No application/production database migration or provider mutation is
part of this verification. Browser E2E was not run on this runtime baseline.

## Covered behavior

- **Subscription facts and trust:** waiting, active, next-period calendar facts,
  financial/administrative blocks, ended and refused terminal revival; original
  effective terms versus changed catalog prices; complete/mismatch/incomplete
  proof; finite trust and provider-free expiry. See
  [reconciliation coverage](../../apps/api/tests/test_billing_subscription_reconciliation_postgres.py).
- **Durable execution:** automatic enrollment/backfill, restart, competing
  consumers, stale results, later hints, retained cleanup capacity and local
  deadline progress during provider slowness. See
  [worker coverage](../../apps/api/tests/test_billing_worker_postgres.py).
- **Recovery and inventory:** zero/unique/ambiguous candidates, delayed visibility,
  fixed active recovery windows, no background CREATE, local contention and
  scoped conflicts. See [recovery coverage](../../apps/api/tests/test_billing_background_recovery_postgres.py)
  and [fault scenarios](../../apps/api/tests/test_billing_background_recovery_faults_postgres.py).
- **Isolation:** separate product facts, trust and jobs for proposal_ai and
  brief_decoder under the same customer/tariff; proven retained account scope
  across credential rotation. See [product isolation](../../apps/api/tests/test_billing_qa_isolation_postgres.py)
  and [retained-scope coverage](../../apps/api/tests/test_billing_retained_scope_postgres.py).
- **Webhook hints:** disabled/authentication/body/privacy rules, all six events,
  durable receipt before acknowledgement, ignored foreign correlation, covered
  generations, restart and polling-only convergence. See
  [receiver coverage](../../apps/api/tests/test_billing_webhook.py) and
  [durable processing](../../apps/api/tests/test_billing_webhook_postgres.py).
- **Operator controls:** read-only inspection, shared GET-only rechecks, both
  audited resolutions, stale/ambiguous proof refusals, replay and atomic audit.
  See [operator coverage](../../apps/api/tests/test_billing_recovery_cli_postgres.py)
  and [review resolutions](../../apps/api/tests/test_billing_recovery_cli_review_postgres.py).
- **Operational contracts:** documented CLI arguments, settings/defaults,
  deployment forwarding, webhook route/events and redacted health/metrics;
  populated worker migration from `20261029_0003` to `20261028_0005`.

The exercised Step 8 scenarios retain purchase/legal history and holds and
assert no primary selection, paid grant, allowance, access revision or
invalidation-outbox production.

## Remaining integration checks

- **Configured test-LBX reconciliation: NOT_RUN.** Configure the authorized test
  connection and reconcile an existing owned subscription through the runbook's
  bounded read-only path. No new purchase/payment is needed.
- **Real webhook enablement: NOT_RUN.** Keep DISABLED/POLLING-ONLY until actual
  authentication, correlation, event-to-GET visibility and restart/polling
  convergence pass the [enablement checklist](ANY-715-billing-operations.md#real-enablement-checklist-and-rollback).
- **Current-baseline browser E2E and application/production migration: NOT_RUN.**
- **Paid access, natural provider renewal, Kernel enforcement and launch:** owned
  by later ANY-504 steps. Simulated lifecycle changes do not establish them.

## Reproduction

Use the repository environment and [canonical commands](../../README.md#api-development-workflow).
For complete local automated verification:

```bash
make test_db_up
npm run check
make test_db_stop
```

The test fixtures own the disposable database lifecycle. Browser acceptance needs
RUN_E2E=true and a running harness stack. Real LBX/webhook checks use their own
configured integration environment and remain separate from simulated tests.
