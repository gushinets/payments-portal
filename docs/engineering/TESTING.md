# Testing Strategy

Status: authoritative
Last verified: 2026-11-19

## Layers

- Static: documentation, generated-artifact, import-boundary, lint, and build
  checks.
- Unit/API/component: calculations, normalization, API behavior and UI effects
  using isolated state and explicit substitutes for external resources.
- PostgreSQL: real Alembic upgrade/downgrade, seeds, constraints, independent
  commits, locks, idempotency and recovery.
- Browser: Playwright journeys against an isolated full stack.
- Runtime: assertions against structured logs, metrics, and traces.

Choose the cheapest layer that protects the actual invariant. Keep calculation
and input-variant matrices in fast tests, with representative integration paths
to prove wiring. A pure text predicate belongs in a unit/component test; retain
browser assertions that use it against real rendered pages. PostgreSQL remains
required when the guarantee depends on migrations, constraints, transaction
boundaries, independent connections/commits, locking or durable recovery;
SQLite or mocks do not establish those guarantees.

Before consolidating cases, map every old assertion/guarantee to its retained
test owner in the execution plan. Preserve distinct failure paths and meaningful
assertions before removing duplicates. For example, expiry-source variants may
live in a fast calendar matrix while PostgreSQL retains publication-stage
rollback/history checks and a real lock-wait test. Fewer tests alone are not
evidence of an improvement.

## Commands

```bash
npm run check:fast
npm run test:api:fast
npm run test:api:postgres
npm run test:api
npm run test:e2e
npm run check
npm run check:fast -- --coverage
npm run check -- --coverage
```

Tests use synthetic users and payment payloads. A skipped PostgreSQL or browser
suite must be stated explicitly in handoff evidence.

`test:api:fast` excludes PostgreSQL and can run without a database server.
`test:api:postgres` runs the PostgreSQL layer with **four processes by default**.
`test:api` runs the fast partition serially, then PostgreSQL with four processes,
retaining outcomes from both even if the fast partition fails to start or run.
Whole modules are assigned greedily by collected case count. Order within
each module is preserved. Small selections use fewer processes when there are
fewer modules. The runner uses standard-library subprocesses.

`check:fast` checks documentation, generated artifacts, architecture, API
lint/format, web boundaries, components, web lint and API-fast. `check` also
builds the web app and runs PostgreSQL. The PostgreSQL stage needs a running
test server as described below. For browser tests, start the application stack
as described in [Development Environment](DEVELOPMENT.md), then run
`npm run test:e2e` or opt in with `RUN_E2E=true npm run check`. Coverage is
opt-in.

For a focused run or serial diagnosis, put harness options before
`--pytest-args`, which must be last:

```bash
npm run test:api:postgres -- --workers 1
python scripts/repo.py test api --workers 2
python scripts/repo.py test api-fast --pytest-args apps/api/tests/test_api_test_runner.py -q
python scripts/repo.py test api-postgres --workers 1 --junitxml=.harness/focused-postgres.xml --pytest-args apps/api/tests/test_identity_legal_persistence_postgres.py -k registration --durations=10
```

`api` and `api-postgres` accept `--workers 1` through `4`; `api-fast` accepts
only `1`. Selectors must reference existing Python tests beneath
`apps/api/tests`; quote a node ID containing spaces or shell metacharacters.
Diagnostic options include `-k`, verbosity, traceback and duration flags. The
only accepted explicit marker expressions are `-m postgres` for
`api-postgres` and `-m 'not postgres'` for `api-fast`; omit `-m` for `api`.
Unsupported options fail rather than bypass collection accounting. The shared
API test environment clears inherited `PYTEST_ADDOPTS` and `PYTEST_PLUGINS`
before pytest starts, including for coverage. The runner also clears both
when called directly. Installed-plugin autoload remains unchanged, and explicit
command-line selectors remain supported.
The runner rejects scheduler, coverage, configuration and report overrides;
use the harness's `--junitxml` and coverage commands instead.

### Coverage and CI

