# LBX connection and product links (ANY-709 Step 1)

Status: IMPLEMENTED_AWAITING_HUMAN_VALIDATION. No runtime/test/migration PASS is
claimed. Customer creation, Widget and purchases remain later ANY-709 steps.

## Connection and deployment

Set private values in the configured environment or the untracked `.env`:
`LBX_BASE_URL` (HTTP(S) origin only), `LBX_SERVER_USERNAME`,
`LBX_SERVER_PASSWORD`, `LBX_WIDGET_SIGNING_SECRET`, and
`LBX_SELLER_ORGANIZATION_ID`. Use production HTTPS. Server API requests append
`/api/rest/v1` exactly once; future Client API/SDK paths are
`/api/rest/v1/client` and `/lbxwidget.js` on the same validated origin. Never put
these secrets in browser configuration, CLI arguments or checked-in files.

All-empty connection settings leave billing unavailable. Partial/invalid
connection settings produce safe billing errors; they do not prevent identity
startup. There is no startup provider call or automatic link publication.
The seller is deployment configuration; catalog reads do not query organizations.
The later purchase agreement must prove the configured seller.

Effective-dated offers also require **`LBX_BILLING_TIMEZONE`**, an actual
operator-supplied IANA billing calendar. The supplied stand-043 evidence does
not establish its timezone: obtain it before the human offer checkpoint. Do
not infer UTC/Moscow from locale or host settings. Missing/invalid calendar is
`selected_offer_billing_timezone_required` / `selected_offer_billing_timezone_invalid`,
an offer error. RU currency interpretation is explicitly `LBX_CURRENCY_ID=1`,
`LBX_CURRENCY=RUB`, major units with two decimal places. Other interpretations
are unsupported offer errors. These settings do not attest credit, tax,
renewal/cancellation or historical-subscription policy; no unknown fact is filled
with false/zero. Later purchase validation must obtain its own applicable facts.

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
development migrations. Apply `20261026_0003` through `npm run migrate:api`
with the intended host database configuration, then `npm run repo:up -- --reuse`.
The harness's normal migrate service also applies the chain during startup.
On hosts without `python` on PATH, prefix npm commands with
`PATH="$PWD/.venv/bin:$PATH"`.

Set `MAPPING_OPERATOR_UIDS` to the explicit numeric execution UID allowlist.
All operator processes must use the same local lock inode under one trusted
directory, with the same execution UID and private permissions. Harness
containers bind `.harness/operator` at `/run/payments-portal`; the default lock
is `/run/payments-portal/operator.lock`. A host CLI must use the corresponding
absolute host path and the same UID. Do not alternate root-created lock files
and an unprivileged host user. Production mounts one lock volume, initialized
from the image's app-owned private directory. Configure the app UID in its
allowlist or deliberately provision the lock for the chosen operator identity.
Query needs authorization but no lock, source requests or source credentials.

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
PYTEST_ADDOPTS='-k any709_step1' npm run test:api:fast
python scripts/repo.py test-db up
PYTEST_ADDOPTS='-k any709_step1' npm run test:api:postgres
python scripts/repo.py test-db stop
# With the human-configured isolated browser harness:
npm --workspace @anytoolai/web run test:components -- CatalogPreview
npm run test:e2e -- apps/web/e2e/catalog-preview.spec.ts
```

The human owns all execution, migrations, application startup and live 043 reads.
Focused tests must select actual tests (zero selected/skipped is not PASS).
Use the fake-provider repricing regression; no live tariff mutation is needed.
Inspect desktop/mobile layout and accessibility during human browser validation.
