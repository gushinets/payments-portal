# ANY-307 — Migrate API dependency management from Poetry to uv

## Plan Overview

| Field | Value |
| --- | --- |
| Project | `Payment portal` |
| Ticket | `ANY-307` |
| Validation date | `2026-08-28` |
| Overall status | Step 1 and Step 2 complete; final verification reported passed; changes uncommitted per request |
| Execution order | Sequential only: Step 1 → manual verification → commit → Step 2 → final verification → commit |
| Steps / commits | 2 |
| Primary scope | Poetry → uv migration for API dependency management and all executable Poetry consumers |
| Approved workflow adjustment | Root npm scripts + `scripts/repo.py` are canonical; Makefile must not duplicate them |
| Final Makefile scope | Only `test_db_up` and `test_db_stop` convenience targets |
| Related scope | `ANY-84` — update only the Python Dependabot ecosystem/current-state wording; Trivy/security policy remains outside ANY-307 |
| Recommended branch | `ANY-307` from up-to-date `main` |

## Validation Result

This revised plan was validated against:

- the current Linear description and acceptance criteria for `ANY-307`;
- the current `main` branch of `gushinets/payments-portal`;
- related Payment Portal tickets `ANY-84`, `ANY-92`, `ANY-108`, and completed `ANY-314`;
- the separate planned frontend-lint ticket `ANY-341`;
- current uv and GitHub Dependabot documentation.

The original plan was technically detailed but too broad in Step 2. In particular, the following are removed from ANY-307:

- introducing Prettier;
- adding frontend formatting policy;
- splitting existing Ruff lint/format responsibilities;
- adding a large Makefile quality-command surface;
- adding a second aggregate verification interface;
- reworking frontend test aggregation;
- unrelated frontend tooling contract changes.

Those changes are not required to migrate Poetry to uv and increase overlap with existing quality/tooling work.

The PostgreSQL helper from the original Step 2 is retained because it closes a real local developer gap without moving database lifecycle ownership out of pytest.

---

# Required Linear Reconciliation Before Merge

The current Linear acceptance criteria still explicitly require:

```text
Makefile commands for install, lock, run, test, and migration use uv or the canonical root environment consistently.
make build_api succeeds.
```

The approved decision in this revised plan is different:

```text
scripts/repo.py owns orchestration.
root npm scripts are the canonical developer aliases.
Makefile must not duplicate npm/repo.py commands.
Makefile contains only test_db_up and test_db_stop.
```

Do not silently implement a result that contradicts the ticket text.

Before merge, reconcile the Linear acceptance criteria so they state the final command policy. The intended replacement is conceptually:

```text
- Canonical API install/sync, lock, run, test, migration, and build commands are exposed through root npm scripts and/or scripts/repo.py and do not require shell activation.
- Makefile does not duplicate root npm/repo.py commands.
- Makefile may contain only Unix/WSL-only shortcuts that have no root npm alias, currently test_db_up and test_db_stop.
- npm run build:api succeeds.
```

This plan records the requested architectural decision, but it does not itself mutate the Linear ticket.

---

# Context and Locked Decisions

## 1. Migration scope

`ANY-307` replaces Poetry as the API dependency and virtual-environment manager with uv.

The migration is tooling-only.

It must not change:

- Python runtime version;
- API behavior;
- OpenAPI contracts;
- application runtime behavior;
- database models;
- Alembic migrations;
- direct Python dependency versions;
- frontend runtime behavior;
- CI quality-gate semantics except where dependency installation necessarily changes.

Current dependency source:

```text
apps/api/pyproject.toml
apps/api/poetry.lock
```

Required target:

```text
apps/api/pyproject.toml   # PEP 621
apps/api/uv.lock          # only committed Python dependency lockfile
```

## 2. uv version

Required uv version:

```text
0.12.7
```

Declare it in `apps/api/pyproject.toml` as:

```toml
[tool.uv]
required-version = "==0.12.7"
package = false
```

The API remains a non-package application. Do not introduce a build backend solely to replace Poetry metadata.

## 3. Python version

Python remains:

```text
>=3.12,<3.13
```

Local development and CI remain on Python 3.12.

uv must not silently download another Python runtime as part of normal repository setup. Local setup must use the already validated Python 3.12 interpreter. CI must continue using `actions/setup-python` for Python 3.12. Docker must use the existing Python base image.

## 4. Direct dependency version policy

Every direct production and development dependency version must remain unchanged.

Production dependencies remain exactly:

```text
alembic==1.18.5
email-validator==2.3.0
fastapi==0.141.1
httpx==0.28.1
opentelemetry-api==1.44.0
opentelemetry-exporter-otlp-proto-http==1.44.0
opentelemetry-instrumentation-fastapi==0.65b0
opentelemetry-instrumentation-sqlalchemy==0.65b0
opentelemetry-sdk==1.44.0
prometheus-client==0.26.0
psycopg[binary]==3.3.4
python-dotenv==1.2.2
sqlalchemy==2.0.51
uvicorn[standard]==0.52.1
pydantic==2.13.4
pydantic-settings==2.15.0
```

