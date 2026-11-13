# ANY-822 — Rebuild test execution acceleration from main

Status: **IN PROGRESS — Steps 1–6 complete; Steps 7–9 pending**
Created: 2026-11-13
Issue: [ANY-822](https://linear.app/paveldik/issue/ANY-822)
Execution branch: `ANY-822`
Base: `2d278f62f0a2f7c4b40fb322618b268580de2301`

## 1. Objective, decisions and preparation

Reduce complete test feedback time while preserving meaningful coverage of
business invariants, PostgreSQL migrations, independent commits, locking and
recovery. Deliver implementation and durable testing guidance; research or a
successful source-code transfer alone does not complete the issue.

Owner-selected acceptance targets on the current machine, without competing
heavy workloads:

- Complete PostgreSQL partition: **at most 10 minutes**.
- Complete canonical `check`, including coverage and excluding browsers:
  **at most 15 minutes**.
- No unexplained new skips/xfails, weaker assertions, increased deadlines or
  retries introduced to obtain a passing result.
- Existing developer aliases and CI use the accelerated path by default.

Follow [root AGENTS](../../../AGENTS.md), [documentation AGENTS](../../AGENTS.md),
[Testing Strategy](../../engineering/TESTING.md),
[Agent Workflow](../../engineering/AGENT_WORKFLOW.md) and
[Coding Conventions](../../engineering/CODING_CONVENTIONS.md). Read the API/web
subtree instructions before changing their tests. This work changes testing
infrastructure and selected tests, not commercial or paid-access behavior.

Preparation completed at the owner's request:

- [x] Fetch remote `main` and fast-forward local `main`; both identify the base
  above on 2026-11-13.
- [x] Preserve the former branch as `822-OLD` at
  `1201e29aa837d0446dd8440139c250536935df66`. Preserve its 15 modified/untracked
  files in a separately verified Git stash.
- [x] Create a new `ANY-822` from that main in the existing working directory.
  No additional worktree is required.
- [x] Record this replacement plan. All implementation steps below are pending.

The old branch is historical research, not an implementation baseline. Its
double-reset ordinary/schema lifecycle and unfinished xdist implementation
must not be carried forward. Broad fixture extraction in its Step 6 did not
improve the measured sample; do not repeat that refactor as an optimization.
Keep installations, commits, pushes and publication under the owner's existing
explicit-authorization rules.

## 2. Source material and measurement baseline

Port the infrastructure slice from ANY-766, including its two follow-up fixes:

- [10c5a4f — isolated templates and workers](https://github.com/gushinets/payments-portal/commit/10c5a4f357324f963f6f3dd1a9340e634e1feb5b)
- [c5df8c9 — pytest arguments and report lifecycle](https://github.com/gushinets/payments-portal/commit/c5df8c987804f35eaba0917b12eac818124e61b4)
- [12d06a6 — marker partitions](https://github.com/gushinets/payments-portal/commit/12d06a6df858246801381bf816d098bb507b706c)

Transfer only the applicable testing changes, not the ANY-766 branch, its
business implementation or its task-specific tests. Adapt selected earlier
ANY-822 changes from `1a58bfe` (settings), `4c0e71d` (single-pass coverage) and
`ad586d5` (public-route waits), without copying their old execution reports or
progress claims.

Historical evidence supports the direction, not acceptance of this rebuild:
ANY-766 recorded a local complete PostgreSQL run around 7m12s and a CI command
around 4m28s, compared with an earlier CI command around 28m53s. These were
different runs/revisions, not controlled repeated measurements of this branch.

Before implementation, capture collection and retain the existing 24-case
identity/legal/email-verification control from the two persistence modules.
Its exact historical IDs are in commit `793118f`, file
`docs/exec-plans/active/ANY-822-step4-verification.json`, under
`ordinary_measurements.baseline.case_ids`. Confirm them against this base and
freeze the selected IDs before changing infrastructure.

Measure the original serial path and final accelerated path using those same
cases, one unmeasured warm-up and three measured runs per side. Use identical
test inputs/settings and installed tool versions; report storage and process
differences explicitly as parts of the intended optimization. Use newly
created disposable resources for the baseline too. A before/after full-suite
run is not required; final absolute runtime targets remain mandatory.

## 3. Ordered infrastructure implementation

### A. Isolate test configuration

- [x] Adapt `1a58bfe`: establish safe test settings before application imports;
  test processes must not consume the personal dotenv file.
- [x] Preserve explicit scenario overrides and apply the same environment to
  pytest workers, CLI tests and other child processes.
- [x] Keep database configuration precedence: explicit
  `TEST_POSTGRES_DATABASE_URL`, then complete explicit `POSTGRES_*_TEST`, then
  worktree runtime configuration. Reject partial configuration.
- [x] Keep production settings semantics unchanged and add focused regressions
  for contamination, override precedence and child-process propagation.

Expected effect: reproducible tests independent of developer configuration;
remove the environment contamination observed during the previous research.

### B. Introduce a dedicated RAM-backed test server

- [x] Port the separate test Compose project, worktree-scoped loopback port
  and runtime `POSTGRES_PORT_TEST` configuration from ANY-766.
- [x] Use the repository's existing pinned PostgreSQL image and a 2 GiB tmpfs
  mounted at `/var/lib/postgresql`. Preserve normal PostgreSQL durability
  settings. Keep the development server and its persistent volume separate.
- [x] Route `test-db up/stop` to this test server. Stale runtime configuration
  must explain that `test-db up` is required.
- [x] Continue supporting explicitly configured test servers. The standard
  acceptance environment uses tmpfs; document RAM requirements and that
  stopping this disposable server loses its test state.

Expected effect: avoid the disk/checkpoint stalls that prevented reliable
parallel execution during ANY-766 experiments.

### C. Clone a migrated database template per scenario

- [x] Give each pytest process unique session-owned scenario/template database
  names. Build its template once through real Alembic `upgrade head`, including
  migration seeds, and close template connections before cloning.
- [x] Replace repeated migrations for `migrated_database` with a fresh database
  clone before each dependent test. Keep business data, mutable fixtures and
  clients function-scoped; do not cache prepared purchase/reconciliation state.
- [x] Keep migration tests' explicit schema resets and upgrade/downgrade
  transitions. Ordinary tests following them must still receive a fresh clone.
- [x] Validate destructive targets before connecting/executing SQL. Use one
  fixture owner, track successful creation, fail on name collisions, and clean
  up only resources created by the current run.
- [x] Dispose pools and reject checked-out connections before replacement.
  Do not pre-drop a colliding database or use `DROP ... FORCE`. Connection
  leaks must remain visible as failures.

Expected effect: remove repeated Alembic startup while retaining PostgreSQL
constraints, triggers, independent connections and real commit behavior.

### D. Port bounded PostgreSQL parallelism

- [x] Implement the stdlib subprocess runner and the three source commits'
  documented argument/report-lifecycle and marker-partition fixes. Add no
  dependency on xdist or another scheduler.
- [x] Default to four PostgreSQL processes, keeping fast API tests serial.
  Partition whole modules greedily by collected case count, preserving order
  within modules. Each process owns separate database resources and artifacts.
- [x] Support `test api-postgres --workers N` and `test api --workers N` for
  1–4 workers; one worker is the serial diagnostic mode. For `api-fast`, allow
  only a serial worker setting. Keep existing npm aliases working.
- [x] `test api` runs the fast and PostgreSQL partitions and retains outcomes
  from both, including when the fast partition fails.
- [x] Retain per-run manifests/logs/JUnit, expected-versus-worker node-ID
  checks, merged JUnit, strict supported marker partitions and safe path/argument
  handling. Fix nondeterministic parameter IDs only where collection requires it.
- [x] Fail on collection errors, worker failures, missing reports or mismatched
  collections. Preserve failures and skips in reports; a previous report must
  never be presented as the current run's success.
- [x] On interruption, stop/join children and allow fixture cleanup before
  forced process termination. Return a nonzero result. Do not sweep resources
  from previous runs; any hard-kill leftovers remain confined to disposable
  test storage and must be reported rather than silently ignored.

Expected effect: parallelize the dominant PostgreSQL partition using the
method already exercised in ANY-766, with complete outcome accounting.

### E. Execute coverage once and wire CI

- [x] Adapt `4c0e71d` to add `check --coverage`, including `--fast --coverage`.
  Run API-fast and frontend components once each with coverage enabled.
- [x] Change CI quality to `check --fast --coverage`, remove the two standalone
  duplicate coverage executions, and preserve artifact publication.
- [x] Run PostgreSQL uninstrumented and parallel in a complete `check`.
  Preserve standalone `coverage api` and `coverage api-fast` behavior and
  scope, using serial execution; do not introduce parallel coverage merging.
- [x] Add tmpfs to the CI PostgreSQL service and use the same four-process
  runner. Preserve existing CI checks and failure diagnostics.

Expected effect: eliminate duplicate API-fast/component work in quality CI
and make normal local and CI commands use the same accelerated implementation.

## 4. Bounded test improvements

For each consolidation, record the old guarantee and its retained test owner.
Preserve assertions before removing cases; do not use test-count reduction as
the success metric.

- [ ] In `test_expiration_never_appends_or_changes_latest_revision`, reduce the
  3x3 PostgreSQL matrix to the three stages `before_database`, `after_history`
  and `after_flush`, using the common account-day boundary. Keep all three
  deadline sources (account day, policy, price) in the existing fast
  `test_evaluation_carries_exclusive_account_calendar_boundary` matrix. Retain
  rollback/history assertions and the separate real PostgreSQL lock-wait test.
- [ ] For
  `test_paid_read_bounds_display_evidence_without_truncating_effective_contents`
  only, replace full purchase/reconciliation setup with a module-local fixture
  for valid persisted reader state. Retain real FK-valid provenance records,
  typed effective state and valid allowance technical terms. Keep the real HTTP
  request, 100-product cap, complete grants/allowances, and before/after billing
  snapshot assertions. Other paid-read scenarios keep their full business path.
  Do not introduce a general billing fixture framework.
- [ ] Move the pure subscription-state regex guard test from Playwright to
  Vitest. Extract one test-only TypeScript helper shared with the real browser
  assertions; preserve its positive/negative input cases and page coverage.
- [ ] Remove the weaker synchronous unverified-email component duplicate,
  retaining the stronger test that checks after React effects have executed.
- [ ] Adapt `ad586d5` only in public-route tests: replace `networkidle` with
  the relevant response and visible-ready-state waits. Await fonts and required
  effects before accessibility assertions; retain desktop/mobile coverage.

Expected effect: fewer redundant database preparations and browser contexts,
plus concrete examples for future work. These are supporting improvements;
RAM, templates and bounded workers remain the main performance intervention.

## 5. Documentation, verification and completion

### Documentation changes

- [ ] Update the existing Testing Strategy as the single detailed authority;
  reconcile README/development/AGENTS command references and links.
- [ ] Document test-server lifecycle, configuration precedence, memory needs,
  default workers, serial diagnosis, interruption behavior and ownership.
- [ ] Require the cheapest test level that protects the actual invariant.
  Keep PostgreSQL for migrations, constraints, independent commits, locks and
  recovery; use fast matrices for calculation variants and representative
  integration paths for wiring.
- [ ] Distinguish fixture resource ownership from factory data shapes; keep
  mutable business setup per test. For new/materially changed test helpers,
  avoid imports from another `test_*.py`; extract only justified shared setup.
- [ ] Require controlled clocks for calendar calculations and observable
  readiness in browser tests, while preserving real timeout/cancellation/lock
  scenarios. Do not treat retries or increased deadlines as repairs.
- [ ] Extend Agent Workflow with focused iteration, final broad verification,
  reuse of still-valid evidence, and an assertion/guarantee map for consolidation.
- [ ] Record compact timings and conclusions in this plan or a short results
  document. Keep detailed logs/manifests/JUnit in `.harness` or CI artifacts;
  do not copy the previous branch's large reports into this rebuild.

Relevant primary references for these rules:
[PostgreSQL database templates](https://www.postgresql.org/docs/18/sql-createdatabase.html),
[pytest-postgresql template approach](https://github.com/dbfixtures/pytest-postgresql),
[Docker tmpfs](https://docs.docker.com/engine/storage/tmpfs/),
[pytest flaky-test guidance](https://docs.pytest.org/en/stable/explanation/flaky.html),
[Playwright practices](https://playwright.dev/docs/best-practices).

### Focused verification during implementation

- [x] Settings/child-process isolation and explicit configuration precedence.
- [x] Fresh state across tests/separate pytest processes, migration seeds and mixed
  ordinary/migration ordering; real independent-commit and locking scenarios.
  Concurrent worker verification passed in Step 5.
- [x] Unsafe-target rejection, collision preservation, connection-leak failure
  and cleanup of owned resources after failed setup/test execution.
- [x] Module partition completeness, one-versus-four-worker equivalence on a
  small real sample, and the mixed API dispatcher on a small controlled sample.
- [x] Collection failure, failed/crashed worker, missing/mismatched manifests
  or JUnit, skips, and interruption; validate return codes and reports.
- [x] Single API-fast/component execution with coverage, unchanged standalone
  coverage scope and compatible npm aliases.
- [ ] The changed backend/component/browser tests and their guarantee map.

### Final acceptance on the implementation revision

- [ ] Run `npm run check -- --coverage` once on the final source state and
  measure its PostgreSQL stage and complete non-browser wall time.
- [ ] Run `npm run typecheck:web` and the complete Playwright suite because
  browser tests change. Reuse valid checks unless affected code or conditions
  change; do not routinely run full fast/API partitions again before `check`.
- [ ] Include collection, database creation/cloning, tests and cleanup in
  runtime figures. Report server startup separately. Use installed dependencies
  and available browsers, retain caches consistently, and state machine/load,
  tools, storage, process count, SHA, commands, outcomes and exclusions.
- [ ] Confirm PostgreSQL <=10 minutes and complete non-browser `check`
  <=15 minutes. If either target fails, profile and correct the measured
  bottleneck within scope; do not declare completion from a successful port.
- [ ] Inspect the final diff, generated-file status and all new files. Record
  each check as passed/failed/blocked/skipped with its actual revision.
- [ ] Validate CI configuration locally; record actual remote CI separately
  after normal authorized publication. Local checks do not imply a CI PASS.

### Current execution evidence

Steps 1–6 are complete; Steps 7–9 remain pending. Evidence is recorded below.
Final runtime and stability acceptance remains Step 9 work.

Preparation verification on 2026-11-13: `npm run docs:check` passed;
`git diff --check` and the new plan's whitespace check passed. At preparation
time, the working changes contained only this plan and its documentation-index
entry; runtime and performance suites had not yet been run.

#### Step 1 — original serial baseline (2026-11-13)

- [x] Read the project instructions, Testing Strategy and preparation evidence;
  preserve the pre-existing plan and documentation-index changes on `ANY-822`.
- [x] Capture complete API, fast and PostgreSQL collections before implementation.
- [x] Resolve and freeze the historical 24-case control against this base.
- [x] Run one excluded warm-up and exactly three measured serial runs, without
  coverage, using newly created disposable resources and unchanged fixtures.
- [x] Verify exact collection, all outcomes, JUnit completeness and database
  cleanup for every run; remove only this run's container and volume.
- [x] Complete final documentation, canonical fast and diff checks.

Collection passed: **2,866 total = 1,871 API-fast + 995 PostgreSQL**. The two
marker partitions are disjoint and their union exactly matches the full
collection. All historical control IDs exist unchanged, including the three
commercial-triplet parameter cases. The ordered, newline-terminated UTF-8 control
list has SHA-256
`71eb278348978f6721ab01cfaf43117f0331c8d6f376d533b800486a61039f65`.
Freeze this exact order and parameter spelling for the final comparison:

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

These unchanged tests characterize transactional registration/rollback,
hashed sessions and reset tokens, logout/revocation, canonical scope/FK
constraints, append-only legal evidence and allowed audit clearing, commercial
triplet constraints, concurrent duplicate registration, and verification/resend
serialization through independent PostgreSQL sessions. No assertions, cases,
deadlines or retries were changed.

The measured command was repository-root `.venv/bin/python -m pytest -p
no:cacheprovider -p any822_evidence --durations=24 -ra --junitxml=<run.xml>`
followed by the 24 exact node IDs above as separate subprocess arguments.
The small evidence plugin only records collected IDs and phase outcomes/times;
it does not modify fixtures or collection. Use the same recorder and frozen
inputs for the final comparison. Each timed interval includes Python/pytest
startup, imports/collection, physical test DB creation, the original per-case
schema reset and Alembic upgrade, tests, teardown and JUnit writing. Server
startup and the post-run read-only cleanup probes are outside those intervals.

- Warm-up, excluded from statistics: **139.834 s**.
- Measured runs, in execution order: **146.553 / 73.228 / 56.941 s**.
- Median: **73.228 s**; range: **56.941–146.553 s**;
  `(max - min) / median`: **122.37%**.
- Setup/call/teardown totals for the measured runs, respectively:
  **107.437/36.763/0.309 s**, **53.665/16.841/0.224 s** and
  **43.610/10.587/0.599 s**. These phase totals exclude pytest startup/reporting.
- All four invocations: **24 passed, exit 0**, exact frozen collection,
  24 JUnit cases, no failures/errors/skips/xfails. After each invocation:
  zero remaining application/test databases and zero other client connections.

Environment and ownership:

- Linux `6.8.0-138-generic`, Intel Xeon E5-2660 v4, 14 cores/28 logical CPUs,
  approximately 31.24 GiB RAM; Python `3.12.13`, pytest `9.1.1`, Alembic
  `1.18.5`, SQLAlchemy `2.0.51`, psycopg `3.3.4`, pytest-cov `7.1.0`,
  Node `24.14.0`, npm `11.11.1`, uv `0.12.7`. Installed pytest-xdist `3.8.0`
  was auto-discovered but unused: **one serial pytest process**, no workers.
  No dependencies were installed or updated; the full installed-version
  inventory is retained with the evidence.
- The repository-pinned PostgreSQL `18.4` image
  `postgres:18.4-alpine3.22@sha256:774521500f4c22761b25a6bdb772a0a3c2e8dd32468210bdad9231c5752ea398`
  was already installed and used with `--pull=never`. The newly created server
  bound only a dynamically allocated `127.0.0.1` port, using a new disk-backed
  Docker volume on ext4 (87% used), without tmpfs or durability tuning.
  `fsync`, `synchronous_commit` and `full_page_writes` were `on`;
  `shared_buffers` was 128 MiB and `max_connections` 100.
  Server startup, including initialization/readiness: **28.524 s**, separately.
- The measurement launcher supplied a clean allowlisted process environment,
  explicit synthetic values for all Settings fields, disabled dotenv's
  `load_dotenv` through `PYTHON_DOTENV_DISABLED=1`, and cleared external source,
  SMTP and telemetry settings. Pydantic's existing dotenv source was still
  present, with consumed fields shadowed by explicit environment values.
  This is a measurement-only precaution; production/test settings code is
  unchanged and Step 2 remains pending. Reuse the frozen `environment.json`
  and installed tool versions for the final sample, changing only owned
  database routing and artifact paths as required by the intended optimization.
- pytest alone created/dropped `any822_baseline_tests` for each invocation.
  The container `any822-baseline-1e08c1fd7869` and its new volume were removed
  after verification; no existing server, volume or database was reused or
  removed. The original fixture's destructive lifecycle remained confined to
  this new disposable server.

Detailed evidence remains ignored under `.harness/any822-step1-20261113/`:
`frozen-control.json`, `control-nodeids.txt`, `collection-*.json/log`,
`collection-summary.json`, `environment.json`, `environment-metadata.json`,
`baseline-results.json`, the measurement launcher/recorder, per-run logs,
phase reports, collections and JUnit, and PostgreSQL logs. Source fingerprints
are retained in `baseline-results.json`.

Final verification at the base SHA above, with only this plan changed during
Step 1 and the pre-existing documentation-index entry preserved:

- **PASSED:** `npm run check:fast`, exit 0, **134.121 s**, executed on the host
  with synthetic settings. It passed documentation/generated-artifact checks,
  architecture, Python lint/format, web boundaries/typechecks, all **414**
  component tests, web lint and all **1,871** API-fast tests (**995 deselected**,
  no skips/xfails). Existing SQLite FK-sort/deprecation warnings remain in the
  log; no source change was made to suppress them.
- **PASSED:** separate `npm run typecheck:web`, final `npm run docs:check`,
  `git diff --check`, explicit untracked-plan whitespace/control-digest checks,
  and inspection of the original-to-current plan diff and all untracked files.
  Measured execution-source fingerprints remain unchanged.
- **RESOLVED environment-only attempts:** the first sandboxed `check:fast`
  stopped at a web tooling test; direct diagnosis exposed `spawnSync npm EPERM`.
  The same three tooling cases passed outside the sandbox. The first host
  attempt then passed 1,868 API-fast cases and failed three runtime-config
  cases because the measurement launcher's `KERNEL_MOCK_ENABLED=false` was
  valid for Pydantic but incompatible with repo.py's `0/1` grammar. The final
  canonical run used `KERNEL_MOCK_ENABLED=0` and passed completely. Dotenv
  loading was enabled for canonical checks because they explicitly test its
  behavior with synthetic files; explicit Settings values remained supplied.
  The frozen benchmark environment and its four original runs were preserved.
  All attempt logs/results remain in `check-fast*` artifacts.
- **SKIPPED by step scope:** full PostgreSQL/complete `check`, coverage,
  browsers and remote CI. No application journey or external-provider runtime
  investigation applies to this measurement/documentation-only change.

Limitations: no competing heavy check was launched by this task during timing,
but the shared developer desktop had background processes. One-minute host
load ranged from approximately **7.78 to 12.90** in the captured samples;
available RAM was approximately 12.89–14.32 GiB across the snapshots, and swap
remained effectively unused. The large measured spread is retained without
discarding or replacing a run. This is a noisy original-path baseline, not
evidence of a stable speedup; compare the final sample with this variability
explicitly. The complete PostgreSQL suite, complete `check`, coverage,
browser suites and remote CI were not run in this measurement step. Full
before/after suite measurement is not required by this plan; final absolute
runtime targets remain Step 9 work.

#### Step 2 — isolate test configuration (2026-11-13)

Completed: isolated test settings and child processes from personal configuration;
retained scenario overrides, database precedence and normal runtime dotenv behavior.

Verification: `npm run check:fast` passed (1,886 API-fast + 414 component tests,
129.235 s); 26 PostgreSQL/CLI cases, docs and diff checks passed. Added 15 settings
regressions; all previous test IDs retained. Evidence: `.harness/any822-step2-20261113/`.
Full PostgreSQL/check, coverage, browsers and CI remained deferred at that
handoff; Steps 3–9 had not started.

#### Step 3 — dedicated RAM-backed PostgreSQL server (2026-11-13)

Completed: dedicated PostgreSQL 18.4 Compose project with a 2 GiB tmpfs,
worktree-scoped loopback port and `test-db up/stop` lifecycle. Normal durability,
development storage and explicit test-server configuration are preserved.
Stale runtime guidance and Compose credential/port precedence are covered.

Verification: `npm run check:fast` passed (1,892 API-fast + 414 component tests,
146.716 s); 28 focused settings/server and 29 PostgreSQL/CLI cases passed.
Real tmpfs, restart, development isolation and owned-resource cleanup verified;
docs and diff checks passed. Evidence: `.harness/any822-step3-20261113/`.
Full PostgreSQL/check, coverage, browsers and CI remain deferred. Step 4 not started.

#### Step 4 — migrated database template (2026-11-13)

Completed: one migrated template per pytest process and fresh scenario clones.
Migration transitions and per-test business state are preserved; collisions,
connection leaks and cleanup of owned resources are covered.

Verification: `npm run check:fast` passed (1,908 API-fast + 414 component tests,
229.539 s); full serial PostgreSQL passed (1,003 tests, 25m24s); final focused
verification passed (62 tests). Previous test IDs are retained; resource cleanup,
docs and diff checks passed. Evidence: `.harness/any822-step4-20261113/`.

Limitations: full `check` was interrupted before the font-dependent web build.
Timings overlapped other checks and are diagnostic. The ANY-766 source commit
was unavailable locally; implementation follows this plan's contract.
Parallelism, coverage, browsers, CI and final acceptance remain Steps 5–9 work.

#### Step 5 — bounded PostgreSQL subprocess runner (2026-11-13)

Completed: four PostgreSQL processes by default, serial API-fast, whole-module
partitioning and `--workers 1–4`. Collection/JUnit accounting, mixed API failure
handling and child-process cleanup are covered; npm aliases are preserved.

Verification: `npm run check:fast` passed (1,941 API-fast + 414 component tests,
134.075 s); full parallel PostgreSQL passed (1,003 tests, 418.608 s). All 33 new
runner regressions passed; the same 29 real cases passed with one/four workers.
All previous test IDs are retained; resource cleanup, docs and diff checks passed.
Evidence: `.harness/any822-step5-20261113/` and `.harness/api-tests/`.

Limitations: the first full run had two SQL statement timeouts, not reproduced
in diagnostics or the final run. Their cause remains unexplained; retain this
stability risk for Step 9. No deadlines were increased, retries added or assertions weakened.
ANY-766 source objects were unavailable locally; exact port parity is unverified.
Windows, full `check`, coverage, browsers and CI were not run. Timings are
diagnostic; Steps 6–9 have not started.

#### Step 6 — single-pass coverage and CI (2026-11-13)

Completed: `check --coverage` runs API-fast and components once each; standalone
coverage remains serial. CI uses this path, a 2 GiB PostgreSQL tmpfs and four
workers, preserving coverage and failure artifacts.

Verification: `npm run check:fast -- --coverage` passed (1,953 API-fast + 414
component tests, 177.381 s); 342 focused checks and 27 PostgreSQL cases with
four workers passed. CI configuration, resource cleanup, docs and diff checks
passed. Evidence: `.harness/any822-step6-20261113/` and `.harness/api-tests/`.

Limitations: complete-check routing and standalone coverage scope were checked
by regressions; full `check`, full instrumented API, browsers and remote CI were
not run. Final runtime/stability acceptance remains Step 9. Steps 7–9 not started.
