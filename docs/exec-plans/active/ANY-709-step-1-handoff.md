# ANY-709 Step 1 handoff

Status: **IMPLEMENTED_AWAITING_HUMAN_VALIDATION**
Date: 2026-10-26
Selected scope: Step 1 only. The supplied untracked implementation plan was preserved unchanged.

## Owner follow-up: environment example inventory (2026-10-26)

Expanded `.env.example` to list all 47 runtime Settings fields and the remaining
supported keys found in the local `.env`, including mock token/options, test DB
host/DSN and observability. Values are public defaults or empty placeholders;
local secrets were inspected only for presence and were not copied or changed.
Obsolete direct-provider/account-ID keys were not restored. Host-only policy
tuning is marked explicitly because Compose currently uses its code defaults.
The billing timezone remains empty by default; an explicit `Etc/UTC` example is
labeled an unconfirmed isolated-test assumption, pending the actual LBX answer.
Read-only key inspection found no missing Settings/supported local keys or
duplicate example assignments; `git diff --check` passed. No runtime wiring,
tests/collection, generation, migrations, containers or live requests were run
for this example-only follow-up.

## PR #150 Steps 1-2 confirmed fixes (base 536e37a, 2026-10-26)

Status: **IMPLEMENTED_AWAITING_HUMAN_VALIDATION**. The checkout was clean at
`536e37a156db53626aaf299fd12295f2e4f0e70e`; no reset, stage, commit, push,
PR/ticket mutation or dependency installation was performed. Earlier validation
results below remain historical and do not validate these corrections.

- Fixed nullable FIO in `apps/api/app/domains/identity/router.py`: normalization
  precedes the nullable union and `max_length=100` applies only to strings.
  `names.py`, auth service, factories, models and migrations are unchanged.
- Updated the exact enum values/export set in `test_model_enums.py` for the
  existing `ExternalCreateOperationState`; the runtime enum is unchanged.
- Replaced runtime `authorize_operator(configuration)` with
  `resolve_operator_principal()`. Every valid actual nonnegative integer OS UID
  supplies `os-euid:<uid>`; invalid/missing identity or `OSError` still gives
  `mapping_operator_identity_unavailable`. Removed the UID allowlist from runtime
  Settings, both example env files, normal/agent/production Compose and
  `scripts/repo.py::write_runtime()`. No replacement flag/actor/endpoint exists.
  Updated `docs/engineering/lbx-product-links.md` and only the active plan's
  mandatory-allowlist paragraph; specs and historical instructions are unchanged.
- Retained command `operator_audit.execution_principal`, immutable publication
  authors/history, private shared host/container lock paths and permissions,
  lock timeout, `operator_preflight_lock`, PostgreSQL locks and revision/CAS.
  `HistoricalOperatorSettings` in test support now owns the former strict UID
  tuple; v1 authorization/CLI, walkthrough allowlist cases and process regressions
  remain intact. The Step 1 fixture no longer supplies a UID list.

Tests written/updated, all **NOT_RUN**: `test_any709_step2_customer.py` covers each
name's null/empty/whitespace/partial input, 100/101 characters after trim,
non-string/control-character rejection; `test_api_identity_session.py` covers
HTTP 200/normalized session, HTTP 422 and optional nullable string branches with
`maxLength=100`. `test_any709_step1_sources.py` covers actual UID variants,
unavailable/invalid OS identity, absence of `--actor` and runtime UID fields,
ignored stale env values and private runtime config/lock preservation.
`test_any709_step1_postgres.py` checks command authors versus immutable history
across different UIDs. `test_kernel_mock_dev.py` now requires omission of the
old env key while retaining mock/secrecy and historical walkthrough checks.
The compatibility/factory tests retain their meaning unchanged.

Formatting/lint used the existing API Ruff with this explicit file set:

```bash
API_FILES=(
  apps/api/app/domains/identity/router.py
  apps/api/app/composition/mapping_operator.py
  apps/api/app/cli/commercial_mappings.py
  apps/api/app/core/settings.py
  apps/api/tests/support/any709_step1.py
  apps/api/tests/support/commercial_mappings.py
  apps/api/tests/test_model_enums.py
  apps/api/tests/test_kernel_mock_dev.py
  apps/api/tests/test_any709_step2_customer.py
  apps/api/tests/test_api_identity_session.py
  apps/api/tests/test_any709_step1_sources.py
  apps/api/tests/test_any709_step1_postgres.py
)
.venv/bin/python -m ruff format --config apps/api/pyproject.toml "${API_FILES[@]}"
.venv/bin/python -m ruff check --config apps/api/pyproject.toml "${API_FILES[@]}"
git diff --check
```