Development dependencies remain exactly:

```text
httpx2==2.10.0
pytest==9.1.1
ruff==0.15.22
polyfactory==3.3.0
pytest-cov==7.1.0
```

Do not add a transitive package as a direct dependency merely to force uv to reproduce Poetry's transitive resolution.

If the resolver produces a transitive-version difference, record the exact old/new version and reason observable from the lockfiles.

## 5. Canonical local environment

The only canonical local Python environment is:

```text
<repository>/.venv
```

Do not create:

```text
apps/api/.venv
```

Do not require:

```bash
source .venv/bin/activate
```

Because the uv project lives in `apps/api`, uv would normally use `apps/api/.venv`. Repository tooling must therefore explicitly set:

```text
UV_PROJECT_ENVIRONMENT=<absolute repository root>/.venv
```

for project-environment operations.

`scripts/repo.py` remains the owner of this orchestration.

## 6. Canonical command policy

The repository already treats root npm scripts backed by `scripts/repo.py` as the canonical cross-platform interface.

Preserve that model.

Final policy:

```text
npm scripts
    -> scripts/repo.py for repository/Python orchestration
    -> existing workspace scripts for frontend operations

Makefile
    -> Unix/WSL convenience only
    -> no duplicate aliases for commands already exposed through npm
    -> only test_db_up / test_db_stop after this ticket
```

Do not turn the Makefile into another command catalog.

Do not add `make help` for two targets.

## 7. Test PostgreSQL ownership

Reuse the existing `postgres` service from:

```text
docker-compose.yml
```

and the current worktree-aware Compose harness.

The repository command owns only the PostgreSQL **server** lifecycle:

```text
start server
stop server
```

The existing pytest fixtures continue to own:

- validating `_test` / `_tests` database safety;
- creating the physical test database;
- dropping/recreating schemas;
- applying Alembic migrations;
- dropping the physical test database after the test session.

Do not create a second PostgreSQL service.

Do not create/drop the physical test database in Makefile or `repo.py`.

Intended Unix/WSL local flow:

```bash
make test_db_up
npm run test:api:postgres
make test_db_stop
```

Complete backend suite:

```bash
make test_db_up
npm run test:api
make test_db_stop
```

Cross-platform equivalent for starting/stopping the server remains available directly through `scripts/repo.py`.

## 8. CI ownership boundary

`ANY-92` already established the Payment Portal quality gate.

ANY-307 must migrate dependency installation from Poetry to uv without redesigning:

- job boundaries;
- coverage behavior;
- PostgreSQL production gate;
- Docker validation;
- browser coverage;
- artifact behavior.

If a CI job currently installs API dependencies but does not actually use host-installed API dependencies, remove the unnecessary dependency install rather than mechanically replacing it with another install.

## 9. Docker ownership boundary

`ANY-314` is completed. Preserve the **current** API Python base image and digest from `main`.

ANY-307 changes only dependency installation.

Do not reopen base-image security work, Trivy baseline work, or image-version upgrades.

Production must install production dependencies only.

Development must include the dev dependency group.

The final production image must contain neither Poetry nor uv.

## 10. Dependabot / ANY-84 boundary

Change only the API Python Dependabot package ecosystem from:

```yaml
package-ecosystem: "pip"
```

to:

```yaml
package-ecosystem: "uv"
```

Preserve:

- directory `/apps/api`;
- schedule;
- group configuration;
- commit-message prefix;
- all unrelated ecosystems.

`ANY-84` continues to own:

- dependency-update policy;
- Trivy scanning;
- security thresholds;
- security workflow behavior.

The active `ANY-84` execution-plan wording that describes Poetry through the `pip` ecosystem becomes stale after this migration and may be factually reconciled in the documentation step.

Do not change Trivy policy.

Do not add a local workaround for Dependabot's uv updater behavior.

Keep the known `dependabot/dependabot-core#15842` risk documented as an upstream risk only.

## 11. Frontend tooling boundary

Do not add Prettier in ANY-307.

Do not add a new frontend formatter.

Do not alter the existing ESLint/typecheck/test split except for root script changes strictly required to eliminate command duplication or keep existing commands working.

Do not implement work belonging to separate frontend quality/tooling tickets such as `ANY-341`.

---

# Out of Scope

Do not:

- upgrade Python;
- upgrade direct Python dependencies;
- upgrade FastAPI, SQLAlchemy, Pydantic, Uvicorn, Alembic, Psycopg, or pytest tooling;
- change API endpoints or contracts;
- change OpenAPI;
- change database schema;
- add Alembic revisions;
- refactor application/domain code;
- move `apps/api/pyproject.toml` to repository root;
- introduce another local virtualenv;
- automatically delete stale virtualenvs;
- change Docker base-image digest;
- change Trivy policy;
- implement Dependabot upstream workarounds;
- add Prettier;
- add Black, isort, mypy, or pyright;
- change backend formatting policy;
- add a new frontend-test aggregate;
- create another aggregate verification command;
- redesign worktree isolation;
- replace the current repository harness architecture.

