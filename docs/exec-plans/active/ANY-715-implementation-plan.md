# ANY-715 — Background Work, Webhooks, Reconciliation & Recovery

Status: proposed; application implementation not started  
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
9. Support multiple consumers safely and provide a tested path from one
   embedded worker to independently deployed workers.
10. Supply Step 9 with trustworthy provider-neutral facts and deadlines.

The initial deployment remains one API replica with an embedded worker.
Capacity is bounded and measured. Supporting 10,000 subscriptions is a
capacity-characterization scenario, not an unverified launch or LBX-throughput
promise.

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

The owner authorized a documentation-only planning delivery on `ANY-715`, based
on `ANY-709`. Commit only this plan as
`ANY-715 - Add background billing implementation plan` and open a draft PR
targeting `ANY-709`. Include the Linear URL, PR #150, source SHAs and an explicit
statement that the branch inherits Step 7. Rebase/retarget to main after Step 7
merges through a separately authorized Git operation. Per-step execution
prompts below do not authorize Git mutations.

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
- Source pools and process-local admission do not establish a multi-process
  capacity policy.

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

For a known canonical subscription, perform two bounded rounds of:

1. `get_user()` — paired provider customer ID and immutable Portal customer key.
2. `get_agreement()` — original canonical agreement, customer, seller and
   permanent agreement correlation.
3. `get_subscription()` — identity, effective services/quantity/prices/total/
   currency, period, lifecycle/blocking and original calendar values.
4. `get_tariff()` — relevant supported prepaid/blocking policy.

Compare relevant normalized fields between rounds. Changing or incomplete proof
does not refresh positive trust. This is defensive rereading, not a provider
atomic-snapshot guarantee. All reads share one absolute operation budget. Reuse
existing decoding, `Decimal` handling and GET retry policy.

Compare against the original accepted purchase and original link revision:

- Current catalog price does not reprice an old subscription.
- Current publication, Kernel availability and sale visibility do not gate
  historical reconciliation.
- Tariff policy reads do not replace effective subscription prices.
- Sale-only archive/visibility changes do not invalidate an existing
  subscription.
- Unsupported or missing applicable policy prevents positive trust refresh.

Keep lifecycle normalization separate from preparation restrictions. Reuse
narrow commercial comparison logic where appropriate.

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
| Financial block `2/1` or administrative block `2/3` | Ordinary negative facts with distinct reason | Supersede prior positive usability immediately |
| Ended `3/0` | Terminal ended/blocked fact | No automatic revival or silent hold release |
| Previously ended canonical ID becomes nonterminal | Terminal-revival conflict | Remain ineligible; controlled review |
| Catalog 10→20; original effective subscription remains accepted 10 | Original terms still match | No false conflict or repricing |
| Effective subscription 10→15, or changed service/quantity/currency | Commercial mismatch when sufficiently proven | Ineligible conflict and review |
| Missing fields, unstable reads, timeout, 404 or exhausted budget | Incomplete/unknown observation | No trust extension; prior good facts only until their existing deadline |
| Foreign customer/agreement or canonical identity drift | Identity conflict | No silent rebind; affected positive usability removed |
| UNKNOWN create: zero / one / multiple candidates | Uncertain / original point-proven binding / ambiguity | GET-only recovery; unchanged fixed deadline |
| `PROVEN_NOT_SENT` | Completed typed no-send evidence | No autonomous POST or overdue UNKNOWN conversion |
| Trust deadline due | Local expiry evidence | Provider-free processing; Step 9 owns later access revision/outbox |

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

Local enrollment sweeps run at startup and every 60 seconds, using keyset batches
of at most 100. They find previously linked subscriptions and missing monitoring,
recovery/deadline work without provider I/O.

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

### Capacity controls and scaling strategy

Separate reusable job execution from FastAPI startup. The runner must not depend
on HTTP request objects or own another business state machine. Provide a minimal
standalone CLI entrypoint using the same runner:

```bash
PYTHONPATH=apps/api .venv/bin/python -m app.cli.billing_worker run
```

Initial production deployment remains embedded. Standalone deployment is an
operational option using the same project/image/database, not a new service
implementation.

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

Provider-operation caps apply across worker consumers for one configured account,
not independently per process. Implement the small PostgreSQL claim-admission
critical section using a stable transaction advisory key and existing active
work leases. Release that transaction before HTTP. Reject inconsistent live
consumer budget configurations. Keep the key stable across processes; do not use
Python's process-randomized hash.

