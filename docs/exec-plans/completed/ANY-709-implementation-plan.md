# ANY-709 - Normal LBX billing, product mapping and real Widget flow

Status: COMPLETED - implementation Steps 1-4 DONE; recorded automated checks PASS; final real LBX purchase/payment acceptance NOT_RUN
Date: 2026-10-27
Review revision: 5 - implementation closed; consecutive migration numbering and local DB transition complete
Program: ANY-504, program Step 7
Delivery: four sequential implementation stages in this file, numbered Step 1-4
Repository destination: `docs/exec-plans/completed/ANY-709-implementation-plan.md`

## Completion record, 2026-10-27

The owner requested closure of completed implementation and consolidation of the
branch migrations. All four implementation steps are **DONE**. This archive
records code delivery and the actual automated evidence; it does not assert full
human acceptance of ANY-709 or production enablement.

- [x] Step 1: ordinary connection, direct product links and current offers.
- [x] Step 2: optional names, durable customer ensure and account Widget.
- [x] Step 3: accepted purchase, consent, preparation and safe recovery.
- [x] Step 4: localized Buy/Continue/Manage UI, shared Widget lifecycle and runbook.

Focused Step 4 evidence is 227 component tests, 38 boundary/tooling tests and 10
synthetic browser cases PASS. The reported Buy timeout was traced to a successful
5.555-second advance exceeding the former 5-second browser deadline; the bounded
billing deadline and lost-response recovery correction have regression coverage.
The owner's recorded real request reached a linked purchase with one prepared
subscription. It does not prove actual intended-agreement Widget payment or a
successful acquiring transaction. Manual QA, real payment and production rollout
remain **NOT_RUN** by owner choice; no paid access or later program work is
claimed complete. Detailed historical NOT_RUN entries below retain their dates.