---

# Step 1 — Atomically migrate API dependency tooling to uv and simplify local command surfaces

**Status:** `done`
**Commit:** `chore(api): migrate dependency management to uv`

## Prompt

Implement Step 1 of ANY-307.

Atomically replace Poetry with uv across project metadata, lockfile, local setup, executable repository commands, CI, Docker, and Python Dependabot while preserving application behavior and direct dependency versions.

At the same time, remove duplicated Makefile API aliases and keep the Makefile as a minimal Unix/WSL-only interface containing only the local test-PostgreSQL server lifecycle targets.

Do not add frontend formatting/lint tooling.

Do not run the automated verification commands listed in the manual-verification section during implementation.

## Relevant existing code

Work primarily in:

- `apps/api/pyproject.toml`
- `apps/api/poetry.lock`
- `scripts/repo.py`
- `package.json`
- `Makefile`
- `.github/workflows/ci.yml`
- `.github/dependabot.yml`
- `apps/api/Dockerfile`
- `docker-compose.yml`
- `docker-compose.agent.yml`
- `apps/api/tests/conftest.py`
- `apps/api/tests/support/postgres.py`
- `apps/api/tests/compatibility/test_python_dependency_contracts.py`
- `apps/api/tests/test_repository_docs.py`
- `apps/api/tests/test_deployment_contract.py`

Preserve the existing worktree-aware harness architecture built around:

- `runtime_config(...)`
- `write_runtime(...)`
- `compose_command(...)`
- `read_runtime_env(...)`
- `canonical_check_environment(...)`
- `direct_api_environment(...)`
- `api_test_marker_args(...)`
- `cmd_test(...)`
- `reexec_in_repository_venv_if_required(...)`

## Implementation

### 1. Convert `apps/api/pyproject.toml` to PEP 621

Replace Poetry metadata with standard PEP 621 metadata.

Required shape:

```toml
[project]
name = "payments-portal-api"
version = "0.1.0"
description = "AnytoolAI Payments Portal API"
requires-python = ">=3.12,<3.13"
dependencies = [
    # exact existing production versions
]

[dependency-groups]
dev = [
    # exact existing development versions
]

[tool.uv]
package = false
required-version = "==0.12.7"
```

Preserve the existing Ruff configuration.

Remove the Poetry build-system configuration.

Do not introduce another build backend.

### 2. Replace `poetry.lock` with `uv.lock`

Using uv `0.12.7`, generate:

```text
apps/api/uv.lock
```

Before deleting the old lockfile, compare the resolved package/version sets.

Requirements:

- every direct production version is unchanged;
- every direct dev version is unchanged;
- every actual transitive version difference is recorded;
- no artificial direct dependencies are added to reproduce Poetry's transitive lock.

Then remove:

```text
apps/api/poetry.lock
```

Final repository state must contain only one committed Python lockfile:

```text
apps/api/uv.lock
```

Generating the required lockfile and comparing lock contents are allowed implementation operations.

### 3. Add a single uv environment helper to `scripts/repo.py`

Do not scatter uv environment construction across commands.

Introduce one focused helper for uv subprocesses that:

- starts from the caller/process environment;
- sets `UV_PROJECT_ENVIRONMENT` to the absolute repository-root `.venv`;
- targets the already validated local Python 3.12 interpreter for environment creation/sync;
- disables automatic Python downloads for repository-managed operations;
- does not depend on an activated virtualenv.

Do not use `VIRTUAL_ENV` as the mechanism for selecting the uv project environment.

Do not create `apps/api/.venv`.

### 4. Migrate `cmd_doctor(...)`

`doctor` must:

- require uv instead of Poetry;
- verify Python 3.12;
- verify that installed uv satisfies the project `required-version` constraint;
- require `apps/api/uv.lock`;
- stop requiring `apps/api/poetry.lock`;
- allow root `.venv` to be absent on a fresh checkout;
- recognize root `.venv` as canonical when present;
- detect `apps/api/.venv` as a conflicting local environment and report it clearly;
- never delete either environment automatically.

Keep the existing Git, Node, npm, Docker, Compose, and worktree-port checks.

### 5. Migrate `cmd_setup(...)`

`setup` must:

- stop invoking `python -m venv`;
- stop invoking Poetry;
- stop setting Poetry-specific environment variables;
- run a locked uv sync against `apps/api/pyproject.toml` / `apps/api/uv.lock`;
- explicitly target repository-root `.venv`;
- use Python 3.12 already present on the system rather than silently downloading another runtime;
- preserve `npm ci`;
- preserve Playwright installation;
- preserve runtime configuration generation.

The normal setup remains:

```bash
npm run repo:setup
```