These are concurrent-operation limits, not a claimed provider requests-per-second
quota. Record actual HTTP request rate, including retries/authentication. If LBX
imposes a hard request-rate quota, shared per-request enforcement is a required
gate before raising deployment capacity; per-process limits cannot be presented
as a global quota.

The documented expansion sequence is:

1. **Initial:** one embedded worker with conservative configured limits.
2. **Increase capacity:** measure latency/rate/backlog and adjust approved
   aggregate limits within the tested LBX/PostgreSQL envelope.
3. **Separate resources:** disable embedded workers in API processes and run the
   same runner in a dedicated process/container.
4. **Add consumers:** launch more copies sharing PostgreSQL claims, leases,
   fences and aggregate admission limits.
5. **Further storage/provider work:** only when measurements identify that
   bottleneck; no speculative MQ, sharding, catalog mirror or autoscaling
   framework.

Increasing replica count alone must not multiply allowed source load. Document
switch/rollback: stop claiming, drain bounded work, disable the old startup mode,
start the new mode and verify progress. PostgreSQL work survives the transition.

### Capacity characterization

At 10,000 ordinary subscriptions:

- Required completed checks per second for a 15-minute cycle: approximately
  11.11.
- The eight-GET baseline requires approximately 88.89 business GETs per second
  before authentication, retries, inventory and urgent traffic.
- One observation per normal check produces approximately 960,000 observations
  per day.

These are estimates for the proposed read shape, not measured LBX capability.
Determine supported capacity from measured check duration, HTTP exchanges and
database cost. Do not choose production consumer count from subscription count
alone.

Add a reproducible opt-in capacity test using disposable PostgreSQL and simulated
LBX: 10,000 seeded owned subscriptions/due work, one/multiple consumers, urgent
and normal work together, slow/unavailable source, restart/recovery bursts,
duplicate webhook hints, ordinary API traffic and local deadlines.

Measure throughput, queue age, cadence lag, actual active concurrency, provider
request rate, database contention and observation/index growth. Assert bounded
memory/work claims, no lost jobs, no stale overwrite and reserved-work progress.

Distinguish measured runtime from latency-based projections. This does not prove
a 10,000-subscription live-provider SLA. Overload is an expected tested condition:
work stays durable, lag becomes visible and trust is not extended to conceal it.
Keep a bounded execution budget; report unfinished draining as overload rather
than PASS. Document the exact opt-in test command and configuration.

Record storage growth and a capacity-review threshold in the runbook. Do not
delete immutable history or implement an unapproved retention/partition policy.

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

1. Startup, embedded/standalone modes, shutdown and restart.
2. Approved cadence, trust, UNKNOWN and retry semantics.
3. Every resource setting, unit, default and per-process/aggregate scope.
4. Exact manual webhook setup for test and production: endpoint, event list,
   secret location, verification and disablement.
5. Every supported CLI command, arguments, prerequisites, effects, refusal cases
   and examples.
6. Monitoring, backlog diagnosis, outage response and safe recovery.
7. Capacity evidence, supported envelope and staged expansion procedure.
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
| Verified lifecycle/commercial facts | 1, 2 | Application/PostgreSQL fixtures and configured read-only checkpoint |
| Historical terms and conflict distinction | 1, 3 | Catalog-change versus effective-change tests |
| Shared HTTP/worker/CLI semantics | 1–5 | Shared use cases and equivalent behavior through entrypoints |
| Enrollment, restart and durable polling | 2 | Newly linked/backfilled subscriptions run without browser traffic |
| Claims, fencing and lost-hint safety | 2 | PostgreSQL concurrency/crash tests |
| Aggregate capacity and deployment modes | 2, 5 | Competing runners, isolated lanes, standalone smoke and runbook |
| UNKNOWN and immutable two-hour deadline | 3 | Zero/one/multiple, no-send, crash and lost-reply tests |
| Inventory and same-tariff ownership | 3 | Proven other-product exclusion and bounded incomplete inventory |
| Trust expiry and unaffected scopes | 1, 2 | Controlled-clock outage and expiry-race tests |
| Optional durable webhook | 4 | Synthetic HTTP/PostgreSQL tests; separate real gate |
| Audited operator controls | 5 | Authorization, stale-proof, refusal and audit tests |
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
missing/extra service, quantity/currency/owner mismatch, unstable reads, terminal
revival, known review and concurrent preparation/reconciliation.

Owner checkpoint: inspect representative sanitized normalized outputs.

