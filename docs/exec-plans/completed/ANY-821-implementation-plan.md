# ANY-821 - Terminal resolution for UNKNOWN purchases

Status: Implemented and verified locally.
Updated: 2026-11-19
Issue: [ANY-821](https://linear.app/paveldik/issue/ANY-821/define-and-implement-terminal-resolution-for-purchases-stuck-in)

## Implemented scope

Operators can complete a stuck purchase with request-specific evidence for
both the agreement and subscription. The transaction records the decision,
fences old work and releases the original hold. The accepted terms and
external object history survive restart and a replacement purchase.
The existing two-hour escalation and payment admission rules still apply.
Foreground latency remains with ANY-819. Production enablement and live LBX
verification remain with ANY-504.

- **Operations.** The [billing runbook](../../engineering/billing-background-operations.md#terminal-completion-any-821)
  documents the evidence, sender shutdown, exact replay and late-case procedure.
- **Storage.** The [schema reference](../../architecture/payment-portal-data-model.md#physical-baseline)
  records the terminal outcome and the merge with the published ANY-766
  migrations. The existing paid-access reducer updates dependent grants in the
  same transaction and preserves allowance history.
- **Customer journey.** The [cabinet](../../product/ru-mvp.md#primary-journey-and-account-states)
  shows the completed outcome through the original purchase link. A customer
  can start a new purchase under current terms.

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
  the existing 20-candidate limit. When the active list and the detail for a
  held purchase disagree, the cabinet reads the deep-linked purchase again.
  Its card and billing action use that result. A released purchase keeps its
  individual terminal status.

The seven ticket cases are exercised through unsent completion and restart,
GET-only recovery after a lost reply, empty discovery with the hold retained,
late discovery after operator action, separate proof for a partial purchase,
two-hour escalation, and repeated/concurrent actions with a replacement.

The regression fixture keeps the held purchase's own subscription visible
alongside a late object listed under the wrong agreement. It runs recovery
before correcting the listing and checks the persisted state of both purchases.
Six PostgreSQL checks failed on `aed33ebb` and passed against the corrected
worker, `advance` and `recover`. Separate controls verify that a conflict on
the held purchase's dedicated agreement or CREATE receipt still opens a case.

Documentation, generated contracts, architecture, lint, 508 web tests, 2,413
fast API tests and the Webpack build passed. One Windows-only API test skipped
on Linux. On PostgreSQL 14, three timestamp assertions required a UTC connection.
The four-worker UTC run hit two SQL timeouts and one fixture deadline. All
1,305 PostgreSQL tests passed in one serial run on a disposable in-memory
database with the original deadlines.

Six browser checks passed on the production build with synthetic billing in
desktop Chromium and Pixel 7 emulation, covering stale detail, stale list,
terminal reload and Widget opening. The full live-stack browser suite was
outside this run.

### Integration with main and ANY-832

ANY-821 was rebased onto `f6b1f1d2`, including the ANY-864 monthly LBX calendar
and the ANY-741 Mako update. For integration with ANY-832 at `f7639e1a`, keep
its inventory fact collector and product projection, and incorporate ANY-821's
released-purchase lookup and case attribution. The three-way preview also
found overlaps in LBX calendar normalization and reconciliation. Retain the
monthly instance-start rules, annual and established calendar anchors and
evidence from the same point read. Verify
first-primary selection and both calendar profiles on the combined tree.

Earlier temporary combinations with PR #168 at `900e3f2c` and PR #171 at
`3e9c1273` passed 70 and 83 selected tests respectively. These results apply
to their recorded snapshots.