### 6. Add focused API dependency commands to `repo.py`

Provide explicit repository operations so package scripts do not need platform-specific environment-variable syntax.

Expose commands equivalent to:

```bash
python scripts/repo.py sync-api
python scripts/repo.py lock-api
python scripts/repo.py check-api-lock
```

Required semantics:

```text
sync-api
    locked uv sync
    targets repository-root .venv
    includes default dev dependency group

lock-api
    intentional mutating uv lock update
    does not silently upgrade direct constraints

check-api-lock
    uv lock --check equivalent
    does not modify uv.lock
```

Reuse the same uv subprocess/environment helper as setup.

Do not create an independent dependency-management implementation for each command.

### 7. Preserve API run/migration execution through the root environment

Keep the existing `dev-api` behavior and root-`.venv` re-execution architecture.

Add a canonical repository migration command equivalent to:

```bash
python scripts/repo.py migrate-api
```

It must:

- run Alembic through the repository-root Python environment;
- use the existing direct local API environment derivation;
- not require shell activation;
- not alter Alembic migration content or runtime migration ownership.

Add `migrate-api` to root-`.venv` re-execution where required.

### 8. Expose the complete API test target

`api_test_marker_args(...)` already supports:

```text
api
```

Expose it in the CLI parser so:

```bash
python scripts/repo.py test api
```

runs the complete backend test suite.

Preserve existing meanings:

```text
api-fast
api-postgres
```

### 9. Add isolated local test-PostgreSQL server lifecycle

Add repository commands:

```bash
python scripts/repo.py test-db up
python scripts/repo.py test-db stop
```

`test-db up` must:

1. create/read the current worktree runtime configuration;
2. write the normal protected harness runtime files;
3. invoke the existing Compose files/project through `compose_command(...)`;
4. start only the existing `postgres` service;
5. use the worktree-specific host PostgreSQL port and project name;
6. wait for the existing PostgreSQL healthcheck before returning success.

Prefer Compose's native wait/health behavior instead of adding a second custom PostgreSQL polling loop.

Do not start:

```text
migrate
api
web
caddy
observability
```

`test-db stop` must:

- stop only the current worktree's `postgres` service;
- preserve its named volume;
- not use `down --volumes`;
- not affect another worktree.

### 10. Make PostgreSQL test targets use the worktree-local server when appropriate

For:

```text
test api-postgres
test api
```

configuration precedence must be explicit.

Use this order:

1. If `TEST_POSTGRES_DATABASE_URL` is explicitly set, preserve it unchanged.
2. Else, if explicit `POSTGRES_*_TEST` configuration is present, preserve that mode; do not silently replace it with a derived URL. If only part of the required explicit configuration is present, fail with a clear configuration error rather than silently ignoring it.
3. Else, derive the local test URL from the current worktree `.harness/runtime.env`.

The derived URL must use:

- `127.0.0.1`;
- worktree-specific mapped `POSTGRES_PORT`;
- configured worktree PostgreSQL username;
- configured worktree PostgreSQL password;
- worktree application database name with `_tests` appended.

Conceptually:

```text
payments_<worktree> -> payments_<worktree>_tests
```

Reuse existing URL escaping/building utilities.

Do not hardcode a worktree database name.

The existing pytest fixture remains the only owner of physical test database create/drop and schema reset/migration behavior.

If a derived local server is required but unavailable, fail with an actionable message such as:

```text
Start the local test PostgreSQL server with:
  python scripts/repo.py test-db up
Unix/WSL shortcut:
  make test_db_up
```

`api-fast` must remain PostgreSQL-independent.

### 11. Make root npm scripts the canonical user-facing aliases

Preserve the existing canonical npm/repo model.

Keep existing scripts where already correct and add/update only the missing API aliases necessary to replace the old Makefile surface.

Final root script surface should include equivalents of:

```text
repo:doctor
repo:setup
repo:up
repo:down
repo:reset

sync:api
lock:api
lock:check:api

dev:api
migrate:api

test:api:fast
test:api:postgres
test:api

build:api

check:fast
check
```

Required mappings:

```text
sync:api            -> python scripts/repo.py sync-api
lock:api            -> python scripts/repo.py lock-api
lock:check:api      -> python scripts/repo.py check-api-lock
migrate:api         -> python scripts/repo.py migrate-api
test:api:fast       -> python scripts/repo.py test api-fast
test:api:postgres   -> python scripts/repo.py test api-postgres
test:api            -> python scripts/repo.py test api
build:api            -> existing docker compose API build behavior
```

In particular, replace the current ambient:

```text
pytest apps/api/tests
```

implementation of `npm run test:api`.

Do not duplicate pytest arguments in package scripts.

### 12. Reduce Makefile to non-duplicated Unix/WSL shortcuts only

Remove the old duplicated targets:

```text
run_api
test_api
migrate_api
lock_api
install_api
build_api
```

