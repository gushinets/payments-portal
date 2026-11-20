# ANY-822 — Accelerate test execution

Issue: [ANY-822](https://linear.app/paveldik/issue/ANY-822)

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
- A post-change measurement of the CI critical path is sufficient for CI timing
  acceptance. Report it separately from the local benchmarks.

## Implementation decisions

- First isolate API test settings before application imports. Use synthetic
  settings and a shared environment helper for pytest and CLI test children.
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
  diagnostics from failed or interrupted runs, including skips and errors from
  collection. Apply bounded fixture cleanup when the nested lifecycle test
  times out. CI sends cancellation signals directly to Python for worker and
  fixture cleanup.
- Collect API-fast and component coverage during their single canonical
  executions. PostgreSQL stays parallel; standalone API coverage stays serial.
- Simplify selected test setups and browser readiness checks. Defer broad
  fixture extraction, parallel check stages and build/environment caching
  until measurements justify the added maintenance.

See the [original implementation sequence](https://github.com/gushinets/payments-portal/blob/e7d12a24a8193c08ad872e8fcbbe040721b1e101/docs/exec-plans/active/ANY-822-implementation-plan.md#3-completed-implementation)
for the ordered steps and their scope. In the runner step, pytest may reorder
cases during worker collection. The runner uses the worker's actual collection
order to validate the executed prefix when `-x` stops a worker. The
[six original acceleration decisions](https://github.com/gushinets/payments-portal/blob/e7d12a24a8193c08ad872e8fcbbe040721b1e101/docs/exec-plans/active/ANY-822-implementation-plan.md#acceleration-candidate-decisions)
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
  Direct row assembly offered no consistent gain for the combined reader and
  expiry scenarios, so the bounded reader retains the shared writer setup.
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

- Compare the same [24 PostgreSQL control cases](https://github.com/gushinets/payments-portal/blob/e7d12a24a8193c08ad872e8fcbbe040721b1e101/docs/exec-plans/active/ANY-822-implementation-plan.md#L234)
  on the original and accelerated local paths. Keep inputs, tool versions and
  durability settings equivalent. Exclude a warm-up, repeat measurements and
  record spread, machine load, storage and active process count.
- Check the full local timing targets with the dedicated tmpfs server and
  `npm run check -- --coverage`. Verify the PostgreSQL test count and cleanup
  of scenario and template databases.
- Check the retained regressions, including migration cycles, worker isolation,
  coverage artifacts and desktop/mobile browser checks.

Record tested revisions, outcomes, timings and limitations in the
[PR](https://github.com/gushinets/payments-portal/pull/170), following the
[Testing Strategy](../../engineering/TESTING.md#verification-and-evidence).