Initial format: 3 reformatted, 9 unchanged; final format: 12 unchanged. Ruff check
and whitespace lint: **exit 0**. `scripts/repo.py` received only the pass-through
deletion and was not API-formatted. `npm run generate` initially exited 127
because `python` was absent from PATH; retry
`PATH="$PWD/.venv/bin:$PATH" npm run generate` completed **exit 0** using existing
dependencies. Only `docs/generated/openapi.json` changed: the three length limits
moved into string branches. Regenerated TypeScript remained byte-identical with
`first_name?`, `surname?`, `patronymic?: string | null`. No migration was needed
or run. Final `rg` inspection found no UID allowlist in new executable runtime or
current configuration; remaining occurrences are negative tests, test-only v1
or historical documentation (including `app/cli/COMMERCIAL_MAPPINGS.md`).

Exact human QA commands from repository root, **NOT_RUN** here:

```bash
export PATH="$PWD/.venv/bin:$PATH"
PYTEST_ADDOPTS='-k "test_python_dependency_contracts or test_model_enums or test_api_identity_session or test_any709_step1_sources or test_any709_step2_customer or test_kernel_mock_dev or test_commercial_sellability or test_catalog_preview_setup or test_operator_preflight_processes"' npm run test:api:fast
# Stage-wide source/customer regressions:
PYTEST_ADDOPTS='-k "any709_step1 or any709_step2 or test_presentation_di or test_billing_foundation_models or test_billing_reconciliation_models or test_lbx_client or test_lbx_selected_offer or test_source_composition or test_preflight or test_mapping_billing_calendar"' npm run test:api:fast
python scripts/repo.py test-db up
PYTEST_ADDOPTS='-k "any709_step1 or any709_step2 or test_commercial_mapping_postgres or test_mapping_publication_expiry_postgres or test_kernel_walkthrough_postgres or test_catalog_api or test_alembic_postgres or test_target_persistence_postgres or test_identity_legal_persistence_postgres"' npm run test:api:postgres
# Stop only if this test server was started solely for these checks:
python scripts/repo.py test-db stop
```

Expected: selected tests pass without skips/zero selection; registration returns
200 for empty/partial FIO and 422 for invalid names; exact enums match; normal CLI
records each actual UID while stored authors stay immutable; historical v1
allowlist/lock/CAS regressions retain their behavior. Wrappers own isolated test
DB configuration; pytest owns the disposable database lifecycle.
Tests/collection, typechecks, builds, scanners, docs/architecture/check suites,
containers, browser and live LBX: **NOT_RUN** under the execution contract.
No current CI/full-QA success is claimed. Steps 3-4, customer recovery, Widget,
agreements, subscriptions and paid access are unchanged. `LBX_BILLING_TIMEZONE`
and price selection are unchanged; the actual timezone still awaits LBX support.

## PR #150 remaining review fixes (base f6746ba, 2026-10-26)

Status: **IMPLEMENTED_AWAITING_HUMAN_VALIDATION**. This is a narrow correction
of the current checkout. Earlier PASS evidence below does not validate this
revision; the local implementation plan was not changed.

- Moved the shared exact-money, quantity and missing-value/refusal helpers
  unchanged into `apps/api/app/integrations/lbx/offer_values.py`; updated
  `selected_offer.py` and `current_offer.py` imports. Static file counts after
  formatting: selected **454**, current **258**, helpers **70** lines. The
  existing 500-line limit and its exceptions remain unchanged. No normalization
  algorithm, Decimal precision, refusal category or comment was discarded.
- Corrected `test_product_head_constraints_reject_invalid_scope_cas_and_duplicate_origin`
  in `apps/api/tests/test_alembic_postgres.py`: FK metadata independently checks
  the exact composite reference and `ON DELETE RESTRICT`; invalid-reference
  INSERT cases retain their named-constraint assertions. DELETE of both a
  referenced and an unreferenced revision must raise `ProgrammingError`,
  SQLSTATE `P0001`, with the exact immutable-history reason. Full mapping/head
  snapshots must remain unchanged. No trigger or working schema was altered.
