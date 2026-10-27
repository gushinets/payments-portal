# ANY-709 - Normal LBX billing, product mapping and real Widget flow

Status: reviewed execution plan based on owner-approved ANY-709 decisions; NOT IMPLEMENTED
Date: 2026-10-26
Review revision: 2 - inherited-code closure and execution clarifications; no new stages
Program: ANY-504, program Step 7
Delivery: four sequential implementation stages in this file, numbered Step 1-4
Repository destination: `docs/exec-plans/active/ANY-709-implementation-plan.md`

## 0. Execution contract - read for every selected step

**2026-10-27 price-calendar correction:** the owner authorized implementation,
targeted tests, formatting/lint, supported canonical checks and Docker runtime
checks for current-price selection and removal of the timezone setting. LBX
support directly confirmed `Europe/Moscow` and the latest-start-date rule for
both price methods. This narrow correction does not authorize LBX writes,
Steps 3-4, stage/commit/push or remote ticket/PR changes. Earlier execution
restrictions below describe the original stage deliveries.

**2026-10-26 manual-QA exception:** for the two reported Steps 1–2 defects,
the owner explicitly authorized local diagnostics/tests/application/containers,
test-043 reads and synthetic customer verification, and separately a second
synthetic customer. This exception does not authorize production, payment,
agreement/subscription creation, Steps 3–4 or stage/commit/push/PR/Linear writes.
Actual results and unresolved acceptance are recorded in the existing Step 1–2
handoffs; the earlier authoring-only restrictions below remain historical for
that original delivery.

This is a NEW plan from current `main`, not an addendum to the rejected plan.
ANY-664 / program Step 6 remains completed. Its accepted delivery and history are
not rewritten. Necessary changes to that code belong to THIS ANY-709 delivery.
PR #143 is closed without merge and was not accepted. Do not merge/cherry-pick
that whole branch, treat its six stages as completed prerequisites, or use its
old instructions as authority. Reuse a relevant implementation/test fragment
only after checking it against this plan and the current code.

Implement ONE selected step, then stop for owner verification/review. Do not
implement later steps automatically. Read sections 0-3, the selected step in
full, applicable AGENTS instructions and its direct current dependencies. Read
preceding-step interfaces/handoffs when required, not all other step prompts.
The owner-approved ticket decisions below supersede the specifically identified
old requirements; this is not permission to redesign unrelated architecture.
The inherited gates named in Step 1 are EXPECTED remediation work, not a new
contradiction that requires stopping for permission. Concrete implementation
layout stays with the executor; another architecture/evidence framework does not.

### Codex may execute

- Read-only code/diff/history inspection and implementation-required file writes.
- Formatting and linting of changed code; fix in-scope findings.
- `npm run generate` when Pydantic/OpenAPI/generated TypeScript or other owned
  generated artifacts change. This is a necessary WRITE, not a test run. Never
  hand-edit generated artifacts. Generation must not contact LBX or run migrations.
- Read-only `git status` / `git diff`; `git diff --check` as whitespace lint.

### Codex must NOT execute

Tests of any kind, pytest collection, Vitest, Node tests, Playwright, browser
smokes, application/live-LBX probes, migrations, builds, typechecks, security
scanners, `npm run check`, `check:fast`, `docs:check`, `architecture:check`, or
`generate:check`. Do not start/restart containers or run `repo:up`, `repo:setup`
or `repo:reset`. Do not use a formatter/linter wrapper that secretly runs tests.
Do not stage, commit, push, change remote tickets, alter LBX records, or fill real
secrets. The human owns environment setup, migrations, test execution and E2E.

WRITE meaningful tests in every step; NOT running them does not mean omitting
them. Report them as `NOT_RUN`. Final step status is
`IMPLEMENTED_AWAITING_HUMAN_VALIDATION`, never a fabricated PASS. Respect the
owner's execution restriction over broader repository instructions to run all
checks. Do not repeatedly seek permission to implement the already-selected
step; stop only for a concrete material contradiction or nonrecoverable blocker.

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

Report changed files; observable result; migrations and generation performed;
format/lint commands with actual outcomes; tests written but NOT_RUN; exact
human commands and expected result; remaining scope/real external prerequisites.
Do not narrate intermediate investigation. Keep delivery notes short and tied to
the selected step. Do not hide an incomplete result behind a green linter.
Include a short removed/replaced/retained summary for the inherited paths touched by this step;
this belongs in the handoff, not a new approval file. Report focused commands for
changed EXISTING regression tests too, not only new any709_stepN tests. Do not
rename unrelated tests or run the entire repository after every edit.

