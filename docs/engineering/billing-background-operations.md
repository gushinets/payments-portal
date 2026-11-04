# Background billing operations

Configuration, scheduling, webhook setup and operator controls for the embedded
billing worker. For connection setup, purchases and Widget operation, use the
[billing runbook](ANY-709-billing-runbook.md). Architectural authority is
[ADR 0005](../architecture/decisions/0005-external-billing-boundary.md) and its
accepted specifications and dated decisions.

## Source authority and trust

LBX owns subscription activation and financial/administrative blocking. Portal
verifies the original customer, agreement/seller, accepted effective terms and
supported prepaid policy. Reconciliation uses authenticated point reads of
`/users/{id}`, `/agreements/{id}`, `/tariffs/{id}` and `/subscriptions/{id}`;
the read window is not an atomic provider snapshot. Current catalog prices,
sale visibility and Kernel publication do not reprice accepted history. Balances,
payments and charges are not a separate Portal settlement authority.

Commercial proof is `COMPLETE_MATCH`, `COMPLETE_MISMATCH` or `INCOMPLETE`. Waiting/unpaid
is inactive/blocked and may have null cycle dates. Complete owned ACTIVE/unblocked
proof with matching terms and coherent cycle evidence records operational
active/allowed facts. Financial and administrative blocks are distinct negative
facts. Ended is terminal; a later nonterminal state for the same canonical ID
opens subscription_terminal_revival_conflict.

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
Restoring the original customer pair does not restore subscription eligibility;
fresh authoritative reconciliation is still required.

The worker produces subscription facts and expiry evidence. It does not choose an
access primary, grant access or create allowances/revisions/invalidations.

## Embedded worker settings and resource limits

The initial deployment is one API process/replica with an embedded worker.
There is no separate process to launch or standalone worker command/container.

- `BILLING_WORKER_ENABLED=true`: starts embedded execution when LBX is configured.
- `BILLING_WORKER_URGENT_CONCURRENCY=2`: urgent source slots, range 1–16.
- `BILLING_WORKER_NORMAL_CONCURRENCY=1`: normal source slots, range 1–16.
- `BILLING_WORKER_IO_TIMEOUT_SECONDS=60`: total source/cleanup budget; greater
  than the cleanup reserve and at most 240 seconds, leaving room for the lease
  margin and refusal retry within the five-minute urgent cadence.
- `BILLING_WORKER_SCAN_BATCH_SIZE=100`: local enrollment/repair batch, range 1–100.

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
one original point-proven candidate may bind; ambiguous/foreign/already-bound
candidates require review or more proof. Recovery preserves the original
operation, request/key/date, accepted history and hold. Known financial conflicts
need audited resolution; a deadline-only escalation can recover normally.

`external_create_deadline` uses the current fixed active financial recovery
window. Legacy rows without an active deadline use original unknown_since + 2h.
Only an explicit authenticated continuation after completed typed PROVEN_NOT_SENT
may start a new two-hour active window for that same command. UNKNOWN, GETs,
backoff and restart cannot extend the window or permit another financial CREATE.
PENDING and completed PROVEN_NOT_SENT are excluded from overdue UNKNOWN
escalation and authorize no background send.

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

`customer_inventory` uses fewer than 100 discovery rows and at most 20 relevant
candidates under one read budget. Capped, duplicate, unstable or partial results
are incomplete, never evidence of absence. A tariff is not product identity:
proposal_ai and brief_decoder can share one tariff only with separately proven
purchases, dedicated agreements and subscriptions. Other-product exclusion needs
original owner/legal/effective-term proof. A unique matching original
POSSIBLE_SEND/UNKNOWN candidate under its bound dedicated agreement, consistent
with any saved receipt, waits for GET-only recovery, including after deadline-only
review escalation. Inventory checks the remaining candidates and cannot bind it.

Proven competition records scoped customer-inventory:v1 evidence without
rebinding or renewing trust. For an unbound subscription command in
PENDING/PROVEN_NOT_SENT, it records `admission_blocked` and retries urgently while
preserving no-send history. The same transaction rotates all unsent-operation
fences so an earlier admission cannot claim a CREATE. Explicit continuation
repeats fresh admission and remains blocked while competition persists.
Competition involving other operation states or an existing binding opens
customer_inventory_conflict review.
Collected conflicts are applied together after
the product reads finish or exhaust their shared budget. A later timeout
preserves earlier timely conflict proof; unfinished scopes remain incomplete.
Fenced apply still rejects stale ownership or work. An incomplete inventory
retry is not evidence that inventory is conflict-free. Inventory success cannot
close known review.