- Updated `apps/api/tests/test_kernel_walkthrough_postgres.py` to override
  `get_session_factory` with the isolated PostgreSQL factory. Kept `get_db`
  separately; `monkeypatch.setitem` restores both overrides at teardown in both
  HTTP scenarios. The stale catalog `SessionLocal` patch was removed; no other
  direct test consumers remain. Publication/source faults/restart/recovery,
  history, secret-redaction and no-automatic-promotion assertions are retained.

Executed commands, all **exit 0**:

```bash
API_FILES=(
  apps/api/app/integrations/lbx/offer_values.py
  apps/api/app/integrations/lbx/selected_offer.py
  apps/api/app/integrations/lbx/current_offer.py
  apps/api/tests/test_alembic_postgres.py
  apps/api/tests/test_kernel_walkthrough_postgres.py
)
.venv/bin/python -m ruff format --config apps/api/pyproject.toml "${API_FILES[@]}"
.venv/bin/python -m ruff check --config apps/api/pyproject.toml "${API_FILES[@]}"
git diff --check
```

Ruff formatted one file and left four unchanged. Generation was not needed:
no schema, OpenAPI or generated contract changed. Final diff review found only
these five Python paths and this handoff; no new runtime feature or Steps 2–4.

**Tests and architecture/CI validation: NOT_RUN.** No collection, typechecks,
builds, migrations, containers, browser or LBX calls were executed. Exact human
commands, from repository root:

```bash
export PATH="$PWD/.venv/bin:$PATH"
npm run architecture:check
PYTEST_ADDOPTS='-k "test_lbx_selected_offer_normalization or test_lbx_selected_offer_failures or test_any709_step1_sources"' npm run test:api:fast
python scripts/repo.py test-db up
PYTEST_ADDOPTS='-k "test_product_head_constraints_reject_invalid_scope_cas_and_duplicate_origin or test_clean_first_install_has_expected_revisions_and_exact_application_schema or test_kernel_walkthrough_postgres"' npm run test:api:postgres
# Stop only if this server was started solely for these tests:
python scripts/repo.py test-db stop
```

Expected: architecture accepts the unchanged size rule; actual selected tests
have zero failures, not zero selected/all skipped. Exact-money/refusal behavior,
immutable DELETE refusal plus unchanged rows, independent FK protection and the
complete isolated HTTP walkthrough must remain valid. Remaining limitation:
human execution is pending; no CI or integration PASS is claimed.

## PR #150 Step 1 correction (2026-10-26)

Status: **IMPLEMENTED_AWAITING_HUMAN_VALIDATION**. The owner's revised local plan
was preserved byte-for-byte (SHA-256 `77d09024a2f223b4a68ba7bfcc6970ce551d96c75615799d6547e7736416850b`).
All earlier test/migration/readiness results below are historical and do not
validate this correction. No tests or collection, typechecks, builds, migrations,
container/browser/application/provider probes, staging, commits or pushes ran.

1. DTOs accept retained sanitized E04/E05 wire bodies: exact numeric `1.0`,
   provider-local midnight and history year/month. Decimal decoding remains
   strict; fractional quantities are parsed then classified as unsupported,
   invalid/nonfinite/bool values are refused, and calendar dates never become
   paid UTC intervals. The fixture README distinguishes retained bodies from
   synthetic tariff/period/Kernel/auth support.
2. Server API readiness requires only origin/username/password. Widget and
   seller requirements are separate future-operation checks. Currency/calendar
   remain offer errors; partial billing leaves Portal identity available.
3. New connection IDs depend on canonical origin and deployment, independently
   of credentials. Proven old scopes keep their immutable IDs/FKs; an authorized
   identical publish records origin on the mutable head for subsequent login
   rotation. Unknown/ambiguous real bindings conflict; synthetic history is inert.
   **New forward migration `20261026_0004_product_head_origin`: AUTHORED_NOT_RUN.**
   It adds only nullable head provenance plus origin/product uniqueness. Existing
   migration files and the working database were not changed. Before rotating an
   unbound old login, perform the runbook's one-time identical publish; a lost old
   identity without retained origin requires separate provenance reconciliation.
4. A typed provider-ID → RUB/major/scale-2 mapping replaces algorithm constants;
   another configured external RUB ID works without float conversion.
