# ANY-897 — Automatic paid access activation after LBX payment

Status: implementation complete; QA timing target met; repository verification open.

[Linear ticket and QA baseline](https://linear.app/paveldik/issue/ANY-897/reduce-the-wait-for-paid-access-after-lbx-payment)

## Expected behavior

The buyer opens the payment Widget and pays in LBX. Portal automatically checks
the selected subscription. The cabinet shows that activation is being checked
during polling and final reconciliation. Once access is committed, the cabinet
shows it automatically. The cabinet shows that activation is still unconfirmed
when the check ends without access or when existing local evidence confirms
waiting and the accelerated job was never saved. Scheduled reconciliation
continues with the tab closed. Use the Russian messages recorded in Linear.

## Server and worker

1. **Start after successful Widget preparation.** Enqueue via `BackgroundTasks`
   after sending the successful payment Widget response for an owned, linked
   purchase that still holds its product scope. Require the fresh Widget proof
   to report the normalized LBX waiting-for-activation state and require the
   selected subscription to have no current or prior paid primary selection.
   Use the existing lifecycle normalization, primary binding and retained
   selection evidence.
   Pass the server-verified identifiers and DB-clock `prepared_at` to the
   callback, which rechecks eligibility and performs one short PostgreSQL write
   with a lock-wait limit. Log enqueue failures. If the callback is lost or the
   write fails, the buyer can pay and the original scheduled reconciliation
   can grant access without a repeat visit. The cabinet shows accelerated
   checking only after the window is saved.
2. **Persist and reuse a bounded window.** Add a work kind to the existing queue
   and enforce uniqueness by LBX account and subscription in PostgreSQL and
   SQLite. Store `prepared_at`, the window deadline, completion time and a
   typed completion reason for activation detected, window expired or purchase
   ineligible. The first committed enqueue fixes the deadline from its
   `prepared_at` and the configured duration. Start QA at five minutes. Reuse
   the job for repeats. To start another window,
   require a new explicit opening whose `prepared_at` is at or after the prior
   deadline plus five seconds and, if a handoff occurred, its 60-second display
   deadline. Require fresh eligibility, no live worker lease and time remaining
   in the new window at enqueue. Compare the captured opening timestamp with
   these bounds so a delayed callback from an earlier opening cannot start a new
   window or change the old deadline or cadence.
3. **Run one logical point read per attempt.** Run the new job in the normal
   lane after due regular jobs, with trust-expiry priority promotion disabled
   for this kind. Use 20-second slots anchored at `prepared_at`, with the first
   read due at 20 seconds. Skip missed slots and allow at most one attempt per
   slot. After a failed attempt, the next eligible slot starts at least 40
   seconds after that attempt started. Each attempt reads only the saved LBX
   subscription. A logical read may include the LBX client's bounded transport
   retries or reauthentication. Bound the wait to five seconds and retain
   resource ownership through existing cleanup.

   Schedule one closing read at the saved deadline, subject to the same
   eligibility and error backoff. Allow that read and its handoff only through
   five seconds after the deadline, including any delay picking up the job.
   Earlier reads must complete by the saved deadline. If the closing
   read cannot run within its budget or still shows waiting, expire the window
   and continue on the regular schedule.
4. **Hand off to regular reconciliation.** Check the deadline, current binding,
   queue lease and matching enqueue generation before and after the point read.
   A response after its allowed deadline or from a stale attempt has no effect
   on the handoff. For the first current `state=2, current_blocking=0` response,
   record the completion time and reason and call
   `enroll_subscription(..., hint=True)` in the same transaction. This moves
   even an existing pending reconciliation forward and preserves a new hint
   when a reconciliation is already running.
   End the accelerated job if access was already committed, the subscription
   ends or the purchase loses its binding. Regular reconciliation uses the
   stored LBX customer, agreement and subscription IDs and the accepted purchase
   terms. It confirms current ownership and seller, an open agreement, matching
   effective terms and supported prepaid policy. First access requires a single
   eligible subscription for the product. Issue the purchased allowance when
   the billing period is proven. A missing period holds back the allowance
   while independently proven product access can still be committed.

Apply [ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md)
and the existing [paid access reconciliation rules](../../engineering/billing-background-operations.md#inputs-acceptance-and-decisions).

## Cabinet

Add an optional `activation_check` field to each product in `GET /api/paid-access`.
Return `checking`, `unconfirmed` or `null` from the PostgreSQL record for the
current purchase. Return `checking` during the saved window, including its
closing read, and for 60 seconds from handoff to regular reconciliation. When
the applicable period expires and access is still pending, return
`unconfirmed`. Without a saved window, return `unconfirmed` for a current
owned and linked purchase awaiting its first activation if the latest
reconciliation observation still provides fresh matching waiting evidence
under the existing source trust rules. Read that evidence locally and return
`null` when it is absent or stale. Committed access, terminal outcomes and
known conflicts take precedence. Regenerate the OpenAPI and TypeScript
contracts using the repository generator.

Refresh the local `GET /api/paid-access` read when the cabinet window regains
focus while visible, including when returning from a separate payment window
leaves the cabinet document visible throughout. Reuse the paid read's session
and in-flight request guards, and keep refreshes on visibility changes, Widget
closure and the 30-second visible polling interval. These actions read local
status without reopening the Widget or changing the server deadline or LBX
schedule. The card updates automatically on the next successful read after the
access revision is committed.

## Verification

- **Regression.** With controlled clocks, capture the pending regular check for
  a waiting subscription. After successful Widget preparation, make LBX active
  and expect the first grant before the captured regular check would have run.
  Record the expected failure on unchanged code. In the same journey after the
  fix, verify that the activation signal leaves the access revision unchanged
  and that regular reconciliation subsequently commits the first grant and
  exactly one accepted allowance.
- **PostgreSQL and API.** Verify eligibility, one job after concurrent opens,
  unchanged deadline and cadence after repeats or a delayed callback, worker
  restart and reopening after expiry. Combine lost and failed enqueue cases
  around the same assertions: the Widget succeeds, the cabinet shows
  `unconfirmed` when fresh waiting evidence exists, and the scheduled worker
  grants access without another open.
  Test the normal lane, logical lookup count, backoff, closing read and atomic
  handoff of already scheduled work. Reject a response beyond its budget and
  one from a stale attempt. Retain the existing proof matrix for block,
  incomplete authoritative proof, competition and missing billing period.
- **Cabinet and browser.** Cover checking before and after handoff, reload,
  expiry, late success and two independent product statuses. Extend the
  representative cabinet browser test to observe the update without a manual
  refresh. Keep the cabinet document visible throughout a separate payment
  window return and verify that regaining focus triggers a local paid-access
  read before the next scheduled tick without a new Widget bootstrap. Check
  desktop, mobile and accessibility evidence. Run
  `npm run test:e2e -- apps/web/e2e/any765-paid-access.spec.ts`. Run
  `npm run check:fast` during implementation and `npm run check` before handoff
  when the environment supports it. The fast check includes generated contract
  verification.
- **Timing and QA.** With controlled clocks, cover activation just after an
  ordinary probe, between the last ordinary probe and the closing read, and
  after the closing read. Verify normal scheduled issuance for late activation.
  On QA, buy Brief Decoder and Proposal AI on separate agreements. Use payment
  inside the Widget for one purchase and observe its automatic update in the
  visible cabinet. For the other purchase, return from a separate payment
  window to an open, visible cabinet and check the local refresh. Verify in a
  separate controlled scenario that access is granted while the cabinet is
  closed, before reopening it. Include repeated returns or reloads and verify
  that the other product's access stays intact. Check deadline and cadence
  invariants in the controlled tests.

  Record `prepared_at`, LBX credit and charge, the last waiting and first
  active and unblocked responses from independent LBX reads, worker detection,
  actual DB commit or first observed committed revision, and the visible
  cabinet update on a common time scale. Aim for a commit within **30 seconds**
  of active evidence becoming available during the fast window under healthy
  QA conditions. Include queue delay, full reconciliation and primary
  selection. Bound availability between the start of the last waiting request
  and receipt of the first active response. Subtract the start of the last
  waiting request from actual commit or first observation of the committed
  revision for a conservative upper bound. Use the first active response and
  actual commit for the lower bound. Repeat an inconclusive measurement.
  Report preparation-to-credit, credit-to-active, active-to-commit and
  commit-to-display for a visible cabinet separately. Use the measured
  `prepared_at` to active interval to assess coverage and choose the window
  duration after QA. Report late activation and its normal scheduled issuance
  separately from the 30-second target.

  Require at least one healthy live run with the selected window that meets
  the 30-second target and shows that the accelerated path granted access.
  Correlate the positive point read and handoff with the regular job advanced
  by the hint, its first-primary selection and the first committed revision
  containing the purchased product's grant. Use work identifiers, queue timing
  and generations as needed to distinguish that run from reconciliation
  already due or running independently. Reuse existing evidence where it is
  sufficient. If neither initial purchase proves the result with the selected
  duration, repeat the timed purchase with that duration. An independently
  scheduled grant is evidence of fallback.

  In the initial Brief Decoder run in Linear, credit arrived almost five
  minutes after payment-form creation and the charge took another 2:54. Use
  it as a reference for the late-activation test. The exact active REST
  transition for that run is unknown.

Start QA with a five-minute window and retain the saved deadline for an open
window when tuning its duration. The 20- and 40-second intervals, five-second
read wait and 60-second confirmation display are the initial settings. The
question of faster activation on the LBX test environment can proceed in parallel.

## Verification results

On 2026-11-23, a Brief Decoder purchase on local Portal with test LBX 043 and
YooKassa met the timing target using a 13-minute QA window. The conservative
upper bound from active, unblocked subscription evidence to the first observed
access commit was 21.5 seconds. The visible cabinet updated 7.0 seconds after
commit. A separate Proposal AI purchase confirmed issuance with the tab closed.

All 1,273 PostgreSQL tests passed. `npm run check` stopped at the API-fast enum
test whose expected `BillingWorkKind` values omit `widget_activation_check`.
The separate web build returned `SecurityFatalError` with the locked Next.js
16.4.2.
