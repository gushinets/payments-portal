# ANY-709 - Normal LBX billing, product mapping and Widget flow

Status: IMPLEMENTED_AND_TESTED - Steps 1-4 and owner payment QA complete; independent final review pending
Completed: 2026-10-27
Program: ANY-504, Step 7
Issue: [ANY-709](https://linear.app/paveldik/issue/ANY-709)

## Goal and delivered scenario

Provide an ordinary LBX-backed purchase journey without per-user operator setup
or approval files. The operator configures the connection and links a Kernel
product to an LBX offer. A verified user can open account billing, review current
terms, accept them, prepare one purchase and open its payment-capable Widget.
Reload, another tab and lost responses preserve the same purchase. Manage uses
its original binding and accepted terms after catalog prices or links change.

All four implementation steps are complete. The owner completed the real test
Widget/YooKassa payment to the intended agreement; the agent verified the same
purchase, ownership, terms, balance/history and explicit refresh. Independent
review of the final code remains pending. Production enablement and paid access
belong to later program steps and are not acceptance claims here.

## Current acceptance and final review

This section and the current runbook status supersede historical checkpoint
limitations below; an earlier NOT_RUN is not the current payment result.

- `CUSTOMER_WIDGET_PASS`: authenticated real test customer, account viewing
  without a subscription, repeat opening and the canonical customer binding.
- `PURCHASE_PREPARATION_PASS`: one held accepted `proposal_ai` purchase, original
  commercial/legal evidence, dedicated agreement 32/seller 21/subscription 31.
  Read-only source proof confirms the original 100 RUB/month terms and owner.
- `MAPPED_PURCHASE_WIDGET_PASS`: the owner selected the intended agreement and
  completed its payment-capable Widget checkout with a configured method.
- `PAYMENT_PASS` (owner-run test): YooKassa credited 100 RUB to that agreement;
  supplied admin/history screenshots distinguish it from the prior admin credit.
  The source balance became 100 RUB after the earlier subscription charge.
- `PAID_ACCESS_NOT_IMPLEMENTED`: program Steps 8-10/launch remain deferred.
- Automated final-head evidence for `9d795b5`: 1,439 fast API, 267 PostgreSQL,
  354 component and 38 boundary tests; CI passed 238 main browser cases and four
  React-runtime cases. Two conditional live-source browser cases were skipped,
  not counted as PASS. Real Kernel producer conformance is ANY-711 and does not
  block the accepted local technical mock plus real LBX scenario.
- The owner requested closure of all remaining work except independent review.
  SDK readiness/diagnostics and the new failure/retry checks passed as recorded
  below; the `9d795b5` totals above remain predecessor evidence.
- Independent final review and human merge approval remain pending; neither
  CodeQL/Sonar results nor author self-review substitutes for that review.

### SDK readiness correction

The old host sent `mounted` immediately after SDK `render()`, although SDK 0.0.1
waits asynchronously for its nested Widget READY message. A vendor READY timeout
could therefore escape the Portal's correlated error presentation.

The host now observes the existing `lbx-widget`/`READY` message only from the
actual nested Widget window at the configured provider origin. The 20-second
deadline remains active after `render()` returns. A failure disposes the host,
shows the localized error and bootstrap request ID, and reports only a closed
failure reason/stage/request ID to the console and optional sanitized Sentry.
It never reads the third-party frame document, forwards payment events or
derives paid access. A valid READY cancels the loading deadline, so an active
checkout is not replaced by a timer. Explicit retry rechecks the same purchase.

Read-only public SDK verification on 2026-10-27: 9,683 bytes, SHA-256
`b1df87ef0e28223d078876e1174f34c9cfb6d242bc3098588636e50402b14b1b`,
unchanged from the prior inspection. This is readiness evidence, not a supported
payment-completed callback or guaranteed success of later vendor API requests.

Readiness verification:

- All 359 frontend component tests passed, including the new host/READY timeout,
  late-session, one-error-per-opening and sanitized console/Sentry cases. The
  first focused set passed all 70 tests. Logs: `/tmp/ANY709-dod-all-components.log`
  and `/tmp/ANY709-dod-components.log`.
- All 14 purchase/Widget desktop/mobile browser cases passed on the rebuilt
  production preview with zero retries/skips. A correct-origin sibling frame
  and a host-generated READY cannot cancel the selected Widget's deadline.
  Missing READY yields one safe correlated error and removes the old frame;
  explicit retry uses the same purchase, with no confirm/advance. Successful
  READY survives a clock advance past the deadline. Error/retry screenshots
  were inspected; axe found zero serious/critical violations and no horizontal
  overflow. Log: `/tmp/ANY709-dod-final-browser.log`.
- The first browser run passed 13/14: one inherited UNKNOWN scenario timed out
  before its session fixture replies reached the browser. The trace shows
  aborted session requests before any SDK opening. The complete unchanged
  suite passed on the separate rerun above; no timeout/assertion was weakened.
- Lint, TypeScript and documentation checks passed. The initial TypeScript run
  exposed two missing `type: undefined` fields in new Sentry test inputs; those
  fixtures were corrected and the full typecheck passed.
- Normal `repo:up -- --reuse` rebuilt the preview while preserving its DB/ports.
  In the authenticated visible browser, the real official SDK loaded the same
  purchase and agreement with balance 100 RUB, and remained mounted beyond the
  deadline without a Portal loading error. Screenshot:
  `/tmp/any709-dod/live-ready.png`. Nested-frame keyboard automation still has
  the recorded focus-root limitation; it is not counted as a new payment check.
- The full canonical verification command is
  `KERNEL_MOCK_ENABLED=0 KERNEL_BASE_URL= KERNEL_SERVICE_TOKEN= PATH="$PWD/.venv/bin:$PATH" npm run check`;
  log `/tmp/ANY709-dod-check.log`. It passed 1,439 fast API tests, all 267
  PostgreSQL tests, 359 component tests, 38 boundary tests, docs/generation/
  architecture/Ruff/lint and the production web build. This uses the isolated
  test DB, not the app DB. Its full harness browser command was skipped; the
  separate 14-case browser run above supplies this follow-up's affected journeys.
  After a message-selection readability cleanup, all eight Sentry tests and web
  lint passed again. Final-head remote CI outcomes are recorded on PR #150.

DoD ownership: D1-D5 are implemented with direct-link/source/configuration
regressions and reconciled current documentation; D6 has automated registration,
optional-name/session/concurrency coverage plus real existing-customer Widget
evidence; D7 has original source proof and the owner payment; D8 has synthetic
fault/history/migration coverage; D9 now includes the real SDK readiness gap and
its safe correlated failure checks. D10's independent final review is the
remaining acceptance item. All optional-name variants and destructive fault
cases were tested synthetically, not repeated as live LBX financial writes.

## Independent review remediation, 2026-10-28

Scope: the owner authorized fixes for the two findings against `34845fd` in
PR #150. The remote HEAD was rechecked and remains
`34845fdddde870e7201735e20ae8f6af7f563cde` before publication. The earlier
acceptance and CI totals remain evidence for that predecessor; CI must rerun
on the remediation commit.

1. Return an authenticated exact accepted-request replay without the user-row
   mutation lock. Keep the locked idempotency/scope recheck for new acceptance.
   Interpret only the user-lock PostgreSQL `55P03` result as temporary
   `503 billing_busy`, preserving transaction rollback and request correlation.
   Do not retry provider commands or reinterpret ambiguous database errors.
2. Keep the existing billing POST deadline active through successful/error-body
   consumption. Clear it only after the whole response operation settles.
3. Add deterministic PostgreSQL/HTTP regressions for locked replay, new-request
   contention, rollback and same-key recovery, plus delayed-body deadline tests.
   Rerun focused tests, the broadest supported canonical checks and the affected
   synthetic desktop/mobile journeys. Record actual results below.

Commercial/legal snapshots, customer/financial identities, scope holds, Widget
authorization and paid-access boundaries remain unchanged. No migration, real
LBX CREATE, payment or deployment is part of this remediation. Commit, push and
PR-description alignment are authorized delivery steps after verification.

Verification for the remediation:

- Before the production fixes, both new PostgreSQL/HTTP regressions reproduced
  `500` under a held user lock; eight new delayed-body cases reproduced the
  missing timeout. Logs: `/tmp/pr150-fix-pg-baseline.log` and
  `/tmp/pr150-fix-web-baseline.log`.
- The focused PostgreSQL purchase/contention run passed 28 tests. The lock and
  Widget error-boundary run passed 15 tests, including reserve/final-session
  contention without reclassifying it as an external integration failure.
  Logs: `/tmp/pr150-fix-pg-focused.log` and `/tmp/pr150-fix-lock-unit-host.log`.
- The canonical `npm run check` passed docs, generation, architecture,
  Ruff formatting/lint, 38 frontend boundary tests, all 370 component tests,
  web lint, all 1,447 fast API tests, the production web build and all 269
  PostgreSQL tests (480.54 seconds). Log: `/tmp/pr150-fix-check-final.log`.
  It uses the isolated `_pr150fix_tests` database, with Kernel mock/base/token
  configuration disabled. The app database is not a test target. The canonical
  full harness browser suite was skipped because `RUN_E2E` was unset; the
  affected synthetic journeys were checked separately below.
- `npm run typecheck:web` passed. Log: `/tmp/pr150-fix-typecheck.log`.
- A focused recheck after the work interruption passed 19 backend/PostgreSQL
  tests and 41 frontend tests, including held-lock HTTP replay/refusal, both
  20-confirmation concurrency cases, delayed-body deadlines and explicit
  same-key UI retry. No further code changes were needed. Logs:
  `/tmp/pr150-recheck-api.log` and `/tmp/pr150-recheck-web.log`.
- All 14 `any709-purchase.spec.ts` browser cases passed on an independent
  production preview at port 41351, desktop and mobile, with zero retries/skips.
  API/SDK substitutions stayed synthetic. Buy/Continue/Manage, preparation
  beyond five seconds, UNKNOWN recovery, selected-purchase bootstrap, READY
  timeout/retry and session teardown remained valid. Axe reported no
  serious/critical violations in the covered views; desktop/mobile prepared and
  cabinet screenshots were inspected. The temporary preview was stopped.
  Log: `/tmp/pr150-fix-browser.log`; screenshots/report: `.harness/playwright-results/`.
- Local installed Next is `16.3.1`, while the lockfile declares `16.4.2`.
  These results do not replace a clean locked CI run on a future patched HEAD.
  No fresh real-LBX CREATE/payment or paid-access acceptance is claimed.

## Retained decisions and boundaries

- Kernel owns enabled products; LBX owns current offers and commercial facts.
  Publication/new purchase use live reads. PostgreSQL retains versioned links,
  accepted terms, consent and operation history; there is no catalog mirror or
  price-age gate. Price changes do not require republishing the product link.
- Product links identify tariff/service/period, not a frozen current price.
  Price selection uses one captured `Europe/Moscow` date, latest applicable
  inclusive start and matching inline/dedicated evidence. Money is exact;
  missing/conflicting facts fail closed and nonempty discounts are unsupported.
- Runtime and CLI share a server-resolved connection scope, stable through
  credential rotation. Preserve proven legacy scope and immutable history;
  never guess an origin, adopt ambiguous objects or promote synthetic evidence.
- Customer ensure is discover -> at most one CREATE per explicit opening ->
  GET recovery. A later separate opening may search/retry after its finite
  send lease clears. The same customer key, slot, receipts and operation survive.
- Financial CREATE has a stricter policy: possible send, timeout, lost response
  or error retains the operation and purchase hold; recovery is GET-only.
  Empty discovery or expiry of the original `unknown_since + 2h` deadline never
  permits another CREATE. Only completed typed no-send evidence allows a later
  explicit advance of the same immutable request/key/deadline with a fresh fence.
  Fences reject stale completion; provider I/O stays
  outside short database transactions.
- Acceptance freezes exact commercial/legal terms and link revision. The server
  rechecks fingerprint, current link and legal versions; a changed offer requires
  review. One user/product hold retains linked unpaid purchases. Financial
  identities and dedicated agreement/subscription bindings are permanent.
- One official SDK lifecycle supports read-only account and verified purchase
  payment presentations. Server-side point reads prove ownership, original
  terms and intended agreement/seller before payment bootstrap. Browser IDs,
  callbacks, local status GETs and SDK flags are not authorization evidence.
- Widget JWT is customer-wide: presentation flags are not product/agreement ACL,
  and logout/remint does not revoke a copied token. No invented provider filter,
  token revocation or default-agreement adoption is claimed.
- The product surface remains `ru`, with existing localization and Bundle 3.
  Backend schemas own generated web contracts. Tokens/private provider fields
  stay out of logs and browser persistence. Legal content remains draft.
- Paid access never follows from payment state, browser return or Widget alone.
  Direct-provider runtime and Portal-owned commercial authority stay removed.

## Step 1: Connection, product links and current offers

- [x] Normal LBX/Kernel deployment configuration and independent provenance.
- [x] One privileged direct-link CLI with revision/CAS and immutable history.
- [x] Enabled Kernel product discovery and live selected LBX current offers.
- [x] Remove approval files, manual account IDs and price-republication gates.

Evidence: [condensed Step 1 report](ANY-709-step-1-handoff.md).

## Step 2: Customer and account Widget

- [x] Optional independent first name, surname and patronymic.
- [x] Verified explicit account opening ensures one customer; ordinary auth/GET
  does not create billing objects and needs no subscription or product link.
- [x] Durable receipts, send leases/fences, shared ensure and read-only diagnosis.
- [x] Fresh Widget JWT, session-safe SDK teardown and safe localized errors.

Evidence: [condensed Step 2 report](ANY-709-step-2-handoff.md).

## Step 3: Accepted purchase and financial recovery

- [x] Review/confirm APIs freeze terms and consent with server-owned validation.
- [x] Idempotent acceptance and user/product scope hold prevent duplicate purchase.
- [x] Prepare a dedicated agreement/subscription, then point-verify readback.
- [x] Preserve uncertain operations and original recovery deadline; coalesce work
  and escalate review without blind financial retries or premature scope release.
- [x] Existing purchase/status and same-key replay survive source outages.
- [x] Payment bootstrap uses the original owned purchase and effective terms.
  Initial financial projection is `unverified`; no paid grant is written.

Focused synthetic HTTP/DB coverage includes normal preparation, response loss,
concurrency, historical Manage, ownership and absence of access writes.

## Step 4: Buy, Continue and Manage

- [x] Product/account UI supports authenticated review, draft legal consent,
  Buy/Continue/Manage, frozen idempotency and explicit changed-terms review.
- [x] One shared Widget lifecycle handles account/payment, concurrent hosts,
  close/logout/session changes and late asynchronous responses.
- [x] Show the proven agreement/seller and truthful awaiting-verification state.
- [x] Reuse generated API contracts, shared transport and all seven locale catalogs.
- [x] Deliver one [billing runbook](../../engineering/ANY-709-billing-runbook.md)
  for deployment, diagnostics, recovery, checks and later integration work.

### Buy timeout correction

The owner's Buy request returned an unavailable message although confirmation
and preparation succeeded. The recorded advance took 5.555 seconds, exceeding
the old 5-second browser deadline. Read-only diagnosis found one held linked
purchase and one subscription; it did not replay any provider operation.

Live billing POSTs now use a finite 130-second deadline covering the supported
120-second API preflight maximum. Auth/local status retain five seconds. A lost
confirmation/advance reply triggers one local GET of the original purchase;
it never automatically repeats a POST or grants payment from saved status.
Manage still obtains fresh purchase-specific proof. At that correction's
checkpoint actual payment was unverified and the working application was not
rebuilt/restarted; later acceptance and deployment supersede those limitations.

## Validation evidence

These are recorded checkpoints, not additive totals or a full final-SHA PASS.
Full command logs before compaction are retained in Git at `2961577`; exact
current repeat commands and human procedures belong to the runbook.

- Steps 1-2: canonical and focused checks passed at their checkpoints; details
  and limits are retained in the two condensed reports. The owner observed a
  real account Widget, which does not prove the product-bound payment journey.
- Step 3: 627 unit/HTTP/architecture regressions and 37 PostgreSQL tests passed,
  including all 13 protocol tests, 26 purchase DB cases and 11 customer-ensure
  regressions. Architecture, docs, generation freshness and Ruff passed.
- Step 4 after the timeout fix: 227 component tests, 38 boundary/tooling tests
  and 10 synthetic browser cases passed with no skips. API/SDK traffic was
  intercepted; the test-owned server exercised desktop and mobile.
- Consolidation before renumbering: 78 PostgreSQL regressions passed, zero skips.
  After renumbering: 17 schema/migration tests passed, zero skips. Coverage
  includes fresh/populated upgrade, all seven purchase states, exact retained
  column values, current-head no-op and atomic rollback on ambiguous holds.
- Formatting/lint, documentation and diff checks passed for their changed files.
  The migration consolidation/rename changed no final schema or HTTP contract,
  so generation was not needed. A full repository check after Steps 3-4 was not run.
- The Step 4 browser harness used webpack polling after a host watch-limit
  failure. At that checkpoint installed Next was 16.3.1 versus manifest 16.4.2;
  no dependency change or production-build acceptance was claimed.

## Migration and local database outcome

The branch has one forward migration, `20261027_0003_normal_billing.py`:

```text
20260924_0001 -> 20261001_0002 -> 20261027_0003
```

The first two main revisions are unchanged. The consolidated migration retains
all 23 original upgrade statements and all 21 reverse-order downgrade statements,
including constraints, indexes, triggers, operation-account and hold backfills.
There are 27 application tables. Conflicting legacy identities/holds fail
atomically rather than deleting or arbitrarily adopting history.

The owner authorized updating the existing local development DB from retired
head `20261027_0006`. Its entire schema matched a fresh current-head reference.
After a protected backup, a guarded transaction changed only `alembic_version`
to `20261027_0003`; fingerprints/counts of all 27 application tables were
unchanged. Normal `migrate-api` then passed without replaying DDL.
Backup: `.harness/backups/any709-before-0003-20261027T065436Z.dump` (0600, ignored).
Production and LBX were not changed by this transition.

Databases at retired intermediate revisions must complete the original chain
before a verified label transition. Never stamp over unapplied operations or
replay this DDL over an already-upgraded schema. See the
[migration procedure](../../engineering/ANY-709-billing-runbook.md#consolidated-any-709-migration).

## Remaining review and next owners

- Independent final review is pending. Owner test-payment/target acceptance is
  complete for the recorded stand/purchase; repeating a payment is not needed
  to verify readiness diagnostics or explicit refresh.
- SDK-readiness verification is recorded in the current acceptance section.
  The PR remains In Review, not merged.
- **ANY-715 / program Step 8:** background worker, webhook/reconciliation and
  read-only financial recovery scheduling. Durable work exists; no worker runs here.
- **Program Steps 9-10:** authoritative paid-access derivation, allowances,
  AccessSnapshot and Kernel invalidation. **ANY-711:** real Kernel producer
  conformance. **Step 11:** production/launch sign-off. None is completed here.

Target authority remains ADR 0005, the accepted external-billing/access designs
and the live-source amendment, as linked from the root `AGENTS.md`.

## Final review remediation, 2026-10-27

The owner authorized fixing the independent review findings in the current
commit. Proven financial no-send now has a fenced explicit resume path; genuinely
unknown outcomes remain GET-only. Same-tariff selections of different products
use the canonical product hold and point-proven historical inventory. The React
runtime fixture now supplies the mounted current-purchase read; assertions and
CI scenarios remain enabled. Catalog copy no longer claims Buy is unavailable.

Security analysis retains the isolated official SDK host and useful test CLI
output. Exact Sonar/CodeQL false-positive rationale and regression coverage are
recorded in [Security](../../SECURITY.md#any-709-analyzer-adjudication-pr-150).
Migrations remain unchanged; the consolidated DDL and guarded local transition
evidence above still apply. At that remediation checkpoint full real
purchase/payment acceptance was NOT_RUN; later owner acceptance supersedes it;
the [runbook checklist](../../engineering/ANY-709-billing-runbook.md#final-review-corrections-and-human-acceptance)
is the required human handoff.

Review verification:

- `KERNEL_MOCK_ENABLED=0 KERNEL_BASE_URL= KERNEL_SERVICE_TOKEN= npm run check`
  with the repository `.venv` on PATH: PASS. Includes 1435 fast API tests,
  265 PostgreSQL tests (12 new review regressions), 339 component tests,
  38 boundary/tooling tests, documentation/generation/architecture, Ruff,
  web lint, TypeScript and production build. Log: `/tmp/ANY709-review-check.log`.
- Four additional malformed-original-date cases were added after that full run
  and passed with `PYTEST_ADDOPTS='-k original_agreement_date' npm run test:api:fast`.
- Current-source `react-runtime.spec.ts` and `any709-purchase.spec.ts`:
  14/14 desktop/mobile PASS, zero retries/skips, synthetic API/SDK only. The
  temporary config imports the repository runtime config and uses isolated port
  3117 with webpack/polling for this host. Report:
  `/tmp/any709-browser-review-report.json`; log: `/tmp/ANY709-review-browser.log`.
- The canonical full harness browser suite was locally skipped because
  `RUN_E2E=true`/its running stack were not selected. The focused browser run
  above covers the changed failure and purchase paths; GitHub owns the full job.
- Local installed Next.js is 16.3.1; manifest/lock require 16.4.2. No dependency
  source was changed. GitHub's clean locked install remains the final check for
  that version. Real provider writes, actual payment and production rollout were
  not run. CodeQL alert 5 was dismissed as the documented false positive;
  the line-scoped Sonar exception requires a fresh PR analysis for gate evidence.

The first post-fix CI on `3982d50` passed Code quality, Production gate, both
harness smoke jobs, CodeQL, Trivy and Sonar (Security A, zero open issues).
Runtime browser checks passed, exposing six stale main-suite CTA expectations:
Step 4 replaced the product's old account link with guest sign-in or authenticated
purchase/billing controls. The tests now verify those controls and the retained
header account link, preserving href/navigation, keyboard Tab focus, viewport and
outline assertions. The current-purchase fixture is explicit. All six focused
desktop/mobile scenarios passed locally with zero retries/skips; web lint,
TypeScript and documentation checks passed. Log:
`/tmp/ANY709-review-portal-browser.log`. The RU journey documentation now describes
this implemented product entry and source-backed offer/purchase behavior.

## Owner-approved cabinet billing follow-up, 2026-10-27

The owner approved one wide Widget in the cabinet. Public product pages retain
current offers, review/consent and preparation; linked purchases become compact
subscription summaries with locale-aware cabinet links carrying the purchase ID.
The cabinet lists only the authenticated user's accepted held purchases from
PostgreSQL, with bounded cursor pagination and links to product detail/all products.
Pending accepted purchases remain resumable and are not presented as paid access.
Historical owned purchases remain visible independently of Kernel/LBX catalog
availability. Payment opening retains the existing fresh authoritative ownership,
agreement/seller and accepted-term checks; a query parameter never authorizes it.
No new provider writes, reconciliation, paid-access derivation or legal approval
is introduced. Verification will cover ownership/pagination, empty/error states,
selected-purchase navigation, one Widget, session races, desktop/mobile and axe.

Follow-up verification PASS:

- Canonical `npm run check:fast` and `npm run check`: docs, generated contract
  freshness, architecture, Ruff, 38 boundary/tooling tests, 352 component tests,
  1,439 PostgreSQL-independent API tests, production web build and 267 PostgreSQL
  tests. The new PostgreSQL cases cover owner isolation, verification, pagination,
  source-independent inventory and released-purchase exclusion. Logs:
  `/tmp/ANY709-cabinet-check-fast.log`, `/tmp/ANY709-cabinet-check.log`.
- The focused browser set covers 24 distinct desktop/mobile scenarios: the new
  product-to-cabinet journey, empty cabinet, source failure/recovery, slow prepare,
  SDK retry, late credentials/logout, native forms and existing account entry.
  The combined run passed 22/24; the remaining two used an obsolete network
  assertion that omitted the new local inventory GET. After correcting that
  assertion, all four account variants passed without retries/skips. The final
  purchase journey was repeated on desktop/mobile with screenshots and zero
  serious/critical axe findings. Logs: `/tmp/ANY709-cabinet-browser-final.log`,
  `/tmp/ANY709-cabinet-browser-account-rerun.log`,
  `/tmp/ANY709-cabinet-browser-journey-final.log`. Initial cold compilation exceeded
  a five-second navigation assertion; the final explicit navigation wait is
  bounded at 20 seconds. A transient unused-font preload warning did not recur.
- Desktop/mobile screenshots were inspected. Only one Widget is mounted, the
  payment target remains visible, cards are compact and local, and horizontal
  overflow/accessibility checks pass. Final lint/docs/diff-whitespace checks PASS.
  Manual authority/session/ownership diff review found no new payment authority,
  provider mutation, legal approval, paid-access or quota behavior.
- Rebuilt the existing local harness using `npm run repo:up -- --reuse`. Existing
  database and ports were retained; API/web are healthy. Cabinet returns HTTP
  200 and includes the new localized UI; inventory without authentication returns
  401. No real LBX CREATE, acquiring payment or user-data reset was performed.
  Rebuild log: `/tmp/ANY709-cabinet-preview-rebuild.log`.
- Full local harness browser suite remains skipped; the isolated focused server
  used synthetic network/SDK responses only. Local installed Next 16.3.1 versus
  locked 16.4.2 remains a clean-CI verification constraint. Human actual Widget
  acquiring/target selection were pending at that checkpoint; later owner
  evidence supersedes that limitation. Legal approval remains outside this delivery.

The inherited `catalog-preview` and `account-logout` browser expectations were
also updated: public catalog publication no longer populates owned inventory.
Sixteen additional Russian/Portuguese desktop/mobile catalog and session cases
passed on the rebuilt production preview, with synthetic HTTP responses only;
owned-list failure remains distinct from empty, new public products stay absent,
and detail/all-products links remain localized. Log:
`/tmp/ANY709-cabinet-catalog-production-browser.log`. This brings the focused
passing set to 40 distinct scenarios. Existing session request-count assertions
were retained: development StrictMode produced three reads instead of the
production expectation of two, so those cases were rerun against production
rather than weakening their assertions. Final changed-test lint/TypeScript PASS.
The implementation SHA `3b9c5b1` passed CI Code quality, Production gate, both
harness smoke jobs, Sonar, CodeQL and Trivy; it is predecessor evidence for the
subsequent test-only amendment. Read final CI against the amended head.

## Authenticated live QA and CI fixture follow-up, 2026-10-27

The owner supplied the test account for authenticated browser QA. Read-only
PostgreSQL and LBX reads confirmed one customer binding (client 29), one held
`proposal_ai` purchase and the original accepted terms. Agreement 32 belongs to
that customer and seller 21; subscription 31 is active, unblocked, 100 RUB per
month with quantity one. The separate `demo_*` agreement belongs to seller 9
and has no Portal provisioning operation. Portal financial access remains
unverified. No new agreement, subscription, legal acceptance or payment was
created during this follow-up. Log: `/tmp/ANY709-user29-live-followup.log`.

Authenticated live browser checks confirmed the compact prepared product page,
the purchase-specific cabinet selection, the owned card and all-products/detail
links, persistence after reload and one outer Widget after both cabinet entry
actions. In the visible built-in browser the real Widget loaded with top-up
buttons on both agreements; selecting the Portal agreement showed active
subscription 31 at 100 RUB/month. Two earlier Chrome attempts reported the
vendor READY timeout, so stable loading across those environments is not a PASS.
Automation could read the nested Widget but its mouse actions reported an
unavailable focus root; keyboard navigation selected the agreement, but did not
complete the top-up form inspection. Real-method/acquiring validation remains
pending at that checkpoint; `MAPPED_PURCHASE_WIDGET_PASS` was not yet recorded
and payment was NOT_RUN. The later owner payment result supersedes this status.
The published vendor bundle also handles Enter/Space on the agreement card
without excluding nested button targets; those keys select the agreement rather
than opening its focused top-up button. This is external Widget behavior, not a
Portal change. Live screenshots: `/tmp/any709-liveqa/`.

CI browser failures on `e3384c9` came from the session-race fixture sending the
new owned-inventory GET to the live API with a synthetic session. The fixture now
returns an explicit empty owned list; the existing session, error and request
count assertions are retained. All 52 desktop/mobile session-race cases passed
against the rebuilt production preview, with synthetic HTTP responses, zero
retries and zero skips. Log: `/tmp/ANY709-live-session-races.log`. The purchase
journey now asserts the complete destination URL, including the single billing
fragment, rather than a partial regular expression.
Both exact-URL desktop/mobile journey cases passed with zero retries/skips
(`/tmp/ANY709-live-exact-journey.log`). The built-in browser alone showed a
duplicated fragment during automation; the selected purchase still survived a
reload. Web lint, TypeScript, docs and diff-whitespace checks passed. The earlier
canonical full checks remain applicable: this amendment changes only browser
fixtures/assertions and this evidence record.

## Owner payment evidence and cabinet refresh, 2026-10-27

On predecessor `50d833c`, the owner completed a Widget top-up through YooKassa.
The supplied checkout, LBX-admin and Widget-history screenshots corroborate a
100 RUB YooKassa credit to the intended Portal agreement for client 29/seller
21. They distinguish it from the earlier administrator credit and show the
resulting 100 RUB balance. Record `MAPPED_PURCHASE_WIDGET_PASS` for this stand
and purchase. This is owner-run payment evidence, not an agent-executed payment
or a production-launch/settlement certification. Paid access remains deferred.
The owner also reported needing to reopen the Widget after payment.

The current public SDK and Widget bundle were fetched read-only and match the
earlier inspected SHA-256 bytes. SDK version 0.0.1 exposes no payment-completed
callback to the Portal. Embedded YooKassa success invalidates vendor agreement
queries internally, but emits no payment-completed message to the SDK host.
No payment-completion callback or vendor DOM access is invented here.

The cabinet's existing open action becomes an explicit localized "Refresh
billing" action while the Widget is open, with a hint to refresh after completing
payment. It reuses the selected purchase and the existing fresh server-side
bootstrap verification. The old sandbox/credential is disposed before waiting;
an unsuccessful verification leaves no stale Widget. There is no timer that
could replace an in-progress checkout, no new payment endpoint, no access-state
change and no remote SDK modification. Component coverage checks same-purchase
refresh, disposal, pending state, verification failure and safe retry; the
desktop/mobile purchase journey now exercises refresh before close/reopen.

Refresh validation:

- All 22 cabinet component cases passed, including the two new refresh cases.
  The full component set passed 354 tests and boundary/tooling passed 38 tests.
  Both desktop/mobile purchase journeys passed without retries/skips, with the
  fresh same-purchase bootstrap, one Widget, no horizontal overflow and zero
  serious/critical axe findings before closing and after reload. Screenshots
  were inspected. Log: `/tmp/ANY709-refresh-journey.log`.
- The first full check inherited local development Kernel mock settings and
  failed four environment-sensitive API tests. Disabling the mock and clearing
  Kernel URL/token only for the test process made those four pass. The full
  rerun uses `KERNEL_MOCK_ENABLED=0 KERNEL_BASE_URL= KERNEL_SERVICE_TOKEN=`;
  `.env` and the running stack's Kernel configuration remain unchanged.
  The rerun passed all 1,439 fast API tests and the production web build.
  Log: `/tmp/ANY709-refresh-check-isolated.log`.
- Rebuilt the existing preview with `npm run repo:up -- --reuse`, retaining its
  ports and data. Authenticated visible-browser refresh removed the old host,
  retained purchase `0471707a-b520-423e-b57c-5d165c40315d`, mounted one new Widget
  and showed the original agreement/seller. Selecting the Portal agreement and
  History again displayed the 100 RUB balance, two 100 RUB credits and the
  earlier 100 RUB charge. No console errors/warnings were captured. No new
  payment or provisioning action was performed. Screenshot:
  `/tmp/any709-refresh/live-history.jpg`.
