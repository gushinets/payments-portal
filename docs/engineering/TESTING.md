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
Whole modules are assigned greedily by collected case count. pytest may
reorder cases when it collects the assigned tests. Small selections use fewer
processes when there are fewer modules. The runner uses standard-library
subprocesses.

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
command output to `.harness/ci/postgres-pytest.log`. After a successful
PostgreSQL test step, CI uploads the merged JUnit as `postgres-test-results`.
The diagnostics upload includes available files in `.harness/ci/` and
`.harness/api-tests/` on failure or cancellation. Docker logs are collected on
failure. See the [CI workflow](../../.github/workflows/ci.yml) for the
exact commands; local checks do not establish remote CI success.

## Test environment and server lifecycle

API pytest setup installs synthetic settings before application imports and
does not consume the personal dotenv file. Canonical launches, workers and CLI
test children use the shared environment helper in
`apps/api/tests/support/settings.py`. Set scenario-specific overrides explicitly
and restore them after the test. The helper sets `PYTHON_DOTENV_DISABLED=1`,
which makes both the API settings loader and `scripts/repo.py` skip their
default `.env` lookup. Do not configure tests by copying personal or production
values.
The API test environment clears inherited libpq routing variables, including
`PGHOSTADDR` and `PGSERVICE`. Explicit test URLs and service-file locations
remain available.

For the worktree's dedicated test server, first run `docker pull` with the full
PostgreSQL `image` reference, including its digest, from
[`docker-compose.test.yml`](../../docker-compose.test.yml). Do this on a fresh
machine or after the repository changes the pinned image. Once the image is
available locally, run the PostgreSQL partition:

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
`test-db up` uses the local copy of the PostgreSQL image pinned for development.
The launcher derives credentials from the worktree ID. Servers with different
IDs use different credentials even when they reuse the same port. Run
`test-db up` after upgrading from shared test credentials to recreate the
disposable container.

The standard test server stores `/var/lib/postgresql` in a **2 GiB tmpfs**;
allow that much available RAM in addition to PostgreSQL and test-process memory.
PostgreSQL durability settings remain at their normal defaults.
`test-db stop` removes the dedicated Compose project and all its disposable
state. Stop it only after its tests finish. Development data and explicitly
configured external servers have separate lifecycles. pytest owns the
scenario/template databases described below. Leave their creation and cleanup
to pytest.