Remove all Poetry variables and virtualenv-shell path logic from Makefile.

Final Makefile target surface:

```text
test_db_up
test_db_stop
```

Semantics:

```text
test_db_up
    -> python scripts/repo.py test-db up

test_db_stop
    -> python scripts/repo.py test-db stop
```

Declare them `.PHONY`.

Do not add npm aliases for these two targets in this ticket; keeping them as the only Makefile-only Unix/WSL convenience is intentional.

Do not add format, lint, test, build, docs, generate, architecture, or aggregate aliases to Makefile when npm/repo commands already exist.

### 13. Migrate GitHub Actions from Poetry to uv

Update every job that genuinely requires host API dependencies.

Remove:

- Poetry installation;
- Poetry commands;
- `POETRY_VIRTUALENVS_CREATE`;
- Poetry-specific environment configuration.

Preserve:

```text
actions/setup-python
Python 3.12
```

Use the official uv setup action pinned to:

```text
c771a70e6277c0a99b617c7a806ffedaca235ff9
```

corresponding to `astral-sh/setup-uv` v9.0.0, and configure uv `0.12.7`.

Cache dependency invalidation must include:

```text
apps/api/uv.lock
```

Where host API dependencies are required, CI must:

```text
uv lock freshness check
-> locked uv sync into repository-root .venv
-> existing checks through the canonical environment
```

Use an explicit CI `UV_PROJECT_ENVIRONMENT` pointing to repository-root `.venv`.

Do not rely on shell activation.

Inspect each job instead of blindly replacing Poetry:

- `quality`: host API dependencies are required; migrate to uv.
- `production-gate`: host API dependencies are required for PostgreSQL pytest/Alembic checks; migrate to uv.
- `browser`: remove the current host Poetry dependency installation if no host API dependency is actually executed before the Docker-backed stack is used. Do not add a pointless uv sync just to mirror the old step.
- `harness-smoke`: do not add API dependency installation unless the job actually requires it.

Preserve job boundaries and existing verification behavior.

### 14. Migrate Docker dependency installation

Update:

```text
apps/api/Dockerfile
```

Preserve the current Python base image and digest from `main`.

Do not perform base-image updates owned by the already completed `ANY-314` work.

Use official uv `0.12.7` only in dependency-builder stages.

Repository policy already pins important container inputs by digest. Resolve the real uv image digest during implementation and pin the uv source reproducibly; do not invent a digest in this plan.

In dependency-builder stages:

- use `/opt/api-venv` as the explicit uv project environment;
- disable uv Python downloads;
- use the base image's Python 3.12;
- copy `apps/api/pyproject.toml` and `apps/api/uv.lock` before application source;
- preserve dependency-layer caching;
- use locked uv sync.

Production dependencies:

```text
exclude dev group
```

Development dependencies:

```text
include dev group
```

Keep the current final runtime-stage design where only the prepared environment crosses from the dependency stage.

Do not copy uv into the final production image.

Final production image must contain neither:

```text
poetry
uv
```

Do not copy host `.venv` into Docker.

### 15. Migrate Python Dependabot from `pip` to `uv`

Update only the API Python ecosystem entry in:

```text
.github/dependabot.yml
```

Change:

```yaml
package-ecosystem: "pip"
```

into:

```yaml
package-ecosystem: "uv"
```

Preserve all other fields and ecosystems.

Do not add ignores/workarounds for `dependabot/dependabot-core#15842`.

### 16. Update tooling contract coverage

Adapt existing tests rather than deleting them.

Update `apps/api/tests/compatibility/test_python_dependency_contracts.py` so it verifies at least:

- PEP 621 production dependency set;
- `[dependency-groups].dev` dependency set;
- exact direct versions;
- Python `>=3.12,<3.13`;
- `[tool.uv].package = false`;
- `[tool.uv].required-version = "==0.12.7"`;
- test tooling remains outside production dependencies;
- Docker production sync excludes the dev group;
- Docker dependency installation is locked;
- Docker no longer installs/uses Poetry;
- final production runtime does not receive uv.

Extend focused repository-tooling coverage for:

- CLI accepts `test api`;
- `sync-api`, `lock-api`, `check-api-lock`, and `migrate-api` parse correctly;
- uv project environment points to root `.venv`;
- `apps/api/.venv` is detected as a conflict by doctor;
- `test-db up` targets only `postgres`;
- `test-db stop` targets only `postgres` and does not delete volumes;
- explicit `TEST_POSTGRES_DATABASE_URL` wins;
- explicit complete `POSTGRES_*_TEST` configuration is preserved;
- partial explicit `POSTGRES_*_TEST` configuration is rejected clearly;
- derived DB name ends in `_tests`;
- derived URL uses worktree mapped port;
- `api-fast` does not require PostgreSQL;
- Makefile contains only the two intended non-duplicated test DB targets.

Update deployment/repository-doc contract tests only where they encode Poetry or old Makefile behavior.

Do not modify application behavior tests.

