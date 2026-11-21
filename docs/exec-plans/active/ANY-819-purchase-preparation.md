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

## Open acceptance items

- Measure a fresh buyer's first attempt from accepting terms to the official
  Widget READY on baseline `f6b1f1d2` and the final revision. Use the same LBX
  test stand, equivalent fresh buyers and offers, and the same
  `BILLING_WORKER_ENABLED` and `PREFLIGHT_TOTAL_TIMEOUT_SECONDS` settings.
  Record the tested SHAs and settings. Capture confirmation, preparation,
  navigation, bootstrap and Widget startup separately, with buyer wait,
  first-attempt errors and retries recorded separately from successful timings.
  Measure reopening and refresh separately on prepared purchases.
- On the final revision, prepare two purchases for the same verified test
  buyer, with the second product on a different tariff. Verify that each
  Widget reaches READY and that the Portal identifies its agreement and seller
  on initial opening, reopening and refresh.
- Complete [W02](https://linear.app/paveldik/issue/ANY-819#comment-a2679865-ce7a-4099-8d1a-3d397ff6c909)
  with those two purchases on separate agreements. Record both balances, open
  payment for one purchase and select the agreement identified by the Portal.
  Complete one payment with a confirmed test method. After settlement, confirm
  that the selected agreement received the credit and the other balance matches
  its recorded value.
