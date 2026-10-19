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

The Makefile contains Unix/WSL convenience shortcuts that delegate to the
existing repository harness and explicit SIMULATED catalog setup:

```bash
make test_db_up
make test_db_stop
make catalog_preview
make catalog_preview_publish
```

The cross-platform equivalents of the test database shortcuts are:

```bash
python scripts/repo.py test-db up
python scripts/repo.py test-db stop
```

`catalog_preview` starts or updates the current worktree's Portal stack and
publishes its declared SIMULATED offer. `catalog_preview_publish` only publishes
into an already running, configured worktree. See the
[Step 6 acceptance procedure](#step-6-stored-catalog-acceptance) for scope,
authorization, repeat execution and evidence requirements.

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

For local visual development, [Step 7 wiring](#step-7-optional-http-mock-walkthrough) adds an opt-in HTTP mock container on the worktree backend network and a real Portal backend/PostgreSQL/localized frontend walkthrough. Runtime verification remains pending. The mock exposes the manifest and local documentation routes, not a whole Kernel or a shared SDK.

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

## Step 8 conformance and independent reference watch

The [Step 8 handoff](../contracts/kernel-capability-manifest/v1/step-8-handoff.md)
records the local HTTP/spec/client checker, exact positive/negative manual
commands, separate upstream documentation/identity watch and future real
producer acceptance. Source implementation is present; verification is pending.
The daily default-branch schedule remains **NOT_YET_OPERATIONAL** until an
actual scheduled run is recorded. Local and source checks remain **NOT_RUN**;
real Kernel conformance remains **DEFERRED_NOT_IMPLEMENTED**. The existing mock,
client and Compose walkthrough are retained unchanged.

## Step 6 stored catalog acceptance

The public catalog reads only immutable published revisions from the configured
`MAPPING_ACCOUNT_ID`. Set it explicitly through the shell or `.env`; `repo:up`
preserves it in the worktree runtime environment and passes it to the API. An
explicit shell value takes precedence, including an empty value. Empty means
`503 catalog_unavailable`; a configured account with no eligible revisions
returns an empty list. There is no automatic account selection or fixture fallback.

The ordinary catalog E2E tests intercept the Portal response. Their success does
not prove that a normal browser can read an offer from the working database.
Use the following separate acceptance path from the repository root on Unix/WSL.
These commands are for the **declared SIMULATED fixture account only**, not real
commercial approval. The existing worktree database must already be initialized;
the setup helper neither creates, resets nor migrates it.

First generate the contracts and run the focused checks manually. Starting the
test database below uses the separate disposable test database, not the working
catalog database.

```bash
source .venv/bin/activate
npm run generate
npm run generate:check
npm run test:api:fast
./.venv/bin/python scripts/repo.py test-db up
npm run test:api:postgres
npm --workspace @anytoolai/web run test:components -- tests/components/CatalogTransport.test.ts tests/components/CatalogPreview.test.tsx tests/components/RequestFailures.test.ts
npm run test:boundaries:web
npm run typecheck:web
```

Then start or update the working harness and publish the fixture through the
existing publisher with one command. This shortcut selects the repository-root
virtual environment directly and does not require shell activation.

```bash
make catalog_preview
CATALOG_PREVIEW_ACCEPTANCE=1 npm run test:e2e -- apps/web/e2e/catalog-stored-preview.spec.ts
```

`make catalog_preview` delegates to `scripts/repo.py up --reuse`, then runs
`make catalog_preview_publish` only if startup succeeded. Repeating it updates
the existing stack and republishes through the same guarded use case. It does
not start the standalone Kernel HTTP mock. Both shortcuts explicitly select
`MAPPING_ACCOUNT_ID=simulated-ru-lbx-account` and the publication shortcut passes
the invoking Unix UID via `MAPPING_OPERATOR_UIDS="[$(id -u)]"`.

For an already running harness with that account configured, publication alone is:

```bash
make catalog_preview_publish
```

An identical publication returns the existing revision without appending a
duplicate. The shortcuts default `CATALOG_PREVIEW_PREVIOUS_REVISION` to `0`;
changed material retains the publisher's revision conflict and approval guards.
Only after inspecting existing history may the operator pass an explicit
`CATALOG_PREVIEW_PREVIOUS_REVISION` Make variable. No automatic conflict retry,
history rewrite or database reset is performed.

The shortcuts do not edit `.env`. Use `make catalog_preview` again on subsequent
starts, or set the same `MAPPING_ACCOUNT_ID` in local `.env` when using ordinary
`npm run repo:up -- --reuse` instead.
The helper loads the existing host-API environment before importing application
settings, so `INSTANCE_TENANT_ID` and `INSTANCE_REGION` can come from the harness
even when an older `.env` lacks them. Explicit shell and `.env` values retain
their existing precedence; mismatched scope or a non-development environment
still causes refusal. The helper itself never invents a UID allowlist; the
explicit Make shortcuts supply it only for this declared simulation.

The explicit UID allowlist grants only permission to run the local publisher;
it does not approve a real product or legal/commercial terms. The helper uses
the existing Step 5 independently declared approval and isolated Kernel/LBX HTTP
recordings through the real clients, normalizer, evaluator and PostgreSQL
publisher. It records the actual authorized OS principal and SIMULATED evidence,
then closes its database engine. It never imports fixtures into the API/browser
runtime, sends a live provider request, inserts a hand-built mapping row, or
starts another mock service. Standalone HTTP-mock wiring/removal uses the Step 7
procedure below; real-source conformance remains a separate handoff.

The helper refuses a production/test environment, another account, another
database naming scope, a mismatched runtime scope, or an unauthorized OS
principal. Publication retains existing revision/CAS, idempotency and append-only
guards. If an existing different revision causes `mapping_revision_conflict`,
inspect it with the existing Step 5 scoped query before choosing an expected
revision; do not delete or rewrite history.

The explicit acceptance test does **not** intercept API responses. It requires
`proposal_ai` to be present in the real Portal API with the fixture's `200.02 RUB`
recurring charge, separate `14.06 RUB` connection charge and fixed allowance `25`.
It opens the list, follows the canonical product-ID route, reloads it, compares
the served revision, checks simulation disclosure, anonymous requests,
accessibility and overflow, and captures desktop/mobile evidence. Without
`CATALOG_PREVIEW_ACCEPTANCE=1` this manual acceptance test is skipped, which is
**not a PASS** for Step 6.

Also open `/ru/products` and `/ru/products/proposal_ai` in the ordinary browser
at the harness origin printed by `repo:up`. The account's older editorial cards
remain presentation placeholders and are not the source of this catalog.
The API must continue to serve the stored preview after the setup process has
exited; browsing performs no Kernel/LBX calls. Existing API tests cover source
admission saturation and production exclusion of persisted simulated evidence.

The implementation agent has not executed these setup/acceptance commands or
claimed the corresponding real API/DB/browser outcome. Human execution and
review are required before recording Step 6 acceptance.

## Step 7 optional HTTP mock walkthrough

**Status: source implementation only; Compose, image, test and browser outcomes
have not been executed or verified by the implementation agent.** All commands
below run manually from the Portal repository root on Unix/WSL. No command in
this procedure contacts live LBX. Real provider reads need separate explicit
authorization; real publication, sales and paid access remain gated on G1–G5.

`KERNEL_MOCK_ENABLED=1` makes `scripts/repo.py` append
`docker-compose.kernel-mock.dev.yml` to the existing base/agent Compose files,
using the same project and backend network. It adds one port at
`runtime.api_port + 9000`, respecting `repo:up --port-offset`. With the opt-in
absent (or `0`), the override and its source settings are omitted. Keep the flag
in the same shell for `repo:up`/`repo:down`, or set it explicitly in local `.env`.

The service reuses the API **development** Docker stage. Its only source inputs
are read-only mounts of `tools/kernel_manifest_mock/` and the versioned
`docs/contracts/kernel-capability-manifest/v1/` directory at their original
`/app/` paths. It runs the unchanged `python -m tools.kernel_manifest_mock
--host 0.0.0.0 --port 8091` entrypoint. The host port binds only `127.0.0.1`;
the service joins only `backend`, without Caddy ingress, CORS or an API
`depends_on` relationship. Existing production Docker exclusions/copy rules and
production Compose remain unchanged.

The API container receives `KERNEL_BASE_URL`, `KERNEL_SERVICE_TOKEN`, its existing
instance scope and the explicit execution-UID allowlist. The existing source
composition assigns SIMULATED provenance independently of URL/credentials.
The opt-in API also mounts `.harness/kernel-walkthrough/` for independent
simulated proposal/approval/input files. Only the explicitly invoked
`apps.api.tests.support.kernel_walkthrough` helper imports recordings; normal
`app/` runtime never imports it. The helper calls the existing
`fresh_mapping_evaluation`, real `LbxServerClient` with isolated selected-read
transport, normalizer and `publish_mapping`; Kernel always uses real HTTP.
There is no fallback on source failure. `prepare` writes the named test approval
separately; neither `dry-run` nor `publish` creates or refreshes approval.

### Opt in, inspect and publish

Generate the Step 6 wire artifacts before building its consumer. These commands
are manual prerequisites, not evidence already obtained:

```bash
npm run repo:setup
npm run generate
npm run generate:check
export APP_ENV=development
export KERNEL_MOCK_ENABLED=1
export MAPPING_ACCOUNT_ID=simulated-ru-lbx-account
export KERNEL_MOCK_TOKEN="$(./.venv/bin/python -c 'import secrets; print(secrets.token_hex(24))')"
export KERNEL_SERVICE_TOKEN="$KERNEL_MOCK_TOKEN"
export MAPPING_OPERATOR_UIDS='[]'
export KERNEL_MOCK_SCENARIO=valid
mkdir -p .harness/kernel-walkthrough
npm run repo:up -- --reuse

dc() {
  docker compose \
    --project-name "$(./.venv/bin/python -c 'import json; print(json.load(open(".harness/runtime.json"))["compose_project"])')" \
    --env-file .harness/runtime.env \
    -f docker-compose.yml -f docker-compose.agent.yml \
    -f docker-compose.kernel-mock.dev.yml "$@"
}
dc config --quiet
dc config --format json | ./.venv/bin/python -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({n:{k:s.get(k) for k in ("build","networks","volumes","ports","depends_on")} for n,s in d["services"].items()},indent=2))'
operator_uid="$(dc exec -T api id -u)"
export MAPPING_OPERATOR_UIDS="[$operator_uid]"
dc up -d --no-deps --force-recreate api

operator() {
  dc exec -T -e PYTHONPATH=.:apps/api api python \
    -m apps.api.tests.support.kernel_walkthrough "$@"
}
operator prepare --output-dir /app/.kernel-walkthrough
operator dry-run --proposal /app/.kernel-walkthrough/proposal.json \
  > .harness/kernel-walkthrough/dry-run.json
operator publish --proposal /app/.kernel-walkthrough/proposal.json \
  --expected-previous-revision 0 > .harness/kernel-walkthrough/publish.json
offer_id="$(./.venv/bin/python -c 'import json; print(json.load(open(".harness/kernel-walkthrough/publish.json"))["billing_offer_id"])')"
operator query --offer-id "$offer_id" > .harness/kernel-walkthrough/query.json
./.venv/bin/python -c 'import json; a=json.load(open(".harness/kernel-walkthrough/dry-run.json")); b=json.load(open(".harness/kernel-walkthrough/publish.json")); assert a["evaluation"]["evaluated_at"] != b["evaluation"]["evaluated_at"]; assert b["stored_document"]["evidence_mode"] == "SIMULATED"; print(b["mapping_revision_id"], b["revision_number"], b["inserted"])'
```

Inspect the rendered mounts/networks/ports, including the absence of mock
dependencies on API/migrate. The whitelist above omits environment values so
credentials are not printed. Keep full `dc config` output private. The initial
empty allowlist cannot run the operator; `id -u` selects the actual container
process UID, which currently is root in the development stage. This authorizes
local CLI execution only. Repeated identical publication returns the existing
immutable row; if different prior material conflicts, query its history and
choose the reviewed expected revision explicitly. Never reset history to make
the walkthrough pass.

Print the actual worktree URLs, then open the list and canonical product URL,
follow the detail link and hard reload. Confirm exact `200.02 RUB` recurring,
`14.06 RUB` connection, allowance `25`, visible simulation and no purchase CTA.
Browser network traffic must contain only Portal catalog calls, with no
manifest calls or service credential. `/docs` is the developer-only exception:

```bash
./.venv/bin/python -c 'import json; r=json.load(open(".harness/runtime.json")); p=r["otlp_http_port"]+1000; print("http://localhost:{}/ru/products\nhttp://localhost:{}/ru/products/proposal_ai\nhttp://127.0.0.1:{}/docs".format(p,p,r["api_port"]+9000))'
mock_port="$(./.venv/bin/python -c 'import json; print(json.load(open(".harness/runtime.json"))["api_port"]+9000)')"
api_origin="$(./.venv/bin/python -c 'import json; print("http://127.0.0.1:"+str(json.load(open(".harness/runtime.json"))["api_port"]))')"
curl --fail-with-body "http://127.0.0.1:$mock_port/openapi.json"
curl --fail-with-body "$api_origin/api/catalog/products/proposal_ai"
CATALOG_PREVIEW_ACCEPTANCE=1 npm run test:e2e -- apps/web/e2e/catalog-stored-preview.spec.ts
```

The existing browser acceptance test uses real Portal HTTP/DB without route
interception. Run it again during the outage below. The existing Step 1 test
`test_documentation_responds_while_manifest_request_is_still_delayed` covers
concurrent Swagger/OpenAPI reads; this wiring does not reimplement that behavior.

### Fail after success, recover and remove

Each failed publication below must return a nonzero status and a safe
`detail.code`; query and preview must retain the previously stored revision.
Disabled/missing cases report `selected_product_*`/`selected_metric_*`, malformed
or wrong-schema responses `kernel_manifest_invalid`, authentication
`kernel_authentication_failed`, forbidden scope `kernel_scope_forbidden`, timeout `kernel_timeout` or the outer
`preflight_deadline_exceeded`, and unavailable/down `kernel_unavailable`.

```bash
for fault in disabled-product missing-product disabled-metric missing-metric malformed-json partial wrong-schema unauthorized forbidden timeout unavailable; do
  export KERNEL_MOCK_SCENARIO="$fault"
  dc up -d --no-deps --force-recreate kernel-mock
  if operator publish --proposal /app/.kernel-walkthrough/proposal.json --expected-previous-revision 0; then
    echo "Unexpected publication success for $fault"
    break
  fi
  operator query --offer-id "$offer_id"
  curl --fail-with-body "$api_origin/api/catalog/products/proposal_ai"
done
export KERNEL_MOCK_SCENARIO=valid
dc up -d --no-deps --force-recreate kernel-mock
operator publish --proposal /app/.kernel-walkthrough/proposal.json --expected-previous-revision 0
dc stop kernel-mock
dc rm -f kernel-mock
dc up -d --no-deps --force-recreate api
dc run --rm migrate
curl --fail-with-body "$api_origin/api/health/live"
curl --fail-with-body "$api_origin/api/health/ready"
operator query --offer-id "$offer_id"
operator publish --proposal /app/.kernel-walkthrough/proposal.json --expected-previous-revision 0
CATALOG_PREVIEW_ACCEPTANCE=1 npm run test:e2e -- apps/web/e2e/catalog-stored-preview.spec.ts
```

The final publication must fail after removal; migrations, API lifespan,
readiness, query and old preview must still work. The helper is never called
at startup. To observe concurrent slow work manually, select `timeout`, start
`operator publish` in one terminal, and execute query/reload in another before
the bounded refusal. The source regression below additionally occupies the
same process-local admission owner with slow HTTP, rejects a second operation
with `preflight_saturated`, and queries/previews the saved row. Separate CLI
processes have separate admission owners; this is not distributed saturation
or later paid-access/reconciliation load evidence.

### Compatible target switch and production exclusion

`test_independent_http_target_switch_changes_only_url_and_credentials` in
`test_kernel_walkthrough_postgres.py` starts an independent, credential-checking
literal HTTP test target, with no mock imports in that handler. It publishes
through the existing mock first, closes it, changes only URL/credential on the
same configured client path, then freshly republishes through the independent
target. It checks retained SIMULATED evidence, genuine-publication refusal and
production catalog exclusion over the same real DB. This proves configuration
replaceability only; it does not establish compatibility with an unbuilt real
producer. It is included in the exact PostgreSQL command below.

For a separately supplied compatible local target reachable on this worktree's
backend network, the manual API-container switch is:

```bash
read -r -p 'Independent local Kernel origin: ' KERNEL_BASE_URL
read -r -s -p 'Independent local service credential: ' KERNEL_SERVICE_TOKEN
export KERNEL_BASE_URL KERNEL_SERVICE_TOKEN
dc up -d --no-deps --force-recreate api
operator dry-run --proposal /app/.kernel-walkthrough/proposal.json
operator publish --proposal /app/.kernel-walkthrough/proposal.json --expected-previous-revision 0
operator query --offer-id "$offer_id"
```

Keep scope, proposal, approval, fixtures and provenance unchanged. Do not point
this procedure at a real producer or reclassify old rows. To restore the accepted
mock use `unset KERNEL_BASE_URL`, set `KERNEL_SERVICE_TOKEN="$KERNEL_MOCK_TOKEN"`,
select `valid` and recreate mock/API. To return to the default harness, remove
the mock as above and run `KERNEL_MOCK_ENABLED=0 npm run repo:up -- --reuse`.
That recreates the API without the dev source settings/mount. Saved simulation
remains saved simulation; genuine historic rows remain subject to ordinary
DB-only selection.

Run the source regressions and canonical checks manually. PostgreSQL tests own
the disposable `_tests` DB lifecycle and never use the walkthrough DB:

```bash
npm run test:api:fast
./.venv/bin/python scripts/repo.py test-db up
npm run test:api:postgres
npm run check:fast
npm run check
```

The new focused files are `test_kernel_mock_dev.py` (opt-in/UID/config guards)
and `test_kernel_walkthrough_postgres.py` (HTTP/DB/API faults, slow saturation,
restart/removal, retry and independent-target switch). Existing browser,
production-simulation and concurrent-documentation regression sources are reused.

Production Settings already refuse every provisional Kernel URL/token, including
HTTPS test URLs. The production deployment validator now also rejects mock
flags/token/scenario, mock profiles and the dev override in `COMPOSE_FILE`.
For example, this manual command must fail before any deployment:

```bash
KERNEL_MOCK_ENABLED=1 CADDY_DOMAIN=portal.example.com \
  ./.venv/bin/python scripts/repo.py validate-production-env
```

In a separate deployment shell without the dev variables and with its required
production configuration supplied, inspect/build the real production inputs:

```bash
docker compose -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.prod.yml config --services
docker build --target production -f apps/api/Dockerfile -t portal-step7-api .
docker run --rm --entrypoint sh portal-step7-api -c 'test ! -e /app/tools/kernel_manifest_mock && test ! -e /app/docs/contracts && test ! -e /app/apps/api/tests'
docker build -f apps/web/Dockerfile --build-arg APP_PUBLIC_BASE_URL=https://portal.example.com --build-arg NEXT_PUBLIC_API_BASE_URL=https://portal.example.com -t portal-step7-web .
docker run --rm --entrypoint sh portal-step7-web -c 'test ! -e /app/tools/kernel_manifest_mock && test ! -e /app/docs/contracts && test ! -e /app/apps/api/tests'
```

The production service list must have no `kernel-mock`; inspect images for the
absence of mock code/contracts/recordings and review the unchanged copy rules.
Never combine the dev override with production Compose. Record actual command
statuses, revision IDs, safe failure codes, browser artifacts, mount/port/image
inspection and remaining failures separately. No runtime PASS, real source
conformance, paid access or launch approval is claimed by this source handoff.
