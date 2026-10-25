# ANY-709 preparation and UNKNOWN recovery

Status: implemented local SIMULATED workflow; human verification pending.

`POST /api/purchases/{id}/continue` resumes the authenticated owner's existing
intent. `GET /api/purchases/{id}` and
`GET /api/billing/products/{product_id}/status` read PostgreSQL only. Product
status returns the owned intent ID so reload can resume the same operation.
Neither status nor `manage` authorizes a Widget credential or paid access.

Every never-sent operation compares the original accepted review through the
existing live Kernel HTTP and recorded LBX selected-offer path. The current
account date must still equal the accepted start date. Missing proof, material
drift, a date rollover or an ineligible user pauses the intent before POST.
Consent and the accepted snapshot are never rewritten.

The committed `unsent -> possible_send` claim owns the one POST permission,
send fence, ownership epoch and fixed two-hour recovery work item. A crash
between that commit and the first packet is still potentially sent. A receipt
alone cannot bind anything: current point GET must prove identity, owner,
seller, correlation and all material subscription terms. Dedicated agreement
identity is bound uniquely before subscription CREATE. The prepared link has
an expired, access-denying projection and no financial-state observation or
allowance. These defaults do not assert a measured provider financial state.

## Operator calls

Use the existing `purchase_application(configuration, factory, sources)`
composition in a controlled operator process on its resource-owning event
loop. Its `preparation` object exposes these deliberately private calls; there
is no public operator HTTP route or background scheduler in this slice:

- `await preparation.advance(user_id, intent_id, read_only=True)` performs only
  discovery/point GETs for previously claimed operations and binds a unique
  complete match. It stops at an unsent stage. No Kernel admission read or
  current profile load is required for recovery.
- `await preparation.inspect(user_id, intent_id)` performs bounded read-only
  discovery for the next unresolved operation, including a manual-review case.
  It returns private typed proof and never binds, sends or releases anything.
- `preparation.escalate_overdue(user_id, intent_id, principal="<audited operator>")`
  synchronously creates/coalesces a manual-review case for an overdue
  `possible_send`/`unknown`, completes its due item and retains the hold. It is
  idempotent. A worker does **not** execute this call yet; Step 8 owns scheduling.

Recovery capacity is separate from new-sale preflight capacity. Commands and
the SIMULATED preparation profile are pinned in the operation recovery
document; no credentials are persisted there. The recording directory must
remain available. Test recordings use fixed provider IDs and explicit opaque
correlation/date substitutions, so they are a single-account scenario fixture,
not a multi-customer provider emulator or production evidence.

Zero discovery results retain UNKNOWN and the original deadline. Multiple,
conflicting or incomplete candidates enter manual review. Network unavailability
retains UNKNOWN. No branch repeats a possibly sent POST, including after
process restart, browser close, source outage or deadline expiry. Definite
pre-send authentication/validation refusal leaves the unsent operation without
a send clock. A definite pre-send failure following a committed claim is
recorded separately and handed to review; it never restores send permission.

## Release and late objects

Use the existing audited `release_purchase_scope` API only with authoritative
no-effect proof, a verified terminal link plus no other unresolved operations,
or explicit audited support evidence. Payment state, elapsed time and empty
discovery are not no-effect proof. An unpaid prepared subscription retains its
hold indefinitely. Support must reconcile all customer/product create records
and retain proof/principal/observation time in the append-only release audit.

A late response must pass the recorded send fence and current hold epoch.
Changed ownership or a conflicting provider binding creates a manual-review
case, retaining evidence and denying progression. A repeated proof of the same
already-bound object is harmless. A late external object discovered after an
audited release requires support review; it cannot become a fresh send,
automatic scope reassignment or paid access.

## Human verification

Tests were written but not executed by the implementation agent. Run from the
repository root:

```bash
make test_db_up
npm run test:api:postgres
npm run test:api:fast
make test_db_stop
```

Focused evidence lives in `apps/api/tests/test_purchase_preparation_postgres.py`
and `apps/api/tests/test_purchase_preparation_contracts.py`: committed claims
before I/O, 200/201 receipts plus point proof, restart, lost commit acknowledgement,
concurrency, zero/one/multiple discovery, drift/date/ownership refusal, explicit
two-hour escalation, DB-only status and expired access-denying links.

## Step 8 handoff

Implementation baseline: `5435ea6f4793c71408736960aa5e6a6c9eadf485` plus the
uncommitted ANY-709 Step 5 changes. No commit, migration, runtime walkthrough or
verification was performed by this implementation agent. Current migration:
`20261021_0003_purchase_scope_fencing`; HTTP OpenAPI service version `0.1.0`;
accepted snapshot schema `v1`; private preparation record
`SIMULATED-purchase-preparation-v1`. Record the final reviewed SHA and human
results before declaring local functional PASS.

The immutable accepted snapshot contains the original request, mapping revision,
Decimal-string recurring/connection/initial money, ISO currency/precision,
component/quantity/period/policy, Kernel metric and allowance, seller
reference/revision, required document version/content/text hashes, explicit
commercial/recurring confirmation, source date/timezone and acceptance time.
`LegalAcceptanceEvent` and `DocumentAcceptance` bind that exact public
fingerprint and document set to this purchase. Current catalog changes never
replace it; original retired legal versions may be used only with matching
immutable document evidence and pinned historical policy.