### 17. Keep the production diff tooling-only

Do not modify modules under:

```text
apps/api/app/
```

unless an unavoidable generated artifact is mechanically affected, which is not expected.

No domain/service/router/model changes are expected.

## Allowed implementation operations

The implementation agent may perform operations required to create dependency artifacts:

```text
generate apps/api/uv.lock with uv 0.12.7
compare poetry.lock and uv.lock package/version sets
update package-manager lock artifacts required by the implementation
```

Do not run the manual verification suite below during implementation.

## After implementation — report

Report:

1. all files changed;
2. final PEP 621 structure;
3. confirmation that every direct dependency version is unchanged;
4. every transitive old/new version difference;
5. exact implementation of root `.venv` selection;
6. how Python downloads are prevented in normal repository operations;
7. how `repo:setup` works after migration;
8. final root npm API command surface;
9. final two-target Makefile;
10. how local test PostgreSQL startup works;
11. exact configuration precedence for PostgreSQL tests;
12. confirmation that pytest still owns physical test DB lifecycle;
13. how CI rejects a stale uv lock;
14. which CI jobs sync API dependencies and which obsolete install was removed;
15. how production Docker excludes dev dependencies;
16. how the final production image avoids Poetry and uv;
17. confirmation that Dependabot changed from `pip` to `uv`;
18. any implementation concern not covered by this plan;
19. exact manual checks to run.

## Manual verification after Step 1

Run manually:

```bash
uv --version

npm run repo:doctor
npm run repo:setup

npm run lock:check:api
npm run sync:api

npm run test:api:fast

make test_db_up
npm run test:api:postgres
npm run test:api
make test_db_stop

npm run check:fast

npm run build:api
```

Then verify lock stability:

```bash
cp apps/api/uv.lock /tmp/uv.lock.before
npm run lock:api
cmp /tmp/uv.lock.before apps/api/uv.lock
```

If `/tmp` is unsuitable on the current platform, compare with the platform-appropriate temporary path or `git diff -- apps/api/uv.lock`.

Also inspect:

```bash
git diff -- apps/api/pyproject.toml apps/api/uv.lock apps/api/poetry.lock
```

Confirm:

```text
apps/api/poetry.lock is deleted
apps/api/uv.lock is committed
no apps/api/.venv was created
Makefile contains only test_db_up and test_db_stop
```

If any check fails, report the exact failure before Step 2.

## Commit

```text
chore(api): migrate dependency management to uv
```

---

# Step 2 — Reconcile documentation and final migration evidence

**Status:** `done`
**Commit:** `Not committed (per request)`

## Prompt

Implement Step 2 of ANY-307.

Update canonical developer/agent documentation to describe uv, repository-root `.venv`, root npm/repo.py commands, the minimal Makefile, local PostgreSQL test-server startup, and the Python Dependabot `uv` ecosystem.

Remove obsolete active Poetry instructions without rewriting historical completed plans merely because they mention Poetry.

Do not add new tooling in this step.

## Relevant documentation

Review and update only where relevant:

- `README.md`
- `AGENTS.md`
- `apps/api/AGENTS.md`
- `docs/engineering/DEVELOPMENT.md`
- `docs/engineering/TESTING.md`
- `docs/exec-plans/active/ANY-84-dependency-container-scanning.md`
- the checked-in ANY-307 execution plan, if present

Also inspect current executable surfaces for stale active Poetry instructions:

- `scripts/repo.py`
- `package.json`
- `Makefile`
- `apps/api/pyproject.toml`
- `apps/api/Dockerfile`
- `.github/workflows/ci.yml`
- `.github/dependabot.yml`

## Implementation

### 1. Document uv as the only API dependency manager

Document:

```text
uv 0.12.7
```

as the required manager.

Source of truth:

```text
apps/api/pyproject.toml
apps/api/uv.lock
```

Remove active instructions that require Poetry.

### 2. Document the root `.venv` policy

State clearly:

```text
<repository>/.venv
```

is the only canonical local API environment.

Do not create:

```text
apps/api/.venv
```

Normal commands do not require shell activation.

Document that repository tooling explicitly selects the root environment.

Do not document automatic deletion of stale environments.

### 3. Document one canonical command path

The normal developer flow must be obvious:

```bash
npm run repo:doctor
npm run repo:setup
npm run repo:up
```

API dependency operations:

```bash
npm run sync:api
npm run lock:api
npm run lock:check:api
```

API runtime/migration/test/build:

```bash
npm run dev:api
npm run migrate:api
npm run test:api:fast
npm run test:api:postgres
npm run test:api
npm run build:api
```

Repository checks remain:

```bash
npm run check:fast
npm run check
```

Do not present equivalent Makefile aliases for these commands.

### 4. Document the intentionally minimal Makefile

Explain that Makefile is not a second command surface.

It exists only for Unix/WSL convenience around local test PostgreSQL server lifecycle:

```bash
make test_db_up
make test_db_stop
```

