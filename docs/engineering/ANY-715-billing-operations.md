# ANY-715 billing operations

Status: Step 1 shared reconciliation implemented; automatic execution is planned.
Updated: 2026-10-28.
Issue: [ANY-715](https://linear.app/paveldik/issue/ANY-715).
Scope: [implementation plan](../exec-plans/active/ANY-715-implementation-plan.md), Step 1.

## Shared proof and original history

`app.composition.reconciliation.reconcile_subscription()` is the reusable outer
I/O seam. It accepts an explicitly supplied LBX client and bounded admission
resource, configuration, session factory and canonical local subscription ID.
It is not a public endpoint, a scheduled worker or an operator CLI command.
It makes no financial POST, Kernel call, catalog discovery or current-offer read.

Application claims a finite subscription lease in a short transaction using
database time, a unique owner and an incrementing fence. The lease covers the
supplied total I/O budget plus a 30-second local apply margin. LBX reads run
outside transactions. Apply rechecks lease/owner/fence, canonical ownership,
original consent, accepted snapshot, permanent operation identities and product
hold under the existing user-first lock policy. Preparation may rotate its own
send fences without invalidating permanent reconciliation provenance.

The normal proof uses one call to each method, in this order:

1. `get_user()` proves the canonical provider customer and immutable Portal key.
2. `get_agreement()` proves the original agreement, customer, seller and permanent
   correlation. A closed agreement can establish ordinary negative facts.
3. `get_tariff()` proves applicable prepaid/full-funding/automatic-blocking,
   non-demo, non-prorated policy and configured currency interpretation.
4. `get_subscription()` proves canonical identity, original effective service,
   quantity, price, total, currency, period and the latest lifecycle/calendar.

Authentication and bounded transport retries remain owned by the shared client.
All four reads share one absolute operation budget. Successful point methods,
`read_started_at`, read completion and immutable local provenance are recorded in
`subscription-reconciliation:v1`. The read window is not an atomic provider
snapshot; a concurrent source change may remain undetected. There is no second
full read round.

Current catalog prices, current mapping heads, source sale visibility/archive
flags and Kernel publication availability do not reprice or invalidate accepted
history. Effective subscription prices are compared with the original accepted
snapshot. Missing policy or currency proof cannot establish positive trust.
No balances, payments, charges or settlement reconstruction decide usability.

## State and finite trust

Commercial evidence is `COMPLETE_MATCH`, `COMPLETE_MISMATCH` or `INCOMPLETE`.
Identity, lifecycle, financial conclusion and calendar completeness are recorded
separately. Unknown numeric source states are incomplete evidence.

Waiting/unpaid becomes inactive/blocked and may have null cycle dates. Supported
ACTIVE/unblocked with complete owned original-term and coherent cycle proof
becomes active/allowed operational source facts. Financial and administrative
blocks remain distinct bounded reasons. Ended is terminal; a later nonterminal
state for the same ID opens `subscription_terminal_revival_conflict`.

Only complete matching proof without a known review refreshes source trust.
Trust starts at `read_started_at` and lasts at most six hours. There is no extra
outage grace interval. Incomplete reads append attempt evidence without replacing
the last complete supporting observation or extending its deadline. Decisive
owned blocks/end or identity/commercial conflicts supersede positive usability
even if unrelated commercial fields are missing. They never renew trust from
incomplete evidence. Timed-out attempts persist only incomplete-attempt evidence;
their delayed results cannot become positive facts. Expired or superseded leases
cannot apply. Failed/cancelled claims remain reclaimable after their finite lease.

Known subscription/financial conflicts require controlled review and cannot be
cleared by an ordinary matching poll or preparation read. Customer-key conflict
uses the existing customer transition: an authenticated explicit account open
may restore the original paired key. That policy does not clear financial or
subscription conflicts. Subsequent preparation can append `prepared-subscription:v1`
but cannot replace monitored lifecycle, financial facts, supporting observation
or trust. The existing linked-state incomplete-read behavior is preserved.

The scope is established with `primary_subscription_id=NULL`; reconciliation
does not select a primary. Every observation keeps `resulting_access_revision`
null. Purchase history, bindings, legal evidence and product hold survive all
lifecycle transitions, including ended. There is no automatic hold release.

## Calendar and downstream limits

Original subscription, instance and calculation-period strings remain calendar
evidence. Positive proof requires valid ordered calculation-period dates;
sentinel/missing dates, reversed periods and contradictions with supplied
lifetime/instance bounds cannot establish positive trust. The provider's latest
calculation-period pair is preserved without inventing an account timezone,
exact UTC boundaries, native cycle ID or allowance identity. This step does not
claim to prove natural rollover or derive paid access from those dates.

Step 2 owns automatic enrollment, durable polling, local trust-expiry execution,
isolated worker resources and startup/shutdown. Later steps own recovery loops,
webhook hints and audited operator commands. Step 9 owns access derivation,
earlier effective authorization deadlines, grants, allowances, revisions and
invalidations. None of those entrypoints or effects is implemented by Step 1.

## Evidence levels and owner checkpoint

Automated fixtures and lifecycle transitions are **SIMULATED**. They establish
local behavior, not real LBX renewal, settlement, webhook delivery or Kernel
conformance. Real read-only normalized-output inspection is **NOT_RUN** here.
Real mutation/payment operations are outside this step's authorization.

Owner checkpoint: inspect sanitized `subscription-reconciliation:v1` outputs for
waiting, active, next calculation period, financial/admin block, ended and
incomplete attempts. Review classification, bounded reasons, read window,
calendar completeness, original purchase/link/legal references and unchanged
trust on incomplete proof. Do not export payloads, credentials, contact fields,
customer keys or authorization data. Synthetic outputs are reproducible through
the `billing_subscription_reconciliation` fast/PostgreSQL test selection in the
plan's shared harness recipe. Real untouched renewal and provider-to-Portal-to-Kernel
acceptance remain separate enablement gates.