5. Catalog composition receives its session factory through DI. Each worker
   owns/closes its DB resources before HTTP. A typed source-failure exception
   preserves 503/no-store independently of diagnostic prefixes; incomplete and
   unsupported offers remain distinct.
6. Existing mock/token, production-source, exact Alembic schema/constraints and
   Portal E2E assertions were updated. Empty catalog, missing product and source
   failure have separate regressions; the false-subscription guard remains.

Changed Python paths (also the exact format/lint coverage):

```bash
API_FILES=(
  apps/api/alembic/versions/20261026_0004_product_head_origin.py
  apps/api/app/{cli/commercial_mappings,composition/catalog,core/settings,domains/catalog/{commercial_offer,link_publication,router},http/dependencies,infrastructure/queries/commercial_mappings,integrations/lbx/{client,current_offer,dto,selected_offer},models/billing_projections}.py
  apps/api/tests/{support/{any709_step1,kernel,lbx,lbx_selected_offer},test_alembic_postgres,test_any709_step1_postgres,test_any709_step1_sources,test_catalog_api,test_kernel_mock_dev,test_lbx_client,test_lbx_selected_offer_normalization,test_source_composition}.py
)
.venv/bin/python -m ruff format --config apps/api/pyproject.toml "${API_FILES[@]}"
.venv/bin/python -m ruff check --config apps/api/pyproject.toml "${API_FILES[@]}"
(cd apps/web && npm exec --no -- eslint e2e/portal-ru.spec.ts --fix --max-warnings=0)
PATH="$PWD/.venv/bin:$PATH" npm run generate
git diff --check
```

Results: Ruff format/check **exit 0** on all 26 paths; the later PostgreSQL test
and source-fixture edits were formatted/linted again, **exit 0**. ESLint **exit 0**. Generation
**exit 0**, updating only `docs/generated/db-schema.md`; OpenAPI/TS unchanged.
Whitespace lint **exit 0**. Other changed files: `.env.example`,
`.env.production.example`, `ARCHITECTURE.md`, the data-model reference, the
[existing runbook](../../engineering/lbx-product-links.md), this handoff,
`apps/api/tests/fixtures/lbx/README.md`, two retained `readiness/*.json` bodies under API
tests, and `apps/web/e2e/portal-ru.spec.ts`. No approval/profile/account-ID input
or fabricated quota was reintroduced. CLI authorization/audit, product CAS,
immutable history/pins and link/current-offer/consent separation remain.

**All new/updated tests: NOT_RUN.** Exact human commands (from repository root):

```bash
export PATH="$PWD/.venv/bin:$PATH"
PYTEST_ADDOPTS='-k "test_any709_step1_sources or test_lbx_client or test_lbx_selected_offer or test_source_composition or test_kernel_mock_dev"' npm run test:api:fast
python scripts/repo.py test-db up
PYTEST_ADDOPTS='-k "test_any709_step1_postgres or test_alembic_postgres or test_catalog_api or test_commercial_mapping_postgres"' npm run test:api:postgres
# Stop the test server only if it was started solely for this verification:
python scripts/repo.py test-db stop
# Intended local working DB only, separately from the isolated test DB:
npm run migrate:api
# With the human-configured browser harness:
npm run test:e2e -- apps/web/e2e/portal-ru.spec.ts apps/web/e2e/catalog-preview.spec.ts
```

Expect selected tests with zero failures (zero selected/all skipped is not
PASS), the full four-revision chain ending at `20261026_0004`, exactly 26
application tables, exact head PK/FK/check/unique constraints and unchanged
historical mapping documents. On the human-configured browser harness use its
configured harness defaults (or its actual `PLAYWRIGHT_BASE_URL` and
`PLAYWRIGHT_API_BASE_URL`). Then follow the runbook's exact host/container
dry-run/publish/query and read-only SQL commands: real source reads, no required
Widget secret/seller for linking, one current head, unchanged pin on identical
publish/repricing and credential rotation, separate unavailable states, no new
customer/purchase/subscription. Pending: human migration/test/live acceptance
and the actual provider billing timezone. Steps 2–4 remain untouched.

## Implemented result

Normal local/agent/production configuration now carries one server-only LBX
connection. Manual account IDs and proposal/approval/source-policy files are
absent from runtime Settings and the normal CLI. The technical Kernel mock has
no billing mounts or publisher-UID startup requirement. Invalid/partial billing
configuration produces safe billing errors without preventing Portal identity
startup; no startup HTTP or automatic publication was added.

