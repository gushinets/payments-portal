# ANY-709 Step 2 delivery

Status: **IMPLEMENTED_AWAITING_HUMAN_VALIDATION**. No runtime PASS claimed.
Scope: approved [Step 2](ANY-709-implementation-plan.md#5-step-2---optional-fio-one-customer-and-a-real-account-widget) only; Steps 3-4 remain deferred.

## PR #150 nullable-name and enum correction (base 536e37a, 2026-10-26)

Status: **IMPLEMENTED_AWAITING_HUMAN_VALIDATION**. Corrected `OptionalName` so
normalization runs before the nullable union and only its string branch has
`max_length=100`. Each FIO field remains independently optional: omitted, null,
empty and whitespace values normalize to None, populated values trim, 100
characters are accepted after trim, and 101/non-string/internal controls reject.
The existing normalizer, auth service, factories, models and migration chain
were retained. The exact enum test now includes the existing
`ExternalCreateOperationState` values/export without changing runtime enums.

Expanded `test_any709_step2_customer.py` and `test_api_identity_session.py`
with normalization/boundary, HTTP 200/422, persisted-session and API-schema
regressions; tests are **NOT_RUN**. Compatibility tests remain unchanged.
Authorized generation moved the three `maxLength=100` constraints into OpenAPI
string branches; generated TypeScript remains `?: string | null` and unchanged.
Ruff and `git diff --check` passed; generation passed after adding the existing
`.venv/bin` to PATH (`python` was initially unavailable). No new migration.

The companion removal of the runtime UID allowlist retains OS-principal audit,
private locks/CAS/history and historical v1 checks. Full changed-file details,
actual format/generation results and exact human QA commands for both steps and
affected regressions are in the
[joint correction handoff](ANY-709-step-1-handoff.md#pr-150-steps-1-2-confirmed-fixes-base-536e37a-2026-10-26).
Earlier PASS evidence does not validate this correction. No tests, collection,
typechecks, builds, scanners, check suites, containers, browser or live LBX ran;
customer recovery/Widget/agreements/subscriptions/paid access and Steps 3-4 are
unchanged. Current price/calendar behavior now follows the direct LBX support
answer and the [2026-10-27 Step 1 correction](ANY-709-step-1-handoff.md#current-price-and-moscow-calendar-correction-2026-10-27-base-d8a8758).

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

## Manual QA correction, 2026-10-26 (base 181b8d0)

**Later owner follow-up:** the [pending investigation below](#owner-pending-follow-up-2026-10-26)
updates the original operation's current state and supplies previously missing
archived first-POST evidence. Earlier snapshots describe the initial QA run.

Scope: the two owner-reported Steps 1–2 defects. The owner explicitly authorized
local execution, isolated tests and test-043 reads/customer smoke for this
correction, then separately approved the second synthetic customer. Earlier
NOT_RUN entries remain historical. The current branch/HEAD was `ANY-709` /
`181b8d0b498311da043a49289ab9aa5b444bc4dd`, initially clean. Owner changes were
not reverted or restored from the previous experiment.

### Original operation: outcome still unknown, no replay

Read-only inspection found operation `84b02ba9-cf64-4bef-90e1-88a7be46d0cf`
created at 08:01:34 UTC, now `pending`, with non-null fence, no receipt/provider
binding, and cleared unknown timestamps. Its review and work item were manually
resolved/done at approximately 11:01:52 UTC. The retained resolution asserts
`operator_confirmed_no_external_effect`; that assertion is not independently
verified provider evidence. The current container logs begin after the first
attempt. No retained first POST request/status/body was found. Config/code show
what the serializer would send, not what that first attempt actually sent.
A new authorized GET search by the original opaque outer key returned HTTP/LBX
200 with zero candidates. That does not prove absence after a possible send.

No original-user billing open, POST, binding, reset, review resolution or
operation update was performed. Its row remains `pending` exactly as found.
Do not open that user's normal billing path while this manually retriable state
lacks a proven absence predicate. Safe restoration needs provider-side request/
audit evidence for the original attempt, or a candidate ID followed by detailed
paired `user_id`/original `outer_id` proof. Empty discovery, UI absence, email or
FIO are insufficient. Until such evidence exists, preserve the slot and use
read-only investigation; any audited quarantine/release is a separate owner
operation. This session does not declare that original failure repaired.

### Confirmed defects and implementation

- `client.py` distinguishes HTTPX pool/connect timeout and connect failure
  before receiving a response from write/read/protocol/late failures. Only the
  proven-unsent case releases its own committed claim. Durable send fencing
  stays before POST; ambiguous outcomes and uncertain commits never authorize
  another CREATE. GET retry budgets retain their timeout/network meanings.
- `_transport.py` decodes once under existing size/encoding/deadline limits,
  handles documented nested `response.error` and LBX errors inside HTTP success,
  and emits allowlisted stage/HTTP/LBX/schema categories with request/operation
  correlation. Untrusted remote text/Pydantic input is never logged. A rejected
  CREATE is not assumed harmless merely from HTTP 4xx.
- `customers.py` commits a receipt candidate in existing recovery fields using
  schema `customer-create-receipt:v1` and document key
  `provider_customer_candidate_id`, under the same operation/key/fence, before
  the verifying network GET. It is not `provider_customer_id`. Reopens prefer
  this durable hint; only point proof binds. Invalid/conflicting/stale hints
  refuse; release cannot erase a received candidate. No DB transaction spans
  HTTP and no new migration/state machine/worker/repair CLI was added.
- Candidate lists may omit `outer_id` as documented by Swagger `ShortUserInfo`.
  They never establish ownership and multiple candidates are not first-picked.
  Detailed GET must match both requested ID and original key.
- The first controlled run exposed an additional actual normal-path blocker:
  043's detailed HTTP/LBX 200 response includes nonempty `password`, which the
  old client rejected after DTO decoding. `LbxUser` now projects only identity
  fields and discards credential/contact fields instead of retaining them or
  rejecting otherwise valid proof. The password value was neither printed nor
  stored. This is proven for the new run, not the unknown historical attempt.

### Live evidence and mutations

Two explicitly synthetic Portal users were registered through ordinary HTTP
registration, received verification mail through a temporary loopback SMTP
receiver, and confirmed through the ordinary authenticated confirmation API.
Both unverified billing requests first returned 403. No direct verification flag
or auth bypass was used. Browser login/open used the ordinary configured Portal
at `http://localhost:39053`, real SDK and test LBX 043.

First test operation `172dee69-c699-4807-922d-3d548155c71f` sent one POST
(HTTP/LBX 201), persisted its receipt, then hit the confirmed detail-password
rejection. After correction it recovered by the saved ID and reached Server
point proof + Client HTTP/LBX 200, without another POST. Several explicit
reopens reused it. Provider ID 24 is now verified/bound.

Second operation `c4510798-92ff-44cf-b906-317c7e274276` exercised a clean first
open on the corrected code: auth 200 → one users POST 201 → detailed GET 200 →
binding → Client GET 200 → Portal readiness. Provider ID 25 is verified/bound.
Both accounts omitted FIO. All three FIO shapes are additionally covered in
isolated PostgreSQL tests. POST fields are type=2, original opaque outer_id,
email and generated transient login/password; absent FIO is omitted, not
fabricated. Portal user UUID, outer key and provider ID remain distinct.

Local application totals changed from 1 to 3 users/customers; PurchaseIntent
and external subscription counts remain 0. No agreement/subscription/payment
CREATE endpoint was called, and no LBX configuration was changed. Existing
original operation/review/work rows remain untouched. Only normal new-user
identity/consent/session/verification and customer/receipt/binding/recovery rows
were written. No application migration ran. PostgreSQL test migrations/resets
were confined to pytest's disposable `_tests` database.

The API container was refreshed from current source without deleting data or
volumes. Temporary diagnostic API/web/SMTP processes were stopped; the normal
worktree services were retained. Test account credentials are not part of Git
or this evidence. The host-only diagnostic catalog's initial `kernel_unavailable`
was an internal Docker hostname mismatch; the ordinary configured Portal source
path returned the Step 1 current offer without changing connection settings.

### Browser outcome and remaining acceptance

Actual official `lbxwidget.js` loaded and created its real
`https://043.lbxbilling.ru/widget/index.html` iframe, but the SDK displayed
its localized Widget-load-failure message. Its public iframe/app assets return 200; the public
loader reports missing iframe readiness. This session has not established the
underlying browser/provider cause. Do not claim CUSTOMER_WIDGET_PASS. The
Portal bootstrap/identity success is distinct from visual SDK readiness.
Closing the Widget and logout removed the iframe; no token was inspected in
browser storage or printed. The opaque-origin sandbox/CSP was preserved.

The original operation outcome, actual Widget rendering, and the previously
unconfirmed billing timezone keep complete Steps 1–2 QA acceptance open. No
payment-capable Widget, agreements, subscriptions, access grants, webhooks,
background workers or Steps 3–4 were implemented.

### Executed verification and final ledger

Final canonical `npm run check`: **exit 0**. It passed documentation,
generation freshness (no generated diff), architecture, Ruff, frontend lint,
38 frontend boundary checks, all 300 component tests, production web build,
1,286 PostgreSQL-free API tests and 177 PostgreSQL tests. Automated Playwright
E2E was explicitly **SKIPPED** by the canonical command because `RUN_E2E` was
not enabled; the real browser scenario above was driven separately, without
SDK/network substitutions. Browser visual Widget acceptance remains **FAIL**.

The broad check ran outside the restrictive sandbox with live connection inputs
blanked **only in the check process**, and two-core CPU affinity to bound test
workers. No `.env`, application setting, test timeout, package/dependency or
worker configuration file was changed. The earlier sandbox boundary failure,
component-worker timeout and local development-source contamination are not
reported as passing runs. A first full API run had 1,452 passes / 5 failures:
four were development Kernel environment contamination, and one retained null
assertion needed the new precise reason. All are covered by the final green
canonical check.

The executed check wrapper was `/tmp/any709_qa_checks.py`; its reproducible
contents, run with the root venv Python from repository root, are:

```python
import os
import subprocess
from pathlib import Path

environment = dict(os.environ)
environment["PATH"] = str(Path.cwd() / ".venv/bin") + os.pathsep + environment["PATH"]
for key in (
    "KERNEL_BASE_URL", "KERNEL_SERVICE_TOKEN", "KERNEL_MOCK_TOKEN",
    "LBX_BASE_URL", "LBX_SERVER_USERNAME", "LBX_SERVER_PASSWORD",
    "LBX_WIDGET_SIGNING_SECRET", "LBX_SELLER_ORGANIZATION_ID",
):
    environment[key] = ""
environment["KERNEL_MOCK_ENABLED"] = "0"
os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
raise SystemExit(subprocess.call(["npm", "run", "check"], env=environment))
```

The final receipt-owner guard additionally rejects a non-sending reader with
the same fence. After that last diff-review adjustment, the normal name-shape,
stale/nonowner/conflicting receipt and uncertain claim/receipt commit cases
were rerun: **6 PostgreSQL tests passed**. Broader PostgreSQL coverage had
already passed all 177 tests. The exact final targeted command was:

```bash
PATH="$PWD/.venv/bin:$PATH" \
PYTEST_ADDOPTS='-k "test_any709_qa_receipt_rejects_stale_fences_and_conflicting_candidates or test_any709_qa_fresh_create_names_point_proof_and_reopen or test_any709_qa_uncertain_commit_never_authorizes_another_post"' \
npm run test:api:postgres
```

The new QA suites plus existing Step 2 tests cover fresh success/reuse; omitted,
partial and full FIO; documented nested errors; pool/connect versus write/read/
protocol failure; no blind replay; durable receipt before failing point GET and
recovery across client restart; short/zero/multiple candidate lists; races,
stale fences and uncertain commit acknowledgements. Offer tests retain exact
money/composition behavior and the raw commercial captures. Final Ruff/format,
documentation and whitespace checks passed.

At the end of that QA run, before the later owner follow-up, read-only evidence
(`.harness/any709-qa/live-summary.json`, ignored) showed that each
of the two test keys has exactly one LBX candidate and one POST; their Portal
ready counts are respectively 3 and 2. The original operation ID/fence/unknown
fields/update timestamp are unchanged. Application totals are 3 users, 3
customer slots, 0 PurchaseIntents and 0 external subscriptions. Browser logout
removed every Widget iframe for both test users. No secrets/customer bodies
were added to fixtures, Git or diagnostic output. No staging, commit, push,
PR/Linear write or test-database container stop was performed (PostgreSQL was
already serving the existing normal worktree).


## Owner pending follow-up, 2026-10-26

Owner-reported Portal request `a5c15d82d08a3fbcdf69a9e049bb1559` returned
`billing_customer_pending`. Current container logs establish that this request
at 13:26:55–56 UTC performed only GET `/users` with HTTP/LBX 200, then returned
pending without a candidate. It did not start a CREATE or reach Client/SDK
bootstrap.

The operation is the original `84b02ba9-cf64-4bef-90e1-88a7be46d0cf`, now
`unknown`, with a new fence and fixed recovery interval 13:24:58–15:24:58 UTC.
It has no receipt candidate, provider binding or resolved timestamp. This is a
change after the previous QA snapshot, not an agent reset during this follow-up.
No database write or original-customer billing open was performed by this
follow-up investigation.

The local Loki archive retained evidence that the current container lacked.
Its OTEL billing fields are structured attributes, rather than JSON text in the
message body; a body-only operation-ID search does not retrieve them. Bounded
UTC-range queries, followed by allowlisted structured-field extraction, found:

- Initial request: Server auth HTTP 200 at 08:01:35.616 UTC, then users POST
  HTTP 500 at 08:01:35.833 UTC, followed by `lbx_unavailable`. Its POST and the
  original operation-open event share the same trace. This establishes that
  the first POST was sent and received HTTP 500; its body and original JSON code
  remain unavailable. The earlier first-send uncertainty is superseded by this
  archived trace evidence, not by an assumption about losing a returned ID.
- Later owner attempt: users POST at 13:24:58.956 UTC, request
  `46d5b77410d3fa3a4077fc2e15cdb39a`, HTTP 500 / LBX code 500, safe reason
  `provider_rejected`, followed by `lbx_unavailable`. No success receipt was
  obtained. This explains the new UNKNOWN interval after the earlier manually
  pending state was opened.
- Fresh GET-only discovery at 13:34:23 UTC: HTTP/LBX 200, zero candidates for
  the original opaque outer key. No customer identity can currently be proven.

Local request-shape inspection shows absent FIO for the original user and both
successful synthetic users. The current command fields are type, outer_id,
email and transient login/password. Differences in email casing and opaque-key
characters were observed without printing values; neither difference is a
proven explanation of the 500 and no identifiers/email were changed to test a
guess. The historical request body is not reconstructed as if it were captured.

The remote error text was intentionally not retained in privacy-safe logs. A
provider server-side error/audit record for the two failed POSTs is now the
concrete missing evidence: what caused HTTP 500, and whether either request
created an object before failing. A 500 plus empty search is not a safe absence
predicate. Do not replay CREATE merely to obtain an error body, bind by email,
or clear UNKNOWN. Read-only recovery can bind only after a candidate's detailed
original-key/ID proof. No provider mutation, manual reset, new account or
subscription/payment action occurred in this follow-up.

Sanitized local evidence: `.harness/any709-qa/original-operation-loki.json` and
`.harness/any709-qa/owner-late-discovery.json` (ignored). Documentation/whitespace
checks are the relevant verification for this diagnostic-only follow-up; no
runtime code or test behavior changed.

## Diagnostic CLI simplification (2026-10-27)

The owner requested retaining useful diagnostics and removing the unshipped
operator binding/reset workflow. The supported command is now
`billing-customer diagnose --user-id <PORTAL_USER_UUID>`; there is no apply,
manual-ID adoption or retry override. It performs scoped read-only PostgreSQL
queries, bounded LBX GET discovery/point proof and allowlisted inspection of
saved CREATE response facts. See the [operator runbook](../../engineering/lbx-product-links.md#customer-diagnosis-cli).
Earlier repair-CLI instructions in execution history are superseded.

The owner's HTTP 500 was independently traced to LBX's email uniqueness
rejection, despite zero results in visible GET searches. That failure must not
be treated as proven absence. The structured, previously recorded curl review
is readable by diagnosis; new bootstrap failures retain only safe response
codes/reason/time in the existing recovery item. No raw response body, email,
password or token is copied into diagnostic output. The independent receipt,
transport-before-dispatch, credential projection and selected-offer DTO fixes
remain in scope. No production semantic or paid-access authority is added.

Validation of this simplification:

- `npm run check` passed documentation, generation, architecture, API lint/format,
  38 web boundary tests, 300 component tests, web lint, 1,293 non-PostgreSQL API
  tests and the production web build. Its PostgreSQL stage passed 194 cases and
  exposed six errors in the newly added negative-test fixtures: recovery work
  was read before claiming a send, and unsupported Settings were constructed
  instead of seeding a foreign-scoped user. These fixture errors were corrected;
  no runtime fix was needed. The affected PostgreSQL suite was rerun with
  `PYTEST_ADDOPTS='-k "billing_customer_diagnostics" --tb=short' npm run test:api:postgres`:
  all 23 cases passed (including the six corrected cases). Together the runs
  cover all 200 PostgreSQL cases on the unchanged runtime code.
- Focused QA/protocol/CLI fast checks: 182 passed. API Ruff, formatting,
  architecture and `git diff --check` passed. The final documentation check was
  rerun after recording these results. Browser E2E was not run; no UI changed.
- The real wrapper was exercised against the current owner's local Portal
  account and test LBX 043 using GET only. It returned `email_conflict`, saved
  HTTP/LBX code 500 and `email_not_unique`; live original-key and both email
  searches returned no candidates, with no source error. The exit status was 2
  as documented. Before/after hashes of users, customer slots, create operations,
  recovery items and review rows were unchanged. No customer CREATE, reset,
  binding mutation, Widget credential, contract, subscription or payment was
  performed. The provider's email conflict remains for Billing Ops resolution.
- Evidence logs remain local under `.harness/any709-qa/diagnose-check.log` and
  `.harness/any709-qa/diagnose-postgres-recheck.log`. No commit, push or PR was made.

## Owner-approved discover/create/recover flow (2026-10-27)

This supersedes the account customer's indefinite UNKNOWN/manual-review hold
policy described earlier in this historical handoff. The owner requested search
before CREATE, binding on a proven match, one CREATE when discovery is empty,
GET recovery after a duplicate/other CREATE failure, and Sentry reporting if the
customer still cannot be resolved. The canonical external-billing design now
contains the narrow account-customer amendment; agreement/subscription creation
and paid-access authority are unchanged.

`app.composition.billing.ensure_customer` is the shared use case and sole runtime
consumer of `LbxServerClient.create_user`. Both key and email discovery lead to
paired point verification; an email-only match never adopts another identity.
An existing bound ID or durable receipt uses its point GET and prevents CREATE.
The same Portal user, opaque key, customer row and permanent operation survive
all attempts. Existing paired work leases/fences prevent simultaneous sends and
stale completion. Each failed completed attempt invalidates stale concurrent
search snapshots. Crashed/cancelled source work keeps a finite active lease;
a later explicit open searches again and can claim after expiry. A failed POST
never loops another POST inside the same opening. Successful recovery resolves
existing reviews and clears recovery work/lease state; no history is deleted.

The HTTP boundary reports unresolved `BillingAccountFailure` once through the
existing sanitized Sentry reporter. Recovered failures, authentication refusals
and an active parallel attempt are not reported as unresolved integration errors.
Delivery still requires the deployment's Sentry DSN/release configuration. The
read-only diagnostic CLI retains historical CREATE facts and now recommends normal
account opening to recover/retry instead of requiring an unavailable repair CLI.

Validation:

- `npm run check` exited 0: 1,298 non-PostgreSQL API tests, 210 PostgreSQL tests,
  38 web boundary tests, 300 component tests, API/web lint, formatting,
  documentation, generated-contract freshness, architecture and production web
  build passed. The supported browser suite was skipped by the canonical command
  because `RUN_E2E=true` was not set.
- New coverage includes ten PostgreSQL ensure/lease/fence scenarios and five
  single-CREATE/Sentry HTTP boundary cases. Existing transport, receipt, concurrent
  bootstrap and diagnostic regressions were adapted to pre-CREATE discovery and
  same-request recovery. The targeted rechecks and final canonical run passed.
- The restricted asynchronous boundary runner stalled and was stopped; the same
  five cases passed in the unrestricted runner and in the final canonical run.
- The owner supplied a screenshot of real Widget rendering for another account.
  No authenticated Portal tab was available through the browser connector for a
  new live owner-account smoke. No real LBX CREATE/reset/binding mutation, Portal
  account deletion or payment was performed for this implementation. The current
  API container was not rebuilt; after rebuilding, the ordinary authenticated
  opening is the entrypoint for recovering the owner's old manual-review row.
- Canonical evidence: `.harness/any709-qa/customer-ensure-check.log`. No migration,
  generated-file hand edit, environment change, commit, push or PR was made.