Cross-platform equivalent:

```bash
python scripts/repo.py test-db up
python scripts/repo.py test-db stop
```

Do not document removed Makefile targets.

### 5. Document PostgreSQL test ownership

Normal Unix/WSL flow:

```bash
make test_db_up
npm run test:api:postgres
make test_db_stop
```

Complete backend suite:

```bash
make test_db_up
npm run test:api
make test_db_stop
```

Explain:

- Compose owns the PostgreSQL server/container;
- `repo.py` owns worktree-specific server orchestration;
- pytest owns the disposable `_tests` database lifecycle;
- developers must not manually create/drop the physical test database.

Document explicit test DB configuration precedence at a practical level without exposing credentials.

### 6. Preserve test boundaries

Keep the existing distinction between:

```text
api-fast
api-postgres
api full suite
frontend tests
browser E2E
```

Do not add frontend formatting or a new test aggregate in this ticket.

### 7. Reconcile ANY-84 current-state wording only

The active `ANY-84` execution plan currently describes Python Dependabot as Poetry through the `pip` ecosystem.

After ANY-307, update only that fact to the actual `uv` ecosystem.

Preserve:

- schedule;
- grouping;
- Trivy rules;
- thresholds;
- security policy;
- other ecosystems.

Mention `dependabot/dependabot-core#15842` only as a known upstream risk if useful.

Do not implement a workaround.

### 8. Record actual migration facts in the ANY-307 plan

Record after implementation:

- actual transitive dependency differences, if any;
- final uv version;
- final setup-uv action version/commit;
- final uv Docker image reference/digest;
- final root `.venv` behavior;
- final Dependabot ecosystem;
- final npm API command names;
- final Makefile targets;
- actual CI jobs that sync host API dependencies.

Do not rewrite locked architectural decisions to hide implementation deviations.

### 9. Remove obsolete active Poetry workflow references

There must be no active requirement for:

```text
poetry
poetry.lock
POETRY_VIRTUALENVS_CREATE
poetry install
poetry lock
```

Historical migration context may still mention Poetry where historically accurate.

Do not rewrite completed historical execution plans just to make global text search return zero results.

## Step 2 implementation evidence

Recorded on 2026-08-28 from the committed Step 1 implementation:

- The final uv version is `0.12.7`. GitHub Actions uses
  `astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9` (v9.0.0).
- The dependency-builder uses
  `ghcr.io/astral-sh/uv:0.12.7@sha256:95f2aa1fe59274951cfe9b0cbc7972e879ff1004bc8945d130a32eb0dbd85945`.
- The uv lock comparison found no direct dependency version changes. The
  unconstrained transitive resolutions changed as follows: `charset-normalizer`
  3.4.9 → 3.5.1, `click` 8.4.2 → 8.5.0, `faker` 40.36.0 → 40.37.0,
  `googleapis-common-protos` 1.75.1 → 1.75.2, `idna` 3.18 → 3.19,
  `protobuf` 7.35.1 → 7.36.0, `pygments` 2.20.0 → 2.21.0,
  `typing-inspection` 0.4.3 → 0.4.4, and `websockets` 17.0.1 → 17.1.
  These are resolver-selected transitive updates; the old and new lockfiles
  contain no changed direct constraints. `payments-portal-api` 0.1.0 is uv's
  root project entry, not a transitive dependency.
- Repository-managed uv subprocesses use `uv_environment`, which removes
  ambient `VIRTUAL_ENV`, sets `UV_PROJECT_ENVIRONMENT` to the resolved
  repository-root `.venv`, sets `UV_PYTHON` to the validated Python 3.12
  executable, and sets `UV_PYTHON_DOWNLOADS=never`. Docker and CI also disable
  uv Python downloads explicitly.
- `repo:setup` validates Python 3.12 and uv, runs the locked development sync
  into the root `.venv`, preserves `npm ci` and Playwright installation, and
  regenerates the worktree runtime configuration.
- The final API npm aliases are `sync:api`, `lock:api`, `lock:check:api`,
  `dev:api`, `migrate:api`, `test:api:fast`, `test:api:postgres`, `test:api`,
  and `build:api`. The Makefile contains only `test_db_up` and `test_db_stop`.
- Local test PostgreSQL startup uses the current worktree's existing Compose
  `postgres` service, its worktree-specific project and mapped port, and
  Compose health waiting. `repo.py` starts/stops only that server service and
  pytest owns the physical `_tests` database lifecycle.
- CI syncs host API dependencies in `quality`, `production-gate`, and `browser`.
  Each validates `apps/api/uv.lock` before a locked sync into the
  repository-root `.venv`. The browser E2E suite has a host-side API Python
  fixture and therefore requires the canonical repository-root `.venv`;
  `harness-smoke` does not sync API dependencies.
- Dependabot's API Python ecosystem is `uv`; its schedule, grouping, commit
  prefix, other ecosystems, and Trivy/security policy remain unchanged.