`check --coverage` and `check --fast --coverage` execute API-fast and components
once each with coverage enabled. A complete check runs PostgreSQL uninstrumented
through the parallel runner; its API coverage report therefore covers only the
fast partition. Standalone `python scripts/repo.py coverage api-fast` retains
that scope, while `python scripts/repo.py coverage api` instruments the complete
backend suite serially. There is no parallel coverage merge.

API coverage is written to `.harness/coverage/api/coverage.xml`; component
coverage is under `.harness/coverage/web-components/`. CI quality uses
`npm run check:fast -- --coverage` and publishes both coverage artifacts. The
production-gate job runs PostgreSQL with four workers on a separate 2 GiB tmpfs
service. Python receives the step's cancellation signal directly and writes
command output to `.harness/ci/postgres-pytest.log`. The diagnostics upload
includes available files in `.harness/ci/` and `.harness/api-tests/` on failure
or cancellation. Docker logs are collected on failure. See the
[CI workflow](../../.github/workflows/ci.yml) for the
exact commands; local checks do not establish remote CI success.

## Test environment and server lifecycle

API pytest setup installs synthetic settings before application imports and
does not consume the personal dotenv file. Canonical launches, workers and CLI
test children use the shared environment helper in
`apps/api/tests/support/settings.py`; scenario-specific overrides remain
explicit and are restored after the test. Normal application dotenv semantics
are unchanged. Do not configure tests by copying personal or production values.

Start the worktree's dedicated PostgreSQL test server before running the
PostgreSQL partition:

```bash
python scripts/repo.py test-db up
npm run test:api:postgres
python scripts/repo.py test-db stop
```

Replace the test command with `npm run test:api` for the complete backend
suite, or `npm run check` for the complete repository check. On Unix/WSL,
`make test_db_up` and `make test_db_stop` are equivalent to the Python
commands. The application stack started by `repo:up` is needed for browser
E2E and manual app use.

The dedicated `docker-compose.test.yml` project
(`payments-<worktree-id>-tests`) publishes a worktree-scoped loopback port.
`test-db up` uses the same pinned PostgreSQL image as development and requires
it to be installed locally. The launcher sets worktree-specific credentials,
so the workers cannot authenticate to another worktree's test server if it
later takes over the port. Run `test-db up` after upgrading from shared test
credentials to recreate the disposable container.

The standard test server stores `/var/lib/postgresql` in a **2 GiB tmpfs**;
allow that much available RAM in addition to PostgreSQL and test-process memory.
PostgreSQL durability settings remain at their normal defaults.
`test-db stop` removes the dedicated Compose project and all its disposable
state. Stop it only after its tests finish. Development data and explicitly
configured external servers have separate lifecycles. pytest owns the
scenario/template databases described below. Leave their creation and cleanup
to pytest.

The harness resolves test database settings in this order.

1. An explicit `TEST_POSTGRES_DATABASE_URL`.
2. A complete explicit set of `POSTGRES_USER_TEST`, `POSTGRES_PASSWORD_TEST`,
   `POSTGRES_PORT_TEST` and `POSTGRES_DB_TEST`. `POSTGRES_HOST_TEST` defaults
   to `localhost` when absent or empty. Partial settings, including a lone
   shell-exported `POSTGRES_PORT_TEST`, are rejected.
3. The worktree runtime configuration. The launcher reads `.harness/runtime.json`
   and `POSTGRES_PORT_TEST` from `.harness/runtime.env` without rewriting
   them and checks that the dedicated Compose service publishes the expected
   loopback endpoint.
   If either file is missing or the test port is invalid or differs between
   the files, run `test-db up` to refresh them. It preserves the offset from
   an existing `runtime.json`.

Configured ports must be between 1 and 65535. The configured database name
must end in `_test` or `_tests`. pytest uses it to validate routing and
assigns its own physical database names. Use a dedicated test server with a
role that can create databases and connect to the `postgres` admin database.
The performance target uses the standard tmpfs server. Explicit test
servers may use other storage.

### Migrated templates and ownership

Each pytest process that uses PostgreSQL generates unique `portal_<uuid>_tests` and
`portal_<uuid>_template_tests` names. The shared lifecycle owner in
`apps/api/tests/support/postgres.py` creates the empty scenario database on
demand. On the first request for `migrated_database`, it creates the template
and runs real Alembic `upgrade head`, including migration seeds. Each request
then replaces the scenario database with a fresh template clone. Template
connections are closed before cloning; mutable business data is never stored
in the template.

