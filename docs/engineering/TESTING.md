# Testing Strategy

Status: authoritative
Last verified: 2026-11-13

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
retaining outcomes from both even if the fast partition fails. Whole modules
are assigned greedily by collected case count; order within each module is
preserved. Small selections use fewer processes when there are fewer modules.
The runner uses stdlib subprocesses, not xdist.

`check:fast` checks documentation, generated artifacts, architecture, API
lint/format, web boundaries, components, web lint and API-fast. `check` also
builds the web app and runs PostgreSQL. Browser tests run separately, or inside
`check` only with `RUN_E2E=true` and a running harness stack. See
[Development Environment](DEVELOPMENT.md) for stack setup. These test commands
do not collect code coverage unless explicitly requested.

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
Unsupported options fail rather than bypass collection accounting. The runner
clears `PYTEST_ADDOPTS` and rejects scheduler, coverage, configuration and report
overrides; use the harness's `--junitxml` and coverage commands instead.

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
service and retains failure diagnostics, including runner artifacts. See the
[CI workflow](../../.github/workflows/ci.yml) for the exact commands; local
checks do not establish remote CI success.

## Test environment and server lifecycle

API pytest setup installs synthetic settings before application imports and
does not consume the personal dotenv file. Canonical launches, workers and CLI
test children use the shared environment helper in
`apps/api/tests/support/settings.py`; scenario-specific overrides remain
explicit and are restored after the test. Normal application dotenv semantics
are unchanged. Do not configure tests by copying personal or production values.

On Unix/WSL, use the repository's worktree-scoped PostgreSQL server lifecycle:

```bash
make test_db_up
npm run test:api:postgres
npm run test:api
make test_db_stop
```

The cross-platform equivalents are `python scripts/repo.py test-db up` and
`python scripts/repo.py test-db stop`. The dedicated `docker-compose.test.yml`
project (`payments-<worktree-id>-tests`) exposes only a worktree-scoped loopback
port, recorded as `POSTGRES_PORT_TEST` in `.harness/runtime.env`. It uses the
same pinned PostgreSQL image as development, which must already be installed;
`test-db up` does not pull images. Development keeps its separate Compose
project, port and persistent volume.
The test-server launcher pins its Compose credentials and port to the written
runtime values so inherited shell variables cannot redirect this local server.

The standard test server stores `/var/lib/postgresql` in a **2 GiB tmpfs**;
allow that much available RAM in addition to PostgreSQL and test-process memory.
PostgreSQL durability settings remain at their normal defaults. `test-db stop`
removes only this dedicated server/project and **loses all of its disposable
test state**; restarting initializes a fresh cluster. An old runtime file without
the dedicated test port fails with instructions to run `test-db up` rather than
falling back to the development server.

Compose owns the PostgreSQL server/container and `repo.py` owns worktree-specific
server orchestration. pytest owns the scenario/template databases described
below; developers must not manually create or drop them. Stop the dedicated
server only after its test processes finish. `test-db` manages this local
Compose project even when tests are configured to use an explicit server; it
does not start or stop that external server.

Test database configuration is resolved in this order: an explicit
`TEST_POSTGRES_DATABASE_URL`; a complete explicit set of `POSTGRES_USER_TEST`,
`POSTGRES_PASSWORD_TEST`, `POSTGRES_PORT_TEST` and `POSTGRES_DB_TEST`
(`POSTGRES_HOST_TEST` is optional and defaults to `localhost`); then the current
worktree runtime configuration, using its dedicated test-server port and a
derived database name ending in `_tests`. Partial explicit configuration is
rejected, including a lone shell-exported `POSTGRES_PORT_TEST`; the runtime file
is read by the harness and need not be sourced. Explicit test servers remain
supported and need not use tmpfs; the standard performance acceptance
environment uses tmpfs. Credentials remain environment-provided and are not
shown in documentation.

The configured database name must end in `_test` or `_tests`, but it is a
validated routing input, not a shared physical database to reuse or delete.
The connection role must be able to create databases and connect to the
same server's `postgres` admin database. Use a dedicated disposable test
server, never a production target.

### Migrated templates and ownership

Each pytest process that uses PostgreSQL generates unique `portal_<uuid>_tests` and
`portal_<uuid>_template_tests` names. The shared lifecycle owner in
`apps/api/tests/support/postgres.py` creates both and runs real Alembic
`upgrade head` once on the template, including migration seeds. Before each
test that requests `migrated_database`, it replaces its own scenario database
with a fresh template clone. Template connections are closed before cloning;
mutable business data is never stored in the template.

Migration tests retain explicit schema resets and upgrade/downgrade transitions.
The next ordinary test receives a fresh clone even after a migration test has
changed the scenario schema. Business setup, sessions and clients remain
function-scoped; reuse of an engine/session factory does not authorize reuse of
prepared purchases, reconciliations or mutable ORM state across tests.

Destructive operations validate targets before connecting or executing SQL.
The owner records successful creation and cleans up only its own databases,
including after failed setup or test execution. Name collisions fail without
pre-dropping existing data. Pools are disposed before replacement; checked-out
connections and external connection leaks remain failures. Do not hide them
with `DROP ... FORCE`, connection termination or cleanup of another run's data.

### Reports, failures and interruption

Every harness `test api*` invocation prints its unique directory under
`.harness/api-tests/`. It contains partition collection logs/manifests,
`expected.json` assignments, worker `nodeids.txt`, `pytest.log`, `manifest.json`
and `junit.xml`, plus a merged `junit.xml` and `result.json` at the run root.
Inspect the printed path for this invocation, not a prior successful run.

Collection errors, failed/crashed workers, missing reports or differences
between expected IDs, worker collections and JUnit produce a nonzero result.
Failures and skips remain in the merged report. Once the `test` command options
are parsed, a caller-supplied `--junitxml` path is marked incomplete before
worker-count validation and test-environment preparation. Expected startup
failures replace it with a current error; the runner does the same before its
own validation when called directly. Execution replaces it with current results,
so an older success cannot represent the new run. Report-write errors remain
visible failures. If a later worker cannot start, available reports from the
started workers are retained alongside the infrastructure error. Reports
already collected are included only once when execution is interrupted.

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