## Scope constraints

Do not:

- change runtime behavior;
- change Python dependencies;
- regenerate locks unnecessarily;
- change application code;
- change migrations;
- change security policy;
- add Prettier;
- add formatting/lint tools;
- reintroduce removed Makefile aliases;
- rename canonical commands without a concrete correctness problem.

## After implementation — report

Report:

1. every documentation file changed;
2. where uv version requirements are documented;
3. where root `.venv` policy is documented;
4. where dependency sync/lock/check commands are documented;
5. where the minimal Makefile policy is documented;
6. where the PostgreSQL test flow is documented;
7. what was reconciled in ANY-84;
8. all remaining active Poetry references and why each is valid;
9. whether Linear acceptance criteria were reconciled with the final no-duplicate-Makefile decision;
10. exact final verification commands.

## Manual final verification

Verification status recorded on 2026-08-28: user reported that all checks
passed. The commands were run by the user, not by the implementation agent.

Run manually:

```bash
npm run repo:doctor
npm run repo:setup

npm run lock:check:api

npm run test:api:fast

make test_db_up
npm run test:api:postgres
npm run test:api
make test_db_stop

npm run docs:check
npm run generate:check
npm run architecture:check

npm run check:fast
npm run check

npm run build:api
npm run build:web
```

Verify the isolated development stack and existing health endpoints:

```bash
npm run repo:up
```

Confirm API liveness/readiness using the current worktree runtime configuration, then run browser verification if the environment is prepared for it:

```bash
npm run test:e2e
```

Finally stop the isolated stack through:

```bash
npm run repo:down
```

Inspect the final diff and confirm:

```text
apps/api/poetry.lock is deleted
apps/api/uv.lock is committed
no executable workflow requires Poetry
no apps/api/.venv is created
Makefile contains only test_db_up and test_db_stop
root npm/repo.py commands are the canonical API workflow
no Prettier/frontend-formatting scope was added
Trivy/security policy is unchanged
application/API/schema behavior is unchanged
```

## Commit

```text
docs(tooling): document canonical uv workflow
```

---

# Final Acceptance Checklist for the Revised Plan

The implementation is complete only when all of the following are true:

- [ ] `apps/api/pyproject.toml` uses PEP 621.
- [ ] `[tool.uv].package = false`.
- [ ] `[tool.uv].required-version = "==0.12.7"`.
- [ ] Python remains `>=3.12,<3.13`.
- [ ] All direct production dependency versions are unchanged.
- [ ] All direct dev dependency versions are unchanged.
- [ ] `apps/api/uv.lock` is committed.
- [ ] `apps/api/poetry.lock` is removed.
- [ ] No second Python lockfile exists.
- [ ] Normal local uv sync targets repository-root `.venv` explicitly.
- [ ] Normal repository tooling does not create `apps/api/.venv`.
- [ ] Normal API commands do not require shell activation.
- [ ] `repo:doctor` requires uv and no longer requires Poetry.
- [ ] `repo:setup` uses locked uv sync.
- [ ] `npm run test:api` uses `scripts/repo.py test api`.
- [ ] Fast and PostgreSQL API test aliases are available through npm.
- [ ] API sync/lock/lock-check/migration/build capabilities are available without Makefile duplication.
- [ ] Makefile contains only `test_db_up` and `test_db_stop`.
- [ ] `test_db_up` starts only the current worktree's existing PostgreSQL service and waits for health.
- [ ] `test_db_stop` stops only that PostgreSQL service and preserves its volume.
- [ ] Explicit `TEST_POSTGRES_DATABASE_URL` remains highest priority.
- [ ] Existing explicit `POSTGRES_*_TEST` mode is preserved.
- [ ] Worktree-local test URL derivation uses a `_tests` database and mapped host port.
- [ ] pytest remains sole owner of physical test DB create/drop and schema reset/migrations.
- [ ] CI uses pinned uv `0.12.7` where host API dependencies are required.
- [ ] CI rejects a stale/missing uv lock.
- [ ] CI cache invalidation includes `apps/api/uv.lock`.
- [ ] Unnecessary browser-job host API dependency installation is removed if confirmed unused.
- [ ] Docker production dependency sync excludes dev dependencies.
- [ ] Docker development dependency sync includes dev dependencies.
- [ ] Docker preserves the current Python base image/digest.
- [ ] Final production image contains neither Poetry nor uv.
- [ ] Dependabot API Python ecosystem is `uv`.
- [ ] Dependabot schedule/group/prefix and other ecosystems are unchanged.
- [ ] Trivy/security policy is unchanged.
- [ ] Active ANY-84 wording is factually reconciled without expanding its policy.
- [ ] No Prettier or unrelated frontend tooling is added.
- [ ] No application/domain/API/OpenAPI/schema behavior changes are introduced.
- [ ] Linear ANY-307 acceptance criteria are reconciled with the approved minimal-Makefile policy before merge.