The one authorized normal CLI supports direct dry-run/publish/query. It keeps
OS-principal audit and the shared local lock, validates an enabled Kernel
product plus complete selected LBX services/periods/prices, and records a v2
immutable link. Product-head CAS spans offer retargets. Identical association
identity is a no-op across ordinary price changes. Historical v1 evidence and
dependent pins are retained; no migration selects/promotes old rows. Conflicting
proven connection bindings produce a migration conflict rather than relabelling.
The old approval fixture builders/CLI live only under tests/support/v1_*;
normal Makefile fixture-publication shortcuts were retired.

Catalog listing discovers enabled Kernel products once, independently of links,
without LBX page fan-out. Selected detail reads the current LBX composition,
price and period, with exact decimal money and separate Kernel/LBX provenance.
Unmapped, incomplete, unsupported and source-error states remain explicit and
no-store. UI and seven locale catalogs consume the generated contract without
invented prices, quotas or purchase success. Source HTTP and short resource-owned
synchronous PostgreSQL work remain separate.

## Migration and generated output

- Authored `20261026_0003_commercial_product_heads`, after actual head `20261001_0002`.
- Adds only one product-head pointer table with unique product scope and restrictive mapping FK; no backfill or history rewrite.
- Working-database migration: **PASS** after the user authorized discarding the old local database; see the execution record below.
- Isolated test-database migration: **PASS** through the focused PostgreSQL tests.
- Executed `PATH="$PWD/.venv/bin:$PATH" npm run generate`: exit 0.
- Generated database schema, OpenAPI and TypeScript contracts were updated by the generator. No generated file was hand-edited.

## Formatting and lint evidence

Ruff format and check completed successfully for all changed API Python files.
Initial unused-import findings were corrected. Subsequent API edits were
formatted/linted again; final affected-file runs passed. ESLint completed with
exit 0, and `git diff --check` completed with exit 0. These are formatting/lint
results, not runtime validation. No typecheck or build ran.
The following explicit path set reproduces the API formatting/lint coverage:

```bash
API_FILES=(
  apps/api/alembic/versions/20261026_0003_commercial_product_heads.py
  apps/api/app/cli/commercial_mappings.py
  apps/api/app/composition/catalog.py
  apps/api/app/composition/mapping_operator.py
  apps/api/app/composition/sources.py
  apps/api/app/core/settings.py
  apps/api/app/domains/catalog/contracts.py
  apps/api/app/domains/catalog/link_publication.py
  apps/api/app/domains/catalog/preview.py
  apps/api/app/domains/catalog/product_link.py
  apps/api/app/domains/catalog/router.py
  apps/api/app/http/errors.py
  apps/api/app/infrastructure/queries/commercial_mappings.py
  apps/api/app/integrations/lbx/client.py
  apps/api/app/integrations/lbx/current_offer.py
  apps/api/app/integrations/lbx/selected_offer.py
  apps/api/app/models/__init__.py
  apps/api/app/models/billing_projections.py
  apps/api/tests/conftest.py
  apps/api/tests/support/any709_step1.py
  apps/api/tests/support/catalog_preview.py
  apps/api/tests/support/commercial_mappings.py
  apps/api/tests/support/kernel.py
  apps/api/tests/support/kernel_walkthrough.py
  apps/api/tests/support/lbx.py
  apps/api/tests/support/lbx_selected_offer.py
  apps/api/tests/support/operator_processes.py
  apps/api/tests/support/v1_cli.py
  apps/api/tests/support/v1_mapping_operator.py
  apps/api/tests/test_any709_step1_postgres.py
  apps/api/tests/test_any709_step1_sources.py
  apps/api/tests/test_architecture.py
  apps/api/tests/test_catalog_api.py
  apps/api/tests/test_catalog_preview_setup.py
  apps/api/tests/test_commercial_mapping_postgres.py
  apps/api/tests/test_commercial_sellability.py
  apps/api/tests/test_kernel_walkthrough_postgres.py
  apps/api/tests/test_lbx_client.py
  apps/api/tests/test_lbx_selected_offer_failures.py
  apps/api/tests/test_lbx_selected_offer_normalization.py
  apps/api/tests/test_mapping_billing_calendar.py
  apps/api/tests/test_repository_docs.py
)
.venv/bin/python -m ruff format --config apps/api/pyproject.toml "${API_FILES[@]}"
.venv/bin/python -m ruff check --config apps/api/pyproject.toml "${API_FILES[@]}"
(cd apps/web && npm exec --no -- eslint src/features/catalog/CatalogPreviewClient.tsx tests/components/CatalogPreview.test.tsx tests/fixtures/catalog.ts e2e/catalog-preview.spec.ts e2e/catalog-stored-preview.spec.ts --fix --max-warnings=0)
git diff --check
```