## 1. Evidence, baseline and scope

### 1.1 Pinned baseline

- Current `main` inspected: `dfdc67a9617df1afb5213b0fb831b770e6d816be`.
- ANY-709 inspected revision: `updatedAt=2026-10-26T02:28:22.122Z`.
- ANY-504 / ANY-709 owner decisions: Step 6 unchanged as history; all corrective
  implementation and narrow documentation alignment belong to program Step 7.
- PR #139 / ANY-664 is merged. PR #143 rejected reference:
  `7e24f7344615ba7877e211471d6bec63ffced2f6`, not the execution base.
- If `main` advances, preserve unrelated merged changes. Check only the relevant
  delta; do not reset to this SHA or restart the entire program research.
- This plan was prepared by reading code, tickets and supplied reports. No repo
  tests, migrations, live provider calls or browser acceptance ran during planning.

Existing main contains source clients, restricted mapping publication, catalog,
identity/legal flows and target billing MODEL TABLES. It does NOT contain the
rejected PR's complete purchase runtime. Schema presence is not working runtime.

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

Read retries are bounded. Business CREATE is not sent through the GET retry loop:
no automatic POST reauth/replay after possible dispatch, timeout, HTTP 5xx or
ambiguous success. Distinguish definite before-send failure from uncertain send.
Valid 200/201 responses and valid body IDs are parsed per operation, then point
verified. Malformed success can mean an object exists; it is not a safe retry.
Keep request status/recovery capacity separate from saturated new-offer reads.

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
| `POST /api/billing/widget-bootstrap` | Explicit ensure-customer + safe JWT; optional Portal purchase reference enables verified payment presentation. |
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

| Plan step | Runnable result after implementation + human setup | Main validation focus |
|---|---|---|
| 1 | Normal LBX connection, direct CLI link and source-backed catalog | No file gates; links/history/current prices; safe migration and startup wiring |
| 2 | Existing/new verified user opens REAL customer Widget without a subscription | One customer, credentials/JWT lifecycle, optional FIO, errors and concurrency |
| 3 | Purchase APIs safely prepare the chosen real subscription and can authorize payment presentation | Consent, scopes/fences, agreement/subscription proof, retries/UNKNOWN |
| 4 | Ordinary user UI completes Buy/Continue/Manage and payment-capable Widget | End-to-end intent, actual payment target, reload/logout/error UX, final handoff |

All four are new delivery stages and start `TODO`. No separate research-only or
formatting-only step. Source changes and migrations are validated in their own
stage; do not defer missing startup wiring or customer identity to Step 4.

Human focused Python commands below use the existing test wrappers and pytest's
`PYTEST_ADDOPTS=-k` filtering. Add the proposed `any709_stepN` filename/test-name
prefixes or report exact equivalent commands for actual names. A zero selected
or entirely skipped run is NOT PASS. For PostgreSQL, the canonical wrapper sets
the isolated worktree test environment; direct pytest without the safe test URL
can skip DB tests. Never use the development application DB as a pytest target.

## 4. Step 1 - Ordinary connection, simple product link and current offers

Status: TODO
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

Status: IMPLEMENTED_AWAITING_HUMAN_VALIDATION
Handoff: [Step 2 delivery](ANY-709-step-2-handoff.md). Tests and runtime acceptance NOT_RUN.
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
4. Recognize operation-specific response status/body and point-read user identity
   before binding. After possible-send failure/crash, only bounded GET/discovery;
   no blind POST replay. Save original 2h deadline/work item at send claim and
   provide callable overdue escalation/read-only recovery for later Step 8.
   No scheduler is started now. A bound customer is reused by both widgets and
   the later purchase flow, not recreated per product.
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

Status: TODO
Depends on: human-accepted Steps 1-2; reuse their link/offer and customer services.

### Result and changed surfaces

Through the new Portal APIs a confirmed purchase results in exactly the chosen
prepared subscription and payment-capable bootstrap, or a precise safe pending/
conflict state. This step is independently reviewable at API/DB/protocol level;
the complete browser Buy/Continue/Manage presentation follows in Step 4.

