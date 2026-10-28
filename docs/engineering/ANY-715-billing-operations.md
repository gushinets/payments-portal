# ANY-715 billing operations

Status: Steps 1–3 shared reconciliation, embedded polling, recovery and inventory implemented.
Updated: 2026-10-28.
Issue: [ANY-715](https://linear.app/paveldik/issue/ANY-715).
Scope: [implementation plan](../exec-plans/active/ANY-715-implementation-plan.md), Steps 1–3.

## Shared proof and original history

`app.composition.reconciliation.reconcile_subscription()` is the reusable outer
I/O seam. It accepts an explicitly supplied LBX client and bounded admission
resource, configuration, session factory and canonical local subscription ID.
The embedded worker calls this shared seam; it is not a public endpoint or operator CLI command.
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

Step 2 supplies automatic enrollment, durable polling and local source-trust
expiry evidence. Step 3 adds uncertain-create recovery/inventory loops. Later steps own
webhook hints and audited operator commands. Step 9 owns primary selection,
access derivation, effective authorization deadlines, grants, allowances,
revisions and invalidations. No paid-access producer runs here.

## Embedded worker settings and resource limits

The initial deployment is one API process/replica. The API lifespan supervises
`app.jobs.billing.BillingWorker` through `app.composition.billing_worker`.
The runner accepts an explicit session factory and LBX client, independent of
HTTP startup. There is no standalone worker command/container.

- `BILLING_WORKER_ENABLED=true`: starts embedded execution when LBX is configured.
- `BILLING_WORKER_URGENT_CONCURRENCY=2`: independent urgent source slots (1–16).
- `BILLING_WORKER_NORMAL_CONCURRENCY=1`: independent normal source slots (1–16).
- `BILLING_WORKER_IO_TIMEOUT_SECONDS=60`: total read/cleanup budget (greater
  than the cleanup reserve, at most 600 seconds).
- `BILLING_WORKER_SCAN_BATCH_SIZE=100`: local batch size (1–100).

`PREFLIGHT_CLEANUP_TIMEOUT_SECONDS` reserves cleanup within that total budget.
Work and subscription leases cover the total budget plus 30 seconds for local
apply/safety. Each source slot has one owner through actual HTTP cleanup.
Timeout/cancellation/expired DB leases do not release unfinished HTTP slots.
No replacement request can accumulate behind an abandoned owner. Apply checks
both queue ownership/expiry and subscription owner/fence/expiry under business
locks. All provider retries are GET-only; the worker never creates a customer,
agreement, subscription, payment or renewal.

These are **per-process** limits, not provider-wide concurrency/RPS guarantees.
The worker owns separate LBX HTTP pools and bounded DB delegation/connection
capacity from purchase, Widget and new-sale resources. Local sweep/deadline work
has separate DB delegation and no provider HTTP. Normal and urgent lanes cannot
consume each other's reserved slots. Wholly unconfigured LBX reports
`not_configured` without source calls; disabled execution reports `disabled`.
Partial LBX configuration also prevents source execution without breaking auth.
Retained cleanup is reported as degraded billing health while local supervision
continues; source unavailability alone does not withdraw identity readiness.
Ordinary automated tests explicitly disable unattended execution.

## Enrollment, cadence and restart

Step 7's canonical local binding and its immediate reconciliation job commit
atomically. Repeated preparation readbacks preserve existing future schedules,
generation and ownership. Coalescing keys use configured account and local
subscription identity, so two products sharing a customer/tariff keep independent
jobs, observations and trust.

Startup and every 60 seconds run a durable local enrollment sweep. Each batch
selects the missing set by subscription ID (no offset/cursor), commits at most
100 enrollments, yields to other tasks and continues until empty. Restart repeats
from missing work. Existing pending/running work, including future jobs and
expired leases awaiting reclaim, is already enrolled; completed recurring jobs
reactivate. Malformed historical provenance is isolated as `invalid` with a
bounded reason, without provider calls or repeatedly failing the first batch.
Missing source-trust expiry jobs are repaired locally as well. Step 3 also repairs missing customer inventory, urgent recovery and independent
create-deadline jobs in bounded batches. Existing customer active-send leases,
future recurring schedules and completed no-send records remain protected.

New links are immediately due. Never-positive/blocked/incomplete/conflicted or
near-expiry (within 30 minutes) work is urgent, with at most five minutes between
scheduled attempts. Claims check the current persisted trust deadline as well as
stored priority, so waiting normal work can use urgent capacity as trust approaches
expiry. This classification preserves the job's due time, generation and live
lease. Otherwise reconciliation runs approximately every 15 minutes.
Recurring due times use deterministic earlier-only jitter up to 20%; incomplete
reads use bounded 30-second exponential backoff capped at five minutes. Scheduling
includes attempt duration; a paused process/backlog can still cause observable
lag and never extends source trust. Authentication/configuration failures cannot
start rapid POST retries and retain the bounded read cooldown.

Claims use short PostgreSQL `FOR UPDATE SKIP LOCKED` transactions, DB time,
unique ownership and an enqueue generation. Consumers claim only available
execution capacity, then claim subscription fences separately. No network runs
under locks. Hints arriving during execution survive completion. Source apply,
trust scheduling and queue rescheduling commit atomically. Local expiry appends
`subscription-trust-expiry:v1` / `deterministic_access_boundary` evidence with the
supporting observation and effective deadline, without changing provider
lifecycle/financial facts, extending trust or writing an access revision.
A concurrent refresh wins through the same lock/generation checks.

## GET-only uncertain-create recovery and customer inventory

`external_create_recovery` runs in the urgent source lane through shared
`recover_financial()` / `recover_customer()` Application proof and transitions.
The permanent recovery key is the original local create-operation ID; receipts
and request/key/date history remain on that same row. Claims commit before GETs.
Apply checks current queue ownership/expiry and the original operation fence.
A lost claim acknowledgement starts no HTTP; a late/superseded result cannot bind.
Recovered canonical subscriptions enroll atomically through the same subscription
binding path. Bound subscriptions use lifecycle reconciliation, avoiding
preparation-only terminal restrictions.

Zero candidates remain uncertain; delayed visibility can later recover. Exactly
one original point-proven agreement/subscription/customer can bind. Multiple,
foreign, swapped or already-bound candidates enter conflict review or remain
incomplete, with no adoption. Saved receipts select only an original candidate;
a discovery list alone never proves ownership. Known financial conflicts remain
open after later matching GETs; only deadline-only review can recover normally.
The hold and original legal/accepted history survive zero matches, review, ended
states and source failure. No worker POST, force release, current-price
reapproval, primary selection or access/grant/allowance/revision write exists.

Recovery retries use bounded earlier-only jitter/backoff, at most five minutes
between scheduled urgent attempts, accounting for attempt duration. A separate
provider-free `external_create_deadline` job uses the original financial
`unknown_since + 2h` pair. It escalates unresolved possible-send/UNKNOWN to
`external_create_outcome_unknown:<operation_kind>` even during an LBX outage.
Retrying GETs, restarting and delayed candidates never move that deadline.
`PENDING` and completed `PROVEN_NOT_SENT` authorize no background CREATE and
are excluded from UNKNOWN repair/escalation. Only the existing authenticated
explicit advance and completed typed no-send rules can resume a financial send.

Customer creation retains its distinct owner-approved explicit-open policy:
background recovery never creates or restores an identity-conflict binding.
An active `customer-send:` lease excludes competing recovery claims. After that
finite lease or a completed explicit attempt, GET recovery is safe. A later
explicit authenticated open may perform its existing discover-before-create
retry with a new fence and its own two-hour pair, on the same customer operation.
The customer policy does not change financial send authority.

`503 billing_busy` / user-lock `55P03` is local contention. Retry the durable job
with the same operation, request, key, send fence and fixed deadline. It is never
provider failure, completed no-send evidence, permission to POST or hold release.
Inspect `last_error_classification=billing_busy` to distinguish this local retry.

`customer_inventory` runs in the normal lane, approximately every six hours
when stable, and retries incomplete/conflicting reads urgently within five
minutes. It uses paired customer proof, fewer than 100 discovery rows and at
most 20 relevant candidates under one worker I/O budget. Capped, duplicate,
unstable or partial results are incomplete, never absence. Two bounded inventory
lists detect observed membership drift; they do not establish an atomic snapshot
or a provider visibility SLA. Point reads must agree with discovery identities.

A tariff is not product identity. `proposal_ai` and `brief_decoder` may share
one tariff/service/period for the same customer/account only with separate
accepted purchases, agreements and subscriptions. Another product is excluded
from competing inventory only through its permanent local owner, original legal
consent, agreement/customer/seller/correlation and original effective-term proof.
Incomplete other-product evidence cannot exclude an object. Proven relevant
competition records scoped `customer-inventory:v1` evidence and a durable
`customer_inventory_conflict` review, reducing the affected subscription's
commercial eligibility without rebinding any object or renewing source trust.
Each bounded pass checks the customer's product scopes before applying its
scoped conflicts together in one fenced transaction. The customer job finishes
once after all those conflicts are recorded; an earlier conflicting product
cannot repeatedly prevent later products from being checked. A stale operation
snapshot or expired work claim rejects the entire conflict batch.
Ordinary inventory success cannot close a known conflict.

Owner checkpoint: review existing synthetic GET traffic and persisted original
history using the `billing_background_recovery` PostgreSQL selection from the
plan's shared harness recipe. All such fixtures are **SIMULATED**; no live billing
failure, provider CREATE or payment is manufactured. Actual test-LBX failure
recovery is **NOT_RUN**. Webhook mode remains **DISABLED/POLLING-ONLY**; webhook
setup and audited resolution/inspection CLI expansion remain Steps 4–5.

## Startup, inspection and shutdown

Apply migration `20261028_0004` through the normal migration service before
starting the API. Start/restart with the existing repository/deployment commands;
there is no additional process to launch. To stop source execution, set
`BILLING_WORKER_ENABLED=false` and restart through the ordinary deployment path.
Stop claiming before replacing the owner. Shutdown drains up to the configured
I/O budget, cancels/awaits tasks and drains source cleanup. If cleanup is still
pending it retains its slot, reports degraded shutdown and propagates failure;
it never reports a successful drain or closes the client underneath live I/O.
After process exit, finite durable leases are reclaimable on restart.

`GET /api/health/billing` exposes named, redacted worker status, occupied slots,
cleanup-pending count, pending/invalid work, oldest due time, failures, enrollment
batch count and last scan/progress times. `/api/health/ready` requires the DB and
progressing local worker supervision; an LBX outage alone does not make identity
unready. `/api/health/live` remains DB-independent. No IDs/secrets are returned.

Prometheus `payment_portal_billing_worker_*` signals report attempts by lane and
outcome, active/cleanup slots, pending/invalid work, oldest overdue age and last
progress time. `failures` counts execution exceptions; completed work and last
progress include durably recorded incomplete attempts and local sweeps. They do
not claim successful source proof. Inspect `source_incomplete` work classifications,
versioned observations and bounded `lbx_http` source/authentication diagnostics
for source failures. Alert on repeated authentication denial/configuration errors
or incomplete reads approaching the affected source-trust deadline; the read
backoff supplies cooldown without preserving or extending trust.
Labels contain no local/customer/product IDs. Growing overdue age,
invalid records, failed local scans (120 seconds) or persistent cleanup warrant
operator investigation. Inspect durable work/projections through existing trusted
local DB access; the expanded purchase inspection/recheck CLI is Step 5.
Do not use public health output as commercial or access authority.

## Future expansion path

Use measured queue age/source latency to tune bounded concurrency/timing within
actual provider limits first. If API resource isolation requires it, a future
thin standalone entrypoint can reuse the same runner/use cases: disable embedded
startup, stop claims, drain/stop the old owner, then restart over the same durable
jobs. Roll back by draining that owner before re-enabling embedded execution.
Add consumers/read optimizations only after measured need and account for
multiplied per-process limits and actual LBX quotas; add aggregate enforcement
when required by that deployment. No scaled deployment, MQ, global admission,
capacity benchmark or large-load claim is implemented by Step 2.

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