The one `(user_id, product_id)` `BillingPurchaseScopeHold` remains the business
owner for both an intent and its linked subscription. Step 8 must use that row,
scope → customer → operation lock order, ownership epoch, send fencing and
audited release helpers. It must not introduce a second reservation or release
an unpaid link on a browser timer. The unique `(account, user)` customer slot
retains its original opaque `billing_customer_key`. Every Widget open proves
the current provider `user_id` plus original `outer_id` pair. Identity conflict
requires read-only investigation; changing the key is not repair.

Every dedicated agreement is tied to its proven customer and seller; a unique
account/agreement binding precedes the canonical subscription link. Correlation
keys and provider `outer_id` labels are discovery hints, never provider
idempotency guarantees. Current subscription `services[].price`, multiplicator,
total, period, currency and policy must prove the accepted original terms. The
stored prepared link retains an expired access-denying projection; no payment,
paid trust, allowance, access-primary or Kernel grant is produced here.

Reusable operations and owners:

- `PurchasePreparation.advance(..., read_only=True)` discovers and point-proves
  claimed operations without another POST; `inspect(...)` is read-only evidence;
  `escalate_overdue(..., principal=...)` performs audited due-item escalation.
  These are defined in `apps/api/app/domains/purchases/preparation.py`.
- `claim_external_create`, `bind_external_create` and `release_purchase_scope`
  remain the persistence/fence/release mechanics. The original operation,
  correlation, send fence and fixed `unknown_since + 2h` deadline are reused.
  `BillingWorkItem` coalesces recovery. Zero results or outages retain UNKNOWN;
  multiple/conflicting/incomplete results enter review. Empty discovery,
  payment state or deadline expiry cannot restore send permission.
- `LbxPreparation.prove_customer/prove_agreement/prove_subscription` normalize
  current point reads; `LbxPurchasePreparation.prove/recover` expose typed
  proof/read-only discovery through the existing private gateway. Only an exact
  unique point match may bind. The independent bounded `purchase_io` capacity
  permits Manage/recovery when new-sale Kernel preflight is unavailable.
- `WidgetApplication.authorize` takes `WidgetPrincipal` (authenticated current
  user/session), product and optional owned intent selector. It loads original
  consent and scope/customer/operations, calls the existing subscription proof
  (fresh customer GET → agreement GET → subscription GET), then rechecks local
  session/hold/evidence after I/O. `bootstrap` hands the result to the restricted
  composition issuer. Historical/imported links without provable original
  evidence return not-ready; they never create an intent or invent consent.
- Public DTOs/routes live in `app/domains/purchases/router.py`; generated
  `docs/generated/openapi.json` and web `api-contracts` remain the wire authority.
  Product status returns the held intent ID for reload/lost-reply recovery.
  Continue resumes that same operation. Bootstrap is authenticated POST with
  `no-store`/`no-referrer` on both success and errors, and does not mutate LBX.

Current flags and source labels:

- `PURCHASE_SIMULATED_PROFILE_FILE` explicitly opts into development/test
  recordings. `APP_ENV=production` rejects that composition. `MAPPING_ACCOUNT_ID`
  selects stored approved terms; a URL change cannot upgrade SIMULATED evidence.
  Neither admission nor preparation can reach a real LBX mutation transport.
- Seller organization `21` is only the controlled SIMULATED profile input,
  with reference `SIMULATED:selected-test-seller-not-live-approval`, revision
  `fixture-v1`. Account credential/origin binding and historical applicability
  come from the persisted private profile. No default/live seller is inferred.
  `LBX_SELLER_ORGANIZATION_ID`, if configured, must match the selected profile.
- Successful current bootstrap returns only `mode=SIMULATED`,
  `sdk=isolated_stub`, `widget_origin=self`, both disable-create/edit flags true,
  and a random non-JWT `SIMULATED:` credential. The local SDK has no network,
  payment, paid-access callback or global credential. It validates the local
  handoff, discards it and returns its own documented mount cleanup function.
  No provider teardown method or remote SDK/CSP allowlist is guessed.
- The private HS256 type-7 signer exists, rejects SIMULATED mapping evidence,
  uses current Unix `iat`, and requires dedicated `LBX_WIDGET_SIGNING_SECRET`.
  It is deliberately unreachable from recorded bootstrap. No actual live SDK
  contract/account allowlist or real JWT enablement is claimed. ANY-634 B4/B5's
  accepted 72-hour replay and direct Client API ACL risks remain unchanged;
  logout clears browser memory, not provider credentials already issued.

Local development and human evidence:

Use a disposable, already-migrated **worktree development** PostgreSQL database
and the real HTTP Kernel mock. Inspect the target database before any manual
`npm run migrate:api`; it is a runtime DB command, not pytest's disposable DB.
The removable runner below neither migrates/resets nor starts production. It
requires the existing UID-authorized development/worktree-DB guard, one declared
SIMULATED account and an explicit purchase profile. Fixed provider fixture IDs
permit one simulated purchasing customer in that DB, not multiple live accounts.
Use separate disposable databases for independent fresh walkthroughs.