**Expected completion**

After this step, the system can reconcile an owned subscription through shared
Application logic and preserve its facts across subsequent preparation reads.

**AI execution prompt**

> Implement Step 1 of `docs/exec-plans/active/ANY-715-implementation-plan.md`. Read its decision matrix, LBX financial/client/current-offer modules, purchase contracts/service/financial transitions, billing models and Step 7 effective-term/recheck/review tests. Build the shared bounded authoritative read/normalization/apply path. Preserve original accepted history, negative-state semantics, finite trust and known-review rules. Protect reconciled facts from preparation-only writes and preserve the `d28eddd` linked-recheck correction. Create the relevant operational runbook sections and documentation checks.
>
> Follow the repository's root and applicable subtree AGENTS.md files, ARCHITECTURE.md, docs/engineering/CODING_CONVENTIONS.md, docs/engineering/AGENT_WORKFLOW.md, and docs/engineering/TESTING.md. Respect existing architectural layers, coding conventions, typing, error handling, transaction ownership, dependency direction and established project structure. Use equivalent authoritative instructions in other affected repositories.
>
> Implement only the specified step. Reuse existing components and preserve the agreed functional outcome and invariants. Do not broaden the scope or start subsequent steps.
>
> Run appropriate formatters, linters and focused automated tests. Fix failures caused by your changes and rerun affected checks. Run additional relevant validation when necessary; report unexecuted or blocked checks accurately.
>
> Run `billing_subscription_reconciliation` fast/PostgreSQL selections, affected Step 7 regressions, architecture and documentation checks using the plan's recipe. Prove historical-price matching, incomplete-read trust limits, ordinary negative states and writer concurrency.
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

### Step 2 — Run durable polling with bounded scalable execution

**Goal**

Make monitoring automatic and restart-safe while establishing the reusable
runner and capacity controls.

**Expected behavior**

Linking atomically enrolls subscriptions. Local sweeps backfill missing work.
The runner claims executable capacity, reads LBX outside transactions, applies
current fenced results and reschedules safely. Multiple consumers share the
queue and aggregate limits. Local deadlines continue during slow provider work.

**Read before implementation**

- Step 1 Application contracts/transitions.
- `apps/api/app/main.py`, `composition/sources.py`, work/subscription models.
- `infrastructure/preflight.py`, customer leases and query/persistence rules.
- `http/health.py`, observability and Sentry boundaries.
- `apps/api/alembic/versions/20261027_0003_normal_billing.py`.
- Settings, Compose variants, harness propagation and deployment tests.

**Implementation**

- Implement the transport-independent runner and lifespan supervision.
- Add queue mechanics, aggregate admission, generation-safe coalescing and
  subscription fencing.
- Add a forward migration for work generation, attempt-start timestamp and
  coalescing constraints. Do not rewrite predecessor migrations.
- Enroll links atomically and backfill via bounded sweeps.
- Implement approved cadence, due-time spreading, backoff and local expiry.
- Provide the standalone worker entrypoint using the same runner; keep embedded
  as the initial deployment.
- Add named `/api/health/billing` output and worker-aware readiness. Liveness
  remains DB-independent; LBX outage alone does not make the identity API unready.
- Propagate settings and disable unattended source work in ordinary tests.
- Document modes/settings, shutdown/restart, capacity and expansion immediately.
- Add settings/commands documentation tests and multi-consumer coverage.

**Invariants / Non-goals**

No network under locks, in-memory correctness queue, generic scheduler, new
billing service, speculative MQ, paid-state writer or automatic scaling policy.

**Verification**

Run `billing_worker` fast/PostgreSQL selections, migration, health, composition
and deployment tests. Prove restart/backfill, coalescing during execution,
competing consumers, stale apply, lease expiry, DB/crash boundaries, customer-send
lease exclusion, aggregate caps, mixed-budget refusal, normal/urgent fairness,
deadline progress under saturation and expiry-versus-refresh races.

Smoke-test embedded and standalone startup with injected/local simulated sources.
Run no production worker. Owner checkpoint: inspect startup, health, persisted
work and the documented mode-switch procedure.

**Expected completion**

After this step, the system can poll automatically, recover queued work after
restart and run the same implementation in embedded or standalone form with
bounded shared capacity.

**AI execution prompt**

