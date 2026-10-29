# ANY-709 billing runbook

Status: IMPLEMENTED_AND_TESTED; owner test-payment and SDK-readiness QA complete;
independent final review pending. Ordinary customer viewing,
accepted purchase preparation and the selected-purchase cabinet Widget are
implemented. The current migration is `20261029_0003_normal_billing`.
The owner completed YooKassa payment on the intended agreement; see the
[recorded result](#owner-payment-result-and-refreshing-the-widget). The
[current acceptance ledger](../exec-plans/completed/ANY-709-implementation-plan.md#current-acceptance-and-final-review)
owns current outcomes. Historical authoring NOT_RUN entries below are explicitly
checkpoint evidence, not the current acceptance status. Paid access and launch
remain later program steps; independent review is not replaced by author QA.

## Connection and deployment

Server API reads and product linking require only `LBX_BASE_URL` (HTTP(S)
origin only), `LBX_SERVER_USERNAME` and `LBX_SERVER_PASSWORD` in the configured
environment or untracked `.env`. Use production HTTPS. `LBX_WIDGET_SIGNING_SECRET`
is a separate account-Widget requirement; `LBX_SELLER_ORGANIZATION_ID` is
an explicit purchase requirement. Missing signing/seller values do not gate GETs or
linking. Server API requests append
`/api/rest/v1` exactly once; Client API/SDK paths are
`/api/rest/v1/client` and `/lbxwidget.js` on the same validated origin. Never put
these secrets in browser configuration, CLI arguments or checked-in files.

All-empty connection settings leave billing unavailable. Partial/invalid
connection settings produce safe billing errors; they do not prevent identity
startup. There is no startup provider call or automatic link publication.
The seller is deployment configuration; catalog reads do not query organizations.
Each new purchase agreement must prove its accepted configured seller.

LBX support directly confirmed that both services `prices[]` and the dedicated
service-prices GET return historical and future prices, and price start dates
take effect inclusively in Moscow. The integration uses the fixed IANA calendar
`Europe/Moscow`; no manual timezone setting is needed. One Moscow evaluation
date is captured for both complete control reads. Each method selects the
selected period's latest start date on or before that date; the selected period,
start date and all monetary values must agree. The dedicated method supplies
the final amount and `price_id`. Multiple distinct historical/future starts are
valid; missing applicable prices, duplicate starts or conflicting current facts
are safe offer errors. A genuine commercial change between control reads still
refuses the offer. Only the chosen current price supplies discount evidence:
explicit `discounts: []` means none, missing/null is incomplete and nonempty
discounts remain unsupported by the MVP. Another price/period cannot supply it.
The pinned API base supplies system IANA `tzdata`; the build checks
`Europe/Moscow` for both development and production targets. The server's local
timezone does not set the billing calendar.

Currency interpretation is a typed mapping from the configured
`LBX_CURRENCY_ID` to `LBX_CURRENCY=RUB`, major units with scale 2. ID 1 is the
supplied test setup, not an algorithm constant; configure another proven external
ID for the same supported RUB contract when needed. Mismatching IDs/unsupported
interpretations
are unsupported offer errors. These settings do not attest credit, tax,
renewal/cancellation or historical-subscription policy; no unknown fact is filled
with false/zero. Purchase point-read validation obtains its own applicable facts.
Currency readiness does not block a raw Server API GET or the
account-Widget readiness check. Real Step 3 purchase proof and the owner payment
result are recorded in the current acceptance ledger; they do not certify
unsupported policy variants.

The transport accepts the retained E04/E05 representations: exact JSON numeric
`1.0` quantity bounds, a provider-local midnight `price_start_date`, and history
`start_date_year`/`start_date_month`. A schedule month means its first calendar
day in the confirmed Moscow price calendar, never a paid UTC interval.
No subscription/tariff UTC duration is derived from these calendar dates.
Fractional quantities parse exactly but are unsupported by the integer-service
profile; missing facts remain incomplete. Invalid/nonfinite numbers and
invalid/conflicting dates fail safely.

Configure the existing Kernel URL/token. Optional `KERNEL_MOCK_ENABLED=1` with
explicit `KERNEL_MOCK_TOKEN` and matching `KERNEL_SERVICE_TOKEN` starts only the
development technical mock. Its default endpoint is `http://kernel-mock:8091`.
It needs no publisher UID, approval files, billing fixtures or billing mounts.
Kernel provenance stays `SIMULATED`; LBX provenance independently remains
`CONFIGURED_SOURCE`. Neither label means production approval. Real Kernel
producer conformance remains ANY-711; the mock is never permitted in production.
Ordinary configured HTTPS connections are accepted in production and carry
`CONFIGURED_SOURCE`, without claiming conformance or launch approval. The
existing `KERNEL_MOCK_ENABLED` opt-in explicitly selects mock provenance; changing
its URL does not remove that label or make the mock legal in production.

Normal local/agent/production Compose configurations pass the connection to the
API. The harness keeps private values in protected `.harness/runtime.env`,
outside runtime.json, doctor output and public web settings. Do not print
`docker compose config`, the protected env file or source credentials in evidence.

## Human setup and privileged CLI

Run only against the intended local environment, never a production URL for
development migrations. Apply the current head `20261029_0003` through `npm run migrate:api`
with the intended host database configuration, then `npm run repo:up -- --reuse`.
The harness's normal migrate service also applies the chain during startup.
On hosts without `python` on PATH, prefix npm commands with
`PATH="$PWD/.venv/bin:$PATH"`.

### Consolidated ANY-709 migration

The branch contains one migration, `20261029_0003`, after main's unchanged
`20261001_0002`. It retains all operations from the former branch-local
`20261026_0003` / `0004` / `0005` / `20261027_0006` chain and the later
`20261028_0004` active financial recovery window, including indexes, constraints,
triggers, operation-account backfill and purchase holds. Upgrade order is the
exact old `0003` then `0004` order; downgrade reverses `0004` before `0003`.
The final schema, legal seed, historical consent and accepted-purchase meaning
are unchanged.

- Fresh databases and databases at `20261001_0002` use the normal migration
  command below. Conflicting old identities or held scopes abort the transaction;
  the migration never chooses, deletes or relabels those records.
- A database already at the final `20261029_0003`, with the nullable active
  recovery column and the complete expected schema, runs normal `upgrade head`
  as a no-op.
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
  Preserve/fingerprint all application rows before and after, then verify normal
  `upgrade head` is a no-op. Never replay the consolidated DDL on that database.
- A fully upgraded database at retired `20261027_0006` has the pre-window schema, but
  its old label is not in the new graph. Verify that its columns, constraints,
  indexes, functions and triggers match the pre-window `0003` in checkout
  `afb46c5`, retain a protected backup, then change only its `alembic_version` label to
  `20261027_0003` in a guarded transaction. Preserve all application rows and
  run old `upgrade head` in `afb46c5` to reach `20261028_0004`. Then perform the
  final verified label transition above. Never rerun the consolidated DDL over
  that schema. The owner explicitly authorized the earlier local `0006 -> 0003`
  transition on 2026-10-27.
- A database still at retired `20261026_0003`, `0004` or `0005` must first run
  the original chain to `20261027_0006` using the pre-consolidation checkout
  (`db63966`) and the same protected deployment/database configuration. Then
  follow the `0006` route above, including the old upgrade to `0004`, before the
  final label transition and switch to this checkout. Do not stamp over unapplied operations.
  This is an operator action, not an automatic compatibility rewrite.

The earlier local development transition completed: `0006 -> 0003`, exact schema
comparison PASS, all rows in 27 application tables preserved, and normal
`upgrade head` PASS afterward. The protected pre-transition backup is
`.harness/backups/any709-before-0003-20261027T065436Z.dump` (0600, ignored).
This was a revision-label update of an already-applied schema, not a downgrade
or repeat application of the consolidated migration.
It does not assert application of the later active-window column or the final
2026-10-29 consolidation. The local application DB was unavailable during that
consolidation, and no application database was started or modified.

The following command changes the configured application database and is for the
operator's intended environment only. Retired labels require the transition
above before this command can resolve them:

```bash
PATH="$PWD/.venv/bin:$PATH" npm run migrate:api
```

Focused automated migration/regression command (disposable `_tests` database;
the existing test PostgreSQL server must already be available):

```bash
PATH="$PWD/.venv/bin:$PATH" PYTEST_ADDOPTS='-k "test_alembic_postgres or test_any709_migration_postgres or test_any709_recovery_migration_postgres or test_any709_step1_postgres or test_any709_step2_postgres or test_any709_step3_postgres"' npm run test:api:postgres
```

### CLI execution and product linking

The CLI records the actual OS effective UID as `os-euid:<uid>` in command audit
and immutable publication history. There is no separate UID allowlist or actor
override. Local access relies on existing environment, secret, file and DB
permissions; unavailable or invalid OS identity refuses the command.
All operator processes must use the same local lock inode under one trusted
directory, with the same execution UID and private permissions. Harness
containers bind `.harness/operator` at `/run/payments-portal`; the default lock
is `/run/payments-portal/operator.lock`. A host CLI must use the corresponding
absolute host path and the same UID. Do not alternate root-created lock files
and an unprivileged host user. Production mounts one lock volume, initialized
from the image's app-owned private directory. Use the app UID or deliberately
provision the lock for the chosen operator identity. The lock protects concurrent
execution; PostgreSQL locking and expected-revision/CAS protect publication.
Query records the OS principal but needs no lock, source requests or source credentials.

In an already configured host environment, use the single normal CLI:

```bash
PYTHONPATH=apps/api .venv/bin/python -m app.cli.commercial_mappings dry-run \
  --product-id proposal_ai --tariff-id 32 --tariff-service-id 1 --period-id 1
PYTHONPATH=apps/api .venv/bin/python -m app.cli.commercial_mappings publish \
  --product-id proposal_ai --tariff-id 32 --tariff-service-id 1 --period-id 1 \
  --expected-previous-revision 0
PYTHONPATH=apps/api .venv/bin/python -m app.cli.commercial_mappings query \
  --product-id proposal_ai
```

IDs above are supplied manual test inputs, never business-code defaults. The
period is **period ID 1**, not association ID 82 or price-row ID 288. Optional
`--quantity` defaults to one commercial service, validated against source bounds;
it is not a Kernel allowance. Non-unit connection charges require proven
quantity semantics and are currently refused rather than inferred.

For the current worktree container, use the harness's exact project/files/env:

```bash
portal_operator() {
  .venv/bin/python - "$@" <<'PY'
import os
import sys
from scripts import repo
command = [*repo.compose_command(repo.load_runtime()), "exec", "-T",
           "--user", f"{os.geteuid()}:{os.getegid()}",
           "-e", "PYTHONPATH=apps/api", "api", "python", "-m",
           "app.cli.commercial_mappings", *sys.argv[1:]]
os.execvpe(command[0], command, os.environ)
PY
}
portal_operator dry-run --product-id proposal_ai --tariff-id 32 --tariff-service-id 1 --period-id 1
portal_operator publish --product-id proposal_ai --tariff-id 32 --tariff-service-id 1 --period-id 1 \
  --expected-previous-revision 0
portal_operator query --product-id proposal_ai
```

`revision_number` is the current **product** head sequence, including retargets
to a different offer. No head is 0. Supply the query result as the expected
revision when replacing a link. Equal link identities are no-ops even after an
ordinary price change; current reads are still required for publication.
`offer_revision_number` is the separate retained per-offer history sequence.
Read exact history with `query --offer-id <returned-billing-offer-id> --revision
<offer_revision_number>`. History remains readable offline; an ambiguous old
scope is refused. A conflicting proven old connection yields
`mapping_existing_connection_scope_conflict`: inspect/migrate that binding
explicitly; never relabel it or ask customers to register again.

The fresh connection ID derives from canonical provider origin plus deployment
tenant/region, never login or password. For an existing credential-derived v1
scope, keep the previous username configured for one authorized identical
`publish` after applying the current head `20261029_0003`. The prior hash must match this exact
origin/username. The command records the proven origin on the mutable head,
returns the same immutable link (`inserted=false`), and preserves its scope/FKs.
Subsequent username/password rotation and new links use that proven storage
scope. Query is read-only; it does not create this compatibility proof. If the
old username was already lost/rotated and no origin was retained, the old hash
alone cannot prove provider membership: expect an explicit connection conflict
and reconcile its provenance separately. Never reset the DB or guess an alias.
Changing the provider origin cannot adopt the former provider's external IDs.

## Observable result and read-only inspection

`GET /api/catalog/products` lists enabled technical products with one bounded
Kernel read and no LBX fan-out. Detail fetches the selected live price,
composition and period. Unmapped products show no price; unsupported/incomplete
offers are explicit. Outages return no-store errors, not stored prices. No
marketing description, technical quota or subscription state is invented.
UI shows the separate development product-source label and current LBX terms.
New purchases require the explicit Step 4 review/consent flow below; catalog reads alone never create a purchase.

Human read-only SQL (use the configured environment's SQL console):

```sql
SELECT h.product_id, h.revision_number AS product_revision,
       h.provider_origin,
       r.mapping_revision_id, r.billing_offer_id, r.revision_number AS offer_revision,
       r.mapping_schema_version, r.mapping_document->'selection' AS selected_ids,
       r.mapping_document->>'kernel_provenance' AS kernel_provenance,
       r.mapping_document->>'lbx_evidence_mode' AS lbx_provenance,
       r.published_at, r.published_by_principal
FROM commercial_product_heads h
JOIN commercial_mapping_revisions r
  ON (r.mapping_revision_id, r.external_billing_account_id) =
     (h.mapping_revision_id, h.external_billing_account_id)
WHERE h.product_id = 'proposal_ai';
SELECT product_id, count(*) FROM commercial_product_heads
GROUP BY external_billing_account_id, product_id HAVING count(*) > 1;
SELECT h.external_billing_account_id, r.billing_offer_id,
       array_agg(h.product_id ORDER BY h.product_id) AS current_products
FROM commercial_product_heads h
JOIN commercial_mapping_revisions r
  ON (r.mapping_revision_id, r.external_billing_account_id) =
     (h.mapping_revision_id, h.external_billing_account_id)
GROUP BY h.external_billing_account_id, r.billing_offer_id HAVING count(*) > 1;
SELECT mapping_revision_id, billing_offer_id, revision_number,
       mapping_schema_version, published_at
FROM commercial_mapping_revisions ORDER BY published_at, revision_number;
SELECT 'customers' AS kind, count(*) FROM external_billing_customers
UNION ALL SELECT 'purchases', count(*) FROM purchase_intents
UNION ALL SELECT 'subscriptions', count(*) FROM external_subscriptions;
```

Expect one selected product head and no duplicates. Repeat the same publish:
`inserted=false`, same immutable pin. Retarget with the current product revision:
one changed head and a retained old revision. Baseline migration creates no
heads, modifies no history and promotes no synthetic evidence. Linking and
catalog browsing leave customer/purchase/subscription counts unchanged.

Both current-head duplicate queries must return no rows. A selected offer can
have only one current product owner. Publication checks this under its offer
lock, including identical retries, and returns `mapping_offer_product_conflict`
without appending a revision on conflict. After a product is retargeted, its old
offer can be linked to another product; all historical pins remain readable.

Retained conflicting heads are not deleted or reassigned automatically. New
catalog/purchase admission fails closed, including the final acceptance recheck.
Operator `query --product-id` remains available for inspecting each pointer and
its CAS revision. Resolve a conflict with an explicitly selected normal `publish`
retarget to another validated offer. Do not reset accepted purchases, customer
bindings, consent or operation rows. Original purchase replay and Manage use
their immutable pins independently of current offer ownership.

## Step 1 regression commands (human rerun)

```bash
export PATH="$PWD/.venv/bin:$PATH"
PYTEST_ADDOPTS='-k "test_any709_step1_sources or test_lbx_client or test_lbx_selected_offer or test_source_composition or test_kernel_mock_dev"' npm run test:api:fast
python scripts/repo.py test-db up
PYTEST_ADDOPTS='-k "test_any709_step1_postgres or test_alembic_postgres or test_catalog_api or test_commercial_mapping_postgres"' npm run test:api:postgres
# Stop only if the server was started solely for these tests:
python scripts/repo.py test-db stop
# With the human-configured isolated browser harness:
npm --workspace @anytoolai/web run test:components -- CatalogPreview
npm run test:e2e -- apps/web/e2e/portal-ru.spec.ts apps/web/e2e/catalog-preview.spec.ts
```

These are human rerun commands; historical Step 1-3 evidence is recorded in the plan. Step 4 authoring executes only changed-file lint and diff whitespace checks.
Focused tests must select actual tests (zero selected/skipped is not PASS).
Use the fake-provider repricing regression; no live tariff mutation is needed.
Inspect desktop/mobile layout and accessibility during human browser validation.


## Human account-Widget checkpoint (Step 2)

Configure the existing Server connection plus `LBX_WIDGET_SIGNING_SECRET` in the
protected environment. There is no browser configuration secret, profile file,
account ID, user allowlist, seller/calendar, Kernel or product-link prerequisite
for this checkpoint. In the intended local working environment only:

```bash
export PATH="$PWD/.venv/bin:$PATH"
npm run migrate:api
npm run repo:up -- --reuse
# Ordinary Compose alternative (use the same intended environment as Step 1):
docker compose run --rm migrate
docker compose up -d --build api
```

Use one environment path, not both. The original Step 2 authoring did not execute
these commands. The owner-authorized 2026-10-26 QA correction subsequently ran
local services/tests and real test-043 customer verification. The implemented
result and retained acceptance limits are recorded in the
[completed plan](../exec-plans/completed/ANY-709-implementation-plan.md#step-2-customer-and-account-widget).
That correction required no application migration.
Normal harness startup uses its migrate service; no manual `alembic stamp` or DB
reset is needed. Existing users retain nullable independent FIO fields; new
registration optionally saves trimmed first name, surname and patronymic. No
LBX request is made on registration, login, catalog browsing or ordinary GET.

1. Sign in as the existing verified user. Open account, then explicitly click
   **Open billing** (localized). The POST has an empty body; it accepts no LBX
   identity, seller, price or browser permission flags. Inspect no-store and the
   request ID without copying the response credential into evidence.
2. Confirm the actual configured `/lbxwidget.js` and official provider iframe,
   and the real empty-account state when applicable. Closing/reopening, reloading,
   two tabs and another product's account link must reuse the same customer.
   A missing mapping, failed quote or pending catalog request cannot block this entry.
3. Repeat with new users with absent/partial/full FIO. Inspect LBX Admin display
   when FIO exists; no exact display-name formula is promised. Portal sends no
   agreement/subscription CREATE. A provider-created default agreement is not
   adopted as a purchase agreement. This checkpoint proves customer viewing only.
4. Verify logout/cross-tab user change/close removes the SDK host. No JWT may
   appear in localStorage/sessionStorage/URLs/journal. SDK/configuration/server-auth/
   Client-readiness/identity/UNKNOWN failures show localized safe text and request ID.
   Never adopt another customer or repair identity drift by automatic PATCH.

A successful users POST now commits its candidate ID to the existing operation
recovery hint before the detailed GET. The hint is not a trusted customer binding;
reopening uses that ID for paired point proof and never repeats CREATE. Server
GET credential/contact fields are discarded by the identity projection. A
short candidate list may omit `outer_id`; its detailed GET still must match.
Every unbound open uses the shared `ensure_customer` operation: original-key
search, email candidate search when needed, point proof, then a fenced CREATE only
if successful discovery found no candidate. Temporary failures use bounded
discover/create/recover with backoff within the existing opening deadline;
failed reads never permit CREATE. Email-uniqueness rejection uses GET recovery
only for the rest of the opening. Permanent errors stop after recovery. Deadline
exhaustion retains the operation for later explicit continuation. Email matches
alone never bind. A known receipt always
uses its saved ID and prevents another CREATE. The owner supplied a successful
Widget rendering screenshot on 2026-10-27; it proves that observed account only.

For the current harness, this helper uses its exact project/files/protected env
without printing secrets and forces a read-only PostgreSQL session:

```bash
portal_sql() {
  .venv/bin/python - "$1" <<'PYSQL'
import os
import sys
from scripts import repo
command = [*repo.compose_command(repo.load_runtime()), "exec", "-T", "postgres",
           "sh", "-c", 'exec env PGOPTIONS="-c default_transaction_read_only=on" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "$1"',
           "portal-sql", sys.argv[1]]
os.execvpe(command[0], command, os.environ)
PYSQL
}
portal_sql 'SELECT customer_id, user_id, provider_customer_id, binding_state FROM external_billing_customers ORDER BY created_at'
```

Pass each read-only query below to `portal_sql`, or use the intended deployment's
SQL console (never a different contour's database):

```sql
SELECT customer_id, external_billing_account_id, user_id, provider_origin,
       provider_customer_id, binding_state
FROM external_billing_customers ORDER BY created_at;
SELECT create_operation_id, customer_id, purchase_intent_id, operation_kind,
       operation_state, send_fence, unknown_since, unknown_recovery_deadline_at,
       bound_external_object_id, resolved_at
FROM external_create_operations ORDER BY created_at;
SELECT work_item_id, scope_reference, work_state, next_attempt_at
FROM billing_work_items WHERE work_kind = 'external_create_recovery';
SELECT review_case_id, reason_code, scope_reference, case_state
FROM manual_review_cases WHERE scope_kind = 'create_operation';
SELECT count(*) FROM purchase_intents;
SELECT count(*) FROM external_subscriptions;
```

After first open: one scoped customer, one permanent customer operation with
NULL purchase ID, one recovery item committed before any POST, no Portal-created
purchase/subscription. Proven binding completes its recovery item and clears its
active-send lease. The owner-approved 2026-10-28 policy permits bounded
same-opening recovery and later explicit opens to claim a retry after fresh
successful empty discovery when the previous attempt has finished or its finite
lease has expired, including old UNKNOWN/manual-review
rows. The same user, opaque key, slot and permanent operation are retained; the
work attempt count/fence and per-attempt recovery deadline advance. An active
lease, saved receipt, ambiguous identity or failed discovery prevents another
POST. There is one CREATE implementation/caller. Temporary failures retry with
backoff and jitter inside the nonrenewable opening budget. Email-uniqueness
rejection switches to GET-only recovery; authorization, identity conflicts and
permanent validation failures stop. A proven match continues to Client readiness;
deadline exhaustion retains the operation and returns a temporary pending error
with request ID, reported once to Sentry. The opening reuses its original email
and opaque key. No infinite loop, direct provider PATCH, user deletion
or diagnostic-CLI mutation is added. Reopening a bound customer uses GETs plus a
fresh JWT. Migration retains historical records and refuses
conflicting unique data rather than deleting/relabeling it. Legacy customer rows
without proven origin/operation require operator review; synthetic rows are never
promoted to live identity. Credential rotation preserves the proven origin scope.

Caller cancellation propagates unchanged, including when protected HTTP cleanup
crosses the work deadline. Only the owning admission `asyncio.timeout` classifies
its expiry. Widget bootstrap and purchase advance translate that owned expiry to
`billing_customer_pending` outside the admission context while customer proof is
incomplete; later Client/payment/financial deadlines keep their original meaning.
Pending HTTP cleanup retains its counted slot and any active customer-send lease.
No cancellation or timeout becomes positive no-send proof or authorizes a replay.

`app.composition.billing.recover_customer` performs provider GET-only recovery
and may persist a paired binding;
`app.domains.billing.customers.escalate_overdue_customers` is callable bounded
escalation. The latter records overdue operations for manual review and retains
all keys; a later explicit account open follows the amended discover/claim flow.
No scheduler is installed in Step 2; later program Step 8 owns background execution.
Elapsed time alone never sends a POST: an explicit authenticated opening, completed
fresh discovery and a successful fenced claim are required.

The SDK host loads once per disposable browsing context and is created only by
the explicit button, including under React development remounts. Its opaque
sandbox CSP contains only the validated configured origin. Browser timeout or
closure does not cancel a possibly sent CREATE. LBX credentials remain potentially
usable for its accepted 72h window after local logout; flags are presentation,
not Client API ACLs. Human validation of real rendering, CSP compatibility,
desktop/mobile accessibility and actual Client readiness is still required.

## Customer diagnosis CLI

When a Portal user cannot open billing, run one read-only operator command:

```bash
.venv/bin/python scripts/repo.py billing-customer diagnose --user-id <PORTAL_USER_UUID>
```

Replace the placeholder with Portal `users.id`, not an email or LBX ID. Run from
this deployment's trusted shell with its normal database and LBX configuration.
The repository wrapper uses the root Python runtime and mapped local PostgreSQL
port; it does not start containers, migrate the database or edit `.env`. Inside
an already configured API container, use
`python -m app.cli.billing_customers diagnose --user-id <PORTAL_USER_UUID>`.
A direct host invocation requires `PYTHONPATH=apps/api`, the intended
`DATABASE_URL` and matching instance/LBX settings. Keep credentials out of CLI
arguments and reports.

The command reads the scoped Portal user, existing immutable customer/create
identity, send fence, receipt candidate and recovery state. It reads saved
allowlisted CREATE response facts, then searches LBX by the original `outer_id`
and original/normalized email using GET requests with `show_passwords: false`.
At most five distinct candidates receive a detailed `GET /users/{id}`. A matching
email is only a search candidate: paired provider ID and unchanged original
`outer_id` are required for identity verification. Multiple candidates,
contradictory receipts or an ID owned by another Portal customer require manual
review. Missing/unverified/conflicting local state prevents provider calls.
PostgreSQL reads use read-only transactions, closed before external HTTP.

JSON includes `diagnosis`, `next_action`, safe state/response facts and candidate
IDs. Email, the opaque outer key, tokens, passwords and arbitrary provider text
are omitted. The tool never changes a binding, operation, review or recovery
item, creates customers, issues Widget JWTs, or authorizes another CREATE.
There are no `--apply`, reset or supplied-customer-ID switches.

Live failures include `lbx_error` and `lbx_response_facts`: HTTP status (null
without a response), JSON LBX code when safely readable, error-field presence,
safe reason/failure category, method/endpoint template, GET retry eligibility
and request/create-operation correlation. Unknown HTTP 500 error envelopes
remain provider refusals (`source_rejected`), distinct from connection failures,
`source_auth_failed`, `source_invalid_response` and `source_rate_limited`.
Saved CREATE response facts remain historical evidence; they do not authorize a
retry or prove that no customer was created. Unresolved CREATE followed by GET
recovery uses the existing public `billing_customer_pending` response; a
pre-CREATE provider refusal uses `billing_source_rejected`. Neither exposes LBX
text. This does not change discovery, send leases/fences or the explicit-open
retry amendment above.

- `binding_verified` (exit 0): the existing binding has fresh paired proof.
  Investigate Client readiness or Widget rendering separately; `widget_checked`
  remains false.
- `not_provisioned` (exit 0): no customer slot exists. Use the normal Portal
  opening flow, which owns creation and all concurrency protections.
- `customer_found_unbound` (exit 2): a matching customer exists. Open billing normally to
  point-verify and restore the existing binding.
- `email_conflict` (exit 2): the latest saved CREATE response reports email
  uniqueness rejection. Resolve the email conflict, then open billing normally for
  fresh discovery and a new attempt if needed. The stored response is historical;
  the diagnostic never sends CREATE to test whether the conflict still exists.
- `create_outcome_unknown`, `email_candidates_unproven`, `identity_conflict`,
  `candidates_ambiguous`, `receipt_invalid` or `connection_conflict` (exit 2):
  preserve identity and investigate the indicated conflict. The diagnostic
  itself never authorizes or performs a retry; normal explicit account opens
  follow the amended discover/claim flow.
- `email_verification_required` (exit 2): verify the existing Portal email first.
- `source_unavailable` (exit 2): check `lbx_error`, connection and credentials,
  then repeat diagnosis. A known historical email conflict can still be reported
  alongside a current connection error.
- Configuration, missing/scoped-out Portal user or database error (exit 1):
  stderr contains a safe `detail.code`.

For new runtime CREATE failures, the normal bootstrap stores only HTTP status,
LBX code, timestamp and an allowlisted reason in the existing recovery work
item's `last_failed_create` field (`customer-create-response:v1`). This does not
change retry authority, fences or deadlines. A successful CREATE ID remains in
the existing validated receipt. The diagnostic also recognizes the structured
historical `curl-customer-comparison:v1` review evidence recorded during this
incident, extracting only safe owner-response fields. It does not parse logs,
private backups or arbitrary review text. Old failures without retained facts
remain unknown; diagnosis never sends a new CREATE to reconstruct a response.
Neither an empty list, HTTP 404/500 nor expiry of the recovery deadline proves
that no customer was created. The owner's account retry policy therefore makes
another explicit, discover-first attempt rather than claiming provider absence.
Saved receipts and identity conflicts still block CREATE. The report is an observation across local/source reads, not a locked
snapshot for a later mutation; rerun it after any concurrent state change.

## Purchase API and financial recovery (Step 3)

Status: IMPLEMENTED; automated checks, original-source purchase proof and the
owner's intended-agreement payment passed for the recorded stand/purchase.
Browser Buy/Continue/Manage is implemented in Step 4. The following is a repeatable human-operated
API checkpoint after review and application migration, using a verified Portal
user and the normal configured link; never assign a research customer ID.

1. `POST /api/purchases/review` with `{"product_id":"<enabled product>"}` and
   the Portal bearer session. Review returns exact decimal strings, quantity,
   period meaning, opaque `revision_id`, `expected_fingerprint`, and required
   legal versions/text hashes. Documents remain drafts. Review makes no provider
   mutation, consent or durable checkout session.
2. `POST /api/purchase-intents` with a stable `Idempotency-Key` header, the same
   product/revision/fingerprint, and `documents` containing each returned
   `document_version_id` and `acceptance_text_hash`. Do not submit provider IDs,
   amounts or flags. The server rereads current source facts, then atomically
   rechecks the link and legal versions and pins acceptance, consent, the local
   customer slot, two permanent financial identities and one user/product hold.
   `terms_changed` requires fresh review. Same key/same selection returns the
   original intent before source I/O; changed meaning conflicts, and another
   key cannot bypass an occupied scope.
3. `POST /api/purchase-intents/<purchase_intent_id>/advance` explicitly ensures
   the shared customer and prepares a dedicated non-offer agreement for the
   accepted seller, then the selected tariff, **period ID** and service quantity.
   Agreement creation uses a Moscow calendar date; the subscription request
   omits activation/start dates, disables manual/demo activation and requests
   balance-gated activation. Original accepted live terms are rechecked before
   each previously unsent financial operation. No DB transaction spans HTTP.
4. Inspect `GET /api/purchase-intents/current?product_id=<product>` and
   `GET /api/purchase-intents/<purchase_intent_id>`. Both use owned local history
   without catalog reads or CREATE. A `linked` result is a prepared subscription,
   with financial status `unverified`, immediately expired paid projection and
   no paid grant, allowance, access primary or Kernel call.
5. `POST /api/billing/widget-bootstrap` with the owned
   `{"purchase_intent_id":"<purchase_intent_id>"}` requires fresh paired customer,
   seller/agreement and original effective-subscription proof. The response has
   `presentation: "payment"`, `disablePayments: false` and the proven intended
   `payment_target.agreement_reference` / `seller_reference` to show next to the
   Widget. All create/edit/stop/autopay/invoice flags stay disabled. The same
   endpoint with `{}` retains account viewing with payments disabled. This is
   one SDK/JWT identity; flags are presentation, not server ACLs or a product-only
   filter. Human acceptance must validate the actual supported agreement payment
   selection; no custom auto-selection/filter or payment API is supplied.

Point proof compares canonical subscription -> dedicated agreement -> customer,
original seller, tariff/period, one fixed non-bulk service, effective price and
quantity/total, supported lifecycle/creation conditions and configured RUB
meaning (including the provider
Cyrillic ruble symbol). It ignores mutable subscription `outer_id`,
current catalog `tariff_price`, historical price-row IDs and association IDs as
subscription authority. Nullable non-applicable bulk fields are preserved;
waiting NULL/1970/3000 calendar values never become paid dates or UTC intervals.
A nonzero accepted connection charge without explicit effective readback remains
pending; it is never assumed to be zero or proven by today's catalog.

A temporary or incomplete agreement/subscription GET does not erase a linked
purchase's proven preparation or original bindings. That Widget opening fails
without a credential; the next explicit open/refresh repeats complete fresh
point verification for the same purchase, without financial CREATE or a separate
advance. Recovery work remains pending until point proof completes; safe failure
facts are retained. A known ownership, seller or material-term mismatch still enters
manual review and cannot be cleared by another matching response alone.

A financial possible-send claim commits its original correlation, request,
fence, `unknown_since + 2h` and one coalesced recovery work item before POST.
A 500/error envelope, malformed success, timeout, crash, lost commit acknowledgement,
zero discovery or elapsed deadline never authorizes another financial POST. An
unresolved operation holds the product scope and resumes through GET-only
recovery; multiple candidates or a known mismatch enter review. At +2h, unresolved
operations escalate to review while retaining the same hold/deadline. A recovered
point match can resolve deadline escalation. Known-conflict reviews require an
audited decision and cannot be cleared by another matching response alone.

A linked unpaid subscription holds its scope indefinitely, including after
browser abandonment. Automatic release here exists only when original terms
changed and all financial operations are still provably unsent under the same
locks as send claims. Customer identity is retained. Other release requires
trustworthy terminal/no-effect evidence and an audited decision; there is no
force-bind/release/grant command or absence inference from an empty list.
Historical Manage uses the accepted revision and effective subscription terms,
without consulting today's price or product head. A purchase failure leaves
independently proven account viewing available; customer uncertainty blocks JWT.

Authorized operators use the existing privileged OS identity boundary. These
commands never print credentials, personal data, raw provider text or bodies:

```bash
.venv/bin/python scripts/repo.py billing-purchase inspect --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid>
.venv/bin/python scripts/repo.py billing-purchase recover --user-id <portal-user-uuid> --purchase-id <purchase-intent-uuid>
```

`inspect` is local/read-only. `recover` performs bounded Server GETs and applies
only fenced point-proven bindings/review state; it never sends customer or
financial CREATE, mints JWT, releases a hold or grants access. Safe stored
HTTP/LBX failure facts explain unresolved CREATE without raw provider text.
The existing `billing-customer diagnose` remains a separate read-only customer
command. CLI invocations are human commands, NOT_RUN by this implementation.

The later Step 8 worker may call `recover_financial()` with an owned local
purchase and `escalate_overdue_financial(factory, now=..., limit=...)` (1..100).
Consume the existing `external_create_recovery` work by operation ID and active
fixed deadline, falling back to the original deadline for predecessor work.
No scheduler/webhook/reconciliation/trust runtime is started in
Step 3. Retain independent future reconciliation capacity and do not reinterpret
preparation observations as verified paid financial facts.

Focused synthetic verification from repository root (executed; rerun commands):

```bash
PATH="$PWD/.venv/bin:$PATH" PYTEST_ADDOPTS='-k any709_step3' npm run test:api:fast
.venv/bin/python scripts/repo.py test-db up
PATH="$PWD/.venv/bin:$PATH" PYTEST_ADDOPTS='-k any709_step3' npm run test:api:postgres
.venv/bin/python scripts/repo.py test-db stop
```

Migration `20261027_0006` was applied to the local development database under
explicit owner authorization on 2026-10-27. Production migration and the explicit
real org/tariff purchase checkpoint through Portal APIs remain owner-operated.
Record sanitized intent/operation/binding evidence, exactly one intended seller
agreement and subscription, correct effective terms, no grant and no duplicate
CREATE on repeated advance. Actual tariff-32 acceptance and actual Widget
payment targeting/payment remain human integration evidence, not synthetic PASS.

## Step 4 browser journey and observation limits

Status: IMPLEMENTED; component/boundary/desktop/mobile synthetic tests and the
recorded live customer/purchase/payment scenario passed. Current independent
review is pending. Initial authoring evidence is retained as history below. The
initial Step 4 consumed Step 3 contracts without DDL; the cabinet follow-up adds
a local owned-inventory GET and regenerated contracts, with no new migration.

Product details load current public offers independently of personal billing.
Guests get an account link; unverified users must verify email first. Verified
users read `GET /api/purchase-intents/current?product_id=...` before displaying
Buy. A failed read is unknown, never an empty purchase. The owner-approved
cabinet follow-up moves all Widget hosts to the cabinet. Account cards are brief
owned-purchase summaries from authenticated `GET /api/purchase-intents` (default
50, maximum 100 per page, UUID keyset cursor). Only held accepted purchases are
listed; released unsuccessful attempts remain in history but leave the cards.
Unfinished accepted purchases remain visible for continuation on product detail.
The cabinet has a full-catalog link and never fetches the public catalog as owned
inventory. Account-only billing remains available if the list/source catalog
fails or the account has no purchase.

Buy first checks the owned current hold, then displays the live review, exact
money/period/quantity/funding and each required canonical RU legal text/version.
All consents start unchecked; documents are explicitly drafts. Confirmation
sends one opaque idempotency key with the reviewed revision/fingerprint/legal
hashes, then performs one bounded advance. No automatic polling loop exists.
A lost confirmation retains its exact request/key in component memory; retry
cannot silently reprice it. Reload discovers the durable held purchase without
storing a purchase key or Widget credential in the browser. A `terms_changed`
refusal requires a new explicit review and consent. Before any new review, the
current hold is checked again, including after an automatic unsent release.

Created purchases show Continue; preparing/uncertain/manual-review purchases
show recovery and their safe purchase reference. Linked purchases show the compact
“Subscription prepared” state, accepted terms and “Manage subscription” link to
`/account?purchase=<id>#billing`. This means prepared, not paid/active. The deep
link performs an owner-scoped local read; it never automatically opens a Widget.
A single owned purchase is visibly selected by default; multiple purchases need
explicit selection (or the product deep link). The cabinet’s open and card-manage
actions both bootstrap that original intent with fresh effective subscription
proof; neither reads today's product head/catalog price as authority. The UI
shows the proven agreement/seller next to the Widget. There is no product-only
filter: the user must select that agreement in the customer-wide Widget.

The common SDK controller destroys any previous account or payment host when
opening another view, closing, changing product/user, or logging out. Late
responses cannot mount an old credential. The data-origin host keeps credentials
out of HTML, URLs, storage and React state. Payment presentation enables only
payments among SDK action flags. Its sandbox permits forms, popups with their
own acquiring context, and user-activated navigation; account viewing retains
its previous stricter sandbox. The configured LBX origin still owns SDK,
connect/frame policy. Actual acquiring compatibility is a human checkpoint.
Provider JWT replay/72-hour `iat` limitations and customer-wide scope remain
accepted residual risks; destroying the local host does not revoke a copied JWT.

Closing or changing the selected purchase destroys the Widget and cancels late
credentials. Reopening explicitly repeats fresh server verification for that
same selected purchase. No status GET on close is presented as an LBX refresh.
The Portal never claims paid/activated, grants access, or mutates
quota. The current purchase DTO exposes no last-observed financial status/time;
the UI therefore uses awaiting-verification text instead of inventing one.
Step 8 must supply future observation/reconciliation feedback.

### Browser deadlines and lost responses

Live catalog listing/detail, review, confirmation, preparation and Widget bootstrap use a finite
130-second browser deadline, covering the server's supported preflight maximum
of 120 seconds plus response/DB overhead. Identity and local purchase/status
GETs retain the ordinary five-second deadline. The browser must not report a
provider outage merely because a valid server operation exceeded five seconds.
Live GET/POST deadlines cover reading both successful and error response bodies; receiving
headers does not end the timer. A timeout never automatically repeats a POST.

An authenticated exact confirmation replay reads its existing accepted intent
without acquiring the user mutation lock. New acceptance still locks and rechecks
the key and product hold before writing. If the bounded user lock times out
(PostgreSQL `55P03`), the caller receives `503 billing_busy` with its request ID;
the transaction closes without accepting a purchase. An explicit retry preserves
the original key and frozen meaning. Other database failures are not classified
as contention, and this temporary refusal does not authorize a financial retry.

On a lost confirmation response, the UI makes one local current-purchase GET.
An accepted intent becomes Continue/Manage; empty/failed inspection retains the
exact frozen confirmation and original key. On a lost advance response, the UI
reads that same intent once locally. A saved `linked` state offers Manage;
otherwise it retains the held purchase and shows recovery. Neither branch
automatically repeats a POST. A local GET never grants payment presentation:
Manage still requires fresh original-purchase proof through bootstrap.

The 2026-10-27 reported incident was a successful 5.555-second preparation
aborted by the former five-second browser timer. Read-only diagnosis confirmed
one linked purchase/subscription and bound financial operations; it did not
repeat creation, alter data or perform provider/payment QA. Rebuilding the web
application is required to deploy the source correction; diagnosis does not
silently rebuild or restart the working application.

## Exact human startup and restart commands

Run from the repository root with the intended environment. These commands were
NOT_RUN during Step 4 authoring. Host commands use root `.venv`, installed npm
workspaces and the normal `.env`/process configuration; no approval JSON is used.

```bash
export PATH="$PWD/.venv/bin:$PATH"
# Host development application database only, after backup/review:
npm run migrate:api
# Normal worktree containers; reloads protected runtime configuration:
npm run repo:up -- --reuse
# Host-process alternative, in separate terminals with the same configuration:
npm run dev:api
npm run dev:web
```

Choose host processes OR containers for application ports. The optional technical
Kernel mock is configured through `KERNEL_MOCK_ENABLED=1` plus matching explicit
mock/service tokens, never a billing test profile. The setup above is for the
local application DB, **not** pytest's disposable `_tests` DB. Step 4 applies no
migration. The current chain ends at `20261029_0003`; earlier owner authorization
applied the previous chain locally and does not authorize production migration
or imply application of this consolidated revision.

For an existing worktree, this helper resolves its exact Compose project,
protected env and optional mock overlay without printing private configuration:

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
# Restart unchanged configuration:
portal_compose restart api web
# Rebuild/recreate the current application after code changes:
portal_compose up -d --build api web
# Container operator CLI (same UID/lock setup as the link section):
portal_compose exec -T --user "$(id -u):$(id -g)" -e PYTHONPATH=apps/api api \
  python -m app.cli.commercial_mappings query --product-id proposal_ai
```

For changed `.env` settings use `npm run repo:up -- --reuse` to refresh the
protected runtime env; a plain restart cannot update container environment.
Host link and full container `portal_operator` publish examples are above.
Use the queried product `revision_number` for CAS, never the offer-history
sequence, price row or period association ID.

Production uses `docker-compose.yml` with `docker-compose.prod.yml`, its own
protected environment, production LBX origin/seller/offers/acquiring and actual
compatible Kernel/service auth. It has no Kernel mock or separate billing code
path. Do not point a populated test DB at production or copy test customer IDs.
The deployment owner reviews backups, migrations and launch gates separately.
Never attach `docker compose config`, `.env`, response credentials or PII to QA.

## Purchase read-only SQL and safe diagnosis

Use the `portal_sql` helper above or a read-only console in the intended contour.
Replace the UUID placeholder with the Portal purchase reference shown in the UI.
These queries select no tokens, personal names/emails, raw requests or recovery
payloads. Avoid publishing provider identifiers outside authorized diagnostics.

```sql
SELECT p.purchase_intent_id, p.product_id, p.state, p.mapping_revision_id,
       p.created_at, p.state_updated_at, (h.purchase_intent_id IS NOT NULL) AS held,
       p.accepted_snapshot_schema_version,
       p.accepted_snapshot->'offer'->'money' AS accepted_money
FROM purchase_intents p
LEFT JOIN billing_purchase_scope_holds h ON h.purchase_intent_id = p.purchase_intent_id
WHERE p.purchase_intent_id = '<portal-purchase-uuid>';
SELECT o.create_operation_id, o.operation_kind, o.operation_state,
       o.send_fence, o.unknown_since, o.unknown_recovery_deadline_at,
       o.bound_external_object_id, w.work_state, w.next_attempt_at,
       COALESCE(w.active_recovery_deadline_at, o.unknown_recovery_deadline_at) AS active_recovery_deadline_at
FROM external_create_operations o
LEFT JOIN billing_work_items w ON w.scope_reference = o.create_operation_id::text
  AND w.work_kind = 'external_create_recovery'
WHERE o.purchase_intent_id = '<portal-purchase-uuid>'
ORDER BY o.operation_kind;
SELECT subscription_id, purchase_intent_id, mapping_revision_id,
       external_agreement_id, external_subscription_id, lifecycle_status,
       financial_access_status, last_authoritative_read_at, projection_valid_until
FROM external_subscriptions WHERE purchase_intent_id = '<portal-purchase-uuid>';
SELECT b.observed_at, b.completeness_classification, b.result_classification,
       b.evidence_document->>'paid_verified' AS paid_verified
FROM billing_state_observations b
JOIN external_subscriptions s ON s.subscription_id = b.subscription_id
WHERE s.purchase_intent_id = '<portal-purchase-uuid>' ORDER BY b.observed_at DESC;
SELECT user_id, product_id, count(*) FROM billing_purchase_scope_holds
GROUP BY user_id, product_id HAVING count(*) > 1;
```

After linking: one product head, immutable history, no new customer/purchase.
After first explicit billing open: one scoped customer and its permanent
customer operation, no artificial PurchaseIntent. After confirmation/preparation:
one immutable acceptance and legal event, one held user/product scope, permanent
agreement/subscription operations and one dedicated agreement/subscription.
Unpaid reload/two tabs retain that scope; close does not release it.

Common failures: verify Portal email for auth errors; fix connection/signing/
seller/Client readiness for configuration errors; use request IDs for normalized
provider rejection, auth failure, invalid response or outage. Never copy raw
`response.error` into UI/support evidence. Use fresh review for `terms_changed`.
For financial UNKNOWN/manual review, retain the purchase and inspect/recover
with the CLI above. Empty discovery or elapsed +2h is not permission to repeat
CREATE. Catalog errors cannot rebind Manage. Widget script/CSP/network failure
allows reopening the same presentation without creating another purchase.
The host waits for the existing SDK `lbx-widget`/`READY` signal from the exact
nested window at the configured LBX origin; returning from `render()` does not
cancel the 20-second loading deadline. A timeout removes the stale host and
shows a localized Portal error with the bootstrap request ID. Console event
`billing_widget_load_failed` and optional sanitized Sentry retain only service,
operation, stage, closed reason and that request ID. Correlate it with the
server bootstrap logs. No vendor error text, URL, token or user fields are
reported. A ready Widget has no refresh timer that could interrupt checkout.
An empty Widget, permanently disabled payments, or another agreement does not
satisfy the payment checkpoint; fix the configured provider payment method.

Forward migrations preserve history and may refuse ambiguous old bindings.
Back up the intended DB before applying the existing chain. Do not downgrade
constraints or delete holds/operations/history to roll back a UI failure. Stop
new purchases and deploy a compatible fix; operator resolution needs separately
proven facts and audit. There is no force-bind, force-release or paid-grant CLI.

## Step 4 human verification commands

These are repeatable checks, not instructions to repeat an acquiring payment.
Recorded results live in the current acceptance ledger. They use synthetic transport
fixtures only. Start/configure the intended isolated browser harness manually;
Playwright's desktop and mobile projects capture screenshots and run axe.

```bash
npm --workspace @anytoolai/web run test:components -- any709-step4 any709-billing-timeouts
npm run test:e2e -- any709-purchase.spec.ts
# Changed existing regressions:
npm --workspace @anytoolai/web run test:components -- any709-step2 AccountClient SessionRaces CatalogPreview CatalogTransport
# Broader human checks, after focused tests:
npm run test:boundaries:web
npm run docs:check
npm run generate:check
npm run typecheck:web
npm run build:web
```

No backend behavior or wire shape changed in Step 4, so no new backend test
selector is supplied. If rechecking inherited financial safety, use the Step 3
fast/PostgreSQL commands above; start only its isolated test DB. Do not run API
tests against the application DB. One owner-selected `npm run check` can replace
overlapping broad checks; do not claim any of these ran during authoring.

## Final human acceptance ledger

1. Configure ordinary local/test settings, migrate the intended application DB,
   start the normal application plus optional technical Kernel mock and publish
   the intended real link. Test inputs are seller 21, `proposal_ai`, tariff 32,
   service 1 and period 1; use actual source prices, not a hardcoded 100 RUB.
2. Existing verified user and new users with absent/partial/full FIO open the
   real customer SDK. Login/ordinary GET alone creates no billing object. Repeat
   opens reuse the same customer. Account viewing works without a subscription.
3. Review real terms, confirm all draft legal consents and Buy. Record safe
   references for one accepted intent and one dedicated intended-seller
   agreement/subscription. Verify effective terms and waiting NULL/sentinel
   dates without inferring a paid month or paid access.
4. Inspect the actual Widget payment action for that agreement/seller. Select
   the intended agreement, verify a configured payment method, and exercise its
   form/popup/return behavior on desktop/mobile. Customer-only viewing or a mock
   SDK cannot pass this checkpoint. Missing acquiring configuration is an explicit
   limitation, not permission to fabricate payment success.
5. Close unpaid, reload and open two tabs. Continue/Manage retain the original
   intent/customer/agreement/subscription. Retarget/repricing regression uses
   synthetic fixtures; do not mutate live tariffs or induce live lost writes.
6. HUMAN alone performs any agreed safe test payment. Record provider facts
   separately; Portal still says awaiting verification and does not grant Kernel
   access. Exercise SDK/unavailable recovery, logout and late-response rejection.
7. Review sanitized request correlation, storage/URL/logs and screenshots/axe.
   Never publish JWT, provider raw text, secrets or PII.

Historical Step 4 authoring checkpoint (superseded by the current acceptance ledger): implementation and diff review were complete;
changed-file ESLint/diff results are recorded in the implementation plan.
Component/browser/boundary/docs/typecheck/build checks, screenshots and axe are
NOT_RUN. Prior Step 1-3 synthetic/local migration evidence remains historical.
Owner-observed customer Widget rendering is not purchase/payment acceptance.
`PURCHASE_PREPARATION_PASS`, `MAPPED_PURCHASE_WIDGET_PASS` and `PAYMENT_PASS` all
were NOT_RUN at that checkpoint. The later owner result records actual purchase
and payment PASS for the intended stand/purchase. Steps 8–10/launch remain deferred.

## Compact program Step 8 integration seam

ANY-715 builds on this code, not PR #143 helper names. Existing models:
`ExternalBillingCustomer`, `PurchaseIntent`, `BillingPurchaseScopeHold`,
`ExternalCreateOperation`, `ExternalSubscription`, `BillingStateObservation`,
`BillingWorkItem` and `ManualReviewCase`. Persisted states are the enums exported
from `app.models`, including `PurchaseIntentState` and
`ExternalCreateOperationState` (`pending`, `possible_send`, `unknown`, `bound`,
`manual_review`).

Customer uniqueness is `(external_billing_account_id, user_id)` and a non-null
provider ID is unique within that account. The purchase hold's primary key is
`(user_id, product_id)` with scoped purchase FK. Financial identity is permanent
per `(purchase_intent_id, operation_kind)`; proven external object IDs are unique
per account/kind. Subscription provider ID and dedicated agreement ID each have
account-scoped uniqueness. Original accepted price/fingerprint/link/legal
versions stay in `accepted_snapshot` plus append-only legal evidence.

Admission locks the user, current product-head publication scope/head, required
legal versions, then customer slot; it rechecks idempotency/hold/link/legal facts
after source I/O. Financial result/claim order is user -> owned purchase/hold ->
operations ordered by kind -> bound subscription as needed. Never perform HTTP
inside those transactions or share a SQLAlchemy Session across threads.

`claim_financial()` atomically commits `possible_send`, original request/fence,
`unknown_since + 2h` and a coalesced `external_create_recovery` work item keyed by
operation UUID before POST. `record_receipt()` saves an untrusted candidate;
`bind_financial()` applies point proof only against the same fence. UNKNOWN can
be recovered to bound or escalated to manual review; deadline expiry/empty GET
never replays CREATE or releases the scope. Customer attempts retain their
separately approved discover-before-create/finite-active-lease policy.

`app.composition.purchases.recover_financial()` is the GET-only provider recovery
entrypoint, with no customer CREATE, JWT or scope release;
`app.domains.purchases.financial.escalate_overdue_financial(factory, now=..., limit=...)`
handles 1..100 due purchases. The CLI `inspect` is local/read-only; `recover`
reads LBX and persists fenced results. It is not a strictly read-only SQL action.
The point-read set includes paired customer identity, dedicated agreement/seller,
subscription plus effective services and period evidence. Mismatch, incomplete
inventory, changed accepted terms and financial UNKNOWN remain distinct safe
reasons; centralized LBX decoding supplies redacted status/code diagnostics.

`prepared-subscription:v1` observations have `preparation_only` completeness,
`not_paid_verified` result, calendar evidence and `paid_verified=false`.
`financial_access_status=unverified` and `projection_valid_until` is not extended.
Waiting/sentinel dates never establish paid UTC intervals. Local status GET and
Widget close never create observations. No paid trust/grant/allowance or access
primary is derived here. Source preflight and billing/recovery budgets remain
separate in `SourceResources`; later workers must preserve isolated normal/
urgent capacity instead of reusing all admission capacity.

There is **no running worker, webhook receiver, reconciliation loop, paid
AccessSnapshot, AccessInvalidation or Kernel usage/quota implementation** here.
Step 8 owns those billing observations/recovery loops; Steps 9–10 own paid-access
and Kernel integration. ANY-709 supplies no fake activation to bridge them.

## Owner-authorized automated test follow-up, 2026-10-27

The owner requested tests only, without QA. Focused component regressions passed
205/205 (including 23 new Step 4 tests); boundary/tooling passed 38/38; synthetic
Playwright passed 8/8 across desktop/mobile, with no skips. The new component
file passed again after removing unsupported test-selector `exact` options.
No production code, billing object, schema or generated API contract changed.

The default browser URL served an old image, so it was not used for acceptance.
The final suite used the ignored test-owned config
`.harness/any709-step4.playwright.config.ts`, a temporary local Next dev server
on port 3107 and intercepted API/SDK traffic. Final totals and limits are in the
[completed plan](../exec-plans/completed/ANY-709-implementation-plan.md#validation-evidence);
the full pre-compaction execution record remains in Git at `2961577`.
At that historical checkpoint manual QA, actual intended-agreement/acquiring
behavior and payment were NOT_RUN. No LBX call/payment, DB migration, container
startup or build was run in that checkpoint; the current ledger records later checks.

The later [timeout-incident correction](../exec-plans/completed/ANY-709-implementation-plan.md#buy-timeout-correction)
passed 227 component tests, 38 boundary/tooling tests and 10 synthetic browser
tests, with no skips. The browser harness used webpack polling after the host
file-watch limit prevented Turbopack startup; no global setting was changed.
At that correction's checkpoint the working application was not rebuilt/restarted
and actual provider/payment QA was unperformed. Later deployment and owner
payment evidence supersede that limitation.

## Final review corrections and human acceptance

Financial `proven_not_sent` is positive evidence from the completed typed
`LbxCreateNotSent` path, with no HTTP task still running. Only this state permits
a later explicit advance to claim the same operation with a fresh fence. It
retains the original request (including agreement date), key, unknown timestamps,
historical +2h deadline and coalesced work item. The newly fenced send records its
own nonrenewable +2h window in `billing_work_items.active_recovery_deadline_at`,
independent of `next_attempt_at` scheduling. Inline recovery and overdue scans use
that active window; GETs, empty discovery and scheduling changes never extend it.
Existing work with a NULL active window uses the immutable original deadline.
There is no retry within that advance.
A process crash or lost claim acknowledgement before persisting this evidence
remains possible-send/UNKNOWN and GET-only. Empty GET, deadline expiry, HTTP 500,
read/write timeout and cancellation never create no-send proof. A GET-only
recovery cannot send even a proven-unsent command. Forward migration
`20261029_0003` includes the former `20261028_0004` nullable active-window
column; it preserves all old rows/evidence and the original evidence triggers.
Fresh/main databases use normal `upgrade head`; already-applied branch databases
require the verified transition above before deployment. Do not roll back to an
older binary while a resumed financial send is unresolved.

The occupied business scope is `(user_id, product_id)`, not tariff ID. Different
products may use supported selections of the same tariff. Inventory ignores a
nonterminal same-tariff subscription only when its permanent local binding proves
a different product in the same user/customer/account/provider scope, and fresh
point reads prove that purchase's original agreement/seller/terms. Unknown,
foreign or mismatching inventory still requires review; unsupported multi-service
profiles remain rejected. Incomplete inventory (missing lifecycle state or too
many candidates for bounded proof) instead retains the same unsent operation and
purchase hold in a retryable pending state. No financial CREATE is permitted
until a later complete read proves inventory safe.

Current accepted-term identity uses `current-terms:v2`: current selected price
ID/start, money, quantity, period and supported policies remain material. The next
scheduled price boundary is observation metadata, excluded from that identity.
Adding a future row cannot invalidate unchanged current terms or strand a purchase
after its agreement is bound. A newly effective price is still a material change.
Continuation recomputes the comparison from stored accepted fields, including
older snapshots; accepted fingerprints, snapshots and legal evidence are never
rewritten.

Human acceptance must use the intended stand, with sanitized IDs/request IDs and
observed results recorded against the tested commit:

1. With a new verified Portal user and an existing LBX-linked user, open account
   billing and purchase `proposal_ai`. Confirm exactly one correct LBX customer.
2. Confirm the current LBX price and accepted terms, dedicated agreement with
   seller 21, and subscription tariff 32/service 1/period 1. These are stand data,
   never application constants.
3. With multiple agreements (including another seller/default), open payment
   Widget, select the displayed intended agreement and verify a usable payment
   method targets it. The customer-wide SDK has no documented agreement ACL or
   automatic selection parameter. Account-only view must still work.
4. Reload, sign out/in and press Continue/Manage; confirm the same purchase,
   agreement and subscription without duplicate CREATEs. Existing automated
   fault tests cover UNKNOWN/no-send/concurrency without real LBX writes.
5. Record `MAPPED_PURCHASE_WIDGET_PASS` only after target and real-method checks.
   Actual payment is human-only; if omitted record `PAYMENT_NOT_RUN`. If performed,
   confirm the intended agreement receives it. Portal must still grant no paid
   access: authoritative access/enforcement belongs to later program steps.

Real payment was performed by the owner and verified through the supplied
provider evidence; the agent did not execute acquiring payment. Analyzer decisions and the
line-scoped false-positive exception are documented in [Security](../SECURITY.md#any-709-analyzer-adjudication-pr-150).

## Cabinet follow-up acceptance, 2026-10-27

The owner approved a single cabinet Widget and compact owned-purchase cards.
The following repeatable checklist describes the cabinet acceptance. Recorded
results and outstanding independent review are in the current acceptance ledger;
the owner does not need to repeat payment to validate readiness or refresh.

1. Open `/ru/products/proposal_ai` as the existing test user. Confirm that the
   prepared state is compact and that no Widget appears on product detail.
2. Follow “Manage subscription”. Confirm the URL carries the original purchase
   ID and the cabinet visibly selects that product. No payment request runs until
   an explicit open. Confirm the proven agreement and seller after opening.
3. Close and reopen with the main button, then use the owned card’s management
   action. Both must show the same payment-capable Widget and agreement; only one
   Widget may be mounted. Changing selection must close the previous one.
4. Confirm the cabinet contains only this user’s accepted purchases, including
   an unfinished purchase if one exists; no other catalog products. Open a detail
   card and the “All products” link. Verify a fresh empty user sees no owned cards
   but can explicitly view their billing account without a purchase.
5. With multiple purchases, verify each selected purchase’s agreement/seller.
   The LBX Widget is customer-wide: manually select the displayed agreement in it.
   `demo_*` or other LBX agreements are not removed by this UX change.
6. Verify the actual acquiring/top-up path in the agreed test environment and
   record its result separately. The prior manual LBX-admin credit proves
   activation, not Widget acquiring. `MAPPED_PURCHASE_WIDGET_PASS` is only an
   evidence-ledger label in this runbook/QA result; it is not a setting or env var.
   Do not declare payment PASS from a Portal prepared state.
7. Check desktop/mobile layout and logout. Legal pages and consent remain draft;
   the warning is intentional pending legal approval. Paid access/usage remain
   deferred and are not inferred from an active billing subscription.

### Owner payment result and refreshing the Widget

On 2026-10-27, the owner completed a 100 RUB YooKassa top-up from the Widget on
`50d833c`. Supplied LBX-admin and Widget-history screenshots show the credit on
the intended `portal-8634d1993dea4260902b6aa003b5fff4` agreement, client 29,
seller 21, and the resulting 100 RUB balance. This records
`MAPPED_PURCHASE_WIDGET_PASS` for this stand/purchase; the payment was performed
by the owner. It does not certify production launch or grant paid access.

After completing payment, use "Refresh billing" above the open Widget if its
balance/history or billing view has not updated. The same selected purchase is
reverified on the server and a fresh Widget replaces the old one. If verification
fails, resolve the displayed error before reopening. The customer-wide Widget
may default to another agreement after refresh; select the displayed intended
agreement again. No new subscription or payment is created by refreshing.

The inspected LBX SDK 0.0.1 exposes no payment-completed callback to the Portal.
Embedded acquiring return and its success UI are vendor-owned. Automatic refresh
at the exact payment-completion point requires a supported LBX notification;
the Portal does not infer payment/access from a browser event or inspect a
third-party checkout's DOM.