First follow the standalone Kernel HTTP setup in
[Development](DEVELOPMENT.md#opt-in-inspect-and-publish). For host execution,
export the inspected host `DATABASE_URL`, matching `POSTGRES_DB`, instance scope,
`KERNEL_BASE_URL` and `KERNEL_SERVICE_TOKEN`. Keep service credentials private.
The Kernel URL must reach that running mock over HTTP. Then run from repo root:

```bash
export PATH="$PWD/.venv/bin:$PATH"
export PYTHONPATH=.:apps/api
export APP_ENV=development
export MAPPING_ACCOUNT_ID=simulated-ru-lbx-account
export MAPPING_OPERATOR_UIDS="[$(id -u)]"
export PURCHASE_SIMULATED_PROFILE_FILE="$PWD/tools/purchase_mock/profile.json"
export MAPPING_APPROVAL_FILE="$PWD/.harness/purchase-walkthrough/approval.json"
export MAPPING_SOURCE_INPUTS_FILE="$PWD/.harness/purchase-walkthrough/inputs.json"
export PURCHASE_TRAFFIC_FILE="$PWD/.harness/purchase-walkthrough/traffic.jsonl"
export PURCHASE_TEST_SESSION_TOKEN="$(./.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
export CORS_ALLOW_ORIGINS=http://localhost:3000
export NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
export PLAYWRIGHT_BASE_URL=http://localhost:3000
export PLAYWRIGHT_API_BASE_URL=http://127.0.0.1:8000
export PURCHASE_FLOW_ACCEPTANCE=1
./.venv/bin/python -m apps.api.tests.support.kernel_walkthrough prepare --output-dir .harness/purchase-walkthrough
./.venv/bin/python -m apps.api.tests.support.kernel_walkthrough publish \
  --proposal .harness/purchase-walkthrough/proposal.json --expected-previous-revision 0 \
  > .harness/purchase-walkthrough/publish.json
./.venv/bin/python -m tools.purchase_mock seed-user
./.venv/bin/python -m tools.purchase_mock serve --port 8000 --traffic-file "$PURCHASE_TRAFFIC_FILE"
```

If prior publication exists, inspect its history and choose the reviewed CAS
revision instead of overwriting/resetting it. The seed provisions a clearly
synthetic verified Portal session, not a provider identity or purchase. The
browser starts signed out, installs that test session, then uses actual Portal
HTTP for review/consent/purchase/preparation/status/bootstrap. Regular
registration/login/email verification have their existing independent tests.
Run `npm run dev:web` in a second terminal with the same public API base; run the
browser commands below in a third with the same acceptance variables. Preserve
the append-only method/path traffic file across API restarts; never capture
headers, bodies, responses or tokens. This is isolated local evidence, not a
new runtime monitoring subsystem.

```bash
npm run generate:check
npm run typecheck:web
npm run test:boundaries:web
make test_db_up
npm run test:api:fast
npm run test:api:postgres
make test_db_stop
npm --workspace @anytoolai/web run test:components -- tests/components/PurchaseJourney.test.tsx
npm exec playwright test -- --config playwright.config.ts apps/web/e2e/purchase-flow.spec.ts --project desktop-chromium
npm exec playwright test -- --config playwright.config.ts apps/web/e2e/purchase-flow.spec.ts --project mobile-chromium
npm run check
```

Run the browser projects sequentially against the same fixture customer: the
first may create, the second must reuse the existing held intent. Tests cover
lost real HTTP reply, reload/continue, exact three LBX POST dispatches, repeated
fresh Widget proof, cross-/same-tab logout and late bootstrap suppression,
memory-only credential, keyboard close/focus, mobile/desktop screenshots and
accessibility. API negatives cover owner/customer/seller/material overrides,
missing effective service price, legal/eligibility loss, unresolved CREATE,
logout across proof and concurrent opens during Kernel outage. Component tests
cover double-submit suppression, stable retry keys and unmount/session races.
No PASS is claimed until a human runs them. Record source/outage/restart/negative
results and screenshots, then perform the plan's final human matrix/review.

Evidence ledger: local functional flow **IMPLEMENTED / NOT_VERIFIED**; production
Portal → LBX → Widget **BLOCKED / NOT_VERIFIED**. G1–G4 selected-account,
Kernel/legal/source and authorized full-smoke evidence remain unverified. No
real G2/provider smoke was started. Step 8 consumes these operations for future
scheduled/urgent GET-only recovery, webhook hints, reconciliation, deterministic
transitions and manual-review workflows. Step 9 owns paid grants/allowances;
Step 10 owns Kernel AccessSnapshot/actual usage. No worker, webhook orchestration,
payment proxy, quota runtime or launch integration is implemented here.

Changed-file inventory for this slice (paths relative to the repository root):

- Backend: `apps/api/app/composition/purchases.py`,
  `apps/api/app/core/settings.py`,
  `apps/api/app/domains/purchases/preparation_contracts.py`,
  `apps/api/app/domains/purchases/router.py`,
  `apps/api/app/domains/purchases/service.py`,
  `apps/api/app/domains/purchases/widget.py`,
  `apps/api/app/infrastructure/queries/widget.py`,
  `apps/api/app/integrations/lbx/purchase_preparation.py`,
  `apps/api/app/integrations/lbx/widget.py`, `apps/api/app/main.py`.
- Browser: `apps/web/src/features/purchases/PurchaseJourney.tsx`,
  `apps/web/src/features/purchases/PurchaseJourneyClient.tsx`,
  `apps/web/src/features/purchases/PurchaseReview.tsx`,
  `apps/web/src/features/purchases/simulated-widget-sdk.ts`,
  `apps/web/src/features/purchases/index.ts`,
  `apps/web/src/features/catalog/ProductDetail.tsx`,
  `apps/web/src/shared/api/purchases.ts`, `apps/web/src/shared/api/transport.ts`,
  `apps/web/src/app/catalog.css`, `apps/web/src/app/purchase.css`,
  `apps/web/eslint.config.mjs` (explicit machine-literal additions only).
- Locales: `apps/web/src/messages/de.json`, `en.json`, `es.json`, `fr.json`,
  `it.json`, `pt.json`, `ru.json` in that same directory.
- Generated wire: `docs/generated/openapi.json`,
  `apps/web/src/generated/api-contracts/index.ts`,
  `apps/web/src/generated/api-contracts/types.gen.ts`.
- Tests/harness: `apps/api/tests/test_widget_api_postgres.py`,
  `apps/api/tests/test_widget_jwt.py`,
  `apps/web/tests/components/PurchaseJourney.test.tsx`,
  `apps/web/e2e/purchase-flow.spec.ts`, `tools/purchase_mock/__main__.py`.
- Configuration/docs: `.env.example`, `ARCHITECTURE.md`, `docs/README.md`,
  `docs/SECURITY.md`, `docs/architecture/payment-portal-data-model.md`,
  `docs/engineering/DEVELOPMENT.md`, this handoff/runbook.

## Step 6: explicit local 043 stand (supersedes the recorded-runtime instructions above)

Status: **IMPLEMENTED_NOT_TESTED**. **PUBLIC_SALE_NOT_ENABLED**. No live provider
request, DB migration, test, lint, typecheck, build or browser walkthrough was
performed during implementation. Real Kernel conformance, payments, paid grants,
allowances, access projection and launch remain outside ANY-709. The Kernel
continues to be the separate `tools/kernel_manifest_mock` HTTP service. There
is no running LBX mock in this mode. The original recorded transports and Widget
stub are regression fixtures only (`APP_ENV=test` or the explicitly invoked
`tools.purchase_mock` regression runner); ordinary development rejects them.

Configure the local Portal API with all of the following, after inspecting the
selected **disposable local** DB and test account. These are configuration names,
not secret values:

- `APP_ENV=development`, `LBX043_ENABLED=true`, exact
  `LBX_BASE_URL=https://043.lbxbilling.ru`, `LBX_SELLER_ORGANIZATION_ID=21`.
- `MAPPING_ACCOUNT_ID` and `LBX_EXTERNAL_BILLING_ACCOUNT_ID`: the same explicitly
  reviewed account identifier; `LBX_SERVER_USERNAME`, `LBX_SERVER_PASSWORD` and
  dedicated `LBX_WIDGET_SIGNING_SECRET` supplied privately. No `NEXT_PUBLIC_*`
  signing/server credentials. Never paste credentials into configuration JSON.
- `LBX043_TEST_USER_IDS`: JSON array of verified **Portal** test-user UUIDs, set
  after ordinary registration/login/email confirmation. Registration alone
  never creates an LBX user. `PURCHASE_SIMULATED_PROFILE_FILE` must be unset.
- `PURCHASE_STAND_PROFILE_FILE`: absolute private path to `profile.json`, with
  its sibling `preparation.json`. Copy the nonsecret, intentionally incomplete
  examples in `tools/lbx043/` into private operator files. Replace the account,
  dates, evidenced account timezone, evidence references/revisions and reviewed
  test terms. The example timezone/date placeholders deliberately cannot admit
  a purchase. Keep `profile.selection/inputs` identical to those in preparation;
  the mapping operator's `inputs.json` must contain that same `inputs` object.
- `KERNEL_BASE_URL`, `KERNEL_SERVICE_TOKEN`, and matching private
  `KERNEL_MOCK_TOKEN` for the separate mock. Start it with
  `PYTHONPATH=.:apps/api .venv/bin/python -m tools.kernel_manifest_mock --host 127.0.0.1 --port 8091`.
  Configure the API's Kernel origin to that service. Use `npm run dev:api` and
  `npm run dev:web` for the Portal, with the existing local PostgreSQL server and
  correct host API/CORS origins. Do not start the recorded LBX runner here.
  The existing bounded `PREFLIGHT_TOTAL_TIMEOUT_SECONDS` can be configured for
  the stand's multi-read latency (for example 30 seconds); it is not a provider SLA.

The approved selection is seller **21**, product `proposal_ai`, tariff **32**,
tariff service **1**, period **1**, quantity **1**, `currency_id=1 → RUB`, major
units, scale **2**, recurring **100 RUB/month**, connection **0**. Price record
**288** and period association **82** are evidence references, not POST period
IDs. `LbxCurrencyMapping` pins the currency to this account; the symbol `rub`
alone never proves currency. All LBX/account input evidence must have its actual
`ACCOUNT_EVIDENCE`/`DOCUMENTED` basis. Its commercial source mode remains
`CONFIGURED_SOURCE`; the mock Kernel and test approvals keep the aggregate
mapping **SIMULATED**, never `GENUINE` or public sellability. Do not relabel
recorded inputs as live evidence. No legal text is changed or legally approved.

Use the known evidence in the plan's §8.2; do not repeat provider certification.
Account credit/policy is independently reviewed configuration, not inferred from
`credit=0` or absent `debt_threshold`. Before SUBSCRIPTION POST, the human must
review and document the intended agreement/credit/possible debit effect, set
`LBX043_FINANCIAL_APPROVAL_REFERENCE` to that review, and populate the pinned
`preparation.financial_policy_evidence` with its account-scoped
`ACCOUNT_EVIDENCE` reference/revision. The initial examples leave it null and
leave the switch empty. Complete the financial policy review before the initial
purchase consent: that profile is part of the immutable preparation pin.
Changing it after consent requires manual review of the existing hold, never
an edited snapshot or a second purchase to bypass it. Missing evidence/approval
refuses SUBSCRIPTION POST and JWT; do not enable it speculatively or edit the billing account to make it
pass. Missing/wrong scope/allowlist/production/default configuration refuses
provider POST and JWT. Keep the six SDK disable flags true for this smoke.

### Manual immutable mapping publication (no automatic mapping creation)

Inspect the target DB/environment first. Use the existing OS UID authorization,
`MAPPING_OPERATOR_UIDS`, `MAPPING_OPERATOR_LOCK_FILE` (trusted shared absolute
path), `MAPPING_APPROVAL_FILE` and `MAPPING_SOURCE_INPUTS_FILE`. Prepare the
independently reviewed nonsecret proposal and approval using the existing
`MappingProposal` and `ApprovedMapping` schemas. The technical binding names
`proposal_ai.test_generations` with its independently approved test allowance;
LBX qty 1 does not define that allowance. Preserve SIMULATED test technical/legal
approvals, exact approved material hash and reviewed document references. A
source read cannot create its own approval. No sample approval is auto-generated.

These commands are read from `app.cli.commercial_mappings`' actual parser;
implementation did not execute them. From repository root:

```bash
export PATH="$PWD/.venv/bin:$PATH"
export PYTHONPATH=.:apps/api
python -m app.cli.commercial_mappings --help
python -m app.cli.commercial_mappings query --offer-id selected-offer:v1:32:1:1
python -m app.cli.commercial_mappings dry-run --proposal .harness/lbx043/proposal.json > .harness/lbx043/dry-run.json
```

Before publication compare the private reviewed material to the dry-run material:

```bash
jq -S '.material' "$MAPPING_APPROVAL_FILE" > .harness/lbx043/approved-material.json
jq -S '.evaluation.material' .harness/lbx043/dry-run.json > .harness/lbx043/current-material.json
diff -u .harness/lbx043/approved-material.json .harness/lbx043/current-material.json
jq '.evaluation | {evidence_mode,kernel_provenance,lbx_evidence_mode,material_fingerprint,selection:.material.references,money:.material.terms.money,period:.material.terms.period,quantity:.material.terms.quantity,field_sources}' .harness/lbx043/dry-run.json
```

The diff must be empty, and the displayed evidence must show 32/1/1, price 288,
association 82, 100 RUB/month, 0 connection and qty 1. Inspect the currency input
alongside it for `currency_id=1`, major/2. Kernel and aggregate mapping must be
SIMULATED, LBX `CONFIGURED_SOURCE`. If an identical approved current revision
already exists, reuse it; do not publish again. Otherwise **the human** invokes
publication with the reviewed current CAS revision (0 only for a genuinely empty
scope), then queries the resulting revision:

```bash
python -m app.cli.commercial_mappings publish --proposal .harness/lbx043/proposal.json --expected-previous-revision "$REVIEWED_PREVIOUS_REVISION"
python -m app.cli.commercial_mappings query --offer-id selected-offer:v1:32:1:1
```

Query must show one correct latest revision for `proposal_ai`. Do not alter
Portal price rows. Inspect actual PostgreSQL `commercial_mapping_revisions`:
`mapping_revision_id`, `external_billing_account_id`, `billing_offer_id`,
`revision_number`, `catalog_digest`, `manifest_version`, `published_at`,
`published_by_principal`, and `mapping_document` (material, material fingerprint,
approval pins, Kernel/LBX source labels and field evidence). Retained history
is immutable; the highest scoped revision is current. Query/publish never run
implicitly from registration, purchase, continue or Widget.

### Human registration and real stand walkthrough

On the selected local DB, apply the additive nullable-name migration only after
confirming the DB target. Check no-name, partial-name and full-name registration;
omitted/null/blank fields become NULL, outer whitespace is trimmed, Cyrillic,
Unicode, internal spaces and hyphens survive, and control characters/overlong
values fail. Inspect only the intended `users` row's three nullable fields.
Email confirmation, both existing legal consents and authentication remain
required. No new name fields are returned by session/profile APIs, and no FIO
is required to purchase. Existing users retain NULL without a backfill.

Perform one deliberately authorized Portal-originated real purchase with a
confirmed allowlisted user and reviewed test legal/mapping pins. After review
and consent, continue the held intent once. Expected results:

1. One `purchase_intents` accepted snapshot and scope hold, then a committed
   customer operation/key before HTTP. Customer discovery uses original
   `outer_id`; a new `/users` request has five base fields plus only the actual
   persisted names (5–8 fields). Login/password are CSPRNG request-only values;
   neither credential, nor names, enter recovery JSON or purchase/legal evidence.
2. Customer point GET proves the original user ID/outer pair. Names never bind
   identity; LBX normalization of names does not invalidate that pair. Inspect
   optional name fields in authorized point readback and separately record
   whether the LBX Admin `Client` column displays them. Blank Admin names are
   permitted; the Email column remains usable. No email-to-name substitution,
   user23 adoption, credential repair PATCH or repeated customer CREATE.
3. Owner-wide GET `/agreements` sends `{"user_id":id}` as JSON. The documented
   automatic org9 agreement is ignored. Only an exact original dedicated
   correlation may be reused after owner/seller/unused proof; another org21
   candidate requires review. Otherwise one explicit org21 non-offer agreement
   is created, without `debt_threshold` or invented offer link. Point GET
   tolerates legitimate empty non-offer link; verifies balance/credit/closure.
   Bound/reserved agreement uniqueness remains enforced by PostgreSQL.
4. One explicit 32/1/1 subscription, qty1, balance activation, no manual/demo,
   no `subscription_start_date`. GET proves canonical IDs, owner→agreement→seller,
   actual `services[].price`, exact total100 RUB and no extra service/subscription
   on the dedicated agreement. Waiting/null/sentinel dates are stored under the
   subscription operation's `provider_observation`, verbatim as LBX calendar
   facts; no paid period or UTC/month expiry is synthesized. Financial/access
   projections remain denied/expired. Read back any actual test-account charges
   and compare with the human's preapproved effect.
5. Click Manage deliberately. Each open checks session, original consents,
   current immutable mapping revision, original customer pair, dedicated seller
   agreement, subscription and no UNKNOWN, then signs a fresh HS256/type7 JWT.
   The official script loads from the exact 043 HTTPS origin, with its Client
   API base and all six disable flags true. The data-URL host has an opaque
   origin, CSP and a memory-only MessageChannel; its nested vendor iframe keeps
   the vendor origin. Close/logout/session change removes that entire context;
   no vendor teardown API is invented. Reopen/reload/new idempotency keys must
   not cause any provider POST. Widget display/waiting/balance never grants access.

Before readiness, the UI offers review/continue/status; ambiguous sends keep
`awaiting_external_result`, conflicts require manual review, and a proved linked
waiting subscription offers Manage. Script/auth errors, unproved customer login,
stale mapping, changed effective price, extra services, wrong seller or missing
financial policy must remain not-ready/refused; do not claim Widget PASS from
an empty shell or a failed Client API. Record actual official rendering and
customer/subscription identity in the human evidence ledger. The opaque-host
SDK/CSP behavior and optional-FIO provider normalization still need that browser
acceptance; no provider compatibility is claimed from component fixtures.

Inspect `purchase_intents`, `billing_purchase_scope_holds`,
`external_billing_customers`, `external_create_operations`, and
`external_subscriptions` for exactly the expected owner/account/key, accepted
revision/fingerprint, original correlations, IDs, send fencing/ownership epoch,
state, fixed UNKNOWN deadline and safe recovery document. Never dump secrets,
raw HTTP bodies or whole credentials into evidence. On UNKNOWN, stop outbound
creates and use the existing read-only recovery/inspection with the **same**
operation. An empty discovery or timeout is not resend authority. Matching
identity with missing/unusable Widget credentials requires not-ready/manual
review, never a blind PATCH/CREATE. Do not attempt another purchase to repair it.

### Manual verification commands — all NOT_RUN

From repository root, after normal local dependency setup:

```bash
export PATH="$PWD/.venv/bin:$PATH"
export PYTHONPATH=.:apps/api
npm run generate:check
# Disposable runtime DB only, after inspecting its target:
npm run migrate:api
# Fast registration / wire / private protocol tests:
python -m pytest -p no:cacheprovider apps/api/tests/test_registration_names.py apps/api/tests/test_api_email_verification.py apps/api/tests/test_lbx043_stand.py apps/api/tests/test_lbx_prepare_readback.py apps/api/tests/test_purchase_preparation_contracts.py apps/api/tests/test_widget_jwt.py
make test_db_up
npm run test:api:postgres
make test_db_stop
npm --workspace @anytoolai/web run test:components -- tests/components/AuthForm.test.tsx tests/components/AuthContractValidation.test.ts tests/components/OfficialWidget.test.ts tests/components/PurchaseJourney.test.tsx tests/components/PresentationErrors.test.tsx
npm run lint:web
npm run typecheck:web
npm run build:web
npm run check
```

PostgreSQL coverage includes the new additive migration and the complete local
stand-shaped flow, competing continuations, restart/UNKNOWN recovery, secret
non-persistence and guarded authenticated bootstrap, alongside existing durable
scope/fence regressions. Protocol fixtures use in-process transports only;
there is no fake LBX service or vendor network access in those tests.

After the human purchase above reaches a proved linked test subscription, a
separate **read-only** opt-in browser smoke can open/reopen/close/logout without
purchasing or continuing. Supply the short-lived Portal test session privately
as `LBX043_PORTAL_SESSION_TOKEN`, set the actual local
`PLAYWRIGHT_BASE_URL`/`PLAYWRIGHT_API_BASE_URL`, then run sequentially:

```bash
LBX043_WIDGET_SMOKE=1 npm exec playwright test -- --config playwright.config.ts apps/web/e2e/lbx043-widget.spec.ts --project desktop-chromium
LBX043_WIDGET_SMOKE=1 npm exec playwright test -- --config playwright.config.ts apps/web/e2e/lbx043-widget.spec.ts --project mobile-chromium
```

This spec disables traces/video/screenshots to avoid credential capture; the
operator records sanitized desktop/mobile and accessibility evidence separately.
The spec's rendered-body check is a smoke signal; the human must still confirm
the displayed customer/subscription and absence of Client API auth failure.
Report **STAND_WIDGET_PASS** only with actual authorized Portal-originated 043
proof, org21/32/1/1/100 RUB, correct official rendering, no duplicates, and FIO
readback when supplied. Admin clickable-name visibility is a separate observed
fact. Failed or incomplete evidence is **BLOCKED_WITH_SPECIFIC_REASON**.

Step 8 consumes these same holds, immutable snapshots, operations, observed LBX
facts and read-only recovery for its later webhook/worker/reconciliation work.
Steps 9–10 own paid access/Kernel grants/usage and Step 11 owns launch. This smoke
never substitutes for those gates or grants a 6h LKG extension.

### Step 6 changed-file inventory

The approved implementation plan was already modified when work started and
was left unchanged. The following paths belong to this implementation:

- [`.env.example`](../../.env.example)
- [`apps/api/alembic/versions/20261025_0004_optional_user_names.py`](../../apps/api/alembic/versions/20261025_0004_optional_user_names.py)
- [`apps/api/app/composition/purchases.py`](../../apps/api/app/composition/purchases.py)
- [`apps/api/app/composition/purchase_profiles.py`](../../apps/api/app/composition/purchase_profiles.py)
- [`apps/api/app/core/settings.py`](../../apps/api/app/core/settings.py)
- [`apps/api/app/domains/identity/names.py`](../../apps/api/app/domains/identity/names.py)
- [`apps/api/app/domains/identity/router.py`](../../apps/api/app/domains/identity/router.py)
- [`apps/api/app/domains/identity/services/auth.py`](../../apps/api/app/domains/identity/services/auth.py)
- [`apps/api/app/domains/purchases/contracts.py`](../../apps/api/app/domains/purchases/contracts.py)
- [`apps/api/app/domains/purchases/preparation.py`](../../apps/api/app/domains/purchases/preparation.py)
- [`apps/api/app/domains/purchases/preparation_review.py`](../../apps/api/app/domains/purchases/preparation_review.py)
- [`apps/api/app/domains/purchases/preparation_contracts.py`](../../apps/api/app/domains/purchases/preparation_contracts.py)
- [`apps/api/app/domains/purchases/router.py`](../../apps/api/app/domains/purchases/router.py)
- [`apps/api/app/domains/purchases/service.py`](../../apps/api/app/domains/purchases/service.py)
- [`apps/api/app/domains/purchases/widget.py`](../../apps/api/app/domains/purchases/widget.py)
- [`apps/api/app/http/errors.py`](../../apps/api/app/http/errors.py)
- [`apps/api/app/integrations/lbx/client.py`](../../apps/api/app/integrations/lbx/client.py)
- [`apps/api/app/integrations/lbx/server_session.py`](../../apps/api/app/integrations/lbx/server_session.py)
- [`apps/api/app/integrations/lbx/currency.py`](../../apps/api/app/integrations/lbx/currency.py)
- [`apps/api/app/integrations/lbx/preparation.py`](../../apps/api/app/integrations/lbx/preparation.py)
- [`apps/api/app/integrations/lbx/preparation_dto.py`](../../apps/api/app/integrations/lbx/preparation_dto.py)
- [`apps/api/app/integrations/lbx/preparation_profile.py`](../../apps/api/app/integrations/lbx/preparation_profile.py)
- [`apps/api/app/integrations/lbx/purchase_preparation.py`](../../apps/api/app/integrations/lbx/purchase_preparation.py)
- [`apps/api/app/integrations/lbx/stand.py`](../../apps/api/app/integrations/lbx/stand.py)
- [`apps/api/app/integrations/lbx/widget.py`](../../apps/api/app/integrations/lbx/widget.py)
- [`apps/api/app/models/identity.py`](../../apps/api/app/models/identity.py)
- [`apps/api/tests/support/lbx043.py`](../../apps/api/tests/support/lbx043.py)
- [`apps/api/tests/test_alembic_postgres.py`](../../apps/api/tests/test_alembic_postgres.py)
- [`apps/api/tests/test_api_email_verification.py`](../../apps/api/tests/test_api_email_verification.py)
- [`apps/api/tests/test_lbx043_purchase_postgres.py`](../../apps/api/tests/test_lbx043_purchase_postgres.py)
- [`apps/api/tests/test_lbx043_stand.py`](../../apps/api/tests/test_lbx043_stand.py)
- [`apps/api/tests/test_registration_names.py`](../../apps/api/tests/test_registration_names.py)
- [`apps/api/tests/test_registration_names_postgres.py`](../../apps/api/tests/test_registration_names_postgres.py)
- [`apps/web/e2e/lbx043-widget.spec.ts`](../../apps/web/e2e/lbx043-widget.spec.ts)
- [`apps/web/src/features/purchases/PurchaseJourneyClient.tsx`](../../apps/web/src/features/purchases/PurchaseJourneyClient.tsx)
- [`apps/web/src/features/purchases/official-widget-sdk.ts`](../../apps/web/src/features/purchases/official-widget-sdk.ts)
- [`apps/web/src/generated/api-contracts/types.gen.ts`](../../apps/web/src/generated/api-contracts/types.gen.ts)
- [`apps/web/src/messages/de.json`](../../apps/web/src/messages/de.json)
- [`apps/web/src/messages/en.json`](../../apps/web/src/messages/en.json)
- [`apps/web/src/messages/es.json`](../../apps/web/src/messages/es.json)
- [`apps/web/src/messages/fr.json`](../../apps/web/src/messages/fr.json)
- [`apps/web/src/messages/it.json`](../../apps/web/src/messages/it.json)
- [`apps/web/src/messages/pt.json`](../../apps/web/src/messages/pt.json)
- [`apps/web/src/messages/ru.json`](../../apps/web/src/messages/ru.json)
- [`apps/web/src/shared/api/auth.ts`](../../apps/web/src/shared/api/auth.ts)
- [`apps/web/src/shared/ui/AuthForm.tsx`](../../apps/web/src/shared/ui/AuthForm.tsx)
- [`apps/web/src/shared/ui/auth-errors.ts`](../../apps/web/src/shared/ui/auth-errors.ts)
- [`apps/web/tests/components/AuthContractValidation.test.ts`](../../apps/web/tests/components/AuthContractValidation.test.ts)
- [`apps/web/tests/components/AuthForm.test.tsx`](../../apps/web/tests/components/AuthForm.test.tsx)
- [`apps/web/tests/components/OfficialWidget.test.ts`](../../apps/web/tests/components/OfficialWidget.test.ts)
- [`apps/web/tests/components/PresentationErrors.test.tsx`](../../apps/web/tests/components/PresentationErrors.test.tsx)
- [`docs/architecture/payment-portal-data-model.md`](../../docs/architecture/payment-portal-data-model.md)
- [`docs/engineering/ANY-709-unknown-recovery.md`](../../docs/engineering/ANY-709-unknown-recovery.md)
- [`docs/generated/db-schema.md`](../../docs/generated/db-schema.md)
- [`docs/generated/openapi.json`](../../docs/generated/openapi.json)
- [`tools/lbx043/inputs.example.json`](../../tools/lbx043/inputs.example.json)
- [`tools/lbx043/preparation.example.json`](../../tools/lbx043/preparation.example.json)
- [`tools/lbx043/profile.example.json`](../../tools/lbx043/profile.example.json)
- [`tools/purchase_mock/__main__.py`](../../tools/purchase_mock/__main__.py)

Formatting: `.venv/bin/ruff format` on the 30 changed Python files completed
(16 reformatted, 14 unchanged); subsequent focused formatting after final edits
completed. Existing web style was applied during editing.
`PATH="$PWD/.venv/bin:$PATH" npm run generate` completed and regenerated the
OpenAPI, TypeScript wire and DB schema artifacts. The initial generation attempt
without the repository Python on PATH could not start; it made no generated
changes. No linters or verification commands were run. No files were staged,
committed or pushed.

Architecture-size follow-up: extracted lazy profile loading/fingerprinting to
`composition/purchase_profiles.py`, Server authentication to
`integrations/lbx/server_session.py`, and manual-review/escalation helpers to
`domains/purchases/preparation_review.py`. Existing entry points, transaction
boundaries, session locks, source budgets and send fencing are retained. Ruff
formatting completed for the six affected Python files. Architecture checks,
linters and tests were not run; manually rerun `npm run check`.
