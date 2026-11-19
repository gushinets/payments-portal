# ANY-822 — Accelerate test execution

Status: local timing and regression criteria met; final-head CI and human review pending
Issue: [ANY-822](https://linear.app/paveldik/issue/ANY-822)
Branch: `ANY-822`, based on `f6b1f1d2`

## Acceptance criteria

- The complete PostgreSQL partition takes at most **10 minutes**. The canonical
  `npm run check -- --coverage` takes at most **15 minutes**, with browser E2E
  excluded. Measure on the target machine without competing heavy workloads.
  Include collection, database creation and cleanup in test time. Record
  PostgreSQL server startup separately.
- Preserve business assertions, real migrations, independent commits, locks
  and recovery. Document new skips or xfails. Keep assertion strength, timing
  constraints and retry limits intact.
- Existing developer aliases and CI use the accelerated path by default.

## Implementation decisions

- Use the worktree's disposable PostgreSQL 18.4 server with 2 GiB tmpfs and
  normal durability. Worktree-specific credentials protect port reuse. Test commands
  derive settings from the worktree, retaining its saved port offset when
  present. Explicit test-server configuration takes precedence.
- Amortize migrations with an on-demand template per pytest process and a
  fresh clone per ordinary database test. Raw migration tests retain explicit
  schema transitions. pytest cleans up only databases it created.
- Use four PostgreSQL processes by default and a serial API-fast partition.
  Assign whole modules by collected count. The combined API command runs
  PostgreSQL after a fast launch or test failure. Preserve available JUnit and
  diagnostics from failed or interrupted runs. CI sends cancellation signals
  directly to Python for worker and fixture cleanup.
- Collect API-fast and component coverage during their single canonical
  executions. PostgreSQL stays parallel; standalone API coverage stays serial.
- Simplify selected test setups and browser readiness checks. Defer broad
  fixture extraction, parallel check stages and build/environment caching
  until measurements justify the added maintenance.

The [six original acceleration decisions](https://github.com/gushinets/payments-portal/blob/e7d12a24a8193c08ad872e8fcbbe040721b1e101/docs/exec-plans/active/ANY-822-implementation-plan.md#acceleration-candidate-decisions)
record the measured costs and trade-offs. The paid-access entry below supersedes
decision 4 on the bounded reader's fixture. See the
[Testing Strategy](../../engineering/TESTING.md) for current commands, ownership,
reports and coverage scope.

## Retained test guarantees

The [full test audit](https://github.com/gushinets/payments-portal/blob/e7d12a24a8193c08ad872e8fcbbe040721b1e101/docs/exec-plans/active/ANY-822-implementation-plan.md#4-test-audit-decisions-and-retained-guarantees)
records the before/after costs where measured and the cases retained unchanged.

- **Mapping expiry.** Three [PostgreSQL cases](../../../apps/api/tests/test_mapping_publication_expiry_postgres.py)
  exercise expiry before database access, after reading revision history and
  after flushing changes. Each checks that the publisher rejects the change and
  leaves revision history intact. A separate case verifies refusal when the
  deadline passes while the publisher waits for a PostgreSQL advisory lock.
  [Calendar tests](../../../apps/api/tests/test_mapping_billing_calendar.py)
  cover the account-day, policy and price deadline inputs in
  `test_evaluation_carries_exclusive_account_calendar_boundary`.
- **Paid access.** [Paid-read tests](../../../apps/api/tests/test_paid_access_read_postgres.py)
  reuse the purchase/reconciliation fixture for the bounded reader. The HTTP
  test compares the complete grants and allowances with committed state, puts
  the paid product beyond the 100-product display cap and checks for writes.
  This replaces a fixture that manually assembled the same billing rows.
  Its historical in-module saving was 1.45 s for this case. The combined
  reader/expiry sample showed no consistent improvement.
- **Frontend.** [Subscription guard tests](../../../apps/web/tests/components/SubscriptionStateGuard.test.ts)
  own every wording variant. [Portal E2E](../../../apps/web/e2e/portal-ru.spec.ts)
  still applies the guard to the real page. The effect-settled
  [unverified-email case](../../../apps/web/tests/components/any765-paid-access.test.tsx)
  retains both no-request and no-refresh assertions. [Public-route E2E](../../../apps/web/e2e/public-routes.spec.ts)
  still covers desktop/mobile responses, hydration, fonts, accessibility and errors.
- **Committed state.** [Identity/legal](../../../apps/api/tests/test_identity_legal_persistence_postgres.py)
  and [email verification](../../../apps/api/tests/test_email_verification_persistence_postgres.py)
  retain real commits, constraints and races. [Database fixtures](../../../apps/api/tests/compatibility/test_database_fixtures.py),
  [template lifecycle](../../../apps/api/tests/compatibility/test_postgres_template_lifecycle.py)
  and [database safety](../../../apps/api/tests/compatibility/test_postgres_test_database_safety.py)
  cover schema, seed and sequence restoration, migration ordering, unsafe
  targets, collisions and checked-out connections.
- **Worker recovery.** [Inventory scheduling](../../../apps/api/tests/test_billing_inventory_scheduling_postgres.py)
  retains lane, due-time and competing reconciliation assertions with explicit
  queue order. [Customer recovery](../../../apps/api/tests/test_billing_background_recovery_faults_postgres.py)
  retains binding and no-send assertions and rejects unintended Kernel calls.
- **Runner and coverage.** [API runner](../../../apps/api/tests/test_api_test_runner.py)
  and [dispatch tests](../../../apps/api/tests/test_api_test_dispatch.py) cover
  serial/parallel selection, option and collection errors, missing or corrupt
  reports, partial launch, cancellation and combined partition outcomes.
  [Coverage checks](../../../apps/api/tests/test_check_coverage.py) verify
  single execution and report scope.

## Verification

The local refactor on top of `608b696a` passed the complete `check --coverage`
handler on Linux in **859.834 s**. PostgreSQL took **566.218 s** with four
workers on the dedicated PostgreSQL 18.4 tmpfs server, including collection
and database cleanup. All **1,219** PostgreSQL cases passed. Their node IDs
and order match the two earlier full collections on November 19. No scenario
or template databases remained before the disposable server was stopped.

API-fast passed 2,563 cases with one existing native Windows filename case
skipped. All 454 component and 38 web boundary tests passed, including
typecheck. The web production build passed. Comparing pytest collection from
the published PR and the working tree gave 3,795 and 3,783 cases respectively.
All changed node IDs belong to launcher, settings or repository tooling tests.
The bounded paid-reader HTTP case passed in 1.885 s using the shared fixture.

The check used this worktree's source, an existing Python 3.12 environment
from a sibling worktree matching the API lock, and cached Manrope files served
on loopback. Browser E2E was excluded per the timing criteria. The final log
and timings are in `.harness/any822-final-check-_3mwaeyw/` and the merged
PostgreSQL report is in
`.harness/api-tests/api-postgres-3d4cdf6c11574854beb86aeb9f669c21/`.
Native Windows launcher behavior and upload on actual CI cancellation were
not exercised locally. See [PR checks](https://github.com/gushinets/payments-portal/pull/170/checks)
for the published revision.

### Prior evidence

- At `e7d12a24`, `npm run test:api:postgres` passed 1,219 cases with four
  workers on PostgreSQL 18.4. Local Bash probes covered SIGINT and SIGTERM
  cleanup. The browser selection on `8de0f4ba` passed 54 desktop/mobile cases.
- Source based on `5062d7fb` passed `npm run check -- --coverage` in
  **850.734 s**, with **2.976 s** for server startup measured separately.
  See `.harness/any822-p1-p3-20261117/check-result.json`.
  At `12b15287`, the complete PostgreSQL partition took **597.834 s**.
- The 24-case Linux control measured **146.553 / 73.228 / 56.941 s** serial on
  ext4 at `2d278f62` and **13.334 / 13.373 / 13.243 s** on tmpfs with migrated
  templates and two active workers on source based on `8496803c`. Both paths
  used the same inputs, tool versions and normal durability. Each excluded a
  warm-up and passed all cases. The baseline spread limits the comparison.
  The control IDs, machine/load and cache conditions, phase timings and
  checkpoint records are in the previous plan at `e7d12a24` and
  `.harness/any822-step1-20261113/`, `.harness/any822-step9-20261113/`.
