# ANY-819 — Shorten purchase preparation before the billing Widget

[Linear issue](https://linear.app/paveldik/issue/ANY-819). Baseline `f6b1f1d2`.

1. Characterize first purchase, a second tariff, opening and recovery using the
   existing PostgreSQL and browser fixtures. Measure confirmation, preparation,
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
4. Verify locally with synthetic source responses and PostgreSQL. On the
   approved test LBX stand, compare timings and repeat
   [W02](https://linear.app/paveldik/issue/ANY-819#comment-a2679865-ce7a-4099-8d1a-3d397ff6c909)
   with multiple agreements. Record live acceptance separately from simulated
   results.

Moving new financial CREATEs to the worker would require a new background-work
contract and would still leave the buyer waiting for the agreement and
subscription. Keep explicit preparation and let the existing GET-only worker
recover the original operation. The browser can use the durable result as soon
as it observes it.

## Local verification

- First preparation retains five canonical customer reads. The review found
  that reducing the count to four let a changed original customer key go
  undetected until after the agreement send. When the create reply is lost,
  advance has already searched once for the agreement before sending. It returns
  the saved pending state. The baseline ran a second search in the same request.
  Separate regressions cover provider-key drift and a changed local customer fence.
- On 2026-11-20, the local review fixes on top of `970a428f` passed
  `npm run check:fast` with
  504 component tests and 2,408 fast API tests, with one API test skipped.
  All seven concurrent purchase scenarios passed on an isolated PostgreSQL 14
  instance. The UNKNOWN case verifies a committed ambiguous subscription
  result, GET-only worker recovery and safe continuation of the second purchase.
  The webpack build with a cached local font and all 60 browser scenarios
  passed on desktop and mobile Chromium (28 purchase and 32 catalog). The
  browser tests used synthetic sources and exercised the payment viewport and
  keyboard focus.

## Live test setup and baseline

The Portal ran on a disposable copy of the stopped ANY-767 Portal database,
with local SMTP and the capability manifest exported from the stand's pinned
Kernel image and profile. Billing HTTP and the official Widget used live test
LBX 043. The Portal worker was disabled on the copy for foreground timing.
The original deployments, volumes, published links and paid control agreement
were untouched. New financial objects, where required, used separate
synthetic test users.

On `f6b1f1d2`, the first live Brief Decoder purchase prepared. Its initial
Widget bootstrap hit a PostgreSQL statement timeout and the first ProposalAI
advance refused incomplete inventory. After retry, both purchases opened the
official Widget and ProposalAI showed two top-up choices with its intended
agreement visible. These successful opening and refresh samples start from
already accepted purchases, so they do not establish a first-attempt
acceptance-to-READY baseline.

## Live samples from the initial implementation

The initial ANY-819 timing records omit the tested build SHA.

- The first purchase took 74.9 s from acceptance to verified Widget READY.
  Confirmation took 5.7 s and advance 29.8 s. In the first advance, the number
  of live LBX exchanges fell from 38 to 37 and canonical customer reads from
  five to four. Both runs took about 30 s for advance at the granularity of the
  paired server logs.
- The second product on a separate tariff reached READY in 47.8 s, including
  6.9 s for confirmation and 30.4 s for advance. Refresh took 9.2 s from the
  refresh click to READY. The official Widget displayed both top-up choices.
  Selecting the intended row opened a top-up form with exactly the agreement
  reference shown by Portal and a recommended test amount of 100 RUB.
- A paired replay used the same two saved purchases. For ProposalAI, click to
  READY took 14.7 s before and 8.8 s after. Refresh took 15.2 s before and 10.4 s
  after. This is one pair of test samples. The changed fresh-buyer journey made
  exactly one customer, two agreement and two subscription CREATE calls.

## Live samples from an earlier review build

The earlier review timing records omit the tested build SHA. The latest local
review fixes have synthetic verification evidence above.

- On a separate local copy, the official LBX 043 Widget reached READY for both
  retained test purchases. Click to READY took 12.8 s for Brief Decoder and
  6.4 s for ProposalAI. ProposalAI refresh took 3.2 s. These are single samples
  on prepared purchases.
- The 100 RUB top-up request for the isolated ProposalAI agreement succeeded
  at the LBX endpoint and redirected to YooKassa. Both agreement balances
  remained zero.

## Open acceptance items

- Measure a fresh buyer's first attempt from accepting terms to the official
  Widget READY on baseline `f6b1f1d2` and the final revision. Use the same LBX
  test stand, equivalent fresh buyers and offers, and the same
  `BILLING_WORKER_ENABLED` and `PREFLIGHT_TOTAL_TIMEOUT_SECONDS` settings.
  Record the tested SHAs and settings. Capture confirmation, preparation,
  navigation, bootstrap and Widget startup separately, with buyer wait,
  first-attempt errors and retries recorded separately from successful timings.
- Complete W02 as a verified test buyer with two prepared purchases on
  different agreements. Record both balances, open payment for one purchase
  and select the agreement identified by the Portal. Complete one payment
  with a confirmed test method. After settlement, compare both balances
  against the recorded values and confirm that only the intended agreement
  received the credit.