## Optional webhook receiver and manual deployment

`POST /api/billing/lbx/webhook` is disabled by default:

- `LBX_WEBHOOK_ENABLED=false`: returns 404 before body processing or DB use.
- `LBX_WEBHOOK_AUTH_HEADER=`: verified credential header name when enabled.
- `LBX_WEBHOOK_AUTH_VALUE=`: entire exact shared-secret header value when enabled.

Keep the webhook secret in the protected API environment/secret manager,
separate from Server API credentials and the Widget signing secret. All Compose
API environments forward these settings. For worktree `repo:up`, root `.env` or
exported values populate private `.harness/runtime.env`; exported values take
precedence. The secret is excluded from public runtime metadata and web settings.

Enabling requires a valid LBX connection and credential configuration. The
receiver accepts exactly one matching credential header, compared in constant
time before body processing. Missing/duplicate/wrong credentials return 401.
Transport/correlation headers such as X-Request-ID and tracing headers cannot
carry the credential. No query-token, anonymous or guessed-signature fallback
exists.

The JSON limit is 65536 bytes for declared and streamed bodies (413).
Unsupported media type returns 415; malformed JSON, unsupported event or invalid
correlation returns 422. Rejections never echo payloads or headers.
Supported events are:

- `create_subscription`
- `change_subscription`
- `block_subscription`
- `new_charge_period`
- `close_subscription`
- `delete_subscription`

Only `event`, positive integer `parameters.subscription_id` and
`parameters.agreement_id`, and optional `parameters.user_id` are used.
Deployment determines account/contour;
proven local bindings determine user/product. Unknown, foreign or conflicting
correlation is acknowledged as ignored and creates no binding.

Known hints commit a redacted receipt and coalesced work before returning 200
with local `delivery_id` and `queued`/`ignored` outcome. The request performs no LBX
REST call and cannot change subscription/access facts. No raw body, credential,
contact or payment field is persisted. Identical payload hashes do not suppress
future events.

Receipts are `pending` until complete authoritative processing marks the covered
`enqueue_generation` values `processed`; later hints remain due. Incomplete reads
and crashes leave pending work retryable. `processed` means a complete reread was
applied, not proof of event-version visibility, payment or access. Polling remains
the correctness path; HTTP 500 is not assumed to cause provider redelivery.

### Test and production setup

