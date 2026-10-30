# ANY-715 billing operations

Status: Steps 1–5 shared reconciliation, embedded polling, recovery, inventory, optional webhook hints and audited operations implemented; final verification recorded in the plan.
Updated: 2026-10-29.
Issue: [ANY-715](https://linear.app/paveldik/issue/ANY-715).
Scope: [implementation plan](../exec-plans/active/ANY-715-implementation-plan.md), Steps 1–5.

## Shared proof and original history

`app.composition.reconciliation.reconcile_subscription()` is the reusable outer
I/O seam. It accepts an explicitly supplied LBX client and bounded admission
resource, configuration, session factory and canonical local subscription ID.
The embedded worker and privileged `reconcile` CLI call this shared seam; it is not a public billing endpoint.
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
incomplete evidence. Effective-term proof checks supplied contradictions before
missing fields: a changed service price with an absent total still opens a
commercial conflict. A positive match continues to require all mandatory terms.
Attempts whose source reads exhaust the I/O budget persist only incomplete
evidence; delayed source results cannot become positive facts. On-time proof
can finish its short fenced DB apply within the existing 30-second lease margin. Expired or superseded leases
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
lifetime/instance bounds cannot establish positive trust. Datetime evidence keeps
its time-of-day precision. Date-only evidence stays a calendar date; mixed
precision on the same day cannot prove ordering and remains incomplete. The provider's latest
calculation-period pair is preserved without inventing an account timezone,
exact UTC boundaries, native cycle ID or allowance identity. This step does not
claim to prove natural rollover or derive paid access from those dates.

Step 2 supplies automatic enrollment, durable polling and local source-trust
expiry evidence. Step 3 adds uncertain-create recovery/inventory loops. Step 4 adds optional webhook hints; Step 5 supplies audited operator commands. Step 9 owns primary selection,
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
DB apply runs outside the source timeout and still checks finite ownership/fences.
Cancelling a DB waiter retains the exact framework thread task and its limiter
until the synchronous transaction finishes. No replacement claim starts in that
lane while cancelled DB work remains live; health reports pending cleanup.
No replacement request can accumulate behind an abandoned owner. Apply checks
both queue ownership/expiry and subscription owner/fence/expiry under business
locks. All provider retries are GET-only; the worker never creates a customer,
agreement, subscription, payment or renewal.

These are **per-process** limits, not provider-wide concurrency/RPS guarantees.
The worker owns separate LBX HTTP pools and bounded DB delegation/connection
capacity from purchase, Widget and new-sale resources. Local sweep/deadline work
has separate DB delegation and no provider HTTP. Normal and urgent lanes cannot
consume each other's reserved slots. Each worker HTTP pool fits the sum of both
lane limits, independently of interactive `PREFLIGHT_MAX_ACTIVE`; retained cleanup
continues to occupy its lane's admission slot. Wholly unconfigured LBX reports
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
provider-free `external_create_deadline` job uses the current financial
`billing_work_items.active_recovery_deadline_at`, falling back to the immutable
original `unknown_since + 2h` pair for pre-migration NULL rows. A completed typed
`PROVEN_NOT_SENT` followed by an authorized explicit advance sets a new active
two-hour window under the send fence; original request/date/history remain unchanged. It escalates unresolved possible-send/UNKNOWN to
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
recovery is **NOT_RUN**. Webhook mode remains **DISABLED/POLLING-ONLY** until its real gate below passes.
Audited resolution and inspection commands are documented below.

## Optional webhook receiver and manual deployment

`POST /api/billing/lbx/webhook` is implemented behind these settings:

- `LBX_WEBHOOK_ENABLED=false`: default; returns 404 before body processing or DB use.
- `LBX_WEBHOOK_AUTH_HEADER=`: required credential header name when enabled.
- `LBX_WEBHOOK_AUTH_VALUE=`: required exact shared-secret header value when enabled;
  keep it in the deployment secret manager/protected API environment, separate
  from Server API credentials and the Widget signing secret.

For worktree `repo:up`, all three settings pass from root `.env` or exported
environment values into private `.harness/runtime.env`; exported values take
precedence. They are excluded from public runtime metadata and web settings.

Enabling requires a valid configured LBX connection. Invalid/missing header or
secret configuration fails startup. Transport/correlation headers (including
`X-Request-ID`, tracing headers and `User-Agent`) cannot carry the credential,
preventing its reuse in request diagnostics. Header names are HTTP case insensitive;
values are compared exactly in constant time. Duplicate/missing/wrong credentials
return 401 before reading the body. No query-token or signature fallback exists.
The JSON receive limit is 65536 bytes, enforced for declared and streamed bodies
(413). Unsupported media type returns 415; malformed JSON, unsupported event or
invalid correlation fields returns 422. Rejections never echo payload or headers.

Supported events are exactly:

- `create_subscription`
- `change_subscription`
- `block_subscription`
- `new_charge_period`
- `close_subscription`
- `delete_subscription`

The Integration reads only `event` and positive integer `parameters.subscription_id`,
`parameters.agreement_id` and optional `parameters.user_id`. Other fields are
discarded. Account/tenant/contour come from deployment configuration; user/product
and work IDs come from existing local bindings. Unknown, foreign or conflicting
correlation is acknowledged as `ignored`, with hashed correlation only. It creates
no binding or recovery authority. Unknown creates still converge through independent
GET-only recovery/inventory. An ignored receipt can be inspected by its local
delivery ID; a later proven binding is polled independently.

A valid known hint atomically commits a redacted receipt and immediate coalesced
reconciliation work before returning 200 with a named response containing only
local `delivery_id` and `outcome` (`queued` or `ignored`). No LBX REST request runs
in receipt, and payload lifecycle/price/payment fields never become facts.
`billing-webhook-receipt:v1` evidence contains only the allowlisted event.
`billing-webhook-work:v1` correlation retains a subject hash and, for queued work,
local subscription/work IDs and `enqueue_generation`. Raw bodies, headers,
credentials, customer contact/payment fields and provider event IDs are not stored.
The body SHA-256 is diagnostic only: identical later events receive separate
receipts and are never permanently deduplicated by hash.

Receipts stay `pending` through failed/incomplete GETs or crashed workers. A fenced
claim applying complete authoritative proof marks only its covered generations
`processed` in the same transaction as facts and rescheduling. Later receipts
remain pending and their immediate hint survives that completion. Reclaiming an
expired lease or restarting uses the same durable work. An incomplete read retries
with the existing urgent backoff; a webhook arriving before REST visibility cannot
extend trust. A complete but still old source response is only a current read;
normal polling observes later visibility without any visibility-SLA assumption.
Known conflicts remain subject to their existing review policy. `processed` means
complete reread applied, never a payment, access grant or event-version match.

### Test and production setup

The [official manual setup guide](https://docs.lbxbilling.ru/api/webhooks/set_webhooks/)
and [event examples](https://docs.lbxbilling.ru/api/webhooks/list_webhooks/)
were checked on 2026-10-28. The guide documents URL, token, event selection and
an optional retry switch; it does not establish the actual authentication header
name/value format for this account. No configuration API is assumed.

1. Keep the receiver disabled while preparing the target deployment's LBX
   connection and secret configuration. Use separate test/production secrets.
   Confirm ordinary embedded polling is healthy and migrations are applied.
2. Test URL: the authorized publicly reachable HTTPS **test Portal origin** plus
   `/api/billing/lbx/webhook`. Production URL: the approved HTTPS
   `APP_PUBLIC_BASE_URL` origin plus `/api/billing/lbx/webhook`, served by that
   contour's API through the existing Caddy `/api/*` proxy. Substitute actual
   deployment origins; do not use a Kernel, Resolver, Widget or another contour URL.
3. In the correct LBX account, open Settings → Parameters → Webhooks → Add.
   Enter the target URL, token from the secret manager, and a nonsecret description.
   Select exactly the six events listed above. The optional **Repeat request**
   switch may be enabled, but Portal correctness does not rely on redelivery.
   Save only as part of an authorized integration gate.
4. Verify the account's real authentication transport through an authorized,
   privacy-controlled test delivery. Set `LBX_WEBHOOK_AUTH_HEADER` to its verified
   credential header and `LBX_WEBHOOK_AUTH_VALUE` to the **entire exact header
   value**, including any verified prefix. Do not guess a header/prefix from the
   token field, accept anonymous delivery, or move the secret into the URL.
   If the account cannot send this mode securely, leave disabled. Avoid body/header
   logging at LBX, ingress, debug proxies, traces and the test capture boundary.
5. Once the test mode is verified, set `LBX_WEBHOOK_ENABLED=true` and restart the
   test API through its ordinary deployment path. Confirm the checklist below.
   A local synthetic POST proves only Portal handling, not real LBX delivery.
6. Production requires its own origin/account/secret and the same verified
   transport, correlation and event-to-GET checks before enablement. Keep one API
   replica and independent polling enabled. Document dated results without secrets.

### Real enablement checklist and rollback

As of 2026-10-28 the gate is **NOT_RUN**, with **DISABLED/POLLING-ONLY** required.
Synthetic HTTP/PostgreSQL coverage is separate from this gate: 38 fast webhook
cases and 10 PostgreSQL webhook cases PASS, including failure after commit,
concurrent claims/hints and polling-only convergence. The full canonical check
also passes; browser E2E was skipped by the harness. Authorized owner QA
must record date, environment and sanitized local delivery/work/observation IDs for:

- Real correct-header delivery accepted; missing/incorrect secret rejected before
  body processing, with no credential/payload leakage.
- Each selected event correlates only to its already owned canonical scope;
  unknown/conflicting correlation stays ignored.
- Receipt and work are durable before 200; worker subsequently uses GETs and the
  shared transition. Verify duplicate/reordered hints and a restart during work.
- Observe event-to-REST visibility, including an early event/incomplete read and
  later convergence. Do not assume a provider delivery or visibility deadline.
- Lose a notification or disable delivery and confirm polling convergence;
  record provider retry behavior only if actually observed.

Rollback: set `LBX_WEBHOOK_ENABLED=false`, restart the API and verify the route
returns 404. Disable/delete the webhook in the correct LBX account when authorized.
Keep `BILLING_WORKER_ENABLED=true` and confirm polling/queue progress. Already
committed pending receipts/work survive disablement and restart; never delete them
or release holds to roll back. Rotate the secret in both systems through the same
verified gate before re-enabling. Investigate old pending receipts by their local
work ID/generation, claim/lease, due time and `last_error_classification`; the
existing worker retries without replaying raw payloads. There is no inbox-delete,
manual replay or provider-configuration CLI in Step 4. No 500→retry assumption
is required after a DB failure or lost response.

## Startup, inspection and shutdown

Apply migrations through `20261028_0005` (worker, following consolidated billing
revision `20261029_0003`) through the normal migration service before starting
the API. Retired ANY-709 revision labels require the verified transition in the
[base migration runbook](ANY-709-billing-runbook.md#consolidated-any-709-migration);
do not replay consolidated DDL over an existing branch schema. Start/restart with the existing repository/deployment commands;
there is no additional process to launch. To stop source execution, set
`BILLING_WORKER_ENABLED=false` and restart through the ordinary deployment path.
Stop claiming before replacing the owner. Shutdown drains up to the configured
I/O budget, cancels/awaits waiters and drains source cleanup plus retained DB
owners. If cleanup is still
pending it retains its slot, reports degraded shutdown and propagates failure;
it never reports a successful drain or closes the client/engine underneath live
I/O or a synchronous DB transaction.
After process exit, finite durable leases are reclaimable on restart.

`GET /api/health/billing` exposes named, redacted worker status, occupied slots,
cleanup-pending count, pending/invalid work, oldest due time, failures, enrollment
batch count and last scan/progress times. `/api/health/ready` requires the DB and
progressing local worker supervision; an LBX outage alone does not make identity
unready. `/api/health/live` remains DB-independent. No IDs/secrets are returned.

Prometheus `payment_portal_billing_worker_*` signals report attempts by lane and
outcome, active/cleanup slots, pending/invalid work, oldest overdue age and last
progress time. `failures` counts execution exceptions. A `BillingRefused` caught
by worker dispatch counts as `refused` only when its retry or quarantine commits
under the current queue owner. This advances last progress and retains the safe
refusal code in durable diagnostics;
it does not increment failures or report an execution exception. Lost ownership
and failed or uncertain commit acknowledgement remain execution failures.
Completed work and last progress include durably recorded incomplete attempts
and local sweeps. Neither completed nor refused attempts claim successful source
proof. Inspect `source_incomplete` work classifications,
versioned observations and bounded `lbx_http` source/authentication diagnostics
for source failures. Alert on repeated authentication denial/configuration errors
or incomplete reads approaching the affected source-trust deadline; the read
backoff supplies cooldown without preserving or extending trust.
Labels contain no local/customer/product IDs. Growing overdue age,
invalid records, failed local scans (120 seconds) or persistent cleanup warrant
operator investigation. Inspect durable work/projections through existing trusted
local DB access; use the purchase `inspect`/`recover`/`reconcile` commands documented below.
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

## Privileged purchase operations

All actions use the existing trusted deployment/OS access boundary and resolve
`os-euid:<uid>` through `resolve_operator_principal()`. An unavailable OS identity
refuses execution. There is no operator role, admin HTTP API or provider-ID
input. Keep the existing `billing-customer diagnose --user-id <portal-user-uuid>`
for separate customer diagnostics and original-key restoration policy.

Invoke `.venv/bin/python scripts/repo.py billing-purchase <action>` with both
`--user-id <portal-user-uuid>` and `--purchase-id <purchase-intent-uuid>`.
The equivalent module is `app.cli.billing_purchases` with `PYTHONPATH=apps/api`
and the same configured deployment environment. JSON success includes the OS
principal; exit 0 means the bounded command completed, not paid access or a
successful provider conclusion. Exit 1 returns only `detail.code`; invalid parser
arguments exit 2. A source refusal cannot expose raw errors or credentials.

- `inspect` reads local evidence only, in a read-only PostgreSQL transaction.
  It opens no source resources and changes no rows or leases. Output includes
  local operation IDs, states, send fences, receipts as booleans, active recovery
  deadlines, canonical subscription lifecycle/commercial/financial facts,
  finite trust, supporting observation/fence, recent observation summaries,
  due/leased work, generations, attempts, errors and review identities/digests.
  Work/review lists cap at 100 with explicit truncation flags; the observation
  list contains the latest 20 records. No customer keys, provider payloads,
  secrets, accepted amounts or raw requests appear in this output.
- `recover` performs bounded GET-only discovery/point proof through the same
  `recover_financial()` as the worker. It may bind the uniquely proven original
  possible-send operation and close a deadline-only escalation. It never sends
  CREATE, adopts PENDING/PROVEN_NOT_SENT, clears a known conflict or changes the
  original request/key/history/deadline. Bound subscriptions use `reconcile`.
- `reconcile` resolves the purchase's canonical local subscription and calls
  the worker's shared four-point read and fenced apply. It may record waiting,
  active, blocked, ended, incomplete or conflicting evidence; known conflicts
  remain open and cannot refresh positive trust. Reads use the existing CLI
  `PREFLIGHT_TOTAL_TIMEOUT_SECONDS` total budget, cleanup reserve and finite
  subscription lease. An active worker/CLI lease may return
  `subscription_reconciliation_busy`; inspect and retry after its owner finishes
  or the lease expires. Source outages never extend trust. Each point result,
  including a scope error, must arrive within the shared read budget. A timely
  proven identity conflict survives a later unrelated read timeout; late facts
  are discarded. Incomplete or blocked CLI results coalesce urgent reconciliation
  within five minutes without clearing a running worker's lease/generation or
  downgrading an existing urgent hint after a complete positive read.
- `resolve-review` is the only explicit audited known-conflict transition.
  Required common options: `--resolution`, `--case-id`,
  `--expected-case-digest`, `--reason` and `--reference`. Copy the current case
  ID and `sha256:` digest from `inspect`. Reason/reference must be nonempty,
  bounded single-line text (500/300 characters); never put secrets or personal
  data there. The reference identifies the incident/ticket. Stale evidence or
  unrelated open cases refuse the command.

Examples (placeholders must be replaced with local IDs and current expectations):

```bash
.venv/bin/python scripts/repo.py billing-purchase inspect --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid>
.venv/bin/python scripts/repo.py billing-purchase recover --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid>
.venv/bin/python scripts/repo.py billing-purchase reconcile --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid>
.venv/bin/python scripts/repo.py billing-purchase resolve-review --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid> --resolution restore-original --case-id <case-uuid> --expected-case-digest <sha256:digest> --expected-observation-id <supporting-observation-uuid> --expected-reconciliation-fence <integer> --reason 'Original canonical facts restored and verified' --reference 'ANY-715'
.venv/bin/python scripts/repo.py billing-purchase resolve-review --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid> --resolution bind-original --case-id <case-uuid> --expected-case-digest <sha256:digest> --operation-id <create-operation-uuid> --expected-operation-fence <send-fence-uuid> --reason 'Original uncertain operation uniquely proven' --reference 'ANY-715'
```

`restore-original` additionally requires `--expected-observation-id` and
`--expected-reconciliation-fence`, with no operation override. It supports only
`subscription_identity_conflict`, `subscription_commercial_mismatch`, or an
original already-bound operation's `financial_binding_conflict` /
`accepted_terms_changed_after_preparation`. All original financial bindings must
still exist. Fresh complete owned original-term/prepaid-policy proof is required.
Apply preserves those bindings, records a new authoritative observation and finite
trust, resolves the corrected case and restores the purchase's linked state.
A block is still a block: resolving commercial review never manually marks paid.
Complete matching ended proof may resolve its corrected commercial conflict while
remaining ended/blocked and held. A nonterminal reread of a previously ended
canonical ID is refused; `subscription_terminal_revival_conflict` itself has no
operator override.

`bind-original` additionally requires `--operation-id` and
`--expected-operation-fence`, with no reconciliation expectations. Only
`financial_binding_conflict` / `accepted_terms_changed_after_preparation` on that
unbound possible-send financial operation are supported. Its immutable saved
request, original correlation, accepted fingerprint and possible-send history
must prove the same command. Full bounded discovery must yield exactly one
point-proven original candidate, including when a receipt is saved. Agreements
also prove the original creation date. Subscription binding additionally requires
complete supported-policy/lifecycle proof. Apply reuses `bind_financial()` and
atomically enrolls the resulting subscription; this preparation does not itself
renew source trust. A remaining PENDING operation still requires the user's
existing explicit authorized advance before any send.

The original conflict evidence must retain its prior POSSIBLE_SEND/UNKNOWN state
and send fence. If an earlier deadline escalation already moved the same
operation to MANUAL_REVIEW, that operation's open
`external_create_outcome_unknown:<kind>` case can supply the preserved original
possible-send evidence. Its schema, purchase/operation identity, saved prior state and
evidence digest are checked; a different operation's deadline or any additional
known conflict still refuses. Historical cases without that proof, or cases
raised from PENDING/PROVEN_NOT_SENT, refuse binding; do not edit the case/history
to manufacture authorization.

Both resolutions lock/recheck user, purchase/hold, ordered financial operations,
subscription and target case before writing. Current customer identity, original
consent, accepted history, saved requests, fences and expected evidence must still
match; a competing poll, operator or changed receipt cannot be overwritten.
Resolution rotates the affected financial fences so older preparation/recovery
results or inventory snapshots cannot reopen the corrected conflict afterward.
`billing-operator-resolution:v1` on the existing review row records OS principal,
reason/reference, command digest, before/after identities, supporting observation
when one exists, and versioned fresh-proof summary/read window. Original case
and source evidence remain intact. Related deadline cases are locked and
rechecked after source I/O, then resolved in the same transaction with the OS
principal, reason/reference, original case digests and a link to the targeted
known-conflict case. Each retains the resulting binding and fresh-proof audit.
Audit/fact/binding/queue updates roll back
as one transaction on failure. A completed identical request by the same OS
principal returns `already_resolved` without source I/O or another audit;
a different repeat refuses as stale. Failed reads may leave only the normal
finite reconciliation claim for safe later reclaim.

Refusals include stale case/digest/observation/fence, incomplete/empty/capped or
ambiguous discovery, foreign or already-bound candidates, unsupported policy,
customer identity conflict, unrelated inventory/review cases, terminal revival,
unsafe unresolved CREATE effects, changed accepted request, arbitrary rebind,
commercial reacceptance, paid marking and quota edits. `billing_review_stale`,
`billing_review_unrelated_cases`, `billing_review_proof_incomplete`,
`billing_review_terminal`, `purchase_history_unproven` and ordinary source/busy
errors require diagnosis rather than bypass. No `release-terminal`, force-release,
manual paid or quota command exists. Ended state retains the hold, purchase,
consent and permanent bindings; proven-unsent automatic release retains its
separate existing Step 7 rule.

## Alerts and outage diagnosis

Treat `last_progress_at` as durable queue/local progress, including incomplete
attempts. `last_verified_subscription_at` and
`payment_portal_billing_worker_last_verified_subscription_timestamp_seconds`
track complete matching subscription proof in this process; they do not prove
all subscriptions are fresh. The bounded
`payment_portal_billing_worker_subscription_proofs_total{outcome}` distinguishes
`verified`, `incomplete` and `conflict`. Process restarts reset these diagnostic
signals; per-subscription persisted evidence remains authoritative.

Alert on growing queue age/cadence lag, stale local scans (120 seconds), invalid
records, persistent cleanup, repeated source authentication denial, or repeated
incomplete proofs approaching a subscription's existing trust deadline. Inspect
`/api/health/billing`, the metrics and the affected purchase's `inspect` output.
During an outage confirm local expiry/deadline work progresses while source work
backs off. Restore connection/authentication through the ordinary deployment
path, keep polling enabled and require fresh complete proof. Use `recover` for
UNKNOWN, `reconcile` for canonical subscriptions and only the supported audited
resolution for a corrected known conflict. Do not delete jobs, reset deadlines,
release holds or enlarge trust to hide backlog. Actual LBX quotas remain
unverified; configured limits apply per-process. Deployment alert routing remains
operator-owned under ANY-86.

## Step 9 handoff

Reuse `subscription-reconciliation:v1`, complete/mismatch/incomplete classification,
original ownership/legal/link/accepted provenance, source observation IDs,
`last_authoritative_read_at`, `projection_valid_until`, and
`subscription-trust-expiry:v1` deterministic boundary evidence. Preserve date-only
and timestamp calendar precision; no account timezone, UTC cycle or allowance
identity is inferred. Incomplete attempts preserve only finite existing support;
known negative/conflict facts supersede usability immediately.

Reuse shared recovery/bind/apply, PostgreSQL claims/generations/fences, active
UNKNOWN windows and the embedded runner's cancellation/cleanup ownership. The
migration head remains `20261028_0005`, after `20261029_0003`; Step 5 adds no DDL.
The two audit modes above are the entire supported operator resolution surface.
Terminal hold release and inventory-conflict overrides remain deferred.

Step 9 owns primary selection, paid grants/allowances, effective-access revisions
and atomic outbox production, and must attach earlier access-reducing deadlines
to this scheduling path. Step 10 owns Kernel wire/invalidation and coupled UTC
calendar design. Step 11 owns real paid-access/natural-renewal and launch QA.
No operator action, observation, webhook, successful CREATE or Widget event
independently grants access. Automated evidence remains **SIMULATED**; real
read-only LBX and real webhook gates must be recorded separately below and in the
implementation record. Production migration and browser E2E are separate checks.

2026-10-29 checkpoint: **NOT_RUN / LBX_NOT_CONFIGURED**. The local configured
read-only check exited before source or database writes; no actual provider read
PASS is claimed. Real webhook authentication/delivery is also NOT_RUN and the
required mode remains **DISABLED/POLLING-ONLY**. See the Step 5 implementation
record for final automated counts and logs; simulated proofs cannot satisfy
either real integration checkpoint.