> Implement Step 2 of `docs/exec-plans/active/ANY-715-implementation-plan.md`. Read Step 1, API lifespan/source composition, work/subscription models, preflight/customer leases, health/telemetry, migration `20261027_0003`, Settings and deployment/harness tests. Build the shared runner, atomic enrollment/backfill, PostgreSQL claims/fences, generation-safe coalescing, approved scheduling and local expiry. Implement bounded aggregate operation admission and isolated resources. Add the standalone entrypoint using the same runner while preserving embedded startup as the default. Update the runbook and settings/CLI documentation checks in this step.
>
> Follow the repository's root and applicable subtree AGENTS.md files, ARCHITECTURE.md, docs/engineering/CODING_CONVENTIONS.md, docs/engineering/AGENT_WORKFLOW.md, and docs/engineering/TESTING.md. Respect existing architectural layers, coding conventions, typing, error handling, transaction ownership, dependency direction and established project structure. Use equivalent authoritative instructions in other affected repositories.
>
> Implement only the specified step. Reuse existing components and preserve the agreed functional outcome and invariants. Do not broaden the scope or start subsequent steps.
>
> Run appropriate formatters, linters and focused automated tests. Fix failures caused by your changes and rerun affected checks. Run additional relevant validation when necessary; report unexecuted or blocked checks accurately.
>
> Run `billing_worker` fast/PostgreSQL selections and affected migration, health, deployment, composition and documentation tests. Prove multiple-consumer correctness, aggregate caps, reserved deadline/urgent progress, restart and lost-hint safety. Generate changed model/OpenAPI artifacts through repository tooling.
>
> If a material contradiction appears, investigate the relevant surrounding context and available evidence, then propose a resolution. Stop and ask only when an important decision cannot be made safely.
>
> Do not run mutating operations against real billing or other external production systems without explicit authorization.
>
> Do not stage, commit, push, switch branches, merge or rebase. Do not modify unrelated worktrees.
>
> Report the implemented behavior, changed files, verification results, remaining limitations and any required manual QA.

**Proposed commit**

`ANY-715 - Run durable polling with scalable worker execution`

### Step 3 — Recover uncertain creates and discover conflicts

**Goal**

Automatically recover uncertain operations and identify customer inventory
conflicts without duplicate external commands.

**Expected behavior**

Urgent GET recovery runs independently of fixed deadline work. One original
point-proven candidate may bind; zero remains uncertain; ambiguity enters review.
Recovered subscriptions enroll in reconciliation. Inventory recognizes another
product only through permanent local ownership and original accepted proof.

**Read before implementation**

- `recover_financial()` and financial claim/bind/pending/escalation.
- `recover_customer()`, customer point proof, send leases and escalation.
- Purchase/customer queries and other-product inventory proof.
- Steps 1–2 runner/shared transitions.
- Step 7 UNKNOWN/no-send/lost-ack/same-tariff/contention tests.

**Implementation**

- Connect existing GET-only recovery to worker-owned resources/budgets.
- Separate urgent recovery from `external_create_deadline`.
- Preserve original financial request/key/date and fixed deadline.
- Never autonomously send for `PENDING` or `PROVEN_NOT_SENT`.
- Respect approved customer explicit-open retry/fence policy.
- Do not apply preparation lifecycle restrictions to already reconciled terminal
  subscriptions.
- Add bounded customer inventory using the current under-100 row and 20
  relevant-candidate limits. Capped/unstable inventory is incomplete, not absence.
- Reuse canonical proof and conflict handling; no unknown adoption or primary
  selection.
- Document recovery decisions, deadlines, limitations and refusal cases.
- Add shared-entrypoint behavior tests.

**Invariants / Non-goals**

No worker POST, deadline extension, empty-list hold release, PII identity
authority or current-price reapproval.

**Verification**

Run `billing_background_recovery` PostgreSQL selection and affected Step 7
customer/UNKNOWN/no-send/same-tariff/contention tests. Cover zero/one/multiple,
delayed visibility, lost response/claim acknowledgement, escalation during
outage, stale fences, late objects, completed no-send beyond its deadline,
active send leases, foreign candidates and legitimate same-tariff products.

Owner checkpoint: inspect existing test history and GET-only recovery traffic.
Do not manufacture a live billing failure.

**Expected completion**

After this step, the system can recover or escalate uncertain creates and
discover relevant conflicts without browser activity or duplicate CREATE.

**AI execution prompt**

