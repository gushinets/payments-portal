# Port ANY-765 onto the rebuilt ANY-715

Status: **DONE** — port implementation and local review follow-up completed.
Archived: 2026-11-09 at the owner's explicit request.
Current-version live acceptance remains partial; verification limits are retained below.
Latest local result: [2026-11-10 PR #164 review corrections](#pr-164-review-corrections--2026-11-10).
The planning sequence and earlier verification entries below are historical
records of their stated snapshots, not instructions to repeat the port or a
claim that the current local diff has a complete canonical PASS.

## Historical planning baseline — 2026-11-06

- [PR #157](https://github.com/gushinets/payments-portal/pull/157): HEAD `ff4f4cd`, branch `ANY-765`, currently based on the old `ANY-715`.
- [PR #161](https://github.com/gushinets/payments-portal/pull/161): HEAD `8c49a84`, branch `refactor/any715-mvp`; still open, not merged.
- The own-change boundary is confirmed: `76ea1a7..ff4f4cd` contains exactly 16 commits and 155 changed files. Port their final result, rather than the full diff of #157 or the old step 8 fix history.
- Read the [original ANY-765 plan](https://github.com/gushinets/payments-portal/blob/ff4f4cd/docs/exec-plans/active/ANY-765-implementation-plan.md), [ticket](https://linear.app/paveldik/issue/ANY-765), ADR 0005 and the linked C1–C4 decisions. Preserve accepted purchase terms, financial identities, retry CREATE restrictions and trust in authenticated point URLs without repeated self-ID checks.

The plan was updated following verification on 2026-11-06. Code, branches and PRs were not changed while checking and editing the plan. The chosen order is to preserve the original branch as `ANY-765-OLD`, close the old PR #157 without merging, continue work in `ANY-765` and open a new PR after the port.

## Porting sequence

### 0. Preserve ANY-765-OLD and prepare the current ANY-765

- Before implementation, refresh remote refs and verify the HEADs of `ANY-765` and #161. Check that the working tree is clean and local `ANY-765` matches the original remote HEAD; do not discard local commits or uncommitted changes. Record the full original SHA as `ANY765_ORIGINAL_SHA` and separately record the selected new base SHA. If the source has changed since `ff4f4cd`, clarify the own-change boundary of step 9 before porting.
- Create `ANY-765-OLD` at the original `ANY-765` HEAD locally and on origin. Verify that both backup refs point exactly to `ANY765_ORIGINAL_SHA`. If the backup branch already exists, check its SHA first; do not overwrite an existing backup branch with different contents.
- After confirming the backup branch, close PR #157 without merging, referencing the preserved source `ANY-765-OLD` and its upcoming replacement with a new PR. Do not delete the backup branch or reopen the old PR for the new implementation.
- Continue working in the current `ANY-765` branch: after the backup, rebuild its local base on the accepted HEAD of #161. If #161 has already been merged, use the current `main` containing its accepted result; for a squash, verify the included changes. Do not create a separate `codex/...` working branch. Do not rewrite remote `ANY-765` before final verification.
- Preserve existing environments, databases and local configuration: a Git branch copy is not an environment backup. Prepare an isolated environment for the new code through the repository harness with separate Compose/database/ports; do not run migrations against the preserved database. Carry the working 60-second foreground timeout setting into the new environment.
- Port the result by subsystem from the original branch's final diff, resolving overlaps in favor of the #161 architecture. Use `ANY-765-OLD` as an immutable source for porting and comparison.

**Check:** the original SHA is preserved in local and remote `ANY-765-OLD`; PR #157 is closed without merging; work continues in `ANY-765` on the recorded new base; existing environments are preserved and the porting environment is isolated. The own diff does not restore the old step 8 implementation.

### 1. Port the preserved functionality and schema

**Almost unchanged:** `technical_terms.py`, `evidence.py`, `purchase_terms.py`, `paid_cycles.py`, `paid_allowances.py`, `paid_contracts.py`, the 100/300 development fixture and paid access models.

**Adapt:** purchase contracts/service/composition, preserving the new #161 fields and behavior, including nullable lifecycle and `agreement_closed`.

- Preserve immutable `accepted-purchase:v2`, the confirmation digest, v1 reading and exact idempotent replay. Old purchases must not receive invented limits.
- Preserve cycle classification, frozen quantities and stable allowance IDs.
- Port [migration `20261031_0006`](https://github.com/gushinets/payments-portal/blob/ff4f4cd/apps/api/alembic/versions/20261031_0006_paid_access.py) after `20261028_0005`: this base has not changed in #161. Preserve preflight, immutable history, logical allowance uniqueness and monotonic guards.

**Checks:** `test_any765_purchase_terms*`, `test_paid_access_policy.py`, `test_paid_access_terms_postgres.py`, `test_paid_access_migration_postgres.py`. Verify upgrade from #161 data, reading existing v2, preserving legacy UTC without converting it to dates and refusing unsafe downgrade.

### 2. Connect the paid writer to #161 reconciliation

**Adapt:** [shared reconciliation](https://github.com/gushinets/payments-portal/blob/8c49a84/apps/api/app/domains/billing/reconciliation.py), its composition/contracts and `paid_access.py`.

**Replace with the #161 mechanism:** the old separate transition implementation in `reconciliation_facts.py`.

- Preserve one claim/read/apply for HTTP, worker and operator, including `ReconciliationResult`, leases, fences and protection against stale ACTIVE.
- Add only step 9 calendar capabilities to the #161 normalizer: lossless precision, an inclusive single-day range, calendar anchors and an explicitly zoned finite instant. Do not derive a UTC deadline from date-only values.
- Preserve the #161 fixes: `3/1` → ENDED/BLOCKED; a closed agreement with an unavailable subscription remains a negative fact for an already bound object; missing `services` with a different price → INCOMPLETE.
- Calendar uncertainty prohibits a new allowance; an independently proven product grant follows the accepted step 9 policy.
- Apply the paid projection, semantic revision, causal audit, outbox and deadlines in the source fact's transaction. The sole `commit_paid_state` does not commit independently.

**Checks:** normalization/reconciliation suites plus paid PostgreSQL tests. Negative facts revoke access immediately without extending trust; incomplete own proof does not extend the six-hour lease. Verify `0→1`, semantic no-op, transition to empty and rollback after intermediate writes.

### 3. Integrate primary selection through shared inventory

**Adapt:** [shared `collect_inventory`](https://github.com/gushinets/payments-portal/blob/8c49a84/apps/api/app/composition/purchase_inventory.py), `inventory_contracts.py`, `discovery.py` and `background_recovery.py::apply_inventory`.

**Replace with the #161 mechanism:** the old `read_inventory_points`, `read_target_inventory`, separate background loop and source-fact application from `paid_inventory.py`.

- Shared inventory continues to apply each known object through leased reconciliation **before the next external read**. A neighboring object or final-list failure does not undo an already persisted negative fact and its paid revision/outbox.
- Add bounded primary evidence to the result: product-scoped candidates, completeness, references to committed observations and the corresponding fences/versions. Do not apply source facts again.
- For eligible proof without a primary, enqueue an urgent hint for the existing `customer_inventory` job. Select the first primary after complete inventory; do not introduce recursive reconciliation → inventory → reconciliation with new discovery.
- Final selection revalidates evidence freshness under user/product locks. Preserve the union with local candidates, no automatic promotion and the trusted-primary policy.
- A newcomer triggers the corresponding review while preserving an independently confirmed primary. Permanent bindings of another product remain that product's bindings even in review.

**Checks:** `test_billing_scoped_inventory_postgres.py`, `test_paid_access_rebase_postgres.py`, `test_paid_access_inventory_failure_postgres.py`. Add failure of the very next point-read after a successful owned block, both candidate orders, timeout/cleanup/final-list failure, membership change and claim loss. Verify that the first primary is prohibited with incomplete relevant inventory; an already committed negative survives a later inventory failure.

### 4. Adapt recovery, restrictions, operator and worker

**Recovery — use the #161 mechanism; do not port the old implementation:** use #161 `purchase_recovery.py` and `preparation.py`. The first binding remains preparation-only; BOUND goes through shared reconciliation. UNKNOWN does not permit a new financial CREATE.

**Restrictions — adapt:** `customers.py`, `customer_reviews.py`, `customer_conflicts.py`, `financial.py` and `background_recovery.py`.

- Preserve #161 `restrict_subscription`, fence rotation and invalidation of old leases.
- Connect the paid commit to existing transaction endings after all restrictions. A customer conflict revokes all dependent products atomically; a product conflict restricts its own scope.
- The old `purchases/review.py` must not replace the newer restriction logic.

**Operator — adapt:** `operator_cases.py`, `operator_review.py`, `operator_contracts.py`, `billing_operator.py`.

- Preserve shared `restore-original`/`bind-original`, exact related-case checks and #161 audit.
- Add the preserved `select-primary` for an already bound, freshly verified subscription. Distinguish the primary-case being resolved from a financial admission conflict; do not clear unrelated reviews.

**Worker — adapt:** `work.py`, `jobs/billing.py`, `billing_worker.py`, queue queries and `paid_deadlines.py`.

- Add local deadlines/repair without a second scheduler. Local reductions work without LBX configuration.
- Preserve retry acknowledgement, generation/lease ownership, urgency and the #161 fixes, including REV-8.
- Preserve the 60-second worker timeout and working 60-second foreground override with Compose forwarding; the application default foreground timeout remains 10 seconds.

**Checks:** #161 recovery/operator/worker suites and paid recovery/cadence/scope-conflict suites. Same-cycle recovery returns the previous IDs; a proven next cycle creates one new set without backfill. Verify stale ACTIVE after restriction/restore, product independence, provider-free expiry, restart/repair, SQL NULL/JSON null and the refresh/expiry race.

### 5. Port authenticated read and the account cabinet

**Almost unchanged:** `paid_read.py`, `paid_router.py`, paid-read queries, `PaidProductAccess.tsx`, `use-paid-access.ts`, the API adapter and locale copy.

**Adapt:** `AccountBilling.tsx`, purchase presentation, wiring/settings and documentation to the polling-only #161 base.

- Preserve local authenticated `GET /api/paid-access`, no-store, session guards and the absence of LBX/Kernel calls.
- An overdue unprocessed deadline returns `paid_access_deadline_pending`; GET does not filter the document or write state.
- Generate OpenAPI/TypeScript through `npm run generate`. Preserve Bundle 3, no invented usage/remaining and the distinction between confirmed empty/unavailable.
- Update the existing ANY-765 plan and runbook for the final integration.

**Checks:** paid-read PostgreSQL, cabinet/session component tests, synthetic Playwright desktop/mobile and accessibility.

## Final acceptance and publication

- Run focused checks during the stages. On the assembled HEAD, perform the agreed final QA: two products, first grant, block/unblock, ended, incomplete/outage, recovery without a new allowance, next cycle, concurrent product updates and atomic outbox while preserving delivery bookkeeping.
- Verify failure before commit and restart after commit: either the entire transition rolls back, or facts/state/revision/outbox are preserved together. Do not treat rollback to a clean #161 build on a populated v2/`0006` database as a supported rollback.
- Run `npm run check` with worktree-local PostgreSQL and the affected browser journeys. Separately inspect the final diff for restored removed handlers and duplicate source writers.
- In the final report, show the working-code increase relative to the selected new base and its size change relative to `ANY-765-OLD`; count tests, documentation and generated files separately. Use the same paths and counting rules for both comparisons. Explain new integration modules and verify that they do not duplicate #161 reconciliation, inventory, recovery, scheduler or source writer. The goal is to preserve step 9 functionality on the shared implementation; do not introduce an arbitrary line limit or a new general refactoring.
- Separately verify the real **LBX → authoritative observation → paid state/revision/outbox → authenticated API → account cabinet** on a supported purchase. New real billing mutations require separate permission. Record an unavailable checkpoint as BLOCKED/NOT_RUN; simulation does not satisfy live acceptance. ANY-819/821, Kernel enforcement and production enablement remain separate tasks.
- After local verification, compare remote `ANY-765` again with `ANY765_ORIGINAL_SHA` recorded in stage 0. If others have added commits, stop the overwrite and first agree on including them. Verify that remote `ANY-765-OLD` is preserved and check the selected new PR base; if the base has changed, incorporate the necessary changes and rerun affected checks.
- Update the existing branch with an explicit lease. Before running the command, ensure that the current branch is `ANY-765`, HEAD matches the verified result and `ANY765_ORIGINAL_SHA` contains the full SHA from stage 0. Do not replace it with a newly read remote HEAD just to make the push succeed:

  ```bash
  git push \
    --force-with-lease="refs/heads/ANY-765:${ANY765_ORIGINAL_SHA:?Original SHA from stage 0 is required}" \
    origin HEAD:refs/heads/ANY-765
  ```

- Create a new Draft PR from `ANY-765` into `refactor/any715-mvp` if #161 is still open, or into the corresponding `main` after it is merged. In the description, include ANY-765, the replaced PR #157, backup branch `ANY-765-OLD`, the accepted result and current checks. Link the new PR in closed #157. Verify that the new PR's own diff contains only step 9 and the necessary adaptation to #161.
- After #161 is merged, rebase `ANY-765` onto the corresponding `main` and change the new PR's base; for a squash, port only the own step 9 result. Verify the final diff and required CI on the published HEAD and final base. The PR remains Draft until successful acceptance; old #157 remains closed. Merge requires human approval.

## Local review corrections — 2026-11-08

Scope: the uncommitted result on `867241cacdbee8fe787445f7f5104742639dbbd3`,
including the rebuilt ANY-715 ancestry. No commit, push or PR update is requested.

- P2-1: check the accepted technical metric's current ownership, unit and
  enablement before each genuinely new financial send. Preserve accepted
  quantity, original identities, linked reconciliation and GET-only recovery.
  Verify refusal before agreement/subscription CREATE, safe resumption and
  unrelated capability/current-quantity changes.
- P2-2: expose product-competitor and subscription-metric cases in scoped
  operator diagnostics. Keep the audited resolution case set unchanged; test
  unrelated scope exclusion and refusal to resolve these diagnostic cases.
- ARCH-1: reserve paid-read DB and framework worker capacity outside sale/source
  pools, with bounded admission and retained cancellation/shutdown ownership.
  Verify real HTTP/PG reads while purchase authentication exhausts the ordinary
  DB pool and shared thread limiter, plus overload and cleanup.
- ARCH-2: pass the worker DB delegate through concurrent-first-binding recovery
  into shared reconciliation. Verify cancellation retains the committing DB
  owner in both the recovery race and ordinary reconciliation control.

Run focused regressions, relevant recovery/operator suites and the broadest
supported canonical checks; record results after verification. DOD-1 live LBX
acceptance remains NOT_RUN and is not replaced by synthetic test results.

Verification of the local corrections, 2026-11-08:

- `npm run check`: **PASS**, exit 0, with isolated source configuration and
  disposable local PostgreSQL. Documentation, generated freshness, architecture,
  Ruff, web boundaries/lint and production build passed; API fast **1,752**,
  PostgreSQL **911**, web component **414** tests passed.
- The **27 added PostgreSQL scenarios** cover capability changes before either
  financial CREATE, immutable quantity and safe resumption, diagnostic scope
  isolation/resolution refusal, worker cancellation ownership, DB/thread
  saturation and reader overload/cancellation. Real lock/statement timeouts
  return retryable `paid_access_busy`; another SQL error retains the ordinary
  failure boundary. A subsequent read succeeds without paid-state mutation.
- Affected Playwright purchase/Widget/paid-cabinet journeys: **18 PASS** across
  desktop/mobile, no retries or skips. Canonical `RUN_E2E=false` is explicit;
  those browser checks ran separately against the final build.
- Actual local Portal HTTP/PostgreSQL/browser integration: **15 PASS**, no
  JavaScript errors, including fresh API and paid-read pool recreation. LBX and
  Kernel transports were synthetic; this is not live-provider acceptance.
- Changes remain local and uncommitted. DOD-1 actual LBX purchase-to-cabinet
  acceptance stays **NOT_RUN**; no real billing mutation or external publication
  was performed.

## Base refresh — 2026-11-09

Issue: https://linear.app/paveldik/issue/ANY-765

- Original Step 9 HEAD: `7a2a4d8cc13d9b007c550813d0f4c1bdff2b7fca`,
  preserved locally as `codex/any-765-before-715-rebase-20261109`.
- New base: `refactor/any715-mvp` at
  `ed642a75f00d7bbac7713b14a610b90b6b83534c`, verified against GitHub.
  Replay only the ten Step 9 commits after the original base `09bda5a`.
- [x] Preserve durable uncertain-create pause, notification retry and explicit
  GET-only original recovery together with transactional paid-access reductions.
- [x] Preserve complete-read trust provenance in the shared paid deadline
  scheduler, deadline repair and deterministic expiry writer.
- [x] Preserve both `inspect-operation` and `select-primary` CLI capabilities.
- Inventory completion now lives with primary decisions in the existing
  `app/domains/billing/discovery.py`; recovery/pause transactions remain in
  `background_recovery.py`. Both fit the existing 500-line architecture limit.
- Trust provenance selects the complete observation whose read-start matches
  the stored trust interval. Complete blocked reads still revoke paid access
  without renewing trust, preserving Step 9's existing policy and Step 8 history.
- [x] Verify inherited recovery/trust regressions, paid deadlines, stale owners,
  unchanged allowance identities and atomic revision/outbox changes.
- [x] Run the broadest supported canonical checks and affected browser journeys;
  record evidence and review the final range-diff.

This refresh is local. No push, PR change, live billing mutation or Kernel
rollout is included; existing live-provider acceptance remains NOT_RUN.

Verification:

- `npm run check`: **PASS**, exit 0. API fast **1,769 passed**, PostgreSQL
  **956 passed**, web components **414 passed**. Documentation, generated
  freshness, architecture, Ruff, web boundaries/lint and the production web
  build passed. The PostgreSQL partition completed in 49m48s.
- Focused recovery/trust, paid-access, inventory and CLI selection: **230 passed**
  (**206 PostgreSQL**, **24 unit**).
  Four new PostgreSQL cases verify trust provenance after paid revocation,
  including complete blocks, missing queue repair and pre-fix payload repair.
  Existing allowance-expiry and CLI tests also verify the next deadline payload
  and coexistence of `inspect-operation` / `select-primary`.
- Synthetic purchase/Widget/paid-cabinet Playwright against the fresh production
  build: **18 passed**, desktop and mobile, including accessibility, without
  retries or skips. Canonical `RUN_E2E=false` is explicit; these affected journeys
  ran separately. The full unrelated browser suite was not run.
- The canonical PostgreSQL partition and focused tests used separate disposable
  databases on the worktree test server. Pytest owned their creation and cleanup;
  no application database was migrated. Live sources and Sentry were disabled.
- Local evidence: `.harness/any765-rebase-check.log`,
  `.harness/any765-rebase-focused.xml`, `.harness/any765-rebase-browser.log` and
  `.harness/any765-rebase-browser-results/`.
- Review: all ten original Step 9 commits are preserved. The replay change is
  confined to recovery/deadline/CLI integration; inventory completion was moved
  into existing discovery ownership to satisfy the unchanged architecture limit.
  Its AST matches the original writer apart from the owner/import move. Expiry
  fixtures retain their original source-proof timestamps. The final own history
  contains the ten replayed commits and one integration follow-up.
- Peer impact: **None**. This refresh preserves the existing Portal paid wire
  and ownership boundaries; no Kernel producer/consumer contract or conformance
  status changes.

## Local review follow-up — 2026-11-09

Issue: https://linear.app/paveldik/issue/ANY-765

Reviewed baseline: `ac8743ff35c5cfaf0fdaf108fa89ad5e71bf49cd`, based on
`refactor/any715-mvp` at `ed642a75f00d7bbac7713b14a610b90b6b83534c`.
Apply locally without changing branches, publishing, or altering the concurrent
ANY-766 documentation work.

- [x] P2-3: use complete relevant product inventory for audited primary selection;
  preserve customer identity, conflict, provenance and final local-version checks.
  Ordinary financial admission continues to require complete customer inventory.
  Cover unrelated incomplete proof and controls for incomplete relevant proof
  and failed discovery through the real PostgreSQL/operator path.
- [x] ARCH-3: separate the selected technical meaning used for confirmation from
  whole-source audit fingerprints. Keep immutable full evidence and exact replay
  of existing v2 purchases. Cover unrelated metric/quantity/version changes,
  selected changes and historical digest compatibility.
- [x] DOD-2: restore a compact current Step 10 handoff in the billing operations
  runbook, including decision/provenance, locks/fences, cycle/allowance identity,
  revision/outbox, B10 compatibility, configuration and evidence limits.
- [x] Run focused regressions and the broadest supported canonical checks;
  record results and inspect the final local diff.

DOD-1 remains partial: the actual Widget/LBX/worker/cabinet path passed on
`7a2a4d8`, while current-HEAD live acceptance and live allowance issuance were
not established. These fixes authorize no real billing mutation and do not
replace that checkpoint with synthetic evidence.

Verification of the local follow-up:

- The 13 new PostgreSQL/HTTP/operator scenarios first reproduced **4 FAIL / 9
  PASS**; after the fixes all **13 PASS**. Controls retain refusal for incomplete
  relevant proof, failed discovery and changed selected terms. Successful cases
  retain complete fresh audit evidence and exact historical v2 replay.
- Focused existing operator-primary authorization/refusal and immutable allowance
  scenarios: **14 PASS**. Pure purchase-terms tests: **18 PASS**.
- Canonical checks passed documentation, generated freshness, architecture, Ruff,
  **38** web boundary/tooling checks, **414** web component tests, web lint,
  **1,769** API fast tests and the production build. The initial attempt used an
  incorrect diagnostic environment (`OTEL_SDK_DISABLED` and the harness's Kernel
  mock flag spelling); after correcting only that temporary runner, the affected
  observability/documentation controls passed **206/206** and the canonical
  pre-PostgreSQL checks passed in full.
- The full **969-case** PostgreSQL partition was **INTERRUPTED** at approximately
  **70%**, at the user's request to limit remaining testing. No failure had been
  reported before interruption; this is not a complete PostgreSQL PASS or a
  successful aggregate `npm run check`. Remaining broad PostgreSQL and browser
  suites were not run. The changed paths have the focused passing results above.
- Final documentation and `git diff --check` passed. Logs are retained locally at
  `/tmp/any765-fixes-red.log`, `/tmp/any765-fixes-green.log`,
  `/tmp/any765-fixes-focused.log`, `/tmp/any765-fixes-check-final.log` and
  `/tmp/any765-fixes-docs-final.log`.
- No migration or public wire shape changed. Historical full-source buyer
  digests remain read-compatible; older pre-fix readers cannot consume new
  selected-digest acceptances. The runbook records this rollback limitation.
- Work remains uncommitted at the reviewed ANY-765 HEAD. The active branch was
  ANY-766 initially and ANY-765 at handoff, with the same SHA; the agent did not
  switch branches. Concurrent ANY-766 documentation is preserved. No commit,
  publication, real billing mutation or Kernel change was performed. The two
  disposable databases were removed, the test-only PostgreSQL server stopped,
  and the pre-existing runtime files restored.

Documentation consistency follow-up:

- Aligned the current README, architecture/product maps, API guide, reliability,
  security, deployment and development guidance with implemented Step 9.
  Confirmed 27 ORM tables and the five-revision chain ending at `0006` without
  connecting to a database. Corrected `0003` forward-upgrade instructions and
  separated the pre-Step-4 reset from retired ANY-709 label transitions.
- Removed repeated settings/recovery/source-policy prose from the handoff and
  clarified product-scoped primary selection and trusted-primary competitor
  diagnostics. Review follow-up REV-1 corrects the calendar distinction: missing,
  sentinel or contradictory cycle bounds prevent metering, while otherwise
  complete eligible product proof may grant access and refresh finite trust.
- REV-2 updates current implementation status in the contour map and ADR 0005;
  its accepted ownership/precedence decisions remain unchanged.
- Refreshed the integration map from pinned Kernel `72ff15bc` source: Manifest
  producer exists; paid HTTP integration and conformance/enablement gates remain
  separate. Linked historical mock/handoff statuses to that current map; removed
  repeated contract summaries and obsolete commercial/auth/locking debt entries.
  Quality grades remain explicitly tied to their dated verification baseline.
  No peer files or accepted specification bodies were changed.
- Marked this porting sequence and its old PASS/NOT_RUN entries as historical;
  the latest local result remains the partial canonical run recorded above.
- Validation: `npm run docs:check`, **195 repository-doc tests** and
  `git diff --check` passed. Application code/tests are unchanged by these
  documentation passes; no PostgreSQL/browser/full application suite was rerun.
  The owner removed the accidentally included ANY-766 plan; its dangling index
  link was removed. The ANY-765 plan was marked DONE and moved to `completed`
  at the owner's request, with its evidence limits preserved.

## PR #164 review corrections — 2026-11-10

Issue: https://linear.app/paveldik/issue/ANY-765

Baseline: `7f985031034f45fde0203f710eb64283cd086e86`. The owner authorized
local fixes only, without staging, commits, publication or live billing changes.
The preceding completed port and evidence remain historical records.

- [x] Preserve a proven finite subscription end across less precise rereads,
  block/recovery and restart using normalized, permanently scoped observation
  history. Retain the exact supporting observation; allow explicit new proof
  to establish a changed end. Keep source trust separate from that boundary.
- [x] Commit overdue effective boundaries before replacing source support.
  Reuse the single semantic writer under the existing user lock and transaction;
  retain both causal revisions, unchanged same-cycle allowance identity and
  final coalesced outbox/deadline scheduling.
- [x] Isolate candidate-local inventory failures to affected products while
  retaining customer-wide financial refusal, final discovery verification,
  global failures and already committed negative facts.
- [x] Normalize explicitly zoned calendar-month anchors at the LBX boundary,
  preserving their offset and date-only/unresolved precision rules.
- [x] Add focused regressions and controls, run the agreed necessary checks,
  update the runbook and inspect the complete local diff. The owner requested
  stopping the full PostgreSQL run after focused verification passed.

Pre-fix validation reproduced all four findings: 12 diagnostic cases produced
7 defect failures and 5 passing controls; 103 existing focused tests passed.
These are deterministic local tests with synthetic external transports, not
new LBX, Kernel or production acceptance.

Local implementation evidence:

- New checked-in pre-fix scenarios: **11 FAIL / 3 PASS** before the changes.
- Focused policy/reconciliation/primary/inventory/recovery coverage: **142 PASS**.
- Final new PostgreSQL regressions and controls: **26 PASS**. They cover finite
  end precision loss, block/recovery and fresh connections; accepted versus
  incomplete extension evidence; expiry-before-refresh and rollback; preservation
  of another product; subscription/agreement point failures versus global
  budget/auth failures; and primary selection with independent source history.
- Runtime changes reuse the existing observation store, semantic writer,
  transaction, inventory and queue. No schema migration, public HTTP contract,
  purchase terms or already-issued allowance tuple changed.
- Completed canonical phases: documentation, generated-contract freshness,
  architecture, Ruff lint/format, web boundaries, **414 web component tests**,
  web lint, **1,771 fast API tests** and the production web build all passed.
- Full canonical PostgreSQL phase: **INTERRUPTED at the owner's request**, with
  **550 PASS** and no reported failures before interruption. This is partial
  evidence, not a full canonical PASS; the focused suites above are the agreed
  verification for these corrections. No further full PostgreSQL run is planned.
- Tests used a disposable native PostgreSQL **14.24** cluster under `/tmp`,
  with synthetic external transports. Test-only `fsync=off` reduced filesystem
  synchronization overhead; this run makes no physical crash-durability claim.
  The private server was stopped after graceful test interruption. No application
  database or shared PostgreSQL configuration was changed.
- Browser/E2E and live LBX/Kernel acceptance were not run. No dependencies were
  installed; nothing was staged, committed or pushed. Evidence is retained under
  `/tmp/any765-pr164-validation-X5LIYY/` (`fixes-red.log`, `fixes-focused.xml`,
  `fixes-additional.xml`, `fixes-check.log`).