Migration tests retain explicit schema resets and upgrade/downgrade transitions.
Tests using the raw engine can run historical transitions independently of the
template migration to head.
The next ordinary test receives a fresh clone even after a migration test has
changed the scenario schema. Business setup, sessions and clients remain
function-scoped; reuse of an engine/session factory does not authorize reuse of
prepared purchases, reconciliations or mutable ORM state across tests.

Destructive operations validate targets before connecting or executing SQL.
The owner records successful creation and cleans up only its own databases,
including after failed setup or test execution. During database DDL, the
fixture defers the runner's graceful interrupt until it records the result.
Name collisions fail without pre-dropping existing data. Pools are disposed
before replacement; checked-out
connections and external connection leaks remain failures. Do not hide them
with `DROP ... FORCE`, connection termination or cleanup of another run's data.

### Reports, failures and interruption

After command/environment preparation and argument validation, the `test api*`
runner prints its unique directory under `.harness/api-tests/`. A completed
run contains collection logs/manifests, `expected.json` assignments, worker
`nodeids.txt`, `pytest.log`, `manifest.json` and `junit.xml`, plus merged
`junit.xml` and `result.json` at the run root. Failed or interrupted runs may
contain only artifacts from the stages reached. Early preparation/validation
failures may have no run directory; a supplied `--junitxml` path records the
startup state as described below. Inspect the current invocation's available
artifacts, not a prior successful run.

Collection errors, failed/crashed workers, missing reports or differences
between expected IDs, worker collections and JUnit produce a nonzero result.
Worker exit 0 requires no JUnit failures/errors; exit 1 requires at least one.
Other worker exit codes or inconsistent results add an `api-runner`
infrastructure error to merged JUnit while retaining available test results.
Failures and skips remain in the merged report. Once the `test` command options
are parsed, a caller-supplied `--junitxml` path is marked incomplete before
worker-count validation and test-environment preparation. Expected startup
failures replace it with a current error; the runner does the same before its
own validation when called directly. Execution replaces it with current results,
so an older success cannot represent the new run. Report-write errors remain
visible failures. If a later worker cannot start, available reports from the
started workers are retained alongside the infrastructure error. Reports
already collected are included only once when execution is interrupted.

An explicit `--pytest-args -x` stops each worker after its first failing test,
including setup or teardown errors. Other workers and API partitions still run.
The worker manifest must confirm that pytest stopped after failure; only then
may JUnit omit the unexecuted collection tail. Its cases must form a nonempty
prefix ending at the failed test. Collection manifests still match the complete
assigned selection, the real failures remain, and the command exits nonzero
without an additional infrastructure error. Worker summaries show executed
versus selected case counts; unexecuted cases are not reported as passes or skips.

On Ctrl-C or termination, the runner interrupts children and gives pytest up to
15 seconds for fixture cleanup, then allows 5 seconds after termination before
force-killing remaining processes. It joins children and returns nonzero
(130 for a handled interruption). Inspect `interrupted.json` in the active
collection/worker directory and the logs for forced termination. Cleanup is
not guaranteed after a forced kill; report any leftovers in disposable storage.
There is no sweep of previous runs' resources. Do not delete pre-existing,
shared or externally managed databases to make a rerun pass.

## Test fixtures

`apps/api/tests/conftest.py` is the shared API test-resource composition root.
Before creating test setup code, reuse its existing fixtures, including the
PostgreSQL URL, engine, session factory, migrated database, and rollback-safe
session fixtures.

When multiple test modules need a missing resource or lifecycle, add a typed
fixture to `conftest.py` with explicit scope, setup, and teardown so the resource
has one owner. Keep a fixture inside a test module only when its setup is truly
specific to that module, and compose it from shared fixtures rather than
creating a second database, engine, or session lifecycle.

