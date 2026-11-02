# ANY-715 verification

Status: final acceptance open; P1-1, P1-2 and ARCH-1 unresolved
Updated: 2026-11-02
Issue: [ANY-715](https://linear.app/paveldik/issue/ANY-715)

This report records coverage, source baselines, open final-review findings and
remaining integration checks. Passing suites do not close the findings below
or establish Step 8 acceptance. The [delivery record](../exec-plans/completed/ANY-715-implementation-plan.md)
owns scope and retained decisions; the [operations guide](ANY-715-billing-operations.md)
owns current commands and operating guarantees.

## Verification sources and scope

Final correctness, architecture and DoD review source:
`b202ad35f5abe2743d8b486359e30f666b5c98b0` on ANY-715, compared with
`main` / merge base `366d902635a699c18b90e0a619f74bb6b0e680c2` (134 changed files).
The earlier delivery checkpoint recorded a successful complete `npm run check`
for runtime source `0edd114c9a3ba30c1de38bd84bab4a8016afba01`. Application runtime
files are unchanged between that checkpoint and the reviewed source.

The final review independently passed the following stages at the reviewed
source, reusing their results across review passes:

- 1,689 fast API tests and 620 PostgreSQL tests.
- 395 frontend component tests and 38 web boundary tests.
- Python/web lint, production build, architecture, documentation and generated
  artifact freshness.

Full `npm run check` attempts in the final-review environment stopped on
inherited Kernel environment settings. After clearing those settings,
`npm run check:fast`, `npm run test:api:postgres` and `npm run build:web` passed
separately. This is stage-by-stage evidence, not a new successful full-command
run. Repository Python was selected through `.venv/bin` in PATH; tests used
`KERNEL_MOCK_ENABLED=0` with empty `KERNEL_BASE_URL` and `KERNEL_SERVICE_TOKEN`.
The web build used the synthetic public origin `https://payments.example.test`.

The checks use disposable PostgreSQL and SIMULATED LBX responses. They exercise
real Portal Application and persistence paths, but do not establish live provider
conformance. No application/production database migration or provider mutation is
part of this verification. Browser E2E was not run on this runtime baseline.

## Open final-review findings

These are confirmed current defects, not deferred Step 9 work. No runtime fix
or permanent regression test was added during the review or this documentation
correction. The important findings prevent a positive merge-readiness conclusion.

- **P1-1 — important, inventory conflict lost on a later timeout.** In
  [customer inventory orchestration](../../apps/api/app/composition/billing_background.py),
  a timely proven conflict is accumulated in memory. A later product exhausting
  the shared read budget exits without applying the accumulated conflict. The
  affected purchase can remain LINKED and its subscription eligible/allowed.
  Required correction: apply timely negative evidence through the existing
  fenced transaction while retaining retry work for incomplete products; do
  not accept late proof or mutate ownership midway through the discovery set.
- **P1-2 — important, payment Widget ignores a newly committed ENDED fact.** The
  [final payment admission](../../apps/api/app/domains/purchases/widget_admission.py)
  checks purchase/operation admission snapshots but not canonical subscription
  lifecycle. If reconciliation commits ENDED after fresh payment proof and
  before final admission, the payment Widget can still be issued. Required
  correction: check terminal canonical state under the final local locks,
  without invalidating healthy repeated reads or the separate account Widget.
  This demonstrates incorrect payment admission, not a paid grant or proven
  financial loss.
- **ARCH-1 — non-blocking, deadline cannot finish after safe hold release.** In
  [local deadline apply](../../apps/api/app/domains/billing/background_recovery.py),
  the hold check precedes operation-state handling. After completed
  PROVEN_NOT_SENT and changed terms safely release the purchase, its deadline
  fails with `purchase_scope_released`, remains running and repeats after lease
  expiry. Required correction: complete the job from verified no-send history
  without requiring a live hold, or finish it atomically with safe release;
  retain the checks needed for review transitions.

Supplemental temporary PostgreSQL diagnostics paired each failing case with a
valid control. P1-1/P1-2 produced two failures and two passing controls; ARCH-1
produced one failure and one passing control on each of two runs. These cases
are outside the checked-in suites, which explains why their green results do
not discharge the findings. The temporary scripts/logs are session evidence,
not durable repository regression coverage.

A separate temporary DoD journey passed through real Portal HTTP advance,
automatic worker polling without browser/webhooks, worker restart, an
effective-term conflict, CLI `inspect`/`reconcile`/`resolve-review`, atomic audit
and idempotent command replay. It preserved purchase history, calendar
precision and six-hour trust and produced no paid-state writes. LBX HTTP
responses were simulated; scheduler due times were advanced locally. It did
not exercise browser rendering, real provider conformance or the repository
CLI wrapper as a subprocess.

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

The covered cases are not a claim that all combinations pass; the open
findings above qualify inventory, payment admission and deadline completion.
The covered reconciliation/recovery scenarios retain purchase/legal history
and applicable holds; safe no-send release keeps its separate Step 7 rule.
Step 8 scenarios assert no primary selection, paid grant, allowance, access
revision or invalidation-outbox production.

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
