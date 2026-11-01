# ANY-709 - Normal LBX billing, product mapping and Widget flow

Status: DONE - implementation Steps 1-4 delivered; final PR acceptance IN REVIEW
Implementation completed: 2026-10-27
Last reconciled: 2026-11-01
Runtime baseline: `6288733a59897590a6813b532b281e358763c730`
Review corrections: 2026-11-01, recorded below
Program: ANY-504, Step 7
Issue: [ANY-709](https://linear.app/paveldik/issue/ANY-709)
Delivery: [PR #150](https://github.com/gushinets/payments-portal/pull/150)

This is the implementation tracker and dated delivery record. All four planned
implementation stages were delivered; their DONE statuses record those milestones.
Open review corrections are tracked below and still prevent an unconditional
final acceptance claim. PR #150 remains open and ANY-709 remains In Review.
Neither the program nor production enablement is marked complete here.

The original 26 October proposal and its execution restrictions remain available
in [Git at 2a0ae3f](https://github.com/gushinets/payments-portal/blob/2a0ae3fa14c46b80afee814b100cf71b178f6a51/docs/exec-plans/active/ANY-709-implementation-plan.md).
They are historical inputs, not instructions for current review or evidence that
today's implementation is unimplemented. Detailed delivery records before the
accidental status reset remain available at
[2442e46](https://github.com/gushinets/payments-portal/blob/2442e4631cadab5acd79300d5fb36911a73c2107/docs/exec-plans/completed/ANY-709-implementation-plan.md).

## Result and authority

An operator configures the ordinary LBX/Kernel connection and publishes an
audited product link. A verified user can review current terms, accept one
purchase, prepare its dedicated agreement/subscription and open payment in the
cabinet. Account-only viewing does not require a purchase. Accepted terms,
consent, bindings and financial operation identities remain in PostgreSQL.

Follow [ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md)
and its dated C1-C4 decisions in [ANY-504](https://linear.app/paveldik/issue/ANY-504)
plus its 1 November point-resource identity decision for normative ownership and
precise supersessions. This tracker records delivery;
it does not amend the accepted specification bodies or create provider guarantees.
The [billing runbook](../../engineering/ANY-709-billing-runbook.md) owns current
setup, publication, diagnosis, recovery, migration and verification commands.

Kernel owns enabled technical products. LBX owns commercial facts and payment UX.
Publication and new purchases use live source reads; immutable accepted history
does not become a periodic catalog mirror. Paid access, reconciliation, Kernel
enforcement and production launch remain later program work.

## Step 1 - Ordinary connection, product links and current offers

Status: DONE

- [x] Normal private connection settings reach the real Integration through
  Settings, harness and Compose; Kernel mock selection is independent of LBX.
- [x] One privileged audited CLI publishes versioned product links with
  ownership/CAS and retained history, without approval/profile files or a second
  manually maintained account ID.
- [x] Public discovery reads enabled Kernel products; detail/review reads current
  selected LBX offers with exact money, quantity, period and effective-price proof.
- [x] Ordinary price changes need no relink; accepted purchase snapshots remain
  immutable. Provider calendar selection uses the confirmed Moscow date.

Delivery began in `2a0ae3f`; wire/scope/readiness corrections followed in
`87dcf1a`. The `e8a6d89` checkpoint explicitly recorded Steps 1-2 implemented
and checked. Current regressions include
[source selection](../../../apps/api/tests/test_any709_step1_sources.py),
[publication/history](../../../apps/api/tests/test_any709_step1_postgres.py) and
[offer profiles](../../../apps/api/tests/test_any709_qa_offers.py).

## Step 2 - Optional names, shared customer and account Widget

Status: DONE

- [x] Independent optional first name, surname and patronymic; existing nullable
  names remain valid and no synthetic customer names are invented.
- [x] Explicit verified account opening uses one shared durable customer slot,
  operation and original key. Registration, login and ordinary GETs do not create
  billing objects; account viewing needs no product, seller or subscription.
- [x] Customer ensure, bounded recovery, receipts, leases/fences, Client readiness
  and read-only diagnostics share one real client and failure classification.
- [x] Fresh type-7 Widget credentials use the canonical customer binding and
  original key; final session/fence checks, no-store and SDK disposal remain.

Delivery: `a8a1d6b`, followed by customer/diagnostic fixes through `1c19f76`.
Later C3 records the bounded customer-only retry policy and its dependence on LBX
email uniqueness; local fencing alone is not native exactly-once prevention.
Customer ambiguity and narrowly evidenced original-key recovery were corrected
at `754501b`. Relevant regressions include
[shared ensure](../../../apps/api/tests/test_billing_customer_ensure_postgres.py),
[conflicts](../../../apps/api/tests/test_billing_customer_conflicts_postgres.py)
and [original-key recovery](../../../apps/api/tests/test_billing_customer_key_recovery_postgres.py).

## Step 3 - Accepted purchase, preparation and financial recovery

Status: DONE

- [x] Review/confirm APIs freeze commercial/legal terms and link revision under
  request idempotency and one user/product hold.
- [x] Durable possible-send claims precede dedicated agreement/subscription
  CREATE; provider HTTP stays outside database transactions and POST never retries.
- [x] Receipts remain candidates until authoritative owner/seller/effective-term
  proof. Financial possible-send/UNKNOWN uses GET-only recovery and retains scope.
- [x] Positive completed not-sent proof permits explicit continuation of the same
  command/key. C4 gives that new attempt a fixed active recovery window without
  rewriting original operation evidence; GETs cannot extend it.
- [x] Historical Manage uses original consent and effective terms. Preparation
  stores no paid grant, allowance or Kernel enforcement decision.

Delivery: `0477a8f`; the stage was closed at `c7efa74`. Review fixes subsequently
covered active deadlines, incomplete inventory, stale terms, every new financial
send's inventory check, origin-scope serialization and customer admission.
See [purchase scenarios](../../../apps/api/tests/test_any709_step3_postgres.py),
[inventory](../../../apps/api/tests/test_any709_subscription_inventory_postgres.py)
and [terms fencing](../../../apps/api/tests/test_any709_terms_fencing_postgres.py).
The remaining unsellable-selection recovery correction is listed below.

## Step 4 - Buy, Continue, Manage and cabinet billing

Status: DONE

- [x] Product detail provides current offers, review/consent and preparation;
  accepted purchases expose Continue/Manage and their original terms.
- [x] The cabinet lists only the user's held accepted purchases, independently
  of public catalog availability, with bounded pagination and purchase selection.
- [x] One wide cabinet Widget handles explicit account/payment viewing and
  refresh. Product Manage links retain the selected purchase across navigation.
- [x] Session changes/logout/close dispose the host; READY handling retains a
  bounded loading deadline and correlated errors. Browser callbacks grant no access.
- [x] Generated contracts, locale catalogs, Bundle 3 and one operational runbook
  support the delivered journey and later integration handoff.

Initial implementation and migration closure: `c7efa74`. The owner-approved
cabinet layout, actual payment record, refresh and SDK corrections are preserved
in [903de1e](https://github.com/gushinets/payments-portal/blob/903de1ed7100c9c37720c1c30c222ec875c0e4e8/docs/exec-plans/completed/ANY-709-implementation-plan.md).
Its section "Owner-approved cabinet billing follow-up, 2026-10-27" records one
wide Widget in the cabinet; product pages retain offers, review/preparation and
cabinet links. This superseded the original proposal's inline detail-page Widget
placement. A second product-detail Widget is not an unfinished implementation
stage. The older ticket wording still needs to be read with this recorded layout
decision; no new payment permission or architectural exception follows from it.

Relevant checks include [purchase UI](../../../apps/web/tests/components/any709-step4.test.tsx),
[cabinet UI](../../../apps/web/tests/components/any709-cabinet.test.tsx) and
[desktop/mobile journeys](../../../apps/web/e2e/any709-purchase.spec.ts).
The concurrent-opening and recovery-message corrections are recorded below.

## What changed in the plan and why

1. **26 October, `2a0ae3f`: initial proposal.** Four TODO stages, implementation
   prompts, a human-owned validation contract and an initially NOT_RUN ledger.
   This described the starting assignment; it could not report later delivery.
2. **26-27 October, `87dcf1a` through `e8a6d89`: align with implemented boundaries.**
   Added inherited Step 6 closure, capability-specific readiness, actual wire
   facts, optional-name/customer work, diagnostic simplification, shared ensure,
   current-price selection and centralized errors. Steps 1-2 became implemented
   checkpoints, and Steps 3-4 were adjusted to consume their actual contracts.
3. **27 October, `0477a8f` and `c7efa74`: record delivery.** Added purchase APIs,
   consent, financial recovery, authorized migration/test outcomes and completion
   of Steps 3-4; moved the tracker into `completed/`. Implementation DONE and
   then-pending real payment verification were separate statuses.
4. **27 October, `903de1e`: consolidate the result.** Replaced a growing mixture
   of original prompts and appended reports with a compact completed-step record.
   Retained the owner-approved single-cabinet layout and owner-run real test
   payment, plus refresh, SDK readiness and the independent-review boundary.
5. **28-31 October, `5f8b4d3` through `754501b`: review remediation.** Recorded
   contention/body deadlines, safe Widget reread failures, customer retry/price
   ambiguity, active financial windows, caller cancellation, offer ownership,
   consolidated migration, inventory/terms/dotenv fixes, origin locking and
   ambiguity/original-key recovery. These were useful implementation/evidence
   changes. Individual logs and predecessor counts were checkpoints, not totals
   to add together or guarantees for a newer binary.
6. **31 October, `2442e46`: restore specification authority.** Restored accepted
   specification bodies and moved precise C1-C4 decisions/results into the
   owning tickets. This preserved the implementation and its completion record.
7. **1 November, `22364fa`: documentation cleanup over-restored the proposal.**
   The intent was to preserve the original plan and remove duplicate reports.
   Replacing the tracker byte-for-byte with `2a0ae3f` also removed DONE statuses,
   accepted UI placement, payment evidence and review outcomes. The resulting
   NOT_IMPLEMENTED/TODO/NOT_RUN presentation no longer described delivered work.
8. **1 November, current reconciliation:** restore a compact execution record,
   completed implementation milestones and dated evidence. Keep the original
   proposal and full checkpoint journal in Git; keep open review work visible.
   Accepted specification bodies, runtime, schema and external records do not
   change in this documentation correction.

## Verification and acceptance records

The following records have different scopes. Historical real-payment evidence,
current automated checks and final PR acceptance are not interchangeable.

- **Implementation Steps 1-4: DONE.** Delivery milestones are recorded above.
  Remaining review corrections do not reset every stage to its original TODO.
- **Historical automated regression: PASS at `6288733`.**
  [CI run 41278718094](https://github.com/gushinets/payments-portal/actions/runs/41278718094)
  checked out merge-test commit `258602bf9dfd3b1d8b154cedc53b5aebc66f6492`, combining
  head `6288733` with base `ace7c27`. Observed job logs record 1,540 fast API,
  406 PostgreSQL and 384 component tests passed; browser jobs record 242 main
  cases and four React-runtime cases passed, with two conditional main cases
  skipped. Typecheck/build, migration, Compose, production images/API readiness
  and Linux/Windows harness jobs passed. Skipped cases are not a live-provider
  PASS. Automated source/SDK fixtures do not establish a new live-LBX or real
  Kernel acceptance result. This is observed CI evidence, not a new local
  full-suite execution.
- **Customer Widget: RECORDED OWNER PASS, 27 October.** Real test-account/SDK
  evidence is retained in the pre-restoration delivery record. It is not a fresh
  current-head live SDK run or a general loading-stability guarantee.
- **Purchase preparation and mapped payment Widget: RECORDED PASS.** The retained
  read-only/owner evidence identifies test client 29, seller 21, agreement 32 and
  subscription 31, with original 100 RUB/month terms. These are historical test
  identifiers, never defaults or instructions to bind a new user manually.
- **Actual test payment: RECORDED OWNER PASS on predecessor `50d833c`.** The owner
  completed a 100 RUB YooKassa Widget credit to the intended agreement. The
  checkout/admin/history observations distinguish it from a prior admin credit.
  See "Owner payment evidence and cabinet refresh, 2026-10-27" in
  [the retained delivery record](https://github.com/gushinets/payments-portal/blob/2442e4631cadab5acd79300d5fb36911a73c2107/docs/exec-plans/completed/ANY-709-implementation-plan.md).
  No later documentation change repeats that payment or certifies settlement.
- **Final PR acceptance: IN REVIEW.** Independent review of the corrections
  below and human merge approval remain open. Green CI does not
  clear a newly reproduced scenario automatically.
- **Paid access/Kernel enforcement and launch: DEFERRED.** Later ANY-504 steps
  own them; real Kernel producer conformance is ANY-711. No production rollout,
  legal approval, fresh provider-uniqueness PASS or new payment is claimed here.

## Review dispositions - 2026-11-01

The status reconciliation did not change runtime behavior. This follow-up fixes
the seven confirmed runtime/UI issues and records the two declined changes;
final independent acceptance remains separate from implementation milestones.

- [x] **Definitively unsellable original selection:** tariff archive, disabled
  product and unsupported composition use the existing fenced terms-change
  transition. Financially unsent purchases release the hold for new consent;
  prior financial effects retain it for review. Incomplete/unavailable source
  reads remain retryable without release.
  [Review thread](https://github.com/gushinets/payments-portal/pull/150#discussion_r4434901437).
- [x] **Concurrent healthy payment opens:** re-observing the same BOUND financial
  identity preserves its fence and still records subscription observations.
  Actual transitions and owner/seller conflicts retain admission protection.
  [Review thread](https://github.com/gushinets/payments-portal/pull/150#discussion_r4434901442).
- [x] **Recovered confirmation with a stale support error:** successful owned
  purchase recovery returns without the old conflict or an automatic advance.
  A failed/empty inspection preserves the original conflict and request ID.
  [Review thread](https://github.com/gushinets/payments-portal/pull/150#discussion_r4434901452).
- [x] **Four small UI/diagnostic corrections:** new Buy shares the existing
  preview's current-offer readiness; DB-only Continue/Manage remains independent
  of catalog failure. Deep-link selection shows a neutral loading option.
  Invalid operator currency is a purchase-configuration error, without gating
  account viewing. Customer-row `55P03` becomes bounded `billing_busy` 503 through
  the existing application boundary; other database failures still propagate.
  Error classification alone does not guarantee persistence of an uncommitted
  receipt, and no new retry loop was added.
- [x] **Timing hardening triaged, no change:** near-expiry authentication can
  produce a refused financial POST and GET-only uncertainty. Production frequency
  and a guaranteed request-lifetime margin remain unproven. An optional safety
  margin is not a required P2 correction; financial UNKNOWN remains GET-only.
- [x] **Point-resource self-ID decision:** the owner explicitly accepted the
  point-endpoint selection boundary in [ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md)
  at `22399f4`. The redundant response-ID-to-URL guards remain removed. Schema,
  original key, retained binding, relationship and final admission checks remain.
- [x] **Detail-page Widget triaged, no second Widget:** the 27 October cabinet
  layout decision above remains the accepted result. Product pages keep
  review/preparation and cabinet links; account-only viewing remains available
  in the cabinet independently of any purchase.
- [x] **Plan/evidence reconciliation:** implementation milestones and dated
  records restored here. Historical proposal statuses no longer masquerade as
  current delivery status; the accepted cabinet layout is visible again.

### Correction verification

- 1,549 fast API, 394 component and 38 web-boundary tests passed. Final focused
  UI regressions passed all 85 cases. Typecheck, lint, Ruff, architecture,
  generation freshness and documentation checks passed; the documentation suite
  passed 194 cases.
- The complete PostgreSQL run passed 417 of 418 cases, including all 12 new
  follow-up regressions. The existing uncertain-receipt-commit case exhausted its
  0.6-second opening deadline. Its claim and receipt variants both passed in an
  unchanged isolated rerun (2 passed). The complete run is not reported as a
  clean PASS. Logs: `/tmp/any709-review-fixes/postgres-all.log` and
  `/tmp/any709-review-fixes/uncertain-commit-rerun.log`.
- The initial `npm run check` passed its pre-build stages, then Turbopack refused
  dependencies symlinked outside this worktree. Copying the same installed
  dependencies into the worktree allowed the normal production build to pass.
  Its completed stages and separately run PostgreSQL suite are recorded above;
  no successful end-to-end canonical invocation is claimed.
- All 16 ANY-709 browser cases passed on the final production build in desktop
  and mobile Chromium, including unavailable Buy, DB-only continuation, one
  payment Widget, UNKNOWN recovery and session disposal. Screenshots were
  inspected; axe found no critical/serious violations. Log and artifacts:
  `/tmp/any709-review-fixes/browser.log` and
  `/tmp/any709-review-fixes/browser-results/`.
- Local Next.js 16.3.1 / Vitest 3.2.7 / Vite 7.3.6 differ from the lockfile's
  16.4.2 / 4.1.12 / 7.3.7; React 19.2.8 matches. These are local results, not a
  current-head locked CI PASS. External HTTP/SDK boundaries were synthetic;
  PostgreSQL was disposable and loopback-only. No live LBX write/payment,
  real-Kernel acceptance, deployment or merge was performed.

For future corrections, append the changed scenario, outcome, checked commit and
verification limits to the appropriate record. Operational procedures stay in
the runbook. Detailed predecessor logs remain available in Git; they do not need
to be copied back into the current tracker.