> Implement Step 3 of `docs/exec-plans/active/ANY-715-implementation-plan.md`. Read existing financial/customer recovery, claims/fences/escalation, inventory ownership queries, Steps 1–2 and Step 7 UNKNOWN/no-send/same-tariff tests. Connect shared GET-only recovery to urgent scheduling and independent fixed-deadline work. Add bounded inventory and scoped conflict evidence. Preserve `PROVEN_NOT_SENT`, permanent financial identity and the distinct customer retry policy. Update the operational recovery/inventory documentation and its checks.
>
> Follow the repository's root and applicable subtree AGENTS.md files, ARCHITECTURE.md, docs/engineering/CODING_CONVENTIONS.md, docs/engineering/AGENT_WORKFLOW.md, and docs/engineering/TESTING.md. Respect existing architectural layers, coding conventions, typing, error handling, transaction ownership, dependency direction and established project structure. Use equivalent authoritative instructions in other affected repositories.
>
> Implement only the specified step. Reuse existing components and preserve the agreed functional outcome and invariants. Do not broaden the scope or start subsequent steps.
>
> Run appropriate formatters, linters and focused automated tests. Fix failures caused by your changes and rerun affected checks. Run additional relevant validation when necessary; report unexecuted or blocked checks accurately.
>
> Run `billing_background_recovery` PostgreSQL coverage and affected Step 7 regressions. Assert no worker CREATE, unchanged financial escalation, safe customer leases, original candidate proof, bounded inventory and equivalent shared recovery behavior.
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

### Step 5 — Deliver audited operations, capacity evidence and final acceptance

**Goal**

Make the complete lifecycle operable and establish measured expansion guidance
and a durable Step 9 handoff.

**Expected behavior**

An operator can inspect evidence, trigger bounded shared recovery/reconciliation
and perform a supported audited resolution. The running stack recovers without
browser/webhook activity, and capacity limits are visible rather than concealed.

**Read before implementation**

- Existing purchase/customer CLI and operator principal resolution.
- Shared transitions from Steps 1–4.
- Review/work/observation models, telemetry/Sentry privacy rules.
- New runbook and documentation-contract tests.

**Implementation**

Extend existing CLI patterns with documented actions:

- `inspect`: local facts, trust, work and reviews.
- `recover`: existing GET-only operation recovery.
- `reconcile`: bounded authoritative subscription recheck.
- `resolve-review`: narrowly supported proof-based resolution.
- `release-terminal`: explicit audited terminal purchase-hold release.

Use real OS principal resolution. Require stable reason/ticket reference and
expected current observation/case where applicable. Reuse original proof and
Application transactions; authorization is not an alternative business path.

Allow only original uniquely proven binding and supported restoration of original
facts. Terminal release requires fresh canonical ended proof, no unresolved
create effect and no downstream paid-primary transition requiring Step 9.
Remove only the hold and record an idempotent audit; preserve immutable purchase
and permanent bindings. Do not label an ended subscription as no external effect.

Refuse UNKNOWN release from empty discovery, arbitrary rebind, terminal revival,
commercial reacceptance, paid marking and quota edits. Add worker `status`
diagnostics from persisted progress/backlog; fleet progress does not prove every
process is healthy.

Complete bounded metrics/alerts and expansion guidance. Local/entity IDs are not
metric labels. Add opt-in `billing_capacity` characterization and
entrypoint-equivalence tests.

Run the configured test-LBX read-only checkpoint on an existing intended Step 7
purchase when available. Require no new payment or provider fixture mutation.

**Invariants / Non-goals**

No second CLI business implementation, admin panel, manual access authority,
retention deletion or speculative distributed infrastructure.

**Verification**

Run `billing_recovery_cli` fast/PostgreSQL selection, shared-entrypoint tests and
the opt-in capacity suite. Verify authorization, stale proof, concurrency,
release, audit and refusals. Measure bounded backlog handling, aggregate caps,
reserved work, API responsiveness and storage growth for 10,000 subscriptions.

Owner checkpoint: review commands, actual test-LBX result, capacity findings,
mode-switch procedure and webhook status. Run final canonical verification below.

**Expected completion**

After this step, the system can operate and diagnose Step 8 with current
documentation, measured limits and a practical expansion procedure.

**AI execution prompt**

