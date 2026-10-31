# ANY-709 - Normal LBX billing, product mapping and Widget flow

Status: IMPLEMENTED_AND_TESTED - Review fixes verified; local startup repaired; automated Widget READY timeouts unclassified; human merge approval pending
Completed: 2026-10-27
Program: ANY-504, Step 7
Issue: [ANY-709](https://linear.app/paveldik/issue/ANY-709)

## Baseline specification restoration and ticket decisions, 2026-10-31

Owner-authorized documentation-only follow-up on runtime head `754501b`.
Restore both changed accepted specifications from PR base `ace7c277`; retain
implemented behavior and record why each departure was selected in ANY-504 and
what was delivered/verified in ANY-709. A short ADR recognizes that exact dated
decision section so unchanged baseline text cannot silently undo the decisions.

- [x] Restore the September external-billing design and October live-source
  amendment byte-for-byte from the PR base, preserving all earlier accepted
  Phase 0, canonical-ID and paid-access facts.
- [x] Prepare decision C1-C4 records with before/after, rationale, precise scope,
  preserved invariants, evidence and the conditional LBX email-uniqueness risk.
  Do not promote that provider assumption to a new verified guarantee.
- [x] Update authority navigation and current operational references. Preserve
  the rest of the tickets and historical verification reports unchanged.
- [x] Verify documentation and unchanged runtime scope; update/read back both
  tickets and create a separate commit, retaining the existing runtime fix.

Verification and delivery:

- Both changed specifications and the untouched Portal-Kernel specification
  are byte-identical to PR base `ace7c277`. The cumulative PR diff has no files
  under `docs/superpowers/specs`. Only Markdown changed from runtime `754501b`.
- Added the dated C1-C4 section to ANY-504 and implementation/result section to
  ANY-709. Readback verified the new text (allowing Linear's issue/link/list
  formatting), the entire prior description and unchanged issue status. No
  historical text, completion checkbox, assignment or title was changed.
- `npm run docs:check`, `npm run architecture:check` and all 194 focused
  repository-documentation tests passed. New canonical `npm run check:fast`
  passed: 1,542 fast API, 385 component and 38 boundary tests, generated
  freshness, documentation, architecture, Ruff and web lint/typecheck.
  Logs: `/tmp/pr150-doc-restoration-focused.log` and
  `/tmp/pr150-doc-restoration-fast.log`.
- The completed full canonical check on `754501b` remains the evidence for the
  unchanged runtime, 406 PostgreSQL cases and production build. PostgreSQL,
  production build and browser E2E were not repeated for this Markdown-only
  change. No new live-provider or provider-uniqueness claim is made.
- ADR 0006 and the navigation recognize only this fixed dated ticket section;
  ordinary issue text cannot silently override the baselines. Current runbook
  and security behavior remain linked to the explicit decisions. No application,
  migration, dependency, generated, legal or paid-access implementation changes.
- Delivery is one new documentation commit on `754501b`, preserving the runtime
  fix and prior history. The concurrent ANY-765/ANY-715 worktrees are untouched.

## Customer conflict recovery follow-up, revised 2026-10-31

Owner-authorized revision of the last commit for
[P1 discussion_r4422516165](https://github.com/gushinets/payments-portal/pull/150#discussion_r4422516165),
against parent `8a3732c`. Preserve the accepted identity contract: LBX `user_id`
is canonical; the original `billing_customer_key` remains the correlation and
paired consistency check. The earlier blanket refusal also blocked the specified
recovery of a previously proven customer after provider-side restoration of that
original key. This revision narrows the fix instead of changing the specification.

- [x] Reproduce that recovery regression with real PostgreSQL and synthetic HTTP.
- [x] Distinguish a proven canonical-ID key mismatch from unresolved discovery
  ambiguity, an unproven first match, a different ID and other review reasons.
  Permit only read-only verification of the same proven ID for that typed cause.
- [x] Resolve that cause only after fenced authoritative proof of the original
  ID/key pair; retain distinct blocking causes and closed audit history.
- [x] Keep strict customer, Widget and financial-send admission under the
  existing locks, including the post-source-I/O financial claim check.
- [x] Restore the September specification to the parent commit, narrow the
  architecture/runbook explanation, and add regression coverage for recovery,
  unresolved drift, mixed causes, stale proof and financial interleavings.
- [x] Run focused and canonical checks, review the final cumulative change
  and record evidence. Deliver as one amended local commit, without pushing.

Implementation:

- Billing owns separate read-recovery and strict admission checks. Both inspect
  retained evidence under the existing customer/customer-operation locks. Only
  a point mismatch for the already proven canonical ID records the versioned
  `customer_original_key_mismatch` cause. Recovery checks its original ID,
  operation and correlation key; untyped legacy causes remain blocked.
- Matching original-pair proof resolves only the permitted UNKNOWN/key-drift
  cases. Distinct ambiguity/wrong-ID/Client conflicts cannot be erased by it.
  Every conflict rotates the fence, so delayed proof cannot overwrite a newer
  cause. Closed cases remain unchanged.
- Financial claims retain strict admission atomically with a genuinely new
  possible-send record after source I/O. Existing UNKNOWN/recover-only guards
  still precede it. The original lock order and held scopes are preserved;
  conflict cannot retroactively cancel an already claimed provider command.
- At runtime checkpoint `754501b`, the September specification was
  byte-identical to parent `8a3732c`; earlier approved amendments remained.
  The later documentation-only follow-up above restores the PR-base bodies. Architecture/runbook explain the narrower policy.
  There is no new operator reconciliation/force-bind workflow.

Verification:

- Before implementation, the new contract diagnostics reproduced the blanket
  refusal (including ordinary key restoration and financial Continue). Log:
  `/tmp/pr150-revision-red.log`.
- First focused run: 38 PostgreSQL cases passed, including the original 25
  conflict regressions (`/tmp/pr150-revision-focused.log`). Two further scenarios
  then covered concurrent ambiguity during key recovery and Client-scope
  mismatch after recovery. Final new suite contains 14 permanent cases.
- All 14 final cases plus four temporary full HTTP diagnostics passed: actual
  registration/email verification, account-first/buy-first, normal/lost customer
  reply, consent, preparation, Widget type 7, logout/login and identity reuse.
  Only SMTP/LBX/Kernel transport edges were substituted. The temporary diagnostic
  was removed before canonical checks. Log: `/tmp/pr150-revision-contract-flows.log`.
- Full `npm run check` passed on the final production/test code: 1,542 fast API,
  406 PostgreSQL, 385 component and 38 web-boundary tests; generated freshness,
  documentation, architecture, Ruff, web lint/typecheck and production build.
  Log: `/tmp/pr150-revision-canonical.log`. The PostgreSQL run includes all 25
  original conflict regressions and 14 new original-key recovery cases.
- Browser E2E was skipped: `RUN_E2E=true` and an application harness were not
  enabled. Synthetic HTTP exercises production use cases and PostgreSQL, not
  live LBX/Kernel or the real Widget SDK. No live CREATE/payment, application
  database mutation, deployment or production-readiness claim is made.
- Locked JavaScript dependencies were installed offline; no lockfile change.
  Python 3.12.13/Ruff 0.15.22 were used. Production modules remain below 500
  lines. No schema, wire, dependency, generated, immutable identity, legal or
  paid-access diff. The isolated test server is `payments-5564c771`; pytest owns
  `pr150_conflict_revision_tests` creation/drop. Concurrent ANY-765/ANY-715 work
  is untouched.

Final local `review-full` pass covered the complete last-fix delta against
`8a3732c`, including the retained conflict/diagnostic tests, new policy module,
new recovery tests and affected callers. No additional confirmed defect was
found within that scope:

- Identity/recovery: two openings cannot erase ambiguity; original-ID/key
  restoration succeeds without another customer or key. Mixed causes, invalid
  evidence and legacy untyped conflicts remain blocked. UNKNOWN and lost-reply
  positive controls continue successfully.
- Concurrency/admission: event-coordinated stale proof cannot overwrite a newer
  conflict. Both agreement and subscription claims refuse conflict committed
  during source I/O, retain accepted evidence/holds, then resume after original
  identity proof with exactly one of each provider object.
- Architecture: billing owns both policies; callers retain transaction/commit
  ownership. Customer-only writers never acquire purchase/user locks; financial
  callers acquire user/purchase/financial rows before customer/operation rows.
  There is no reverse lock acquisition or provider HTTP inside these DB units.
- Result: the four HTTP journeys preserve verification, canonical type-7
  identity, accepted consent and purchase reuse across lost replies/login.
  This validates this fix, not the whole program or real-provider readiness.

ANY-715/ANY-765 integration must carry the narrow cause evidence, read-recovery
policy, strict send/Widget admission and post-I/O financial claim check together.
Do not carry forward the superseded blanket read refusal or infer causes for
historical generic conflicts. No automatic existing-data repair is supplied.

## Origin-scope serialization follow-up, 2026-10-30

Owner-authorized fix for
[P1 discussion_r4421302727](https://github.com/gushinets/payments-portal/pull/150#discussion_r4421302727)
on `688127c`. The prior shared-query/NULL-head guard did not serialize account
selection with publication. Preserve immutable account IDs, accepted consent,
customer/financial operation identities and recovery fences. No schema or wire
change, live provider write, payment or database repair is required.

- [x] Share one PostgreSQL transaction advisory lock keyed by deployment
  tenant/contour and normalized provider origin, independent of credentials and
  legacy/default account aliases. Require READ COMMITTED and inherit finite
  caller timeouts; only known contention becomes a temporary refusal.
- [x] Serialize customer scope resolution/reservation and every origin-backed
  publication branch. Purchase acceptance takes origin before product/head
  locks; publication locks the product at the resolved account. Keep provider
  HTTP outside transactions and preserve exact replay/recovery paths.
- [x] Extract focused admission units within the existing 500-line limits.
- [x] Add event-coordinated PostgreSQL regressions for the missing ordering,
  both directions, empty first rows, rollback, bounded contention, purchase lock
  order, rotation and safe HTTP refusal/replay. Retain ambiguity and historical
  evidence controls.
- [x] Run focused checks, correctness/architecture/DoD review and the broadest
  supported canonical check; record results and remaining acceptance limits.
- [x] Update the runbook with the protocol, coordinated writer rollout,
  read-only consistency audit and ANY-715/ANY-765 integration handoff.

Baseline: the unchanged PR head was independently reproduced with PostgreSQL
READ COMMITTED and synthetic HTTP. Publication committed between the first
customer account read and its following head query; the customer/operation
committed at the default account, one synthetic CREATE returned a candidate,
and later reservation refused the two proven scopes. The existing overlap test
paused publication before its commit and did not exercise this ordering.

The production patch extracts customer scope admission and purchase lock order
into focused units. Publication resolves scope under the common origin lock and
then uses the same resolved-account product lock as acceptance. Customer
reservation reenters the already-held origin lock within purchase acceptance's
transaction; neither the helper nor the resolver owns commit/rollback.

Focused production-patch checks passed: 11 lock/error-classification cases and
33 PostgreSQL/HTTP cases across the new protocol, retained scopes, purchase
contention, stale-term fencing and subscription inventory. The subsequently
added HTTP Widget case checks safe `billing_busy`, no provider request or local
identity while blocked, then successful explicit reopening with one customer
and no financial CREATE. Its result is recorded with final canonical evidence
below. The earlier 99-test temporary prototype is separate design evidence.

Self-review of the complete fix and affected callers:

- Correctness: the two-read scope decision and slot/head write share one lock;
  the missing schedule now observes a real PostgreSQL advisory waiter. Both
  transaction orders, rollback and timeout preserve one scope. Existing exact
  replay returns before new-admission locks; financial UNKNOWN remains GET-only.
- Architecture: all active customer/head origin writers and purchase acceptance
  participate. User → origin → resolved product → offer/rows has no reverse
  acquisition between these participants. Provider HTTP remains outside DB
  units. There is no registry table, schema change or duplicate scope authority.
- DoD: real HTTP purchase contention/refusal/retry and Widget reopening cover
  the affected entrypoints, with request IDs, no-store, retained accepted terms
  and no duplicate customer/financial identity. No new confirmed actionable
  issue was found in this fix's reviewed boundary; this is not renewed full-PR
  or live-provider acceptance.

Final production-patch verification:

- Full `npm run check` passed in one completed final run: 1,542 fast API,
  367 PostgreSQL, 385 component and 38 boundary tests, documentation/generated
  artifact checks, architecture, Ruff, web lint and production build. Log:
  `/tmp/pr150-origin-fix-canonical.log`. The PostgreSQL partition includes the
  Widget HTTP contention/reopen case and all new origin-lock regressions.
- `npm ci --offline --no-audit --no-fund` installed the unchanged lockfile.
  Web-workspace ESLint is 10.8.1; Next/Vitest/Vite are 16.4.2/4.1.12/7.3.7.
  Initial copied dependencies omitted workspace-nested packages; the initial
  boundary failure was environmental and was resolved by the clean install.
- Earlier combined API attempts could not connect after the previously shared
  local test server stopped. The final run used this worktree's own isolated
  Compose PostgreSQL server and disposable `pr150_origin_fix_canonical_tests`;
  pytest owned the database lifecycle. No application database was migrated or
  repaired. Source HTTP was synthetic throughout.
- Architecture/source limits and final diff checks passed; no package,
  lockfile, generated, schema or legal-content change was introduced. The
  documentation evidence update was checked separately after the full run.
- Browser E2E was skipped by the canonical runner because `RUN_E2E=true` and a
  running application harness were not enabled. Real HTTP ASGI purchase/Widget
  journeys ran against PostgreSQL and synthetic provider transport. No fresh
  real SDK/LBX/payment or production acceptance result is claimed.

No live-provider operation or GitHub reply/thread resolution has been performed.
The owner authorized committing and pushing this verified follow-up to ANY-709.
ANY-715/ANY-765 integration remains an explicit handoff; their working copies
were not changed by this ANY-709 fix. Human merge approval is still required.

## Three-pass review remediation, 2026-10-30

Owner-authorized scope: implement all five confirmed findings from the
correctness, architecture and definition-of-done reviews of `a2bcb59` against
main `ace7c27`. Preserve immutable history, external ownership and paid-access
rules; no schema change or live payment is required.

- [x] ARCH-1: use consistent origin-backed connection scope evidence for
  publication and customer reservation; gate unproven retained legacy heads
  before creating a competing permanent customer.
- [x] P2-4409711513: encode runtime dotenv values for the actual Compose
  consumer without changing signing-secret bytes; refuse unsupported controls.
- [x] ARCH-2: align purchase product-ID admission with the published-link bound.
- [x] DOD-1: correct the current migration handoff and distinguish historical
  checkpoints from the single current `20261029_0003` revision.
- [x] DOD-2: retain safe request IDs for cabinet inventory and deep-link errors,
  clearing stale diagnostics on retry, selection and session changes.
- [x] Run focused regressions, affected journeys and canonical verification;
  record results and remaining environment limits below.

Implementation:

- Catalog and customer admission share origin-backed account evidence. Catalog
  still validates its immutable link documents. Customer reservation refuses a
  recognized unproven legacy head before any slot/operation/HTTP CREATE; an
  authorized no-op publication records origin on the mutable head. Existing
  customer-only scopes govern first publication. No ID/FK/history is rewritten.
- The runtime writer uses Compose's supported dotenv escapes and dollar
  escaping; its reader uses the matching grammar. Unsupported controls fail
  without exposing values or replacing an existing private runtime file.
- The product-link and purchase boundaries share the 1,024-character policy.
  Review, confirmation and current-hold lookup retain full identifiers; OpenAPI
  was regenerated with `npm run generate`. No schema change is required.
- Cabinet read states retain a safe server request ID or the sent local ID.
  Retry, selection and session invalidation clear the applicable stale state;
  late responses cannot restore it. Existing localized copy is reused.
- PR #150's migration paragraph now agrees with the actual single revision and
  runbook. Its earlier verification commit is explicitly a historical checkpoint.
  The current graph below supersedes the preserved 2026-10-27 database evidence.

Verification of the actual working-tree fixes (not the earlier prototypes):

- Before implementation, permanent regressions reproduced five PostgreSQL
  failures with five passing controls, five component failures with 24 passing
  controls, and 29 dotenv failures with 40 passing controls. Logs:
  `/tmp/any709-fixes-red-postgres.log`, `/tmp/any709-fixes-red-ui.log`,
  `/tmp/any709-fixes-red-dotenv.log`.
- Focused checks passed: 10 PostgreSQL scenarios, 29 cabinet component cases and
  69 dotenv cases. The product-ID cases exercise live source evaluation,
  publication, catalog, current hold, review, confirmation, advance and Widget
  at lengths 256/257/1024; all three purchase inputs reject length 1025
  specifically as `product_id` too long. Scope cases include an event-coordinated
  publication/open overlap, customer-only first publication, genuine ambiguity,
  unchanged immutable documents and a bound account with an unrelated bad link.
- An actual network-disabled Compose container preserved all 17 synthetic
  secret variants. Settings and the real Widget signer then passed independent
  HMAC checks against the original bytes. Together with unsupported-control and
  private-file-preservation controls, 43 checks passed:
  `/tmp/any709-fixes-compose-container.log`. No real secrets were used.
- Full `npm run check` passed in one final run: 1,531 fast API, 355 PostgreSQL,
  385 component and 38 web boundary tests; documentation/generation,
  architecture, Ruff, web lint and production build also passed. Log:
  `/tmp/any709-fixes-canonical-final.log`. No deadline or test budget changed.
  An earlier run stopped at Turbopack's refusal of dependency symlinks outside
  the worktree; replacing those links with local copies of the same installed
  dependencies resolved it. No package/lockfile change was needed.
- `npm run typecheck:web` passed (`/tmp/any709-fixes-typecheck.log`). The full
  runner skipped the general browser suite without `RUN_E2E=true`; affected
  journeys were separately driven against the production build in desktop and
  mobile Chromium through real Portal HTTP and disposable PostgreSQL. Both
  passed: one accepted purchase/customer/agreement/subscription, the same
  purchase after reload and catalog outage, explicit Widget refresh and logout,
  and zero purchased allowances. Only Kernel/LBX/SDK used synthetic responses.
  Subsequently injected browser HTTP read faults verified both request IDs,
  128-character wrapping, explicit recovery and no page overflow. Axe found zero
  serious/critical violations in healthy and error views. Log:
  `/tmp/any709-fixes-browser-api.log`; screenshots:
  `/tmp/any709-fixes-{desktop,mobile}-{real-api,cabinet-errors}.png`.
- Local dependency versions remain the previously recorded Next 16.3.1,
  Vitest 3.2.7 and Vite 7.3.6, versus locked 16.4.2/4.1.12/7.3.7; React 19.2.8
  matches. This is local evidence, not new-head locked-install CI evidence.
  The application DB, live LBX, paid-access rules and deployment were untouched.
  Review fixes were verified in the separate `any-709-review-fixes` worktree;
  the original working directory stays on clean `ANY-765`.
- Final documentation and diff checks passed after updating this handoff. The
  task-owned Next process and worktree-local test PostgreSQL server were stopped.
  Logs: `/tmp/any709-fixes-final-docs.log`, `/tmp/any709-fixes-db-stop.log`.

## Owner-requested local startup and real Widget validation, 2026-10-30

The owner's `npm run repo:up -- --reuse` runs the original working directory on
`ANY-765` (`7ca593b`), separately from this ANY-709 review worktree. Image builds
passed; startup stopped because the local application DB retained retired label
`20261027_0003`. Initial read-only checks found 27 application tables and no
`billing_work_items.active_recovery_deadline_at` column. The earlier synthetic
Widget tests do not establish actual LBX/SDK readiness. Their error screenshot
deliberately shows injected read failures, not a healthy live-provider result.

- [x] Read the actual migrate failure and inspect the retained local schema.
- [x] Save a protected application-DB backup before any change:
  `.harness/backups/before-retired-revision-repair-20261030.dump` in the original
  working directory (0600, ignored).
- [x] Compare the retained schema with the original migration checkpoint and
  current references; preserve row fingerprints through the runbook transition.
- [x] Start the owner's local stand and verify actual LBX/SDK Widget behavior
  in the browser, recording the branch and any remaining limits accurately.

Local application-DB repair: PASS.

- Original checkpoint `afb46c5` exactly matched the retained schema (ignoring
  pg_dump random guard tokens and the nonfunctional default public-schema
  comment). The protected backup was successfully restored into a separate
  pytest-owned `payments_cf94dbf9_migration_audit_tests` database.
- Rehearsed the complete transition there: old `20261027_0003` to old
  `20261028_0004`, exact schema comparison with fresh `20261029_0003`, guarded
  single-row version-label transition, then normal current `upgrade head` to
  ANY-715's `20261028_0005`. All original column values in all 27 application
  tables / 116 rows remained byte-equivalent under sorted JSON fingerprints.
- Applied that same verified path to the owner's local application DB, checking
  its source schema/fingerprints before mutation, after the old upgrade, and
  against the final current-head reference. Original values were preserved.
  The active-window and worker-generation columns were applied through their
  original migrations; no DDL was skipped and consolidated DDL was not replayed.
- The owner's exact `npm run repo:up -- --reuse` then exited 0. Migrate exited
  0; API/web/PostgreSQL/observability are healthy and Caddy serves
  `http://localhost:39053`. Both API health endpoints returned 200. The stand is
  left running. Root `ANY-765` source and index remain unchanged; the ANY-709
  review fixes remain in their separate worktree.
- Evidence: `/tmp/any709-local-db-audit.log` (rehearsal PASS),
  `/tmp/any709-local-db-repair.log` (application repair PASS),
  `/tmp/any709-real-stand-up.log` (startup PASS). Protected fingerprints/schema
  hashes are in `.harness/backups/retired-revision-audit-20261030.json` (0600)
  in the original working directory. The pytest audit database was removed by
  its fixture after rehearsal.

Actual LBX Widget validation: one successful automated opening; automated READY
timeouts remain unclassified. The owner reports the manual close/reopen flow works.

- Used the owner's existing authenticated Chrome session at the local stand,
  the actual configured `https://043.lbxbilling.ru` SDK and Client API, and the
  already accepted purchase. No interception, fake vendor replies or SDK
  substitution was used. Kernel remains the configured development mock;
  this does not claim real Kernel conformance or production acceptance.
- A successful opening showed the intended `portal-8634...` agreement, 100 RUB
  balance, active subscription 31, the actual monthly test tariff and payment
  history dated 2026-10-27. Viewing/selecting the agreement and history did not
  perform a payment or accept new legal/commercial terms.
- Other automated retries after an error and an automated Portal refresh failed to obtain the
  vendor iframe's `READY`. Confirmed failed bootstrap requests returned HTTP
  200; the SDK logged `Widget iframe failed to load or did not send READY` at
  its built-in 10-second deadline, followed by Portal's 20-second SDK failure
  and safe request ID. A control with no intermediate iframe inspection also
  failed. These observations establish timeouts in the automated run, not a
  general Widget defect or instability in the owner's manual flow. The agent
  did not separately reproduce the manual close-then-open cycle. The owner
  subsequently reported that repeated manual opening and closing work. The
  effect of automation is unresolved; no new payment PASS is claimed.
- Public `/lbxwidget.js`, `/widget/index.html` and `/widget/app.js` returned
  200; the widget HTML has its root element and neither CSP nor X-Frame-Options
  response headers. Thus the SDK's deployment suggestion alone does not prove
  missing files. The deeper cause across delivery, browser/frame initialization
  and the READY protocol is not yet established. Do not hide it by weakening
  sandbox/CSP, bypassing READY, inventing SDK configuration or increasing
  business-operation deadlines.
- Known failed request IDs include `f8eca6ff8567fdaae19a7e13d59e0efb`,
  `ba8d80d1c1903477983393ebb5e03377`, `3ccdfcf821d5ec5a34a94b2b68cff301`,
  `35530d6aa5243929e9451a9473418e73`, and
  `6715a360ff62f275cf9e0f73a254f5c8`. The successful opening used
  `cba4bb8dcb696aeef5b2707f61d8df5e`. Capture current bootstrap/SDK timing
  together when investigating; do not include JWTs, auth headers or response
  credentials. Final actual-error screenshot:
  `/tmp/any709-real-widget-final.jpg`. This supersedes any interpretation of
  the synthetic screenshots as live Widget evidence. The actual-error image
  records the automated attempt only; it does not contradict the owner's
  successful manual close/reopen check.

## Subscription-send inventory review fix, 2026-10-30

Owner-authorized follow-up for
[P1 discussion_r4409729888](https://github.com/gushinets/payments-portal/pull/150#discussion_r4409729888):
recheck customer-wide same-tariff subscription inventory before every genuinely
new subscription send, including an explicit `PROVEN_NOT_SENT` continuation
after its agreement was bound. A prior agreement check is not current admission
proof for that later send.

- [x] Refuse an unproven competing subscription without a subscription POST;
  retain the purchase hold and immutable accepted evidence.
- [x] Keep incomplete inventory retryable and ended subscriptions admissible.
- [x] Preserve the exception for another point-proven Portal purchase and reject
  changed ownership/seller/material terms on that proof.
- [x] Preserve GET-only recovery after an ambiguous CREATE outcome, on both
  explicit advance and recovery entrypoints.
- [x] Reproduce with PostgreSQL regressions, run focused and canonical checks,
  and record their actual results. No schema, paid-access or wire change.

Implementation and focused evidence:

- The existing customer-wide inventory check now guards both unsent financial
  operations, rather than only agreement creation. It remains below the
  GET-only/recover-only guards and before the durable possible-send claim.
  Known conflicts enter review with the scope held; incomplete reads preserve
  the pending/no-send operation for a later explicit attempt.
- Six new admission cases cover first subscription send and proven-not-sent
  continuation after agreement preparation, with competing, ended or incomplete
  external subscriptions. Two recovery controls prove that a 500-after-effect
  subscription still binds through GET only, despite new competing inventory.
- Eight additional cases extend the existing other-product/same-tariff matrix
  through subscription no-send continuation: valid original Portal proof stays
  admissible, while unknown inventory, wrong seller and changed material terms
  require review. Accepted evidence and operation identities remain unchanged.
- Before the fix: 10 expected failures and 14 passing controls (four unrelated
  cases deselected), `/tmp/any709-p1-red.log`. After the fix: 45 PostgreSQL
  purchase/inventory/recovery/terms-fencing tests passed,
  `/tmp/any709-p1-focused.log`. Ruff check/format and `git diff --check` passed.
- Full `npm run check` passed documentation/generation, architecture, Ruff,
  38 web boundary tests, 378 component tests, lint, all 1,488 fast API tests,
  the production web build and all 345 PostgreSQL tests. Log:
  `/tmp/any709-p1-canonical.log`. The repository-root `.venv/bin` was on `PATH`;
  optional local Kernel mock/connection environment overrides were disabled for
  the canonical test process. No runtime deadline or test budget was changed.
- Browser E2E was skipped by the canonical runner: it requires `RUN_E2E=true`
  and a running harness stack. Synthetic HTTP and the worktree-local disposable
  PostgreSQL test database were used; no live LBX mutation or payment. The test
  PostgreSQL server was stopped after verification.

## Current-offer, stale-advance and dotenv review fixes, 2026-10-29

Owner-authorized scope: the three confirmed P2 findings on `fc85a95`.

- [x] Validate period metadata only on the uniquely effective price; retain
  complete date, schedule, selected-price and inline consistency checks.
- [x] Fence the terms-change transition against the purchase/operation snapshot
  that authorized source I/O. A concurrent advance must retain its newer result;
  genuine changes to still-current unsent terms must retain their refusal path.
- [x] Parse matching dotenv quotes and escapes before forwarding private values,
  preserving bootstrap without extra runtime dependencies and environment override
  precedence. Test the actual file-to-Settings path and the Widget signature.
- [x] Reproduce the failures with permanent regressions, run focused and canonical
  checks, and record actual evidence. No migrations, live LBX mutations, accepted
  history rewrites or paid-access changes are required.

Implementation and evidence:

- The price selector validates all relevant start dates, selects the unique
  effective row, then checks its period metadata and next-change consistency.
  Twelve new current/history/future cases include mismatched and missing period
  metadata; strict selected-row refusal and existing inline/date checks remain.
- The terms transition locks the latest purchase and financial operations, then
  compares their snapshots with those used before source I/O. Newer state,
  fences, receipts or bindings make the old decision inapplicable; the caller
  returns a fresh purchase. LINKED purchases cannot be demoted by catalog terms.
  Five PostgreSQL cases cover agreement/subscription interleavings, a changed
  fence returning to the same state, and genuine unsent terms-change controls.
  Original accepted/legal evidence, scopes and financial CREATE identities stay
  intact; fresh payment point proof succeeds after the stale request returns.
- Twenty-six dotenv cases cover real files, paired quotes, escapes, whitespace,
  process-environment precedence, redacted invalid-input errors and the complete
  private runtime-file/Settings/Widget-signature path. Bootstrap remains standard
  library only. A Python 3.12 `-S` check passed, and 2,000 synthetic quoted-value
  round trips matched `python-dotenv` with interpolation disabled.
- Before implementation, the regressions reproduced 26 fast failures and three
  PostgreSQL state-transition failures; the genuine terms-change controls passed.
  Focused source/configuration checks passed, including the final 100-case
  offer/dotenv subset. The focused purchase/recovery suite passed 61 PostgreSQL
  cases. Logs: `/tmp/any709-p2-red-fast.log`, `/tmp/any709-p2-red-postgres.log`,
  `/tmp/any709-p2-focused-fast.log`, `/tmp/any709-p2-focused-postgres.log`.
- Full `npm run check` passed documentation/generation, architecture, Ruff,
  38 boundary tests, 378 component tests, lint, all 1,488 fast API tests and the
  production web build. PostgreSQL finished with 327 passed and two failures:
  `test_customer_ensure_find_create_recover[unknown_error_after_effect]` and
  `[old_review]` expired their 0.6-second request budgets. Repeating their
  unchanged customer-only file in isolation passed all 11 cases. This is not an
  entirely green single canonical run; customer code/tests and runtime deadlines
  were not changed to hide the result. Logs: `/tmp/any709-p2-canonical-check.log`,
  `/tmp/any709-p2-customer-controls.log`.
- Browser E2E was not run (no web changes or running harness stack). Synthetic
  HTTP and disposable PostgreSQL were used; no live LBX mutation, application-DB
  migration, deployment or payment occurred. No wire/schema changes were needed.

## Single branch migration, 2026-10-29

Owner request: keep one ANY-709 migration after main's unchanged
`20261001_0002`, without losing schema operations or retained data.

- [x] Fold old `20261027_0003` and `20261028_0004` into one
  `20261029_0003`, retaining exact upgrade and reverse downgrade order.
- [x] Update chain assertions, populated recovery tests and current docs.
- [x] Compare the saved pre-consolidation chain with the single migration:
  operation AST, PostgreSQL schema objects, populated rows and rollback behavior.
- [x] Verify the retired-head transition without replaying DDL; record results
  and the supported canonical checks.

Local application DB revision/schema audit was unavailable (`OperationalError`);
no application database was started or modified. All migration exercises use
disposable PostgreSQL databases. Previously applied branch revisions require the
explicit, verified transition in the runbook; no runtime auto-stamp is added.
The final revision has a new date/ID so old `0003` cannot silently skip the
active-window column. Both retired IDs are refused until the verified transition.
The preliminary check using the old ID was stopped before the final validation;
all final migration checks run with `20261029_0003`.

Focused evidence:

- The saved `afb46c5` migration files were compared structurally: new upgrade
  AST equals old `0003` plus old `0004`, and new downgrade AST equals old `0004`
  plus old `0003`. Every original statement and its ordering are retained.
- `KERNEL_MOCK_ENABLED=0 KERNEL_BASE_URL= KERNEL_SERVICE_TOKEN= TEST_POSTGRES_DATABASE_URL=postgresql+psycopg://review:isolated-test@127.0.0.1:55440/any709_squash_focused_tests .venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_alembic_postgres.py apps/api/tests/test_any709_migration_postgres.py apps/api/tests/test_any709_recovery_migration_postgres.py -q`:
  22 passed on final revision `20261029_0003`, including explicit refusal of both
  retired revision IDs; log `/tmp/any709-squash-focused.log`.
- A separate comparison against the saved original chain exercised old `0003`
  and old `0004`, populated financial operations/work (including a non-NULL
  active window), old-chain completion, guarded version-only transition and
  new `upgrade head` as a no-op. All rows of 27 application tables were identical
  across the transition. Fresh old/new schema signatures matched every column,
  144 constraints, 180 indexes, nine functions, nine triggers and sequences.
  Both cases passed; log `/tmp/any709-squash-equivalence.log`. The first isolated
  comparison run failed Settings validation for an empty test password; using
  an explicit synthetic test password resolved the diagnostic setup issue.

Final canonical verification:

- `PATH="$PWD/.venv/bin:$PATH" KERNEL_MOCK_ENABLED=0 KERNEL_BASE_URL= KERNEL_SERVICE_TOKEN= APP_PUBLIC_BASE_URL=https://payments.example.test TEST_POSTGRES_DATABASE_URL=postgresql+psycopg://review:isolated-test@127.0.0.1:55440/any709_squash_canonical_tests npm run check`:
  PASS on the final revision: documentation, generation freshness, architecture,
  Ruff, 38 web boundary checks, 378 component tests, web lint/build, 1,450 fast
  API tests and all 324 PostgreSQL tests. Log: `/tmp/any709-squash-check.log`.
- Exactly one migration file differs from main's migration inventory:
  `20261029_0003_normal_billing.py`; both main migrations are byte-for-byte
  unchanged. The graph has three revisions and one head.
- Browser E2E was skipped (`RUN_E2E` unset, no harness stack). No web or runtime
  billing behavior changed. The application database remains untouched; its
  unavailable audit is not counted as an applied revision-label transition.

## Final local review remediation, 2026-10-28

Owner-authorized scope: P1-1, ARCH-1 and DOD-1 on `f5aacab`.

- [x] P1-1: compare fresh and accepted commercial terms in the same canonical
  connection scope, retaining historical account FKs, consent and operation IDs.
- [x] ARCH-1: reject another current product owner under the offer publication
  lock, including no-op publication; reject ambiguous retained links for new
  catalog/purchase admission while keeping operator queries/history and accepted
  purchase management available. Do not delete or automatically reassign data.
- [x] DOD-1: add per-attempt `duration_ms` to the existing safe LBX event;
  preserve streaming, deadlines, cancellation and retry classification.
- [x] Add focused regressions, run the supported canonical checks and record
  actual results. No real LBX writes or new payment are required for these fixes.

The fixes add no schema migration and do not rewrite historical fingerprints,
account bindings, consent, operation IDs or accepted snapshots. Provider-origin
and seller checks remain in force. Peer impact: None; Kernel product IDs and
wire contracts are unchanged.

A read-only transaction against the existing local application database found
one current head and zero duplicate account/offer groups. No application data
was changed. Automated fault/concurrency tests use separate disposable databases
and synthetic HTTP transports.

Verification on the resulting working tree:

- `PATH="$PWD/.venv/bin:$PATH" KERNEL_MOCK_ENABLED=0 KERNEL_BASE_URL= KERNEL_SERVICE_TOKEN= TEST_POSTGRES_DATABASE_URL=postgresql+psycopg://review@127.0.0.1:55440/any709_canonical_tests npm run check`
  passed documentation, generated-contract freshness, architecture, Ruff,
  38 web boundary checks, 378 component tests, web lint/build, 1,450 fast API
  tests and all 320 PostgreSQL tests. Log: `/tmp/any709-remediation-check.log`.
- Separate `npm run test:api:fast` and `npm run test:api:postgres` runs in the
  same isolated environment also passed 1,450 and 320 tests respectively. Logs:
  `/tmp/any709-remediation-api-fast.log` and
  `/tmp/any709-remediation-api-postgres.log`.
- The new regressions cover old/new account scopes, username rotation, actual
  price changes, simultaneous offer claims, offer reuse after retarget, retained
  conflicting heads, acceptance recheck, original Manage/idempotent replay, and
  precise HTTP body/close/error duration with safe diagnostics.
- The first focused runs exposed test-fixture mistakes: the duration probe
  bypassed counted source scheduling and omitted JSON Content-Type; one old
  migration test reused the same offer for a second product. The probe now uses
  the real counted path and valid headers; the migration fixture uses a distinct
  offer while preserving its scope/history assertions. All affected checks
  subsequently passed in the complete suites.
- Browser E2E was skipped by the canonical command because `RUN_E2E` was unset
  and no harness stack was started. No web source changed; browser results from
  prior review remain predecessor evidence, not a new E2E claim.

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

## Widget recheck recovery correction, 2026-10-28

The independent review reproduced a linked purchase losing its prepared state
after a transient agreement/subscription GET failure. The next cabinet retry
then returned `409 purchase_not_prepared` before any provider read. A separate
advance was required even after LBX recovered.

The owner authorized a narrow correction: retain `linked` preparation and its
permanent bindings on incomplete reads, while the current payment opening still
refuses credentials without fresh complete proof. Keep recovery work/failure
facts, manual review for known conflicts, original consent, financial no-retry
rules and the existing bootstrap gates. No migration or wire change is needed.

Verification plan:

- Reproduce HTTP refresh failure on disposable PostgreSQL for both agreement
  and subscription point reads, with unavailable and incomplete source replies.
  All four new cases failed before the production correction.
- Verify direct explicit bootstrap retry, persisted prepared state after reload,
  unchanged acceptance/bindings, GET-only rechecks and exactly one original
  customer/agreement/subscription CREATE through synthetic transports.
- Retain seller, customer and effective-price conflict refusals, including after
  a later matching response; run focused purchase tests and canonical checks.

Focused post-fix verification: 46 PostgreSQL purchase/contention/recovery cases
passed, including all four new HTTP retry cases and three known-conflict cases.
Log: `/tmp/pr150-widget-focused.log`.

Canonical post-fix `npm run check`: PASS, including documentation, generation
freshness, architecture, Ruff formatting/lint, 1,447 fast API tests, 275 PostgreSQL
tests, 370 component tests, 38 boundary/tooling tests, web lint/typecheck and the
production web build. Log: `/tmp/pr150-widget-check.log`. PostgreSQL ran on a
separate temporary version-14 cluster with a disposable `_tests` database and
Unix socket; it was stopped afterwards. The configured application database was
not used. Local Next.js remains 16.3.1 versus locked 16.4.2; clean CI must validate
the eventual published correction. The full harness browser suite was skipped
because `RUN_E2E` and a running stack were not selected. This backend-only change
is covered through real HTTP/application/PostgreSQL paths with synthetic LBX;
no new live Widget/acquiring acceptance is claimed.

No real LBX CREATE/payment, working-database change or deployment is authorized
or performed by this correction. Baseline log: `/tmp/pr150-widget-baseline.log`.

## Owner-approved bounded customer recovery and pricing correction, 2026-10-28

The owner approved replacing one customer CREATE per explicit opening with a
bounded discover/create/recover cycle within the existing nonrenewable request
budget. UNKNOWN records uncertainty and is not a permanent customer block.
Successful complete discovery may authorize another fenced customer attempt;
failed discovery never means absence. Reuse the original customer slot,
operation, opaque key and opening's email. A saved receipt or binding permits
point recovery only. Email-uniqueness rejection switches the opening to GET-only
recovery; identity conflicts, authorization and permanent validation failures
stop. Retry temporary failures with bounded backoff. Deadline exhaustion retains
the operation for a later opening. No agreement/subscription retry policy changes.
This selected customer policy relies on LBX email uniqueness; it is not native
CREATE idempotency or a newly verified provider guarantee.

The price correction selects the latest start on/before the captured Moscow
date and rejects competing rows at that effective start only. Historical/future
ties do not invalidate an otherwise unique current offer.

- [x] Rebase ANY-709 onto main `83637fb01d446b97e9c952d3bee0862674542084`
  (ANY-669 native sharp checks); all 17 commits replayed without conflicts.
- [x] Reproduced the missing same-opening recovery and irrelevant-price cases:
  all eight new regressions failed before the fix, while both effective-date
  ambiguity cases passed. Log: `/tmp/pr150-recovery-baseline.log`.
- [x] Implement both corrections and focused synthetic/PostgreSQL regressions.
- [x] Align specification, architecture, security, schema/runbook guidance and
  Linear ANY-709 sections 4B/D6/D8 with the approved policy.
- [x] Run focused checks, independent review and the broadest supported check;
  record actual evidence and remaining limitations here.

Verification completed on the rebased working tree:

- Full canonical `npm run check` PASS (exit 0): **1,447 fast API, 285 PostgreSQL,
  370 component and 38 frontend boundary tests**; documentation, generation
  freshness, architecture, Ruff lint/format, web lint and production build,
  including main's native sharp guard. Log:
  `/tmp/pr150-recovery-canonical-final.log`. Kernel settings were isolated and
  PostgreSQL used a dedicated disposable `_tests` database owned by pytest.
- **13 focused PostgreSQL recovery/diagnostic checks** passed separately,
  including delayed visibility after email rejection, lost replies with/without
  a provider side effect, failed discovery, permanent refusal, durable receipt
  continuation, caller cancellation and deadline exhaustion. Log:
  `/tmp/pr150-recovery-final-edges.log`.
- Independent Bugbot review found no bugs. `git diff --check` passed. Rebase
  range-diff confirmed all 17 original commits retained identical patches.
- An early canonical attempt exposed a test-environment mismatch
  (`KERNEL_MOCK_ENABLED=false` instead of harness `0`); the corrected full run
  above completed all stages without test failures.
- The canonical command skipped browser E2E (`RUN_E2E` was not enabled).
  No new live LBX/payment run or Docker/runtime smoke is claimed. Installed local
  Next.js remains `16.3.1` versus locked `16.4.2`; clean CI must validate the
  locked install on the published rebased HEAD. Previous CI results do not
  establish this new HEAD's result. No migration or public wire change is added.

No live LBX CREATE/payment, working-database mutation or deployment is part of
this correction. Issue: https://linear.app/paveldik/issue/ANY-709.

## Reproduced review follow-up, 2026-10-28

The owner authorized fixes for four independently reproduced findings from PR
#150. The regression scenarios precede implementation; synthetic provider
responses are not live LBX acceptance evidence.

- [x] Preserve original financial command/history while giving a genuinely new
  explicit `PROVEN_NOT_SENT` resume its own fenced two-hour recovery window.
  Inline recovery and overdue scans must agree; GETs cannot extend it.
- [x] Keep incomplete inventory retryable without financial sends; retain the
  same purchase/hold and preserve manual review for proven conflicts.
- [x] Exclude future price scheduling from current commercial identity, retain
  immutable accepted snapshots and compare existing snapshots compatibly.
- [x] Give source-backed catalog GETs the bounded live-request deadline and
  cover delayed headers/bodies plus ordinary short-timeout controls.
- [x] Run focused PostgreSQL/frontend checks, actual Chromium HTTP verification,
  broad canonical checks and inspect the final changes before updating PR #150.

Implementation: additive migration `20261028_0004` adds a nullable active deadline
to recovery work, with original-deadline fallback for existing rows. Financial
commands, timestamps, keys and accepted/legal evidence remain immutable. The
current comparison contract is `current-terms:v2`, reproducible from stored
accepted fields without rewriting historical fingerprints. Catalog list/detail
GETs use the existing 130-second live-operation budget; local reads stay at five
seconds. Migration and normal `upgrade head` guidance are in the runbook.

Focused verification passed 12 PostgreSQL cases (including migration/old-deadline
fallback and exact schema), 29 deadline cases and web lint. The preceding broader
financial/migration run passed 69 cases; its only failure was the expected
revision-chain assertion, corrected and rechecked in the 12-case run. Two further
cases now exercise a future price becoming effective before continuation, for
both old and new stored fingerprints; they are included in the full check.
The first full check stopped on five-second timeouts in two unchanged navigation
tests. Both files passed immediately in isolation (17 tests, unchanged limits);
the next full run passed all 378 component tests. Its fast backend checks exposed
two additional exact-model assertions that still listed the predecessor columns;
those expectations now include the nullable active deadline (all eight model
contract tests passed).

Final `npm run check` PASS: 1,447 fast API tests, 298 PostgreSQL tests (including
all 12 cross-step recovery cases plus the additive migration preservation case),
378 component tests, 38 frontend boundary tests, docs, generated-artifact freshness,
architecture, Ruff, web lint and production build. Log:
`/tmp/pr150-recovery-four-fixes-canonical-final.log`. The canonical command skipped
the full browser suite; the dedicated delayed-catalog page test separately passed
desktop/mobile Chromium against that build with a synthetic 5.709-second Portal
response, actual browser fetch/time and no automatic retry. Log:
`/tmp/pr150-recovery-browser-page.log`. Both cases also passed the final rerun
with accessibility and overflow checks plus screenshots after dismissing the
cookie banner (20.9 seconds total).

Local toolchain limits: Next.js 16.3.1 vs locked 16.4.2, Vitest 3.2.7 vs locked
4.1.12, Vite 7.3.6 vs locked 7.3.7; React 19.2.8 matches. Clean exact-head CI must
verify the locked installation. Real LBX mutation/payment, deployment and an
application-database migration are outside this follow-up; migration checks used
disposable PostgreSQL only. Independent final review and human merge approval
remain pending.

## Caller cancellation correction (REV-1), 2026-10-28

The owner authorized fixing the reproduced caller-cancellation defect and then
replying to all review findings in PR #150. A caller can cancel before the work
deadline while protected HTTP cleanup outlasts it. `ensure_customer` must not
infer the cancellation owner from the clock or replace it with a billing error.

- [x] Propagate cancellation unchanged; normalize only the owning admission
  timeout outside its context, while the customer phase is still incomplete.
- [x] Exercise GET/POST cleanup, caller cancellation and owned expiry through
  both Widget bootstrap and purchase advance using disposable PostgreSQL and
  synthetic HTTP. Preserve possible-send evidence, leases and safe continuation.
- [x] Keep later payment/financial timeouts distinct from customer recovery.
- [x] Run focused and canonical checks and inspect the final diff.

Delivery includes publishing the validated fix and replying in the six human
review threads plus the Sonar cancellation finding with commit/scenario evidence.

No schema, financial retry policy, paid-access authority or live provider mutation
is part of this correction. Human review and merge approval remain separate.

Before the implementation change, the new integration matrix reproduced all four
caller-cancellation failures (GET/POST through Widget/advance); six owned-expiry
and later-phase controls passed. Log: `/tmp/pr150-recovery-caller-cancel-red.log`.
The production fix removes clock-based cancellation inference. Public entrypoints
translate the admission owner's typed deadline only while customer proof remains
incomplete, after the admission context has distinguished its own cancellation.
Source cleanup counting, active leases and permanent operation evidence remain
intact; explicit continuation recovers the same customer without an extra CREATE.
The unchanged redacted subscription-observation projection moves into its own
composition module to retain the 500-line file limit without a guard exception.

After the fix, all 57 focused customer/recovery/failure cases passed. Final
`npm run check` PASS: 1,447 fast API, 308 PostgreSQL (including the ten new
cancellation/expiry cases), 378 component and 38 frontend boundary tests, docs,
generated-artifact freshness, architecture, Ruff, web lint and production build.
Log: `/tmp/pr150-recovery-caller-cancel-canonical-final.log`; PostgreSQL took
610.70 seconds. The canonical command skipped the full browser suite. The earlier
delayed-catalog browser evidence and predecessor `39f46d7` locked-install CI are
recorded separately; new-head CI/Sonar results belong to the PR, not this local
check. Local dependency-version differences recorded above still apply.

Final diff review verified that the existing bootstrap/advance admission bodies
are AST-identical apart from the readiness marker, and the extracted observation
projection is AST-identical apart from its name. The behavior change is confined
to cancellation/owned-expiry classification. No application database migration,
live LBX CREATE/payment or deployment was performed.

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
- Customer ensure uses the owner-approved bounded discover/create/recover cycle
  above. The same customer key, slot, receipts and operation survive; failed
  discovery never authorizes CREATE and saved identity evidence allows GET only.
- Financial CREATE has a stricter policy: possible send, timeout, lost response
  or error retains the operation and purchase hold; recovery is GET-only.
  Empty discovery or expiry of the original `unknown_since + 2h` deadline never
  permits another CREATE. Only completed typed no-send evidence allows a later
  explicit advance of the same immutable request/key/history with a fresh fence
  and a separate active two-hour recovery deadline on the reused work item.
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

Current branch handoff (supersedes the historical checkpoint below): one
forward migration, `20261029_0003_normal_billing.py`, after main's unchanged
`20261001_0002`:

```text
20260924_0001 -> 20261001_0002 -> 20261029_0003
```

Databases labelled with retired `20261027_0003` or `20261028_0004` require the
guarded, verified transition in the
[current runbook](../../engineering/ANY-709-billing-runbook.md#consolidated-any-709-migration).
The old label alone does not prove that all consolidated operations ran; never
replay DDL over a matching schema or stamp over missing operations.

Historical checkpoint, 2026-10-27 (not the current migration graph):

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
