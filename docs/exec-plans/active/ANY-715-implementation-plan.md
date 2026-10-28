# ANY-715 — Background Work, Webhooks, Reconciliation & Recovery

Status: Step 1 implemented and locally verified; Steps 2–5 not started
Updated: 2026-10-28  
Issue: https://linear.app/paveldik/issue/ANY-715  
Program: https://linear.app/paveldik/issue/ANY-504

Operational runbook to build during implementation:
`docs/engineering/ANY-715-billing-operations.md`.

## 1. Goal & Final Expected Outcome

After an owned Step 7 subscription is prepared, Portal automatically enrolls it
for authoritative LBX reconciliation. The user may close the browser. Missing
webhooks, unavailable LBX, lost responses and Portal restarts do not discard the
monitoring or recovery work.

The running system must:

1. Independently reread known subscriptions on the approved normal/urgent cadence.
2. Verify canonical customer/agreement/subscription ownership, original accepted
   terms and supported prepaid policy.
3. Persist accurate waiting, active, blocked and ended facts; distinguish
   commercial mismatch, identity conflict and incomplete evidence.
4. Refresh source trust only from complete authoritative proof, for at most six
   hours.
5. Execute local trust-expiry and uncertain-create escalation work without
   provider availability.
6. Recover possible-send/UNKNOWN financial operations through GET-only discovery
   and point proof, preserving permanent send fences and original two-hour
   escalation.
7. Optionally accept authenticated webhook hints into a durable redacted inbox
   and coalesced queue, with independent polling as the correctness path.
8. Provide documented privileged CLI inspection, bounded rechecks and
   proof-based audited resolutions.
9. Keep claims and facts safe under competing consumers, while initially running
   one embedded worker with bounded resources.
10. Supply Step 9 with trustworthy provider-neutral facts and deadlines.

The initial deployment remains one API replica with an embedded worker, suitable
for the current small workload. Separating execution, durable jobs and business
logic preserves a future expansion path without implementing extra deployment
modes or hypothetical load requirements now.

Step 8 does not select an access primary, grant paid access, create allowances,
update access revisions, produce invalidations or implement Kernel enforcement.

## 2. Current State & Reusable Implementation

### Baseline and delivery policy

Latest inspected sources:

- `ANY-709`, `origin/ANY-709`, PR #150 HEAD:
  `d28edddb565a2d7e1e6a5892199e3c00d3ad5417`.
- Current `main` / PR #150 target:
  `e323d56c380ba3d98a650fc6db29556eb0ca748e`.