The branch-local revisions `20261026_0003`, `20261026_0004`, `20261026_0005`
and `20261027_0006` are consolidated into one forward revision,
`20261027_0003`, after main's unchanged `20261001_0002`. Every original upgrade
operation and reverse-order downgrade operation is retained. The owner requested
consecutive numbering after the initial consolidation retained `0006`. A fully
upgraded local `20261027_0006` schema needs a verified revision-label transition,
not a DDL replay. Intermediate retired revisions must finish the original chain
before that transition; never reset data or stamp over unapplied operations.
Current instructions are in
the [billing runbook](../../engineering/ANY-709-billing-runbook.md#consolidated-any-709-migration).

The following execution prompts and per-stage delivery records are retained
implementation history, not instructions to start more work.

### Closure and migration consolidation evidence

- Four branch migration files became one; main's first two revisions are
  untouched. Source AST comparison before/after formatting confirmed all 23
  original upgrade statements and all 21 reverse-order downgrade statements
  remain identical, including nested operations and SQL bodies.
- Updated the existing Alembic/Step 1-3 PostgreSQL tests for the consolidated
  predecessor. Added `test_any709_migration_postgres.py`: all seven purchase
  states preserve every predecessor table's existing column values, only the
  intended account/hold fields are backfilled, an already-current database
  preserves names/origins/fences and all rows, and ambiguous old holds roll back
  the entire migration without changing data or the recorded predecessor.
- The exact focused command below passed **78/78**, with 1,610 deselected and
  **zero skips**, in 144.10s. Its disposable `_tests` database was owned and
  removed by pytest. No application/production database migration, provider
  calls or manual QA ran for consolidation.
- Changed-file Ruff formatting/checks, documentation checks and
  `git diff --check`: **PASS**. Generation: **NOT_NEEDED**, because the final
  schema, models and wire contracts did not change. Broad build/typecheck/full
  repository checks: **NOT_RUN** in this focused follow-up.

Exact repeat commands from the repository root (PostgreSQL test server already
available; no application database migration is part of these commands):

```bash
PATH="$PWD/.venv/bin:$PATH" PYTEST_ADDOPTS='-k "test_alembic_postgres or test_any709_migration_postgres or test_any709_step1_postgres or test_any709_step2_postgres or test_any709_step3_postgres"' npm run test:api:postgres
.venv/bin/python -m ruff format --config apps/api/pyproject.toml --check apps/api/alembic/versions/20261027_0003_normal_billing.py apps/api/tests/test_alembic_postgres.py apps/api/tests/test_any709_step1_postgres.py apps/api/tests/test_any709_step2_postgres.py apps/api/tests/test_any709_step3_postgres.py apps/api/tests/test_any709_migration_postgres.py
.venv/bin/python -m ruff check --config apps/api/pyproject.toml apps/api/alembic/versions/20261027_0003_normal_billing.py apps/api/tests/test_alembic_postgres.py apps/api/tests/test_any709_step1_postgres.py apps/api/tests/test_any709_step2_postgres.py apps/api/tests/test_any709_step3_postgres.py apps/api/tests/test_any709_migration_postgres.py
PATH="$PWD/.venv/bin:$PATH" npm run docs:check
git diff --check
```

### Owner-requested consecutive numbering and local DB update

After the initial consolidation kept the former head for compatibility, the
owner explicitly requested consecutive revision numbers and immediate local DB
update. The current single branch migration is now
`apps/api/alembic/versions/20261027_0003_normal_billing.py`; the graph is
`20260924_0001 -> 20261001_0002 -> 20261027_0003`. Its upgrade/downgrade SQL is
unchanged. Earlier records below retain the revision IDs actually executed.

The verified development database was at `20261027_0006`. A fresh isolated
`_tests` database was migrated to the new head and its complete public schema
was compared with the application database: tables, physical column order/types/
defaults, constraints, indexes, functions and triggers matched exactly. A
protected custom-format PostgreSQL backup was saved at
`.harness/backups/any709-before-0003-20261027T065436Z.dump` (mode 0600, ignored).

Under bounded database locks, the owner-authorized transition changed exactly
one `alembic_version` row, `20261027_0006 -> 20261027_0003`. Fingerprints and
counts of every application table matched before/after in that transaction:
all rows in **27 tables preserved**, including 4 users, 4 billing customers,
1 purchase, 1 subscription, 5 legal acceptance events and 15 document
acceptances. Schema remained identical. Canonical `migrate-api` then completed
successfully with the database already at head and no DDL replay. The temporary
reference database was removed. Production and LBX were not touched; no manual
product/payment QA was performed.

The new graph and data-preservation suites passed **17/17**, 1,671 deselected,
zero skips, in 25.00s:

```bash
PATH="$PWD/.venv/bin:$PATH" PYTEST_ADDOPTS='-k "test_alembic_postgres or test_any709_migration_postgres"' npm run test:api:postgres
PATH="$PWD/.venv/bin:$PATH" npm run migrate:api
```

Changed-file Ruff, documentation checks and `git diff --check`: **PASS**.
Generation is **NOT_NEEDED**; there is no final-schema or HTTP-contract change.

## 0. Execution contract - read for every selected step

**Current rules for Steps 3-4 (2026-10-27).** Historical write-only/test-pause
instructions for Steps 1-2 were superseded by separately authorized QA. Actual
Step 1-2 code, targeted/canonical automated checks, the owner's real Widget
observation and full ANY-709 acceptance are distinct evidence. The historical
exceptions and their exact outcomes remain in the Step 1-2 handoffs.

Owner follow-up on 2026-10-27 explicitly authorizes the agent to execute
migrations, tests and focused QA for Step 3. This additionally permits applying
`20261027_0006` to the verified local development application database. The
production database and real LBX financial writes remain outside this QA run.
See the Step 3 follow-up evidence below; the initial delivery's NOT_RUN entries
are retained as historical evidence.

Implement ONE selected step, then stop for owner QA/review. Read sections 0-3,
the selected step, applicable AGENTS and directly relevant current code. Start
from the latest PR #150 checkout, never the original main baseline or PR #143.
Reuse delivered code for product offers, customer ensure, JWT/Widget and central
LBX error decoding; no duplicate provider adapters or parallel state machines.

### Codex may execute

- Code changes, necessary forward migration files, generated API/contracts,
  changed-file formatting/linting and `git diff --check`.
- Focused unit, HTTP mock, API, disposable PostgreSQL and synthetic frontend
  tests, plus relevant existing regressions. Use existing supported test wrappers;
  any migration execution must be **isolated to the test database**.
- Supported focused checks and one `npm run check` at the completed stage
  checkpoint when the harness is available. Report explicit executed results.
- Synthetic browser tests against an isolated harness; they are not evidence of
  real LBX payment.

### Codex must NOT execute

- Any live LBX write: no real customer, agreement, subscription or payment POST,
  no edits of tariff, price or organization in 043 or production. The owner
  performs the explicit real-LBX purchase/payment QA checkpoint.
- Migrations against the owner's application or production DB, destructive
  cleanup, force binding, synthetic paid grants, external secrets/PII in logs.
- Scheduler/webhooks/paid-access/Kernel implementation (program Steps 8-11).
- Stage, commit, push, modify Linear/PR or unrelated changes without separate
  owner instruction.

Do not claim full human acceptance from automated PASS. A real Widget with no
subscription is Step 2 evidence only; prepared payment and actual payment
remain separate Step 3-4/final acceptance outcomes.

### Formatting / linting commands

Run from repository root using the existing root `.venv` and installed npm
workspace tools. Use explicit changed-file paths in the actual command/report:

```bash
# Changed API Python, including new tests and migrations:
.venv/bin/python -m ruff format --config apps/api/pyproject.toml <changed-python-files>
.venv/bin/python -m ruff check --config apps/api/pyproject.toml <changed-python-files>

# Changed frontend TypeScript/TSX, paths relative to apps/web:
(cd apps/web && npm exec --no -- eslint <changed-web-files> --fix --max-warnings=0)

# Whole existing web lint is allowed when needed for changed shared contracts:
npm run lint:web

# Only when generated source contracts changed:
npm run generate

git diff --check
```

The angle-bracket arguments are explicit placeholders, not executable filenames.
Do not apply the API formatter configuration indiscriminately to the entire
repository or reformat unrelated harness code. Preserve local harness/Markdown/
JSON style and perform only necessary formatting there. The pinned web package
has ESLint but no dedicated Prettier/format script: use installed ESLint fixes
and matching existing style; do not install a formatter or pretend lint is a
build/typecheck. If a required tool/dependency is unavailable, report its exact
failure and manual remedy; do not run installation/build/test suites instead.

### Required handoff after each step

Report changed files, observable behavior, migration/generation, exact tests,
lint/build/check outcomes, skipped checks, safe manual QA and remaining scope.
Distinguish IMPLEMENTED, AUTOMATED_PASS, HUMAN_QA_PASS and NOT_RUN. Include a
brief removed/replaced/retained note for inherited code and commands to retest
changed existing regressions. Avoid duplicate broad test runs during iteration.

## 1. Evidence, baseline and scope

### 1.1 Pinned baseline

- Historical planning main baseline: `dfdc67a9617df1afb5213b0fb831b770e6d816be`. Steps 3-4 start from the latest PR #150 head with delivered Steps 1-2, never from this pinned SHA.
- ANY-709 inspected revision: `updatedAt=2026-10-26T02:28:22.122Z`.
- ANY-504 / ANY-709 owner decisions: Step 6 unchanged as history; all corrective
  implementation and narrow documentation alignment belong to program Step 7.
- PR #139 / ANY-664 is merged. PR #143 rejected reference:
  `7e24f7344615ba7877e211471d6bec63ffced2f6`, not the execution base.
- If `main` advances, preserve unrelated merged changes. Check only the relevant
  delta; do not reset to this SHA or restart the entire program research.
- This plan was prepared by reading code, tickets and supplied reports. No repo
  tests, migrations, live provider calls or browser acceptance ran during planning.

The historical main baseline contained source clients, restricted mapping,
catalog and purchase MODEL TABLES, but not working purchase runtime. The current
PR now delivers product links/current offers and customer/account Widget.
Schema presence still does not mean Step 3 purchase runtime exists.

### 1.2 What the current code establishes

| Surface on pinned main | Use in this plan |
|---|---|
| `app/cli/commercial_mappings.py` | Keep one CLI; replace required proposal/approval/source-input files with direct linking. |
| `app/composition/mapping_operator.py` | Remove manual account-ID equality, proof-file loading and blanket production refusal; preserve bounded reads, operator authorization and transaction boundaries. |
| `app/domains/catalog/{mapping_evidence,publication,preview}.py` | Separate link identity, live offer and accepted purchase; adapt versioned readers. Existing preview currently groups products from stored mapping heads. |
| `app/models/billing_projections.py` | Reuse immutable `commercial_mapping_revisions`; do not add a second price catalog or activate inert whole-catalog projection tables. |
| `app/models/billing_purchase.py` | Reuse customer, PurchaseIntent and ExternalCreateOperation. Customer operations already allow NULL purchase ID. Strengthen missing uniqueness/fencing rather than inventing a parallel ledger. |
| `app/integrations/lbx/{client,dto,selected_offer,offer_inputs,privacy}.py` | Reuse real HTTP, Decimal and protocol validation. Main client currently exposes selected GETs, not complete customer/purchase commands. |
| `app/composition/sources.py`, Kernel client/mock | Keep one technical HTTP contract; remove hard-wired simulation as a blocker for REAL LBX, not honest source provenance. |
| `docker-compose*.yml`, `scripts/repo.py`, `.env.example` | Finish normal configuration delivery, remove billing walkthrough mounts from Kernel-mock startup. |
| identity router/service/model, AuthForm, product/account features | Extend existing surfaces, generated contracts, seven locale catalogs and Bundle 3; no auth/UI rewrite. |

Paths prefixed `app/` in this table are under `apps/api/`.

### 1.3 Provider facts already available - do not re-run Phase 0

- HS256 Widget JWT with `ident_type=7`, `ident=string(LBX user_id)` works. Mint
  fresh `iat=now` per allowed open. Accepted B4/B5 limitations remain: `exp` is
  not a proven LBX expiry guard, remint/logout does not revoke a copied token,
  and UI flags are not server ACL. No new revocation/proxy/ACL research project.
- The supplied `ANY709-LBX043-user-create-full-widget-e2e.md` reports one user
  CREATE with type/email/outer_id/login/password, real Client API and Widget
  success, including a later process without login/password. The password must
  not be stored. This proves identity flow, NOT Portal purchase/payment E2E.
- `ANY709-LBX043-agreement-23-readonly.md`: research customer 23 has agreement
  25 at organization 9, not seller 21; no subscriptions found. Provider-created
  default agreements can exist; their precise trigger was not proven. Never
  adopt one merely because it is first/empty, nor block customer login over it.
- B6/B12/B13 give the dedicated-agreement, discovery and no-blind-repeat basis.
  A zero discovery result after possible send is NOT proof no object exists.
- LBX tariff services/periods own prices. Actual existing subscription effective
  service prices and total are not automatically today's catalog price.
- Dates are provider calendar evidence. Waiting subscriptions may have NULL or
  sentinel dates; do not derive a paid month or UTC midnight from them.
- The inspected 043 schema did not expose `debt_threshold`; do not invent its
  request/readback. Missing does not mean zero or prove credit disabled.
- Supplied test setup: seller 21, product `proposal_ai`, tariff 32, tariff service
  1, period 1, price row 288 (100 RUB/month), period association 82. These are
  manual test inputs, NEVER business-code constants. Association 82 is not
  `period_id`; price 288 is not a permanent mapping target or mandatory field
  on a subscription service.
- RU UI/API evidence supports configured `currency_id=1 -> RUB`, major units.
  Keep exact decimal comparison and a small typed currency interpretation, not
  a global inference that numeric currency 1 means RUB in every future provider.
- Concrete organization-21 agreement/subscription creation and payment via the
  FINAL Portal still require human acceptance. The earlier stopped probe is
  NOT proof those actions passed; no additional pre-implementation probe series.

Reports are supplied research artifacts, not guaranteed repository files. The
executor need not find private paths on another worktree. Keep this factual
handoff and use canonical retained evidence only when a concrete DTO needs it.

### 1.4 In scope and explicit deferrals

Deliver ordinary real-LBX configuration; file-independent product linking and
current offers; optional FIO; safe lazy customer creation; actual SDK/JWT;
PurchaseIntent/consent; dedicated agreement/subscription preparation/readback;
request-driven recovery and Step 8 handoff; user Buy/Continue/Manage; diagnostics;
necessary migrations, tests and narrow documentation corrections.

NOT in scope: operating background worker/webhook receiver/reconciliation loop
(ANY-715); grants, paid-trust renewal, allowance creation, AccessSnapshot or
Kernel usage implementation (program Steps 9-10); real Kernel producer changes
(ANY-711); full production/paid-access launch sign-off (Step 11); Portal payment
APIs, credit/trials/overage/bundles/upgrades; admin UI; universal adapter/scheduler;
rewriting legal texts or reopening ANY-664. Do not assign fake quota just to link
an access product. Actual metered quantities must have their proper commercial
meaning before the later paid-allowance feature is enabled.

## 2. Fixed result and implementation decisions

### 2.1 User and operator outcomes

| Action | Required result |
|---|---|
| Normal startup with connection settings | Real HTTP integration is wired; no billing test mode/profile mounts. Unconfigured billing does not break Portal login. |
| Authorized CLI links a product | One current product-to-offer association with history; no duplicate publisher or three manually maintained JSON files. |
| Register/login | Portal identity only; optional independent surname/name/patronymic. No LBX CREATE on login/ordinary GET. |
| Verified user explicitly opens Details/billing | Ensure one LBX customer, point-verify identity, mint fresh JWT, mount official customer Widget even without subscription. |
| Confirm Buy | Freeze the accepted live terms and reserve one purchase; prepare the correct subscription; verify it; offer payment of its proper agreement. |
| Reload/two tabs/return before payment | Same customer and purchase/subscription; Continue or recovery state, not duplicate CREATE. |
| Existing subscription Manage | Verify its original binding and effective terms, not today's replacement link or catalog price; open billing without new purchase. |
| New catalog price | New buyers receive current terms; old consent/history is unchanged; no re-publication just for a price change. |
| Error/outage | Safe localized reason/request ID and useful redacted diagnostic; no fake Widget, invented no-subscription state or blind retry. |

### 2.2 Three distinct records; no duplicate catalog

1. **Product link:** selected Kernel `product_id` and LBX tariff/service/period
   identities, version/audit and separate source provenance. No required price,
   approval certificates, research references, user-specific setup or invented
   technical allowance. Retargeting creates a new link revision.
2. **Current offer:** transient normalized live LBX price/period/composition and
   applicable supported conditions for the selected link. Source of commercial
   truth is LBX. Do not make the historical publication price a prerequisite.
3. **Accepted purchase:** immutable exact accepted money/currency, component/
   quantity/period, link revision and applicable legal-document versions plus
   user/time. It is evidence of this user's consent, not a Portal price editor.

New price before acceptance is a new offer, not a global mapping conflict. Price
change between review and submission returns `terms_changed` with fresh review;
no silently repriced CREATE. Once any agreement/subscription CREATE may have
happened, do not release its scope or start a replacement automatically. Recover
that operation first; an actually mismatching prepared subscription enters
review, not an altered accepted snapshot. A customer created for the account is
not itself a paid product subscription and can survive an abandoned review.

### 2.3 One real connection; minimal internal compatibility

Required operator-facing LBX settings: `LBX_BASE_URL`, `LBX_SERVER_USERNAME`,
`LBX_SERVER_PASSWORD`, `LBX_WIDGET_SIGNING_SECRET`,
`LBX_SELLER_ORGANIZATION_ID`. Reuse normal instance, DB, public origins, SMTP,
Kernel URL/service token, timeout and existing privileged-CLI settings.

Remove `MAPPING_ACCOUNT_ID` and `LBX_EXTERNAL_BILLING_ACCOUNT_ID` as manual
inputs. Do not replace them with a new manual account name. Retain existing
internal scope columns/FKs as needed: use one server-resolved deployment scope
from the trusted connection, shared by runtime and CLI. Prefer minimal existing
storage-compatible resolution, not a new account registry/routing framework.
Never derive it from a password, locale or browser value. Preserve an existing
proven scope; do not relabel incompatible historical objects as the new account.
Actual conflicting old real bindings are a migration conflict, not a reason to
ask all users to register again. Synthetic v1 data is never promoted to live.
The chosen internal resolution must be deterministic for a fresh deployment, identical in host/container CLI
and runtime, stable on restart and credential rotation, and unable to read old
external IDs against another configured provider origin. Preserve original
historical scope values rather than rewriting immutable rows. Ambiguous real
legacy bindings are diagnosed locally; they do not authorize a destructive reset.

Currency interpretation is a small provider-side typed mapping. The direct LBX
support answer confirms one fixed `Europe/Moscow` price calendar; no manual
timezone setting or per-link `effective_on` is needed. Capture one Moscow date
for both complete control reads. For the selected service/period, each price
method selects the maximum start date on or before that date, inclusively.
Inline `prices[]` may contain multiple historical and future prices. Compare
the selected period, start and monetary values with the dedicated price method;
use its confirmed amount and `price_id`. Missing/ambiguous applicable prices or
conflicts refuse the offer; real commercial drift between reads still refuses.
Validate discounts only for the selected current inline price and retain the
unsupported-nonempty-discounts rule. Do not derive UTC subscription/tariff
intervals from calendar dates or store a current price in the product link.

Server/Client API and SDK addresses come only from validated server config;
use the correct `/api/rest/v1`, `/api/rest/v1/client` and `/lbxwidget.js` paths,
not duplicated suffixes or browser-controlled URLs. Secret values must never be
printed by startup diagnostics, generated Compose reports or `repo:doctor`.
Missing/all-empty LBX config means unavailable billing; invalid partial config
must produce an actionable validation result without breaking unrelated auth.
No construction/import-time provider calls or automatic link publication.

### 2.4 Minimal persistence evolution

Use forward migrations after the actual main Alembic head. Do not rewrite the
frozen baseline or reuse the rejected PR migration numbers blindly. Migration
files are authored, NOT executed by Codex.

- Version existing mapping documents for the new link representation. Retain a
  narrow v1 historical reader; do not fabricate empty approval/metric fields to
  satisfy old `ApprovedMapping`. Preserve referenced immutable rows and legal
  history. Querying old history does not make it eligible for a new real sale.
- Enforce one current link per product across different offer IDs. If existing
  revisions cannot express a unique current selection, add ONE small product-
  head pointer to existing revision IDs with CAS. This is not a product/price
  catalog. Retarget atomically; keep old pins readable. Do not pick arbitrarily
  among multiple legacy heads. The normal one-time CLI publication can establish
  the intended new head; no destructive mass reset is required.
- Use existing ExternalBillingCustomer and ExternalCreateOperation. Strengthen
  non-null provider customer uniqueness and single create identity/send fence.
  Customer operations have no artificial PurchaseIntent.
- Add a narrow purchase-scope hold unique per user/product if absent; the future
  access-primary row is NOT the purchase mutex. Keep a linked unpaid purchase
  held, with no browser timeout release.
- Agreement and subscription operations have permanent per-intent/kind identity
  and unique proven object bindings; an agreement cannot be bound twice before
  the subscription row exists. Dedicated agreement ownership is permanent for
  the subscription's history, not merely while active.
- At a possible-send claim, atomically record operation ownership/fence and the
  original `unknown_since + 2h` deadline plus coalesced durable work item. A
  crash in `possible_send` is uncertain. Elapsed time does not permit retransmit.
- Reuse observations/manual-review/work-item models where necessary. Do not add
  a separate framework, paid grants or worker runtime. Initial subscription
  projection remains explicitly not paid-verified, never a fabricated denial
  measured from LBX and never a positive grant.

### 2.5 Shared operation and I/O rules

Application owns synchronous transaction/state decisions. Existing async HTTP
lives at its outer resource-owning boundary; do not propagate async through
Domain/Persistence, run blocking SQLAlchemy on the event loop, move a request
Session across threads or start nested event loops. Reuse main's composition,
preflight and framework worker conventions. HTTP always occurs between short
transactions. Apply results only against the current ownership fence.

Read retries are bounded. All LBX Server API methods use the now-centralized
decoder for HTTP status, JSON `code`, `response.error`, safe diagnostics and
bounded GET retry eligibility. An HTTP 500 can be a business refusal; neither
its message nor a zero-result discovery proves a possibly sent CREATE had no
side effect. No raw provider text, personal data or secrets in public errors.

**Customer and financial CREATE deliberately have different recovery policies.**
The owner-approved Step 2 `ensure_customer()` performs discover -> at most one
POST per explicit account opening -> GET recovery. After a failed attempt's
finite active-send lease clears, a later **separate** authenticated open may
discover again and make one more customer attempt, preserving the original
slot, opaque key, operation and history. It never POST-retries within one open.

For **agreement/subscription CREATE** in Step 3, a possible send, 5xx/error
envelope, timeout, lost response or malformed success retains the original
financial operation and held purchase scope; recovery is GET-only. Do not
blindly repeat financial CREATE because a new request arrived, a query was
empty or the +2h deadline elapsed. Only separately proven terminal/no-effect
and audited safe release can free the financial scope. Successful 200/201
response IDs require authoritative point readback. Never route business POST
through the GET retry loop or start HTTP inside a database transaction.

### 2.6 Widget has two presentations, not two identity systems

Use one server-side bootstrap contract and one SDK lifecycle. Customer/account
view requires current Portal auth + verified email + proven customer identity;
it does not require current product price or any subscription. Use non-purchasing
presentation there. Payment-capable presentation is issued only after the
specific owned prepared/existing purchase's readback and original acceptance
checks. On purchase conflict, account viewing may remain read-only when customer
identity is sound; a customer identity conflict/UNKNOWN blocks JWT itself.

The server decides flags; the browser cannot choose provider IDs, seller, amount
or permissions. `disableCreateSubscription` and `disableEditSubscription` remain
true for the product-bound flow. Payment must NOT remain permanently disabled
once a purchase is ready. Do not automatically enable autopay/invoice/stop paths
outside supported scope. All SDK flags are presentation only: the customer-wide
JWT is not restricted to one product/agreement, and no Portal check revokes a
previously issued LBX JWT. Retain the accepted provider residual risk honestly.

A provider-default agreement at another organization does not satisfy purchase
binding. Show the proven intended agreement reference/seller next to payment;
validate the supported target-selection path during human acceptance. Do not
invent a product-only Widget filter or auto-select an arbitrary account balance.

### 2.7 Bounded public contract, generated once

Retain main's catalog URLs and generated transport. The following new routes
are this plan's proposed implementation contract, NOT claims they exist today:

| Route/use case | Meaning |
|---|---|
| `POST /api/billing/widget-bootstrap` | Step 2 currently implements the empty account-only request/response. Step 3 extends this **same** contract with optional owned prepared-purchase reference and verified payment presentation; keep empty account-only requests backward compatible. |
| `POST /api/purchases/review` | Current selected offer + opaque link revision + expected terms fingerprint + legal versions for authenticated review; no provider mutation and no extra durable checkout session. |
| `POST /api/purchase-intents` | Server-recomputed current terms matched to submitted expected fingerprint/legal selection; one accepted intent under idempotency/business scope. |
| `GET /api/purchase-intents/current?product_id=...` | Authorized existing local purchase/scope state; no source-catalog dependency or hidden CREATE. |
| `GET /api/purchase-intents/{id}` | Owned durable status; no business mutation. |
| `POST /api/purchase-intents/{id}/advance` | Explicit bounded preparation, or read-only provider recovery for an uncertain operation. |

Use server-owned Pydantic schemas and generated TS; public outputs are normalized
states and opaque Portal references. Browser input never supplies LBX IDs/price
as authority. The submitted expected fingerprint and opaque link revision are
compared with server facts, not trusted as proof by themselves. Do not accept an operator
retarget between review and confirmation just because two offers cost the same.
In the short purchase-pin transaction recheck the exact reviewed current link,
required legal versions, idempotency and product hold after source I/O; a
concurrent local change refuses the new pin with a fresh-review result. Never
perform source I/O while holding those locks. Reuse legal acceptance storage.
Before new admission, inspect existing idempotency/scope first. Same key + changed
meaning conflicts; same key + same meaning returns the same record even when
sources are unavailable. Recheck auth/session after asynchronous work before
returning a JWT. Do not redesign global errors/auth or introduce review tables.

### 2.8 Documentation changes are part of this implementation

Replace ONLY the conflicting active prescriptions as their owning step changes:
manual approval files/price-republication, operator account IDs, source-backed
catalog and customer-only Widget authorization. Keep purchase-time accepted
price, effective readback, ownership, no-blind-retry and future access guarantees.
Update both relevant AGENTS digests/ADR navigation only where they repeat the
changed rule; preserve historical ANY-664 scope and label as-built vs target.
Do not apply `ANY-504-docs-correction-20261026.py` automatically. Do not rewrite
unchanged AccessSnapshot or date-only/UTC quota contracts in this ticket.

## 3. Stage map and validation ownership

| Plan step | Runnable result after implementation + human setup | Main validation focus | Implementation |
|---|---|---|---|
| 1 | Normal LBX connection, direct CLI link and source-backed catalog | No file gates; links/history/current prices; safe migration and startup wiring | DONE |
| 2 | Existing/new verified user opens REAL customer Widget without a subscription | One customer, credentials/JWT lifecycle, optional FIO, errors and concurrency | DONE |
| 3 | Purchase APIs safely prepare the chosen real subscription and can authorize payment presentation | Consent, scopes/fences, agreement/subscription proof, retries/UNKNOWN | DONE |
| 4 | Ordinary user UI completes Buy/Continue/Manage and payment-capable Widget | End-to-end intent, actual payment target, reload/logout/error UX, final handoff | DONE |

Steps 1-2 are implemented and have recorded automated/local QA; the owner
additionally reports their previously blocked customer registered and opened
the real Widget. This is an owner observation, not proof of full purchase
or payment. Step 3 has recorded focused synthetic/local QA. Step 4 is implemented
with focused synthetic tests PASS and final real purchase/payment QA NOT_RUN. No extra research-only stage; do not
defer missing customer/connection behavior into Step 4.

Human focused Python commands below use the existing test wrappers and pytest's
`PYTEST_ADDOPTS=-k` filtering. Add the proposed `any709_stepN` filename/test-name
prefixes or report exact equivalent commands for actual names. A zero selected
or entirely skipped run is NOT PASS. For PostgreSQL, the canonical wrapper sets
the isolated worktree test environment; direct pytest without the safe test URL
can skip DB tests. Never use the development application DB as a pytest target.

## 4. Step 1 - Ordinary connection, simple product link and current offers

Status: DONE (implementation); recorded source/price checks PASS; final real payment acceptance NOT_RUN.
Depends on: approved sections 0-3 and actual main, NOT old PR #143 runtime.

### Result and changed surfaces

An operator can start normal Portal + optional Kernel mock, publish one link
without JSON approvals and read actual offers. Price changes do not require
re-linking. Customer/purchase actions remain explicitly not implemented until
later steps; no fake purchase success.

Inspect/modify: `core/settings.py`; `composition/{sources,mapping_operator}.py`;
`cli/commercial_mappings.py`; catalog contracts/evaluation/publication/preview/
router/presenters and their queries; LBX offer input/normalization/provenance;
`models/billing_projections.py` and necessary forward migration;
`docker-compose.yml`, `.agent.yml`, `.prod.yml`, `.kernel-mock.dev.yml`;
`scripts/repo.py`, `.env.example`; existing catalog API adapters/features/locales;
only related docs/guards/tests. Use actual paths in current main where a name
has moved; this is a bounded surface map, not permission for unrelated refactors.

### Implement

1. Deliver one normal server-only connection config through local/agent/prod
   launch. Reuse existing settings validation and secret handling. Remove manual
   account-ID inputs, required profile/approval mounts and billing fields from
   Kernel-mock startup. Keep existing CLI authorization and shared local lock
   mechanism, but do not require publisher UID approval just to start the mock.
2. Remove unconditional production rejection of a CONFIGURED real connection.
   Kernel mock remains dev/test-only. Preserve separate Kernel/LBX provenance;
   the real LBX path works with a dev Kernel mock, without calling either real
   source "approved production" merely because its URL changed.
3. Replace required proposal/approval/source-policy documents with a small
   validated direct CLI request. Keep `dry-run`, `publish`, `query`, execution
   principal/audit and expected-head concurrency. Input IDs select facts; the
   command cannot receive an authoritative price or fabricated quota.
4. Read the complete relevant tariff services/periods and enabled Kernel product.
   Preserve one fixed periodic supported selected service and explicit quantity
   rules; additional default-assigned services/missing memberships refuse that
   offer. Do not require catalog-organization checks: seller is deployment
   config and is proven on the actual purchase agreement. Do not scan all LBX.
5. Refactor live offer normalization so actual API facts + ordinary currency/
   necessary calendar config suffice. Remove manual proof-reference obligations;
   do not fill missing policy fields with invented false/zero/default approval.
   Keep supported-profile validation relevant to this offer, and distinguish
   unsupported from incomplete. Optional/unknown unrelated future features must
   not become a global blocker for customer login.
6. Implement versioned link persistence/current product head per 2.2-2.4. Same
   link identity is a no-op despite an ordinary price change. Retarget is CAS-
   protected and versioned. Preserve old v1 history, dependent keys/consents;
   synthetic/unverifiable legacy entries do not become live by migration.
7. Adapt ALL catalog/CLI consumers to the new representation, not just argument
   parsing. Source-backed products are discoverable independently of mapping.
   Selected detail/review reads current commercial values with bounded work.
   Unmapped products show unavailable Buy, not invented prices. Source failures
   are explicit; keep no-store errors and normalized generated contracts.
8. Avoid new background catalog jobs and unnecessary page fan-out: list technical
   products once per bounded API action; obtain offer details for the selected
   product as needed. Do not invent missing Kernel presentation fields or block
   known product IDs because optional marketing data is absent.
9. Align only related active mapping/source-read rules in docs. Existing code
   behavior not yet changed must still be labelled as-built, not already fixed.
   Add the normal deployment/link instructions in one runbook; no new proof file.

### Inherited ANY-664 closure register - mandatory in this step

This is a review checklist for the SAME Step 1, not new subtasks or an operator
configuration artifact. Paths below are under `apps/api/app/` unless stated.
An obsolete name may remain in immutable history, a narrow v1 reader or negative
tests; it must not remain a prerequisite of the new runtime/linking path.

| Verified inherited path | Concrete replacement / closure condition |
|---|---|
| `core/settings.py`: `require_safe_kernel_configuration`, `require_safe_lbx_configuration`; `composition/mapping_operator.py` | Remove BOTH the unconditional production Kernel refusal and the separate publication refusal. Remove mandatory equality/input of two account IDs. Preserve URL/auth/TLS/scope validation; a compatible configured remote Kernel and LBX must be constructible in production-shaped tests without claiming actual producer conformance. |
| `composition/sources.py` and downstream evidence-mode checks | Remove unconditional Kernel `SIMULATED` assignment for every configured source. Preserve explicit dev-mock provenance and real-LBX provenance separately. Dev mock + real billing works; no automatic legacy SIMULATED-to-GENUINE rewrite or mock in production. No new approval flag/certificate replaces the old gate. |
| `cli/commercial_mappings.py`, `composition/mapping_operator.py` | Eliminate required `--proposal`, approval/source input loaders and file path settings from dry-run/publish. Preserve authorized operator, audit, bounded local locking and product-head CAS. `query`/history remain usable without contacting LBX. |
| `integrations/lbx/offer_inputs.py`, `selected_offer.py`, `offer_provenance.py`, `domains/catalog/commercial_offer.py` | Replace `SelectedPolicyEvidence` / `REQUIRED_POLICY_FIELDS` and `_validate_configuration` proof prerequisites in the new path, including required `reference/revision/basis` and historical-policy certificates. Remove their required constructors/serializers as well as loaders. Use the fact-source rules below; do not leave `policy_evidence_missing` as the inevitable result after deleting JSON. |
| `domains/catalog/mapping_evidence.py`, `publication.py` and mapping queries/storage | A version-aware v2 link path must not call old `ApprovedMapping` / `require_replacement_approval` or compare publication-price fingerprints to authorize a new price. Keep independent link identity, product head, immutable v1 readability and commit-uncertainty/CAS safety. Do not edit old JSON/digests in place. |
| `domains/catalog/preview.py`, `router.py`, presenters, generated types and current web consumers | Remove the old assumption that every product exists only as a stored approved offer with mandatory `CatalogAllowance`. An access product without a configured metered package has no allowance, not an invented zero/one quota. A known product without a link/current quote remains a product with a precise unavailable Buy state. Preserve exact money and localized display. |
| Root Compose files, `scripts/repo.py`, `.env.example` | Remove approval/source-policy mounts from `docker-compose.kernel-mock.dev.yml`. Trace all used connection values through env input -> harness runtime env -> normal/agent/prod containers and CLI. Keep secrets server-only; merely editing Settings or the example env is not completed wiring. |
| Related active docs and tests/guards | Replace assertions that enforce retired approvals, frozen publication price or all-source simulation gates with the new behavioral contract. Preserve completed Step 6 history, real ownership/consent/money/concurrency tests and test fixtures. No broad disablement of guards or search-and-delete across historical documents. |

Owner-approved correction: the privileged local CLI has no separate UID
allowlist. Existing environment, secret, file and DB permissions control access;
the actual OS effective UID supplies `os-euid:<uid>` for command audit and
immutable publication history. Unavailable or invalid OS identity still refuses
the command. Keep the shared private local lock for concurrent execution and
the PostgreSQL locks/expected-revision CAS; ordinary app/mock startup does not
require an operator lock. Document this operational boundary in the runbook.

The rejected PR's `stand.py`, `purchase_profiles.py`, `preparation_profile.py`,
`LBX043_*`, `PURCHASE_*PROFILE_FILE` and `tools/lbx043/*.example.json` are NOT all
in main. Do not spend time reconstructing them to delete them. If a useful
fragment from PR #143 is copied in a later step, remove those dependencies in
THAT step; no hidden recorded transport, fixed IDs/price or subscription-only
account-entry rule may be carried forward.

### Fact sources and capability-specific readiness

Deleting a proof file does not mean inventing its old fields. Refactor the
consumers to require facts needed by the particular operation:

| Concern | Source and boundary |
|---|---|
| Product and selected service/period/quantity | Authenticated Kernel manifest plus documented LBX tariff/services/periods and fixed quantity rules. A list is validated according to its documented contract; no operator-written completeness certificate. |
| Current monetary quote | Actual service-price fields and configured currency units/scale. Direct LBX support confirms `Europe/Moscow`, inclusive latest-start-date selection in both methods and historical/future inline prices. Use one date for both control reads, require selected current facts to agree and keep precise missing/ambiguous/conflict errors; no timezone setting. |
| Supported preparation flags | Actual tariff/service flags and the explicit supported CREATE choices. Do not infer absent `debt_threshold`, global credit policy or financial eligibility. Future paid-access proof is not a prerequisite of a simple product link or customer Widget. |
| Renewal/cancellation acceptance | Existing required versioned Portal documents and applicable documented provider facts for THIS purchase. Do not fabricate legal/policy text or require a separate operator proof-file version on every price change. |
| Historical obligations | The immutable accepted purchase plus that concrete subscription's effective readback. A fake `historical_policy` certificate or today's catalogue equality cannot replace either. A truly missing material fact yields a precise affected-operation error. |

A new-path positive test must succeed with normal configuration + realistic
source responses, without constructing the retired policy/approval objects in
its fixture. Merely bypassing them in a mock or adding a new `approved=true`
default does not satisfy this step. No unsupported discount/tax/credit promise
may be introduced to make the test succeed.

Keep existing auth/core-deployment validation. Billing readiness is local to the
operation, not an import-time reason to crash otherwise valid Portal auth:

| Operation | Relevant dependencies only |
|---|---|
| Technical product listing | Kernel connection and valid manifest; no required LBX Widget secret or published offer. |
| Direct link/current offer | Server API connection, technical product and supported selected offer/currency/applicability. No customer, subscription, Widget secret or proof file. |
| Customer account bootstrap (Step 2) | Auth/verified email, Server API and Widget signing configuration, proven customer. No offer/calendar/allowance/seller agreement prerequisite. |
| Product-bound purchase/payment (Step 3) | Valid link/live terms/consent, configured seller and billing/Widget connection, then actual prepared-subscription proof. |

Missing/invalid billing values must produce a safe capability-specific error and
no outbound request using an invalid URL or secret. This is not permission to
ignore invalid configuration or weaken production TLS. Do not add a capability
registry/framework; use the existing composition and feature error boundaries.

### CLI target and manual setup contract

These are TARGET commands to implement, not commands to run during authoring:

```bash
# From the configured environment, with root venv and current operator privileges:
PYTHONPATH=apps/api .venv/bin/python -m app.cli.commercial_mappings dry-run \
  --product-id proposal_ai --tariff-id 32 --tariff-service-id 1 --period-id 1

PYTHONPATH=apps/api .venv/bin/python -m app.cli.commercial_mappings publish \
  --product-id proposal_ai --tariff-id 32 --tariff-service-id 1 --period-id 1 \
  --expected-previous-revision 0

PYTHONPATH=apps/api .venv/bin/python -m app.cli.commercial_mappings query \
  --product-id proposal_ai
```

`0` means no CURRENT product link; replacement uses the revision returned by
query. Preserve an existing `query --offer-id/--revision` history path if required
for referenced v1 rows. Define expected revision consistently at PRODUCT head,
including a change of offer; no accidental cross-offer head choice. Provide
matching commands inside the normal worktree container using the actual harness
configuration, without printing secrets or assuming an unrelated Compose project.

### Tests to write (not run)

`test_any709_step1_sources.py`: real-client mocked HTTP parsing, enabled product,
complete selected composition, correct period vs period-association ID, exact
money, current price change, invalid/unknown currency or price dates, unavailable
sources, separate mock provenance, removed-config independence, configuration
pass-through and redaction. Add positive normal-config tests with NO retired
proof objects; production-shaped compatible remote-source configuration; dev
Kernel mock + real-client LBX; missing signing secret not breaking catalog/auth;
known unmapped product and absent metered allowance without fabricated values.
Use captured LBX 043 fixtures plus synthetic historical/future prices for
selected-period applicability, duplicate dates, absent current prices,
cross-method conflicts and selected-only discount evidence. Cover the inclusive
2026-10-31 23:59:59 MSK -> 2026-11-01 00:00:00 MSK boundary, one evaluation date
across both control reads, actual drift, host-timezone independence and no
timezone configuration. Check IANA availability in Python and the API image.
Use test transports, not real credentials or a live network.

`test_any709_step1_postgres.py`: migration on populated baseline; legacy history
readability; link publish/query; identical repeat; concurrent first publication;
retarget/CAS across offers; no duplicate active product heads; unchanged old pins;
no synthetic promotion. Include restart/credential rotation with unchanged
internal scope and rejection of incompatible existing real connection bindings.
Update relevant existing catalog/publication tests for changed semantics rather than weakening ownership/no-store/concurrency tests.

### Human verification and review checkpoint

```bash
PYTEST_ADDOPTS='-k any709_step1' npm run test:api:fast
python scripts/repo.py test-db up
PYTEST_ADDOPTS='-k any709_step1' npm run test:api:postgres
python scripts/repo.py test-db stop
```

Then HUMAN sets connection secrets, applies the forward migration with
`npm run migrate:api` to the intended local DB and runs
`npm run repo:up -- --reuse`. Execute CLI dry-run/publish/query on 043. Inspect
through supplied read-only SQL: one current link, correct product/offer refs,
immutable revision/audit, no new billing customer/purchase/subscription. Do not
run development migrations with a production URL.

PASS: application wiring is complete; link works without old files/IDs; listing
is honest and the selected offer is live; tests establish history/CAS safety.
Close each inherited register row in the handoff with the changed consumer and
its focused test/manual observation. Old names retained solely for v1 history or
negative tests are documented, not mistaken for a runtime dependency. A result
that still asks the owner to supply approval/policy JSON is NOT Step 1 completion.
No need to mutate a real tariff to test repricing: use the focused fake-provider
test; human live repricing is optional only when explicitly authorized.

### AI prompt

> Implement ONLY Step 1 of this plan from the actual current main. Read sections
> 0-3, this full step, applicable AGENTS and the direct source/catalog/CLI/config
> dependencies. Deliver ordinary real LBX wiring, one direct product-link CLI,
> versioned history/current-head safety and source-backed catalog/current offers.
> Close the inherited ANY-664 register through Settings, normalizers, stored
> readers, API/generated web contracts and Compose, not only CLI loaders.
> Remove mandatory proposal/approval/profile workflow and manual duplicate
> account IDs without deleting accepted history, weakening validation, inventing
> policy/quantity facts or reclassifying synthetic IDs. Keep the Kernel mock
> technical and dev-only; no billing fixture in normal runtime. Resolve concrete
> code layout yourself using existing clients/publication/persistence boundaries.
> Align only the changed documentation rules; do not apply the old bulk script.
> Write focused unit/PostgreSQL tests and exact operator/read-only SQL examples.
> Follow section 0: formatting/lint and needed generation only; no tests,
> migrations, builds, containers, live probes, stage/commit/push. Stop after this
> step and report actual commands, NOT_RUN tests and the manual checkpoint.

## 5. Step 2 - Optional FIO, one customer and a real account Widget

Status: DONE (implementation); recorded automated/local checks PASS and owner observed the real account Widget; real payment acceptance NOT_RUN.
Handoff: [Step 2 delivery](ANY-709-step-2-handoff.md). Original NOT_RUN statements predate the recorded subsequent corrections and checks.
Depends on: human-accepted Step 1 interfaces and ordinary connection wiring.

### Result and changed surfaces

An existing or new verified Portal user can explicitly open billing and see the
real official Widget, including its empty state, without a PurchaseIntent or
prepared subscription. Concurrent opens cannot create multiple LBX customers.

Modify identity model/service/router and `AuthForm`/auth adapters; add a narrow
billing-account application/route; extend the existing LBX transport with users
and Client API reads/JWT; reuse customer/operation/work-item models and minimal
persistence/queries/migration; connect product/account entry, SDK lifecycle,
public safe errors/locales/CSP. Generate OpenAPI/TS in this step.

### Implement

1. Add independently optional first name, surname and patronymic end-to-end.
   Trim empty strings to absence, bound valid input without inventing actual
   names, keep existing users nullable. Do not make FIO/email changes a mandatory
   profile-repair flow. Do not copy email into a name field. Pass the existing
   confirmed email and only populated FIO to LBX when creating a new customer.
2. Reuse one customer slot and one common create-operation mechanism. Before
   POST, commit opaque key and operation/send fence; enforce one customer per
   Portal user/deployment and unique proven provider ID. A customer-only operation
   uses NULL purchase reference as the current model already permits.
3. Implement typed users GET/discovery/CREATE on the REAL existing Server API
   client. User POST includes `type=2`, email, saved outer key, unique CSPRNG
   technical login and strong random password (the tested 24-character ASCII
   letters/digits pattern is sufficient for compatibility). Keep credentials
   only in transient request memory. No password/raw request in recovery JSON,
   model repr/errors, logs, artifacts or generated config. No password reset or
   automatic PATCH for old malformed research customers.
4. Recognize operation-specific response status/body and point-read identity
   before binding. The owner-approved current `ensure_customer()` uses a fresh
   key/email discovery (point-proven by original identity), at most one CREATE
   during an explicit opening, then GET-only recovery after any CREATE failure.
   A later explicit opening can discover again and attempt one customer POST
   after its finite lease clears, preserving original key/slot/operation.
   Active leases, saved receipt and ambiguous identity prevent new POST.
   Save fenced possible-send and +2h recovery evidence, no scheduler. The
   financial operations in Step 3 **must not inherit** this retry allowance.
5. Implement authenticated POST bootstrap. Each allowed open rechecks session,
   email and paired provider ID/original customer outer key, then signs fresh
   type-7 JWT. For newly created/recovered/not-yet-ready customers, perform the
   necessary bounded Client API readiness read; wrong credentials receive a
   useful error, not another CREATE. Protect JWT response with no-store.
6. Mount the actual configured SDK on explicit user action, never during anonymous
   GET, link prefetch or render-only execution. Route mounts in React development
   must still be safe to repeat. Deduplicate SDK loading, ignore late responses
   for old user/product/request generation, clear Portal-held JWT at logout/
   unmount and avoid token persistence. Only validated configured origins enter
   CSP; do not disable CSP or use blanket wildcard access to make the test pass.
7. Use customer/account read-only presentation at this stage; do not fabricate a
   paid subscription or enable arbitrary creation inside Widget. No request to
   create a purchase agreement/subscription merely to open the account. Provider
   default agreement side effects, if observed, remain provider-owned and are
   not adopted as the later dedicated purchase agreement.
8. Explain configuration, identity, Server auth, UNKNOWN, Client readiness and
   SDK failures in localized UI with request ID. Journal sanitized stage/method/
   endpoint template/status/reason and operation correlation. Preserve useful
   errors without echoing passwords/JWT/email/FIO; no raw HTTP dump. Maintain
   actual provider facts vs local not-ready/access-not-yet-derived distinctions.
9. Update the precise Widget authorization documentation and security tests; do
   not remove purchase readback or claim UI flags prevent direct Client writes.

### Tests to write (not run)

`test_any709_step2_customer.py` and `test_any709_step2_postgres.py`: optional/full/
partial FIO; existing user migration; no registration-side LBX CREATE; genuine
user/Client response parsing; malformed success; two products/tabs racing on one
customer; possible-send crash/lost reply/late fenced completion; zero/one/multiple
recovery results; +2h escalation retains hold; existing customer reuse; changed
outer key; stale session after await; no secret persistence/PII leakage.

`any709-step2.test.tsx`: real SDK loader boundary substituted only inside tests;
explicit open, empty state, no-token-storage, reload/logout/user-switch races,
SDK failure and safe error display. With customer identity/readiness healthy,
a missing mapping or failed quote must not remove/block the billing entry or
await a failing catalog request before bootstrap. Keep guest/verification guards.
Test fixtures must never contact real LBX.

### Human verification and review checkpoint

```bash
PYTEST_ADDOPTS='-k any709_step2' npm run test:api:fast
python scripts/repo.py test-db up
PYTEST_ADDOPTS='-k any709_step2' npm run test:api:postgres
python scripts/repo.py test-db stop
npm --workspace @anytoolai/web run test:components -- any709-step2
```

Human applies migrations/restarts normal local stack, signs in with the EXISTING
verified user and opens Details/billing. Confirm official SDK/Client API and
one proven customer binding. Repeat/reload/open another product: same user ID,
no second CREATE and no Portal-created purchase agreement/subscription. Repeat
with a new optional-FIO user; inspect Admin display when FIO is provided, without
claiming an undocumented exact display-name formula. Inspect no secrets in
journal/storage; do not paste a JWT/signed Network request into the report.

PASS is `CUSTOMER_WIDGET_PASS` only. Empty real Widget proves this stage, not
payment or full ANY-709. Missing mapping/price must not prevent account access.

### AI prompt

> Implement ONLY Step 2 after human acceptance of Step 1. Read sections 0-3,
> this step and direct identity/customer/LBX/SDK dependencies. Add optional FIO
> without changing existing login/email semantics. Deliver one durable, fenced
> lazy customer operation, real users/Client reads, fresh type-7 JWT and official
> Widget on explicit open, including an empty account. Share customer identity
> across products and later purchases. A possibly sent POST is never replayed;
> save its deadline before send, recover read-only and expose precise safe errors.
> No subscription, price/profile gate, fake PurchaseIntent or billing fixture is
> allowed just to open the account. Do not persist technical credentials or JWT.
> Write backend/PostgreSQL/component tests, wire the actual UI and generated contracts,
> update only relevant Widget rules and provide the human smoke/SQL instructions.
> Follow section 0 execution restrictions; do not run tests/live LBX/containers,
> migrations/builds/typechecks or stage/commit/push. Stop and report this stage.

## 6. Step 3 - Accepted purchase, safe preparation and recovery

Status: DONE (implementation); focused synthetic tests and owner-authorized local migration PASS; final real payment acceptance NOT_RUN.
Depends on: current implemented Steps 1-2, their interfaces and the owner's
customer/Widget QA; confirm prior acceptance evidence for the real-LBX stage.

### Result and changed surfaces

Through Portal APIs the explicitly accepted purchase results in exactly the
chosen prepared subscription and payment-capable bootstrap, or a precise
pending/conflict state. Reuse Step 1's `Europe/Moscow` current-offer selection,
Step 2's **existing shared `ensure_customer()`**, and common LBX response/error
decoding. Do not fork account customer creation, JWT, error classification or
price handling. Step 3 is independently reviewable at API/DB/protocol level;
Step 4 completes Buy/Continue/Manage browser presentation.

Modify focused purchase app/routes/contracts; legal acceptance; relevant
purchase/operation/subscription models, scope queries/persistence; add narrow
agreement/subscription DTOs and methods to the existing LBX client; extend
the current account Widget bootstrap with optional verified purchase/payment
presentation; migration, Step 8 recovery seam and tests. No second SDK/identity
system or scheduler.

### Implement

1. Deliver the review/intent/current/status/advance contracts in 2.7. Review reads
   the selected current link, enabled technical product and complete applicable
   LBX offer. Return exact decimal money, service/period meaning and current legal
   versions. It does not create a subscription, consent or durable checkout.
2. On confirmation, first find same idempotency key and occupied user/product
   scope BEFORE new live reads. Same key/same meaning returns the existing intent;
   changed same-key request conflicts. Different keys cannot create parallel
   held purchases. New admission revalidates actual source terms and compares
   the expected fingerprint/legal versions. Client price/flags are never authority.
3. In ONE short transaction pin accepted snapshot, required append-only consent,
   current link revision and purchase hold. Create/reuse the LOCAL customer slot
   if needed for the existing FK; this transaction sends no customer POST.
   Recheck the exact reviewed link and current required legal versions under
   the local publication/hold concurrency boundary per 2.7. A retarget must not
   slip through on identical money. Do not resurrect an old catalog-
   approval file as legal acceptance. Keep source/config artifacts out of runtime
   authorization. Existing legal text remains unchanged; test legal versions
   remain clearly non-production legal approval.
4. Add minimal scope/operation fences and immutable-evidence guards described in
   2.4, reusing Step 2's customer operation. No paid-access-primary selection is
   performed. A linked unpaid subscription holds the scope indefinitely until
   proven terminal/no-effect or audited safe release, never a browser TTL.
5. `advance` resumes a bounded pipeline: call shared `ensure_customer()`;
   discover purchase bindings/operations; prepare dedicated agreement, selected
   subscription, authoritative readback and proven binding. Customer account
   opening remains independent of product price. Its owner-approved later-open
   customer retry policy is **not** a rule for financial CREATE. Revalidate the
   ORIGINAL accepted terms before previously UNSENT financial preparation after
   delay/restart/deadline, using Step 1's live Moscow-date offer, not stored
   current catalog prices. Do not silently reprice accepted conditions, turn
   an UNKNOWN financial operation into a fresh sale or rerun the original
   financial POST. Readback remains authoritative; never hold a DB transaction
   over LBX HTTP.
6. For an existing customer, use documented scoped inventory plus point proofs and
   local nonterminal/UNKNOWN scopes before admitting another relevant create.
   No list ordering, pagination guesses, whole-account scans or "zero -> retry".
   A foreign default agreement is not the chosen purchase agreement. Recover
   only a dedicated agreement whose origin/purpose/owner/seller are proven.
7. Extend the existing typed LBX client for agreement/subscription commands
   and reads, using its central HTTP response decoder and `LbxResponseFacts`.
   All endpoints interpret HTTP status, JSON `code`, `response.error` and
   safe failure categories consistently, including unknown texts and real
   HTTP 500. Provider error is diagnostic and does not prove a non-side-effect.
   Preserve documented filtered GET and 200/201 semantics; financial POST never
   uses GET retry. Persist durable identity, fence, original deadline and
   recoverable non-secret request facts before possible send.
8. Agreement request: proven user ID, explicit configured organization, durable
   unique number/correlation and documented create fields. Use supported non-offer
   form where the accepted evidence calls for it; empty agreement_link is not an
   error by itself. Creation date is a provider-required contract field, not a
   purchased period; where an LBX calendar date is needed, use the confirmed
   `Europe/Moscow` calendar, never `LBX_BILLING_TIMEZONE`, host timezone,
   invented UTC intervals or an operator-written per-purchase profile. Do not
   add undocumented `debt_threshold` or claim missing credit facts are zero.
9. Subscription request: selected tariff and PERIOD ID, explicit selected service
   with verified fixed quantity, balance-gated activation, no manual/demo path
   for this MVP. Omit `subscription_start_date` for the evidence-backed supported
   flow; do not invent activation date/UTC month. Record that actual tariff-32
   acceptance still needs the human integration check, not a new preparatory probe.
10. Point readback: canonical subscription ID -> agreement -> user, expected
    seller, tariff/period/service composition, quantity, effective unit/total
    recurring and applicable connection amounts, currency, supported creation
    conditions. Preserve observed nullable/sentinel waiting dates as not-yet-paid
    facts. Do not require subscription `price_id=288` or association ID 82, nor
    reject a known subscription solely on its mutable subscription outer_id.
11. Persist confirmed subscription binding and observed waiting/active/etc facts
    WITHOUT issuing grants, assuming financial eligibility or extending paid
    trust. Known mismatch is conflict; incomplete proof stays pending/review.
    Catalog change alone cannot invalidate an unchanged historical subscription.
12. Extend the *existing* `POST /api/billing/widget-bootstrap` from Step 2
    with an optional owned prepared-purchase reference and generated DTOs.
    Preserve the empty account-only request/response and single SDK/JWT identity.
    Only the original accepted purchase and verified concrete subscription,
    customer, seller and agreement readback enable payment-capable flags.
    Manage checks the original binding, not today's catalog price/mapping.
    Customer identity UNKNOWN blocks JWT; purchase-only failure does not block
    independently proven account-only viewing or fabricate paid access.
13. Deliver request-driven **financial** GET-only recovery, callable overdue
    escalation and bounded authorized operator financial inspect/recover using
    existing app functions. The current `billing-customer diagnose` remains a
    read-only customer command, not a financial operation or a separate
    HTTP 500 decoder. Reuse safe centralized diagnostics. No force-bind/grant,
    guessed absence proof, support UI or Step 8 worker. Document holds,
    trustworthy release requirements and Step 8 integration seam.

### State and failure matrix to implement

| Situation | Required behavior |
|---|---|
| New free product scope; fresh offer/consent match | One immutable accepted intent; at most one potentially sent CREATE of each intended object. |
| Same request repeated / two different keys | Return same intent or occupied scope; never create another subscription. |
| Price changes before accepted intent | Fresh review/terms_changed; no provider financial object created at unaccepted price. |
| Accepted intent, no agreement/subscription may have been sent, terms now differ | Mark safe not-prepared/needs-new-consent outcome without rewriting acceptance; new accepted attempt only after safe hold resolution. Keep the shared customer. |
| Agreement/subscription may already exist when terms differ | Keep hold; recover and verify original operation; conflict/manual review rather than silent replacement/repricing. |
| Malformed success, possibly sent financial POST with 5xx (including `response.error`), timeout or crash | Financial UNKNOWN/hold and original deadline; GET-only recovery. Error text does not authorize a repeated CREATE. |
| Discovery zero / multiple / one fully proven | Pending / review / bind existing object. No count alone authorizes a retry. |
| Deadline reaches +2h | Escalate to review; do not release scope or retransmit. |
| Old worker/response arrives after fence changed | Reject stale apply; retain newer result and safe holds. |
| Prepared unpaid subscription and page abandoned | Same intent/subscription remains resumable without checkout TTL. |
| Current catalog price changed, old effective subscription unchanged | Historical Manage/readback can succeed using original consent. |
| User switched/logged out during preparation/bootstrap | No wrong-user result/JWT; recorded operation remains safely recoverable. |

### Focused tests and validation

`test_any709_step3_purchase.py`, `test_any709_step3_postgres.py`: exact accepted
terms/doc versions; before/after-acceptance price changes; owner/tenant/auth
failure; same/different key races (including 20 attempts); customer shared with
account entry; agreement and subscription permanent uniqueness; no HTTP under
transaction; possible-send/DB-commit acknowledgement loss and late fences;
zero/one/multiple discovery; restart/+2h/hold behavior; real-format 200/201 and
malformed successes; org9 rejected for seller21; waiting dates; period ID vs
association ID; changed subscription outer hint; effective vs catalog price;
legacy link/Manage history; no grants/trust writes; redaction and bounded capacity.
Include link retarget and legal-version changes while source I/O is in flight,
equal-price different-offer selection, and unchanged terms with only irrelevant
observation timestamps/read-set provenance changing. Those must not silently
rebind a purchase or manufacture a new monetary-consent conflict.
Test that payment flags are not permanently fixed true in the generated DTO.
Additionally cover reuse of the actual `ensure_customer()`, the separate
customer-later-open vs financial-no-retry policies, shared LBX 500/200 error
envelopes for agreement/subscription GET/POST, and confirmed Moscow dates.
All automated tests use synthetic provider transports, never live LBX writes.

### Human verification and review checkpoint

```bash
PYTEST_ADDOPTS='-k any709_step3' npm run test:api:fast
python scripts/repo.py test-db up
PYTEST_ADDOPTS='-k any709_step3' npm run test:api:postgres
python scripts/repo.py test-db stop
```

Codex may run these focused commands on the isolated disposable test DB,
plus relevant regressions and a canonical stage check. Only the HUMAN may apply
migrations to the intended application DB and use real LBX 043 through Portal
API/Swagger to review and explicitly confirm one test purchase. Use a
verified user/current product link, not a manually assigned research user ID.
Record intent/operation IDs and sanitized provider bindings; inspect that there
is one proper seller agreement and one correct subscription, no paid grant and
no repeat CREATE. SDK payment presentation may be inspected here; no payment is
sent by the implementation agent. Report precise provider errors if live
org21/tariff32 behavior differs, rather than adding global approval flags.

### AI prompt

> Implement ONLY Step 3 using the latest accepted Step 1-2 code and handoffs.
> Read sections 0-3 and this step, then directly affected purchase/legal/LBX
> interfaces. Create immutable PurchaseIntent/consent, one held scope and the
> review/confirm/current/status/advance APIs. Reuse `ensure_customer()`, the
> Europe/Moscow current-offer selector and shared LBX response/error decoder.
> Customer later-explicit-open retry must NOT become financial CREATE retry.
> Before any agreement/subscription possible send record its durable
> fence/identity/hold and original +2h escalation; a 500 `response.error`
> is diagnostic, not proof of no side effects. Use seller21 only via config,
> chosen tariff/service/period and authoritative concrete subscription readback.
> Extend existing widget-bootstrap for optional verified payment presentation,
> leaving the account-only request unchanged. No repricing, blind financial
> replay, fabricated paid access or Step 8 worker. Write and run focused
> synthetic/disposable-DB tests, generated contracts and stage checks permitted
> by section 0. No live LBX writes, owner-DB migration or stage/commit/push.
> Stop for owner QA/review with actual results and safe manual commands.

### Step 3 delivery, 2026-10-27

Initial delivery record; superseded for executed checks by the owner-authorized
follow-up below. IMPLEMENTED only. That request explicitly prohibited tests, typechecks, builds,
migration execution, app/live-provider probes, containers and broader checks.
Consequently, automated behavior acceptance and HUMAN_QA_PASS are **NOT_RUN**.
Base checkout: `9baaf2b225f951e04a0febe159795d158c870d52`; the starting working tree
was clean. No stage, commit, push, branch change or external-system write occurred.
Step 4 has not started.

The API now reviews current enabled-product/link/LBX terms, confirms immutable
acceptance with append-only exact document evidence, reserves one product hold,
returns owned local current/status, and explicitly advances bounded preparation.
Same-key/occupied-scope checks precede live reads; publication and required legal
versions are rechecked in the pin transaction after I/O. Original consent is
verified again before financial preparation/payment, without requiring old legal
versions to remain active. No financial HTTP runs inside SQL transactions.

The existing account customer ensure, JWT/Client readiness, central LBX decoder
and Moscow price selector are reused. One permanent financial operation per
intent/kind records its fence, original request/deadline and recovery work before
possible send. Dedicated agreement/subscription discovery and canonical point
proof can bind or report pending/conflict; malformed success, 500/response.error,
zero results, restart and +2h never trigger financial POST replay or TTL release.
Deadline escalation, safe unsent-terms hold resolution and authorized financial
inspect/GET-only recover are supplied, with no worker or force-release/grant.
Prepared subscription evidence is financially `unverified`, with no trust interval,
access-primary selection, grant, allowance or Kernel paid-access write.

The existing bootstrap accepts an optional owned prepared purchase, point-checks
its original customer/seller/agreement/effective subscription and session/fences,
and returns payment presentation with `disablePayments=false` and the intended
agreement/seller reference. Empty account-only requests remain compatible.
Create/edit/stop/autopay/invoice flags remain disabled. Historical Manage ignores
today's product head/catalog price. The real customer-wide JWT and accepted LBX
permission/replay risks are unchanged; the SDK gets no invented product filter.

Removed/replaced/retained: extracted the existing local customer-slot reservation
so consent/intent/hold can commit together; centralized the already-fenced POST
transport for its three actual consumers; replaced the account-only bootstrap
restriction only for verified prepared purchases. Retained one customer ensure,
SDK/JWT, HTTP error decoder, all immutable mapping/legal history and customer-only
viewing. Existing v1 mapping readers remain unchanged; unrecognized legacy purchase
snapshots fail closed as `purchase_history_unproven` rather than being promoted.
No legal source text, locale catalog or frontend purchase UI was changed.

Migration `20261027_0006` is authored, **NOT_RUN**. It adds the separate purchase
mutex, scoped permanent financial identities/bindings/evidence guard, unique
subscription/agreement history and explicit unverified financial state. Existing
operation scopes are copied from their own customers and nonterminal purchase
holds are backfilled; ambiguous history fails rather than choosing/deleting it.
No frozen baseline or prior migration was edited.

Tests authored/updated, all **NOT_RUN**:

- `test_any709_step3_purchase.py`: real typed synthetic HTTP 200/201/500,
  shared decoder/no POST retry, effective vs catalog terms, invalid/missing
  proof, seller isolation, nullable waiting dates/bulk facts, connection proof,
  generated boolean payment flag contract, account/payment response flags and
  the confirmed Moscow calendar.
- `test_any709_step3_postgres.py`: atomic consent/hold, 20 same/different-key
  attempts, price changes before/after acceptance/possible send, current-link
  retarget/legal change during source reads, shared customer, no HTTP while a DB
  resource is held, malformed/lost replies, zero/multiple discovery, restart/+2h,
  commit acknowledgement loss, stale fences, permanent uniqueness, old terms
  after price/link/legal-active changes, local API ownership/outage retrieval,
  logout before JWT, missing consent, populated forward upgrade and no paid writes.
- Updated the existing model/enumeration/schema/architecture/target-persistence
  expectations for this migration. Existing customer/Widget/source regressions
  remain required human verification.

Executed outcomes:

- Ruff format: PASS on the 29 changed API/migration/test Python files, with
  explicit file paths in the executed command; the harness keeps its existing
  manual formatting. Ruff check: PASS on the same paths.
- `KERNEL_MOCK_ENABLED=0 KERNEL_BASE_URL= KERNEL_SERVICE_TOKEN= PATH="$PWD/.venv/bin:$PATH" npm run generate`: PASS.
  Regenerated OpenAPI, SQLAlchemy schema reference and TypeScript contracts only.
  An initial generation found a misplaced `as_utc` import; it was corrected and
  final generation completed. Generation imports schemas without running the app.
- `npm run lint:web`: PASS (`eslint . --max-warnings=0`).
- `git diff --check`: PASS. Correctness and payment-security checklists were
  reviewed against the result/acceptance criteria; this is static review, not
  test/runtime evidence.
- All tests, typechecks, builds, migrations, app/browser/live-provider probes,
  container startup, architecture/docs checks and `check:fast`/`check`: **NOT_RUN**.

Exact human commands from repository root, **NOT_RUN** here:

```bash
PATH="$PWD/.venv/bin:$PATH" PYTEST_ADDOPTS='-k any709_step3' npm run test:api:fast
.venv/bin/python scripts/repo.py test-db up
PATH="$PWD/.venv/bin:$PATH" PYTEST_ADDOPTS='-k any709_step3' npm run test:api:postgres
.venv/bin/python scripts/repo.py test-db stop
```

Retest affected existing regressions with the same isolated test DB lifecycle:

```bash
PATH="$PWD/.venv/bin:$PATH" PYTEST_ADDOPTS='-k "any709_step1 or any709_step2 or any709_qa_offers or mapping_billing_calendar or billing_customer or lbx or billing_foundation or billing_reconciliation or model_enums or canonical_orm or clean_first_install or target_persistence"' npm run test:api:fast
.venv/bin/python scripts/repo.py test-db up
PATH="$PWD/.venv/bin:$PATH" PYTEST_ADDOPTS='-k "any709_step1 or any709_step2 or any709_qa_offers or mapping_billing_calendar or billing_customer or lbx or billing_foundation or billing_reconciliation or model_enums or canonical_orm or clean_first_install or target_persistence"' npm run test:api:postgres
.venv/bin/python scripts/repo.py test-db stop
```

After human review/tests, only the human may run
`.venv/bin/python scripts/repo.py migrate-api` against the intended configured
application database. Then follow the exact API/CLI checkpoint in the
[purchase runbook](../../engineering/lbx-product-links.md#purchase-api-and-financial-recovery-step-3):
review -> explicit confirmation with stable key -> advance -> current/status ->
optional purchase bootstrap. Repeat advance/reload and confirm one intended
seller agreement/subscription and no grants or repeated CREATE. The normal
`billing-purchase inspect` and `recover` commands are documented there.

Limitations: actual org21/tariff32 preparation, effective real readback, supported
Widget agreement targeting and payment still need human acceptance. A nonzero
accepted connection charge without effective connection evidence remains pending.
No current source/identity/consent ambiguity is guessed away. Step 4 browser UI,
Step 8 worker/reconciliation and later paid-access/Kernel delivery are deferred
as approved. No business decision or invariant was changed.

Changed files (including generated artifacts):

- `AGENTS.md`
- `ARCHITECTURE.md`
- `README.md`
- `apps/api/AGENTS.md`
- `apps/api/alembic/versions/20261027_0006_purchase_preparation.py`
- `apps/api/app/cli/billing_purchases.py`
- `apps/api/app/composition/billing.py`
- `apps/api/app/composition/purchases.py`
- `apps/api/app/core/settings.py`
- `apps/api/app/domains/billing/customers.py`
- `apps/api/app/domains/billing/router.py`
- `apps/api/app/domains/purchases/__init__.py`
- `apps/api/app/domains/purchases/contracts.py`
- `apps/api/app/domains/purchases/router.py`
- `apps/api/app/domains/purchases/service.py`
- `apps/api/app/infrastructure/queries/purchases.py`
- `apps/api/app/integrations/lbx/README.md`
- `apps/api/app/integrations/lbx/client.py`
- `apps/api/app/integrations/lbx/current_offer.py`
- `apps/api/app/integrations/lbx/financial.py`
- `apps/api/app/main.py`
- `apps/api/app/models/__init__.py`
- `apps/api/app/models/billing_purchase.py`
- `apps/api/app/models/billing_subscriptions.py`
- `apps/api/app/models/enums.py`
- `apps/api/tests/support/any709_step3.py`
- `apps/api/tests/test_alembic_postgres.py`
- `apps/api/tests/test_any709_step3_postgres.py`
- `apps/api/tests/test_any709_step3_purchase.py`
- `apps/api/tests/test_architecture.py`
- `apps/api/tests/test_billing_foundation_models.py`
- `apps/api/tests/test_billing_reconciliation_models.py`
- `apps/api/tests/test_model_enums.py`
- `apps/api/tests/test_target_persistence_postgres.py`
- `apps/web/src/generated/api-contracts/index.ts`
- `apps/web/src/generated/api-contracts/types.gen.ts`
- `docs/README.md`
- `docs/RELIABILITY.md`
- `docs/SECURITY.md`
- `docs/architecture/decisions/0005-external-billing-boundary.md`
- `docs/architecture/payment-portal-data-model.md`
- `docs/engineering/lbx-product-links.md`
- `docs/exec-plans/completed/ANY-709-implementation-plan.md`
- `docs/generated/db-schema.md`
- `docs/generated/openapi.json`
- `scripts/repo.py`

### Step 3 owner-authorized tests, migration and focused QA, 2026-10-27

Status: IMPLEMENTED + AUTOMATED_PASS for the focused synthetic scenarios;
LOCAL_DEVELOPMENT_MIGRATION_PASS. Real LBX purchase/payment HUMAN_QA_PASS is
NOT_RUN. The owner explicitly requested running migrations/tests and basic QA
and supplied two failing PostgreSQL tests. This follow-up supersedes the initial
delivery's execution pause, without starting Step 4 or changing business rules.

Both reported failures were reproduced and corrected in test setup:

- Populated upgrade seeded customer operations by calling the current application
  against revision `0005`, before its new ORM account column existed. Seed the
  prior operation schema directly, then upgrade and assert the original customer
  key, operation ID/state/correlation/fence and +2h recovery timestamps survive,
  with the operation account backfilled from its own customer.
- Lost-commit-acknowledgement injection inspected `Session.dirty` after the claim
  deliberately flushed. Inspect the retained session identity map instead and
  assert that the injected loss actually occurred. GET recovery retains the
  original fence/deadline/hold and sends no agreement CREATE.

Added two complete HTTP smoke scenarios using the real app router/middleware,
disposable PostgreSQL and synthetic Kernel/LBX transports: ordinary preparation
and a lost agreement response with temporarily invisible discovery. Both cover
account bootstrap, review, immutable confirmation, occupied alternate-key scope,
refused premature payment, advance/Continue, verified payment presentation,
original agreement number/seller target, source-independent current/status/same-key
replay, exactly one customer/agreement/subscription and no paid-access writes.
The smoke test initially compared the agreement number to its numeric provider ID;
the expected customer-facing reference was corrected, then both scenarios passed.

Architecture/docs checks also exposed Step 3 delivery gaps, now corrected:

- Query storage takes the acceptance row bound as an argument rather than
  importing a Domain policy constant.
- Financial transactions moved unchanged from `purchases/service.py` to
  `purchases/financial.py`; composition and tests use that owner directly.
- The existing single-attempt HTTP body moved unchanged to LBX `_transport.py`;
  `LbxRead` moved to `dto.py`, preserving client reexports. There is one client,
  response decoder and POST path. All runtime modules meet the existing 500-line
  limit with no exception or architecture-rule weakening.
- Engineering docs use an English description of the provider currency symbol.

Executed outcomes:

- Final unit/HTTP/architecture regression selection: **627 passed** in 16.95s,
  including all **13 Step 3** protocol/contract tests.
- Final PostgreSQL selection: **37 passed** in 82.64s, comprising all **26 Step 3**
  tests (including both new API smoke cases) and **11 shared customer-ensure**
  regressions. Clean upgrades and the populated `0005 -> 0006` upgrade execute
  only in the disposable test database.
- Earlier expanded PostgreSQL run: **122 existing related regressions passed**;
  only the two new smoke reference expectations failed, corrected and rerun as
  described above. No claim that this initial combined run was a full PASS.
- An initial sandboxed fast run was interrupted after 9 passes when its HTTP
  test stalled; the unsandboxed focused runs completed, first 548 and finally
  627 passing. No runtime code workaround was introduced for the sandbox.
- Explicitly verified the application target as this worktree's local loopback
  development database, then ran `scripts/repo.py migrate-api`: **PASS**, revision
  `20261026_0005 -> 20261027_0006`. Counts before/after were identical: users 4,
  customers 4, create operations 4, document acceptances 12, legal events 4;
  purchases and subscriptions remained 0. No production migration/provider I/O.
- Ruff format/check: **PASS** on all 9 Python files changed in this follow-up.
- `npm run architecture:check`, `npm run docs:check`,
  `KERNEL_MOCK_ENABLED=0 KERNEL_BASE_URL= KERNEL_SERVICE_TOKEN= PATH="$PWD/.venv/bin:$PATH" npm run generate:check`,
  and `git diff --check`: **PASS**. Generated contracts remained current.
- Full canonical check, builds/typechecks, browser E2E, real LBX financial writes,
  actual Widget agreement selection/payment and production migration: **NOT_RUN**.
  QA here is API/DB/protocol evidence with synthetic providers; the full human
  integration checkpoint remains in the purchase runbook. No staging/commit/push
  or next-step implementation occurred.

Exact final retest commands from the repository root:

```bash
.venv/bin/python scripts/repo.py test-db up
PATH="$PWD/.venv/bin:$PATH" PYTEST_ADDOPTS='-k "any709_step3 or billing_customer_ensure_postgres" --tb=short --show-capture=no' npm run test:api:postgres
PATH="$PWD/.venv/bin:$PATH" PYTEST_ADDOPTS='-k "any709_step3 or any709_step1 or any709_step2 or any709_qa_offers or mapping_billing_calendar or billing_customer or lbx or billing_foundation or billing_reconciliation or model_enums or canonical_orm or clean_first_install or target_persistence or architecture" --tb=short --show-capture=no -o faulthandler_timeout=60' npm run test:api:fast
.venv/bin/python scripts/repo.py test-db stop
```

Follow-up changed files: `apps/api/tests/test_any709_step3_postgres.py`,
`apps/api/tests/test_any709_step3_purchase.py`,
`apps/api/app/domains/purchases/service.py`,
`apps/api/app/domains/purchases/financial.py` (new),
`apps/api/app/composition/purchases.py`,
`apps/api/app/infrastructure/queries/purchases.py`,
`apps/api/app/integrations/lbx/client.py`,
`apps/api/app/integrations/lbx/_transport.py`,
`apps/api/app/integrations/lbx/dto.py`, `apps/api/AGENTS.md`, `README.md`,
`ARCHITECTURE.md`, `docs/RELIABILITY.md`, `docs/SECURITY.md`,
`docs/architecture/decisions/0005-external-billing-boundary.md`,
`docs/architecture/payment-portal-data-model.md`,
`docs/engineering/lbx-product-links.md`, and this plan. Existing user changes
were preserved. Migration `0006` itself required no SQL correction.

## 7. Step 4 - Complete Buy, Continue and Manage UI; final acceptance handoff

Status: DONE (implementation); targeted synthetic tests PASS; real-payment verification NOT_RUN.
Depends on: human-accepted Step 3 API behavior and Steps 1-2 normal real Widget.

### Result and changed surfaces

The normal product/account screens implement the agreed end-to-end flow without
operator help per user. Payment is actually available for the prepared correct
subscription. All exceptional states remain truthful and recoverable. The owner
has one runnable test/prod configuration guide and the Step 8 integration seam.

Modify existing product detail/account feature state/CTAs, focused purchase API
adapters and Widget controller, generated-contract consumers, seven locale files,
focused component/browser tests, request-ID diagnostics, runbook and final
as-built documentation. Do not redesign the main cabinet or defer missing
backend/configuration from previous steps into an undocumented cleanup list.

### Implement

1. Anonymous page remains read-only; auth/verified-email prompts precede personal
   billing actions. Verified Details can open the Step 2 account Widget and live
   offer independently. Map current intent/subscription state to Buy, Continue,
   Manage, preparing, recovery, terms_changed or review; not `unknown -> none`.
2. Buy displays actual review/required consents, confirms once and follows the
   same intent through bounded advance/status. Do not automatically accept a
   new price on retry or obtain a new idempotency key while the scope is held.
   On reload discover the owned current intent by product; token/key browser
   persistence is not necessary to recreate a purchase.
3. After proof, request payment bootstrap, replace/readjust the actual SDK view
   without retaining an old JWT, and identify the intended agreement/seller.
   The payable subscription may be prepared before the Widget opens or after an
   earlier account-only view. No fake product-filter API or arbitrary SDK create.
4. Preserve a safe SDK instance lifecycle across repeated clicks, product/user
   changes, logout, failed script load and late API results. Payment button must
   not stay disabled by an obsolete response type/frontend constant. No token in
   browser storage/URL/logs/Sentry; tests use synthetic tokens only.
5. Continue resumes the original held purchase; Manage validates its original
   bound subscription. Latest link/currency/catalog changes cannot silently
   rebind the existing relationship. Present actual conflicts and safe retry/
   support reference, not an endless spinner or a second Buy.
6. Widget close/callback can prompt a bounded status refresh, but never mark paid,
   grant access or mutate quota. Show observed billing state and separately that
   paid-access delivery belongs to later stages. No fake instant activation.
   A local status GET is not a new LBX observation. Until the Step 8 loop exists,
   show the last observed state/time or awaiting-verification truthfully; do not
   claim the status refreshed at LBX merely because a local GET returned 200.
7. Finish accessible desktop/mobile Bundle 3, localization and request-ID
   diagnostics. Use Step 3's generated Portal contracts and centralized LBX
   error classification: distinguish provider rejection, outage, auth, invalid
   response, terms_changed and financial UNKNOWN/recovery. Never expose raw
   `response.error` or invent a second frontend error parser/schema.
8. Reconcile touched docs/guards with as-built code, preserve completed Step 6
   history and explicitly list Step 8-10 deferrals. Remove abandoned runtime
   loaders/config/sample profiles/test-stub paths if any were selectively copied.
   Do not remove reusable test doubles/fixtures or broaden into unrelated cleanup.
   Confirm no copied PR #143 loader/gate leaked through Steps 2-3; do not defer
   the mandatory Step 1 inherited-code closure until this final stage.
9. Finish ONE runbook at `docs/engineering/ANY-709-billing-runbook.md` with the
   actual commands, safe read-only SQL, normal config, test DB vs application DB,
   mapping IDs/revisions, common failures, migration/rollback cautions, human
   acceptance ledger and concise Step 8 handoff. No compulsory companion JSON.

### Focused tests and validation

`any709-step4.test.tsx`: guest/verified flow, fresh review, double click, terms
changed, return unpaid, Manage with old link, script failure, wrong-user late
response, no secrets and truthful payment/access status.

`apps/web/e2e/any709-purchase.spec.ts`: desktop/mobile interaction and failure
states. Automated SDK/network substitutions are explicitly test-scoped and
must not mutate LBX or grant access. Separate this from the HUMAN real-LBX
acceptance; a mocked browser suite is not real Widget/payment evidence.

Extend backend contract/diagnostic regressions only where this step changes them;
keep test grouping `any709_step4`. Codex may run targeted synthetic
component/browser and isolated API tests plus the stage check under section 0;
actual LBX payment acceptance remains human-only.

### Human verification and review checkpoint

```bash
npm --workspace @anytoolai/web run test:components -- any709-step4
# HUMAN starts/configures the appropriate isolated browser harness first:
npm run test:e2e -- any709-purchase.spec.ts
# If this step adds backend regressions:
PYTEST_ADDOPTS='-k any709_step4' npm run test:api:fast
```

Then perform section 8 real acceptance through the ordinary application, not a
standalone HTML Widget or direct LBX research client. Independent review verifies
intent/business logic/architecture and actual outcome, not only checklist/code
shape. All four implementation stages must be accepted; no extra fifth "fix all
missing wiring" stage is planned.

### AI prompt

> Implement ONLY Step 4 from reviewed Steps 1-3 and the existing customer
> Widget, not a new SDK/identity system. Complete Details, review/consent,
> Buy, Continue, Manage and payment-capable presentation of the proven target
> agreement. Preserve original acceptance/link history, customer reuse,
> held financial scope and read-only account view. Handle changed prices,
> pending/UNKNOWN recovery, normalized provider rejections, no source,
> retry/race/logout and safe request ID without duplicate CREATE or fake
> paid access. Use generated API DTOs, localization and existing Widget
> lifecycle. Write and run focused synthetic component/browser/isolated tests
> and permitted checks, and finish the one runbook and Step 8 handoff.
> No live provider writes/payments, owner data migrations, background workers,
> Kernel access or stage/commit/push. Report real-vs-synthetic evidence.

### Step 4 delivery, 2026-10-27

Status: IMPLEMENTED_AWAITING_HUMAN_QA. The current owner instruction limits this
turn to editing and plan-required formatting/lint/generation; it overrides this
step's earlier permission to run tests. No tests, typechecks, builds, migrations,
containers, application/provider probes or external updates ran in this delivery.
The starting checkout was clean at `db63966` with delivered Steps 1–3.

Implemented result:

- Product details and existing account product cards now use the same localized
  Buy/Continue/Manage controls. Guest and email-verification prompts precede
  personal billing; public live offer loading and account Widget opening remain
  independent of purchase/current-catalog failures.
- Current owned hold lookup precedes Buy/review. Review displays exact terms and
  required canonical RU draft legal versions/text. Confirmation is fenced against
  double clicks and keeps the same key/meaning after uncertain responses. A
  terms-change refusal requires a new explicit review with unchecked consent.
- One bounded advance follows acceptance; Continue/recovery retains the original
  intent. Reload/status uses local owned history; uncertain/manual-review states
  cannot become an invented empty purchase or a replacement Buy.
- Manage and successful preparation request the original intent's payment
  bootstrap. The shared disposable SDK controller validates presentation/target,
  enables payments, shows agreement/seller and replaces any older SDK host.
  Payment-only form/popup/user-navigation sandbox permissions remove inherited
  account-view restrictions. No invented product filter or payment REST call.
- Closing reads local saved status once. The UI explicitly awaits authoritative
  financial verification and distinguishes payment from deferred paid access.
  Credentials remain outside storage, URLs, UI state and diagnostics; late
  results after close/logout/product/user changes cannot mount them.
- All seven locales, Bundle 3 responsive controls, semantic consent/heading
  structure, request-ID diagnostics, synthetic component/browser coverage and
  the single billing runbook are updated. The browser suite authors desktop/
  mobile screenshots and axe checks; none were executed here.

Removed/replaced/retained: replaced the duplicated account-only controller with
one shared SDK lifecycle and removed its permanent account/payment refusal.
Moved the existing exact money formatter to shared presentation, retaining its
old export for callers/regressions. Replaced the former runbook body with a
navigation stub retaining historical anchors; the complete guide now lives at
`docs/engineering/ANY-709-billing-runbook.md`. Old ANY-664 CLI/client instructions
are explicitly historical; source inspection found no PR #143 profile loader or
manual account/approval gate in runtime/config. Existing test doubles and
completed Step 6 history are retained. No backend model, wire contract, financial
policy, provider configuration or access/Kernel behavior changed.

Formatting/lint/generation evidence:

- IMPLEMENTED: changed-file ESLint fixes and matching existing CSS/JSON/Markdown
  style. Initial lint found React effect/ref rules; those were corrected without
  suppressions. Final full changed-file ESLint exited 0; the final heading/session-race changes
  also passed focused lint. Exact command (paths relative to `apps/web`):

  ```bash
  (cd apps/web && npm exec --no -- eslint eslint.config.mjs 'src/app/[locale]/account/page.tsx' src/features/account/AccountClient.tsx src/features/billing/BillingAccount.tsx src/features/billing/index.ts src/features/billing/official-widget-sdk.ts src/features/billing/ProductBilling.tsx src/features/billing/PurchaseTerms.tsx src/features/billing/WidgetView.tsx src/features/billing/errors.ts src/features/billing/use-billing-widget.ts src/features/catalog/CatalogPreviewClient.tsx src/features/catalog/ProductDetail.tsx src/features/catalog/format-money.ts src/shared/api/billing.ts src/shared/api/transport.ts src/shared/api/purchases.ts src/shared/formatting/money.ts tests/components/AccountClient.test.tsx tests/components/SessionRaces.test.tsx tests/components/any709-step2.test.tsx tests/components/any709-step4.test.tsx tests/fixtures/purchase.ts e2e/any709-purchase.spec.ts --fix --max-warnings=0)
  ```

- `git diff --check`: PASS. No Python source changed, so Ruff is not applicable.
- Migration: NONE. Generated sources/contracts: UNCHANGED; `npm run generate`
  is NOT_REQUIRED and was not run. Locale catalogs are source files.
- Tests: NOT_RUN, including new `any709-step4.test.tsx` and
  `any709-purchase.spec.ts` and changed existing regressions. No AUTOMATED_PASS
  or HUMAN_QA_PASS is claimed for Step 4. All typechecks/builds/canonical checks,
  docs/boundary checks, screenshots/axe and real payment verification: NOT_RUN.

Exact manual verification from the repository root:

```bash
npm --workspace @anytoolai/web run test:components -- any709-step4
# Human configures/starts the isolated browser harness first:
npm run test:e2e -- any709-purchase.spec.ts
npm --workspace @anytoolai/web run test:components -- any709-step2 AccountClient SessionRaces CatalogPreview CatalogTransport
npm run test:boundaries:web
npm run docs:check
npm run generate:check
npm run typecheck:web
npm run build:web
```

Then follow the single runbook's normal test configuration and final real
scenario through the ordinary application. Real agreement/payment target,
acquiring form/popup/return behavior, effective subscription prices and any safe
test payment remain human-only NOT_RUN. Existing customer Widget observation
and inherited Step 3 synthetic/local migration evidence do not prove them.
The existing purchase DTO provides no observed financial time/state; this UI
uses the approved awaiting-verification alternative. No new wire schema was
invented. Workers/webhooks/reconciliation, paid trust/grants/AccessSnapshot and
Kernel usage/quota remain program Steps 8–10. The runbook records actual models,
locks/fences, GET-only recovery/escalation interfaces, SQL and capacity limits
for ANY-715. No new business-decision contradiction was found.

Diff review: checked the selected result/acceptance criteria and final human
scenario against route wiring, generated DTO consumption, consent/idempotency,
held recovery, original-link Manage, payment flags/sandbox, SDK races, localized
safe diagnostics, observation truth and future-stage boundaries. No stage,
commit, push, PR/Linear change or next-step implementation was performed.

Changed files (repository-relative inventory):

- `AGENTS.md`
- `ARCHITECTURE.md`
- `README.md`
- `apps/api/AGENTS.md`
- `apps/api/app/cli/COMMERCIAL_MAPPINGS.md`
- `apps/api/app/integrations/lbx/README.md`
- `apps/web/e2e/any709-purchase.spec.ts`
- `apps/web/eslint.config.mjs`
- `apps/web/src/app/[locale]/account/page.tsx`
- `apps/web/src/app/product-detail.css`
- `apps/web/src/features/account/AccountClient.tsx`
- `apps/web/src/features/billing/BillingAccount.tsx`
- `apps/web/src/features/billing/ProductBilling.tsx`
- `apps/web/src/features/billing/PurchaseTerms.tsx`
- `apps/web/src/features/billing/WidgetView.tsx`
- `apps/web/src/features/billing/errors.ts`
- `apps/web/src/features/billing/index.ts`
- `apps/web/src/features/billing/official-widget-sdk.ts`
- `apps/web/src/features/billing/use-billing-widget.ts`
- `apps/web/src/features/catalog/CatalogPreviewClient.tsx`
- `apps/web/src/features/catalog/ProductDetail.tsx`
- `apps/web/src/features/catalog/format-money.ts`
- `apps/web/src/messages/de.json`
- `apps/web/src/messages/en.json`
- `apps/web/src/messages/es.json`
- `apps/web/src/messages/fr.json`
- `apps/web/src/messages/it.json`
- `apps/web/src/messages/pt.json`
- `apps/web/src/messages/ru.json`
- `apps/web/src/shared/api/billing.ts`
- `apps/web/src/shared/api/purchases.ts`
- `apps/web/src/shared/api/transport.ts`
- `apps/web/src/shared/formatting/money.ts`
- `apps/web/tests/components/AccountClient.test.tsx`
- `apps/web/tests/components/SessionRaces.test.tsx`
- `apps/web/tests/components/any709-step2.test.tsx`
- `apps/web/tests/components/any709-step4.test.tsx`
- `apps/web/tests/fixtures/purchase.ts`
- `docs/PRODUCT.md`
- `docs/README.md`
- `docs/SECURITY.md`
- `docs/architecture/contours.md`
- `docs/architecture/decisions/0005-external-billing-boundary.md`
- `docs/engineering/ANY-709-billing-runbook.md`
- `docs/engineering/lbx-product-links.md`
- `docs/exec-plans/completed/ANY-709-implementation-plan.md`
- `docs/product/ru-mvp.md`

### Step 4 owner-authorized automated tests, 2026-10-27

The owner explicitly requested running the tests and checking their execution,
with **no QA**. This follow-up authorizes automated test execution after the
initial write-only handoff above. Historical NOT_RUN entries describe that first
turn; current synthetic outcomes are recorded here. No manual/exploratory QA,
live LBX call/payment, application DB migration, production change, container
startup, build, stage/commit/push or next program step was performed.

Executed outcomes (all final runs exited 0, no skipped tests):

- `npm --workspace @anytoolai/web run test:components -- any709-step4 any709-step2 AccountClient SessionRaces CatalogPreview CatalogTransport`:
  **205 PASS in 6 files** (19.35s). The new Step 4 file contains 23 tests;
  inherited account/Widget/session/catalog regressions contain 182 tests.
- `npm run test:boundaries:web`: **38 PASS** (5.99s), including seven-catalog
  key/ICU parity, direct-copy/architecture/transport guards and the existing
  TypeScript-tooling regression. That existing test invokes `next typegen` and
  the web typecheck internally; no separate broad typecheck command was run.
- `npm exec playwright test -- --config .harness/any709-step4.playwright.config.ts any709-purchase.spec.ts`:
  **8 PASS**, four scenarios in each desktop/mobile project (46.1s).
  These tests intercept every API request and substitute only the SDK boundary.
  Automated screenshot, overflow and axe assertions are part of the suite;
  they are not manual/human acceptance or evidence of actual LBX payment.
- After correcting the test-only selector option described below,
  `npm --workspace @anytoolai/web run test:components -- any709-step4`:
  **23 PASS** (10.38s). Unchanged production code and the other 182 regressions
  did not need another duplicate run.
- Changed test ESLint with `--fix --max-warnings=0`: PASS;
  `git diff --check`: PASS.

Failures investigated and resolved:

1. Restricted sandbox initially prevented Chromium launch (`sandbox_host_linux`,
   EPERM) and the tooling test's `spawnSync npm`. Repeating those existing tests
   outside the sandbox resolved the OS restrictions; no production guard was
   weakened and no test assertion was disabled.
2. The default Playwright URL served the old application image without Step 4.
   The stale-build run was stopped and is not acceptance evidence. A temporary,
   ignored config starts a test-owned Next dev server from this checkout at
   `http://127.0.0.1:3107`, sets the synthetic API origin to port 3108 and uses
   `reuseExistingServer=false`; the webServer lifecycle ends with Playwright.
   No existing application/DB/container was restarted. All API/SDK responses
   remain intercepted, so no billing service is contacted.
3. The tooling regression exposed nine TypeScript errors in the new component
   test: Testing Library's `ByRoleOptions` does not support Playwright's `exact`
   option. Removed that test-only option; role names already match exactly by
   default. The component rerun and all 38 boundary/tooling tests then passed.
   No application implementation change was necessary.

The temporary Playwright config imports the canonical root config and overrides
only workers (2), the local web URL and a test-owned `webServer` command:
`npm --workspace @anytoolai/web run dev -- --hostname 127.0.0.1 --port 3107`.
It warms `/ru/products/proposal_ai` and injects `APP_PUBLIC_BASE_URL`, the
synthetic `NEXT_PUBLIC_API_BASE_URL` and `NEXT_TELEMETRY_DISABLED=1`. Its readiness
request and route compilation are test infrastructure, not manual QA. No
backend/API contracts or commercial data changed. The installed dev server
reported Next.js 16.3.1; the manifest pins 16.4.2. No dependency installation or
upgrade was performed in this test-only follow-up.

Artifacts: `.harness/playwright-report/results.json`,
`.harness/playwright-report/html/index.html` and
`.harness/playwright-results/`. These contain synthetic test identities/tokens
only. Runtime guards keep actual credentials out of the recorded UI/storage.
The ignored `.harness/any709-step4.playwright.config.ts` remains available for
repeating the exact isolated browser command above.

Current conclusion: **AUTOMATED_PASS for the selected synthetic Step 4 tests
and listed regressions**. HUMAN_QA_PASS, actual intended-agreement/acquiring
compatibility and PAYMENT_PASS remain **NOT_RUN**. This follow-up does not
perform the separately deferred QA or implement reconciliation/paid access.

### Step 4 purchase timeout incident and correction, 2026-10-27

Owner report: Buy showed the generic unavailable message for request
`7eca309854ed636e00a6534f50ac2554`. Diagnosis used only existing API logs, its
recorded Tempo trace and a PostgreSQL session with
`default_transaction_read_only=on`. No Buy/advance/recover was replayed, no new
LBX call was sent, and no data was changed during diagnosis. Original provider
CREATE entries belong to the owner's reported click, not this investigation.

Observed facts:

- Original `POST /api/purchase-intents` and its `/advance` both completed with
  HTTP 200. Original agreement CREATE returned 201 and subscription CREATE 200;
  point reads completed successfully.
- The recorded server `/advance` span took **5555.422487 ms**. The browser's shared
  transport timer aborted fetch after **5000 ms**, before that successful reply.
  The UI therefore showed its client-side generic unavailable message and never
  proceeded to Widget bootstrap for this action.
- Read-only persistence inspection confirmed one held `linked` purchase, bound
  agreement/subscription operations and exactly one subscription row.
  `financial_access_status` remains `unverified`; this is not paid access or
  actual-payment evidence. Per-user/provider identifiers are omitted here.

Correction, within the existing Step 4 UI/transport scope:

- `postJson` accepts an optional finite deadline while retaining five seconds by
  default. Live review/confirm/advance and both Widget presentations use one
  `billingRequestTimeoutMs=130000` policy, covering the API's supported 120-second
  preflight maximum plus DB/response overhead. Identity and local status GETs
  retain five seconds. Backend budgets, retries and financial rules are unchanged.
- After a lost confirmation reply, one local current-intent GET discovers any
  accepted intent. Empty/failed inspection retains the original frozen review
  and key. No confirmation/advance POST is automatically repeated.
- After a lost advance reply, one local GET inspects that same original intent.
  Saved `linked` state offers Manage; failure/pending state retains the held
  purchase and shows recovery. No payment is authorized from the local GET;
  Manage still requests fresh original-purchase bootstrap proof.
- Added 11 virtual-time transport tests, three lost-response UI regressions and
  one delayed-preparation E2E scenario exercised in both browser projects.

Changed in this correction:

- `apps/web/src/shared/api/transport.ts`
- `apps/web/src/shared/api/billing-policy.ts` (new)
- `apps/web/src/shared/api/billing.ts`
- `apps/web/src/shared/api/purchases.ts`
- `apps/web/src/features/billing/ProductBilling.tsx`
- `apps/web/tests/components/any709-billing-timeouts.test.ts` (new)
- `apps/web/tests/components/any709-step4.test.tsx`
- `apps/web/e2e/any709-purchase.spec.ts`
- `docs/engineering/ANY-709-billing-runbook.md`
- This implementation plan.

Executed synthetic verification:

```bash
npm --workspace @anytoolai/web run test:components -- any709-step4 any709-step2 any709-billing-timeouts AuthContractValidation AccountClient SessionRaces CatalogPreview CatalogTransport
npm run test:boundaries:web
npm exec playwright test -- --config .harness/any709-step4.playwright.config.ts any709-purchase.spec.ts
(cd apps/web && npm exec --no -- eslint src/shared/api/transport.ts src/shared/api/billing-policy.ts src/shared/api/billing.ts src/shared/api/purchases.ts src/features/billing/ProductBilling.tsx tests/components/any709-step4.test.tsx tests/components/any709-billing-timeouts.test.ts --fix --max-warnings=0)
(cd apps/web && npm exec --no -- eslint e2e/any709-purchase.spec.ts --fix --max-warnings=0)
git diff --check
```

- Component tests: **227 PASS in 8 files**, no skips (7.16s), including 11 new
  timeout-policy tests and 26 Step 4 UI tests.
- Boundary/tooling: **38 PASS**, no skips (4.63s), including the existing
  TypeScript regression; no separate broad typecheck/build command was run.
- E2E: **10 PASS**, no skips (1.2m), including the delayed-preparation regression
  on desktop and mobile; all API/SDK responses are synthetic.
- Changed-file ESLint and diff whitespace: PASS. No Python/API schema/migration
  change or contract generation is required.

The first browser harness startup failed before tests because Turbopack hit the
OS file-watch limit. The ignored test config uses `--webpack` with
`WATCHPACK_POLLING=1000` for this rerun, without changing global watcher limits,
production config, dependencies or working containers. A permission-review
request timed out; the single permitted retry was approved. All browser API/SDK
traffic remains synthetic. Existing installed Next version is still 16.3.1
versus manifest 16.4.2, as recorded in the earlier follow-up.

The working web application was **not rebuilt/restarted** by this diagnosis;
the timeout correction is a source change until normal deployment. Reloading
reads the already-linked intent and can offer Manage without a replacement
purchase. Actual provider/payment QA, paid access and later program steps remain
out of scope. No stage/commit/push or external-system mutation was performed.

## 8. Human acceptance: normal setup and complete ANY-709 result

### 8.1 Ordinary test vs production configuration

| Input | Current local/test | Production |
|---|---|---|
| Portal DB | Its own local/test application DB; separate disposable pytest DB | Separate production DB |
| LBX origin | `https://043.lbxbilling.ru` | Production LBX origin |
| Server credentials | Existing test Server API credentials | Production Server API credentials |
| Widget signing secret | Test Client JWT signing secret, NOT the Server password | Production Client JWT signing secret |
| Seller | Organization 21 | Production seller organization ID |
| Kernel source | Existing separate technical HTTP mock | Actual compatible Kernel API/service auth |
| Product link | `proposal_ai -> tariff32 / service1 / period1` | Same real product identity -> that environment's actual offer IDs |
| Commercial config/payment method | Configured in test LBX, suitable safe payment test path | Configured by manager in production LBX |

Connection/privileged CLI parameters are one-time deployment configuration.
The price calendar is fixed to `Europe/Moscow` from the direct LBX support
answer; no timezone configuration is required in test or production. Ordinary
auth, SMTP and environment secrets use existing repository mechanisms.

Do NOT configure: user UUID lists; `LBX043_*` approvals; `MAPPING_ACCOUNT_ID`;
`LBX_EXTERNAL_BILLING_ACCOUNT_ID`; `PURCHASE_*PROFILE_FILE`; proposal/approval/
preparation/source-policy JSON. Test fixtures are not runtime configuration.

The final runbook must show EXACT host/container CLI and restart commands for the
current harness, and read-only SQL for actual table/column names. Explain what
changes after linking, after first customer open, and after one purchase. No
secrets are shown in diagnostic output. Synthetic existing mappings are not live
bindings; use the intended new real provider link, not the research user IDs.

Production uses the same compatible integration code, not necessarily identical
provider object numbers or automatically available acquiring. Configure its own
seller/offers/payment method and one CLI link; do not copy test customer IDs or
point a populated test DB at production. Actual deployment and Kernel conformance
remain human acceptance, not a hidden runtime authorization certificate.

### 8.2 Final real manual scenario

1. Start ordinary application with the test connection, existing Kernel mock,
   required migrations and one real link. No test SDK/global recording mode.
2. Existing verified user opens billing; assert real SDK/customer identity. New
   user with absent/partial/full FIO follows the same path. Login/registration
   alone sends no billing CREATE; subsequent account opens reuse the customer.
3. Review `proposal_ai` current terms. Explicitly accept and Buy. Inspect one
   accepted intent, own seller21 agreement and one subscription on the selected
   tariff/service/period. Confirm effective price from the concrete subscription,
   not a hardcoded 100, and correct waiting-state dates without paid access claim.
4. Verify the real Widget provides payment for THAT agreement/subscription. An
   empty list, `disablePayments=true` or another default agreement is not PASS.
   Payment-method setup missing in LBX is an explicit acceptance limitation,
   not grounds to add approval files or fabricate payment success.
5. Close before payment, return/reload/open two tabs: Continue/Manage preserves
   the same objects. Exercise deterministic loss/concurrency with automated
   transport/PG tests, not destructive live fault injection.
6. HUMAN may perform the agreed safe test payment through LBX's configured method.
   Record observed provider facts separately. Do not claim Kernel paid access is
   implemented by ANY-709; its production background derivation is Steps 8-10.
7. Inspect logs/browser storage/request correlation without publishing JWT or PII.
   Demonstrate a safe unavailable/SDK failure path and recovery; don't disable
   ownership or replay uncertain creates to make the demo green.

### 8.3 Final broad commands - human only, once at the end

The following aliases exist in the inspected main. They are NOT execution-agent
instructions and need the documented local dependencies/test server:

```bash
npm run docs:check
npm run generate:check
npm run architecture:check
npm run typecheck:web
python scripts/repo.py test-db up
npm run test:api
python scripts/repo.py test-db stop
npm --workspace @anytoolai/web run test:components
npm run test:boundaries:web
npm run build:web
# With the intended browser harness running:
npm run test:e2e -- any709-purchase.spec.ts
```

A final owner-selected `npm run check` may replace overlapping broad checks;
do not run both just to duplicate work. Use focused step checks during iteration,
not the entire repository after each tiny edit. User reviews/commits/pushes when
ready. Production migrations/payment actions are never automatic QA commands.

### 8.4 Acceptance ledger

| Result | Evidence needed | Status at implementation closure |
|---|---|---|
| FORMAT_LINT | Recorded step checks and changed-file lint | RECORDED_PASS |
| STEP_1_LINK_PASS | Source-priced local link/preview and automated checks; final real setup separately | IMPLEMENTED_WITH_LOCAL_QA |
| CUSTOMER_WIDGET_PASS | Owner saw real Widget for recovered customer; final multi-user E2E still due | OWNER_QA_OBSERVED |
| PURCHASE_PREPARATION_PASS | Synthetic API/PG coverage; owner request trace reached linked with one subscription | AUTOMATED_PASS; OWNER_REQUEST_OBSERVED; final manual scenario NOT_RUN |
| MAPPED_PURCHASE_WIDGET_PASS | Actual payment-capable Widget for intended agreement | NOT_RUN |
| PAYMENT_PASS / PAYMENT_NOT_RUN | Human-authorized payment or explicit non-execution | NOT_RUN |
| AUTOMATED_REGRESSION_PASS | Recorded step suites; Step 4: 227 component, 38 boundary, 10 synthetic browser | FOCUSED_AUTOMATED_PASS; full final suite NOT_RUN |
| PAID_ACCESS_IN_KERNEL | Program Steps 8-10/11, NOT this ticket | DEFERRED |

Full ANY-709 acceptance requires the implemented product-bound payment path,
not merely customer Widget PASS. An unavailable payment method leaves payment
acceptance incomplete and explicitly owned, not silently treated as success.
Full ANY-504 requires the later paid-access/Kernel execution outcomes too.

## 9. Compact Step 8 handoff - part of Step 4 runbook

Record actual model/enum/API names, safe operation state transitions and lock
order; which tuple uniquely holds customer/product/agreement/subscription scope;
possible-send fence, original +2h deadline and work-item coalescing; callable
read-only recover/escalate interfaces; supported minimal point-read set and
normalization/mismatch/UNKNOWN reasons; accepted price/legal/link history;
provider waiting/date limitations; no grant/trust extension yet; isolated pools/
budgets; safe logs and human recovery/runbook commands. Explicitly state there is
NO running worker/webhook receiver or implemented paid AccessSnapshot here.
ANY-715 builds on the NEW accepted code, not the rejected PR's helper names.

## 10. Source register and bounded research notes

Sources used for decisions, not a request that Codex repeat all reading:

- [S1 - ANY-709 current requirements](https://linear.app/paveldik/issue/ANY-709/7-deliver-normal-lbx-billing-and-widget-flow-and-simplify-product), read 2026-10-26; revision timestamp in 1.1.
- [S2 - ANY-504 program](https://linear.app/paveldik/issue/ANY-504), owner clarification and restored Step 6 history in this conversation. [ANY-664](https://linear.app/paveldik/issue/ANY-664) remains Done; [ANY-715](https://linear.app/paveldik/issue/ANY-715) owns worker/reconciliation.
- [S3 - pinned main](https://github.com/gushinets/payments-portal/tree/dfdc67a9617df1afb5213b0fb831b770e6d816be).
- [S4 - root instructions](https://github.com/gushinets/payments-portal/blob/dfdc67a9617df1afb5213b0fb831b770e6d816be/AGENTS.md), API/web AGENTS and coding conventions: ownership, sync/async, generated contracts, local tooling and English engineering artifacts.
- [S5 - CLI](https://github.com/gushinets/payments-portal/blob/dfdc67a9617df1afb5213b0fb831b770e6d816be/apps/api/app/cli/commercial_mappings.py), [composition](https://github.com/gushinets/payments-portal/blob/dfdc67a9617df1afb5213b0fb831b770e6d816be/apps/api/app/composition/mapping_operator.py), [catalog preview](https://github.com/gushinets/payments-portal/blob/dfdc67a9617df1afb5213b0fb831b770e6d816be/apps/api/app/domains/catalog/preview.py): current manual workflow and active consumers.
- [S6 - existing purchase schema](https://github.com/gushinets/payments-portal/blob/dfdc67a9617df1afb5213b0fb831b770e6d816be/apps/api/app/models/billing_purchase.py), [mapping schema](https://github.com/gushinets/payments-portal/blob/dfdc67a9617df1afb5213b0fb831b770e6d816be/apps/api/app/models/billing_projections.py): reuse/constraint/migration baseline.
- [S7 - LBX client](https://github.com/gushinets/payments-portal/blob/dfdc67a9617df1afb5213b0fb831b770e6d816be/apps/api/app/integrations/lbx/client.py), dto.py and SELECTED_OFFER.md: selected GETs, numeric/date handling and source-input limitations, not new live proof.
- [S8 - external billing design](https://github.com/gushinets/payments-portal/blob/dfdc67a9617df1afb5213b0fb831b770e6d816be/docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md), [Kernel access design](https://github.com/gushinets/payments-portal/blob/dfdc67a9617df1afb5213b0fb831b770e6d816be/docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md), live-source amendment: retained invariants; narrow owner-approved supersession described in 2.8, not blanket rejection of those designs.
- [S9 - root commands](https://github.com/gushinets/payments-portal/blob/dfdc67a9617df1afb5213b0fb831b770e6d816be/package.json), apps/web/package.json, apps/api/pyproject.toml, tests/conftest.py, playwright.config.ts and Compose agent: actual tooling aliases and test isolation.
- Review recheck (2026-10-26): main and the ANY-709 revision in 1.1 are unchanged; PR #143 remains closed/unmerged. Direct rereads additionally covered Settings validators, source provenance, selected-offer proof requirements, stored mapping validation, catalog response fields and Kernel-mock Compose. This is code/document review, not runtime proof.
- Supplied user-create-full-widget-e2e/agreement-23-readonly reports and prior plan: proven provider observations and FORMAT reference only. Earlier stopped-probe gates, recorded-only runtime and old prompts are not inherited requirements.

The authoritative requirements above come from the updated owner/ticket record.
The four-stage decomposition, proposed route/CLI shapes, narrow storage strategy
and focused test grouping are planning choices for approval, not claims they
already exist or have passed testing. The `Europe/Moscow` price calendar is
confirmed and implemented; provider purchase/readback/payment-method readiness
still needs human acceptance. No production launch or Kernel paid access is
inferred from synthetic or customer Widget tests.

## Owner-requested customer repair CLI, 2026-10-26

Superseded by the diagnostic-only scope below; retained as decision history.

The owner authorized a single operator entrypoint that diagnoses from durable
customer/create state and fresh Server GETs, without parsing application logs.
Implement preview by default and explicit apply, plus optional candidate ID for
operator-assisted point verification. Reuse original keys, paired identity,
connection scope and existing binding transitions. Never CREATE/PATCH a provider
customer, mint a Widget credential, delete history, or release UNKNOWN from an
empty search. Missing trustworthy absence evidence remains a manual decision.

Delivery sequence: add scoped snapshots and atomic guarded/audited binding;
compose bounded GET-only recovery; expose through the repository CLI and document
exact commands/results; test previews, candidate/identity conflicts, stale state,
repeated apply, database uniqueness and provider failures with isolated fixtures.
No repair apply against the owner's account is included in this implementation.

## Owner-approved diagnostic simplification, 2026-10-27

Replace the unfinished repair CLI with GET-only `billing-customer diagnose`.
Remove apply/bind/reset paths and their dedicated concurrency/audit machinery.
Read scoped durable state, receipt evidence and stored CREATE failures; query
LBX by stored identity, original key and email without granting ownership from
email. Never scan raw logs or send a diagnostic CREATE. Preserve the independent
QA fixes for customer DTOs, receipt retention, unsent classification and offers.
Persist only allowlisted HTTP/LBX CREATE failure facts on the existing recovery
work item so future diagnoses can explain errors without retaining raw bodies.
The owner explicitly requested verification, superseding the earlier test pause
for this work. Run focused tests, supported canonical checks and a read-only
smoke on the current owner account. Do not create more provider customers.

Completed: diagnostic-only command and runbook delivered; repair-only code/tests
removed. The 23 diagnostic PostgreSQL cases, retained QA regressions and read-only
043 owner smoke passed. See the Step 2 handoff's diagnostic simplification section
for canonical-stage results, corrected negative-test fixtures and skipped browser
E2E. The owner's stored email conflict was identified without changing real data.

## Owner-approved customer ensure flow, 2026-10-27

Implement the explicitly requested account-only find/bind/create/find flow. The
owner rejected indefinite UNKNOWN blocking for account creation and requested a
single reusable CREATE use case plus Sentry reporting for unresolved failure.
Keep original paired identity proof, same user/key/permanent operation, durable
receipt protection and finite active-send leases/CAS fencing for concurrent opens.
One POST per explicit open; after failure only GET recovery in that same request.
A later open may retry after fresh empty discovery once the prior lease is released
or expired. Scope the baseline amendment to customer account bootstrap; do not add
purchase/agreement/subscription runtime or claim all future scenarios exist.

Delivery: update domain send claim/lease lifecycle; expose shared ensure_customer;
report handled integration errors once at the HTTP boundary; update protocol,
PostgreSQL/concurrency and Sentry boundary tests and current architecture/runbook.
Run focused and canonical checks, inspect final diff and record actual evidence.
No commit/push/PR or unrelated data cleanup is included.

Completed: shared discover/create/recover use case, active-send lease/fencing,
sanitized once-only Sentry boundary and diagnostic next actions implemented.
Canonical `npm run check` passed (1,508 API tests, 300 component tests, 38 web
boundary tests and production build). The Step 2 handoff records detailed evidence
and the unperformed live owner-account/browser smoke. No real account reset,
CREATE, container rebuild or commit/push/PR was performed for this change.

## Central LBX Server API error handling (2026-10-27)

Owner-requested correction on checkout `ce93c1177589aa038000afe385816de74847e98f`;
[ANY-709](https://linear.app/paveldik/issue/ANY-709/7-deliver-normal-lbx-billing-and-widget-flow-and-simplify-product),
existing [PR #150](https://github.com/gushinets/payments-portal/pull/150).
No commit or push is authorized for this correction.

Cause: `decode_response` extracted provider reasons but applied its transient
HTTP-status branch before provider rejection, so an actual HTTP 500 erased the
provider failure class. The correction keeps one bounded decoder for every
Server API method, separates safe provider classification from GET retry policy,
and extends existing response facts/logging to HTTP, no-response and transport
failures. Generic 5xx envelopes retain provider classification and bounded GET
retries; the known permanent rejection does not retry. POST never loops.

Delivery checklist:

- [x] Correct the shared decoder and preserve safe codes/reasons/correlation.
- [x] Preserve customer discovery, send fencing, receipts and GET recovery.
- [x] Distinguish provider refusal and unknown CREATE in Portal presentation;
      expose live safe response facts through the existing read-only diagnosis.
- [x] Verify synthetic HTTP/error/privacy matrix, existing customer/Widget
      regressions, PostgreSQL behavior and the broadest supported canonical check.
- [x] Inspect final diff and record actual checks and remaining limitations.


Verified evidence:

- Full canonical check passed with process-only isolation of development Kernel
  settings (no `.env` edits):
  `KERNEL_MOCK_ENABLED=0 KERNEL_BASE_URL= KERNEL_SERVICE_TOKEN= PATH="$PWD/.venv/bin:$PATH" npm run check`.
  Results: 1,422 non-PostgreSQL API tests, 218 PostgreSQL tests, 301 web component
  tests, 38 web boundary tests, production build, TypeScript, Ruff lint/format,
  ESLint, architecture, docs and generated-contract freshness checks passed.
- The final conservative GET retry adjustment for malformed 500 envelopes was
  verified with the same environment and `npm run check:fast` (all stages passed),
  plus `.venv/bin/python -m pytest -q apps/api/tests/test_lbx_error_contract.py
  apps/api/tests/test_lbx_client_errors.py` (142 passed). The new transport matrix
  has 80 cases, including generic and known 500s, 200 error envelopes, auth/rate
  limits, malformed/oversized payloads, multiple endpoint templates, GET/POST
  behavior, partial/no-response failures, correlation and private-text canaries.
- Changed existing regressions were exercised directly:
  `test_any709_step2_customer.py`, `test_any709_step2_failures.py`,
  `test_lbx_client_errors.py`, `test_billing_customer_ensure_boundary.py`,
  `test_billing_customer_diagnostics_cli.py`, plus the customer diagnostics,
  ensure, Step 2 failures and Step 2 PostgreSQL files; the complete canonical
  partitions then passed. The PostgreSQL suite covers a provider returning an
  unknown error after creating the customer: GET recovery binds the same customer
  and allows viewing without another POST. CLI integration uses synthetic LBX
  500s, safe JSON output and the unchanged unsent operation.
- A temporary production web server and Playwright checked all five public
  failure states on desktop (1440x1000) and mobile (390x844), with synthetic API
  interception, keyboard activation, request-ID display, no private-text display,
  no Widget mount on failure, no overflow and no unexpected console/page/network
  errors. Axe WCAG A/AA checks reported zero violations. Screenshots were visually
  inspected. Local evidence (ignored, synthetic fixtures only):
  `.harness/any709-lbx-errors/{desktop.png,mobile.png,results.json}`.
  The temporary server was stopped; the already-running PostgreSQL test server
  was reused.
- `git diff --check` and the correctness/payment-security/UI checklists were
  applied. No generated, legal, database schema, pricing/calendar, Kernel,
  Widget/JWT implementation or purchase-runtime changes were introduced.

Replaced: HTTP-status-first failure classification and loss of response context
on transport failures. Retained: one decoder/HTTP event vocabulary, bounded
admission/retries, private vendor-log suppression, customer discover/create/GET
recovery, send leases/CAS fencing, receipts, read-only diagnosis and single HTTP
failure reporting. Portal adds only `billing_source_rejected`; unresolved CREATE
reuses `billing_customer_pending` and its existing localized presentation.

Limitations: LBX supplies free-form error text, not a proven business-error
catalog, permanence marker, native CREATE idempotency or no-side-effect proof.
Generic 5xx refusals therefore remain provider failures with conservative GET
retries; no error envelope authorizes a blind POST retry. The existing
owner-approved later-explicit-open customer policy remains unchanged.

The normal unisolated check initially exposed development Kernel mock settings
leaking into production-settings/harness negative tests; clearing only the three
Kernel environment values above resolved those unrelated failures. An early
sandbox-only focused ASGI run was interrupted and rerun successfully with local
socket access. Full browser E2E (`RUN_E2E=true`) and live LBX/customer Widget
acceptance were not run; the focused synthetic browser check above is the UI
regression evidence. No real provider call, commit or push was performed.