Modify new focused purchase application/routes/contracts; existing legal models/
services; purchase/operation/subscription models and scope queries/persistence;
existing LBX client plus narrow agreement/subscription DTO/normalizers; bootstrap
payment eligibility, migrations and Step 8 recovery seam. Do not implement a
parallel provider state machine or scheduler.

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
5. `advance` is bounded and resumes one pipeline: ensure customer; discover/check
   relevant existing bindings/operations; prepare dedicated agreement; prepare
   selected subscription; authoritative readback; persist proven link. Before a
   previously UNSENT financial preparation resumes after a pause/restart/deadline,
   freshly revalidate the ORIGINAL accepted terms; reuse a read only within the
   current bounded operation, never across an expired preflight. No repricing or
   fresh new-sale admission for UNKNOWN/read-only recovery. Customer-only ensure
   does not acquire a commercial prerequisite. Source reads cannot make later
   provider CREATE atomic, so final effective-subscription readback still matters.
   No HTTP while holding a DB transaction and no duplicate send after a crash.
6. For an existing customer, use documented scoped inventory plus point proofs and
   local nonterminal/UNKNOWN scopes before admitting another relevant create.
   No list ordering, pagination guesses, whole-account scans or "zero -> retry".
   A foreign default agreement is not the chosen purchase agreement. Recover
   only a dedicated agreement whose origin/purpose/owner/seller are proven.
7. Extend the same typed REAL LBX client for agreement/subscription commands and
   reads. Preserve documented JSON filter transport and operation-specific 200/
   201 semantics. Do not reuse a GET retry wrapper for a POST. Every possible
   send has durable identity/fence/deadline first. Full safe request shape, not
   secrets, is recoverable for noncredential creates.
8. Agreement request: proven user ID, explicit configured organization, durable
   unique number/correlation and documented create fields. Use supported non-offer
   form where the accepted evidence calls for it; empty agreement_link is not an
   error by itself. Creation date is a provider-required contract field, not a
   purchased period; derive it from the documented configured billing calendar
   only if needed, never from an operator-written per-purchase profile. Do not
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
12. Extend bootstrap payment eligibility: original owned accepted purchase and
    effective readback choose payment-capable flags. Existing Manage does not
    require fresh new-sale approval, current mapping head equality or today's
    catalog price. Unknown customer identity blocks all JWT; a purchase-only
    issue does not fabricate successful payment or prevent safe account viewing.
13. Deliver request-driven read-only recovery and callable overdue escalation,
    plus one bounded authorized operator inspect/recover entry point using the
    same application functions. Do not add a UI for support or arbitrary force-
    bind/grant commands. Document held scopes and evidence for safe release;
    do not implement an unproved absence predicate. Save Step 8 handoff details.

### State and failure matrix to implement

| Situation | Required behavior |
|---|---|
| New free product scope; fresh offer/consent match | One immutable accepted intent; at most one potentially sent CREATE of each intended object. |
| Same request repeated / two different keys | Return same intent or occupied scope; never create another subscription. |
| Price changes before accepted intent | Fresh review/terms_changed; no provider financial object created at unaccepted price. |
| Accepted intent, no agreement/subscription may have been sent, terms now differ | Mark safe not-prepared/needs-new-consent outcome without rewriting acceptance; new accepted attempt only after safe hold resolution. Keep the shared customer. |
| Agreement/subscription may already exist when terms differ | Keep hold; recover and verify original operation; conflict/manual review rather than silent replacement/repricing. |
| Success body is missing/invalid, post-send 5xx, timeout, crash | UNKNOWN, original deadline and hold; GET-only recovery. |
| Discovery zero / multiple / one fully proven | Pending / review / bind existing object. No count alone authorizes a retry. |
| Deadline reaches +2h | Escalate to review; do not release scope or retransmit. |
| Old worker/response arrives after fence changed | Reject stale apply; retain newer result and safe holds. |
| Prepared unpaid subscription and page abandoned | Same intent/subscription remains resumable without checkout TTL. |
| Current catalog price changed, old effective subscription unchanged | Historical Manage/readback can succeed using original consent. |
| User switched/logged out during preparation/bootstrap | No wrong-user result/JWT; recorded operation remains safely recoverable. |

### Tests to write (not run)

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

### Human verification and review checkpoint

```bash
PYTEST_ADDOPTS='-k any709_step3' npm run test:api:fast
python scripts/repo.py test-db up
PYTEST_ADDOPTS='-k any709_step3' npm run test:api:postgres
python scripts/repo.py test-db stop
```

After migration in the intended local environment, the HUMAN may use the named
Portal API/Swagger to review and explicitly confirm one test purchase. Use a
verified user/current product link, not a manually assigned research user ID.
Record intent/operation IDs and sanitized provider bindings; inspect that there
is one proper seller agreement and one correct subscription, no paid grant and
no repeat CREATE. SDK payment presentation may be inspected here; no payment is
sent by the implementation agent. Report precise provider errors if live
org21/tariff32 behavior differs, rather than adding global approval flags.