- Merge base: `dfdc67a9617df1afb5213b0fb831b770e6d816be`.
- [PR #150](https://github.com/gushinets/payments-portal/pull/150) remains open.
- Step 7 migration head: `20261027_0003`.
- The working tree was clean before creating the plan branch.

Commit `d28eddd` preserves a linked purchase across transient/incomplete Widget
point-read failures. Each payment opening still requires fresh complete proof.
Known customer/seller/material-term conflicts remain manual-review cases and do
not disappear merely because a later response matches.

Develop Step 8 from the current `ANY-709` branch without waiting for its merge.
Refresh relevant Step 7 interfaces and tests after subsequent review corrections.
PR #143 is rejected history and supplies no implementation dependency.

The planning branch `ANY-715` inherits `ANY-709`; its draft
[PR #154](https://github.com/gushinets/payments-portal/pull/154) targets `ANY-709`
and records the Step 7 dependency. Rebase/retarget to main after Step 7 merges
through a separately authorized Git operation. Per-step execution prompts below
do not authorize Git mutations.

Owner-requested revalidation keeps the five implementation steps and removes
premature capacity requirements. Only this plan changes in this revision; no
Step 8 application behavior is presented as implemented.

### Reuse and gap register

| Surface | Provenance | Decision |
|---|---|---|
| Subscription, scope, observation, work, review and inbox tables | `MAIN_CONFIRMED`, with Step 7 extensions | **REUSE.** Existing storage is not evidence of a running worker. |
| Accepted purchase, consent, product hold and permanent operation identities | `PR150_PROVISIONAL` | **REUSE.** Preserve original price, service, quantity, period, currency, seller, origin and legal history. |
| `recover_financial()` and financial escalation | `PR150_PROVISIONAL` | **REUSE / ADAPT.** Preserve shared GET-only recovery and fixed financial deadlines. |
| `recover_customer()` and customer send leases | `PR150_PROVISIONAL` | **REUSE.** Preserve the separately approved explicit-open customer retry policy. |
| LBX client, decoder, exact values and bounded retry | `MAIN_CONFIRMED`, extended by Step 7 | **REUSE.** Add the lifecycle boundary and dedicated worker resources. |
| `prepared-subscription:v1` observations | `PR150_PROVISIONAL` | **ADAPT.** Preparation evidence cannot replace stronger reconciled facts or renew trust. |
| Linked-state recovery correction | `PR150_PROVISIONAL`, `d28eddd` | **PRESERVE.** Transient source failure does not erase proven preparation. |
| Scheduler, enrollment, lifecycle normalization and expiry | `STEP8_TO_BUILD` | **BUILD.** |
| Webhook receiver and durable processing | `STEP8_TO_BUILD` | **BUILD; default disabled.** Real authentication/delivery remains an enablement gate. |
| Final Step 7 review | `STEP7_PENDING` | Track relevant corrections and validate the combined result. |
| Paid derivation, allowance/revision/outbox and Kernel wire | Later Steps 9–10 | **DEFERRED.** |

Concrete reusable seams:

- `apps/api/app/composition/purchases.py::recover_financial()`.
- `apps/api/app/domains/purchases/financial.py`.
- `apps/api/app/composition/billing.py::recover_customer()` and
  `apps/api/app/domains/billing/customers.py`.
- `apps/api/app/cli/billing_purchases.py`, customer diagnostics and
  `apps/api/app/composition/mapping_operator.py::resolve_operator_principal()`.
- `apps/api/app/integrations/lbx/{client,financial,current_offer,_transport}.py`.
- Existing billing models, `infrastructure/queries` helpers, shared test
  fixtures and factories.
- `apps/api/app/main.py::lifespan()`, source composition, health and
  observability boundaries.

Confirmed gaps:

- Financial work initially schedules the two-hour escalation time; it is not an
  urgent recovery loop.
- Work leases and subscription fencing fields have no running dispatcher.
- Preparation `prove_subscription()` rejects ended state `3` and is not the
  lifecycle normalizer.
- Repeated preparation binding can overwrite lifecycle/supporting-observation
  fields.
- Customer active-send leases share recovery rows and require claim
  compatibility.
- There is no working webhook receiver or Step 8 operational CLI/runbook.
- Source pools/admission are process-local. MVP needs isolated worker resources;
  a provider-wide capacity policy is a future deployment concern.

### Planning verification

On `d28eddd`, the following were rerun successfully:

- Reconciliation model, LBX client and error-contract tests: 129 PASS.
- Architecture check: PASS.
- Documentation check: PASS.

An earlier run on `7924586` stalled after 13 cases in
`test_any709_step3_purchase.py`, at the Widget-response test. No PASS is claimed
for that run. The completed Step 7 plan reports broader verification for its
correction; planning did not independently rerun that PostgreSQL/full-check
evidence. No fresh live-LBX or Step 8 runtime PASS is claimed.

## 3. Architecture, Decisions & Dependencies

### Authority and focused reading

Follow root/API/documentation instructions and:

- [ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md).
- [External Billing Boundary Design](../../superpowers/specs/2026-09-15-external-billing-boundary-design.md):
  subscription projection, webhooks, reconciliation/freshness, manual review,
  worker topology and transactions.
- [Portal–Kernel design](../../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md):
  snapshot time/clock-skew boundary for downstream handoff.
- [Accepted live-source amendment](../../superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md),
  sections 5.3–5.5.
- [Phase 0 handoff](../../superpowers/phase0/2026-10-14-any-634-lbx-evidence-handoff.md),
  B8 and B10–B15.
- [ANY-709 runbook](../../engineering/ANY-709-billing-runbook.md): Step 8 seam and
  final recovery corrections.
- Current as-built schema, coding conventions, testing, reliability and
  security requirements. The [Kernel map](../../integrations/platform-kernel.md)
  supplies the downstream boundary; no Kernel code or fresh real-producer
  conformance is claimed by this ticket.

The ANY-715 owner decision resolves the retained settlement-proof ambiguity:
LBX owns activation and blocking. Complete owned, commercially verified,
supported prepaid ACTIVE/unblocked facts provide the operational source
conclusion. Do not reconstruct settlements through charges, payments, balance
changes or balance. Do not rewrite canonical architecture specifications here.

### One shared Application implementation

HTTP, worker and CLI are entrypoints into shared use cases:

- Integration authenticates, decodes and normalizes LBX.
- Application owns proof requirements, transitions, transaction boundaries,
  conflicts, recovery and audit.
- Persistence implements claims, locks, queries and atomic storage mechanics.
- Entrypoints own transport, scheduling, operator authorization and presentation.

Reuse the same reconciliation and recovery functions. Do not implement separate
worker or CLI versions of ownership checks, accepted-term comparison, binding or
trust renewal. Authorization differences remain explicit: a worker cannot
acquire a permission reserved for an authenticated user's explicit advance or
an audited operator action.

### Authoritative read contract

For a known canonical subscription, use one bounded set of four point reads,
with IDs taken from the permanent local bindings and accepted purchase:

1. `get_user()` — paired provider customer ID and immutable Portal customer key.
2. `get_agreement()` — original canonical agreement, customer, seller and
   permanent agreement correlation.
3. `get_tariff()` — relevant supported prepaid/blocking policy and currency
   interpretation; sale visibility/archive fields do not decide old purchases.
4. `get_subscription()` — identity, effective services/quantity/prices/total/
   currency, period, lifecycle/blocking and original calendar values. Read it last
   so the lifecycle/effective-term point is the latest read in the set.

Each read proves a different required fact; none can be replaced by a discovery
list, stored preparation evidence or current catalog price. Reuse the paired
customer check and exact original agreement/seller/correlation proof. Check the
applicable tariff flags for the supported prepaid, full-funding, auto-blocking,
non-demo/non-prorated profile, without importing new-sale availability rules.

Remove unconditional duplication of this set: neither the authority documents
nor the existing point contracts require two rounds. The DTOs expose no common
source revision or atomic snapshot; repeating all GETs does not establish one.
Record the read window/provenance and verify all returned identities, joins and
material facts against the original purchase. Contradictory, missing or unknown
proof cannot renew positive trust and schedules a bounded later retry. Do not
claim that an undetected concurrent provider change is impossible.

All reads share one absolute operation budget. Reuse existing decoding,
`Decimal` handling and GET retry policy. Four is the normal business-read set,
not a wire-request limit including authentication and bounded transport retries.

Compare against the original accepted purchase and original link revision:

- Current catalog price does not reprice an old subscription.
- Current publication, Kernel availability and sale visibility do not gate
  historical reconciliation.
- Tariff policy reads do not replace effective subscription prices.
- Sale-only archive/visibility changes do not invalidate an existing
  subscription.
- Unsupported or missing applicable policy prevents positive trust refresh.

Keep lifecycle normalization separate from preparation restrictions. Reuse
narrow commercial comparison logic where appropriate. A terminal/closed source
must still yield owned negative facts; preparation-only open-agreement and
nonterminal restrictions must not reject that ordinary lifecycle observation.

Normalized output must include local identity and immutable purchase/link/legal
provenance; `COMPLETE_MATCH`, `COMPLETE_MISMATCH` or `INCOMPLETE` commercial
classification; independent lifecycle and operational financial conclusions;
original calendar values/completeness; read timing, provenance and bounded
reason codes. Only Integration interprets LBX numeric states.

Waiting/unpaid may legitimately have null cycle dates. Positive operational
proof requires coherent current-cycle evidence; missing/sentinel/contradictory
cycle values cannot establish new positive trust. Preserve calendar facts
without inventing UTC boundaries or allowance/cycle identity.

### Decision matrix

| Source result | Persisted conclusion | Retry, trust and handoff |
|---|---|---|
| Owned waiting `state=-2/block=0`, including null cycle dates | Real inactive/blocked observation; commercial match when supported | Urgent polling; no invented paid period |
| Fully verified supported prepaid `state=2/block=0` | Active/allowed operational facts and complete matching evidence | Finite source trust; normal cadence when urgency clears; no grant |
| Same owned subscription reports a coherent new calculation period, with unchanged accepted effective terms | Updated calendar/lifecycle facts; no inferred settlement | Refresh trust only on complete proof; no allowance/cycle ID or UTC invention |
| Financial block `2/1` or administrative block `2/3` | Ordinary negative facts with distinct reason | Supersede prior positive usability immediately |
| Insufficient funds are suspected, but LBX has not supplied a complete confirmed block | No Portal accounting conclusion from balance or missing renewal fields | Preserve only existing finite LKG; retry incomplete evidence; `2/1` is the confirmed financial-block case |
| Ended `3/0` | Terminal ended/blocked fact | No automatic revival or silent hold release |
| Previously ended canonical ID becomes nonterminal | Terminal-revival conflict | Remain ineligible; controlled review |
| Catalog 10→20; original effective subscription remains accepted 10 | Original terms still match | No false conflict or repricing |
| Effective subscription 10→15, or changed service/quantity/currency | Commercial mismatch when sufficiently proven | Ineligible conflict and review |
| Missing/contradictory fields, timeout, 404 or exhausted budget | Incomplete/unknown observation | No trust extension; prior good facts only until their existing deadline |
| Foreign customer/agreement or canonical identity drift | Identity conflict | No silent rebind; affected positive usability removed |
| UNKNOWN create: zero / one / multiple candidates | Uncertain / original point-proven binding / ambiguity | GET-only recovery; unchanged fixed deadline |
| `PROVEN_NOT_SENT` | Completed typed no-send evidence | No autonomous POST or overdue UNKNOWN conversion |
| Trust deadline due | Local expiry evidence | Provider-free processing; Step 9 owns later access revision/outbox |
| Complete matching source proof returns after outage/expiry | Fresh owned facts with a new finite trust deadline | Original identities/history remain; Step 9 alone derives paid access |
| Local `503 billing_busy` / user-lock `55P03` | Local PostgreSQL contention, not an LBX result or no-send proof | Retry appropriate local/GET work safely; preserve create state, original key/fence and deadline |

Decisive authoritative negative/conflict evidence must not be hidden by
unrelated missing commercial fields. Applying it still requires proof of the
intended canonical subject.

Existing known financial/manual-review conflicts cannot be cleared by ordinary
polling merely because terms later match. Preserve the approved customer
original-key restoration policy separately; do not generalize it into automatic
financial-conflict resolution.

### Projection and writer rules

Use existing subscription, observation, scope and review tables. Create/reuse
`BillingProductAccessScope` with `primary_subscription_id=NULL` for observation
provenance. Do not implement primary selection.

Shared Application apply must:

- Renew trust only on complete authoritative proof.
- Anchor trust conservatively to the beginning of the successful read set.
- Bound it by six hours or an earlier independently proven absolute deadline.
- Leave date-only periods as calendar facts.
- Append incomplete-attempt evidence without replacing the complete supporting
  observation.
- Immediately record negative/conflicting usability changes.
- Keep all Step 8 `resulting_access_revision` values null.

Use existing `deterministic_access_boundary` observation shape for trust expiry,
with scope, subscription, effective deadline and supporting observation. Preserve
source timestamps/history; local expiry is not a new provider financial block.
Step 9 will attach any earlier effective authorization deadline required by its
clock-skew policy; Step 8 does not invent a Portal–Kernel skew value.

Repeated Step 7 preparation/payment proof may append preparation evidence but
cannot overwrite reconciled lifecycle, financial status, supporting observation
or trust. Preserve `d28eddd` linked-state behavior.

### Durable worker and backpressure

Initial topology: one embedded supervisor in API lifespan, one API replica,
PostgreSQL-durable work. Use concrete work kinds:

- `external_create_recovery`
- `subscription_reconciliation`
- `customer_inventory`
- `billing_enrollment_sweep`
- `subscription_trust_expiry`
- `external_create_deadline`

Coalesce by server-resolved account/local object identity. Repeated hints update
existing work and bring it forward; they do not create another pending copy
every interval.

Add to existing work storage a nonnegative enqueue generation counter, a
last-attempt-start timestamp and unique coalescing indexes for new kinds,
preserving existing recovery identity. A completion cannot clear a newer hint.

Use short `FOR UPDATE SKIP LOCKED` claims, unique claim ownership, lease expiry
and conditional completion. Subscription reads additionally use the existing
monotonic reconciliation fence. Use database time for persisted claims/due
comparisons and monotonic elapsed time for outbound budgets.

Claim only available execution capacity. Do not lease a large batch and leave
most of it waiting in memory until its lease expires. Never hold queue locks
while acquiring business locks. Claim/commit, then acquire the subscription
lease separately. Network I/O occurs outside transactions. Apply follows the
established business lock order, with work finalization last.

#### Automatic enrollment and restart/backfill

When Step 7 creates the canonical local subscription, atomically insert/coalesce
its immediate reconciliation job in that same transaction. Repeated preparation
readback must not re-enroll an already monitored subscription or reset its due
time. Recovered bindings use this same enrollment path.

Run local enrollment sweeps at startup and every 60 seconds, without provider
I/O. Select only eligible linked subscriptions in the configured account that
lack usable recurring reconciliation work, ordered by local subscription ID,
with a batch limit of 100. Use an anti-join against the durable coalescing key;
there is no offset or cursor that can skip missing records.

Commit idempotent inserts/reactivation for the batch, yield to other worker
tasks, then query the remaining missing set. Continue until it is empty. The
previous batch leaves the missing set after commit, so the next query reaches
later subscriptions instead of repeating the first 100. On restart, repeat from
the missing set; committed enrollment itself is the durable progress marker.

The unique job key handles concurrent linking, sweeps and webhook enqueue. A
race uses upsert/recheck, not duplicate jobs or a new immediate hint. Existing
pending/running jobs, including future-due jobs and expired leases awaiting
reclaim, are already enrolled: preserve their schedule, generation and ownership.
An unexpectedly completed recurring job is reactivated safely. Do not reclassify
completed `PROVEN_NOT_SENT` operation recovery as missing UNKNOWN work.

Eligibility requires the original purchase/customer/link provenance and canonical
subscription binding; never adopt a foreign or unproven subscription. Isolate
and report a malformed historical record rather than repeatedly failing the
whole sweep or hot-looping. Apply equivalent bounded/idempotent repair to missing
inventory, unresolved recovery and local deadline jobs without moving an
existing UNKNOWN deadline or trust deadline.

#### Timeout, expired leases and unfinished I/O

Reuse `PreflightAdmission` / `PreflightBudget` for dedicated worker resources.
One execution slot owns its outbound task through actual completion/cleanup,
including when the waiter times out or is cancelled. A timed-out waiter or an
expired database lease never releases that occupied slot or permits detached
replacement HTTP to accumulate. Do not restart a failed runner over still-live
resource owners.

Reserve cleanup inside the total configured I/O budget. Derive the claim and
subscription lease duration from that budget plus a bounded local apply/safety
margin (initially 30 seconds); do not allow the ordinary lease to expire before
the permitted read/cleanup window. Use the existing finite DB lock policy and
short apply transactions; no heartbeat/distributed execution framework is needed.

A lease can nevertheless expire during a paused process or uncooperative I/O.
A second handler may reclaim work with fresh ownership and a higher subscription
fence. Apply must recheck both current work ownership and the subscription
owner/fence/lease under the business locks, plus original purchase/scope facts.
Reject expired, superseded or timed-out attempt results even if their old GET
eventually succeeds. Conditional completion cannot clear a newer claim/hint.

Failure/cancellation leaves durable work retryable; a lost claim acknowledgement
does not start HTTP until ownership is established. Shutdown stops claims, drains
bounded work and cancels/awaits source cleanup using the existing policy. If
cleanup remains pending, retain its resource ownership, report degraded health
and do not claim successful shutdown. A process exit leaves leases reclaimable.
All repeated external operations on these paths are GET-only.

Approved schedules:

- Known normal reconciliation: approximately 15 minutes.
- Urgent attempts: no more than five minutes apart.
- Stable customer inventory: approximately six hours.
- Source trust: at most six hours.
- Financial UNKNOWN escalation: original `unknown_since + 2h`.

Urgency includes unresolved work, never-positive linked subscriptions and trust
expiry within 30 minutes. Distribute recurring due times across the interval,
using earlier-only jitter where a maximum interval applies. Newly linked
subscriptions remain immediately due.

Use bounded backoff and existing transport retry semantics. Scheduling accounts
for operation duration. Authentication/configuration failures use cooldown and
alerts. Keep financial escalation separate from retry cadence; exclude completed
`PROVEN_NOT_SENT` from overdue UNKNOWN work. Customer explicit-open retries retain
their separately approved per-attempt policy.

### MVP resource controls and future expansion

Separate reusable job execution from FastAPI startup. The runner must not depend
on HTTP request objects or own another business state machine. Implement only
the embedded startup mode for MVP; no standalone worker CLI/container or
horizontally scaled production deployment is required now.

Resource settings:

- `BILLING_WORKER_ENABLED`, default true.
- `BILLING_WORKER_URGENT_CONCURRENCY`, initial default 2.
- `BILLING_WORKER_NORMAL_CONCURRENCY`, initial default 1.
- `BILLING_WORKER_IO_TIMEOUT_SECONDS`, initial default 60.
- `BILLING_WORKER_SCAN_BATCH_SIZE`, initial default 100.

Normal reconciliation and inventory share normal capacity. Local deadlines have
independent execution capacity and perform no provider HTTP. Worker clients,
HTTP pools and bounded database delegation are isolated from new-sale and Widget
resources. Wholly unconfigured LBX leaves the worker `not_configured` without
source calls.

The concurrency limits apply per worker process, not provider-wide. The initial
one-process deployment bounds worker calls by the configured urgent plus normal
slots; interactive purchase/Widget/CLI calls have their own existing budgets.
Finite GET timeouts/retries and retained cleanup ownership prevent abandoned
requests from creating an unbounded tail. These are not global requests-per-second
quotas. Record active slots, cleanup-pending work, failures, queue age, cadence
lag and last successful progress with bounded-cardinality telemetry.

Keep PostgreSQL claim/fence/coalescing correctness safe for competing handlers;
test it with two handlers. Do not build aggregate admission, fleet configuration
consensus or a new distributed limiter for this initial deployment. Any future
increase in process count must account for multiplied per-process limits and
actual LBX quotas before enablement.

Document a short future expansion path in the runbook:

1. Diagnose growing queue age/latency using real operating evidence; tune bounded
   concurrency and timing within provider limits when needed.
2. If API resource isolation requires it, add a thin standalone entrypoint for
   the same runner and shared Application functions. Disable embedded startup,
   stop claiming, drain/stop the old owner and restart against the same durable
   jobs. Preserve a rollback path.
3. Add consumers or optimize LBX reads only after measured need. Reuse existing
   claims/leases/fences and introduce aggregate rate/concurrency enforcement if
   required by the chosen deployment/provider limits.

Those are future operational changes, not Step 8 deliverables. No synthetic
subscription-count target, separate capacity benchmark, speculative MQ, sharding,
retention deletion or autoscaling framework is required. Small deterministic
tests must still prove bounded work, urgent/local progress and visible lag during
source slowness. Backlog never extends trust or makes unfinished work a PASS.

### Webhook mode and production setup

Implement webhook and independent polling. Default webhook off.

The [official configuration guide](https://docs.lbxbilling.ru/api/webhooks/set_webhooks/)
documents manual URL/token/event setup. No configuration endpoint was found in
the inspected [public Swagger](https://demo.lbxbilling.ru/swagger/swagger.json).
Treat manual setup as the supported deployment procedure; do not infer an
undocumented API.

Initial receiver event allowlist, from
[official examples](https://docs.lbxbilling.ru/api/webhooks/list_webhooks/):

- `create_subscription`
- `change_subscription`
- `block_subscription`
- `new_charge_period`
- `close_subscription`
- `delete_subscription`

Implement `POST /api/billing/lbx/webhook` with named response DTOs:

- `LBX_WEBHOOK_ENABLED=false`.
- Required `LBX_WEBHOOK_AUTH_HEADER` and secret `LBX_WEBHOOK_AUTH_VALUE` when
  enabled.
- Exact constant-time shared-secret-header verification.
- No anonymous, query-token or guessed-signature fallback.
- Deployment-resolved account/contour.
- Authentication before bounded body processing.

The actual header/value transport remains a real integration gate. If the chosen
account cannot use the supported secure mode, keep disabled; do not claim
compatibility. Disabled mode returns 404 without processing the payload.

In one short transaction, save redacted receipt/correlation and coalesce immediate
work before acknowledgement. No provider REST occurs in the request. Unknown
authenticated correlation may be recorded as ignored. Conflicting/cross-scope
hints cannot create bindings or route work to another user.

Use safe hashes and allowlisted fields. Do not persist raw bodies, headers,
credentials or payment/PII fields. Duplicate safety comes from coalescing and
fenced GET/apply. Without a proven unique provider event ID, do not permanently
suppress future events using a payload hash.

Mark only receipts covered by a successful claim as processed; later arrivals
remain due through their generation. The inbox must retain enough local work
correlation to inspect and retry processing without retaining raw payload.

Enablement requires real test-LBX authentication, delivery, correlation,
duplicate handling and event-to-GET verification. Correctness never assumes
HTTP 500 causes LBX redelivery. Gate failure leaves `DISABLED/POLLING-ONLY` and
does not block core Step 8 acceptance.

### Documentation ownership and freshness

Create one operational authority:
`docs/engineering/ANY-715-billing-operations.md`. It must contain:

1. Embedded startup, shutdown, restart and the distinction between implemented
   behavior and the future standalone expansion path.
2. Approved cadence, trust, UNKNOWN and retry semantics.
3. Every resource setting, unit, default and per-process scope; do not describe
   these as provider-wide quotas.
4. Exact manual webhook setup for test and production: endpoint, event list,
   secret location, verification and disablement.
5. Every supported CLI command, arguments, prerequisites, effects, refusal cases
   and examples.
6. Monitoring, backlog diagnosis, outage response and safe recovery.
7. Backlog diagnosis and the short future expansion path, with no hypothetical
   load target or unimplemented deployment commands.
8. Current real/simulated/unverified integration status.

Never put secret values in examples. Every implementation step updates its
runbook section in the same change. Do not postpone documentation until the final
step.

Add focused documentation-contract tests comparing CLI names/options with the
real parser, resource names/defaults with Settings, receiver route/events with
implementation, and runbook coverage of operational actions. Structural tests
cannot prove vendor UI/authentication behavior. Keep a dated real-integration
checklist and require semantic review when assumptions change.

Update `docs/README.md` navigation and affected current-state architecture,
reliability, security and schema guidance. Do not create another research report
or rewrite accepted architecture specifications.

## 4. Functional DoD & Acceptance Coverage

| Capability | Owner steps | Acceptance evidence |
|---|---|---|
| Verified lifecycle/commercial facts, including renewal/block/end | 1, 2 | Synthetic lifecycle integration and configured read-only checkpoint |
| Historical terms and conflict distinction | 1, 3 | Catalog-change versus effective-change tests |
| Shared HTTP/worker/CLI semantics | 1–5 | Shared use cases and equivalent behavior through entrypoints |
| Enrollment, restart and durable polling | 2 | Several small batches, restart/concurrent enqueue; no browser dependency |
| Claims, fencing and lost-hint safety | 2 | Two-handler PostgreSQL tests, expired lease with unfinished GET, crash/cancel |
| Bounded MVP execution and future expansion | 2, 5 | Isolated lanes, retained cleanup slots, embedded smoke and runbook |
| UNKNOWN and immutable two-hour deadline | 3 | Zero/one/multiple, no-send, crash and lost-reply tests |
| Local `billing_busy` preserves CREATE authority | 3 | PostgreSQL contention and shared recovery regressions |
| Inventory and same-tariff ownership | 3 | Proven other-product exclusion and bounded incomplete inventory |
| Trust expiry and unaffected scopes | 1, 2 | Controlled-clock outage and expiry-race tests |
| Optional durable webhook | 4 | Synthetic HTTP/PostgreSQL tests; separate real gate |
| Narrow audited operator controls | 5 | Allowed resolutions, stale-proof/refusal/audit tests; no terminal hold release |
| Current runbook and scaling strategy | All | Documentation-contract tests and operational review |
| Step 9 handoff | 5 | Versioned facts, deadlines, constraints and exact evidence |

## 5. Sequential Implementation Steps

### Shared verification commands

Use existing harness environment ownership for focused selections:

```bash
PYTHONPATH=.:apps/api .venv/bin/python - <<'PY'
import subprocess
from scripts import repo

target = "api-fast"
selection = "billing_subscription_reconciliation"
environment = repo.api_test_environment(
    target, repo.canonical_check_environment()
)
subprocess.run(
    repo.api_pytest_command(
        *repo.api_test_marker_args(target), "-k", selection
    ),
    env=environment,
    check=True,
)
PY
```

For PostgreSQL, use `target="api-postgres"` after `make test_db_up`. Shared pytest
fixtures own the disposable physical database. Stop only the server started for
this work. During each step:

```bash
.venv/bin/python scripts/repo.py lint api
npm run architecture:check
npm run docs:check
```

Format changed Python with repository Ruff tooling. Run `npm run generate` after
model/OpenAPI changes, followed by `npm run generate:check`. Do not hand-edit
generated files. Do not run the full suite after every step without cause.

### Step 1 — Establish shared authoritative reconciliation

**Goal**

Produce defensible provider-neutral subscription facts through one reusable
Application path.

**Expected behavior**

Composition reads the original purchase and bounded LBX proof outside
transactions. Integration normalizes it. Application verifies current
ownership/fences and persists accurate positive, negative, incomplete or conflict
evidence. Later preparation/payment readback preserves those stronger facts.

**Read before implementation**

- Root/API instructions and authority sections listed above.
- `apps/api/app/integrations/lbx/{financial,client,current_offer}.py`.
- `apps/api/app/domains/purchases/{contracts,service,financial}.py`.
- Subscription, observation, scope and review models/enums.
- `test_any709_step3_purchase.py`, `test_any709_step3_postgres.py`,
  `test_any709_review_fixes_postgres.py`, reconciliation model tests and factories.

**Implementation**

- Add focused contracts/Application reconciliation under the existing billing
  slice and LBX normalization under Integration.
- Implement the read/decision matrix and bounded evidence.
- Use the four distinct point reads once per normal attempt; explain their
  proof responsibilities and test missing/contradictory fields. Do not duplicate
  current-offer/catalog reads or add a second full proof round.
- Reuse original consent, accepted snapshot and permanent identities.
- Share commercial comparison without weakening preparation restrictions.
- Establish scope provenance with no selected primary.
- Implement complete/incomplete/negative/conflict transitions and terminal
  revival protection.
- Respect financial review cases and the distinct customer restoration policy.
- Prevent preparation writers from overwriting reconciled facts; preserve
  `d28eddd`.
- Create runbook sections for proof, state/trust semantics and evidence levels.
- Add behavior tests and initial documentation-contract coverage.

**Invariants / Non-goals**

No current-price reapproval, Kernel preflight, settlement reconstruction, grants,
automatic hold release or UTC cycle invention.

**Verification**

Run `billing_subscription_reconciliation` fast/PostgreSQL selections and affected
Step 7 regressions. Cover required statuses, null waiting dates, unknown status,
historical/catalog changes, effective drift without instance change,
missing/extra service, quantity/currency/owner mismatch, contradictory read sets, terminal
revival, known review and concurrent preparation/reconciliation.

For the normal known-subscription path, assert one call to each of the four point
methods (authentication/transport retry tests remain separate). Cover waiting →
active, both blocking types, active → next calculation period with unchanged
terms, provider-confirmed underfunding block, ended and incomplete renewal facts.
Assert the same purchase/bindings survive and no Portal payment/allowance/cycle
identity is invented. Contradictory returned facts reject positive proof; do not
claim atomic provider-snapshot detection from these tests.

Owner checkpoint: inspect representative sanitized normalized outputs.

**Expected completion**

After this step, the system can reconcile an owned subscription through shared
Application logic and preserve its facts across subsequent preparation reads.

**AI execution prompt**

> Implement Step 1 of `docs/exec-plans/active/ANY-715-implementation-plan.md`. Read its decision matrix, LBX financial/client/current-offer modules, purchase contracts/service/financial transitions, billing models and Step 7 effective-term/recheck/review tests. Build the shared bounded authoritative read/normalization/apply path using the four distinct point reads, without a second full round or current catalog repricing. Verify their identities, original terms and supported policy; preserve the read window without claiming an atomic source snapshot. Cover waiting, activation, renewal/calendar changes, confirmed financial/admin blocking and ended states. Preserve original accepted history, finite trust and known-review rules. Protect reconciled facts from preparation-only writes and preserve the `d28eddd` linked-recheck correction. Create the relevant operational runbook sections and documentation checks.
>
> Follow the repository's root and applicable subtree AGENTS.md files, ARCHITECTURE.md, docs/engineering/CODING_CONVENTIONS.md, docs/engineering/AGENT_WORKFLOW.md, and docs/engineering/TESTING.md. Respect existing architectural layers, coding conventions, typing, error handling, transaction ownership, dependency direction and established project structure. Use equivalent authoritative instructions in other affected repositories.
>
> Implement only the specified step. Reuse existing components and preserve the agreed functional outcome and invariants. Do not broaden the scope or start subsequent steps.
>
> Run appropriate formatters, linters and focused automated tests. Fix failures caused by your changes and rerun affected checks. Run additional relevant validation when necessary; report unexecuted or blocked checks accurately.
>
> Run `billing_subscription_reconciliation` fast/PostgreSQL selections, affected Step 7 regressions, architecture and documentation checks using the plan's recipe. Prove the minimum read set, historical-price matching, missing/contradictory-proof rejection, lifecycle/renewal normalization, incomplete-read trust limits, ordinary negative states and writer concurrency. Use synthetic provider transitions; do not execute real payments.
>
> If a material contradiction appears, investigate the relevant surrounding context and available evidence, then propose a resolution. Stop and ask only when an important decision cannot be made safely.
>
> Do not run mutating operations against real billing or other external production systems without explicit authorization.
>
> Do not stage, commit, push, switch branches, merge or rebase. Do not modify unrelated worktrees.
>
> Report the implemented behavior, changed files, verification results, remaining limitations and any required manual QA.

**Proposed commit**

`ANY-715 - Establish shared authoritative reconciliation`

**Step 1 execution evidence — 2026-10-28**

- Shared claim/read/normalize/apply, original provenance, finite trust,
  negative/conflict handling and preparation-writer protection are implemented.
  No worker, queue enrollment, webhook, operator command or paid-access producer
  is enabled by this step.
- `billing_subscription_reconciliation`: 42 fast tests and 7 PostgreSQL tests
  PASS with synthetic sources. The PostgreSQL coverage includes minimum reads,
  lifecycle/history, outage beyond trust expiry, review preservation,
  preparation races, fencing, customer restoration, timeout and HTTP 404.
- Affected Step 7 PostgreSQL suite: 32 PASS on isolated rerun. The first combined
  selection reported failures under concurrent checks and hit its 240-second
  wrapper limit before a failure summary; it is not a PASS. The isolated rerun
  completed without those failures.
- API Ruff lint/format, architecture, documentation, generated-artifact
  freshness and `npm run check:fast` PASS. The fast canonical run included
  1,489 API tests, 38 web boundary tests and 370 component tests.
- `npm run check` PASS, including the production web build and all 282
  PostgreSQL tests. The final source-scope guard was followed by another
  42-test focused fast PASS. Browser E2E was skipped by the canonical harness
  because `RUN_E2E=true` and a running browser stack were not supplied.
- The [operations runbook](../../engineering/ANY-715-billing-operations.md)
  records implemented semantics and deferred runtime work. Sanitized normalizer
  examples were inspected locally and saved under ignored
  `.harness/any715-step1-normalized-examples.json`; they are SIMULATED and do not
  represent executed provider point reads.
- Real LBX normalized-output inspection, untouched natural renewal and human
  owner acceptance remain NOT_RUN. No real financial mutation or Git mutation
  was performed.

### Step 2 — Run durable polling with bounded execution

**Goal**

Make monitoring automatic for new and existing subscriptions, restart-safe and
bounded within the single-process MVP deployment.

**Expected behavior**

Linking atomically enrolls subscriptions. The local sweep drains successive
missing-work batches, preserving existing schedules, and repeats safely after
restart. The embedded runner claims only available slots, reads LBX outside
transactions, applies current fenced results and reschedules safely. Expired
leases cannot make old reads authoritative or free still-occupied HTTP slots.
Local deadlines continue during slow provider work.
The two enabled mock products, `proposal_ai` and `brief_decoder`, have separate
owned subscriptions and independently enrolled/reconciled facts, including after
restart. Mock Kernel supplies only technical product/metric identity; synthetic
LBX responses supply subscription states.

**Read before implementation**

- Step 1 Application contracts/transitions.
- `apps/api/app/main.py`, `composition/sources.py`, work/subscription models.
- `infrastructure/preflight.py` (`PreflightAdmission`, `PreflightBudget`), its
  cancellation/cleanup tests, customer leases and query/persistence rules.
- `http/health.py`, observability and Sentry boundaries.
- `apps/api/alembic/versions/20261027_0003_normal_billing.py`.
- Settings, Compose variants, harness propagation and deployment tests.
- Selective reference: `any-765-mock-two-products`, commit
  `c1b093757702c112298a07f60999e9697f0efcd4`. Inspect its diff for
  `tools/kernel_manifest_mock/server.py`, the versioned manifest fixture/digest,
  `apps/api/tests/support/kernel.py`, manifest client/mock tests and
  `scripts/check_kernel_manifest_contract.py`; adapt against current ANY-715.

**Implementation**

- Implement the transport-independent runner and lifespan supervision.
- Add queue mechanics, dedicated bounded admission, generation-safe coalescing
  and subscription fencing; reuse existing unfinished-I/O ownership.
- Add a forward migration for work generation, attempt-start timestamp and
  coalescing constraints. Do not rewrite predecessor migrations.
- Enroll links atomically and implement the missing-set sweep above. Keep each
  batch at most 100, yield between commits and continue until no work is missing.
  Do not reset existing future jobs or mistake expired leases for absent jobs.
- Implement approved cadence, due-time spreading, backoff and local expiry.
- Derive leases from the total I/O budget plus the bounded apply/safety margin.
  Reject expired/timed-out/stale apply; retain slots until real cleanup ends.
- Keep the runner independent of HTTP startup, but implement only embedded
  startup. Future extraction does not require another business implementation.
- Add named `/api/health/billing` output and worker-aware readiness. Liveness
  remains DB-independent; LBX outage alone does not make the identity API unready.
- Propagate settings and disable unattended source work in ordinary tests.
- Document settings, shutdown/restart, batch progression, per-process limits and
  the future expansion path immediately.
- Add settings documentation tests and small competing-handler coverage.

**Selective two-product mock reuse**

Port only compatible technical mock/fixture/test changes from the referenced
commit. Keep the complete six-product manifest with `proposal_ai` and
`brief_decoder` enabled, and independent TEST-ONLY metrics
`proposal_ai.test_generations` (`generation`) and
`brief_decoder.test_analyses` (`analysis`). Update the fixture semantic digest
and independent expected values consistently. Adapt mock missing/disabled
product/metric scenarios to affect only their intended product; preserve the
other product and its metric. Scope contract-checker metric selection to the
selected product instead of all manifest metrics.

Preserve current manifest schema, routes, service authentication, contour/scope
checks and SIMULATED provenance. Update only applicable fixture-description
text and tests that assumed one enabled product. Do not merge/cherry-pick the
whole ANY-765 branch or replace current files with its old Step 7 versions.
Reuse the completed Step 1 contracts; do not redo that step or its evidence.

Exclude the donor's `paid-access-test-offers.json`, its loading/OpenAPI metadata
and the associated 100/300 allowance examples/tests. Those quantities belong to
future Step 9, not the Capability Manifest or Step 8 subscription proof. No
allowances, grants or quota calculations are introduced. Mock discovery remains
test setup, not a new Kernel dependency for historical reconciliation. Use
synthetic LBX GET responses and disposable local records for both subscriptions;
do not create real paid/provider objects.

**Invariants / Non-goals**

No network under locks, in-memory correctness queue, generic scheduler, new
billing service, standalone deployment, aggregate distributed admission,
speculative MQ, paid-state writer or automatic scaling policy.

**Verification**

Run `billing_worker` fast/PostgreSQL selections, migration, health, composition
and affected deployment tests. With batch size 2 and five eligible subscriptions,
prove all three batches enroll, restart after a committed batch completes the
remainder, a new link is immediate, and concurrent sweeps/linking create one job.
Verify repeated sweeps preserve existing future due times and expired claims.

Add a small two-product PostgreSQL/integration fixture for the same user and
billing account with independent purchases/agreements/subscriptions. Verify
both products enroll through linking and backfill, duplicate hints coalesce per
subscription without collapsing product jobs, each reconciles its own synthetic
LBX facts, and restart preserves both schedules/bindings. Inspect separate work,
observation and projection identities; no paid-state writes are permitted.

Run affected `test_kernel_manifest_mock.py` and
`test_kernel_manifest_client.py` coverage and the existing contract checker
(`.venv/bin/python scripts/check_kernel_manifest_contract.py`). Verify both
metrics, consistent semantic digests and product-specific mock failure cases,
without importing Step 9 quantity expectations or weakening contract guards.

Use two handlers and controlled clocks/transports to cover: A's lease expires
while its GET remains live; B reclaims/applies; A cannot overwrite or complete B's
work; the old HTTP slot remains counted. Also cover cancellation-resistant
cleanup, timeout/restart, lost claim acknowledgement, hints during execution,
customer-send lease exclusion, normal/urgent fairness, provider-free deadlines
under occupied source slots and expiry-versus-refresh races. Assert bounded
active requests and no external CREATE, without a large load test.

Smoke-test embedded startup with injected/local simulated sources. Run no
production worker. Owner checkpoint: inspect startup, health, batch progress,
persisted work and the documented future expansion path.

**Expected completion**

After this step, the system can automatically monitor every eligible linked
subscription, resume durable work after restart and reject stale handler results
with bounded embedded execution and visible backlog. The two enabled technical
mock products independently enroll and reconcile through synthetic LBX facts;
neither product's job or observation is reused as the other's.

**AI execution prompt**

> Implement Step 2 of `docs/exec-plans/active/ANY-715-implementation-plan.md`. Read Step 1, API lifespan/source composition, work/subscription models, PreflightAdmission/PreflightBudget and cleanup tests, customer leases, health/telemetry, migration `20261027_0003`, Settings and deployment/harness tests. Build the transport-independent runner with embedded startup only, atomic enrollment and the bounded missing-set backfill, PostgreSQL claims/fences, generation-safe coalescing, approved scheduling and local expiry. Preserve existing due times during repeated sweeps. Reuse isolated bounded resource admission; unfinished HTTP keeps its slot, and expired/timed-out/superseded results cannot apply. Derive leases from the I/O budget and bounded apply margin. Document per-process limits and future extraction/expansion; do not implement standalone deployment or distributed admission now.
>
> Selectively adapt the technical mock/fixture/test hunks of `c1b093757702c112298a07f60999e9697f0efcd4` from `any-765-mock-two-products`: enable `proposal_ai` and `brief_decoder` with their distinct test metrics, keep digest expectations consistent and isolate mock product/metric scenarios. Do not import the donor branch, old Step 7 code, paid-access example loading/OpenAPI metadata or 100/300 expectations. Reuse completed Step 1 unchanged. Add independent two-product enrollment/reconciliation/restart coverage using synthetic LBX GETs; Mock Kernel is technical vocabulary, not billing-state authority or a new reconciliation dependency. No real paid objects, allowances, grants or quota calculations.
>
> Follow the repository's root and applicable subtree AGENTS.md files, ARCHITECTURE.md, docs/engineering/CODING_CONVENTIONS.md, docs/engineering/AGENT_WORKFLOW.md, and docs/engineering/TESTING.md. Respect existing architectural layers, coding conventions, typing, error handling, transaction ownership, dependency direction and established project structure. Use equivalent authoritative instructions in other affected repositories.
>
> Implement only the specified step. Reuse existing components and preserve the agreed functional outcome and invariants. Do not broaden the scope or start subsequent steps.
>
> Run appropriate formatters, linters and focused automated tests. Fix failures caused by your changes and rerun affected checks. Run additional relevant validation when necessary; report unexecuted or blocked checks accurately.
>
> Run `billing_worker` fast/PostgreSQL selections and affected migration, health, deployment, composition and documentation tests. Use several small enrollment batches and a restart/concurrent enqueue. Use two handlers to prove stale-apply rejection after lease expiry with unfinished HTTP, retained slots, bounded cancellation/timeout cleanup, reserved deadline/urgent progress and lost-hint safety. No capacity benchmark or large fixture population is required. Generate changed model/OpenAPI artifacts through repository tooling.
>
> Run the affected manifest mock/client tests and existing contract checker, plus focused two-product worker/PostgreSQL cases. Assert separate jobs, bindings, observations and trust; duplicate hints and restart must not conflate products. Keep existing schema/auth/scope/provenance checks intact.
>
> If a material contradiction appears, investigate the relevant surrounding context and available evidence, then propose a resolution. Stop and ask only when an important decision cannot be made safely.
>
> Do not run mutating operations against real billing or other external production systems without explicit authorization.
>
> Do not stage, commit, push, switch branches, merge or rebase. Do not modify unrelated worktrees.
>
> Report the implemented behavior, changed files, verification results, remaining limitations and any required manual QA.

**Proposed commit**

`ANY-715 - Run durable polling with bounded worker execution`

### Step 3 — Recover uncertain creates and discover conflicts

**Goal**

Automatically recover uncertain operations and identify customer inventory
conflicts without duplicate external commands.

**Expected behavior**

Urgent GET recovery runs independently of fixed deadline work. One original
point-proven candidate may bind; zero remains uncertain; ambiguity enters review.
Recovered subscriptions enroll in reconciliation. Inventory recognizes another
product only through permanent local ownership and original accepted proof.
`proposal_ai` and `brief_decoder` may share an LBX tariff while retaining distinct
accepted purchases, dedicated agreements, subscriptions and recovery outcomes.

**Read before implementation**

- `recover_financial()` and financial claim/bind/pending/escalation.
- `recover_customer()`, customer point proof, send leases and escalation.
- Purchase/customer queries and other-product inventory proof.
- Steps 1–2 runner/shared transitions.
- Step 7 UNKNOWN/no-send/lost-ack/same-tariff/contention tests.
- Step 2's adapted two-product mock/fixtures and synthetic LBX setup; reuse the
  current same-tariff ownership proof, not the donor branch's old purchase code.

**Implementation**

- Connect existing GET-only recovery to worker-owned resources/budgets.
- Separate urgent recovery from `external_create_deadline`.
- Preserve original financial request/key/date and fixed deadline.
- Never autonomously send for `PENDING` or `PROVEN_NOT_SENT`.
- Respect approved customer explicit-open retry/fence policy.
- Treat `503 billing_busy` from the Step 7 user-lock `55P03` path as local
  contention, not provider failure or completed no-send evidence. Retry local
  work/GET recovery without modifying send authority, original key/fence or
  `unknown_since + 2h`. Only the existing explicit authenticated advance and
  completed typed no-send rules can authorize their respective CREATE path.
- Do not apply preparation lifecycle restrictions to already reconciled terminal
  subscriptions.
- Add bounded customer inventory using the current under-100 row and 20
  relevant-candidate limits. Capped/unstable inventory is incomplete, not absence.
- Reuse canonical proof and conflict handling; no unknown adoption or primary
  selection.
- Document recovery decisions, deadlines, limitations and refusal cases.
- Add shared-entrypoint behavior tests.
- Exercise both products for one user/customer in the same billing account.
  The same tariff/service/period selection is valid across products only with
  separate accepted purchases, dedicated agreements and canonical subscriptions.
  Use local product/purchase/subscription identity for jobs and proof, never
  tariff ID alone. Exclude the other product from competing inventory only after
  its permanent owner/agreement/seller/original-effective-term proof succeeds.
  Recovery or conflict handling for one must not rebind, overwrite or consume
  the other's operation/work/observation. Preserve existing uniqueness rules.

**Invariants / Non-goals**

No worker POST, deadline extension, empty-list hold release, PII identity
authority or current-price reapproval.

**Verification**

Run `billing_background_recovery` PostgreSQL selection and affected Step 7
customer/UNKNOWN/no-send/same-tariff/contention tests. Cover zero/one/multiple,
delayed visibility, lost response/claim acknowledgement, escalation during
outage, stale fences, late objects, completed no-send beyond its deadline,
active send leases, foreign candidates and legitimate same-tariff products.
Include contention before a claim and during recovery/apply: `billing_busy`
must not create `PROVEN_NOT_SENT`, reset UNKNOWN/deadlines, release the hold or
trigger a background POST. Verify the eventual GET-only retry uses the original
operation and enrollment remains idempotent.

Using synthetic LBX responses, prove legitimate same-tariff inventory for both
products with distinct agreements/subscriptions; recover one original UNKNOWN
while the other's binding remains unchanged. Cover swapped/foreign agreement or
subscription IDs, incomplete other-product proof and ambiguous candidates: refuse
unsafe adoption/exclusion, retain affected review/UNKNOWN fences, and never bind
one product's object to the other. Inspect per-product work/projection/history
and preserve holds. Test both product roles without provider CREATE, payment,
allowances, grants or any use of 100/300 as subscription/quota authority.

Owner checkpoint: inspect existing test history and GET-only recovery traffic.
Do not manufacture a live billing failure.

**Expected completion**

After this step, the system can recover or escalate uncertain creates and
discover relevant conflicts without browser activity or duplicate CREATE,
including isolated recovery for two products that legitimately share a tariff
but have different permanent purchase/agreement/subscription bindings.

**AI execution prompt**

> Implement Step 3 of `docs/exec-plans/active/ANY-715-implementation-plan.md`. Read existing financial/customer recovery, claims/fences/escalation, inventory ownership queries, Steps 1–2 and Step 7 UNKNOWN/no-send/same-tariff/contention tests. Connect shared GET-only recovery to urgent scheduling and independent fixed-deadline work. Add bounded inventory and scoped conflict evidence. Preserve `PROVEN_NOT_SENT`, permanent financial identity and the distinct customer retry policy. `503 billing_busy` means local PostgreSQL contention, not provider failure or no-send proof; it must not authorize CREATE, reset an operation/deadline or release a hold. Update the operational recovery/inventory documentation and its checks.
>
> Reuse Step 2's two-product fixtures for `proposal_ai` and `brief_decoder`. Verify same-user/customer/account subscriptions may share one LBX tariff only with distinct accepted purchases, agreements and subscriptions. Keep jobs/recovery/projections scoped to their original products. Exclude another product from competing inventory only after current permanent ownership and original effective-term proof; refuse swapped/foreign/ambiguous or incomplete proof without cross-product adoption. Use synthetic LBX responses, preserve current Step 7/Step 1 contracts and add no paid-access/quantity logic or real provider objects.
>
> Follow the repository's root and applicable subtree AGENTS.md files, ARCHITECTURE.md, docs/engineering/CODING_CONVENTIONS.md, docs/engineering/AGENT_WORKFLOW.md, and docs/engineering/TESTING.md. Respect existing architectural layers, coding conventions, typing, error handling, transaction ownership, dependency direction and established project structure. Use equivalent authoritative instructions in other affected repositories.
>
> Implement only the specified step. Reuse existing components and preserve the agreed functional outcome and invariants. Do not broaden the scope or start subsequent steps.
>
> Run appropriate formatters, linters and focused automated tests. Fix failures caused by your changes and rerun affected checks. Run additional relevant validation when necessary; report unexecuted or blocked checks accurately.
>
> Run `billing_background_recovery` PostgreSQL coverage and affected Step 7 regressions. Assert no worker CREATE, unchanged financial escalation, safe customer leases, original candidate proof, bounded inventory and equivalent shared recovery behavior. Include local `billing_busy` before claim and during recovery/apply; prove safe retry retains original identity/fencing and cannot manufacture no-send evidence.
>
> Add focused two-product PostgreSQL/integration cases for valid same-tariff ownership, recovery of only one UNKNOWN, swapped/foreign IDs and incomplete/ambiguous candidates. Repeat with product roles reversed and assert no cross-product binding, job completion or observation/projection overwrite.
>
> If a material contradiction appears, investigate the relevant surrounding context and available evidence, then propose a resolution. Stop and ask only when an important decision cannot be made safely.
>
> Do not run mutating operations against real billing or other external production systems without explicit authorization.
>
> Do not stage, commit, push, switch branches, merge or rebase. Do not modify unrelated worktrees.
>
> Report the implemented behavior, changed files, verification results, remaining limitations and any required manual QA.

**Proposed commit**

`ANY-715 - Recover uncertain creates and discover inventory conflicts`

### Step 4 — Add authenticated webhook hints and deployment instructions

**Goal**

Accelerate shared reconciliation through durable authenticated notifications,
with repeatable test/production setup.

**Expected behavior**

An enabled authenticated event commits a redacted receipt and coalesced work
before acknowledgement. The worker reads LBX and invokes the same transition.
Disabled webhook mode remains fully functional through polling.

**Read before implementation**

- Webhook contract above and primary LBX configuration/event sources.
- Security durable-receipt/privacy requirements.
- HTTP request/error/named DTO conventions.
- Inbox/work models, Steps 1–3 shared paths and deployment/documentation tests.

**Implementation**

- Add narrow Integration authentication/parsing and Presentation endpoint.
- Implement disabled default, exact header-secret mode, bounded body and safe
  correlation.
- Atomically persist receipt and enqueue through Application.
- Reuse coalescing/generation and worker GET/apply.
- Track covered receipt processing without losing later arrivals.
- Add configuration/privacy/contract tests and generated artifacts.
- Write exact manual LBX setup: events, environment URLs, secret placement,
  verification and disablement. Check docs against actual route/events/settings.
- Keep real header/delivery compatibility as the separate enablement gate.

**Invariants / Non-goals**

No provider calls in receipt, raw-body persistence, anonymous hints,
webhook-derived facts, assumed provider retries or payment ledger.

**Verification**

Run `billing_webhook` fast/PostgreSQL tests and contract/privacy/deployment/docs
guards. Cover disabled/invalid credentials, malformed/oversized input,
unsupported events, unknown/cross-scope correlation, duplicate/reordered/lost
notifications, DB-before-commit failure, response loss, worker crash, hints during
claims and delayed REST visibility.

Owner checkpoint: execute the narrow real test-LBX gate when authorized.
Otherwise retain `DISABLED/POLLING-ONLY`. Do not mutate LBX configuration without
authorization.

**Expected completion**

After this step, the system can durably receive secure hints, and an operator can
repeat the documented setup on production after its own verification.

**AI execution prompt**

> Implement Step 4 of `docs/exec-plans/active/ANY-715-implementation-plan.md`. Read the webhook contract, current official LBX event/configuration documentation, Security receipt/privacy rules, HTTP DTO/error conventions, inbox/work storage and shared reconciliation/recovery. Build the default-disabled authenticated receiver and atomic redacted receipt/queue path. Use worker GETs and shared Application transitions. Document exact manual test/production setup, supported events, secrets configuration, gate and rollback; add code-to-documentation checks.
>
> Follow the repository's root and applicable subtree AGENTS.md files, ARCHITECTURE.md, docs/engineering/CODING_CONVENTIONS.md, docs/engineering/AGENT_WORKFLOW.md, and docs/engineering/TESTING.md. Respect existing architectural layers, coding conventions, typing, error handling, transaction ownership, dependency direction and established project structure. Use equivalent authoritative instructions in other affected repositories.
>
> Implement only the specified step. Reuse existing components and preserve the agreed functional outcome and invariants. Do not broaden the scope or start subsequent steps.
>
> Run appropriate formatters, linters and focused automated tests. Fix failures caused by your changes and rerun affected checks. Run additional relevant validation when necessary; report unexecuted or blocked checks accurately.
>
> Run `billing_webhook` fast/PostgreSQL selections and privacy, deployment, API-generation and documentation checks. Prove commit-before-ack, duplicate/order/crash safety and polling-only convergence. Do not invent actual LBX authentication transport or claim real delivery from simulated tests.
>
> If a material contradiction appears, investigate the relevant surrounding context and available evidence, then propose a resolution. Stop and ask only when an important decision cannot be made safely.
>
> Do not run mutating operations against real billing or other external production systems without explicit authorization.
>
> Do not stage, commit, push, switch branches, merge or rebase. Do not modify unrelated worktrees.
>
> Report the implemented behavior, changed files, verification results, remaining limitations and any required manual QA.

**Proposed commit**

`ANY-715 - Add durable webhook hints and deployment runbook`

### Step 5 — Deliver audited operations and lifecycle handoff

**Goal**

Make the complete lifecycle operable with narrowly proven operator resolutions,
current documentation and a durable Step 9 handoff.

**Expected behavior**

An operator can inspect evidence, trigger bounded shared recovery/reconciliation
and resolve a supported case only after fresh original-object proof. The running
stack recovers without browser/webhook activity; stuck work and resource limits
are visible. Terminal purchase holds and immutable history remain intact.

**Read before implementation**

- `apps/api/app/cli/billing_purchases.py`, existing customer diagnostic CLI and
  `composition/mapping_operator.py::resolve_operator_principal()`.
- `domains/purchases/financial.py` review/bind transitions,
  `domains/purchases/service.py` locks/holds and purchase query helpers.
- Shared transitions from Steps 1–4.
- Review/work/observation models, telemetry/Sentry privacy rules.
- New runbook and documentation-contract tests.

**Implementation**

Extend the existing privileged `billing-purchase` CLI, using its OS principal
and deployment access boundary; do not introduce roles or a new admin API. Keep
the existing customer diagnose command. Document these purchase actions:

- `inspect`: local facts, trust, work and reviews.
- `recover`: existing GET-only operation recovery.
- `reconcile`: bounded authoritative subscription recheck.
- `resolve-review`: only the supported audited cases below.

`inspect` reads local evidence without source I/O or mutation. `recover` keeps
the existing GET-only proof/binding behavior; deadline-only escalation can still
resolve through that existing path. `reconcile` uses the same bounded read/apply
as the worker. None bypasses a known-conflict review or changes immutable terms.

Use `resolve-review` only when ordinary recovery is deliberately blocked by an
open known-conflict case and one of these resolutions is now provable:

1. **Restore original facts:** the original canonical binding still belongs to
   this purchase and LBX now again proves its original owner, agreement/seller,
   accepted terms and supported policy. Persist fresh reconciled facts and
   resolve the corresponding corrected conflict; do not change the binding.
2. **Bind the original uncertain operation:** bounded complete discovery now
   finds exactly one original point-proven candidate, with the original saved
   operation/correlation/request and no competing binding. Apply the shared
   original bind transition with explicit audited resolution of its conflict.
   The operation must have possible-send history; `PENDING`/`PROVEN_NOT_SENT`
   cannot adopt a coincidental provider object.

Require user/purchase/case identity, expected current case and supporting
observation/operation fence, a nonempty reason and ticket/reference. The command
collects fresh proof through shared Application functions; operator-provided IDs
or assertions are not source evidence. Customer original-key restoration keeps
its existing separate policy, not a new financial identity override.

In the short apply transaction, use the existing user → purchase/hold → ordered
operation → subscription lock order and lock/recheck the target review. Reject
changed expected evidence/ownership/fence, unrelated open cases or a stale read.
Atomically record the permitted binding/fact update and case resolution with OS
principal, reason/reference, before/after identities, supporting observation and
versioned proof summary in the existing audit/review storage. Preserve original
evidence; an identical completed resolution is idempotent, and a different repeat
or concurrent stale resolution is refused. Enqueue required reconciliation using
the same transaction/queue contracts as other entrypoints.

Refuse incomplete/capped or ambiguous discovery, foreign or already-bound
objects, arbitrary rebind, mapping/commercial reacceptance, terminal revival,
unresolved unsafe CREATE effects, manual paid marking and quota edits. Do not
close a case merely because an operator supplies a reason or repeats a matching
GET; the explicitly supported proof and audited transition are required.

**Terminal hold release is deferred.** Remove `release-terminal` from this
ticket's required CLI: fresh ended state alone does not prove safe repurchase,
absence of late CREATE or compatibility with later primary/access transitions.
Keep the hold, original purchase, consent and permanent bindings. This does not
change Step 7's existing proven-unsent automatic release rule. A future scoped
decision may define additional release semantics; do not add a force-release
escape hatch now.

Expose local worker progress/backlog through the existing planned health and
`inspect` diagnostics rather than another administrative subsystem. Complete
bounded metrics/alerts and the short future expansion guidance. Local/entity IDs
are not metric labels. Add entrypoint-equivalence tests; no capacity benchmark.

Run the configured test-LBX read-only checkpoint on an existing intended Step 7
purchase when available. Require no new payment or provider fixture mutation.

**Invariants / Non-goals**

No second CLI business implementation, new operator permission, admin panel,
terminal hold release, manual access authority, retention deletion or speculative
distributed infrastructure.

**Verification**

Run `billing_recovery_cli` fast/PostgreSQL selection and shared-entrypoint tests.
Prove both permitted resolutions and their exact persisted effects, OS principal
failure, missing reason/reference, stale case/observation/fence, simultaneous
worker/operator apply, ambiguous/foreign candidates, idempotent replay and atomic
audit rollback on failure. Verify normal recovery cannot close a known conflict,
no terminal release command exists and holds/history/create fences survive ended,
empty-discovery and refusal cases. Confirm worker/CLI share the same proof and
transitions while retaining distinct authorization.

Use the small worker/fault fixtures to verify bounded backlog, urgent/local
progress and truthful health during source failure; no artificial load target.
Owner checkpoint: review documented CLI effects/refusals, actual read-only
test-LBX result, future expansion guidance and webhook status. Run final
canonical implementation verification below.

**Expected completion**

After this step, the system can diagnose Step 8, perform only proven audited
resolutions and provide Step 9 with verified lifecycle/recovery/deadline facts,
current commands and an explicit future expansion path.

**AI execution prompt**

> Implement Step 5 of `docs/exec-plans/active/ANY-715-implementation-plan.md`. Read the existing billing-purchase/customer CLI, OS operator principal composition, purchase financial review/bind/hold locks, Steps 1–4 shared transitions, billing evidence/work/review models, telemetry privacy rules and the operational runbook. Extend the existing CLI with inspect/recover/reconcile and only the two specified audited resolve-review cases: restore original canonical facts or bind the uniquely proven original possible-send operation. Require fresh complete proof, expected case/observation/fence and reason/reference; atomically recheck, apply and audit. Preserve existing authorization and reuse the same Application functions as worker/HTTP. Do not implement terminal hold release, arbitrary identity override, new operator rights or a capacity benchmark. Finish health/metrics, documentation checks, future expansion guidance and the Step 9 handoff.
>
> Follow the repository's root and applicable subtree AGENTS.md files, ARCHITECTURE.md, docs/engineering/CODING_CONVENTIONS.md, docs/engineering/AGENT_WORKFLOW.md, and docs/engineering/TESTING.md. Respect existing architectural layers, coding conventions, typing, error handling, transaction ownership, dependency direction and established project structure. Use equivalent authoritative instructions in other affected repositories.
>
> Implement only the specified step. Reuse existing components and preserve the agreed functional outcome and invariants. Do not broaden the scope or start subsequent steps.
>
> Run appropriate formatters, linters and focused automated tests. Fix failures caused by your changes and rerun affected checks. Run additional relevant validation when necessary; report unexecuted or blocked checks accurately.
>
> Run `billing_recovery_cli` fast/PostgreSQL coverage, shared-entrypoint scenarios and final canonical implementation checks. Verify allowed resolutions, refusals, stale/concurrent proof, idempotency and atomic audit; prove holds/history/UNKNOWN fences remain protected and no release-terminal command is added. Exercise the complete polling lifecycle and small cancellation/outage/restart scenarios. Use only authorized read-only test-LBX integration, with no real payment or provider mutation. Classify simulated versus actual integration evidence and webhook status separately. Ensure CLI/settings/events documentation matches implementation.
>
> If a material contradiction appears, investigate the relevant surrounding context and available evidence, then propose a resolution. Stop and ask only when an important decision cannot be made safely.
>
> Do not run mutating operations against real billing or other external production systems without explicit authorization.
>
> Do not stage, commit, push, switch branches, merge or rebase. Do not modify unrelated worktrees.
>
> Report the implemented behavior, changed files, verification results, remaining limitations and any required manual QA.

**Proposed commit**

`ANY-715 - Deliver audited operations and lifecycle handoff`

## 6. Final Verification & Review

### Complete behavior scenario

Run real Portal HTTP/Application and disposable PostgreSQL with simulated LBX:

1. Prepare/link a purchase and remove browser activity; automatically enroll it.
2. Backfill several small batches of pre-existing subscriptions, restart after a
   committed batch and verify no missing or duplicate monitoring work.
3. Record waiting, then active/unblocked, coherent next-period calendar facts,
   financial/admin block and ended on the same original owned subscription.
4. Distinguish provider-confirmed underfunding block from an incomplete renewal
   or a balance-based guess; preserve accepted effective terms and calendar facts.
5. Verify finite trust, negative supersession and terminal revival protection.
6. Lose a CREATE reply, restart and recover through GET-only proof; exercise
   zero/multiple candidates and exact two-hour escalation.
7. Inject local `billing_busy`; preserve operation identity/UNKNOWN fencing and
   never send another CREATE or manufacture no-send evidence.
8. Drop/duplicate/reorder webhook hints; repeat with webhook disabled.
9. Expire trust during outage while unrelated scopes remain independent; restore
   LBX and require fresh complete proof before new positive trust.
10. Keep A's GET running after its lease expires; let B reclaim/apply, then reject
    A's late result/completion while retaining its occupied HTTP slot.
11. Exercise timeout/cancellation/restart and generation-safe hints with two
    handlers; verify bounded requests and provider-free deadline progress.
12. Perform both supported CLI resolutions and the specified refusals; verify
    atomic audit and unchanged holds/history, including terminal subscriptions.
13. Smoke-test embedded startup and small-source-saturation/backlog scenarios
    without lost work, unbounded claims or trust extension.

Assert no Step 8 primary, allowance, paid-state revision or invalidation-outbox
writes.

### Two-product isolation acceptance

Use the adapted Mock Kernel technical manifest plus synthetic LBX GET responses
and disposable PostgreSQL fixtures for `proposal_ai` and `brief_decoder`, owned
by the same user/customer/account. Give each a separate accepted purchase,
agreement and subscription; include the supported shared-tariff case. Repeat
these scenarios with product roles reversed:

- Activate one while the other remains waiting; only the intended product's
  lifecycle, supporting observation and trust change.
- Financially/administratively block one while the other's independently
  verified subscription stays active and within its own trust deadline.
- Return a subscription-specific timeout, 404 or incomplete/mismatching response
  for one; preserve the other's facts, bindings, jobs and independent trust.
- Expire one source-trust deadline while the other still has valid fresh proof;
  provider-free expiry affects only the intended product. Recover the first
  through complete synthetic proof without modifying the other.
- Restart/replay hints and recover one UNKNOWN without collapsing the two job
  keys or completing/rebinding the other product's operation.

Compare per-product persisted lifecycle/completeness, supporting observations,
trust deadlines, work and original ownership before/after each targeted action;
allow the other product to change only through its own legitimately executed
work. Shared customer identity/account failures or a provider-wide outage may
legitimately affect both: distinguish these from product-specific failures and
never extend either trust deadline to mask the outage.

Mock Kernel proves only technical product/metric availability; it does not
activate/block subscriptions. All multi-subscription transitions here are
SIMULATED LBX evidence, with no real paid object/payment creation. The 100/300
purchase examples remain Step 9 concerns; assert no allowance, grant, quota
calculation, access revision or Kernel enforcement is introduced.

### Evidence classification

Record separately:

- `SIMULATED`: provider transitions, renewal, faults, small concurrency/backlog
  and restart tests, including two-product isolation with synthetic LBX states.
- `CONFIGURED_TEST_LBX_READ_VERIFIED`: actual bounded read-only integration.
- `REAL WEBHOOK ENABLEMENT VERIFIED` or `DISABLED/POLLING-ONLY`.
- Configured per-process resource limits and unverified provider quotas; no
  large-load capability or horizontally scaled deployment is claimed.
- Step 9/10/11 incompleteness.

Unavailable integration does not block development, but leaves that acceptance
checkpoint outstanding. Never turn an unexecuted or simulated check into live
PASS. Preserve B8 pricing, B10 calendar/UTC deferral, B11 natural-renewal limits,
B14 delivery/authentication gaps and B15 evidence levels.

### Automated checks

After focused tests:

```bash
npm run generate:check
npm run architecture:check
npm run docs:check
npm run check:fast
make test_db_up
npm run test:api:postgres
npm run check
```

These commands verify the completed application implementation, not this
documentation-only plan revision. There is no separate capacity benchmark or
large subscription fixture requirement. Run affected frontend/build/browser
checks when required. Report skipped/blocked checks accurately.

Recheck Step 7 shared writers, linked-read recovery, customer leases, isolated
source budgets and no-send/UNKNOWN/contention behavior. Reproduce or classify the earlier stalled
test in the implementation environment.

### Documentation and operational review

Verify that a reviewer can follow the runbook to start/restart/inspect the worker;
configure webhook on test and repeat on production; execute every CLI command;
diagnose backlog/source failure/trust expiry; identify per-process limits and
cleanup-pending requests; understand enrollment progress and permitted/refused
operator effects; and distinguish implemented embedded operation from the short
future expansion path. Do not document unimplemented commands as available.

Check runbook references against parsers, Settings, routes and event constants.
Review semantic accuracy and secret handling separately. Record final SHA,
migrations, commands/results and remaining gates. Obtain independent semantic,
security and reliability review and human merge approval.

## 7. Handoff to Next Step

Step 9 receives:

- Versioned observations and complete/mismatch/incomplete matrix.
- Canonical ownership, original accepted terms and prepaid-policy proof.
- Source observation identities, trust deadlines, incomplete-read behavior and
  deterministic expiry evidence.
- Original calendar facts without invented UTC or allowance identity.
- Recovery/fencing/coalescing APIs and fixed financial UNKNOWN semantics.
- Scoped conflicts, exact supported/refused audited operator resolutions and the
  deliberate deferral of terminal hold release.
- Reusable runner with embedded startup, bounded per-process resources,
  cancellation/cleanup ownership and a documented future expansion path.
- Current CLI/webhook/monitoring runbook and documentation freshness checks.
- Final migrations, tested SHAs and classified evidence.

Step 9 owns primary selection, grants, allowances, effective-access revisions and
atomic outbox production. It must reuse the worker and attach its effective
access-reducing deadlines to the established scheduling path.

Step 10 owns Kernel wire/invalidation delivery and coupled calendar-to-wire
design. Step 11 owns full real paid-access/natural-renewal and launch acceptance.

No observation, webhook, Widget result, successful CREATE or operator action
independently authorizes paid access.
