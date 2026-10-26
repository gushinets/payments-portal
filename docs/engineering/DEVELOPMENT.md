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

The Makefile contains only the `test_db_up` and `test_db_stop` convenience
shortcuts. Normal startup uses `npm run repo:up -- --reuse`; direct product
linking uses the one `app.cli.commercial_mappings` CLI. See the
[normal LBX connection and link runbook](lbx-product-links.md). Historical
`catalog_preview`/`catalog_preview_publish` shortcuts have been retired.

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

For local visual development, [Step 7 wiring](#step-7-optional-http-mock-walkthrough) adds an opt-in HTTP mock container on the worktree backend network and a real Portal backend/PostgreSQL/localized frontend walkthrough. The joined positive browser acceptance passed on 2026-10-21; see the execution record below. The mock exposes the manifest and local documentation routes, not a whole Kernel or a shared SDK.

- Portal implements **one** production-shaped typed Kernel HTTP client, currently verified against the mock and selected by internal service URL and configured service authentication. Portal runtime must not import mock code/fixtures or fall back to them. Only dev/test configuration may select the mock; no browser calls to mock internals. A compatible real endpoint can later use this client after real conformance and separate production enablement; unknown wire/hash/auth/scope differences must first be reconciled.
- Local mock is **disabled by default**; it can be stopped and removed without preventing Portal builds, database migrations, or normal startup. Missing Kernel must fail closed for **new publication and new purchase admission**, with no source-manifest cache fallback; previously confirmed paid subscriptions retain their separate finite trust rules. Mock-derived mapping evidence must be **SIMULATED**, rejected by real admission and excluded from production catalog queries even after changing URLs. No configuration switch upgrades an old simulated revision.
- No mock process/config/image/test data/auth bypass may be enabled or bundled in production Compose, production API/web image, or production deployment. Step 1 excludes mock files from root Docker build inputs and rejects standalone startup outside explicit development/test environments. Production integration/config rejection and Compose removal checks remain part of the later optional wiring.

### Keep the mock aligned with real Kernel

The **implemented, versioned, service-authorized** manifest contract in `gushinets/anytoolai-platform` becomes the source of truth when it exists. Until then, the accepted specs and explicitly provisional local conventions/independent fixtures define the mock boundary. Product identity provenance is pinned to Kernel commit `079eb03e28d7a50b980795c63c3e4533b785d11f`; that pin does not prove a manifest endpoint, paid registry or approved release.

ANY-664 delivers Portal-local schema/client/mock conformance. Check shape/required fields, tenant/region, product/metric relationships, enabled semantics, independent literal digest and auth/HTTP errors. Historical product identity pins remain provenance only. This work must not import a Kernel runtime package, edit Kernel or require a matching checkout.

- Run focused local conformance checks in the existing Portal PR CI. The owner removed external source monitoring on 2026-10-19 because the real manifest API is not implemented; no replacement monitor is required here.
- Distinguish local fixture conformance from the missing real producer and actual future incompatibility. Never report a local PASS as actual-producer verification.
- When Kernel delivers its actual contract, reconcile endpoint/schema/hash/auth/scope and run conformance against that implementation before real enablement. Its delivery date, production credentials and paid metric approvals do not block fixture-based Portal implementation or ticket completion.
- Keep the mechanism small and use existing repository test/CI practices. Real API verification is a separate mandatory task before real publication or sales.

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

The later Portal walkthrough must demonstrate the real UI/backend with the optional mock for complete, disabled/missing, malformed/partial/version-incompatible and unavailable/unauthorized cases, refusing a **new** publication and recovering on a fresh read. No retired manifest-LKG rule applies. Demonstrate mock removal and production exclusion, plus a deliberately incompatible local contract case. Actual-producer transition/conformance remains explicitly unverified until a compatible Kernel endpoint exists.

These are **Portal delivery requirements of ANY-664**, with real producer and production enablement tracked separately. No local demonstration authorizes real sales, payments or paid execution.

## Step 8 local conformance and deferred real Kernel API

The [Step 8 handoff](../contracts/kernel-capability-manifest/v1/step-8-handoff.md)
records the local HTTP/spec/client checker, exact positive/negative manual
commands and mandatory future real producer acceptance. Existing CI retains
local conformance and negative cases; the external source monitor is removed.
The handoff records local conformance PASS in
[CI run 39260471356](https://github.com/gushinets/payments-portal/actions/runs/39260471356)
at `15736d6b69c57deb8681e4a951959d78031fb992`, separately from the historical
implementation-agent formatting/lint-only report. This is not a fresh run or
blanket manual acceptance. Real Kernel conformance remains
**DEFERRED_NOT_IMPLEMENTED**; checking
the provisional local contract does not verify the real API. The existing mock,
client and Compose walkthrough are retained unchanged.

The handoff also records the CodeQL review of the two operator JSON sinks.
Their output is restricted evidence, including verbatim `reason`, approval
references, account identifiers and OS principal. Run only within the trusted
OS/configuration/DB boundary and protect stdout/redirected files accordingly.
Use credential-free approval/evidence references; never place secrets, signed
access URLs, card data or unnecessary personal data in operator input. Do not
forward full operator results to shared logs, telemetry or public CI artifacts.
This preserves the existing JSON and immutable audit contract.

Operator `dry-run` and `publish` validate the complete selected tariff service
list, including each explicit `enabled_by_default` flag. The selected service
must be the only default-assigned service; optional services (`0`) are excluded.
Missing/ambiguous composition refuses the operation, and the default composition
is pinned in selected evidence/digest. No LBX tariff is mutated.

Historical ANY-664 v1 approval files pinned independent technical/commercial/legal
versions. ANY-709 Step 1 supersedes that operator workflow: a direct product link
contains no price or file approval. Current prices come from LBX without
re-publication; future purchase consent freezes the accepted exact terms. The
v1 history reader and test-only fixture harness retain the old evidence format.

### Operator publication bounds

Every operator `dry-run`/`publish` requires `MAPPING_OPERATOR_LOCK_FILE`: one
absolute path in a pre-provisioned trusted local directory for the deployment.
The directory must not be writable by group/others. Run all commands under an
OS identity that can open the same file; it is created with mode `0600`, must
remain private and regular, and is never deleted on release. Do not change the
path per proposal, current directory or process. Symlinks, unsafe permissions,
missing configuration, open/lock errors and unsupported platforms fail closed
with `mapping_operator_lock_unavailable` before creating source clients.

Unix `flock(LOCK_EX | LOCK_NB)` permits **one active operator command**. A
contender immediately receives `preflight_saturated` before Kernel/LBX HTTP.
The file lock spans source reads, cleanup and publication/commit; process exit
also releases it. `query` remains DB-only and requires neither this file nor
source settings. Existing `preflight_max_active`/`preflight_max_waiting` control
the process-local `PreflightAdmission`, not cross-process concurrency. There is
no PostgreSQL connection held for this file lock and no distributed protection:
multiple operator hosts without the same local lock require a separate design.

Current link publication keeps the shared monotonic operation deadline across
source cleanup and PostgreSQL lock/CAS. A link is an association, not an accepted
price or calendar lease. Current offer reads need the configured billing calendar.

## Step 6 stored catalog acceptance (historical ANY-664)

The following records the completed ANY-664 workflow, not current setup.
ANY-709 Step 1 removes its manual account/files and DB-only public catalog. Use
[the normal connection/link runbook](lbx-product-links.md); the old fixture
helpers are retained only under tests and are not deployment entrypoints.

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
mkdir -p .harness/kernel-walkthrough
chmod 700 .harness/kernel-walkthrough
export MAPPING_OPERATOR_LOCK_FILE="$PWD/.harness/kernel-walkthrough/operator.lock"
make catalog_preview
# For browser acceptance, use the standalone HTTP publication procedure below.
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

The joined Step 7 procedure below passed on 2026-10-21 after explicit owner
authorization, including the real API/DB/browser checks. Its exact revision and
saved artifacts are recorded in the completed ANY-664 plan.

## Step 7 optional HTTP mock walkthrough (historical ANY-664)

The recorded joined walkthrough below is historical. The normal technical mock
now has no billing mounts, approval files or publisher-UID startup requirement.
Current source-backed catalog setup follows the [normal runbook](lbx-product-links.md).

**Status: the positive joined P1 acceptance passed on 2026-10-21, with 2 Chromium
projects passed and zero skips.** See the [execution record](../exec-plans/completed/ANY-664-implementation-plan.md#p1-joined-browser-acceptance--pass-2026-10-21)
for the exact revision, artifacts and verification limits. Fault/removal and
production-image checks below were not rerun in that session. All commands
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
export PATH="$PWD/.venv/bin:$PATH"
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
chmod 700 .harness/kernel-walkthrough
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
  dc exec -T -e PYTHONPATH=.:apps/api \
    -e MAPPING_OPERATOR_LOCK_FILE=/app/.kernel-walkthrough/operator.lock api python \
    -m apps.api.tests.support.kernel_walkthrough "$@"
}
# prepare is an explicit independent SIMULATED review, using the configured
# account calendar's current date. dry-run/publish never rewrite that date.
operator prepare --output-dir /app/.kernel-walkthrough
operator dry-run --proposal /app/.kernel-walkthrough/proposal.json \
  > .harness/kernel-walkthrough/dry-run.json
operator publish --proposal /app/.kernel-walkthrough/proposal.json \
  --expected-previous-revision 0 > .harness/kernel-walkthrough/publish.json
offer_id="$(./.venv/bin/python -c 'import json; print(json.load(open(".harness/kernel-walkthrough/publish.json"))["billing_offer_id"])')"
operator query --offer-id "$offer_id" > .harness/kernel-walkthrough/query.json
./.venv/bin/python -c 'import json; a=json.load(open(".harness/kernel-walkthrough/dry-run.json")); b=json.load(open(".harness/kernel-walkthrough/publish.json")); assert a["evaluation"]["evaluated_at"] != b["evaluation"]["evaluated_at"]; q=json.load(open(".harness/kernel-walkthrough/query.json")); assert b["stored_document"]["evidence_mode"] == "SIMULATED"; assert q["mapping_revision_id"] == b["mapping_revision_id"]; assert q["document"] == b["stored_document"]; print(b["mapping_revision_id"], b["revision_number"], b["inserted"])'
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
export CATALOG_PREVIEW_PUBLICATION_FILE="$PWD/.harness/kernel-walkthrough/publish.json"
CATALOG_PREVIEW_ACCEPTANCE=1 npm run test:e2e -- \
  apps/web/e2e/catalog-stored-preview.spec.ts --trace on
# Preserve both projects' success screenshots, JSON assertions and traces
# before another Playwright run overwrites the standard result directories.
evidence_dir=".harness/kernel-walkthrough/evidence-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$evidence_dir"
cp .harness/kernel-walkthrough/{dry-run,publish,query}.json "$evidence_dir/"
cp -a .harness/playwright-results "$evidence_dir/"
cp -a .harness/playwright-report "$evidence_dir/"
dc ps --format json kernel-mock > "$evidence_dir/kernel-mock-service.json"
dc logs --no-color kernel-mock > "$evidence_dir/kernel-mock.log"
```

The browser test requires the exact `publish.json` above. It compares its
PostgreSQL revision ID/number, SIMULATED evidence, 200.02/14.06 RUB and allowance
25 with the initial API list, browser list request, linked detail request and
reload. Each project attaches list/detail/reload screenshots and safe API facts;
`--trace on` retains a trace on success too. Both desktop and mobile Chromium
must pass with zero skips. The report is `.harness/playwright-report/html`, with
machine results in `.harness/playwright-report/results.json` and attachments in
`.harness/playwright-results`. Keep these artifacts private: operator JSON is
privileged audit evidence. A skipped default CI test is not acceptance evidence.
The local QA of 2026-10-20 already proved PostgreSQL → Portal API → Chromium
without interception and the separate source checks; this remaining run joins
those checks through the standalone HTTP mock and the same stored revision.
This exact run passed on 2026-10-21 with revision 2
(`232a5492-1bab-471b-84ee-2a01ed8ac911`); screenshots and machine evidence were
reviewed. Artifacts are preserved locally under
`.harness/kernel-walkthrough/evidence-P1-20261021T023715Z/`.
Run the same acceptance command during the outage below,
preserving that run's artifacts in a separate evidence directory. The existing Step 1 test
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
with `preflight_saturated`, and queries/previews the saved row. Operator CLI
processes additionally share the configured local file lock, including the
walkthrough helper above. Its container path maps to the same file under the
host's `.harness/kernel-walkthrough` bind mount; filesystem permissions must
allow the chosen execution identities to open that private file. This is not
distributed saturation or later paid-access/reconciliation load evidence.

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
inspection and remaining failures separately. The recorded positive P1 PASS does
not establish real source conformance, paid access or launch approval.

## ANY-664 PR #139 review correction checks (2026-10-21)

Source corrections and lint are distinct from runtime PASS. Run these commands
manually from the repository root. The agent subsequently executed the authorized
P1 Compose/publication/browser scenario above, including its normal development
build and migration startup; the focused pytest/PostgreSQL suites below were not
rerun in that session. Keep the existing 2026-10-20 QA evidence; it does not need
to be repeated separately.

After that session, the owner reported a successful
`RUN_E2E=true npm run check` on the final changes (2026-10-21). See the completed
plan's [final verification record](../exec-plans/completed/ANY-664-implementation-plan.md#final-owner-verification--pass-2026-10-21).

1. Run the targeted quantity/calendar/approval regressions without PostgreSQL:

   ```bash
   export PATH="$PWD/.venv/bin:$PATH"
   mkdir -p .harness/any-664-review
   PYTHONPATH=.:apps/api .venv/bin/python - <<'PYTEST_FAST'
   import subprocess
   import sys
   from scripts import repo
   subprocess.run([
       sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-m", "not postgres",
       "apps/api/tests/test_lbx_selected_offer_normalization.py",
       "apps/api/tests/test_lbx_selected_offer_failures.py",
       "apps/api/tests/test_mapping_billing_calendar.py",
       "apps/api/tests/test_commercial_sellability.py",
       "--junitxml=.harness/any-664-review/targeted.xml",
   ], env=repo.canonical_check_environment(), check=True)
   PYTEST_FAST
   ```

   PASS: integral bounds accepted; 1.5 refused even at 100.00; old/future dates,
   expired/not-yet-valid policy and missing/foreign/unproven calendar refused;
   account date at UTC midnight offset accepted; crossing account midnight
   refused; both dry-run and publish protected. No real source requests.

2. Start the existing test PostgreSQL server and run persistence/HTTP regressions:

   ```bash
   .venv/bin/python scripts/repo.py test-db up
   PYTHONPATH=.:apps/api .venv/bin/python - <<'PYTEST_POSTGRES'
   import subprocess
   import sys
   from scripts import repo
   environment = repo.api_test_environment("api-postgres", repo.canonical_check_environment())
   subprocess.run([
       sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-m", "postgres",
       "apps/api/tests/test_commercial_mapping_postgres.py",
       "apps/api/tests/test_kernel_walkthrough_postgres.py",
       "apps/api/tests/test_catalog_api.py",
       "--junitxml=.harness/any-664-review/postgres.xml",
   ], env=environment, check=True)
   PYTEST_POSTGRES
   ```

   PASS: v1 → v2 → reused v1 rejects changed material/hash independently for
   technical/commercial/legal pins; unchanged historical approval is reusable;
   concurrent publishers retain one valid append; CAS/idempotency, rollback and
   append-only guards remain green. These tests use the disposable `_tests` DB;
   pytest owns its creation/migration/removal, never the working catalog DB.

3. Use the existing **Step 7 optional HTTP mock walkthrough → Opt in, inspect
   and publish** procedure above, followed by the existing `npm run test:e2e`
   command with its acceptance flag and publication artifact. No additional npm
   command or orchestration layer is required. Keep the mock enabled in the same
   shell used for startup and teardown.

   On an existing different head, inspect `operator query` for
   `selected-offer:v1:701:1001:901` and pass its reviewed revision number instead
   of 0. Never reset history. The recorded price remains valid only through
   2026-12-31; beyond that it must fail until separately reviewed fixture
   maintenance.

   PASS: both Chromium projects succeed without skips, every HTTP representation
   equals the exact published revision and material, and screenshots/results/traces
   are retained as described above. Any failed assertion, nonzero command or skip
   is not PASS.

4. After focused checks and browser evidence, run the remaining repository gates:

   ```bash
   npm run lint:web
   npm run typecheck:web
   npm run docs:check
   npm run architecture:check
   npm run generate:check
   npm run check:fast
   npm run check
   .venv/bin/python scripts/repo.py test-db stop
   ```

   PASS requires successful exits and retained results; record any unsupported
   environment check as skipped, not passed. Stop the test server after checks;
   the working stack and its immutable publications remain intact.

## ANY-664 three P2 corrections (2026-10-22)

This correction delivery runs Ruff formatting/lint and static documentation /
architecture checks only. Runtime PASS still requires the manual commands below;
no pytest, Playwright, build or migration was run during this correction.

From the repository root on Unix/WSL:

```bash
export PATH="$PWD/.venv/bin:$PATH"
npm run test:api:fast

# Isolate the independent CLI-process regressions (real local HTTP, no live LBX).
PYTHONPATH=.:apps/api .venv/bin/python - <<'PYTEST_PROCESSES'
import subprocess
import sys
from scripts import repo
subprocess.run([
    sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-m", "not postgres",
    "apps/api/tests/test_operator_preflight_processes.py",
], env=repo.canonical_check_environment(), check=True)
PYTEST_PROCESSES

.venv/bin/python scripts/repo.py test-db up
npm run test:api:postgres
.venv/bin/python scripts/repo.py test-db stop

RUN_E2E=true npm run check
```

The fast suite includes account-calendar/DST bounds, expiry during Kernel/LBX
cleanup, fail-closed lock paths and independent-process saturation/release/crash
recovery. PostgreSQL coverage includes catalog `no-store` on success/404/503,
expiry during actual advisory-lock wait, history reads and after flush, unchanged
row count/latest revision on refusal, commit before expiry, idempotency and
lost-ack recovery. It also runs two independent `publish` processes against real
PostgreSQL, then retries without a duplicate, and executes an independent
DB-only `query` while the operator file lock is held. No source mutation or real
billing operation is part of these regressions.