## Tests and human checkpoint

### Subsequent user-authorized execution

The user explicitly authorized applying the migration and running the focused
tests after the original no-execution handoff. Results:

- `PATH="$PWD/.venv/bin:$PATH" PYTEST_ADDOPTS='-k any709_step1' npm run test:api:fast`: **23 passed**, 1236 deselected, exit 0.
- `PATH="$PWD/.venv/bin:$PATH" PYTEST_ADDOPTS='-k any709_step1' npm run test:api:postgres`: **15 passed**, 1244 deselected, exit 0.
- PostgreSQL tests used the isolated `payments_cf94dbf9_tests` database. The existing worktree PostgreSQL service was already healthy; it was neither restarted nor stopped.
- Initial read-only preflight verified local `127.0.0.1:32053`, database `payments_cf94dbf9`, APP_ENV=development. Its prior Alembic revision was **20261025_0004**, from rejected PR #143; the current branch expects predecessor **20261001_0002** and target **20261026_0003**. The new product-head table was absent.
- Prior working data included two mapping revisions; zero billing customers, purchase intents and external subscriptions.
- The first direct `npm run migrate:api` attempt did not execute because automatic permission review timed out. A guarded retry refused the unknown branch revision without changing the database. The user then explicitly authorized deleting the local database's data and applying the current chain.
- Because the rejected branch's migrations are forward-only, the authorized operation recreated only local development database `payments_cf94dbf9`. Exact repository/project, APP_ENV, loopback host, port, database name and prior revision guards ran before deletion. The API service was temporarily stopped; other databases and Docker volumes were preserved.
- The canonical `repo.cmd_migrate_api` command (`python -m alembic -c apps/api/alembic.ini upgrade head`) completed with exit 0: **20260924_0001 → 20261001_0002 → 20261026_0003**. No rejected-branch migration was imported or stamped.
- Read-only verification confirmed **26 application tables**, `commercial_product_heads` present, old `billing_purchase_scope_holds` absent, and zero users, mappings, product heads, billing customers, purchase intents and external subscriptions immediately after migration.
- API startup completed successfully. Post-start verification confirmed revision **20261026_0003**, zero users, six document versions and one legal entity seeded by normal startup. API readiness returned **HTTP 200**, `{"status":"ready"}`; API, web and PostgreSQL containers were healthy. The user can register again.
- An initial read-only seed-count query used the incorrect name `legal_documents` and failed; the corrected `document_versions` query succeeded. This did not change data or affect migration success.
- **NOT_RUN:** frontend component/E2E tests, broader suites, live-provider/browser acceptance and typechecks/builds. Focused tests: **38 passed**; working-database migration: **PASS**. Full live acceptance remains pending.

Local readiness can be checked again with:

```bash
curl --fail --silent http://127.0.0.1:31053/api/health/ready
docker ps --filter label=com.docker.compose.project=payments-cf94dbf9 --format '{{.Names}}\t{{.State}}\t{{.Status}}'
```

### Original authoring-phase checkpoint

At the original handoff, **NOT_RUN:** all tests, including new `test_any709_step1_sources.py`,
`test_any709_step1_postgres.py`, changed catalog API tests and frontend
component/E2E coverage. Written cases cover live exact money/repricing,
configuration/redaction, source failures, no startup HTTP, quantity/composition,
calendar/currency errors, separate provenance, history/populated upgrade,
concurrent first publication, cross-offer CAS, lost commit acknowledgement,
unchanged pins, no synthetic promotion and no new customer/purchase/subscription.
No tests were collected or executed. Typechecks, builds, migrations, containers,
live-provider/application probes, broader checks and fresh screenshots were not run.

Exact selected-step human commands (the host here needs the repository venv on PATH):

