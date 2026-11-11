# ANY-709 billing runbook

Status: current operational reference for the ANY-709 implementation.

[ADR 0005](../architecture/decisions/0005-external-billing-boundary.md) points to
accepted contracts and the exact dated C1-C4 decisions in
[ANY-504](https://linear.app/paveldik/issue/ANY-504), and owns the accepted
1 November point-resource identity decision. Implementation results,
review fixes and acceptance evidence belong to
[ANY-709](https://linear.app/paveldik/issue/ANY-709).
The [implementation plan and delivery record](../exec-plans/completed/ANY-709-implementation-plan.md)
tracks completed milestones and review dispositions, with the original proposal
linked as historical input.
This guide supplies commands and recovery procedures, not additional exceptions.

## Connection and deployment

Set `LBX_BASE_URL` to the provider HTTP(S) origin only, plus
`LBX_SERVER_USERNAME` and `LBX_SERVER_PASSWORD` in the protected environment.
Production requires HTTPS. `LBX_WIDGET_SIGNING_SECRET` is additionally required
for the Widget; `LBX_SELLER_ORGANIZATION_ID` is required for purchases. Missing
Widget/seller settings do not block source reads or product linking. All-empty
billing configuration leaves billing unavailable without breaking identity.
Invalid partial configuration produces a safe billing error, with no startup
provider call or automatic publication.

Server API, Client API and SDK paths are `/api/rest/v1`, `/api/rest/v1/client`
and `/lbxwidget.js` on that same validated origin. Do not append them to the
configured origin. Never put credentials in browser settings or CLI arguments.
The normal harness forwards `.env`/process settings to Compose through protected
`.harness/runtime.env`. Matching dotenv quotes/escapes preserve literal secret
bytes; process environment wins. Invalid quoting/control characters fail safely.
Do not print `.env`, the runtime file, `docker compose config` or credentials.

Configure `LBX_CURRENCY_ID` for the supported `LBX_CURRENCY=RUB`, major units,
scale 2 contract. Numeric ID 1 is test configuration, not a universal currency
constant. Current offer selection uses the fixed `Europe/Moscow` price calendar;
there is no `LBX_BILLING_TIMEZONE` setting. Provider calendar/sentinel dates never
establish paid UTC intervals. Unsupported discounts, credit or effective-price
facts cannot be filled with guessed zero/false values.

With `BACKEND_CONSUMERS` configured, Step 11 selects each product's manifest
origin and outgoing credential from its registered backend entry. See the
[source configuration](../contracts/product-backend-api/README.md#implemented-step-11-technical-sources-and-history).
Legacy `KERNEL_BASE_URL`/`KERNEL_SERVICE_TOKEN` still serve technical reads when
the registry is empty and remain the Step 7 invalidation sender's connection
until Step 13. Keep them aligned with the Kernel entry when delivery is enabled.
They do not select another registered backend's manifest. Optional
`KERNEL_MOCK_ENABLED=1` with explicit matching `KERNEL_MOCK_TOKEN` and
`KERNEL_SERVICE_TOKEN` starts the development technical mock at
`http://kernel-mock:8091`; it needs no billing mounts, publisher UID or approval
files. Kernel evidence stays SIMULATED, independently of LBX CONFIGURED_SOURCE.
Ordinary HTTPS connections may be configured in production; CONFIGURED_SOURCE
is not producer conformance or launch approval. Mock mode remains development/
test only, including after changing its URL. It also keeps the registered
`platform-kernel` consumer SIMULATED; the harness mock's token must match that
entry's outgoing credential when it supplies manifest reads. ANY-711's delivered
producer/contract evidence does not approve current deployment conformance or
commercial enablement.

Test and production deployments use the same integration code with separate
DBs, origins, credentials, sellers and provider objects. Do not repoint a
populated test DB to production or copy its customer IDs. Production uses the
normal Compose file plus `docker-compose.prod.yml` and its own launch gates.

## Startup and restart

From the repository root, use the intended environment and root `.venv`:

```bash
export PATH="$PWD/.venv/bin:$PATH"
# Changes the configured application DB; check retired revisions below first:
npm run migrate:api
# Starts/reuses this worktree's containers and refreshes protected configuration:
npm run repo:up -- --reuse
# Host-process alternative, in separate terminals instead of application containers:
npm run dev:api
npm run dev:web
```

The normal harness also runs its migrate service. Application migrations do not
use pytest's disposable `_tests` database. After a code change rebuild the
application; a plain restart does not rebuild images or refresh environment.
Use `repo:up -- --reuse` after changing `.env`.

For an existing harness, this helper resolves its exact Compose project/files
and protected environment without printing them:

```bash
portal_compose() {
  .venv/bin/python - "$@" <<'PYCOMPOSE'
import os
import sys
from scripts import repo
command = [*repo.compose_command(repo.load_runtime()), *sys.argv[1:]]
os.execvpe(command[0], command, os.environ)
PYCOMPOSE
}
portal_compose restart api web
portal_compose up -d --build api web
```

### Consolidated ANY-709 migration

ANY-709 consolidated its migrations into `20261029_0003`, following
`20261001_0002`. It retains all operations from the former branch-local
`20261026_0003` / `0004` / `0005` / `20261027_0006` chain and the later
`20261028_0004` active financial recovery window, including indexes, constraints,
triggers, operation-account backfill and purchase holds. Within the consolidated
revision, upgrade preserves the old `0003` then `0004` operation order;
downgrade reverses those operations.
The consolidation preserved that baseline's schema, legal seed, historical
consent and accepted-purchase meaning. The
[current schema reference](../architecture/payment-portal-data-model.md#physical-baseline)
owns the subsequent forward chain and its current head.
The retained transitions below align old ANY-709 branch labels at `0003` before
the normal forward upgrade; they do not make `0003` the current head.

- Fresh databases and databases at `20261001_0002` use the normal migration
  command above. Conflicting old identities or held scopes abort the transaction;
  the migration never chooses, deletes or relabels those records.
- A database at `20261029_0003`, with the nullable active recovery column and
  its complete expected schema, runs normal `upgrade head` to apply all subsequent
  revisions. The paid migration refuses incompatible history without repairing it.
- A **pre-consolidation** database at `20261027_0003` may lack
  `billing_work_items.active_recovery_deadline_at`. The new distinct revision ID
  makes `upgrade head` refuse this retired label instead of silently skipping
  the missing column. Finish its
  normal upgrade to `20261028_0004` using the old checkout `afb46c5` before
  switching to this checkout. Do not stamp an unapplied column as complete.
- For an old fully applied `20261028_0004`, stop concurrent migration processes,
  retain a protected backup and compare all columns/types/defaults, constraints,
  indexes, functions and triggers with a fresh final `20261029_0003` database.
  After an exact match, use a guarded transaction that requires the single old
  `0004` version row to change only `alembic_version` to `20261029_0003`.
  Preserve/fingerprint all application rows across that label-only transition,
  then run normal `upgrade head` through the current head. Never replay the
  consolidated DDL on that database.
- A fully upgraded database at retired `20261027_0006` has the pre-window schema, but
  its old label is not in the new graph. Verify that its columns, constraints,
  indexes, functions and triggers match the pre-window `0003` in checkout
  `afb46c5`, retain a protected backup, then change only its `alembic_version` label to
  `20261027_0003` in a guarded transaction. Preserve all application rows and
  run old `upgrade head` in `afb46c5` to reach `20261028_0004`. Then perform the
  final verified label transition above. Never rerun the consolidated DDL over
  that schema.
- A database still at retired `20261026_0003`, `0004` or `0005` must first run
  the original chain to `20261027_0006` using the pre-consolidation checkout
  (`db63966`) and the same protected deployment/database configuration. Then
  follow the `0006` route above, including the old upgrade to `0004`, before the
  final label transition and switch to this checkout. Do not stamp over unapplied operations.
  This is an operator action, not an automatic compatibility rewrite.

Fresh/main databases use the ordinary migration command above. A matching
current head is a no-op. Never replay consolidated DDL over an already-upgraded
schema or stamp over missing operations. Recovery must retain matching binaries,
constraints and data; a UI failure does not authorize deleting history/holds.

## CLI execution and product linking

One CLI supplies `dry-run`, `publish` and `query`. It records the actual OS UID
as `os-euid:<uid>`; there is no actor override or UID allowlist. Authorization
uses existing shell, secret, file and database permissions.
All writing operator processes share one private local lock inode and execution
UID. Containers mount `.harness/operator` at `/run/payments-portal`; production
uses an app-owned private lock volume. A host CLI must use the corresponding
host path. Do not alternate root-created locks and an unprivileged operator.
`query` is DB-only and requires no lock/source credentials.

In the already configured host environment, provision the trusted lock directory
for that operator and set `MAPPING_OPERATOR_LOCK_FILE` to its absolute path
(e.g. `$PWD/.harness/operator/operator.lock` for the normal harness). Then:

```bash
PYTHONPATH=apps/api .venv/bin/python -m app.cli.commercial_mappings dry-run \
  --product-id proposal_ai --tariff-id 32 --tariff-service-id 1 --period-id 1 \
  --metric-key proposal_ai.generations --unit generation --allowance-quantity "$APPROVED_ALLOWANCE_QUANTITY"
PYTHONPATH=apps/api .venv/bin/python -m app.cli.commercial_mappings publish \
  --product-id proposal_ai --tariff-id 32 --tariff-service-id 1 --period-id 1 \
  --metric-key proposal_ai.generations --unit generation --allowance-quantity "$APPROVED_ALLOWANCE_QUANTITY" \
  --expected-previous-revision 0
PYTHONPATH=apps/api .venv/bin/python -m app.cli.commercial_mappings query \
  --product-id proposal_ai
```

The IDs are manual test examples, never business defaults. Period 1 is a period
ID, not association 82 or price-row 288. Quantity defaults to one commercial
service subject to source bounds; it is not a Kernel allowance. Non-unit
connection charges without proven quantity semantics remain unsupported.

ANY-766 Step 3 requires all three technical flags for `dry-run` and `publish`.
The operator supplies an owner-approved integer `APPROVED_ALLOWANCE_QUANTITY`;
there is no launch default. Zero is a finite zero allowance. Booleans, floats,
negative values and values above 2^53−1 are rejected. `--quantity` still selects
LBX commercial service quantity; it never determines the technical allowance.
The exact product/metric/unit must be enabled in its freshly read configured
source manifest (Kernel is the first source). The development Kernel mock cannot
publish configured technical terms.
Ordinary production commercial flags remain disabled until sales approval;
these examples authorize neither real associations nor enablement.

ANY-766 Step 11 metered publications use `product-link-v4` in the existing
immutable mapping table.
Its selected identity includes the fixed-per-cycle technical offer, LBX selection
and source provenance. Fresh selected-offer LBX reads, OS principal, product CAS,
history and uncertain-commit recovery remain required. Unrelated manifest/version
changes do not create a new selected identity. New buyer acceptance pins
`purchased-technical-terms:v3` inside `accepted-purchase:v4`, including explicit
source/backend owner, mapping revision/digest, account/selection, commercial
fingerprint and neutral manifest evidence.
The complete source/audit digests remain separate from `confirmation_digest()`.
Review shows quantity/unit before consent; changed selected terms require a new
review. Accepted purchases and their renewal quantities never rebind to a newer
mapping. Existing v1/v2 links and purchases, SIMULATED terms and exact historical
v2 full-digest replay remain readable without rewriting stored documents.
The [Step 11 source/history guide](../contracts/product-backend-api/README.md#implemented-step-11-technical-sources-and-history)
defines registry endpoint/credential selection, source ownership refusal and the
unchanged historical serializers. Existing v3 links, terms v2 and purchases v3
remain readable; their missing owner resolves to Kernel only in memory. Metered
publication refuses changing a retained product's source/backend owner. The
unmetered Kernel development path retains its old format. No migration is needed,
but readers predating Step 11 cannot read newly written formats even at the same
migration head; exclude those binaries from rollback/install combinations.
Legacy links without a published quantity cannot start a new production purchase;
original accepted-operation replay/recovery remains independent of new-sale terms.
ANY-766 Step 5 implements configured-source allowance derivation and snapshot V2
serving; [billing operations](billing-background-operations.md#any-766-step-5--production-allowances-and-snapshot-serving)
defines their provenance and serving rules.

For the configured harness, use its shared lock and current host UID:

```bash
portal_operator() {
  portal_compose exec -T --user "$(id -u):$(id -g)" -e PYTHONPATH=apps/api \
    api python -m app.cli.commercial_mappings "$@"
}
portal_operator query --product-id proposal_ai
portal_operator dry-run --product-id proposal_ai --tariff-id 32 --tariff-service-id 1 --period-id 1 \
  --metric-key proposal_ai.generations --unit generation --allowance-quantity "$APPROVED_ALLOWANCE_QUANTITY"
portal_operator publish --product-id proposal_ai --tariff-id 32 --tariff-service-id 1 --period-id 1 \
  --metric-key proposal_ai.generations --unit generation --allowance-quantity "$APPROVED_ALLOWANCE_QUANTITY" \
  --expected-previous-revision 0
```

Use the returned **product** `revision_number` for CAS, including offer retargets;
no current head means expected revision 0. `offer_revision_number` is separate
history numbering. `query --offer-id <returned-billing-offer-id> --revision
<offer_revision_number>` reads exact immutable history offline. Equal link
identities are no-ops across ordinary price changes; publication still requires
live checks. One selected offer has one current product owner; conflicting heads
refuse new admission with `mapping_offer_product_conflict`. Retarget explicitly
through normal publication; never rewrite dependent purchases/consent/history.

### Connection scope and rollout

Fresh scope depends on normalized provider origin plus deployment tenant/region,
not credentials. For a recognized legacy credential-derived head, keep its old
username for one authorized identical `publish` after the current migration.
That records proven origin on the mutable head without replacing immutable
scope/FKs; later credential rotation retains it. A lost old username without
proven origin cannot be reconstructed from its hash. Multiple proven scopes or
unproven/conflicting legacy heads require diagnosis, never guessed aliases.
Account-only opening refuses a competing reservation until legacy provenance is
bound. Customer-only proven scope also governs first product publication.

All writing API/CLI processes must use the shared origin-lock protocol before
rollout; older binaries do not participate. See the exact lock order in the
[concurrency and preparation boundary](#concurrency-and-preparation-boundary). Caller timeouts return temporary
`503 billing_busy` for customer/purchase contention, or `mapping_storage_busy`
for publication, without renewing deadlines. Exact accepted-request replay stays
local. READ COMMITTED is required; provider HTTP stays outside transactions.

Inspect retained scopes read-only before rollout:

```sql
SELECT provider_origin, count(DISTINCT external_billing_account_id) AS account_count
FROM (
    SELECT provider_origin, external_billing_account_id
    FROM commercial_product_heads WHERE provider_origin IS NOT NULL
    UNION
    SELECT provider_origin, external_billing_account_id
    FROM external_billing_customers WHERE provider_origin IS NOT NULL
) AS origin_scopes
GROUP BY provider_origin
HAVING count(DISTINCT external_billing_account_id) > 1;
```

Returned origins need evidence-based reconciliation of retained bindings and
possible-send history. This query cannot prove NULL-origin legacy membership.
The lock prevents new conflicting admissions; it does not repair old ambiguity.

## Human account-Widget checkpoint (Step 2)

Sign in with verified email and explicitly open billing in the cabinet.
Account-only `POST /api/billing/widget-bootstrap` accepts `{}` and no browser
provider IDs/flags. Registration, login and ordinary GETs create no LBX object.
The account opening needs no offer, product link, seller or subscription.
Optional first name, surname and patronymic remain independent; no fake names
or provider password repair is performed.

The shared customer ensure retains one local slot/operation/original key across
products and openings. A known receipt/canonical `user_id` uses paired point
proof with the unchanged original `outer_id`, never another CREATE. Email is
only candidate search, not ownership proof. The Portal never PATCHes that key.
The LBX point endpoint selects the requested customer; Portal does not impose a
separate equality check between the response ID and the ID in the URL. The shared
customer flow checks the decoded proof against the retained binding and original
key.

Customer decision C3 permits bounded discover/create/recover with backoff inside
a nonrenewable opening budget. A later claim requires fresh successful complete
empty discovery and completion/expiry of the previous active-send lease. Failed
reads never prove absence. This C3 retry policy applies only before the durable
deadline pause. Under the [2026-11-09 decision](../architecture/decisions/0005-external-billing-boundary.md#accepted-unknown-recovery-and-lifecycle-metadata-decisions---2026-11-09),
later explicit openings of a `paused` operation are GET-only: an empty listing
or expired send lease cannot authorize CREATE. See the
[two-hour recovery procedure](billing-background-operations.md#unknown-create-after-two-hours).
Email-uniqueness rejection makes the remainder of
that opening GET-only; authorization/permanent errors stop. **Remote duplicate
prevention depends on LBX enforcing email uniqueness across repeated/concurrent
creates.** Local fencing and an unchanged key do not prove an earlier POST had
no effect; this is not native provider idempotency or unconditional exactly-once.

Unresolved discovery ambiguity, an original-key mismatch before binding, a
conflict with the retained customer binding, Client scope mismatch or provider-ID
collision remains blocking across openings. Shorter listings cannot settle it;
merely closing a case does not clear binding
conflict. Only a separately evidenced original-key mismatch for the same proven
ID permits read-only recovery of that original ID/key pair, under the current
fence and with no other blocking cause. Legacy untyped conflicts are not guessed.
No replacement customer/key, force-bind or SQL state reset is part of recovery.
Customer sends, final Widget admission and new financial claims retain strict
locked checks; a new conflict during source I/O prevents a new financial POST.

A successful open checks Client readiness and current session/fence before
returning a fresh no-store type-7 JWT for the canonical user ID. Closing,
refreshing, switching purchase/user or logout disposes the local SDK host.
That does not revoke a copied provider token; flags are presentation, not ACLs.
See [Widget security](../SECURITY.md#account-widget-credentials-any-709-step-2).

## Customer diagnosis CLI

```bash
.venv/bin/python scripts/repo.py billing-customer diagnose --user-id <PORTAL_USER_UUID>
```

Run from this deployment's trusted shell with its normal DB/LBX configuration.
The wrapper does not start containers, migrate or edit `.env`. Inside an already
configured API container use `python -m app.cli.billing_customers diagnose
--user-id <PORTAL_USER_UUID>`. A direct host module invocation also requires
`PYTHONPATH=apps/api` and the intended `DATABASE_URL`/instance settings.

Diagnosis uses read-only local transactions, then provider GETs with
`show_passwords: false`; at most five candidates receive point reads. Output
contains safe state, candidate IDs and allowlisted HTTP/LBX response facts,
never email, outer key, tokens, arbitrary provider text or raw payloads.
Historical CREATE response facts explain an incident but do not prove absence
or authorize another CREATE. No `--apply`, supplied-customer-ID or reset exists.

Exit 0 means `binding_verified` or `not_provisioned`; the latter needs normal
explicit opening. Exit 2 covers actionable unbound, email/identity/connection
conflict, ambiguity, unknown outcome, unverified email or source failure. Inspect
the safe `diagnosis`/`next_action`, resolve its cause and rerun normal diagnosis/
opening; do not force an identity. Exit 1 is configuration, user-scope or DB error.
Client readiness/Widget rendering is not verified by this command.

## Purchase API and financial recovery (Step 3)

The normal UI reviews/accepts on product detail and opens payment in the cabinet.
For API inspection use the authenticated verified owner's session:

1. `POST /api/purchases/review` with `{"product_id":"<enabled product>"}`
   returns exact decimal terms, `revision_id`, `expected_fingerprint` and legal
   document versions/text hashes. It creates no consent or provider object.
2. `POST /api/purchase-intents` with a stable `Idempotency-Key`, reviewed
   product/revision/fingerprint and `documents` (`document_version_id`,
   `acceptance_text_hash`) rereads sources and atomically pins acceptance and
   one user/product hold. Do not submit provider IDs, money or permission flags.
   Same key/meaning returns the original purchase; another key cannot bypass its
   hold. `terms_changed` requires fresh review and explicit consent.
3. Explicit `POST /api/purchase-intents/<id>/advance` ensures the shared customer,
   dedicated non-offer agreement for the configured seller, and selected
   tariff/period/service/quantity. It requests balance-gated activation, omitting
   manual/demo activation and subscription start dates. Original accepted terms
   and customer-wide same-tariff inventory are checked before **each** new
   financial send, including subscription continuation after proven no-send.
   Incomplete inventory stays pending. A competitor blocks unsent admission while
   preserving PENDING/PROVEN_NOT_SENT evidence and explicit continuation after
   correction; it never manufactures a permanent financial review before send.
   Another permanently bound Portal purchase remains its own product even during
   review; its leased reconciliation handles its own commercial conflict.
   If its subscription send is still unresolved, the new purchase waits with its
   existing hold and no financial send. Resume it after the original purchase
   completes. An ambiguous candidate or failed owner/seller/terms proof cannot
   authorize a send. Possible-send and canonical inventory conflicts require the
   audited original operator path after correction.
   Its local snapshot uses the existing bounded user-row lock shared by purchase
   transitions; provider HTTP runs after that transaction closes.
   The number of other held Portal purchases is not a separate admission quota.
4. `GET /api/purchase-intents/current?product_id=<product>` and
   `GET /api/purchase-intents/<id>` read owned local history without CREATE or
   catalog calls. Authenticated `GET /api/purchase-intents` lists held purchases
   with UUID cursor pagination (default 50, maximum 100).
5. `POST /api/billing/widget-bootstrap` with `{"purchase_intent_id":"<id>"}`
   requires fresh original customer/agreement/seller and effective subscription
   proof. The payment response identifies the proven target agreement/seller;
   only payments are enabled among action flags. Empty-body account viewing
   stays independent. The customer-wide SDK has no product/agreement ACL or
   automatic selection: the user selects the displayed intended agreement.

The backend owns Widget presentation, payment target and action flags. The
frontend consumes that successful typed response without rechecking those
business decisions. URL/HTML safety, iframe message source/origin and stale
session checks retain their separate browser responsibilities.

Point proof uses canonical subscription/agreement/customer IDs, accepted seller,
tariff/period, fixed-service effective price and quantity/total. Today's catalog
price, price-row/association IDs and mutable subscription `outer_id` are not
subscription authority. Waiting NULL/1970/3000 calendar values are not paid dates.
A nonzero connection charge without explicit effective readback stays pending.
A newly linked subscription has zero positive trust: a proved source negative
is `blocked`, otherwise financial status is `unverified`. Preparation creates no
access primary, grant, allowance or Kernel call. ANY-765 derives paid access
separately through shared authoritative reconciliation and complete inventory.

### Recovery and safe continuation

```bash
.venv/bin/python scripts/repo.py billing-purchase inspect --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid>
.venv/bin/python scripts/repo.py billing-purchase recover --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid>
```

`inspect` is local/read-only. `recover` performs provider GETs and persists only
fenced point-proven bindings/review state; it is not a read-only SQL action.
It never sends CREATE, mints JWT, releases scope or grants access. Use request
IDs and safe stored HTTP/LBX facts; do not publish raw responses or credentials.

Possible-send commits immutable request/key, fence, first `unknown_since + 2h`
and coalesced work before financial POST. A timeout, 500/error, malformed success,
crash, lost commit acknowledgement, empty discovery or expiry never permits
another financial CREATE. UNKNOWN is GET-only and keeps its hold. Overdue work
enters review; point proof may resolve deadline escalation, not a known conflict.
Advance, worker and operator share `composition/purchase_recovery.py`: saved
original command/key, possible-send history, original dedicated agreement and
fresh ownership/applicable effective terms must be proved before first binding.
The operator collects each required point once and reuses the normalized proof
for the existing authorization/bind/audit transaction.

A proved original ended subscription or closed agreement remains recoverable.
First binding records the immutable relationship and known negative in the same
transaction, with no positive trust or payment admission. A closed agreement is
retained as `prepared-agreement:v1` product-scoped evidence; both advance and the
financial claim reject a new subscription send for that historical closure.
A legitimate waiting subscription needs no fictitious paid cycle dates to prove
its original creation. Already bound financial recovery is a no-op, including
bound operations placed in review; a concurrent first binder makes the losing
candidate proof stale and its caller uses claimed subscription reconciliation.

Only completed typed `LbxCreateNotSent` evidence permits a later explicit advance
of the same operation/request with a fresh fence. Its fixed active +2h deadline
is stored on `billing_work_items.active_recovery_deadline_at`; the original
operation history is immutable. Existing NULL work deadlines fall back to the
original deadline. GETs/scheduling do not extend either window; no retry occurs
within that advance. Do not roll back to an older binary while such a send is
unresolved. Caller cancellation does not create no-send proof or clear a lease.

A temporary/incomplete payment recheck refuses that credential while retaining
linked preparation for later fresh proof. Known owner/seller/term conflicts stay
in review. Manage uses original accepted history, independently of current link/
price. Linked unpaid purchases hold scope without TTL. Automatic release occurs
only for changed accepted terms while **all** financial operations are provably
unsent under send-claim locks. Other release needs trustworthy audited evidence;
there is no force-release/grant command or absence inference from zero results.

Final payment admission rechecks session, ownership, operation fences and the
canonical subscription under the same locks. An ENDED fact committed after
source readback refuses payment opening; a healthy reread or financial block
alone does not invalidate fresh payment proof. Account-only viewing remains
independent of purchase lifecycle.

## Browser operation and diagnostics

Prepared product detail links to `/account?purchase=<id>#billing`. The deep link
selects an owned purchase but never opens payment automatically. One shared
cabinet Widget serves account/payment views; multiple purchases need explicit
selection. Owned inventory remains available independently of source catalog.
Refresh billing disposes the old host, rechecks the same purchase and opens a
fresh Widget. It creates no subscription/payment; the provider may require
selecting the intended agreement again. There is no supported payment-completed
SDK callback and no Portal refresh timer that interrupts checkout.

Live catalog/review/confirm/advance/bootstrap requests have a 130-second browser
deadline covering body consumption; identity/local purchase GETs use five
seconds. A lost confirm/advance reply triggers one local inspection, retaining
its original key/purchase; no POST repeats automatically. Pending/error UI keeps
a safe request ID. Local status is not an LBX refresh or paid verification.
ANY-715 now supplies persisted observation/reconciliation facts and operator
diagnostics; it does not add a new public billing-status UI contract. See the
[billing operations guide](billing-background-operations.md).

SDK `render()` is not readiness. The isolated host waits up to 20 seconds for
`lbx-widget` READY from the exact nested window at the configured provider origin.
Failure removes the host and shows its safe request ID; successful READY stops
the loading timer. Correlate `billing_widget_load_failed` with server bootstrap
logs. Never weaken CSP/sandbox or infer payment/access from READY/browser return.

For DB inspection use the intended contour's read-only SQL session. Example:

```sql
SELECT customer_id, external_billing_account_id, provider_origin,
       provider_customer_id, binding_state
FROM external_billing_customers ORDER BY created_at;
SELECT p.purchase_intent_id, p.product_id, p.state, p.mapping_revision_id,
       (h.purchase_intent_id IS NOT NULL) AS held
FROM purchase_intents p
LEFT JOIN billing_purchase_scope_holds h ON h.purchase_intent_id = p.purchase_intent_id;
SELECT o.create_operation_id, o.operation_kind, o.operation_state,
       o.bound_external_object_id, o.send_fence,
       o.unknown_since, o.unknown_recovery_deadline_at,
       COALESCE(w.active_recovery_deadline_at, o.unknown_recovery_deadline_at) AS active_deadline
FROM external_create_operations o
LEFT JOIN billing_work_items w ON w.scope_reference = o.create_operation_id::text
  AND w.work_kind = 'external_create_recovery';
SELECT reason_code, scope_reference, case_state FROM manual_review_cases;
```

Inspect selected mapping/history with operator `query`. Customer-only opening
has no artificial purchase; confirmation owns one hold/consent; preparation owns
one dedicated agreement/subscription. Repeated opens/advance/Manage must retain
these identities. Never delete/relabel holds, receipts, reviews or accepted pins
to recover a UI or provider failure.

## Concurrency and preparation boundary

Purchase and background recovery share the same ownership and send-authority
transitions. Reuse these owners when changing either path:

- New customer reservation, purchase acceptance and origin-backed publication
  share the tenant/region/normalized-origin transaction advisory lock.
  Applicable order: user -> origin -> resolved-account product -> offer/head/
  legal/customer rows. Purchase acceptance takes origin **before** product;
  publication resolves scope under origin. See
  [purchase admission](../../apps/api/app/domains/purchases/admission.py),
  [customer scope](../../apps/api/app/domains/billing/customer_scope.py) and
  [link publication](../../apps/api/app/domains/catalog/link_publication.py).
- New financial claims use user -> owned purchase/hold -> financial operations
  ordered by kind -> customer -> customer-create operation, then apply strict
  current customer review checks before possible-send commit. A conflict during
  inventory/source I/O prevents a new claim. Customer-only writers never wait on
  purchase/user locks after acquiring customer rows. See
  [financial claims](../../apps/api/app/domains/purchases/financial.py) and
  [customer policies](../../apps/api/app/domains/billing/customer_reviews.py).
  Result/recovery transactions keep their existing owner functions/fences;
  provider HTTP never holds those transactions or shares a Session across threads.
- Canonical `ExternalCreateOperationState` includes `pending`, `possible_send`,
  `unknown`, `proven_not_sent`, `bound`, `manual_review`. Identity is permanent
  per customer or financial intent/kind. Scope hold is `(user_id, product_id)`.
  Keep original-key cause evidence, narrow read recovery, strict final/send
  admission, all distinct review causes and immutable accepted history together.
- `app.composition.billing.recover_customer` and
  `app.composition.purchases.recover_financial` perform GET-only recovery;
  customer escalation retains `escalate_overdue_customers`. Financial escalation
  uses durable `external_create_deadline` claim/apply through
  `domains/billing/background_recovery.py`; the unused financial scanner/query
  are removed. Reuse coalesced `external_create_recovery` work and active
  deadlines, retaining source/recovery capacity separation. The embedded GET-only worker has isolated normal/urgent
  capacity; see [background operations](billing-background-operations.md).
- `prepared-subscription:v1` observations are `preparation_only` /
  `not_paid_verified` or `source_negative`, with `paid_verified=false`; no
  positive trust is extended. They contain redacted original-proof evidence.
  First-binding persistence cannot rewrite an existing canonical subscription.
  Shared claimed reconciliation owns ongoing lifecycle and trust. Payment
  Widget, already-bound advance, worker and operator reconciliation acquire the
  subscription lease before point reads and apply through the same fenced
  transaction. Repeated opens do not rebind financial operations or append
  preparation observations. ANY-765 adds committed paid state and authenticated
  cabinet reads. ANY-766 now implements snapshot V2 and invalidation delivery;
  cabinet usage remains pending. Preparation grants no paid access.
- Payment presentation requires a committed complete identity/commercial match,
  supported nonterminal lifecycle and final local session/customer/purchase
  admission after Client readiness. Waiting/unpaid and financially blocked
  subscriptions can be payable. Missing paid-cycle calendar dates do not block
  payment when identity, material terms and nonterminal lifecycle are proven;
  they still prevent positive trust renewal. Unknown agreement closure remains
  non-payable even when its subscription's block is proven. Incomplete identity/commercial or
  terminal proof cannot return payment credentials; account-only Widget remains independent. Lease contention
  returns retryable `purchase_pending`, without unclaimed source reads.
- Bound HTTP reconciliation keeps the source budget separate from short DB
  apply, preserving a timely negative when later policy I/O expires. Every
  source call and final credential admission still check the absolute deadline.
  HTTP/operator reads coalesce follow-up work without finishing another queue
  owner's claim; inventory-origin observations cannot finish a customer job.
- Customer identity conflicts atomically restrict all linked subscriptions;
  financial-operation conflicts restrict only their purchase. Both invalidate
  in-flight reconciliation leases without rewriting source timestamps/history,
  so restoration cannot make an earlier ACTIVE proof valid again.

## Authenticated cabinet paid-access read

`GET /api/paid-access` requires the current deployment's active authenticated
session and verified email. It reads only local PostgreSQL state, without LBX,
Kernel, Widget bootstrap or source-admission resources. Both success and refusal
responses use `Cache-Control: no-store`. Identity may update session last-seen;
the paid read does not write billing state, renew trust or repair deadlines.

The API lifespan reserves two PostgreSQL connections (no overflow) and two
framework worker slots for this read, independently of new-purchase and source
work. Up to eight further reads may wait; excess requests receive retryable
`503 paid_access_busy`. PostgreSQL lock/statement waits are bounded at 2/10
seconds and also return `paid_access_busy`; other DB failures retain the ordinary
failure boundary. Include these two connections per API process in deployment connection
budgets. Cancelled HTTP waiters retain their DB task/slot until completion;
shutdown drains those tasks before disposing the pool and reports incomplete
cleanup rather than closing underneath a running read.

The shared user lock keeps the committed revision, complete grants/allowances,
provenance and deadline consistent with concurrent writers. An unprocessed
effective deadline at or before the sampled database time returns `503` with
`paid_access_deadline_pending`; it never filters expired tuples under an unchanged
revision. The existing local worker must commit the reduction before reads resume.

The cabinet reads this endpoint independently of held-purchase listing and
billing Widget availability. It refreshes explicitly, every 30 seconds while
visible, after visibility returns and after Widget closure. These are local reads,
not payment confirmation. Session changes/unmount discard late responses and
stop polling; the displayed result expires conservatively using server duration
and the browser's monotonic clock.

Per-product confirmed access, fresh authoritative absence and unavailable evidence
remain distinct. Implicit revision zero with no product evidence is confirmed
empty; unavailable reads are never presented as empty. Product evidence is bounded
to 100 entries with `evidence_complete=false` when truncated; committed grants and
allowances are not truncated. Technical terms retain their `SIMULATED` or
`CONFIGURED_SOURCE` provenance; legacy purchases without terms stay unknown.
Actual usage and remaining quota remain unavailable. Production cannot derive
simulated metering; this read does not implement Kernel enforcement or delivery.

## Verification commands

Use synthetic transport fixtures and the isolated test DB for automated checks;
never run API tests against the application DB or induce live lost writes.
From the configured repository environment:

```bash
npm run docs:check
npm run generate:check
npm run architecture:check
npm run check:fast
# Start only this worktree's disposable-test PostgreSQL server when needed:
python scripts/repo.py test-db up
npm run check
# Stop only the server started solely for these tests:
python scripts/repo.py test-db stop
# With an isolated browser harness configured:
npm run test:e2e -- any709-purchase.spec.ts
```

These are rerun commands, not recorded PASS. Human verification uses the intended
stand and the same owned customer/purchase/agreement across reload, two tabs,
Manage, refresh and logout. Actual provider payment must be an explicit human
action; do not repeat a payment to check refresh/readiness. Record outcomes,
limits, independent review and the tested SHA in ANY-709. Legal source remains
draft; neither Widget/payment nor a green test run grants paid access or launch.
