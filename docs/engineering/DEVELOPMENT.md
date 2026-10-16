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

**Status: ANY-664 implementation Step 1 adds the standalone mock and provisional contract/test source; human verification is pending.** The real source of product identity is Platform Kernel (`gushinets/anytoolai-platform`), not Portal mock fixtures or UI placeholders. All ANY-664 implementation belongs to this Portal repository. Real Kernel producer delivery and actual-producer conformance are later enablement gates, not prerequisites for completing the Portal ticket.

The [provisional manifest contract](../contracts/kernel-capability-manifest/v1/README.md) records the source pins, complete six-product test deployment, TEST-ONLY metric, provisional bearer/digest conventions, startup scenarios and exact manual commands. Start the standalone server from the Portal root:

```bash
APP_ENV=development KERNEL_MOCK_TOKEN=local-kernel-test-only \
  ./.venv/bin/python -m tools.kernel_manifest_mock --port 8091 --scenario valid
```

The same standalone server serves read-only [Swagger UI](http://127.0.0.1:8091/docs) at `/docs` and OpenAPI 3.1 at `/openapi.json`, without credentials in either document. Its manifest response schema comes directly from the versioned JSON Schema; bearer auth and scope are documented, and the existing manifest restrictions remain unchanged. Swagger UI uses pinned `swagger-ui-dist@5.32.15` CSS/JS from jsDelivr, so rendering the UI requires browser access to that CDN. The local OpenAPI JSON has no CDN dependency.

The mock uses the standard-library `ThreadingHTTPServer`; an actively delayed manifest request does not block `/docs` or `/openapi.json`. Existing service-auth, exact-scope, browser-origin and explicit development/test startup restrictions remain in place.

For local visual development, later ANY-664 implementation adds an **opt-in, separate HTTP mock container** on the development Compose network and the real Portal backend/PostgreSQL/localized frontend walkthrough. Step 1 does not wire a Portal client, Compose or the Portal browser. The mock exposes the manifest and local documentation routes, not a whole Kernel or a shared SDK.

- Portal will use **one** production-shaped typed Kernel client for both real and mocked servers, selected by internal service URL and configured service authentication. Portal runtime must not import mock code/fixtures or fall back to them. Only dev/test configuration may select the mock; no browser calls to mock internals. A compatible real endpoint can replace it via URL/credentials; unknown wire/hash/auth differences must be reconciled before real enablement.
- Local mock is **disabled by default**; it can be stopped and removed without preventing Portal builds, database migrations, or normal startup. Missing Kernel must fail closed for **new publication and new purchase admission**, with no source-manifest cache fallback; previously confirmed paid subscriptions retain their separate finite trust rules. Mock-derived mapping evidence must be **SIMULATED**, rejected by real admission and excluded from production catalog queries even after changing URLs. No configuration switch upgrades an old simulated revision.
- No mock process/config/image/test data/auth bypass may be enabled or bundled in production Compose, production API/web image, or production deployment. Step 1 excludes mock files from root Docker build inputs and rejects standalone startup outside explicit development/test environments. Production integration/config rejection and Compose removal checks remain part of the later optional wiring.

### Keep the mock aligned with real Kernel

The **implemented, versioned, service-authorized** manifest contract in `gushinets/anytoolai-platform` becomes the source of truth when it exists. Until then, the accepted specs and explicitly provisional local conventions/independent fixtures define the mock boundary. Product identity provenance is pinned to Kernel commit `079eb03e28d7a50b980795c63c3e4533b785d11f`; that pin does not prove a manifest endpoint, paid registry or approved release.

ANY-664 must deliver small Portal-local schema/client/mock conformance and focused source-reference drift checks. Check shape/required fields, tenant/region, product/metric relationships, enabled semantics, independent literal digest, auth/HTTP errors and pinned product identities. This work must not import a Kernel runtime package, edit Kernel or require a matching checkout.

- Run focused checks on relevant Portal PRs and detect upstream changes independently with a bounded reference watch. A pinned local fixture alone cannot detect future upstream drift.
- Distinguish local fixture conformance from external-reference unavailability, a missing real producer and actual future incompatibility. Never report a local PASS as actual-producer verification or fail for unrelated Kernel commits/new products outside the selected fixture.
- When Kernel delivers its actual contract, reconcile endpoint/schema/hash/auth/scope and run conformance against that implementation before real enablement. Its delivery date, production credentials and paid metric approvals do not block fixture-based Portal implementation or ticket completion.
- Keep the mechanism small and use existing repository test/CI practices. The reference watch and future-producer handoff are later ANY-664 work; Step 1 does not claim they exist or pass.

### Required local verification

For Step 1, run the focused source and structural checks from the Portal root:

```bash
./.venv/bin/python -m pytest -q apps/api/tests/test_kernel_manifest_mock.py
npm run architecture:check
npm run docs:check
```

With the standalone mock running, check Swagger/OpenAPI availability in a second terminal:

```bash
curl --fail-with-body -i http://127.0.0.1:8091/docs
curl --fail-with-body -i http://127.0.0.1:8091/openapi.json
```

Open `/docs` in a browser and compare its documented endpoint/auth/scope/schemas with the contract. The focused tests verify OpenAPI/schema reference correspondence and retained manifest restrictions. The contract README includes the remaining HTTP auth/scope/unavailable/timeout commands. These commands have not been run by the implementation agent.

For the concurrent timeout check, restart the mock in the first terminal:

```bash
APP_ENV=development KERNEL_MOCK_TOKEN=local-kernel-test-only \
  ./.venv/bin/python -m tools.kernel_manifest_mock --port 8091 \
  --scenario timeout --delay-seconds 10
```

Start a slow request in a second terminal:

```bash
curl --fail-with-body --max-time 15 \
  -H 'Authorization: Bearer local-kernel-test-only' \
  'http://127.0.0.1:8091/internal/v1/capability-manifest?tenant_id=anytoolai&region=ru'
```

While it is still pending, run the following in a third terminal. Both routes must return `200` before the manifest request finishes:

```bash
curl --fail-with-body --max-time 2 -i http://127.0.0.1:8091/docs
curl --fail-with-body --max-time 2 -i http://127.0.0.1:8091/openapi.json
```

The focused test suite includes an event-synchronized check of this overlap using an actual HTTP manifest request; it holds the request at its delay boundary until both metadata responses have completed.

The later Portal walkthrough must demonstrate the real UI/backend with the optional mock for complete, disabled/missing, malformed/partial/version-incompatible and unavailable/unauthorized cases, refusing a **new** publication and recovering on a fresh read. No retired manifest-LKG rule applies. Demonstrate mock removal and production exclusion, plus a deliberately incompatible local contract/reference case. Actual-producer transition/conformance remains explicitly unverified until a compatible Kernel endpoint exists.

These are **Portal delivery requirements of ANY-664**, with real producer and production enablement tracked separately. No local demonstration authorizes real sales, payments or paid execution.
