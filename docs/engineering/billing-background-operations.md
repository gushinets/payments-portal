# Background billing operations

Configuration, scheduling, polling-only operation and operator controls for the embedded
billing worker. For connection setup, purchases and Widget operation, use the
[billing runbook](ANY-709-billing-runbook.md). Architectural authority is
[ADR 0005](../architecture/decisions/0005-external-billing-boundary.md) and its
accepted specifications and dated decisions.

## Source authority and trust

LBX owns subscription activation and financial/administrative blocking. Portal
verifies the original customer, agreement/seller, accepted effective terms and
supported prepaid policy. Reconciliation uses authenticated point reads of
`/users/{id}`, `/agreements/{id}`, `/tariffs/{id}` and `/subscriptions/{id}`;
the read window is not an atomic provider snapshot. Owner/agreement/subscription
reads precede tariff policy so an unavailable slow policy cannot erase an
already timely negative. Every point result and scope error is checked against
the same absolute budget; late responses are discarded. Current catalog prices,
sale visibility and Kernel publication do not reprice accepted history. Balances,
payments and charges are not a separate Portal settlement authority.

LBX's `block_to_close_days` is informational lifecycle metadata under the
[2026-11-09 decision](../architecture/decisions/0005-external-billing-boundary.md#accepted-unknown-recovery-and-lifecycle-metadata-decisions---2026-11-09).
It is optional for current-offer admission and excluded from current material
fingerprints. Its absence or change alone does not affect Widget admission or
source trust. Portal uses the concrete subscription's blocking/ended facts;
LBX owns automatic closure. Existing accepted snapshots/digests remain intact.

Commercial proof is `COMPLETE_MATCH`, `COMPLETE_MISMATCH` or `INCOMPLETE`.
Missing material effective terms, applicable policy or currency interpretation
remain `INCOMPLETE` even alongside a known difference. Only full material
reconstruction can establish `COMPLETE_MISMATCH`; original-key/owner/relationship
contradictions remain decisive independently of commercial completeness.
Waiting/unpaid is inactive/blocked and may have null cycle dates. Complete owned ACTIVE/unblocked
proof with matching terms and coherent cycle evidence records operational
active/allowed facts. Financial and administrative blocks are distinct negative
facts. State 3 with recognized blocking values 0, 1 or 3 is ended. A valid
agreement closure also proves ended for the owned subscription. For an already
bound subscription, complete customer/agreement ownership plus the retained
canonical binding can prove that negative even if the subscription read is
unavailable; it cannot establish a first binding from an unknown candidate.
Ended is terminal; a later nonterminal state for the same canonical ID
opens subscription_terminal_revival_conflict.

Payment Widget opening also reads the original agreement's bounded subscription
inventory under the same reconciliation lease and I/O budget. Unexpected live
subscriptions conflict regardless of tariff; terminal subscriptions are excluded
using the shared lifecycle rules. A stable complete re-list is required before
payment presentation. Incomplete discovery cannot mint a payment Widget or renew
source trust; confirmed conflicts use the canonical fenced apply immediately,
without waiting for the background inventory cadence. Account-only viewing does
not require this purchase-specific check.

Payment-Widget admission uses the explicit opening's own fresh proof, under the
[2026-11-09 owner decision](../architecture/decisions/0005-external-billing-boundary.md#accepted-payment-widget-admission-decision---2026-11-09).
A later independent incomplete poll or reconciliation fence change does not
cancel that proof by itself. The post-Client-API local check still refuses a
changed session/binding/consent, unresolved review, proven identity/commercial
conflict or ended subscription. An incomplete opening proof still refuses the
Widget, and retained source trust cannot replace the opening's required reads.
Background polling and its source-trust deadlines continue independently.

Only complete matching proof without a known review refreshes source trust.
Trust begins at `read_started_at` and lasts at most six hours, with no outage
grace. Incomplete reads preserve the existing finite support without extending
it. Authoritative subscription apply reduces usability for proven owned
negative/conflicting facts even if unrelated commercial fields are missing.
Customer inventory applies its collected evidence separately, as described
below. Polling cannot clear a known financial/subscription conflict merely
because later terms match.

Provider calendar dates retain their original precision. Missing, sentinel or
contradictory current-cycle bounds cannot establish positive trust. Date-only
facts do not imply a timezone, UTC boundary or allowance identity.

Purchase consent, original terms, permanent bindings and held product scope
survive reconciliation, outages and ended state. Existing proven account scope
survives credential rotation at the same origin; ambiguous/foreign scope refuses
as billing_connection_conflict. A customer-key conflict uses the existing explicit
account-open recovery policy; background recovery cannot restore that conflict.
See [customer diagnosis and recovery](ANY-709-billing-runbook.md#customer-diagnosis-cli).

The worker produces subscription facts and expiry evidence. It does not choose an
access primary, grant access or create allowances/revisions/invalidations.

## Embedded worker settings and resource limits

The initial deployment is one API process/replica with an embedded worker.
There is no separate process to launch or standalone worker command/container.

- `BILLING_WORKER_ENABLED=true`: starts embedded execution when LBX is configured.
- `BILLING_WORKER_URGENT_CONCURRENCY=2`: urgent source slots, range 1–16.
- `BILLING_WORKER_NORMAL_CONCURRENCY=1`: normal source slots, range 1–16.
- `BILLING_WORKER_IO_TIMEOUT_SECONDS=60`: total source/cleanup budget; greater
  than the cleanup reserve and at most 240 seconds. This leaves the 30-second
  claim/apply margin and refusal retry within the five-minute urgent cadence.
- `BILLING_WORKER_SCAN_BATCH_SIZE=100`: local enrollment/repair batch, range 1–100.

Foreground purchase preparation and Widget opening use
`PREFLIGHT_TOTAL_TIMEOUT_SECONDS`, forwarded by development, agent and production
Compose. The production example currently sets **60 seconds** as a temporary
operating value pending [ANY-819](https://linear.app/paveldik/issue/ANY-819);
preserve the working local override. The application default remains 10 seconds.
This foreground budget is separate from the worker timeout above.

`PREFLIGHT_CLEANUP_TIMEOUT_SECONDS` reserves cleanup within the total I/O budget.
Finite work/subscription leases include a 30-second local apply margin. Late or
superseded source results cannot overwrite newer facts. Timely proof may finish
its short database apply within the lease margin. Unfinished HTTP/database work
retains its occupied capacity through cleanup, including after cancellation.

Limits are per-process, not provider-wide concurrency or requests-per-second
quotas. Urgent, normal and provider-free local work have reserved capacity;
worker resources are isolated from purchase/Widget/new-sale resources.
Unconfigured or partially configured LBX reports `not_configured` without source
execution; disabled execution reports `disabled`. Source outage alone does not
withdraw identity readiness.

Increase capacity only from measured queue age/source latency and actual LBX
limits. A future separate worker can reuse the durable jobs, but requires an
explicit stop-claim/drain/replace procedure and aggregate capacity review before
adding processes. Limits do not coordinate capacity across API replicas.

## Enrollment, cadence and recovery

Prepared/recovered subscriptions enroll automatically. Durable work resumes after
restart, and periodic local repair fills missing work without resetting existing
schedules. Malformed history is quarantined as invalid; recoverable customer
state and local contention remain retryable. Enrollment needs no provider HTTP.

- Normal subscription reconciliation runs approximately every 15 minutes.
- Never-positive, blocked, incomplete, conflicted or near-expiry subscriptions
  are urgent, with at most five minutes between scheduled attempts. Near expiry
  means source trust has 30 minutes or less remaining.
- Automatic uncertain-create recovery runs only inside its fixed two-hour
  window. Its separate deadline job pauses discovery and reports the case.
- Stable customer inventory runs approximately every six hours; incomplete or
  conflicting inventory retries urgently within five minutes.
- Source-trust expiry and uncertain-create escalation run locally without
  provider HTTP, independently of source execution capacity.

Local source-trust expiry does not invent a provider block or renew trust.
Recurring schedules use earlier-only jitter. Incomplete source reads use bounded
backoff up to five minutes. Process pauses/backlog can cause observable cadence
lag; they never extend trust. Claims/fences prevent competing or stale consumers
from overwriting newer facts, and hints arriving during work remain due.

`external_create_recovery` is GET-only. Zero candidates remain uncertain; exactly
one original point-proven candidate may bind; ambiguous/foreign candidates or
an identity bound to another purchase require review or more proof. Recovery preserves the original
operation, request/key/date, accepted history and hold. Known financial conflicts
need audited resolution; a deadline-only escalation permits explicit user/CLI
GET-only recovery after automatic discovery has paused.
Advance, worker and operator use the same GET-only original-operation collector
and transactional binder. The original saved command, actual possible-send
history and fresh ownership/effective terms are required. A known binding never
re-enters preparation: completed recovery is a no-op, while lifecycle updates
require the existing subscription lease. A concurrent first binder discards the
losing candidate proof and forces fresh claimed reconciliation.

Original termination is recoverable history, including a closed agreement.
First binding atomically retains the binding and normalized negative, with zero
positive trust. A retained closed agreement blocks a new subscription POST.
Waiting subscriptions need no invented cycle dates to prove their creation;
ended objects cannot open payment presentation. No background financial replay
or uncertain-hold release is introduced.

`external_create_deadline` uses the current fixed active financial recovery
window. Legacy rows without an active deadline use original unknown_since + 2h.
Only an explicit authenticated continuation after completed typed PROVEN_NOT_SENT
may start a new two-hour active window for that same command. UNKNOWN, GETs,
backoff and restart cannot extend the window or permit another financial CREATE.
PENDING and completed PROVEN_NOT_SENT are excluded from overdue UNKNOWN
escalation and authorize no background send.

At the fixed deadline, unresolved customer/agreement/subscription discovery work
becomes `paused`; its lease is revoked while the original operation/hold remains.
Repair and restart do not re-enroll paused work. An independent inventory pass
still has its own cadence and cannot bind a paused unknown operation. The
deadline job becomes durable notification work: a failed/disabled Sentry SDK
keeps it pending with a five-minute retry, without resuming LBX discovery. A
successful SDK capture completes it. A crash after capture may repeat the event;
the fixed failure-class fingerprint groups repeats into the same Sentry issue.

Automatic recovery checks the fixed active window before source I/O and again
inside the first-binding transaction. A GET finishing after the deadline cannot
bind even if the independent local deadline job has not run yet; recovery
commits the pause and leaves escalation/notification to that job. A deadline
pause between queue claim and source entry is acknowledged as stopped work,
without an additional worker-failure report. Other stale/lost claims remain
errors. Explicit user/operator GET-only recovery is unchanged.

Completing a deadline job for an already finished operation does not require
the original purchase hold. Safe no-send release or a new purchase in that
product scope does not prevent cleanup. Escalating an unresolved financial
operation still requires its original hold.

Customer creation keeps its separate explicit-open retry policy. An active
customer-send: lease excludes competing recovery. Background execution never
creates customers, agreements, subscriptions, payments or renewals.
A `billing_busy` / PostgreSQL `55P03` refusal is local contention: retry the same
work without changing send authority, deadlines or holds. Use
`last_error_classification` to distinguish local contention from source errors.

`customer_inventory`, pre-send admission and operator recovery share one bounded
inventory implementation: fewer than 100 discovery rows, at most 20 relevant
candidates and a stable complete re-list under one read budget. Capped, duplicate,
unstable or partial discovery never proves absence. Permanent original bindings
identify known subscriptions, including another product already in review;
proposal_ai and brief_decoder may share a tariff without sharing product identity.
Each known subscription uses its existing lease and shared reconciliation writer.
Its commercial conflict stays scoped to that subscription. Timely canonical
negatives commit independently even if later discovery fails. Inventory-origin
observations validate the customer work owner without finishing the customer job.

A proved original possible-send/UNKNOWN candidate (including evidenced
deadline-only review) waits for original-operation recovery, not another POST.
The scan still checks later candidates. A closed agreement or terminal subscription
is not a live competitor. Proven competition records scoped customer-inventory:v1
evidence. For a PENDING/PROVEN_NOT_SENT purchase without a canonical subscription,
it rotates unsent admission fences while preserving no-send evidence and the hold;
correction permits another explicit advance of the same operation. For an active
binding or possible-send operation it creates customer_inventory_conflict review.
Incomplete passes never clear reviews. Local binding/operation versions are
rechecked at commit, using versions returned by this attempt's own claimed applies;
concurrent changes require a fresh attempt.

## Polling-only operation

This MVP build has no webhook receiver. `POST /api/billing/lbx/webhook` is
unavailable/404, has no handler, and cannot enqueue work or mutate billing facts.
There is no receiver enablement or authentication configuration in Settings,
env examples, Compose or harness propagation. An old deployment variable cannot
activate an endpoint in this build. Do not configure an LBX delivery URL for it.

Keep `BILLING_WORKER_ENABLED=true` with the configured contour-local LBX
connection. Durable enrollment/repair, source reads, uncertain-create recovery,
customer inventory and provider-free deadlines provide correctness without a
callback or browser session. Existing purchases and permanent bindings survive
worker restart. Later observation hints still coalesce through the same queue;
a stale owner or unacknowledged retry is failure, not committed progress.
Incomplete/conflicting customer inventory has urgent priority and a due time
within five minutes. A clean pass returns to normal priority/six-hour inventory
only when no newer generation is pending.

The `external_billing_webhook_deliveries` table and its existing schema are
retained as history. This build neither receives new rows nor processes or
marks retained inbox rows. Historical pending/processed/ignored values remain
unchanged by polling. Do not drop/truncate history or manually clear it as a
worker recovery action. Source reconciliation and paid-access authority remain
independent of receipt state. Any future receiver requires a separate scoped
implementation and real provider authentication/delivery evidence.

## Startup, inspection and shutdown

Apply migration `20261028_0005` after consolidated billing revision `20261029_0003`
through the normal migration service before API startup. For retired branch
revision labels, follow the [base migration runbook](ANY-709-billing-runbook.md#consolidated-any-709-migration).
Use the existing repository/deployment start/restart commands. To disable worker
execution, set `BILLING_WORKER_ENABLED=false` and restart. Shutdown stops claims
and drains bounded work/cleanup; outstanding work remains reclaimable after
finite lease expiry. Persistent cleanup is degraded health, not a successful drain.

`GET /api/health/billing` reports redacted worker status, occupied/cleanup slots,
pending/invalid work, oldest due time, execution errors and scan/progress times.
`/api/health/ready` requires the DB and progressing local supervision; LBX outage
alone does not make identity unready. `/api/health/live` remains DB-independent.
Health is diagnostic, never commercial/access authority.

## Privileged purchase operations

Commands use existing trusted deployment/OS access and identify the operator as
`os-euid:<uid>`. Unavailable OS identity refuses execution. Customer diagnosis is
`billing-customer diagnose --user-id <portal-user-uuid>`; it is read-only and
cannot resolve review.

Invoke `.venv/bin/python scripts/repo.py billing-purchase <action>` with
`--user-id <portal-user-uuid>` and `--purchase-id <purchase-intent-uuid>`.
The read-only `inspect-operation` lookup instead takes only `--operation-id`.
Success JSON includes the operator principal. Exit 0 means the command completed,
not that payment or positive source proof was established. Exit 1 returns only
`detail.code`; invalid parser arguments exit 2.

- `inspect`: local read-only evidence; no source I/O, row changes or leases.
  Output includes original operations/fences, current subscription facts/trust,
  recent observation summaries, work and review IDs/digests. Work/review lists
  cap at 100 with truncation flags; observations contain the latest 20 records.
  No customer keys, raw requests, credentials or accepted amounts are exposed.
- `inspect-operation --operation-id <local-operation-uuid>`: resolve the opaque
  operation reference from Sentry locally. It checks configured origin/account
  and tenant/region, returns local owner/purchase references and follow-up CLI
  commands, and opens no source resources. It uses the same trusted OS boundary.
- `recover`: bounded GET-only recovery of the original possible-send operation.
  It may prove a binding or close deadline-only review, but cannot send CREATE,
  adopt PENDING/PROVEN_NOT_SENT or clear known conflicts. For a bound subscription,
  use `reconcile`.
- `reconcile`: bounded authoritative recheck of the canonical subscription.
  It records waiting/active/blocked/ended/incomplete/conflicting evidence and
  schedules follow-up. Known conflicts remain open. The budget is
  `PREFLIGHT_TOTAL_TIMEOUT_SECONDS` with its cleanup reserve; active work may
  return `subscription_reconciliation_busy`. Inspect and retry after completion
  or finite lease expiry. Source outage never extends trust.
- `resolve-review`: fresh-proof audited resolution, with required `--resolution`,
  `--case-id`, `--expected-case-digest`, `--reason` and `--reference`. Copy the current
  case ID and `sha256:` digest from `inspect`. Reason/reference are nonempty bounded
  single-line text (500/300 characters); include no secrets or personal data.

Examples; replace placeholders with local IDs and current expectations:

```bash
.venv/bin/python scripts/repo.py billing-purchase inspect --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid>
.venv/bin/python scripts/repo.py billing-purchase recover --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid>
.venv/bin/python scripts/repo.py billing-purchase reconcile --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid>
.venv/bin/python scripts/repo.py billing-purchase resolve-review --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid> --resolution restore-original --case-id <case-uuid> --expected-case-digest <sha256:digest> --expected-observation-id <supporting-observation-uuid> --expected-reconciliation-fence <integer> --reason 'Original facts verified' --reference 'ANY-715'
.venv/bin/python scripts/repo.py billing-purchase resolve-review --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid> --resolution bind-original --case-id <case-uuid> --expected-case-digest <sha256:digest> --operation-id <create-operation-uuid> --expected-operation-fence <send-fence-uuid> --reason 'Original operation proven' --reference 'ANY-715'
```

`restore-original` also requires `--expected-observation-id` and
`--expected-reconciliation-fence`, with no operation override. Supported cases are
subscription_identity_conflict, subscription_commercial_mismatch, or an original
already-bound operation's financial_binding_conflict /
accepted_terms_changed_after_preparation, or customer_inventory_conflict. All
original bindings and fresh complete owned original-term/prepaid proof must hold. It restores facts and linked state
without rebinding. Blocked/ended facts remain blocked/ended and held; terminal
revival has no override.

`select-primary` uses the same observation/fence expectations as
`restore-original`. It accepts only `primary_selection_required` for the already
bound subscription, with no unrelated open reviews or financial admission
conflict. Fresh complete eligible original proof, complete current inventory and
`PAID_ACCESS_CLOCK_SKEW_SECONDS` are required. It cannot replace another selected
primary, create a subscription or invent quota. The case, selection, paid state,
revision, outbox and audit commit together. Repeating the identical command replays
the saved result without source calls.

`bind-original` also requires `--operation-id` and `--expected-operation-fence`, with
no reconciliation expectations. Supported cases are financial_binding_conflict /
accepted_terms_changed_after_preparation / customer_inventory_conflict on an
unbound possible-send financial operation. Complete bounded discovery must prove exactly one original candidate,
even with a saved receipt. Saved request/correlation/accepted terms, original
agreement date and supported subscription lifecycle/policy must match. Binding
enrolls reconciliation without itself renewing trust. This includes a proved
original terminal subscription or closed agreement. Each required point is read
once; the same normalized original proof authorizes binding and its atomic
audit. Complete original creation is separate from a complete paid-cycle proof.

The conflict evidence must retain original POSSIBLE_SEND/UNKNOWN state and send
fence; the same operation's deadline-review evidence may supply it. Missing
history or PENDING/PROVEN_NOT_SENT cannot be turned into send proof. Both commands
use the same fresh inventory check. Restore claims the target once,
keeps that lease through proof/inventory, then commits target facts, exact case
resolution and audit together. Inventory reuses those target reads; independently
claimed sibling negatives may commit without resolving the target. Bind may accept
its own pending candidate only together with the complete saved-original proof.
Only evidence-linked inventory, canonical and same-operation deadline cases may
resolve together; unrelated cases still refuse. Both commands
recheck current ownership, consent, case digest and expected fences. The audit
billing-operator-resolution:v1 records principal, reason/reference and proof
atomically with facts/binding, related-case resolution and scheduling. An identical
completed request by the same operator replays without writes/source calls;
a changed or stale repeat refuses.

Refusals include stale evidence, incomplete/capped/ambiguous discovery, foreign
or already-bound objects, unsupported policy, customer identity conflict,
unrelated open cases, terminal revival and changed accepted requests. Diagnose
billing_review_stale, billing_review_unrelated_cases, billing_review_proof_incomplete,
billing_review_terminal, purchase_history_unproven and ordinary source/busy errors;
do not bypass them. There is no release-terminal, force-release, arbitrary rebind,
commercial reacceptance, manual paid or quota command. Terminal revival has no
override; an inventory review requires fresh proof that competition was corrected. Existing Step 7 proven-unsent automatic
release keeps its separate rule.

Source proof intervals are bracketed by short PostgreSQL clock reads before
and after source I/O; their sessions close before HTTP. Reconciliation claims,
financial possible-send start/deadline and operator-resolution windows use the
same database clock. API wall-clock skew cannot reject an otherwise current
proof. Owner/fence, expired lease and prior-attempt checks remain mandatory;
incomplete reads never extend the six-hour trust, and first binding grants no
positive trust.

An unexpected live subscription on a known dedicated agreement conflicts with
that agreement's purchase regardless of tariff. Tariff-scoped competition is
also retained; ended subscriptions and closed agreements keep their exceptions.
Known subscription IDs on another purchase's agreement receive the same point
checks; a contradictory canonical identity proof also triggers them when
discovery lags or omits the known ID. These checks share the existing candidate
limit and source budget. A known sibling is never adopted as an UNKNOWN original.
A customer identity conflict discovered while proving an UNKNOWN candidate
uses the customer-wide fenced writer and discards the now-stale inventory.
Only a proven original-key mismatch permits original-pair recovery; a generic
source-scope conflict does not.

## Alerts and outage diagnosis

Inspect /api/health/billing, payment_portal_billing_worker_* metrics and the
affected purchase's inspect output. last_progress_at includes durable incomplete
attempts and local work; it is not new authoritative proof.
Completed/refused queue attempts report progress, not verified source proof;
the failures counter reports execution errors.
last_verified_subscription_at and
payment_portal_billing_worker_last_verified_subscription_timestamp_seconds track
complete matching proof in this process, not freshness of every subscription.
payment_portal_billing_worker_subscription_proofs_total distinguishes verified,
incomplete and conflict. Process metrics reset on restart; persisted per-scope
evidence remains authoritative.

Alert on growing queue age/cadence lag, stale local scans (120 seconds), invalid
records, persistent cleanup, repeated authentication denial and incomplete proof
approaching its trust deadline. During an outage, confirm local expiry/deadline
progress while source reads back off. Restore connection/authentication through
the normal deployment path and require fresh proof. Use recover for UNKNOWN,
reconcile for bound subscriptions and only supported audited conflict resolutions.
Do not delete work, reset deadlines, release holds or extend trust to hide backlog.
Alert routing remains operator-owned under ANY-86.

## UNKNOWN create after two hours

Sentry exception type: `BillingRecoveryExhausted`. The fixed message explains
that the LBX create result is still unknown, automatic discovery is paused and
duplicate-prevention holds remain. Its allowlisted `billing_recovery` context
contains only local operation/kind/review-case references, the runbook URL, and
the `inspect-operation` command. Owner/purchase references and follow-up commands
are resolved locally; no user IDs, provider payload, customer email, provider
correlation key, card data, credential or token are sent to Sentry.

Use the existing API Sentry DSN/release configuration. Configure occurrence/event
notifications for this exception type to the existing billing operator so every
newly paused case alerts even while its failure-class issue is already open.
New-issue/regression-only rules do not satisfy this requirement. Alert routing
is operator-managed Sentry project configuration; an SDK capture alone is not
proof that email or another notification channel is configured or delivered.
The fingerprint is a fixed failure-class key; correlation IDs stay in contexts.
Each event identifies its case; repeated events with the same `case_id` refer
to the same case. An accepted case is not reported on every GET. Delivery testing
must use an isolated recording transport unless a real alert test is authorized.

Operator procedure:

1. Read the Sentry event and run its `inspect_command` (`inspect-operation`).
   This local lookup returns the owner/purchase references and the actual
   inspect/recover commands. Run its returned `inspect_command` to read current
   evidence. If the original operation has already recovered, verify that its
   specific review case is resolved and record that case as handled; do not
   create another object. The Sentry issue groups multiple cases. Keep it open
   while any case remains unresolved; recovery of one operation is not a reason
   to close the grouped issue.
2. Check connection/authentication and LBX availability through normal setup.
   An empty discovery result still does not prove that creation never happened.
3. For an agreement/subscription, run the local lookup's `recover_command`. It invokes
   bounded GET-only original recovery. A unique proven original may bind and
   resolve its deadline-only review. No new financial POST is sent.
4. For a customer, run `billing-customer diagnose --user-id <portal-user-uuid>`
   as provided by the local lookup, then have the user explicitly reopen their billing
   account after source recovery. Original paired point proof is still required;
   the paused worker does not send another customer CREATE.
5. If multiple/foreign candidates, changed effective terms or unrelated cases
   remain, inspect their exact case IDs/digests. Use only the supported audited
   `resolve-review` actions above after establishing their required proof. These
   actions cannot adopt an arbitrary ID or assert payment.
6. If no original object can be proved, retain the hold and investigate with
   LBX using the saved original-operation evidence. This build has no supported
   "declare absent / reset unknown purchase" operation (ANY-821). Do not delete
   work/operation rows or force-release the hold to start a replacement.

An explicit user's "Continue recovery" also remains available after the pause.
It can prove the original through GET but cannot repeat an uncertain financial
CREATE. After a successful recovery, normal monitoring of the now-bound
subscription resumes; first binding alone does not establish positive trust.

## Projection and access boundary

Consume subscription-reconciliation:v1 observations, original ownership/legal/
accepted provenance, commercial classification, last_authoritative_read_at and
projection_valid_until. subscription-trust-expiry:v1 supplies deterministic
source-expiry evidence. Incomplete attempts preserve only finite existing support;
known negative/conflicting facts supersede usability. Calendar precision stays
provider evidence, without an inferred UTC cycle or allowance identity.

ANY-765 selects a first primary through complete shared inventory and records
paid grants/allowances, semantic revisions and a coalesced invalidation outbox.
The existing local lane uses the earliest supported paid/source deadline. It
removes expired access or metering without source configuration or HTTP and
repairs missing, completed or incorrectly delayed deadline jobs after restart.
It never renews source trust or issues an allowance. A proven same-cycle recovery
reuses its allowance identity; a proven later cycle issues one current set without
backfill. Date-only cycles supply no inferred UTC deadline or urgency.

`PAID_ACCESS_CLOCK_SKEW_SECONDS` has no default: supply the deployment's supported
clock guarantee (1..299 seconds). Without it, positive derivation stays disabled;
local reductions continue. Foreground default remains 10 seconds, with the
existing 60-second deployment override; worker source timeout remains 60 seconds.
Step 10 owns Kernel wire/invalidation delivery and coupled UTC calendar design.
Step 11 owns complete real paid-access/natural-renewal and launch acceptance.
