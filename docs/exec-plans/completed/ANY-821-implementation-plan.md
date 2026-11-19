# ANY-821 - Terminal resolution for UNKNOWN purchases

Status: Implemented on ANY-821, including audited-object recovery and first-binding ownership checks.
Updated: 2026-11-19
Execution branch: `ANY-821`
Issue: [ANY-821](https://linear.app/paveldik/issue/ANY-821/define-and-implement-terminal-resolution-for-purchases-stuck-in)

## Goal and verified context

Provide an audited operator action that safely completes a stuck purchase and
allows a new attempt, preserving original identities and accepted history.
Deliver one coherent change in three parts.

Follow [AGENTS.md](../../../AGENTS.md), [ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md),
the [delivery workflow](../../engineering/AGENT_WORKFLOW.md), their linked coding
and testing guidance, and the [Kernel integration map](../../integrations/platform-kernel.md).

Planning checkout: `ANY-821` at `2d278f62`; compared main: `6e3d458a`.
The following PR snapshots informed implementation decisions on 2026-11-16:

- [ANY-832 / PR 168](https://github.com/gushinets/payments-portal/pull/168),
  [20eacc5d](https://github.com/gushinets/payments-portal/commit/20eacc5dfb7e20551ae3c40c1c67d941b1e0f3ff):
  already owns inventory relationship history, product-impact classification and
  receipt validation. Preserve these owners rather than duplicating them.
  Its retained-history writer still requires an active hold, so released
  purchases need the narrow historical path described below.
- [ANY-766 / PR 167](https://github.com/gushinets/payments-portal/pull/167),
  [3b94b7df](https://github.com/gushinets/payments-portal/commit/3b94b7df009e58b5b565861ff5c543722b935474):
  already retains activation history and atomically updates recipient outboxes
  through the shared paid-state writer. Use that writer, not separate delivery
  machinery. Its cabinet still rejects `scope_held=false`; migration head is
  `20261113_0013`.
- [ANY-864 / PR 171](https://github.com/gushinets/payments-portal/pull/171),
  [1dea1b98](https://github.com/gushinets/payments-portal/commit/1dea1b986672c3cdc4a3c103ae1760d4403e2dd1):
  fixes monthly allowance calendar interpretation. Preserve its regressions;
  it creates no extra purchase-resolution implementation work.

These planning snapshots support automatic release only for changed terms
before a possible send. The
[current schema reference](../../architecture/payment-portal-data-model.md#physical-baseline)
records the integrated Portal migration chain.

## Original implementation plan

Before runtime edits, establish focused failing regressions for the affected
resolution, worker and UI behavior. Reuse existing recovery and audit coverage.

### 1. Add audited operator completion

- Add one `resolve-purchase` CLI action using `ManualReviewCase` for audit:
  principal, reason, reference, evidence and original identities. Reuse digest
  helpers to expose the expected state in `inspect` and reject stale decisions.
- Release only when every original financial operation is proven not sent,
  definitively confirmed by LBX to have had no effect, or its created objects
  are confirmed safely terminal. Check both operations in partial preparation.
  A found live original uses existing GET-only recovery, never another CREATE.
- Cancellation is operator-only, including proven-not-sent cases. For possible
  sends, stop actual sending API/worker processes before obtaining final LBX
  confirmation; audit the ordering and request-specific evidence. Empty discovery,
  elapsed time or disabling workers is insufficient. Without proof, retain the
  hold and resume ordinary operation.
- Under existing business locks, atomically record the resolution, fence old
  work, set the terminal result and `resolved_at`, and release only this hold.
  An identical repeat returns the saved result before requiring an active hold.
- Use `resolved_no_external_effect` for proven absence of effect. Add
  `resolved_external_terminal` for retained objects that were created and ended;
  update the canonical enum, database constraint and generated API contract.
  Preserve original requests, bindings, UNKNOWN evidence and accepted terms.

### 2. Preserve terminality and replacement-purchase isolation

- Exclude completed purchases from recovery reenrollment after restart. Reject
  stale claims and results without reviving the old flow or modifying its
  replacement. Preserve normal active-writer hold checks.
- Recognize late original objects using retained purchase/operation identities.
  They receive no automatic access or cross-purchase adoption. Route unsafe
  findings to existing manual review; the same operator action must support
  resolving the exact late-object case after its original hold has gone.
  Keep financial CREATE blocked until those cases are resolved, independently
  of later listing results.
  Preserve ANY-832's inventory owners and strict financial admission on integration.
- Keep completed purchases ineligible in the existing paid-access dependency
  checks and call the shared reducer in the resolution transaction, preserving
  ANY-766's activation history and outboxes without quota resets or Kernel calls.

### 3. Show the outcome and verify the complete flow

- Update existing pending/review copy with recovery or support as the next
  action. Show terminal outcomes through the existing purchase GET and cabinet
  `?purchase=<id>` link, allowing inspection after the hold is released and
  offering navigation to a new purchase.
  Preserve ANY-766's usage UI when combining this existing-screen change.
- Extend the existing billing operations runbook with the stop-confirm-resolve
  procedure, evidence requirements, partial preparation and late-object handling.
- Cover no-send, lost-response recovery, insufficient evidence, the existing
  two-hour escalation, partial preparation, terminal objects, repeated commands,
  restart, stale-worker races, late discovery after a replacement, user/product
  isolation and UI reload. Use PostgreSQL for transaction and migration behavior.
- Give the ANY-821 migration a distinct revision from its actual main parent.
  Join the independent ANY-821/ANY-766 heads with a merge revision during
  integration; do not rewrite published ANY-766 migrations. Verify both upgrade
  paths and the combined head.
- Run focused tests, `npm run generate`, and the broadest supported canonical
  checks; record skips and limitations. Check the touched inventory, paid-state,
  migration and cabinet seams in an isolated combination with the pinned PRs.

## Scope and progress

No new tables, HTTP endpoints, background processes, full purchase-history UI or
universal `available_actions`. Keep the two-hour escalation policy and existing
financial CREATE safeguards. Foreground latency remains ANY-819; production
enablement and real-provider gates remain with their existing owners.

- [x] Operator completion and minimal state/contract migration.
- [x] Terminal guards, late-object handling and shared paid-state integration.
- [x] Existing-screen presentation, runbook and focused verification.

## Review and verification

- GET-only recovery uses permanent bindings and positively attested IDs for both
  financial operations. It checks a known subscription independently of a failed
  agreement read. Searching without a subscription ID requires an unambiguous
  agreement. A disproved receipt alone cannot establish ownership.
- The late-case writer rechecks bindings and audit evidence under the user lock,
  including attestations made during the GET. Only an observation of the same
  relationship completed by the confirmation time can be dismissed as delayed.
  Positive attestation supersedes older disproof. Earlier commands remain replayable.
  First binding and attestation serialize by account, object kind and ID across users.
- The worker records a proven late original on its released purchase. The case
  blocks new financial CREATEs for that customer and first-primary selection
  for implicated products, even after a listing omission. Trusted primaries
  continue normal reconciliation. A listing discrepancy alone pauses admission.
  A second purchase keeps its operation, fence and receipt unless its own
  evidence proves a conflict.
- A retained subscription listed as ended requires a current point read within
  the existing 20-candidate limit. The cabinet uses the active list for a held
  purchase and the individual terminal status for a released purchase.
  The [operations runbook](../../engineering/billing-background-operations.md)
  documents the proof and operator procedure.

The seven ticket cases are exercised through unsent completion and restart,
GET-only recovery after a lost reply, empty discovery with the hold retained,
late discovery after operator action, separate proof for a partial purchase,
two-hour escalation, and repeated/concurrent actions with a replacement.

Before the rebase, 86 focused tests and 1,289 PostgreSQL tests passed with
disposable PostgreSQL 18.6 and synthetic LBX. Those runs covered the stale
listing's effect on the original purchase. On November 19, checking the other
held purchase exposed two false manual reviews, with and without a different
CREATE receipt. Both failed on the held purchase's persisted state before the fix.

On the rebased branch, both cases preserve the held purchase, operation, send
fence, receipt and open reviews. Once the original case closes, GET-only
recovery binds the held purchase's own subscription. A confirmed conflict on
its dedicated agreement or CREATE receipt still opens a case on that operation.
The focused run passed 92 tests covering all seven scenarios, ownership races,
monthly allowances and Alembic. A Windows-only Mako path test skipped on Linux.

On November 19, the canonical check passed documentation, generated contracts,
architecture, lint, 503 web tests, 2,413 fast API tests and the Webpack build
using cached fonts. One Windows-only fast test skipped on Linux. On PostgreSQL
14.24, 1,292 of 1,297 tests passed on the first four-worker run. Three fixture
queries, one purchase preflight and the two-consumer Portal/Kernel probe timed
out. All five passed on a serial retry with the same code and deadlines.
Four separate Playwright runs on the production build passed on desktop
Chromium and Pixel 7 with synthetic billing, including held and released deep
links. The full live-stack browser suite was outside this run.

### Integration with main and ANY-832

ANY-821 was rebased onto `f6b1f1d2`, including the ANY-864 monthly LBX calendar
and the ANY-741 Mako update. For integration with ANY-832 at `f7639e1a`, keep
its inventory fact collector and product projection, and incorporate ANY-821's
released-purchase lookup and case attribution. The three-way preview also
found overlaps in LBX calendar normalization and reconciliation. Preserve the
monthly instance-start rules, annual and established calendar anchors, and the
point evidence from the same GET. The documentation overlaps in the index and
schema reference were update dates. Verify first-primary selection and both
calendar profiles on the eventual combined tree.

Earlier verification covered the Webpack production build with cached Manrope
files and held and released deep links in desktop Chrome and Pixel 7, including
keyboard focus, layout and billing-section axe checks. Temporary combinations
with PR #168 at `900e3f2c` and PR #171 at `3e9c1273` passed 70 and 83 selected
tests respectively. These results apply to their recorded snapshots.
