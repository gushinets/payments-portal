# ANY-709 Step 2 delivery

Status: **IMPLEMENTED_AWAITING_HUMAN_VALIDATION**. No runtime PASS claimed.
Scope: approved [Step 2](ANY-709-implementation-plan.md#5-step-2---optional-fio-one-customer-and-a-real-account-widget) only; Steps 3-4 remain deferred.

The account now has an explicit localized billing button independent of catalog
loading, mappings, prices, seller/calendar and subscriptions. Verified existing
and new users use the actual configured SDK and customer-only presentation.
Registration supports independently optional trimmed FIO, existing users stay
nullable, and registration/login/GET do not create billing objects.

One permanent customer operation reserves the opaque key before HTTP. Its
possible-send claim commits the ownership fence, original two-hour deadline and
coalesced recovery item atomically. Concurrent opens reuse that identity;
200/201 receipts require paired point proof. Possible-send failures/crashes use
bounded read-only discovery; zero matches never release/replay, multiple matches
enter review. Only transport-proven before-dispatch failure can reset the SAME
operation. Overdue escalation retains the slot; restored original identity can
resolve its review. Recovery/escalation are callable without starting a scheduler.

Each open verifies Server identity, signs fresh type-7 JWT, checks Client
readiness, and rechecks Portal auth after I/O before its no-store response.
Technical credentials exist only in the transient POST. The SDK loads once per
disposable opaque-origin context under configured-origin CSP. Late results are
ignored; close/logout/user change/unmount destroy Portal-held SDK/token state.
The existing transport carries a bounded request ID so timeout and SDK errors
can be correlated without showing raw provider diagnostics.
No fake PurchaseIntent, agreement, subscription, payment or paid-access fact is
created. Customer-wide JWT/72h and provider-owned Client API risks remain.

Removed/replaced/retained: replaced blanket subscription/price prerequisites for
account viewing with identity/readiness authorization; retained purchase readback
requirements for later payment presentation, verified-email/session semantics,
immutable keys, no blind replay, Bundle 3 and seven locales. No old customer
runtime existed to remove. Legacy identity is not guessed/promoted or repaired
by PATCH. Historical binding/origin conflicts require operator review; the
migration does not reset/delete history.

Migration authored: `20261026_0005_customer_widget`, after actual head
`20261026_0004`. Adds three nullable name columns, nullable proven customer
origin and send fence, scoped non-null provider-ID uniqueness, permanent
customer-operation identity and coalesced recovery uniqueness. **NOT EXECUTED.**
Conflicting historical unique data must be reconciled; no destructive workaround.

Generation: `PATH="$PWD/.venv/bin:$PATH" npm run generate` completed twice,
**exit 0**. Generated DB schema, OpenAPI and TypeScript contracts were updated
by the generator; no generated file was hand-edited.

Formatting/lint only: final Ruff format/check **exit 0** across all changed API
Python paths; ESLint with fixes **exit 0** across changed authored web paths;
`git diff --check` **exit 0**. Initial two unused Python imports were corrected.
No tests, collection, typechecks, builds, migrations, probes, scanners, containers
or broad repository checks ran. Nothing was staged, committed, pushed or changed
in external systems.

Exact formatting/lint coverage (repository root):

```bash
API_FILES=(
  apps/api/alembic/versions/20261026_0005_customer_widget.py
  apps/api/app/composition/billing.py
  apps/api/app/composition/sources.py
  apps/api/app/core/settings.py
  apps/api/app/domains/billing/__init__.py
  apps/api/app/domains/billing/contracts.py
  apps/api/app/domains/billing/customers.py
  apps/api/app/domains/billing/router.py
  apps/api/app/domains/identity/names.py
  apps/api/app/domains/identity/router.py
  apps/api/app/domains/identity/services/auth.py
  apps/api/app/infrastructure/queries/billing_customers.py
  apps/api/app/integrations/lbx/client.py
  apps/api/app/integrations/lbx/customer.py
  apps/api/app/integrations/lbx/errors.py
  apps/api/app/main.py
  apps/api/app/models/__init__.py
  apps/api/app/models/billing_operations.py
  apps/api/app/models/billing_purchase.py
  apps/api/app/models/enums.py
  apps/api/app/models/identity.py
  apps/api/tests/test_alembic_postgres.py
  apps/api/tests/test_any709_step2_customer.py
  apps/api/tests/test_any709_step2_postgres.py
  apps/api/tests/test_api_identity_session.py
  apps/api/tests/test_billing_foundation_models.py
  apps/api/tests/test_billing_reconciliation_models.py
  apps/api/tests/test_presentation_di.py

)
.venv/bin/python -m ruff format --config apps/api/pyproject.toml "${API_FILES[@]}"
.venv/bin/python -m ruff check --config apps/api/pyproject.toml "${API_FILES[@]}"
(cd apps/web && npm exec --no -- eslint \
  eslint.config.mjs \
  'src/app/[locale]/account/page.tsx' \
  src/features/account/AccountClient.tsx \
  src/features/billing/BillingAccount.tsx \
  src/features/billing/index.ts \
  src/features/billing/official-widget-sdk.ts \
  src/shared/api/auth.ts \
  src/shared/api/billing.ts \
  src/shared/ui/AuthForm.tsx \
  tests/components/AccountClient.test.tsx \
  tests/components/SessionRaces.test.tsx \
  tests/components/any709-step2.test.tsx \
  --fix --max-warnings=0)
git diff --check
```

Tests written/updated: **NOT_RUN**. New protocol, PostgreSQL and component suites
cover optional/partial/full FIO, populated migration, transient credentials,
200/201 and malformed success, one customer under races, possible-send crash/lost
reply, late fences, zero/one/multiple discovery, fixed +2h escalation, existing
reuse, outer-key drift, stale session after await, no-store/permission guards,
no secrets in evidence/logs, explicit SDK loading, independent catalog entry,
logout/user-switch/unmount races and safe SDK/error recovery. Existing schema,
auth/DI, model, account and session regression expectations were updated.

Exact HUMAN commands, from repository root (a zero-selected/all-skipped run is
not PASS):

```bash
export PATH="$PWD/.venv/bin:$PATH"
PYTEST_ADDOPTS='-k "any709_step2 or test_api_identity_session or test_presentation_di or test_billing_foundation_models or test_billing_reconciliation_models or test_lbx_client or test_source_composition"' npm run test:api:fast
python scripts/repo.py test-db up
PYTEST_ADDOPTS='-k "any709_step2 or test_alembic_postgres or test_target_persistence_postgres or test_identity_legal_persistence_postgres or test_any709_step1_postgres or test_commercial_mapping_postgres"' npm run test:api:postgres
# Stop only if this test server was started solely for this verification:
python scripts/repo.py test-db stop
npm --workspace @anytoolai/web run test:components -- any709-step2 AccountClient SessionRaces AuthForm AuthContractValidation
# Intended local working environment only, separate from the isolated test DB:
npm run migrate:api
npm run repo:up -- --reuse
```

Expected: tests select and pass; head is `20261026_0005`; existing identities/FIO
stay nullable; explicit open results in one customer and no Portal purchase or
subscription. Follow the [human Widget checkpoint and exact read-only SQL helper](../../engineering/lbx-product-links.md#human-account-widget-checkpoint-step-2)
for existing/new users, two tabs/products, failed/missing quote, real empty Widget,
privacy, desktop/mobile accessibility and close/logout checks. **CUSTOMER_WIDGET_PASS**
requires human observation; it is not payment/full-ANY-709/Kernel-access PASS.
Real Server/Widget secrets, Client readiness, provider rendering/CSP compatibility
and operator resolution of any legacy conflict remain external prerequisites.
No worker is installed; later program Step 8 owns background recovery.

Protocol implementation uses the approved plan/Phase 0 facts plus the narrow
[official SDK interface](https://docs.lbxbilling.ru/integration_lbx/widget/widget_connection/)
and [vendor users/Client API reference](https://demo.lbxbilling.ru/swagger/).
No live provider experiment was repeated.

Changed files (including generated output and this handoff):

- `ARCHITECTURE.md`
- `README.md`
- `apps/api/AGENTS.md`
- `apps/api/alembic/versions/20261026_0005_customer_widget.py`
- `apps/api/app/composition/billing.py`
- `apps/api/app/composition/sources.py`
- `apps/api/app/core/settings.py`
- `apps/api/app/domains/billing/__init__.py`
- `apps/api/app/domains/billing/contracts.py`
- `apps/api/app/domains/billing/customers.py`
- `apps/api/app/domains/billing/router.py`
- `apps/api/app/domains/identity/names.py`
- `apps/api/app/domains/identity/router.py`
- `apps/api/app/domains/identity/services/auth.py`
- `apps/api/app/infrastructure/queries/billing_customers.py`
- `apps/api/app/integrations/lbx/README.md`
- `apps/api/app/integrations/lbx/client.py`
- `apps/api/app/integrations/lbx/customer.py`
- `apps/api/app/integrations/lbx/errors.py`
- `apps/api/app/main.py`
- `apps/api/app/models/__init__.py`
- `apps/api/app/models/billing_operations.py`
- `apps/api/app/models/billing_purchase.py`
- `apps/api/app/models/enums.py`
- `apps/api/app/models/identity.py`
- `apps/api/tests/test_alembic_postgres.py`
- `apps/api/tests/test_any709_step2_customer.py`
- `apps/api/tests/test_any709_step2_postgres.py`
- `apps/api/tests/test_api_identity_session.py`
- `apps/api/tests/test_billing_foundation_models.py`
- `apps/api/tests/test_billing_reconciliation_models.py`
- `apps/api/tests/test_presentation_di.py`
- `apps/web/eslint.config.mjs`
- `apps/web/src/app/[locale]/account/page.tsx`
- `apps/web/src/features/account/AccountClient.tsx`
- `apps/web/src/features/billing/BillingAccount.tsx`
- `apps/web/src/features/billing/index.ts`
- `apps/web/src/features/billing/official-widget-sdk.ts`
- `apps/web/src/generated/api-contracts/index.ts`
- `apps/web/src/generated/api-contracts/types.gen.ts`
- `apps/web/src/messages/de.json`
- `apps/web/src/messages/en.json`
- `apps/web/src/messages/es.json`
- `apps/web/src/messages/fr.json`
- `apps/web/src/messages/it.json`
- `apps/web/src/messages/pt.json`
- `apps/web/src/messages/ru.json`
- `apps/web/src/shared/api/auth.ts`
- `apps/web/src/shared/api/billing.ts`
- `apps/web/src/shared/ui/AuthForm.tsx`
- `apps/web/tests/components/AccountClient.test.tsx`
- `apps/web/tests/components/SessionRaces.test.tsx`
- `apps/web/tests/components/any709-step2.test.tsx`
- `docs/PRODUCT.md`
- `docs/SECURITY.md`
- `docs/architecture/payment-portal-data-model.md`
- `docs/engineering/lbx-product-links.md`
- `docs/exec-plans/active/ANY-709-implementation-plan.md`
- `docs/exec-plans/active/ANY-709-step-2-handoff.md`
- `docs/generated/db-schema.md`
- `docs/generated/openapi.json`
- `docs/product/ru-mvp.md`
- `docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md`
- `docs/superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md`

## PR #150 Step 2 review amendment (2026-10-26)

Status: **IMPLEMENTED_AWAITING_HUMAN_VALIDATION**. Based on current checkout
`8be6eca`; existing owner changes, including specs, are retained.

- Proven unsent failures after a committed claim, before task admission, or
  after scheduling a task that stopped before dispatch release only the owning
  operation/fence. The next explicit open reuses its operation and outer key.
  Preflight exposes the same counted task; a deadline alone never proves it
  stopped. Possible dispatch, lost replies, running tasks and uncertain commits
  retain the existing read-only recovery/no-replay rule.
- Preauth GET uses the existing finite attempt/backoff limits and same budget;
  internal retry wrappers no longer escape as generic 500 errors. Server auth,
  source outage, invalid response and Client readiness remain distinct. Invalid
  source responses have a separate localized message in all seven catalogs.
- Error envelopes use the existing size/encoding/deadline limits. Diagnostics
  contain HTTP status, bounded numeric LBX code, allowlisted reason, stage,
  endpoint template and Portal request ID. Known invalid-login errors become
  `credentials_denied`; unknown text stays `unknown`. Remote text and credentials
  are never logged. Client denial preserves the bound customer.
- Extracted cohesive wire/stream/decoder helpers into `_transport.py`, retaining
  the single client and existing pools. `client.py` is below 500 lines; no size
  exception or limit change. Existing direct consumers keep their imports.
- The existing empty-catalog E2E now includes Billing's H2/named region, verified
  button state and no bootstrap/SDK/iframe before explicit action, retaining the
  H1, keyboard, layout and Axe assertions in all four viewport/email variants.

Removed/replaced/retained: replaced deadline-only unsent handling, leaked preauth
retry wrappers and outdated heading counts; retained account-only admission,
permanent customer identity, fences, protected cleanup and no POST retry. No
Steps 3-4, normative specs, migrations or SDK sandbox/CSP changes were added.

Changed files in this amendment:

- `apps/api/app/composition/billing.py`
- `apps/api/app/domains/billing/customers.py`
- `apps/api/app/infrastructure/preflight.py`
- `apps/api/app/integrations/lbx/{client,_transport}.py`
- `apps/api/tests/test_any709_step2_failures.py`
- `apps/api/tests/test_any709_step2_failures_postgres.py`
- `apps/web/e2e/portal-ru.spec.ts`
- `apps/web/src/features/billing/BillingAccount.tsx`
- `apps/web/src/messages/{de,en,es,fr,it,pt,ru}.json`
- `apps/web/tests/components/any709-step2.test.tsx`
- This existing handoff.

Actual formatting/lint commands, repository root; all **exit 0**:

```bash
API_REVIEW_FILES=(
  apps/api/app/composition/billing.py
  apps/api/app/domains/billing/customers.py
  apps/api/app/infrastructure/preflight.py
  apps/api/app/integrations/lbx/client.py
  apps/api/app/integrations/lbx/_transport.py
  apps/api/tests/test_any709_step2_failures.py
  apps/api/tests/test_any709_step2_failures_postgres.py
)
.venv/bin/python -m ruff format --config apps/api/pyproject.toml "${API_REVIEW_FILES[@]}"
.venv/bin/python -m ruff check --config apps/api/pyproject.toml "${API_REVIEW_FILES[@]}"
(cd apps/web && npm exec --no -- eslint e2e/portal-ru.spec.ts src/features/billing/BillingAccount.tsx tests/components/any709-step2.test.tsx --fix --max-warnings=0)
git diff --check
```

Generation: **NOT_NEEDED / NOT_RUN**; no schema, OpenAPI, generated wire or other
generated source changed. Tests, collection, typechecks, builds, migrations,
architecture/broad checks, containers, browser and live requests: **NOT_RUN**.
New tests cover claim/task admission deadlines, same-identity reopen, stale and
nonowner release, bounded preauth failures, lost replies with empty discovery,
still-running POST, safe diagnostics/size caps and bound Client denial; existing
component and E2E regressions are updated. No staging, commit, push or external
provider/configuration changes.

Exact targeted HUMAN commands, repository root (not executed by Codex):

```bash
export PATH="$PWD/.venv/bin:$PATH"
PYTEST_ADDOPTS='-k "any709_step2 or test_lbx_client or test_preflight or test_source_composition"' npm run test:api:fast
python scripts/repo.py test-db up
PYTEST_ADDOPTS='-k any709_step2' npm run test:api:postgres
# Stop only if this isolated test server was started for these checks:
python scripts/repo.py test-db stop
npm --workspace @anytoolai/web run test:components -- any709-step2
npm run architecture:check
# With the intended browser harness already running:
npm run test:e2e -- apps/web/e2e/portal-ru.spec.ts --grep 'account preserves identity and email verification with an empty catalog'
```

Expected: selected tests pass without skips; preauth/proven-unsent failures leave
the same operation pending; explicit recovery creates at most one customer;
possible-send failures never authorize another POST; the four E2E variants pass.
Architecture must be checked by the human; line count alone is not its PASS.

Separate real-provider acceptance remains required: open the **actual Widget
through Portal**, reopen using the **same LBX customer**, then verify that close
and logout remove it. Isolated protocol/component tests do not establish real
SDK compatibility with the opaque sandbox wrapper. No CI, runtime or live Widget
PASS is claimed; real credentials, Client readiness and human SDK acceptance
remain external prerequisites.