On case-sensitive filesystems, checkout paths that differ only by letter case
derive the same worktree ID, Compose project, and default test port. Use
checkout paths that differ by more than letter case. Otherwise `test-db stop`
can stop a server shared by both checkouts.
[ANY-892](https://linear.app/paveldik/issue/ANY-892) tracks the collision.

The harness resolves test database settings in this order.

1. An explicit `TEST_POSTGRES_DATABASE_URL`.
2. A complete explicit set of `POSTGRES_USER_TEST`, `POSTGRES_PASSWORD_TEST`,
   `POSTGRES_PORT_TEST` and `POSTGRES_DB_TEST`. `POSTGRES_HOST_TEST` defaults
   to `localhost` when absent or empty. Partial settings, including a lone
   shell-exported `POSTGRES_PORT_TEST`, are rejected.
3. The current worktree's dedicated Compose service. Its settings come from
   the checkout path and the port offset saved in `.harness/runtime.json`.
   A fresh checkout uses the default offset. Test commands leave development
   runtime files untouched, ignore the personal dotenv and verify that Compose
   publishes the expected loopback endpoint.

Configured ports must be between 1 and 65535. The configured database name
must end in `_test` or `_tests`. The fixture validates the name before
generating its own physical database names and rejects a `dbname` query
override. For an explicit connection, confirm the effective host and port,
including any routing overrides in the URL query. The Compose endpoint check
applies only to the worktree fallback. Use a dedicated test server with a role
that can create databases and connect to the `postgres` admin database.
For migration tests, include the username, password and host in the URL
authority so Alembic can initialize application settings. For example,
`postgresql+psycopg://test_user:test_password@localhost:42500/portal_tests`.
The performance target uses the standard tmpfs server. Explicit test
servers may use other storage.

### Recovering worktree runtime metadata

The test commands reject malformed or foreign `runtime.json` files. If only
`runtime.env` survives, restore `runtime.json` with the original offset.
Keep a copy of damaged metadata before restoring it.

To regenerate the metadata for an existing worktree, use the offset passed
to `npm run repo:up -- --port-offset`, or `0` if it used the default.
If only a valid `runtime.env` remains, subtract the default test port reported
by the command below from the saved `POSTGRES_PORT_TEST` value.

```bash
python -c "from scripts.repo import runtime_config; print(runtime_config().test_postgres_port)"
```

From the repository root, restore `runtime.json` with that offset. The example
uses offset `37` and preserves the existing `runtime.env` and its application
settings. Then start the dedicated test server.

```bash
python -c "
import json
import sys
from dataclasses import asdict
from scripts.repo import RUNTIME_JSON, _write_runtime_file, runtime_config

config = runtime_config(int(sys.argv[1]))
_write_runtime_file(RUNTIME_JSON, json.dumps(asdict(config), indent=2) + '\n')
" 37
python scripts/repo.py test-db up
```

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

The runner prints its directory under `.harness/api-tests/`. Open the merged
`junit.xml` and `result.json` for the outcome. Each partition retains its
collection log and `collection/junit.xml` when available. After successful
collection with selected tests, `expected.json` records the worker assignments.
Each `worker-*/` directory contains the selected node IDs, pytest log, manifest
and `junit.xml`. The merged JUnit includes collection-time skips and errors,
with identical cases from both partitions reported once. With `--junitxml`,
the CLI publishes an incomplete report before setup, then replaces it with the
startup error or the finished report. Each write replaces the requested file
after the new XML is complete. If the initial write fails, the CLI stops before
setup and reports that an existing file may be from a previous run. If writing
the startup error fails, the incomplete report remains readable and the CLI
reports both errors. A failed final publication also leaves the incomplete
report readable and makes the command fail.

Harness options are parsed before the CLI writes the incomplete report. An
unknown option or `--workers` without a value can leave a report from a previous
run. Check the process exit status alongside the requested XML.

Collection failures, crashes and missing or inconsistent required reports make
the command fail. After a partial launch or handled cancellation, the runner
merges the readable JUnit files from collection and workers. A worker killed
before writing its report can leave completed tests out of the merged results.
A first interrupt during finalization also records cancellation in the merged
JUnit and `result.json` and publishes the available results.

GitHub Actions can stop the test step before the runner writes the merged JUnit.
Use any individual collection and worker reports already written. The
cancellation diagnostics step is configured to upload available files.

The runner checks JUnit against assigned node IDs and worker exit status, including
skips and setup/teardown errors. With `--pytest-args -x`, each worker can stop
after its first failure. Its manifest confirms the stop and its JUnit must cover
every test through that failure in the worker's collection order. Other workers
and partitions finish normally.

On interruption the runner sends a graceful interrupt and waits up to 15 seconds
for pytest cleanup. It then terminates remaining children and waits up to 5 more
seconds before killing any survivors. On Windows it terminates a child
immediately if `Ctrl-Break` cannot be delivered. It waits for the children to
exit and returns `130` on a handled interruption. When child execution was
interrupted, look for `interrupted.json` in the collection or worker
directories to see whether termination was forced. Report leftovers in
disposable storage and preserve resources owned by other runs.

The PostgreSQL template lifecycle test applies the same bounded cleanup to its
nested pytest processes when a child exceeds its 60-second deadline. On POSIX
the nested child shares the worker's process group and handles only the first
`SIGINT`, allowing fixture cleanup to continue if the worker forwards another.
Deadline failures include the child log, whether termination was forced and
any database names recorded by the child.

## Test fixtures

Use fixtures for resource lifecycles, dependency overrides and environment
changes that require teardown. Reuse the PostgreSQL URL, engine, session
factory, migrated database and rollback-safe session in `apps/api/tests/conftest.py`.

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

Record the commands run, tested revision, outcomes, timings and limitations in
the PR or a separate verification report. Detailed logs, manifests, JUnit and
browser artifacts belong in ignored `.harness/` directories or CI artifacts.

Performance comparisons must retain the same selected inputs, settings and tool
versions. Exclude a warm-up, repeat measurements and report the spread, machine
load, storage, process count and cache conditions. Include collection, database
creation, cloning and cleanup in test wall time. Report server startup
separately. A diagnostic run or local PASS does not establish final timing or
remote CI acceptance.

### Test review checklist

- [ ] Choose the cheapest [test layer](#layers) that exercises the required
  behavior and meaningful failure paths. For each moved, consolidated or
  removed case, record the retained assertion or the retired requirement.
- [ ] Assert observable outcomes. Keep real PostgreSQL, HTTP and browser
  checks where the boundary itself is part of the guarantee.
- [ ] Verify [fixture ownership](#test-fixtures), seed restoration and cleanup
  for resources created by the test.
- [ ] Check [clock and readiness controls](#clocks-readiness-and-stability).
  Preserve real timeout, cancellation and lock tests where timing matters.
- [ ] Run the applicable [canonical checks](#commands). Record results, skips
  and any coverage scope for the tested revision.

Underlying mechanics and guidance: [PostgreSQL database templates](https://www.postgresql.org/docs/18/sql-createdatabase.html),
[Docker tmpfs](https://docs.docker.com/engine/storage/tmpfs/),
[pytest flaky-test guidance](https://docs.pytest.org/en/stable/explanation/flaky.html)
and [Playwright practices](https://playwright.dev/docs/best-practices).