The [official setup guide](https://docs.lbxbilling.ru/api/webhooks/set_webhooks/)
and [event examples](https://docs.lbxbilling.ru/api/webhooks/list_webhooks/)
document manual URL/token/event configuration. They do not establish this
account's actual authentication header/value format. No configuration API is
assumed.

1. Keep the receiver disabled while configuring the target LBX connection and
   secret. Use separate test/production secrets. Apply migrations and confirm
   healthy independent polling.
2. Test URL: authorized publicly reachable HTTPS test Portal origin plus
   /api/billing/lbx/webhook. Production URL: approved APP_PUBLIC_BASE_URL origin
   plus that path, through the contour-local Caddy /api/* proxy. Use neither
   Kernel/Resolver/Widget origins nor another contour.
3. In the correct LBX account, open Settings → Parameters → Webhooks → Add.
   Enter the URL, token from the secret manager and a nonsecret description.
   Select the six listed events. Repeat request may be enabled; correctness
   does not depend on redelivery. Save as part of the authorized integration check.
4. Verify actual credential transport through a privacy-controlled test delivery.
   Set LBX_WEBHOOK_AUTH_HEADER and LBX_WEBHOOK_AUTH_VALUE to the verified header
   and entire exact value, including any prefix. Avoid body/header logging at
   capture boundaries. If secure compatible delivery cannot be established,
   leave the receiver disabled.
5. After transport verification, enable the test API through its normal restart
   procedure and complete the checklist below. A synthetic POST proves only
   Portal handling. Production needs its own account/origin/secret verification
   before enablement. Keep one API replica and independent polling.

### Real enablement checklist and rollback

Keep DISABLED/POLLING-ONLY until the deployment owner verifies actual provider
authentication, correlation and delivery for that environment:

- Correct credentials are accepted; missing/wrong credentials are rejected
  before body processing without leaking credentials or payloads.
- All selected events correlate only to the proven local scope; unknown or
  conflicting correlation stays ignored.
- Receipt/work are durable before acknowledgement; subsequent worker GETs
  process hints safely across duplicate/reordered events and restart.
- Early/incomplete REST visibility converges through later reads, without an
  assumed provider delivery or visibility deadline.
- Lost/disabled delivery still converges through polling.

Rollback: set LBX_WEBHOOK_ENABLED=false, restart the API and confirm route 404.
Disable/delete the provider webhook when authorized. Keep BILLING_WORKER_ENABLED
true and confirm queue progress. Committed work survives disablement/restart;
never delete receipts/jobs or release holds as rollback. Rotate secrets through
the same verified procedure. For pending receipts, inspect their work ID,
generation, due time, lease and last_error_classification. There is no inbox-delete,
manual-replay or provider-configuration CLI.

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
Success JSON includes the operator principal. Exit 0 means the command completed,
not that payment or positive source proof was established. Exit 1 returns only
`detail.code`; invalid parser arguments exit 2.

- `inspect`: local read-only evidence; no source I/O, row changes or leases.
  Output includes original operations/fences, current subscription facts/trust,
  recent observation summaries, work and review IDs/digests. Work/review lists
  cap at 100 with truncation flags; observations contain the latest 20 records.
  No customer keys, raw requests, credentials or accepted amounts are exposed.
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
accepted_terms_changed_after_preparation, and customer_inventory_conflict on an
original bound subscription. All original bindings and fresh complete
owned original-term/prepaid proof must hold. It restores facts and linked state
without rebinding. Blocked/ended facts remain blocked/ended and held; terminal
revival has no override.

`bind-original` also requires `--operation-id` and `--expected-operation-fence`, with
no reconciliation expectations. Supported cases are financial_binding_conflict /
accepted_terms_changed_after_preparation on an unbound possible-send financial
operation, and customer_inventory_conflict on an original possible-send
subscription. Complete bounded discovery must prove exactly one original candidate,
even with a saved receipt. Saved request/correlation/accepted terms, original
agreement date and supported subscription lifecycle/policy must match. Binding
enrolls reconciliation without itself renewing trust.
An ended/closed original outcome may be resolved with complete matching proof;
it remains negative and held, with payment presentation refused.

The conflict evidence must retain original POSSIBLE_SEND/UNKNOWN state and send
fence; the same operation's deadline-review evidence may supply it. Missing
history or PENDING/PROVEN_NOT_SENT cannot be turned into send proof. Both commands
recheck current ownership, consent, case digest and expected fences. The audit
billing-operator-resolution:v1 records principal, reason/reference and proof
atomically with facts/binding, related-case resolution and scheduling. An identical
completed request by the same operator replays without writes/source calls;
a changed or stale repeat refuses.

Inventory review additionally requires fresh bounded customer discovery, point
ownership/effective-term proof and stable discovery membership, within the same
resolution read budget. The original subscription must be present. An unexplained
nonterminal competitor, incomplete reads or changed local purchase/review witnesses
refuse resolution. Other-product original subscriptions may be recognized while
their inventory reviews remain open. An unbound neighbor additionally requires
its preserved possible-send evidence, exact original request and a unique
candidate under its dedicated agreement; this does not bind or resolve that
neighbor. Unrelated reviews still refuse. Each purchase is resolved explicitly.
The shared writer rechecks all local witnesses under the user lock and records
`review-inventory:v1` proof in the atomic operator audit. A clean background
inventory still does not close a known review automatically.

Refusals include stale evidence, incomplete/capped/ambiguous discovery, foreign
or already-bound objects, unsupported policy, customer identity conflict,
unrelated open cases, terminal revival and changed accepted requests. Diagnose
billing_review_stale, billing_review_unrelated_cases, billing_review_proof_incomplete,
billing_review_terminal, purchase_history_unproven and ordinary source/busy errors;
do not bypass them. There is no release-terminal, force-release, arbitrary rebind,
commercial reacceptance, manual paid or quota command. Terminal revival overrides
remain deferred. Existing Step 7 proven-unsent automatic
release keeps its separate rule.

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

## Projection and access boundary

Consume subscription-reconciliation:v1 observations, original ownership/legal/
accepted provenance, commercial classification, last_authoritative_read_at and
projection_valid_until. subscription-trust-expiry:v1 supplies deterministic
source-expiry evidence. Incomplete attempts preserve only finite existing support;
known negative/conflicting facts supersede usability. Calendar precision stays
provider evidence, without an inferred UTC cycle or allowance identity.

Scopes have `primary_subscription_id=NULL` and observations keep
`resulting_access_revision` null. Step 9 owns primary selection, paid
grants/allowances, effective-access revisions and atomic outbox production;
it must attach earlier effective access deadlines to the existing scheduler.
Step 10 owns Kernel wire/invalidation delivery and coupled UTC calendar design.
Step 11 owns complete real paid-access/natural-renewal and launch acceptance.