> Implement Step 5 of `docs/exec-plans/active/ANY-715-implementation-plan.md`. Read existing CLI/operator composition, Steps 1–4 shared transitions, billing evidence/work/review models, telemetry privacy rules and the operational runbook. Add only the specified inspection, recheck, proof-based resolution and terminal-release controls. Reuse the same Application functions as HTTP and worker. Finish status/metrics, documentation-contract checks, reproducible capacity characterization and the Step 9 handoff.
>
> Follow the repository's root and applicable subtree AGENTS.md files, ARCHITECTURE.md, docs/engineering/CODING_CONVENTIONS.md, docs/engineering/AGENT_WORKFLOW.md, and docs/engineering/TESTING.md. Respect existing architectural layers, coding conventions, typing, error handling, transaction ownership, dependency direction and established project structure. Use equivalent authoritative instructions in other affected repositories.
>
> Implement only the specified step. Reuse existing components and preserve the agreed functional outcome and invariants. Do not broaden the scope or start subsequent steps.
>
> Run appropriate formatters, linters and focused automated tests. Fix failures caused by your changes and rerun affected checks. Run additional relevant validation when necessary; report unexecuted or blocked checks accurately.
>
> Run `billing_recovery_cli` fast/PostgreSQL coverage, shared-entrypoint scenarios, opt-in `billing_capacity` characterization and final canonical checks. Verify the running polling lifecycle and only authorized read-only test-LBX integration. Record measured versus projected capacity, simulated faults and actual webhook status separately. Ensure CLI/settings/events documentation matches implementation.
>
> If a material contradiction appears, investigate the relevant surrounding context and available evidence, then propose a resolution. Stop and ask only when an important decision cannot be made safely.
>
> Do not run mutating operations against real billing or other external production systems without explicit authorization.
>
> Do not stage, commit, push, switch branches, merge or rebase. Do not modify unrelated worktrees.
>
> Report the implemented behavior, changed files, verification results, remaining limitations and any required manual QA.

**Proposed commit**

`ANY-715 - Deliver audited operations and capacity handoff`

## 6. Final Verification & Review

### Complete behavior scenario

Run real Portal HTTP/Application and disposable PostgreSQL with simulated LBX:

1. Prepare/link a purchase and remove browser activity.
2. Observe enrollment and waiting normalization.
3. Progress to active/unblocked, financial/admin block and ended.
4. Verify finite trust, negative supersession and terminal revival protection.
5. Lose a CREATE reply, restart and recover through GET-only proof.
6. Exercise zero/multiple candidates and exact two-hour escalation.
7. Drop/duplicate/reorder webhook hints; repeat with webhook disabled.
8. Expire trust during outage while unrelated scopes remain independent.
9. Let a stale consumer finish after a newer observation; reject its apply.
10. Perform supported and refused CLI resolutions.
11. Switch embedded/standalone runners and run multiple consumers.
12. Exercise overload without lost work, unbounded claims or trust extension.

Assert no Step 8 primary, allowance, paid-state revision or invalidation-outbox
writes.

### Evidence classification

Record separately:

- `SIMULATED`: provider transitions, faults, renewal and capacity tests.
- `CONFIGURED_TEST_LBX_READ_VERIFIED`: actual bounded read-only integration.
- `REAL WEBHOOK ENABLEMENT VERIFIED` or `DISABLED/POLLING-ONLY`.
- Measured versus extrapolated capacity and unverified LBX limits.
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

Run the documented opt-in capacity command separately and record environment,
configuration, duration and result. Do not hide it among skipped canonical tests.
Run affected frontend/build/browser checks when required. Report skipped/blocked
checks accurately.

Recheck Step 7 shared writers, linked-read recovery, customer leases, source
capacity and no-send/UNKNOWN behavior. Reproduce or classify the earlier stalled
test in the implementation environment.

### Documentation and operational review

Verify that a reviewer can follow the runbook to start/restart/inspect the worker;
configure webhook on test and repeat on production; execute every CLI command;
diagnose backlog/source failure/trust expiry; identify the tested capacity
envelope; expand using documented gates; and distinguish current capability
from future operational work.

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
- Scoped conflicts, review gates and audited operator controls.
- Reusable runner, startup modes, aggregate capacity controls and measured
  expansion guidance.
- Current CLI/webhook/monitoring runbook and documentation freshness checks.
- Final migrations, tested SHAs and classified evidence.

Step 9 owns primary selection, grants, allowances, effective-access revisions and
atomic outbox production. It must reuse the worker and attach its effective
access-reducing deadlines to the established scheduling path.

Step 10 owns Kernel wire/invalidation delivery and coupled calendar-to-wire
design. Step 11 owns full real paid-access/natural-renewal and launch acceptance.

No observation, webhook, Widget result, successful CREATE or operator action
independently authorizes paid access.
