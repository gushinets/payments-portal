# ANY-715 — Reconciliation and recovery delivery

Status: Step 8 implemented; configured test-LBX acceptance remains open
Updated: 2026-11-02
Issue: [ANY-715](https://linear.app/paveldik/issue/ANY-715)
Program: [ANY-504](https://linear.app/paveldik/issue/ANY-504)

This completed delivery record captures the result, retained decisions and
next-step boundary. Use the [operations guide](../../engineering/ANY-715-billing-operations.md)
for current commands and operating guarantees, and the
[verification report](../../engineering/ANY-715-qa-report.md) for tested coverage
and open integration checks. Architectural authority remains
[ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md)
and its accepted specifications and dated decisions.

## Delivered result

An owned prepared subscription is monitored without further browser activity.
Portal records authoritative subscription facts and recovers uncertain creates
through durable scheduled work, including across restarts and missing webhooks.
All five implementation slices are delivered:

1. Authoritative subscription reconciliation verifies original ownership,
   accepted effective terms and supported prepaid policy, and records waiting,
   active, blocked, ended, incomplete or conflicting facts with finite trust.
2. Embedded PostgreSQL-durable polling enrolls subscriptions automatically,
   resumes work after restart and protects newer facts from stale consumers.
   Local deadlines have execution capacity independent of provider HTTP.
3. GET-only recovery and bounded customer inventory retain original operation
   identities, send authority, purchase holds and independent product scopes.
4. Optional authenticated webhooks commit redacted hints before acknowledgement.
   Polling remains independent; webhook mode is DISABLED/POLLING-ONLY until the
   real enablement check passes.
5. Privileged inspection and rechecks support only two audited resolutions:
   restoring original canonical facts and binding a uniquely proven original
   possible-send operation.

## Retained decisions

- **Financial truth belongs to LBX.** As clarified in ANY-715, a complete owned,
  commercially verified supported prepaid ACTIVE/unblocked observation is LBX's
  operational eligibility signal. Portal does not reconstruct settlements from
  payments, charges or balances. Step 8 records facts; Step 9 derives paid access.
- **Accepted purchases retain their meaning.** Today's catalog price or sale
  visibility does not reprice an existing subscription. Actual effective-term
  or ownership changes require conflict handling. Different products may share
  a tariff under one customer only with separately proven purchases, dedicated
  agreements and subscriptions.
- **Trust is finite.** Complete matching proof can establish at most six hours
  from read start. Incomplete reads do not extend it; known negative/conflicting
  facts reduce usability immediately. Provider calendar precision is preserved
  without inventing UTC cycle boundaries or an allowance identity.
- **Recovery does not create financial send permission.** UNKNOWN is GET-only.
  Only an explicit authenticated continuation after completed typed
  PROVEN_NOT_SENT can establish a new fixed active two-hour recovery window for
  the same financial command. Original immutable history remains intact. This
  follows C4 in the accepted ANY-709 contract decisions in
  [ANY-504](https://linear.app/paveldik/issue/ANY-504), linked by ADR 0005.
  Customer explicit-open retry retains its separate accepted policy.
- **Initial deployment stays small.** One API replica runs the embedded worker.
  Resource limits apply per process. Webhooks are optional; separate worker
  deployment and aggregate admission require a measured operational need.
- **Operator input is not billing authority.** Resolutions need fresh original
  proof and current expected evidence. Terminal hold release, inventory-conflict
  overrides, arbitrary rebind and manual paid marking are outside this delivery.

## Step 9 handoff

Step 9 receives versioned subscription observations, original ownership and
accepted/legal provenance, commercial classifications, source-trust deadlines,
calendar evidence and deterministic local expiry signals. The operations guide
owns their interpretation and supported recovery controls.

Step 9 owns primary selection, paid grants/allowances, effective-access revisions
and atomic invalidation-outbox production. Step 10 owns Kernel wire/delivery and
coupled calendar-to-UTC design. Step 11 owns complete paid-access, natural-renewal
and launch acceptance. Reconciliation, webhook receipt, Widget callbacks and
operator actions do not independently grant access.

## Acceptance status

Local automated implementation verification is complete; the
[verification report](../../engineering/ANY-715-qa-report.md) pins its source and
coverage. Configured read-only LBX reconciliation remains unverified. Real
webhook authentication/delivery must be verified before enablement; until then,
keep polling-only mode. Local completion does not authorize production migration
or launch.