```bash
export PATH="$PWD/.venv/bin:$PATH"
PYTEST_ADDOPTS='-k any709_step1' npm run test:api:fast
python scripts/repo.py test-db up
PYTEST_ADDOPTS='-k any709_step1' npm run test:api:postgres
python scripts/repo.py test-db stop
```

Expect actual selected tests and no failure; zero selected/all skipped is not PASS.
Then follow the [normal LBX runbook](../../engineering/lbx-product-links.md)
for intended-local-DB migration, ordinary startup, direct host/current-worktree
container CLI commands, read-only SQL, and desktop/mobile/browser validation.
The runbook contains the exact dry-run/publish/query commands and expected
single-head, immutable-history and unchanged billing-object counts.

## Limitations and final diff review

- Human setup must provide connection secrets, actual operator UID/lock permissions and the actual LBX billing IANA timezone. Supplied 043 evidence does not establish a timezone; it was not guessed.
- RU currency interpretation is explicitly configured as ID 1 / RUB major units, two decimals. Unknown interpretations remain offer errors. Non-unit quantities with nonzero connection charges remain incomplete without a proven quantity basis.
- Real Kernel producer/conformance remains ANY-711; production launch approval remains separately gated. A development Kernel mock can accompany configured real LBX; its provenance remains SIMULATED independently of LBX.
- Buy, customer creation, Widget, consent/purchases, recovery orchestration and paid access remain later steps. No legal source text was changed.
- Diff reviewed against Step 1 result/acceptance and its role in the final scenario: normal setup and one live association precede the later customer/purchase flow. No later step was started, no external provider was changed, and no stage/commit/push occurred. The local development database reset was explicitly authorized by the user.
- Focused automated tests and the working-database migration passed after user authorization. Local API readiness passed; no full live-provider/launch PASS is claimed.

## Changed files

The following is the complete Step 1 file manifest; the pre-existing untracked
implementation plan is excluded because it was not edited:

- `.env.example`
- `.env.production.example`
- `AGENTS.md`
- `ARCHITECTURE.md`
- `Makefile`
- `README.md`
- `apps/api/AGENTS.md`
- `apps/api/Dockerfile`
- `apps/api/alembic/versions/20261026_0003_commercial_product_heads.py`
- `apps/api/app/cli/commercial_mappings.py`
- `apps/api/app/composition/catalog.py`
- `apps/api/app/composition/mapping_operator.py`
- `apps/api/app/composition/sources.py`
- `apps/api/app/core/settings.py`
- `apps/api/app/domains/catalog/contracts.py`
- `apps/api/app/domains/catalog/link_publication.py`
- `apps/api/app/domains/catalog/preview.py`
- `apps/api/app/domains/catalog/product_link.py`
- `apps/api/app/domains/catalog/router.py`
- `apps/api/app/http/errors.py`
- `apps/api/app/infrastructure/queries/commercial_mappings.py`
- `apps/api/app/integrations/lbx/client.py`
- `apps/api/app/integrations/lbx/current_offer.py`
- `apps/api/app/integrations/lbx/selected_offer.py`
- `apps/api/app/models/__init__.py`
- `apps/api/app/models/billing_projections.py`
- `apps/api/tests/conftest.py`
- `apps/api/tests/support/any709_step1.py`
- `apps/api/tests/support/catalog_preview.py`
- `apps/api/tests/support/commercial_mappings.py`
- `apps/api/tests/support/kernel.py`
- `apps/api/tests/support/kernel_walkthrough.py`
- `apps/api/tests/support/lbx.py`
- `apps/api/tests/support/lbx_selected_offer.py`
- `apps/api/tests/support/operator_processes.py`
- `apps/api/tests/support/v1_cli.py`
- `apps/api/tests/support/v1_mapping_operator.py`
- `apps/api/tests/test_any709_step1_postgres.py`
- `apps/api/tests/test_any709_step1_sources.py`
- `apps/api/tests/test_architecture.py`
- `apps/api/tests/test_catalog_api.py`
- `apps/api/tests/test_catalog_preview_setup.py`
- `apps/api/tests/test_commercial_mapping_postgres.py`
- `apps/api/tests/test_commercial_sellability.py`
- `apps/api/tests/test_kernel_walkthrough_postgres.py`
- `apps/api/tests/test_lbx_client.py`
- `apps/api/tests/test_lbx_selected_offer_failures.py`
- `apps/api/tests/test_lbx_selected_offer_normalization.py`
- `apps/api/tests/test_mapping_billing_calendar.py`
- `apps/api/tests/test_repository_docs.py`
- `apps/web/e2e/catalog-preview.spec.ts`
- `apps/web/e2e/catalog-stored-preview.spec.ts`
- `apps/web/src/features/catalog/CatalogPreviewClient.tsx`
- `apps/web/src/generated/api-contracts/index.ts`
- `apps/web/src/generated/api-contracts/types.gen.ts`
- `apps/web/src/messages/de.json`
- `apps/web/src/messages/en.json`
- `apps/web/src/messages/es.json`
- `apps/web/src/messages/fr.json`
- `apps/web/src/messages/it.json`
- `apps/web/src/messages/pt.json`
- `apps/web/src/messages/ru.json`
- `apps/web/tests/components/CatalogPreview.test.tsx`
- `apps/web/tests/fixtures/catalog.ts`
- `docker-compose.agent.yml`
- `docker-compose.kernel-mock.dev.yml`
- `docker-compose.prod.yml`
- `docker-compose.yml`
- `docs/PRODUCT.md`
- `docs/README.md`
- `docs/architecture/contours.md`
- `docs/architecture/decisions/0005-external-billing-boundary.md`
- `docs/architecture/payment-portal-data-model.md`
- `docs/contracts/kernel-capability-manifest/v1/README.md`
- `docs/engineering/DEVELOPMENT.md`
- `docs/engineering/lbx-product-links.md`
- `docs/exec-plans/active/ANY-709-step-1-handoff.md`
- `docs/generated/db-schema.md`
- `docs/generated/openapi.json`
- `docs/integrations/platform-kernel.md`
- `docs/product/ru-mvp.md`
- `docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md`
- `docs/superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md`
- `scripts/repo.py`