For new or materially changed helpers, do not import from another
`test_*.py`. Keep one-consumer setup local; extract justified shared data shapes
to `factories/` or reusable support to `support/`, with shared lifecycle fixtures
owned by `conftest.py`. This is a rule for the changed slice, not an instruction
to refactor unrelated existing tests.

PostgreSQL tests must not resolve database environment variables or perform
physical database lifecycle independently when a shared fixture already owns
that responsibility. Every destructive database or schema operation must pass
the shared test-database safety validation before connecting or executing SQL.

## Test data factories

Assess existing coverage and setup before changing a contract. For a bug, run
a focused failing regression before its fix; for behavior-preserving work,
characterize existing results and compatibility. A vocabulary or type change
does not authorize new serialized keys, nulls, values, defaults or identities.

Reuse typed factories under `apps/api/tests/factories/` for repeated object
shapes, defaults and construction invariants. Extract a missing factory only
when a current consumer/invariant justifies it. Simple one-off setup may remain
inline. Touching a related test does not mandate factory migration; move only
setup whose repeated knowledge or changed invariant benefits from one owner.
Do not add a factory framework or migrate unrelated tests to satisfy wording.

Use factories for object shape and default test data. Use fixtures for resource
lifecycle, dependency overrides, environment changes, database sessions, and
other setup that requires teardown. Put a fixture in `apps/api/tests/conftest.py`
only when multiple test modules need it; keep module-specific setup as a
module-local fixture near the tests that use it.

## FastAPI dependency substitution

Use `app.dependency_overrides` when a route already exposes an explicit FastAPI
resource or context dependency, including `get_db`,
authenticated-current-session context (`get_current_session`). Restore the
previous override mapping in teardown or a
`finally` block so overrides cannot leak between tests. Prefer this supported
substitution point to monkeypatching a module global; do not mass-migrate
unrelated historical tests whose dependencies are not part of the changed
slice.

Stateless Application/service functions are not DI-managed only for testability.
Test them by calling the inward function directly with explicit dependencies and
typed input. Add a shared API client or override fixture only after multiple test
modules need the same lifecycle; otherwise keep the lifecycle local to the test
module and make cleanup explicit.

## Clocks, readiness and stability

Control the clock used for calendar, expiry and calculation matrices; choose
explicit timezone/day-boundary inputs instead of depending on today's date or
sleeping until it changes. Restore clock overrides after each test. Keep real
timeout, cancellation, independent-commit and lock-wait scenarios where elapsed
time and concurrency are the guarantee; a fake clock must not replace those
mechanisms.

In browser tests, wait for the relevant response and visible ready state using
web-first assertions. Register a response wait before the triggering action.
Await required effects and `document.fonts.ready` before accessibility or
layout-sensitive assertions. Do not use global `networkidle` or arbitrary
sleeps as a proxy for page readiness. Diagnose ordering, leaked resources and
uncontrolled state when tests are flaky; retries, larger deadlines and weaker
assertions are not repairs.

## Verification and evidence

Use focused checks during iteration, then the broadest applicable canonical
check before handoff. Reuse still-valid results when the implementation,
environment and scope are unchanged; do not rerun every full partition before
the final `check`. Record an assertion/guarantee map when consolidating tests,
and explicitly report skipped or blocked layers. The
[Agent Workflow](AGENT_WORKFLOW.md) defines the delivery loop.

Keep compact commands, revision, outcomes, timing conclusions and limitations
in the execution plan. Detailed logs, manifests, JUnit and browser artifacts
belong in ignored `.harness/` directories or CI artifacts. Performance comparisons
must retain the same selected inputs, settings and tool versions, an excluded
warm-up and repeated measurements; report the spread and machine/load, storage,
process count and cache conditions. Include collection, database creation,
cloning and cleanup in test wall time; report server startup separately. A
diagnostic run or local PASS does not establish final timing or remote CI acceptance.

Underlying mechanics and guidance: [PostgreSQL database templates](https://www.postgresql.org/docs/18/sql-createdatabase.html),
[Docker tmpfs](https://docs.docker.com/engine/storage/tmpfs/),
[pytest flaky-test guidance](https://docs.pytest.org/en/stable/explanation/flaky.html)
and [Playwright practices](https://playwright.dev/docs/best-practices).
