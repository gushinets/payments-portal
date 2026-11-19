# ANY-822 — Rebuild test execution acceleration from main

Status: implementation complete; local verification and CI scope recorded below
Created: 2026-11-13
Issue: [ANY-822](https://linear.app/paveldik/issue/ANY-822)
Execution branch: `ANY-822`
Original base: `2d278f62f0a2f7c4b40fb322618b268580de2301`
Rebased on main: `f6b1f1d2415763baa6b4a22b0bbe8b2e874c279d` (ANY-741/864, 2026-11-19)

## 1. Current acceptance (2026-11-19)

The full local result below covers source based on
`5062d7fb5c78990a20ea926356ccdb64337af3b2`, before the later rebases and
dependency updates.

- **CI before the latest rebase:** [run 44214225942](https://github.com/gushinets/payments-portal/actions/runs/44214225942)
  passed for pushed head `aac8876907fbc2b2f96915c8bd61c8b6d3ea7998`,
  tested as merge ref `26f99ae661c59ec64d4ce1b6db3b4dbc9c930885` on
  base `aa9d8f996cba91feaaaad6a9937eef0c590ae4fa`. Verification on the
  current base is tracked in the [PR checks](https://github.com/gushinets/payments-portal/pull/170/checks).

- **PASSED locally before the latest rebase:** `npm run check -- --coverage`, **850.734 s**:
  **2,417 API-fast**, **1,212 PostgreSQL**, **454 components**, static checks
  and web build; no test skips or failures. PostgreSQL used four workers,
  isolated tmpfs storage and normal durability. Server startup was **2.976 s**,
  excluded from the check; builds used cached local Manrope fonts. Owned test
  databases and the disposable container were cleaned up.
- **PASSED on previous base `2e6d3adc`:** 467 focused infrastructure/smoke tests, offline
  lock validation and documentation checks. The local environment retains
  older dependency versions; CI verifies the new pins.
- **Earlier CI:** [run 44085844288](https://github.com/gushinets/payments-portal/actions/runs/44085844288)
  passed for `378af431f22fb9090105a8ed18c84aa4dda8b292`; it does not cover
  subsequent changes.
- **PASSED in baseline CI:** [run 43855533270](https://github.com/gushinets/payments-portal/actions/runs/43855533270)
  for commit `5062d7fb5c78990a20ea926356ccdb64337af3b2`, tested as merge
  ref `d095e5395d77a9020ef7e4888628448301a4fd5b`. Quality, production gate,
  browser and Linux/Windows harness-smoke jobs passed. Windows evidence covers
  harness smoke only. This run does not cover the latest test-infrastructure changes.
- **UNVERIFIED:** actual CI cancellation and diagnostic upload on cancellation,
  the complete Windows API runner,
  full paired/live acceptance and complete serial API coverage. Browser
  evidence is from CI, not the latest local check.

Recorded local logs, source fingerprints and cleanup results:
`.harness/any822-p1-p3-20261117/` and the recorded `.harness/api-tests/` run.
Post-rebase checks: `.harness/any822-rebase-20261117-58bbaa56/`.
Earlier measurements below describe historical source states. Current execution
instructions belong to the [Testing Strategy](../../engineering/TESTING.md).

### Local review follow-up on `8de0f4ba`

The working tree validates explicit PostgreSQL ports, verifies the worktree
Compose endpoint, defers interruption until worker registration, delivers CI
cancellation signals directly to Python, and builds migrated templates on
demand. The local Bash probe handled SIGINT and SIGTERM with fixture cleanup and
exit 130. A Compose smoke test accepted the dedicated server and rejected an
unrelated listener.

All 1,219 PostgreSQL cases passed on the disposable server. The focused
tooling suite passed 521 cases. `check:fast` passed static and web checks,
including 454 components, and reported 2,554 API-fast passes, one platform
skip, and five failures with local dnspython and OpenTelemetry versions below
the lockfile pins. Remote cancellation and coverage timing remain unverified
for these changes.

## 2. Objective, scope and decisions

Reduce complete feedback time while preserving business assertions, PostgreSQL
migrations, independent commits, locking and recovery. Owner-selected targets
on the current machine, without competing heavy workloads:

- Complete PostgreSQL partition: **at most 10 minutes**.
- Complete canonical `check`, including coverage and excluding browsers:
  **at most 15 minutes**.
- No unexplained new skips/xfails, weaker assertions, increased deadlines or
  retries introduced to obtain a passing result.
- Existing developer aliases and CI use the accelerated path by default.

The change owns test infrastructure, bounded test improvements and guidance;
it does not change commercial or paid-access behavior. During the initial
rebuild only the ANY-766 infrastructure slice was in scope. The later rebase
retains the business changes already merged into main.

The former branch `822-OLD` at `1201e29aa837d0446dd8440139c250536935df66`
and its separately verified stash were preserved during preparation. Its
unfinished xdist/double-reset design is historical research, not the baseline.
Broad fixture extraction did not improve that sample and was not repeated.
No new scheduler dependency, business-state cache or fixture framework was added.

Follow [root AGENTS](../../../AGENTS.md), [documentation AGENTS](../../AGENTS.md),
[Agent Workflow](../../engineering/AGENT_WORKFLOW.md) and
[Coding Conventions](../../engineering/CODING_CONVENTIONS.md), including the
API/web subtree instructions and the owner's explicit-authorization rules.

### Acceleration candidate decisions

Costs below use the historical samples in Sections 5–6 and Step 7 evidence;
combined changes and single runs do not establish isolated speedup factors.

1. **Coverage — select:** run API-fast/components once, retaining scope and
   artifacts. Duplicate-suite time was not isolated; baseline fast check:
   134.121 s. Low effort/maintenance; guard against omitted checks with
   [coverage contracts](../../../apps/api/tests/test_check_coverage.py).
2. **PostgreSQL setup — select templates:** amortize the baseline's
   43.610–107.437 s setup per 24-case run. Medium effort/maintenance, one lifecycle
   owner. Shared rollback cannot isolate independent commits; selective cleanup
   must track seeds/schema/sequences. Test stale state, leaks and ownership.
3. **PostgreSQL parallelism — select four processes:** overlap the dominant
   partition (1,003 cases: serial 25m24s; parallel 418.608 s). Medium effort/
   maintenance for module assignment and reporting. Isolate worker databases,
   verify one/four-worker equivalence and cleanup, and require RAM headroom.
4. **Billing setup — select one reader fixture; defer broad extraction:** avoid
   unrelated purchase setup while retaining real persisted state and HTTP.
   Low local effort/maintenance; broad extraction risks hiding stage interactions.
   Combined reader/expiry sample: 33.580 / 28.317 / 33.396 s; no stable saving.
5. **Concurrent verification stages — defer:** targets were met by addressing
   PostgreSQL and duplication; incremental benefit is unmeasured. Baseline fast
   check: 134.121 s, versus serial PostgreSQL 25m24s. Medium/high scheduling and
   maintenance cost; generation ordering, shared outputs and CPU/RAM contention
   outweigh an unproven gain. Keep existing independent CI jobs.
6. **Frontend/browser — select focused level/readiness fixes; defer environment
   and build caching:** remove unnecessary contexts and background-network waits.
   Post-change: 54 browser cases in 88.599 s, separate build 25.901 s; individual
   setup/before timings unavailable. Low effort/maintenance for existing helpers;
   caching adds unmeasured benefit and invalidation risk. Preserve real rendered,
   hydrated, font-ready and accessible page assertions.

## 3. Completed implementation

- [x] **Settings:** safe configuration before application imports; no personal
  dotenv in tests; shared child-process environment and explicit scenario
  overrides. Preserve URL / complete `POSTGRES_*_TEST` / worktree precedence,
  reject partial inputs and retain normal application dotenv behavior.
  Include ANY-766 `BACKEND_*` settings in isolation.
- [x] **Server:** separate worktree Compose project and loopback test port;
  pinned PostgreSQL 18.4 image, 2 GiB tmpfs and normal durability. Preserve the
  development volume and explicit test-server support. `test-db up` never pulls;
  `test-db stop` removes this disposable server. Document RAM and stale-runtime
  guidance in the Testing Strategy.
- [x] **Database ownership:** one migrated schema/seed template per process,
  fresh scenario clones and function-scoped business setup. Preserve explicit
  migration transitions and fresh state afterwards. Validate before destructive
  operations; track creation, preserve collisions, dispose pools and reject
  checked-out/external connection leaks. No pre-drop, FORCE or foreign-run sweep.
- [x] **Runner:** stdlib subprocesses, four PostgreSQL workers by default,
  serial fast API and `--workers 1–4` diagnosis. Balance whole modules by case
  count, preserving case order. Run both API partitions even after fast failure.
  Validate selectors, collections, manifests, JUnit and exit status; retain real
  failures/skips and available reports after partial launch or interruption.
  Invalidate old caller JUnit before startup checks. Stop/join children with
  graceful cleanup before escalation; handled interruptions return 130.
- [x] **Coverage/CI:** API-fast and components run once with `check --coverage`;
  PostgreSQL remains parallel and uninstrumented. Standalone `coverage api`
  and `coverage api-fast` remain serial with their original scopes. CI uses
  the accelerated path, preserves coverage artifacts and uploads available
  runner diagnostics on failure/cancellation; Docker logs remain failure-only.
- [x] **Documentation:** Testing Strategy is the detailed authority. README,
  Development, AGENTS and Agent Workflow link it and agree on commands,
  ownership, test levels, clocks/readiness and evidence reuse.

## 4. Test audit decisions and retained guarantees

The bounded candidates below cover expensive, overlapping and unstable tests,
including retained controls. Step 7 evidence is in
`.harness/any822-step7-20261113/` (before/after/final JUnit and browser reports).
JUnit times include setup/call/teardown; separate setup cost is unavailable
unless stated. Missing timings are not claimed as savings.

- **Consolidate — expiry matrix:** nine PostgreSQL cases (6.621 s) become three
  (3.203 s; final 4.980 s). [Expiry tests](../../../apps/api/tests/test_mapping_publication_expiry_postgres.py)
  retain publication-stage refusal, rollback/history and the real lock wait.
  [Calendar tests](../../../apps/api/tests/test_mapping_billing_calendar.py)
  retain all deadline sources in `test_evaluation_carries_exclusive_account_calendar_boundary`.
  Two explicit owners avoid repeating setup without losing source/wiring coverage.
- **Accelerate — bounded paid reader:** use local typed, FK-valid persisted
  state; retain PostgreSQL/HTTP, the 100-product cap, complete grants/allowances
  and no-write snapshots in [paid-read tests](../../../apps/api/tests/test_paid_access_read_postgres.py).
  Case time: 1.833 → 0.380 s in-module; 1.945 s isolated. Fixture/provenance drift
  is the maintenance risk; keep technical terms and the beyond-cap paid product.
- **Retain — other paid-read journeys:** full purchase/reconciliation setup
  protects stage interactions, committed authority and saturation behavior in
  [paid-read tests](../../../apps/api/tests/test_paid_access_read_postgres.py).
  Keep PostgreSQL/HTTP and function-scoped data; broad extraction has no measured
  benefit and would hide distinct interaction failures.
- **Move — subscription wording:** every regex input remains in
  [SubscriptionStateGuard.test.ts](../../../apps/web/tests/components/SubscriptionStateGuard.test.ts).
  [Portal browser tests](../../../apps/web/e2e/portal-ru.spec.ts) retain real page
  assertions using the same helper. Pure strings need no browser; one predicate
  owner prevents divergence and duplicate maintenance.
- **Remove — synchronous unverified-email duplicate:** it added no failure mode
  beyond [the effect-settled component test](../../../apps/web/tests/components/any765-paid-access.test.tsx),
  which retains both no-request and no-refresh assertions. Keep component level;
  waiting for effects prevents the earlier weak assertion from passing too soon.
- **Rewrite — public-route waits:** [browser tests](../../../apps/web/e2e/public-routes.spec.ts)
  retain desktop/mobile responses, hydration, fonts, accessibility and error
  assertions. Relevant readiness conditions replace `networkidle`; checking
  too early remains the risk. Cost is the 54-case sample above, with no before
  comparison; explicit conditions own readiness rather than network activity.
- **Retain — committed-state/migration controls:** the frozen 24-case control
  spent 53.665 s in setup in its median baseline run. Keep real commits,
  constraints and races in [identity/legal](../../../apps/api/tests/test_identity_legal_persistence_postgres.py)
  and [email verification](../../../apps/api/tests/test_email_verification_persistence_postgres.py).
  [Template lifecycle](../../../apps/api/tests/compatibility/test_postgres_template_lifecycle.py)
  and [database fixtures](../../../apps/api/tests/compatibility/test_database_fixtures.py)
  retain schema/seed/sequence restoration, mixed migration order and leak checks.
  Shared lifecycle ownership reduces setup; rollback/mocks would lose these guarantees.
- **Rewrite — unstable worker setup:** [inventory scheduling](../../../apps/api/tests/test_billing_inventory_scheduling_postgres.py)
  establishes queue order; [customer recovery](../../../apps/api/tests/test_billing_background_recovery_faults_postgres.py)
  rejects unintended Kernel calls. Keep real PostgreSQL worker effects, lane/
  due-time, competing reconciliation, binding and no-send assertions. Failure
  frequency/setup cost were not isolated; repair local setup instead of deleting
  valuable tests or relaxing deadlines/retries.

Infrastructure compatibility owners remain:

- **ANY-766 DB safety:** unique names/routing and unsafe-template rejection
  remain in database-safety tests; real template-lifecycle tests reject
  checked-out connections. ANY-766 database-fixture tests retain committed
  DDL, seed and sequence isolation.
- **ANY-766 runner:** module balancing, serial/parallel outcomes, collection
  failure, option validation and cancellation cleanup remain in API runner
  regressions, including zero-exit/no-report crashes. Adapted tiny-subprocess
  dispatch tests preserve fast-before-PostgreSQL execution and combined
  success/failure reports. Stale success after collection interruption is
  intentionally replaced by the current incomplete/error status.

Focused checks cover one/four-worker equivalence, real migration/ordinary test
ordering across processes, seeds, unsafe targets, collisions, cleanup failures,
report corruption, partial launch, cancellation and single-pass coverage.
Real timeout, cancellation and lock-wait tests retain elapsed-time mechanisms.
Shared fixtures own resources; factories own data shapes; no unrelated helper
migration or test-framework refactor was required.

## 5. Frozen before/after measurement (2026-11-13)

This controlled sample predates the ANY-766 rebase. It compares infrastructure,
not the current full-suite runtime. The same 24 identity/legal/verification
cases, inputs and installed tool versions were retained, with one excluded
warm-up and three measured runs per side. Exact historical IDs originated in
`793118f:docs/exec-plans/active/ANY-822-step4-verification.json`, under
`ordinary_measurements.baseline.case_ids`.

The ordered, newline-terminated UTF-8 control list has SHA-256
`71eb278348978f6721ab01cfaf43117f0331c8d6f376d533b800486a61039f65`:

```text
apps/api/tests/test_email_verification_persistence_postgres.py::test_confirm_and_resend_race_serializes_on_user_lock
apps/api/tests/test_email_verification_persistence_postgres.py::test_verification_persistence_reads_and_claims_only_exact_scoped_valid_token
apps/api/tests/test_identity_legal_persistence_postgres.py::test_auth_session_scope_must_match_canonical_user
apps/api/tests/test_identity_legal_persistence_postgres.py::test_canonical_user_delete_is_restricted_by_auth_session
apps/api/tests/test_identity_legal_persistence_postgres.py::test_concurrent_duplicate_registration_keeps_one_complete_result
apps/api/tests/test_identity_legal_persistence_postgres.py::test_document_acceptance_rows_are_append_only
apps/api/tests/test_identity_legal_persistence_postgres.py::test_document_acceptance_scope_must_match_document_version
apps/api/tests/test_identity_legal_persistence_postgres.py::test_document_acceptance_scope_must_match_event_user
apps/api/tests/test_identity_legal_persistence_postgres.py::test_document_version_material_is_immutable_but_active_selection_may_change
apps/api/tests/test_identity_legal_persistence_postgres.py::test_document_version_scope_must_match_legal_entity
apps/api/tests/test_identity_legal_persistence_postgres.py::test_foreign_password_reset_token_is_not_claimed_or_mutated
apps/api/tests/test_identity_legal_persistence_postgres.py::test_known_reset_token_scope_must_match_canonical_user
apps/api/tests/test_identity_legal_persistence_postgres.py::test_legal_acceptance_event_accepts_a_complete_commercial_triplet
apps/api/tests/test_identity_legal_persistence_postgres.py::test_legal_acceptance_event_audit_metadata_may_only_be_cleared
apps/api/tests/test_identity_legal_persistence_postgres.py::test_legal_acceptance_event_commercial_triplet_is_all_or_none_and_nonempty[billing-account--fingerprint]
apps/api/tests/test_identity_legal_persistence_postgres.py::test_legal_acceptance_event_commercial_triplet_is_all_or_none_and_nonempty[billing-account-None-None]
apps/api/tests/test_identity_legal_persistence_postgres.py::test_legal_acceptance_event_commercial_triplet_is_all_or_none_and_nonempty[billing-account-offer-   ]
apps/api/tests/test_identity_legal_persistence_postgres.py::test_legal_acceptance_event_core_evidence_cannot_be_updated_or_deleted
apps/api/tests/test_identity_legal_persistence_postgres.py::test_legal_event_scope_must_match_canonical_user
apps/api/tests/test_identity_legal_persistence_postgres.py::test_normal_logout_deletes_only_the_selected_session
apps/api/tests/test_identity_legal_persistence_postgres.py::test_password_reset_binds_canonical_user_and_revokes_security_state
apps/api/tests/test_identity_legal_persistence_postgres.py::test_registration_failure_rolls_back_identity_session_and_legal_evidence
apps/api/tests/test_identity_legal_persistence_postgres.py::test_registration_persists_canonical_identity_hashed_session_and_legal_event
apps/api/tests/test_identity_legal_persistence_postgres.py::test_unknown_email_password_reset_uses_hashed_decoy_without_user_binding
```

- **Original serial/disk path:** warm-up **139.834 s**; measured
  **146.553 / 73.228 / 56.941 s**; median **73.228 s**;
  range **56.941–146.553 s**, relative range **122.37%**.
  Setup/call/teardown totals: **107.437/36.763/0.309**,
  **53.665/16.841/0.224**, **43.610/10.587/0.599 s**.
  Server startup **28.524 s**, separately.
- **Accelerated tmpfs/template path:** warm-up **13.188 s**; measured
  **13.334 / 13.373 / 13.243 s**; median **13.334 s**. Four workers were
  configured; these two modules used **two actual workers**.
- Each invocation retained the exact control collection and **24 passed**,
  complete JUnit, no skips/xfails and verified owned-resource cleanup. Timing
  includes collection, database setup, tests and fixture/report teardown;
  server startup and post-run probes are separate. No full before/after suite
  measurement was required; current absolute targets are assessed in Section 1.

Baseline host: Linux `6.8.0-138-generic`, Xeon E5-2660 v4 (14 cores/28 logical
CPUs), 31.24 GiB RAM. Python `3.12.13`, pytest `9.1.1`, Alembic `1.18.5`,
SQLAlchemy `2.0.51`, psycopg `3.3.4`, pytest-cov `7.1.0`, Node `24.14.0`,
npm `11.11.1`, uv `0.12.7`; installed xdist `3.8.0` was unused. PostgreSQL
18.4 used the repository pin with normal durability; baseline storage was a
new disk-backed ext4 Docker volume (87% used), final storage a 2 GiB tmpfs.
No dependencies were installed/updated. Synthetic settings and owned routing
isolated both measurements from personal or external data.
Baseline Pydantic dotenv loading still existed; explicit synthetic fields
shadowed consumed values. Step 2 subsequently disabled that test source.

The original baseline was noisy: host load **7.78–12.90**, available RAM
**12.89–14.32 GiB**, effectively no swap; no competing heavy check was launched
by this task. Preserve the spread and storage/process differences; these
samples do not establish a stable speedup factor.

Exact commands, frozen environment/tool inventory, source fingerprints, phase
outcomes, manifests, JUnit and server logs:
`.harness/any822-step1-20261113/` and `.harness/any822-step9-20261113/`.

## 6. Historical implementation checkpoints

These dated passes describe their own source states, not the current branch.
Full step-by-step details remain in Git at `12b15287` and in the evidence paths.

- **Step 1:** original collection **2,866 = 1,871 fast + 995 PostgreSQL**;
  `check:fast` **134.121 s**, 414 components; separate typecheck/docs passed.
- **Step 2:** `check:fast` **129.235 s**, 1,886 fast + 414 components;
  26 PostgreSQL/CLI and 15 new isolation regressions passed.
- **Step 3:** `check:fast` **146.716 s**, 1,892 fast + 414 components;
  28 settings/server and 29 PostgreSQL/CLI cases; real server isolation,
  restart and cleanup passed.
- **Step 4:** `check:fast` **229.539 s**, 1,908 fast + 414 components;
  full serial PostgreSQL **1,003 tests, 25m24s**, 62 final focused tests passed.
  The full check stopped at unavailable build fonts at that checkpoint.
- **Step 5:** `check:fast` **134.075 s**, 1,941 fast + 414 components;
  parallel PostgreSQL **1,003 tests, 418.608 s**, 33 runner regressions and
  the same 29 real cases with one/four workers passed.
- **Step 6:** `check:fast -- --coverage` **177.381 s**, 1,953 fast + 414
  components; 342 focused checks and 27 PostgreSQL cases passed.
- **Step 7:** 1,953 fast + 414 components; 15 PostgreSQL, 24 calendar and
  54 desktop/mobile browser cases, web typecheck and static checks passed.
- **Step 8:** documentation-only; **353 tooling tests, 15.184 s** and
  16 command examples validated without dispatching database commands.
- **Step 9/review fixes:** `8496803c` plus local fixes; complete coverage check
  **622.442 s**, 1,967 fast + 414 components, PostgreSQL **997 tests, 407.486 s**.
  47 runner and 33 affected PostgreSQL cases passed. Reused web typecheck,
  **244 browser passes + 2 opt-in skips**, 4 React runtime passes, no retries.
- **2026-11-14 corrections:** bootstrap guidance, duplicate PostgreSQL example
  and fixed-interpreter S8705 annotation; six real-reexec regressions retained.
  `check:fast -- --coverage`: **1,974 fast + 414 components**, passed.
- **2026-11-16 reporting follow-up, before rebase:** `80da57f2` plus fixes;
  seven regressions failed before the fix, both affected modules then passed
  (**117 tests**). Complete coverage check **624.982 s**: **2,003 fast**,
  **997 PostgreSQL**, **414 components**; build/static checks and cleanup passed.

- **2026-11-16 post-rebase acceptance:** `12b15287`; complete coverage check
  **887.182 s**: **2,411 fast**, **1,211 PostgreSQL passed + 1 prerequisite
  skip**, **454 components**. Whole PostgreSQL runner **597.834 s**; server
  startup **2.189 s**, separately. Both timing targets passed in this sample,
  with only **2.166 s** PostgreSQL margin; this is not a stable timing guarantee.
  Evidence: `.harness/any822-rebase-20261116/`.

Intermediate SQL statement timeouts, inventory-ordering and HTTP-cleanup
failures were retained in diagnostics. Final checks passed after the ordering
and reporting fixes; the isolated statement-timeout/cleanup causes were not
established. No production deadline, retry or assertion was relaxed. Older
statements that ANY-766 sources or later steps were unavailable applied only
to those handoffs; they are superseded by Section 1.

Evidence by step: `.harness/any822-step2-20261113/`,
`.harness/any822-step3-20261113/`, `.harness/any822-step4-20261113/`,
`.harness/any822-step5-20261113/`, `.harness/any822-step6-20261113/`,
`.harness/any822-step7-20261113/`, `.harness/any822-step8-20261113/`.
Final/review evidence: `.harness/any822-review-fixes-81411570eab5/`,
`.harness/any822-strong-fixes-6747e01dd3d5/`,
`.harness/any822-final-review-20261114/`,
`.harness/any822-reporting-followup-20261116-a35232ff/` and `.harness/api-tests/`.

## 7. Source references

Infrastructure source slice:

- [10c5a4f — isolated templates and workers](https://github.com/gushinets/payments-portal/commit/10c5a4f357324f963f6f3dd1a9340e634e1feb5b)
- [c5df8c9 — pytest arguments and report lifecycle](https://github.com/gushinets/payments-portal/commit/c5df8c987804f35eaba0917b12eac818124e61b4)
- [12d06a6 — marker partitions](https://github.com/gushinets/payments-portal/commit/12d06a6df858246801381bf816d098bb507b706c)

Earlier ANY-822 inputs: `1a58bfe` (settings), `4c0e71d` (single-pass coverage)
and `ad586d5` (public-route waits); their old progress claims were not reused.
Mechanics and guidance: [PostgreSQL templates](https://www.postgresql.org/docs/18/sql-createdatabase.html),
[pytest-postgresql](https://github.com/dbfixtures/pytest-postgresql),
[Docker tmpfs](https://docs.docker.com/engine/storage/tmpfs/),
[pytest stability](https://docs.pytest.org/en/stable/explanation/flaky.html) and
[Playwright practices](https://playwright.dev/docs/best-practices).