## Manual QA correction, 2026-10-26 (base 181b8d0)

The owner explicitly authorized execution for this correction, superseding this
plan's earlier no-test restriction for the two reported Steps 1–2 defects only.
No stage/commit/push, PR/Linear changes, production access, payment, agreement,
subscription, later-stage implementation or normative-spec edit is authorized.

The selected 043 GETs were read live and retained byte-for-byte in
`apps/api/tests/fixtures/lbx/qa043/` with their evidence/compatibility README.
The service has integer `record_id=101`, distinct from `tariff_service_id=1`, and
`prices[period_id=1].discounts=[]` without service-level `discounts`. Money and
dates remain unchanged. The stand's Swagger 1.0.11 describes the legacy
service-level period discounts; the official discount guide is separate
commercial evidence, not a guarantee of the observed inline wire extension.

`dto.py` explicitly models these fields. `discounts.py` selects evidence only
after matching the chosen inline price's service, period, money and effective
date. It supports either representation, rejects contradictory/ambiguous/null
or missing evidence distinctly, and parses/refuses nonempty discounts as
unsupported. Another period cannot fill in missing selected evidence. Both
current and retained selected-offer consumers use it. Known metadata is typed;
unclassified extensions still fail closed. No blanket DTO ignore, money
coercion, current-price algorithm or timezone change was made.

The ordinary configured Portal endpoint
`GET http://localhost:39053/api/catalog/products/proposal_ai` returned HTTP 200,
`CURRENT_OFFER`, 100.00 RUB recurring, 0.00 connection, quantity 1, monthly
instance-start period. Technical product provenance remains `SIMULATED` (the
existing separate Kernel development mock); billing provenance is
`CONFIGURED_SOURCE`. Existing local `LBX_BILLING_TIMEZONE=Etc/UTC` was preserved,
not introduced or confirmed by this check. Provider timezone confirmation is
still required before claiming genuine commercial-calendar acceptance.

Regression coverage includes captured payloads, legacy/both discount formats,
nonempty/missing/null/wrong type/conflicting/other-period/duplicate discount
cases, typed record metadata and identity separation. Existing exact-money,
quantity and selected-composition checks remain. The retained selected-offer
null regression now expects the more precise `discounts_null` reason.

Execution evidence and remaining Widget/original-operation limitations are in
the [Step 2 QA correction](ANY-709-step-2-handoff.md#manual-qa-correction-2026-10-26-base-181b8d0).
No migration or Portal HTTP contract changed; generated artifacts are unchanged.
