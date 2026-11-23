# ANY-819 — Shorten purchase preparation before the billing Widget

[Linear issue](https://linear.app/paveldik/issue/ANY-819). Baseline `f6b1f1d2`.

1. Characterize first purchase, opening and recovery using the existing
   PostgreSQL and browser fixtures. Measure confirmation, preparation,
   navigation, bootstrap and Widget READY separately.
2. Reuse the owned purchase snapshot within bootstrap. Recheck the original
   customer key after reading the live offer before the first agreement send.
   Retain live admission per send, fresh payment proof and final session/fence
   admission. Leave possible-send discovery to the existing durable GET-only
   worker after an ambiguous reply and expose when the buyer can continue.
3. Poll owned local status in the active browser flow. Open the selected payment
   Widget from a single explicit, session-bound click. Show the target before
   READY and preserve explicit account viewing and repeat opening. While an
   advance reply is outstanding, use the saved held and linked status to make
   payment available. Close the selected payment Widget on a confirmed
   non-payable or missing purchase.
4. Verify locally with synthetic source responses and PostgreSQL. Run the open
   acceptance scenarios below on the approved test LBX stand. Record live
   acceptance separately from simulated results in the PR.

Moving new financial CREATEs to the worker would require a new background-work
contract and would still leave the buyer waiting for the agreement and
subscription. Keep explicit preparation and let the existing GET-only worker
recover the original operation. The browser can use the durable result as soon
as it observes it.

## Regression test coverage

Verify that reload and delayed replies preserve the original financial
operations without duplicate agreements or subscriptions. The browser closure
and full API restart scenarios are part of the end-to-end acceptance below.

- The [purchase browser scenarios](../../../apps/web/e2e/any709-purchase.spec.ts)
  cover desktop and mobile, keyboard confirmation, recovery and session refusal.
  Keep one constrained-viewport scenario that delays session and bootstrap,
  scrolls during bootstrap, and checks the verified target before READY.
- The [product component tests](../../../apps/web/tests/components/any709-step4.test.tsx)
  cover focus on a surviving terms control, manual and automatic status updates,
  and recovery of the original confirmation after a lost reply, including when
  a status check returns no purchase.
- The [cabinet component tests](../../../apps/web/tests/components/any709-cabinet.test.tsx)
  cover refusal and non-payable outcomes across an open Widget and an in-flight
  opening, including the focus handoff. They distinguish a current-session
  refusal from stale purchase results, unrelated 401s and replaced sessions.
  The [shared paid-read tests](../../../apps/web/tests/components/any765-paid-access.test.tsx)
  cover session replacement and unmount.
- The [purchase PostgreSQL tests](../../../apps/api/tests/test_any709_step3_postgres.py)
  cover recovery from persisted state after recreating source resources,
  a late CREATE reply after concurrent binding, live identity and fence before
  the first send, and deferral of discovery to GET-only recovery after an
  ambiguous CREATE.

## Open acceptance items

For each interruption scenario, arrange for LBX to accept the financial CREATE
and delay its reply until after the interruption. Compare the saved operation
IDs and correlation keys before and after recovery. Verify in LBX that recovery
produces no duplicate agreements or subscriptions.

- Close the browser while a financial CREATE is in flight. Reopen the product as
  the same verified buyer and verify that the saved purchase resumes from its
  recorded state.
- Stop the API process while a financial CREATE is in flight, before the result
  is recorded. Restart the full process with the same database and the billing
  worker enabled. Verify that GET-only recovery finds the original operation
  from persisted state.
- Measure a fresh buyer's first attempt from accepting terms to the official
  Widget READY on baseline `f6b1f1d2` and the final revision. Use the same LBX
  test stand, equivalent fresh buyers and offers, and the same
  `BILLING_WORKER_ENABLED` and `PREFLIGHT_TOTAL_TIMEOUT_SECONDS` settings.
  Record the tested SHAs and settings. Capture confirmation, preparation,
  navigation, bootstrap and Widget startup separately, with buyer wait,
  first-attempt errors and retries recorded separately from successful timings.
  Measure reopening and refresh separately on prepared purchases.
- On the final revision, prepare Brief Decoder and Proposal AI purchases for
  the same verified test buyer on different tariffs and separate agreements.
  Verify that each Widget reaches READY and that the Portal identifies its
  agreement and seller on initial opening, reopening and refresh. In the
  cabinet, switch the selected purchase and verify that the Portal displays
  its agreement reference and that the buyer can find the same agreement in LBX.
- Complete [W02](https://linear.app/paveldik/issue/ANY-819#comment-a2679865-ce7a-4099-8d1a-3d397ff6c909)
  with those two purchases on separate agreements. Record both balances, open
  payment for one purchase and select the agreement identified by the Portal.
  Complete one payment with a confirmed test method. After settlement, confirm
  that the selected agreement received the credit and the other balance matches
  its recorded value.
