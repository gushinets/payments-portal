# ANY-709 Step 1 handoff

Status: **IMPLEMENTED_AWAITING_HUMAN_VALIDATION**
Date: 2026-10-26
Selected scope: Step 1 only. The supplied untracked implementation plan was preserved unchanged.

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