### AI prompt

> Implement ONLY Step 3 from human-accepted Steps 1-2. Read sections 0-3, this
> step and direct purchase/legal/model/LBX interfaces. Preserve the prepared-
> unpaid-subscription-before-payment design. Build review/confirmation/current/
> status/advance APIs, one immutable accepted snapshot and legal event, one held
> product scope and the shared durable customer/agreement/subscription operation
> mechanism. Use real documented requests, explicit configured seller and selected
> service/period, then authoritative effective-term readback. Save send fences and
> original 2h escalation before a possible POST. Never blind-repeat, reprice
> accepted meaning, release uncertainty on zero matches/time, or mint payment
> presentation from unproven binding. Customer-only account entry stays separate.
> Implement bounded GET-only recovery/operator inspection and Step 8 seam, not
> its worker or paid access. Write the focused tests/forward migrations/generated
> contracts and safe manual API/SQL instructions. Execute only section 0 allowed
> format/lint/generation commands. No tests/live mutations/migrations/builds or
> stage/commit/push. Stop with a concrete API-level checkpoint for the owner.

## 7. Step 4 - Complete Buy, Continue and Manage UI; final acceptance handoff

Status: TODO
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
7. Finish accessible desktop/mobile Bundle 3 presentation, localization and
   diagnostic correlation. Keep frontend wire DTOs generated and transport-
   owned; no second handwritten runtime schema or broad auth/error redesign.
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

### Tests to write (not run)

`any709-step4.test.tsx`: guest/verified flow, fresh review, double click, terms
changed, return unpaid, Manage with old link, script failure, wrong-user late
response, no secrets and truthful payment/access status.

`apps/web/e2e/any709-purchase.spec.ts`: desktop/mobile interaction and failure
states. Automated SDK/network substitutions are explicitly test-scoped and
must not mutate LBX or grant access. Separate this from the HUMAN real-LBX
acceptance; a mocked browser suite is not real Widget/payment evidence.

Extend backend contract/diagnostic regressions only where this step changes them;
keep test grouping `any709_step4` for focused manual runs. Run no test commands.

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

> Implement ONLY Step 4 using the accepted Steps 1-3 contracts. Read sections
> 0-3, this step and directly affected frontend/API/session/SDK code. Complete
> ordinary Details, live review/consent, Buy, Continue and Manage with the real
> configured Widget and verified intended payment agreement. Reuse one customer,
> one accepted purchase/scope and one SDK lifecycle; handle reload, races, changed
> price, UNKNOWN, source failure and logout without duplicate CREATE or fake
> access. Keep client-contract generation, localization, Bundle 3 and privacy.
> Write focused component/browser tests using test-only substitutions. Finalize
> the one runbook, read-only SQL, narrow docs/guard corrections and Step 8 handoff.
> Do not turn payment callbacks into paid authority or implement workers/Kernel
> access. Follow section 0: formatting/lint and necessary generation only, NO
> tests/browser/live payment/migrations/builds/typechecks or stage/commit/push.
> Report implementation status, NOT_RUN checks and exact human acceptance steps;
> do not claim full E2E on the basis of a stub or empty Widget.

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

| Result | Evidence needed | Initial state |
|---|---|---|
| FORMAT_LINT | Actual per-step commands/outcomes, not a code-review guess | NOT_RUN |
| STEP_1_LINK_PASS | Tests, normal configuration, direct live link/query, honest catalog and all inherited ANY-664 closure rows | NOT_RUN |
| CUSTOMER_WIDGET_PASS | Normal Portal, existing/new user, actual SDK/Client identity, no duplicate customer | NOT_RUN |
| PURCHASE_PREPARATION_PASS | Correct consent, one intent/dedicated agreement/subscription, actual readback and retry safety | NOT_RUN |
| MAPPED_PURCHASE_WIDGET_PASS | Actual prepared intended subscription and usable correct-agreement payment UI | NOT_RUN |
| PAYMENT_PASS / PAYMENT_NOT_RUN | Human-authorized actual test-payment observation, or honest explicit non-execution | NOT_RUN |
| AUTOMATED_REGRESSION_PASS | Human/CI suites against final SHA, with meaningful selected tests | NOT_RUN |
| PAID_ACCESS_IN_KERNEL | Program Steps 8-10 / Step 11, NOT this ticket's implementation claim | DEFERRED |

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
already exist or have passed testing. Unknown account/calendar/payment-method
facts are explicitly separated from evidence. No test, production enablement or
future Kernel functionality is inferred from a successful document review.

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
