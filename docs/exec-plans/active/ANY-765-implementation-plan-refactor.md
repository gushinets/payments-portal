# Port ANY-765 onto the rebuilt ANY-715

## Verified baseline

- [PR #157](https://github.com/gushinets/payments-portal/pull/157): HEAD `ff4f4cd`, branch `ANY-765`, currently based on the old `ANY-715`.
- [PR #161](https://github.com/gushinets/payments-portal/pull/161): HEAD `8c49a84`, branch `refactor/any715-mvp`; still open, not merged.
- The own-change boundary is confirmed: `76ea1a7..ff4f4cd` contains exactly 16 commits and 155 changed files. Port their final result, rather than the full diff of #157 or the old step 8 fix history.
- Read the [current ANY-765 plan](https://github.com/gushinets/payments-portal/blob/ff4f4cd/docs/exec-plans/active/ANY-765-implementation-plan.md), [ticket](https://linear.app/paveldik/issue/ANY-765), ADR 0005 and the linked C1–C4 decisions. Preserve accepted purchase terms, financial identities, retry CREATE restrictions and trust in authenticated point URLs without repeated self-ID checks.

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
