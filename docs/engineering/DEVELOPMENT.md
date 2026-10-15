# Development Environment

Status: authoritative
Last verified: 2026-08-28

Use `scripts/repo.py` through root npm commands. It derives a stable worktree ID,
Compose project, database port, and service ports without sharing state with
another worktree.

```bash
npm run repo:doctor
npm run repo:setup
npm run repo:up
```

The harness writes `.harness/runtime.json` and `.harness/runtime.env`; both are
untracked. Use `npm run repo:down` for normal teardown and `npm run repo:reset`
only when disposable database state may be removed.

Lower-level commands are diagnostic interfaces, not substitutes for the
canonical full check:

```bash
npm run dev:web
npm run dev:api
npm run lint:web
npm run test:api
```

## API dependency management

The API uses uv `0.12.7`. `apps/api/pyproject.toml` and `apps/api/uv.lock` are
the dependency source of truth. Repository setup and Docker dependency stages
use the locked uv file.

The only canonical local API environment is `<repository>/.venv`. Repository
tooling selects it explicitly, so do not create `apps/api/.venv` or require
shell activation. Stale environments are never deleted automatically.

After changing an API dependency, update and then check the lock file through
the root npm aliases:

```bash
npm run lock:api
npm run lock:check:api
```

To synchronize the development dependencies into the canonical root
environment, run:

```bash
npm run sync:api
```

The normal repository flow is:

```bash
npm run repo:doctor
npm run repo:setup
npm run repo:up
```

API runtime, migration, test, and build operations are exposed through the
root aliases `dev:api`, `migrate:api`, `test:api:fast`, `test:api:postgres`,
`test:api`, and `build:api`. Repository checks remain `npm run check:fast` and
`npm run check`.

## Minimal Makefile

The Makefile is not a second command surface. It contains only Unix/WSL
convenience shortcuts for the local PostgreSQL test server:

```bash
make test_db_up
make test_db_stop
```

The cross-platform equivalents are:

```bash
python scripts/repo.py test-db up
python scripts/repo.py test-db stop
```

Compose owns the PostgreSQL server/container and `repo.py` owns its
worktree-specific orchestration. pytest owns creation, migration, schema reset,
and teardown of the disposable `_tests` database; developers must not manually
create or drop the physical test database.

For PostgreSQL tests, configuration precedence is: explicit
`TEST_POSTGRES_DATABASE_URL`; complete explicit `POSTGRES_*_TEST` configuration
(partial configuration fails); then the current worktree runtime configuration
with its mapped host port and a derived `_tests` database name. Credentials are
read from the environment and are not documented here.

The normal Unix/WSL PostgreSQL flow is:

```bash
make test_db_up
npm run test:api:postgres
make test_db_stop
```

The complete backend flow uses `npm run test:api` in the middle. The
`test:api:fast` alias remains PostgreSQL-independent.


## Local Kernel Manifest Mock (ANY-664, development only)

**Status: approved requirements for the Step 6 implementation plan; not yet an implemented service or passing contract check.** The real source of product identity is Platform Kernel (`gushinets/anytoolai-platform`), not Portal mock fixtures or UI placeholders.

For local visual development without a running Kernel, Step 6 should provide an **opt-in, separate HTTP mock container** attached to the development Compose network (profile or development-only override). Keep the real Portal backend, PostgreSQL and web frontend running. The mock exposes only the needed versioned, complete internal Capability Manifest API, not a substitute for a whole Kernel or a shared SDK.

- Portal uses **one** production-shaped typed Kernel client for both real and mocked servers. Switch between them **only** via internal service base URL and appropriate credentials/config; there must be **no application-code changes**, mock-specific imports, production fallback to fixtures, or browser calls to mock internals.
- Local mock is **disabled by default**; it can be stopped and removed without preventing Portal builds, database migrations, or normal startup. Missing Kernel must fail closed for **new publication and new purchase admission**, with no source-manifest cache fallback; previously confirmed paid subscriptions are handled by their separate finite trust rules. Mock fixtures are development/test evidence only and cannot establish real-account `SELLABLE` admission.
- No mock process/config/image/test data/auth bypass may be enabled or bundled in production Compose, production API/web image, or production deployment. Add verification that attempts to enable mock mode in production fail explicitly rather than quietly returning fake products.

### Keep the mock aligned with real Kernel

The **implemented, versioned, service-authorized** manifest contract in `gushinets/anytoolai-platform` becomes the source of truth when it exists. Before then, the two approved architectural specs and jointly reviewed fixtures define a **provisional** contract; mock fixtures must **not** be mistaken for a real Kernel API.

Step 6 must deliver a reproducible, small cross-repository conformance check: verify the mock and Portal typed client against the Kernel-owned authoritative OpenAPI/fixtures and their exact pinned Kernel commit. Check schema/required fields, tenant and region, product/metric relationship, enabled semantics, manifest digest/version, auth/HTTP errors and representative current product IDs. When Kernel's actual endpoint lands, run conformance against that implementation, not solely against static mock JSON.

- Run the check for **every relevant Portal PR** and fail on incompatible or invalid fixtures.
- Also detect **upstream changes in Kernel** independently of Portal PRs: use an upstream push/webhook trigger where available, or a bounded scheduled cross-repo drift check that fetches the current Kernel default-branch contract. A pinned fixture checked only in Portal CI cannot detect later Kernel changes.
- Emit an actionable failing status/alert for actual contract incompatibility or unavailable authoritative verification; do not silently classify an old fixture as current or fail for unrelated Kernel commits/new products outside the selected test fixture.
- Keep the mechanism small and use existing repository test/CI practices rather than inventing a general mock framework. Document the chosen trigger, source revision, update procedure and supported compatibility policy in the Step 6 implementation plan.

### Required local verification

Demonstrate the real Portal UI and backend with the optional container for: complete valid manifest, disabled/missing product or metric, malformed/partial/version-incompatible response, unavailable/unauthorized mock, immediate failure of a **new** publication and later recovery on a fresh live read (no retired manifest-LKG freshness rule). Prove the drift check detects an intentionally incompatible Kernel contract change. Demonstrate mock removal and base-URL-only transition to a compatible Kernel test instance, and assert production build/Compose excludes all mock artifacts.

The above is a **delivery requirement of ANY-664**, not evidence that a mock or automatic drift detector currently exists.
