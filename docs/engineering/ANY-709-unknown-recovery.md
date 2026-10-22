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
