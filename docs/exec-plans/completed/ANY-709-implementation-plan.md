# ANY-709 - Normal LBX billing, product mapping and Widget flow

Status: COMPLETED - implementation Steps 1-4 DONE; real payment acceptance NOT_RUN
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

All four implementation steps are complete. Automated checks and the local DB
transition passed at the checkpoints below. Actual acquiring/payment, complete
human purchase acceptance and production enablement remain unverified.

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
Manage still obtains fresh purchase-specific proof. Actual payment remains
unverified; the correction did not rebuild/restart the working web application.

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

## Remaining acceptance and next owners

- **NOT_RUN:** final human purchase/target-selection/acquiring scenario, actual
  payment and production rollout. The owner's recorded purchase reached linked
  state with one prepared subscription; it is not full human acceptance.
- The official Widget must offer payment for the intended agreement/seller;
  missing acquiring configuration or a different default agreement is not PASS.
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
evidence above still apply. Full real purchase/payment acceptance remains NOT_RUN;
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
