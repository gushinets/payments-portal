# LBX connection, product links and account Widget (ANY-709 Steps 1-3)

Status: IMPLEMENTED_AWAITING_HUMAN_VALIDATION. Step 2 adds explicit account-only
customer/Widget bootstrap. Step 3 adds accepted-purchase APIs and verified payment
presentation. Focused synthetic tests have passed and migration `20261027_0006`
was applied to the local development database under explicit owner authorization.
Real LBX purchase/payment QA is NOT_RUN. Step 4 browser purchase UI is pending.

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
account-Widget readiness check. Real Step 3 provider acceptance remains pending.

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
development migrations. Apply the current head `20261026_0005` through `npm run migrate:api`
with the intended host database configuration, then `npm run repo:up -- --reuse`.
The harness's normal migrate service also applies the chain during startup.
On hosts without `python` on PATH, prefix npm commands with
`PATH="$PWD/.venv/bin:$PATH"`.

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
`publish` after applying `20261026_0004`. The prior hash must match this exact
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
Buy remains unavailable in this step.

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

## Human verification (NOT_RUN by Codex)

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

The human owns all execution, migrations, application startup and live 043 reads.
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
local services/tests and real test-043 customer verification; see the
[QA handoff](../exec-plans/active/ANY-709-step-2-handoff.md#manual-qa-correction-2026-10-26-base-181b8d0).
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
search, email candidate search when needed, point proof, then one CREATE only if
successful discovery found no candidate. CREATE failure triggers GET recovery
before returning an error. Email matches alone never bind. A known receipt always
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
active-send lease. The owner-approved 2026-10-27 policy permits another explicit
open to claim a retry after fresh empty discovery when the previous attempt has
finished or its finite lease has expired, including old UNKNOWN/manual-review
rows. The same user, opaque key, slot and permanent operation are retained; the
work attempt count/fence and per-attempt recovery deadline advance. An active
lease, saved receipt, ambiguous identity or failed discovery prevents another
POST. There is one CREATE implementation/caller and at most one POST per opening.
On rejection (including email uniqueness), recovery searches again; a proven match
continues to Client readiness, otherwise a safe error with request ID is returned
and reported once to Sentry. No retry loop, direct provider PATCH, user deletion
or diagnostic-CLI mutation is added. Reopening a bound customer uses GETs plus a
fresh JWT. Migration retains historical records and refuses
conflicting unique data rather than deleting/relabeling it. Legacy customer rows
without proven origin/operation require operator review; synthetic rows are never
promoted to live identity. Credential rotation preserves the proven origin scope.

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

Status: IMPLEMENTED; focused synthetic tests and the local development migration
have passed. Real purchase/payment QA is NOT_RUN. The existing customer Widget observation proves only account
viewing. Browser Buy/Continue/Manage is Step 4. The following is a human-operated
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
Consume the existing `external_create_recovery` work by operation ID and original
fixed deadline. No scheduler/webhook/reconciliation/trust runtime is started in
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
